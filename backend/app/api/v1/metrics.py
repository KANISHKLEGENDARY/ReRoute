"""
Metrics Aggregation API Endpoint.

Calculates dynamic, on-demand performance metrics computed directly over
the `decision_trace` table:
- Disruptions handled
- Auto-resolution vs. Escalation rate
- Average and p95 end-to-end latency
- Average fare delta (INR)
- LLM fallback rate
- Average token usage and cost per run (USD and INR)
"""

from typing import Any, Dict, List
import numpy as np
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.trace import DecisionTrace
from app.agent.context_budget import usd_to_inr

router = APIRouter(prefix="/metrics", tags=["Metrics & Observability"])
settings = get_settings()


class MetricsSummary(BaseModel):
    disruptions_handled: int = Field(default=0, description="Count of distinct disruption events processed")
    auto_resolution_rate: float = Field(default=0.0, description="Percentage/rate of disruptions successfully rebooked")
    escalation_rate: float = Field(default=0.0, description="Percentage/rate of disruptions escalated to human review")
    error_rate: float = Field(default=0.0, description="Percentage/rate of disruptions that ended in error")
    avg_latency_ms: float = Field(default=0.0, description="Average measured pipeline latency in milliseconds")
    p95_latency_ms: float = Field(default=0.0, description="95th percentile pipeline latency in milliseconds")
    avg_fare_delta_inr: float = Field(default=0.0, description="Average fare delta in INR for rebooked flights")
    llm_fallback_rate: float = Field(default=0.0, description="Percentage/rate of runs where deterministic fallback was used")
    llm_fallback_reasons: Dict[str, int] = Field(
        default_factory=lambda: {
            "none": 0,
            "no_key": 0,
            "outage": 0,
            "rate_limit": 0,
            "budget": 0,
            "invalid_output": 0,
            "model_not_found": 0,
        },
        description="Count of fallbacks broken down by reason"
    )
    avg_tokens_per_run: float = Field(default=0.0, description="Average total tokens (input + output) per event")
    avg_cost_usd_per_run: float = Field(default=0.0, description="Average estimated LLM cost in USD per event")
    avg_cost_inr_per_run: float = Field(default=0.0, description="Average estimated LLM cost in INR per event")
    avg_agent_steps: float = Field(default=0.0, description="Average agent loop steps per event")
    avg_revisions_used: float = Field(default=0.0, description="Average proposal revisions used per event")
    first_proposal_valid_rate: float = Field(default=0.0, description="Rate at which the first proposed flight was policy-compliant")


@router.get("", response_model=MetricsSummary)
async def get_system_metrics(db: AsyncSession = Depends(get_db)):
    """
    Computes system performance metrics aggregated from RESULT stage decision traces per event_id.
    """
    stmt = (
        select(DecisionTrace)
        .where(DecisionTrace.stage == "RESULT")
        .order_by(DecisionTrace.timestamp.asc(), DecisionTrace.id.asc())
    )
    result = await db.execute(stmt)
    result_traces = result.scalars().all()

    if not result_traces:
        return MetricsSummary()

    # Deduplicate by event_id, keeping the latest RESULT row for each distinct event
    events_map: Dict[str, DecisionTrace] = {}
    for trace in result_traces:
        evt_id = trace.event_id or f"LEGACY-{trace.id}"
        events_map[evt_id] = trace

    total_events = len(events_map)
    if total_events == 0:
        return MetricsSummary()

    rebooked_count = 0
    escalated_count = 0
    error_count = 0
    latencies: List[float] = []
    fare_deltas: List[float] = []
    fallback_count = 0
    fallback_reasons: Dict[str, int] = {
        "none": 0,
        "no_key": 0,
        "outage": 0,
        "rate_limit": 0,
        "budget": 0,
        "invalid_output": 0,
        "model_not_found": 0,
    }
    tokens_list: List[int] = []
    cost_usd_list: List[float] = []
    cost_inr_list: List[float] = []
    agent_steps_list: List[int] = []
    revisions_list: List[int] = []
    first_prop_valid_count = 0

    for trace in events_map.values():
        out = trace.output_snapshot or {}
        action = str(out.get("action", "")).upper()

        if action in ["REBOOKED", "REBOOKED_AND_HOTEL"]:
            rebooked_count += 1
            if "fare_delta_inr" in out and out["fare_delta_inr"] is not None:
                fare_deltas.append(float(out["fare_delta_inr"]))
        elif action == "ESCALATED":
            escalated_count += 1
        elif action == "ERROR":
            error_count += 1

        # Measured pipeline latency (not timestamp gap)
        lat = 0.0
        try:
            lat = float(out.get("latency_ms", 0.0))
        except (ValueError, TypeError):
            lat = 0.0
        latencies.append(lat)

        # Fallback metrics
        is_fallback = bool(out.get("llm_fallback", False))
        if is_fallback:
            fallback_count += 1
            reason = str(out.get("llm_fallback_reason", "outage")).lower()
        else:
            reason = str(out.get("llm_fallback_reason", "none")).lower()
        fallback_reasons[reason] = fallback_reasons.get(reason, 0) + 1

        # Token & cost metrics
        tok_in = 0
        tok_out = 0
        try:
            tok_in = int(out.get("tokens_in", 0))
        except (ValueError, TypeError):
            tok_in = 0
        try:
            tok_out = int(out.get("tokens_out", 0))
        except (ValueError, TypeError):
            tok_out = 0
        tokens_list.append(tok_in + tok_out)

        c_usd = 0.0
        try:
            c_usd = float(out.get("cost_usd", 0.0))
        except (ValueError, TypeError):
            c_usd = 0.0
        cost_usd_list.append(c_usd)

        c_inr = 0.0
        try:
            c_inr = float(out.get("cost_inr", 0.0))
        except (ValueError, TypeError):
            c_inr = 0.0
        cost_inr_list.append(c_inr)

        # Agent step & revision metrics
        steps = 1
        try:
            steps = int(out.get("agent_steps", 1))
        except (ValueError, TypeError):
            steps = 1
        agent_steps_list.append(steps)

        revs = 0
        try:
            revs = int(out.get("revisions_used", 0))
        except (ValueError, TypeError):
            revs = 0
        revisions_list.append(revs)

        if bool(out.get("first_proposal_valid", True)):
            first_prop_valid_count += 1

    auto_res_rate = round(rebooked_count / total_events, 4)
    esc_rate = round(escalated_count / total_events, 4)
    err_rate = round(error_count / total_events, 4)
    fb_rate = round(fallback_count / total_events, 4)
    first_valid_rate = round(first_prop_valid_count / total_events, 4)

    avg_lat = round(float(np.mean(latencies)), 2) if latencies else 0.0
    p95_lat = round(float(np.percentile(latencies, 95)), 2) if latencies else 0.0
    avg_fare = round(float(np.mean(fare_deltas)), 2) if fare_deltas else 0.0
    avg_tokens = round(float(np.mean(tokens_list)), 1) if tokens_list else 0.0
    avg_cost_usd = round(float(np.mean(cost_usd_list)), 6) if cost_usd_list else 0.0
    avg_cost_inr = round(float(np.mean(cost_inr_list)), 2) if cost_inr_list else 0.0
    avg_steps = round(float(np.mean(agent_steps_list)), 2) if agent_steps_list else 0.0
    avg_revs = round(float(np.mean(revisions_list)), 2) if revisions_list else 0.0

    return MetricsSummary(
        disruptions_handled=total_events,
        auto_resolution_rate=auto_res_rate,
        escalation_rate=esc_rate,
        error_rate=err_rate,
        avg_latency_ms=avg_lat,
        p95_latency_ms=p95_lat,
        avg_fare_delta_inr=avg_fare,
        llm_fallback_rate=fb_rate,
        llm_fallback_reasons=fallback_reasons,
        avg_tokens_per_run=avg_tokens,
        avg_cost_usd_per_run=avg_cost_usd,
        avg_cost_inr_per_run=avg_cost_inr,
        avg_agent_steps=avg_steps,
        avg_revisions_used=avg_revs,
        first_proposal_valid_rate=first_valid_rate,
    )
