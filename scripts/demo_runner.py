import httpx

BASE = "http://127.0.0.1:8001"
scenarios = ["credential_theft", "insider_threat", "network_scan"]
tenants = ["google", "microsoft", "amazon"]

with httpx.Client(timeout=5.0) as client:
    for tenant in tenants:
        for scenario in scenarios:
            payload = {"tenant_id": tenant, "scenario": scenario}
            r = client.post(f"{BASE}/demo/generate/attack", json=payload)
            print(f"{tenant} - {scenario} -> {r.status_code} {r.text}")
