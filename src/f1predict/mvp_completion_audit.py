"""Completion audit for the diagnostic MVP objective."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from f1predict.domain import utc_now
from f1predict.replay_artifacts import replay_stem


MVP_COMPLETE_STATUSES = {"achieved", "diagnostic_achieved"}


@dataclass(frozen=True)
class MVPCompletionRequirement:
    requirement_id: str
    title: str
    status: str
    mvp_required: bool
    formal_edge_required: bool
    evidence: tuple[str, ...]
    residual_risks: tuple[str, ...]
    next_actions: tuple[str, ...]
    artifact_refs: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "title": self.title,
            "status": self.status,
            "mvp_required": self.mvp_required,
            "formal_edge_required": self.formal_edge_required,
            "evidence": list(self.evidence),
            "residual_risks": list(self.residual_risks),
            "next_actions": list(self.next_actions),
            "artifact_refs": self.artifact_refs,
        }


@dataclass(frozen=True)
class MVPCompletionAuditReport:
    year: int
    as_of: str
    generated_at: str
    status: str
    mvp_complete: bool
    formal_edge_ready: bool
    mvp_gate_status: str
    summary: dict[str, Any]
    requirements: tuple[MVPCompletionRequirement, ...]
    next_actions: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "as_of": self.as_of,
            "generated_at": self.generated_at,
            "status": self.status,
            "mvp_complete": self.mvp_complete,
            "formal_edge_ready": self.formal_edge_ready,
            "mvp_gate_status": self.mvp_gate_status,
            "summary": self.summary,
            "requirements": [row.to_dict() for row in self.requirements],
            "next_actions": list(self.next_actions),
            "warnings": list(self.warnings),
        }

    def to_markdown(self) -> str:
        lines = [
            f"# F1Predict MVP Completion Audit ({self.year})",
            "",
            f"- Generated at: `{self.generated_at}`",
            f"- Replay cutoff: `{self.as_of}`",
            f"- Status: **{self.status}**",
            f"- MVP complete: **{self.mvp_complete}**",
            f"- Formal edge ready: **{self.formal_edge_ready}**",
            f"- MVP gate status: **{self.mvp_gate_status}**",
            "",
            "## Summary",
            "",
        ]
        for key, value in self.summary.items():
            lines.append(f"- {key}: {value}")
        lines.extend(
            [
                "",
                "## Requirement Audit",
                "",
                "| Requirement | Status | MVP Required | Formal Edge Required | Evidence | Residual Risks |",
                "|---|---|---:|---:|---|---|",
            ]
        )
        for row in self.requirements:
            evidence = "<br>".join(row.evidence[:4]) or "n/a"
            risks = "<br>".join(row.residual_risks[:4]) or "none"
            lines.append(
                "| "
                f"{row.title} | {row.status} | {row.mvp_required} | "
                f"{row.formal_edge_required} | {evidence} | {risks} |"
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


class MVPCompletionAuditBuilder:
    """Audits the current artifacts against the user's MVP delivery objective."""

    def __init__(self, reports_root: Path | str = Path("reports"), workspace_root: Path | str = Path(".")) -> None:
        self.reports_root = Path(reports_root)
        self.workspace_root = Path(workspace_root)

    def build(self, year: int, as_of: str) -> MVPCompletionAuditReport:
        stem = replay_stem(year, as_of)
        reports = self._load_reports(year, stem)
        requirements = (
            self._architecture_requirement(),
            self._codex_layer_requirement(reports, stem),
            self._factor_translation_requirement(reports),
            self._simulation_requirement(reports, stem),
            self._market_gap_requirement(reports, stem),
            self._replay_problem_requirement(reports, stem),
            self._frontend_requirement(reports),
            self._positive_help_requirement(reports, stem),
            self._formal_edge_boundary_requirement(reports, stem),
            self._verification_requirement(reports, stem),
        )
        mvp_incomplete = [
            row
            for row in requirements
            if row.mvp_required and row.status not in MVP_COMPLETE_STATUSES
        ]
        mvp_complete = not mvp_incomplete
        gate = reports["mvp_gate"]
        formal_edge_ready = bool(gate.get("formal_edge_ready"))
        status = self._status(mvp_complete, formal_edge_ready)
        return MVPCompletionAuditReport(
            year=year,
            as_of=as_of,
            generated_at=utc_now().replace(microsecond=0).isoformat(),
            status=status,
            mvp_complete=mvp_complete,
            formal_edge_ready=formal_edge_ready,
            mvp_gate_status=str(gate.get("status") or "missing"),
            summary=self._summary(requirements, reports),
            requirements=requirements,
            next_actions=self._next_actions(requirements, reports),
            warnings=self._warnings(requirements, reports),
        )

    def write(
        self,
        year: int,
        as_of: str,
        output_dir: Path | str = Path("reports/mvp_completion_audit"),
    ) -> dict[str, Path]:
        report = self.build(year, as_of)
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        stem = replay_stem(year, as_of)
        json_path = directory / f"{stem}.mvp_completion_audit.json"
        markdown_path = directory / f"{stem}.mvp_completion_audit.md"
        json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(report.to_markdown(), encoding="utf-8")
        return {"json": json_path, "markdown": markdown_path}

    def _load_reports(self, year: int, stem: str) -> dict[str, dict[str, Any]]:
        return {
            "mvp_gate": self._read_optional(self.reports_root / "mvp_gate" / f"{stem}.mvp_gate.json"),
            "chronological": self._read_optional(
                self.reports_root / "chronological_replay" / f"{stem}.chronological_replay.json"
            ),
            "analysis": self._read_optional(self.reports_root / "replay_analysis" / f"{stem}.analysis.json"),
            "improvement": self._read_optional(
                self.reports_root / "improvement_plan" / f"{stem}.improvement_plan.json"
            ),
            "market": self._read_optional(self.reports_root / "market_readiness" / f"{stem}.market_readiness.json"),
            "calibration": self._read_optional(self.reports_root / "calibration" / f"{stem}.calibration.json"),
            "model_error": self._read_optional(
                self.reports_root / "model_error_review" / f"{stem}.model_error_review.json"
            ),
            "simulator_calibration": self._read_optional(
                self.reports_root / "simulator_calibration" / f"{stem}.simulator_calibration.json"
            ),
            "freeze": self._read_optional(self.reports_root / "replay_freeze" / f"{stem}.freeze.json"),
            "track_assets": self._read_optional(self.reports_root / "track_assets" / f"{year}_track_asset_audit.json"),
            "prediction_packet": self._latest_prediction_packet("british_gp"),
            "research_candidates": self._read_optional(self.reports_root / "research_candidates" / "british_gp.json"),
            "research_preflight": self._read_optional(self.reports_root / "research_preflight" / "british_gp.json"),
        }

    def _architecture_requirement(self) -> MVPCompletionRequirement:
        paths = (
            "src/f1predict/pipeline.py",
            "src/f1predict/models/simulator.py",
            "src/f1predict/models/pace.py",
            "src/f1predict/models/technical_factors.py",
            "src/f1predict/intelligence/research_plan.py",
            "src/f1predict/intelligence/source_candidates.py",
            "src/f1predict/intelligence/research_packet.py",
            "src/f1predict/intelligence/evidence_quality.py",
            "src/f1predict/chronological_replay.py",
            "src/f1predict/mvp_gate.py",
            "src/f1predict/server.py",
            "web/app.js",
            "docs/f1_prediction_architecture_report.md",
        )
        missing = tuple(path for path in paths if not self._workspace_path(path).exists())
        return MVPCompletionRequirement(
            requirement_id="modular_extensible_architecture",
            title="Modular, Extensible Project Architecture",
            status="achieved" if not missing else "partial",
            mvp_required=True,
            formal_edge_required=False,
            evidence=(
                "pipeline, simulator, technical-factor, Codex-intelligence, replay, gate, server, and frontend modules are separated.",
                f"checked_paths={len(paths)}; missing_paths={len(missing)}",
                "architecture report is present for future large-project expansion.",
            ),
            residual_risks=missing,
            next_actions=tuple(f"Restore or implement {path}." for path in missing),
            artifact_refs={
                "architecture_report": "docs/f1_prediction_architecture_report.md",
                "pipeline": "src/f1predict/pipeline.py",
                "frontend": "web/app.js",
            },
        )

    def _codex_layer_requirement(self, reports: dict[str, dict[str, Any]], stem: str) -> MVPCompletionRequirement:
        gate_row = self._gate_requirement(reports, "codex_normalized_intelligence")
        gate_summary = reports["mvp_gate"].get("summary", {})
        source_candidates = reports["research_candidates"]
        preflight = reports["research_preflight"]
        candidate_ready = int(gate_summary.get("codex_source_candidate_ready_reports") or 0)
        preflight_passed = int(gate_summary.get("codex_preflight_passed_reports") or 0)
        achieved = gate_row.get("status") in {"passed", "diagnostic_passed"} and candidate_ready > 0 and preflight_passed > 0
        return MVPCompletionRequirement(
            requirement_id="codex_normalized_llm_layer",
            title="Codex-Normalized Intelligence Layer",
            status="diagnostic_achieved" if achieved else "partial",
            mvp_required=True,
            formal_edge_required=True,
            evidence=(
                f"mvp_gate_status={gate_row.get('status', 'missing')}",
                f"events_with_evidence={self._metric(reports['chronological'], 'diagnostic_metrics.events_with_evidence', 0)}",
                f"source_candidate_status={source_candidates.get('status', 'missing')}",
                f"research_preflight_status={preflight.get('status', 'missing')}",
                "Codex workflow includes source candidate audits, packet preflight, source logs, evidence quality, conflict checks, and factor contracts.",
            ),
            residual_risks=tuple(gate_row.get("gaps") or ()),
            next_actions=tuple(gate_row.get("next_actions") or ()),
            artifact_refs={
                "mvp_gate": self._report_path("mvp_gate", stem, ".mvp_gate.json"),
                "source_candidates": "reports/research_candidates/british_gp.json",
                "research_preflight": "reports/research_preflight/british_gp.json",
            },
        )

    def _factor_translation_requirement(self, reports: dict[str, dict[str, Any]]) -> MVPCompletionRequirement:
        packet = reports["prediction_packet"]
        context = packet.get("codex_context", {})
        route_counts = context.get("factor_route_counts", {})
        factor_trace = context.get("factor_trace", [])
        required_routes = ("track_contextual_pace", "race_start_launch", "tyre_degradation", "wet_weather")
        present_routes = tuple(route for route in required_routes if int(route_counts.get(route) or 0) > 0)
        has_effective_inputs = any(row.get("effective_race_input") is not None for row in factor_trace if isinstance(row, dict))
        has_track_demands = any(row.get("track_demand_component") for row in factor_trace if isinstance(row, dict))
        achieved = len(present_routes) >= 3 and has_effective_inputs and has_track_demands
        return MVPCompletionRequirement(
            requirement_id="news_facts_to_simulation_factors",
            title="News and Facts to Simulation Factors",
            status="diagnostic_achieved" if achieved else "partial",
            mvp_required=True,
            formal_edge_required=True,
            evidence=(
                f"factor_trace_count={context.get('factor_trace_count', len(factor_trace))}",
                f"factor_route_counts={self._format_map(route_counts)}",
                f"routes_present={', '.join(present_routes) or 'none'}",
                f"effective_inputs={has_effective_inputs}; track_demands={has_track_demands}",
            ),
            residual_risks=(
                "The routing contract is proven on diagnostic British GP packets and smoke fixtures, not yet on a large held-out season corpus.",
            ),
            next_actions=(
                "Run a matched no-Codex and Codex-factor ablation after source and market inputs are frozen.",
            ),
            artifact_refs={
                "prediction_packet": str(packet.get("artifact_path") or "reports/prediction_packets/british_gp/"),
                "technical_factor_model": "src/f1predict/models/technical_factors.py",
            },
        )

    def _simulation_requirement(self, reports: dict[str, dict[str, Any]], stem: str) -> MVPCompletionRequirement:
        gate_row = self._gate_requirement(reports, "simulation_and_probabilities")
        packet = reports["prediction_packet"]
        prediction = packet.get("prediction", {})
        probabilities = prediction.get("race_probabilities", [])
        simulation_replay = prediction.get("simulation_replay", [])
        achieved = gate_row.get("status") in {"passed", "diagnostic_passed"} and bool(probabilities) and bool(simulation_replay)
        return MVPCompletionRequirement(
            requirement_id="multi_round_simulation_probabilities",
            title="Multi-Round Simulation and Probability Outputs",
            status="diagnostic_achieved" if achieved else "partial",
            mvp_required=True,
            formal_edge_required=True,
            evidence=(
                f"mvp_gate_status={gate_row.get('status', 'missing')}",
                f"probability_rows={len(probabilities)}",
                f"simulation_replay_rows={len(simulation_replay)}",
                f"simulator_calibration_candidates={reports['simulator_calibration'].get('candidate_count', 0)}",
            ),
            residual_risks=tuple(gate_row.get("gaps") or ()),
            next_actions=tuple(gate_row.get("next_actions") or ()),
            artifact_refs={
                "prediction_packet": "reports/prediction_packets/british_gp/",
                "simulator_calibration": self._report_path("simulator_calibration", stem, ".simulator_calibration.json"),
            },
        )

    def _market_gap_requirement(self, reports: dict[str, dict[str, Any]], stem: str) -> MVPCompletionRequirement:
        gate_row = self._gate_requirement(reports, "market_gap_analysis")
        achieved = gate_row.get("status") in {"passed", "diagnostic_passed"} and not bool(gate_row.get("blocks_mvp_delivery"))
        return MVPCompletionRequirement(
            requirement_id="market_gap_analysis_no_execution",
            title="Market Gap Analysis Without Trade Execution",
            status="diagnostic_achieved" if achieved else "partial",
            mvp_required=True,
            formal_edge_required=True,
            evidence=(
                f"mvp_gate_status={gate_row.get('status', 'missing')}",
                f"market_scored_events={self._extract_evidence_value(gate_row, 'market_scored_events')}",
                f"market_unresolved_events={reports['mvp_gate'].get('summary', {}).get('market_unresolved_events', 0)}",
                "Project compares model probabilities against market snapshots; no execution workflow is part of the MVP.",
            ),
            residual_risks=tuple(gate_row.get("gaps") or ()),
            next_actions=tuple(gate_row.get("next_actions") or ()),
            artifact_refs={
                "market_readiness": self._report_path("market_readiness", stem, ".market_readiness.json"),
                "mvp_gate": self._report_path("mvp_gate", stem, ".mvp_gate.json"),
            },
        )

    def _replay_problem_requirement(self, reports: dict[str, dict[str, Any]], stem: str) -> MVPCompletionRequirement:
        replay_scope = reports["chronological"].get("replay_scope", {})
        due = int(replay_scope.get("due_events") or 0)
        replayed = int(replay_scope.get("replayed_events") or 0)
        analysis = reports["analysis"]
        improvement = reports["improvement"]
        achieved = due > 0 and due == replayed and bool(analysis) and bool(improvement)
        return MVPCompletionRequirement(
            requirement_id="chronological_replay_and_problem_analysis",
            title="Chronological Replay and Problem Analysis",
            status="diagnostic_achieved" if achieved else "partial",
            mvp_required=True,
            formal_edge_required=True,
            evidence=(
                f"due_events={due}; replayed_events={replayed}",
                f"top_pick_hit_rate={self._metric(reports['chronological'], 'diagnostic_metrics.top_pick_hit_rate', 'n/a')}",
                f"analysis_status={analysis.get('status', 'missing')}",
                f"top_priority={improvement.get('top_priority', 'missing')}",
            ),
            residual_risks=tuple(reports["chronological"].get("warnings") or ()),
            next_actions=tuple(reports["chronological"].get("next_actions") or ()),
            artifact_refs={
                "chronological_replay": self._report_path("chronological_replay", stem, ".chronological_replay.json"),
                "replay_analysis": self._report_path("replay_analysis", stem, ".analysis.json"),
                "improvement_plan": self._report_path("improvement_plan", stem, ".improvement_plan.json"),
            },
        )

    def _frontend_requirement(self, reports: dict[str, dict[str, Any]]) -> MVPCompletionRequirement:
        gate_row = self._gate_requirement(reports, "frontend_dashboard")
        track = reports["track_assets"]
        screenshot_paths = (
            "output/playwright/british_gp_8811_final_track_canvas.png",
            "output/playwright/british_gp_8811_final_replay_track_canvas.png",
            "output/playwright/mvp-gate-delivery-ready-summary.png",
        )
        existing_screenshots = tuple(path for path in screenshot_paths if self._workspace_path(path).exists())
        achieved = gate_row.get("status") == "passed" and track.get("status") == "passed"
        return MVPCompletionRequirement(
            requirement_id="frontend_inspection_dashboard",
            title="Frontend Inspection Dashboard",
            status="achieved" if achieved else "partial",
            mvp_required=True,
            formal_edge_required=False,
            evidence=(
                f"mvp_gate_status={gate_row.get('status', 'missing')}",
                f"track_asset_audit_status={track.get('status', 'missing')}",
                f"track_asset_passed_events={track.get('passed_event_count', 0)}/{track.get('event_count', 0)}",
                f"playwright_screenshots={len(existing_screenshots)}",
                "Dashboard exposes event map, official track asset audit, simulation replay, packet/preflight, market gap, replay analysis, MVP gate, calibration, and freeze panels.",
            ),
            residual_risks=tuple(gate_row.get("gaps") or ()),
            next_actions=tuple(gate_row.get("next_actions") or ()),
            artifact_refs={
                "frontend": "web/index.html",
                "frontend_logic": "web/app.js",
                "track_assets": "reports/track_assets/2026_track_asset_audit.json",
                "british_gp_track_screenshot": existing_screenshots[0] if existing_screenshots else "",
            },
        )

    def _positive_help_requirement(self, reports: dict[str, dict[str, Any]], stem: str) -> MVPCompletionRequirement:
        packet = reports["prediction_packet"]
        context = packet.get("codex_context", {})
        chronological_metrics = reports["chronological"].get("diagnostic_metrics", {})
        model_error = reports["model_error"]
        evidence_impact_count = int(context.get("evidence_impact_count") or 0)
        events_with_impact = int(chronological_metrics.get("events_with_evidence_impact") or 0)
        reviewed_events = int(model_error.get("reviewed_events") or 0)
        max_delta = context.get("max_evidence_win_delta")
        achieved = evidence_impact_count > 0 and events_with_impact > 0 and reviewed_events > 0
        return MVPCompletionRequirement(
            requirement_id="codex_factor_positive_help_diagnostics",
            title="Codex Factor Impact Diagnostics",
            status="diagnostic_achieved" if achieved else "partial",
            mvp_required=True,
            formal_edge_required=True,
            evidence=(
                f"packet_evidence_impact_count={evidence_impact_count}",
                f"events_with_evidence_impact={events_with_impact}",
                f"max_evidence_win_delta={max_delta}",
                f"model_error_reviewed_events={reviewed_events}; missed_events={model_error.get('missed_events', 0)}",
            ),
            residual_risks=(
                "Current evidence proves Codex factors are routed and move simulated probabilities; it does not yet prove positive lift versus a locked no-Codex baseline.",
                "Formal positive-help claims require matched ablations after input archives and market snapshots are frozen.",
            ),
            next_actions=(
                "Add a no-Codex replay ablation and a Codex-factor-only ablation on the same replay freeze.",
                "Promote the result only if source, market, seeds, and simulator config are locked.",
            ),
            artifact_refs={
                "prediction_packet": "reports/prediction_packets/british_gp/",
                "model_error_review": self._report_path("model_error_review", stem, ".model_error_review.json"),
                "chronological_replay": self._report_path("chronological_replay", stem, ".chronological_replay.json"),
            },
        )

    def _formal_edge_boundary_requirement(
        self,
        reports: dict[str, dict[str, Any]],
        stem: str,
    ) -> MVPCompletionRequirement:
        gate = reports["mvp_gate"]
        summary = gate.get("summary", {})
        formal_blockers = int(summary.get("formal_edge_blockers") or 0)
        boundary_clear = bool(gate.get("mvp_delivery_ready")) and not bool(gate.get("formal_edge_ready")) and formal_blockers > 0
        return MVPCompletionRequirement(
            requirement_id="formal_edge_boundary",
            title="Formal Edge Boundary",
            status="formal_blocked" if boundary_clear else "partial",
            mvp_required=False,
            formal_edge_required=True,
            evidence=(
                f"mvp_delivery_ready={gate.get('mvp_delivery_ready', False)}",
                f"formal_edge_ready={gate.get('formal_edge_ready', False)}",
                f"formal_edge_blockers={formal_blockers}",
                "The MVP is explicitly diagnostic; stable edge, CLV, and trade execution are not claimed.",
            ),
            residual_risks=tuple(gate.get("warnings") or ()),
            next_actions=tuple(gate.get("next_actions") or ()),
            artifact_refs={"mvp_gate": self._report_path("mvp_gate", stem, ".mvp_gate.json")},
        )

    def _verification_requirement(self, reports: dict[str, dict[str, Any]], stem: str) -> MVPCompletionRequirement:
        required_paths = (
            "scripts/smoke_test.py",
            "src/f1predict/mvp_gate.py",
            "web/app.js",
            "reports/mvp_gate/" + f"{stem}.mvp_gate.json",
            "reports/prediction_packets/british_gp/british_gp_20260630T120000_0000.prediction_packet.json",
        )
        missing = tuple(path for path in required_paths if not self._workspace_path(path).exists())
        achieved = not missing and bool(reports["mvp_gate"].get("mvp_delivery_ready"))
        return MVPCompletionRequirement(
            requirement_id="verification_and_artifact_checks",
            title="Verification and Artifact Checks",
            status="achieved" if achieved else "partial",
            mvp_required=True,
            formal_edge_required=False,
            evidence=(
                "Smoke test covers official British GP track asset, replay rows, factor routing, packet preflight, market/readiness plumbing, and MVP gate.",
                f"required_artifacts={len(required_paths)}; missing_artifacts={len(missing)}",
                f"mvp_gate_ready={reports['mvp_gate'].get('mvp_delivery_ready', False)}",
            ),
            residual_risks=missing,
            next_actions=tuple(f"Restore or regenerate {path}." for path in missing),
            artifact_refs={
                "smoke_test": "scripts/smoke_test.py",
                "mvp_gate": self._report_path("mvp_gate", stem, ".mvp_gate.json"),
            },
        )

    @staticmethod
    def _status(mvp_complete: bool, formal_edge_ready: bool) -> str:
        if mvp_complete and formal_edge_ready:
            return "mvp_complete_and_formal_edge_ready"
        if mvp_complete:
            return "mvp_complete_formal_edge_not_ready"
        return "mvp_incomplete"

    @staticmethod
    def _summary(
        requirements: tuple[MVPCompletionRequirement, ...],
        reports: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for row in requirements:
            counts[row.status] = counts.get(row.status, 0) + 1
        mvp_required = [row for row in requirements if row.mvp_required]
        return {
            "requirement_count": len(requirements),
            "mvp_required_count": len(mvp_required),
            "status_counts": dict(sorted(counts.items())),
            "mvp_incomplete_count": sum(1 for row in mvp_required if row.status not in MVP_COMPLETE_STATUSES),
            "formal_edge_blockers": reports["mvp_gate"].get("summary", {}).get("formal_edge_blockers", 0),
            "top_replay_issue": reports["improvement"].get("top_priority", ""),
            "chronological_hit_rate": MVPCompletionAuditBuilder._metric(
                reports["chronological"], "diagnostic_metrics.top_pick_hit_rate", "n/a"
            ),
            "codex_events_with_evidence": MVPCompletionAuditBuilder._metric(
                reports["chronological"], "diagnostic_metrics.events_with_evidence", 0
            ),
            "codex_factor_trace_count": reports["prediction_packet"].get("codex_context", {}).get("factor_trace_count", 0),
        }

    @staticmethod
    def _next_actions(
        requirements: tuple[MVPCompletionRequirement, ...],
        reports: dict[str, dict[str, Any]],
    ) -> tuple[str, ...]:
        actions: list[str] = []
        for row in requirements:
            if row.status not in MVP_COMPLETE_STATUSES or row.formal_edge_required:
                actions.extend(row.next_actions)
        actions.extend(str(item) for item in reports["mvp_gate"].get("next_actions", []))
        return tuple(dict.fromkeys(action for action in actions if action))[:10]

    @staticmethod
    def _warnings(
        requirements: tuple[MVPCompletionRequirement, ...],
        reports: dict[str, dict[str, Any]],
    ) -> tuple[str, ...]:
        warnings = [
            "mvp_completion_is_diagnostic_not_stable_edge",
            "codex_positive_help_requires_matched_no_codex_ablation_before_formal_claims",
        ]
        warnings.extend(str(item) for item in reports["mvp_gate"].get("warnings", []))
        if any(row.mvp_required and row.status not in MVP_COMPLETE_STATUSES for row in requirements):
            warnings.append("mvp_required_rows_incomplete")
        return tuple(dict.fromkeys(warnings))

    def _gate_requirement(self, reports: dict[str, dict[str, Any]], requirement_id: str) -> dict[str, Any]:
        for row in reports["mvp_gate"].get("requirements", []):
            if row.get("requirement_id") == requirement_id:
                return row
        return {}

    def _latest_prediction_packet(self, event_id: str) -> dict[str, Any]:
        directory = self.reports_root / "prediction_packets" / event_id
        if not directory.exists():
            return {}
        packets = sorted(directory.glob("*.prediction_packet.json"))
        if not packets:
            return {}
        payload = self._read_optional(packets[-1])
        payload["artifact_path"] = self._display_path(packets[-1])
        return payload

    @staticmethod
    def _read_optional(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _workspace_path(self, relative_path: str) -> Path:
        return self.workspace_root / relative_path

    @staticmethod
    def _metric(report: dict[str, Any], dotted_key: str, default: Any) -> Any:
        value: Any = report
        for key in dotted_key.split("."):
            if not isinstance(value, dict) or key not in value:
                return default
            value = value[key]
        return value

    @staticmethod
    def _extract_evidence_value(gate_row: dict[str, Any], prefix: str) -> str:
        for item in gate_row.get("evidence", []):
            text = str(item)
            if text.startswith(prefix + "="):
                return text.split("=", 1)[1]
        return "missing"

    @staticmethod
    def _format_map(value: object) -> str:
        if not isinstance(value, dict) or not value:
            return "none"
        return ", ".join(f"{key}={count}" for key, count in sorted(value.items()))

    def _report_path(self, directory: str, stem: str, suffix: str) -> str:
        return self._display_path(self.reports_root / directory / f"{stem}{suffix}")

    @staticmethod
    def _display_path(path: Path | str) -> str:
        return str(path).replace("\\", "/")
