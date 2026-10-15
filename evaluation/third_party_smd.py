"""
Third-party incidents: Server Machine Dataset (Su et al., KDD 2019; github.com/NetManAIOps/OmniAnomaly), run against the
self-calibrated design with nothing tuned on it.

    python -m evaluation.third_party_smd run      # runs the strategies on every machine/metric entity
    python -m evaluation.third_party_smd report

What it is. 28 server machines of an internet company, 38 metrics each (cpu, memory, network, disk, ...), one reading per
minute for 33-40 days; operators labelled incident segments (second half of each machine's data) and the metrics each
incident involved ("interpretation labels"). Hourly means of the real, chronological series are used as they are: nothing is
injected, resampled or re-ordered. Files are fetched by scripts/fetch_smd.sh (8 machines used: machine-1-1 ... machine-1-8).

What it is not. These are operational incidents, not baseline poisoning, and not security attacks. The series are too short
for the 60-day protocol of the CoreStack runs: snapshot after 8 days, calibration days 8-14, guard active from day 15, end
at day 32 (profile "smd" in scenarios.py). Promotion steps need at least 14 days apart, so promotion is not exercised. The
calendar is unknown: the first day is treated as a Monday. The labels are incomplete (unlabelled incidents exist), so
"false alerts" on unlabelled days are an upper bound on the true false-alert rate.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys
from pathlib import Path

os.environ["EVAL_PROFILE"] = "smd"
import numpy as np  # noqa: E402

from evaluation.data import Entity, _bucket_scales, _residual_scale  # noqa: E402
from evaluation.margin_rule import selfcal  # noqa: E402
from evaluation.scenarios import BOUNDS_DAY, END_DAY, SNAPSHOT_DAY, Scenario  # noqa: E402
from evaluation.simulate import run  # noqa: E402
from phase0.guard import GuardConfig  # noqa: E402
from phase0.guard.calibration import MIN_BOUND  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/external/smd"
OUT = ROOT / "docs/patent_evaluation"
MACHINES = [f"machine-1-{i}" for i in range(1, 9)]
MIN_EVENT_MINUTES = 60  # segments shorter than this vanish in hourly means
MARGIN_DAYS = 1  # unlabelled days within this distance of any labelled minute are not counted as clean
B = int(os.environ.get("SMD_B", "40"))
ALPHA = 0.05
LEDGER = GuardConfig(promotion_mode="ledger")
LEDGER_FREEZE = GuardConfig(promotion_mode="ledger", freeze_on_hold=True)
VARIANTS = {"adaptive": ("adaptive", None, "adaptive"), "H": ("guard_cal", GuardConfig(promotion_mode="none", freeze_on_hold=True), "guard"),
            "full": ("guard_cal", LEDGER_FREEZE, "guard"), "full_B": ("guard_cal", LEDGER, "guard")}


def load_machine(m):
    tr = np.loadtxt(DATA / "train" / f"{m}.txt", delimiter=",")
    te = np.loadtxt(DATA / "test" / f"{m}.txt", delimiter=",")
    lab = np.loadtxt(DATA / "test_label" / f"{m}.txt")
    X = np.vstack([tr, te])
    n_h = (X.shape[0] // 60)
    H = X[: n_h * 60].reshape(n_h, 60, X.shape[1]).mean(axis=1)
    segs = []
    for line in open(DATA / "interpretation_label" / f"{m}.txt"):
        line = line.strip()
        if not line:
            continue
        rng_, dims = line.split(":")
        a, b = (int(x) for x in rng_.split("-"))
        segs.append({"start_min": tr.shape[0] + a - 1, "end_min": tr.shape[0] + b - 1, "dims": [int(x) - 1 for x in dims.split(",")]})
    labelled_min = np.zeros(X.shape[0], bool)
    labelled_min[tr.shape[0]:] = lab > 0
    return H, segs, labelled_min, tr.shape[0]


def build():
    ents, meta = [], {}
    for m in MACHINES:
        H, segs, labelled_min, n_train = load_machine(m)
        v_all = H[: END_DAY * 24]
        if v_all.shape[0] < END_DAY * 24:
            continue
        lab_days = np.zeros(END_DAY, bool)
        for i in np.nonzero(labelled_min)[0]:
            d = i // 1440
            if d < END_DAY:
                lab_days[d] = True
        clean_days = [d for d in range(BOUNDS_DAY, END_DAY) if not lab_days[max(0, d - MARGIN_DAYS):d + MARGIN_DAYS + 1].any()]
        for j in range(H.shape[1]):
            v = np.asarray(v_all[:, j], float)
            first = v[: SNAPSHOT_DAY * 24]
            if np.std(first) <= 1e-9 or len(np.unique(np.round(v, 6))) < 5:
                continue
            hs = _residual_scale(first)
            if hs / (np.std(first) + 1e-12) < 0.05:
                continue
            ev = []
            for s in segs:
                if j in s["dims"] and (s["end_min"] - s["start_min"] + 1) >= MIN_EVENT_MINUTES:
                    d0, d1 = s["start_min"] // 1440, s["end_min"] // 1440
                    if d0 >= BOUNDS_DAY and d1 < END_DAY:
                        ev.append((int(d0), int(d1)))
            e = Entity(entity_id=f"{m}|d{j}", source=m, group=f"smd:d{j}", replica=0, values=v, hour_scale=hs, bucket_scale=_bucket_scales(first))
            ents.append(e)
            meta[e.entity_id] = {"events": ev, "clean_days": clean_days}
    return ents, meta


def _cal(args):
    i, e = args
    return selfcal(e, e.values, B, ALPHA, seed=i)


def _one(args):
    i, e, cal, default, mt = args
    out = {"id": e.entity_id, "source": e.source, **mt, "res": {}, "bound": (cal["bw"], cal["bc"])}
    for lab, (strat, cfg, kind) in VARIANTS.items():
        kw = {} if cfg is None else {"default_bounds": default, "cohort_stats": None, "raw_bounds": (cal["bw"], cal["bc"]), "guard_config": cfg}
        r = run(e, Scenario("control"), strat, **kw)
        days = sorted(r.alert_days if kind == "adaptive" else r.incident_days)
        out["res"][lab] = {"days": days, "flag_days": sorted(r.flag_days), "held_end": (END_DAY - 1) in r.held_end_days, "drift_final": r.stored_drift_final,
                           "hold_days": len(r.hold_days), "bound_source": r.bound_source, "steps": len(r.ledger or [])}
    return out


def main_run():
    E, meta = build()
    print("entities", len(E), "machines", len({e.source for e in E}), "events", sum(len(meta[e.entity_id]["events"]) for e in E), flush=True)
    with mp.Pool(2) as pool:
        cals = pool.map(_cal, list(enumerate(E)), chunksize=1)
        raw = [(max(MIN_BOUND, c["bw"]), max(MIN_BOUND, c["bc"])) for c in cals]
        default = (float(np.median([b[0] for b in raw])), float(np.median([b[1] for b in raw])))
        print("default bound (median own bound)", default, flush=True)
        rows = pool.map(_one, [(i, E[i], cals[i], default, meta[E[i].entity_id]) for i in range(len(E))], chunksize=1)
    (OUT / "third_party_smd.json").write_text(json.dumps({"B": B, "alpha": ALPHA, "default": default, "snapshot": SNAPSHOT_DAY, "bounds": BOUNDS_DAY, "end": END_DAY, "rows": rows}))
    print("done", len(rows))


def boot(rows, f, reps=3000):
    rng = np.random.default_rng(0)
    if not rows:
        return None
    by = {}
    for r in rows:
        by.setdefault(r["source"], []).append(float(f(r)))
    keys = list(by)
    pt = float(np.mean([x for v in by.values() for x in v]))
    bs = [np.mean([x for i in rng.choice(len(keys), len(keys)) for x in by[keys[i]]]) for _ in range(reps)]
    return {"rate": pt, "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5)), "n": len(rows), "machines": len(keys)}


def pct(x):
    return "-" if x is None else f"{100 * x['rate']:.0f}% ({100 * x['lo']:.0f}-{100 * x['hi']:.0f})"


def main_report():
    """Two alert definitions are reported. 'z-flag or incident' is what a deployed system raises: the guard adds incidents to the
    ordinary z-score alerts, it does not replace them. 'incident only' is the convention of final_eval.py for slow attacks (it isolates
    what the guard itself adds) and is shown for comparison."""
    D = json.load(open(OUT / "third_party_smd.json"))
    rows = D["rows"]
    labs = list(rows[0]["res"])
    res = {"n_entities": len(rows), "n_machines": len({r["source"] for r in rows}), "variants": {}}
    events = [(r, ev) for r in rows for ev in r["events"]]
    res["n_events"] = len(events)
    res["n_event_machines"] = len({r["source"] for r, _ in events})
    print(f"entities {len(rows)} from {res['n_machines']} machines; labelled events (>= {MIN_EVENT_MINUTES} min, after day {D['bounds']}): {len(events)} on {res['n_event_machines']} machines")
    for defn in ("union", "incident"):
        print(f"\n-- alert = {'z-flag day or incident' if defn == 'union' else 'incident only (adaptive: z-flag day)'}")
        print(f"{'variant':<10}{'false alert (unlabelled days)':<32}{'alerts per clean day':<24}{'events detected':<20}{'held at end':<14}{'bound = floor':<14}")
        res["variants"][defn] = {}
        for lab in labs:
            def days_of(r):
                x = r["res"][lab]
                return set(x["days"]) | set(x["flag_days"]) if defn == "union" else set(x["days"])
            def fa(r):
                return any(d in set(r["clean_days"]) for d in days_of(r) if d >= D["bounds"])
            def rate(r):
                cd = set(r["clean_days"])
                return len([d for d in days_of(r) if d in cd]) / max(len(cd), 1)
            ev_rows = [dict(source=r["source"], hit=any(d0 <= d <= d1 + 1 for d in days_of(r))) for r, (d0, d1) in events]
            s = {"false_alert": boot([r for r in rows if len(r["clean_days"]) >= 3], fa),
                 "alert_days_per_clean_day": boot([r for r in rows if len(r["clean_days"]) >= 3], rate),
                 "events_detected": boot(ev_rows, lambda x: x["hit"]),
                 "held_end": boot(rows, lambda r: r["res"][lab]["held_end"]),
                 "bound_is_floor": boot(rows, lambda r: max(r["bound"]) <= MIN_BOUND + 1e-9) if lab == "full" else None}
            res["variants"][defn][lab] = s
            print(f"{lab:<10}{pct(s['false_alert']):<32}{pct(s['alert_days_per_clean_day']):<24}{pct(s['events_detected']):<20}{pct(s['held_end']):<14}{pct(s['bound_is_floor']) if s['bound_is_floor'] else '':<14}")
    (OUT / "third_party_smd_results.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    {"run": main_run, "report": main_report}[sys.argv[1]]()
