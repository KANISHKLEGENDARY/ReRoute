"""
WebSocket Activity Feed Manager for ReRoute.

Manages active WebSocket client connections and broadcasts live updates for:
- Routine flight poll checks
- Ingested disruption events
- Pipeline stage decision traces
- Final rebooking actions
"""

import asyncio
import json
import logging
from typing import Any, Dict, Set
from fastapi import WebSocket

logger = logging.getLogger("reroute.activity_feed")


class ActivityFeedManager:
    """
    Singleton connection manager broadcasting real-time activity events.
    """

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)
        logger.info("[WS] Client connected. Active clients: %d", len(self.active_connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self.active_connections.discard(websocket)
        logger.info("[WS] Client disconnected. Active clients: %d", len(self.active_connections))

    async def broadcast(self, event_type: str, data: Dict[str, Any]) -> None:
        message = json.dumps({"type": event_type, "data": data})
        async with self._lock:
            dead_connections = set()
            for connection in self.active_connections:
                try:
                    await connection.send_text(message)
                except Exception:
                    dead_connections.add(connection)
            for dead in dead_connections:
                self.active_connections.discard(dead)


# Global singleton instance
activity_feed = ActivityFeedManager()
