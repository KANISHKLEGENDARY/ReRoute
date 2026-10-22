"""
MCP Server for ReRoute Travel-Disruption Concierge.

Exposes ReRoute observability and simulation tools to MCP clients (Claude Desktop,
MCP Inspector) over stdio. This is a thin HTTP wrapper over the existing FastAPI
endpoints, maintaining complete separation from pipeline logic and database access.
"""

import json
import os
from typing import Any, Optional
import httpx

# Official MCP SDK: MCPServer in mcp >= 2.0.0, FastMCP in mcp 1.x
try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer

mcp = MCPServer("reroute-mcp")

# Optional transport override for testing without live network
_transport: Optional[httpx.BaseTransport] = None


def set_transport(transport: Optional[httpx.BaseTransport]) -> None:
    """Configures custom transport for isolated unit testing."""
    global _transport
    _transport = transport


async def _request(
    method: str,
    path: str,
    params: Optional[dict] = None,
    json_data: Optional[dict] = None,
) -> tuple[Any, Optional[str]]:
    """Helper executing HTTP requests to backend without exposing secrets in logs."""
    backend_url = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")
    demo_key = os.environ.get("DEMO_API_KEY", "")
    headers = {"Content-Type": "application/json"}
    if demo_key:
        headers["X-Demo-Key"] = demo_key

    url = f"{backend_url}{path}"
    try:
        async with httpx.AsyncClient(transport=_transport, timeout=10.0) as client:
            resp = await client.request(method, url, params=params, json=json_data, headers=headers)
            if resp.status_code >= 400:
                detail = resp.text
                try:
                    detail = resp.json().get("detail", resp.text)
                except Exception:
                    pass
                return None, f"Error: Request failed with status {resp.status_code}: {detail}"
            return resp.json(), None
    except httpx.RequestError:
        return None, f"Error: Backend service is unreachable at {backend_url}. Ensure FastAPI is running."
    except Exception as exc:
        return None, f"Error: {str(exc)}"


@mcp.tool(description="Returns system metrics including disruptions handled, auto-resolution rate, and latency.")
async def get_metrics() -> str:
    """Retrieve aggregate performance and operational metrics from the backend."""
    data, err = await _request("GET", "/api/v1/metrics")
    return err if err else json.dumps(data, indent=2)


@mcp.tool(description="Lists recent disruption events with action, flight, and latency (limit up to 50).")
async def list_recent_events(limit: int = 10) -> str:
    """Fetch recent disruption outcomes formatted as a compact summary."""
    safe_limit = max(1, min(int(limit), 50))
    data, err = await _request("GET", "/api/v1/events", params={"limit": safe_limit})
    if err:
        return err

    events = [
        {
            "event_id": e.get("event_id"),
            "flight": e.get("itinerary_id"),
            "disruption": e.get("disruption_type"),
            "action": e.get("action"),
            "verdict": e.get("policy_verdict"),
            "latency_ms": e.get("latency_ms"),
            "fare_delta_inr": e.get("fare_delta_inr"),
        }
        for e in (data if isinstance(data, list) else [])
    ]
    return json.dumps(events, indent=2)


@mcp.tool(description="Returns the stage-by-stage execution trace and final result for a specific event.")
async def get_event_trace(event_id: str) -> str:
    """Inspect full decision trace stages and rationale for an event ID."""
    clean_id = str(event_id).strip()
    if not clean_id:
        return "Error: event_id is required."
    data, err = await _request("GET", f"/api/v1/events/{clean_id}")
    return err if err else json.dumps(data, indent=2)


@mcp.tool(description="Triggers a sandbox disruption event (CANCELLED, DELAYED, MISSED_CONNECTION) for a flight leg.")
async def simulate_disruption(flight_leg_id: int, event_type: str, notice_text: str = "") -> str:
    """Dispatches a synthetic disruption into the sandbox event queue."""
    clean_type = str(event_type).strip().upper()
    if clean_type not in {"CANCELLED", "DELAYED", "MISSED_CONNECTION"}:
        return "Error: event_type must be one of CANCELLED, DELAYED, MISSED_CONNECTION."

    payload = {
        "flight_leg_id": int(flight_leg_id),
        "event_type": clean_type,
        "notice_text": str(notice_text)[:500] if notice_text else None,
    }
    data, err = await _request("POST", "/api/v1/events/simulate", json_data=payload)
    return err if err else json.dumps(data, indent=2)


if __name__ == "__main__":
    # Runs the server using stdio transport for Claude Desktop / MCP Inspector
    mcp.run(transport="stdio")
