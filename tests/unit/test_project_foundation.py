from datetime import datetime, timezone
from pathlib import Path

from live_ingestion.mappers.vocab_reconciler import VocabReconciler
from shared.config import ConfigLoader


ROOT = Path(__file__).resolve().parents[2]


def test_config_loader_reads_documented_yaml():
    config = ConfigLoader.from_file(ROOT / "config" / "config.yaml")

    assert config.require("encoder.sequence_length") == 32
    assert config.get("ingestion.batch_window_seconds") == 30


def test_live_vocab_reconciler_reads_nested_feature_metadata():
    reconciler = VocabReconciler(ROOT / "config" / "feature_meta.json")

    resolved, has_oov = reconciler.resolve_categorical_fields(
        {
            "cloud": "AWS",
            "entity_type": "Instances",
            "namespace": "AWS/EC2",
            "metric_name": "CPUUtilization",
        }
    )

    assert resolved["cloud"] == "AWS"
    assert resolved["metric_name"] == "CPUUtilization"
    assert has_oov is False


def test_runtime_contract_paths_are_importable():
    from phase3.cloud_connect.cloud_connection_service import CloudConnectionService
    from phase3.cloud_connect.credential_store import CredentialStore
    from phase3.notifications.sms_notifier import SmsNotifier
    from phase3.notifications.webhook_notifier import WebhookNotifier
    from phase3.onboarding.onboarding_wizard_service import OnboardingWizardService

    assert all(
        cls is not None
        for cls in (
            CloudConnectionService,
            CredentialStore,
            SmsNotifier,
            WebhookNotifier,
            OnboardingWizardService,
        )
    )
