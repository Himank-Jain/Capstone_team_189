"""
scripts/run_p2m7_against_entity_store.py
=====================================================
P2-M7 integration example -- shows how an inference-loop orchestrator
wires EntityStoreReader (P2-M6) into CosineDeviationScorer (P2-M7).

CosineDeviationScorer never imports phase2.store itself (see the module
docstring in phase2/detection/cosine_deviation_scorer.py) -- fetching
CurrentEmbedding/EntityProfile and handing them to compute_scores() is
this script's job, not the scorer's.

Run from the project root:
    python -m scripts.run_p2m7_against_entity_store vm-aws-002
"""

import argparse
from datetime import datetime, timezone

import numpy as np

from phase2.detection.cosine_deviation_scorer import CosineDeviationScorer
from phase2.store.entity_store_reader import EntityStoreReader
from phase2.store.redis_entity_store import build_redis_client
from shared.types import CurrentEmbedding


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("entity_id")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=6379)
    args = parser.parse_args()

    redis_client = build_redis_client(host_str=args.host, port_int=args.port)
    reader = EntityStoreReader(redis_client_sync=redis_client)
    scorer = CosineDeviationScorer()

    # In production this comes from CurrentEmbeddingAggregator (P2-M5) for
    # the live batch. Here we either reuse the stored current_embedding, or
    # fall back to a small perturbation of the centroid so the example runs
    # even if P2-M5 hasn't written one yet.
    profile = reader.fetch_entity_profile(args.entity_id)
    stored_current = reader.fetch_current_embedding(args.entity_id)

    if stored_current is not None:
        emb = stored_current
    elif profile is not None:
        rng = np.random.default_rng(0)
        noisy = profile.centroid_emb + rng.normal(scale=0.05, size=128).astype(np.float32)
        emb = noisy / np.linalg.norm(noisy)
    else:
        rng = np.random.default_rng(0)
        raw = rng.normal(size=128).astype(np.float32)
        emb = raw / np.linalg.norm(raw)

    current_emb = CurrentEmbedding(
        entity_id=args.entity_id,
        emb=emb,
        batch_ts=datetime.now(timezone.utc),
        n_records=1,
        cloud_provider=profile is not None and "AWS" or "Unknown",
    )

    result = scorer.compute_scores(current_emb, profile)

    print(f"entity_id: {args.entity_id}")
    print(f"  profile found: {profile is not None}")
    if profile is not None:
        print(f"  history length: {len(profile.history_embs)}")
        print(f"  cold_start_flag (upstream, P2-M4): {profile.cold_start_flag}")
    print("DeviationResult:")
    print(f"  global_score: {result.global_score:.4f}  (flag={result.global_flag})")
    print(f"  local_score:  {result.local_score:.4f}  (flag={result.local_flag})")


if __name__ == "__main__":
    main()
