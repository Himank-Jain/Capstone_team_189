"""
test_phase0_producer.py
==========================
Produces ~30 stable vm-042:cpu_usage readings (all landing in the same
hour bucket) followed by one deliberate extreme outlier, to a real Kafka
topic. Tracks delivery confirmation properly (success/failed/still
pending) rather than assuming flush() succeeding means anything, per the
same lesson learned fixing the Phase 2 producer test.
"""
import json
import random
import sys
from datetime import datetime, timedelta, timezone

from confluent_kafka import Producer

TOPIC = "vm-metrics-stream"
FLUSH_TIMEOUT_S = 15

producer = Producer({"bootstrap.servers": "localhost:9092"})
delivery_results = {"success": 0, "failed": 0, "failures": []}

def delivery_report(err, msg):
    if err is not None:
        delivery_results["failed"] += 1
        delivery_results["failures"].append(str(err))
    else:
        delivery_results["success"] += 1

# All points stamped at hour=3 (with split_weekday_weekend disabled on
# the consumer side, only the hour matters for bucket assignment) so
# they all land in the SAME bucket regardless of which calendar day each
# one is nominally dated.
base_ts = datetime(2025, 11, 11, 3, 0, tzinfo=timezone.utc)

points = []
random.seed(42)
for day_offset in range(30):
    points.append({
        "vm_id": "vm-042",
        "metric_name": "cpu_usage",
        "timestamp": (base_ts - timedelta(days=day_offset)).isoformat(),
        "value": round(62.0 + random.uniform(-3.0, 3.0), 2),
    })

# The deliberate outlier — should be flagged once the baseline has enough history
points.append({
    "vm_id": "vm-042",
    "metric_name": "cpu_usage",
    "timestamp": base_ts.isoformat(),
    "value": 150.0,
})

n_attempted = len(points)
print(f"Producing {n_attempted} points to topic '{TOPIC}' ({n_attempted - 1} stable + 1 outlier)...")

for p in points:
    producer.produce(TOPIC, value=json.dumps(p).encode("utf-8"), callback=delivery_report)
    producer.poll(0)

n_still_pending = producer.flush(FLUSH_TIMEOUT_S)

print(f"succeeded: {delivery_results['success']}  failed: {delivery_results['failed']}  "
      f"still_pending: {n_still_pending}")

if n_still_pending > 0 or delivery_results["failed"] > 0:
    print("✗ FAILED: not all points confirmed delivered")
    sys.exit(1)

print(f"✓ All {n_attempted} points confirmed delivered.")
sys.exit(0)
