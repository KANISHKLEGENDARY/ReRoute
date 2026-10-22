"""
In-Memory Evaluation Adapter for ReRoute Travel-Disruption Concierge.

Connects evaluation suites (Promptfoo, unit tests, benchmarks) to the pure-function
production pipeline `handle_disruption(event, booking, deps, constraints)` without
touching PostgreSQL, Redis, external networks, or sending real emails.
"""

from copy import deepcopy
from datetime import datetime, date, timezone
import logging
from typing import Any, Dict, List, Optional, Union

from app.schemas.pipeline import (
    ActionType,
    CabinClass,
    CandidateFlight,
    DecisionResult,
    DisruptionEvent,
    DisruptionType,
    HotelOption,
    OriginalBooking,
    PolicyVerdict,
    TripConstraints,
)
from app.sandbox.inventory import FlightInventorySandbox
from app.agent.orchestrator import (
    InMemoryTraceSink,
    PipelineDeps,
)
from app.agent.pipeline import handle_disruption
from app.agent.llm import (
    FakeLLM,
    get_llm_client,
)

logger = logging.getLogger("reroute.eval_adapter")


class FakeNotifier:
    """
    In-memory notifier test double.
    Captures outgoing emails and notifications for assertion verification without sending.
    """

    def __init__(self):
        self.sent_notifications: List[Dict[str, Any]] = []

    def send(self, recipient: str, subject: str, body: str, **kwargs) -> None:
        self.sent_notifications.append({
            "recipient": recipient,
            "subject": subject,
            "body": body,
            **kwargs,
        })

    async def asend(self, recipient: str, subject: str, body: str, **kwargs) -> None:
        self.send(recipient, subject, body, **kwargs)


def _parse_dt(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        # Support ISO formats
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    return None


def _parse_date(val: Any) -> Optional[date]:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        return date.fromisoformat(val[:10])
    return None


class ItineraryState:
    """
    In-memory state model representing a traveler's itinerary with multiple flight legs
    and an optional linked hotel booking. Updated after each disruption execution.
    """

    def __init__(self, itinerary_dict: Dict[str, Any]):
        self.itinerary_id: int = int(itinerary_dict.get("itinerary_id", 101))
        user_info = itinerary_dict.get("user", {})
        self.user_id: int = int(user_info.get("user_id", 1))
        self.user_name: str = str(user_info.get("user_name", "Aarav Sharma"))
        self.user_email: str = str(user_info.get("user_email", "aarav@example.com"))

        raw_legs = itinerary_dict.get("legs", [])
        self.legs: List[Dict[str, Any]] = []
        for leg in raw_legs:
            leg_copy = deepcopy(leg)
            if leg_copy.get("flight_number") is not None:
                leg_copy["flight_number"] = f"{leg_copy['flight_number']}".upper()
            if leg_copy.get("airline_code") is not None:
                leg_copy["airline_code"] = f"{leg_copy['airline_code']}".upper()
            self.legs.append(leg_copy)

        raw_hotel = itinerary_dict.get("hotel")
        self.hotel: Optional[Dict[str, Any]] = deepcopy(raw_hotel) if raw_hotel else None

    def find_leg_index(self, event: DisruptionEvent) -> int:
        """Find the index of the affected flight leg within the itinerary."""
        if event.flight_id is not None:
            for idx, leg in enumerate(self.legs):
                if leg.get("flight_leg_id") == event.flight_id:
                    return idx

        if event.flight_number:
            for idx, leg in enumerate(self.legs):
                if leg.get("flight_number") == event.flight_number:
                    return idx

        # Default to first leg if not specified
        return 0

    def build_booking_for_leg(self, leg_index: int) -> OriginalBooking:
        """Constructs an OriginalBooking schema for the specified leg."""
        if not self.legs or leg_index >= len(self.legs):
            raise IndexError(f"Leg index {leg_index} out of bounds for itinerary {self.itinerary_id}")

        leg = self.legs[leg_index]

        dep_dt = _parse_dt(leg.get("departure_time")) or datetime.utcnow()
        arr_dt = _parse_dt(leg.get("arrival_time")) or datetime.utcnow()

        cabin_raw = leg.get("cabin_class", "ECONOMY")
        cabin = CabinClass(cabin_raw) if isinstance(cabin_raw, str) else cabin_raw

        # Construct downstream legs (subsequent legs in trip sequence)
        downstream_legs: List[Dict[str, Any]] = []
        for downstream_leg in self.legs[leg_index + 1 :]:
            downstream_dep = _parse_dt(downstream_leg.get("departure_time"))
            downstream_arr = _parse_dt(downstream_leg.get("arrival_time"))
            downstream_legs.append({
                "flight_leg_id": downstream_leg.get("flight_leg_id"),
                "flight_number": downstream_leg.get("flight_number"),
                "origin": downstream_leg.get("origin"),
                "destination": downstream_leg.get("destination"),
                "departure_time": downstream_dep.isoformat() if downstream_dep else None,
                "arrival_time": downstream_arr.isoformat() if downstream_arr else None,
            })

        # Construct upstream legs (preceding legs in trip sequence)
        upstream_legs: List[Dict[str, Any]] = []
        for upstream_leg in self.legs[:leg_index]:
            upstream_dep = _parse_dt(upstream_leg.get("departure_time"))
            upstream_arr = _parse_dt(upstream_leg.get("arrival_time"))
            upstream_legs.append({
                "flight_leg_id": upstream_leg.get("flight_leg_id"),
                "flight_number": upstream_leg.get("flight_number"),
                "origin": upstream_leg.get("origin"),
                "destination": upstream_leg.get("destination"),
                "departure_time": upstream_dep.isoformat() if upstream_dep else None,
                "arrival_time": upstream_arr.isoformat() if upstream_arr else None,
            })

        # Construct hotel option if linked
        hotel_option: Optional[HotelOption] = None
        if self.hotel:
            cin = _parse_date(self.hotel.get("checkin_date")) or date.today()
            cout = _parse_date(self.hotel.get("checkout_date")) or (date.today())
            hotel_option = HotelOption(
                hotel_id=str(self.hotel.get("hotel_id", "HTL-001")),
                hotel_name=str(self.hotel.get("hotel_name", "Partner Hotel")),
                city=str(self.hotel.get("city", leg.get("destination", "BOM"))),
                airport_code=str(self.hotel.get("airport_code", leg.get("destination", "BOM"))),
                checkin_date=cin,
                checkout_date=cout,
                room_type=str(self.hotel.get("room_type", "Standard Room")),
                rate_per_night_inr=float(self.hotel.get("rate_per_night_inr", 4000.0)),
                status=str(self.hotel.get("status", "CONFIRMED")),
                confirmation_reference=str(self.hotel.get("confirmation_reference", "HTL-CONF-001")),
                address=self.hotel.get("address"),
            )

        return OriginalBooking(
            user_id=self.user_id,
            user_email=self.user_email,
            user_name=self.user_name,
            itinerary_id=self.itinerary_id,
            flight_leg_id=int(leg.get("flight_leg_id", leg_index + 1)),
            airline_code=str(leg.get("airline_code", "6E")),
            flight_number=str(leg.get("flight_number", "6E-204")),
            pnr=str(leg.get("pnr", f"PNR-{self.itinerary_id}-{leg_index + 1}")),
            origin=str(leg.get("origin", "DEL")),
            destination=str(leg.get("destination", "BOM")),
            departure_time=dep_dt,
            arrival_time=arr_dt,
            cabin_class=cabin,
            fare_paid_inr=float(leg.get("fare_paid_inr", 4500.0)),
            status=str(leg.get("status", "CONFIRMED")),
            hotel=hotel_option,
            downstream_legs=downstream_legs,
            upstream_legs=upstream_legs,
        )

    def apply_decision_result(self, leg_index: int, result: DecisionResult) -> None:
        """Updates the in-memory itinerary state with the execution output."""
        if leg_index < len(self.legs):
            leg = self.legs[leg_index]
            if result.action in (ActionType.REBOOKED, ActionType.REBOOKED_AND_HOTEL):
                if result.new_flight:
                    leg["flight_id"] = result.new_flight.get("flight_id")
                    leg["flight_number"] = result.new_flight.get("flight_number", leg.get("flight_number"))
                    leg["departure_time"] = result.new_flight.get("departure_time")
                    leg["arrival_time"] = result.new_flight.get("arrival_time")
                    leg["pnr"] = result.new_flight.get("new_pnr", result.new_flight.get("pnr", leg.get("pnr")))
                    leg["fare_paid_inr"] = float(result.new_flight.get("fare_inr", leg.get("fare_paid_inr", 0.0)))
                    leg["status"] = "REBOOKED"
            elif result.action == ActionType.ESCALATED:
                leg["status"] = "ESCALATED"

        if result.hotel and self.hotel:
            if "new_checkin" in result.hotel:
                self.hotel["checkin_date"] = result.hotel["new_checkin"]
            if "new_checkout" in result.hotel:
                self.hotel["checkout_date"] = result.hotel["new_checkout"]
            self.hotel["status"] = "MODIFIED"

    def to_dict(self) -> Dict[str, Any]:
        """Exports the current state as a serializable dictionary."""
        return {
            "itinerary_id": self.itinerary_id,
            "user": {
                "user_id": self.user_id,
                "user_name": self.user_name,
                "user_email": self.user_email,
            },
            "legs": deepcopy(self.legs),
            "hotel": deepcopy(self.hotel) if self.hotel else None,
        }


def _create_llm_instance(llm_mode: str, scenario: Dict[str, Any]) -> Any:
    """Instantiates the test LLM instance based on scenario configuration."""
    if llm_mode == "fake_good":
        return FakeLLM(mode="good")
    elif llm_mode == "fake_bad":
        behavior = (
            scenario.get("scripted_behavior")
            or scenario.get("fake_mode")
            or scenario.get("behavior")
            or "hallucinated_id"
        )
        return FakeLLM(
            mode=behavior,
            scripted_flight_id=scenario.get("scripted_flight_id"),
            scripted_rationale=scenario.get("scripted_rationale"),
        )
    elif llm_mode == "real":
        import os
        run_live = os.environ.get("RUN_LIVE_LLM", "0").lower() in ("1", "true", "yes")
        if not run_live:
            # Opt-in guard: without RUN_LIVE_LLM=1, safe deterministic fallback
            return FakeLLM(mode="good")
        from app.core.config import get_settings
        from app.agent.llm import GeminiLLMClient, NoKeyLLMClient
        s = get_settings()
        target_model = scenario.get("model") or s.LLM_MODEL
        if not s.GOOGLE_API_KEY:
            return NoKeyLLMClient()
        return GeminiLLMClient(
            api_key=s.GOOGLE_API_KEY,
            model=target_model,
            temperature=0.0,
            settings=s,
        )
    else:
        return FakeLLM(mode="good")


async def run_scenario(scenario: Dict[str, Any], seed: int = 0) -> Dict[str, Any]:
    """
    Executes an evaluation scenario end-to-end through `handle_disruption`.

    Parameters:
    - scenario: Dictionary specifying itinerary, event(s), constraints, and expectations.
    - seed: Deterministic integer seed for sandbox inventory.

    Returns:
    - Dict containing DecisionResult, traces, notifications, and updated itinerary state.
    """
    try:
        scenario_id = scenario.get("id", "scenario_unknown")
        category = scenario.get("category", "general")
        severity = scenario.get("severity", "normal")
        scenario_seed = int(scenario.get("seed", seed))

        # 1. Initialize In-Memory Itinerary State
        raw_itinerary = scenario.get("itinerary", {})
        if not raw_itinerary.get("legs"):
            # Provide default baseline leg if omitted
            raw_itinerary = {
                "itinerary_id": 101,
                "user": {"user_id": 1, "user_name": "Aarav Sharma", "user_email": "aarav@example.com"},
                "legs": [
                    {
                        "flight_leg_id": 1,
                        "airline_code": "6E",
                        "flight_number": "6E-204",
                        "pnr": "PNR123",
                        "origin": "DEL",
                        "destination": "BOM",
                        "departure_time": "2026-10-20T06:00:00",
                        "arrival_time": "2026-10-20T08:10:00",
                        "cabin_class": "ECONOMY",
                        "fare_paid_inr": 4800.0,
                        "status": "CONFIRMED",
                    }
                ],
            }
        state = ItineraryState(raw_itinerary)

        # 2. Initialize Seeded Sandbox Inventory
        inventory = FlightInventorySandbox(seed=scenario_seed)
        if scenario.get("no_inventory"):
            # Emulate no available flights for testing
            inventory.search_flights = lambda *args, **kwargs: []

        for custom_flight in scenario.get("custom_flights", []):
            cf_copy = deepcopy(custom_flight)
            if "flight_number" in cf_copy and cf_copy["flight_number"] is not None:
                cf_copy["flight_number"] = f"{cf_copy['flight_number']}".upper()
            if "airline_code" in cf_copy and cf_copy["airline_code"] is not None:
                cf_copy["airline_code"] = f"{cf_copy['airline_code']}".upper()
            if "flight_id" in cf_copy and cf_copy["flight_id"] is not None:
                cf_copy["flight_id"] = f"{cf_copy['flight_id']}"
            cf = CandidateFlight(**cf_copy)
            inventory.add_override_flight(cf)

        for custom_hotel in scenario.get("custom_hotels", []):
            ch = HotelOption(**custom_hotel)
            inventory.add_override_hotel(ch)

        # 3. In-Memory Trace Sink and Notifier
        trace_sink = InMemoryTraceSink(event_id=scenario_id)
        fake_notifier = FakeNotifier()

        # 4. LLM Instance
        llm_mode = scenario.get("llm_mode", "fake_good")
        llm_client = _create_llm_instance(llm_mode, scenario)

        # 5. Extract Event(s) Sequence
        raw_events = scenario.get("events") or scenario.get("event_sequence")
        if not raw_events:
            raw_event = scenario.get("event", {})
            raw_events = [raw_event]

        results_list: List[DecisionResult] = []
        final_result: Optional[DecisionResult] = None

        # 6. Execute Events in Sequence
        for e_idx, ev_dict in enumerate(raw_events):
            event_id = str(ev_dict.get("event_id", f"{scenario_id}_evt_{e_idx + 1}"))
            ev_type_str = ev_dict.get("event_type", "CANCELLED")
            try:
                ev_type = DisruptionType(ev_type_str)
            except ValueError:
                ev_type = DisruptionType.NONE

            ev_timestamp = _parse_dt(ev_dict.get("timestamp")) or datetime(2026, 10, 20, 6, 0, tzinfo=timezone.utc)

            raw_fn = ev_dict.get("flight_number")
            flight_number = f"{raw_fn}".upper() if raw_fn is not None else None
            raw_fid = ev_dict.get("flight_id")
            flight_id = int(raw_fid) if raw_fid is not None else None

            event = DisruptionEvent(
                event_id=event_id,
                event_type=ev_type,
                flight_id=flight_id,
                flight_number=flight_number,
                delay_minutes=int(ev_dict.get("delay_minutes", 0)),
                diverted_to=ev_dict.get("diverted_to"),
                reason=ev_dict.get("reason"),
                notice_text=ev_dict.get("notice_text"),
                traveler_preferences=ev_dict.get("traveler_preferences"),
                timestamp=ev_timestamp,
                details=ev_dict.get("details", {}),
            )

            # Determine affected leg from updated state
            affected_leg_idx = state.find_leg_index(event)
            booking = state.build_booking_for_leg(affected_leg_idx)

            # Clock: align fake clock with the event timestamp
            clock = ev_timestamp

            # Trip Constraints
            raw_constraints = scenario.get("constraints", {})
            allowed_cabins = [
                CabinClass(c) for c in raw_constraints.get("allowed_cabins", [booking.cabin_class])
            ]
            constraints = TripConstraints(
                max_fare_delta_inr=float(raw_constraints.get("max_fare_delta_inr", 5000.0)),
                max_delay_hours=float(raw_constraints.get("max_delay_hours", 3.0)),
                min_airport_buffer_minutes=int(raw_constraints.get("min_airport_buffer_minutes", 45)),
                min_connection_buffer_minutes=int(raw_constraints.get("min_connection_buffer_minutes", 45)),
                allowed_cabins=allowed_cabins,
                required_origin=booking.origin,
                required_destination=booking.destination,
                earliest_departure_time=clock,
                original_arrival_time=booking.arrival_time,
                downstream_departure_time=(
                    _parse_dt(booking.downstream_legs[0]["departure_time"])
                    if booking.downstream_legs and "departure_time" in booking.downstream_legs[0]
                    else None
                ),
                upstream_arrival_time=(
                    _parse_dt(booking.upstream_legs[-1]["arrival_time"])
                    if booking.upstream_legs and "arrival_time" in booking.upstream_legs[-1]
                    else None
                ),
            )

            # Build Pipeline Dependencies for this step
            deps = PipelineDeps(
                inventory=inventory,
                llm=llm_client,
                trace_sink=trace_sink,
                clock=clock,
                daily_cost_budget_usd=float(scenario.get("daily_cost_budget_usd", 10.0)),
                current_daily_cost_usd=float(scenario.get("current_daily_cost_usd", 0.0)),
            )
            # Attach notifier double
            deps.notifier = fake_notifier

            # Execute pure-function pipeline
            res = await handle_disruption(
                event=event,
                booking=booking,
                deps=deps,
                constraints=constraints,
            )

            # Capture notification into FakeNotifier
            if res.notification and res.notification.get("subject"):
                fake_notifier.send(
                    recipient=booking.user_email,
                    subject=res.notification.get("subject", ""),
                    body=res.notification.get("body", ""),
                )

            # Update in-memory itinerary state
            state.apply_decision_result(affected_leg_idx, res)

            results_list.append(res)
            final_result = res

        if not final_result:
            raise RuntimeError("Scenario produced no decision results")

        # Compile final output package
        tool_call_count = sum(1 for s in trace_sink.stages if s.get("stage") == "TOOL_CALL")
        captured_notif = (
            fake_notifier.sent_notifications[-1]
            if fake_notifier.sent_notifications
            else final_result.notification
        )

        return {
            "scenario_id": scenario_id,
            "category": category,
            "severity": severity,
            "seed": scenario_seed,
            "event_id": final_result.event_id,
            "detected": final_result.detected,
            "disruption_type": (
                final_result.disruption_type.value
                if hasattr(final_result.disruption_type, "value")
                else str(final_result.disruption_type)
            ),
            "action": (
                final_result.action.value
                if hasattr(final_result.action, "value")
                else str(final_result.action)
            ),
            "policy_verdict": (
                final_result.policy_verdict.value
                if hasattr(final_result.policy_verdict, "value")
                else str(final_result.policy_verdict)
            ),
            "policy_reasons": final_result.policy_reasons,
            "new_flight": final_result.new_flight,
            "hotel": final_result.hotel,
            "fare_delta": final_result.fare_delta,
            "explanation": final_result.explanation,
            "notification": captured_notif,
            "trace_stages": [s for s in trace_sink.stages],
            "tool_calls": tool_call_count,
            "metrics": final_result.metrics,
            "error": final_result.error,
            "itinerary": state.to_dict(),
            "sequence_results": [r.model_dump(mode="json") for r in results_list],
            "captured_notifications": fake_notifier.sent_notifications,
        }

    except Exception as e:
        logger.error("[EVAL ADAPTER ERROR] Scenario execution failed: %s", str(e), exc_info=True)
        return {
            "scenario_id": scenario.get("id", "scenario_error"),
            "category": scenario.get("category", "error"),
            "severity": scenario.get("severity", "normal"),
            "action": "ERROR",
            "policy_verdict": "ESCALATE",
            "policy_reasons": ["ADAPTER_ERROR"],
            "new_flight": None,
            "hotel": None,
            "fare_delta": 0.0,
            "explanation": f"Evaluation adapter error: {str(e)}",
            "notification": {},
            "trace_stages": [],
            "tool_calls": 0,
            "metrics": {},
            "error": str(e),
            "itinerary": scenario.get("itinerary", {}),
            "sequence_results": [],
            "captured_notifications": [],
        }
