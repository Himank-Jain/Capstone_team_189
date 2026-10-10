"""
scripts/run_p2m8_against_entity_store.py
=====================================================
P2-M8 integration example -- shows how an inference-loop orchestrator
wires EntityStoreReader/Writer (P2-M6) into MmdDriftMonitor +
AsyncDriftWorker (P2-M8), exactly the same shape as
run_p2m7_against_entity_store.py does for CosineDeviationScorer.

MmdDriftMonitor never imports phase2.store itself (see its module
docstring) -- fetching the profile is EntityStoreReader's job (inside
compute_drift, which the caller injects a reader into at construction
time); running that off the hot path and caching the result is
AsyncDriftWorker's job. This script is the orchestrator gluing all three
together against a real Redis wire-protocol client.

Run from the project root:
    python -m scripts.run_p2m8_against_entity_store vm-aws-002
    python -m scripts.run_p2m8_against_entity_store vm-aws-002 --seed-demo-drift

If no real Redis is reachable at --host/--port, falls back to an
in-process fakeredis instance (same fakeredis.FakeRedis used by the unit
tests) so this script is runnable in any environment -- it exercises the
exact same EntityStoreReader/Writer/AsyncDriftWorker code paths either
way, just swapping the underlying transport.
"""

import argparse
from datetime import datetime, timezone

import numpy as np

from phase2.detection.async_drift_worker import AsyncDriftWorker
from phase2.detection.cosine_deviation_scorer import CosineDeviationScorer
from phase2.detection.mmd_drift_monitor import MmdDriftMonitor
from phase2.store.entity_store_reader import EntityStoreReader
from phase2.store.entity_store_writer import EntityStoreWriter
from phase2.store.redis_entity_store import build_redis_client
from shared.constants import REDIS_HISTORY_LEN
from shared.types import CurrentEmbedding, EntityProfile


def _connect_redis(host: str, port: int, force_fake: bool):
    if not force_fake:
        client = build_redis_client(host_str=host, port_int=port)
        try:
            client.ping()
            print(f"Connected to real Redis at {host}:{port}")
            return client
        except Exception as exc:
            print(f"Could not reach real Redis at {host}:{port} ({exc}) -- falling back to fakeredis")
    import fakeredis
    return fakeredis.FakeRedis(decode_responses=False)


def _unit(v: np.ndarray) -> np.ndarray:
    return (v / np.linalg.norm(v)).astype(np.float32)


def _cluster_embs(n: int, center: np.ndarray, noise_scale: float, seed: int):
    rng = np.random.default_rng(seed)
    return [_unit(center + rng.normal(scale=noise_scale, size=128).astype(np.float32)) for _ in range(n)]


def seed_demo_profile(writer: EntityStoreWriter, entity_id: str) -> None:
    """Write a synthetic-but-real EntityProfile whose OLDER 20 history
    embeddings sit in one behavioral cluster and whose NEWEST 10 sit in a
    clearly different one -- a genuine drift signal, written through the
    real P2-M6 write path (pipeline SET/LPUSH/LTRIM/HSET), not faked."""
    rng = np.random.default_rng(0)
    center_a = _unit(rng.normal(size=128).astype(np.float32))
    center_b = _unit(rng.normal(size=128).astype(np.float32) + 8.0)  # far away

    past = _cluster_embs(20, center_a, noise_scale=0.03, seed=1)
    recent = _cluster_embs(min(10, REDIS_HISTORY_LEN - 20), center_b, noise_scale=0.03, seed=2)
    history = past + recent  # chronological oldest-first

    profile = EntityProfile(
        entity_id=entity_id,
        centroid_emb=_unit(np.mean(np.stack(history), axis=0)),
        history_embs=history,
        emb_variance=0.0,
        n_records=len(history),
        last_update_ts=datetime.now(timezone.utc),
        cold_start_flag=False,
    )
    writer.write_entity_profile(profile)
    print(f"Seeded demo profile for entity_id={entity_id}: "
          f"{len(past)} 'past'-cluster + {len(recent)} 'recent'-cluster embeddings "
          "written through the real P2-M6 EntityStoreWriter.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("entity_id")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=6379)
    parser.add_argument("--fake", action="store_true", help="force in-process fakeredis, skip real-Redis probe")
    parser.add_argument(
        "--seed-demo-drift", action="store_true",
        help="write a synthetic drifted history for entity_id before scoring, via the real P2-M6 writer",
    )
    args = parser.parse_args()

    redis_client = _connect_redis(args.host, args.port, args.fake)

    reader = EntityStoreReader(redis_client_sync=redis_client)
    writer = EntityStoreWriter(redis_client_sync=redis_client)

    if args.seed_demo_drift:
        seed_demo_profile(writer, args.entity_id)

    profile = reader.fetch_entity_profile(args.entity_id)
    print(f"\nentity_id: {args.entity_id}")
    print(f"  profile found: {profile is not None}")
    if profile is not None:
        print(f"  history length: {len(profile.history_embs)}")

    # ── P2-M8: MMD drift, run off the hot path via AsyncDriftWorker ────────
    drift_monitor = MmdDriftMonitor(entity_store_reader=reader, null_calibration_pairs=300)
    drift_worker = AsyncDriftWorker(drift_monitor=drift_monitor, redis_client_sync=redis_client)

    print("\nSubmitting MMD drift computation to the background thread pool "
          "(NOT the hot inference path)...")
    future = drift_worker.submit_compute(args.entity_id)
    drift_result = future.result(timeout=30)

    print("DriftScore (P2-M8, just computed):")
    print(f"  drift_score: {drift_result.drift_score:.4f}  (flag={drift_result.drift_flag})")
    print(f"  computed_at: {drift_result.computed_at.isoformat()}")

    # Prove the Redis cache round-trip independently of the Future's own
    # return value -- this is what the hot inference path actually calls.
    cached = drift_worker.get_cached_drift(args.entity_id)
    assert cached is not None, "expected a cached DriftScore immediately after compute"
    print(f"  re-read from Redis cache (TTL={drift_worker._cache_ttl_sec}s): "
          f"drift_score={cached.drift_score:.4f} matches={abs(cached.drift_score - drift_result.drift_score) < 1e-9}")

    # ── P2-M7 preview, for context: the two real P2-M10 inputs side by side ─
    if profile is not None:
        scorer = CosineDeviationScorer()
        current_emb = CurrentEmbedding(
            entity_id=args.entity_id,
            emb=profile.history_embs[-1],  # most recent window-embedding as a stand-in "current" batch
            batch_ts=datetime.now(timezone.utc),
            n_records=1,
            cloud_provider="AWS",
        )
        deviation_result = scorer.compute_scores(current_emb, profile)
        print("\nDeviationResult (P2-M7, for context -- P2-M10's other real input):")
        print(f"  global_score: {deviation_result.global_score:.4f}  (flag={deviation_result.global_flag})")
        print(f"  local_score:  {deviation_result.local_score:.4f}  (flag={deviation_result.local_flag})")

    drift_worker.shutdown()


if __name__ == "__main__":
    main()
