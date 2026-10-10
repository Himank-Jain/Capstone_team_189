from typing import Any, Dict


def build_login_response() -> Dict[str, Any]:
    return {
        "access_token": "demo-access-token",
        "refresh_token": "demo-refresh-token",
        "user": {"email": "demo@capstone189.local", "role": "Admin"},
    }
