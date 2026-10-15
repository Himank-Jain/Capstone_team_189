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
    """The rule fixed before the results (both conditions)."""
    ok = [(x_sigma(k), k) for k in P if x_sigma(k) is not None and P[k]["absorbed3"]["rate"] <= ABSORB_MAX
          and P[k]["growth_resolved_of_flagged"] is not None and P[k]["growth_resolved_of_flagged"]["rate"] >= RESOLVE_MIN]
    return sorted(ok)


def descriptive_range(slack=0.02):
    """Post hoc and descriptive, not the pre-declared rule: linked settings whose absorption is within `slack` of hold-only's
    (the absorption that the bound alone leaves) while at least RESOLVE_MIN - 0.05 of flagged growth is resolved."""
    base = P["hold_only"]["absorbed3"]["rate"]
    return sorted((x_sigma(k), k) for k in P if k.startswith("L") and P[k]["absorbed3"]["rate"] <= base + slack
                  and P[k]["growth_resolved_of_flagged"]["rate"] >= RESOLVE_MIN - 0.05)


def main():
    fig, ax = plt.subplots(figsize=(8.6, 5.0), dpi=160)
    red, blue, grey = "#c0392b", "#1f6f8b", "#555555"
    fam = family("L")
    xs = [x for x, _ in fam]
    for key, c, ls, lw in (("absorbed3", red, "-", 2.2), ("growth_resolved_of_flagged", blue, "-", 2.2), ("absorbed_fast4", grey, ":", 1.6)):
        ys = [P[k][key]["rate"] * 100 for _, k in fam]
        ax.plot(xs, ys, ls, color=c, lw=lw, marker="o", ms=4)
        if key != "absorbed_fast4":
            ax.fill_between(xs, [P[k][key]["lo"] * 100 for _, k in fam], [P[k][key]["hi"] * 100 for _, k in fam], color=c, alpha=0.12, lw=0)
    for key, c in (("absorbed3", red), ("growth_resolved_of_flagged", blue)):  # unlinked family, thin dashed
        f2 = family("F")
        ax.plot([x for x, _ in f2], [P[k][key]["rate"] * 100 for _, k in f2], "--", color=c, lw=1.0, marker="s", ms=3, alpha=0.7)
    ho, nc = P["hold_only"], P["no_cap"]
    for key, c in (("absorbed3", red), ("growth_resolved_of_flagged", blue)):
        ax.plot([xs[0] / 1.35], [ho[key]["rate"] * 100], marker="D", color=c, ms=6, mfc="white")
        ax.plot([xs[-1] * 1.35], [nc[key]["rate"] * 100], marker="D", color=c, ms=6, mfc="white")
    ax.text(xs[0] / 1.35, 104, "hold\nonly", ha="center", va="bottom", fontsize=7.5, color=grey)
    ax.text(xs[-1] * 1.35, 104, "no\ncap", ha="center", va="bottom", fontsize=7.5, color=grey)
    rng = descriptive_range()
    if rng:
        ax.axvspan(rng[0][0] / 1.12, rng[-1][0] * 1.12, color="#2e8b57", alpha=0.13, lw=0)
        ax.text((rng[0][0] * rng[-1][0]) ** 0.5, 92, "proposed range\n(post hoc)", ha="center", va="center", fontsize=8, color="#2e8b57")
    ax.axhline(ABSORB_MAX * 100, color=red, lw=0.7, ls=":")
    ax.text(xs[-1] * 1.6, ABSORB_MAX * 100 + 1.5, "5% rule", fontsize=7, color=red, ha="right")
    ax.text(xs[-1] * 1.45, 41, "growth resolved", color=blue, fontsize=8.5, ha="right", va="top")
    ax.text(xs[-1] * 1.45, 70, "3σ attack absorbed", color=red, fontsize=8.5, ha="right", va="top")
    ax.text(xs[-1] * 1.45, 99, "fast 4σ attack absorbed", color=grey, fontsize=8.5, ha="right", va="top")
    ax.set_xscale("log")
    ticks = [0.25, 0.5, 1, 2, 4, 8]
    ax.set_xticks(ticks, [f"{t:g}" for t in ticks])
    ax.minorticks_off()
    ax.set_xlim(xs[0] / 1.8, xs[-1] * 1.8)
    ax.set_xlabel("promotion allowance per step, scale units (median entity)   |   top axis: multiples of the validated bound")
    ax.set_ylabel("% of entities")
    ax.set_ylim(-3, 112)
    sec = ax.secondary_xaxis("top", functions=(lambda x: x / (P["L1"]["median_bound_unit"] or 0.5), lambda k: k * (P["L1"]["median_bound_unit"] or 0.5)))
    sec.set_xticks([0.5, 1, 2, 4, 8, 16], ["0.5", "1", "2", "4", "8", "16"])
    ax.set_title(f"{DATASET}: attack absorbed vs growth resolved against allowance ({'stable shadow alone' if MODE == 'ev0' else 'with change-event draws'}); dashed = fixed unit", fontsize=8.5, pad=24)
    ax.spines[["right"]].set_visible(False)
    fig.tight_layout()
    path = OUT / f"allowance_curve_{MODE}_{DATASET}.png"
    fig.savefig(path)
    print("wrote", path)
    print("pre-declared operating range (sigma per step, label):", [(round(x, 3), k) for x, k in operating_range()] or "no setting satisfies both conditions")
    print("descriptive range (post hoc):", [(round(x, 3), k) for x, k in rng])
    for f_ in ("L", "F"):
        for x, k in family(f_):
            p = P[k]
            print(f"{k:<6}{x:>6.2f}σ  absorbed {100*p['absorbed3']['rate']:>5.1f}%  resolved {100*p['growth_resolved_of_flagged']['rate']:>5.1f}%  fast4 absorbed {100*p['absorbed_fast4']['rate']:>5.1f}%")


if __name__ == "__main__":
    main()
