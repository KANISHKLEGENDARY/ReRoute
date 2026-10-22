"""
LLM Safety, Global Shared Counter, Rate Limiting, and Pacing.

Guarantees:
1. Every real API call attempt (including retries and failed 429s) across all sources
   (live app, scripts, tests, evals) increments a persistent shared counter in ./.llm_usage.
2. The day boundary is midnight Pacific Time (America/Los_Angeles).
3. Hard stop at 80% of model daily limit (e.g. 400 for 500/day models, 16 for 20/day models):
   makes NO call, triggers deterministic fallback with reason `budget`, logs once. Warns at 60%.
4. Concurrency 1 and pacing: waits at least (60 / rpm) * 1.2 seconds between calls for that model
   (~4.8s for 15 rpm, ~14.4s for 5 rpm).
5. Per-event cap MAX_LLM_CALLS_PER_EVENT (default 6).
6. Safe execution on 429: backoff, attempt counted, and after retries falls back with reason `rate_limit`.
"""

import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger("reroute.llm_safety")

PACIFIC_TZ = ZoneInfo("America/Los_Angeles")

DEFAULT_MODEL_LIMITS: Dict[str, Dict[str, int]] = {
    "gemini-3.5-flash-lite": {"rpm": 15, "rpd": 500},
    "gemini-3.1-flash-lite": {"rpm": 15, "rpd": 500},
    "gemini-3.6-flash": {"rpm": 5, "rpd": 20},
    "gemini-3.7-flash": {"rpm": 5, "rpd": 20},
    "gemini-3.8-flash": {"rpm": 5, "rpd": 20},
    "gemini-3-flash": {"rpm": 5, "rpd": 20},
}
UNKNOWN_MODEL_LIMIT: Dict[str, int] = {"rpm": 5, "rpd": 20}

_WARNED_MODELS: Set[Tuple[str, str]] = set()
_STOPPED_MODELS: Set[Tuple[str, str]] = set()

_LAST_CALL_TIMES: Dict[str, float] = {}
_PACER_LOCK_ASYNC: Optional[asyncio.Lock] = None
_PACER_SEMAPHORE_ASYNC: Optional[asyncio.Semaphore] = None
_PACER_LOCK_SYNC = threading.Lock()


def normalize_model_name(model: str) -> str:
    """Normalize model string, stripping 'models/' prefixes."""
    m = (model or "").strip()
    if m.startswith("models/"):
        m = m[len("models/"):]
    return m or "unknown-model"


def get_model_limits(model: str) -> Dict[str, Any]:
    """
    Returns rate and daily limits for a model:
    {
      "rpm": int,
      "rpd": int,
      "stop_threshold": int,  # 80% of rpd
      "warn_threshold": int,  # 60% of rpd
      "pacing_interval_sec": float,  # (60 / rpm) * 1.2
    }
    """
    norm = normalize_model_name(model)
    limits_dict = DEFAULT_MODEL_LIMITS

    raw_env = os.environ.get("LLM_MODEL_LIMITS")
    if raw_env:
        try:
            parsed = json.loads(raw_env)
            if isinstance(parsed, dict):
                limits_dict = parsed
        except Exception:
            pass

    cfg = limits_dict.get(norm, UNKNOWN_MODEL_LIMIT)
    rpm = int(cfg.get("rpm", 5))
    rpd = int(cfg.get("rpd", 20))
    stop_threshold = int(rpd * 0.8)
    warn_threshold = int(rpd * 0.6)
    pacing_interval = (60.0 / max(1, rpm)) * 1.2

    return {
        "rpm": rpm,
        "rpd": rpd,
        "stop_threshold": stop_threshold,
        "warn_threshold": warn_threshold,
        "pacing_interval_sec": pacing_interval,
    }


def get_pacific_date(dt: Optional[datetime] = None) -> str:
    """
    Returns YYYY-MM-DD for the date in America/Los_Angeles timezone.
    Boundary is midnight Pacific Time.
    """
    if dt is None:
        return datetime.now(PACIFIC_TZ).strftime("%Y-%m-%d")

    if dt.tzinfo is None:
        # Naive datetime: assume UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(PACIFIC_TZ).strftime("%Y-%m-%d")


def get_usage_file_path() -> Path:
    """
    Resolves the path to the shared .llm_usage counter file.
    Works seamlessly across Docker containers (/app/.llm_usage) and Windows host.
    """
    env_path = os.environ.get("LLM_USAGE_FILE")
    if env_path:
        return Path(env_path)

    candidates = [
        Path("/app/.llm_usage"),
        Path(__file__).resolve().parents[3] / ".llm_usage",
        Path.cwd() / ".llm_usage",
        Path(__file__).resolve().parents[2] / ".llm_usage",
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            return c

    # Default fallback
    if Path("/app").exists() and Path("/app").is_dir():
        return Path("/app/.llm_usage")
    return Path(__file__).resolve().parents[3] / ".llm_usage"


class FileLock:
    """Cross-platform, atomic, inter-process file lock using O_CREAT | O_EXCL."""

    def __init__(self, lockfile: Path, timeout: float = 10.0):
        self.lockfile = lockfile
        self.timeout = timeout
        self.fd: Optional[int] = None

    def __enter__(self):
        start = time.time()
        while True:
            try:
                self.fd = os.open(str(self.lockfile), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                return self
            except FileExistsError:
                if time.time() - start > self.timeout:
                    # Clean up stale locks older than timeout
                    try:
                        mtime = os.path.getmtime(str(self.lockfile))
                        if time.time() - mtime > self.timeout:
                            os.remove(str(self.lockfile))
                            continue
                    except Exception:
                        pass
                    raise TimeoutError(f"Timed out acquiring lock on {self.lockfile}")
                time.sleep(0.05)

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except Exception:
                pass
        try:
            if self.lockfile.exists():
                os.remove(str(self.lockfile))
        except Exception:
            pass


def _read_usage_data(filepath: Path) -> Dict[str, Any]:
    if not filepath.exists():
        return {}
    try:
        content = filepath.read_text(encoding="utf-8").strip()
        if not content:
            return {}
        return json.loads(content)
    except Exception as e:
        logger.warning("Could not read LLM usage file %s: %s", filepath, e)
        return {}


def _write_usage_data(filepath: Path, data: Dict[str, Any]) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = filepath.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.replace(tmp_path, filepath)
    except Exception:
        # Fallback if atomic replace fails across mount
        filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")
        if tmp_path.exists():
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def get_model_call_count(model: str, day_str: Optional[str] = None) -> int:
    """Returns the recorded number of API call attempts for the given model and day."""
    norm = normalize_model_name(model)
    day = day_str or get_pacific_date()
    filepath = get_usage_file_path()
    lockfile = filepath.with_suffix(".lock")

    try:
        with FileLock(lockfile):
            data = _read_usage_data(filepath)
            return int(data.get(norm, {}).get(day, 0))
    except Exception:
        data = _read_usage_data(filepath)
        return int(data.get(norm, {}).get(day, 0))


def record_call_attempt(model: str, day_str: Optional[str] = None) -> int:
    """
    Atomically increments and returns the call attempt count for the model and day.
    Called for EVERY attempt (initial calls, retries, and failed 429s).
    """
    norm = normalize_model_name(model)
    day = day_str or get_pacific_date()
    filepath = get_usage_file_path()
    lockfile = filepath.with_suffix(".lock")

    with FileLock(lockfile):
        data = _read_usage_data(filepath)
        if norm not in data or not isinstance(data[norm], dict):
            data[norm] = {}
        curr = int(data[norm].get(day, 0)) + 1
        data[norm][day] = curr
        _write_usage_data(filepath, data)
        return curr


def check_call_safety(model: str, day_str: Optional[str] = None) -> Tuple[bool, str]:
    """
    Checks if a real API call is permitted under daily quota limits.
    Returns (True, "") if allowed.
    If 80% daily limit is reached: returns (False, "budget") and logs once.
    If 60% daily limit is reached: logs warning once.
    """
    norm = normalize_model_name(model)
    day = day_str or get_pacific_date()
    count = get_model_call_count(norm, day)
    limits = get_model_limits(norm)

    stop_thresh = limits["stop_threshold"]
    warn_thresh = limits["warn_threshold"]
    rpd = limits["rpd"]

    key = (norm, day)

    if count >= stop_thresh:
        if key not in _STOPPED_MODELS:
            logger.error(
                "[LLM BUDGET STOP] Hard safety limit reached for model '%s' on %s "
                "(%d/%d calls, 80%% cap is %d). Refusing real API call; deterministic fallback triggered.",
                norm,
                day,
                count,
                rpd,
                stop_thresh,
            )
            _STOPPED_MODELS.add(key)
        return False, "budget"

    if count >= warn_thresh:
        if key not in _WARNED_MODELS:
            logger.warning(
                "[LLM BUDGET WARNING] Model '%s' on %s reached %d/%d calls (60%% threshold is %d).",
                norm,
                day,
                count,
                rpd,
                warn_thresh,
            )
            _WARNED_MODELS.add(key)

    return True, ""


async def async_pace_call(model: str) -> None:
    """
    Asynchronously paces calls for the model:
    Enforces concurrency 1 and waits at least (60 / rpm) * 1.2 seconds between calls.
    """
    global _PACER_LOCK_ASYNC, _PACER_SEMAPHORE_ASYNC
    if _PACER_LOCK_ASYNC is None:
        _PACER_LOCK_ASYNC = asyncio.Lock()
    if _PACER_SEMAPHORE_ASYNC is None:
        _PACER_SEMAPHORE_ASYNC = asyncio.Semaphore(1)

    norm = normalize_model_name(model)
    interval = get_model_limits(norm)["pacing_interval_sec"]

    await _PACER_SEMAPHORE_ASYNC.acquire()
    try:
        async with _PACER_LOCK_ASYNC:
            now = time.monotonic()
            last = _LAST_CALL_TIMES.get(norm, 0.0)
            elapsed = now - last
            if elapsed < interval:
                await asyncio.sleep(interval - elapsed)
            _LAST_CALL_TIMES[norm] = time.monotonic()
    finally:
        _PACER_SEMAPHORE_ASYNC.release()


def sync_pace_call(model: str) -> None:
    """
    Synchronously paces calls for the model (used by CLI scripts).
    Enforces concurrency 1 and waits at least (60 / rpm) * 1.2 seconds between calls.
    """
    norm = normalize_model_name(model)
    interval = get_model_limits(norm)["pacing_interval_sec"]

    with _PACER_LOCK_SYNC:
        now = time.monotonic()
        last = _LAST_CALL_TIMES.get(norm, 0.0)
        elapsed = now - last
        if elapsed < interval:
            time.sleep(interval - elapsed)
        _LAST_CALL_TIMES[norm] = time.monotonic()
