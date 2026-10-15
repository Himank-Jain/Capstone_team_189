"""
Plot the promotion trade-off and name the operating range.

    python -m evaluation.allowance_plot <dataset> [ev0|ev]

Reads allowance_curve_curve_ev0_<dataset>.json (stable shadow alone justifies the step) or allowance_curve_curve_<dataset>.json
(change-event draws of the frozen protocol), as written by `python -m evaluation.ablation_report <dataset> curve_ev0|curve`.

Range rule (docs/patent_evaluation/ABLATION.md, fixed before the results): every allowance setting with at most 5% of 3 sigma
stealth attacks absorbed (point estimate) and at least 50% of flagged legitimate growth resolved at the end of the horizon.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

DATASET = sys.argv[1]
MODE = sys.argv[2] if len(sys.argv) > 2 else "ev0"
SET = "curve_ev0" if MODE == "ev0" else "curve"
OUT = Path(__file__).resolve().parents[1] / "docs/patent_evaluation"
R = json.load(open(OUT / f"allowance_curve_{SET}_{DATASET}.json"))
P = R["points"]
ABSORB_MAX, RESOLVE_MIN = 0.05, 0.50


def x_sigma(lab):
    if lab.startswith("F"):
        return float(lab[1:])
    if lab.startswith("L"):
        return float(lab[1:]) * (P[lab]["median_bound_unit"] or 0.5)
    return None


def family(prefix):
    pts = [(x_sigma(k), k) for k in P if k.startswith(prefix)]
    return sorted(pts)


def operating_range():
    ok = [(x_sigma(k), k) for k in P if x_sigma(k) is not None and P[k]["absorbed3"]["rate"] <= ABSORB_MAX
          and P[k]["growth_resolved_of_flagged"] is not None and P[k]["growth_resolved_of_flagged"]["rate"] >= RESOLVE_MIN]
    return sorted(ok)


def main():
    fig, ax = plt.subplots(figsize=(8.6, 4.8), dpi=160)
    col = {"abs": "#c0392b", "res": "#1f6f8b"}
    for prefix, ls, lab_sfx, alpha in (("L", "-", "multiple of validated bound (linked)", 1.0), ("F", "--", "fixed scale units (unlinked)", 0.75)):
        fam = family(prefix)
        xs = [x for x, _ in fam]
        for key, c, name in (("absorbed3", col["abs"], "3σ attack absorbed"), ("growth_resolved_of_flagged", col["res"], "flagged growth resolved")):
            ys = [P[k][key]["rate"] * 100 for _, k in fam]
            lo = [P[k][key]["lo"] * 100 for _, k in fam]
            hi = [P[k][key]["hi"] * 100 for _, k in fam]
            ax.plot(xs, ys, ls, color=c, lw=2.0 if prefix == "L" else 1.4, marker="o", ms=4, alpha=alpha, label=f"{name}, {lab_sfx}")
            if prefix == "L":
                ax.fill_between(xs, lo, hi, color=c, alpha=0.12, lw=0)
    rng = operating_range()
    if rng:
        ax.axvspan(rng[0][0] * 0.9, rng[-1][0] * 1.1, color="#2e8b57", alpha=0.12, lw=0)
        ax.text((rng[0][0] * rng[-1][0]) ** 0.5, 103, "operating range", ha="center", va="bottom", fontsize=9, color="#2e8b57")
    ax.axhline(ABSORB_MAX * 100, color=col["abs"], lw=0.7, ls=":")
    ax.axhline(RESOLVE_MIN * 100, color=col["res"], lw=0.7, ls=":")
    ax.set_xscale("log")
    ax.set_xlabel("promotion allowance per step (scale units, log scale)")
    ax.set_ylabel("% of entities")
    ax.set_ylim(-3, 108)
    ax.set_title(f"{DATASET}: attack absorbed vs growth resolved ({'stable shadow alone' if MODE == 'ev0' else 'with change-event draws'})", fontsize=10)
    ax.legend(fontsize=7.5, loc="center left", frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    path = OUT / f"allowance_curve_{MODE}_{DATASET}.png"
    fig.savefig(path)
    print("wrote", path)
    print("operating range (sigma per step, label):", [(round(x, 3), k) for x, k in rng] or "no setting satisfies both conditions")
    for fam in ("L", "F"):
        for x, k in family(fam):
            p = P[k]
            print(f"{k:<6}{x:>6.2f}σ  absorbed {100*p['absorbed3']['rate']:>5.1f}%  resolved {100*p['growth_resolved_of_flagged']['rate'] if p['growth_resolved_of_flagged'] else float('nan'):>5.1f}%")


if __name__ == "__main__":
    main()
