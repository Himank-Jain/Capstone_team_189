"""
validate_p2m9_real_data.py
=============================
Proves EpisodeRetriever works correctly against the REAL FAISS index
(model_registry/behavioral_space.faiss, ~280K vectors) rather than the
small synthetic index the unit tests use.

Checks:
  1. The real index loads via ArtifactBundle.load_latest() and has the
     expected vector count.
  2. A real stored vector, used as its own query, finds itself as a
     near-perfect match (sim ~1.0) when self-filtering is off.
  3. The SAME query with exclude_entity_id set NEVER returns that
     entity, and still returns k results (over-fetch margin works).
  4. Redis caching (fakeredis here — swap for a real client if you want
     to test against your actual Redis container) returns identical
     results on a cache hit vs the original query.
"""
import sys

import fakeredis

sys.path.insert(0, ".")

from phase1.registry.artifact_bundle import ArtifactBundle
from phase2.detection.episode_retriever import EpisodeRetriever

print("Loading real ArtifactBundle (encoder + FAISS index)...")
bundle, encoder, faiss_indexer = ArtifactBundle.load_latest(registry_dir_str="model_registry")
print(f"Real FAISS index loaded: {faiss_indexer.index.ntotal} vectors\n")

faiss_indexer.index.make_direct_map()  # required for reconstruct() on an IVF index

real_vector_0 = faiss_indexer.index.reconstruct(0)
real_entity_0 = faiss_indexer.metadata_list[0]["entity_id"]
print(f"Query = actual stored vector 0, belonging to entity:\n  {real_entity_0}\n")

redis_client = fakeredis.FakeStrictRedis()
retriever = EpisodeRetriever(faiss_indexer, redis_client=redis_client)

# ── 1. Self-match without filtering ──────────────────────────────────────────
results_no_filter = retriever.search(real_vector_0, k=5)
top = results_no_filter[0]
print(f"[No filtering] top result: episode_id={top.episode_id}  sim={top.similarity_score:.6f}")
assert top.episode_id == "0", f"Expected episode_id '0', got {top.episode_id!r}"
assert top.similarity_score > 0.999, f"Expected near-1.0 self-match, got {top.similarity_score}"
print("  -> PASS: found itself as a near-perfect match\n")

# ── 2. Self-filtering ─────────────────────────────────────────────────────────
results_filtered = retriever.search(real_vector_0, k=5, exclude_entity_id=real_entity_0)
print(f"[With exclude_entity_id] {len(results_filtered)} results:")
for r in results_filtered:
    marker = " <-- SHOULD NEVER APPEAR" if r.entity_id == real_entity_0 else ""
    print(f"  episode_id={r.episode_id:>7}  sim={r.similarity_score:.4f}  "
          f"entity={r.entity_id[:55]}...{marker}")
assert all(r.entity_id != real_entity_0 for r in results_filtered), \
    "FAIL: self-retrieval leaked through the exclude filter!"
assert len(results_filtered) == 5, f"Expected 5 results after over-fetch, got {len(results_filtered)}"
print("  -> PASS: querying entity never appears, still got a full k=5\n")

# ── 3. Cache hit returns identical results ───────────────────────────────────
cache_key = retriever._cache_key(real_entity_0, real_vector_0)
cached_before = redis_client.get(cache_key)
assert cached_before is not None, "FAIL: nothing was cached after the query above"

results_cached = retriever.search(real_vector_0, k=5, exclude_entity_id=real_entity_0)
assert [r.episode_id for r in results_cached] == [r.episode_id for r in results_filtered], \
    "FAIL: cached results differ from the original query"
print("[Cache] hit returns identical episode_ids to the original query")
print("  -> PASS\n")

# ── 4. batch_search parity with individual search ────────────────────────────
import numpy as np
batch_results = retriever.batch_search(
    np.stack([real_vector_0]), k=5, exclude_entity_ids=[real_entity_0],
)
assert [r.episode_id for r in batch_results[0]] == [r.episode_id for r in results_filtered], \
    "FAIL: batch_search diverged from search() for the same query"
print("[batch_search] matches search() results exactly for the same query")
print("  -> PASS\n")

print("=" * 70)
print("✓ ALL CHECKS PASSED — EpisodeRetriever verified against your REAL")
print(f"  {faiss_indexer.index.ntotal}-vector FAISS index, not just synthetic test data.")
print("=" * 70)
