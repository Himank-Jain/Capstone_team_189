from typing import Any, Dict


def build_summary_payload() -> Dict[str, Any]:
    return {
        "active_alerts": 12,
        "critical_alerts": 2,
        "event_volume": 187,
        "model_confidence": 0.96,
    }
