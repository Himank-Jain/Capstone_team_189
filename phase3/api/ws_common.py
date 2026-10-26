from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket

alert_clients: List["WebSocket"] = []
# Tenants each socket may receive. None means unrestricted (legacy header mode).
client_tenants: Dict[int, Optional[Set[str]]] = {}


def register_client(websocket: "WebSocket", tenants: Optional[Set[str]]) -> None:
    alert_clients.append(websocket)
    client_tenants[id(websocket)] = tenants


def unregister_client(websocket: "WebSocket") -> None:
    try:
        alert_clients.remove(websocket)
    except ValueError:
        pass
    client_tenants.pop(id(websocket), None)


async def broadcast_alert(message: Dict[str, Any]) -> None:
    """Send a message to every socket allowed to see the message's tenant."""
    tenant_id = message.get("tenant_id")
    dead_clients = []
    for ws in list(alert_clients):
        allowed = client_tenants.get(id(ws))
        if tenant_id is not None and allowed is not None and tenant_id not in allowed:
            continue
        try:
            await ws.send_json(message)
        except Exception:
            dead_clients.append(ws)
    for ws in dead_clients:
        unregister_client(ws)
