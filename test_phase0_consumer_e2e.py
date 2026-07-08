"""
test_phase0_consumer_e2e.py
==============================
Full end-to-end Phase 0 test: real Kafka -> KafkaStreamReader ->
AnomalyScoringWorker -> real Redis-backed RollingBaselineStore.

Run test_phase0_producer.py in a second terminal after this one prints
"[KafkaStreamReader] Subscribed..." to see the 30 stable readings build
up a baseline and the final outlier get flagged.
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")

import redis

from phase0.baseline.rolling_baseline_store import RollingBaselineStore
from phase0.bucketing.bucket_key_resolver import BucketKeyResolver
from phase0.scoring.zscore_scorer import ZScoreScorer
from phase0.streaming.kafka_stream_reader import KafkaStreamReader
from phase0.workers.anomaly_scoring_worker import AnomalyScoringWorker

TOPIC = "vm-metrics-stream"
GROUP_ID = "phase0-e2e-consumer-v1"

redis_client = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
# Clean slate so this run's bucket starts fresh
for key in redis_client.scan_iter("phase0:baseline:vm-042:*"):
    redis_client.delete(key)

store = RollingBaselineStore(redis_client)
# split_weekday_weekend=False so the producer's "different calendar day,
# same hour" points all land in one bucket, matching the producer script.
bucket_resolver = BucketKeyResolver(split_weekday_weekend=False)
scorer = ZScoreScorer(threshold=3.0, min_samples=5)

anomalies_seen = []

def on_score(result):
    tag = "🚨 ANOMALY" if result.is_anomaly else ("(cold-start)" if result.cold_start else "ok")
    print(f"  [{tag}] value={result.value:.1f}  z={result.z_score:.2f}  "
          f"baseline_mean={result.baseline_mean:.1f}  baseline_std={result.baseline_std:.1f}")
    if result.is_anomaly:
        anomalies_seen.append(result)

reader = KafkaStreamReader(
    bootstrap_servers="localhost:9092",
    topic=TOPIC,
    group_id=GROUP_ID,
)

worker = AnomalyScoringWorker(
    stream_reader=reader,
    baseline_store=store,
    on_score=on_score,
    bucket_resolver=bucket_resolver,
    scorer=scorer,
    poll_timeout_ms=1000,
)

async def run_for_a_while():
    task = asyncio.create_task(worker.run_async())
    await asyncio.sleep(20)
    worker.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

asyncio.run(run_for_a_while())

print(f"\n--- Summary ---")
print(f"points_processed_total: {worker.points_processed_total}")
print(f"anomalies_flagged_total: {worker.anomalies_flagged_total}")
if anomalies_seen:
    print(f"Flagged anomaly value(s): {[a.value for a in anomalies_seen]}")
