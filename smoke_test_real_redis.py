"""
smoke_test_real_redis.py
===========================
Same checks as test_rolling_baseline_store.py, but against a REAL Redis
server (docker-compose's capstone-redis), not fakeredis. Confirms no
subtle real-vs-fake WATCH/MULTI/EXEC behavioral differences.
"""
import sys
import threading
from datetime import datetime

import redis

sys.path.insert(0, ".")

from phase0.baseline.rolling_baseline_store import RollingBaselineStore
from phase0.bucketing.bucket_key_resolver import BucketKeyResolver

client = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

# Clean slate for this test run
for key in client.scan_iter("phase0:baseline:*"):
    client.delete(key)

print("Connected to real Redis:", client.ping())

# ── 1. Basic round-trip ──────────────────────────────────────────────────────
store = RollingBaselineStore(client)
key = BucketKeyResolver().resolve("vm-042", "cpu_usage", datetime(2025, 11, 11, 3, 0))

for v in [60.0, 62.0, 64.0, 61.0, 63.0]:
    state = store.update_bucket(key, v)

print(f"After 5 updates: count={state.count} mean={state.mean:.2f} std={state.std:.2f}")
assert state.count == 5
assert abs(state.mean - 62.0) < 0.01

fetched = store.get_bucket_state(key)
assert fetched.count == 5
print("✓ Round-trip through real Redis matches in-memory state")

# ── 2. Window eviction ───────────────────────────────────────────────────────
small_store = RollingBaselineStore(client, window_size=5)
key2 = BucketKeyResolver().resolve("vm-999", "memory_usage", datetime(2025, 11, 11, 4, 0))
for v in [10, 20, 30, 40, 50, 60, 70]:
    state2 = small_store.update_bucket(key2, v)

assert state2.count == 5
assert list(state2.window) == [30, 40, 50, 60, 70]
print(f"✓ Window eviction correct: {list(state2.window)}")

# ── 3. Real concurrency stress test against the ACTUAL server ──────────────
key3 = BucketKeyResolver().resolve("vm-stress", "disk_io", datetime(2025, 11, 11, 5, 0))
stress_store = RollingBaselineStore(client, window_size=10000)

n_threads = 16
updates_per_thread = 25
total_expected = n_threads * updates_per_thread
errors = []

def worker(thread_id):
    try:
        for i in range(updates_per_thread):
            stress_store.update_bucket(key3, float(thread_id * 1000 + i))
    except Exception as e:
        errors.append(str(e))

threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
for t in threads:
    t.start()
for t in threads:
    t.join()

final = stress_store.get_bucket_state(key3)
print(f"Concurrency test: expected={total_expected} actual={final.count} errors={len(errors)}")
assert final.count == total_expected, f"LOST WRITES: {total_expected - final.count}"
assert not errors

print("\n✓ ALL CHECKS PASSED against a real Redis server.")