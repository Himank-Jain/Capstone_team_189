import asyncio
from typing import Optional, Set

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from phase3.db.models import TenantMembershipRow

from .routers import _support
from .ws_common import register_client, unregister_client
from .ws_heartbeat import build_stage_heartbeat

router = APIRouter()


def _allowed_tenants(token: Optional[str]) -> Optional[Set[str]]:
    """Tenants a socket may receive alerts for.

    With a valid token: the caller's memberships. Without one: nothing when
    sign-in is required (heartbeats only), everything in legacy header mode.
    """
    if token:
        try:
            user_id = _support.user_id_from_token(token)
        except HTTPException:
            return set()
        with _support.platform_session_factory.session_scope() as session:
            rows = session.query(TenantMembershipRow).filter_by(user_id=user_id).all()
            return {row.tenant_id for row in rows}
    return set() if _support.auth_required() else None


@router.websocket("/ws/heartbeat")
async def heartbeat_stream(websocket: WebSocket, token: Optional[str] = None) -> None:
    await websocket.accept()
    register_client(websocket, _allowed_tenants(token))
    try:
        while True:
            heartbeat = build_stage_heartbeat("encoding", "vol-0a12")
            await websocket.send_json(heartbeat)
            # Send heartbeat every 30 seconds (was 5) to reduce UI flickering
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        return
    finally:
        unregister_client(websocket)
