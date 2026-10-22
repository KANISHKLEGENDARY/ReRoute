"""
Assertion Helpers and Utilities for ReRoute Evaluation Suite.

Provides parsing, extraction, date comparisons, and invariant grading utilities.
"""

from datetime import datetime, date, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, Optional, Tuple

eval_dir = Path(__file__).resolve().parents[1]
repo_root = eval_dir.parent
backend_dir = repo_root / "backend"

if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
if str(eval_dir) not in sys.path:
    sys.path.insert(0, str(eval_dir))

from app.sandbox.inventory import FlightInventorySandbox, default_inventory
from app.schemas.pipeline import to_naive_utc


def parse_output_and_context(output: str, context: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Parses the JSON output string from the provider and extracts the scenario from context.
    """
    try:
        if isinstance(output, str):
            data = json.loads(output)
        elif isinstance(output, dict):
            data = output
        else:
            data = {"raw_output": str(output)}
    except Exception as e:
        data = {"error": f"Failed to parse JSON output: {e}", "raw_output": output}

    vars_dict = context.get("vars", {}) if context else {}
    scenario = vars_dict.get("scenario")
    if not scenario:
        scenario = vars_dict

    return data, scenario


def parse_datetime(val: Any) -> Optional[datetime]:
    """Robustly parse ISO datetime strings or datetime objects to UTC naive."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return to_naive_utc(val)
    if isinstance(val, str):
        cleaned = val.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(cleaned)
            return to_naive_utc(dt)
        except Exception:
            return None
    return None


def parse_date(val: Any) -> Optional[date]:
    """Parse date from string or date object."""
    if val is None:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        try:
            return date.fromisoformat(val[:10])
        except Exception:
            return None
    return None


def pass_result(reason: str = "Invariant passed") -> Dict[str, Any]:
    return {"pass": True, "score": 1.0, "reason": reason}


def fail_result(reason: str) -> Dict[str, Any]:
    return {"pass": False, "score": 0.0, "reason": reason}


# Sensitive patterns to check for PII or secret leakage
LEAK_PATTERNS = [
    re.compile(r"AIzaSy[A-Za-z0-9\-_]{33}"),  # Google API Key format
    re.compile(r"sk-[A-Za-z0-9]{20,}"),      # OpenAI / generic key format
    re.compile(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}"),  # bcrypt hash
    re.compile(r"supersecret_dev_key"),       # Dev secret key
    re.compile(r"Bearer\s+[A-Za-z0-9\-_.]+"),  # Bearer token
]
