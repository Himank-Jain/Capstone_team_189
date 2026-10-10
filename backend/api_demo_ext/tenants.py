from typing import Any, Dict, List


def get_demo_tenants() -> List[Dict[str, Any]]:
    return [
        {"id": "google", "name": "Google", "live_alert_count": 4, "health": "healthy"},
        {"id": "microsoft", "name": "Microsoft", "live_alert_count": 2, "health": "healthy"},
        {"id": "amazon", "name": "Amazon", "live_alert_count": 6, "health": "warning"},
        {"id": "oracle", "name": "Oracle", "live_alert_count": 1, "health": "healthy"},
        {"id": "openai", "name": "OpenAI", "live_alert_count": 3, "health": "healthy"},
    ]
