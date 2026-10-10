"""
tests/unit/phase2/test_mmd_drift_monitor.py
Unit tests for P2-M8 mmd_rbf / median_heuristic_sigma / MmdDriftMonitor.
No Redis/fakeredis needed -- MmdDriftMonitor only depends on
BaseEntityStoreReader, satisfied here by a plain in-memory fake.
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np
import pytest

from phase2.detection.mmd_drift_monitor import (
    MmdDriftMonitor,
    median_heuristic_sigma,
    mmd_rbf,
    rbf_kernel_matrix,
)
from phase2.store.base_entity_store import BaseEntityStoreReader
from shared.constants import SCORE_DRIFT_THRESH
from shared.types import EntityProfile


# ─────────────────────────────────────────────────────────────────────────────
# Fake reader (implements only what MmdDriftMonitor needs)
# ─────────────────────────────────────────────────────────────────────────────

class FakeEntityStoreReader(BaseEntityStoreReader):
    def __init__(self, profiles: Optional[Dict[str, EntityProfile]] = None):
        self._profiles = profiles or {}

    def set_profile(self, entity_id: str, profile: EntityProfile) -> None:
        self._profiles[entity_id] = profile

    def fetch_entity_profile(self, entity_id: str) -> Optional[EntityProfile]:
        return self._profiles.get(entity_id)

    def fetch_current_embedding(self, entity_id: str):
        raise NotImplementedError

    def list_known_entity_ids(self) -> List[str]:
        return list(self._profiles.keys())

    async def fetch_entity_profile_async(self, entity_id: str):
        raise NotImplementedError

    async def fetch_current_embedding_async(self, entity_id: str):
        raise NotImplementedError


def rand_unit_emb(seed: int, dim: int = 128) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=dim).astype(np.float32)
    return v / np.linalg.norm(v)


def cluster_embs(n: int, center_seed: int, noise_scale: float, dim: int = 128) -> List[np.ndarray]:
    """n unit-normalised embeddings clustered around a fixed random center."""
    center = rand_unit_emb(center_seed, dim=dim)
    rng = np.random.default_rng(center_seed + 1000)
    out = []
    for i in range(n):
        v = center + rng.normal(scale=noise_scale, size=dim).astype(np.float32)
        out.append(v / np.linalg.norm(v))
    return out


def make_profile(entity_id: str, history: List[np.ndarray]) -> EntityProfile:
    centroid = np.mean(np.stack(history), axis=0) if history else np.zeros(128, dtype=np.float32)
    if np.linalg.norm(centroid) > 0:
        centroid = centroid / np.linalg.norm(centroid)
    return EntityProfile(
        entity_id=entity_id,
        centroid_emb=centroid,
        history_embs=history,
        emb_variance=0.0,
        n_records=len(history),
        last_update_ts=datetime.now(timezone.utc),
        cold_start_flag=False,
    )


# ─────────────────────────────────────────────────────────────────────────────
# mmd_rbf / rbf_kernel_matrix -- pure math
# ─────────────────────────────────────────────────────────────────────────────

def test_rbf_kernel_matrix_matches_naive_loop():
    rng = np.random.default_rng(0)
    A = rng.normal(size=(6, 4))
    B = rng.normal(size=(5, 4))
    sigma = 1.3
    fast = rbf_kernel_matrix(A, B, sigma)
    naive = np.zeros((6, 5))
    for i in range(6):
        for j in range(5):
            naive[i, j] = np.exp(-np.sum((A[i] - B[j]) ** 2) / (2 * sigma * sigma))
    np.testing.assert_allclose(fast, naive, atol=1e-10)
    print("test_rbf_kernel_matrix_matches_naive_loop PASSED")


def test_rbf_kernel_matrix_rejects_nonpositive_sigma():
    A = np.zeros((3, 2))
    with pytest.raises(ValueError):
        rbf_kernel_matrix(A, A, sigma=0.0)
    print("test_rbf_kernel_matrix_rejects_nonpositive_sigma PASSED")


def test_mmd_identical_distributions_near_zero():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(50, 8))
    Y = rng.normal(size=(50, 8))  # same distribution, different draw
    sigma = median_heuristic_sigma(X, Y)
    value = mmd_rbf(X, Y, sigma=sigma)
    # unbiased estimator can dip slightly negative; should hover near 0
    assert abs(value) < 0.05, f"expected near-zero MMD^2 for same distribution, got {value}"
    print("test_mmd_identical_distributions_near_zero PASSED")


def test_mmd_well_separated_distributions_clearly_positive():
    rng = np.random.default_rng(2)
    X = rng.normal(loc=0.0, size=(50, 8))
    Y = rng.normal(loc=10.0, size=(50, 8))  # far away cluster
    sigma = median_heuristic_sigma(X, Y)
    value = mmd_rbf(X, Y, sigma=sigma)
    assert value > 0.5, f"expected large MMD^2 for well-separated clusters, got {value}"
    print("test_mmd_well_separated_distributions_clearly_positive PASSED")


def test_mmd_requires_at_least_two_samples_per_side():
    X = np.zeros((1, 4))
    Y = np.zeros((5, 4))
    with pytest.raises(ValueError):
        mmd_rbf(X, Y, sigma=1.0)
    print("test_mmd_requires_at_least_two_samples_per_side PASSED")


def test_median_heuristic_sigma_positive_for_spread_data():
    rng = np.random.default_rng(3)
    X = rng.normal(size=(10, 4))
    Y = rng.normal(size=(10, 4))
    sigma = median_heuristic_sigma(X, Y)
    assert sigma > 0
    print("test_median_heuristic_sigma_positive_for_spread_data PASSED")


def test_median_heuristic_sigma_degenerate_falls_back_to_default():
    same_point = np.ones((10, 4))
    sigma = median_heuristic_sigma(same_point, same_point, default_sigma=2.5)
    assert sigma == 2.5
    print("test_median_heuristic_sigma_degenerate_falls_back_to_default PASSED")


# ─────────────────────────────────────────────────────────────────────────────
# MmdDriftMonitor -- integration of the above through a fake store
# ─────────────────────────────────────────────────────────────────────────────

def test_no_profile_returns_neutral_fallback():
    reader = FakeEntityStoreReader()
    monitor = MmdDriftMonitor(reader, rng=np.random.default_rng(0))
    result = monitor.compute_drift("vm-unknown")
    assert result.entity_id == "vm-unknown"
    assert result.drift_score == 0.5
    assert result.drift_flag is False
    print("test_no_profile_returns_neutral_fallback PASSED")


def test_insufficient_history_returns_neutral_fallback():
    reader = FakeEntityStoreReader()
    # only 4 total history embeddings -- far too few to trust a split
    reader.set_profile("vm-thin", make_profile("vm-thin", cluster_embs(4, 1, 0.02)))
    monitor = MmdDriftMonitor(reader, min_samples_per_dist=5, rng=np.random.default_rng(0))
    result = monitor.compute_drift("vm-thin")
    assert result.drift_score == 0.5
    assert result.drift_flag is False
    print("test_insufficient_history_returns_neutral_fallback PASSED")


def test_stable_entity_low_drift_score():
    """History drawn from ONE tight cluster throughout -- past and recent
    slices are statistically indistinguishable, so drift_score should stay
    low and NOT flag."""
    reader = FakeEntityStoreReader()
    history = cluster_embs(30, center_seed=42, noise_scale=0.02)
    reader.set_profile("vm-stable", make_profile("vm-stable", history))
    monitor = MmdDriftMonitor(
        reader,
        min_samples_per_dist=5,
        null_calibration_pairs=200,  # smaller for test speed
        rng=np.random.default_rng(7),
    )
    result = monitor.compute_drift("vm-stable")
    assert 0.0 <= result.drift_score <= 1.0
    assert result.drift_score < SCORE_DRIFT_THRESH
    assert result.drift_flag is False
    print(f"test_stable_entity_low_drift_score PASSED (drift_score={result.drift_score:.4f})")


def test_drifted_entity_high_drift_score_and_flag():
    """First 20 window-embeddings from cluster A, last 10 from a distant
    cluster B -- the 'recent' slice (last 1/3) should land mostly/entirely
    in cluster B, producing a clearly elevated, flagged drift_score."""
    reader = FakeEntityStoreReader()
    past_part = cluster_embs(20, center_seed=10, noise_scale=0.01)
    recent_part = cluster_embs(10, center_seed=99999, noise_scale=0.01)  # far-away center
    history = past_part + recent_part  # chronological oldest-first
    reader.set_profile("vm-drifted", make_profile("vm-drifted", history))
    monitor = MmdDriftMonitor(
        reader,
        min_samples_per_dist=5,
        null_calibration_pairs=200,
        rng=np.random.default_rng(11),
    )
    result = monitor.compute_drift("vm-drifted")
    assert result.drift_score > SCORE_DRIFT_THRESH, (
        f"expected clearly elevated drift_score, got {result.drift_score:.4f}"
    )
    assert result.drift_flag is True
    print(f"test_drifted_entity_high_drift_score_and_flag PASSED (drift_score={result.drift_score:.4f})")


def test_drift_score_always_in_unit_interval():
    reader = FakeEntityStoreReader()
    history = cluster_embs(30, center_seed=5, noise_scale=0.1)
    reader.set_profile("vm-bounded", make_profile("vm-bounded", history))
    monitor = MmdDriftMonitor(
        reader, null_calibration_pairs=200, rng=np.random.default_rng(2)
    )
    result = monitor.compute_drift("vm-bounded")
    assert 0.0 <= result.drift_score <= 1.0
    print("test_drift_score_always_in_unit_interval PASSED")


def test_subsampling_caps_sample_count():
    reader = FakeEntityStoreReader()
    monitor = MmdDriftMonitor(
        reader, max_samples_per_dist=5, rng=np.random.default_rng(0)
    )
    big = np.random.default_rng(0).normal(size=(50, 128))
    sub = monitor._subsample(big)
    assert sub.shape[0] == 5
    small = big[:3]
    sub_small = monitor._subsample(small)
    assert sub_small.shape[0] == 3  # unchanged, below the cap
    print("test_subsampling_caps_sample_count PASSED")


def test_null_calibration_is_cached_per_entity():
    """Calling compute_drift twice for the SAME entity should hit the
    calibration cache the second time -- verified by monkeypatching the
    private calibration method and counting calls."""
    reader = FakeEntityStoreReader()
    history = cluster_embs(30, center_seed=3, noise_scale=0.05)
    reader.set_profile("vm-cached", make_profile("vm-cached", history))
    monitor = MmdDriftMonitor(
        reader, null_calibration_pairs=50, rng=np.random.default_rng(1)
    )

    call_count = {"n": 0}
    original = monitor._calibrate_null_scale

    def counting_wrapper(X, Y, sigma):
        call_count["n"] += 1
        return original(X, Y, sigma)

    monitor._calibrate_null_scale = counting_wrapper

    monitor.compute_drift("vm-cached")
    monitor.compute_drift("vm-cached")
    assert call_count["n"] == 1, f"expected calibration to run once and be cached, ran {call_count['n']} times"
    print("test_null_calibration_is_cached_per_entity PASSED")


def test_invalidate_calibration_forces_recompute():
    reader = FakeEntityStoreReader()
    history = cluster_embs(30, center_seed=3, noise_scale=0.05)
    reader.set_profile("vm-invalidate", make_profile("vm-invalidate", history))
    monitor = MmdDriftMonitor(
        reader, null_calibration_pairs=50, rng=np.random.default_rng(1)
    )
    call_count = {"n": 0}
    original = monitor._calibrate_null_scale

    def counting_wrapper(X, Y, sigma):
        call_count["n"] += 1
        return original(X, Y, sigma)

    monitor._calibrate_null_scale = counting_wrapper

    monitor.compute_drift("vm-invalidate")
    monitor.invalidate_calibration("vm-invalidate")
    monitor.compute_drift("vm-invalidate")
    assert call_count["n"] == 2
    print("test_invalidate_calibration_forces_recompute PASSED")


def test_computed_at_is_recent_utc():
    reader = FakeEntityStoreReader()
    history = cluster_embs(30, center_seed=8, noise_scale=0.05)
    reader.set_profile("vm-ts", make_profile("vm-ts", history))
    monitor = MmdDriftMonitor(reader, null_calibration_pairs=50, rng=np.random.default_rng(0))
    before = datetime.now(timezone.utc)
    result = monitor.compute_drift("vm-ts")
    after = datetime.now(timezone.utc)
    assert before <= result.computed_at <= after
    print("test_computed_at_is_recent_utc PASSED")


if __name__ == "__main__":
    test_rbf_kernel_matrix_matches_naive_loop()
    test_rbf_kernel_matrix_rejects_nonpositive_sigma()
    test_mmd_identical_distributions_near_zero()
    test_mmd_well_separated_distributions_clearly_positive()
    test_mmd_requires_at_least_two_samples_per_side()
    test_median_heuristic_sigma_positive_for_spread_data()
    test_median_heuristic_sigma_degenerate_falls_back_to_default()
    test_no_profile_returns_neutral_fallback()
    test_insufficient_history_returns_neutral_fallback()
    test_stable_entity_low_drift_score()
    test_drifted_entity_high_drift_score_and_flag()
    test_drift_score_always_in_unit_interval()
    test_subsampling_caps_sample_count()
    test_null_calibration_is_cached_per_entity()
    test_invalidate_calibration_forces_recompute()
    test_computed_at_is_recent_utc()
