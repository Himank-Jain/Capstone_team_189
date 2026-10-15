from datetime import datetime, timezone

import fakeredis
import numpy as np

from phase2.store.entity_store_writer import EntityStoreWriter
from shared.types import EntityProfile


def _profile():
    centroid = np.zeros(128, dtype=np.float32)
    centroid[0] = 1.0
    return EntityProfile(
        entity_id="entity-a",
        centroid_emb=centroid,
        history_embs=[centroid.copy()],
        emb_variance=0.0,
        n_records=1,
        last_update_ts=datetime.now(timezone.utc),
        cold_start_flag=False,
    )


def test_fixed_resolution_discards_quarantined_embeddings_and_keeps_profile():
    redis = fakeredis.FakeStrictRedis(decode_responses=False)
    writer = EntityStoreWriter(redis, history_len_int=5)
    prior = _profile()
    writer.write_entity_profile(prior)
    writer.set_baseline_frozen("entity-a", True, "tenant-a")
    writer.record_frozen_embeddings(
        "entity-a", [_embedding(1)], "tenant-a"
    )

    assert writer.is_baseline_frozen("entity-a", "tenant-a")
    assert not writer.is_baseline_frozen("entity-a", "tenant-b")
    writer.resolve_frozen_baseline("entity-a", "FIXED", 0.5, 5, 3, "tenant-a")

    current = writer.fetch_entity_profile("entity-a")
    assert not writer.is_baseline_frozen("entity-a", "tenant-a")
    assert len(current.history_embs) == 1
    np.testing.assert_allclose(current.centroid_emb, prior.centroid_emb, atol=0.001)
    assert redis.exists("tenant:tenant-a:entity:entity-a:baseline:frozen_history") == 0


def test_expected_change_reseeds_and_uses_bounded_high_alpha():
    writer = EntityStoreWriter(
        fakeredis.FakeStrictRedis(decode_responses=False), history_len_int=5
    )
    writer.write_entity_profile(_profile())
    writer.set_baseline_frozen("entity-a", True, "tenant-a")
    writer.record_frozen_embeddings(
        "entity-a",
        [
            _embedding(1),
            _embedding(1),
        ],
        "tenant-a",
    )

    writer.resolve_frozen_baseline("entity-a", "EXPECTED_CHANGE", 0.5, 5, 2, "tenant-a")

    current = writer.fetch_entity_profile("entity-a")
    assert len(current.history_embs) == 3
    assert current.centroid_emb[1] > 0
    assert writer.next_baseline_alpha("entity-a", 0.1, "tenant-a") == 0.5
    assert writer.next_baseline_alpha("entity-a", 0.1, "tenant-a") == 0.5
    assert writer.next_baseline_alpha("entity-a", 0.1, "tenant-a") == 0.1


def _embedding(index):
    embedding = np.zeros(128, dtype=np.float32)
    embedding[index] = 1.0
    return embedding
