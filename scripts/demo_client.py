import httpx

BASE = "http://127.0.0.1:8001"

with httpx.Client(timeout=5.0) as client:
    r = client.get(f"{BASE}/stats/summary")
    print("GET /stats/summary ->", r.status_code)
    print(r.json())

    r = client.get(f"{BASE}/tenants")
    print("GET /tenants ->", r.status_code)
    print(r.json())

    r = client.post(f"{BASE}/auth/login", json={"email": "demo@example.com", "password": "pass"})
    print("POST /auth/login ->", r.status_code)
    print(r.json())

    payload = {"tenant_id": "demo-1", "scenario": "credential_theft"}
    r = client.post(f"{BASE}/demo/generate/attack", json=payload)
    print("POST /demo/generate/attack ->", r.status_code)
    print(r.json())
