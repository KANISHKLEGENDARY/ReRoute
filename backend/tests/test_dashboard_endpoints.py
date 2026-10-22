"""
Tests for Dashboard API Endpoints:
1. GET /api/v1/events (recent events from RESULT rows)
2. GET /api/v1/events/{event_id} (all trace stages + result)
3. POST /api/v1/events/simulate with X-Demo-Key enforcement
"""

import os
from datetime import datetime, timezone
from unittest.mock import patch
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import create_application
from app.core.database import async_session_factory, init_db
from app.models.user import User
from app.models.itinerary import Itinerary
from app.models.flight_leg import FlightLeg
from app.models.trace import DecisionTrace

app = create_application()


@pytest.fixture
async def setup_events_data():
    """Initializes tables and seeds a user, itinerary, flight leg, and decision trace rows."""
    await init_db()
    async with async_session_factory() as session:
        user = User(
            name="Dashboard Test User",
            email=f"dash_{datetime.utcnow().timestamp()}@reroute.travel",
            phone="+919999999999",
            password_hash="testhash123",
        )
        session.add(user)
        await session.flush()

        itinerary = Itinerary(user_id=user.id, status="ACTIVE")
        session.add(itinerary)
        await session.flush()

        flight_leg = FlightLeg(
            itinerary_id=itinerary.id,
            leg_order=1,
            airline_code="6E",
            flight_number="204",
            pnr="PNR-DASH-1",
            origin="DEL",
            destination="BOM",
            departure_datetime=datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc),
            arrival_datetime=datetime(2026, 10, 20, 12, 15, tzinfo=timezone.utc),
            cabin_class="ECONOMY",
            fare_paid=5000.0,
            currency="INR",
            status="CONFIRMED",
        )
        session.add(flight_leg)
        await session.flush()

        # Seed traces for event EVT-DASH-001
        event_id = "EVT-DASH-001"
        trace_detect = DecisionTrace(
            event_id=event_id,
            itinerary_id=itinerary.id,
            stage="DETECTION",
            input_snapshot={"event_type": "CANCELLED"},
            output_snapshot={"detected": True},
        )
        trace_result = DecisionTrace(
            event_id=event_id,
            itinerary_id=itinerary.id,
            stage="RESULT",
            input_snapshot={"event_id": event_id},
            output_snapshot={
                "action": "REBOOKED",
                "policy_verdict": "APPROVED",
                "fare_delta_inr": -180.0,
                "latency_ms": 45.2,
                "tokens_in": 512,
                "tokens_out": 68,
                "cost_usd": 0.000052,
                "cost_inr": 0.01,
                "cost_estimated": False,
                "llm_fallback": False,
                "llm_fallback_reason": "none",
            },
        )
        session.add_all([trace_detect, trace_result])
        await session.commit()

        return {
            "flight_leg_id": flight_leg.id,
            "event_id": event_id,
            "itinerary_id": itinerary.id,
        }


@pytest.mark.asyncio
async def test_events_list_endpoint(setup_events_data):
    """Test GET /api/v1/events returns recent events list ordered newest first."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/events?limit=10")
        assert resp.status_code == 200
        events = resp.json()
        assert isinstance(events, list)
        assert len(events) >= 1

        matched = [e for e in events if e["event_id"] == setup_events_data["event_id"]]
        assert len(matched) == 1
        evt = matched[0]
        assert evt["action"] == "REBOOKED"
        assert evt["policy_verdict"] == "APPROVED"
        assert evt["fare_delta_inr"] == -180.0


@pytest.mark.asyncio
async def test_event_detail_endpoint(setup_events_data):
    """Test GET /api/v1/events/{event_id} returns all stages and final result snapshot."""
    event_id = setup_events_data["event_id"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/events/{event_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["event_id"] == event_id
        assert len(data["stages"]) >= 2
        stage_names = [s["stage"] for s in data["stages"]]
        assert "DETECTION" in stage_names
        assert "RESULT" in stage_names
        assert data["result"]["action"] == "REBOOKED"

        # 404 for non-existent event
        notFound = await client.get("/api/v1/events/EVT-NON-EXISTENT")
        assert notFound.status_code == 404


@pytest.mark.asyncio
async def test_simulate_demo_key_required_when_set(setup_events_data):
    """Test POST /api/v1/events/simulate requires X-Demo-Key when DEMO_API_KEY is configured."""
    transport = ASGITransport(app=app)
    flight_leg_id = setup_events_data["flight_leg_id"]
    body = {"flight_leg_id": flight_leg_id, "event_type": "CANCELLED"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Case 1: DEMO_API_KEY is set in environment
        with patch.dict(os.environ, {"DEMO_API_KEY": "demo-secret-key-123"}):
            # Missing header -> 401
            resp_missing = await client.post("/api/v1/events/simulate", json=body)
            assert resp_missing.status_code == 401

            # Wrong header -> 401
            resp_wrong = await client.post(
                "/api/v1/events/simulate",
                json=body,
                headers={"X-Demo-Key": "wrong-key"},
            )
            assert resp_wrong.status_code == 401

            # Correct header -> 200
            resp_ok = await client.post(
                "/api/v1/events/simulate",
                json=body,
                headers={"X-Demo-Key": "demo-secret-key-123"},
            )
            assert resp_ok.status_code == 200
            assert resp_ok.json()["status"] in ["published", "fallback_dispatched"]

        # Case 2: DEMO_API_KEY is unset/empty -> allows without header
        with patch.dict(os.environ, {"DEMO_API_KEY": ""}):
            resp_no_gate = await client.post("/api/v1/events/simulate", json=body)
            assert resp_no_gate.status_code == 200
