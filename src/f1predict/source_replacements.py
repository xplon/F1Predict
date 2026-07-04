"""Replacement-source candidates for unresolved source archive blockers."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from f1predict.data_sources.http_clients import HttpTextClient
from f1predict.domain import EvidenceClaim
from f1predict.domain import parse_dt, utc_now
from f1predict.intelligence.codex import CodexEvidenceProvider, EvidencePacketStore
from f1predict.intelligence.source_registry import SourceLogAuditor, SourceSnapshotter, WaybackAvailabilityClient
from f1predict.storage import RawSnapshotStore


DEFAULT_BLOCKER_REPORT = Path("reports/source_archives/remaining_blockers_cdx_discovery.json")
DEFAULT_REPLACEMENT_DIR = Path("reports/source_replacements")
DEFAULT_REPLACEMENT_BASENAME = "remaining_blockers.source_replacements"
DEFAULT_REPLACEMENT_REPORT = DEFAULT_REPLACEMENT_DIR / f"{DEFAULT_REPLACEMENT_BASENAME}.json"
DEFAULT_CONTENT_OVERRIDE_PATH = Path("data/research/source_replacements/tool_content_overrides.json")


@dataclass(frozen=True)
class SourceReplacementCandidateDefinition:
    candidate_id: str
    event_id: str
    source: str
    source_class: str
    url: str
    evidence_type: str
    expected_terms: tuple[str, ...]
    requires_manual_content_review: bool = False
    notes: str = ""


@dataclass(frozen=True)
class SourceReplacementCandidate:
    event_id: str
    event_name: str | None
    source_index: int | None
    original_url: str
    original_title: str | None
    original_published_at: str | None
    original_observed_at: str | None
    knowledge_cutoff: str | None
    used_in_claim_ids: tuple[str, ...]
    candidate_id: str
    source: str
    source_class: str
    evidence_type: str
    url: str
    status: str
    current_check_status: str
    current_content_source: str
    archive_check_status: str
    current_content_verified: bool
    current_content_review_required: bool
    archive_content_verified: bool
    archive_content_check_status: str
    archive_temporal_check_status: str
    evidence_available_at: str | None
    formal_replacement_ready: bool
    title: str | None = None
    content_length: int | None = None
    found_terms: tuple[str, ...] = ()
    missing_terms: tuple[str, ...] = ()
    archive_content_length: int | None = None
    archive_found_terms: tuple[str, ...] = ()
    archive_missing_terms: tuple[str, ...] = ()
    historical_archive: dict[str, Any] | None = None
    nearest_archive: dict[str, Any] | None = None
    current_content_snapshot: dict[str, Any] | None = None
    manual_content_review: dict[str, Any] | None = None
    error: str | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_name": self.event_name,
            "source_index": self.source_index,
            "original_url": self.original_url,
            "original_title": self.original_title,
            "original_published_at": self.original_published_at,
            "original_observed_at": self.original_observed_at,
            "knowledge_cutoff": self.knowledge_cutoff,
            "used_in_claim_ids": list(self.used_in_claim_ids),
            "candidate_id": self.candidate_id,
            "source": self.source,
            "source_class": self.source_class,
            "evidence_type": self.evidence_type,
            "url": self.url,
            "status": self.status,
            "current_check_status": self.current_check_status,
            "current_content_source": self.current_content_source,
            "archive_check_status": self.archive_check_status,
            "current_content_verified": self.current_content_verified,
            "current_content_review_required": self.current_content_review_required,
            "archive_content_verified": self.archive_content_verified,
            "archive_content_check_status": self.archive_content_check_status,
            "archive_temporal_check_status": self.archive_temporal_check_status,
            "evidence_available_at": self.evidence_available_at,
            "formal_replacement_ready": self.formal_replacement_ready,
            "title": self.title,
            "content_length": self.content_length,
            "found_terms": list(self.found_terms),
            "missing_terms": list(self.missing_terms),
            "archive_content_length": self.archive_content_length,
            "archive_found_terms": list(self.archive_found_terms),
            "archive_missing_terms": list(self.archive_missing_terms),
            "historical_archive": self.historical_archive,
            "nearest_archive": self.nearest_archive,
            "current_content_snapshot": self.current_content_snapshot,
            "manual_content_review": self.manual_content_review,
            "error": self.error,
            "notes": self.notes,
            "blocker_codes": list(source_replacement_blocker_codes(self)),
            "next_action_category": source_replacement_next_action_category(self),
            "minimum_missing_requirements": list(source_replacement_missing_requirements(self)),
            "review_summary": source_replacement_review_summary(self),
            "next_action": source_replacement_next_action(self),
            "command_templates": list(source_replacement_command_templates(self)),
            "acceptance_criteria": list(source_replacement_acceptance_criteria(self)),
        }


@dataclass(frozen=True)
class SourceReplacementApplyResult:
    event_id: str
    candidate_id: str
    applied_claim_ids: tuple[str, ...]
    source_log_path: str
    snapshot_path: str
    packet_path: str
    can_archive: bool
    findings: tuple[dict[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "candidate_id": self.candidate_id,
            "applied_claim_ids": list(self.applied_claim_ids),
            "source_log_path": self.source_log_path,
            "snapshot_path": self.snapshot_path,
            "packet_path": self.packet_path,
            "can_archive": self.can_archive,
            "findings": list(self.findings),
        }


class SourceReplacementApplyError(ValueError):
    """Raised when a replacement candidate cannot be safely applied."""


@dataclass(frozen=True)
class SourceReplacementEvent:
    event_id: str
    event_name: str | None
    knowledge_cutoff: str | None
    original_url: str
    original_title: str | None
    status: str
    next_action: str
    candidate_count: int
    cutoff_valid_replacement_count: int
    used_in_claim_ids: tuple[str, ...]
    candidates: tuple[SourceReplacementCandidate, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_name": self.event_name,
            "knowledge_cutoff": self.knowledge_cutoff,
            "original_url": self.original_url,
            "original_title": self.original_title,
            "status": self.status,
            "next_action": self.next_action,
            "candidate_count": self.candidate_count,
            "cutoff_valid_replacement_count": self.cutoff_valid_replacement_count,
            "used_in_claim_ids": list(self.used_in_claim_ids),
            "blocker_code_counts": _count_candidate_blocker_codes(self.candidates),
            "next_action_category_counts": _count_candidate_action_categories(self.candidates),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


@dataclass(frozen=True)
class SourceReplacementReport:
    generated_at: str
    input_path: str
    check_current: bool
    check_archive: bool
    blocker_count: int
    event_count: int
    candidate_count: int
    cutoff_valid_replacement_count: int
    status_counts: dict[str, int]
    event_status_counts: dict[str, int]
    events: tuple[SourceReplacementEvent, ...]

    @property
    def remaining_candidate_count(self) -> int:
        return max(0, self.candidate_count - self.cutoff_valid_replacement_count)

    @property
    def archive_proof_required_count(self) -> int:
        return sum(
            1
            for event in self.events
            for candidate in event.candidates
            if candidate.status in {
                "candidate_needs_archive_proof",
                "candidate_needs_content_and_archive_review",
                "candidate_needs_archive_content_review",
                "candidate_needs_archive_temporal_review",
            }
        )

    @property
    def content_review_required_count(self) -> int:
        return sum(
            1
            for event in self.events
            for candidate in event.candidates
            if candidate.status in {
                "candidate_needs_content_review",
                "candidate_needs_content_and_archive_review",
                "candidate_needs_archive_content_review",
                "candidate_needs_archive_temporal_review",
            }
        )

    @property
    def lookup_failed_count(self) -> int:
        return sum(
            1
            for event in self.events
            for candidate in event.candidates
            if candidate.status == "candidate_lookup_failed"
        )

    @property
    def blocker_code_counts(self) -> dict[str, int]:
        return _count_candidate_blocker_codes(
            candidate for event in self.events for candidate in event.candidates
        )

    @property
    def next_action_category_counts(self) -> dict[str, int]:
        return _count_candidate_action_categories(
            candidate for event in self.events for candidate in event.candidates
        )

    @property
    def status(self) -> str:
        if self.blocker_count == 0:
            return "no_source_blockers"
        if self.cutoff_valid_replacement_count:
            return "replacement_candidates_ready_for_source_log_review"
        if self.candidate_count:
            return "replacement_candidates_need_archive_or_content_review"
        return "no_replacement_candidates_found"

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "input_path": self.input_path,
            "status": self.status,
            "check_current": self.check_current,
            "check_archive": self.check_archive,
            "blocker_count": self.blocker_count,
            "event_count": self.event_count,
            "candidate_count": self.candidate_count,
            "cutoff_valid_replacement_count": self.cutoff_valid_replacement_count,
            "remaining_candidate_count": self.remaining_candidate_count,
            "archive_proof_required_count": self.archive_proof_required_count,
            "content_review_required_count": self.content_review_required_count,
            "lookup_failed_count": self.lookup_failed_count,
            "blocker_code_counts": self.blocker_code_counts,
            "next_action_category_counts": self.next_action_category_counts,
            "status_counts": self.status_counts,
            "event_status_counts": self.event_status_counts,
            "events": [event.to_dict() for event in self.events],
            "rows": [candidate.to_dict() for event in self.events for candidate in event.candidates],
        }

    def to_markdown(self) -> str:
        lines = [
            "# Source Replacement Candidate Report",
            "",
            f"- Generated at: `{self.generated_at}`",
            f"- Input: `{self.input_path}`",
            f"- Status: **{self.status}**",
            f"- Blockers: {self.blocker_count}",
            f"- Candidates: {self.candidate_count}",
            f"- Cutoff-valid replacements: {self.cutoff_valid_replacement_count}",
            f"- Remaining candidates needing review/proof: {self.remaining_candidate_count}",
            f"- Archive proof required: {self.archive_proof_required_count}",
            f"- Content review required: {self.content_review_required_count}",
            f"- Blocker codes: {_format_counts(self.blocker_code_counts)}",
            f"- Next action categories: {_format_counts(self.next_action_category_counts)}",
            "",
            "## Events",
            "",
            "| Event | Status | Cutoff | Candidates | Cutoff-Valid | Next Action |",
            "|---|---|---|---:|---:|---|",
        ]
        for event in self.events:
            lines.append(
                "| "
                f"{event.event_name or event.event_id} | {event.status} | "
                f"{event.knowledge_cutoff or 'n/a'} | {event.candidate_count} | "
                f"{event.cutoff_valid_replacement_count} | {event.next_action} |"
            )
        lines.extend(["", "## Candidate Details", ""])
        for event in self.events:
            lines.extend([f"### {event.event_name or event.event_id}", ""])
            if not event.candidates:
                lines.extend(["- No catalogued replacement candidates for this blocker.", ""])
                continue
            for candidate in event.candidates:
                lines.extend(
                    [
                        f"- `{candidate.candidate_id}`: {candidate.status}",
                        f"  - URL: `{candidate.url}`",
                        f"  - Current check: {candidate.current_check_status}",
                        f"  - Current source: {candidate.current_content_source}",
                        f"  - Archive check: {candidate.archive_check_status}",
                        f"  - Archive content check: {candidate.archive_content_check_status}",
                        f"  - Archive temporal check: {candidate.archive_temporal_check_status}",
                        f"  - Blockers: {_format_tuple(source_replacement_blocker_codes(candidate))}",
                        f"  - Action category: {source_replacement_next_action_category(candidate)}",
                        f"  - Review: {source_replacement_review_summary(candidate)}",
                        f"  - Next: {source_replacement_next_action(candidate)}",
                    ]
                )
                for requirement in source_replacement_missing_requirements(candidate):
                    lines.append(f"  - Missing: {requirement}")
                if candidate.evidence_available_at:
                    lines.append(f"  - Evidence available at: {candidate.evidence_available_at}")
                if candidate.missing_terms:
                    lines.append(f"  - Missing terms: {', '.join(candidate.missing_terms)}")
                if candidate.archive_missing_terms:
                    lines.append(f"  - Archive missing terms: {', '.join(candidate.archive_missing_terms)}")
                if candidate.nearest_archive:
                    nearest_at = candidate.nearest_archive.get("archived_at") or "n/a"
                    relation = candidate.nearest_archive.get("cutoff_relation") or "unknown"
                    lines.append(f"  - Nearest archive: {nearest_at} ({relation})")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


class SourceReplacementCandidateBuilder:
    """Builds a review queue of replacement sources for unresolved blocker rows."""

    def __init__(
        self,
        http: HttpTextClient | None = None,
        wayback: WaybackAvailabilityClient | None = None,
        candidate_catalog: Iterable[SourceReplacementCandidateDefinition] | None = None,
        content_overrides_path: Path | str | None = DEFAULT_CONTENT_OVERRIDE_PATH,
        content_overrides: dict[str, Any] | None = None,
    ) -> None:
        self.http = http or HttpTextClient(timeout_seconds=15)
        self.wayback = wayback or WaybackAvailabilityClient()
        self.candidate_catalog = tuple(candidate_catalog or DEFAULT_CANDIDATE_CATALOG)
        self.content_overrides = (
            _normalize_content_overrides(content_overrides)
            if content_overrides is not None
            else _load_content_overrides(content_overrides_path)
        )

    def build(
        self,
        input_path: Path | str = DEFAULT_BLOCKER_REPORT,
        event_ids: Iterable[str] | None = None,
        check_current: bool = True,
        check_archive: bool = True,
    ) -> SourceReplacementReport:
        path = Path(input_path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        selected = set(event_ids or [])
        blocker_rows = [
            row
            for row in raw.get("rows", [])
            if isinstance(row, dict) and (not selected or row.get("event_id") in selected)
        ]
        catalog_by_event: dict[str, list[SourceReplacementCandidateDefinition]] = {}
        for definition in self.candidate_catalog:
            catalog_by_event.setdefault(definition.event_id, []).append(definition)

        events = tuple(
            self._build_event(
                row,
                catalog_by_event.get(str(row.get("event_id") or ""), []),
                check_current=check_current,
                check_archive=check_archive,
            )
            for row in blocker_rows
        )
        rows = tuple(candidate for event in events for candidate in event.candidates)
        return SourceReplacementReport(
            generated_at=utc_now().replace(microsecond=0).isoformat(),
            input_path=str(path),
            check_current=check_current,
            check_archive=check_archive,
            blocker_count=len(blocker_rows),
            event_count=len(events),
            candidate_count=len(rows),
            cutoff_valid_replacement_count=sum(1 for candidate in rows if candidate.formal_replacement_ready),
            status_counts=_status_counts(candidate.status for candidate in rows),
            event_status_counts=_status_counts(event.status for event in events),
            events=events,
        )

    def write(
        self,
        input_path: Path | str = DEFAULT_BLOCKER_REPORT,
        event_ids: Iterable[str] | None = None,
        check_current: bool = True,
        check_archive: bool = True,
        output_dir: Path | str = DEFAULT_REPLACEMENT_DIR,
    ) -> dict[str, Path]:
        report = self.build(
            input_path=input_path,
            event_ids=event_ids,
            check_current=check_current,
            check_archive=check_archive,
        )
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        json_path = directory / f"{DEFAULT_REPLACEMENT_BASENAME}.json"
        markdown_path = directory / f"{DEFAULT_REPLACEMENT_BASENAME}.md"
        json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(report.to_markdown(), encoding="utf-8")
        return {"json": json_path, "markdown": markdown_path}

    def _build_event(
        self,
        blocker: dict[str, Any],
        definitions: list[SourceReplacementCandidateDefinition],
        check_current: bool,
        check_archive: bool,
    ) -> SourceReplacementEvent:
        candidates = tuple(
            self._build_candidate(
                blocker,
                definition,
                check_current=check_current,
                check_archive=check_archive,
            )
            for definition in definitions
        )
        ready = sum(1 for candidate in candidates if candidate.formal_replacement_ready)
        if ready:
            status = "replacement_ready"
            next_action = "Snapshot the cutoff-valid replacement into the source log, link the original claim IDs, and rerun source audit."
        elif any(candidate.status == "candidate_needs_archive_proof" for candidate in candidates):
            status = "replacement_candidates_need_archive_proof"
            next_action = "Find or attach an at-or-before-cutoff historical archive proof for the verified replacement candidate."
        elif candidates:
            status = "replacement_candidates_need_review"
            next_action = "Manually review candidate content and keep searching for cutoff-valid archive proof."
        else:
            status = "no_replacement_candidate_found"
            next_action = "Search for another source class with cutoff-valid proof, such as FIA documents, timing PDFs, or live reports."
        return SourceReplacementEvent(
            event_id=str(blocker.get("event_id") or ""),
            event_name=str(blocker.get("event_name") or "") or None,
            knowledge_cutoff=str(blocker.get("knowledge_cutoff") or "") or None,
            original_url=str(blocker.get("url") or ""),
            original_title=str(blocker.get("title") or "") or None,
            status=status,
            next_action=next_action,
            candidate_count=len(candidates),
            cutoff_valid_replacement_count=ready,
            used_in_claim_ids=_string_tuple(blocker.get("used_in_claim_ids")),
            candidates=candidates,
        )

    def _build_candidate(
        self,
        blocker: dict[str, Any],
        definition: SourceReplacementCandidateDefinition,
        check_current: bool,
        check_archive: bool,
    ) -> SourceReplacementCandidate:
        title: str | None = None
        content_length: int | None = None
        found_terms: tuple[str, ...] = ()
        missing_terms = definition.expected_terms
        current_status = "not_checked"
        current_content_source = "not_checked"
        current_content_snapshot: dict[str, Any] | None = None
        manual_content_review: dict[str, Any] | None = None
        manual_content_review_supports_claim = False
        current_verified = False
        error_parts: list[str] = []

        if check_current:
            try:
                override = self.content_overrides.get(definition.url)
                if override is not None:
                    content = _content_override_text(override)
                    if not content:
                        raise ValueError("content override has no content_text")
                    manual_content_review = _manual_content_review_summary(override)
                    manual_content_review_supports_claim = _manual_content_review_supports_claim(override)
                    current_content_source = str(
                        override.get("captured_by")
                        or override.get("source_type")
                        or override.get("verification_method")
                        or "tool_content_override"
                    )
                    current_content_snapshot = _content_override_summary(override)
                    title = str(override.get("title") or "") or _extract_title(content)
                else:
                    content = self.http.get_text(definition.url)
                    current_content_source = "http"
                    title = _extract_title(content)
                content_length = len(content)
                found_terms, missing_terms = _term_matches(content, definition.expected_terms)
                if missing_terms:
                    current_status = "missing_expected_terms"
                elif definition.requires_manual_content_review and manual_content_review_supports_claim:
                    current_status = "verified_manual_reviewed_content"
                    current_verified = True
                elif definition.requires_manual_content_review:
                    current_status = "current_content_review_required"
                elif override is not None:
                    current_status = "verified_tool_content"
                    current_verified = True
                else:
                    current_status = "verified_current_content"
                    current_verified = True
            except Exception as exc:  # noqa: BLE001 - candidate review should continue per source.
                current_status = "current_lookup_failed"
                current_content_source = "lookup_failed"
                error_parts.append(f"current:{exc}")
        else:
            current_status = "not_checked"

        archive_status = "not_checked"
        archive_content_status = "not_checked"
        archive_content_verified = False
        archive_content_length: int | None = None
        archive_found_terms: tuple[str, ...] = ()
        archive_missing_terms: tuple[str, ...] = ()
        historical_archive: dict[str, Any] | None = None
        nearest_archive: dict[str, Any] | None = None
        cutoff = str(blocker.get("knowledge_cutoff") or "") or None
        cutoff_dt = parse_dt(cutoff) if cutoff else None
        evidence_floor_dt = _evidence_available_floor(blocker)
        evidence_available_at = evidence_floor_dt.isoformat() if evidence_floor_dt is not None else None
        archive_temporal_status = "not_checked"
        if check_archive and cutoff_dt is not None:
            try:
                historical_archive = self.wayback.archive_before(definition.url, cutoff_dt)
                archive_status = "cutoff_valid_archive" if historical_archive else "no_archive_before_cutoff"
            except Exception as exc:  # noqa: BLE001 - leave the candidate reviewable.
                archive_status = "archive_lookup_failed"
                error_parts.append(f"archive:{exc}")
            if historical_archive is None:
                nearest_lookup = getattr(self.wayback, "nearest_capture", None)
                if callable(nearest_lookup):
                    try:
                        nearest_archive = nearest_lookup(definition.url, cutoff_dt)
                    except Exception as exc:  # noqa: BLE001 - nearest archive is diagnostic only.
                        error_parts.append(f"nearest_archive:{exc}")
                if (
                    nearest_archive
                    and nearest_archive.get("cutoff_relation") == "after_cutoff"
                    and archive_status == "no_archive_before_cutoff"
                ):
                    archive_status = "archive_after_cutoff_not_valid"
            if historical_archive is not None:
                archive_url = str(historical_archive.get("archive_url") or "")
                if archive_url:
                    try:
                        archive_content = self.http.get_text(archive_url)
                        archive_content_length = len(archive_content)
                        archive_found_terms, archive_missing_terms = _term_matches(
                            archive_content,
                            definition.expected_terms,
                        )
                        if archive_missing_terms:
                            archive_content_status = "archive_missing_expected_terms"
                        else:
                            archive_content_status = "verified_archive_content"
                            archive_content_verified = True
                    except Exception as exc:  # noqa: BLE001 - archive proof must include readable claim content.
                        archive_content_status = "archive_content_lookup_failed"
                        archive_missing_terms = definition.expected_terms
                        error_parts.append(f"archive_content:{exc}")
                else:
                    archive_content_status = "archive_url_missing"
                    archive_missing_terms = definition.expected_terms
            archive_temporal_status = _archive_temporal_status(historical_archive, evidence_floor_dt)
        elif check_archive:
            archive_status = "missing_cutoff"
            archive_temporal_status = "missing_cutoff"

        status = _candidate_status(
            current_status=current_status,
            archive_status=archive_status,
            current_verified=current_verified,
            content_review_required=definition.requires_manual_content_review,
            historical_archive=historical_archive,
            archive_content_verified=archive_content_verified,
            archive_temporal_status=archive_temporal_status,
        )
        return SourceReplacementCandidate(
            event_id=str(blocker.get("event_id") or ""),
            event_name=str(blocker.get("event_name") or "") or None,
            source_index=int(blocker.get("source_index")) if blocker.get("source_index") is not None else None,
            original_url=str(blocker.get("url") or ""),
            original_title=str(blocker.get("title") or "") or None,
            original_published_at=str(blocker.get("published_at") or "") or None,
            original_observed_at=str(blocker.get("observed_at") or "") or None,
            knowledge_cutoff=cutoff,
            used_in_claim_ids=_string_tuple(blocker.get("used_in_claim_ids")),
            candidate_id=definition.candidate_id,
            source=definition.source,
            source_class=definition.source_class,
            evidence_type=definition.evidence_type,
            url=definition.url,
            status=status,
            current_check_status=current_status,
            current_content_source=current_content_source,
            archive_check_status=archive_status,
            current_content_verified=current_verified,
            current_content_review_required=(
                definition.requires_manual_content_review and not manual_content_review_supports_claim
            ),
            archive_content_verified=archive_content_verified,
            archive_content_check_status=archive_content_status,
            archive_temporal_check_status=archive_temporal_status,
            evidence_available_at=evidence_available_at,
            formal_replacement_ready=status == "cutoff_valid_replacement_candidate",
            title=title,
            content_length=content_length,
            found_terms=found_terms,
            missing_terms=missing_terms,
            archive_content_length=archive_content_length,
            archive_found_terms=archive_found_terms,
            archive_missing_terms=archive_missing_terms,
            historical_archive=historical_archive,
            nearest_archive=nearest_archive,
            current_content_snapshot=current_content_snapshot,
            manual_content_review=manual_content_review,
            error="; ".join(error_parts) or None,
            notes=definition.notes,
        )


class SourceReplacementApplier:
    """Applies formal-ready replacement candidates into source/evidence logs."""

    def __init__(
        self,
        replacement_report_path: Path | str = DEFAULT_REPLACEMENT_REPORT,
        research_root: Path | str = Path("data/research"),
        packet_root: Path | str = Path("data/evidence"),
        evidence_provider: CodexEvidenceProvider | None = None,
        raw_store: RawSnapshotStore | None = None,
        source_snapshotter: SourceSnapshotter | None = None,
    ) -> None:
        self.replacement_report_path = Path(replacement_report_path)
        self.research_root = Path(research_root)
        self.packet_root = Path(packet_root)
        self.evidence_provider = evidence_provider or CodexEvidenceProvider(packet_root=packet_root)
        self.source_snapshotter = source_snapshotter or SourceSnapshotter(
            raw_store=raw_store,
            research_root=research_root,
        )

    def apply_candidate(
        self,
        candidate_id: str,
        content_override: str | None = None,
    ) -> SourceReplacementApplyResult:
        candidate = self._candidate(candidate_id)
        if not candidate.get("formal_replacement_ready"):
            raise SourceReplacementApplyError(
                f"{candidate_id} is not formal_replacement_ready; status={candidate.get('status')}"
            )
        historical_archive = candidate.get("historical_archive")
        if not isinstance(historical_archive, dict):
            raise SourceReplacementApplyError(f"{candidate_id} has no historical_archive proof")
        claim_ids = tuple(str(value) for value in candidate.get("used_in_claim_ids", []) if value)
        if not claim_ids:
            raise SourceReplacementApplyError(f"{candidate_id} does not list used_in_claim_ids")
        event_id = str(candidate.get("event_id") or "")
        cutoff = str(candidate.get("knowledge_cutoff") or "") or None
        available_at = str(candidate.get("evidence_available_at") or "") or cutoff
        if not event_id or not cutoff or not available_at:
            raise SourceReplacementApplyError(f"{candidate_id} is missing event_id, knowledge_cutoff, or evidence_available_at")

        cutoff_dt = parse_dt(cutoff)
        existing_claims = self.evidence_provider.load_event_evidence(event_id, cutoff_dt)
        claims_by_id = {claim.claim_id: claim for claim in existing_claims}
        missing_claim_ids = [claim_id for claim_id in claim_ids if claim_id not in claims_by_id]
        if missing_claim_ids:
            raise SourceReplacementApplyError(
                f"{candidate_id} cannot update missing claim ids: {', '.join(missing_claim_ids)}"
            )

        replacement_claims = tuple(
            self._replacement_claim(claims_by_id[claim_id], candidate, available_at)
            for claim_id in claim_ids
        )
        snapshot = self.source_snapshotter.snapshot_url(
            event_id=event_id,
            url=str(candidate["url"]),
            source=str(candidate["source"]),
            source_class=str(candidate["source_class"]),
            published_at=available_at,
            observed_at=available_at,
            knowledge_cutoff=cutoff,
            notes=f"Applied source replacement candidate {candidate_id}. Original source: {candidate.get('original_url')}",
            used_in_claim_ids=list(claim_ids),
            content_override=content_override,
            historical_archive=historical_archive,
        )
        audit = SourceLogAuditor().audit_claims(
            list(replacement_claims),
            snapshot.source_log_path,
            knowledge_cutoff=cutoff,
        )
        if not audit.can_archive:
            raise SourceReplacementApplyError(
                f"{candidate_id} source audit failed after snapshot: {json.dumps(audit.to_dict(), ensure_ascii=False)}"
            )
        packet_path = EvidencePacketStore(self.packet_root).write_event_packet(
            event_id,
            list(replacement_claims),
            source_log_path=snapshot.source_log_path,
            params={
                "source_replacement_candidate": candidate_id,
                "source_replacement_report": str(self.replacement_report_path),
                "source_audit": audit.to_dict(),
            },
        )
        return SourceReplacementApplyResult(
            event_id=event_id,
            candidate_id=candidate_id,
            applied_claim_ids=claim_ids,
            source_log_path=snapshot.source_log_path,
            snapshot_path=snapshot.snapshot_path,
            packet_path=str(packet_path),
            can_archive=audit.can_archive,
            findings=tuple(finding.to_dict() for finding in audit.findings),
        )

    def _candidate(self, candidate_id: str) -> dict[str, Any]:
        if not self.replacement_report_path.exists():
            raise SourceReplacementApplyError(f"replacement report not found: {self.replacement_report_path}")
        raw = json.loads(self.replacement_report_path.read_text(encoding="utf-8"))
        matches = [
            row for row in raw.get("rows", [])
            if isinstance(row, dict) and row.get("candidate_id") == candidate_id
        ]
        if not matches:
            raise SourceReplacementApplyError(f"candidate_id not found in replacement report: {candidate_id}")
        if len(matches) > 1:
            raise SourceReplacementApplyError(f"candidate_id is not unique in replacement report: {candidate_id}")
        return matches[0]

    @staticmethod
    def _replacement_claim(
        claim: EvidenceClaim,
        candidate: dict[str, Any],
        available_at: str,
    ) -> EvidenceClaim:
        return replace(
            claim,
            source=str(candidate.get("source") or claim.source),
            source_url=str(candidate.get("url") or claim.source_url),
            published_at=available_at,
            observed_at=available_at,
        )


CURRENT_CONTENT_BLOCKERS = {
    "current_lookup_failed",
    "current_content_not_checked",
    "manual_current_content_review_required",
    "current_content_missing_expected_terms",
    "current_content_not_verified",
}

ARCHIVE_AVAILABILITY_BLOCKERS = {
    "knowledge_cutoff_missing",
    "cutoff_archive_missing",
    "archive_after_cutoff_not_valid",
    "archive_lookup_failed",
    "archive_not_checked",
    "archive_not_cutoff_valid",
}

ARCHIVE_CONTENT_BLOCKERS = {
    "archive_content_lookup_failed",
    "archive_url_missing",
    "archive_content_missing_expected_terms",
    "archive_content_not_checked",
    "archive_content_not_verified",
}

ARCHIVE_TEMPORAL_BLOCKERS = {
    "archive_before_evidence_time",
    "archive_time_invalid",
    "evidence_time_missing",
    "archive_temporal_not_verified",
}


def source_replacement_blocker_codes(candidate: SourceReplacementCandidate) -> tuple[str, ...]:
    if candidate.formal_replacement_ready:
        return ()

    codes: list[str] = []
    current_status = candidate.current_check_status
    if current_status == "current_lookup_failed":
        _append_unique(codes, "current_lookup_failed")
    elif current_status == "not_checked":
        _append_unique(codes, "current_content_not_checked")
    elif current_status == "current_content_review_required" or candidate.current_content_review_required:
        _append_unique(codes, "manual_current_content_review_required")
    elif current_status == "missing_expected_terms":
        _append_unique(codes, "current_content_missing_expected_terms")
    elif not candidate.current_content_verified:
        _append_unique(codes, "current_content_not_verified")

    archive_status = candidate.archive_check_status
    if archive_status == "missing_cutoff":
        _append_unique(codes, "knowledge_cutoff_missing")
    elif archive_status == "no_archive_before_cutoff":
        _append_unique(codes, "cutoff_archive_missing")
    elif archive_status == "archive_after_cutoff_not_valid":
        _append_unique(codes, "cutoff_archive_missing")
        _append_unique(codes, "archive_after_cutoff_not_valid")
    elif archive_status == "archive_lookup_failed":
        _append_unique(codes, "archive_lookup_failed")
    elif archive_status == "not_checked":
        _append_unique(codes, "archive_not_checked")
    elif archive_status != "cutoff_valid_archive":
        _append_unique(codes, "archive_not_cutoff_valid")

    if candidate.historical_archive is not None and archive_status == "cutoff_valid_archive":
        archive_content_status = candidate.archive_content_check_status
        if archive_content_status == "archive_missing_expected_terms":
            _append_unique(codes, "archive_content_missing_expected_terms")
        elif archive_content_status == "archive_content_lookup_failed":
            _append_unique(codes, "archive_content_lookup_failed")
        elif archive_content_status == "archive_url_missing":
            _append_unique(codes, "archive_url_missing")
        elif archive_content_status == "not_checked":
            _append_unique(codes, "archive_content_not_checked")
        elif not candidate.archive_content_verified:
            _append_unique(codes, "archive_content_not_verified")

        temporal_status = candidate.archive_temporal_check_status
        if temporal_status == "archive_before_evidence_time":
            _append_unique(codes, "archive_before_evidence_time")
        elif temporal_status == "invalid_archive_time":
            _append_unique(codes, "archive_time_invalid")
        elif temporal_status == "missing_evidence_time":
            _append_unique(codes, "evidence_time_missing")
        elif temporal_status not in {"archive_time_supports_evidence"}:
            _append_unique(codes, "archive_temporal_not_verified")

    return tuple(codes)


def source_replacement_next_action_category(candidate: SourceReplacementCandidate) -> str:
    if candidate.formal_replacement_ready:
        return "apply_ready_candidate"
    codes = set(source_replacement_blocker_codes(candidate))
    has_current_gap = bool(codes & CURRENT_CONTENT_BLOCKERS)
    has_archive_gap = bool(codes & (ARCHIVE_AVAILABILITY_BLOCKERS | ARCHIVE_CONTENT_BLOCKERS | ARCHIVE_TEMPORAL_BLOCKERS))
    if "current_lookup_failed" in codes:
        return "retry_lookup"
    if has_current_gap and has_archive_gap:
        return "review_current_content_and_find_archive"
    if has_current_gap:
        return "review_current_content"
    if "archive_lookup_failed" in codes:
        return "retry_lookup"
    if codes & ARCHIVE_TEMPORAL_BLOCKERS:
        return "find_archive_after_evidence_time"
    if codes & ARCHIVE_CONTENT_BLOCKERS:
        return "review_archive_content"
    if codes & ARCHIVE_AVAILABILITY_BLOCKERS:
        return "find_cutoff_archive"
    return "manual_review_candidate"


def source_replacement_missing_requirements(candidate: SourceReplacementCandidate) -> tuple[str, ...]:
    requirements: list[str] = []
    codes = set(source_replacement_blocker_codes(candidate))
    if "current_lookup_failed" in codes:
        requirements.append("current replacement page must be reachable or supplied by a reviewed tool-content override")
    if "current_content_not_checked" in codes:
        requirements.append("current replacement page content must be checked against the expected claim terms")
    if "manual_current_content_review_required" in codes:
        requirements.append("manual review must confirm the replacement page supports the same cited claim")
    if "current_content_missing_expected_terms" in codes:
        requirements.append(
            "current replacement content must establish expected terms: "
            + _format_tuple(candidate.missing_terms)
        )
    if "current_content_not_verified" in codes:
        requirements.append("current replacement content must be verified before formal replay use")
    if "knowledge_cutoff_missing" in codes:
        requirements.append("candidate must inherit a replay knowledge cutoff before archive proof can be assessed")
    if "cutoff_archive_missing" in codes:
        requirements.append(
            "Wayback/CDX archive capture must exist at or before "
            + (candidate.knowledge_cutoff or "the replay cutoff")
        )
    if "archive_after_cutoff_not_valid" in codes:
        requirements.append("nearest archive capture is after the cutoff and cannot prove point-in-time availability")
    if "archive_lookup_failed" in codes:
        requirements.append("archive lookup must succeed or be replaced with manually verified historical archive proof")
    if "archive_not_checked" in codes:
        requirements.append("archive availability must be checked against the replay cutoff")
    if "archive_not_cutoff_valid" in codes:
        requirements.append("archive proof must be a cutoff-valid historical capture")
    if "archive_content_lookup_failed" in codes:
        requirements.append("archived page content must be readable for source audit")
    if "archive_url_missing" in codes:
        requirements.append("historical archive proof must include an archive URL")
    if "archive_content_missing_expected_terms" in codes:
        requirements.append(
            "archived page content must establish expected terms: "
            + _format_tuple(candidate.archive_missing_terms)
        )
    if "archive_content_not_checked" in codes:
        requirements.append("archived page content must be checked against the cited claim terms")
    if "archive_content_not_verified" in codes:
        requirements.append("archived page content must be verified before formal replay use")
    if "archive_before_evidence_time" in codes:
        requirements.append(
            "archive capture must be after the evidence timestamp "
            + (candidate.evidence_available_at or "for the original claim")
            + " and at or before the replay cutoff"
        )
    if "archive_time_invalid" in codes:
        requirements.append("historical archive proof must include a valid archived_at timestamp")
    if "evidence_time_missing" in codes:
        requirements.append("original evidence published_at/observed_at is required for temporal proof")
    if "archive_temporal_not_verified" in codes:
        requirements.append("archive timestamp must be checked against both evidence time and replay cutoff")
    return tuple(requirements)


def source_replacement_review_summary(candidate: SourceReplacementCandidate) -> str:
    event_label = candidate.event_name or candidate.event_id
    if candidate.status == "cutoff_valid_replacement_candidate":
        return f"{event_label} has a replacement candidate with current-content checks and cutoff-valid archive proof."
    if candidate.status == "candidate_needs_archive_proof":
        if candidate.nearest_archive and candidate.nearest_archive.get("cutoff_relation") == "after_cutoff":
            return (
                f"{event_label} has a strong current replacement candidate, but the nearest Wayback capture "
                f"({candidate.nearest_archive.get('archived_at')}) is after the replay cutoff."
            )
        return (
            f"{event_label} has a strong current replacement candidate, but no Wayback/CDX capture "
            "at or before the replay cutoff was found."
        )
    if candidate.status == "candidate_needs_content_review":
        return f"{event_label} has archive proof, but the candidate content still needs manual review before replacement."
    if candidate.status == "candidate_needs_archive_content_review":
        return (
            f"{event_label} has current content and a cutoff-valid archive URL, but the archived page content "
            "does not yet prove the cited claim."
        )
    if candidate.status == "candidate_needs_archive_temporal_review":
        return (
            f"{event_label} has current and archived content matches, but the archive capture does not prove "
            f"the claim was available by the evidence timestamp ({candidate.evidence_available_at or 'unknown'})."
        )
    if candidate.status == "candidate_needs_content_and_archive_review":
        if candidate.nearest_archive and candidate.nearest_archive.get("cutoff_relation") == "after_cutoff":
            return (
                f"{event_label} candidate is missing formal proof: content review is still required, and "
                f"the nearest Wayback capture ({candidate.nearest_archive.get('archived_at')}) is after the cutoff."
            )
        return (
            f"{event_label} candidate is not enough for formal replay yet: content review and/or "
            "cutoff-valid archive proof is still missing."
        )
    if candidate.status == "candidate_lookup_failed":
        return f"{event_label} candidate lookup failed and cannot be accepted without a successful retry or manual proof."
    return f"{event_label} candidate status is {candidate.status}."


def source_replacement_next_action(candidate: SourceReplacementCandidate) -> str:
    cutoff = candidate.knowledge_cutoff or "the replay cutoff"
    if candidate.status == "cutoff_valid_replacement_candidate":
        return (
            "Snapshot this URL with historical_archive metadata, link used_in_claim_ids, "
            "then rerun evidence source audit and source readiness."
        )
    if candidate.status == "candidate_needs_archive_proof":
        return f"Find an archive capture for this candidate at or before {cutoff}, then snapshot it into the source log."
    if candidate.status == "candidate_needs_content_review":
        return "Manually verify the page supports the cited claim, then snapshot it with the existing archive proof."
    if candidate.status == "candidate_needs_archive_content_review":
        return "Find a cutoff-valid archive capture whose archived content contains the cited claim terms, or use another source."
    if candidate.status == "candidate_needs_archive_temporal_review":
        return (
            "Find an archive capture after the evidence timestamp and at or before the replay cutoff, "
            "or manually review another source with stronger point-in-time proof."
        )
    if candidate.status == "candidate_needs_content_and_archive_review":
        return f"Verify the page supports the cited claim and find an archive capture at or before {cutoff}."
    if candidate.status == "candidate_lookup_failed":
        return "Retry current and archive lookup; if it still fails, replace with a different verifiable source."
    return "Review this candidate manually before using it as replay evidence."


def source_replacement_command_templates(candidate: SourceReplacementCandidate) -> tuple[str, ...]:
    claim_flags = " ".join(f"--claim-id {claim_id}" for claim_id in candidate.used_in_claim_ids)
    apply_command = (
        "python -m f1predict.cli apply-source-replacement "
        f"--candidate-id {candidate.candidate_id} "
        "--replacement-report reports\\source_replacements\\remaining_blockers.source_replacements.json"
    )
    snapshot = (
        "python -m f1predict.cli snapshot-source "
        f"--event {candidate.event_id} "
        f"--url {candidate.url} "
        f'--source "{candidate.source}" '
        f"--source-class {candidate.source_class} "
        "--published-at <published-before-cutoff> "
        "--observed-at <observed-before-cutoff> "
        f"--knowledge-cutoff {candidate.knowledge_cutoff or '<cutoff>'} "
        "--historical-archive-url <archive-url> "
        "--historical-archived-at <archived-before-cutoff> "
        f"--historical-original-url {candidate.url} "
        "--historical-verification-method wayback"
    )
    if claim_flags:
        snapshot = f"{snapshot} {claim_flags}"
    if candidate.formal_replacement_ready:
        return (
            apply_command,
            f"python -m f1predict.cli formal-readiness --year 2026 --as-of <as-of> --write",
        )
    return (
        f"python -m f1predict.cli source-replacement-candidates --event {candidate.event_id} --write",
        snapshot,
        f"python -m f1predict.cli discover-source-archives --event {candidate.event_id} --write",
    )


def source_replacement_acceptance_criteria(candidate: SourceReplacementCandidate) -> tuple[str, ...]:
    cutoff = candidate.knowledge_cutoff or "event cutoff"
    return (
        "candidate page content supports the same claim IDs as the original blocked source",
        f"published_at and observed_at are at or before {cutoff}",
        "local snapshot captured before cutoff, or historical_archive.archived_at is at or before cutoff",
        "historical_archive.archived_at is not earlier than the claim/source evidence timestamp",
        "historical_archive.original_url matches the replacement URL",
        "source audit passes after replacing or supplementing the original source record",
    )


def _count_candidate_blocker_codes(candidates: Iterable[SourceReplacementCandidate]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for candidate in candidates:
        counter.update(source_replacement_blocker_codes(candidate))
    return dict(sorted(counter.items()))


def _count_candidate_action_categories(candidates: Iterable[SourceReplacementCandidate]) -> dict[str, int]:
    counter: Counter[str] = Counter(source_replacement_next_action_category(candidate) for candidate in candidates)
    return dict(sorted(counter.items()))


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _format_tuple(values: Iterable[str]) -> str:
    items = tuple(value for value in values if value)
    return ", ".join(items) if items else "none"


def _format_counts(values: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(values.items())) if values else "none"


def _candidate_status(
    current_status: str,
    archive_status: str,
    current_verified: bool,
    content_review_required: bool,
    historical_archive: dict[str, Any] | None,
    archive_content_verified: bool,
    archive_temporal_status: str,
) -> str:
    archive_time_ok = archive_temporal_status == "archive_time_supports_evidence"
    has_archive = (
        historical_archive is not None
        and archive_status == "cutoff_valid_archive"
        and archive_content_verified
        and archive_time_ok
    )
    if current_verified and has_archive:
        return "cutoff_valid_replacement_candidate"
    if (
        current_verified
        and historical_archive is not None
        and archive_status == "cutoff_valid_archive"
        and archive_content_verified
        and not archive_time_ok
    ):
        return "candidate_needs_archive_temporal_review"
    if current_verified and historical_archive is not None and archive_status == "cutoff_valid_archive":
        return "candidate_needs_archive_content_review"
    if current_verified and not has_archive:
        return "candidate_needs_archive_proof"
    if has_archive:
        return "candidate_needs_content_review"
    if current_status in {"current_lookup_failed", "not_checked"} and archive_status in {"archive_lookup_failed", "not_checked"}:
        return "candidate_lookup_failed"
    if current_status == "current_lookup_failed" and not content_review_required:
        return "candidate_lookup_failed"
    return "candidate_needs_content_and_archive_review"


def _evidence_available_floor(blocker: dict[str, Any]) -> datetime | None:
    timestamps = []
    for key in ("published_at", "observed_at"):
        value = blocker.get(key)
        parsed = parse_dt(str(value)) if value else None
        if parsed is not None:
            timestamps.append(parsed)
    return max(timestamps) if timestamps else None


def _archive_temporal_status(historical_archive: dict[str, Any] | None, evidence_floor: datetime | None) -> str:
    if historical_archive is None:
        return "not_checked"
    archived_at = parse_dt(str(historical_archive.get("archived_at"))) if historical_archive.get("archived_at") else None
    if archived_at is None:
        return "invalid_archive_time"
    if evidence_floor is None:
        return "missing_evidence_time"
    if archived_at < evidence_floor:
        return "archive_before_evidence_time"
    return "archive_time_supports_evidence"


def _extract_title(content: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", content, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    title = re.sub(r"\s+", " ", match.group(1)).strip()
    return title or None


def _term_matches(content: str, terms: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    normalized = _normalize(content)
    found: list[str] = []
    missing: list[str] = []
    for term in terms:
        if _normalize(term) in normalized:
            found.append(term)
        else:
            missing.append(term)
    return tuple(found), tuple(missing)


def _load_content_overrides(path: Path | str | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    input_path = Path(path)
    if not input_path.exists():
        return {}
    try:
        raw = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return _normalize_content_overrides(raw)


def _normalize_content_overrides(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    rows = raw.get("overrides")
    if isinstance(rows, list):
        output = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "")
            if url:
                output[url] = dict(row)
        return output
    output = {}
    for url, row in raw.items():
        if isinstance(row, dict):
            normalized = dict(row)
            normalized.setdefault("url", url)
            output[str(url)] = normalized
    return output


def _content_override_text(row: dict[str, Any]) -> str:
    return str(row.get("content_text") or row.get("text") or "")


def _content_override_summary(row: dict[str, Any]) -> dict[str, Any]:
    excluded = {"content_text", "text"}
    return {str(key): value for key, value in row.items() if key not in excluded}


def _manual_content_review_supports_claim(row: dict[str, Any]) -> bool:
    status = str(row.get("manual_review_status") or row.get("claim_support_status") or "").strip().lower()
    if status not in {"supports_claim", "accepted", "verified"}:
        return False
    reviewer = str(row.get("reviewed_by") or row.get("captured_by") or "").strip()
    notes = str(row.get("manual_review_notes") or row.get("review_notes") or row.get("notes") or "").strip()
    return bool(reviewer and notes)


def _manual_content_review_summary(row: dict[str, Any]) -> dict[str, Any] | None:
    keys = (
        "manual_review_status",
        "claim_support_status",
        "reviewed_by",
        "reviewed_at",
        "manual_review_notes",
        "review_notes",
        "verification_method",
    )
    summary = {key: row.get(key) for key in keys if row.get(key)}
    if not summary:
        return None
    summary["supports_claim"] = _manual_content_review_supports_claim(row)
    return summary


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).lower()


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if item)
    if value:
        return (str(value),)
    return ()


def _status_counts(statuses: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for status in statuses:
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


DEFAULT_CANDIDATE_CATALOG: tuple[SourceReplacementCandidateDefinition, ...] = (
    SourceReplacementCandidateDefinition(
        candidate_id="miami_gp_fia_qualifying_classification",
        event_id="miami_gp",
        source="FIA official qualifying classification",
        source_class="fia",
        evidence_type="official_classification",
        url="https://www.fia.com/events/fia-formula-one-world-championship/season-2026/miami-grand-prix/qualifying-classification",
        expected_terms=("Qualifying Classification", "Andrea Kimi Antonelli", "1:27.798", "Max Verstappen", "Charles Leclerc"),
        notes="Official FIA classification page observed as a strong current-content candidate; still needs cutoff-valid archive proof.",
    ),
    SourceReplacementCandidateDefinition(
        candidate_id="miami_gp_f1_results_qualifying",
        event_id="miami_gp",
        source="Formula1.com official qualifying results",
        source_class="f1_official",
        evidence_type="official_results_page",
        url="https://www.formula1.com/en/results/2026/races/1284/miami/qualifying",
        expected_terms=("Miami", "Qualifying"),
        requires_manual_content_review=True,
        notes="Formula1.com results pages require structured-content review because the page payload can include unrelated site JSON.",
    ),
    SourceReplacementCandidateDefinition(
        candidate_id="miami_gp_techradar_race_preview_grid",
        event_id="miami_gp",
        source="TechRadar race preview and starting grid",
        source_class="media",
        evidence_type="media_starting_grid",
        url="https://www.techradar.com/how-to-watch/formula-one/how-to-watch-miami-grand-prix-2026-f1-live-stream-preview-schedule",
        expected_terms=("Miami Grand Prix", "Antonelli", "pole", "Max Verstappen", "Charles Leclerc"),
        notes=(
            "Web-search-discovered media candidate. It can only replace the blocked source if current content "
            "supports the claim and Wayback/CDX proves availability at or before the cutoff."
        ),
    ),
    SourceReplacementCandidateDefinition(
        candidate_id="miami_gp_forbes_starting_grid",
        event_id="miami_gp",
        source="Forbes starting grid article",
        source_class="media",
        evidence_type="media_starting_grid",
        url="https://www.forbes.com/sites/yaraelshebiny/2026/05/03/starting-grid-for-the-2026-f1-miami-grand-prix/",
        expected_terms=("Miami Grand Prix", "Antonelli", "Max Verstappen", "Charles Leclerc", "Starting Grid"),
        notes=(
            "Web-search-discovered media candidate. The article date is close to the replay cutoff, so archive "
            "timing must be checked before use."
        ),
    ),
    SourceReplacementCandidateDefinition(
        candidate_id="miami_gp_sbnation_updated_grid",
        event_id="miami_gp",
        source="SB Nation updated starting grid article",
        source_class="media",
        evidence_type="media_starting_grid",
        url="https://www.sbnation.com/formula-one/1113160/miami-grand-prix-starting-grid-hadjar",
        expected_terms=("Miami Grand Prix", "Antonelli", "pole", "Max Verstappen", "Hadjar"),
        notes=(
            "Web-search-discovered media candidate. This may be a post-qualifying grid-update source; it still "
            "requires cutoff-valid archive proof."
        ),
    ),
    SourceReplacementCandidateDefinition(
        candidate_id="canadian_gp_fia_qualifying_classification",
        event_id="canadian_gp",
        source="FIA official qualifying classification",
        source_class="fia",
        evidence_type="official_classification",
        url="https://www.fia.com/events/fia-formula-one-world-championship/season-2026/canadian-grand-prix/qualifying-classification",
        expected_terms=("Qualifying Classification", "George Russell", "Kimi Antonelli"),
        notes="Official FIA classification page candidate; current public HTML may be incomplete and must be reviewed before replacement.",
    ),
    SourceReplacementCandidateDefinition(
        candidate_id="canadian_gp_f1_results_qualifying",
        event_id="canadian_gp",
        source="Formula1.com official qualifying results",
        source_class="f1_official",
        evidence_type="official_results_page",
        url="https://www.formula1.com/en/results/2026/races/1285/canada/qualifying",
        expected_terms=("Canada", "Qualifying"),
        requires_manual_content_review=True,
        notes="Formula1.com results pages require structured-content review because the page payload can include unrelated site JSON.",
    ),
    SourceReplacementCandidateDefinition(
        candidate_id="canadian_gp_techradar_race_preview_grid",
        event_id="canadian_gp",
        source="TechRadar race preview and starting grid",
        source_class="media",
        evidence_type="media_starting_grid",
        url="https://www.techradar.com/how-to-watch/formula-one/canadian-grand-prix-2026-f1-free",
        expected_terms=("Canadian Grand Prix", "George Russell", "Kimi Antonelli", "Starting Grid", "pole"),
        requires_manual_content_review=True,
        notes=(
            "Web-search-discovered media candidate. A Wayback capture may predate the qualifying result, so this "
            "candidate requires manual body-content review before it can replace a pole-position claim."
        ),
    ),
    SourceReplacementCandidateDefinition(
        candidate_id="canadian_gp_skysports_rain_grid",
        event_id="canadian_gp",
        source="Sky Sports Canadian GP grid article",
        source_class="media",
        evidence_type="media_starting_grid",
        url="https://www.skysports.com/f1/news/12433/13547300/canadian-gp-rain-set-to-cause-chaos-in-sundays-race-with-george-russell-on-pole-from-mercedes-team-mate-kimi-antonelli",
        expected_terms=("Canadian GP", "George Russell", "Kimi Antonelli", "Lando Norris", "pole"),
        notes=(
            "Web-search-discovered media candidate with explicit grid text in search results; still requires "
            "current-content and cutoff-valid archive checks."
        ),
    ),
    SourceReplacementCandidateDefinition(
        candidate_id="canadian_gp_si_starting_grid",
        event_id="canadian_gp",
        source="Sports Illustrated starting grid article",
        source_class="media",
        evidence_type="media_starting_grid",
        url="https://www.si.com/onsi/f1/news/f1-canadian-grand-prix-starting-grid-and-start-time",
        expected_terms=("Canadian Grand Prix", "George Russell", "Kimi Antonelli", "Lando Norris", "pole"),
        notes=(
            "Web-search-discovered media candidate. It is useful only if archived at or before the replay cutoff."
        ),
    ),
    SourceReplacementCandidateDefinition(
        candidate_id="barcelona_gp_fia_qualifying_classification",
        event_id="barcelona_gp",
        source="FIA official qualifying classification",
        source_class="fia",
        evidence_type="official_classification",
        url="https://www.fia.com/events/fia-formula-one-world-championship/season-2026/barcelona-catalunya-grand-prix/qualifying",
        expected_terms=("Qualifying Classification", "George Russell", "1:14.679", "Lewis Hamilton", "Andrea Kimi Antonelli"),
        notes="Official FIA classification page observed as a strong current-content candidate; still needs cutoff-valid archive proof.",
    ),
    SourceReplacementCandidateDefinition(
        candidate_id="barcelona_gp_f1_results_qualifying",
        event_id="barcelona_gp",
        source="Formula1.com official qualifying results",
        source_class="f1_official",
        evidence_type="official_results_page",
        url="https://www.formula1.com/en/results/2026/races/1287/spain/qualifying",
        expected_terms=("Spain", "Qualifying"),
        requires_manual_content_review=True,
        notes="Formula1.com results pages require structured-content review because the page payload can include unrelated site JSON.",
    ),
    SourceReplacementCandidateDefinition(
        candidate_id="barcelona_gp_techradar_race_preview_grid",
        event_id="barcelona_gp",
        source="TechRadar race preview and starting grid",
        source_class="media",
        evidence_type="media_starting_grid",
        url="https://www.techradar.com/how-to-watch/formula-one/catalunya-grand-prix-2026-f1-free",
        expected_terms=("Barcelona-Catalunya Grand Prix", "George Russell", "Lewis Hamilton", "Kimi Antonelli", "Starting Grid"),
        notes=(
            "Web-search-discovered media candidate. Search metadata indicates publication after the midnight UTC "
            "cutoff, so it should remain rejected unless archive proof contradicts that."
        ),
    ),
    SourceReplacementCandidateDefinition(
        candidate_id="barcelona_gp_youtube_qualifying_highlights",
        event_id="barcelona_gp",
        source="Formula 1 YouTube qualifying highlights",
        source_class="media",
        evidence_type="video_highlights_page",
        url="https://www.youtube.com/watch?v=Q2fMM4H9bWY",
        expected_terms=("Qualifying Highlights", "Barcelona-Catalunya Grand Prix", "Russell"),
        requires_manual_content_review=True,
        notes=(
            "Wayback CDX has cutoff-valid captures for this URL, but archived YouTube HTML may not expose enough "
            "claim text; keep it manual-review only."
        ),
    ),
)
