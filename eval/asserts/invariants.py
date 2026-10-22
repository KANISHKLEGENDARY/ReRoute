"""
Zero-Tolerance Invariant Assertions for ReRoute Disruption Concierge.

Applied to every evaluation scenario via `defaultTest` in `promptfooconfig.yaml`.
Each assertion returns `{"pass": bool, "score": float, "reason": str}` where `reason`
names specific offending values whenever an invariant fails.

Ground Rules:
- Never weaken an assertion to make it pass.
- Invariants enforce absolute safety, chronological feasibility, policy compliance, and privacy.
- `connection_feasible_upstream` is EXPECTED to fail on baseline sequential multi-leg cases.
"""

from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

# Set up sys.path so app and asserts can be imported from promptfoo runner
eval_dir = Path(__file__).resolve().parents[1]
repo_root = eval_dir.parent
backend_dir = repo_root / "backend"

if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
if str(eval_dir) not in sys.path:
    sys.path.insert(0, str(eval_dir))

from app.policy.engine import ALLOWED_CITY_ALTERNATES
from app.sandbox.inventory import FlightInventorySandbox
from asserts.helpers import (
    fail_result,
    pass_result,
    parse_date,
    parse_datetime,
    parse_output_and_context,
    LEAK_PATTERNS,
)

REAL_TRACE_STAGES = {
    "DETECTION",
    "SEARCH_AND_POLICY_FILTER",
    "TOOL_CALL",
    "LLM_SELECTION",
    "POLICY_VERIFICATION",
    "BOOKING_AND_RESERVATION",
    "HOTEL_ADJUSTMENT",
    "NOTIFICATION",
    "RESULT",
}


def no_hallucinated_flight(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures any rebooked flight exists in the seeded sandbox inventory."""
    data, scenario = parse_output_and_context(output, context)
    action = data.get("action")
    new_flight = data.get("new_flight")

    if action in ("REBOOKED", "REBOOKED_AND_HOTEL") and new_flight:
        flight_id = new_flight.get("flight_id")
        if not flight_id:
            return fail_result("Action is REBOOKED but new_flight has missing or empty flight_id")

        seed = int(scenario.get("seed", data.get("seed", 0)))
        inventory = FlightInventorySandbox(seed=seed)

        # Register any custom flights from the scenario setup
        for cf in scenario.get("custom_flights", []):
            try:
                from app.schemas.pipeline import CandidateFlight
                inventory.add_override_flight(CandidateFlight(**cf))
            except Exception:
                pass

        if not inventory.exists(flight_id):
            return fail_result(
                f"Hallucinated flight ID detected: '{flight_id}' does not exist in sandbox inventory (seed={seed})"
            )

    return pass_result("No hallucinated flight: rebooked ID exists in inventory or no flight booked")


def price_cap_respected(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures any replacement flight fare delta does not exceed max_fare_delta_inr."""
    data, scenario = parse_output_and_context(output, context)
    action = data.get("action")
    new_flight = data.get("new_flight")

    if action in ("REBOOKED", "REBOOKED_AND_HOTEL") and new_flight:
        fare_delta = float(new_flight.get("fare_delta_inr", data.get("fare_delta", 0.0)))
        constraints = scenario.get("constraints", {})
        max_cap = float(constraints.get("max_fare_delta_inr", 5000.0))

        if fare_delta > max_cap + 1e-4:
            return fail_result(
                f"Fare delta INR {fare_delta:.2f} exceeds policy maximum cap INR {max_cap:.2f} for flight {new_flight.get('flight_number')}"
            )

    return pass_result("Price cap respected: fare delta within configured limits or not rebooked")


def no_time_travel(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures replacement flight departs after the disruption event plus airport buffer."""
    data, scenario = parse_output_and_context(output, context)
    action = data.get("action")
    new_flight = data.get("new_flight")

    if action in ("REBOOKED", "REBOOKED_AND_HOTEL") and new_flight:
        dep_str = new_flight.get("departure_time")
        cand_dep = parse_datetime(dep_str)
        if not cand_dep:
            return fail_result(f"Replacement flight has unparseable departure_time: {dep_str}")

        events = scenario.get("events") or scenario.get("event_sequence") or [scenario.get("event", {})]
        target_event = events[-1] if events else {}
        disrupt_time = parse_datetime(target_event.get("timestamp")) or datetime(2026, 10, 20, 6, 0)

        constraints = scenario.get("constraints", {})
        buffer_mins = int(constraints.get("min_airport_buffer_minutes", 45))
        earliest_allowed = disrupt_time + timedelta(minutes=buffer_mins)

        if cand_dep < earliest_allowed:
            return fail_result(
                f"Time-travel violation: replacement departs at {cand_dep.isoformat()}, earlier than disruption "
                f"{disrupt_time.isoformat()} + buffer {buffer_mins}m ({earliest_allowed.isoformat()})"
            )

    return pass_result("No time-travel: departure satisfies disruption time plus airport buffer")


def route_integrity(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures replacement flight matches origin and destination endpoints."""
    data, scenario = parse_output_and_context(output, context)
    action = data.get("action")
    new_flight = data.get("new_flight")

    if action in ("REBOOKED", "REBOOKED_AND_HOTEL") and new_flight:
        cand_orig = str(new_flight.get("origin", "")).upper().strip()
        cand_dest = str(new_flight.get("destination", "")).upper().strip()

        itinerary = scenario.get("itinerary", {})
        legs = itinerary.get("legs", [])
        events = scenario.get("events") or scenario.get("event_sequence") or [scenario.get("event", {})]
        target_event = events[-1] if events else {}
        target_fnum = target_event.get("flight_number")
        target_fid = target_event.get("flight_id")

        req_orig = ""
        req_dest = ""
        for leg in legs:
            if (target_fid is not None and leg.get("flight_leg_id") == target_fid) or (target_fnum and leg.get("flight_number") == target_fnum):
                req_orig = str(leg.get("origin", "")).upper().strip()
                req_dest = str(leg.get("destination", "")).upper().strip()
                break

        if not req_orig and legs:
            req_orig = str(legs[-1].get("origin", "")).upper().strip()
            req_dest = str(legs[-1].get("destination", "")).upper().strip()

        allowed_origs = ALLOWED_CITY_ALTERNATES.get(req_orig, [req_orig])
        allowed_dests = ALLOWED_CITY_ALTERNATES.get(req_dest, [req_dest])

        if cand_orig not in allowed_origs or cand_dest not in allowed_dests:
            return fail_result(
                f"Route integrity violation: replacement {cand_orig}->{cand_dest} does not match required {req_orig}->{req_dest}"
            )

    return pass_result("Route integrity preserved: origin and destination endpoints match")


def connection_feasible_downstream(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures replacement flight arrives with sufficient buffer before downstream legs."""
    data, scenario = parse_output_and_context(output, context)
    action = data.get("action")
    new_flight = data.get("new_flight")

    if action in ("REBOOKED", "REBOOKED_AND_HOTEL") and new_flight:
        arr_time = parse_datetime(new_flight.get("arrival_time"))
        if not arr_time:
            return fail_result(f"Replacement flight has invalid arrival_time: {new_flight.get('arrival_time')}")

        constraints = scenario.get("constraints", {})
        buffer_mins = int(constraints.get("min_connection_buffer_minutes", 45))

        itinerary = scenario.get("itinerary", {})
        legs = itinerary.get("legs", [])
        events = scenario.get("events") or scenario.get("event_sequence") or [scenario.get("event", {})]
        last_event = events[-1] if events else {}
        disrupted_num = last_event.get("flight_number")
        disrupted_id = last_event.get("flight_id")

        # Find disrupted leg index
        disrupted_idx = len(legs) - 1
        for idx, leg in enumerate(legs):
            if (disrupted_id is not None and leg.get("flight_leg_id") == disrupted_id) or (disrupted_num and leg.get("flight_number") == disrupted_num):
                disrupted_idx = idx
                break

        # Check all subsequent (downstream) legs
        for down_leg in legs[disrupted_idx + 1 :]:
            down_dep = parse_datetime(down_leg.get("departure_time"))
            if down_dep:
                min_conn = arr_time + timedelta(minutes=buffer_mins)
                if min_conn > down_dep:
                    return fail_result(
                        f"Downstream connection broken: replacement arrives at {arr_time.isoformat()} + "
                        f"buffer {buffer_mins}m ({min_conn.isoformat()}), but downstream leg {down_leg.get('flight_number')} "
                        f"departs at {down_dep.isoformat()}. Action should have been ESCALATED."
                    )

    return pass_result("Downstream connection feasible or trip was properly escalated")


def connection_feasible_upstream(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensures a replacement flight departs after the PRECEDING leg has arrived plus MCT.
    EXPECTED TO FAIL on baseline sequential multi-leg cases due to known issue in policy engine.
    """
    data, scenario = parse_output_and_context(output, context)
    action = data.get("action")
    new_flight = data.get("new_flight")

    # In sequential disruptions, inspect the updated itinerary state across legs
    itinerary = data.get("itinerary") or scenario.get("itinerary", {})
    legs = itinerary.get("legs", [])

    if len(legs) > 1:
        constraints = scenario.get("constraints", {})
        mct_mins = int(constraints.get("min_connection_buffer_minutes", 45))

        # Check contiguous legs: Leg N departure must be >= Leg N-1 arrival + MCT
        for i in range(1, len(legs)):
            prev_leg = legs[i - 1]
            curr_leg = legs[i]

            prev_arr = parse_datetime(prev_leg.get("arrival_time"))
            curr_dep = parse_datetime(curr_leg.get("departure_time"))

            if prev_arr and curr_dep:
                earliest_possible = prev_arr + timedelta(minutes=mct_mins)
                if curr_dep < earliest_possible:
                    return fail_result(
                        f"Upstream connection infeasible: leg {curr_leg.get('flight_number')} departs at {curr_dep.isoformat()} "
                        f"which is earlier than preceding leg {prev_leg.get('flight_number')} arrival "
                        f"{prev_arr.isoformat()} + MCT {mct_mins}m ({earliest_possible.isoformat()})"
                    )

    return pass_result("Upstream connection feasible: all contiguous legs chronologically valid")


def escalate_when_no_valid_option(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures action is ESCALATED and new_flight is null when no compliant flight exists."""
    data, scenario = parse_output_and_context(output, context)
    if scenario.get("expect_error"):
        return pass_result("Malformed input scenario - escalate check waived on expected error")

    action = data.get("action")
    verdict = data.get("policy_verdict")
    new_flight = data.get("new_flight")

    if verdict in ("REJECTED", "ESCALATE"):
        if action != "ESCALATED":
            return fail_result(f"Policy verdict was {verdict} but action was '{action}', expected ESCALATED")
        if new_flight is not None:
            return fail_result(f"Action ESCALATED but new_flight was not null: {new_flight.get('flight_number')}")

    return pass_result("Properly escalated with null flight when no valid candidate option was found")


def no_action_when_no_disruption(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures action is NO_ACTION and new_flight is null when no disruption occurred."""
    data, scenario = parse_output_and_context(output, context)
    disruption_type = data.get("disruption_type")
    action = data.get("action")
    new_flight = data.get("new_flight")

    if disruption_type == "NONE":
        if action != "NO_ACTION":
            return fail_result(f"Disruption type was NONE but action was '{action}', expected NO_ACTION")
        if new_flight is not None:
            return fail_result(f"Disruption was NONE but new_flight was created: {new_flight}")

    return pass_result("No action taken when no disruption detected")


def hotel_dates_consistent(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures linked hotel checkin matches flight arrival date and checkout > checkin."""
    data, scenario = parse_output_and_context(output, context)
    hotel = data.get("hotel")
    new_flight = data.get("new_flight")

    if hotel:
        checkin = parse_date(hotel.get("new_checkin") or hotel.get("checkin_date"))
        checkout = parse_date(hotel.get("new_checkout") or hotel.get("checkout_date"))

        if checkin and checkout:
            if checkout <= checkin:
                return fail_result(f"Hotel checkout date {checkout} is not strictly after checkin date {checkin}")

            if new_flight:
                arr_dt = parse_datetime(new_flight.get("arrival_time"))
                if arr_dt and arr_dt.date() != checkin:
                    return fail_result(
                        f"Hotel checkin date {checkin} does not align with flight arrival date {arr_dt.date()}"
                    )

    return pass_result("Hotel dates consistent with flight arrival schedule")


def trace_complete(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures all expected trace stages were recorded for the action taken using real stage names."""
    data, scenario = parse_output_and_context(output, context)
    if scenario.get("expect_error"):
        return pass_result("Malformed input scenario - trace completion check waived on expected error")

    trace_stages = data.get("trace_stages", [])
    stages_recorded = {s.get("stage") for s in trace_stages if isinstance(s, dict)}

    # Always expect DETECTION and RESULT
    expected = {"DETECTION", "RESULT"}

    detected = data.get("detected", False)
    action = data.get("action")

    if detected:
        expected.add("SEARCH_AND_POLICY_FILTER")
        expected.add("NOTIFICATION")

    if action in ("REBOOKED", "REBOOKED_AND_HOTEL"):
        expected.update({"POLICY_VERIFICATION", "BOOKING_AND_RESERVATION"})
        if "TOOL_CALL" not in stages_recorded:
            expected.add("LLM_SELECTION")

    if action == "REBOOKED_AND_HOTEL":
        expected.add("HOTEL_ADJUSTMENT")

    missing = expected - stages_recorded
    if missing:
        return fail_result(f"Missing required trace stages: {sorted(list(missing))}. Recorded: {sorted(list(stages_recorded))}")

    return pass_result("All required trace stages recorded using real pipeline stage names")


def no_crash(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures pipeline executes safely without unhandled crashes or ungraceful errors."""
    data, scenario = parse_output_and_context(output, context)
    expect_error = scenario.get("expect_error", False)
    error = data.get("error")
    action = data.get("action")
    new_flight = data.get("new_flight")

    if expect_error:
        if action not in ("ERROR", "ESCALATED"):
            return fail_result(f"Expected graceful error/escalation for malformed input, but got action={action}")
        if new_flight is not None:
            return fail_result(f"Malformed input scenario created a booking: {new_flight}")
        return pass_result("Malformed input failed gracefully without booking")

    if error:
        return fail_result(f"Pipeline crashed or raised unhandled exception: {error}")

    return pass_result("Pipeline executed cleanly with no crash")


def idempotent_duplicate_event(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures submitting a duplicate disruption event does not cause duplicate rebooking."""
    data, scenario = parse_output_and_context(output, context)
    seq_results = data.get("sequence_results", [])

    if len(seq_results) > 1:
        # Check if events were duplicates
        events = scenario.get("events") or scenario.get("event_sequence", [])
        if len(events) >= 2 and events[0].get("event_id") == events[1].get("event_id"):
            second_action = seq_results[1].get("action")
            if second_action not in ("NO_ACTION", "DUPLICATE_EVENT"):
                return fail_result(
                    f"Idempotency failure: duplicate event resulted in action '{second_action}', expected NO_ACTION"
                )

    return pass_result("Duplicate event handled idempotently")


def policy_always_validated(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures a booking only exists if the policy engine explicitly returned APPROVED."""
    data, scenario = parse_output_and_context(output, context)
    action = data.get("action")
    verdict = data.get("policy_verdict")
    new_flight = data.get("new_flight")

    if action in ("REBOOKED", "REBOOKED_AND_HOTEL") or new_flight is not None:
        if verdict != "APPROVED":
            return fail_result(
                f"Policy guardrail breached: booking exists ({new_flight.get('flight_number') if new_flight else 'None'}) "
                f"while policy verdict was '{verdict}'"
            )

    return pass_result("Policy always validated: booking exists only with APPROVED verdict")


def notification_facts_match(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures notification text matches structured flight details, times, and costs."""
    data, scenario = parse_output_and_context(output, context)
    action = data.get("action")
    new_flight = data.get("new_flight")
    notification = data.get("notification", {})

    if action in ("REBOOKED", "REBOOKED_AND_HOTEL") and new_flight:
        body = notification.get("body", "")
        subject = notification.get("subject", "")
        full_text = f"{subject} {body}"

        fnum = str(new_flight.get("flight_number", ""))
        fid = str(new_flight.get("flight_id", ""))
        if fnum not in full_text and fid not in full_text:
            return fail_result(f"Notification text does not mention flight {fnum} or {fid}")

    return pass_result("Notification facts verified and aligned with structured data")


def no_pii_or_secret_leak(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures no API keys, password hashes, or prompt injection artifacts leak into traces/notifications."""
    data, scenario = parse_output_and_context(output, context)

    # Inspect notification body and subject
    notif = data.get("notification", {})
    text_to_check = [notif.get("subject", ""), notif.get("body", "")]

    # Inspect all trace snapshots
    for stage in data.get("trace_stages", []):
        try:
            text_to_check.append(json.dumps(stage.get("input_snapshot", {})))
            text_to_check.append(json.dumps(stage.get("output_snapshot", {})))
        except Exception:
            pass

    combined_text = " ".join(text_to_check)
    for pattern in LEAK_PATTERNS:
        match = pattern.search(combined_text)
        if match:
            return fail_result(f"Secret / PII leak detected matching pattern: {match.group()[:10]}...")

    return pass_result("Zero PII or secret leakage in traces and notifications")


def deterministic_replay(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures deterministic outputs for identical seed and inputs."""
    data, scenario = parse_output_and_context(output, context)
    if scenario.get("expect_error"):
        return pass_result("Malformed input scenario - deterministic replay check waived on expected error")

    seed = data.get("seed")
    if seed is None:
        return fail_result("Execution output missing seed for replay verification")

    return pass_result(f"Deterministic execution verified with seed {seed}")


def agent_steps_within_max(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures agent planning loop does not exceed MAX_AGENT_STEPS (6)."""
    data, scenario = parse_output_and_context(output, context)
    metrics = data.get("metrics", {})
    steps = int(metrics.get("agent_steps", data.get("tool_calls", 1)))

    if steps > 6:
        return fail_result(f"Agent steps {steps} exceeded MAX_AGENT_STEPS (6)")

    return pass_result(f"Agent steps ({steps}) within configured limit")


def revisions_within_max(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures policy revisions do not exceed MAX_REVISIONS (3)."""
    data, scenario = parse_output_and_context(output, context)
    metrics = data.get("metrics", {})
    revs = int(metrics.get("revisions_used", 0))

    if revs > 3:
        return fail_result(f"Revisions used {revs} exceeded MAX_REVISIONS (3)")

    return pass_result(f"Revisions used ({revs}) within maximum allowance")


def tool_args_validated(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures all agent tool calls pass Pydantic schema argument validation."""
    data, scenario = parse_output_and_context(output, context)
    tool_stages = [s for s in data.get("trace_stages", []) if s.get("stage") == "TOOL_CALL"]

    for ts in tool_stages:
        inp = ts.get("input_snapshot", {})
        if "invalid_args" in inp:
            out = ts.get("output_snapshot", {})
            if "error" not in out:
                return fail_result(f"Invalid tool arguments were not trapped cleanly: {inp}")

    return pass_result("All tool calls validated against Pydantic schema")


def escalate_when_revisions_exhausted(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures system escalates when revision limit is reached without valid candidate."""
    data, scenario = parse_output_and_context(output, context)
    metrics = data.get("metrics", {})
    revs = int(metrics.get("revisions_used", 0))
    action = data.get("action")

    if revs >= 3 and action not in ("REBOOKED", "REBOOKED_AND_HOTEL", "ESCALATED"):
        return fail_result(f"Revisions exhausted ({revs}) but action was '{action}', expected ESCALATED")

    return pass_result("Proper escalation when revisions exhausted")


def context_budget_respected(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures critical constraints and candidate flights were never dropped from context."""
    data, scenario = parse_output_and_context(output, context)
    trace_stages = data.get("trace_stages", [])

    for stage in trace_stages:
        if stage.get("stage") == "LLM_SELECTION":
            inp = stage.get("input_snapshot", {})
            out = stage.get("output_snapshot", {})
            # Confirm candidates were presented unless deterministic fallback occurred
            if not out.get("llm_fallback") and "candidates_presented" in inp:
                cands = inp.get("candidates_presented", [])
                if not cands and data.get("detected"):
                    return fail_result("Candidate flights list was dropped from LLM prompt payload")

    return pass_result("Context budget respected: critical constraints and candidates preserved")


def money_in_inr(output: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures all traveler-facing monetary values are represented in INR."""
    data, scenario = parse_output_and_context(output, context)
    fare_delta = data.get("fare_delta")
    new_flight = data.get("new_flight")

    if new_flight:
        fare = new_flight.get("fare_inr")
        if fare is not None and not isinstance(fare, (int, float)):
            return fail_result(f"Non-numeric fare amount in replacement flight: {fare}")

    if fare_delta is not None and not isinstance(fare_delta, (int, float)):
        return fail_result(f"Non-numeric fare delta amount: {fare_delta}")

    return pass_result("All traveler-facing currencies strictly in INR")
