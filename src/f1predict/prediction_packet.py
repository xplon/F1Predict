"""Auditable single-event prediction packets."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from f1predict.domain import PredictionReport, parse_dt, utc_now
from f1predict.event_inputs import audit_event_input
from f1predict.market import after_cutoff_market_count, event_market_snapshots
from f1predict.pipeline import PredictionPipeline
from f1predict.storage import safe_name


@dataclass(frozen=True)
class PredictionPacket:
    event_id: str
    event_name: str
    generated_at: str
    knowledge_cutoff: str | None
    iterations: int
    status: str
    formal_edge_ready: bool
    packet_payload_sha256: str
    blocker_codes: tuple[str, ...]
    warning_codes: tuple[str, ...]
    event_input_audit: dict[str, Any]
    market_context: dict[str, Any]
    model_context: dict[str, Any]
    codex_context: dict[str, Any]
    probability_summary: dict[str, Any]
    top_market_edges: tuple[dict[str, Any], ...]
    prediction: dict[str, Any]

    def to_dict(self, include_payload_hash: bool = True) -> dict[str, Any]:
        payload = {
            "event_id": self.event_id,
            "event_name": self.event_name,
            "generated_at": self.generated_at,
            "knowledge_cutoff": self.knowledge_cutoff,
            "iterations": self.iterations,
            "status": self.status,
            "formal_edge_ready": self.formal_edge_ready,
            "blocker_codes": list(self.blocker_codes),
            "warning_codes": list(self.warning_codes),
            "event_input_audit": self.event_input_audit,
            "market_context": self.market_context,
            "model_context": self.model_context,
            "codex_context": self.codex_context,
            "probability_summary": self.probability_summary,
            "top_market_edges": list(self.top_market_edges),
            "prediction": self.prediction,
        }
        if include_payload_hash:
            payload["packet_payload_sha256"] = self.packet_payload_sha256
        return payload

    def to_markdown(self) -> str:
        lines = [
            f"# Prediction Packet: {self.event_name}",
            "",
            f"- Event: `{self.event_id}`",
            f"- Generated at: `{self.generated_at}`",
            f"- Knowledge cutoff: `{self.knowledge_cutoff or 'latest/current'}`",
            f"- Iterations: `{self.iterations}`",
            f"- Status: **{self.status}**",
            f"- Formal edge ready: `{self.formal_edge_ready}`",
            f"- Packet payload SHA-256: `{self.packet_payload_sha256}`",
            "",
            "## Probability Summary",
            "",
        ]
        for row in self.probability_summary.get("top_win_probabilities", []):
            lines.append(
                f"- `{row.get('driver_id')}` win={_fmt_pct(row.get('win'))}, "
                f"podium={_fmt_pct(row.get('podium'))}, expected_points={row.get('expected_points')}"
            )
        lines.extend(["", "## Codex Evidence", ""])
        lines.append(f"- Claims: `{self.codex_context.get('evidence_count', 0)}`")
        lines.append(f"- Quality rows: `{self.codex_context.get('evidence_quality_count', 0)}`")
        lines.append(f"- Weak/review-required: `{self.codex_context.get('weak_evidence_quality_count', 0)}`")
        lines.append(f"- Strong: `{self.codex_context.get('strong_evidence_quality_count', 0)}`")
        intake = self.codex_context.get("intake") or {}
        if intake:
            lines.append(f"- Source-candidate status: `{intake.get('source_candidate_status', 'missing')}`")
            lines.append(f"- Research preflight status: `{intake.get('research_preflight_status', 'missing')}`")
            lines.append(f"- Preflight valid claims: `{intake.get('preflight_valid_claim_count', 0)}`")
        quality_counts = self.codex_context.get("quality_status_counts") or {}
        for status, count in quality_counts.items():
            lines.append(f"- `{status}`: {count}")
        triangulation_counts = self.codex_context.get("triangulation_status_counts") or {}
        if triangulation_counts:
            lines.append("- Triangulation:")
            for status, count in triangulation_counts.items():
                lines.append(f"  - `{status}`: {count}")
        conflict_counts = self.codex_context.get("conflict_status_counts") or {}
        if conflict_counts:
            lines.append("- Source conflicts:")
            for status, count in conflict_counts.items():
                lines.append(f"  - `{status}`: {count}")
        factor_route_counts = self.codex_context.get("factor_route_counts") or {}
        if factor_route_counts:
            lines.extend(["", "## Normalized Factor Trace", ""])
            lines.append(f"- Routed factors: `{self.codex_context.get('factor_trace_count', 0)}`")
            lines.append(f"- Observed probability movement: `{self.codex_context.get('factor_observed_movement_count', 0)}`")
            lines.append(f"- Average model input weight: `{self.codex_context.get('average_model_input_weight', 'n/a')}`")
            for route, count in factor_route_counts.items():
                lines.append(f"- `{route}`: {count}")
            for row in self.codex_context.get("factor_trace", [])[:8]:
                lines.append(
                    f"- `{row.get('claim_id')}` {row.get('target_id')} -> `{row.get('metric')}` "
                    f"-> `{row.get('route')}` ({row.get('route_status')}), "
                    f"weight={row.get('model_input_weight')}, weighted={row.get('weighted_input_impact')}, "
                    f"effective_race={row.get('effective_race_input')}, "
                    f"context_multiplier={row.get('context_multiplier')}, "
                    f"max_win_delta={_fmt_signed_pct(row.get('max_win_probability_delta'))}"
                )
        lines.extend(["", "## Market Context", ""])
        lines.append(f"- Usable snapshots: `{self.market_context.get('usable_snapshot_count', 0)}`")
        lines.append(f"- After-cutoff snapshots: `{self.market_context.get('after_cutoff_snapshot_count', 0)}`")
        lines.append(f"- Market edges: `{self.market_context.get('market_edge_count', 0)}`")
        for edge in self.top_market_edges:
            lines.append(
                f"- `{edge.get('outcome_id')}` conservative_edge_after_cost="
                f"{_fmt_pct(edge.get('conservative_edge_after_cost'))}, recommendation={edge.get('recommendation')}"
            )
        simulator_config = self.model_context.get("simulator_config") or {}
        if simulator_config:
            lines.extend(["", "## Model Context", ""])
            lines.append(f"- Simulator config: `{simulator_config.get('config_id', 'unknown')}`")
            lines.append(f"- Config description: {simulator_config.get('description', '')}")
            lines.append(f"- Race score lap-time scale: `{simulator_config.get('race_score_lap_time_scale')}`")
            lines.append(f"- Race noise base SD: `{simulator_config.get('race_noise_base_sd')}`")
            lines.append(f"- Race noise per-lap SD: `{simulator_config.get('race_noise_per_lap_sd')}`")
            lines.append(f"- Qualifying noise SD: `{simulator_config.get('qualifying_noise_sd')}`")
        lines.extend(["", "## Input Audit", ""])
        lines.append(f"- Event input quality: `{self.event_input_audit.get('quality')}`")
        for code in self.event_input_audit.get("risk_codes", []):
            lines.append(f"- Input risk: `{code}`")
        if self.blocker_codes:
            lines.extend(["", "## Formal Blockers", ""])
            for code in self.blocker_codes:
                lines.append(f"- `{code}`")
        if self.warning_codes:
            lines.extend(["", "## Warnings", ""])
            for code in self.warning_codes:
                lines.append(f"- `{code}`")
        return "\n".join(lines).rstrip() + "\n"


class PredictionPacketBuilder:
    """Builds a self-contained audit packet for one race prediction."""

    def __init__(self, pipeline: PredictionPipeline | None = None, reports_root: Path | str = Path("reports")) -> None:
        self.pipeline = pipeline or PredictionPipeline()
        self.reports_root = Path(reports_root)

    def build(
        self,
        event_id: str,
        knowledge_cutoff: str | None = None,
        iterations: int | None = None,
    ) -> PredictionPacket:
        pipeline = self._pipeline_for_iterations(iterations)
        report = pipeline.predict_event(event_id, knowledge_cutoff)
        season = pipeline.data_source.load()
        cutoff_dt = parse_dt(knowledge_cutoff) if knowledge_cutoff else None
        usable_markets = event_market_snapshots(season.markets, event_id, cutoff_dt, market_type="winner")
        after_cutoff_markets = after_cutoff_market_count(season.markets, event_id, cutoff_dt, market_type="winner")
        event_input_audit = audit_event_input(report.event).to_dict()
        model_context = self._model_context(pipeline)
        codex_context = self._codex_context(report)
        codex_context["intake"] = self._codex_intake_context(event_id)
        market_context = self._market_context(report, usable_markets, after_cutoff_markets)
        probability_summary = self._probability_summary(report)
        top_market_edges = tuple(self._top_market_edges(report))
        blockers, warnings = self._readiness_codes(
            event_input_audit,
            codex_context,
            market_context,
            report,
        )
        status = "ready_for_paper_review" if not blockers else "diagnostic_only"
        packet = PredictionPacket(
            event_id=event_id,
            event_name=report.event.name,
            generated_at=utc_now().replace(microsecond=0).isoformat(),
            knowledge_cutoff=knowledge_cutoff,
            iterations=report.iterations,
            status=status,
            formal_edge_ready=False,
            packet_payload_sha256="",
            blocker_codes=tuple(blockers),
            warning_codes=tuple(warnings),
            event_input_audit=event_input_audit,
            market_context=market_context,
            model_context=model_context,
            codex_context=codex_context,
            probability_summary=probability_summary,
            top_market_edges=top_market_edges,
            prediction=report.to_dict(),
        )
        payload_hash = self._payload_sha256(packet.to_dict(include_payload_hash=False))
        return PredictionPacket(
            event_id=packet.event_id,
            event_name=packet.event_name,
            generated_at=packet.generated_at,
            knowledge_cutoff=packet.knowledge_cutoff,
            iterations=packet.iterations,
            status=packet.status,
            formal_edge_ready=False,
            packet_payload_sha256=payload_hash,
            blocker_codes=packet.blocker_codes,
            warning_codes=packet.warning_codes,
            event_input_audit=packet.event_input_audit,
            market_context=packet.market_context,
            model_context=packet.model_context,
            codex_context=packet.codex_context,
            probability_summary=packet.probability_summary,
            top_market_edges=packet.top_market_edges,
            prediction=packet.prediction,
        )

    @staticmethod
    def _model_context(pipeline: PredictionPipeline) -> dict[str, Any]:
        return {
            "pipeline_class": pipeline.__class__.__name__,
            "simulator_config": pipeline.simulator_config.to_dict(),
        }

    def write(
        self,
        event_id: str,
        knowledge_cutoff: str | None = None,
        iterations: int | None = None,
        output_dir: Path | str = Path("reports/prediction_packets"),
    ) -> dict[str, Path]:
        packet = self.build(event_id, knowledge_cutoff=knowledge_cutoff, iterations=iterations)
        directory = Path(output_dir) / safe_name(event_id)
        directory.mkdir(parents=True, exist_ok=True)
        stem = self._stem(event_id, knowledge_cutoff)
        json_path = directory / f"{stem}.prediction_packet.json"
        markdown_path = directory / f"{stem}.prediction_packet.md"
        json_path.write_text(json.dumps(packet.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(packet.to_markdown(), encoding="utf-8")
        return {"json": json_path, "markdown": markdown_path}

    @staticmethod
    def _codex_context(report: PredictionReport) -> dict[str, Any]:
        quality_counts: dict[str, int] = {}
        risk_counts: dict[str, int] = {}
        triangulation_counts: dict[str, int] = {}
        conflict_counts: dict[str, int] = {}
        for row in report.evidence_quality:
            quality_counts[row.quality_status] = quality_counts.get(row.quality_status, 0) + 1
            triangulation_counts[row.triangulation_status] = triangulation_counts.get(row.triangulation_status, 0) + 1
            conflict_counts[row.conflict_status] = conflict_counts.get(row.conflict_status, 0) + 1
            for flag in row.risk_flags:
                risk_counts[flag] = risk_counts.get(flag, 0) + 1
        factor_route_counts: dict[str, int] = {}
        factor_status_counts: dict[str, int] = {}
        model_input_weights = [row.model_input_weight for row in report.evidence_quality]
        for row in report.factor_trace:
            factor_route_counts[row.route] = factor_route_counts.get(row.route, 0) + 1
            factor_status_counts[row.route_status] = factor_status_counts.get(row.route_status, 0) + 1
        return {
            "evidence_count": len(report.evidence),
            "evidence_quality_count": len(report.evidence_quality),
            "evidence_impact_count": len(report.evidence_impact),
            "factor_trace_count": len(report.factor_trace),
            "factor_observed_movement_count": factor_status_counts.get("observed_probability_movement", 0),
            "factor_route_counts": dict(sorted(factor_route_counts.items())),
            "factor_route_status_counts": dict(sorted(factor_status_counts.items())),
            "factor_trace": [
                {
                    "claim_id": row.claim_id,
                    "target_type": row.target_type,
                    "target_id": row.target_id,
                    "claim_type": row.claim_type,
                    "metric": row.metric,
                    "direction": row.direction,
                    "route": row.route,
                    "model_surface": row.model_surface,
                    "route_status": row.route_status,
                    "raw_signed_impact": row.raw_signed_impact,
                    "weighted_input_impact": row.weighted_input_impact,
                    "effective_race_input": row.effective_race_input,
                    "effective_qualifying_input": row.effective_qualifying_input,
                    "signed_input_impact": row.signed_input_impact,
                    "max_win_probability_delta": row.max_win_probability_delta,
                    "affected_outcome_count": row.affected_outcome_count,
                    "quality_status": row.quality_status,
                    "source_status": row.source_status,
                    "triangulation_status": row.triangulation_status,
                    "conflict_status": row.conflict_status,
                    "source_reliability": row.source_reliability,
                    "model_input_weight": row.model_input_weight,
                    "context_multiplier": row.context_multiplier,
                    "context_multiplier_reason": row.context_multiplier_reason,
                    "track_demand_component": row.track_demand_component,
                    "track_demand_value": row.track_demand_value,
                    "track_demand_profile": row.track_demand_profile,
                    "risk_flags": list(row.risk_flags),
                    "route_notes": list(row.route_notes),
                }
                for row in report.factor_trace
            ],
            "weak_evidence_quality_count": sum(
                count for status, count in quality_counts.items()
                if status in {"weak_diagnostic", "review_required"}
            ),
            "strong_evidence_quality_count": quality_counts.get("strong", 0),
            "review_required_count": sum(1 for claim in report.evidence if claim.review_required),
            "quality_status_counts": dict(sorted(quality_counts.items())),
            "triangulation_status_counts": dict(sorted(triangulation_counts.items())),
            "conflict_status_counts": dict(sorted(conflict_counts.items())),
            "conflicting_evidence_count": len(report.evidence_quality) - conflict_counts.get("no_conflict", 0),
            "average_model_input_weight": round(sum(model_input_weights) / len(model_input_weights), 4)
            if model_input_weights
            else None,
            "min_model_input_weight": min(model_input_weights) if model_input_weights else None,
            "single_source_or_seed_count": sum(
                count for status, count in triangulation_counts.items()
                if status in {"single_source", "same_source_repetition", "seed_or_test_only", "unlinked_source"}
            ),
            "quality_risk_counts": dict(sorted(risk_counts.items())),
            "max_evidence_win_delta": max(
                (row.max_win_probability_delta for row in report.evidence_impact),
                key=lambda value: abs(value),
                default=None,
            ),
        }

    @staticmethod
    def _market_context(report: PredictionReport, usable_markets: list[Any], after_cutoff_markets: int) -> dict[str, Any]:
        positive_edges = [
            edge for edge in report.market_edges
            if (
                edge.conservative_edge_after_cost
                if edge.conservative_edge_after_cost is not None
                else edge.edge_after_cost
            ) > 0
        ]
        return {
            "usable_snapshot_count": len(usable_markets),
            "after_cutoff_snapshot_count": after_cutoff_markets,
            "market_edge_count": len(report.market_edges),
            "positive_edge_count": len(positive_edges),
            "market_ids": [market.market_id for market in usable_markets],
            "missing_same_time_market": len(usable_markets) == 0,
        }

    @staticmethod
    def _probability_summary(report: PredictionReport) -> dict[str, Any]:
        top = sorted(report.race_probabilities, key=lambda row: row.win, reverse=True)[:8]
        return {
            "top_win_probabilities": [
                {
                    "driver_id": row.driver_id,
                    "win": round(row.win, 4),
                    "podium": round(row.podium, 4),
                    "expected_points": round(row.expected_points, 3),
                    "average_finish": round(row.average_finish, 3),
                }
                for row in top
            ],
            "probability_mass_top8": round(sum(row.win for row in top), 4),
        }

    @staticmethod
    def _top_market_edges(report: PredictionReport) -> list[dict[str, Any]]:
        def edge_value(edge: Any) -> float:
            value = edge.conservative_edge_after_cost
            return float(value if value is not None else edge.edge_after_cost)

        return [
            {
                "market_id": edge.market_id,
                "outcome_id": edge.outcome_id,
                "model_probability": edge.model_probability,
                "market_probability": edge.market_probability,
                "conservative_edge_after_cost": edge.conservative_edge_after_cost,
                "recommendation": edge.recommendation,
                "risk_flags": list(edge.risk_flags),
            }
            for edge in sorted(report.market_edges, key=edge_value, reverse=True)[:8]
        ]

    @staticmethod
    def _readiness_codes(
        event_input_audit: dict[str, Any],
        codex_context: dict[str, Any],
        market_context: dict[str, Any],
        report: PredictionReport,
    ) -> tuple[list[str], list[str]]:
        blockers: list[str] = []
        warnings: list[str] = []
        if event_input_audit.get("risk_codes"):
            blockers.append("event_input_provenance_required")
        if market_context.get("missing_same_time_market"):
            blockers.append("market_snapshot_required")
        if market_context.get("after_cutoff_snapshot_count", 0):
            warnings.append("after_cutoff_market_snapshots_excluded")
        if codex_context.get("evidence_count", 0) == 0:
            blockers.append("codex_evidence_required")
        if codex_context.get("weak_evidence_quality_count", 0):
            blockers.append("codex_evidence_quality_review_required")
        if codex_context.get("review_required_count", 0):
            warnings.append("codex_claims_require_review")
        if any(
            "diagnostic_conservative_calibration" in edge.risk_flags
            for edge in report.market_edges
        ):
            blockers.append("probability_calibration_diagnostic_only")
        if report.ai_judgement.get("market_snapshot_count", 0) == 0:
            warnings.append("market_gap_comparison_disabled")
        return list(dict.fromkeys(blockers)), list(dict.fromkeys(warnings))

    @staticmethod
    def _payload_sha256(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _pipeline_for_iterations(self, iterations: int | None) -> PredictionPipeline:
        if iterations is None or iterations == self.pipeline.iterations:
            return self.pipeline
        return PredictionPipeline(
            data_source=self.pipeline.data_source,
            evidence_provider=self.pipeline.evidence_provider,
            feature_provider=self.pipeline.feature_provider,
            result_repository=self.pipeline.result_repository,
            official_standings_repository=self.pipeline.official_standings_repository,
            evidence_quality_scorer=self.pipeline.evidence_quality_scorer,
            factor_trace_builder=self.pipeline.factor_trace_builder,
            weather_forecast_provider=self.pipeline.weather_forecast_provider,
            iterations=iterations,
            simulator_config=self.pipeline.simulator_config,
        )

    def _codex_intake_context(self, event_id: str) -> dict[str, Any]:
        candidate_path = self.reports_root / "research_candidates" / f"{safe_name(event_id)}.json"
        preflight_path = self.reports_root / "research_preflight" / f"{safe_name(event_id)}.json"
        candidate = self._read_optional_json(candidate_path)
        preflight = self._read_optional_json(preflight_path)
        return {
            "source_candidate_status": candidate.get("status") or "missing_source_candidate_audit",
            "candidate_count": int(candidate.get("candidate_count") or 0) if candidate else 0,
            "candidate_review_ready_count": int(candidate.get("review_ready_count") or 0) if candidate else 0,
            "candidate_blocked_count": int(candidate.get("blocked_count") or 0) if candidate else 0,
            "candidate_warning_count": int(candidate.get("warning_count") or 0) if candidate else 0,
            "research_preflight_status": preflight.get("status") or "missing_research_preflight",
            "preflight_valid_claim_count": int(preflight.get("valid_claim_count") or 0) if preflight else 0,
            "preflight_blocking_issue_count": int(preflight.get("blocking_issue_count") or 0) if preflight else 0,
            "preflight_warning_count": int(preflight.get("warning_count") or 0) if preflight else 0,
            "preflight_archive_precheck_can_archive": bool(preflight.get("archive_precheck_can_archive")) if preflight else False,
            "preflight_factor_route_counts": preflight.get("factor_route_counts", {}) if preflight else {},
            "source_candidate_report_path": str(candidate_path) if candidate_path.exists() else None,
            "research_preflight_report_path": str(preflight_path) if preflight_path.exists() else None,
        }

    @staticmethod
    def _read_optional_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _stem(event_id: str, knowledge_cutoff: str | None) -> str:
        suffix = "latest" if not knowledge_cutoff else knowledge_cutoff.replace(":", "").replace("-", "").replace("+", "_").replace("T", "T")
        suffix = suffix.replace("\\", "_").replace("/", "_")
        return safe_name(f"{event_id}_{suffix}")


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_signed_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value) * 100:+.1f}%"
    except (TypeError, ValueError):
        return "n/a"
