"""Diagnostic simulator-parameter calibration over replayable races."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from f1predict.calibration import ReplayCalibrationBuilder, ReplayCalibrationReport
from f1predict.domain import utc_now
from f1predict.models.simulator import SimulatorConfig
from f1predict.pipeline import PredictionPipeline


@dataclass(frozen=True)
class SimulatorCalibrationCandidateResult:
    rank: int
    config_id: str
    description: str
    selected_for_review: bool
    composite_score: float
    delta_vs_baseline: dict[str, Any]
    config: dict[str, Any]
    scored_events: int
    market_scored_events: int
    summary: dict[str, Any]
    event_rows: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "config_id": self.config_id,
            "description": self.description,
            "selected_for_review": self.selected_for_review,
            "composite_score": self.composite_score,
            "delta_vs_baseline": self.delta_vs_baseline,
            "config": self.config,
            "scored_events": self.scored_events,
            "market_scored_events": self.market_scored_events,
            "summary": self.summary,
            "event_rows": list(self.event_rows),
        }


@dataclass(frozen=True)
class SimulatorCalibrationReport:
    year: int
    as_of: str
    generated_at: str
    status: str
    formal_simulator_claim_ready: bool
    iterations: int
    candidate_count: int
    baseline_config_id: str
    recommended_config_id: str | None
    scoring_method: str
    warnings: tuple[str, ...]
    candidates: tuple[SimulatorCalibrationCandidateResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "as_of": self.as_of,
            "generated_at": self.generated_at,
            "status": self.status,
            "formal_simulator_claim_ready": self.formal_simulator_claim_ready,
            "iterations": self.iterations,
            "candidate_count": self.candidate_count,
            "baseline_config_id": self.baseline_config_id,
            "recommended_config_id": self.recommended_config_id,
            "scoring_method": self.scoring_method,
            "warnings": list(self.warnings),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# F1Predict Simulator Calibration Diagnostics ({self.year})",
            "",
            f"- Generated at: `{self.generated_at}`",
            f"- Replay cutoff: `{self.as_of}`",
            f"- Status: **{self.status}**",
            f"- Formal simulator claim ready: **{self.formal_simulator_claim_ready}**",
            f"- Iterations per candidate: {self.iterations}",
            f"- Baseline config: `{self.baseline_config_id}`",
            f"- Recommended for review: `{self.recommended_config_id or 'n/a'}`",
            f"- Scoring method: {self.scoring_method}",
            "",
            "## Warnings",
            "",
        ]
        for warning in self.warnings:
            lines.append(f"- {warning}")
        lines.extend(
            [
                "",
                "## Candidate Ranking",
                "",
                "| Rank | Config | Score | Hit | Actual p | Brier | Log loss | Cal gap | Delta log loss |",
                "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for candidate in self.candidates:
            summary = candidate.summary
            delta = candidate.delta_vs_baseline
            lines.append(
                "| "
                f"{candidate.rank} | {candidate.config_id} | {candidate.composite_score:.4f} | "
                f"{self._fmt_pct(summary.get('top_pick_hit_rate'))} | "
                f"{self._fmt_pct(summary.get('mean_actual_winner_probability'))} | "
                f"{self._fmt_num(summary.get('mean_winner_brier_score'))} | "
                f"{self._fmt_num(summary.get('mean_actual_log_loss'))} | "
                f"{self._fmt_num(summary.get('weighted_top_pick_calibration_gap'))} | "
                f"{self._fmt_signed(delta.get('mean_actual_log_loss'))} |"
            )
        lines.extend(["", "## Top Candidate Event Deltas", ""])
        top = self.candidates[0] if self.candidates else None
        if top is None:
            lines.append("No candidates were scored.")
        else:
            lines.append("| Event | Top pick | Actual | Hit | Actual p | Delta actual p | Rank |")
            lines.append("|---|---|---|---:|---:|---:|---:|")
            for row in top.event_rows:
                lines.append(
                    "| "
                    f"{row['event_id']} | {row['top_pick']} | {row['actual_winner']} | "
                    f"{row['hit']} | {self._fmt_pct(row.get('actual_winner_probability'))} | "
                    f"{self._fmt_signed(row.get('actual_probability_delta_vs_baseline'), pct=True)} | "
                    f"{row['actual_winner_rank']} |"
                )
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _fmt_num(value: Any) -> str:
        return "n/a" if value is None else f"{float(value):.4f}"

    @staticmethod
    def _fmt_pct(value: Any) -> str:
        return "n/a" if value is None else f"{float(value) * 100:.1f}%"

    @staticmethod
    def _fmt_signed(value: Any, pct: bool = False) -> str:
        if value is None:
            return "n/a"
        number = float(value)
        scale = 100.0 if pct else 1.0
        suffix = "%" if pct else ""
        return f"{number * scale:+.4f}{suffix}"


class SimulatorCalibrationBuilder:
    """Compares hand-curated simulator parameter candidates over replay rows."""

    scoring_method = (
        "lower is better: log_loss + brier + 1.5*abs(top_pick_calibration_gap) "
        "- 0.25*mean_actual_winner_probability - 0.10*top_pick_hit_rate"
    )

    def __init__(
        self,
        pipeline: PredictionPipeline | None = None,
        candidate_configs: tuple[SimulatorConfig, ...] | None = None,
    ) -> None:
        self.pipeline = pipeline or PredictionPipeline(iterations=1200)
        self.candidate_configs = candidate_configs or default_simulator_candidate_configs()

    def build(self, year: int, as_of: str, iterations: int | None = None) -> SimulatorCalibrationReport:
        effective_iterations = iterations or self.pipeline.iterations
        baseline_config = self.candidate_configs[0]
        baseline_report = self._calibration_report(year, as_of, effective_iterations, baseline_config)
        baseline_summary = baseline_report.summary
        baseline_probabilities = {
            row.event_id: row.actual_winner_probability
            for row in baseline_report.events
        }
        raw_results: list[tuple[SimulatorConfig, ReplayCalibrationReport, float]] = [
            (baseline_config, baseline_report, self._composite_score(baseline_summary))
        ]
        for config in self.candidate_configs[1:]:
            report = self._calibration_report(year, as_of, effective_iterations, config)
            raw_results.append((config, report, self._composite_score(report.summary)))

        ranked = sorted(raw_results, key=lambda item: (item[2], item[0].config_id))
        baseline_score = raw_results[0][2]
        baseline_summary = raw_results[0][1].summary
        candidates: list[SimulatorCalibrationCandidateResult] = []
        for rank, (config, report, score) in enumerate(ranked, start=1):
            candidates.append(
                SimulatorCalibrationCandidateResult(
                    rank=rank,
                    config_id=config.config_id,
                    description=config.description,
                    selected_for_review=rank == 1,
                    composite_score=round(score, 4),
                    delta_vs_baseline=self._summary_delta(report.summary, baseline_summary, score, baseline_score),
                    config=config.to_dict(),
                    scored_events=report.scored_events,
                    market_scored_events=report.market_scored_events,
                    summary=report.summary,
                    event_rows=tuple(self._event_rows(report, baseline_probabilities)),
                )
            )
        warnings = self._warnings(raw_results)
        recommended = candidates[0].config_id if candidates else None
        return SimulatorCalibrationReport(
            year=year,
            as_of=as_of,
            generated_at=utc_now().isoformat(),
            status="diagnostic_only",
            formal_simulator_claim_ready=False,
            iterations=effective_iterations,
            candidate_count=len(candidates),
            baseline_config_id=baseline_config.config_id,
            recommended_config_id=recommended,
            scoring_method=self.scoring_method,
            warnings=tuple(warnings),
            candidates=tuple(candidates),
        )

    def write(
        self,
        year: int,
        as_of: str,
        iterations: int | None = None,
        output_dir: Path | str = Path("reports/simulator_calibration"),
    ) -> dict[str, Path]:
        report = self.build(year, as_of, iterations)
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"{year}_asof_{as_of.replace(':', '').replace('+', '_').replace('-', '')}"
        json_path = directory / f"{stem}.simulator_calibration.json"
        markdown_path = directory / f"{stem}.simulator_calibration.md"
        json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(report.to_markdown(), encoding="utf-8")
        return {"json": json_path, "markdown": markdown_path}

    def _calibration_report(
        self,
        year: int,
        as_of: str,
        iterations: int,
        config: SimulatorConfig,
    ) -> ReplayCalibrationReport:
        pipeline = self._pipeline_for_config(iterations, config)
        return ReplayCalibrationBuilder(pipeline=pipeline).build(year, as_of)

    def _pipeline_for_config(self, iterations: int, config: SimulatorConfig) -> PredictionPipeline:
        return PredictionPipeline(
            data_source=self.pipeline.data_source,
            evidence_provider=self.pipeline.evidence_provider,
            feature_provider=self.pipeline.feature_provider,
            result_repository=self.pipeline.result_repository,
            official_standings_repository=self.pipeline.official_standings_repository,
            evidence_quality_scorer=self.pipeline.evidence_quality_scorer,
            weather_forecast_provider=self.pipeline.weather_forecast_provider,
            iterations=iterations,
            simulator_config=config,
        )

    @staticmethod
    def _composite_score(summary: dict[str, Any]) -> float:
        if not summary:
            return 999.0
        log_loss = float(summary.get("mean_actual_log_loss") or 999.0)
        brier = float(summary.get("mean_winner_brier_score") or 999.0)
        gap = abs(float(summary.get("weighted_top_pick_calibration_gap") or 0.0))
        actual_probability = float(summary.get("mean_actual_winner_probability") or 0.0)
        hit_rate = float(summary.get("top_pick_hit_rate") or 0.0)
        return log_loss + brier + 1.5 * gap - 0.25 * actual_probability - 0.10 * hit_rate

    @staticmethod
    def _summary_delta(
        summary: dict[str, Any],
        baseline: dict[str, Any],
        score: float,
        baseline_score: float,
    ) -> dict[str, Any]:
        keys = (
            "top_pick_hit_rate",
            "mean_actual_winner_probability",
            "mean_winner_brier_score",
            "mean_actual_log_loss",
            "weighted_top_pick_calibration_gap",
        )
        delta = {"composite_score": round(score - baseline_score, 4)}
        for key in keys:
            current = summary.get(key)
            base = baseline.get(key)
            delta[key] = None if current is None or base is None else round(float(current) - float(base), 4)
        return delta

    @staticmethod
    def _event_rows(
        report: ReplayCalibrationReport,
        baseline_probabilities: dict[str, float],
    ) -> list[dict[str, Any]]:
        rows = []
        for row in report.events:
            baseline_probability = baseline_probabilities.get(row.event_id)
            probability_delta = None
            if baseline_probability is not None:
                probability_delta = round(row.actual_winner_probability - baseline_probability, 4)
            rows.append(
                {
                    "event_id": row.event_id,
                    "event_name": row.event_name,
                    "top_pick": row.top_pick,
                    "actual_winner": row.actual_winner,
                    "hit": row.hit,
                    "top_pick_probability": row.top_pick_probability,
                    "actual_winner_probability": row.actual_winner_probability,
                    "actual_probability_delta_vs_baseline": probability_delta,
                    "actual_winner_rank": row.actual_winner_rank,
                    "winner_brier_score": row.winner_brier_score,
                    "actual_log_loss": row.actual_log_loss,
                }
            )
        return rows

    @staticmethod
    def _warnings(
        raw_results: list[tuple[SimulatorConfig, ReplayCalibrationReport, float]],
    ) -> list[str]:
        scored_counts = [report.scored_events for _, report, _ in raw_results]
        market_scored_counts = [report.market_scored_events for _, report, _ in raw_results]
        warnings = [
            "diagnostic_only_not_formal_simulator_calibration",
            "candidate_grid_is_hand_curated_not_exhaustive",
            "candidate_selection_is_in_sample_no_holdout",
            "same_replay_inputs_as_current_diagnostic_pipeline",
            "recommended_config_requires_review_before_default_use",
        ]
        if scored_counts and max(scored_counts) < 20:
            warnings.append("small_sample_less_than_20_scored_events")
        if scored_counts and market_scored_counts and max(market_scored_counts) < max(scored_counts):
            warnings.append("market_scored_subset_incomplete")
        if len(set(scored_counts)) > 1:
            warnings.append("candidate_scored_event_counts_differ")
        return warnings


def default_simulator_candidate_configs() -> tuple[SimulatorConfig, ...]:
    baseline = SimulatorConfig()
    return (
        baseline,
        replace(
            baseline,
            config_id="legacy_default_current",
            description="Previous default before the diagnostic pace-separation calibration update.",
            qualifying_noise_sd=0.44,
            race_score_lap_time_scale=0.58,
            race_noise_base_sd=5.6,
            race_noise_per_lap_sd=0.055,
            operational_noise_per_stop=1.05,
        ),
        replace(
            baseline,
            config_id="wider_race_variance",
            description="More race noise and qualifying spread to reduce brittle top-pick confidence.",
            qualifying_noise_sd=0.50,
            race_noise_base_sd=6.8,
            race_noise_per_lap_sd=0.065,
            operational_noise_per_stop=1.20,
        ),
        replace(
            baseline,
            config_id="grid_weighted",
            description="Stronger track-position penalty and slightly more stable qualifying order.",
            qualifying_noise_sd=0.36,
            grid_penalty_scale=1.25,
            race_noise_base_sd=5.2,
        ),
        replace(
            baseline,
            config_id="strategy_weighted",
            description="More reward for team strategy and safety-car pit conversion.",
            strategy_quality_scale=0.95,
            safety_car_pit_gain_fraction=0.48,
            safety_car_pit_gain_cap=9.5,
            operational_noise_per_stop=1.15,
        ),
        replace(
            baseline,
            config_id="chaos_weighted",
            description="Higher race-event variance and stronger safety-car bunching.",
            qualifying_noise_sd=0.52,
            race_noise_base_sd=7.5,
            race_noise_per_lap_sd=0.075,
            operational_noise_min_sd=1.0,
            operational_noise_per_stop=1.35,
            safety_car_bunching_per_grid_position=0.22,
        ),
    )
