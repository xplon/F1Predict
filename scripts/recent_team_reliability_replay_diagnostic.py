"""Replay diagnostic for the recent team reliability feature candidate.

This compares the default feature pipeline with the explicit
recent-team-reliability candidate over the same replay rows. It is diagnostic
only: the scored sample is small and there is no held-out split.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from f1predict.calibration import ReplayCalibrationBuilder, ReplayCalibrationReport  # noqa: E402
from f1predict.domain import utc_now  # noqa: E402
from f1predict.features.provider import ProcessedFeatureProvider  # noqa: E402
from f1predict.pipeline import PredictionPipeline  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--as-of", default="2026-07-07T00:00:00+00:00")
    parser.add_argument("--iterations", type=int, default=60)
    parser.add_argument("--output-dir", default="reports/recent_team_reliability_replay_diagnostic")
    args = parser.parse_args()

    baseline = ReplayCalibrationBuilder(PredictionPipeline(iterations=args.iterations)).build(args.year, args.as_of)
    candidate = ReplayCalibrationBuilder(
        PredictionPipeline(
            iterations=args.iterations,
            feature_provider=ProcessedFeatureProvider(enable_recent_team_reliability_form=True),
        )
    ).build(args.year, args.as_of)
    report = _report(args.year, args.as_of, args.iterations, baseline, candidate)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.year}_asof_{args.as_of.replace(':', '').replace('+', '_').replace('-', '')}"
    json_path = output_dir / f"{stem}.recent_team_reliability_replay_diagnostic.json"
    md_path = output_dir / f"{stem}.recent_team_reliability_replay_diagnostic.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, ensure_ascii=False, indent=2))


def _report(
    year: int,
    as_of: str,
    iterations: int,
    baseline: ReplayCalibrationReport,
    candidate: ReplayCalibrationReport,
) -> dict[str, Any]:
    return {
        "year": year,
        "as_of": as_of,
        "generated_at": utc_now().isoformat(),
        "status": "diagnostic_only",
        "formal_claim_ready": False,
        "iterations": iterations,
        "candidate_id": "recent_team_reliability_form",
        "warnings": [
            "diagnostic_only_not_formal_ablation",
            "same_replay_inputs_and_iterations",
            "small_sample_no_holdout",
            "feature_mapping_candidate_not_registered_latest",
        ],
        "baseline": _summary_payload(baseline),
        "candidate": _summary_payload(candidate),
        "delta_vs_baseline": _summary_delta(candidate.summary, baseline.summary),
        "events": _event_rows(baseline, candidate),
    }


def _summary_payload(report: ReplayCalibrationReport) -> dict[str, Any]:
    return {
        "scored_events": report.scored_events,
        "market_scored_events": report.market_scored_events,
        "summary": report.summary,
        "warnings": list(report.warnings),
    }


def _summary_delta(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "top_pick_hit_rate",
        "mean_actual_winner_probability",
        "mean_winner_brier_score",
        "mean_actual_log_loss",
        "weighted_top_pick_calibration_gap",
    )
    output: dict[str, Any] = {}
    for key in keys:
        left = candidate.get(key)
        right = baseline.get(key)
        output[key] = None if left is None or right is None else round(float(left) - float(right), 4)
    return output


def _event_rows(baseline: ReplayCalibrationReport, candidate: ReplayCalibrationReport) -> list[dict[str, Any]]:
    candidate_by_event = {row.event_id: row for row in candidate.events}
    rows = []
    for base in baseline.events:
        current = candidate_by_event.get(base.event_id)
        if current is None:
            continue
        rows.append(
            {
                "event_id": base.event_id,
                "event_name": base.event_name,
                "actual_winner": base.actual_winner,
                "baseline_top_pick": base.top_pick,
                "candidate_top_pick": current.top_pick,
                "baseline_hit": base.hit,
                "candidate_hit": current.hit,
                "baseline_actual_winner_probability": base.actual_winner_probability,
                "candidate_actual_winner_probability": current.actual_winner_probability,
                "actual_winner_probability_delta": round(
                    current.actual_winner_probability - base.actual_winner_probability,
                    4,
                ),
                "baseline_actual_winner_rank": base.actual_winner_rank,
                "candidate_actual_winner_rank": current.actual_winner_rank,
                "baseline_log_loss": base.actual_log_loss,
                "candidate_log_loss": current.actual_log_loss,
            }
        )
    return rows


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Recent Team Reliability Replay Diagnostic",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Replay cutoff: `{report['as_of']}`",
        f"- Iterations: `{report['iterations']}`",
        f"- Status: **{report['status']}**",
        "- Formal claim ready: **False**",
        "",
        "## Summary",
        "",
    ]
    baseline = report["baseline"]["summary"]
    candidate = report["candidate"]["summary"]
    delta = report["delta_vs_baseline"]
    for key in delta:
        lines.append(f"- {key}: baseline={baseline.get(key)} candidate={candidate.get(key)} delta={delta.get(key)}")
    lines.extend(["", "## Warnings", ""])
    for warning in report["warnings"]:
        lines.append(f"- {warning}")
    lines.extend(["", "## Event Rows", ""])
    lines.append("| Event | Actual | Base top | Cand top | Base p | Cand p | Delta | Base rank | Cand rank |")
    lines.append("|---|---|---|---|---:|---:|---:|---:|---:|")
    for row in report["events"]:
        lines.append(
            "| "
            f"{row['event_name']} | {row['actual_winner']} | {row['baseline_top_pick']} | "
            f"{row['candidate_top_pick']} | {row['baseline_actual_winner_probability']:.4f} | "
            f"{row['candidate_actual_winner_probability']:.4f} | {row['actual_winner_probability_delta']:+.4f} | "
            f"{row['baseline_actual_winner_rank']} | {row['candidate_actual_winner_rank']} |"
        )
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    main()
