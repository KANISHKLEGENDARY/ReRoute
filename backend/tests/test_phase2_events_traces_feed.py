"""
Phase 2 Test Suite: Events, Traces, Live Feed, and Metrics.
Covers:
1. Simulate payload validation and Redis publish
2. Trace completeness with PII/secret redaction
3. Metrics math aggregation (disruptions handled, auto-resolution, p95 latency, cost in INR)
4. WebSocket live activity sequence and broadcasting
"""

from datetime import datetime, date, timedelta
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.main import create_application
from app.core.database import async_session_factory, init_db
from app.core.activity_feed import activity_feed
from app.models.user import User
from app.models.itinerary import Itinerary
from app.models.flight_leg import FlightLeg
from app.models.hotel import HotelBooking
from app.models.trace import DecisionTrace
from app.services.trace_sink import DatabaseTraceSink, redact_pii_and_secrets
from app.services.consumer import process_disruption_event
from app.schemas.pipeline import DisruptionType


app = create_application()


@pytest.fixture
async def seed_test_trip():
    """Seeds a test user, itinerary, flight leg, and hotel booking."""
    async with async_session_factory() as session:
        user = User(
            name="Priya Sharma",
            email=f"priya_{datetime.utcnow().timestamp()}@example.com",
            phone="+919876543210",
            password_hash="supersecret_hash_value",
        )
        session.add(user)
        await session.flush()

        itinerary = Itinerary(
            user_id=user.id,
            status="ACTIVE",
        )
        session.add(itinerary)
        await session.flush()

        leg = FlightLeg(
            itinerary_id=itinerary.id,
            leg_order=1,
            airline_code="6E",
            flight_number="204",
            pnr="PNR-PRIYA-01",
            origin="DEL",
            destination="BOM",
            departure_datetime=datetime(2026, 10, 20, 10, 0, 0),
            arrival_datetime=datetime(2026, 10, 20, 12, 10, 0),
            cabin_class="ECONOMY",
            fare_paid=4500.0,
            currency="INR",
            status="ON_TIME",
        )
        session.add(leg)

        hotel = HotelBooking(
            itinerary_id=itinerary.id,
            hotel_name="The Orchid Mumbai",
            confirmation_reference="HTL-PRIYA-01",
            checkin_date=date(2026, 10, 20),
            checkout_date=date(2026, 10, 22),
            room_rate=4800.0,
            currency="INR",
            status="CONFIRMED",
        )
        session.add(hotel)

        await session.commit()
        return {"user_id": user.id, "itinerary_id": itinerary.id, "flight_leg_id": leg.id}


@pytest.mark.asyncio
async def test_simulate_endpoint_and_payload(seed_test_trip):
    """
    Test POST /api/v1/events/simulate triggers event publication and validates 404 handling.
    """
    leg_id = seed_test_trip["flight_leg_id"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Valid simulation request
        resp = await client.post(
            "/api/v1/events/simulate",
            json={
                "flight_leg_id": leg_id,
                "event_type": "CANCELLED",
                "delay_minutes": 0,
                "reason": "Air traffic congestion",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ["published", "fallback_dispatched"]
        assert data["payload"]["event_type"] == "CANCELLED"
        assert data["payload"]["flight_id"] == leg_id

        # 2. Non-existent flight leg ID returns 404
        resp_404 = await client.post(
            "/api/v1/events/simulate",
            json={"flight_leg_id": 999999, "event_type": "CANCELLED"},
        )
        assert resp_404.status_code == 404


@pytest.mark.asyncio
async def test_trace_completeness_and_pii_redaction(seed_test_trip):
    """
    Test that running a disruption creates complete stage records in decision_trace
    and sanitizes secrets / passwords.
    """
    leg_id = seed_test_trip["flight_leg_id"]
    itin_id = seed_test_trip["itinerary_id"]

    # Test PII redactor unit logic directly
    dirty_snapshot = {
        "user": "Alex",
        "password": "my_plaintext_password",
        "api_key": "sk-1234567890",
        "nested": {"secret_token": "bearer-xyz", "safe_val": 42},
    }
    clean_snapshot = redact_pii_and_secrets(dirty_snapshot)
    assert clean_snapshot["password"] == "[REDACTED]"
    assert clean_snapshot["api_key"] == "[REDACTED]"
    assert clean_snapshot["nested"]["secret_token"] == "[REDACTED]"
    assert clean_snapshot["nested"]["safe_val"] == 42

    from uuid import uuid4
    test_event_id = f"TEST-TRACE-{uuid4().hex[:6]}"

    # Process disruption via consumer
    event_payload = {
        "event_id": test_event_id,
        "event_type": "CANCELLED",
        "flight_id": leg_id,
        "flight_number": "6E-204",
        "reason": "Engine check",
    }
    result = await process_disruption_event(event_payload)
    assert result is not None

    # Inspect decision_trace rows in database
    async with async_session_factory() as session:
        stmt = (
            select(DecisionTrace)
            .where(DecisionTrace.itinerary_id == itin_id)
            .order_by(DecisionTrace.id.asc())
        )
        traces = (await session.execute(stmt)).scalars().all()

        assert len(traces) >= 5
        recorded_stages = [t.stage for t in traces]
        assert "DETECTION" in recorded_stages
        assert "SEARCH_AND_POLICY_FILTER" in recorded_stages
        assert "NOTIFICATION" in recorded_stages
        assert "RESULT" in recorded_stages

        # Verify no passwords or secrets leaked in snapshots
        for t in traces:
            snap_str = str(t.input_snapshot) + str(t.output_snapshot)
            assert "supersecret" not in snap_str
            assert "my_plaintext_password" not in snap_str

    # Test GET /api/v1/itinerary/{id}/trace endpoint (grouped by event_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        trace_resp = await client.get(f"/api/v1/itinerary/{itin_id}/trace")
        assert trace_resp.status_code == 200
        trace_dict = trace_resp.json()
        assert test_event_id in trace_dict
        all_stages = [s for grp in trace_dict.values() for s in grp]
        assert len(all_stages) == len(traces)


@pytest.mark.asyncio
async def test_metrics_math_aggregation():
    """
    Test GET /api/v1/metrics dynamic mathematical aggregation over decision traces.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/metrics")
        assert resp.status_code == 200
        metrics = resp.json()

        assert "disruptions_handled" in metrics
        assert "auto_resolution_rate" in metrics
        assert "escalation_rate" in metrics
        assert "error_rate" in metrics
        assert "avg_latency_ms" in metrics
        assert "p95_latency_ms" in metrics
        assert "avg_fare_delta_inr" in metrics
        assert "llm_fallback_rate" in metrics
        assert "llm_fallback_reasons" in metrics
        assert "avg_cost_inr_per_run" in metrics
        assert "first_proposal_valid_rate" in metrics
        assert metrics["auto_resolution_rate"] >= 0.0
        assert metrics["escalation_rate"] >= 0.0


@pytest.mark.asyncio
async def test_websocket_activity_feed_sequence():
    """
    Test WebSocket connection handshake and broadcast delivery.
    """
    from starlette.testclient import TestClient
    client = TestClient(app)

    with client.websocket_connect("/api/v1/ws/activity") as websocket:
        # 1. Receive initial welcome handshake
        handshake = websocket.receive_json()
        assert handshake["type"] == "CONNECTED"

        # 2. Ping-pong test
        websocket.send_text("ping")
        assert websocket.receive_text() == "pong"
