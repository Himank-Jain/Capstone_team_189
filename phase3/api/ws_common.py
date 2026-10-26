from typing import Any, Dict, List

from fastapi import WebSocket

alert_clients: List["WebSocket"] = []


async def broadcast_alert(message: Dict[str, Any]) -> None:
    dead_clients = []
    for ws in alert_clients:
        try:
            await ws.send_json(message)
        except Exception:
            dead_clients.append(ws)
    for ws in dead_clients:
        try:
            alert_clients.remove(ws)
        except ValueError:
            pass
