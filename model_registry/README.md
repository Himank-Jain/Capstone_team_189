# Model registry artifacts

`tstcc_encoder_final.pt` and `artifacts_manifest.json` are preserved registry
inputs. Do not remove them during repository cleanup. The active `0.2.0`
bundle in `synthetic_32/` is also retained because the manifest points to its
checkpoint and FAISS index. Other corpus outputs, checkpoints, indexes, and
index metadata are local generated artifacts and are ignored by Git.

## Rebuild a model bundle

Run these commands from the repository root, using the same
`aug_pairs.parquet` for metadata generation, training, and indexing. To recreate the 32-resource synthetic seed corpus without MongoDB, run this
from the repository root:

```python
from scripts.generate_corpus import (
    CONFIG,
    build_corpus,
    generate_synthetic_anchors,
    generate_synthetic_seeds,
    write_output,
)

CONFIG["max_resources"] = 32
CONFIG["output_dir"] = "./corpus_output/synthetic_32"
seeds = generate_synthetic_seeds(CONFIG)
anchors = generate_synthetic_anchors(seeds, CONFIG)
write_output(build_corpus(seeds, anchors, CONFIG), CONFIG)
```

This creates `pretrain_corpus.parquet`; the training steps below also require
an event-based `aug_pairs.parquet` created by a compatible augmentation
producer. The repository's standalone legacy pair-generation scripts use an
older wide schema and are not compatible with this training pipeline.

Then generate metadata, train, and build the FAISS index:

```powershell
python scripts/generate_feature_meta.py --parquet <aug_pairs.parquet> --out model_registry/feature_meta.json
python -m phase1.train.train_tstcc --parquet <aug_pairs.parquet> --epochs 20 --checkpoint-dir model_registry
python scripts/build_faiss_index.py --parquet <aug_pairs.parquet> --checkpoint model_registry/tstcc_encoder_final.pt --out model_registry/behavioral_space
```

The metadata must remain version-locked to the checkpoint: do not regenerate
it from a different corpus when registering an existing checkpoint. Register
the resulting files with `phase1.registry.model_registry.ModelRegistry` and
`phase1.registry.artifact_bundle.ArtifactBundle`, passing the matching
`feature_meta.json` and the FAISS output prefix (without `.faiss` or
`.meta.pkl`). For example, after choosing a new version identifier:

```python
import json
from pathlib import Path

from phase1.registry.artifact_bundle import ArtifactBundle
from phase1.registry.model_registry import ModelRegistry, ModelRegistryConfigData

registry = ModelRegistry(ModelRegistryConfigData())
bundle = ArtifactBundle(
    version_str="0.2.1",
    encoder_path=Path("model_registry/tstcc_encoder_final.pt"),
    faiss_index_path=Path("model_registry/behavioral_space"),
    config_dict=json.loads(Path("model_registry/config.json").read_text(encoding="utf-8")),
    feature_meta_dict=json.loads(
        Path("model_registry/feature_meta.json").read_text(encoding="utf-8")
    ),
)
registry.register(bundle)
```

Keep each registered model version's source corpus and build settings
available for reproducibility.

Generated runtime artifacts belong under `model_registry/`; source code and
the registry instructions belong in the tracked project tree.
