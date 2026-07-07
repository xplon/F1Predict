"""One-command chronological replay bundle."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from f1predict.calibration import ReplayCalibrationBuilder, ReplayCalibrationReport
from f1predict.domain import utc_now
from f1predict.improvement_plan import ImprovementPlanBuilder, ImprovementPlanReport
from f1predict.manifest import ReplayFreezeManifestBuilder
from f1predict.model_error_review import ModelErrorReviewBuilder
from f1predict.pipeline import PredictionPipeline
from f1predict.readiness import FormalReadinessBuilder, FormalReadinessReport
from f1predict.replay import ReplayCoverageBuilder
from f1predict.replay_analysis import ReplayAnalysisBuilder, ReplayAnalysisReport


@dataclass(frozen=True)
class ChronologicalReplayTimelineRow:
    round_number: int
    racing_sequence_number: int | None
    event_id: str
    event_name: str
    date_end: str
    status: str
    prediction_input_source: str | None
    event_input_quality: str | None
    top_pick: str | None
    actual_winner: str | None
    hit: bool | None
    actual_winner_probability: float | None
    actual_winner_rank: int | None
    mean_abs_rank_error: float | None
    mean_abs_points_error: float | None
    podium_overlap_rate: float | None
    points_overlap_rate: float | None
    evidence_count: int
    evidence_quality_count: int
    weak_evidence_quality_count: int
    source_snapshot_count: int
    retrospective_source_snapshot_count: int
    market_snapshot_count: int
    market_snapshot_after_cutoff_count: int
    issue_codes: tuple[str, ...]
    blocking_action_categories: tuple[str, ...]
    warning_action_categories: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_number": self.round_number,
            "racing_sequence_number": self.racing_sequence_number,
            "event_id": self.event_id,
            "event_name": self.event_name,
            "date_end": self.date_end,
            "status": self.status,
            "prediction_input_source": self.prediction_input_source,
            "event_input_quality": self.event_input_quality,
            "top_pick": self.top_pick,
            "actual_winner": self.actual_winner,
            "hit": self.hit,
            "actual_winner_probability": self.actual_winner_probability,
            "actual_winner_rank": self.actual_winner_rank,
            "mean_abs_rank_error": self.mean_abs_rank_error,
            "mean_abs_points_error": self.mean_abs_points_error,
            "podium_overlap_rate": self.podium_overlap_rate,
            "points_overlap_rate": self.points_overlap_rate,
            "evidence_count": self.evidence_count,
            "evidence_quality_count": self.evidence_quality_count,
            "weak_evidence_quality_count": self.weak_evidence_quality_count,
            "source_snapshot_count": self.source_snapshot_count,
            "retrospective_source_snapshot_count": self.retrospective_source_snapshot_count,
            "market_snapshot_count": self.market_snapshot_count,
            "market_snapshot_after_cutoff_count": self.market_snapshot_after_cutoff_count,
            "issue_codes": list(self.issue_codes),
            "blocking_action_categories": list(self.blocking_action_categories),
            "warning_action_categories": list(self.warning_action_categories),
        }


@dataclass(frozen=True)
class ChronologicalReplayBundle:
    year: int
    as_of: str
    generated_at: str
    status: str
    formal_edge_ready: bool
    formal_backtest_ready: bool
    formal_probability_claim_ready: bool
    replay_scope: dict[str, Any]
    diagnostic_metrics: dict[str, Any]
    readiness_summary: dict[str, Any]
    calibration_summary: dict[str, Any]
    improvement_summary: dict[str, Any]
    root_causes: tuple[dict[str, Any], ...]
    timeline: tuple[ChronologicalReplayTimelineRow, ...]
    next_actions: tuple[str, ...]
    artifact_refs: dict[str, str]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "as_of": self.as_of,
            "generated_at": self.generated_at,
            "status": self.status,
            "formal_edge_ready": self.formal_edge_ready,
            "formal_backtest_ready": self.formal_backtest_ready,
            "formal_probability_claim_ready": self.formal_probability_claim_ready,
            "replay_scope": self.replay_scope,
            "diagnostic_metrics": self.diagnostic_metrics,
            "readiness_summary": self.readiness_summary,
            "calibration_summary": self.calibration_summary,
            "improvement_summary": self.improvement_summary,
            "root_causes": list(self.root_causes),
            "timeline": [row.to_dict() for row in self.timeline],
            "next_actions": list(self.next_actions),
            "artifact_refs": self.artifact_refs,
            "warnings": list(self.warnings),
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Chronological Replay Bundle ({self.year})",
            "",
            f"- Generated at: `{self.generated_at}`",
            f"- Replay cutoff: `{self.as_of}`",
            f"- Status: **{self.status}**",
            f"- Formal edge ready: **{self.formal_edge_ready}**",
            f"- Formal backtest ready: **{self.formal_backtest_ready}**",
            f"- Formal probability claim ready: **{self.formal_probability_claim_ready}**",
            "",
            "## Replay Scope",
            "",
        ]
        for key, value in self.replay_scope.items():
            lines.append(f"- {key}: {value}")
        lines.extend(["", "## Diagnostics", ""])
        selected_metrics = (
            "diagnostic_scored_events",
            "top_pick_hit_rate",
            "median_actual_winner_rank",
            "mean_abs_rank_error",
            "mean_abs_points_error",
            "mean_podium_overlap_rate",
            "mean_points_overlap_rate",
            "events_with_evidence_quality",
            "events_with_weak_evidence_quality",
            "events_with_market_snapshots",
            "events_with_market_snapshots_after_cutoff",
            "events_with_retrospective_source_snapshots",
        )
        for key in selected_metrics:
            if key in self.diagnostic_metrics:
                lines.append(f"- {key}: {self.diagnostic_metrics[key]}")
        lines.extend(["", "## Readiness", ""])
        for key, value in self.readiness_summary.items():
            lines.append(f"- {key}: {value}")
        lines.extend(["", "## Calibration", ""])
        for key, value in self.calibration_summary.items():
            lines.append(f"- {key}: {value}")
        if self.root_causes:
            lines.extend(["", "## Root Causes", ""])
            for cause in self.root_causes:
                lines.extend(
                    [
                        f"### {cause.get('code')} ({cause.get('severity')})",
                        "",
                        f"- Count: {cause.get('count')}",
                        f"- Blocks formal claim: {cause.get('blocks_formal_claim')}",
                        f"- Diagnosis: {cause.get('diagnosis')}",
                        f"- Improvement: {cause.get('improvement')}",
                        "",
                    ]
                )
        if self.next_actions:
            lines.extend(["## Next Actions", ""])
            for index, action in enumerate(self.next_actions, start=1):
                lines.append(f"{index}. {action}")
            lines.append("")
        lines.extend(["## Timeline", ""])
        lines.append(
            "| Round | Race Seq | Event | Status | Pick | Actual | Hit | Actual P | Rank | Rank MAE | Points MAE | Top10 | Blockers | Issues |"
        )
        lines.append("|---:|---:|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|")
        for row in self.timeline:
            hit = "" if row.hit is None else "yes" if row.hit else "no"
            race_sequence = "" if row.racing_sequence_number is None else str(row.racing_sequence_number)
            actual_probability = (
                "" if row.actual_winner_probability is None else f"{row.actual_winner_probability:.4f}"
            )
            actual_rank = "" if row.actual_winner_rank is None else str(row.actual_winner_rank)
            rank_mae = "" if row.mean_abs_rank_error is None else f"{row.mean_abs_rank_error:.2f}"
            points_mae = "" if row.mean_abs_points_error is None else f"{row.mean_abs_points_error:.2f}"
            top10 = "" if row.points_overlap_rate is None else f"{row.points_overlap_rate:.2f}"
            blockers = ", ".join(row.blocking_action_categories)
            issues = ", ".join(row.issue_codes)
            lines.append(
                "| "
                f"{row.round_number} | {race_sequence} | {row.event_name} | {row.status} | "
                f"{row.top_pick or ''} | {row.actual_winner or ''} | {hit} | "
                f"{actual_probability} | {actual_rank} | {rank_mae} | {points_mae} | {top10} | "
                f"{blockers} | {issues} |"
            )
        if self.artifact_refs:
            lines.extend(["", "## Artifact Refs", ""])
            for key, path in self.artifact_refs.items():
                lines.append(f"- {key}: `{path}`")
        if self.warnings:
            lines.extend(["", "## Warnings", ""])
            for warning in self.warnings:
                lines.append(f"- {warning}")
        return "\n".join(lines).rstrip() + "\n"


class ChronologicalReplayBundleBuilder:
    """Orchestrates the full replay diagnostics into one audited bundle."""

    def __init__(
        self,
        pipeline: PredictionPipeline | None = None,
        reports_root: Path | str = Path("reports"),
    ) -> None:
        self.pipeline = pipeline or PredictionPipeline(iterations=1200)
        self.reports_root = Path(reports_root)

    def build(
        self,
        year: int,
        as_of: str,
        iterations: int = 1200,
        artifact_refs: dict[str, str] | None = None,
    ) -> ChronologicalReplayBundle:
        pipeline = self._pipeline_for_iterations(iterations)
        analysis = ReplayAnalysisBuilder(pipeline).build(year, as_of)
        readiness = FormalReadinessBuilder(pipeline).build(year, as_of)
        calibration = ReplayCalibrationBuilder(pipeline).build(year, as_of)
        improvement = ImprovementPlanBuilder(pipeline, reports_root=self.reports_root).build(year, as_of)
        action_categories_by_event = self._action_categories_by_event(readiness)
        timeline = tuple(
            self._timeline_row(row, action_categories_by_event)
            for row in analysis.event_diagnostics
        )
        formal_ready = (
            analysis.formal_backtest_ready
            and readiness.formal_backtest_ready
            and calibration.formal_probability_claim_ready
        )
        return ChronologicalReplayBundle(
            year=year,
            as_of=as_of,
            generated_at=utc_now().replace(microsecond=0).isoformat(),
            status="formal_ready" if formal_ready else "diagnostic_only",
            formal_edge_ready=formal_ready,
            formal_backtest_ready=analysis.formal_backtest_ready and readiness.formal_backtest_ready,
            formal_probability_claim_ready=calibration.formal_probability_claim_ready,
            replay_scope=dict(analysis.replay_coverage),
            diagnostic_metrics=dict(analysis.diagnostic_metrics),
            readiness_summary=self._readiness_summary(readiness),
            calibration_summary=self._calibration_summary(calibration),
            improvement_summary=self._improvement_summary(improvement),
            root_causes=tuple(cause.__dict__ for cause in analysis.root_causes),
            timeline=timeline,
            next_actions=self._next_actions(readiness, improvement, analysis),
            artifact_refs=artifact_refs or {},
            warnings=self._warnings(analysis, readiness, calibration),
        )

    def write(
        self,
        year: int,
        as_of: str,
        iterations: int = 1200,
        output_dir: Path | str = Path("reports/chronological_replay"),
        write_components: bool = True,
        write_freeze: bool = True,
    ) -> dict[str, Path]:
        pipeline = self._pipeline_for_iterations(iterations)
        stem = self._stem(year, as_of)
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        json_path = directory / f"{stem}.chronological_replay.json"
        markdown_path = directory / f"{stem}.chronological_replay.md"
        artifact_refs = {
            "chronological_replay_json": str(json_path),
            "chronological_replay_markdown": str(markdown_path),
        }
        paths: dict[str, Path] = {}
        if write_components:
            replay_path = ReplayCoverageBuilder(pipeline).write(year, as_of)
            analysis_paths = ReplayAnalysisBuilder(pipeline).write(year, as_of)
            readiness_paths = FormalReadinessBuilder(pipeline).write(year, as_of)
            calibration_paths = ReplayCalibrationBuilder(pipeline).write(year, as_of)
            model_error_paths = ModelErrorReviewBuilder(pipeline).write(year, as_of)
            improvement_paths = ImprovementPlanBuilder(pipeline, reports_root=self.reports_root).write(year, as_of)
            paths.update(
                {
                    "replay_coverage": replay_path,
                    "replay_analysis_json": analysis_paths["json"],
                    "replay_analysis_markdown": analysis_paths["markdown"],
                    "formal_readiness_json": readiness_paths["json"],
                    "formal_readiness_markdown": readiness_paths["markdown"],
                    "calibration_json": calibration_paths["json"],
                    "calibration_markdown": calibration_paths["markdown"],
                    "model_error_review_json": model_error_paths["json"],
                    "model_error_review_markdown": model_error_paths["markdown"],
                    "improvement_plan_json": improvement_paths["json"],
                    "improvement_plan_markdown": improvement_paths["markdown"],
                }
            )
            artifact_refs.update({key: str(path) for key, path in paths.items()})
        bundle = self.build(year, as_of, iterations=iterations, artifact_refs=artifact_refs)
        json_path.write_text(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(bundle.to_markdown(), encoding="utf-8")
        paths["json"] = json_path
        paths["markdown"] = markdown_path
        if write_freeze:
            freeze_paths = ReplayFreezeManifestBuilder().write(year, as_of, iterations=iterations)
            paths["replay_freeze_json"] = freeze_paths["json"]
            paths["replay_freeze_markdown"] = freeze_paths["markdown"]
        return paths

    def _pipeline_for_iterations(self, iterations: int) -> PredictionPipeline:
        if iterations == self.pipeline.iterations:
            return self.pipeline
        return PredictionPipeline(
            data_source=self.pipeline.data_source,
            evidence_provider=self.pipeline.evidence_provider,
            feature_provider=self.pipeline.feature_provider,
            result_repository=self.pipeline.result_repository,
            official_standings_repository=self.pipeline.official_standings_repository,
            evidence_quality_scorer=self.pipeline.evidence_quality_scorer,
            weather_forecast_provider=self.pipeline.weather_forecast_provider,
            iterations=iterations,
            simulator_config=self.pipeline.simulator_config,
        )

    @staticmethod
    def _timeline_row(
        row: Any,
        action_categories_by_event: dict[str, dict[str, tuple[str, ...]]],
    ) -> ChronologicalReplayTimelineRow:
        event_id = row.event_id or row.event_name
        action_categories = action_categories_by_event.get(event_id, {"blocking": (), "warning": ()})
        return ChronologicalReplayTimelineRow(
            round_number=row.round_number,
            racing_sequence_number=row.racing_sequence_number,
            event_id=event_id,
            event_name=row.event_name,
            date_end=row.date_end,
            status=row.status,
            prediction_input_source=row.prediction_input_source,
            event_input_quality=row.event_input_quality,
            top_pick=row.top_pick,
            actual_winner=row.actual_winner,
            hit=row.hit,
            actual_winner_probability=row.actual_winner_probability,
            actual_winner_rank=row.actual_winner_rank,
            mean_abs_rank_error=row.mean_abs_rank_error,
            mean_abs_points_error=row.mean_abs_points_error,
            podium_overlap_rate=row.podium_overlap_rate,
            points_overlap_rate=row.points_overlap_rate,
            evidence_count=row.evidence_count,
            evidence_quality_count=row.evidence_quality_count,
            weak_evidence_quality_count=row.weak_evidence_quality_count,
            source_snapshot_count=row.source_snapshot_count,
            retrospective_source_snapshot_count=row.retrospective_source_snapshot_count,
            market_snapshot_count=row.market_snapshot_count,
            market_snapshot_after_cutoff_count=row.market_snapshot_after_cutoff_count,
            issue_codes=tuple(row.issue_codes),
            blocking_action_categories=action_categories["blocking"],
            warning_action_categories=action_categories["warning"],
        )

    @staticmethod
    def _action_categories_by_event(readiness: FormalReadinessReport) -> dict[str, dict[str, tuple[str, ...]]]:
        output: dict[str, dict[str, tuple[str, ...]]] = {}
        for event in readiness.events:
            blocking = tuple(
                dict.fromkeys(action.category for action in event.actions if action.blocks_formal_claim)
            )
            warning = tuple(
                dict.fromkeys(action.category for action in event.actions if not action.blocks_formal_claim)
            )
            output[event.event_id] = {"blocking": blocking, "warning": warning}
        return output

    @staticmethod
    def _readiness_summary(readiness: FormalReadinessReport) -> dict[str, Any]:
        return {
            "status": readiness.status,
            "formal_backtest_ready": readiness.formal_backtest_ready,
            "blocking_action_count": readiness.blocking_action_count,
            "warning_action_count": readiness.warning_action_count,
            "action_category_counts": readiness.action_category_counts,
            "workstream_count": len(readiness.workstreams),
        }

    @staticmethod
    def _calibration_summary(calibration: ReplayCalibrationReport) -> dict[str, Any]:
        return {
            "status": calibration.status,
            "formal_probability_claim_ready": calibration.formal_probability_claim_ready,
            "scored_events": calibration.scored_events,
            "market_scored_events": calibration.market_scored_events,
            "summary": calibration.summary,
            "warnings": list(calibration.warnings),
        }

    @staticmethod
    def _improvement_summary(improvement: ImprovementPlanReport) -> dict[str, Any]:
        return {
            "status": improvement.status,
            "formal_edge_ready": improvement.formal_edge_ready,
            "top_priority": improvement.top_priority,
            "blocking_workstream_count": improvement.blocking_workstream_count,
            "diagnostic_workstream_count": improvement.diagnostic_workstream_count,
            "workstreams": [
                {
                    "workstream_id": row.workstream_id,
                    "title": row.title,
                    "priority": row.priority,
                    "status": row.status,
                    "blocks_formal_claim": row.blocks_formal_claim,
                }
                for row in improvement.workstreams
            ],
        }

    @staticmethod
    def _next_actions(
        readiness: FormalReadinessReport,
        improvement: ImprovementPlanReport,
        analysis: ReplayAnalysisReport,
    ) -> tuple[str, ...]:
        workstream_actions = [
            f"P{row.priority} {row.title}: {row.status}"
            for row in improvement.workstreams
            if row.blocks_formal_claim
        ]
        if workstream_actions:
            return tuple(workstream_actions[:6])
        if readiness.next_actions:
            return readiness.next_actions[:6]
        return analysis.next_actions[:6]

    @staticmethod
    def _warnings(
        analysis: ReplayAnalysisReport,
        readiness: FormalReadinessReport,
        calibration: ReplayCalibrationReport,
    ) -> tuple[str, ...]:
        warnings: list[str] = []
        if not analysis.formal_backtest_ready:
            warnings.append("diagnostic_replay_not_formal_backtest")
        if not readiness.formal_backtest_ready:
            warnings.append("formal_readiness_inputs_required")
        if not calibration.formal_probability_claim_ready:
            warnings.append("probability_calibration_diagnostic_only")
        warnings.extend(calibration.warnings)
        return tuple(dict.fromkeys(warnings))

    @staticmethod
    def _stem(year: int, as_of: str) -> str:
        return f"{year}_asof_{as_of.replace(':', '').replace('+', '_').replace('-', '')}"
