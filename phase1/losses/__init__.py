"""
Loss Functions
==============

Contrastive learning objectives.
"""

from .ntxent_loss import (
    NTXentLossComputer,
    NTXentLossConfigData,
)

__all__ = [
    "NTXentLossComputer",
    "NTXentLossConfigData",
]