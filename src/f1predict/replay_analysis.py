"""Diagnostic analysis for chronological replay outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from f1predict.domain import parse_dt, utc_now
from f1predict.intelligence.evidence_workflow import EvidenceCoverageAuditor
from f1predict.pipeline import PredictionPipeline
from f1predict.replay import ReplayCoverageBuilder, ReplayCoverageReport


SEVERITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}


ISSUE_DEFINITIONS = {
    "missing_codex_evidence": {
        "severity": "critical",
        "impact": "The replay cannot test the LLM/Codex information layer if no source-backed claims were available at the cutoff.",
        "recommendation": "Fill each event workspace with source-snapshotted, audited Codex evidence before using replay quality as an edge signal.",
        "blocks_formal_claim": True,
    },
    "missing_source_snapshots": {
        "severity": "critical",
        "impact": "Claims cannot be audited point-in-time without archived source snapshots.",
        "recommendation": "Use snapshot-source before ingest-evidence for each race-week source.",
        "blocks_formal_claim": True,
    },
    "retrospective_source_snapshots": {
        "severity": "high",
        "impact": "Sources were snapshotted after the replay cutoff, so the content may not exactly match what was knowable at prediction time.",
        "recommendation": "For formal replay, collect immutable source snapshots before each prediction cutoff or use an archived source with a verifiable historical capture.",
        "blocks_formal_claim": True,
    },
    "missing_market_snapshot": {
        "severity": "critical",
        "impact": "Market-gap edge and CLV cannot be evaluated without same-time prices for at least one model-supported market.",
        "recommendation": "Store Polymarket orderbook/price snapshots at every prediction cutoff; winner markets are preferred, supported non-winner markets remain diagnostic-only.",
        "blocks_formal_claim": True,
    },
    "market_snapshot_after_cutoff": {
        "severity": "medium",
        "impact": "A market snapshot exists for the event, but it was captured after the replay cutoff and is excluded from edge comparison.",
        "recommendation": "Keep after-cutoff rows excluded from scoring; replace them only if a same-time orderbook/price snapshot is available.",
        "blocks_formal_claim": False,
    },
    "generated_structure_only_event_input": {
        "severity": "high",
        "impact": "Generated event inputs do not expose enough field-level provenance to audit what the model truly knew.",
        "recommendation": "Regenerate event rows with field-level provenance for calendar metadata, results, track profile, weather priors, and visual map inputs.",
        "blocks_formal_claim": True,
    },
    "heuristic_generated_event_profile": {
        "severity": "high",
        "impact": "The event has source-backed calendar/result/geometry/lap-count inputs where available, but at least one simulation-driving profile field still uses heuristics or placeholders.",
        "recommendation": "Replace remaining heuristic generated profile fields with point-in-time weather priors and review any placeholder circuit profiles before formal replay.",
        "blocks_formal_claim": True,
    },
    "missing_processed_features": {
        "severity": "high",
        "impact": "The pace model is relying on seed priors without structured session or form features.",
        "recommendation": "Backfill point-in-time OpenF1/FastF1 feature summaries for every completed replay row.",
        "blocks_formal_claim": True,
    },
    "season_opener_no_prior_form": {
        "severity": "low",
        "impact": "No previous-race FastF1 form exists before the season opener; this is an expected point-in-time feature boundary rather than a data-ingestion failure.",
        "recommendation": "Keep the opener explicit in diagnostics, and add preseason testing or verified race-week practice features when available.",
        "blocks_formal_claim": False,
    },
    "seed_result_overridden_by_fastf1": {
        "severity": "low",
        "impact": "Seed scenario labels differ from FastF1, but the replay actual winner is already taken from the canonical FastF1 result.",
        "recommendation": "Keep seed results scenario-only and retain the FastF1 result path in replay diagnostics.",
        "blocks_formal_claim": False,
    },
    "calendar_result_round_mismatch": {
        "severity": "medium",
        "impact": "Calendar and result sources still disagree after accounting for cancelled events.",
        "recommendation": "Inspect event identity matching and source schedules before trusting the affected replay row.",
        "blocks_formal_claim": False,
    },
    "top_pick_miss": {
        "severity": "medium",
        "impact": "The highest-probability driver did not match the actual winner in this diagnostic replay.",
        "recommendation": "Inspect actual-winner probability/rank, then separate model weakness from missing inputs.",
        "blocks_formal_claim": False,
    },
    "missing_due_prediction": {
        "severity": "critical",
        "impact": "A due event has results but no replayable prediction row.",
        "recommendation": "Create or repair the event input so every due race is replayed chronologically.",
        "blocks_formal_claim": True,
    },
}


@dataclass(frozen=True)
class ReplayEventDiagnostic:
    round_number: int
    racing_sequence_number: int | None
    cancelled_before_count: int
    event_id: str | None
    event_name: str
    date_end: str
    status: str
    prediction_input_source: str | None
    event_input_quality: str | None
    event_input_risk_codes: tuple[str, ...]
    event_input_verified_fields: tuple[str, ...]
    event_input_derived_fields: tuple[str, ...]
    event_input_heuristic_fields: tuple[str, ...]
    event_input_placeholder_fields: tuple[str, ...]
    result_source: str | None
    fastf1_winner: str | None
    top_pick: str | None
    actual_winner: str | None
    hit: bool | None
    top_probability: float | None
    actual_winner_probability: float | None
    actual_winner_rank: int | None
    full_field_driver_count: int
    mean_abs_rank_error: float | None
    mean_abs_points_error: float | None
    podium_overlap_rate: float | None
    points_overlap_rate: float | None
    evidence_count: int
    evidence_impact_count: int
    evidence_quality_count: int
    weak_evidence_quality_count: int
    strong_evidence_quality_count: int
    max_evidence_win_delta: float | None
    source_snapshot_count: int
    retrospective_source_snapshot_count: int
    archive_backed_source_snapshot_count: int
    retrospective_source_details: tuple[dict[str, Any], ...]
    archive_backed_source_details: tuple[dict[str, Any], ...]
    feature_adjustment_count: int
    market_snapshot_count: int
    market_snapshot_after_cutoff_count: int
    market_snapshot_details: tuple[dict[str, Any], ...]
    market_snapshot_after_cutoff_details: tuple[dict[str, Any], ...]
    missing_market_snapshot_detail: dict[str, Any] | None
    market_edge_count: int
    warnings: tuple[str, ...]
    issue_codes: tuple[str, ...]


@dataclass(frozen=True)
class ReplayIssue:
    code: str
    severity: str
    count: int
    affected_events: tuple[str, ...]
    impact: str
    recommendation: str
    blocks_formal_claim: bool


@dataclass(frozen=True)
class ReplayRootCause:
    code: str
    severity: str
    count: int
    affected_events: tuple[str, ...]
    diagnosis: str
    evidence: str
    improvement: str
    blocks_formal_claim: bool


@dataclass(frozen=True)
class ReplayAnalysisReport:
    year: int
    as_of: str
    generated_at: str
    status: str
    replay_coverage: dict[str, Any]
    diagnostic_metrics: dict[str, Any]
    issues: tuple[ReplayIssue, ...]
    root_causes: tuple[ReplayRootCause, ...]
    event_diagnostics: tuple[ReplayEventDiagnostic, ...]
    formal_backtest_ready: bool
    next_actions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "as_of": self.as_of,
            "generated_at": self.generated_at,
            "status": self.status,
            "replay_coverage": self.replay_coverage,
            "diagnostic_metrics": self.diagnostic_metrics,
            "formal_backtest_ready": self.formal_backtest_ready,
            "issues": [issue.__dict__ for issue in self.issues],
            "root_causes": [cause.__dict__ for cause in self.root_causes],
            "event_diagnostics": [row.__dict__ for row in self.event_diagnostics],
            "next_actions": list(self.next_actions),
        }

    def to_markdown(self) -> str:
        lines = [
            f"# F1Predict Replay Diagnostic Analysis ({self.year})",
            "",
            f"- Generated at: `{self.generated_at}`",
            f"- Replay cutoff: `{self.as_of}`",
            f"- Status: **{self.status}**",
            f"- Formal backtest ready: **{self.formal_backtest_ready}**",
            "",
            "## Summary",
            "",
            f"- Calendar events: {self.replay_coverage['calendar_events']}",
            f"- Due events: {self.replay_coverage['due_events']}",
            f"- Replayed events: {self.replay_coverage['replayed_events']}",
            f"- Result-available events: {self.replay_coverage['result_available_events']}",
            f"- Diagnostic top-pick hit rate: {self.diagnostic_metrics['top_pick_hit_rate']}",
            f"- Mean absolute rank error: {self.diagnostic_metrics.get('mean_abs_rank_error')}",
            f"- Mean absolute points error: {self.diagnostic_metrics.get('mean_abs_points_error')}",
            f"- Mean podium overlap rate: {self.diagnostic_metrics.get('mean_podium_overlap_rate')}",
            f"- Mean points-position overlap rate: {self.diagnostic_metrics.get('mean_points_overlap_rate')}",
            f"- Events with Codex evidence: {self.diagnostic_metrics['events_with_evidence']}",
            f"- Events with Codex evidence impact diagnostics: {self.diagnostic_metrics['events_with_evidence_impact']}",
            f"- Events with Codex evidence quality diagnostics: {self.diagnostic_metrics['events_with_evidence_quality']}",
            f"- Events with weak/review-required evidence quality: {self.diagnostic_metrics['events_with_weak_evidence_quality']}",
            f"- Max Codex evidence win delta: {self.diagnostic_metrics['max_evidence_win_delta']}",
            f"- Events with retrospective source snapshots: {self.diagnostic_metrics['events_with_retrospective_source_snapshots']}",
            f"- Events with archive-backed source snapshots: {self.diagnostic_metrics['events_with_archive_backed_source_snapshots']}",
            f"- Events with market snapshots: {self.diagnostic_metrics['events_with_market_snapshots']}",
            f"- Events with after-cutoff market snapshots: {self.diagnostic_metrics['events_with_market_snapshots_after_cutoff']}",
        ]
        input_qualities = self.diagnostic_metrics.get("input_quality_breakdown") or {}
        for quality, bucket in input_qualities.items():
            if isinstance(bucket, dict):
                lines.append(f"- Input quality `{quality}`: {bucket.get('events', 0)} scored events")
        lines.extend(
            [
                "",
                "This report is diagnostic only. It is useful for finding failure modes, but it is not a matched edge backtest until the blocking issues below are resolved.",
                "",
                "## Core Issues",
                "",
            ]
        )
        if self.issues:
            for issue in self.issues:
                events = ", ".join(issue.affected_events[:8])
                if len(issue.affected_events) > 8:
                    events += f", +{len(issue.affected_events) - 8} more"
                lines.extend(
                    [
                        f"### {issue.code} ({issue.severity}, {issue.count})",
                        "",
                        f"- Impact: {issue.impact}",
                        f"- Recommendation: {issue.recommendation}",
                        f"- Blocks formal claim: {issue.blocks_formal_claim}",
                        f"- Affected events: {events}",
                        "",
                    ]
                )
        else:
            lines.append("No issues detected by the current diagnostic rules.")
            lines.append("")

        if self.root_causes:
            lines.extend(["## Root Cause Diagnosis", ""])
            for cause in self.root_causes:
                events = ", ".join(cause.affected_events[:8])
                if len(cause.affected_events) > 8:
                    events += f", +{len(cause.affected_events) - 8} more"
                lines.extend(
                    [
                        f"### {cause.code} ({cause.severity}, {cause.count})",
                        "",
                        f"- Diagnosis: {cause.diagnosis}",
                        f"- Evidence: {cause.evidence}",
                        f"- Improvement: {cause.improvement}",
                        f"- Blocks formal claim: {cause.blocks_formal_claim}",
                        f"- Affected events: {events}",
                        "",
                    ]
                )

        source_rows = [
            row for row in self.event_diagnostics
            if row.retrospective_source_details or row.archive_backed_source_details
        ]
        if source_rows:
            lines.extend(["## Source Snapshot Audit", ""])
            lines.append("| Event | Status | Source | Published | Captured | Archive | URL |")
            lines.append("|---|---|---|---|---|---|---|")
            for row in source_rows:
                for detail in row.retrospective_source_details:
                    lines.append(self._source_detail_markdown(row.event_name, detail))
                for detail in row.archive_backed_source_details:
                    lines.append(self._source_detail_markdown(row.event_name, detail))
            lines.append("")

        market_rows = [
            row for row in self.event_diagnostics
            if row.missing_market_snapshot_detail or row.market_snapshot_after_cutoff_details or row.market_snapshot_details
        ]
        if market_rows:
            lines.extend(["## Market Snapshot Audit", ""])
            lines.append("| Event | Status | Market | Cutoff | Captured | Top Prices |")
            lines.append("|---|---|---|---|---|---|")
            for row in market_rows:
                if row.missing_market_snapshot_detail:
                    lines.append(self._missing_market_detail_markdown(row.event_name, row.missing_market_snapshot_detail))
                for detail in row.market_snapshot_after_cutoff_details:
                    lines.append(self._market_detail_markdown(row.event_name, detail))
                for detail in row.market_snapshot_details:
                    lines.append(self._market_detail_markdown(row.event_name, detail))
            lines.append("")

        lines.extend(["## Next Actions", ""])
        lines.extend(f"1. {action}" for action in self.next_actions)
        lines.extend(["", "## Event Diagnostics", ""])
        lines.append(
            "| Round | Race Seq | Event | Input | Quality | Result Source | Pick | Actual | Hit | Actual P | Actual Rank | Rank MAE | Points MAE | Top10 | Issues |"
        )
        lines.append("|---:|---:|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---|")
        for row in self.event_diagnostics:
            hit = "" if row.hit is None else "yes" if row.hit else "no"
            actual_probability = "" if row.actual_winner_probability is None else f"{row.actual_winner_probability:.3f}"
            actual_rank = "" if row.actual_winner_rank is None else str(row.actual_winner_rank)
            rank_mae = "" if row.mean_abs_rank_error is None else f"{row.mean_abs_rank_error:.2f}"
            points_mae = "" if row.mean_abs_points_error is None else f"{row.mean_abs_points_error:.2f}"
            top10 = "" if row.points_overlap_rate is None else f"{row.points_overlap_rate:.2f}"
            issues = ", ".join(row.issue_codes)
            race_sequence = "" if row.racing_sequence_number is None else str(row.racing_sequence_number)
            lines.append(
                "| "
                f"{row.round_number} | {race_sequence} | {row.event_name} | {row.prediction_input_source or ''} | "
                f"{row.event_input_quality or ''} | {row.result_source or ''} | {row.top_pick or ''} | "
                f"{row.actual_winner or ''} | {hit} | "
                f"{actual_probability} | {actual_rank} | {rank_mae} | {points_mae} | {top10} | {issues} |"
            )
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _source_detail_markdown(event_name: str, detail: dict[str, Any]) -> str:
        title = str(detail.get("title") or detail.get("source") or "")
        if len(title) > 72:
            title = title[:69] + "..."
        url = str(detail.get("url") or "")
        link = f"[source]({url})" if url else ""
        archive = detail.get("archived_at") or detail.get("archive_status") or ""
        return (
            f"| {event_name} | {detail.get('archive_status') or ''} | {title} | "
            f"{detail.get('published_at') or ''} | {detail.get('captured_at') or ''} | "
            f"{archive} | {link} |"
        )

    @staticmethod
    def _missing_market_detail_markdown(event_name: str, detail: dict[str, Any]) -> str:
        return (
            f"| {event_name} | {detail.get('status') or ''} | {detail.get('market_type') or ''} | "
            f"{detail.get('required_at_or_before') or ''} |  | after-cutoff snapshots: {detail.get('after_cutoff_snapshot_count', 0)} |"
        )

    @staticmethod
    def _market_detail_markdown(event_name: str, detail: dict[str, Any]) -> str:
        prices = detail.get("top_prices") if isinstance(detail.get("top_prices"), list) else []
        top_prices = ", ".join(
            f"{item.get('outcome_id')}={float(item.get('price', 0.0)):.2f}"
            for item in prices[:3]
            if isinstance(item, dict)
        )
        return (
            f"| {event_name} | {detail.get('status') or ''} | {detail.get('market_id') or ''} | "
            f"{detail.get('knowledge_cutoff') or ''} | {detail.get('captured_at') or ''} | {top_prices} |"
        )


class ReplayAnalysisBuilder:
    """Builds diagnostic failure analysis over chronological replay rows."""

    def __init__(
        self,
        pipeline: PredictionPipeline | None = None,
        replay_builder: ReplayCoverageBuilder | None = None,
        evidence_auditor: EvidenceCoverageAuditor | None = None,
    ) -> None:
        self.pipeline = pipeline or PredictionPipeline(iterations=1200)
        self.replay_builder = replay_builder or ReplayCoverageBuilder(self.pipeline)
        self.evidence_auditor = evidence_auditor or EvidenceCoverageAuditor(
            self.pipeline.data_source,
            self.pipeline.evidence_provider,
        )

    def build(self, year: int, as_of: str) -> ReplayAnalysisReport:
        replay = self.replay_builder.build(year, as_of)
        evidence_coverage = self.evidence_auditor.build(as_of=as_of)
        source_snapshots_by_event = {
            row.event_id: row.source_snapshot_count for row in evidence_coverage.rows
        }
        retrospective_snapshots_by_event = {
            row.event_id: row.retrospective_source_snapshot_count for row in evidence_coverage.rows
        }
        archive_backed_snapshots_by_event = {
            row.event_id: row.archive_backed_source_snapshot_count for row in evidence_coverage.rows
        }
        retrospective_details_by_event = {
            row.event_id: row.retrospective_source_details for row in evidence_coverage.rows
        }
        archive_backed_details_by_event = {
            row.event_id: row.archive_backed_source_details for row in evidence_coverage.rows
        }
        market_details_by_event = {
            row.event_id: row.market_snapshot_details for row in evidence_coverage.rows
        }
        market_after_cutoff_details_by_event = {
            row.event_id: row.market_snapshot_after_cutoff_details for row in evidence_coverage.rows
        }
        missing_market_details_by_event = {
            row.event_id: row.missing_market_snapshot_detail for row in evidence_coverage.rows
        }
        season = self.pipeline.data_source.load()
        events_by_id = {event.event_id: event for event in season.events}

        event_rows: list[ReplayEventDiagnostic] = []
        for row in replay.rows:
            event = events_by_id.get(row.seed_event_id or "")
            prediction = None
            if row.status == "replayed" and row.seed_event_id and event is not None:
                cutoff = f"{event.date}T00:00:00+00:00"
                prediction = self.pipeline.predict_event(row.seed_event_id, cutoff)
            prediction_payload = prediction.to_dict() if prediction else None
            top_probability, actual_probability, actual_rank = self._prediction_metrics(
                prediction_payload,
                row.top_pick,
                row.actual_winner,
            )
            evidence_impact_count, max_evidence_delta = self._evidence_impact_metrics(prediction_payload)
            (
                evidence_quality_count,
                weak_evidence_quality_count,
                strong_evidence_quality_count,
            ) = self._evidence_quality_metrics(prediction_payload)
            source_snapshot_count = source_snapshots_by_event.get(row.seed_event_id or "", 0)
            retrospective_source_snapshot_count = retrospective_snapshots_by_event.get(row.seed_event_id or "", 0)
            archive_backed_source_snapshot_count = archive_backed_snapshots_by_event.get(row.seed_event_id or "", 0)
            retrospective_source_details = retrospective_details_by_event.get(row.seed_event_id or "", ())
            archive_backed_source_details = archive_backed_details_by_event.get(row.seed_event_id or "", ())
            market_snapshot_details = market_details_by_event.get(row.seed_event_id or "", ())
            market_snapshot_after_cutoff_details = market_after_cutoff_details_by_event.get(row.seed_event_id or "", ())
            missing_market_snapshot_detail = missing_market_details_by_event.get(row.seed_event_id or "") or None
            issue_codes = self._issue_codes(
                row.__dict__,
                source_snapshot_count,
                retrospective_source_snapshot_count,
            )
            event_rows.append(
                ReplayEventDiagnostic(
                    round_number=row.round_number,
                    racing_sequence_number=row.racing_sequence_number,
                    cancelled_before_count=row.cancelled_before_count,
                    event_id=row.seed_event_id,
                    event_name=row.event_name,
                    date_end=row.date_end,
                    status=row.status,
                    prediction_input_source=row.prediction_input_source,
                    event_input_quality=row.event_input_quality,
                    event_input_risk_codes=row.event_input_risk_codes,
                    event_input_verified_fields=row.event_input_verified_fields,
                    event_input_derived_fields=row.event_input_derived_fields,
                    event_input_heuristic_fields=row.event_input_heuristic_fields,
                    event_input_placeholder_fields=row.event_input_placeholder_fields,
                    result_source=row.result_source,
                    fastf1_winner=row.fastf1_winner,
                    top_pick=row.top_pick,
                    actual_winner=row.actual_winner,
                    hit=row.hit,
                    top_probability=top_probability,
                    actual_winner_probability=actual_probability,
                    actual_winner_rank=actual_rank,
                    full_field_driver_count=row.full_field_driver_count,
                    mean_abs_rank_error=row.mean_abs_rank_error,
                    mean_abs_points_error=row.mean_abs_points_error,
                    podium_overlap_rate=row.podium_overlap_rate,
                    points_overlap_rate=row.points_overlap_rate,
                    evidence_count=row.evidence_count,
                    evidence_impact_count=evidence_impact_count,
                    evidence_quality_count=evidence_quality_count,
                    weak_evidence_quality_count=weak_evidence_quality_count,
                    strong_evidence_quality_count=strong_evidence_quality_count,
                    max_evidence_win_delta=max_evidence_delta,
                    source_snapshot_count=source_snapshot_count,
                    retrospective_source_snapshot_count=retrospective_source_snapshot_count,
                    archive_backed_source_snapshot_count=archive_backed_source_snapshot_count,
                    retrospective_source_details=tuple(retrospective_source_details),
                    archive_backed_source_details=tuple(archive_backed_source_details),
                    feature_adjustment_count=row.feature_adjustment_count,
                    market_snapshot_count=row.market_snapshot_count,
                    market_snapshot_after_cutoff_count=row.market_snapshot_after_cutoff_count,
                    market_snapshot_details=tuple(market_snapshot_details),
                    market_snapshot_after_cutoff_details=tuple(market_snapshot_after_cutoff_details),
                    missing_market_snapshot_detail=missing_market_snapshot_detail,
                    market_edge_count=row.market_edge_count,
                    warnings=row.warnings,
                    issue_codes=issue_codes,
                )
            )

        issues = self._aggregate_issues(event_rows)
        metrics = self._diagnostic_metrics(event_rows, evidence_coverage.to_dict())
        root_causes = self._root_causes(event_rows, issues, metrics)
        next_actions = self._next_actions(issues)
        formal_ready = not any(issue.blocks_formal_claim for issue in issues)
        return ReplayAnalysisReport(
            year=year,
            as_of=as_of,
            generated_at=utc_now().isoformat(),
            status="diagnostic_only",
            replay_coverage=self._coverage_summary(replay),
            diagnostic_metrics=metrics,
            issues=issues,
            root_causes=root_causes,
            event_diagnostics=tuple(event_rows),
            formal_backtest_ready=formal_ready,
            next_actions=next_actions,
        )

    def write(
        self,
        year: int,
        as_of: str,
        output_dir: Path | str = Path("reports/replay_analysis"),
    ) -> dict[str, Path]:
        report = self.build(year, as_of)
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"{year}_asof_{self._stem_time(as_of)}"
        json_path = directory / f"{stem}.analysis.json"
        markdown_path = directory / f"{stem}.analysis.md"
        json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(report.to_markdown(), encoding="utf-8")
        return {"json": json_path, "markdown": markdown_path}

    @staticmethod
    def _prediction_metrics(
        prediction: dict[str, Any] | None,
        top_pick: str | None,
        actual_winner: str | None,
    ) -> tuple[float | None, float | None, int | None]:
        if not prediction:
            return None, None, None
        probabilities = prediction.get("race_probabilities", [])
        if not isinstance(probabilities, list):
            return None, None, None
        top_probability = None
        actual_probability = None
        actual_rank = None
        for index, item in enumerate(probabilities, start=1):
            if not isinstance(item, dict):
                continue
            driver_id = str(item.get("driver_id"))
            if top_pick and driver_id == top_pick:
                top_probability = round(float(item.get("win", 0.0)), 4)
            if actual_winner and driver_id == actual_winner:
                actual_probability = round(float(item.get("win", 0.0)), 4)
                actual_rank = index
        return top_probability, actual_probability, actual_rank

    @staticmethod
    def _evidence_impact_metrics(payload: dict[str, Any] | None) -> tuple[int, float | None]:
        if payload is None:
            return 0, None
        rows = payload.get("evidence_impact") or []
        if not isinstance(rows, list):
            return 0, None
        deltas = [
            float(row.get("max_win_probability_delta", 0.0))
            for row in rows
            if isinstance(row, dict)
        ]
        if not deltas:
            return len(rows), None
        max_delta = max(deltas, key=abs)
        return len(rows), round(max_delta, 4)

    @staticmethod
    def _evidence_quality_metrics(payload: dict[str, Any] | None) -> tuple[int, int, int]:
        if payload is None:
            return 0, 0, 0
        rows = payload.get("evidence_quality") or []
        if not isinstance(rows, list):
            return 0, 0, 0
        weak = sum(
            1 for row in rows
            if isinstance(row, dict) and row.get("quality_status") in {"weak_diagnostic", "review_required"}
        )
        strong = sum(1 for row in rows if isinstance(row, dict) and row.get("quality_status") == "strong")
        return len(rows), weak, strong

    @staticmethod
    def _issue_codes(
        row: dict[str, Any],
        source_snapshot_count: int,
        retrospective_source_snapshot_count: int,
    ) -> tuple[str, ...]:
        codes: set[str] = set()
        status = str(row.get("status") or "")
        if status not in {"replayed", "result_available_no_prediction", "missing_due_data"}:
            return ()
        warnings = tuple(str(item) for item in row.get("warnings", ()))
        if status in {"result_available_no_prediction", "missing_due_data"}:
            codes.add("missing_due_prediction")
        if row.get("hit") is False:
            codes.add("top_pick_miss")
        if int(row.get("evidence_count") or 0) == 0 and status == "replayed":
            codes.add("missing_codex_evidence")
        if source_snapshot_count == 0 and status == "replayed":
            codes.add("missing_source_snapshots")
        if retrospective_source_snapshot_count > 0 and status == "replayed":
            codes.add("retrospective_source_snapshots")
        if status == "replayed" and int(row.get("round_number") or 0) == 1:
            codes.add("season_opener_no_prior_form")
        elif int(row.get("feature_adjustment_count") or 0) == 0 and status == "replayed":
            codes.add("missing_processed_features")
        if int(row.get("market_snapshot_count") or 0) == 0 and status == "replayed":
            codes.add("missing_market_snapshot")
        if int(row.get("market_snapshot_after_cutoff_count") or 0) > 0 and status == "replayed":
            codes.add("market_snapshot_after_cutoff")
        risk_codes = tuple(str(item) for item in row.get("event_input_risk_codes", ()))
        for risk_code in risk_codes:
            if risk_code in ISSUE_DEFINITIONS:
                codes.add(risk_code)
        if (
            str(row.get("prediction_input_source") or "") == "openf1_calendar_generated"
            and not row.get("event_input_quality")
        ):
            codes.add("generated_structure_only_event_input")
        for warning in warnings:
            if warning == "seed_result_overridden_by_fastf1":
                codes.add("seed_result_overridden_by_fastf1")
            if warning.startswith("round_mismatch_"):
                codes.add("calendar_result_round_mismatch")
            if warning == "no_codex_evidence_at_cutoff":
                codes.add("missing_codex_evidence")
            if warning == "no_market_snapshot_at_cutoff":
                codes.add("missing_market_snapshot")
            if warning == "market_snapshot_after_cutoff":
                codes.add("market_snapshot_after_cutoff")
            if warning in {"generated_structure_only_event_input", "heuristic_generated_event_profile"}:
                codes.add(warning)
        return tuple(sorted(codes, key=lambda code: (SEVERITY_ORDER[ISSUE_DEFINITIONS[code]["severity"]], code)))

    @staticmethod
    def _aggregate_issues(rows: list[ReplayEventDiagnostic]) -> tuple[ReplayIssue, ...]:
        affected: dict[str, list[str]] = {}
        for row in rows:
            label = row.event_id or row.event_name
            for code in row.issue_codes:
                affected.setdefault(code, []).append(label)
        issues: list[ReplayIssue] = []
        for code, events in affected.items():
            definition = ISSUE_DEFINITIONS[code]
            unique_events = tuple(dict.fromkeys(events))
            issues.append(
                ReplayIssue(
                    code=code,
                    severity=str(definition["severity"]),
                    count=len(unique_events),
                    affected_events=unique_events,
                    impact=str(definition["impact"]),
                    recommendation=str(definition["recommendation"]),
                    blocks_formal_claim=bool(definition["blocks_formal_claim"]),
                )
            )
        issues.sort(key=lambda issue: (SEVERITY_ORDER[issue.severity], -issue.count, issue.code))
        return tuple(issues)

    @staticmethod
    def _root_causes(
        rows: list[ReplayEventDiagnostic],
        issues: tuple[ReplayIssue, ...],
        metrics: dict[str, Any],
    ) -> tuple[ReplayRootCause, ...]:
        issue_by_code = {issue.code: issue for issue in issues}
        scored = [row for row in rows if row.hit is not None]

        root_causes: list[ReplayRootCause] = []

        market_rows, market_events = ReplayAnalysisBuilder._rows_for_issue_codes(
            rows,
            {"missing_market_snapshot", "market_snapshot_after_cutoff"},
        )
        if market_events:
            missing = issue_by_code.get("missing_market_snapshot")
            late = issue_by_code.get("market_snapshot_after_cutoff")
            valid_count = sum(1 for row in scored if row.market_snapshot_count > 0)
            root_causes.append(
                ReplayRootCause(
                    code="market_data_gap",
                    severity="critical",
                    count=len(market_events),
                    affected_events=market_events,
                    diagnosis=(
                        "The replay can score race outcomes, but it cannot validate market edge or CLV "
                        "without same-time prices for model-supported markets across most completed races."
                    ),
                    evidence=(
                        f"{valid_count}/{len(scored)} scored replay rows have cutoff-valid supported-market snapshots; "
                        f"{missing.count if missing else 0} are missing cutoff-valid rows and "
                        f"{late.count if late else 0} have after-cutoff rows excluded."
                    ),
                    improvement=(
                        "Archive live Polymarket order-book snapshots at each future cutoff, and import "
                        "reviewed historical CLOB definitions plus price history for completed 2026 races; "
                        "use winner markets for formal winner-edge claims and supported non-winner markets for diagnostic gaps."
                    ),
                    blocks_formal_claim=True,
                )
            )

        source_rows, source_events = ReplayAnalysisBuilder._rows_for_issue_codes(
            rows,
            {"missing_source_snapshots", "retrospective_source_snapshots"},
        )
        if source_events:
            missing = issue_by_code.get("missing_source_snapshots")
            retro = issue_by_code.get("retrospective_source_snapshots")
            archive_backed = sum(1 for row in scored if row.archive_backed_source_snapshot_count > 0)
            root_causes.append(
                ReplayRootCause(
                    code="source_time_integrity_gap",
                    severity="high" if missing is None else "critical",
                    count=len(source_events),
                    affected_events=source_events,
                    diagnosis=(
                        "The Codex evidence layer is populated, but some evidence was snapshotted "
                        "after the prediction cutoff without cutoff-valid archive proof."
                    ),
                    evidence=(
                        f"{retro.count if retro else 0} replay rows still rely on retrospective "
                        f"source snapshots; {archive_backed} scored rows have archive-backed source proof."
                    ),
                    improvement=(
                        "Replace retrospective rows with pre-cutoff snapshots or verified Wayback "
                        "captures, and keep source-audit gating mandatory before ingesting claims."
                    ),
                    blocks_formal_claim=True,
                )
            )

        missed_rows, missed_events = ReplayAnalysisBuilder._rows_for_issue_codes(rows, {"top_pick_miss"})
        if missed_events:
            top3_count = sum(
                1 for row in scored
                if row.actual_winner_rank is not None and row.actual_winner_rank <= 3
            )
            root_causes.append(
                ReplayRootCause(
                    code="model_ranking_calibration_gap",
                    severity="medium",
                    count=len(missed_events),
                    affected_events=missed_events,
                    diagnosis=(
                        "The strategy-aware race-time simulator often keeps the true winner in contention, "
                        "but its top-pick calibration is not strong enough for an edge claim."
                    ),
                    evidence=(
                        f"Diagnostic top-pick hit rate is {metrics.get('top_pick_hit_rate')}; "
                        f"median actual-winner rank is {metrics.get('median_actual_winner_rank')}; "
                        f"{top3_count}/{len(scored)} actual winners were ranked in the top 3."
                    ),
                    improvement=(
                        "Add stronger qualifying/practice/session features, calibrate the tyre/weather/strategy "
                        "parameters against historical races, and track probability calibration before comparing against markets."
                    ),
                    blocks_formal_claim=False,
                )
            )

        opener_rows, opener_events = ReplayAnalysisBuilder._rows_for_issue_codes(
            rows,
            {"season_opener_no_prior_form"},
        )
        if opener_events:
            root_causes.append(
                ReplayRootCause(
                    code="feature_horizon_boundary",
                    severity="low",
                    count=len(opener_events),
                    affected_events=opener_events,
                    diagnosis=(
                        "The first race has no same-season prior-race FastF1 form by design; this is a "
                        "point-in-time feature horizon boundary rather than a data failure."
                    ),
                    evidence=f"{len(opener_rows)} replay row has no previous-race form features.",
                    improvement=(
                        "Add preseason testing, prior-season carryover, and race-week practice features "
                        "so the opener is not driven mainly by seed priors."
                    ),
                    blocks_formal_claim=False,
                )
            )

        label_rows, label_events = ReplayAnalysisBuilder._rows_for_issue_codes(
            rows,
            {"seed_result_overridden_by_fastf1"},
        )
        if label_events:
            root_causes.append(
                ReplayRootCause(
                    code="seed_label_provenance_gap",
                    severity="low",
                    count=len(label_events),
                    affected_events=label_events,
                    diagnosis=(
                        "Some seed scenario labels differ from canonical FastF1 results, but replay "
                        "already uses FastF1 as the actual-result authority."
                    ),
                    evidence=f"{len(label_events)} seed rows required canonical FastF1 result override.",
                    improvement=(
                        "Keep seed labels scenario-only, refresh seed fixtures from canonical result "
                        "snapshots, and preserve the override warning as provenance."
                    ),
                    blocks_formal_claim=False,
                )
            )

        root_causes.sort(key=lambda cause: (SEVERITY_ORDER[cause.severity], -cause.count, cause.code))
        return tuple(root_causes)

    @staticmethod
    def _rows_for_issue_codes(
        rows: list[ReplayEventDiagnostic],
        codes: set[str],
    ) -> tuple[list[ReplayEventDiagnostic], tuple[str, ...]]:
        selected = [row for row in rows if any(code in row.issue_codes for code in codes)]
        events = tuple(dict.fromkeys(row.event_id or row.event_name for row in selected))
        return selected, events

    @staticmethod
    def _diagnostic_metrics(rows: list[ReplayEventDiagnostic], evidence_coverage: dict[str, Any]) -> dict[str, Any]:
        scored = [row for row in rows if row.hit is not None]
        hits = sum(1 for row in scored if row.hit)
        hit_rate = hits / len(scored) if scored else None
        input_sources: dict[str, dict[str, Any]] = {}
        input_qualities: dict[str, dict[str, Any]] = {}
        for row in scored:
            source = row.prediction_input_source or "unknown"
            bucket = input_sources.setdefault(source, {"events": 0, "hits": 0, "hit_rate": None})
            bucket["events"] += 1
            bucket["hits"] += 1 if row.hit else 0
            quality = row.event_input_quality or "unknown"
            quality_bucket = input_qualities.setdefault(quality, {"events": 0, "hits": 0, "hit_rate": None})
            quality_bucket["events"] += 1
            quality_bucket["hits"] += 1 if row.hit else 0
        for bucket in input_sources.values():
            bucket["hit_rate"] = round(bucket["hits"] / bucket["events"], 4) if bucket["events"] else None
        for bucket in input_qualities.values():
            bucket["hit_rate"] = round(bucket["hits"] / bucket["events"], 4) if bucket["events"] else None
        actual_ranks = [row.actual_winner_rank for row in scored if row.actual_winner_rank is not None]
        evidence_deltas = [
            row.max_evidence_win_delta
            for row in scored
            if row.max_evidence_win_delta is not None
        ]
        median_actual_rank = None
        if actual_ranks:
            ordered = sorted(actual_ranks)
            median_actual_rank = ordered[len(ordered) // 2]
        max_evidence_delta = None
        if evidence_deltas:
            max_evidence_delta = round(max(evidence_deltas, key=abs), 4)
        rank_errors = [row.mean_abs_rank_error for row in scored if row.mean_abs_rank_error is not None]
        points_errors = [row.mean_abs_points_error for row in scored if row.mean_abs_points_error is not None]
        podium_overlaps = [row.podium_overlap_rate for row in scored if row.podium_overlap_rate is not None]
        points_overlaps = [row.points_overlap_rate for row in scored if row.points_overlap_rate is not None]
        return {
            "diagnostic_scored_events": len(scored),
            "top_pick_hits": hits,
            "top_pick_misses": len(scored) - hits,
            "top_pick_hit_rate": None if hit_rate is None else round(hit_rate, 4),
            "median_actual_winner_rank": median_actual_rank,
            "mean_abs_rank_error": round(sum(rank_errors) / len(rank_errors), 4) if rank_errors else None,
            "mean_abs_points_error": round(sum(points_errors) / len(points_errors), 4) if points_errors else None,
            "mean_podium_overlap_rate": round(sum(podium_overlaps) / len(podium_overlaps), 4)
            if podium_overlaps
            else None,
            "mean_points_overlap_rate": round(sum(points_overlaps) / len(points_overlaps), 4)
            if points_overlaps
            else None,
            "events_with_evidence_impact": sum(1 for row in scored if row.evidence_impact_count > 0),
            "events_with_evidence_quality": sum(1 for row in scored if row.evidence_quality_count > 0),
            "events_with_weak_evidence_quality": sum(1 for row in scored if row.weak_evidence_quality_count > 0),
            "events_with_strong_evidence_quality": sum(1 for row in scored if row.strong_evidence_quality_count > 0),
            "max_evidence_win_delta": max_evidence_delta,
            "input_source_breakdown": input_sources,
            "input_quality_breakdown": input_qualities,
            "events_with_evidence": evidence_coverage.get("events_with_evidence", 0),
            "events_with_source_snapshots": evidence_coverage.get("events_with_source_snapshots", 0),
            "events_with_retrospective_source_snapshots": evidence_coverage.get(
                "events_with_retrospective_source_snapshots", 0
            ),
            "events_with_archive_backed_source_snapshots": evidence_coverage.get(
                "events_with_archive_backed_source_snapshots", 0
            ),
            "events_with_market_snapshots": evidence_coverage.get("events_with_market_snapshots", 0),
            "events_with_market_snapshots_after_cutoff": evidence_coverage.get(
                "events_with_market_snapshots_after_cutoff", 0
            ),
            "events_needing_codex_research": evidence_coverage.get("events_needing_codex_research", 0),
        }

    @staticmethod
    def _coverage_summary(replay: ReplayCoverageReport) -> dict[str, Any]:
        return {
            "calendar_events": replay.calendar_events,
            "cancelled_events": replay.cancelled_events,
            "due_events": replay.due_events,
            "replayed_events": replay.replayed_events,
            "result_available_events": replay.result_available_events,
            "missing_due_events": replay.missing_due_events,
        }

    @staticmethod
    def _next_actions(issues: tuple[ReplayIssue, ...]) -> tuple[str, ...]:
        actions: list[str] = []
        for issue in issues:
            if issue.blocks_formal_claim and issue.recommendation not in actions:
                actions.append(issue.recommendation)
        if not actions:
            actions.append("Run a matched replay with frozen configs, market snapshots, and source-backed evidence.")
        return tuple(actions[:5])

    @staticmethod
    def _stem_time(value: str) -> str:
        parsed = parse_dt(value)
        if parsed is None:
            return value.replace(":", "").replace("+", "_").replace("-", "")
        return parsed.isoformat().replace(":", "").replace("+", "_").replace("-", "")
