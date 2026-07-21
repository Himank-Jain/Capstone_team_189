from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Union

import pandas as pd


class SchemaValidationError(ValueError):
    """Raised when a record violates the canonical corpus schema."""


class CorpusIterator:
    """Lazily load corpus files, validate records, normalize timestamps, and yield batches.

    The iterator accepts Parquet or JSON file paths, validates a minimal
    canonical schema, normalizes timestamps to UTC, deduplicates by
    (entity_id, timestamp), and returns dictionaries that are compatible with
    the downstream Phase 1 pipeline.
    """

    REQUIRED_FIELDS = {
        "entity_id",
        "timestamp",
        "op_id",
        "region",
        "cloud_provider",
        "numeric_features",
        "categorical_features",
    }

    def __init__(
        self,
        source_paths: Sequence[Union[str, os.PathLike[str]]],
        batch_size: int = 256,
        chunk_size: Optional[int] = None,
    ) -> None:
        self.source_paths = [Path(path) for path in source_paths]
        if not self.source_paths:
            raise ValueError("source_paths must contain at least one file")
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        self.batch_size = batch_size
        self.chunk_size = chunk_size

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        seen_keys: set[tuple[str, str]] = set()
        pending_records: List[Dict[str, Any]] = []

        for path in self.source_paths:
            for record in self._iter_records_from_path(path):
                normalized = self._normalize_record(record)
                if normalized is None:
                    continue
                dedup_key = (normalized["entity_id"], normalized["timestamp"])
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                pending_records.append(normalized)
                if len(pending_records) >= self.batch_size:
                    yield {"records": pending_records[: self.batch_size]}
                    pending_records = pending_records[self.batch_size :]

        if pending_records:
            yield {"records": pending_records}

    def _iter_records_from_path(self, path: Path) -> Iterator[Dict[str, Any]]:
        if path.suffix.lower() == ".parquet":
            yield from self._iter_parquet_records(path)
        elif path.suffix.lower() == ".json":
            yield from self._iter_json_records(path)
        else:
            raise ValueError(f"Unsupported file type: {path}")

    def _iter_parquet_records(self, path: Path) -> Iterator[Dict[str, Any]]:
        chunk_size = self.chunk_size or 100_000
        dataframe = pd.read_parquet(path, engine="pyarrow", columns=None)
        for _, row in dataframe.iterrows():
            row_dict = row.to_dict()
            yield row_dict

    def _iter_json_records(self, path: Path) -> Iterator[Dict[str, Any]]:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, list):
            for item in payload:
                yield item
        elif isinstance(payload, dict):
            yield payload
        else:
            raise SchemaValidationError("JSON payload must be an object or a list of objects")

    def _normalize_record(self, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(record, dict):
            raise SchemaValidationError("Each input row must be a dictionary")
        missing = [field for field in self.REQUIRED_FIELDS if field not in record]
        if missing:
            raise SchemaValidationError(f"Missing required fields: {missing}")

        normalized = dict(record)
        normalized["entity_id"] = str(record["entity_id"])
        normalized["op_id"] = str(record["op_id"])
        normalized["region"] = str(record["region"])
        normalized["cloud_provider"] = str(record["cloud_provider"])
        normalized["numeric_features"] = self._normalize_numeric_features(record["numeric_features"])
        normalized["categorical_features"] = self._normalize_categorical_features(record["categorical_features"])
        normalized["timestamp"] = self._normalize_timestamp(record["timestamp"])

        if not normalized["entity_id"]:
            raise SchemaValidationError("entity_id cannot be empty")
        if not normalized["timestamp"]:
            raise SchemaValidationError("timestamp cannot be empty")
        return normalized

    @staticmethod
    def _normalize_timestamp(raw_timestamp: Any) -> str:
        if isinstance(raw_timestamp, datetime):
            ts = raw_timestamp
        else:
            ts = pd.to_datetime(str(raw_timestamp), utc=True)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        return ts.isoformat()

    @staticmethod
    def _normalize_numeric_features(raw_numeric_features: Any) -> List[float]:
        if isinstance(raw_numeric_features, (list, tuple)):
            values = []
            for value in raw_numeric_features:
                values.append(float(value))
            return values
        if isinstance(raw_numeric_features, dict):
            return [float(value) for value in raw_numeric_features.values()]
        raise SchemaValidationError("numeric_features must be a list or tuple")

    @staticmethod
    def _normalize_categorical_features(raw_categorical_features: Any) -> Dict[str, Any]:
        if not isinstance(raw_categorical_features, dict):
            raise SchemaValidationError("categorical_features must be a dictionary")
        return {str(key): str(value) for key, value in raw_categorical_features.items()}
