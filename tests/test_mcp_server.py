"""
Unit tests for ReRoute MCP Server.

Verifies:
1. Tool successfully fetches and formats data via mock HTTP transport.
2. Input validation strictly rejects invalid event types before network dispatch.
3. Network connection errors result in clear, user-friendly backend-down messages.
"""

import json
import sys
from pathlib import Path
import httpx
import pytest

# Ensure repository root is on sys.path for direct test invocation
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_server.server import (
    get_event_trace,
    get_metrics,
    list_recent_events,
    set_transport,
    simulate_disruption,
)


@pytest.mark.asyncio
async def test_tool_returns_data():
    """Verify tool executes request via transport and returns formatted JSON data."""
    def handler(request: httpx.Request) -> httpx.Response:
        if "/api/v1/metrics" in str(request.url):
            return httpx.Response(200, json={"disruptions_handled": 42, "auto_resolution_rate": 0.88})
        if "/api/v1/events" in str(request.url):
            return httpx.Response(200, json=[{
                "event_id": "EVT-001",
                "itinerary_id": 10,
                "disruption_type": "CANCELLED",
                "action": "REBOOKED",
                "policy_verdict": "APPROVED",
                "latency_ms": 120.5,
                "fare_delta_inr": 450.0,
            }])
        return httpx.Response(404, json={"detail": "Not found"})

    set_transport(httpx.MockTransport(handler))
    try:
        metrics_res = await get_metrics()
        metrics = json.loads(metrics_res)
        assert metrics["disruptions_handled"] == 42
        assert metrics["auto_resolution_rate"] == 0.88

        events_res = await list_recent_events(limit=5)
        events = json.loads(events_res)
        assert len(events) == 1
        assert events[0]["event_id"] == "EVT-001"
        assert events[0]["action"] == "REBOOKED"
        assert events[0]["latency_ms"] == 120.5
    finally:
        set_transport(None)


@pytest.mark.asyncio
async def test_input_validation_rejects_bad_event_type():
    """Verify simulate_disruption rejects invalid event types without network call."""
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"status": "published"})

    set_transport(httpx.MockTransport(handler))
    try:
        res = await simulate_disruption(flight_leg_id=1, event_type="INVALID_TYPE")
        assert "Error: event_type must be one of CANCELLED, DELAYED, MISSED_CONNECTION" in res
        assert called is False, "HTTP call should not be made when input validation fails"

        res_case = await simulate_disruption(flight_leg_id=1, event_type="diverted")
        assert "Error: event_type must be one of CANCELLED, DELAYED, MISSED_CONNECTION" in res_case
        assert called is False
    finally:
        set_transport(None)


@pytest.mark.asyncio
async def test_backend_down_message():
    """Verify unreachable backend produces clear error text without leaking secrets."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused by target machine", request=request)

    set_transport(httpx.MockTransport(handler))
    try:
        res = await get_metrics()
        assert "Error: Backend service is unreachable" in res
        assert "Ensure FastAPI is running" in res

        trace_res = await get_event_trace("EVT-999")
        assert "Error: Backend service is unreachable" in trace_res
    finally:
        set_transport(None)
