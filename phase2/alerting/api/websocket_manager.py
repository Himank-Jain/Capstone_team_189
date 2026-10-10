"""
phase2/alerting/api/websocket_manager.py
==========================================
P2-M14  Explainable Alert API — ConnectionManager
CAPSTONE-189

Backs the /alerts/stream WebSocket endpoint (ticket: "capstone bonus —
implement it after all delivery channels work"). Broadcasts each
dispatched alert to every currently-connected dashboard client.

Design notes
------------
1. Dead-connection cleanup on broadcast failure. A client that
   disconnected without a clean close handshake (browser tab closed,
   network drop) will fail on the next send, not the next receive.
   broadcast() catches per-connection send failures and removes that
   connection from the active set rather than letting one dead client
   break the broadcast to everyone else — the same
   "one channel's failure must not block the others" principle
   dispatcher.py applies to notifiers, applied here to WS fan-out.
"""

from __future__ import annotations

import logging
from typing import Any, List

logger_obj: logging.Logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._active_connections: List[Any] = []

    async def connect(self, websocket: Any) -> None:
        await websocket.accept()
        self._active_connections.append(websocket)

    def disconnect(self, websocket: Any) -> None:
        if websocket in self._active_connections:
            self._active_connections.remove(websocket)

    async def broadcast(self, message: str) -> None:
        dead_connections = []
        for connection in self._active_connections:
            try:
                await connection.send_text(message)
            except Exception as exc:  # noqa: BLE001 -- one dead client must not break the rest
                logger_obj.debug("[ConnectionManager] dropping dead connection: %s", exc)
                dead_connections.append(connection)
        for connection in dead_connections:
            self.disconnect(connection)

    @property
    def n_connections(self) -> int:
        return len(self._active_connections)
