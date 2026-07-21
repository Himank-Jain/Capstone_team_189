"""
tests/unit/phase2/test_episode_retriever.py
================================================
P2-M9  |  Unit tests for EpisodeRetriever, using a small synthetic FAISS
index (not the real 145MB one — that's covered separately by a real-data
smoke test) so these run fast and need no external files.

Covers: exact cosine-similarity conversion against hand-computed values,
self-retrieval filtering, over-fetch behavior when filtering would
otherwise under-fill k, batch_search parity with per-query search, and
Redis cache hit/miss behavior via fakeredis.
"""
import numpy as np
import pytest

from phase1.embedding_space.faiss_indexer import FaissIndexer
import faiss

from phase2.detection.episode_retriever import EpisodeRetriever


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v)


def _build_small_index(vectors: np.ndarray, metadata: list) -> FaissIndexer:
    """IndexFlatL2 (exact, no IVF training needed) — simplest possible
    real FaissIndexer for fast, deterministic unit tests."""
    flat_index = faiss.IndexFlatL2(128)
    indexer = FaissIndexer(flat_index)
    indexer.add(vectors, metadata)
    return indexer


def _make_corpus(n=10, seed=0):
    rng = np.random.default_rng(seed)
    vectors = np.stack([_l2_normalize(rng.normal(size=128)) for _ in range(n)]).astype(np.float32)
    metadata = [
        {"entity_id": f"vm-{i:03d}", "timestamp": f"2026-01-0{(i % 9) + 1}T00:00:00+00:00",
         "cloud_provider": "AWS", "severity_label": None}
        for i in range(n)
    ]
    return vectors, metadata


class TestSimilarityConversion:
    def test_identical_vector_gives_similarity_one(self):
        vectors, metadata = _make_corpus(n=5)
        indexer = _build_small_index(vectors, metadata)
        retriever = EpisodeRetriever(indexer, redis_client=None)

        results = retriever.search(vectors[0], k=1)
        assert results[0].similarity_score == pytest.approx(1.0, abs=1e-4)
        assert results[0].episode_id == "0"

    def test_similarity_matches_hand_computed_formula(self):
        # Two orthogonal unit vectors -> squared L2 dist = 2 -> cos_sim = 0
        a = np.zeros(128, dtype=np.float32); a[0] = 1.0
        b = np.zeros(128, dtype=np.float32); b[1] = 1.0
        metadata = [{"entity_id": "vm-b", "timestamp": None, "cloud_provider": "AWS", "severity_label": None}]
        indexer = _build_small_index(b.reshape(1, -1), metadata)
        retriever = EpisodeRetriever(indexer, redis_client=None)

        results = retriever.search(a, k=1)
        assert results[0].similarity_score == pytest.approx(0.0, abs=1e-4)

    def test_opposite_vectors_give_similarity_negative_one(self):
        a = np.zeros(128, dtype=np.float32); a[0] = 1.0
        b = np.zeros(128, dtype=np.float32); b[0] = -1.0
        metadata = [{"entity_id": "vm-b", "timestamp": None, "cloud_provider": "AWS", "severity_label": None}]
        indexer = _build_small_index(b.reshape(1, -1), metadata)
        retriever = EpisodeRetriever(indexer, redis_client=None)

        results = retriever.search(a, k=1)
        assert results[0].similarity_score == pytest.approx(-1.0, abs=1e-4)


class TestSelfFiltering:
    def test_excludes_the_querying_entity(self):
        vectors, metadata = _make_corpus(n=10)
        indexer = _build_small_index(vectors, metadata)
        retriever = EpisodeRetriever(indexer, redis_client=None)

        results = retriever.search(vectors[0], k=5, exclude_entity_id="vm-000")
        assert all(r.entity_id != "vm-000" for r in results)
        assert len(results) == 5  # over-fetch margin absorbed the exclusion

    def test_no_exclusion_when_not_requested(self):
        vectors, metadata = _make_corpus(n=10)
        indexer = _build_small_index(vectors, metadata)
        retriever = EpisodeRetriever(indexer, redis_client=None)

        results = retriever.search(vectors[0], k=3)
        assert results[0].entity_id == "vm-000"  # self-match IS allowed here


class TestResultFields:
    def test_episode_id_is_faiss_internal_index(self):
        vectors, metadata = _make_corpus(n=5)
        indexer = _build_small_index(vectors, metadata)
        retriever = EpisodeRetriever(indexer, redis_client=None)

        results = retriever.search(vectors[2], k=1)
        assert results[0].episode_id == "2"

    def test_severity_label_none_is_preserved_not_defaulted(self):
        vectors, metadata = _make_corpus(n=3)
        indexer = _build_small_index(vectors, metadata)
        retriever = EpisodeRetriever(indexer, redis_client=None)

        results = retriever.search(vectors[0], k=1)
        assert results[0].severity_label is None

    def test_timestamp_parsed_to_datetime(self):
        vectors, metadata = _make_corpus(n=3)
        indexer = _build_small_index(vectors, metadata)
        retriever = EpisodeRetriever(indexer, redis_client=None)

        results = retriever.search(vectors[0], k=1)
        assert results[0].timestamp is not None
        assert results[0].timestamp.year == 2026


class TestBatchSearch:
    def test_batch_search_matches_individual_search_results(self):
        vectors, metadata = _make_corpus(n=10)
        indexer = _build_small_index(vectors, metadata)
        retriever = EpisodeRetriever(indexer, redis_client=None)

        individual = [retriever.search(vectors[i], k=3) for i in range(3)]
        batched = retriever.batch_search(vectors[:3], k=3)

        for ind, bat in zip(individual, batched):
            assert [r.episode_id for r in ind] == [r.episode_id for r in bat]

    def test_batch_search_respects_per_query_exclusion(self):
        vectors, metadata = _make_corpus(n=10)
        indexer = _build_small_index(vectors, metadata)
        retriever = EpisodeRetriever(indexer, redis_client=None)

        results = retriever.batch_search(
            vectors[:2], k=3, exclude_entity_ids=["vm-000", None],
        )
        assert all(r.entity_id != "vm-000" for r in results[0])
        assert results[1][0].entity_id == "vm-001"  # no exclusion -> self-match allowed


class TestRedisCache:
    def test_cache_miss_then_hit(self):
        import fakeredis
        vectors, metadata = _make_corpus(n=5)
        indexer = _build_small_index(vectors, metadata)
        redis_client = fakeredis.FakeStrictRedis()
        retriever = EpisodeRetriever(indexer, redis_client=redis_client)

        first = retriever.search(vectors[0], k=2, exclude_entity_id="vm-999")
        # Confirm something was actually cached
        cache_key = retriever._cache_key("vm-999", vectors[0])
        assert redis_client.get(cache_key) is not None

        second = retriever.search(vectors[0], k=2, exclude_entity_id="vm-999")
        assert [r.episode_id for r in first] == [r.episode_id for r in second]

    def test_disabled_cache_still_works(self):
        vectors, metadata = _make_corpus(n=5)
        indexer = _build_small_index(vectors, metadata)
        retriever = EpisodeRetriever(indexer, redis_client=None)

        results = retriever.search(vectors[0], k=2)
        assert len(results) == 2
