"""
Write only the self-calibrated fleet cache (bounds from each entity's own calibration days) for a dataset.

    python -m evaluation.fleet_cache <dataset> eval

Same computation as the first stage of evaluation.selfcal_eval; used where the full self-calibrated evaluation is not needed
(the long-horizon sets, whose bounds depend on the horizon and cannot be copied from the 100-day set).
"""
from __future__ import annotations

import json
import multiprocessing as mp

from evaluation.final_eval import DATASET, build
from evaluation.selfcal_eval import ALPHA, B, FLEET_CACHE, _fleet

if __name__ == "__main__":
    E = build()
    print(DATASET, "fleet cache, alpha", ALPHA, "B", B, "entities", len(E), flush=True)
    if FLEET_CACHE.exists():
        print("exists", FLEET_CACHE)
    else:
        with mp.Pool(2) as pool:
            fleet = pool.map(_fleet, [(i, e) for i, e in enumerate(E)], chunksize=1)
        FLEET_CACHE.write_text(json.dumps(fleet))
        print("wrote", FLEET_CACHE, len(fleet))
