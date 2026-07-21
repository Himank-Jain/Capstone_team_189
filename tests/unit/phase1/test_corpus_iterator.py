import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase1.corpus.corpus_iterator import CorpusIterator


def test_corpus_iterator_parquet_and_json(tmp_path):
    parquet_path = tmp_path / "sample.parquet"
    json_path = tmp_path / "sample.json"

    records = [
        {
            "entity_id": "entity-1",
            "timestamp": "2025-01-01T00:00:00Z",
            "op_id": "op-1",
            "region": "us-east-1",
            "cloud_provider": "AWS",
            "numeric_features": [1.1, 2.2],
            "categorical_features": {"namespace": "prod", "metric_name": "cpu"},
        },
        {
            "entity_id": "entity-1",
            "timestamp": "2025-01-01T00:01:00+00:00",
            "op_id": "op-2",
            "region": "us-east-1",
            "cloud_provider": "AWS",
            "numeric_features": [3.3, 4.4],
            "categorical_features": {"namespace": "prod", "metric_name": "cpu"},
        },
        {
            "entity_id": "entity-2",
            "timestamp": "2025-01-01T00:02:00Z",
            "op_id": "op-3",
            "region": "eu-west-1",
            "cloud_provider": "Azure",
            "numeric_features": [5.5, 6.6],
            "categorical_features": {"namespace": "dev", "metric_name": "mem"},
        },
    ]

    pd.DataFrame(records).to_parquet(parquet_path, index=False)
    json_path.write_text(json.dumps(records[:2]), encoding="utf-8")

    iterator = CorpusIterator(source_paths=[parquet_path, json_path], batch_size=2)
    batches = list(iterator)

    assert len(batches) == 2
    first_batch = batches[0]["records"]
    assert len(first_batch) == 2
    assert first_batch[0]["timestamp"].endswith("+00:00")
    assert first_batch[0]["cloud_provider"] == "AWS"
    assert first_batch[0]["numeric_features"] == [1.1, 2.2]
    assert first_batch[0]["categorical_features"]["metric_name"] == "cpu"
    assert first_batch[1]["timestamp"].endswith("+00:00")
