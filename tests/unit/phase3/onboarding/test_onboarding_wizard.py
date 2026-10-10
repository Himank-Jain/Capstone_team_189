from __future__ import annotations

from phase3.onboarding.wizard_service import OnboardingWizardService


def test_onboarding_wizard_tracks_progress_and_completes_state():
    wizard = OnboardingWizardService()

    session = wizard.start_onboarding(user_id="user-1", tenant_name="Acme", source_mode="synthetic")
    assert session["status"] == "in_progress"
    assert session["tenant_name"] == "Acme"

    wizard.record_step(session["session_id"], "cloud_connection", {"provider": "AWS"})
    wizard.record_step(session["session_id"], "notification_setup", {"channel": "email"})
    wizard.mark_complete(session["session_id"], "enable_monitoring", {"enabled": True})

    final = wizard.get_session(session["session_id"])
    assert final["status"] == "complete"
    assert final["steps"]["cloud_connection"]["provider"] == "AWS"
    assert final["steps"]["enable_monitoring"]["enabled"] is True
