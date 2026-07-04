"""Batch archive Codex research packets into audited evidence storage."""

from __future__ import annotations

import json
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse, urlunparse

from f1predict.data_sources.augmented import CalendarAugmentedDataSource
from f1predict.domain import EvidenceClaim, EvidenceQuality
from f1predict.domain import FactorTrace, RaceEvent, SeasonState, parse_dt, utc_now
from f1predict.intelligence.codex import CodexEvidenceProvider, EvidencePacketStore
from f1predict.intelligence.evidence_quality import EvidenceQualityScorer
from f1predict.intelligence.evidence_workflow import CodexResearchWorkspaceBuilder
from f1predict.intelligence.factor_contract import validate_factor_claim_contract
from f1predict.intelligence.factor_trace import FACTOR_ROUTES, FactorTraceBuilder
from f1predict.intelligence.source_candidates import CodexSourceCandidateBuilder
from f1predict.intelligence.source_registry import DEFAULT_SOURCE_RELIABILITY, SourceLogAuditor, SourceSnapshotter
from f1predict.storage import RawSnapshotStore, safe_name


class _SeasonDataSource(Protocol):
    def load(self) -> SeasonState: ...


@dataclass(frozen=True)
class ResearchPacketArchiveResult:
    event_id: str
    claim_count: int
    source_count: int
    draft_path: str
    source_log_path: str
    packet_path: str
    can_archive: bool
    findings: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "claim_count": self.claim_count,
            "source_count": self.source_count,
            "draft_path": self.draft_path,
            "source_log_path": self.source_log_path,
            "packet_path": self.packet_path,
            "can_archive": self.can_archive,
            "findings": self.findings,
        }


@dataclass(frozen=True)
class ResearchPacketPreflightFinding:
    severity: str
    code: str
    detail: str
    claim_id: str | None = None
    source_url: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {
            "severity": self.severity,
            "code": self.code,
            "detail": self.detail,
        }
        if self.claim_id:
            payload["claim_id"] = self.claim_id
        if self.source_url:
            payload["source_url"] = self.source_url
        return payload


@dataclass(frozen=True)
class ResearchPacketPreflightClaimRow:
    claim_id: str
    target_type: str
    target_id: str
    metric: str
    direction: str
    route: str | None
    route_status: str | None
    quality_status: str | None
    quality_score: float | None
    source_status: str | None
    triangulation_status: str | None
    conflict_status: str | None
    model_input_weight: float | None
    context_multiplier: float | None
    context_multiplier_reason: str | None
    track_demand_component: str | None
    track_demand_value: float | None
    track_demand_profile: dict[str, Any] | None
    raw_signed_impact: float
    weighted_input_impact: float
    effective_race_input: float
    effective_qualifying_input: float | None
    signed_input_impact: float
    risk_flags: tuple[str, ...]
    source_audit_codes: tuple[str, ...]
    factor_contract_codes: tuple[str, ...]
    route_notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "metric": self.metric,
            "direction": self.direction,
            "route": self.route,
            "route_status": self.route_status,
            "quality_status": self.quality_status,
            "quality_score": self.quality_score,
            "source_status": self.source_status,
            "triangulation_status": self.triangulation_status,
            "conflict_status": self.conflict_status,
            "model_input_weight": self.model_input_weight,
            "context_multiplier": self.context_multiplier,
            "context_multiplier_reason": self.context_multiplier_reason,
            "track_demand_component": self.track_demand_component,
            "track_demand_value": self.track_demand_value,
            "track_demand_profile": self.track_demand_profile,
            "raw_signed_impact": self.raw_signed_impact,
            "weighted_input_impact": self.weighted_input_impact,
            "effective_race_input": self.effective_race_input,
            "effective_qualifying_input": self.effective_qualifying_input,
            "signed_input_impact": self.signed_input_impact,
            "risk_flags": list(self.risk_flags),
            "source_audit_codes": list(self.source_audit_codes),
            "factor_contract_codes": list(self.factor_contract_codes),
            "route_notes": list(self.route_notes),
        }


@dataclass(frozen=True)
class ResearchPacketPreflightResult:
    packet_id: str | None
    event_id: str
    knowledge_cutoff: str | None
    status: str
    claim_count: int
    valid_claim_count: int
    source_count: int
    archive_precheck_can_archive: bool
    blocking_issue_count: int
    warning_count: int
    quality_status_counts: dict[str, int]
    conflict_status_counts: dict[str, int]
    route_status_counts: dict[str, int]
    factor_route_counts: dict[str, int]
    average_model_input_weight: float | None
    min_model_input_weight: float | None
    max_model_input_weight: float | None
    source_audit: dict[str, Any] | None
    source_candidate_audit: dict[str, Any] | None
    findings: tuple[ResearchPacketPreflightFinding, ...]
    claims: tuple[ResearchPacketPreflightClaimRow, ...]
    limitations: tuple[str, ...]

    @property
    def can_archive(self) -> bool:
        return self.archive_precheck_can_archive

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "event_id": self.event_id,
            "knowledge_cutoff": self.knowledge_cutoff,
            "status": self.status,
            "claim_count": self.claim_count,
            "valid_claim_count": self.valid_claim_count,
            "source_count": self.source_count,
            "archive_precheck_can_archive": self.archive_precheck_can_archive,
            "blocking_issue_count": self.blocking_issue_count,
            "warning_count": self.warning_count,
            "quality_status_counts": self.quality_status_counts,
            "conflict_status_counts": self.conflict_status_counts,
            "route_status_counts": self.route_status_counts,
            "factor_route_counts": self.factor_route_counts,
            "average_model_input_weight": self.average_model_input_weight,
            "min_model_input_weight": self.min_model_input_weight,
            "max_model_input_weight": self.max_model_input_weight,
            "source_audit": self.source_audit,
            "source_candidate_audit": self.source_candidate_audit,
            "findings": [finding.to_dict() for finding in self.findings],
            "claims": [claim.to_dict() for claim in self.claims],
            "limitations": list(self.limitations),
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Research Packet Preflight: {self.event_id}",
            "",
            f"- Status: `{self.status}`",
            f"- Archive precheck can archive: `{self.archive_precheck_can_archive}`",
            f"- Claims: `{self.valid_claim_count}/{self.claim_count}` valid",
            f"- Sources: `{self.source_count}`",
            f"- Blocking issues: `{self.blocking_issue_count}`",
            f"- Warnings: `{self.warning_count}`",
            f"- Average model input weight: `{self.average_model_input_weight}`",
            f"- Source candidate audit: `{(self.source_candidate_audit or {}).get('status', 'not_checked')}`",
            "",
            "## Route Counts",
            "",
        ]
        for key, value in sorted(self.factor_route_counts.items()):
            lines.append(f"- `{key}`: `{value}`")
        lines.extend(["", "## Claim Rows", ""])
        if self.claims:
            lines.append("| claim_id | metric | route | route_status | quality | conflict | weight | context | demand | effective | contract | audit |")
            lines.append("| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |")
            for claim in self.claims:
                audit = ", ".join(claim.source_audit_codes) or "none"
                contract = ", ".join(claim.factor_contract_codes) or "ok"
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            claim.claim_id,
                            claim.metric,
                            claim.route or "n/a",
                            claim.route_status or "n/a",
                            claim.quality_status or "n/a",
                            claim.conflict_status or "n/a",
                            str(claim.model_input_weight),
                            str(claim.context_multiplier),
                            str(claim.track_demand_value),
                            str(claim.effective_race_input),
                            contract,
                            audit,
                        ]
                    )
                    + " |"
                )
        else:
            lines.append("No valid claim rows.")
        if self.findings:
            lines.extend(["", "## Findings", ""])
            for finding in self.findings:
                claim = f" claim={finding.claim_id}" if finding.claim_id else ""
                source = f" source={finding.source_url}" if finding.source_url else ""
                lines.append(f"- `{finding.severity}` `{finding.code}`{claim}{source}: {finding.detail}")
        lines.extend(["", "## Limitations", ""])
        lines.extend(f"- {item}" for item in self.limitations)
        lines.append("")
        return "\n".join(lines)


class ResearchPacketError(ValueError):
    """Raised when a Codex research packet cannot be archived."""


class CodexResearchPacketPreflight:
    """Dry-run validation and simulator-routing preview for research packets."""

    limitations = (
        "Preflight is diagnostic only: it uses an existing source_log.json when available, otherwise builds a synthetic source log.",
        "A passing preflight must still be archived with archive-research-packet before claims enter predictions.",
        "Impact movement is not measured here; model input weights and factor routes are previewed before simulation.",
    )

    def __init__(
        self,
        data_source: _SeasonDataSource | None = None,
        factor_trace_builder: FactorTraceBuilder | None = None,
    ) -> None:
        self.data_source = data_source or CalendarAugmentedDataSource()
        self.factor_trace_builder = factor_trace_builder or FactorTraceBuilder()

    def preflight_file(
        self,
        path: Path | str,
        event_id: str | None = None,
        knowledge_cutoff: str | None = None,
        source_candidate_report_path: Path | str | None = None,
        source_candidates_input_path: Path | str | None = None,
    ) -> ResearchPacketPreflightResult:
        packet_path = Path(path)
        try:
            packet = json.loads(packet_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ResearchPacketError(f"{packet_path}: invalid JSON: {exc}") from exc
        inferred_candidates = packet_path.parent / "source_candidates.json"
        inferred_source_log = packet_path.parent / "source_log.json"
        return self.preflight_packet(
            packet,
            event_id=event_id,
            knowledge_cutoff=knowledge_cutoff,
            source_candidate_report_path=source_candidate_report_path,
            source_candidates_input_path=source_candidates_input_path or (inferred_candidates if inferred_candidates.exists() else None),
            source_log_path=inferred_source_log if inferred_source_log.exists() else None,
        )

    def preflight_packet(
        self,
        packet: dict[str, Any],
        event_id: str | None = None,
        knowledge_cutoff: str | None = None,
        source_candidate_report_path: Path | str | None = None,
        source_candidates_input_path: Path | str | None = None,
        source_log_path: Path | str | None = None,
    ) -> ResearchPacketPreflightResult:
        findings: list[ResearchPacketPreflightFinding] = []
        resolved_event = event_id or str(packet.get("event_id") or "")
        if not resolved_event:
            findings.append(
                ResearchPacketPreflightFinding("error", "missing_event_id", "research packet requires event_id")
            )
            resolved_event = "unknown_event"
        cutoff = knowledge_cutoff or packet.get("knowledge_cutoff")
        cutoff_text = str(cutoff) if cutoff is not None else None
        cutoff_dt = self._normalize_cutoff(cutoff_text, findings)

        sources = self._packet_objects(packet, "sources", findings)
        claims_raw = self._packet_objects(packet, "claims", findings)
        if self._has_unfilled_placeholders(sources) or self._has_unfilled_placeholders(claims_raw):
            findings.append(
                ResearchPacketPreflightFinding(
                    "warning",
                    "research_packet_template_unfilled",
                    "research_packet_template.json still contains REPLACE_WITH placeholders; fill source-backed rows before running full archive preflight.",
                )
            )
            source_candidate_audit = self._source_candidate_audit(
                resolved_event,
                cutoff_text,
                [],
                findings,
                source_candidate_report_path=source_candidate_report_path,
                source_candidates_input_path=source_candidates_input_path,
            )
            return self._result(
                packet=packet,
                event_id=resolved_event,
                knowledge_cutoff=cutoff_text,
                claim_count=len(claims_raw),
                valid_claims=[],
                source_count=len(sources),
                source_audit=None,
                source_candidate_audit=source_candidate_audit,
                findings=findings,
                evidence_quality=[],
                factor_trace=[],
                status_override="research_packet_template_unfilled",
            )

        claims = self._claims(claims_raw, resolved_event, findings)
        self._validate_source_links(sources, {claim.claim_id for claim in claims}, findings)
        self._validate_source_metadata(sources, findings)
        source_candidate_audit = self._source_candidate_audit(
            resolved_event,
            cutoff_text,
            sources,
            findings,
            source_candidate_report_path=source_candidate_report_path,
            source_candidates_input_path=source_candidates_input_path,
        )

        if not claims:
            return self._result(
                packet=packet,
                event_id=resolved_event,
                knowledge_cutoff=cutoff_text,
                claim_count=len(claims_raw),
                valid_claims=[],
                source_count=len(sources),
                source_audit=None,
                source_candidate_audit=source_candidate_audit,
                findings=findings,
                evidence_quality=[],
                factor_trace=[],
            )

        season = self._load_season(findings)
        event = self._event_for_preflight(season, resolved_event, findings)
        existing_source_log_path = Path(source_log_path) if source_log_path else None
        if existing_source_log_path and existing_source_log_path.exists():
            source_audit = self._source_audit(
                claims,
                existing_source_log_path,
                cutoff_text if cutoff_dt else None,
                findings,
            )
            quality_root = existing_source_log_path.parent.parent
            quality = self._quality_preflight(
                resolved_event,
                claims,
                quality_root,
                cutoff_dt,
                findings,
            )
        else:
            with tempfile.TemporaryDirectory(prefix="f1predict_preflight_") as temp_dir:
                research_root = Path(temp_dir)
                source_log_path = self._write_synthetic_source_log(
                    research_root,
                    event=event,
                    event_id=resolved_event,
                    sources=sources,
                    knowledge_cutoff=cutoff_text,
                    cutoff_dt=cutoff_dt,
                )
                source_audit = self._source_audit(claims, source_log_path, cutoff_text if cutoff_dt else None, findings)
                quality = self._quality_preflight(
                    resolved_event,
                    claims,
                    research_root,
                    cutoff_dt,
                    findings,
                )
        try:
            factor_trace = self.factor_trace_builder.build(season, event, claims, [], quality)
        except Exception as exc:  # noqa: BLE001 - expose route failures as packet findings.
            findings.append(
                ResearchPacketPreflightFinding(
                    "error",
                    "factor_trace_preflight_failed",
                    f"Factor routing preflight failed: {exc}",
                )
            )
            factor_trace = []

        return self._result(
            packet=packet,
            event_id=resolved_event,
            knowledge_cutoff=cutoff_text,
            claim_count=len(claims_raw),
            valid_claims=claims,
            source_count=len(sources),
            source_audit=source_audit,
            source_candidate_audit=source_candidate_audit,
            findings=findings,
            evidence_quality=quality,
            factor_trace=factor_trace,
        )

    @classmethod
    def write_outputs(
        cls,
        result: ResearchPacketPreflightResult,
        json_output: Path | str | None = None,
        markdown_output: Path | str | None = None,
    ) -> dict[str, str]:
        written: dict[str, str] = {}
        if json_output:
            path = Path(json_output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            written["json_output"] = str(path)
        if markdown_output:
            path = Path(markdown_output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(result.to_markdown(), encoding="utf-8")
            written["markdown_output"] = str(path)
        return written

    @staticmethod
    def _packet_objects(
        packet: dict[str, Any],
        name: str,
        findings: list[ResearchPacketPreflightFinding],
    ) -> list[dict[str, Any]]:
        value = packet.get(name)
        if not isinstance(value, list):
            findings.append(
                ResearchPacketPreflightFinding("error", f"invalid_{name}_field", f"research packet field {name!r} must be a list")
            )
            return []
        items = [item for item in value if isinstance(item, dict)]
        if len(items) != len(value):
            findings.append(
                ResearchPacketPreflightFinding("error", f"invalid_{name}_item", f"research packet field {name!r} must contain only objects")
            )
        return items

    @classmethod
    def _has_unfilled_placeholders(cls, value: Any) -> bool:
        if isinstance(value, str):
            return "REPLACE_WITH" in value
        if isinstance(value, dict):
            return any(cls._has_unfilled_placeholders(item) for item in value.values())
        if isinstance(value, (list, tuple)):
            return any(cls._has_unfilled_placeholders(item) for item in value)
        return False

    @classmethod
    def _claims(
        cls,
        claims_raw: list[dict[str, Any]],
        event_id: str,
        findings: list[ResearchPacketPreflightFinding],
    ) -> list[EvidenceClaim]:
        claims: list[EvidenceClaim] = []
        for index, raw in enumerate(claims_raw, start=1):
            claim_id = str(raw.get("claim_id") or f"claims[{index}]")
            try:
                claim = EvidenceClaim.from_dict(raw)
            except Exception as exc:  # noqa: BLE001 - preflight should expose exact schema failures.
                findings.append(
                    ResearchPacketPreflightFinding(
                        "error",
                        "invalid_claim_schema",
                        f"claims[{index}] is not a valid EvidenceClaim: {exc}",
                        claim_id=claim_id,
                    )
                )
                continue
            claims.append(claim)
            if claim.event_id != event_id:
                findings.append(
                    ResearchPacketPreflightFinding(
                        "error",
                        "claim_event_mismatch",
                        f"claim event_id={claim.event_id!r} does not match requested event_id={event_id!r}",
                        claim_id=claim.claim_id,
                    )
                )
            if not (0.0 <= claim.confidence <= 1.0):
                findings.append(
                    ResearchPacketPreflightFinding("error", "invalid_claim_confidence", "confidence must be 0..1", claim_id=claim.claim_id)
                )
            if not (0.0 <= claim.uncertainty <= 1.0):
                findings.append(
                    ResearchPacketPreflightFinding("error", "invalid_claim_uncertainty", "uncertainty must be 0..1", claim_id=claim.claim_id)
                )
            if claim.magnitude < 0.0:
                findings.append(
                    ResearchPacketPreflightFinding("error", "invalid_claim_magnitude", "magnitude must be non-negative", claim_id=claim.claim_id)
                )
            if claim.direction not in {"positive", "negative", "neutral"}:
                findings.append(
                    ResearchPacketPreflightFinding("error", "invalid_claim_direction", "direction must be positive, negative, or neutral", claim_id=claim.claim_id)
                )
            if claim.metric not in FACTOR_ROUTES:
                findings.append(
                    ResearchPacketPreflightFinding(
                        "warning",
                        "unsupported_metric_route",
                        "metric is accepted as raw data but has no simulator route",
                        claim_id=claim.claim_id,
                    )
                )
            for issue in validate_factor_claim_contract(claim):
                findings.append(
                    ResearchPacketPreflightFinding(
                        issue.severity,
                        issue.code,
                        issue.detail,
                        claim_id=claim.claim_id,
                    )
                )
            for field_name, value in (("published_at", claim.published_at), ("observed_at", claim.observed_at)):
                if cls._parse_dt(value) is None:
                    findings.append(
                        ResearchPacketPreflightFinding(
                            "error",
                            f"invalid_claim_{field_name}",
                            f"{field_name} is not a parseable ISO timestamp",
                            claim_id=claim.claim_id,
                        )
                    )
        return claims

    @staticmethod
    def _validate_source_links(
        sources: list[dict[str, Any]],
        claim_ids: set[str],
        findings: list[ResearchPacketPreflightFinding],
    ) -> None:
        linked: set[str] = set()
        for index, source in enumerate(sources, start=1):
            missing = [
                name
                for name in ("url", "source", "source_class", "used_in_claim_ids")
                if name not in source
            ]
            if missing:
                findings.append(
                    ResearchPacketPreflightFinding(
                        "error",
                        "source_missing_required_fields",
                        f"sources[{index}] missing required fields: {', '.join(missing)}",
                        source_url=str(source.get("url") or ""),
                    )
                )
            used = source.get("used_in_claim_ids")
            if not isinstance(used, list) or not used:
                findings.append(
                    ResearchPacketPreflightFinding(
                        "error",
                        "source_unlinked",
                        f"sources[{index}].used_in_claim_ids must be a non-empty list",
                        source_url=str(source.get("url") or ""),
                    )
                )
                continue
            unknown = sorted(str(item) for item in used if str(item) not in claim_ids)
            if unknown:
                findings.append(
                    ResearchPacketPreflightFinding(
                        "error",
                        "source_links_unknown_claims",
                        f"sources[{index}] links unknown claim ids: {', '.join(unknown)}",
                        source_url=str(source.get("url") or ""),
                    )
                )
            linked.update(str(item) for item in used)
        unlinked = sorted(claim_ids - linked)
        for claim_id in unlinked:
            findings.append(
                ResearchPacketPreflightFinding(
                    "error",
                    "claim_missing_source_link",
                    "claim is not linked by any source.used_in_claim_ids",
                    claim_id=claim_id,
                )
            )

    @classmethod
    def _validate_source_metadata(
        cls,
        sources: list[dict[str, Any]],
        findings: list[ResearchPacketPreflightFinding],
    ) -> None:
        for index, source in enumerate(sources, start=1):
            url = str(source.get("url") or "")
            source_class = str(source.get("source_class") or "").strip().lower()
            if source_class and source_class not in DEFAULT_SOURCE_RELIABILITY:
                findings.append(
                    ResearchPacketPreflightFinding(
                        "error",
                        "unsupported_source_class",
                        f"sources[{index}].source_class={source_class!r} is not supported",
                        source_url=url,
                    )
                )
            for field_name in ("published_at", "observed_at"):
                value = source.get(field_name)
                if value is not None and cls._parse_dt(str(value)) is None:
                    findings.append(
                        ResearchPacketPreflightFinding(
                            "error",
                            f"invalid_source_{field_name}",
                            f"sources[{index}].{field_name} is not a parseable ISO timestamp",
                            source_url=url,
                        )
                    )

    def _source_candidate_audit(
        self,
        event_id: str,
        knowledge_cutoff: str | None,
        sources: list[dict[str, Any]],
        findings: list[ResearchPacketPreflightFinding],
        source_candidate_report_path: Path | str | None = None,
        source_candidates_input_path: Path | str | None = None,
    ) -> dict[str, Any]:
        source_urls = [
            str(source.get("url") or "").strip()
            for source in sources
            if str(source.get("url") or "").strip()
        ]
        report, report_source, report_path = self._load_source_candidate_report(
            event_id,
            knowledge_cutoff,
            source_candidate_report_path=source_candidate_report_path,
            source_candidates_input_path=source_candidates_input_path,
        )
        if report is None:
            if source_urls:
                findings.append(
                    ResearchPacketPreflightFinding(
                        "warning",
                        "missing_source_candidate_audit",
                        "No source-candidate audit was found; run codex-source-candidates before turning Codex search/open results into claims.",
                    )
                )
            return {
                "status": "missing_source_candidate_audit",
                "source": "not_found",
                "candidate_count": 0,
                "matched_source_count": 0,
                "unmatched_source_count": len(source_urls),
                "not_ready_source_count": 0,
                "blocked_candidate_source_count": 0,
                "report_path": None,
            }

        rows = report.get("rows") if isinstance(report.get("rows"), list) else []
        row_by_url: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = _canonical_url(str(row.get("url") or ""))
            if not key:
                continue
            existing = row_by_url.get(key)
            if existing is None or _candidate_status_rank(str(row.get("status") or "")) < _candidate_status_rank(str(existing.get("status") or "")):
                row_by_url[key] = row

        matched = 0
        unmatched = 0
        not_ready = 0
        blocked = 0
        for source in sources:
            url = str(source.get("url") or "").strip()
            if not url:
                continue
            candidate = row_by_url.get(_canonical_url(url))
            if candidate is None:
                unmatched += 1
                findings.append(
                    ResearchPacketPreflightFinding(
                        "error",
                        "source_candidate_missing",
                        "Research packet source URL was not present in the audited source candidates.",
                        source_url=url,
                    )
                )
                continue
            matched += 1
            candidate_event = str(candidate.get("event_id") or event_id)
            if candidate_event != event_id:
                blocked += 1
                findings.append(
                    ResearchPacketPreflightFinding(
                        "error",
                        "source_candidate_event_mismatch",
                        f"Audited candidate event_id={candidate_event!r} does not match research packet event_id={event_id!r}.",
                        source_url=url,
                    )
                )
            status = str(candidate.get("status") or "")
            if status == "candidate_ready_for_claim_review":
                continue
            if status == "candidate_blocked":
                blocked += 1
            else:
                not_ready += 1
            findings.append(
                ResearchPacketPreflightFinding(
                    "error",
                    "source_candidate_not_ready",
                    f"Audited candidate status={status or 'unknown'} must be ready before source-backed claims can be archived.",
                    source_url=url,
                )
            )

        if str(report.get("event_id") or event_id) != event_id:
            findings.append(
                ResearchPacketPreflightFinding(
                    "error",
                    "source_candidate_report_event_mismatch",
                    f"Source-candidate report event_id={report.get('event_id')!r} does not match research packet event_id={event_id!r}.",
                )
            )

        return {
            "status": report.get("status"),
            "source": report_source,
            "candidate_count": int(report.get("candidate_count") or len(rows)),
            "review_ready_count": int(report.get("review_ready_count") or 0),
            "blocked_count": int(report.get("blocked_count") or 0),
            "warning_count": int(report.get("warning_count") or 0),
            "matched_source_count": matched,
            "unmatched_source_count": unmatched,
            "not_ready_source_count": not_ready,
            "blocked_candidate_source_count": blocked,
            "report_path": str(report_path) if report_path else None,
        }

    def _load_source_candidate_report(
        self,
        event_id: str,
        knowledge_cutoff: str | None,
        source_candidate_report_path: Path | str | None = None,
        source_candidates_input_path: Path | str | None = None,
    ) -> tuple[dict[str, Any] | None, str, Path | None]:
        candidate_report_path = (
            Path(source_candidate_report_path)
            if source_candidate_report_path
            else Path("reports") / "research_candidates" / f"{event_id}.json"
        )
        if candidate_report_path.exists():
            return json.loads(candidate_report_path.read_text(encoding="utf-8-sig")), "candidate_report", candidate_report_path
        if source_candidates_input_path:
            input_path = Path(source_candidates_input_path)
            if input_path.exists():
                report = CodexSourceCandidateBuilder().build_file(
                    event_id,
                    input_path,
                    knowledge_cutoff=knowledge_cutoff,
                )
                return report.to_dict(), "candidate_input_live_audit", input_path
        return None, "not_found", None

    @staticmethod
    def _load_event(
        season: SeasonState,
        event_id: str,
    ) -> RaceEvent | None:
        return next((event for event in season.events if event.event_id == event_id), None)

    def _load_season(self, findings: list[ResearchPacketPreflightFinding]) -> SeasonState:
        try:
            return self.data_source.load()
        except Exception as exc:  # noqa: BLE001 - preflight should still show packet-level findings.
            findings.append(
                ResearchPacketPreflightFinding(
                    "warning",
                    "season_load_failed",
                    f"Could not load season data for target/track validation: {exc}",
                )
            )
            return SeasonState(season=0, teams={}, drivers={}, events=[], markets=[])

    def _event_for_preflight(
        self,
        season: SeasonState,
        event_id: str,
        findings: list[ResearchPacketPreflightFinding],
    ) -> RaceEvent:
        event = self._load_event(season, event_id)
        if event is not None:
            return event
        findings.append(
            ResearchPacketPreflightFinding(
                "warning",
                "event_not_in_season",
                "event_id was not found in the loaded season; route preview uses an unknown-track placeholder.",
            )
        )
        return RaceEvent(
            event_id=event_id,
            name=event_id,
            round_number=0,
            date="",
            track_type="unknown",
            laps=0,
            completed=False,
            weather_prior={},
            track_map=[],
        )

    @classmethod
    def _write_synthetic_source_log(
        cls,
        research_root: Path,
        event: RaceEvent,
        event_id: str,
        sources: list[dict[str, Any]],
        knowledge_cutoff: str | None,
        cutoff_dt: datetime | None,
    ) -> Path:
        directory = research_root / safe_name(event_id)
        directory.mkdir(parents=True, exist_ok=True)
        captured_at = utc_now().replace(microsecond=0).isoformat()
        records = []
        for index, source in enumerate(sources, start=1):
            source_class = str(source.get("source_class") or "").strip().lower()
            reliability = DEFAULT_SOURCE_RELIABILITY.get(source_class)
            published_at = str(source.get("published_at")) if source.get("published_at") is not None else None
            observed_at = str(source.get("observed_at") or published_at or captured_at)
            records.append(
                {
                    "source": str(source.get("source") or ""),
                    "url": str(source.get("url") or ""),
                    "title": str(source.get("title") or "") or None,
                    "published_at": published_at,
                    "observed_at": observed_at,
                    "knowledge_cutoff": knowledge_cutoff,
                    "cutoff_status": cls._cutoff_status(published_at, observed_at, cutoff_dt),
                    "source_class": source_class or None,
                    "reliability": reliability,
                    "captured_at": captured_at,
                    "snapshot_path": f"preflight://{event_id}/{index}",
                    "content_length": len(str(source.get("content") or "")),
                    "used_in_claim_ids": [str(item) for item in source.get("used_in_claim_ids", [])],
                    "notes": str(source.get("notes") or "preflight synthetic source row"),
                    **(
                        {"historical_archive": source["historical_archive"]}
                        if isinstance(source.get("historical_archive"), dict)
                        else {}
                    ),
                }
            )
        path = directory / "source_log.json"
        path.write_text(
            json.dumps(
                {
                    "event_id": event_id,
                    "event_name": event.name,
                    "knowledge_cutoff": knowledge_cutoff,
                    "preflight_only": True,
                    "sources": records,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return path

    @staticmethod
    def _source_audit(
        claims: list[EvidenceClaim],
        source_log_path: Path,
        knowledge_cutoff: str | None,
        findings: list[ResearchPacketPreflightFinding],
    ):
        try:
            audit = SourceLogAuditor().audit_claims(claims, source_log_path, knowledge_cutoff)
        except Exception as exc:  # noqa: BLE001 - report source-audit exceptions as preflight blockers.
            findings.append(
                ResearchPacketPreflightFinding(
                    "error",
                    "source_audit_failed",
                    f"Synthetic source audit failed: {exc}",
                )
            )
            return None
        for finding in audit.findings:
            findings.append(
                ResearchPacketPreflightFinding(
                    finding.severity,
                    f"source_audit_{finding.code}",
                    finding.detail,
                    claim_id=finding.claim_id,
                )
            )
        return audit.to_dict()

    @staticmethod
    def _quality_preflight(
        event_id: str,
        claims: list[EvidenceClaim],
        research_root: Path,
        cutoff_dt: datetime | None,
        findings: list[ResearchPacketPreflightFinding],
    ) -> list[EvidenceQuality]:
        try:
            return EvidenceQualityScorer(research_root=research_root).score_event(
                event_id,
                claims,
                [],
                cutoff_dt,
            )
        except Exception as exc:  # noqa: BLE001 - preflight should return findings instead of crashing.
            findings.append(
                ResearchPacketPreflightFinding(
                    "error",
                    "quality_preflight_failed",
                    f"Evidence quality preflight failed: {exc}",
                )
            )
            return []

    @classmethod
    def _result(
        cls,
        packet: dict[str, Any],
        event_id: str,
        knowledge_cutoff: str | None,
        claim_count: int,
        valid_claims: list[EvidenceClaim],
        source_count: int,
        source_audit: dict[str, Any] | None,
        source_candidate_audit: dict[str, Any] | None,
        findings: list[ResearchPacketPreflightFinding],
        evidence_quality: list[EvidenceQuality],
        factor_trace: list[FactorTrace],
        status_override: str | None = None,
    ) -> ResearchPacketPreflightResult:
        by_claim_trace = {row.claim_id: row for row in factor_trace}
        by_claim_quality = {row.claim_id: row for row in evidence_quality}
        source_codes_by_claim: dict[str, list[str]] = {}
        factor_contract_codes_by_claim: dict[str, list[str]] = {}
        for finding in findings:
            if finding.claim_id and finding.code.startswith("source_audit_"):
                source_codes_by_claim.setdefault(finding.claim_id, []).append(finding.code.removeprefix("source_audit_"))
            if finding.claim_id and finding.code.startswith("factor_contract_"):
                factor_contract_codes_by_claim.setdefault(finding.claim_id, []).append(finding.code)
        claim_rows = tuple(
            cls._claim_row(
                claim,
                by_claim_trace.get(claim.claim_id),
                by_claim_quality.get(claim.claim_id),
                source_codes_by_claim,
                factor_contract_codes_by_claim,
            )
            for claim in valid_claims
        )
        model_weights = [
            row.model_input_weight for row in claim_rows
            if row.model_input_weight is not None
        ]
        blocking_count = sum(1 for finding in findings if finding.severity == "error")
        warning_count = sum(1 for finding in findings if finding.severity == "warning")
        source_can_archive = bool(source_audit and source_audit.get("can_archive", False))
        archive_precheck = bool(valid_claims) and blocking_count == 0 and source_can_archive
        status = status_override or ("preflight_passed" if archive_precheck else "preflight_failed")
        return ResearchPacketPreflightResult(
            packet_id=str(packet.get("packet_id")) if packet.get("packet_id") is not None else None,
            event_id=event_id,
            knowledge_cutoff=knowledge_cutoff,
            status=status,
            claim_count=claim_count,
            valid_claim_count=len(valid_claims),
            source_count=source_count,
            archive_precheck_can_archive=archive_precheck,
            blocking_issue_count=blocking_count,
            warning_count=warning_count,
            quality_status_counts=dict(sorted(Counter(row.quality_status or "unknown" for row in claim_rows).items())),
            conflict_status_counts=dict(sorted(Counter(row.conflict_status or "unknown" for row in claim_rows).items())),
            route_status_counts=dict(sorted(Counter(row.route_status or "unknown" for row in claim_rows).items())),
            factor_route_counts=dict(sorted(Counter(row.route or "unknown" for row in claim_rows).items())),
            average_model_input_weight=round(sum(model_weights) / len(model_weights), 4) if model_weights else None,
            min_model_input_weight=min(model_weights) if model_weights else None,
            max_model_input_weight=max(model_weights) if model_weights else None,
            source_audit=source_audit,
            source_candidate_audit=source_candidate_audit,
            findings=tuple(findings),
            claims=claim_rows,
            limitations=cls.limitations,
        )

    @staticmethod
    def _claim_row(
        claim: EvidenceClaim,
        trace: FactorTrace | None,
        quality: EvidenceQuality | None,
        source_codes_by_claim: dict[str, list[str]],
        factor_contract_codes_by_claim: dict[str, list[str]],
    ) -> ResearchPacketPreflightClaimRow:
        return ResearchPacketPreflightClaimRow(
            claim_id=claim.claim_id,
            target_type=claim.target_type,
            target_id=claim.target_id,
            metric=claim.metric,
            direction=claim.direction,
            route=trace.route if trace else None,
            route_status=trace.route_status if trace else None,
            quality_status=quality.quality_status if quality else trace.quality_status if trace else None,
            quality_score=quality.quality_score if quality else None,
            source_status=quality.source_status if quality else trace.source_status if trace else None,
            triangulation_status=quality.triangulation_status if quality else trace.triangulation_status if trace else None,
            conflict_status=quality.conflict_status if quality else trace.conflict_status if trace else None,
            model_input_weight=quality.model_input_weight if quality else trace.model_input_weight if trace else None,
            context_multiplier=trace.context_multiplier if trace else None,
            context_multiplier_reason=trace.context_multiplier_reason if trace else None,
            track_demand_component=trace.track_demand_component if trace else None,
            track_demand_value=trace.track_demand_value if trace else None,
            track_demand_profile=trace.track_demand_profile if trace else None,
            raw_signed_impact=trace.raw_signed_impact if trace else round(claim.signed_impact(), 4),
            weighted_input_impact=trace.weighted_input_impact if trace else round(claim.signed_impact(), 4),
            effective_race_input=trace.effective_race_input if trace else round(claim.signed_impact(), 4),
            effective_qualifying_input=trace.effective_qualifying_input if trace else None,
            signed_input_impact=round(
                trace.signed_input_impact if trace else claim.signed_impact(),
                4,
            ),
            risk_flags=quality.risk_flags if quality else trace.risk_flags if trace else (),
            source_audit_codes=tuple(dict.fromkeys(source_codes_by_claim.get(claim.claim_id, []))),
            factor_contract_codes=tuple(dict.fromkeys(factor_contract_codes_by_claim.get(claim.claim_id, []))),
            route_notes=trace.route_notes if trace else (),
        )

    @staticmethod
    def _normalize_cutoff(
        value: str | None,
        findings: list[ResearchPacketPreflightFinding],
    ) -> datetime | None:
        if not value:
            return None
        parsed = CodexResearchPacketPreflight._parse_dt(value)
        if parsed is None:
            findings.append(
                ResearchPacketPreflightFinding(
                    "error",
                    "invalid_knowledge_cutoff",
                    f"knowledge_cutoff is not a parseable ISO timestamp: {value}",
                )
            )
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _cutoff_status(
        published_at: str | None,
        observed_at: str | None,
        cutoff_dt: datetime | None,
    ) -> str:
        if cutoff_dt is None:
            return "no_cutoff"
        published = CodexResearchPacketPreflight._parse_dt(published_at)
        observed = CodexResearchPacketPreflight._parse_dt(observed_at)
        if published_at and published is None:
            return "invalid_published_at"
        if observed_at and observed is None:
            return "invalid_observed_at"
        if published is not None and CodexResearchPacketPreflight._as_utc(published) > cutoff_dt:
            return "after_cutoff_published"
        if observed is not None and CodexResearchPacketPreflight._as_utc(observed) > cutoff_dt:
            return "after_cutoff_observed"
        if published is None:
            return "unknown_published_at"
        return "within_cutoff"

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return parse_dt(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class CodexResearchPacketArchiver:
    """Archives a Codex-produced sources+claims manifest with source auditing.

    The manifest is the handoff boundary for tool-using Codex research. Codex can
    inspect arbitrary web/PDF/market sources, but the model only receives claims
    after this class snapshots the sources, validates the JSONL schema, and
    checks point-in-time source linkage.
    """

    def __init__(
        self,
        research_root: Path | str = Path("data/research"),
        raw_store: RawSnapshotStore | None = None,
        packet_root: Path | str = Path("data/evidence"),
        evidence_provider: CodexEvidenceProvider | None = None,
        workspace_builder: CodexResearchWorkspaceBuilder | None = None,
    ) -> None:
        self.research_root = Path(research_root)
        self.raw_store = raw_store or RawSnapshotStore()
        self.packet_root = Path(packet_root)
        self.evidence_provider = evidence_provider or CodexEvidenceProvider(packet_root=packet_root)
        self.workspace_builder = workspace_builder or CodexResearchWorkspaceBuilder()

    def archive_file(
        self,
        path: Path | str,
        event_id: str | None = None,
        knowledge_cutoff: str | None = None,
        replace_draft: bool = True,
    ) -> ResearchPacketArchiveResult:
        packet_path = Path(path)
        try:
            packet = json.loads(packet_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ResearchPacketError(f"{packet_path}: invalid JSON: {exc}") from exc
        return self.archive_packet(packet, event_id, knowledge_cutoff, replace_draft)

    def archive_packet(
        self,
        packet: dict[str, Any],
        event_id: str | None = None,
        knowledge_cutoff: str | None = None,
        replace_draft: bool = True,
    ) -> ResearchPacketArchiveResult:
        resolved_event = event_id or str(packet.get("event_id") or "")
        if not resolved_event:
            raise ResearchPacketError("research packet requires event_id")
        cutoff = knowledge_cutoff or packet.get("knowledge_cutoff")
        if cutoff is not None:
            cutoff = str(cutoff)

        sources = self._list_field(packet, "sources")
        claims_raw = self._list_field(packet, "claims")
        if not sources:
            raise ResearchPacketError("research packet requires at least one source")
        if not claims_raw:
            raise ResearchPacketError("research packet requires at least one claim")

        directory = self.research_root / resolved_event
        directory.mkdir(parents=True, exist_ok=True)
        try:
            self.workspace_builder.write_event_workspace(
                resolved_event,
                knowledge_cutoff=cutoff,
                output_dir=self.research_root,
            )
        except ValueError:
            self._ensure_minimal_source_log(directory, resolved_event, cutoff)

        claims = [EvidenceClaim.from_dict(raw) for raw in claims_raw]
        wrong_event = [claim.claim_id for claim in claims if claim.event_id != resolved_event]
        if wrong_event:
            raise ResearchPacketError(
                f"claims use a different event_id: {', '.join(wrong_event)}"
            )
        claim_ids = {claim.claim_id for claim in claims}
        self._validate_source_links(sources, claim_ids)

        snapshotter = SourceSnapshotter(
            raw_store=self.raw_store,
            research_root=self.research_root,
        )
        for source in sources:
            used_ids = [str(item) for item in source.get("used_in_claim_ids", [])]
            snapshotter.snapshot_url(
                event_id=resolved_event,
                url=str(source["url"]),
                source=str(source["source"]),
                source_class=str(source["source_class"]),
                published_at=source.get("published_at"),
                observed_at=source.get("observed_at"),
                knowledge_cutoff=cutoff,
                notes=str(source.get("notes", "")),
                used_in_claim_ids=used_ids,
                content_override=source.get("content"),
                historical_archive=source.get("historical_archive"),
            )

        draft_path = directory / "draft_evidence.jsonl"
        mode = "w" if replace_draft else "a"
        with draft_path.open(mode, encoding="utf-8") as handle:
            for claim in claims:
                handle.write(json.dumps(claim.__dict__, ensure_ascii=False, sort_keys=True))
                handle.write("\n")

        validated_claims = self.evidence_provider.validate_event_file(resolved_event, draft_path)
        source_log_path = directory / "source_log.json"
        audit = SourceLogAuditor().audit_claims(
            validated_claims,
            source_log_path,
            knowledge_cutoff=cutoff,
        )
        if not audit.can_archive:
            raise ResearchPacketError(
                f"research packet source audit failed: {json.dumps(audit.to_dict(), ensure_ascii=False)}"
            )
        archived_path = EvidencePacketStore(self.packet_root).write_event_packet(
            resolved_event,
            validated_claims,
            source_log_path=source_log_path,
            params={"research_packet": packet.get("packet_id"), "source_audit": audit.to_dict()},
        )
        return ResearchPacketArchiveResult(
            event_id=resolved_event,
            claim_count=len(validated_claims),
            source_count=len(sources),
            draft_path=str(draft_path),
            source_log_path=str(source_log_path),
            packet_path=str(archived_path),
            can_archive=audit.can_archive,
            findings=[finding.to_dict() for finding in audit.findings],
        )

    @staticmethod
    def _list_field(packet: dict[str, Any], name: str) -> list[dict[str, Any]]:
        value = packet.get(name)
        if not isinstance(value, list):
            raise ResearchPacketError(f"research packet field {name!r} must be a list")
        items = [item for item in value if isinstance(item, dict)]
        if len(items) != len(value):
            raise ResearchPacketError(f"research packet field {name!r} must contain only objects")
        return items

    @staticmethod
    def _validate_source_links(sources: list[dict[str, Any]], claim_ids: set[str]) -> None:
        linked: set[str] = set()
        for index, source in enumerate(sources, start=1):
            missing = [
                name
                for name in ("url", "source", "source_class", "used_in_claim_ids")
                if name not in source
            ]
            if missing:
                raise ResearchPacketError(
                    f"sources[{index}] missing required fields: {', '.join(missing)}"
                )
            used = source.get("used_in_claim_ids")
            if not isinstance(used, list) or not used:
                raise ResearchPacketError(
                    f"sources[{index}].used_in_claim_ids must be a non-empty list"
                )
            unknown = sorted(str(item) for item in used if str(item) not in claim_ids)
            if unknown:
                raise ResearchPacketError(
                    f"sources[{index}] links unknown claim ids: {', '.join(unknown)}"
                )
            linked.update(str(item) for item in used)
        unlinked = sorted(claim_ids - linked)
        if unlinked:
            raise ResearchPacketError(f"claims are not linked to any source: {', '.join(unlinked)}")

    @staticmethod
    def _ensure_minimal_source_log(directory: Path, event_id: str, cutoff: str | None) -> None:
        path = directory / "source_log.json"
        if path.exists():
            return
        payload = {
            "event_id": event_id,
            "event_name": event_id,
            "knowledge_cutoff": cutoff,
            "sources": [],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _candidate_status_rank(status: str) -> int:
    if status == "candidate_ready_for_claim_review":
        return 0
    if status == "candidate_needs_review":
        return 1
    if status == "candidate_blocked":
        return 2
    return 3


def _canonical_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if not parsed.scheme or not parsed.netloc:
        return value.strip()
    path = parsed.path.rstrip("/") or "/"
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            parsed.query,
            "",
        )
    )
