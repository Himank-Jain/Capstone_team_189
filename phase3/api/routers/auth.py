"""Account registration, sign-in, session identity, and tenant member management."""

from __future__ import annotations

import os
import re
import uuid
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from phase3.db.models import TenantMembershipRow, TenantRow, UserRow
from phase3.shared.exceptions import DuplicateUserError, InvalidCredentialsError
from phase3.shared.types import Role

from . import _support
from ._support import (
    LEGACY_DEMO_USER_ID,
    TENANT_CONNECTIONS,
    current_user_id,
    ensure_demo_tenants,
    get_auth_service,
    require_owner_membership,
    require_tenant_membership,
)

router = APIRouter(tags=["auth"])

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PASSWORD_LENGTH = 8
_MAX_PASSWORD_BYTES = 72  # bcrypt ignores anything past 72 bytes; reject instead.
_ROLE_RANK = {Role.OWNER.value: 3, Role.OPERATOR.value: 2, Role.VIEWER.value: 1}


class Credentials(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., max_length=256)


class MemberCreateRequest(BaseModel):
    email: str = Field(..., max_length=255)
    role: Role = Role.VIEWER


class MemberRoleRequest(BaseModel):
    role: Role


class AdminAccessRequest(BaseModel):
    # NONE removes the account from every demo workspace (the account remains).
    role: Literal["OWNER", "OPERATOR", "VIEWER", "NONE"]


def _normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if not _EMAIL_PATTERN.match(normalized):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    return normalized


def _validate_password(password: str) -> None:
    if len(password) < _MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Password must be at least {_MIN_PASSWORD_LENGTH} characters",
        )
    if len(password.encode("utf-8")) > _MAX_PASSWORD_BYTES:
        raise HTTPException(
            status_code=422, detail=f"Password must be at most {_MAX_PASSWORD_BYTES} bytes"
        )


def _signup_role(is_first_account: bool) -> str:
    if is_first_account:
        return Role.OWNER.value
    configured = os.getenv("CAPSTONE_SIGNUP_ROLE", Role.VIEWER.value).strip().upper()
    return configured if configured in _ROLE_RANK else Role.VIEWER.value


def _memberships_for(user_id: str) -> List[Dict[str, Any]]:
    with _support.platform_session_factory.session_scope() as session:
        rows = (
            session.query(TenantMembershipRow, TenantRow)
            .join(TenantRow, TenantRow.tenant_id == TenantMembershipRow.tenant_id)
            .filter(TenantMembershipRow.user_id == user_id)
            .order_by(TenantRow.name)
            .all()
        )
        return [
            {"tenant_id": tenant.tenant_id, "tenant_name": tenant.name, "role": membership.role}
            for membership, tenant in rows
        ]


# ---------------------------------------------------------------------------
# Administration
# ---------------------------------------------------------------------------
# An administrator is an account that is OWNER of every demo workspace. The
# first registered account becomes one automatically; CAPSTONE_ADMIN_EMAIL /
# CAPSTONE_ADMIN_PASSWORD create or promote one when the API starts; and
# scripts/manage_users.py can promote an existing account from the terminal.


def _workspace_ids() -> List[str]:
    return list(TENANT_CONNECTIONS)


def is_platform_admin(user_id: str) -> bool:
    with _support.platform_session_factory.session_scope() as session:
        roles = {
            row.tenant_id: row.role
            for row in session.query(TenantMembershipRow).filter_by(user_id=user_id).all()
        }
    return all(roles.get(tenant_id) == Role.OWNER.value for tenant_id in _workspace_ids())


def require_platform_admin(user_id: str = Depends(current_user_id)) -> str:
    if not is_platform_admin(user_id):
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user_id


def set_workspace_access(user_id: str, role: Optional[str]) -> None:
    """Give an account one role in every demo workspace (None removes access)."""
    ensure_demo_tenants()
    with _support.platform_session_factory.session_scope() as session:
        if session.get(UserRow, user_id) is None:
            raise HTTPException(status_code=404, detail="Account not found")
        memberships = {
            row.tenant_id: row
            for row in session.query(TenantMembershipRow).filter_by(user_id=user_id).all()
        }
        # Validate everything first so a refusal leaves no partial change.
        for tenant_id in _workspace_ids():
            current = memberships.get(tenant_id)
            losing_owner = current is not None and current.role == Role.OWNER.value and role != Role.OWNER.value
            if losing_owner and _owner_count(session, tenant_id) <= 1:
                raise HTTPException(
                    status_code=409,
                    detail=f"Workspace {tenant_id} needs at least one owner",
                )
        for tenant_id in _workspace_ids():
            current = memberships.get(tenant_id)
            if role is None:
                if current is not None:
                    session.delete(current)
            elif current is None:
                session.add(
                    TenantMembershipRow(
                        membership_id=f"tm-{uuid.uuid4()}",
                        user_id=user_id,
                        tenant_id=tenant_id,
                        role=role,
                    )
                )
            else:
                current.role = role


def ensure_admin_account(email: str, password: Optional[str]) -> tuple[str, bool]:
    """Create (or find) an account and make it OWNER of every demo workspace.

    Returns (user_id, created). An existing account keeps its password.
    """
    normalized = _normalize_email(email)
    ensure_demo_tenants()
    with _support.platform_session_factory.session_scope() as session:
        row = session.query(UserRow).filter_by(email=normalized).one_or_none()
        user_id = row.user_id if row is not None else None
    created = False
    if user_id is None:
        if not password:
            raise HTTPException(status_code=422, detail="A password is required to create the admin")
        _validate_password(password)
        user_id = get_auth_service().register(normalized, password).user_id
        created = True
    set_workspace_access(user_id, Role.OWNER.value)
    return user_id, created


def bootstrap_admin_from_env() -> Optional[str]:
    """Create/promote the admin named by CAPSTONE_ADMIN_EMAIL at API start."""
    email = os.getenv("CAPSTONE_ADMIN_EMAIL", "").strip()
    if not email:
        return None
    try:
        user_id, created = ensure_admin_account(email, os.getenv("CAPSTONE_ADMIN_PASSWORD", ""))
    except HTTPException as exc:
        print(f"[auth] Could not set up admin {email}: {exc.detail}")
        return None
    print(
        f"[auth] Admin account {'created' if created else 'confirmed'}: {email} "
        "(owner of every demo workspace)"
        + ("" if created else "; its existing password was left unchanged")
    )
    return user_id


def _session_payload(user_id: str, access_token: Optional[str] = None) -> Dict[str, Any]:
    with _support.platform_session_factory.session_scope() as session:
        row = session.get(UserRow, user_id)
        if row is None:
            raise HTTPException(status_code=401, detail="Account no longer exists")
        email = row.email
    memberships = _memberships_for(user_id)
    highest_role = max(
        (item["role"] for item in memberships),
        key=lambda role: _ROLE_RANK.get(role, 0),
        default=None,
    )
    payload: Dict[str, Any] = {
        "user": {
            "user_id": user_id,
            "email": email,
            "role": highest_role,
            "is_admin": is_platform_admin(user_id),
        },
        "memberships": memberships,
    }
    if access_token is not None:
        auth_service = get_auth_service()
        payload.update(
            {
                "access_token": access_token,
                "token_type": "bearer",
                "expires_in": auth_service.token_ttl_seconds,
            }
        )
    return payload


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(payload: Credentials) -> Dict[str, Any]:
    email = _normalize_email(payload.email)
    _validate_password(payload.password)
    ensure_demo_tenants()
    with _support.platform_session_factory.session_scope() as session:
        existing_accounts = (
            session.query(UserRow).filter(UserRow.user_id != LEGACY_DEMO_USER_ID).count()
        )
    auth_service = get_auth_service()
    try:
        user = auth_service.register(email, payload.password)
    except DuplicateUserError as exc:
        raise HTTPException(
            status_code=409, detail="An account with this email already exists"
        ) from exc

    role = _signup_role(is_first_account=existing_accounts == 0)
    with _support.platform_session_factory.session_scope() as session:
        for tenant_id in TENANT_CONNECTIONS:
            session.add(
                TenantMembershipRow(
                    membership_id=f"tm-{uuid.uuid4()}",
                    user_id=user.user_id,
                    tenant_id=tenant_id,
                    role=role,
                )
            )
    return _session_payload(user.user_id, auth_service.issue_token(user.user_id))


@router.post("/auth/login")
def login(payload: Credentials) -> Dict[str, Any]:
    auth_service = get_auth_service()
    try:
        token = auth_service.login(payload.email, payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    user_id = str(auth_service.verify_token(token)["sub"])
    return _session_payload(user_id, token)


@router.get("/auth/me")
def me(user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    return _session_payload(user_id)


@router.get("/tenants")
def list_my_tenants(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
) -> List[Dict[str, Any]]:
    """Tenants the signed-in user belongs to (all demo tenants in legacy mode)."""
    ensure_demo_tenants()
    if not _support.auth_required() and not authorization and not x_user_id:
        memberships = None
    else:
        memberships = {
            item["tenant_id"]: item
            for item in _memberships_for(_support.resolve_request_user(authorization, x_user_id))
        }
    with _support.platform_session_factory.session_scope() as session:
        tenants = (
            session.query(TenantRow)
            .filter(TenantRow.tenant_id.in_(list(TENANT_CONNECTIONS)))
            .order_by(TenantRow.name)
            .all()
        )
        result = []
        for tenant in tenants:
            if memberships is not None and tenant.tenant_id not in memberships:
                continue
            result.append(
                {
                    "id": tenant.tenant_id,
                    "name": tenant.name,
                    "live_alert_count": 0,
                    "health": "healthy",
                    "role": memberships[tenant.tenant_id]["role"] if memberships else None,
                }
            )
    return result


def _member_rows(session, tenant_id: str):
    return (
        session.query(TenantMembershipRow, UserRow)
        .join(UserRow, UserRow.user_id == TenantMembershipRow.user_id)
        .filter(TenantMembershipRow.tenant_id == tenant_id)
        .order_by(UserRow.email)
        .all()
    )


def _owner_count(session, tenant_id: str) -> int:
    return (
        session.query(TenantMembershipRow)
        .filter_by(tenant_id=tenant_id, role=Role.OWNER.value)
        .count()
    )


def _member_payload(membership: TenantMembershipRow, user: UserRow) -> Dict[str, Any]:
    return {
        "user_id": user.user_id,
        "email": user.email,
        "role": membership.role,
        "joined_at": membership.created_at,
    }


@router.get("/members", dependencies=[Depends(require_tenant_membership)])
def list_members(tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id")):
    resolved_tenant = _support._tenant_header(tenant_id)
    with _support.platform_session_factory.session_scope() as session:
        return [
            _member_payload(membership, user)
            for membership, user in _member_rows(session, resolved_tenant)
            if user.user_id != LEGACY_DEMO_USER_ID
        ]


@router.post("/members", status_code=status.HTTP_201_CREATED)
def add_member(
    payload: MemberCreateRequest,
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    _owner: str = Depends(require_owner_membership),
) -> Dict[str, Any]:
    resolved_tenant = _support._tenant_header(tenant_id)
    email = _normalize_email(payload.email)
    with _support.platform_session_factory.session_scope() as session:
        user = session.query(UserRow).filter_by(email=email).one_or_none()
        if user is None:
            raise HTTPException(
                status_code=404,
                detail="No account uses that email yet; ask them to register first",
            )
        existing = (
            session.query(TenantMembershipRow)
            .filter_by(user_id=user.user_id, tenant_id=resolved_tenant)
            .one_or_none()
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="That user is already a member")
        membership = TenantMembershipRow(
            membership_id=f"tm-{uuid.uuid4()}",
            user_id=user.user_id,
            tenant_id=resolved_tenant,
            role=payload.role.value,
        )
        session.add(membership)
        session.flush()
        return _member_payload(membership, user)


@router.patch("/members/{member_user_id}")
def change_member_role(
    member_user_id: str,
    payload: MemberRoleRequest,
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    _owner: str = Depends(require_owner_membership),
) -> Dict[str, Any]:
    resolved_tenant = _support._tenant_header(tenant_id)
    with _support.platform_session_factory.session_scope() as session:
        membership = (
            session.query(TenantMembershipRow)
            .filter_by(user_id=member_user_id, tenant_id=resolved_tenant)
            .one_or_none()
        )
        if membership is None:
            raise HTTPException(status_code=404, detail="Member not found")
        if (
            membership.role == Role.OWNER.value
            and payload.role != Role.OWNER
            and _owner_count(session, resolved_tenant) <= 1
        ):
            raise HTTPException(
                status_code=409, detail="A workspace needs at least one owner"
            )
        membership.role = payload.role.value
        user = session.get(UserRow, member_user_id)
        return _member_payload(membership, user)


@router.delete("/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    member_user_id: str,
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    _owner: str = Depends(require_owner_membership),
) -> None:
    resolved_tenant = _support._tenant_header(tenant_id)
    with _support.platform_session_factory.session_scope() as session:
        membership = (
            session.query(TenantMembershipRow)
            .filter_by(user_id=member_user_id, tenant_id=resolved_tenant)
            .one_or_none()
        )
        if membership is None:
            raise HTTPException(status_code=404, detail="Member not found")
        if membership.role == Role.OWNER.value and _owner_count(session, resolved_tenant) <= 1:
            raise HTTPException(
                status_code=409, detail="A workspace needs at least one owner"
            )
        session.delete(membership)


def _account_rows() -> List[Dict[str, Any]]:
    with _support.platform_session_factory.session_scope() as session:
        users = (
            session.query(UserRow)
            .filter(UserRow.user_id != LEGACY_DEMO_USER_ID)
            .order_by(UserRow.email)
            .all()
        )
        tenants = {row.tenant_id: row.name for row in session.query(TenantRow).all()}
        memberships: Dict[str, List[Dict[str, Any]]] = {}
        for row in session.query(TenantMembershipRow).all():
            memberships.setdefault(row.user_id, []).append(
                {"tenant_id": row.tenant_id, "tenant_name": tenants.get(row.tenant_id, row.tenant_id), "role": row.role}
            )
        result = []
        for user in users:
            items = sorted(memberships.get(user.user_id, []), key=lambda item: item["tenant_name"])
            roles = {item["tenant_id"]: item["role"] for item in items}
            result.append(
                {
                    "user_id": user.user_id,
                    "email": user.email,
                    "created_at": user.created_at,
                    "memberships": items,
                    "is_admin": all(
                        roles.get(tenant_id) == Role.OWNER.value for tenant_id in _workspace_ids()
                    ),
                }
            )
        return result


@router.get("/admin/users")
def admin_list_users(_admin: str = Depends(require_platform_admin)) -> List[Dict[str, Any]]:
    return _account_rows()


@router.put("/admin/users/{target_user_id}/access")
def admin_set_access(
    target_user_id: str,
    payload: AdminAccessRequest,
    admin_user_id: str = Depends(require_platform_admin),
) -> Dict[str, Any]:
    if target_user_id == admin_user_id and payload.role != Role.OWNER.value:
        raise HTTPException(status_code=409, detail="You can't remove your own admin access")
    set_workspace_access(target_user_id, None if payload.role == "NONE" else payload.role)
    return next(item for item in _account_rows() if item["user_id"] == target_user_id)


__all__ = [
    "bootstrap_admin_from_env",
    "ensure_admin_account",
    "is_platform_admin",
    "router",
    "set_workspace_access",
]
