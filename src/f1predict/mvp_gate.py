"""MVP delivery gate over the current diagnostic replay state."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from f1predict.domain import utc_now


def _format_count_map(value: object) -> str:
    if not isinstance(value, dict) or not value:
        return "none"
    return ", ".join(f"{key}={count}" for key, count in sorted(value.items()))


@dataclass(frozen=True)
class MVPGateRequirement:
    requirement_id: str
    title: str
    status: str
    blocks_mvp_delivery: bool
    blocks_formal_edge: bool
    evidence: tuple[str, ...]
    gaps: tuple[str, ...]
    next_actions: tuple[str, ...]
    artifact_refs: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "title": self.title,
            "status": self.status,
            "blocks_mvp_delivery": self.blocks_mvp_delivery,
            "blocks_formal_edge": self.blocks_formal_edge,
            "evidence": list(self.evidence),
            "gaps": list(self.gaps),
            "next_actions": list(self.next_actions),
            "artifact_refs": self.artifact_refs,
        }


@dataclass(frozen=True)
class MVPGateReport:
    year: int
    as_of: str
    generated_at: str
    status: str
    diagnostic_mvp_operational: bool
    mvp_delivery_ready: bool
    formal_edge_ready: bool
    summary: dict[str, Any]
    requirements: tuple[MVPGateRequirement, ...]
    next_actions: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "as_of": self.as_of,
            "generated_at": self.generated_at,
            "status": self.status,
            "diagnostic_mvp_operational": self.diagnostic_mvp_operational,
            "mvp_delivery_ready": self.mvp_delivery_ready,
            "formal_edge_ready": self.formal_edge_ready,
            "summary": self.summary,
            "requirements": [requirement.to_dict() for requirement in self.requirements],
            "next_actions": list(self.next_actions),
            "warnings": list(self.warnings),
        }

    def to_markdown(self) -> str:
        lines = [
            f"# F1Predict MVP Delivery Gate ({self.year})",
            "",
            f"- Generated at: `{self.generated_at}`",
            f"- Replay cutoff: `{self.as_of}`",
            f"- Status: **{self.status}**",
            f"- Diagnostic MVP operational: **{self.diagnostic_mvp_operational}**",
            f"- MVP delivery ready: **{self.mvp_delivery_ready}**",
            f"- Formal edge ready: **{self.formal_edge_ready}**",
            "",
            "## Summary",
            "",
        ]
        for key, value in self.summary.items():
            lines.append(f"- {key}: {value}")
        lines.extend(
            [
                "",
                "## Requirement Gate",
                "",
                "| Requirement | Status | Blocks MVP | Blocks Formal Edge | Evidence | Gaps |",
                "|---|---|---:|---:|---|---|",
            ]
        )
        for row in self.requirements:
            evidence = "<br>".join(row.evidence[:3]) or "n/a"
            gaps = "<br>".join(row.gaps[:3]) or "none"
            lines.append(
                "| "
                f"{row.title} | {row.status} | {row.blocks_mvp_delivery} | "
                f"{row.blocks_formal_edge} | {evidence} | {gaps} |"
            )
        if self.next_actions:
            lines.extend(["", "## Next Actions", ""])
            for index, action in enumerate(self.next_actions, start=1):
                lines.append(f"{index}. {action}")
        if self.warnings:
            lines.extend(["", "## Warnings", ""])
            for warning in self.warnings:
                lines.append(f"- {warning}")
        return "\n".join(lines).rstrip() + "\n"


class MVPGateBuilder:
    """Builds a requirement-by-requirement delivery gate for the MVP objective."""

    def __init__(self, reports_root: Path | str = Path("reports"), workspace_root: Path | str = Path(".")) -> None:
        self.reports_root = Path(reports_root)
        self.workspace_root = Path(workspace_root)

    def build(self, year: int, as_of: str) -> MVPGateReport:
        stem = self._stem(year, as_of)
        reports = {
            "chronological": self._read_optional(self.reports_root / "chronological_replay" / f"{stem}.chronological_replay.json"),
            "analysis": self._read_optional(self.reports_root / "replay_analysis" / f"{stem}.analysis.json"),
            "readiness": self._read_optional(self.reports_root / "formal_readiness" / f"{stem}.readiness.json"),
            "calibration": self._read_optional(self.reports_root / "calibration" / f"{stem}.calibration.json"),
            "simulator_calibration": self._read_optional(
                self.reports_root / "simulator_calibration" / f"{stem}.simulator_calibration.json"
            ),
            "improvement": self._read_optional(self.reports_root / "improvement_plan" / f"{stem}.improvement_plan.json"),
            "market": self._read_optional(self.reports_root / "market_readiness" / f"{stem}.market_readiness.json"),
            "source": self._read_optional(self.reports_root / "source_archives" / "remaining_blockers_cdx_discovery.json"),
            "source_replacements": self._read_optional(self.reports_root / "source_replacements" / "remaining_blockers.source_replacements.json"),
            "codex_intake": self._codex_intake_summary(),
            "model_error": self._read_optional(self.reports_root / "model_error_review" / f"{stem}.model_error_review.json"),
            "freeze": self._read_optional(self.reports_root / "replay_freeze" / f"{stem}.freeze.json"),
            "track_assets": self._read_optional(self.reports_root / "track_assets" / f"{year}_track_asset_audit.json"),
        }
        requirements = (
            self._data_pipeline_requirement(reports, stem),
            self._codex_requirement(reports, stem),
            self._simulation_requirement(reports, stem),
            self._market_requirement(reports, stem),
            self._chronological_requirement(reports, stem),
            self._frontend_requirement(reports),
            self._improvement_requirement(reports, stem),
            self._reproducibility_requirement(reports, stem),
        )
        diagnostic_operational = all(
            row.status in {"passed", "diagnostic_passed", "partial"} for row in requirements
        ) and bool(reports["chronological"])
        mvp_ready = not any(row.blocks_mvp_delivery for row in requirements)
        formal_edge_ready = bool(
            reports["chronological"].get("formal_edge_ready")
            and reports["readiness"].get("formal_backtest_ready")
            and reports["calibration"].get("formal_probability_claim_ready")
        )
        status = self._status(diagnostic_operational, mvp_ready, formal_edge_ready)
        warnings = self._warnings(requirements, reports)
        return MVPGateReport(
            year=year,
            as_of=as_of,
            generated_at=utc_now().replace(microsecond=0).isoformat(),
            status=status,
            diagnostic_mvp_operational=diagnostic_operational,
            mvp_delivery_ready=mvp_ready,
            formal_edge_ready=formal_edge_ready,
            summary=self._summary(requirements, reports),
            requirements=requirements,
            next_actions=self._next_actions(requirements, reports),
            warnings=warnings,
        )

    def write(
        self,
        year: int,
        as_of: str,
        output_dir: Path | str = Path("reports/mvp_gate"),
    ) -> dict[str, Path]:
        report = self.build(year, as_of)
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        stem = self._stem(year, as_of)
        json_path = directory / f"{stem}.mvp_gate.json"
        markdown_path = directory / f"{stem}.mvp_gate.md"
        json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(report.to_markdown(), encoding="utf-8")
        return {"json": json_path, "markdown": markdown_path}

    def _data_pipeline_requirement(self, reports: dict[str, dict[str, Any]], stem: str) -> MVPGateRequirement:
        replay_scope = reports["chronological"].get("replay_scope", {})
        due = int(replay_scope.get("due_events") or 0)
        replayed = int(replay_scope.get("replayed_events") or 0)
        missing = int(replay_scope.get("missing_due_events") or 0)
        passed = due > 0 and replayed == due and missing == 0
        return MVPGateRequirement(
            requirement_id="data_pipeline",
            title="Data Acquisition and Processing",
            status="passed" if passed else "missing",
            blocks_mvp_delivery=not passed,
            blocks_formal_edge=not passed,
            evidence=(
                f"calendar_events={replay_scope.get('calendar_events', 0)}",
                f"due_events={due}; replayed_events={replayed}; missing_due_events={missing}",
                "OpenF1/FastF1/F1 official/weather/market snapshot adapters are present in src/f1predict.",
            ),
            gaps=() if passed else ("Replay does not cover every due event at the cutoff.",),
            next_actions=() if passed else ("Rerun calendar/result ingestion and chronological replay.",),
            artifact_refs={"chronological_replay": self._report_path("chronological_replay", stem, ".chronological_replay.json")},
        )

    def _codex_requirement(self, reports: dict[str, dict[str, Any]], stem: str) -> MVPGateRequirement:
        metrics = reports["chronological"].get("diagnostic_metrics", {})
        source = reports["source"]
        replacements = reports.get("source_replacements", {})
        intake = reports.get("codex_intake", {})
        evidence_events = int(metrics.get("events_with_evidence") or 0)
        weak_events = int(metrics.get("events_with_weak_evidence_quality") or 0)
        remaining_sources = int(source.get("source_count") or 0)
        replacement_candidates = int(replacements.get("candidate_count") or 0)
        cutoff_valid_replacements = int(replacements.get("cutoff_valid_replacement_count") or 0)
        archive_proof_required = int(replacements.get("archive_proof_required_count") or 0)
        content_review_required = int(replacements.get("content_review_required_count") or 0)
        replacement_blocker_codes = replacements.get("blocker_code_counts", {})
        replacement_action_categories = replacements.get("next_action_category_counts", {})
        source_candidate_ready = int(intake.get("source_candidates_ready_count") or 0)
        preflight_passed = int(intake.get("preflight_passed_count") or 0)
        diagnostic_passed = bool(evidence_events and source_candidate_ready and preflight_passed)
        status = "diagnostic_passed" if diagnostic_passed else "partial" if evidence_events else "missing"
        gaps = []
        if not evidence_events:
            gaps.append("No replayed event has Codex evidence attached.")
        if source_candidate_ready == 0:
            gaps.append("No event has a ready Codex source-candidate audit report yet.")
        if preflight_passed == 0:
            gaps.append("No event has a passed Codex research-packet preflight report yet.")
        if remaining_sources:
            gaps.append(
                f"Formal edge blocker: {remaining_sources} source snapshots still lack cutoff-valid archive proof."
            )
            if replacement_candidates:
                gaps.append(
                    f"Formal edge candidate queue: {replacement_candidates} replacement candidates are catalogued; "
                    f"{cutoff_valid_replacements} currently have cutoff-valid proof."
                )
        if weak_events:
            gaps.append(f"Formal edge blocker: {weak_events} events still have weak/review-required evidence quality rows.")
        if remaining_sources and replacement_candidates:
            next_actions = (
                "Attach cutoff-valid archive proof for verified replacement candidates, snapshot them into source_log.json, then rerun source audit and readiness.",
            )
        elif not diagnostic_passed:
            next_actions = (
                "Run Codex source-candidate audit and research-packet preflight for at least one event before delivery.",
            )
        elif gaps:
            next_actions = (
                "Keep formal-edge source proof actions open while treating the current Codex chain as diagnostic MVP input.",
            )
        else:
            next_actions = ()
        return MVPGateRequirement(
            requirement_id="codex_normalized_intelligence",
            title="Codex-Normalized Intelligence Layer",
            status=status,
            blocks_mvp_delivery=not diagnostic_passed,
            blocks_formal_edge=bool(remaining_sources),
            evidence=(
                f"events_with_evidence={evidence_events}",
                f"events_with_evidence_quality={metrics.get('events_with_evidence_quality', 0)}",
                f"replacement_candidates={replacement_candidates}; cutoff_valid_replacements={cutoff_valid_replacements}",
                f"replacement_archive_proof_required={archive_proof_required}; content_review_required={content_review_required}",
                f"replacement_blocker_codes={_format_count_map(replacement_blocker_codes)}",
                f"replacement_next_action_categories={_format_count_map(replacement_action_categories)}",
                f"source_candidate_reports={intake.get('candidate_report_count', 0)}; ready={intake.get('source_candidates_ready_count', 0)}",
                f"research_preflight_reports={intake.get('preflight_report_count', 0)}; passed={intake.get('preflight_passed_count', 0)}",
                "Codex plans, source logs, evidence templates, source audit, and archive proof checks are implemented.",
            ),
            gaps=tuple(gaps),
            next_actions=next_actions,
            artifact_refs={
                "source_readiness": "reports/source_archives/remaining_blockers_cdx_discovery.json",
                "source_replacements": "reports/source_replacements/remaining_blockers.source_replacements.json",
                "research_candidates": "reports/research_candidates/",
                "research_preflight": "reports/research_preflight/",
                "replay_analysis": self._report_path("replay_analysis", stem, ".analysis.json"),
            },
        )

    def _simulation_requirement(self, reports: dict[str, dict[str, Any]], stem: str) -> MVPGateRequirement:
        calibration = reports["calibration"]
        simulator_calibration = reports.get("simulator_calibration", {})
        model_error = reports["model_error"]
        scored = int(calibration.get("scored_events") or 0)
        reviewed = int(model_error.get("reviewed_events") or 0)
        passed = scored > 0 and reviewed == scored
        simulator_candidate_count = int(simulator_calibration.get("candidate_count") or 0)
        return MVPGateRequirement(
            requirement_id="simulation_and_probabilities",
            title="Multi-Round Simulation and Probability Outputs",
            status="diagnostic_passed" if passed else "missing",
            blocks_mvp_delivery=not passed,
            blocks_formal_edge=not bool(calibration.get("formal_probability_claim_ready")),
            evidence=(
                f"calibration_scored_events={scored}",
                f"model_error_reviewed_events={reviewed}; missed_events={model_error.get('missed_events', 0)}",
                f"mean_actual_winner_probability={calibration.get('summary', {}).get('mean_actual_winner_probability')}",
                (
                    "simulator_calibration="
                    f"{simulator_calibration.get('recommended_config_id', 'not_generated')} "
                    f"candidates={simulator_candidate_count}"
                ),
            ),
            gaps=(
                "Probability calibration is diagnostic-only and small-sample.",
                "Simulator parameter ranking is diagnostic-only until rerun as a held-out matched ablation.",
            ) if calibration.get("status") != "formal_ready" else (),
            next_actions=(
                (
                    "Review simulator-calibration candidates, then run matched held-out simulator ablations "
                    "after source and market inputs are frozen."
                ),
            ),
            artifact_refs={
                "calibration": self._report_path("calibration", stem, ".calibration.json"),
                "simulator_calibration": self._report_path(
                    "simulator_calibration",
                    stem,
                    ".simulator_calibration.json",
                ),
                "model_error_review": self._report_path("model_error_review", stem, ".model_error_review.json"),
            },
        )

    def _market_requirement(self, reports: dict[str, dict[str, Any]], stem: str) -> MVPGateRequirement:
        market = reports["market"]
        calibration = reports["calibration"]
        readiness = reports["readiness"]
        category_counts = readiness.get("action_category_counts") or {}
        missing_supported = int(category_counts.get("market_snapshot_required") or 0)
        unresolved_scan_rows = int(market.get("unresolved_event_count") or 0)
        blocking_scan_rows = int(market.get("blocking_unresolved_event_count", missing_supported) or 0)
        warning_only_scan_rows = int(market.get("warning_only_unresolved_event_count") or 0)
        market_scored = int(calibration.get("market_scored_events") or 0)
        alternative_events = int(market.get("events_with_alternative_definitions") or 0)
        alternative_definitions = int(market.get("alternative_definition_count") or 0)
        market_blocker_codes = market.get("blocker_code_counts", {})
        market_warning_codes = market.get("warning_code_counts", {})
        market_action_categories = market.get("next_action_category_counts", {})
        search_attempted = bool(
            market.get("events_with_search_results")
            or market.get("total_search_results")
            or market.get("action_count")
        )
        diagnostic_market_ready = bool(market_scored and (missing_supported == 0 or search_attempted))
        status = "diagnostic_passed" if diagnostic_market_ready else "partial" if search_attempted else "missing"
        return MVPGateRequirement(
            requirement_id="market_gap_analysis",
            title="Market Gap and Same-Time Price Comparison",
            status=status,
            blocks_mvp_delivery=not diagnostic_market_ready,
            blocks_formal_edge=bool(missing_supported),
            evidence=(
                f"market_scored_events={market_scored}",
                f"missing_model_supported_market_snapshots={missing_supported}",
                f"market_readiness_status={market.get('status', 'missing')}",
                f"market_readiness_blocking_unresolved_rows={blocking_scan_rows}",
                f"market_readiness_warning_only_rows={warning_only_scan_rows}",
                f"market_readiness_total_unresolved_rows={unresolved_scan_rows}",
                f"total_search_results={market.get('total_search_results', 0)}",
                f"diagnostic_non_winner_market_events={alternative_events}; definitions={alternative_definitions}",
                f"market_blocker_codes={_format_count_map(market_blocker_codes)}",
                f"market_warning_codes={_format_count_map(market_warning_codes)}",
                f"market_next_action_categories={_format_count_map(market_action_categories)}",
            ),
            gaps=(
                f"Formal edge blocker: {missing_supported} completed replay events still lack usable same-time model-supported market snapshots.",
            ) if missing_supported else (),
            next_actions=(
                "Backfill reviewed market definitions and cutoff-valid CLOB price history before making formal edge or CLV claims.",
            ) if missing_supported else () if diagnostic_market_ready else (
                "Archive at least one cutoff-valid supported market snapshot before MVP delivery.",
            ),
            artifact_refs={
                "market_readiness": self._report_path("market_readiness", stem, ".market_readiness.json"),
                "calibration": self._report_path("calibration", stem, ".calibration.json"),
            },
        )

    def _chronological_requirement(self, reports: dict[str, dict[str, Any]], stem: str) -> MVPGateRequirement:
        chronological = reports["chronological"]
        replay_scope = chronological.get("replay_scope", {})
        due = int(replay_scope.get("due_events") or 0)
        replayed = int(replay_scope.get("replayed_events") or 0)
        passed = due > 0 and replayed == due
        return MVPGateRequirement(
            requirement_id="chronological_replay",
            title="First-Race-to-Cutoff Chronological Replay",
            status="diagnostic_passed" if passed else "missing",
            blocks_mvp_delivery=not passed,
            blocks_formal_edge=not bool(chronological.get("formal_backtest_ready")),
            evidence=(
                f"status={chronological.get('status', 'missing')}",
                f"timeline_rows={len(chronological.get('timeline', []))}",
                f"top_pick_hit_rate={chronological.get('diagnostic_metrics', {}).get('top_pick_hit_rate')}",
            ),
            gaps=(
                "Replay is diagnostic-only until market/source/readiness blockers are resolved.",
            ),
            next_actions=tuple(chronological.get("next_actions", [])[:3]),
            artifact_refs={"chronological_replay": self._report_path("chronological_replay", stem, ".chronological_replay.json")},
        )

    def _frontend_requirement(self, reports: dict[str, dict[str, Any]]) -> MVPGateRequirement:
        index = self._read_text(self.workspace_root / "web" / "index.html")
        app = self._read_text(self.workspace_root / "web" / "app.js")
        assets = list((self.workspace_root / "web" / "assets" / "tracks").glob("*.*"))
        track_audit = reports.get("track_assets") or {}
        required_ids = (
            "trackCanvas",
            "replayFrame",
            "probabilityTable",
            "marketReadinessList",
            "sourceReadinessList",
            "modelErrorList",
            "chronologicalList",
        )
        missing_ids = [item for item in required_ids if item not in index and item not in app]
        freeze_groups = {
            group.get("group_id"): group
            for group in reports["freeze"].get("artifact_groups", [])
            if isinstance(group, dict)
        }
        track_audit_passed = track_audit.get("status") in {"passed", None}
        passed = not missing_ids and len(assets) >= 22 and track_audit_passed
        gaps = [f"Missing frontend target: {item}" for item in missing_ids]
        if track_audit and not track_audit_passed:
            gaps.append(
                f"Track asset audit status={track_audit.get('status')} "
                f"missing={track_audit.get('missing_asset_count', 0)} files={track_audit.get('missing_file_count', 0)}"
            )
        return MVPGateRequirement(
            requirement_id="frontend_dashboard",
            title="Frontend Inspection Dashboard",
            status="passed" if passed else "partial",
            blocks_mvp_delivery=not passed,
            blocks_formal_edge=False,
            evidence=(
                f"track_asset_files={len(assets)}",
                f"track_asset_audit_status={track_audit.get('status', 'not_generated')}",
                f"track_asset_audit_passed_events={track_audit.get('passed_event_count', 'n/a')}/{track_audit.get('event_count', 'n/a')}",
                f"frontend_manifest_files={freeze_groups.get('frontend', {}).get('file_count', 0)}",
                "Dashboard includes track map, simulation replay, market/source readiness, model error review, replay, calibration, and freeze panels.",
            ),
            gaps=tuple(gaps),
            next_actions=() if passed else ("Restore missing dashboard targets and rerun browser verification.",),
            artifact_refs={
                "frontend": "web/index.html",
                "track_assets": "reports/track_assets/2026_track_asset_audit.json",
            },
        )

    def _improvement_requirement(self, reports: dict[str, dict[str, Any]], stem: str) -> MVPGateRequirement:
        improvement = reports["improvement"]
        workstreams = improvement.get("workstreams", [])
        passed = bool(workstreams)
        return MVPGateRequirement(
            requirement_id="problem_analysis_and_improvement_plan",
            title="Problem Analysis and Improvement Plan",
            status="passed" if passed else "missing",
            blocks_mvp_delivery=not passed,
            blocks_formal_edge=False,
            evidence=(
                f"top_priority={improvement.get('top_priority', 'missing')}",
                f"blocking_workstreams={improvement.get('blocking_workstream_count', 0)}",
                f"diagnostic_workstreams={improvement.get('diagnostic_workstream_count', 0)}",
            ),
            gaps=() if passed else ("Improvement plan report is missing.",),
            next_actions=tuple(
                f"P{row.get('priority')} {row.get('title')}: {row.get('status')}"
                for row in workstreams[:3]
                if isinstance(row, dict)
            ),
            artifact_refs={"improvement_plan": self._report_path("improvement_plan", stem, ".improvement_plan.json")},
        )

    def _reproducibility_requirement(self, reports: dict[str, dict[str, Any]], stem: str) -> MVPGateRequirement:
        freeze = reports["freeze"]
        flags = tuple(str(item) for item in freeze.get("integrity_flags", []))
        group_count = len(freeze.get("artifact_groups", []))
        passed = bool(freeze.get("manifest_payload_sha256")) and group_count >= 4
        return MVPGateRequirement(
            requirement_id="reproducibility_and_artifact_freeze",
            title="Reproducibility and Artifact Freeze",
            status="diagnostic_passed" if passed else "missing",
            blocks_mvp_delivery=not passed,
            blocks_formal_edge=bool(flags),
            evidence=(
                f"freeze_status={freeze.get('status', 'missing')}",
                f"artifact_groups={group_count}",
                f"manifest_hash={(freeze.get('manifest_payload_sha256') or '')[:12]}",
            ),
            gaps=flags,
            next_actions=tuple(freeze.get("command_plan", [])[:3]),
            artifact_refs={"replay_freeze": self._report_path("replay_freeze", stem, ".freeze.json")},
        )

    @staticmethod
    def _status(diagnostic_operational: bool, mvp_ready: bool, formal_edge_ready: bool) -> str:
        if formal_edge_ready and mvp_ready:
            return "formal_edge_ready"
        if mvp_ready:
            return "mvp_delivery_ready"
        if diagnostic_operational:
            return "diagnostic_mvp_operational_inputs_required"
        return "mvp_incomplete"

    @staticmethod
    def _summary(requirements: tuple[MVPGateRequirement, ...], reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for row in requirements:
            counts[row.status] = counts.get(row.status, 0) + 1
        return {
            "requirement_count": len(requirements),
            "status_counts": counts,
            "mvp_blockers": sum(1 for row in requirements if row.blocks_mvp_delivery),
            "formal_edge_blockers": sum(1 for row in requirements if row.blocks_formal_edge),
            "top_priority": reports["improvement"].get("top_priority", ""),
            "blocking_action_count": reports["readiness"].get("blocking_action_count", 0),
            "market_unresolved_events": reports["market"].get(
                "blocking_unresolved_event_count",
                reports["market"].get("unresolved_event_count", 0),
            ),
            "market_total_unresolved_events": reports["market"].get("unresolved_event_count", 0),
            "market_warning_only_events": reports["market"].get("warning_only_unresolved_event_count", 0),
            "source_unresolved_rows": reports["source"].get("source_count", 0),
            "source_replacement_candidates": reports.get("source_replacements", {}).get("candidate_count", 0),
            "cutoff_valid_source_replacements": reports.get("source_replacements", {}).get("cutoff_valid_replacement_count", 0),
            "codex_source_candidate_ready_reports": reports.get("codex_intake", {}).get("source_candidates_ready_count", 0),
            "codex_preflight_passed_reports": reports.get("codex_intake", {}).get("preflight_passed_count", 0),
        }

    @staticmethod
    def _next_actions(
        requirements: tuple[MVPGateRequirement, ...],
        reports: dict[str, dict[str, Any]],
    ) -> tuple[str, ...]:
        actions: list[str] = []
        for action in reports["chronological"].get("next_actions", []):
            actions.append(str(action))
        for row in requirements:
            if row.blocks_mvp_delivery:
                actions.extend(row.next_actions)
        return tuple(dict.fromkeys(actions))[:8]

    @staticmethod
    def _warnings(requirements: tuple[MVPGateRequirement, ...], reports: dict[str, dict[str, Any]]) -> tuple[str, ...]:
        warnings = [
            "diagnostic_status_is_not_formal_edge_proof",
            *[str(item) for item in reports["chronological"].get("warnings", [])],
        ]
        if any(row.blocks_mvp_delivery for row in requirements):
            warnings.append("mvp_delivery_blockers_remaining")
        return tuple(dict.fromkeys(warnings))

    def _read_optional(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _codex_intake_summary(self) -> dict[str, Any]:
        candidate_reports = self._read_report_dir(self.reports_root / "research_candidates", ".json")
        preflight_reports = self._read_report_dir(self.reports_root / "research_preflight", ".json")
        candidate_status_counts = self._status_counts(candidate_reports)
        preflight_status_counts = self._status_counts(preflight_reports)
        return {
            "candidate_report_count": len(candidate_reports),
            "preflight_report_count": len(preflight_reports),
            "candidate_status_counts": candidate_status_counts,
            "preflight_status_counts": preflight_status_counts,
            "source_candidates_ready_count": candidate_status_counts.get("source_candidates_ready_for_claim_review", 0),
            "source_candidates_blocked_count": candidate_status_counts.get("source_candidates_blocked", 0),
            "preflight_passed_count": preflight_status_counts.get("preflight_passed", 0),
            "preflight_failed_count": preflight_status_counts.get("preflight_failed", 0),
            "preflight_unfilled_template_count": preflight_status_counts.get("research_packet_template_unfilled", 0),
        }

    @staticmethod
    def _read_report_dir(directory: Path, suffix: str) -> list[dict[str, Any]]:
        if not directory.exists():
            return []
        reports: list[dict[str, Any]] = []
        for path in sorted(directory.glob(f"*{suffix}")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                reports.append(payload)
        return reports

    @staticmethod
    def _status_counts(reports: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for report in reports:
            status = str(report.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
        return dict(sorted(counts.items()))

    @staticmethod
    def _read_text(path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _stem(year: int, as_of: str) -> str:
        return f"{year}_asof_{as_of.replace(':', '').replace('+', '_').replace('-', '')}"

    @staticmethod
    def _report_path(directory: str, stem: str, suffix: str) -> str:
        return f"reports/{directory}/{stem}{suffix}"
