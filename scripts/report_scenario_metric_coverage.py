"""Report scenario metric-family coverage against the trained feature vocabulary."""

from __future__ import annotations

import argparse
from pathlib import Path

from demo_generator.generator import DemoGenerator, metric_family_matches


def render_report(generator: DemoGenerator) -> str:
    families = sorted(
        {
            signature.metric_family
            for scenario in generator.scenarios.values()
            for signature in scenario.signature
        }
    )
    lines = [
        "# Scenario metric vocabulary coverage",
        "",
        "Generated from `model_registry/feature_meta.json` by "
        "`scripts/report_scenario_metric_coverage.py`.",
        "",
        "| Metric family | Matching trained metric names | Status |",
        "|---|---|---|",
    ]
    for family in families:
        metric_names = metric_family_matches(family, generator.metric_vocabulary)
        names = ", ".join(f"`{name}`" for name in metric_names) or "—"
        status = "covered" if metric_names else "**unmapped; no metric invented**"
        lines.append(f"| `{family}` | {names} | {status} |")

    clouds = generator._load_feature_clouds()
    missing_providers = sorted(set(("AWS", "Azure", "GCP", "OCI")) - clouds)
    lines.extend(
        [
            "",
            "## Provider vocabulary note",
            "",
            f"The trained `cloud` vocabulary contains: {', '.join(sorted(clouds)) or 'none'}.",
            "Providers without a trained cloud category: "
            f"{', '.join(missing_providers) or 'none'}.",
            "OCI is offered in the synthetic control panel, but this bundle has no OCI cloud "
            "category; its categorical cloud embedding may therefore use UNK.",
            "",
            "Unmapped metric families are skipped by event generation and logged. This report "
            "does not substitute a different metric name.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docs" / "scenario_metric_coverage.md",
    )
    arguments = parser.parse_args()
    generator = DemoGenerator()
    report = render_report(generator)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(report, encoding="utf-8")
    print(f"Wrote {arguments.output}")


if __name__ == "__main__":
    main()
