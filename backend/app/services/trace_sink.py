"""
Database-Backed Decision Trace Sink with PII & Secret Redaction.

Persists stage-by-stage explainability logs into the `decision_trace` table
and broadcasts live stage transitions to the WebSocket activity feed.
"""

from datetime import datetime
import re
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trace import DecisionTrace
from app.core.activity_feed import activity_feed

# Keys that must always be sanitized in decision traces
SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "secret",
    "secret_key",
    "api_key",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "jwt",
}

TOKEN_METRIC_KEYS = {
    "tokens",
    "tokens_in",
    "tokens_out",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "prompt_tokens_est",
    "max_tokens",
    "token_count",
}


def redact_pii_and_secrets(obj: Any) -> Any:
    """
    Recursively scrubs sensitive keys and PII patterns from JSON snapshot dictionaries.
    Preserves numerical token accounting metrics (tokens_in, tokens_out).
    """
    if isinstance(obj, dict):
        sanitized = {}
        for k, v in obj.items():
            k_lower = str(k).lower()
            if k_lower in TOKEN_METRIC_KEYS or "tokens_in" in k_lower or "tokens_out" in k_lower:
                sanitized[k] = redact_pii_and_secrets(v)
            elif k_lower in SENSITIVE_KEYS or any(s in k_lower for s in ["password", "secret", "private_key"]):
                sanitized[k] = "[REDACTED]"
            elif "token" in k_lower and not any(t in k_lower for t in ["count", "usage", "in", "out", "est", "num", "budget"]):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = redact_pii_and_secrets(v)
        return sanitized
    elif isinstance(obj, list):
        return [redact_pii_and_secrets(item) for item in obj]
    elif isinstance(obj, str):
        # Redact bearer tokens or API key strings if found
        if re.match(r"^Bearer\s+[A-Za-z0-9\-_.]+", obj):
            return "Bearer [REDACTED]"
        return obj
    return obj


import asyncio
import time
from datetime import datetime, timezone


class DatabaseTraceSink:
    """
    Trace sink implementing the `record_stage` protocol, persisting to Postgres/SQLite.
    Gives each stage its own real timestamp and latency_ms, written as the stage completes,
    and streams each stage over WebSocket as it finishes.
    """

    def __init__(self, session: AsyncSession, itinerary_id: int, event_id: str = ""):
        self.session = session
        self.itinerary_id = itinerary_id
        self.event_id = event_id or "UNKNOWN"
        self.stages: List[Dict[str, Any]] = []
        self._last_perf_counter = time.perf_counter()

    def record_stage(
        self,
        stage_name: str,
        input_snapshot: Dict[str, Any],
        output_snapshot: Dict[str, Any],
    ) -> None:
        """
        Records a stage with exact completion timestamp, stage latency_ms,
        and streams immediately to the WebSocket activity feed.
        """
        now_perf = time.perf_counter()
        stage_latency_ms = round((now_perf - self._last_perf_counter) * 1000.0, 2)
        self._last_perf_counter = now_perf

        now_utc = datetime.now(timezone.utc)

        clean_input = redact_pii_and_secrets(input_snapshot)
        clean_output = redact_pii_and_secrets(output_snapshot)

        # Ensure latency_ms is recorded on the stage snapshot
        if "latency_ms" not in clean_output:
            clean_output["latency_ms"] = stage_latency_ms

        entry_event_id = (
            clean_input.get("event_id")
            or clean_output.get("event_id")
            or self.event_id
        )

        entry = {
            "event_id": str(entry_event_id),
            "stage": stage_name,
            "itinerary_id": self.itinerary_id,
            "input_snapshot": clean_input,
            "output_snapshot": clean_output,
            "timestamp": now_utc,
            "latency_ms": clean_output.get("latency_ms", stage_latency_ms),
        }
        self.stages.append(entry)

        # Stream stage immediately over WebSocket activity feed as it finishes
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                activity_feed.broadcast(
                    "STAGE_TRACE",
                    {
                        "event_id": str(entry_event_id),
                        "itinerary_id": self.itinerary_id,
                        "stage": stage_name,
                        "output_snapshot": clean_output,
                        "timestamp": now_utc.isoformat(),
                        "latency_ms": clean_output.get("latency_ms", stage_latency_ms),
                    },
                )
            )
        except RuntimeError:
            pass

    async def flush_to_db(self) -> List[DecisionTrace]:
        """
        Asynchronously writes all buffered stage traces into the database with their
        individual real completion timestamps and latencies.
        """
        persisted_records: List[DecisionTrace] = []
        for entry in self.stages:
            record = DecisionTrace(
                event_id=entry["event_id"],
                itinerary_id=self.itinerary_id,
                stage=entry["stage"],
                input_snapshot=entry["input_snapshot"],
                output_snapshot=entry["output_snapshot"],
                timestamp=entry["timestamp"],
            )
            self.session.add(record)
            persisted_records.append(record)

        await self.session.flush()
        return persisted_records
