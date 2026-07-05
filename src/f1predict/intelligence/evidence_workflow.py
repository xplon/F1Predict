"""Codex evidence research workflow utilities."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from f1predict.domain import EvidenceClaim, RaceEvent, SeasonState, parse_dt, utc_now
from f1predict.event_inputs import EventInputAudit, audit_event_input
from f1predict.features.provider import ProcessedFeatureProvider
from f1predict.intelligence.codex import CodexEvidenceProvider
from f1predict.intelligence.research_brief import ResearchBriefBuilder
from f1predict.intelligence.research_plan import CodexResearchPlanBuilder
from f1predict.intelligence.source_registry import source_has_cutoff_archive_proof
from f1predict.market import event_market_snapshots
from f1predict.pipeline import PredictionPipeline


SUPPORTED_MARKET_TYPES = ("winner", "constructor_double_podium")


class SeasonDataSource(Protocol):
    def load(self) -> SeasonState: ...


@dataclass(frozen=True)
class EvidenceCoverageRow:
    event_id: str
    event_name: str
    round_number: int
    date: str
    completed: bool
    prediction_input_source: str
    event_input_quality: str
    event_input_risk_codes: tuple[str, ...]
    event_input_verified_fields: tuple[str, ...]
    event_input_derived_fields: tuple[str, ...]
    event_input_heuristic_fields: tuple[str, ...]
    event_input_placeholder_fields: tuple[str, ...]
    evidence_count: int
    review_required_count: int
    source_classes: tuple[str, ...]
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
    missing_inputs: tuple[str, ...]
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_name": self.event_name,
            "round_number": self.round_number,
            "date": self.date,
            "completed": self.completed,
            "prediction_input_source": self.prediction_input_source,
            "event_input_quality": self.event_input_quality,
            "event_input_risk_codes": list(self.event_input_risk_codes),
            "event_input_verified_fields": list(self.event_input_verified_fields),
            "event_input_derived_fields": list(self.event_input_derived_fields),
            "event_input_heuristic_fields": list(self.event_input_heuristic_fields),
            "event_input_placeholder_fields": list(self.event_input_placeholder_fields),
            "evidence_count": self.evidence_count,
            "review_required_count": self.review_required_count,
            "source_classes": list(self.source_classes),
            "source_snapshot_count": self.source_snapshot_count,
            "retrospective_source_snapshot_count": self.retrospective_source_snapshot_count,
            "archive_backed_source_snapshot_count": self.archive_backed_source_snapshot_count,
            "retrospective_source_details": list(self.retrospective_source_details),
            "archive_backed_source_details": list(self.archive_backed_source_details),
            "feature_adjustment_count": self.feature_adjustment_count,
            "market_snapshot_count": self.market_snapshot_count,
            "market_snapshot_after_cutoff_count": self.market_snapshot_after_cutoff_count,
            "market_snapshot_details": list(self.market_snapshot_details),
            "market_snapshot_after_cutoff_details": list(self.market_snapshot_after_cutoff_details),
            "missing_market_snapshot_detail": self.missing_market_snapshot_detail,
            "missing_inputs": list(self.missing_inputs),
            "status": self.status,
        }


@dataclass(frozen=True)
class EvidenceCoverageReport:
    generated_at: str
    as_of: str | None
    event_count: int
    completed_event_count: int
    events_with_evidence: int
    events_with_source_snapshots: int
    events_with_retrospective_source_snapshots: int
    events_with_archive_backed_source_snapshots: int
    events_with_market_snapshots: int
    events_with_market_snapshots_after_cutoff: int
    events_needing_codex_research: int
    rows: list[EvidenceCoverageRow]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "as_of": self.as_of,
            "event_count": self.event_count,
            "completed_event_count": self.completed_event_count,
            "events_with_evidence": self.events_with_evidence,
            "events_with_source_snapshots": self.events_with_source_snapshots,
            "events_with_retrospective_source_snapshots": self.events_with_retrospective_source_snapshots,
            "events_with_archive_backed_source_snapshots": self.events_with_archive_backed_source_snapshots,
            "events_with_market_snapshots": self.events_with_market_snapshots,
            "events_with_market_snapshots_after_cutoff": self.events_with_market_snapshots_after_cutoff,
            "events_needing_codex_research": self.events_needing_codex_research,
            "rows": [row.to_dict() for row in self.rows],
        }


class EvidenceCoverageAuditor:
    """Reports which events have normalized Codex evidence and market context."""

    def __init__(
        self,
        data_source: SeasonDataSource | None = None,
        evidence_provider: CodexEvidenceProvider | None = None,
        feature_provider: ProcessedFeatureProvider | None = None,
        research_root: Path | str = Path("data/research"),
    ) -> None:
        pipeline = PredictionPipeline()
        self.data_source = data_source or pipeline.data_source
        self.evidence_provider = evidence_provider or pipeline.evidence_provider
        self.feature_provider = feature_provider or pipeline.feature_provider
        self.research_root = Path(research_root)

    def build(self, as_of: str | None = None) -> EvidenceCoverageReport:
        season = self.data_source.load()
        cutoff = parse_dt(as_of)
        rows: list[EvidenceCoverageRow] = []
        for event in season.events:
            event_dt = parse_dt(f"{event.date}T00:00:00+00:00")
            if cutoff is not None and event_dt is not None and event_dt > cutoff:
                continue
            evidence_cutoff = event_dt if event.completed else cutoff
            claims = self.evidence_provider.load_event_evidence(event.event_id, evidence_cutoff)
            feature_adjustments = self.feature_provider.load_event_features(season, event, evidence_cutoff)
            market_details = self._market_snapshot_details(
                season.markets,
                event,
                evidence_cutoff,
                after_cutoff=False,
            )
            market_after_cutoff_details = self._market_snapshot_details(
                season.markets,
                event,
                evidence_cutoff,
                after_cutoff=True,
            )
            market_count = len(market_details)
            market_after_cutoff_count = len(market_after_cutoff_details)
            missing_market_detail = (
                self._missing_market_detail(event, evidence_cutoff, market_after_cutoff_count)
                if market_count == 0
                else None
            )
            (
                source_snapshot_count,
                retrospective_source_snapshot_count,
                archive_backed_source_snapshot_count,
                retrospective_source_details,
                archive_backed_source_details,
            ) = self._source_snapshot_diagnostics(event.event_id)
            event_input_audit = audit_event_input(event)
            missing = self._missing_inputs(
                event,
                claims,
                feature_adjustments,
                market_count,
                source_snapshot_count,
                event_input_audit,
            )
            rows.append(
                EvidenceCoverageRow(
                    event_id=event.event_id,
                    event_name=event.name,
                    round_number=event.round_number,
                    date=event.date,
                    completed=event.completed,
                    prediction_input_source=self._input_source(event),
                    event_input_quality=event_input_audit.quality,
                    event_input_risk_codes=event_input_audit.risk_codes,
                    event_input_verified_fields=event_input_audit.verified_fields,
                    event_input_derived_fields=event_input_audit.derived_fields,
                    event_input_heuristic_fields=event_input_audit.heuristic_fields,
                    event_input_placeholder_fields=event_input_audit.placeholder_fields,
                    evidence_count=len(claims),
                    review_required_count=sum(1 for claim in claims if claim.review_required),
                    source_classes=tuple(sorted({self._source_class(claim) for claim in claims})),
                    source_snapshot_count=source_snapshot_count,
                    retrospective_source_snapshot_count=retrospective_source_snapshot_count,
                    archive_backed_source_snapshot_count=archive_backed_source_snapshot_count,
                    retrospective_source_details=tuple(retrospective_source_details),
                    archive_backed_source_details=tuple(archive_backed_source_details),
                    feature_adjustment_count=len(feature_adjustments),
                    market_snapshot_count=market_count,
                    market_snapshot_after_cutoff_count=market_after_cutoff_count,
                    market_snapshot_details=tuple(market_details),
                    market_snapshot_after_cutoff_details=tuple(market_after_cutoff_details),
                    missing_market_snapshot_detail=missing_market_detail,
                    missing_inputs=tuple(missing),
                    status="needs_codex_research" if "codex_evidence" in missing else "evidence_present",
                )
            )

        return EvidenceCoverageReport(
            generated_at=utc_now().isoformat(),
            as_of=as_of,
            event_count=len(rows),
            completed_event_count=sum(1 for row in rows if row.completed),
            events_with_evidence=sum(1 for row in rows if row.evidence_count > 0),
            events_with_source_snapshots=sum(1 for row in rows if row.source_snapshot_count > 0),
            events_with_retrospective_source_snapshots=sum(
                1 for row in rows if row.retrospective_source_snapshot_count > 0
            ),
            events_with_archive_backed_source_snapshots=sum(
                1 for row in rows if row.archive_backed_source_snapshot_count > 0
            ),
            events_with_market_snapshots=sum(1 for row in rows if row.market_snapshot_count > 0),
            events_with_market_snapshots_after_cutoff=sum(
                1 for row in rows if row.market_snapshot_after_cutoff_count > 0
            ),
            events_needing_codex_research=sum(1 for row in rows if row.status == "needs_codex_research"),
            rows=rows,
        )

    @staticmethod
    def _missing_inputs(
        event: RaceEvent,
        claims: list[EvidenceClaim],
        feature_adjustments: list[Any],
        market_count: int,
        source_snapshot_count: int,
        event_input_audit: EventInputAudit,
    ) -> list[str]:
        missing = []
        if source_snapshot_count == 0:
            missing.append("source_snapshots")
        if not claims:
            missing.append("codex_evidence")
        if event.completed and not feature_adjustments:
            missing.append("processed_features")
        if market_count == 0:
            missing.append("market_snapshot")
        if "generated_structure_only_event_input" in event_input_audit.risk_codes:
            missing.append("verified_event_input_provenance")
        if "heuristic_generated_event_profile" in event_input_audit.risk_codes:
            missing.append("verified_event_profile")
        return missing

    @staticmethod
    def _input_source(event: RaceEvent) -> str:
        source = event.feature_refs.get("event_source")
        return str(source) if source else "seed"

    def _source_snapshot_diagnostics(self, event_id: str) -> tuple[int, int, int, list[dict[str, Any]], list[dict[str, Any]]]:
        path = self.research_root / event_id / "source_log.json"
        if not path.exists():
            return 0, 0, 0, [], []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return 0, 0, 0, [], []
        sources = raw.get("sources", [])
        if not isinstance(sources, list):
            return 0, 0, 0, [], []
        cutoff = parse_dt(str(raw.get("knowledge_cutoff"))) if raw.get("knowledge_cutoff") else None
        snapshot_count = 0
        retrospective_count = 0
        archive_backed_count = 0
        retrospective_details: list[dict[str, Any]] = []
        archive_backed_details: list[dict[str, Any]] = []
        for source in sources:
            if not isinstance(source, dict) or not source.get("snapshot_path"):
                continue
            snapshot_count += 1
            captured = parse_dt(str(source.get("captured_at"))) if source.get("captured_at") else None
            has_archive_proof = source_has_cutoff_archive_proof(source, cutoff)
            if has_archive_proof:
                archive_backed_count += 1
                archive_backed_details.append(self._source_detail(source, raw.get("knowledge_cutoff"), "archive_backed"))
            if (
                cutoff is not None
                and captured is not None
                and captured > cutoff
                and not has_archive_proof
            ):
                retrospective_count += 1
                retrospective_details.append(self._source_detail(source, raw.get("knowledge_cutoff"), "missing_cutoff_archive"))
        return snapshot_count, retrospective_count, archive_backed_count, retrospective_details, archive_backed_details

    @staticmethod
    def _source_detail(source: dict[str, Any], knowledge_cutoff: Any, status: str) -> dict[str, Any]:
        archive = source.get("historical_archive") if isinstance(source.get("historical_archive"), dict) else None
        return {
            "source": source.get("source"),
            "url": source.get("url"),
            "title": source.get("title"),
            "source_class": source.get("source_class"),
            "published_at": source.get("published_at"),
            "observed_at": source.get("observed_at"),
            "captured_at": source.get("captured_at"),
            "knowledge_cutoff": knowledge_cutoff,
            "cutoff_status": source.get("cutoff_status"),
            "snapshot_path": source.get("snapshot_path"),
            "archive_status": status,
            "archive_url": archive.get("archive_url") if archive else None,
            "archived_at": archive.get("archived_at") if archive else None,
            "archive_verification_method": archive.get("verification_method") if archive else None,
        }

    @classmethod
    def _market_snapshot_details(
        cls,
        markets: list[Any],
        event: RaceEvent,
        cutoff: Any,
        after_cutoff: bool,
    ) -> list[dict[str, Any]]:
        if after_cutoff:
            rows = [
                market
                for market in markets
                if market.event_id == event.event_id
                and market.market_type in SUPPORTED_MARKET_TYPES
                and cutoff is not None
                and not market.is_available(cutoff)
            ]
        else:
            rows = []
            for market_type in SUPPORTED_MARKET_TYPES:
                rows.extend(event_market_snapshots(markets, event.event_id, cutoff, market_type=market_type))
        status = "after_cutoff" if after_cutoff else "cutoff_valid"
        return [cls._market_detail(market, event, cutoff, status) for market in rows]

    @staticmethod
    def _market_detail(market: Any, event: RaceEvent, cutoff: Any, status: str) -> dict[str, Any]:
        prices = getattr(market, "prices", {}) or {}
        top_prices = sorted(prices.items(), key=lambda item: float(item[1]), reverse=True)[:5]
        market_id = str(getattr(market, "market_id", "") or "")
        return {
            "event_id": event.event_id,
            "event_name": event.name,
            "market_id": market_id,
            "market_type": getattr(market, "market_type", None),
            "captured_at": getattr(market, "captured_at", None),
            "knowledge_cutoff": cutoff.isoformat() if hasattr(cutoff, "isoformat") else cutoff,
            "status": status,
            "source": "seed" if market_id.startswith("seed_") else "market_snapshot_store",
            "liquidity": getattr(market, "liquidity", 0.0),
            "spread_estimate": getattr(market, "spread_estimate", 0.0),
            "outcome_count": len(prices),
            "top_prices": [{"outcome_id": outcome_id, "price": price} for outcome_id, price in top_prices],
        }

    @staticmethod
    def _missing_market_detail(
        event: RaceEvent,
        cutoff: Any,
        after_cutoff_count: int,
    ) -> dict[str, Any]:
        return {
            "event_id": event.event_id,
            "event_name": event.name,
            "market_type": "supported_model_market",
            "supported_market_types": list(SUPPORTED_MARKET_TYPES),
            "required_at_or_before": cutoff.isoformat() if hasattr(cutoff, "isoformat") else cutoff,
            "status": "missing_cutoff_valid_snapshot",
            "after_cutoff_snapshot_count": after_cutoff_count,
            "recommendation": (
                "Archive a same-time snapshot for a model-supported market before this cutoff "
                "(winner preferred, constructor_double_podium accepted as diagnostic market-gap evidence), "
                "or backfill from a reviewed price-history source without using post-race prices."
            ),
        }

    @staticmethod
    def _source_class(claim: EvidenceClaim) -> str:
        source = f"{claim.source} {claim.source_url}".lower()
        if "seed://" in source:
            return "seed"
        if "fia" in source:
            return "fia"
        if "formula1.com" in source or "f1" in source and "official" in source:
            return "f1_official"
        if "openf1" in source or "fastf1" in source:
            return "structured_data"
        if "weather" in source or "met office" in source or "radar" in source:
            return "weather"
        if "polymarket" in source:
            return "market"
        if any(team in source for team in ("mercedes", "ferrari", "mclaren", "red bull", "aston martin")):
            return "team_or_driver"
        return "media"


class CodexResearchWorkspaceBuilder:
    """Writes deterministic research tasks for Codex tool-using evidence work."""

    def __init__(
        self,
        data_source: SeasonDataSource | None = None,
        evidence_provider: CodexEvidenceProvider | None = None,
    ) -> None:
        pipeline = PredictionPipeline()
        self.data_source = data_source or pipeline.data_source
        self.evidence_provider = evidence_provider or pipeline.evidence_provider

    def write_event_workspace(
        self,
        event_id: str,
        knowledge_cutoff: str | None = None,
        output_dir: Path | str = Path("data/research"),
    ) -> list[Path]:
        season = self.data_source.load()
        event = next((item for item in season.events if item.event_id == event_id), None)
        if event is None:
            raise ValueError(f"Unknown event_id: {event_id}")
        cutoff = knowledge_cutoff or f"{event.date}T00:00:00+00:00"
        directory = Path(output_dir) / event.event_id
        directory.mkdir(parents=True, exist_ok=True)

        brief = ResearchBriefBuilder(self.data_source, self.evidence_provider).build(event.event_id)
        plan = CodexResearchPlanBuilder(self.data_source, self.evidence_provider).build(
            event.event_id,
            knowledge_cutoff=cutoff,
        )
        task_path = directory / "research_task.md"
        plan_json_path = directory / "codex_research_plan.json"
        plan_markdown_path = directory / "codex_research_plan.md"
        template_path = directory / "evidence_template.json"
        source_candidates_path = directory / "source_candidates.json"
        packet_template_path = directory / "research_packet_template.json"
        source_log_path = directory / "source_log.json"
        draft_path = directory / "draft_evidence.jsonl"

        task_path.write_text(self._task_text(event, cutoff, brief), encoding="utf-8")
        plan_paths = CodexResearchPlanBuilder.write(plan, output_dir=Path(output_dir))
        template_path.write_text(json.dumps(self._evidence_template(event, cutoff), ensure_ascii=False, indent=2), encoding="utf-8")
        source_candidates_path.write_text(
            json.dumps(self._source_candidates_template(event, cutoff), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        packet_template_path.write_text(
            json.dumps(self._research_packet_template(event, cutoff), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._ensure_source_log(source_log_path, event, cutoff)
        if not draft_path.exists():
            draft_path.write_text("", encoding="utf-8")
        return [
            task_path,
            plan_paths["json"] if plan_paths.get("json") else plan_json_path,
            plan_paths["markdown"] if plan_paths.get("markdown") else plan_markdown_path,
            template_path,
            source_candidates_path,
            packet_template_path,
            source_log_path,
            draft_path,
        ]

    def write_due_workspaces(
        self,
        as_of: str,
        output_dir: Path | str = Path("data/research"),
        only_missing_evidence: bool = True,
    ) -> list[Path]:
        coverage = EvidenceCoverageAuditor(self.data_source, self.evidence_provider).build(as_of=as_of)
        paths: list[Path] = []
        for row in coverage.rows:
            if not row.completed:
                continue
            if only_missing_evidence and row.evidence_count > 0:
                continue
            paths.extend(self.write_event_workspace(row.event_id, f"{row.date}T00:00:00+00:00", output_dir))
        return paths

    @staticmethod
    def _task_text(event: RaceEvent, cutoff: str, brief: str) -> str:
        queries = [
            f"{event.name} {event.date} F1 practice qualifying race preview",
            f"{event.name} {event.date} FIA documents race director notes",
            f"{event.name} {event.date} team upgrades Mercedes Ferrari McLaren Red Bull",
            f"{event.name} {event.date} weather forecast F1",
            f"{event.name} Polymarket winner market rules prices",
        ]
        lines = [
            brief.rstrip(),
            "",
            "## Point-In-Time Cutoff",
            f"- knowledge_cutoff: `{cutoff}`",
            "- Reject any source where published_at or observed_at is after the cutoff.",
            "",
            "## Search Queries",
        ]
        lines.extend(f"- {query}" for query in queries)
        lines.extend(
            [
                "",
                "## Workflow",
                "1. Read `codex_research_plan.md` first; it defines source tasks, quality gates, metric mapping, and impact bands for this event.",
                "2. Save Codex tool search/open results into `source_candidates.json`, including task_id, query, URL, snippet, timestamps, source_class, model_metrics, and target_hints.",
                f"3. Run `f1predict codex-source-candidates --event {{event_id}} --input data/research/{{event_id}}/source_candidates.json --knowledge-cutoff {cutoff}` before drafting claims.",
                "4. Prefer filling `research_packet_template.json`; `f1predict preflight-research-packet` checks schema, source-candidate links, source links, conflicts, model input weights, and simulator routes before archive.",
                "5. For manual drafts, snapshot every inspected web/PDF/market source with `f1predict snapshot-source` before using it in a claim.",
                "6. Write only source-backed claims to `draft_evidence.jsonl`.",
                "7. Assign low confidence and high uncertainty to rumors, conflicting reports, or single-source claims.",
                "8. Run `f1predict validate-evidence --event {event_id} --path data/research/{event_id}/draft_evidence.jsonl` if manually editing drafts.",
                "9. Run `f1predict audit-evidence-sources --event {event_id} --input data/research/{event_id}/draft_evidence.jsonl --source-log data/research/{event_id}/source_log.json`.",
                "10. Archive validated claims with `f1predict ingest-evidence --event {event_id} --input data/research/{event_id}/draft_evidence.jsonl --source-log data/research/{event_id}/source_log.json`.",
                "",
                "## Source Snapshot Example",
                f"- `f1predict snapshot-source --event {event.event_id} --url <url> --source <name> --source-class media --published-at <iso> --knowledge-cutoff {cutoff} --claim-id <claim_id>`",
                "",
                "## Source Candidate Audit Example",
                f"- `f1predict codex-source-candidates --event {event.event_id} --input data/research/{event.event_id}/source_candidates.json --knowledge-cutoff {cutoff} --output reports/research_candidates/{event.event_id}.json --markdown-output reports/research_candidates/{event.event_id}.md`",
                "",
                "## Batch Archive Example",
                f"- `f1predict preflight-research-packet --input data/research/{event.event_id}/research_packet_template.json --event {event.event_id} --knowledge-cutoff {cutoff} --source-candidate-report reports/research_candidates/{event.event_id}.json --output reports/research_preflight/{event.event_id}.json --markdown-output reports/research_preflight/{event.event_id}.md`",
                f"- `f1predict archive-research-packet --input data/research/{event.event_id}/research_packet_template.json --event {event.event_id} --knowledge-cutoff {cutoff}`",
                "",
                "## Final Evidence Archive",
                f"- `data/evidence/{event.event_id}/packets/`",
            ]
        )
        return "\n".join(lines).replace("{event_id}", event.event_id) + "\n"

    @staticmethod
    def _evidence_template(event: RaceEvent, cutoff: str) -> dict[str, Any]:
        return {
            "notes": "Manual fallback template. Copy one completed object per line into draft_evidence.jsonl, then audit and archive it before replay.",
            "knowledge_cutoff": cutoff,
            "example_claim": {
                "claim_id": f"{event.event_id}-codex-001",
                "event_id": event.event_id,
                "source": "REPLACE_WITH_SOURCE_NAME",
                "source_url": "REPLACE_WITH_SOURCE_URL",
                "published_at": "REPLACE_WITH_ISO_TIMESTAMP",
                "observed_at": "REPLACE_WITH_ISO_TIMESTAMP",
                "target_type": "team",
                "target_id": "REPLACE_WITH_TEAM_OR_DRIVER_ID",
                "claim_type": "upgrade|track_fit|power_unit|ers|aero|launch|weight|weather|reliability|strategy|market",
                "metric": "race_pace|race_execution|qualifying_pace|power_unit|energy_recovery|straight_line_speed|drag_efficiency|low_speed_traction|launch_performance|weight|upgrade_effect|tyre_deg|reliability|wet_skill|strategy",
                "direction": "positive",
                "magnitude": 0.03,
                "confidence": 0.5,
                "uncertainty": 0.35,
                "evidence_text": "One source-backed sentence.",
                "reasoning": "Why this source-backed mechanism should move the selected model metric on this circuit.",
                "review_required": True,
            },
        }

    @staticmethod
    def _source_candidates_template(event: RaceEvent, cutoff: str) -> dict[str, Any]:
        return {
            "event_id": event.event_id,
            "knowledge_cutoff": cutoff,
            "notes": "Fill this with Codex web search/open outputs before writing research_packet_template.json claims.",
            "candidates": [
                {
                    "candidate_id": f"{event.event_id}-source-001",
                    "task_id": f"{event.event_id}:team-updates-track-fit",
                    "query": "REPLACE_WITH_SEARCH_QUERY",
                    "source": "REPLACE_WITH_SOURCE_NAME",
                    "source_class": "media",
                    "url": "REPLACE_WITH_SOURCE_URL",
                    "title": "REPLACE_WITH_PAGE_OR_RESULT_TITLE",
                    "snippet": "Tool-visible source-backed result text or summary.",
                    "published_at": "REPLACE_WITH_ISO_TIMESTAMP_OR_NULL",
                    "observed_at": "REPLACE_WITH_ISO_TIMESTAMP",
                    "captured_by": "codex_web_search",
                    "model_metrics": ["energy_recovery"],
                    "target_hints": ["mercedes"],
                }
            ],
        }

    @staticmethod
    def _research_packet_template(event: RaceEvent, cutoff: str) -> dict[str, Any]:
        claim_id = f"{event.event_id}-codex-001"
        source_url = "REPLACE_WITH_SOURCE_URL"
        return {
            "packet_id": f"{event.event_id}-codex-research-001",
            "event_id": event.event_id,
            "knowledge_cutoff": cutoff,
            "sources": [
                {
                    "source": "REPLACE_WITH_SOURCE_NAME",
                    "url": source_url,
                    "source_class": "media",
                    "published_at": "REPLACE_WITH_ISO_TIMESTAMP",
                    "observed_at": "REPLACE_WITH_ISO_TIMESTAMP",
                    "used_in_claim_ids": [claim_id],
                    "notes": "Why this source is relevant and how reliable it is.",
                }
            ],
            "claims": [
                {
                    "claim_id": claim_id,
                    "event_id": event.event_id,
                    "source": "REPLACE_WITH_SOURCE_NAME",
                    "source_url": source_url,
                    "published_at": "REPLACE_WITH_ISO_TIMESTAMP",
                    "observed_at": "REPLACE_WITH_ISO_TIMESTAMP",
                    "target_type": "team",
                    "target_id": "REPLACE_WITH_TEAM_OR_DRIVER_ID",
                    "claim_type": "upgrade|track_fit|power_unit|ers|aero|launch|weight|weather|reliability|strategy|market",
                    "metric": "race_pace|race_execution|qualifying_pace|power_unit|energy_recovery|straight_line_speed|drag_efficiency|low_speed_traction|launch_performance|weight|upgrade_effect|tyre_deg|reliability|wet_skill|strategy",
                    "direction": "positive",
                    "magnitude": 0.03,
                    "confidence": 0.5,
                    "uncertainty": 0.35,
                    "evidence_text": "One source-backed sentence.",
                    "reasoning": "Why this source-backed mechanism should move the selected model metric on this circuit.",
                    "review_required": True,
                }
            ],
        }

    @staticmethod
    def _source_log_template(event: RaceEvent, cutoff: str) -> dict[str, Any]:
        return {
            "event_id": event.event_id,
            "event_name": event.name,
            "knowledge_cutoff": cutoff,
            "sources": [],
            "source_record_schema": {
                "source": "name",
                "url": "https://...",
                "title": "optional page title",
                "published_at": "ISO timestamp or null",
                "observed_at": "ISO timestamp",
                "knowledge_cutoff": cutoff,
                "cutoff_status": "within_cutoff|after_cutoff_published|after_cutoff_observed|unknown_published_at",
                "source_class": "fia|f1_official|team_or_driver|media|weather|market|structured_data",
                "reliability": "default score assigned from source_class",
                "captured_at": "snapshot capture ISO timestamp",
                "snapshot_path": "data/raw/research_sources/...",
                "historical_archive": {
                    "archive_url": "https://webcache-or-archive.example/snapshot",
                    "archived_at": "ISO timestamp at or before cutoff",
                    "original_url": "https://...",
                    "verified_at": "ISO timestamp when Codex verified the archive",
                    "verification_method": "wayback|memento|publisher_archive|manual_review",
                    "notes": "optional archive proof notes",
                },
                "content_length": 0,
                "used_in_claim_ids": [],
                "notes": "short audit note",
            },
        }

    @classmethod
    def _ensure_source_log(cls, path: Path, event: RaceEvent, cutoff: str) -> None:
        template = cls._source_log_template(event, cutoff)
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                raw = {}
            raw.setdefault("event_id", event.event_id)
            raw.setdefault("event_name", event.name)
            raw.setdefault("knowledge_cutoff", cutoff)
            raw.setdefault("sources", [])
            raw["source_record_schema"] = template["source_record_schema"]
        else:
            raw = template
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
