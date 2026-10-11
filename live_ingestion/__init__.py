"""Canonical package for read-only live cloud ingestion connectors."""

from .connectors.base_live_ingestor import BaseLiveIngestor, LiveIngestorConfigData

__all__ = ["BaseLiveIngestor", "LiveIngestorConfigData"]
