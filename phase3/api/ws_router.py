import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .ws_common import alert_clients
from .ws_heartbeat import build_stage_heartbeat

router = APIRouter()


@router.websocket("/ws/heartbeat")
async def heartbeat_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    alert_clients.append(websocket)
    try:
        while True:
            heartbeat = build_stage_heartbeat("encoding", "vol-0a12")
            await websocket.send_json(heartbeat)
            # Send heartbeat every 30 seconds (was 5) to reduce UI flickering
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        return
    finally:
        try:
            alert_clients.remove(websocket)
        except ValueError:
            pass
