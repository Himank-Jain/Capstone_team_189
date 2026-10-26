"""End-to-end checks for registration, sign-in, token identity, and member roles."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from phase3.api.app import app
from phase3.api.routers import _support
from phase3.db.models import Base, IncidentRow, TenantMembershipRow, UserRow
from phase3.db.session import PlatformSessionFactory

SECRET = "test-secret-that-is-definitely-longer-than-32-bytes"
PASSWORD = "Corr3ct-Horse!"


@pytest.fixture
def client(tmp_path, monkeypatch):
    factory = PlatformSessionFactory({"database_url": f"sqlite:///{tmp_path / 'auth.db'}"})
    Base.metadata.create_all(factory.build_engine())
    monkeypatch.setattr(_support, "platform_session_factory", factory)
    monkeypatch.setenv("CAPSTONE_AUTH_REQUIRED", "true")
    monkeypatch.setenv("PLATFORM_JWT_SECRET", SECRET)
    monkeypatch.setenv("PLATFORM_BCRYPT_ROUNDS", "4")
    monkeypatch.delenv("CAPSTONE_SIGNUP_ROLE", raising=False)
    _support.reset_auth_service()
    with TestClient(app) as test_client:
        yield test_client, factory
    _support.reset_auth_service()


def _register(client, email):
    response = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return response.json()


def _headers(session, tenant_id="google"):
    return {"Authorization": f"Bearer {session['access_token']}", "X-Tenant-Id": tenant_id}


def test_first_account_owns_demo_workspaces_and_later_accounts_are_viewers(client):
    test_client, _ = client
    owner = _register(test_client, "Owner@Example.com")
    viewer = _register(test_client, "viewer@example.com")

    assert owner["user"]["email"] == "owner@example.com"
    assert {m["role"] for m in owner["memberships"]} == {"OWNER"}
    assert {m["role"] for m in viewer["memberships"]} == {"VIEWER"}
    assert len(owner["memberships"]) == 5

    me = test_client.get("/auth/me", headers=_headers(viewer))
    assert me.status_code == 200
    assert me.json()["user"]["user_id"] == viewer["user"]["user_id"]


def test_registration_validation_and_duplicates(client):
    test_client, _ = client
    _register(test_client, "dup@example.com")

    duplicate = test_client.post(
        "/auth/register", json={"email": "DUP@example.com", "password": PASSWORD}
    )
    short = test_client.post("/auth/register", json={"email": "a@example.com", "password": "short"})
    bad_email = test_client.post("/auth/register", json={"email": "nope", "password": PASSWORD})

    assert duplicate.status_code == 409
    assert short.status_code == 422
    assert bad_email.status_code == 422


def test_login_requires_correct_password_and_rejects_legacy_demo_identity(client):
    test_client, _ = client
    _register(test_client, "analyst@example.com")
    _support.provision_demo_identity()

    ok = test_client.post("/auth/login", json={"email": "analyst@example.com", "password": PASSWORD})
    wrong = test_client.post(
        "/auth/login", json={"email": "analyst@example.com", "password": "not-the-password"}
    )
    unknown = test_client.post("/auth/login", json={"email": "ghost@example.com", "password": PASSWORD})
    legacy = test_client.post(
        "/auth/login", json={"email": "demo@capstone189.local", "password": "demo-only"}
    )

    assert ok.status_code == 200 and ok.json()["access_token"]
    assert wrong.status_code == 401
    assert unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]
    assert legacy.status_code == 401


def test_tenant_routes_require_a_valid_token(client):
    test_client, _ = client
    session = _register(test_client, "ops@example.com")
    user_id = session["user"]["user_id"]
    expired = jwt.encode(
        {"sub": user_id, "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        SECRET,
        algorithm="HS256",
    )
    forged = jwt.encode({"sub": user_id}, "another-secret-that-is-also-32-bytes-long", "HS256")

    assert test_client.get("/incidents", headers={"X-Tenant-Id": "google"}).status_code == 401
    assert (
        test_client.get(
            "/incidents", headers={"X-Tenant-Id": "google", "X-User-Id": user_id}
        ).status_code
        == 401
    ), "the X-User-Id header alone must not authenticate"
    assert (
        test_client.get(
            "/incidents",
            headers={"X-Tenant-Id": "google", "Authorization": f"Bearer {expired}"},
        ).status_code
        == 401
    )
    assert (
        test_client.get(
            "/incidents",
            headers={"X-Tenant-Id": "google", "Authorization": f"Bearer {forged}"},
        ).status_code
        == 401
    )
    assert test_client.get("/incidents", headers=_headers(session)).status_code == 200
    assert test_client.get("/stats/summary", headers={"X-Tenant-Id": "google"}).status_code == 401


def test_token_cannot_be_paired_with_another_users_id_or_foreign_tenant(client):
    test_client, _ = client
    owner = _register(test_client, "owner@example.com")
    viewer = _register(test_client, "viewer@example.com")

    spoofed = test_client.get(
        "/incidents",
        headers={**_headers(viewer), "X-User-Id": owner["user"]["user_id"]},
    )
    foreign = test_client.get("/incidents", headers=_headers(viewer, tenant_id="tenant-not-mine"))

    assert spoofed.status_code == 403
    assert foreign.status_code == 403


def test_viewer_is_read_only_until_an_owner_promotes_them(client):
    test_client, factory = client
    owner = _register(test_client, "owner@example.com")
    viewer = _register(test_client, "viewer@example.com")
    now = datetime.now(timezone.utc)
    with factory.session_scope() as session:
        session.add(
            IncidentRow(
                incident_id="incident-1",
                tenant_id="google",
                entity_id="vol-g00g",
                severity="HIGH",
                status="OPEN",
                first_seen_at=now,
                last_seen_at=now,
                details={},
            )
        )

    denied = test_client.post("/incidents/incident-1/acknowledge", headers=_headers(viewer))
    assert denied.status_code == 403
    assert (
        test_client.patch(
            f"/members/{owner['user']['user_id']}",
            headers=_headers(viewer),
            json={"role": "VIEWER"},
        ).status_code
        == 403
    )

    promoted = test_client.patch(
        f"/members/{viewer['user']['user_id']}", headers=_headers(owner), json={"role": "OPERATOR"}
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "OPERATOR"

    allowed = test_client.post("/incidents/incident-1/acknowledge", headers=_headers(viewer))
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "ACKNOWLEDGED"


def test_owner_member_management_and_last_owner_protection(client):
    test_client, factory = client
    owner = _register(test_client, "owner@example.com")
    teammate = _register(test_client, "teammate@example.com")

    members = test_client.get("/members", headers=_headers(owner))
    assert members.status_code == 200
    assert {m["email"] for m in members.json()} == {"owner@example.com", "teammate@example.com"}

    removed = test_client.delete(
        f"/members/{teammate['user']['user_id']}", headers=_headers(owner)
    )
    assert removed.status_code == 204
    assert test_client.get("/incidents", headers=_headers(teammate)).status_code == 403
    assert len(test_client.get("/tenants", headers=_headers(teammate)).json()) == 4

    re_added = test_client.post(
        "/members", headers=_headers(owner), json={"email": "teammate@example.com", "role": "OPERATOR"}
    )
    assert re_added.status_code == 201
    assert re_added.json()["role"] == "OPERATOR"
    assert (
        test_client.post(
            "/members", headers=_headers(owner), json={"email": "nobody@example.com", "role": "VIEWER"}
        ).status_code
        == 404
    )

    demote_self = test_client.patch(
        f"/members/{owner['user']['user_id']}", headers=_headers(owner), json={"role": "VIEWER"}
    )
    remove_self = test_client.delete(f"/members/{owner['user']['user_id']}", headers=_headers(owner))
    assert demote_self.status_code == 409
    assert remove_self.status_code == 409


def test_deleted_account_tokens_stop_working(client):
    test_client, factory = client
    session = _register(test_client, "temp@example.com")
    user_id = session["user"]["user_id"]
    with factory.session_scope() as db:
        db.query(TenantMembershipRow).filter_by(user_id=user_id).delete()
        db.query(UserRow).filter_by(user_id=user_id).delete()

    response = test_client.get("/auth/me", headers=_headers(session))
    assert response.status_code == 401


def test_alert_stream_only_delivers_alerts_for_the_users_tenants(client):
    import asyncio

    from phase3.api import ws_common
    from phase3.api.ws_router import _allowed_tenants

    test_client, _ = client
    owner = _register(test_client, "owner@example.com")
    viewer = _register(test_client, "viewer@example.com")
    assert (
        test_client.delete(f"/members/{viewer['user']['user_id']}", headers=_headers(owner)).status_code
        == 204
    )

    class FakeSocket:
        def __init__(self):
            self.messages = []

        async def send_json(self, message):
            self.messages.append(message)

    owner_ws, viewer_ws, anonymous_ws = FakeSocket(), FakeSocket(), FakeSocket()
    ws_common.register_client(owner_ws, _allowed_tenants(owner["access_token"]))
    ws_common.register_client(viewer_ws, _allowed_tenants(viewer["access_token"]))
    ws_common.register_client(anonymous_ws, _allowed_tenants(None))
    try:
        asyncio.run(ws_common.broadcast_alert({"type": "alert", "tenant_id": "google"}))
        asyncio.run(ws_common.broadcast_alert({"type": "stage_heartbeat"}))
    finally:
        for ws in (owner_ws, viewer_ws, anonymous_ws):
            ws_common.unregister_client(ws)

    assert [m["type"] for m in owner_ws.messages] == ["alert", "stage_heartbeat"]
    assert [m["type"] for m in viewer_ws.messages] == ["stage_heartbeat"]
    assert [m["type"] for m in anonymous_ws.messages] == ["stage_heartbeat"]


def test_env_admin_is_created_at_startup_and_can_sign_in(tmp_path, monkeypatch):
    from phase3.api.routers.auth import bootstrap_admin_from_env

    factory = PlatformSessionFactory({"database_url": f"sqlite:///{tmp_path / 'admin.db'}"})
    Base.metadata.create_all(factory.build_engine())
    monkeypatch.setattr(_support, "platform_session_factory", factory)
    monkeypatch.setenv("CAPSTONE_AUTH_REQUIRED", "true")
    monkeypatch.setenv("PLATFORM_JWT_SECRET", SECRET)
    monkeypatch.setenv("PLATFORM_BCRYPT_ROUNDS", "4")
    monkeypatch.setenv("CAPSTONE_ADMIN_EMAIL", "Admin@Example.com")
    monkeypatch.setenv("CAPSTONE_ADMIN_PASSWORD", "admin-pass-2026")
    _support.reset_auth_service()
    with TestClient(app) as test_client:  # startup hook runs here
        login = test_client.post(
            "/auth/login", json={"email": "admin@example.com", "password": "admin-pass-2026"}
        )
        assert login.status_code == 200, login.text
        assert login.json()["user"]["is_admin"] is True
        # Registering afterwards does not make anyone else an owner.
        other = _register(test_client, "first.user@example.com")
        assert other["user"]["is_admin"] is False
        assert {m["role"] for m in other["memberships"]} == {"VIEWER"}
    # Running the bootstrap again is idempotent and keeps the password.
    monkeypatch.setenv("CAPSTONE_ADMIN_PASSWORD", "a-different-password")
    assert bootstrap_admin_from_env() == login.json()["user"]["user_id"]
    _support.reset_auth_service()


def test_admin_console_manages_access_across_all_workspaces(client):
    test_client, _ = client
    admin = _register(test_client, "admin@example.com")
    member = _register(test_client, "member@example.com")
    member_id = member["user"]["user_id"]
    assert admin["user"]["is_admin"] is True

    assert test_client.get("/admin/users", headers=_headers(member)).status_code == 403
    listing = test_client.get("/admin/users", headers=_headers(admin))
    assert listing.status_code == 200
    assert {row["email"]: row["is_admin"] for row in listing.json()} == {
        "admin@example.com": True,
        "member@example.com": False,
    }

    promoted = test_client.put(
        f"/admin/users/{member_id}/access", headers=_headers(admin), json={"role": "OWNER"}
    )
    assert promoted.status_code == 200 and promoted.json()["is_admin"] is True
    assert test_client.get("/auth/me", headers=_headers(member)).json()["user"]["is_admin"] is True

    removed = test_client.put(
        f"/admin/users/{member_id}/access", headers=_headers(admin), json={"role": "NONE"}
    )
    assert removed.status_code == 200 and removed.json()["memberships"] == []
    assert test_client.get("/tenants", headers=_headers(member)).json() == []

    self_demote = test_client.put(
        f"/admin/users/{admin['user']['user_id']}/access", headers=_headers(admin), json={"role": "VIEWER"}
    )
    assert self_demote.status_code == 409


def test_cli_promotes_an_existing_account_to_admin(client, capsys):
    from scripts.manage_users import main

    test_client, _ = client
    _register(test_client, "owner@example.com")
    viewer = _register(test_client, "swathi@example.com")
    assert viewer["user"]["is_admin"] is False

    assert main(["promote", "Swathi@Example.com"]) == 0
    assert "now an admin" in capsys.readouterr().out
    me = test_client.get("/auth/me", headers=_headers(viewer)).json()
    assert me["user"]["is_admin"] is True
    assert {m["role"] for m in me["memberships"]} == {"OWNER"}

    assert main(["list"]) == 0
    assert "swathi@example.com" in capsys.readouterr().out
