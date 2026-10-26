from phase3.api.analytics import build_summary_payload
from phase3.api.auth import build_login_response
from phase3.api.tenants import get_demo_tenants
from phase3.api.ws_heartbeat import build_stage_heartbeat
from demo_generator.generator import DemoGenerator


def test_demo_layer_flow():
    login = build_login_response()
    tenants = get_demo_tenants()
    summary = build_summary_payload()
    heartbeat = build_stage_heartbeat("encoding", "vol-0a12")
    generator = DemoGenerator()
    payload = generator.build_payload("google", "credential_theft")

    assert login["user"]["role"] == "Admin"
    assert len(tenants) == 5
    assert summary["active_alerts"] == 12
    assert heartbeat["stage"] == "encoding"
    assert payload["tenant_id"] == "google"
    assert payload["scenario"] == "credential_theft"
