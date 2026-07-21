import pandas as pd
import pyarrow.parquet as pq

# Sample only 2 row groups instead of loading all 17M rows
pf = pq.ParquetFile('aug_pairs.parquet')
df = pf.read_row_group(0).to_pandas()  # ~20k rows, fast

print(f"Sample size: {len(df)} rows")

# 1. Pair integrity
counts = df.groupby('pair_id')['view'].count()
assert (counts == 2).all(), f"Bad pairs: {counts[counts != 2]}"
views = df.groupby('pair_id')['view'].apply(set)
assert (views == {'a', 'b'}).all(), "Missing a or b view"
print("✓ Pair integrity OK")

# 2. Timestamp jitter
a = df[df['view'] == 'a'].set_index('pair_id')
b = df[df['view'] == 'b'].set_index('pair_id')
ts_diff = (a['timestamp'] - b['timestamp']).abs()
print(f"✓ Timestamp jitter mean_diff={ts_diff.mean()}")

# 3. Mask flags
mask_cols = [c for c in df.columns if c.endswith('_masked')]
for col in mask_cols:
    vals = set(df[col].unique())
    assert vals.issubset({0.0, 1.0}), f"{col} has unexpected values: {vals}"
print(f"✓ Mask flags valid: {mask_cols}")

# 4. Nulls
nulls = df.isnull().sum()
nulls = nulls[nulls > 0]
print("✓ No nulls" if nulls.empty else f"✗ Nulls:\n{nulls}")

print("\nDtypes:\n", df.dtypes)