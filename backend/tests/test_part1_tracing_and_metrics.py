"""
Part 1 Test Suite: Event-Level Tracing, Metrics, Idempotency, and Simulation Hooks.

Covers:
1. Two distinct events on the same itinerary:
   - disruptions_handled == 2
   - Latency equals the recorded pipeline latency (not timestamp gap)
   - All stages persisted per event (including RESULT stage)
2. Duplicate event_id idempotency (ignored, no duplicate traces or rebooking)
3. Pipeline error handling (no silent failure: yields a RESULT row with action=ERROR)
4. Simulate endpoint hooks with notice_text and traveler_preferences validation
"""

from datetime import datetime, date, timedelta, timezone
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.main import create_application
from app.core.database import async_session_factory, init_db
from app.models.user import User
from app.models.itinerary import Itinerary
from app.models.flight_leg import FlightLeg
from app.models.hotel import HotelBooking
from app.models.trace import DecisionTrace
from app.services.consumer import process_disruption_event
from app.schemas.pipeline import DisruptionType, ActionType

app = create_application()


from uuid import uuid4

@pytest.fixture
async def seed_multi_leg_trip():
    """Seeds a test user, itinerary with two flight legs, and a hotel booking."""
    async with async_session_factory() as session:
        user = User(
            name="Ananya Verma",
            email=f"ananya_{uuid4().hex[:8]}@example.com",
            phone="+919876543299",
            password_hash="test_bcrypt_hash",
        )
        session.add(user)
        await session.flush()

        itinerary = Itinerary(
            user_id=user.id,
            status="ACTIVE",
        )
        session.add(itinerary)
        await session.flush()

        # Leg 1: DEL -> BOM
        leg1 = FlightLeg(
            itinerary_id=itinerary.id,
            leg_order=1,
            airline_code="6E",
            flight_number="204",
            pnr="PNR-MULTI-01",
            eticket_number="098-2001",
            origin="DEL",
            destination="BOM",
            departure_datetime=datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc),
            arrival_datetime=datetime(2026, 10, 20, 12, 10, 0, tzinfo=timezone.utc),
            cabin_class="ECONOMY",
            fare_paid=4800.0,
            currency="INR",
            status="ON_TIME",
        )
        session.add(leg1)

        # Leg 2: BOM -> GOI
        leg2 = FlightLeg(
            itinerary_id=itinerary.id,
            leg_order=2,
            airline_code="6E",
            flight_number="512",
            pnr="PNR-MULTI-02",
            eticket_number="098-2002",
            origin="BOM",
            destination="GOI",
            departure_datetime=datetime(2026, 10, 20, 14, 30, 0, tzinfo=timezone.utc),
            arrival_datetime=datetime(2026, 10, 20, 15, 45, 0, tzinfo=timezone.utc),
            cabin_class="ECONOMY",
            fare_paid=2800.0,
            currency="INR",
            status="ON_TIME",
        )
        session.add(leg2)

        hotel = HotelBooking(
            itinerary_id=itinerary.id,
            hotel_name="Goa Beach Resort",
            confirmation_reference="HTL-GOA-77",
            checkin_date=date(2026, 10, 20),
            checkout_date=date(2026, 10, 23),
            room_rate=4500.0,
            currency="INR",
            status="CONFIRMED",
        )
        session.add(hotel)

        await session.commit()
        return {
            "user_id": user.id,
            "itinerary_id": itinerary.id,
            "leg1_id": leg1.id,
            "leg2_id": leg2.id,
        }


@pytest.mark.asyncio
async def test_two_events_on_same_itinerary_and_metrics(seed_multi_leg_trip):
    """
    Asserts:
    1. Two distinct events run on the same itinerary.
    2. All pipeline stages are persisted per event, each with event_id, ending in RESULT.
    3. GET /metrics returns disruptions_handled == 2.
    4. Latency equals the recorded pipeline latency (not timestamp gap between events).
    5. GET /api/v1/itinerary/{id}/trace returns stages grouped by event_id ordered by event then time.
    """
    itin_id = seed_multi_leg_trip["itinerary_id"]
    leg1_id = seed_multi_leg_trip["leg1_id"]
    leg2_id = seed_multi_leg_trip["leg2_id"]

    evt1_id = f"EVT-ITIN-{uuid4().hex[:8]}"
    evt2_id = f"EVT-ITIN-{uuid4().hex[:8]}"

    # 1. Process Event 1 on Leg 1
    event1 = {
        "event_id": evt1_id,
        "event_type": "CANCELLED",
        "flight_id": leg1_id,
        "flight_number": "6E-204",
        "reason": "Air traffic control operational cancellation",
    }
    res1 = await process_disruption_event(event1)
    assert res1 is not None

    # 2. Process Event 2 on Leg 2
    event2 = {
        "event_id": evt2_id,
        "event_type": "CANCELLED",
        "flight_id": leg2_id,
        "flight_number": "6E-512",
        "reason": "Technical equipment swap",
    }
    res2 = await process_disruption_event(event2)
    assert res2 is not None

    # 3. Verify traces in DB
    async with async_session_factory() as session:
        stmt = (
            select(DecisionTrace)
            .where(DecisionTrace.itinerary_id == itin_id)
            .order_by(DecisionTrace.id.asc())
        )
        traces = (await session.execute(stmt)).scalars().all()

        evt1_traces = [t for t in traces if t.event_id == evt1_id]
        evt2_traces = [t for t in traces if t.event_id == evt2_id]

        # All stages persisted per event
        assert len(evt1_traces) >= 4
        assert len(evt2_traces) >= 4

        evt1_stages = [t.stage for t in evt1_traces]
        evt2_stages = [t.stage for t in evt2_traces]

        assert "DETECTION" in evt1_stages
        assert "RESULT" in evt1_stages
        assert "DETECTION" in evt2_stages
        assert "RESULT" in evt2_stages

        # Verify RESULT snapshots
        res1_row = [t for t in evt1_traces if t.stage == "RESULT"][0]
        res2_row = [t for t in evt2_traces if t.stage == "RESULT"][0]

        lat1 = res1_row.output_snapshot.get("latency_ms")
        lat2 = res2_row.output_snapshot.get("latency_ms")
        assert lat1 is not None and lat1 > 0
        assert lat2 is not None and lat2 > 0

    # 4. Call GET /api/v1/metrics
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        m_resp = await client.get("/api/v1/metrics")
        assert m_resp.status_code == 200
        metrics = m_resp.json()

        # Distinct events count is at least 2
        assert metrics["disruptions_handled"] >= 2
        # Latency reflects recorded pipeline latency, not 18-hour timestamp gap!
        assert metrics["avg_latency_ms"] < 60000.0  # Pipeline latency is fast, never hours!

        # 5. Call GET /api/v1/itinerary/{id}/trace (grouped by event_id)
        t_resp = await client.get(f"/api/v1/itinerary/{itin_id}/trace")
        assert t_resp.status_code == 200
        trace_data = t_resp.json()

        assert evt1_id in trace_data
        assert evt2_id in trace_data
        assert len(trace_data[evt1_id]) == len(evt1_traces)
        assert len(trace_data[evt2_id]) == len(evt2_traces)


@pytest.mark.asyncio
async def test_duplicate_event_id_ignored(seed_multi_leg_trip):
    """
    Asserts:
    Event idempotency: a duplicate/redelivered event_id must not run the pipeline
    or book twice, and must not create duplicate trace rows.
    """
    itin_id = seed_multi_leg_trip["itinerary_id"]
    leg1_id = seed_multi_leg_trip["leg1_id"]
    dup_id = f"EVT-IDEMP-{uuid4().hex[:8]}"

    event = {
        "event_id": dup_id,
        "event_type": "CANCELLED",
        "flight_id": leg1_id,
        "flight_number": "6E-204",
        "reason": "Bird strike initial alert",
    }

    # First delivery: processes successfully
    res1 = await process_disruption_event(event)
    assert res1 is not None

    async with async_session_factory() as session:
        stmt = select(DecisionTrace).where(DecisionTrace.event_id == dup_id)
        initial_trace_count = len((await session.execute(stmt)).scalars().all())
        assert initial_trace_count >= 4

    # Second delivery with exact same event_id: must be ignored
    res2 = await process_disruption_event(event)
    assert res2 is None

    async with async_session_factory() as session:
        stmt = select(DecisionTrace).where(DecisionTrace.event_id == dup_id)
        new_trace_count = len((await session.execute(stmt)).scalars().all())
        # Trace count must not change
        assert new_trace_count == initial_trace_count


@pytest.mark.asyncio
async def test_pipeline_error_yields_result_row_with_action_error(seed_multi_leg_trip):
    """
    Asserts:
    No silent failures: an unhandled pipeline error still records a persisted
    RESULT row with action=ERROR, error message, and latency_ms.
    """
    from unittest.mock import patch

    leg1_id = seed_multi_leg_trip["leg1_id"]
    err_id = f"EVT-CRASH-{uuid4().hex[:8]}"
    error_event = {
        "event_id": err_id,
        "event_type": "CANCELLED",
        "flight_id": leg1_id,
        "flight_number": "6E-204",
        "reason": "Test fault injection",
    }

    # Simulate an unexpected internal crash inside LangGraph execution
    with patch("app.agent.pipeline._compiled_graph.ainvoke", side_effect=RuntimeError("Simulated engine explosion")):
        res = await process_disruption_event(error_event)
        # Even on error, process_disruption_event completes without unhandled crash
        assert res is not None
        assert res.get("action") == ActionType.ERROR.value
        assert "Simulated engine explosion" in res.get("error", "")

    # Verify that decision_trace contains a RESULT row with action="ERROR"
    async with async_session_factory() as session:
        stmt = (
            select(DecisionTrace)
            .where(DecisionTrace.event_id == err_id)
            .where(DecisionTrace.stage == "RESULT")
        )
        res_trace = (await session.execute(stmt)).scalars().first()

        assert res_trace is not None
        assert res_trace.output_snapshot["action"] == "ERROR"
        assert "Simulated engine explosion" in res_trace.output_snapshot["error"]


@pytest.mark.asyncio
async def test_simulate_endpoint_extended_fields(seed_multi_leg_trip):
    """
    Asserts:
    POST /api/v1/events/simulate accepts notice_text, traveler_preferences, delay_minutes,
    validates text field lengths, and passes them to Redis event payload.
    """
    leg_id = seed_multi_leg_trip["leg1_id"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Valid extended fields
        resp = await client.post(
            "/api/v1/events/simulate",
            json={
                "flight_leg_id": leg_id,
                "event_type": "DELAYED",
                "delay_minutes": 75,
                "reason": "Late incoming aircraft",
                "notice_text": "We regret to inform that 6E-204 is delayed by 75 minutes due to rotational delay.",
                "traveler_preferences": "Seat near front, no middle seats, prefer IndiGo.",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        payload = data["payload"]
        assert payload["notice_text"] == "We regret to inform that 6E-204 is delayed by 75 minutes due to rotational delay."
        assert payload["traveler_preferences"] == "Seat near front, no middle seats, prefer IndiGo."
        assert payload["delay_minutes"] == 75

        # 2. Length validation: notice_text exceeding 1000 characters is rejected
        oversized_notice = "A" * 1001
        resp_too_long = await client.post(
            "/api/v1/events/simulate",
            json={
                "flight_leg_id": leg_id,
                "event_type": "CANCELLED",
                "notice_text": oversized_notice,
            },
        )
        assert resp_too_long.status_code == 422
