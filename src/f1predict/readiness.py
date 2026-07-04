"""Formal replay readiness and intake manifest."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from f1predict.domain import utc_now
from f1predict.pipeline import PredictionPipeline
from f1predict.replay_analysis import ReplayAnalysisBuilder, ReplayAnalysisReport, ReplayEventDiagnostic


@dataclass(frozen=True)
class FormalReadinessAction:
    action_id: str
    event_id: str
    event_name: str
    category: str
    severity: str
    blocks_formal_claim: bool
    summary: str
    required_by: str | None
    details: dict[str, Any]
    command_templates: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "event_id": self.event_id,
            "event_name": self.event_name,
            "category": self.category,
            "severity": self.severity,
            "blocks_formal_claim": self.blocks_formal_claim,
            "summary": self.summary,
            "required_by": self.required_by,
            "details": self.details,
            "command_templates": list(self.command_templates),
        }


@dataclass(frozen=True)
class FormalReadinessEvent:
    event_id: str
    event_name: str
    date_end: str
    status: str
    blocking_action_count: int
    warning_action_count: int
    actions: tuple[FormalReadinessAction, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_name": self.event_name,
            "date_end": self.date_end,
            "status": self.status,
            "blocking_action_count": self.blocking_action_count,
            "warning_action_count": self.warning_action_count,
            "actions": [action.to_dict() for action in self.actions],
        }


@dataclass(frozen=True)
class FormalReadinessWorkstream:
    workstream_id: str
    title: str
    priority: int
    category: str
    severity: str
    blocks_formal_claim: bool
    blocking_action_count: int
    warning_action_count: int
    event_ids: tuple[str, ...]
    success_criteria: tuple[str, ...]
    command_templates: tuple[str, ...]
    actions: tuple[FormalReadinessAction, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "workstream_id": self.workstream_id,
            "title": self.title,
            "priority": self.priority,
            "category": self.category,
            "severity": self.severity,
            "blocks_formal_claim": self.blocks_formal_claim,
            "blocking_action_count": self.blocking_action_count,
            "warning_action_count": self.warning_action_count,
            "event_ids": list(self.event_ids),
            "success_criteria": list(self.success_criteria),
            "command_templates": list(self.command_templates),
            "actions": [action.to_dict() for action in self.actions],
        }


@dataclass(frozen=True)
class FormalReadinessReport:
    year: int
    as_of: str
    generated_at: str
    status: str
    formal_backtest_ready: bool
    blocking_action_count: int
    warning_action_count: int
    action_category_counts: dict[str, int]
    workstreams: tuple[FormalReadinessWorkstream, ...]
    events: tuple[FormalReadinessEvent, ...]
    next_actions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "as_of": self.as_of,
            "generated_at": self.generated_at,
            "status": self.status,
            "formal_backtest_ready": self.formal_backtest_ready,
            "blocking_action_count": self.blocking_action_count,
            "warning_action_count": self.warning_action_count,
            "action_category_counts": self.action_category_counts,
            "workstreams": [workstream.to_dict() for workstream in self.workstreams],
            "events": [event.to_dict() for event in self.events],
            "next_actions": list(self.next_actions),
        }

    def to_markdown(self) -> str:
        lines = [
            f"# F1Predict Formal Replay Readiness ({self.year})",
            "",
            f"- Generated at: `{self.generated_at}`",
            f"- Replay cutoff: `{self.as_of}`",
            f"- Status: **{self.status}**",
            f"- Formal backtest ready: **{self.formal_backtest_ready}**",
            f"- Blocking actions: {self.blocking_action_count}",
            f"- Warning actions: {self.warning_action_count}",
            "",
            "## Action Counts",
            "",
        ]
        for category, count in sorted(self.action_category_counts.items()):
            lines.append(f"- {category}: {count}")
        if self.workstreams:
            lines.extend(["", "## Workstreams", ""])
            for workstream in self.workstreams:
                event_list = ", ".join(f"`{event_id}`" for event_id in workstream.event_ids)
                lines.extend(
                    [
                        f"### {workstream.priority}. {workstream.title} (`{workstream.category}`)",
                        "",
                        f"- Severity: {workstream.severity}",
                        f"- Blocks formal claim: {workstream.blocks_formal_claim}",
                        f"- Blocking actions: {workstream.blocking_action_count}",
                        f"- Warning actions: {workstream.warning_action_count}",
                        f"- Events: {event_list or 'n/a'}",
                    ]
                )
                if workstream.success_criteria:
                    lines.append("- Success criteria:")
                    for criterion in workstream.success_criteria:
                        lines.append(f"  - {criterion}")
                if workstream.command_templates:
                    lines.append("- Command templates:")
                    for command in workstream.command_templates:
                        lines.append(f"  - `{command}`")
                lines.append("")
        lines.extend(["", "## Intake Queue", ""])
        for event in self.events:
            if not event.actions:
                continue
            lines.extend(
                [
                    f"### {event.event_name} (`{event.event_id}`)",
                    "",
                    f"- Event status: {event.status}",
                    f"- Blocking actions: {event.blocking_action_count}",
                    f"- Warning actions: {event.warning_action_count}",
                    "",
                ]
            )
            for action in event.actions:
                lines.extend(
                    [
                        f"#### {action.category} ({action.severity})",
                        "",
                        f"- Blocks formal claim: {action.blocks_formal_claim}",
                        f"- Required by: {action.required_by or 'n/a'}",
                        f"- Summary: {action.summary}",
                    ]
                )
                if action.command_templates:
                    lines.append("- Command templates:")
                    for command in action.command_templates:
                        lines.append(f"  - `{command}`")
                lines.append("")
        if self.next_actions:
            lines.extend(["## Next Actions", ""])
            for action in self.next_actions:
                lines.append(f"- {action}")
        return "\n".join(lines).rstrip() + "\n"


class FormalReadinessBuilder:
    """Turns replay diagnostics into a concrete input-backfill queue."""

    def __init__(self, pipeline: PredictionPipeline | None = None) -> None:
        self.pipeline = pipeline or PredictionPipeline(iterations=1200)

    def build(self, year: int, as_of: str) -> FormalReadinessReport:
        analysis = ReplayAnalysisBuilder(self.pipeline).build(year, as_of)
        events = tuple(self._event_readiness(row, year, as_of) for row in analysis.event_diagnostics)
        all_actions = [action for event in events for action in event.actions]
        blocking_actions = [
            action
            for action in all_actions
            if action.blocks_formal_claim
        ]
        warning_actions = [
            action
            for action in all_actions
            if not action.blocks_formal_claim
        ]
        category_counts: dict[str, int] = {}
        for action in all_actions:
            category_counts[action.category] = category_counts.get(action.category, 0) + 1
        formal_ready = not blocking_actions and analysis.formal_backtest_ready
        return FormalReadinessReport(
            year=year,
            as_of=as_of,
            generated_at=utc_now().isoformat(),
            status="formal_ready" if formal_ready else "inputs_required",
            formal_backtest_ready=formal_ready,
            blocking_action_count=len(blocking_actions),
            warning_action_count=len(warning_actions),
            action_category_counts=category_counts,
            workstreams=self._workstreams(all_actions),
            events=events,
            next_actions=self._next_actions(blocking_actions, warning_actions, analysis),
        )

    def write(
        self,
        year: int,
        as_of: str,
        output_dir: Path | str = Path("reports/formal_readiness"),
    ) -> dict[str, Path]:
        report = self.build(year, as_of)
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"{year}_asof_{self._stem_time(as_of)}"
        json_path = directory / f"{stem}.readiness.json"
        markdown_path = directory / f"{stem}.readiness.md"
        json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(report.to_markdown(), encoding="utf-8")
        return {"json": json_path, "markdown": markdown_path}

    def _event_readiness(self, row: ReplayEventDiagnostic, year: int, as_of: str) -> FormalReadinessEvent:
        actions = tuple(self._actions_for_row(row, year, as_of))
        blocking = sum(1 for action in actions if action.blocks_formal_claim)
        warning = len(actions) - blocking
        if row.status in {"cancelled", "not_due"}:
            status = row.status
        elif blocking:
            status = "blocked"
        elif warning:
            status = "diagnostic_ready_with_warnings"
        else:
            status = "formal_input_ready"
        return FormalReadinessEvent(
            event_id=row.event_id or row.event_name,
            event_name=row.event_name,
            date_end=row.date_end,
            status=status,
            blocking_action_count=blocking,
            warning_action_count=warning,
            actions=actions,
        )

    def _actions_for_row(self, row: ReplayEventDiagnostic, year: int, as_of: str) -> list[FormalReadinessAction]:
        if row.status in {"cancelled", "not_due"}:
            return []
        actions: list[FormalReadinessAction] = []
        event_id = row.event_id or row.event_name
        if row.missing_market_snapshot_detail:
            actions.append(self._market_snapshot_action(row, event_id, year, as_of))
        if row.market_snapshot_after_cutoff_details:
            actions.append(self._late_market_action(row, event_id, year, as_of))
        for index, detail in enumerate(row.retrospective_source_details, start=1):
            actions.append(self._source_archive_action(row, event_id, detail, index))
        if row.evidence_count == 0:
            actions.append(
                FormalReadinessAction(
                    action_id=f"{event_id}:codex_evidence",
                    event_id=event_id,
                    event_name=row.event_name,
                    category="codex_evidence_required",
                    severity="critical",
                    blocks_formal_claim=True,
                    summary="No normalized Codex evidence is available at the replay cutoff.",
                    required_by=self._event_cutoff(row),
                    details={"issue_codes": list(row.issue_codes)},
                    command_templates=(
                        f"python -m f1predict.cli prepare-research --event {event_id} --knowledge-cutoff {self._event_cutoff(row)}",
                        f"python -m f1predict.cli preflight-research-packet --input data\\research\\{event_id}\\research_packet_template.json --event {event_id} --knowledge-cutoff {self._event_cutoff(row)} --output reports\\research_preflight\\{event_id}.json --markdown-output reports\\research_preflight\\{event_id}.md",
                        f"python -m f1predict.cli archive-research-packet --input data\\research\\{event_id}\\research_packet_template.json --event {event_id} --knowledge-cutoff {self._event_cutoff(row)}",
                    ),
                )
            )
        if row.feature_adjustment_count == 0 and row.round_number != 1:
            actions.append(
                FormalReadinessAction(
                    action_id=f"{event_id}:processed_features",
                    event_id=event_id,
                    event_name=row.event_name,
                    category="processed_features_required",
                    severity="high",
                    blocks_formal_claim=True,
                    summary="No point-in-time structured feature adjustments are available for this replay row.",
                    required_by=self._event_cutoff(row),
                    details={"round_number": row.round_number},
                    command_templates=(
                        "python -m f1predict.cli ingest-openf1 --year 2026 --event-query <event-name> --include-session-data",
                        "python -m f1predict.cli summarize-openf1 --year 2026 --event-query <event-name> --write",
                    ),
                )
            )
        if row.hit is False:
            actions.append(
                FormalReadinessAction(
                    action_id=f"{event_id}:model_calibration",
                    event_id=event_id,
                    event_name=row.event_name,
                    category="model_calibration_review",
                    severity="medium",
                    blocks_formal_claim=False,
                    summary=(
                        "The actual winner was not the top pick in diagnostic replay; inspect probability rank "
                        "after blocking input gaps are fixed."
                    ),
                    required_by=None,
                    details={
                        "top_pick": row.top_pick,
                        "actual_winner": row.actual_winner,
                        "actual_winner_probability": row.actual_winner_probability,
                        "actual_winner_rank": row.actual_winner_rank,
                        "max_evidence_win_delta": row.max_evidence_win_delta,
                    },
                    command_templates=(
                        f"python -m f1predict.cli predict --event {event_id} --knowledge-cutoff {self._event_cutoff(row)} --iterations 5000",
                    ),
                )
            )
        return actions

    def _workstreams(self, actions: list[FormalReadinessAction]) -> tuple[FormalReadinessWorkstream, ...]:
        grouped: dict[str, list[FormalReadinessAction]] = {}
        for action in actions:
            grouped.setdefault(action.category, []).append(action)
        workstreams = [
            self._workstream_for_category(category, category_actions)
            for category, category_actions in grouped.items()
        ]
        return tuple(
            sorted(
                workstreams,
                key=lambda workstream: (
                    workstream.priority,
                    0 if workstream.blocks_formal_claim else 1,
                    workstream.category,
                ),
            )
        )

    def _workstream_for_category(
        self,
        category: str,
        actions: list[FormalReadinessAction],
    ) -> FormalReadinessWorkstream:
        config = self._workstream_config(category)
        ordered = sorted(
            actions,
            key=lambda action: (
                0 if action.blocks_formal_claim else 1,
                {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(action.severity, 9),
                action.required_by or "",
                action.event_id,
                action.action_id,
            ),
        )
        event_ids = tuple(dict.fromkeys(action.event_id for action in ordered))
        command_templates = tuple(
            dict.fromkeys(command for action in ordered for command in action.command_templates)
        )[:8]
        severity = min(
            (action.severity for action in ordered),
            key=lambda severity_value: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(
                severity_value,
                9,
            ),
            default="low",
        )
        blocking = sum(1 for action in ordered if action.blocks_formal_claim)
        return FormalReadinessWorkstream(
            workstream_id=config["workstream_id"],
            title=config["title"],
            priority=int(config["priority"]),
            category=category,
            severity=severity,
            blocks_formal_claim=blocking > 0,
            blocking_action_count=blocking,
            warning_action_count=len(ordered) - blocking,
            event_ids=event_ids,
            success_criteria=tuple(config["success_criteria"]),
            command_templates=command_templates,
            actions=tuple(ordered),
        )

    def _market_snapshot_action(
        self,
        row: ReplayEventDiagnostic,
        event_id: str,
        year: int,
        as_of: str,
    ) -> FormalReadinessAction:
        detail = row.missing_market_snapshot_detail or {}
        cutoff = str(detail.get("required_at_or_before") or self._event_cutoff(row))
        return FormalReadinessAction(
            action_id=f"{event_id}:market_snapshot",
            event_id=event_id,
            event_name=row.event_name,
            category="market_snapshot_required",
            severity="critical",
            blocks_formal_claim=True,
            summary=(
                "A cutoff-valid model-supported market snapshot is required before market-gap edge or CLV "
                "can be evaluated; winner markets are preferred, supported non-winner markets can only "
                "support diagnostic market-gap evidence."
            ),
            required_by=cutoff,
            details=detail,
            command_templates=(
                f"python -m f1predict.cli search-backfill-polymarket-history --event {event_id} --knowledge-cutoff {cutoff} --market-type winner --include-closed --write --output reports\\market_normalization\\{event_id}_price_history.json --search-output reports\\market_normalization\\{event_id}_search_payload.json",
                f"python -m f1predict.cli search-backfill-polymarket-history --event {event_id} --knowledge-cutoff {cutoff} --market-type constructor_double_podium --include-closed --write --output reports\\market_normalization\\{event_id}_constructor_double_podium_price_history.json --search-output reports\\market_normalization\\{event_id}_constructor_double_podium_search_payload.json",
                f"python -m f1predict.cli search-backfill-polymarket-history --event {event_id} --knowledge-cutoff {cutoff} --market-type driver_h2h --include-closed --write --output reports\\market_normalization\\{event_id}_driver_h2h_price_history.json --search-output reports\\market_normalization\\{event_id}_driver_h2h_search_payload.json",
                f"python -m f1predict.cli reviewed-market-template --event {event_id} --market-type winner > data\\research\\markets\\{event_id}_reviewed_winner_market.json",
                f"python -m f1predict.cli archive-reviewed-market-snapshot --event {event_id} --input data\\research\\markets\\{event_id}_reviewed_winner_market.json --knowledge-cutoff {cutoff} --require-cutoff-valid",
                f"python -m f1predict.cli formal-readiness --year {year} --as-of {as_of} --write",
            ),
        )

    def _late_market_action(
        self,
        row: ReplayEventDiagnostic,
        event_id: str,
        year: int,
        as_of: str,
    ) -> FormalReadinessAction:
        cutoff = self._event_cutoff(row)
        return FormalReadinessAction(
            action_id=f"{event_id}:late_market_replacement",
            event_id=event_id,
            event_name=row.event_name,
            category="after_cutoff_market_replacement",
            severity="medium",
            blocks_formal_claim=False,
            summary="Existing market rows were captured after the replay cutoff and are excluded from edge scoring.",
            required_by=cutoff,
            details={
                "after_cutoff_snapshots": list(row.market_snapshot_after_cutoff_details),
                "excluded_from_prediction": True,
                "blocking_market_action": bool(row.missing_market_snapshot_detail),
            },
            command_templates=(
                f"python -m f1predict.cli search-backfill-polymarket-history --event {event_id} --knowledge-cutoff {cutoff} --market-type winner --include-closed --write --output reports\\market_normalization\\{event_id}_price_history.json --search-output reports\\market_normalization\\{event_id}_search_payload.json",
                f"python -m f1predict.cli reviewed-market-template --event {event_id} --market-type winner > data\\research\\markets\\{event_id}_reviewed_winner_market.json",
                f"python -m f1predict.cli archive-reviewed-market-snapshot --event {event_id} --input data\\research\\markets\\{event_id}_reviewed_winner_market.json --knowledge-cutoff {cutoff} --require-cutoff-valid",
                f"python -m f1predict.cli formal-readiness --year {year} --as-of {as_of} --write",
            ),
        )

    def _source_archive_action(
        self,
        row: ReplayEventDiagnostic,
        event_id: str,
        detail: dict[str, Any],
        index: int,
    ) -> FormalReadinessAction:
        cutoff = str(detail.get("knowledge_cutoff") or self._event_cutoff(row))
        source_url = str(detail.get("url") or "")
        return FormalReadinessAction(
            action_id=f"{event_id}:source_archive:{index}",
            event_id=event_id,
            event_name=row.event_name,
            category="source_archive_required",
            severity="high",
            blocks_formal_claim=True,
            summary="A late local source snapshot needs cutoff-valid archive proof or a replacement source.",
            required_by=cutoff,
            details=detail,
            command_templates=(
                f"python -m f1predict.cli discover-source-archives --event {event_id} --write --output reports\\source_archives\\{event_id}_wayback.json",
                f"python -m f1predict.cli snapshot-source --event {event_id} --url {source_url} --source <source-name> --source-class <class> --published-at <published-at> --observed-at <observed-before-cutoff> --knowledge-cutoff {cutoff} --historical-archive-url <archive-url> --historical-archived-at <archived-before-cutoff> --historical-original-url {source_url} --historical-verification-method wayback",
            ),
        )

    @staticmethod
    def _workstream_config(category: str) -> dict[str, Any]:
        configs: dict[str, dict[str, Any]] = {
            "market_snapshot_required": {
                "workstream_id": "market_snapshot_backfill",
                "title": "Market Snapshot Backfill",
                "priority": 1,
                "success_criteria": (
                    "Each listed event has a cutoff-valid model-supported market snapshot archived under data/market_snapshots.",
                    "The selected snapshot timestamp is at or before the replay cutoff for that event.",
                    "Replay analysis reports no missing supported-market snapshot for the listed events.",
                ),
            },
            "after_cutoff_market_replacement": {
                "workstream_id": "after_cutoff_market_replacement",
                "title": "After-Cutoff Market Replacement",
                "priority": 2,
                "success_criteria": (
                    "Existing after-cutoff seed or backfilled rows are replaced by cutoff-valid rows or remain excluded.",
                    "Replay analysis still records excluded late rows as diagnostics without using them for prediction.",
                ),
            },
            "source_archive_required": {
                "workstream_id": "source_archive_proof",
                "title": "Source Archive Proof",
                "priority": 3,
                "success_criteria": (
                    "Each retrospective source has pre-cutoff archive proof or is replaced by a pre-cutoff source snapshot.",
                    "Source audit reports archive-backed snapshots instead of unverified retrospective snapshots.",
                ),
            },
            "codex_evidence_required": {
                "workstream_id": "codex_evidence_intake",
                "title": "Codex Evidence Intake",
                "priority": 4,
                "success_criteria": (
                    "Each listed event has a normalized evidence packet frozen at the replay cutoff.",
                    "The packet passes source-log audit before it is used in replay diagnostics.",
                ),
            },
            "processed_features_required": {
                "workstream_id": "processed_feature_backfill",
                "title": "Processed Feature Backfill",
                "priority": 5,
                "success_criteria": (
                    "Each listed event has point-in-time structured feature adjustments.",
                    "Replay diagnostics no longer report zero feature adjustments for non-opening rounds.",
                ),
            },
            "model_calibration_review": {
                "workstream_id": "model_calibration_review",
                "title": "Model Calibration Review",
                "priority": 6,
                "success_criteria": (
                    "Re-run predict and calibration reports after input blockers are fixed.",
                    "Inspect misses, actual-winner ranks, and overconfidence before promoting any edge claim.",
                ),
            },
        }
        return configs.get(
            category,
            {
                "workstream_id": category,
                "title": category.replace("_", " ").title(),
                "priority": 99,
                "success_criteria": (
                    "Resolve all listed actions and re-run formal readiness.",
                ),
            },
        )

    @staticmethod
    def _next_actions(
        blocking_actions: list[FormalReadinessAction],
        warning_actions: list[FormalReadinessAction],
        analysis: ReplayAnalysisReport,
    ) -> tuple[str, ...]:
        if blocking_actions:
            ordered = sorted(
                blocking_actions,
                key=lambda action: (
                    {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(action.severity, 9),
                    action.category,
                    action.event_id,
                ),
            )
            by_category: dict[str, str] = {}
            for action in ordered:
                by_category.setdefault(action.category, action.summary)
            return tuple(by_category.values())[:6]
        if warning_actions:
            return tuple(dict.fromkeys(action.summary for action in warning_actions[:5]))
        return tuple(analysis.next_actions)

    @staticmethod
    def _event_cutoff(row: ReplayEventDiagnostic) -> str:
        date_part = str(row.date_end).split("T", maxsplit=1)[0]
        return f"{date_part}T00:00:00+00:00"

    @staticmethod
    def _stem_time(value: str) -> str:
        return value.replace(":", "").replace("+", "_").replace("-", "")
