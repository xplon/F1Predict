"""Source snapshot registry for Codex research."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse, urlunparse

from f1predict.data_sources.http_clients import HttpJsonClient, HttpTextClient
from f1predict.domain import EvidenceClaim
from f1predict.domain import parse_dt, utc_now
from f1predict.storage import RawSnapshotStore, SnapshotRecord


DEFAULT_SOURCE_RELIABILITY = {
    "fia": 0.95,
    "f1_official": 0.95,
    "team_or_driver": 0.85,
    "structured_data": 0.85,
    "media": 0.75,
    "weather": 0.70,
    "market": 0.65,
    "rumor": 0.35,
    "social": 0.20,
}


@dataclass(frozen=True)
class SourceSnapshotResult:
    event_id: str
    url: str
    source: str
    source_class: str
    reliability: float
    captured_at: str
    content_length: int
    title: str | None
    cutoff_status: str
    snapshot_path: str
    source_log_path: str
    historical_archive: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "url": self.url,
            "source": self.source,
            "source_class": self.source_class,
            "reliability": self.reliability,
            "captured_at": self.captured_at,
            "content_length": self.content_length,
            "title": self.title,
            "cutoff_status": self.cutoff_status,
            "snapshot_path": self.snapshot_path,
            "source_log_path": self.source_log_path,
            "historical_archive": self.historical_archive,
        }


@dataclass(frozen=True)
class SourceAuditFinding:
    claim_id: str
    severity: str
    code: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "claim_id": self.claim_id,
            "severity": self.severity,
            "code": self.code,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class SourceAuditReport:
    source_log_path: str
    claim_count: int
    source_count: int
    findings: tuple[SourceAuditFinding, ...]

    @property
    def blocking_findings(self) -> tuple[SourceAuditFinding, ...]:
        return tuple(finding for finding in self.findings if finding.severity == "error")

    @property
    def can_archive(self) -> bool:
        return not self.blocking_findings

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_log_path": self.source_log_path,
            "claim_count": self.claim_count,
            "source_count": self.source_count,
            "can_archive": self.can_archive,
            "findings": [finding.to_dict() for finding in self.findings],
        }


@dataclass(frozen=True)
class SourceArchiveDiscoveryRow:
    event_id: str
    source_index: int
    url: str
    knowledge_cutoff: str | None
    captured_at: str | None
    status: str
    historical_archive: dict[str, Any] | None = None
    nearest_archive: dict[str, Any] | None = None
    error: str | None = None
    event_name: str | None = None
    source: str | None = None
    title: str | None = None
    source_class: str | None = None
    published_at: str | None = None
    observed_at: str | None = None
    used_in_claim_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_name": self.event_name,
            "source_index": self.source_index,
            "url": self.url,
            "source": self.source,
            "title": self.title,
            "source_class": self.source_class,
            "published_at": self.published_at,
            "observed_at": self.observed_at,
            "knowledge_cutoff": self.knowledge_cutoff,
            "captured_at": self.captured_at,
            "status": self.status,
            "historical_archive": self.historical_archive,
            "nearest_archive": self.nearest_archive,
            "error": self.error,
            "used_in_claim_ids": list(self.used_in_claim_ids),
            "top_issue_code": self.status,
            "review_summary": source_archive_review_summary(self),
            "next_action": source_archive_next_action(self),
            "replacement_query": source_archive_replacement_query(self),
            "recommended_source_classes": list(source_archive_recommended_classes(self)),
            "acceptance_criteria": list(source_archive_acceptance_criteria(self)),
        }


@dataclass(frozen=True)
class SourceArchiveDiscoveryReport:
    generated_at: str
    research_root: str
    write: bool
    source_log_count: int
    source_count: int
    candidate_count: int
    sources_updated: int
    status_counts: dict[str, int]
    rows: tuple[SourceArchiveDiscoveryRow, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "research_root": self.research_root,
            "write": self.write,
            "source_log_count": self.source_log_count,
            "source_count": self.source_count,
            "candidate_count": self.candidate_count,
            "sources_updated": self.sources_updated,
            "status_counts": self.status_counts,
            "rows": [row.to_dict() for row in self.rows],
        }


def _event_label(event_id: str, event_name: str | None = None) -> str:
    if event_name:
        return event_name
    return event_id.replace("_", " ").title()


def source_archive_review_summary(row: SourceArchiveDiscoveryRow) -> str:
    event_label = _event_label(row.event_id, row.event_name)
    if row.status == "archive_candidate":
        return (
            f"{event_label} has a Wayback capture at or before the replay cutoff; "
            "write the proof into source_log.json before using it in a formal replay."
        )
    if row.status == "already_has_archive":
        return f"{event_label} already has historical archive proof attached to the source record."
    if row.status == "not_retrospective":
        return f"{event_label} source was captured before the cutoff and does not need archive backfill."
    if row.status == "no_archive_before_cutoff":
        nearest = row.nearest_archive or {}
        if nearest.get("archived_at") and nearest.get("cutoff_relation") == "after_cutoff":
            return (
                f"{event_label} source was captured locally after the cutoff, and the nearest "
                f"Wayback hit found at {nearest.get('archived_at')} is after the cutoff; this "
                "remains retrospective evidence and is not formal replay proof."
            )
        return (
            f"{event_label} source was captured locally after the cutoff, and Wayback/CDX did not "
            "return an at-or-before-cutoff capture; this remains retrospective evidence."
        )
    if row.status == "archive_lookup_failed":
        return f"{event_label} archive lookup failed; the source cannot be cleared until lookup succeeds."
    if row.status == "unsupported_url":
        return f"{event_label} source URL is not archive-checkable through the Wayback lookup path."
    if row.status == "missing_cutoff":
        return f"{event_label} source is missing a replay cutoff, so archive validity cannot be judged."
    if row.status == "invalid_archive_candidate":
        return f"{event_label} produced an archive candidate, but validation rejected it: {row.error or 'unknown error'}."
    if row.status in {"invalid_source_log", "invalid_sources"}:
        return f"{event_label} source log structure is invalid and must be repaired before archive review."
    return f"{event_label} source archive status is {row.status}."


def source_archive_next_action(row: SourceArchiveDiscoveryRow) -> str:
    event_label = _event_label(row.event_id, row.event_name)
    if row.status == "archive_candidate":
        return (
            "Run discover-source-archives with --write for this event, then rerun readiness intake "
            "and replay reports so the cutoff-valid archive proof is frozen."
        )
    if row.status in {"already_has_archive", "not_retrospective"}:
        return "No replacement source is required for this row."
    if row.status == "no_archive_before_cutoff":
        cutoff = row.knowledge_cutoff or "the replay cutoff"
        return (
            f"Replace or supplement the {event_label} source with evidence verifiably available by {cutoff}: "
            "FIA classification/timing PDFs, official F1 live timing or session reports with archive proof, "
            "credible live-report media snapshots, weather data, and same-time market snapshots."
        )
    if row.status == "archive_lookup_failed":
        return "Rerun archive discovery; if the lookup still fails, add a manually reviewed archive proof or replace the source."
    if row.status == "unsupported_url":
        return "Replace with an HTTP(S) source or attach manually reviewed cutoff proof for the original material."
    if row.status == "missing_cutoff":
        return "Set the event/source knowledge_cutoff, then rerun archive discovery."
    if row.status == "invalid_archive_candidate":
        return "Fix the archive metadata mismatch or search for a different archive capture before the cutoff."
    if row.status in {"invalid_source_log", "invalid_sources"}:
        return "Repair the source_log.json schema, then rerun source archive discovery."
    return "Review this source row manually before using it in a formal replay."


def source_archive_replacement_query(row: SourceArchiveDiscoveryRow) -> str:
    event_label = _event_label(row.event_id, row.event_name)
    cutoff_date = (row.knowledge_cutoff or "").split("T", maxsplit=1)[0] or "cutoff date"
    title_bits = []
    if row.title:
        title_bits.append(row.title)
    elif row.source:
        title_bits.append(row.source)
    title_hint = " ".join(title_bits)
    core_terms = f'"{event_label}" qualifying results pole FIA Formula 1 live report'
    if title_hint:
        core_terms = f'{core_terms} "{title_hint[:90]}"'
    return f"{core_terms} published or archived before {cutoff_date}"


def source_archive_recommended_classes(row: SourceArchiveDiscoveryRow) -> tuple[str, ...]:
    if row.status in {"already_has_archive", "not_retrospective"}:
        return ()
    return ("fia", "f1_official", "structured_data", "media", "weather", "market")


def source_archive_acceptance_criteria(row: SourceArchiveDiscoveryRow) -> tuple[str, ...]:
    if row.status in {"already_has_archive", "not_retrospective"}:
        return ()
    cutoff = row.knowledge_cutoff or "event cutoff"
    return (
        f"published_at and observed_at are at or before {cutoff}",
        "local snapshot captured before cutoff, or historical_archive.archived_at is at or before cutoff",
        "source URL and archive original_url match the cited source",
        "claims cite source_url and used_in_claim_ids links back to the claim IDs",
    )


class SourceLogAuditor:
    """Audits evidence claims against a research source log."""

    def audit_claims(
        self,
        claims: list[EvidenceClaim],
        source_log_path: Path | str,
        knowledge_cutoff: str | None = None,
    ) -> SourceAuditReport:
        path = Path(source_log_path)
        if not path.exists():
            findings = tuple(
                SourceAuditFinding(
                    claim_id=claim.claim_id,
                    severity="error",
                    code="missing_source_log",
                    detail=f"source_log does not exist: {path}",
                )
                for claim in claims
            )
            return SourceAuditReport(str(path), len(claims), 0, findings)

        raw = json.loads(path.read_text(encoding="utf-8"))
        sources = [item for item in raw.get("sources", []) if isinstance(item, dict)]
        cutoff = knowledge_cutoff or raw.get("knowledge_cutoff")
        cutoff_dt = parse_dt(str(cutoff)) if cutoff else None
        by_url: dict[str, list[dict[str, Any]]] = {}
        for source in sources:
            by_url.setdefault(str(source.get("url", "")), []).append(source)

        findings: list[SourceAuditFinding] = []
        for claim in claims:
            source_matches = by_url.get(claim.source_url, [])
            if not source_matches:
                findings.append(
                    SourceAuditFinding(
                        claim.claim_id,
                        "error",
                        "missing_source_snapshot",
                        f"No source_log entry has url={claim.source_url!r}",
                    )
                )
                continue
            if not any(claim.claim_id in (source.get("used_in_claim_ids") or []) for source in source_matches):
                findings.append(
                    SourceAuditFinding(
                        claim.claim_id,
                        "error",
                        "claim_not_linked_to_source",
                        "A matching source URL exists, but used_in_claim_ids does not include the claim_id.",
                    )
                )

            for source in source_matches:
                status = str(source.get("cutoff_status") or "")
                if status.startswith("after_cutoff"):
                    findings.append(
                        SourceAuditFinding(
                            claim.claim_id,
                            "error",
                            "source_after_cutoff",
                            f"Source cutoff_status={status}",
                        )
                    )
                if status == "unknown_published_at" and not claim.review_required:
                    findings.append(
                        SourceAuditFinding(
                            claim.claim_id,
                            "error",
                            "unknown_published_at_requires_review",
                            "Source has unknown published_at; claim must set review_required=true.",
                        )
                    )
                if not source.get("snapshot_path"):
                    findings.append(
                        SourceAuditFinding(
                            claim.claim_id,
                            "error",
                            "missing_snapshot_path",
                            "Source log entry has no snapshot_path.",
                        )
                    )
                captured_at = self._source_captured_at(source)
                if captured_at is None:
                    findings.append(
                        SourceAuditFinding(
                            claim.claim_id,
                            "error",
                            "missing_snapshot_captured_at",
                            "Source log entry has no captured_at and the snapshot metadata could not be read.",
                        )
                    )
                else:
                    archive_findings = historical_archive_findings(source, cutoff_dt, claim.claim_id, claim=claim)
                    findings.extend(archive_findings)
                    has_archive_proof = source_has_cutoff_archive_proof(source, cutoff_dt)
                    if cutoff_dt is not None and captured_at > cutoff_dt and not has_archive_proof:
                        findings.append(
                            SourceAuditFinding(
                                claim.claim_id,
                                "warning",
                                "snapshot_captured_after_cutoff",
                                (
                                    "Source was snapshotted after the replay knowledge cutoff; "
                                    "this can support retrospective research but not a frozen point-in-time replay."
                                ),
                            )
                        )
                    if cutoff_dt is not None and captured_at > cutoff_dt and has_archive_proof:
                        findings.append(
                            SourceAuditFinding(
                                claim.claim_id,
                                "info",
                                "historical_archive_supports_cutoff",
                                "Source was snapshotted locally after the cutoff, but a verified historical archive capture is at or before the cutoff.",
                            )
                        )
                    for label, timestamp, code in (
                        ("source published_at", source.get("published_at"), "source_published_after_snapshot"),
                        ("source observed_at", source.get("observed_at"), "source_observed_after_snapshot"),
                        ("claim published_at", claim.published_at, "claim_published_after_snapshot"),
                        ("claim observed_at", claim.observed_at, "claim_observed_after_snapshot"),
                    ):
                        timestamp_dt = parse_dt(str(timestamp)) if timestamp else None
                        if timestamp_dt is not None and timestamp_dt > captured_at:
                            findings.append(
                                SourceAuditFinding(
                                    claim.claim_id,
                                    "error",
                                    code,
                                    f"{label}={timestamp} is later than snapshot captured_at={captured_at.isoformat()}.",
                                )
                            )

            if cutoff_dt is not None and not claim.is_available(cutoff_dt):
                findings.append(
                    SourceAuditFinding(
                        claim.claim_id,
                        "error",
                        "claim_after_cutoff",
                        "claim published_at/observed_at is after the knowledge cutoff.",
                    )
                )

        return SourceAuditReport(str(path), len(claims), len(sources), tuple(findings))

    @staticmethod
    def _source_captured_at(source: dict[str, Any]) -> datetime | None:
        captured_at = source.get("captured_at")
        if captured_at:
            return parse_dt(str(captured_at))
        snapshot_path = source.get("snapshot_path")
        if not snapshot_path:
            return None
        data_path = Path(str(snapshot_path))
        meta_path = data_path.with_name(f"{data_path.stem}.meta.json")
        if not meta_path.exists():
            return None
        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        captured_at = raw.get("captured_at")
        return parse_dt(str(captured_at)) if captured_at else None


class SourceSnapshotter:
    """Fetches source pages and records them in the research source log."""

    def __init__(
        self,
        http: HttpTextClient | None = None,
        raw_store: RawSnapshotStore | None = None,
        research_root: Path | str = Path("data/research"),
    ) -> None:
        self.http = http or HttpTextClient()
        self.raw_store = raw_store or RawSnapshotStore()
        self.research_root = Path(research_root)

    def snapshot_url(
        self,
        event_id: str,
        url: str,
        source: str,
        source_class: str,
        published_at: str | None = None,
        observed_at: str | None = None,
        knowledge_cutoff: str | None = None,
        notes: str = "",
        used_in_claim_ids: list[str] | None = None,
        content_override: str | None = None,
        historical_archive: dict[str, Any] | None = None,
    ) -> SourceSnapshotResult:
        source_class = self._normalize_source_class(source_class)
        captured_at = utc_now().replace(microsecond=0).isoformat()
        observed = observed_at or captured_at
        content = content_override if content_override is not None else self.http.get_text(url)
        title = self._extract_title(content)
        cutoff_status = self._cutoff_status(published_at, observed, knowledge_cutoff)
        reliability = DEFAULT_SOURCE_RELIABILITY[source_class]
        payload = {
            "event_id": event_id,
            "url": url,
            "source": source,
            "source_class": source_class,
            "reliability": reliability,
            "published_at": published_at,
            "observed_at": observed,
            "knowledge_cutoff": knowledge_cutoff,
            "cutoff_status": cutoff_status,
            "title": title,
            "content": content,
            "content_length": len(content),
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "historical_archive": historical_archive,
        }
        record = self.raw_store.write_json(
            "research_sources",
            f"{event_id}_{source_class}_{self._url_key(url)}",
            payload,
            {
                "event_id": event_id,
                "url": url,
                "source_class": source_class,
                "published_at": published_at,
                "observed_at": observed,
                "knowledge_cutoff": knowledge_cutoff,
            },
        )
        source_log_path = self._append_source_log(
            event_id=event_id,
            source=source,
            url=url,
            source_class=source_class,
            reliability=reliability,
            published_at=published_at,
            observed_at=observed,
            knowledge_cutoff=knowledge_cutoff,
            cutoff_status=cutoff_status,
            snapshot=record,
            title=title,
            content_length=len(content),
            notes=notes,
            used_in_claim_ids=used_in_claim_ids or [],
            historical_archive=historical_archive,
        )
        return SourceSnapshotResult(
            event_id=event_id,
            url=url,
            source=source,
            source_class=source_class,
            reliability=reliability,
            captured_at=record.captured_at,
            content_length=len(content),
            title=title,
            cutoff_status=cutoff_status,
            snapshot_path=str(record.path),
            source_log_path=str(source_log_path),
            historical_archive=historical_archive,
        )

    def _append_source_log(
        self,
        event_id: str,
        source: str,
        url: str,
        source_class: str,
        reliability: float,
        published_at: str | None,
        observed_at: str,
        knowledge_cutoff: str | None,
        cutoff_status: str,
        snapshot: SnapshotRecord,
        title: str | None,
        content_length: int,
        notes: str,
        used_in_claim_ids: list[str],
        historical_archive: dict[str, Any] | None,
    ) -> Path:
        directory = self.research_root / event_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "source_log.json"
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
        else:
            raw = {
                "event_id": event_id,
                "event_name": event_id,
                "knowledge_cutoff": knowledge_cutoff,
                "sources": [],
            }
        raw.setdefault("sources", [])
        source_record = {
            "source": source,
            "url": url,
            "title": title,
            "published_at": published_at,
            "observed_at": observed_at,
            "knowledge_cutoff": knowledge_cutoff,
            "cutoff_status": cutoff_status,
            "source_class": source_class,
            "reliability": reliability,
            "captured_at": snapshot.captured_at,
            "snapshot_path": str(snapshot.path),
            "content_length": content_length,
            "used_in_claim_ids": used_in_claim_ids,
            "notes": notes,
        }
        if historical_archive:
            source_record["historical_archive"] = historical_archive
        raw["sources"].append(source_record)
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @staticmethod
    def _normalize_source_class(source_class: str) -> str:
        normalized = source_class.strip().lower()
        if normalized not in DEFAULT_SOURCE_RELIABILITY:
            allowed = ", ".join(sorted(DEFAULT_SOURCE_RELIABILITY))
            raise ValueError(f"Unsupported source_class {source_class!r}. Allowed: {allowed}")
        return normalized

    @staticmethod
    def _extract_title(content: str) -> str | None:
        match = re.search(r"<title[^>]*>(.*?)</title>", content, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        title = re.sub(r"\s+", " ", match.group(1)).strip()
        return title or None

    @staticmethod
    def _cutoff_status(published_at: str | None, observed_at: str | None, knowledge_cutoff: str | None) -> str:
        cutoff = parse_dt(knowledge_cutoff)
        if cutoff is None:
            return "no_cutoff"
        published = parse_dt(published_at) if published_at else None
        observed = parse_dt(observed_at) if observed_at else None
        if published is not None and published > cutoff:
            return "after_cutoff_published"
        if observed is not None and observed > cutoff:
            return "after_cutoff_observed"
        if published is None:
            return "unknown_published_at"
        return "within_cutoff"

    @staticmethod
    def _url_key(url: str) -> str:
        return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


class WaybackAvailabilityClient:
    """Finds Internet Archive Wayback captures at or before a cutoff."""

    api_url = "https://archive.org/wayback/available"
    cdx_url = "https://web.archive.org/cdx"

    def __init__(self, http: HttpJsonClient | None = None) -> None:
        self.http = http or HttpJsonClient(timeout_seconds=10)

    def archive_before(self, url: str, cutoff: datetime) -> dict[str, Any] | None:
        cutoff = cutoff.astimezone(timezone.utc)
        errors: list[str] = []
        successful_lookup_count = 0
        for candidate_url in _wayback_url_variants(url):
            try:
                proof = self._archive_before_available(candidate_url, cutoff, original_url=url)
                successful_lookup_count += 1
            except Exception as exc:  # noqa: BLE001 - fall back to other Wayback endpoints.
                errors.append(f"availability:{candidate_url}: {exc}")
                continue
            if proof is not None:
                return proof
        for candidate_url in _wayback_url_variants(url):
            try:
                proof = self._archive_before_cdx(candidate_url, cutoff, original_url=url)
                successful_lookup_count += 1
            except Exception as exc:  # noqa: BLE001 - try the remaining URL variants.
                errors.append(f"cdx:{candidate_url}: {exc}")
                continue
            if proof is not None:
                return proof
        if errors and successful_lookup_count == 0:
            raise RuntimeError("; ".join(errors))
        return None

    def nearest_capture(self, url: str, cutoff: datetime) -> dict[str, Any] | None:
        """Return the closest Wayback availability hit for diagnostics only.

        Unlike :meth:`archive_before`, this does not enforce the cutoff. Callers
        must treat after-cutoff captures as non-formal evidence.
        """
        cutoff = cutoff.astimezone(timezone.utc)
        errors: list[str] = []
        for candidate_url in _wayback_url_variants(url):
            try:
                proof = self._nearest_available_capture(candidate_url, cutoff, original_url=url)
            except Exception as exc:  # noqa: BLE001 - diagnostics should keep trying URL variants.
                errors.append(f"availability:{candidate_url}: {exc}")
                continue
            if proof is not None:
                return proof
        if errors:
            return {
                "error": "; ".join(errors),
                "original_url": url,
                "verified_at": utc_now().replace(microsecond=0).isoformat(),
                "verification_method": "wayback_available_api",
            }
        return None

    def _archive_before_available(
        self,
        candidate_url: str,
        cutoff: datetime,
        original_url: str,
    ) -> dict[str, Any] | None:
        payload = self.http.get_json(
            self.api_url,
            {
                "url": candidate_url,
                "timestamp": _wayback_timestamp(cutoff),
                "closest": "before",
            },
        )
        closest = (
            payload.get("archived_snapshots", {}).get("closest")
            if isinstance(payload, dict)
            else None
        )
        if not isinstance(closest, dict) or not closest.get("available"):
            return None
        timestamp = str(closest.get("timestamp") or "")
        archived_at = _parse_wayback_timestamp(timestamp)
        if archived_at is None or archived_at > cutoff:
            return None
        notes = f"Wayback availability API status={closest.get('status')}; timestamp={timestamp}."
        if not _same_url(candidate_url, original_url):
            notes = f"{notes} Matched URL variant: {candidate_url}."
        return {
            "archive_url": str(closest.get("url") or ""),
            "archived_at": archived_at.isoformat(),
            "original_url": original_url,
            "verified_at": utc_now().replace(microsecond=0).isoformat(),
            "verification_method": "wayback_available_api",
            "notes": notes,
        }

    def _nearest_available_capture(
        self,
        candidate_url: str,
        cutoff: datetime,
        original_url: str,
    ) -> dict[str, Any] | None:
        payload = self.http.get_json(
            self.api_url,
            {
                "url": candidate_url,
                "timestamp": _wayback_timestamp(cutoff),
                "closest": "before",
            },
        )
        closest = (
            payload.get("archived_snapshots", {}).get("closest")
            if isinstance(payload, dict)
            else None
        )
        if not isinstance(closest, dict) or not closest.get("available"):
            return None
        timestamp = str(closest.get("timestamp") or "")
        archived_at = _parse_wayback_timestamp(timestamp)
        if archived_at is None:
            return None
        relation = "after_cutoff" if archived_at > cutoff else "at_or_before_cutoff"
        notes = (
            f"Wayback availability API status={closest.get('status')}; "
            f"timestamp={timestamp}; relation={relation}."
        )
        if not _same_url(candidate_url, original_url):
            notes = f"{notes} Matched URL variant: {candidate_url}."
        return {
            "archive_url": str(closest.get("url") or ""),
            "archived_at": archived_at.isoformat(),
            "original_url": original_url,
            "verified_at": utc_now().replace(microsecond=0).isoformat(),
            "verification_method": "wayback_available_api",
            "cutoff_relation": relation,
            "notes": notes,
        }

    def _archive_before_cdx(
        self,
        candidate_url: str,
        cutoff: datetime,
        original_url: str,
    ) -> dict[str, Any] | None:
        payload = self.http.get_json(
            self.cdx_url,
            {
                "url": candidate_url,
                "to": _wayback_timestamp(cutoff),
                "output": "json",
                "fl": "timestamp,original,statuscode,mimetype",
                "filter": "statuscode:200",
                "sort": "reverse",
                "limit": 1,
            },
        )
        row = _first_cdx_row(payload)
        if row is None:
            return None
        timestamp = str(row.get("timestamp") or "")
        archived_at = _parse_wayback_timestamp(timestamp)
        if archived_at is None or archived_at > cutoff:
            return None
        matched_url = str(row.get("original") or candidate_url)
        notes = (
            "Wayback CDX API status=200; "
            f"timestamp={timestamp}; matched_url={matched_url}; mimetype={row.get('mimetype')}."
        )
        return {
            "archive_url": f"http://web.archive.org/web/{timestamp}/{matched_url}",
            "archived_at": archived_at.isoformat(),
            "original_url": original_url,
            "verified_at": utc_now().replace(microsecond=0).isoformat(),
            "verification_method": "wayback_cdx_api",
            "notes": notes,
        }


class SourceArchiveBackfiller:
    """Discovers cutoff-valid historical archive proofs for source logs."""

    def __init__(
        self,
        research_root: Path | str = Path("data/research"),
        client: WaybackAvailabilityClient | None = None,
    ) -> None:
        self.research_root = Path(research_root)
        self.client = client or WaybackAvailabilityClient()

    def discover(
        self,
        event_ids: Iterable[str] | None = None,
        write: bool = False,
        limit: int | None = None,
    ) -> SourceArchiveDiscoveryReport:
        selected = set(event_ids or [])
        rows: list[SourceArchiveDiscoveryRow] = []
        source_log_count = 0
        source_count = 0
        sources_updated = 0

        for path in sorted(self.research_root.glob("*/source_log.json")):
            event_id = path.parent.name
            if selected and event_id not in selected:
                continue
            if limit is not None and source_log_count >= limit:
                break
            source_log_count += 1
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                rows.append(
                    SourceArchiveDiscoveryRow(
                        event_id=event_id,
                        source_index=-1,
                        url="",
                        knowledge_cutoff=None,
                        captured_at=None,
                        status="invalid_source_log",
                        error=str(exc),
                    )
                )
                continue
            sources = raw.get("sources", [])
            if not isinstance(sources, list):
                rows.append(
                    SourceArchiveDiscoveryRow(
                        event_id=event_id,
                        source_index=-1,
                        url="",
                        knowledge_cutoff=str(raw.get("knowledge_cutoff")) if raw.get("knowledge_cutoff") else None,
                        captured_at=None,
                        status="invalid_sources",
                    )
                )
                continue
            changed = False
            for index, source in enumerate(sources):
                if not isinstance(source, dict):
                    continue
                source_count += 1
                row, proof = self._discover_source(event_id, index, raw, source)
                rows.append(row)
                if proof is not None and write and source.get("historical_archive") != proof:
                    source["historical_archive"] = proof
                    changed = True
                    sources_updated += 1
            if changed:
                path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

        return SourceArchiveDiscoveryReport(
            generated_at=utc_now().replace(microsecond=0).isoformat(),
            research_root=str(self.research_root),
            write=write,
            source_log_count=source_log_count,
            source_count=source_count,
            candidate_count=sum(1 for row in rows if row.historical_archive is not None),
            sources_updated=sources_updated,
            status_counts=_status_counts(row.status for row in rows),
            rows=tuple(rows),
        )

    def _discover_source(
        self,
        event_id: str,
        index: int,
        raw: dict[str, Any],
        source: dict[str, Any],
    ) -> tuple[SourceArchiveDiscoveryRow, dict[str, Any] | None]:
        url = str(source.get("url") or "")
        cutoff = str(source.get("knowledge_cutoff") or raw.get("knowledge_cutoff") or "") or None
        captured = str(source.get("captured_at") or "") or None
        cutoff_dt = parse_dt(cutoff) if cutoff else None
        captured_dt = parse_dt(captured) if captured else None
        raw_claim_ids = source.get("used_in_claim_ids", [])
        if isinstance(raw_claim_ids, (list, tuple)):
            used_in_claim_ids = tuple(str(claim_id) for claim_id in raw_claim_ids if claim_id)
        elif raw_claim_ids:
            used_in_claim_ids = (str(raw_claim_ids),)
        else:
            used_in_claim_ids = ()
        base = {
            "event_id": event_id,
            "event_name": str(raw.get("event_name") or "") or None,
            "source_index": index,
            "url": url,
            "source": str(source.get("source") or "") or None,
            "title": str(source.get("title") or "") or None,
            "source_class": str(source.get("source_class") or "") or None,
            "published_at": str(source.get("published_at") or "") or None,
            "observed_at": str(source.get("observed_at") or "") or None,
            "knowledge_cutoff": cutoff,
            "captured_at": captured,
            "used_in_claim_ids": used_in_claim_ids,
        }
        if source.get("historical_archive"):
            return SourceArchiveDiscoveryRow(**base, status="already_has_archive", historical_archive=source.get("historical_archive")), None
        if not url.startswith(("http://", "https://")):
            return SourceArchiveDiscoveryRow(**base, status="unsupported_url"), None
        if cutoff_dt is None:
            return SourceArchiveDiscoveryRow(**base, status="missing_cutoff"), None
        if captured_dt is not None and captured_dt <= cutoff_dt:
            return SourceArchiveDiscoveryRow(**base, status="not_retrospective"), None
        try:
            proof = self.client.archive_before(url, _ensure_utc(cutoff_dt))
        except Exception as exc:  # noqa: BLE001 - discovery should be per-source resilient.
            return SourceArchiveDiscoveryRow(**base, status="archive_lookup_failed", error=str(exc)), None
        if proof is None:
            try:
                nearest = self.client.nearest_capture(url, _ensure_utc(cutoff_dt))
            except Exception as exc:  # noqa: BLE001 - keep archive diagnostics non-blocking.
                nearest = {
                    "error": str(exc),
                    "original_url": url,
                    "verified_at": utc_now().replace(microsecond=0).isoformat(),
                    "verification_method": "wayback_available_api",
                }
            return SourceArchiveDiscoveryRow(
                **base,
                status="no_archive_before_cutoff",
                nearest_archive=nearest,
            ), None
        candidate_source = dict(source)
        candidate_source["historical_archive"] = proof
        findings = historical_archive_findings(candidate_source, cutoff_dt, "__archive_discovery__")
        if findings:
            return (
                SourceArchiveDiscoveryRow(
                    **base,
                    status="invalid_archive_candidate",
                    historical_archive=proof,
                    error="; ".join(f"{finding.code}: {finding.detail}" for finding in findings),
                ),
                None,
            )
        return SourceArchiveDiscoveryRow(**base, status="archive_candidate", historical_archive=proof), proof


def historical_archive_findings(
    source: dict[str, Any],
    cutoff_dt: datetime | None,
    claim_id: str,
    claim: EvidenceClaim | None = None,
) -> list[SourceAuditFinding]:
    archive = source.get("historical_archive")
    if archive is None:
        return []
    if not isinstance(archive, dict):
        return [
            SourceAuditFinding(
                claim_id,
                "error",
                "invalid_historical_archive",
                "historical_archive must be an object.",
            )
        ]
    missing = [
        field
        for field in ("archive_url", "archived_at", "original_url", "verified_at", "verification_method")
        if not archive.get(field)
    ]
    if missing:
        return [
            SourceAuditFinding(
                claim_id,
                "error",
                "invalid_historical_archive",
                f"historical_archive missing required fields: {', '.join(missing)}.",
            )
        ]
    findings: list[SourceAuditFinding] = []
    archived_at = parse_dt(str(archive.get("archived_at")))
    verified_at = parse_dt(str(archive.get("verified_at")))
    if archived_at is None:
        findings.append(
            SourceAuditFinding(
                claim_id,
                "error",
                "invalid_historical_archive",
                f"historical_archive archived_at is invalid: {archive.get('archived_at')!r}.",
            )
        )
    if verified_at is None:
        findings.append(
            SourceAuditFinding(
                claim_id,
                "error",
                "invalid_historical_archive",
                f"historical_archive verified_at is invalid: {archive.get('verified_at')!r}.",
            )
        )
    if cutoff_dt is not None and archived_at is not None and archived_at > cutoff_dt:
        findings.append(
            SourceAuditFinding(
                claim_id,
                "error",
                "historical_archive_after_cutoff",
                f"historical_archive archived_at={archived_at.isoformat()} is after the replay cutoff={cutoff_dt.isoformat()}.",
            )
        )
    if not _same_url(str(archive.get("original_url")), str(source.get("url"))):
        findings.append(
            SourceAuditFinding(
                claim_id,
                "error",
                "historical_archive_url_mismatch",
                "historical_archive original_url does not match the source url.",
            )
        )
    timestamp_checks: list[tuple[str, str | None, str]] = [
        ("source published_at", source.get("published_at"), "source_published_after_historical_archive"),
        ("source observed_at", source.get("observed_at"), "source_observed_after_historical_archive"),
    ]
    if claim is not None:
        timestamp_checks.extend(
            [
                ("claim published_at", claim.published_at, "claim_published_after_historical_archive"),
                ("claim observed_at", claim.observed_at, "claim_observed_after_historical_archive"),
            ]
        )
    for label, timestamp, code in timestamp_checks:
        timestamp_dt = parse_dt(str(timestamp)) if timestamp else None
        if archived_at is not None and timestamp_dt is not None and timestamp_dt > archived_at:
            findings.append(
                SourceAuditFinding(
                    claim_id,
                    "error",
                    code,
                    f"{label}={timestamp} is later than historical archive archived_at={archived_at.isoformat()}.",
                )
            )
    return findings


def source_has_cutoff_archive_proof(source: dict[str, Any], cutoff_dt: datetime | None) -> bool:
    if cutoff_dt is None:
        return False
    return not historical_archive_findings(source, cutoff_dt, "__source__") and source.get("historical_archive") is not None


def _same_url(left: str, right: str) -> bool:
    return left.rstrip("/#") == right.rstrip("/#")


def _wayback_url_variants(url: str) -> tuple[str, ...]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return (url,)
    variants: list[str] = []

    def add(candidate: str) -> None:
        normalized = candidate.rstrip("#")
        if normalized not in variants:
            variants.append(normalized)

    add(url)
    alternate_scheme = "http" if parsed.scheme == "https" else "https"
    add(urlunparse(parsed._replace(scheme=alternate_scheme)))
    return tuple(variants)


def _first_cdx_row(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, list) or len(payload) < 2:
        return None
    header = payload[0]
    row = payload[1]
    if not isinstance(header, list) or not isinstance(row, list):
        return None
    values = {str(name): row[index] for index, name in enumerate(header) if index < len(row)}
    if not values.get("timestamp"):
        return None
    return values


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _wayback_timestamp(value: datetime) -> str:
    return _ensure_utc(value).strftime("%Y%m%d%H%M%S")


def _parse_wayback_timestamp(value: str) -> datetime | None:
    if not re.fullmatch(r"\d{14}", value):
        return None
    return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def _status_counts(statuses: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for status in statuses:
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))
