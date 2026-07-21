"""
Models Package
==============

Contains all neural network architectures used in Phase 1.
"""

from .tstcc_encoder import (
    TstccEncoder,
    build_tstcc_encoder,
    build_tstcc_encoder_for_aug_pairs,
    TstccEncoderConfigData,
    EmbeddingLayer,
    EmbeddingLayerConfigData,
    Time2Vec,
    AttentionPooling,
    ProjectionHead,
)

__all__ = [
    "TstccEncoder",
    "build_tstcc_encoder",
    "build_tstcc_encoder_for_aug_pairs",
    "TstccEncoderConfigData",
    "EmbeddingLayer",
    "EmbeddingLayerConfigData",
    "Time2Vec",
    "AttentionPooling",
    "ProjectionHead",
]