"""
Diagnostic #2: check validation success/failure PER ENTITY, since the
first 10 raw rows (all from the Web_Apps entity) validated fine, but the
full 3-entity sample used by smoke_test_real_corpus.py failed 100%.
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

from phase2.ingestion.schema_validator import SchemaValidator, SchemaValidationError

CORPUS_PATH = "pretrain_corpus.parquet"

df = pd.read_parquet(CORPUS_PATH, columns=[
    "entity_id", "timestamp", "cloud", "entity_type", "namespace",
    "metric_name", "value",
])

sample_entities = df["entity_id"].unique()[:3]

for entity_id in sample_entities:
    entity_df = df[df["entity_id"] == entity_id].head(50)
    print(f"\n=== entity: {entity_id[:60]}... ===")
    print(f"  rows sampled: {len(entity_df)}")
    print(f"  null counts:\n{entity_df.isnull().sum().to_string()}")

    reasons = Counter()
    n_ok = 0
    first_failure_row = None
    for row in entity_df.to_dict(orient="records"):
        try:
            SchemaValidator.validate(row)
            n_ok += 1
        except SchemaValidationError as exc:
            reasons[str(exc)] += 1
            if first_failure_row is None:
                first_failure_row = row

    print(f"  ok={n_ok}  failed={sum(reasons.values())}")
    if reasons:
        print(f"  failure reasons: {dict(reasons)}")
        print(f"  first failing row: {first_failure_row}")

# Also reproduce the EXACT groupby().apply() step from smoke_test_real_corpus.py
print("\n\n=== reproducing smoke_test_real_corpus.py's groupby/apply step ===")
subset = df[df["entity_id"].isin(sample_entities)]
subset2 = subset.groupby("entity_id", group_keys=False).apply(lambda g: g.head(200))
print(f"subset2 shape: {subset2.shape}")
print(f"subset2 columns: {list(subset2.columns)}")
print(f"subset2 index type: {type(subset2.index)}")
print(subset2.head(3).to_string())

n_ok2, n_fail2 = 0, 0
first_fail = None
for row in subset2.to_dict(orient="records"):
    try:
        SchemaValidator.validate(row)
        n_ok2 += 1
    except SchemaValidationError as exc:
        n_fail2 += 1
        if first_fail is None:
            first_fail = (row, str(exc))

print(f"\nvia groupby/apply reproduction: ok={n_ok2}  failed={n_fail2}")
if first_fail:
    print(f"first failure row: {first_fail[0]}")
    print(f"first failure reason: {first_fail[1]}")