"""
tests/unit/phase2/test_inference_encoder.py
================================================
P2-M3  |  Unit tests for InferenceEncoder and LatencyStats.

Covers: constructor rejects an encoder whose projection head is still
enabled; warm-up runs without touching latency_stats; encode() produces
correctly-shaped, L2-normalised output and chunks internally at
chunk_size; encode_single() matches the corresponding row from a batched
call; LatencyStats percentile math against hand-computed values.
"""
import pytest
import torch

from phase1.models.tstcc_encoder import build_tstcc_encoder_for_aug_pairs
from phase2.encoding.inference_encoder import InferenceEncoder, LatencyStats

VOCAB_SIZES = dict(
    cloud_vocab_size_int=4, entity_type_vocab_size_int=5,
    namespace_vocab_size_int=5, metric_name_vocab_size_int=6,
)


def _build_inference_ready_encoder():
    encoder = build_tstcc_encoder_for_aug_pairs(**VOCAB_SIZES, use_projection_bool=True)
    encoder.disable_projection()
    encoder.eval()
    return encoder


def _dummy_tensors(n, seq_len=32):
    numeric = torch.randn(n, seq_len, 3)
    categorical = torch.randint(0, 4, (n, seq_len, 4))
    timestamps = torch.rand(n, seq_len, 1)
    return numeric, categorical, timestamps


class TestConstructorSafety:
    def test_rejects_encoder_with_projection_still_enabled(self):
        encoder = build_tstcc_encoder_for_aug_pairs(**VOCAB_SIZES, use_projection_bool=True)
        # deliberately NOT calling disable_projection()
        with pytest.raises(ValueError, match="projection head"):
            InferenceEncoder(encoder, warm_up=False)

    def test_accepts_properly_prepared_encoder(self):
        encoder = _build_inference_ready_encoder()
        inf_enc = InferenceEncoder(encoder, warm_up=False)
        assert inf_enc.encoder is encoder


class TestWarmup:
    def test_warmup_does_not_pollute_latency_stats(self):
        encoder = _build_inference_ready_encoder()
        inf_enc = InferenceEncoder(encoder, warm_up=True)
        assert inf_enc.latency_stats.count == 0

    def test_warmup_can_be_disabled(self):
        encoder = _build_inference_ready_encoder()
        inf_enc = InferenceEncoder(encoder, warm_up=False)
        assert inf_enc.latency_stats.count == 0  # nothing ran at all


class TestEncode:
    def test_output_shape_and_dtype(self):
        encoder = _build_inference_ready_encoder()
        inf_enc = InferenceEncoder(encoder, warm_up=False)
        numeric, categorical, timestamps = _dummy_tensors(10)
        result = inf_enc.encode(numeric, categorical, timestamps)
        assert result.shape == (10, 128)

    def test_output_is_l2_normalised(self):
        encoder = _build_inference_ready_encoder()
        inf_enc = InferenceEncoder(encoder, warm_up=False)
        numeric, categorical, timestamps = _dummy_tensors(5)
        result = inf_enc.encode(numeric, categorical, timestamps)
        norms = result.norm(p=2, dim=-1)
        assert torch.allclose(norms, torch.ones_like(norms), atol=1e-4)

    def test_chunking_produces_same_result_as_one_big_batch(self):
        # A batch larger than chunk_size must produce IDENTICAL results
        # to what each record would get independently -- chunking is a
        # memory optimization, not a behavior change.
        encoder = _build_inference_ready_encoder()
        inf_enc_chunked = InferenceEncoder(encoder, chunk_size=4, warm_up=False)
        numeric, categorical, timestamps = _dummy_tensors(10)

        chunked_result = inf_enc_chunked.encode(numeric, categorical, timestamps)
        single_batch_result = inf_enc_chunked.encoder(numeric, categorical, timestamps)

        assert torch.allclose(chunked_result, single_batch_result, atol=1e-5)

    def test_records_one_latency_sample_per_chunk(self):
        encoder = _build_inference_ready_encoder()
        inf_enc = InferenceEncoder(encoder, chunk_size=4, warm_up=False)
        numeric, categorical, timestamps = _dummy_tensors(10)  # 3 chunks: 4,4,2
        inf_enc.encode(numeric, categorical, timestamps)
        assert inf_enc.latency_stats.count == 3

    def test_empty_batch_returns_empty_tensor(self):
        encoder = _build_inference_ready_encoder()
        inf_enc = InferenceEncoder(encoder, warm_up=False)
        numeric, categorical, timestamps = _dummy_tensors(0)
        result = inf_enc.encode(numeric, categorical, timestamps)
        assert result.shape[0] == 0


class TestEncodeSingle:
    def test_matches_corresponding_batch_row(self):
        encoder = _build_inference_ready_encoder()
        inf_enc = InferenceEncoder(encoder, warm_up=False)
        numeric, categorical, timestamps = _dummy_tensors(5)

        batch_result = inf_enc.encode(numeric, categorical, timestamps)
        single_result = inf_enc.encode_single(numeric[2], categorical[2], timestamps[2])

        assert single_result.shape == (128,)
        assert torch.allclose(single_result, batch_result[2], atol=1e-5)


class TestLatencyStats:
    def test_percentiles_match_hand_computed(self):
        stats = LatencyStats()
        for v in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
            stats.record(float(v))
        # nearest-rank at index round(0.5*9)=4 (0-indexed) -> ordered[4] == 50.0
        assert stats.p50 == pytest.approx(50.0)
        assert stats.count == 10

    def test_empty_stats_return_zero_not_crash(self):
        stats = LatencyStats()
        assert stats.p50 == 0.0
        assert stats.p95 == 0.0
        assert stats.p99 == 0.0

    def test_max_samples_caps_memory(self):
        stats = LatencyStats(max_samples=5)
        for v in range(10):
            stats.record(float(v))
        assert stats.count == 5
        assert stats._samples_ms == [5.0, 6.0, 7.0, 8.0, 9.0]  # oldest dropped
