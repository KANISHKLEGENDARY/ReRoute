"""
End-to-End Pipeline Tests for ReRoute Autonomous Concierge.
Covers Cancellation, Delay, Missed Connection, No Inventory, Hotel Shift,
Duplicate Event, Hallucinated LLM ID, LLM Outage, Over-Budget, and Notifications.
"""

from datetime import date, datetime, timedelta
import pytest

from app.agent.llm import FakeLLM
from app.agent.orchestrator import InMemoryTraceSink, PipelineDeps
from app.agent.pipeline import handle_disruption
from app.sandbox.inventory import FlightInventorySandbox
from app.schemas.pipeline import (
    ActionType,
    CabinClass,
    CandidateFlight,
    DisruptionEvent,
    DisruptionType,
    HotelOption,
    OriginalBooking,
    PolicyVerdict,
    TripConstraints,
)


@pytest.fixture
def mock_booking() -> OriginalBooking:
    return OriginalBooking(
        user_id=42,
        user_email="alex.traveler@example.com",
        user_name="Alex Traveler",
        itinerary_id=101,
        flight_leg_id=201,
        airline_code="6E",
        flight_number="6E-204",
        pnr="PNR-6E-9999",
        origin="DEL",
        destination="BOM",
        departure_time=datetime(2026, 10, 15, 10, 0, 0),
        arrival_time=datetime(2026, 10, 15, 12, 10, 0),
        cabin_class=CabinClass.ECONOMY,
        fare_paid_inr=4500.0,
        status="CONFIRMED",
        hotel=HotelOption(
            hotel_id="HTL-BOM-01",
            hotel_name="The Orchid Mumbai",
            city="Mumbai",
            airport_code="BOM",
            checkin_date=date(2026, 10, 15),
            checkout_date=date(2026, 10, 17),
            room_type="Deluxe Room",
            rate_per_night_inr=4800.0,
            status="CONFIRMED",
            confirmation_reference="CONF-BOM-8888",
        ),
    )


@pytest.mark.asyncio
async def test_pipeline_cancellation_happy_path(mock_booking):
    """Test standard cancellation: agent finds candidate, validates policy, rebooks and updates hotel."""
    event = DisruptionEvent(
        event_id="EVT-001",
        event_type=DisruptionType.CANCELLED,
        flight_id=201,
        flight_number="6E-204",
        reason="Technical maintenance",
        timestamp=datetime(2026, 10, 15, 8, 30, 0),
    )

    trace_sink = InMemoryTraceSink()
    deps = PipelineDeps(
        inventory=FlightInventorySandbox(),
        llm=FakeLLM(mode="good"),
        trace_sink=trace_sink,
        clock=datetime(2026, 10, 15, 8, 30, 0),
    )

    result = await handle_disruption(event=event, booking=mock_booking, deps=deps)

    assert result.detected is True
    assert result.disruption_type == DisruptionType.CANCELLED
    assert result.action in [ActionType.REBOOKED, ActionType.REBOOKED_AND_HOTEL]
    assert result.policy_verdict == PolicyVerdict.APPROVED
    assert result.new_flight is not None
    assert result.new_flight["new_pnr"].startswith("RR-")
    assert result.notification["subject"] != ""
    assert result.metrics["latency_ms"] > 0
    assert len(trace_sink.stages) >= 4


@pytest.mark.asyncio
async def test_pipeline_delay_breaks_connection(mock_booking):
    """Test delay causing broken connection layover."""
    # Add downstream connecting leg
    mock_booking.downstream_legs = [
        {
            "flight_number": "6E-789",
            "origin": "BOM",
            "destination": "GOI",
            "departure_time": datetime(2026, 10, 15, 14, 0, 0).isoformat(),
        }
    ]

    # Delay of 120 mins pushes arrival from 12:10 to 14:10, breaking 14:00 connection
    event = DisruptionEvent(
        event_id="EVT-002",
        event_type=DisruptionType.DELAYED,
        flight_id=201,
        flight_number="6E-204",
        delay_minutes=120,
        timestamp=datetime(2026, 10, 15, 9, 0, 0),
    )

    deps = PipelineDeps(
        inventory=FlightInventorySandbox(),
        llm=FakeLLM(mode="good"),
        clock=datetime(2026, 10, 15, 9, 0, 0),
    )

    result = await handle_disruption(event=event, booking=mock_booking, deps=deps)

    assert result.detected is True
    assert result.disruption_type == DisruptionType.MISSED_CONNECTION
    assert result.policy_verdict in [PolicyVerdict.APPROVED, PolicyVerdict.ESCALATE]


@pytest.mark.asyncio
async def test_pipeline_no_inventory_escalates(mock_booking):
    """When no candidate flights exist or match policy, the system escalates safely."""
    event = DisruptionEvent(
        event_id="EVT-003",
        event_type=DisruptionType.CANCELLED,
        flight_id=201,
        flight_number="6E-204",
        timestamp=datetime(2026, 10, 15, 8, 30, 0),
    )

    # Empty inventory
    empty_inventory = FlightInventorySandbox()
    empty_inventory.search_flights = lambda *args, **kwargs: []

    deps = PipelineDeps(
        inventory=empty_inventory,
        llm=FakeLLM(mode="good"),
        clock=datetime(2026, 10, 15, 8, 30, 0),
    )

    result = await handle_disruption(event=event, booking=mock_booking, deps=deps)

    assert result.detected is True
    assert result.action == ActionType.ESCALATED
    assert result.policy_verdict == PolicyVerdict.ESCALATE
    assert result.new_flight is None
    assert "escalated" in result.notification["body"].lower()


@pytest.mark.asyncio
async def test_pipeline_idempotent_duplicate_event(mock_booking):
    """A duplicate event for an already rebooked itinerary returns NO_ACTION."""
    mock_booking.status = "REBOOKED"

    event = DisruptionEvent(
        event_id="EVT-004",
        event_type=DisruptionType.CANCELLED,
        flight_id=201,
        flight_number="6E-204",
        timestamp=datetime(2026, 10, 15, 8, 30, 0),
    )

    deps = PipelineDeps(llm=FakeLLM(mode="good"))
    result = await handle_disruption(event=event, booking=mock_booking, deps=deps)

    assert result.detected is False
    assert result.action == ActionType.NO_ACTION


@pytest.mark.asyncio
async def test_pipeline_hallucinated_llm_id_fallback(mock_booking):
    """When LLM hallucinates a non-existent flight ID, fallback to deterministic ranking."""
    event = DisruptionEvent(
        event_id="EVT-005",
        event_type=DisruptionType.CANCELLED,
        flight_id=201,
        flight_number="6E-204",
        timestamp=datetime(2026, 10, 15, 8, 30, 0),
    )

    deps = PipelineDeps(
        inventory=FlightInventorySandbox(),
        llm=FakeLLM(mode="hallucinated_id"),
        clock=datetime(2026, 10, 15, 8, 30, 0),
    )

    result = await handle_disruption(event=event, booking=mock_booking, deps=deps)

    # Must succeed via deterministic fallback
    assert result.action in [ActionType.REBOOKED, ActionType.REBOOKED_AND_HOTEL]
    assert result.metrics["llm_fallback"] is True
    assert result.new_flight is not None


@pytest.mark.asyncio
async def test_pipeline_llm_outage_fallback(mock_booking):
    """When LLM service throws 503 outage exception, fallback to deterministic ranking seamlessly."""
    event = DisruptionEvent(
        event_id="EVT-006",
        event_type=DisruptionType.CANCELLED,
        flight_id=201,
        flight_number="6E-204",
        timestamp=datetime(2026, 10, 15, 8, 30, 0),
    )

    deps = PipelineDeps(
        inventory=FlightInventorySandbox(),
        llm=FakeLLM(mode="outage"),
        clock=datetime(2026, 10, 15, 8, 30, 0),
    )

    result = await handle_disruption(event=event, booking=mock_booking, deps=deps)

    assert result.action in [ActionType.REBOOKED, ActionType.REBOOKED_AND_HOTEL]
    assert result.metrics["llm_fallback"] is True
    assert result.new_flight is not None


@pytest.mark.asyncio
async def test_pipeline_over_budget_fallback(mock_booking):
    """When token budget is exceeded, fallback to deterministic ranking."""
    event = DisruptionEvent(
        event_id="EVT-007",
        event_type=DisruptionType.CANCELLED,
        flight_id=201,
        flight_number="6E-204",
        timestamp=datetime(2026, 10, 15, 8, 30, 0),
    )

    deps = PipelineDeps(
        inventory=FlightInventorySandbox(),
        llm=FakeLLM(mode="over_budget"),
        clock=datetime(2026, 10, 15, 8, 30, 0),
    )

    result = await handle_disruption(event=event, booking=mock_booking, deps=deps)

    assert result.action in [ActionType.REBOOKED, ActionType.REBOOKED_AND_HOTEL]
    assert result.metrics["llm_fallback"] is True


@pytest.mark.asyncio
async def test_pipeline_hotel_shift_multi_night_and_late_arrival(mock_booking):
    """
    Cancelled flight causing traveler to arrive late on a future date must shift hotel check-in,
    including a multi-night shift, maintaining consistent stay duration.
    """
    event = DisruptionEvent(
        event_id="EVT-HOTEL-SHIFT-01",
        event_type=DisruptionType.CANCELLED,
        flight_id=201,
        flight_number="6E-204",
        reason="Flight cancelled due to airspace closure",
        timestamp=datetime(2026, 10, 15, 8, 30, 0),
    )

    # Candidate flight arriving 2 days later late at night (23:30)
    inventory = FlightInventorySandbox()
    replacement_flight = CandidateFlight(
        flight_id="6E-999-20261017-LATE",
        airline_code="6E",
        airline_name="IndiGo",
        flight_number="6E-999",
        origin="DEL",
        destination="BOM",
        departure_time=datetime(2026, 10, 17, 21, 0, 0),
        arrival_time=datetime(2026, 10, 17, 23, 30, 0),
        cabin_class=CabinClass.ECONOMY,
        fare_inr=5200.0,
        available_seats=5,
    )
    inventory.add_override_flight(replacement_flight)

    # Set constraint arrival to allow this candidate flight date
    constraints = TripConstraints(
        max_fare_delta_inr=5000.0,
        max_delay_hours=60.0,
        required_origin="DEL",
        required_destination="BOM",
        earliest_departure_time=datetime(2026, 10, 15, 8, 30, 0),
        original_arrival_time=datetime(2026, 10, 15, 12, 10, 0),
        allowed_cabins=[CabinClass.ECONOMY],
    )

    deps = PipelineDeps(
        inventory=inventory,
        llm=FakeLLM(mode="scripted", scripted_flight_id="6E-999-20261017-LATE"),
        clock=datetime(2026, 10, 15, 8, 30, 0),
    )

    result = await handle_disruption(
        event=event,
        booking=mock_booking,
        deps=deps,
        constraints=constraints,
    )

    assert result.detected is True
    assert result.action == ActionType.REBOOKED_AND_HOTEL
    assert result.hotel is not None

    orig_nights = (mock_booking.hotel.checkout_date - mock_booking.hotel.checkin_date).days
    new_checkin = date.fromisoformat(result.hotel["new_checkin"])
    new_checkout = date.fromisoformat(result.hotel["new_checkout"])
    new_nights = (new_checkout - new_checkin).days

    # Multi-night shift verification
    assert result.hotel["date_shift_days"] == 2
    assert new_checkin == date(2026, 10, 17)
    assert new_checkout == date(2026, 10, 19)
    # Check-in and check-out consistency
    assert new_nights == orig_nights
    # Late check-in flagged (arrival at 23:30)
    assert result.hotel["is_late_checkin"] is True


@pytest.mark.asyncio
async def test_pipeline_delay_below_threshold_no_action(mock_booking):
    """Delay below the policy threshold (e.g. 30 mins) results in NO_ACTION and no new booking."""
    event = DisruptionEvent(
        event_id="EVT-DELAY-MINOR",
        event_type=DisruptionType.DELAYED,
        flight_id=201,
        flight_number="6E-204",
        delay_minutes=30,
        timestamp=datetime(2026, 10, 15, 9, 0, 0),
    )

    deps = PipelineDeps(
        inventory=FlightInventorySandbox(),
        llm=FakeLLM(mode="good"),
        clock=datetime(2026, 10, 15, 9, 0, 0),
    )

    result = await handle_disruption(event=event, booking=mock_booking, deps=deps)

    assert result.detected is False
    assert result.disruption_type == DisruptionType.NONE
    assert result.action == ActionType.NO_ACTION
    assert result.new_flight is None


@pytest.mark.asyncio
async def test_pipeline_delay_above_threshold_detected(mock_booking):
    """Delay just above the threshold (e.g. 65 mins) is detected as an actionable disruption."""
    event = DisruptionEvent(
        event_id="EVT-DELAY-MAJOR",
        event_type=DisruptionType.DELAYED,
        flight_id=201,
        flight_number="6E-204",
        delay_minutes=65,
        timestamp=datetime(2026, 10, 15, 9, 0, 0),
    )

    deps = PipelineDeps(
        inventory=FlightInventorySandbox(),
        llm=FakeLLM(mode="good"),
        clock=datetime(2026, 10, 15, 9, 0, 0),
    )

    result = await handle_disruption(event=event, booking=mock_booking, deps=deps)

    assert result.detected is True
    assert result.disruption_type == DisruptionType.DELAYED


@pytest.mark.asyncio
async def test_pipeline_missed_connection_standalone(mock_booking):
    """Missed connection event as its own explicit disruption scenario."""
    event = DisruptionEvent(
        event_id="EVT-MC-STANDALONE",
        event_type=DisruptionType.MISSED_CONNECTION,
        flight_id=201,
        flight_number="6E-204",
        reason="Missed connecting flight due to inbound delay",
        timestamp=datetime(2026, 10, 15, 9, 30, 0),
    )

    deps = PipelineDeps(
        inventory=FlightInventorySandbox(),
        llm=FakeLLM(mode="good"),
        clock=datetime(2026, 10, 15, 9, 30, 0),
    )

    result = await handle_disruption(event=event, booking=mock_booking, deps=deps)

    assert result.detected is True
    assert result.disruption_type == DisruptionType.MISSED_CONNECTION
    assert result.action in [ActionType.REBOOKED, ActionType.REBOOKED_AND_HOTEL, ActionType.ESCALATED]


@pytest.mark.asyncio
async def test_pipeline_daily_cost_budget_fallback(mock_booking):
    """When daily LLM cost budget is exceeded, pipeline falls back to deterministic mode without invoking LLM."""
    event = DisruptionEvent(
        event_id="EVT-DAILY-BUDGET-01",
        event_type=DisruptionType.CANCELLED,
        flight_id=201,
        flight_number="6E-204",
        timestamp=datetime(2026, 10, 15, 8, 30, 0),
    )

    fake_llm = FakeLLM(mode="good")
    deps = PipelineDeps(
        inventory=FlightInventorySandbox(),
        llm=fake_llm,
        clock=datetime(2026, 10, 15, 8, 30, 0),
        daily_cost_budget_usd=5.0,
        current_daily_cost_usd=6.5,  # Exceeded daily limit
    )

    result = await handle_disruption(event=event, booking=mock_booking, deps=deps)

    assert result.action in [ActionType.REBOOKED, ActionType.REBOOKED_AND_HOTEL]
    assert result.metrics["llm_fallback"] is True
    assert fake_llm.call_count == 0  # Proves LLM was not called
    assert result.new_flight is not None


@pytest.mark.asyncio
async def test_pipeline_daily_cost_budget_resets_on_new_day(mock_booking):
    """
    Daily cost budget resets to 0.0 when deps.clock advances to a new calendar day,
    never relying on datetime.now(). Also verifies metrics expose cost_inr.
    """
    day1_clock = datetime(2026, 10, 15, 10, 0, 0)
    fake_llm = FakeLLM(mode="good")
    deps = PipelineDeps(
        inventory=FlightInventorySandbox(),
        llm=fake_llm,
        clock=day1_clock,
        daily_cost_budget_usd=5.0,
        current_daily_cost_usd=6.0,  # Exceeded on Day 1
    )

    # 1. On Day 1: budget exceeded -> fallback triggers
    event1 = DisruptionEvent(
        event_id="EVT-RESET-01",
        event_type=DisruptionType.CANCELLED,
        flight_id=201,
        flight_number="6E-204",
        timestamp=day1_clock,
    )
    res1 = await handle_disruption(event=event1, booking=mock_booking, deps=deps)
    assert res1.metrics["llm_fallback"] is True
    assert fake_llm.call_count == 0

    # 2. Advance deps.clock to Day 2 (strictly via deps.clock, not datetime.now)
    day2_clock = datetime(2026, 10, 16, 9, 0, 0)
    deps.clock = day2_clock
    # Check that daily cost resets to 0.0
    assert deps.get_current_daily_cost() == 0.0

    # 3. On Day 2: budget is fresh -> LLM runs normally
    booking_day2 = mock_booking.model_copy(deep=True)
    booking_day2.departure_time = datetime(2026, 10, 16, 10, 0, 0)
    booking_day2.arrival_time = datetime(2026, 10, 16, 12, 10, 0)
    event2 = DisruptionEvent(
        event_id="EVT-RESET-02",
        event_type=DisruptionType.CANCELLED,
        flight_id=201,
        flight_number="6E-204",
        timestamp=day2_clock,
    )
    res2 = await handle_disruption(event=event2, booking=booking_day2, deps=deps)
    assert res2.metrics["llm_fallback"] is False
    assert fake_llm.call_count == 1
    assert "cost_inr" in res2.metrics
    assert res2.metrics["cost_inr"] >= 0.0



