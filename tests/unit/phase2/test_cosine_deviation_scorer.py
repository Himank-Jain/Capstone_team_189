"""
tests/unit/phase2/test_cosine_deviation_scorer.py
Unit tests for P2-M7 CosineDeviationScorer. No Redis/fakeredis needed --
compute_scores() is a pure function over CurrentEmbedding + EntityProfile.
"""
from datetime import datetime, timezone

import numpy as np

from phase2.detection.cosine_deviation_scorer import (
    CosineDeviationScorer,
    compute_cosine_distance,
)
from shared.constants import SCORE_GLOBAL_THRESH, SCORE_LOCAL_THRESH
from shared.types import CurrentEmbedding, EntityProfile


def rand_unit_emb(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=128).astype(np.float32)
    return v / np.linalg.norm(v)


def make_current_embedding(entity_id: str, emb: np.ndarray) -> CurrentEmbedding:
    return CurrentEmbedding(
        entity_id=entity_id,
        emb=emb,
        batch_ts=datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc),
        n_records=1,
        cloud_provider="AWS",
    )


def make_profile(entity_id: str, centroid: np.ndarray, history) -> EntityProfile:
    return EntityProfile(
        entity_id=entity_id,
        centroid_emb=centroid,
        history_embs=history,
        emb_variance=0.0,
        n_records=len(history),
        last_update_ts=datetime.now(timezone.utc),
        cold_start_flag=False,
    )


def test_identical_embeddings_score_zero():
    v = rand_unit_emb(1)
    assert compute_cosine_distance(v, v) < 1e-6
    print("test_identical_embeddings_score_zero PASSED")


def test_orthogonal_embeddings_score_one():
    a = np.zeros(128, dtype=np.float32); a[0] = 1.0
    b = np.zeros(128, dtype=np.float32); b[1] = 1.0
    assert abs(compute_cosine_distance(a, b) - 1.0) < 1e-6
    print("test_orthogonal_embeddings_score_one PASSED")


def test_no_profile_returns_neutral_defaults():
    scorer = CosineDeviationScorer()
    ce = make_current_embedding("vm-new", rand_unit_emb(2))
    result = scorer.compute_scores(ce, profile=None)
    assert result.global_score == 0.5
    assert result.local_score == 0.5
    assert result.global_flag is False
    assert result.local_flag is False
    assert result.entity_id == "vm-new"
    print("test_no_profile_returns_neutral_defaults PASSED")


def test_current_matches_centroid_and_full_history_no_flags():
    scorer = CosineDeviationScorer()
    v = rand_unit_emb(3)
    profile = make_profile("vm-001", centroid=v, history=[v] * 30)
    ce = make_current_embedding("vm-001", v)
    result = scorer.compute_scores(ce, profile)
    assert result.global_score < 1e-6
    assert result.local_score < 1e-6
    assert result.global_flag is False
    assert result.local_flag is False
    print("test_current_matches_centroid_and_full_history_no_flags PASSED")


def test_variable_length_history_under_max():
    scorer = CosineDeviationScorer()
    centroid = rand_unit_emb(4)
    profile = make_profile("vm-002", centroid=centroid, history=[centroid] * 5)
    ce = make_current_embedding("vm-002", centroid)
    result = scorer.compute_scores(ce, profile)
    assert len(profile.history_embs) == 5
    assert result.local_score < 1e-6
    print("test_variable_length_history_under_max PASSED")


def test_empty_history_falls_back_to_global():
    scorer = CosineDeviationScorer()
    centroid = rand_unit_emb(5)
    profile = make_profile("vm-003", centroid=centroid, history=[])
    ce = make_current_embedding("vm-003", rand_unit_emb(6))
    result = scorer.compute_scores(ce, profile)
    assert result.global_score == result.local_score
    print("test_empty_history_falls_back_to_global PASSED")


def test_flags_trip_above_threshold():
    scorer = CosineDeviationScorer()
    dim = 128
    centroid_orth = np.zeros(dim, dtype=np.float32); centroid_orth[1] = 1.0
    far = np.zeros(dim, dtype=np.float32); far[0] = 1.0
    profile = make_profile("vm-004", centroid=centroid_orth, history=[centroid_orth])
    ce = make_current_embedding("vm-004", far)
    result = scorer.compute_scores(ce, profile)
    assert result.global_score > SCORE_GLOBAL_THRESH
    assert result.global_flag is True
    assert result.local_flag is True
    print("test_flags_trip_above_threshold PASSED")


def test_cold_start_flag_on_profile_does_not_change_scoring():
    """A profile with cold_start_flag=True (seeded from global mean by P2-M4)
    is scored exactly like any other profile -- P2-M7 does not special-case it."""
    scorer = CosineDeviationScorer()
    v = rand_unit_emb(7)
    profile = make_profile("vm-005", centroid=v, history=[v] * 3)
    profile.cold_start_flag = True
    ce = make_current_embedding("vm-005", v)
    result = scorer.compute_scores(ce, profile)
    assert result.global_score < 1e-6
    print("test_cold_start_flag_on_profile_does_not_change_scoring PASSED")


if __name__ == "__main__":
    test_identical_embeddings_score_zero()
    test_orthogonal_embeddings_score_one()
    test_no_profile_returns_neutral_defaults()
    test_current_matches_centroid_and_full_history_no_flags()
    test_variable_length_history_under_max()
    test_empty_history_falls_back_to_global()
    test_flags_trip_above_threshold()
    test_cold_start_flag_on_profile_does_not_change_scoring()
