"""
Pure-Function Disruption Pipeline Core.

Entrypoint: `handle_disruption(event, booking, deps, constraints) -> DecisionResult`
Guaranteed Pure: No FastAPI dependencies, no database session, no Redis inside.
All side effects and state dependencies injected cleanly via `PipelineDeps`.
"""

import logging
import time
from typing import Any, Dict, List, Optional
from datetime import datetime

logger = logging.getLogger("reroute.pipeline")

from app.schemas.pipeline import (
    ActionType,
    CandidateFlight,
    DecisionMetrics,
    DecisionResult,
    DisruptionEvent,
    DisruptionType,
    OriginalBooking,
    PolicyResult,
    PolicyVerdict,
    TripConstraints,
)
from app.agent.orchestrator import (
    ConciergeState,
    InMemoryTraceSink,
    PipelineDeps,
    build_concierge_graph,
)
from app.agent.context_budget import calculate_cost, usd_to_inr
from app.core.config import get_settings

# Pre-compiled workflow graph singleton
_compiled_graph = build_concierge_graph()



async def handle_disruption(
    event: DisruptionEvent,
    booking: OriginalBooking,
    deps: Optional[PipelineDeps] = None,
    constraints: Optional[TripConstraints] = None,
) -> DecisionResult:
    """
    Pure-function pipeline execution.
    Takes event + booking state + deps, executes the agent state graph,
    and returns a clean, fully-typed DecisionResult.
    """
    start_time = time.perf_counter()
    pipeline_deps = deps or PipelineDeps()

    if constraints is None:
        clock_time = pipeline_deps.clock
        if clock_time and clock_time.date() <= booking.departure_time.date():
            earliest_dep = clock_time
        else:
            earliest_dep = booking.departure_time

        constraints = TripConstraints(
            required_origin=booking.origin,
            required_destination=booking.destination,
            earliest_departure_time=earliest_dep,
            original_arrival_time=booking.arrival_time,
            allowed_cabins=[booking.cabin_class],
        )

    initial_state: ConciergeState = {
        "event": event,
        "booking": booking,
        "constraints": constraints,
        "deps": pipeline_deps,
        "trace_stages": [],
        "start_time_monotonic": start_time,
    }

    try:
        # Run graph through LangGraph async invoke
        final_state: ConciergeState = await _compiled_graph.ainvoke(initial_state)

        end_time = time.perf_counter()
        latency_ms = round((end_time - start_time) * 1000.0, 2)

        is_disrupted = final_state.get("is_disrupted", False)
        disruption_type = final_state.get("disruption_type", DisruptionType.NONE)
        action = final_state.get("action", ActionType.NO_ACTION)
        verdict = final_state.get("final_verdict", PolicyVerdict.APPROVED)

        rebooking_rec = final_state.get("rebooking_record")
        hotel_rec = final_state.get("hotel_record")
        notif = final_state.get("notification")

        candidates: List[CandidateFlight] = final_state.get("candidates", [])
        policy_results: List[PolicyResult] = final_state.get("policy_results", [])
        
        reasons_list: List[str] = []
        if final_state.get("final_policy_result"):
            reasons_list = final_state["final_policy_result"].reasons
        elif policy_results:
            for pr in policy_results:
                reasons_list.extend(pr.reasons)
            reasons_list = list(set(reasons_list))

        tokens_in = final_state.get("tokens_in", 0)
        tokens_out = final_state.get("tokens_out", 0)
        cost_estimated = final_state.get("cost_estimated", (tokens_in == "unknown" or tokens_out == "unknown"))
        cost_usd = final_state.get("cost_usd")
        if cost_usd is None:
            if isinstance(tokens_in, int) and isinstance(tokens_out, int):
                s = get_settings()
                cost_usd = calculate_cost(
                    tokens_in,
                    tokens_out,
                    price_in_per_mtok=s.LLM_PRICE_INPUT_PER_MTOK_USD,
                    price_out_per_mtok=s.LLM_PRICE_OUTPUT_PER_MTOK_USD,
                )
            else:
                cost_usd = 0.0
        cost_inr = final_state.get("cost_inr", usd_to_inr(cost_usd, get_settings().USD_TO_INR))
        llm_fallback = final_state.get("llm_fallback", False)

        fare_delta = 0.0
        if rebooking_rec:
            fare_delta = float(rebooking_rec.get("fare_delta_inr", 0.0))

        notification_dict = (
            {"subject": notif.subject, "body": notif.body}
            if notif
            else {}
        )

        result_summary = {
            "event_id": event.event_id,
            "action": action.value if hasattr(action, "value") else str(action),
            "policy_verdict": verdict.value if hasattr(verdict, "value") else str(verdict),
            "new_flight": rebooking_rec,
            "fare_delta_inr": fare_delta,
            "llm_fallback": llm_fallback,
            "llm_fallback_reason": final_state.get(
                "llm_fallback_reason",
                "outage" if llm_fallback else "none"
            ),
            "agent_steps": final_state.get("agent_steps", 1),
            "revisions_used": final_state.get("revisions_used", 0),
            "tool_calls": final_state.get("tool_calls", 0),
            "first_proposal_valid": final_state.get("first_proposal_valid", True),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
            "cost_inr": cost_inr,
            "cost_estimated": cost_estimated,
            "latency_ms": latency_ms,
            "error": final_state.get("error"),
        }

        if hasattr(pipeline_deps, "trace_sink") and pipeline_deps.trace_sink:
            pipeline_deps.trace_sink.record_stage(
                "RESULT",
                {"event_id": event.event_id},
                result_summary,
            )

        trace_stages = (
            pipeline_deps.trace_sink.stages
            if hasattr(pipeline_deps.trace_sink, "stages")
            else []
        )

        return DecisionResult(
            event_id=event.event_id,
            detected=is_disrupted,
            disruption_type=disruption_type,
            alternatives_considered=[c.model_dump(mode="json") for c in candidates],
            policy_verdict=verdict,
            policy_reasons=reasons_list,
            action=action,
            new_flight=rebooking_rec,
            hotel=hotel_rec,
            fare_delta=fare_delta,
            explanation=final_state.get("explanation", ""),
            citations=[],
            notification=notification_dict,
            trace_stages=trace_stages,
            metrics={
                "latency_ms": latency_ms,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": cost_usd,
                "cost_inr": cost_inr,
                "cost_estimated": cost_estimated,
                "llm_fallback": llm_fallback,
            },
            error=final_state.get("error"),
        )


    except Exception as e:
        end_time = time.perf_counter()
        latency_ms = round((end_time - start_time) * 1000.0, 2)
        logger.error(
            "[PIPELINE ERROR] Pipeline exception processing event %s: %s",
            event.event_id,
            str(e),
            exc_info=True,
        )

        error_summary = {
            "event_id": event.event_id,
            "action": ActionType.ERROR.value,
            "policy_verdict": PolicyVerdict.ESCALATE.value,
            "new_flight": None,
            "fare_delta_inr": 0.0,
            "llm_fallback": True,
            "llm_fallback_reason": "outage",
            "agent_steps": 0,
            "revisions_used": 0,
            "tool_calls": 0,
            "first_proposal_valid": False,
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0.0,
            "cost_inr": 0.0,
            "latency_ms": latency_ms,
            "error": str(e),
        }

        if hasattr(pipeline_deps, "trace_sink") and pipeline_deps.trace_sink:
            pipeline_deps.trace_sink.record_stage(
                "RESULT",
                {"event_id": event.event_id, "error": str(e)},
                error_summary,
            )

        trace_stages = (
            pipeline_deps.trace_sink.stages
            if hasattr(pipeline_deps.trace_sink, "stages")
            else []
        )

        return DecisionResult(
            event_id=event.event_id,
            detected=False,
            disruption_type=DisruptionType.NONE,
            alternatives_considered=[],
            policy_verdict=PolicyVerdict.ESCALATE,
            policy_reasons=["PIPELINE_ERROR"],
            action=ActionType.ERROR,
            new_flight=None,
            hotel=None,
            fare_delta=0.0,
            explanation=f"Pipeline error during autonomous disruption processing: {str(e)}",
            citations=[],
            notification={},
            trace_stages=trace_stages,
            metrics={
                "latency_ms": latency_ms,
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd": 0.0,
                "cost_inr": 0.0,
                "llm_fallback": True,
            },
            error=str(e),
        )
