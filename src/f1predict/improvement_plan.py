"""Build a prioritized improvement plan from replay diagnostics."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from f1predict.calibration import ReplayCalibrationBuilder
from f1predict.domain import utc_now
from f1predict.pipeline import PredictionPipeline
from f1predict.readiness import FormalReadinessBuilder, FormalReadinessReport


def _format_count_map(value: object) -> str:
    if not isinstance(value, dict) or not value:
        return "none"
    return ", ".join(f"{key}={count}" for key, count in sorted(value.items()))


@dataclass(frozen=True)
class ImprovementWorkstream:
    workstream_id: str
    title: str
    priority: int
    status: str
    blocks_formal_claim: bool
    why: str
    current_evidence: tuple[str, ...]
    acceptance_checks: tuple[str, ...]
    command_templates: tuple[str, ...]
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "workstream_id": self.workstream_id,
            "title": self.title,
            "priority": self.priority,
            "status": self.status,
            "blocks_formal_claim": self.blocks_formal_claim,
            "why": self.why,
            "current_evidence": list(self.current_evidence),
            "acceptance_checks": list(self.acceptance_checks),
            "command_templates": list(self.command_templates),
            "metrics": self.metrics,
        }


@dataclass(frozen=True)
class ImprovementPlanReport:
    year: int
    as_of: str
    generated_at: str
    status: str
    formal_edge_ready: bool
    top_priority: str
    blocking_workstream_count: int
    diagnostic_workstream_count: int
    readiness_summary: dict[str, Any]
    calibration_summary: dict[str, Any]
    artifact_refs: dict[str, str]
    workstreams: tuple[ImprovementWorkstream, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "as_of": self.as_of,
            "generated_at": self.generated_at,
            "status": self.status,
            "formal_edge_ready": self.formal_edge_ready,
            "top_priority": self.top_priority,
            "blocking_workstream_count": self.blocking_workstream_count,
            "diagnostic_workstream_count": self.diagnostic_workstream_count,
            "readiness_summary": self.readiness_summary,
            "calibration_summary": self.calibration_summary,
            "artifact_refs": self.artifact_refs,
            "workstreams": [workstream.to_dict() for workstream in self.workstreams],
        }


class ImprovementPlanBuilder:
    """Combines readiness, market/source scans, and calibration into next steps."""

    def __init__(
        self,
        pipeline: PredictionPipeline | None = None,
        reports_root: Path | str = Path("reports"),
    ) -> None:
        self.pipeline = pipeline or PredictionPipeline(iterations=1200)
        self.reports_root = Path(reports_root)

    def build(self, year: int, as_of: str) -> ImprovementPlanReport:
        readiness = FormalReadinessBuilder(self.pipeline).build(year, as_of)
        calibration = ReplayCalibrationBuilder(self.pipeline).build(year, as_of)
        market_report, market_path = self._read_optional_json(
            self.reports_root / "market_readiness" / f"{self._stem(year, as_of)}.market_readiness.json"
        )
        source_report, source_path = self._read_optional_json(
            self.reports_root / "source_archives" / "remaining_blockers_cdx_discovery.json"
        )
        source_replacements_report, source_replacements_path = self._read_optional_json(
            self.reports_root / "source_replacements" / "remaining_blockers.source_replacements.json"
        )
        model_error_report, model_error_path = self._read_optional_json(
            self.reports_root / "model_error_review" / f"{self._stem(year, as_of)}.model_error_review.json"
        )
        workstreams = (
            self._market_workstream(readiness, market_report, year, as_of),
            self._source_workstream(readiness, source_report, source_replacements_report, year, as_of),
            self._replay_freeze_workstream(readiness, year, as_of),
            self._calibration_workstream(calibration, year, as_of),
            self._model_iteration_workstream(calibration, model_error_report, year, as_of),
        )
        blocking_count = sum(1 for workstream in workstreams if workstream.blocks_formal_claim)
        top_priority = next((workstream.title for workstream in workstreams if workstream.blocks_formal_claim), "")
        artifact_refs = {
            "market_readiness": str(market_path) if market_path else "",
            "source_archive_recheck": str(source_path) if source_path else "",
            "source_replacements": str(source_replacements_path) if source_replacements_path else "",
            "model_error_review": str(model_error_path) if model_error_path else "",
            "formal_readiness": str(
                self.reports_root / "formal_readiness" / f"{self._stem(year, as_of)}.readiness.json"
            ),
            "calibration": str(self.reports_root / "calibration" / f"{self._stem(year, as_of)}.calibration.json"),
        }
        return ImprovementPlanReport(
            year=year,
            as_of=as_of,
            generated_at=utc_now().replace(microsecond=0).isoformat(),
            status="inputs_required" if blocking_count else "ready_for_formal_replay",
            formal_edge_ready=readiness.formal_backtest_ready and blocking_count == 0,
            top_priority=top_priority,
            blocking_workstream_count=blocking_count,
            diagnostic_workstream_count=len(workstreams) - blocking_count,
            readiness_summary={
                "status": readiness.status,
                "formal_backtest_ready": readiness.formal_backtest_ready,
                "blocking_action_count": readiness.blocking_action_count,
                "warning_action_count": readiness.warning_action_count,
                "action_category_counts": readiness.action_category_counts,
            },
            calibration_summary=calibration.summary,
            artifact_refs=artifact_refs,
            workstreams=workstreams,
        )

    def write(
        self,
        year: int,
        as_of: str,
        output_dir: Path | str = Path("reports/improvement_plan"),
    ) -> dict[str, Path]:
        report = self.build(year, as_of)
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        stem = self._stem(year, as_of)
        json_path = directory / f"{stem}.improvement_plan.json"
        md_path = directory / f"{stem}.improvement_plan.md"
        json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(self._markdown(report), encoding="utf-8")
        return {"json": json_path, "markdown": md_path}

    def _market_workstream(
        self,
        readiness: FormalReadinessReport,
        market_report: dict[str, Any],
        year: int,
        as_of: str,
    ) -> ImprovementWorkstream:
        counts = readiness.action_category_counts
        missing = int(counts.get("market_snapshot_required", 0))
        late = int(counts.get("after_cutoff_market_replacement", 0))
        late_blocking = sum(
            1
            for workstream in readiness.workstreams
            for action in workstream.actions
            if action.category == "after_cutoff_market_replacement" and action.blocks_formal_claim
        )
        definitions = int(market_report.get("events_with_definitions") or 0)
        unresolved = int(market_report.get("unresolved_event_count") or 0)
        blocking_unresolved = int(market_report.get("blocking_unresolved_event_count", missing) or 0)
        warning_only_unresolved = int(market_report.get("warning_only_unresolved_event_count") or 0)
        alternative_definition_events = int(market_report.get("events_with_alternative_definitions") or 0)
        alternative_definition_count = int(market_report.get("alternative_definition_count") or 0)
        market_blocker_codes = market_report.get("blocker_code_counts", {})
        market_warning_codes = market_report.get("warning_code_counts", {})
        market_action_categories = market_report.get("next_action_category_counts", {})
        market_rows = market_report.get("rows") if isinstance(market_report.get("rows"), list) else []
        backfill_attempted = sum(1 for row in market_rows if row.get("backfill_attempted"))
        backfill_cutoff_valid = sum(
            1 for row in market_rows if int(row.get("backfill_cutoff_valid_snapshot_count") or 0) > 0
        )
        backfill_no_winner_definitions = sum(
            1
            for row in market_rows
            if row.get("backfill_attempted") and int(row.get("backfill_definition_count") or 0) == 0
        )
        status = "blocked_no_usable_market_definitions"
        if definitions:
            status = "candidate_definitions_need_price_backfill"
        if not missing and not late_blocking:
            status = "complete"
        if not missing and late and not late_blocking:
            status = "late_market_rows_excluded"
        evidence = [
            f"{missing} events still need cutoff-valid model-supported market snapshots.",
            f"{late} events have after-cutoff market rows recorded as excluded diagnostics; {late_blocking} still block formal claims.",
        ]
        if market_report:
            evidence.append(
                f"Market scan status={market_report.get('status')} with {market_report.get('total_search_results', 0)} search results, "
                f"{definitions} usable definitions, {blocking_unresolved} blocking unresolved rows, and "
                f"{warning_only_unresolved} warning-only unresolved rows."
            )
            if backfill_attempted:
                evidence.append(
                    f"Integrated search/history backfill has been attempted for {backfill_attempted} events; "
                    f"{backfill_cutoff_valid} events produced cutoff-valid winner snapshots and "
                    f"{backfill_no_winner_definitions} events found no 2026 winner definitions."
                )
            if alternative_definition_count:
                evidence.append(
                    f"{alternative_definition_count} diagnostic non-winner market definitions are available across "
                    f"{alternative_definition_events} events; these can support diagnostic market-gap evidence but not formal winner-edge claims."
                )
            evidence.append(f"Market blocker codes: {_format_count_map(market_blocker_codes)}.")
            evidence.append(f"Market warning codes: {_format_count_map(market_warning_codes)}.")
            evidence.append(f"Market action categories: {_format_count_map(market_action_categories)}.")
        return ImprovementWorkstream(
            workstream_id="market_same_time_snapshots",
            title="Backfill Same-Time Market Snapshots",
            priority=1,
            status=status,
            blocks_formal_claim=bool(missing or late_blocking),
            why=(
                "Market-gap diagnostics need prices for at least one model-supported market at or before each replay "
                "cutoff; formal winner-edge claims still need winner markets."
            ),
            current_evidence=tuple(evidence),
            acceptance_checks=(
                "Each completed replay event has a cutoff-valid model-supported market snapshot in data/market_snapshots.",
                "Reviewed manual/Codex market inputs enter through archive-reviewed-market-snapshot with reviewer, source, outcome mapping, and cutoff checks.",
                "After-cutoff seed or backfilled rows remain excluded from replay scoring.",
                "formal-readiness no longer emits blocking market_snapshot_required actions.",
                "Any after-cutoff market rows remain excluded from scoring and are reported only as warnings.",
                "verify-readiness-intake reports the relevant market action_ids as resolved.",
            ),
            command_templates=(
                f"python -m f1predict.cli scan-readiness-markets --year {year} --as-of {as_of} --limit 30 --include-closed --write",
                "python -m f1predict.cli search-backfill-polymarket-history --event <event_id> --knowledge-cutoff <cutoff> --market-type winner --include-closed --write --output reports\\market_normalization\\<event_id>_price_history.json --search-output reports\\market_normalization\\<event_id>_search_payload.json",
                "python -m f1predict.cli search-backfill-polymarket-history --event <event_id> --knowledge-cutoff <cutoff> --market-type constructor_double_podium --include-closed --write --output reports\\market_normalization\\<event_id>_constructor_double_podium_price_history.json --search-output reports\\market_normalization\\<event_id>_constructor_double_podium_search_payload.json",
                "python -m f1predict.cli search-backfill-polymarket-history --event <event_id> --knowledge-cutoff <cutoff> --market-type driver_h2h --include-closed --write --output reports\\market_normalization\\<event_id>_driver_h2h_price_history.json --search-output reports\\market_normalization\\<event_id>_driver_h2h_search_payload.json",
                "python -m f1predict.cli reviewed-market-template --event <event_id> --market-type winner > data\\research\\markets\\<event_id>_reviewed_winner_market.json",
                "python -m f1predict.cli archive-reviewed-market-snapshot --event <event_id> --input data\\research\\markets\\<event_id>_reviewed_winner_market.json --knowledge-cutoff <cutoff> --require-cutoff-valid",
                f"python -m f1predict.cli verify-readiness-intake --year {year} --as-of {as_of} --write",
            ),
            metrics={
                "market_snapshot_required": missing,
                "after_cutoff_market_replacement": late,
                "blocking_after_cutoff_market_replacement": late_blocking,
                "events_with_definitions": definitions,
                "unresolved_event_count": unresolved,
                "blocking_unresolved_event_count": blocking_unresolved,
                "warning_only_unresolved_event_count": warning_only_unresolved,
                "events_with_alternative_definitions": alternative_definition_events,
                "alternative_definition_count": alternative_definition_count,
                "backfill_attempted_events": backfill_attempted,
                "backfill_cutoff_valid_events": backfill_cutoff_valid,
                "backfill_no_winner_definition_events": backfill_no_winner_definitions,
                "market_blocker_code_counts": market_blocker_codes,
                "market_warning_code_counts": market_warning_codes,
                "market_next_action_category_counts": market_action_categories,
                "issue_counts": market_report.get("search_report", {}).get("issue_counts", {}),
            },
        )

    def _source_workstream(
        self,
        readiness: FormalReadinessReport,
        source_report: dict[str, Any],
        source_replacements_report: dict[str, Any],
        year: int,
        as_of: str,
    ) -> ImprovementWorkstream:
        missing = int(readiness.action_category_counts.get("source_archive_required", 0))
        remaining = int(source_report.get("source_count") or missing)
        archive_candidates = int(source_report.get("candidate_count") or 0)
        replacement_candidates = int(source_replacements_report.get("candidate_count") or 0)
        cutoff_valid_replacements = int(source_replacements_report.get("cutoff_valid_replacement_count") or 0)
        replacement_remaining = int(source_replacements_report.get("remaining_candidate_count") or 0)
        archive_proof_required = int(source_replacements_report.get("archive_proof_required_count") or 0)
        content_review_required = int(source_replacements_report.get("content_review_required_count") or 0)
        lookup_failed = int(source_replacements_report.get("lookup_failed_count") or 0)
        replacement_blocker_codes = source_replacements_report.get("blocker_code_counts", {})
        replacement_action_categories = source_replacements_report.get("next_action_category_counts", {})
        status = "replacement_sources_required"
        if replacement_candidates:
            status = "replacement_candidates_need_archive_or_content_review"
        if cutoff_valid_replacements:
            status = "replacement_candidates_ready_for_source_log_review"
        if not missing:
            status = "complete"
        return ImprovementWorkstream(
            workstream_id="source_archive_proof",
            title="Replace or Prove Retrospective Sources",
            priority=2,
            status=status,
            blocks_formal_claim=bool(missing),
            why="Codex evidence can support replay only when its source availability is proven before the event cutoff.",
            current_evidence=(
                f"{missing} source_archive_required readiness actions remain.",
                f"Wayback/CDX recheck found {archive_candidates} cutoff-valid archive candidates for {remaining} remaining sources.",
                f"Replacement search catalogued {replacement_candidates} candidates; {cutoff_valid_replacements} are cutoff-valid, "
                f"{archive_proof_required} still need archive proof, and {content_review_required} need content review.",
                f"Replacement blocker codes: {_format_count_map(replacement_blocker_codes)}.",
                f"Replacement action categories: {_format_count_map(replacement_action_categories)}.",
            ),
            acceptance_checks=(
                "Each retrospective source has historical_archive proof with archived_at at or before the replay cutoff, or is replaced by a pre-cutoff source.",
                "Source coverage reports archive-backed snapshots instead of retrospective snapshots for the affected events.",
                "formal-readiness no longer emits source_archive_required actions.",
            ),
            command_templates=(
                f"python -m f1predict.cli discover-source-archives --event miami_gp --event canadian_gp --event barcelona_gp --output reports\\source_archives\\remaining_blockers_cdx_discovery.json",
                "python -m f1predict.cli source-replacement-candidates --event miami_gp --event canadian_gp --event barcelona_gp --write",
                "python -m f1predict.cli snapshot-source --event <event_id> --url <url> --source <name> --source-class <class> --published-at <iso> --observed-at <iso-before-cutoff> --knowledge-cutoff <cutoff> --historical-archive-url <archive-url> --historical-archived-at <archived-before-cutoff> --historical-original-url <url> --historical-verification-method wayback",
                f"python -m f1predict.cli formal-readiness --year {year} --as-of {as_of} --write",
            ),
            metrics={
                "source_archive_required": missing,
                "remaining_source_count": remaining,
                "archive_candidate_count": archive_candidates,
                "replacement_candidate_count": replacement_candidates,
                "cutoff_valid_replacement_count": cutoff_valid_replacements,
                "remaining_candidate_count": replacement_remaining,
                "archive_proof_required_count": archive_proof_required,
                "content_review_required_count": content_review_required,
                "lookup_failed_count": lookup_failed,
                "remaining_status_counts": source_report.get("status_counts", {}),
                "replacement_status_counts": source_replacements_report.get("status_counts", {}),
                "replacement_blocker_code_counts": replacement_blocker_codes,
                "replacement_next_action_category_counts": replacement_action_categories,
            },
        )

    @staticmethod
    def _replay_freeze_workstream(
        readiness: FormalReadinessReport,
        year: int,
        as_of: str,
    ) -> ImprovementWorkstream:
        return ImprovementWorkstream(
            workstream_id="formal_replay_freeze",
            title="Regenerate Formal Replay Freeze",
            priority=3,
            status="blocked_by_input_readiness" if not readiness.formal_backtest_ready else "ready_to_freeze",
            blocks_formal_claim=not readiness.formal_backtest_ready,
            why="The replay state must be regenerated and fingerprinted after input blockers are resolved.",
            current_evidence=(
                f"formal_backtest_ready={readiness.formal_backtest_ready}.",
                f"blocking_action_count={readiness.blocking_action_count}.",
            ),
            acceptance_checks=(
                "replay-report, analyze-replay, formal-readiness, calibration-report, and replay-freeze-manifest are rerun after input fixes.",
                "replay-freeze-manifest has no formal_edge_claim_not_ready integrity flag.",
                "Disk, CLI, and API freeze hashes match.",
            ),
            command_templates=(
                f"python -m f1predict.cli replay-report --year {year} --as-of {as_of} --write",
                f"python -m f1predict.cli analyze-replay --year {year} --as-of {as_of} --write",
                f"python -m f1predict.cli formal-readiness --year {year} --as-of {as_of} --write",
                f"python -m f1predict.cli calibration-report --year {year} --as-of {as_of} --write",
                f"python -m f1predict.cli replay-freeze-manifest --year {year} --as-of {as_of} --write",
            ),
            metrics={
                "formal_backtest_ready": readiness.formal_backtest_ready,
                "blocking_action_count": readiness.blocking_action_count,
            },
        )

    @staticmethod
    def _calibration_workstream(calibration: Any, year: int, as_of: str) -> ImprovementWorkstream:
        warnings = tuple(calibration.warnings)
        return ImprovementWorkstream(
            workstream_id="probability_calibration",
            title="Recalibrate Probabilities After Input Fixes",
            priority=4,
            status="diagnostic_waiting_for_inputs",
            blocks_formal_claim=False,
            why="Probability and edge claims need enough scored events and market-scored events after input blockers are resolved.",
            current_evidence=(
                f"calibration status={calibration.status}.",
                f"scored_events={calibration.scored_events}; market_scored_events={calibration.market_scored_events}.",
                f"warnings={', '.join(warnings) if warnings else 'none'}.",
            ),
            acceptance_checks=(
                "Calibration is rerun after market/source blockers are fixed.",
                "Market-scored subset covers the replay events used for edge analysis.",
                "Overconfidence and top-pick bins are reviewed before promoting edge claims.",
            ),
            command_templates=(
                f"python -m f1predict.cli calibration-report --year {year} --as-of {as_of} --write",
            ),
            metrics={
                "status": calibration.status,
                "formal_probability_claim_ready": calibration.formal_probability_claim_ready,
                "scored_events": calibration.scored_events,
                "market_scored_events": calibration.market_scored_events,
                "warnings": list(warnings),
                "summary": calibration.summary,
            },
        )

    @staticmethod
    def _model_iteration_workstream(
        calibration: Any,
        model_error_report: dict[str, Any],
        year: int,
        as_of: str,
    ) -> ImprovementWorkstream:
        hit_rate = calibration.summary.get("top_pick_hit_rate")
        findings = tuple(str(item) for item in model_error_report.get("findings", [])[:3])
        issue_counts = model_error_report.get("issue_counts", {})
        miss_count = model_error_report.get("missed_events")
        reviewed_events = model_error_report.get("reviewed_events")
        evidence = [
            f"Current diagnostic top-pick hit rate={hit_rate}.",
            "Calibration currently remains diagnostic and small-sample.",
        ]
        if model_error_report:
            evidence.append(f"Model error review found {miss_count}/{reviewed_events} replay misses.")
            evidence.extend(findings)
        return ImprovementWorkstream(
            workstream_id="model_iteration",
            title="Review Misses and Model Assumptions",
            priority=5,
            status="diagnostic_after_formal_inputs",
            blocks_formal_claim=False,
            why="Model ranking and confidence tuning should use the frozen replay after input integrity is fixed.",
            current_evidence=tuple(evidence),
            acceptance_checks=(
                "Use only frozen replay inputs for model comparisons.",
                "Run matched ablations before changing strategy, pace, reliability, or evidence weights.",
                "Use model-error-review to choose the next ablation factor before editing simulator defaults.",
                "Label model changes as diagnostic until the experiment controls are matched.",
            ),
            command_templates=(
                f"python -m f1predict.cli model-error-review --year {year} --as-of {as_of} --write",
                f"python -m f1predict.cli analyze-replay --year {year} --as-of {as_of} --write",
                f"python -m f1predict.cli calibration-report --year {year} --as-of {as_of} --write",
            ),
            metrics={
                "top_pick_hit_rate": hit_rate,
                "mean_actual_winner_probability": calibration.summary.get("mean_actual_winner_probability"),
                "weighted_top_pick_calibration_gap": calibration.summary.get("weighted_top_pick_calibration_gap"),
                "model_error_issue_counts": issue_counts,
                "model_error_reviewed_events": reviewed_events,
                "model_error_missed_events": miss_count,
            },
        )

    @staticmethod
    def _read_optional_json(path: Path) -> tuple[dict[str, Any], Path | None]:
        if not path.exists():
            return {}, None
        return json.loads(path.read_text(encoding="utf-8")), path

    @staticmethod
    def _stem(year: int, as_of: str) -> str:
        return f"{year}_asof_{as_of.replace(':', '').replace('+', '_').replace('-', '')}"

    @staticmethod
    def _markdown(report: ImprovementPlanReport) -> str:
        lines = [
            f"# F1Predict Improvement Plan ({report.year})",
            "",
            f"- Replay cutoff: `{report.as_of}`",
            f"- Status: `{report.status}`",
            f"- Formal edge ready: `{report.formal_edge_ready}`",
            f"- Top priority: {report.top_priority or 'none'}",
            f"- Blocking workstreams: {report.blocking_workstream_count}",
            "",
            "## Workstreams",
            "",
        ]
        for workstream in report.workstreams:
            lines.extend(
                [
                    f"### P{workstream.priority} {workstream.title}",
                    "",
                    f"- Status: `{workstream.status}`",
                    f"- Blocks formal claim: `{workstream.blocks_formal_claim}`",
                    f"- Why: {workstream.why}",
                    "- Evidence:",
                    *[f"  - {item}" for item in workstream.current_evidence],
                    "- Acceptance checks:",
                    *[f"  - {item}" for item in workstream.acceptance_checks],
                    "- First command:",
                    f"  - `{workstream.command_templates[0]}`" if workstream.command_templates else "  - n/a",
                    "",
                ]
            )
        return "\n".join(lines)
