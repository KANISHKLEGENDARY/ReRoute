"""
Budget Guards Driven by Persisted RESULT Rows.

Computes:
- DAILY_LLM_BUDGET_USD: total notional LLM cost for the active calendar day
- DAILY_LLM_CALL_LIMIT: total LLM calls made for the active calendar day

Day boundary strictly determined by `deps.clock`, never `datetime.now()`.
Queries persisted `decision_trace` RESULT rows (or in-memory trace sink in tests).
"""

from datetime import datetime, date, timezone
from typing import Tuple, Optional, Any
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.models.trace import DecisionTrace
from app.core.database import async_session_factory


async def check_persisted_budget_guards(
    deps: Any,
    settings: Optional[Settings] = None,
) -> Tuple[bool, str, float, int]:
    """
    Computes daily cost and call count from persisted RESULT rows for deps.clock.date().
    Returns: (is_exceeded, reason, daily_cost_usd, daily_calls)
    """
    s = settings or get_settings()
    clock_dt = getattr(deps, "clock", datetime.utcnow())
    target_date = clock_dt.date()

    daily_cost_usd = 0.0
    daily_calls = 0

    # 1. Check in-memory stages if available (in unit tests)
    if hasattr(deps, "trace_sink") and hasattr(deps.trace_sink, "stages"):
        for entry in deps.trace_sink.stages:
            if entry.get("stage") == "RESULT":
                # Check entry timestamp date against deps.clock date
                ts = entry.get("timestamp")
                entry_date = None
                if isinstance(ts, datetime):
                    entry_date = ts.date()
                elif isinstance(ts, str):
                    try:
                        entry_date = datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
                    except Exception:
                        pass

                if entry_date == target_date:
                    out = entry.get("output_snapshot", {})
                    cost = float(out.get("cost_usd", 0.0))
                    tokens_in = int(out.get("tokens_in", 0))
                    fallback = bool(out.get("llm_fallback", False))

                    if not fallback or cost > 0 or tokens_in > 0:
                        daily_calls += 1
                        daily_cost_usd += cost

    # 2. Check Postgres / SQLite database if active session factory exists
    try:
        async with async_session_factory() as session:
            stmt = select(DecisionTrace).where(DecisionTrace.stage == "RESULT")
            result = await session.execute(stmt)
            rows = result.scalars().all()

            db_cost = 0.0
            db_calls = 0
            for r in rows:
                if r.timestamp and r.timestamp.date() == target_date:
                    out = r.output_snapshot or {}
                    cost = float(out.get("cost_usd", 0.0))
                    tokens_in = int(out.get("tokens_in", 0))
                    fallback = bool(out.get("llm_fallback", False))

                    if not fallback or cost > 0 or tokens_in > 0:
                        db_calls += 1
                        db_cost += cost

            # Maximize between DB and memory to prevent undercounting
            daily_cost_usd = max(daily_cost_usd, db_cost)
            daily_calls = max(daily_calls, db_calls)
    except Exception:
        pass

    daily_cost_usd = round(daily_cost_usd, 6)

    # Check budget thresholds
    if daily_cost_usd >= s.DAILY_LLM_BUDGET_USD:
        return True, "budget", daily_cost_usd, daily_calls

    if daily_calls >= s.DAILY_LLM_CALL_LIMIT:
        return True, "budget", daily_cost_usd, daily_calls

    return False, "none", daily_cost_usd, daily_calls
