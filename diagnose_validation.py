"""
Diagnostic: why is every real corpus row failing SchemaValidator?
Prints the raw row + the actual exception for the first few failures.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

from phase2.ingestion.schema_validator import SchemaValidator, SchemaValidationError

CORPUS_PATH = "pretrain_corpus.parquet"

df = pd.read_parquet(CORPUS_PATH, columns=[
    "entity_id", "timestamp", "cloud", "entity_type", "namespace",
    "metric_name", "value",
])

print("dtypes:")
print(df.dtypes)
print()
print("first row raw:")
first_row = df.iloc[0].to_dict()
for k, v in first_row.items():
    print(f"  {k!r}: {v!r}  (type={type(v).__name__})")

print()
print("--- validation attempts on first 10 rows ---")
n_ok, n_fail = 0, 0
for i, row in enumerate(df.head(10).to_dict(orient="records")):
    try:
        rec = SchemaValidator.validate(row)
        n_ok += 1
        print(f"row {i}: OK -> {rec}")
    except SchemaValidationError as exc:
        n_fail += 1
        print(f"row {i}: FAILED -> {exc}")

print(f"\n{n_ok} ok, {n_fail} failed out of 10")