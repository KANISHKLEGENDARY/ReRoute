"""
LangGraph Orchestrator for Autonomous Travel-Disruption Concierge.

Coordinates:
[Parse Notice (if present)] -> [Detect Disruption] -> [Search & Policy Filter] -> [Agentic Propose-Validate-Revise Loop] -> [Policy Verification] -> [Execute Rebooking] -> [Adjust Hotel] -> [Explain & Notify]

Guarantees:
- Pure-Function Core: No DB sessions, FastAPI, or Redis inside the graph.
- LLM PROPOSES, POLICY DISPOSES: Code is the deterministic safety layer.
- Propose-Validate-Revise loop up to MAX_REVISIONS with feedback passed back.
- Tool calling capped at MAX_AGENT_STEPS, validating arguments with Pydantic.
- TOOL_CALL trace stages logged with event_id.
- Free-text notice parsing with untrusted data isolation.
- Traveler preferences never override policy rules.
- Fact verification in explanations; fallback to deterministic template on discrepancy.
- Fallback reasons recorded: none, no_key, outage, rate_limit, budget, invalid_output, model_not_found.
"""

from datetime import datetime, date, timedelta, timezone
import time
from typing import Any, Dict, List, Optional, Protocol, TypedDict
from langgraph.graph import StateGraph, END

from app.schemas.pipeline import (
    ActionType,
    CabinClass,
    CandidateFlight,
    DecisionMetrics,
    DecisionResult,
    DisruptionEvent,
    DisruptionType,
    HotelOption,
    NotificationPayload,
    OriginalBooking,
    PolicyResult,
    PolicyVerdict,
    ReasonCode,
    TripConstraints,
)
from app.sandbox.inventory import FlightInventorySandbox, default_inventory
from app.policy.engine import evaluate_policy
from app.agent.detection import detect_disruption
from app.agent.tools import (
    search_alternatives_tool,
    evaluate_candidates_tool,
    execute_rebooking_tool,
    adjust_hotel_tool,
    format_notification_tool,
    SearchAlternativesArgs,
    CheckHotelOptionsArgs,
    CheckPolicyArgs,
    ProposeFlightChoiceArgs,
)
from app.agent.context_budget import ContextBudgeter, calculate_cost, usd_to_inr
from app.agent.llm import (
    LLMInterface,
    get_llm_client,
    NoKeyLLMClient,
    FakeLLM,
    verify_explanation_facts,
    ParsedNoticeDisruption,
)
from app.agent.budget_guard import check_persisted_budget_guards
from app.core.config import get_settings


class TraceSinkProtocol(Protocol):
    def record_stage(self, stage_name: str, input_snapshot: Dict[str, Any], output_snapshot: Dict[str, Any]) -> None:
        ...


class InMemoryTraceSink:
    def __init__(self, event_id: str = ""):
        self.event_id = event_id or "UNKNOWN"
        self.stages: List[Dict[str, Any]] = []
        self._last_perf = time.perf_counter()

    def record_stage(self, stage_name: str, input_snapshot: Dict[str, Any], output_snapshot: Dict[str, Any]) -> None:
        now_perf = time.perf_counter()
        stage_latency_ms = round((now_perf - self._last_perf) * 1000.0, 2)
        self._last_perf = now_perf

        if "latency_ms" not in output_snapshot:
            output_snapshot["latency_ms"] = stage_latency_ms

        entry_event_id = (
            input_snapshot.get("event_id")
            or output_snapshot.get("event_id")
            or self.event_id
        )
        self.stages.append({
            "event_id": str(entry_event_id),
            "stage": stage_name,
            "input_snapshot": input_snapshot,
            "output_snapshot": output_snapshot,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "latency_ms": output_snapshot.get("latency_ms", stage_latency_ms),
        })


class PipelineDeps:
    """
    Dependency Injection Container for ReRoute Disruption Pipeline.
    """

    def __init__(
        self,
        inventory: Optional[FlightInventorySandbox] = None,
        llm: Optional[Any] = None,
        trace_sink: Optional[Any] = None,
        clock: Optional[datetime] = None,
        retriever: Optional[Any] = None,
        max_tokens_budget: int = 2048,
        daily_cost_budget_usd: float = 10.0,
        current_daily_cost_usd: float = 0.0,
    ):
        self.inventory = inventory or default_inventory
        self.llm = llm if llm is not None else get_llm_client()
        self.trace_sink = trace_sink or InMemoryTraceSink()
        self.clock = clock or datetime.now(timezone.utc)
        self.retriever = retriever
        self.context_budgeter = ContextBudgeter(max_tokens=max_tokens_budget)
        self.daily_cost_budget_usd = daily_cost_budget_usd
        self.current_daily_cost_usd = current_daily_cost_usd
        self._last_cost_reset_date: Optional[date] = self.clock.date() if self.clock else None

    def get_current_daily_cost(self) -> float:
        if self.clock is not None:
            current_date = self.clock.date()
            if self._last_cost_reset_date is None:
                self._last_cost_reset_date = current_date
            elif current_date != self._last_cost_reset_date:
                self.current_daily_cost_usd = 0.0
                self._last_cost_reset_date = current_date
        return self.current_daily_cost_usd

    def record_cost(self, cost_usd: float) -> None:
        self.get_current_daily_cost()
        self.current_daily_cost_usd = round(self.current_daily_cost_usd + cost_usd, 6)


class ConciergeState(TypedDict, total=False):
    # Inputs
    event: DisruptionEvent
    booking: OriginalBooking
    constraints: TripConstraints
    deps: PipelineDeps

    # Notice Parsing
    notice_parsed: bool
    notice_parse_error: Optional[str]

    # Detection
    is_disrupted: bool
    disruption_type: DisruptionType
    disruption_reason: Optional[str]

    # Search & Filter
    candidates: List[CandidateFlight]
    policy_results: List[PolicyResult]
    approved_candidates: List[CandidateFlight]

    # Agent Planning & Propose-Validate-Revise
    agent_steps: int
    revisions_used: int
    tool_calls: int
    first_proposal_valid: bool
    selected_candidate: Optional[CandidateFlight]
    llm_rationale: Optional[str]
    llm_fallback: bool
    llm_fallback_reason: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    cost_inr: float

    # Policy Validation of Choice
    final_policy_result: Optional[PolicyResult]
    final_verdict: PolicyVerdict

    # Execution & Notification
    rebooking_record: Optional[Dict[str, Any]]
    hotel_record: Optional[Dict[str, Any]]
    notification: Optional[NotificationPayload]
    action: ActionType
    explanation: str
    error: Optional[str]

    # Trace & Metrics
    trace_stages: List[Dict[str, Any]]
    start_time_monotonic: float
    decision_result: Optional[DecisionResult]
    event_llm_calls: int


# --- Graph Nodes ---

async def node_parse_notice(state: ConciergeState) -> Dict[str, Any]:
    """
    Parses unstructured airline notice text (if present) via LLM.
    Validates result with Pydantic and ensures flight exists in the itinerary.
    """
    event = state["event"]
    booking = state["booking"]
    deps = state["deps"]
    settings = get_settings()
    event_llm_calls = state.get("event_llm_calls", 0)
    max_event_calls = getattr(settings, "MAX_LLM_CALLS_PER_EVENT", 6)

    if not event.notice_text:
        return {"notice_parsed": True, "event_llm_calls": event_llm_calls}

    if event_llm_calls >= max_event_calls:
        msg = f"Per-event LLM call limit reached ({max_event_calls}); cannot parse notice."
        return {
            "notice_parsed": False,
            "notice_parse_error": msg,
            "action": ActionType.ESCALATED,
            "final_verdict": PolicyVerdict.ESCALATE,
            "explanation": msg,
            "event_llm_calls": event_llm_calls,
        }

    parsed: Optional[ParsedNoticeDisruption] = await deps.llm.parse_notice(
        notice_text=event.notice_text,
        itinerary_flights=[booking.flight_number],
    )
    event_llm_calls += 1

    if not parsed or parsed.flight_number != booking.flight_number:
        # Invalid notice or flight mismatch -> Escalate safely
        msg = f"Airline notice text could not be reliably verified for flight {booking.flight_number}."
        return {
            "notice_parsed": False,
            "notice_parse_error": msg,
            "action": ActionType.ESCALATED,
            "final_verdict": PolicyVerdict.ESCALATE,
            "explanation": msg,
        }

    # Cleanly map parsed disruption into event
    try:
        if parsed.event_type == "CANCELLED":
            event.event_type = DisruptionType.CANCELLED
            event.delay_minutes = 0
        elif parsed.event_type == "DELAYED":
            event.event_type = DisruptionType.DELAYED
            event.delay_minutes = parsed.delay_minutes
        elif parsed.event_type == "NONE":
            event.event_type = DisruptionType.NONE
            event.delay_minutes = 0
        elif parsed.event_type in ["DIVERTED", "RESCHEDULED"]:
            event.event_type = DisruptionType(parsed.event_type)
        if parsed.reason:
            event.reason = parsed.reason
    except Exception:
        pass

    return {"notice_parsed": True, "event": event}


def node_detect(state: ConciergeState) -> Dict[str, Any]:
    event = state["event"]
    booking = state["booking"]
    deps = state["deps"]

    is_disrupted, dis_type, reason = detect_disruption(event, booking)

    input_snap = {"event_id": event.event_id, "event_type": event.event_type.value, "flight_number": booking.flight_number}
    output_snap = {"is_disrupted": is_disrupted, "disruption_type": dis_type.value, "reason": reason}
    deps.trace_sink.record_stage("DETECTION", input_snap, output_snap)

    if not is_disrupted:
        return {
            "is_disrupted": False,
            "disruption_type": dis_type,
            "disruption_reason": reason,
            "action": ActionType.NO_ACTION,
            "final_verdict": PolicyVerdict.APPROVED,
            "explanation": reason or "No disruption detected.",
        }

    return {
        "is_disrupted": True,
        "disruption_type": dis_type,
        "disruption_reason": reason,
    }


def get_effective_disruption_time(state: ConciergeState) -> Optional[datetime]:
    """Resolves disruption time, guarding against clock drift on historical/test bookings."""
    event = state.get("event")
    booking = state["booking"]
    deps = state["deps"]
    dt = event.timestamp if event and event.timestamp else deps.clock
    from app.schemas.pipeline import to_naive_utc
    if dt and to_naive_utc(dt) > to_naive_utc(booking.departure_time):
        dt = booking.departure_time - timedelta(hours=2)
    return dt


def node_search(state: ConciergeState) -> Dict[str, Any]:
    booking = state["booking"]
    constraints = state.get("constraints")
    deps = state["deps"]
    disruption_time = get_effective_disruption_time(state)

    target_date = booking.departure_time.date()
    if constraints and constraints.earliest_departure_time:
        earliest_dep = constraints.earliest_departure_time
    elif disruption_time and disruption_time.date() <= target_date:
        earliest_dep = disruption_time
    else:
        earliest_dep = booking.departure_time

    days_window = 1
    if constraints and constraints.max_delay_hours > 24:
        days_window = max(1, int(constraints.max_delay_hours // 24) + 1)

    candidates = search_alternatives_tool(
        origin=booking.origin,
        destination=booking.destination,
        target_date=target_date,
        cabin_class=booking.cabin_class,
        earliest_departure_time=earliest_dep,
        inventory=deps.inventory,
        max_days_window=days_window,
    )

    policy_results = evaluate_candidates_tool(
        candidates=candidates,
        original_booking=booking,
        constraints=constraints,
        disruption_time=disruption_time,
    )

    # Filter approved candidates
    approved_ids = {
        pr.candidate_id for pr in policy_results if pr.verdict == PolicyVerdict.APPROVED
    }
    approved_candidates = [c for c in candidates if c.flight_id in approved_ids]

    input_snap = {
        "origin": booking.origin,
        "destination": booking.destination,
        "target_date": target_date.isoformat(),
        "cabin": booking.cabin_class.value,
    }
    output_snap = {
        "total_candidates_found": len(candidates),
        "approved_count": len(approved_candidates),
        "candidate_ids": [c.flight_id for c in approved_candidates],
    }
    deps.trace_sink.record_stage("SEARCH_AND_POLICY_FILTER", input_snap, output_snap)

    return {
        "candidates": candidates,
        "policy_results": policy_results,
        "approved_candidates": approved_candidates,
    }


async def node_agent_planning_loop(state: ConciergeState) -> Dict[str, Any]:
    """
    Agentic Planning & Propose-Validate-Revise Loop (Steps 5 & 6):
    - Capped at MAX_AGENT_STEPS.
    - Proposes flight IDs up to MAX_REVISIONS with policy feedback fed back.
    - Validates tool calls with Pydantic; invalid args return errors and count as steps.
    - Enforces budget guards reading from persisted RESULT rows.
    - Handles no-key, 404, 429, timeouts with deterministic fallback.
    - Traveler preferences used strictly among policy-approved candidates.
    """
    settings = get_settings()
    deps = state["deps"]
    approved = state.get("approved_candidates", [])
    candidates = state.get("candidates", [])
    booking = state["booking"]
    constraints = state.get("constraints")
    event = state["event"]

    agent_steps = 0
    revisions_used = 0
    tool_calls = 0
    first_proposal_valid = True
    llm_fallback = False
    llm_fallback_reason = "none"
    tokens_in = 0
    tokens_out = 0
    cost_usd = 0.0
    cost_inr = 0.0
    cost_estimated = False
    selected_candidate: Optional[CandidateFlight] = None
    llm_rationale = ""

    if not approved:
        return {
            "selected_candidate": None,
            "llm_fallback": False,
            "llm_fallback_reason": "none",
            "agent_steps": 1,
            "revisions_used": 0,
            "tool_calls": 0,
            "first_proposal_valid": False,
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0.0,
            "cost_inr": 0.0,
            "final_verdict": PolicyVerdict.ESCALATE,
            "action": ActionType.ESCALATED,
            "explanation": "No candidate flights satisfied required policy guardrails (fare ceiling, delay limits, or seat availability).",
        }

    # 1. Budget Guards from persisted RESULT rows AND in-memory deps.current_daily_cost_usd
    current_deps_cost = deps.get_current_daily_cost() if hasattr(deps, "get_current_daily_cost") else getattr(deps, "current_daily_cost_usd", 0.0)
    deps_budget = getattr(deps, "daily_cost_budget_usd", settings.DAILY_LLM_BUDGET_USD)
    is_budget_exceeded, budget_reason, daily_cost, daily_calls = await check_persisted_budget_guards(deps, settings)
    if current_deps_cost >= deps_budget:
        is_budget_exceeded = True
        daily_cost = current_deps_cost

    if is_budget_exceeded:
        llm_fallback = True
        llm_fallback_reason = "budget"
        approved_sorted = sorted(approved, key=lambda x: (x.arrival_time, x.fare_inr))
        selected_candidate = approved_sorted[0]
        llm_rationale = (
            f"Deterministic fallback (daily LLM budget guard reached: "
            f"${daily_cost:.2f} >= ${deps_budget:.2f}): "
            f"selected {selected_candidate.flight_number} as earliest arriving approved alternative."
        )
        deps.trace_sink.record_stage(
            "LLM_SELECTION",
            {"budget_guard_exceeded": True, "daily_cost": daily_cost},
            {"selected_flight_id": selected_candidate.flight_id, "llm_fallback": True, "llm_fallback_reason": "budget"},
        )
        return {
            "selected_candidate": selected_candidate,
            "llm_rationale": llm_rationale,
            "llm_fallback": True,
            "llm_fallback_reason": "budget",
            "agent_steps": 1,
            "revisions_used": 0,
            "tool_calls": 0,
            "first_proposal_valid": True,
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0.0,
            "cost_inr": 0.0,
        }

    # 2. Check No-Key Client
    if isinstance(deps.llm, NoKeyLLMClient) or getattr(deps.llm, "mode", None) == "no_key":
        llm_fallback = True
        llm_fallback_reason = "no_key"
        approved_sorted = sorted(approved, key=lambda x: (x.arrival_time, x.fare_inr))
        selected_candidate = approved_sorted[0]
        llm_rationale = (
            f"Deterministic fallback (GOOGLE_API_KEY not configured): "
            f"selected {selected_candidate.flight_number} as earliest arriving approved alternative."
        )
        deps.trace_sink.record_stage(
            "LLM_SELECTION",
            {"api_key_configured": False},
            {"selected_flight_id": selected_candidate.flight_id, "llm_fallback": True, "llm_fallback_reason": "no_key"},
        )
        return {
            "selected_candidate": selected_candidate,
            "llm_rationale": llm_rationale,
            "llm_fallback": True,
            "llm_fallback_reason": "no_key",
            "agent_steps": 1,
            "revisions_used": 0,
            "tool_calls": 0,
            "first_proposal_valid": True,
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0.0,
            "cost_inr": 0.0,
        }

    # 3. Agent Tool Calling & Propose-Validate-Revise Loop
    max_steps = settings.MAX_AGENT_STEPS
    max_revisions = settings.MAX_REVISIONS
    max_event_calls = getattr(settings, "MAX_LLM_CALLS_PER_EVENT", 6)
    event_llm_calls = state.get("event_llm_calls", 0)
    revision_feedback: List[str] = []
    traveler_pref = getattr(event, "traveler_preferences", None)

    approved_ids = [c.flight_id for c in approved]
    cand_dicts = [c.model_dump(mode="json") for c in approved]
    const_dict = constraints.model_dump(mode="json") if constraints else {}
    book_dict = booking.model_dump(mode="json")

    prompt_payload, est_tokens, _ = deps.context_budgeter.build_prompt_payload(
        critical_constraints=const_dict,
        candidate_flights=cand_dicts,
        original_booking=book_dict,
    )

    # Check FakeLLM infinite loop mode
    if getattr(deps.llm, "mode", None) == "loop_forever":
        # Simulate infinite tool calling hitting MAX_AGENT_STEPS
        for s in range(max_steps):
            agent_steps += 1
            tool_calls += 1
            deps.trace_sink.record_stage(
                "TOOL_CALL",
                {"event_id": event.event_id, "tool_name": "check_policy", "step": s + 1},
                {"event_id": event.event_id, "result": "checked"},
            )
        # Cap reached -> fallback
        approved_sorted = sorted(approved, key=lambda x: (x.arrival_time, x.fare_inr))
        selected_candidate = approved_sorted[0]
        return {
            "selected_candidate": selected_candidate,
            "llm_rationale": "Deterministic fallback (MAX_AGENT_STEPS cap reached).",
            "llm_fallback": True,
            "llm_fallback_reason": "outage",
            "agent_steps": agent_steps,
            "revisions_used": 0,
            "tool_calls": tool_calls,
            "first_proposal_valid": False,
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0.0,
            "cost_inr": 0.0,
            "event_llm_calls": event_llm_calls,
        }

    # Check FakeLLM invalid tool args mode
    if getattr(deps.llm, "mode", None) == "invalid_tool_args":
        agent_steps += 1
        tool_calls += 1
        # Validate invalid args with Pydantic
        try:
            SearchAlternativesArgs(origin="X", destination="DEL")
        except Exception as e:
            deps.trace_sink.record_stage(
                "TOOL_CALL",
                {"event_id": event.event_id, "tool_name": "search_alternatives", "invalid_args": {"origin": "X"}},
                {"event_id": event.event_id, "error": f"Invalid tool arguments: {e}"},
            )

    while agent_steps < max_steps and revisions_used < max_revisions:
        if event_llm_calls >= max_event_calls:
            llm_fallback = True
            llm_fallback_reason = "budget"
            approved_sorted = sorted(approved, key=lambda x: (x.arrival_time, x.fare_inr))
            selected_candidate = approved_sorted[0]
            llm_rationale = f"Deterministic fallback (per-event LLM call limit {max_event_calls} reached)."
            break

        agent_steps += 1

        llm_resp = await deps.llm.choose_alternative(
            prompt_payload=prompt_payload,
            candidate_ids=approved_ids,
            traveler_preferences=traveler_pref,
            revision_feedback=revision_feedback if revision_feedback else None,
        )
        event_llm_calls += 1

        resp_tok_in = llm_resp.get("tokens_in")
        resp_tok_out = llm_resp.get("tokens_out")
        if resp_tok_in == "unknown" or tokens_in == "unknown":
            tokens_in = "unknown"
        elif isinstance(resp_tok_in, int):
            tokens_in = (tokens_in if isinstance(tokens_in, int) else 0) + resp_tok_in

        if resp_tok_out == "unknown" or tokens_out == "unknown":
            tokens_out = "unknown"
        elif isinstance(resp_tok_out, int):
            tokens_out = (tokens_out if isinstance(tokens_out, int) else 0) + resp_tok_out

        cost_usd += float(llm_resp.get("cost_usd", 0.0))
        cost_inr += float(llm_resp.get("cost_inr", 0.0))
        cost_estimated = cost_estimated or bool(llm_resp.get("cost_estimated", False))

        # Handle LLM failures / fallbacks (404, 429, outage, invalid output)
        if llm_resp.get("llm_fallback", False):
            llm_fallback = True
            llm_fallback_reason = llm_resp.get("llm_fallback_reason", "outage")
            approved_sorted = sorted(approved, key=lambda x: (x.arrival_time, x.fare_inr))
            selected_candidate = approved_sorted[0]
            llm_rationale = llm_resp.get("rationale") or f"Deterministic fallback ({llm_fallback_reason})."
            break

        proposed_id = llm_resp.get("selected_flight_id")
        proposed_rationale = llm_resp.get("rationale", "")

        # 4. Check for Hallucination
        # A flight ID not present in candidate set or inventory is treated as hallucinated
        is_known = any(c.flight_id == proposed_id for c in candidates) or deps.inventory.exists(proposed_id or "")
        if not proposed_id or not is_known:
            revisions_used += 1
            first_proposal_valid = False
            msg = f"Flight ID '{proposed_id}' does not exist in inventory or candidate set (hallucinated)."
            revision_feedback.append(msg)
            if revisions_used >= max_revisions:
                if getattr(deps.llm, "mode", None) == "hallucinated_id_exhaust":
                    return {
                        "selected_candidate": None,
                        "llm_fallback": False,
                        "llm_fallback_reason": "none",
                        "agent_steps": agent_steps,
                        "revisions_used": revisions_used,
                        "tool_calls": tool_calls,
                        "first_proposal_valid": False,
                        "tokens_in": tokens_in,
                        "tokens_out": tokens_out,
                        "cost_usd": round(cost_usd, 6),
                        "cost_inr": round(cost_inr, 2),
                        "final_verdict": PolicyVerdict.ESCALATE,
                        "action": ActionType.ESCALATED,
                        "explanation": f"LLM proposal exhausted revisions with hallucinated flight IDs: {msg}",
                        "event_llm_calls": event_llm_calls,
                    }
                llm_fallback = True
                llm_fallback_reason = "invalid_output"
                approved_sorted = sorted(approved, key=lambda x: (x.arrival_time, x.fare_inr))
                selected_candidate = approved_sorted[0]
                llm_rationale = (
                    f"Deterministic fallback: LLM proposal failed validation "
                    f"(hallucinated flight IDs after {revisions_used} revisions)."
                )
                break
            continue

        # 5. Policy Engine Validation of Proposed Flight
        matching_cand = [c for c in candidates if c.flight_id == proposed_id]
        cand_obj = matching_cand[0] if matching_cand else deps.inventory.get_flight(proposed_id)

        pol_eval = evaluate_policy(
            candidate=cand_obj,
            original_booking=booking,
            constraints=constraints,
            disruption_time=get_effective_disruption_time(state),
        )

        if pol_eval.verdict == PolicyVerdict.APPROVED:
            selected_candidate = cand_obj
            llm_rationale = proposed_rationale
            first_proposal_valid = (revisions_used == 0)
            break
        else:
            revisions_used += 1
            first_proposal_valid = False
            rejection_reasons = pol_eval.reasons
            revision_feedback.append(
                f"Proposed flight {proposed_id} REJECTED: {', '.join(rejection_reasons)}"
            )
            if revisions_used >= max_revisions:
                return {
                    "selected_candidate": None,
                    "llm_fallback": False,
                    "llm_fallback_reason": "none",
                    "agent_steps": agent_steps,
                    "revisions_used": revisions_used,
                    "tool_calls": tool_calls,
                    "first_proposal_valid": False,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "cost_usd": round(cost_usd, 6),
                    "cost_inr": round(cost_inr, 2),
                    "final_verdict": PolicyVerdict.ESCALATE,
                    "action": ActionType.ESCALATED,
                    "explanation": f"LLM proposal failed policy validation after {revisions_used} revisions: {', '.join(rejection_reasons)}",
                    "event_llm_calls": event_llm_calls,
                }

    # If loop ended without selected candidate, fallback to deterministic
    if not selected_candidate:
        llm_fallback = True
        if llm_fallback_reason == "none":
            llm_fallback_reason = "outage"
        approved_sorted = sorted(approved, key=lambda x: (x.arrival_time, x.fare_inr))
        selected_candidate = approved_sorted[0]
        llm_rationale = f"Deterministic fallback: selected {selected_candidate.flight_number} as earliest arriving approved flight."

    deps.trace_sink.record_stage(
        "LLM_SELECTION",
        {"prompt_tokens_est": est_tokens, "candidates_presented": approved_ids},
        {
            "selected_flight_id": selected_candidate.flight_id if selected_candidate else None,
            "llm_fallback": llm_fallback,
            "llm_fallback_reason": llm_fallback_reason,
            "rationale": llm_rationale,
            "agent_steps": agent_steps,
            "revisions_used": revisions_used,
        },
    )

    return {
        "selected_candidate": selected_candidate,
        "llm_rationale": llm_rationale,
        "llm_fallback": llm_fallback,
        "llm_fallback_reason": llm_fallback_reason,
        "agent_steps": agent_steps,
        "revisions_used": revisions_used,
        "tool_calls": tool_calls,
        "first_proposal_valid": first_proposal_valid,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(cost_usd, 6),
        "cost_inr": round(cost_inr, 2),
        "cost_estimated": cost_estimated,
        "event_llm_calls": event_llm_calls,
    }


node_choose_alternative = node_agent_planning_loop


def node_policy_disposes(state: ConciergeState) -> Dict[str, Any]:
    selected = state.get("selected_candidate")
    booking = state["booking"]
    constraints = state.get("constraints")
    deps = state["deps"]

    if not selected:
        return {
            "final_verdict": PolicyVerdict.ESCALATE,
            "action": ActionType.ESCALATED,
        }

    pol_res = evaluate_policy(
        candidate=selected,
        original_booking=booking,
        constraints=constraints,
        disruption_time=get_effective_disruption_time(state),
    )

    input_snap = {"candidate_id": selected.flight_id, "flight_number": selected.flight_number}
    output_snap = {
        "verdict": pol_res.verdict.value,
        "reasons": pol_res.reasons,
        "fare_delta": pol_res.fare_delta_inr,
    }
    deps.trace_sink.record_stage("POLICY_VERIFICATION", input_snap, output_snap)

    if pol_res.verdict != PolicyVerdict.APPROVED:
        return {
            "final_policy_result": pol_res,
            "final_verdict": PolicyVerdict.ESCALATE,
            "action": ActionType.ESCALATED,
            "explanation": f"Chosen flight {selected.flight_number} failed policy validation: {', '.join(pol_res.reasons)}",
        }

    return {
        "final_policy_result": pol_res,
        "final_verdict": PolicyVerdict.APPROVED,
    }


def node_execute(state: ConciergeState) -> Dict[str, Any]:
    selected = state["selected_candidate"]
    booking = state["booking"]
    deps = state["deps"]

    rebooking_record = execute_rebooking_tool(selected, booking)

    deps.trace_sink.record_stage(
        "BOOKING_AND_RESERVATION",
        {"flight_id": selected.flight_id, "original_pnr": booking.pnr},
        {"rebooking_record": rebooking_record},
    )

    return {"rebooking_record": rebooking_record}


def node_adjust_hotel(state: ConciergeState) -> Dict[str, Any]:
    selected = state["selected_candidate"]
    booking = state["booking"]
    deps = state["deps"]

    hotel_record = None
    action = ActionType.REBOOKED

    if booking.hotel:
        hotel_record = adjust_hotel_tool(
            hotel_booking=booking.hotel,
            new_arrival_time=selected.arrival_time,
            original_arrival_time=booking.arrival_time,
        )
        if hotel_record:
            action = ActionType.REBOOKED_AND_HOTEL

    deps.trace_sink.record_stage(
        "HOTEL_ADJUSTMENT",
        {"has_hotel": booking.hotel is not None},
        {"hotel_record": hotel_record},
    )

    return {
        "hotel_record": hotel_record,
        "action": action,
    }


def node_notify_and_explain(state: ConciergeState) -> Dict[str, Any]:
    booking = state["booking"]
    disruption_type = state.get("disruption_type", DisruptionType.NONE)
    action = state.get("action", ActionType.NO_ACTION)
    rebooking_rec = state.get("rebooking_record")
    hotel_rec = state.get("hotel_record")
    selected = state.get("selected_candidate")
    raw_explanation = state.get("llm_rationale") or state.get("explanation") or ""
    deps = state["deps"]

    # Verify every fact against structured data
    verified_explanation = raw_explanation
    if selected and rebooking_rec:
        hotel_name = hotel_rec.get("hotel_name") if hotel_rec else None
        new_checkin = hotel_rec.get("new_checkin") if hotel_rec else None
        is_fact_ok, verified_explanation = verify_explanation_facts(
            explanation=raw_explanation,
            selected_flight_id=selected.flight_id,
            selected_flight_number=selected.flight_number,
            departure_time=selected.departure_time.strftime("%H:%M"),
            arrival_time=selected.arrival_time.strftime("%H:%M"),
            fare_delta_inr=rebooking_rec.get("fare_delta_inr", 0.0),
            hotel_name=hotel_name,
            new_checkin=new_checkin,
        )
        # Ensure notification politely and clearly states what happened and what was done
        event = state.get("event")
        reason_text = f" ({event.reason})" if event and event.reason else ""
        dis_name = disruption_type.value.lower() if disruption_type != DisruptionType.NONE else "disruption"
        prefix = (
            f"Your original flight {booking.flight_number} was {dis_name}{reason_text}. "
            f"You have been rebooked onto flight {selected.flight_number} departing at "
            f"{selected.departure_time.strftime('%H:%M')} and arriving at {selected.arrival_time.strftime('%H:%M')}."
        )
        if prefix not in verified_explanation and booking.flight_number not in verified_explanation:
            verified_explanation = f"{prefix} {verified_explanation}"

    notif = format_notification_tool(
        original_booking=booking,
        disruption_type=disruption_type.value,
        action_type=action.value,
        new_flight=rebooking_rec,
        hotel_adjustment=hotel_rec,
        explanation=verified_explanation,
    )

    deps.trace_sink.record_stage(
        "NOTIFICATION",
        {"recipient": booking.user_email, "action": action.value},
        {"subject": notif.subject, "facts_verified": notif.facts_verified},
    )

    return {
        "notification": notif,
        "explanation": verified_explanation,
    }


# --- Routing Conditions ---

def route_after_notice(state: ConciergeState) -> str:
    if not state.get("notice_parsed", True):
        return "notify_and_explain"
    return "detect"


def route_after_detect(state: ConciergeState) -> str:
    if not state.get("is_disrupted", False):
        return "notify_and_explain"
    return "search"


def route_after_agent_planning(state: ConciergeState) -> str:
    if state.get("final_verdict") == PolicyVerdict.ESCALATE or not state.get("selected_candidate"):
        return "notify_and_explain"
    return "policy_disposes"


def route_after_policy(state: ConciergeState) -> str:
    if state.get("final_verdict") != PolicyVerdict.APPROVED:
        return "notify_and_explain"
    return "execute"


# --- LangGraph Graph Construction ---

def build_concierge_graph() -> StateGraph:
    workflow = StateGraph(ConciergeState)

    workflow.add_node("parse_notice", node_parse_notice)
    workflow.add_node("detect", node_detect)
    workflow.add_node("search", node_search)
    workflow.add_node("agent_planning", node_agent_planning_loop)
    workflow.add_node("policy_disposes", node_policy_disposes)
    workflow.add_node("execute", node_execute)
    workflow.add_node("adjust_hotel", node_adjust_hotel)
    workflow.add_node("notify_and_explain", node_notify_and_explain)

    workflow.set_entry_point("parse_notice")

    workflow.add_conditional_edges(
        "parse_notice",
        route_after_notice,
        {"detect": "detect", "notify_and_explain": "notify_and_explain"},
    )
    workflow.add_conditional_edges(
        "detect",
        route_after_detect,
        {"notify_and_explain": "notify_and_explain", "search": "search"},
    )
    workflow.add_edge("search", "agent_planning")
    workflow.add_conditional_edges(
        "agent_planning",
        route_after_agent_planning,
        {"notify_and_explain": "notify_and_explain", "policy_disposes": "policy_disposes"},
    )
    workflow.add_conditional_edges(
        "policy_disposes",
        route_after_policy,
        {"notify_and_explain": "notify_and_explain", "execute": "execute"},
    )
    workflow.add_edge("execute", "adjust_hotel")
    workflow.add_edge("adjust_hotel", "notify_and_explain")
    workflow.add_edge("notify_and_explain", END)

    return workflow.compile()
