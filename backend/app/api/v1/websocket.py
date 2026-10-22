"""
WebSocket Activity Stream Endpoint.

Streams real-time concierge actions:
`ws://.../api/v1/ws/activity`
Delivers immediate updates for background poll checks, disruption triggers,
decision trace stages, and final rebooking executions without manual browser refreshes.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.activity_feed import activity_feed

router = APIRouter(prefix="/ws", tags=["WebSocket Activity Feed"])


@router.websocket("/activity")
async def activity_websocket_endpoint(websocket: WebSocket):
    """
    WebSocket connection endpoint for real-time frontend activity streaming.
    """
    await activity_feed.connect(websocket)
    try:
        # Send initial connection handshake event
        await websocket.send_json({
            "type": "CONNECTED",
            "message": "Connected to ReRoute real-time activity stream.",
        })
        while True:
            # Keep listener alive, listen for any client pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await activity_feed.disconnect(websocket)
    except Exception:
        await activity_feed.disconnect(websocket)
