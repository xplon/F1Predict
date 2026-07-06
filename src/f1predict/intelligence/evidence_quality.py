"""Source-aware quality scoring for normalized Codex evidence claims."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from f1predict.domain import EvidenceClaim, EvidenceImpact, EvidenceQuality, parse_dt
from f1predict.intelligence.source_registry import DEFAULT_SOURCE_RELIABILITY, source_has_cutoff_archive_proof
from f1predict.storage import safe_name


@dataclass(frozen=True)
class _SourceRecord:
    url: str
    source_class: str | None
    reliability: float | None
    cutoff_status: str | None
    published_at: str | None
    captured_at: str | None
    historical_archive: dict[str, Any] | None
    used_in_claim_ids: tuple[str, ...]


@dataclass(frozen=True)
class _TriangulationContext:
    status: str
    score: float
    corroborating_claim_count: int
    corroborating_source_count: int
    independent_source_count: int
    risk_flags: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class _ConflictContext:
    status: str
    score: float
    conflicting_claim_count: int
    conflicting_source_count: int
    conflicting_independent_source_count: int
    risk_flags: tuple[str, ...]
    reasons: tuple[str, ...]


_NO_TRIANGULATION = _TriangulationContext(
    status="unlinked_source",
    score=0.55,
    corroborating_claim_count=0,
    corroborating_source_count=0,
    independent_source_count=0,
    risk_flags=("unlinked_source_triangulation",),
    reasons=("No source URL could be linked for triangulation.",),
)

_NO_CONFLICT = _ConflictContext(
    status="no_conflict",
    score=1.0,
    conflicting_claim_count=0,
    conflicting_source_count=0,
    conflicting_independent_source_count=0,
    risk_flags=(),
    reasons=(),
)


class EvidenceQualityScorer:
    """Scores LLM-produced evidence after source and impact normalization.

    This is an audit layer, not a probability model. It makes Codex inputs
    inspectable by combining the claim's own confidence, source registry
    metadata, cutoff status, review flags, and diagnostic probability impact.
    """

    def __init__(self, research_root: Path | str = Path("data/research")) -> None:
        self.research_root = Path(research_root)

    def score_event(
        self,
        event_id: str,
        claims: list[EvidenceClaim],
        impacts: list[EvidenceImpact],
        knowledge_cutoff: datetime | None = None,
    ) -> list[EvidenceQuality]:
        source_records = self._source_records(event_id)
        impact_by_claim = {row.claim_id: row for row in impacts}
        triangulation_by_claim = self._triangulation_contexts(claims, source_records)
        conflict_by_claim = self._conflict_contexts(claims, source_records)
        rows = [
            self._score_claim(
                claim,
                source_records,
                impact_by_claim.get(claim.claim_id),
                triangulation_by_claim.get(claim.claim_id, _NO_TRIANGULATION),
                conflict_by_claim.get(claim.claim_id, _NO_CONFLICT),
                knowledge_cutoff,
            )
            for claim in claims
        ]
        return sorted(rows, key=lambda row: (row.quality_score, abs(row.signed_input_impact)), reverse=True)

    def _score_claim(
        self,
        claim: EvidenceClaim,
        source_records: dict[str, list[_SourceRecord]],
        impact: EvidenceImpact | None,
        triangulation: _TriangulationContext,
        conflict: _ConflictContext,
        knowledge_cutoff: datetime | None,
    ) -> EvidenceQuality:
        records = source_records.get(claim.source_url, [])
        linked_records = [
            record for record in records
            if not record.used_in_claim_ids or claim.claim_id in record.used_in_claim_ids
        ]
        selected = linked_records[0] if linked_records else records[0] if records else None
        source_reliability = self._source_reliability(claim, selected)
        source_factor = source_reliability if source_reliability is not None else 0.45
        claim_factor = _clamp(claim.confidence * max(0.0, 1.0 - claim.uncertainty))
        text_factor = self._text_factor(claim)
        cutoff_factor, source_status, cutoff_reasons, cutoff_flags = self._cutoff_factor(
            claim,
            selected,
            knowledge_cutoff,
        )
        review_factor = 0.82 if claim.review_required else 1.0
        base_score = _clamp(
            claim_factor * 0.40
            + source_factor * 0.32
            + text_factor * 0.18
            + triangulation.score * 0.10
        )
        quality_score = round(base_score * cutoff_factor * review_factor * conflict.score, 4)
        max_delta = impact.max_win_probability_delta if impact else None
        impact_level = self._impact_level(max_delta)
        flags: list[str] = []
        reasons: list[str] = [
            f"claim_confidence={claim.confidence:.2f}, uncertainty={claim.uncertainty:.2f}",
            f"source_reliability={source_reliability:.2f}" if source_reliability is not None else "source_reliability=unknown",
            f"source_status={source_status}",
            f"triangulation={triangulation.status}",
            f"conflict={conflict.status}",
            f"impact_level={impact_level}",
        ]
        if claim.review_required:
            flags.append("claim_requires_review")
            reasons.append("Claim is explicitly marked review_required.")
        if claim.source_url.startswith("seed://"):
            flags.append("seed_scenario_source")
            reasons.append("Seed scenario evidence is useful for plumbing but not formal edge evidence.")
        if not records:
            flags.append("source_log_missing")
            reasons.append("No source_log entry was found for this claim URL.")
        elif linked_records != records and not linked_records:
            flags.append("claim_not_linked_to_source_record")
            reasons.append("Source URL exists but used_in_claim_ids does not link this claim.")
        flags.extend(cutoff_flags)
        flags.extend(triangulation.risk_flags)
        flags.extend(conflict.risk_flags)
        reasons.extend(cutoff_reasons)
        reasons.extend(triangulation.reasons)
        reasons.extend(conflict.reasons)
        if quality_score >= 0.70 and not flags:
            quality_status = "strong"
        elif quality_score >= 0.52 and not any(flag.endswith("after_cutoff") for flag in flags):
            quality_status = "usable_diagnostic"
        elif quality_score >= 0.35:
            quality_status = "weak_diagnostic"
        else:
            quality_status = "review_required"
        model_input_weight = self._model_input_weight(quality_score, flags=flags, conflict=conflict)
        reasons.append(f"model_input_weight={model_input_weight:.2f}")
        return EvidenceQuality(
            claim_id=claim.claim_id,
            source=claim.source,
            quality_status=quality_status,
            quality_score=quality_score,
            source_reliability=round(source_reliability, 4) if source_reliability is not None else None,
            source_status=source_status,
            triangulation_status=triangulation.status,
            triangulation_score=round(triangulation.score, 4),
            conflict_status=conflict.status,
            conflict_score=round(conflict.score, 4),
            corroborating_claim_count=triangulation.corroborating_claim_count,
            corroborating_source_count=triangulation.corroborating_source_count,
            independent_source_count=triangulation.independent_source_count,
            conflicting_claim_count=conflict.conflicting_claim_count,
            conflicting_source_count=conflict.conflicting_source_count,
            conflicting_independent_source_count=conflict.conflicting_independent_source_count,
            model_input_weight=model_input_weight,
            evidence_strength=round(claim_factor, 4),
            impact_level=impact_level,
            signed_input_impact=round(claim.signed_impact(), 4),
            max_win_probability_delta=max_delta,
            risk_flags=tuple(dict.fromkeys(flags)),
            reasons=tuple(reasons),
        )

    def _source_records(self, event_id: str) -> dict[str, list[_SourceRecord]]:
        source_log = self.research_root / safe_name(event_id) / "source_log.json"
        if not source_log.exists():
            return {}
        raw = json.loads(source_log.read_text(encoding="utf-8"))
        records: dict[str, list[_SourceRecord]] = {}
        for item in raw.get("sources", []):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            if not url:
                continue
            records.setdefault(url, []).append(
                _SourceRecord(
                    url=url,
                    source_class=str(item.get("source_class") or "") or None,
                    reliability=_as_float(item.get("reliability")),
                    cutoff_status=str(item.get("cutoff_status") or "") or None,
                    published_at=str(item.get("published_at") or "") or None,
                    captured_at=str(item.get("captured_at") or "") or None,
                    historical_archive=item.get("historical_archive") if isinstance(item.get("historical_archive"), dict) else None,
                    used_in_claim_ids=tuple(str(value) for value in (item.get("used_in_claim_ids") or [])),
                )
            )
        return records

    @staticmethod
    def _triangulation_contexts(
        claims: list[EvidenceClaim],
        source_records: dict[str, list[_SourceRecord]],
    ) -> dict[str, _TriangulationContext]:
        groups: dict[tuple[str, str, str, str], list[EvidenceClaim]] = {}
        for claim in claims:
            groups.setdefault(
                (
                    str(claim.target_type),
                    str(claim.target_id),
                    str(claim.metric),
                    str(claim.direction),
                ),
                [],
            ).append(claim)

        contexts: dict[str, _TriangulationContext] = {}
        for group_claims in groups.values():
            source_urls = sorted(
                {
                    url
                    for group_claim in group_claims
                    for url in EvidenceQualityScorer._claim_source_urls(group_claim, source_records)
                }
            )
            source_classes = sorted(
                {
                    source_class
                    for group_claim in group_claims
                    for source_class in EvidenceQualityScorer._claim_source_classes(group_claim, source_records)
                }
            )
            source_domains = sorted(
                {
                    EvidenceQualityScorer._source_domain(url)
                    for url in source_urls
                    if EvidenceQualityScorer._source_domain(url)
                }
            )
            non_scenario_domains = [
                domain for domain in source_domains
                if domain not in {"seed", "test"}
            ]
            independent_count = max(len(non_scenario_domains), len(source_classes))
            scenario_only = bool(source_urls) and all(
                url.startswith("seed://") or url.startswith("test://")
                for url in source_urls
            )

            flags: list[str] = []
            reasons: list[str] = []
            if len(source_urls) >= 2 and independent_count >= 2 and not scenario_only:
                status = "independent_corroboration"
                score = 1.0
                reasons.append(
                    f"{len(group_claims)} related claims are supported by {len(source_urls)} sources "
                    f"across {independent_count} independent source groups."
                )
            elif len(group_claims) >= 2 and len(source_urls) >= 1:
                status = "same_source_repetition" if len(source_urls) == 1 else "limited_corroboration"
                score = 0.86 if len(source_urls) == 1 else 0.92
                flags.append(status)
                reasons.append(
                    f"{len(group_claims)} related claims exist, but independent source diversity is limited."
                )
            elif scenario_only:
                status = "seed_or_test_only"
                score = 0.68
                flags.append("seed_only_triangulation")
                reasons.append("The claim is supported only by seed/test scenario sources.")
            elif source_urls:
                status = "single_source"
                score = 0.78
                flags.append("single_source_claim")
                reasons.append("Only one source currently supports this normalized claim direction.")
            else:
                status = "unlinked_source"
                score = 0.55
                flags.append("unlinked_source_triangulation")
                reasons.append("No source URL could be linked for triangulation.")

            context = _TriangulationContext(
                status=status,
                score=score,
                corroborating_claim_count=len(group_claims),
                corroborating_source_count=len(source_urls),
                independent_source_count=independent_count,
                risk_flags=tuple(flags),
                reasons=tuple(reasons),
            )
            for group_claim in group_claims:
                contexts[group_claim.claim_id] = context
        return contexts

    @staticmethod
    def _conflict_contexts(
        claims: list[EvidenceClaim],
        source_records: dict[str, list[_SourceRecord]],
    ) -> dict[str, _ConflictContext]:
        groups: dict[tuple[str, str, str], list[EvidenceClaim]] = {}
        for claim in claims:
            groups.setdefault(
                (
                    str(claim.target_type),
                    str(claim.target_id),
                    str(claim.metric),
                ),
                [],
            ).append(claim)

        contexts: dict[str, _ConflictContext] = {}
        for group_claims in groups.values():
            for claim in group_claims:
                opposing = [
                    other
                    for other in group_claims
                    if other.claim_id != claim.claim_id
                    and EvidenceQualityScorer._directions_conflict(claim.direction, other.direction)
                ]
                if not opposing:
                    contexts[claim.claim_id] = _NO_CONFLICT
                    continue
                conflict_claims = [claim, *opposing]
                source_urls = sorted(
                    {
                        url
                        for conflict_claim in conflict_claims
                        for url in EvidenceQualityScorer._claim_source_urls(conflict_claim, source_records)
                    }
                )
                source_classes = sorted(
                    {
                        source_class
                        for conflict_claim in conflict_claims
                        for source_class in EvidenceQualityScorer._claim_source_classes(conflict_claim, source_records)
                    }
                )
                source_domains = sorted(
                    {
                        EvidenceQualityScorer._source_domain(url)
                        for url in source_urls
                        if EvidenceQualityScorer._source_domain(url)
                    }
                )
                non_scenario_domains = [
                    domain for domain in source_domains
                    if domain not in {"seed", "test"}
                ]
                independent_count = max(len(non_scenario_domains), len(source_classes))
                scenario_only = bool(source_urls) and all(
                    url.startswith("seed://") or url.startswith("test://")
                    for url in source_urls
                )
                flags = ["conflicting_claim_direction"]
                reasons = [
                    f"{len(opposing)} opposing claim(s) disagree on {claim.target_type}:{claim.target_id} {claim.metric}."
                ]
                if independent_count >= 2 and not scenario_only:
                    status = "independent_source_conflict"
                    score = 0.58
                    flags.append("independent_source_conflict")
                    reasons.append(
                        f"Opposing claims are supported by {len(source_urls)} source URL(s) "
                        f"across {independent_count} independent source groups."
                    )
                elif scenario_only:
                    status = "seed_or_test_conflict"
                    score = 0.78
                    flags.append("seed_conflict")
                    reasons.append("Opposing claims are only seed/test scenario inputs.")
                elif len(source_urls) <= 1:
                    status = "same_source_conflict"
                    score = 0.72
                    flags.append("same_source_conflict")
                    reasons.append("Opposing claims are not independently sourced yet.")
                else:
                    status = "limited_source_conflict"
                    score = 0.66
                    flags.append("limited_source_conflict")
                    reasons.append("Opposing claims have limited independent source diversity.")
                contexts[claim.claim_id] = _ConflictContext(
                    status=status,
                    score=score,
                    conflicting_claim_count=len(opposing),
                    conflicting_source_count=len(source_urls),
                    conflicting_independent_source_count=independent_count,
                    risk_flags=tuple(flags),
                    reasons=tuple(reasons),
                )
        return contexts

    @staticmethod
    def _directions_conflict(left: str, right: str) -> bool:
        return {left, right} == {"positive", "negative"}

    @staticmethod
    def _claim_source_urls(
        claim: EvidenceClaim,
        source_records: dict[str, list[_SourceRecord]],
    ) -> tuple[str, ...]:
        records = source_records.get(claim.source_url, [])
        linked_records = [
            record for record in records
            if not record.used_in_claim_ids or claim.claim_id in record.used_in_claim_ids
        ]
        if linked_records:
            return tuple(sorted({record.url for record in linked_records if record.url}))
        return (claim.source_url,) if claim.source_url else ()

    @staticmethod
    def _claim_source_classes(
        claim: EvidenceClaim,
        source_records: dict[str, list[_SourceRecord]],
    ) -> tuple[str, ...]:
        records = source_records.get(claim.source_url, [])
        linked_records = [
            record for record in records
            if not record.used_in_claim_ids or claim.claim_id in record.used_in_claim_ids
        ]
        classes = sorted(
            {
                str(record.source_class)
                for record in linked_records
                if record.source_class
            }
        )
        if classes:
            return tuple(classes)
        if claim.source_url.startswith("seed://"):
            return ("seed",)
        if claim.source_url.startswith("test://"):
            return ("test",)
        return ()

    @staticmethod
    def _source_domain(url: str) -> str:
        if url.startswith("seed://"):
            return "seed"
        if url.startswith("test://"):
            return "test"
        parsed = urlparse(url)
        return parsed.netloc.lower()

    @staticmethod
    def _source_reliability(claim: EvidenceClaim, record: _SourceRecord | None) -> float | None:
        if record and record.reliability is not None:
            return _clamp(record.reliability)
        if record and record.source_class:
            return DEFAULT_SOURCE_RELIABILITY.get(record.source_class)
        if claim.source_url.startswith("seed://"):
            return 0.30
        if claim.source_url.startswith("test://"):
            return 0.20
        return None

    @staticmethod
    def _text_factor(claim: EvidenceClaim) -> float:
        combined = f"{claim.evidence_text} {claim.reasoning}".strip()
        if len(combined) >= 220:
            return 0.85
        if len(combined) >= 120:
            return 0.70
        if len(combined) >= 60:
            return 0.55
        return 0.35

    @staticmethod
    def _cutoff_factor(
        claim: EvidenceClaim,
        record: _SourceRecord | None,
        knowledge_cutoff: datetime | None,
    ) -> tuple[float, str, list[str], list[str]]:
        reasons: list[str] = []
        flags: list[str] = []
        if record is None:
            return 0.78, "source_log_missing", reasons, flags
        status = record.cutoff_status or "unknown"
        factor = 1.0
        if status.startswith("after_cutoff"):
            factor = 0.45
            flags.append("source_after_cutoff")
            reasons.append(f"Source cutoff status is {status}.")
        elif status == "unknown_published_at":
            factor = 0.70
            flags.append("unknown_published_at")
            reasons.append("Source published_at is unknown.")
        if knowledge_cutoff is not None:
            observed = parse_dt(claim.observed_at)
            published = parse_dt(claim.published_at)
            if observed is None or published is None or observed > knowledge_cutoff or published > knowledge_cutoff:
                factor = min(factor, 0.45)
                flags.append("claim_after_cutoff")
                reasons.append("Claim timestamps are not available before the prediction cutoff.")
            captured = parse_dt(record.captured_at)
            archive_ok = source_has_cutoff_archive_proof(
                {
                    "url": record.url,
                    "published_at": record.published_at,
                    "historical_archive": record.historical_archive,
                    "captured_at": record.captured_at,
                },
                knowledge_cutoff,
            )
            if captured is not None and captured > knowledge_cutoff and not archive_ok:
                factor = min(factor, 0.62)
                flags.append("snapshot_after_cutoff")
                reasons.append("Source snapshot was captured after cutoff without archive proof.")
            if archive_ok:
                status = "archive_backed"
                reasons.append("Historical archive proof supports cutoff availability.")
        return factor, status, reasons, flags

    @staticmethod
    def _impact_level(max_delta: float | None) -> str:
        if max_delta is None:
            return "not_modeled"
        magnitude = abs(max_delta)
        if magnitude >= 0.03:
            return "material"
        if magnitude >= 0.01:
            return "moderate"
        if magnitude > 0:
            return "small"
        return "none"

    @staticmethod
    def _model_input_weight(
        quality_score: float,
        flags: list[str] | tuple[str, ...],
        conflict: _ConflictContext,
    ) -> float:
        if "claim_after_cutoff" in flags or "source_after_cutoff" in flags:
            return 0.0
        if "seed_scenario_source" in flags:
            return 0.0
        weight = _clamp(0.18 + quality_score)
        if "snapshot_after_cutoff" in flags:
            weight = min(weight, 0.55)
        if "claim_requires_review" in flags:
            weight = min(weight, 0.72)
        if "seed_only_triangulation" in flags:
            weight = min(weight, 0.62)
        if conflict.status != "no_conflict":
            weight = min(weight, conflict.score)
        if "source_log_missing" in flags or "claim_not_linked_to_source_record" in flags:
            weight = min(weight, 0.55)
        return round(_clamp(weight), 4)


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
