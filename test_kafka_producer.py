"""
test_kafka_producer.py
=======================
Pushes synthetic telemetry events to the local Kafka topic and PROVES
delivery, rather than assuming success just because flush() returned.

Three distinct failure modes are tracked and reported separately, since
each means something different:
  1. Explicit delivery failure — the broker/callback told us a specific
     message failed (err is not None in delivery_report).
  2. Delivery timeout — flush() returned > 0, meaning some produced
     messages NEVER got a delivery callback at all within the timeout
     (e.g. broker unreachable). These are silent unless you check
     flush()'s return value, which the earlier version of this script
     did not do.
  3. Count mismatch — success + failed + still-pending should always
     equal the number of events we tried to produce; if not, something
     is being double-counted or lost, worth knowing about even if it's
     unlikely to occur here.

Exits with a non-zero status code if anything didn't fully succeed, so
this can be used as a real pass/fail check rather than something you
have to eyeball.
"""
import json
import sys
from datetime import datetime, timedelta, timezone

from confluent_kafka import Producer

TOPIC = "telemetry-events"
FLUSH_TIMEOUT_S = 15

producer = Producer({"bootstrap.servers": "localhost:9092"})

delivery_results = {"success": 0, "failed": 0, "failures": []}

def delivery_report(err, msg):
    if err is not None:
        delivery_results["failed"] += 1
        delivery_results["failures"].append(str(err))
        print(f"  ✗ Delivery failed: {err}")
    else:
        delivery_results["success"] += 1
        print(f"  ✓ Delivered to {msg.topic()} [{msg.partition()}] offset {msg.offset()}")

now = datetime.now(timezone.utc)
events = []

for i in range(8):
    events.append({
        "entity_id": "vm-kafka-test-001" if i % 2 == 0 else "storage-kafka-test-002",
        "timestamp": (now + timedelta(minutes=i)).isoformat(),
        "cloud": "AWS" if i % 2 == 0 else "Azure",
        "entity_type": "VirtualMachine" if i % 2 == 0 else "StorageAccount",
        "namespace": "Compute" if i % 2 == 0 else "Storage",
        "metric_name": "cpu_usage" if i % 2 == 0 else "Availability",
        "value": 40.0 + i,
    })

# Deliberately malformed event (missing 'value') — should reach the broker
# fine (Kafka doesn't validate payload schema) but get rejected downstream
# by SchemaValidator on the consumer side, not here.
events.append({
    "entity_id": "bad-entity-003",
    "timestamp": now.isoformat(),
    "cloud": "AWS",
    "entity_type": "VirtualMachine",
    "namespace": "Compute",
    "metric_name": "cpu_usage",
})

n_attempted = len(events)
print(f"Producing {n_attempted} events to topic '{TOPIC}'...")

try:
    for event in events:
        producer.produce(TOPIC, value=json.dumps(event).encode("utf-8"), callback=delivery_report)
        producer.poll(0)  # let already-completed callbacks fire without blocking
except BufferError as exc:
    print(f"✗ Local producer queue is full: {exc}")
    sys.exit(1)

# flush() returns the number of messages STILL in the queue after the
# timeout — i.e. messages that never got a delivery_report callback at
# all. This is the case the original script silently ignored.
n_still_pending = producer.flush(FLUSH_TIMEOUT_S)

print(f"\n--- Delivery summary ---")
print(f"attempted:     {n_attempted}")
print(f"succeeded:     {delivery_results['success']}")
print(f"failed:        {delivery_results['failed']}")
print(f"still pending: {n_still_pending}  (never got a callback within {FLUSH_TIMEOUT_S}s)")

accounted_for = delivery_results["success"] + delivery_results["failed"] + n_still_pending
if accounted_for != n_attempted:
    print(f"⚠ COUNT MISMATCH: accounted_for={accounted_for} != attempted={n_attempted}")

if n_still_pending > 0:
    print(f"\n✗ FAILED: {n_still_pending} message(s) never confirmed — is the "
          f"broker reachable at localhost:9092? (check `docker compose ps`)")
    sys.exit(1)

if delivery_results["failed"] > 0:
    print(f"\n✗ FAILED: {delivery_results['failed']} message(s) explicitly failed:")
    for reason in delivery_results["failures"]:
        print(f"    - {reason}")
    sys.exit(1)

print(f"\n✓ All {n_attempted} events confirmed delivered.")
sys.exit(0)