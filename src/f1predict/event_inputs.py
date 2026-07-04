"""Event-input provenance and quality classification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from f1predict.domain import RaceEvent


@dataclass(frozen=True)
class EventInputAudit:
    quality: str
    risk_codes: tuple[str, ...]
    verified_fields: tuple[str, ...]
    derived_fields: tuple[str, ...]
    heuristic_fields: tuple[str, ...]
    placeholder_fields: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality": self.quality,
            "risk_codes": list(self.risk_codes),
            "verified_fields": list(self.verified_fields),
            "derived_fields": list(self.derived_fields),
            "heuristic_fields": list(self.heuristic_fields),
            "placeholder_fields": list(self.placeholder_fields),
        }


def audit_event_input(event: RaceEvent | dict[str, Any] | None) -> EventInputAudit:
    """Classify whether an event row is fully sourced or still heuristic.

    The audit is intentionally conservative. It does not bless a generated
    event as formal-ready just because it has a real calendar row or result;
    simulation-driving fields such as track profile and weather priors must
    also have sourced or derived provenance before the blocker disappears.
    """

    if event is None:
        return EventInputAudit(
            quality="missing_event_input",
            risk_codes=("missing_event_input",),
            verified_fields=(),
            derived_fields=(),
            heuristic_fields=(),
            placeholder_fields=(),
        )

    feature_refs = _feature_refs(event)
    source = str(feature_refs.get("event_source") or "seed")
    if source != "openf1_calendar_generated":
        quality = "seed_with_fastf1_result" if feature_refs.get("result_source") else "seed"
        return EventInputAudit(
            quality=quality,
            risk_codes=(),
            verified_fields=("event_metadata",),
            derived_fields=(),
            heuristic_fields=(),
            placeholder_fields=(),
        )

    provenance = feature_refs.get("event_input_provenance")
    if not isinstance(provenance, dict):
        return EventInputAudit(
            quality="generated_structure_only",
            risk_codes=("generated_structure_only_event_input",),
            verified_fields=(),
            derived_fields=(),
            heuristic_fields=(),
            placeholder_fields=(),
        )

    verified = _fields_with_quality(provenance, "verified")
    derived = _fields_with_quality(provenance, "derived")
    heuristic = _fields_with_quality(provenance, "heuristic")
    placeholder = _fields_with_quality(provenance, "placeholder")
    risk_codes: list[str] = []
    if not verified:
        risk_codes.append("generated_structure_only_event_input")
    if heuristic or placeholder:
        risk_codes.append("heuristic_generated_event_profile")

    if "generated_structure_only_event_input" in risk_codes:
        quality = "generated_structure_only"
    elif placeholder:
        quality = "generated_with_placeholder_profile"
    elif "heuristic_generated_event_profile" in risk_codes:
        quality = "generated_with_partial_verified_profile"
    elif verified or derived:
        quality = "generated_verified"
    else:
        quality = "generated_with_heuristic_profile"

    return EventInputAudit(
        quality=quality,
        risk_codes=tuple(dict.fromkeys(risk_codes)),
        verified_fields=verified,
        derived_fields=derived,
        heuristic_fields=heuristic,
        placeholder_fields=placeholder,
    )


def _feature_refs(event: RaceEvent | dict[str, Any]) -> dict[str, Any]:
    if isinstance(event, RaceEvent):
        refs = event.feature_refs
    else:
        refs = event.get("feature_refs")
    return refs if isinstance(refs, dict) else {}


def _fields_with_quality(provenance: dict[str, Any], quality: str) -> tuple[str, ...]:
    fields = []
    for field, raw in provenance.items():
        if not isinstance(raw, dict):
            continue
        raw_quality = raw.get("quality")
        if raw_quality == quality or (quality == "verified" and raw_quality == "verified_visual"):
            fields.append(str(field))
    return tuple(sorted(fields))
