"""Shared contract for turning Codex claims into simulator factors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from f1predict.domain import EvidenceClaim
from f1predict.intelligence.factor_trace import FACTOR_ROUTES, TRACK_CONTEXTUAL_METRICS
from f1predict.models.technical_factors import technical_factor_profile


GENERIC_CLAIM_TYPES = (
    "corroboration",
    "quote",
    "contradiction",
    "risk",
)

TECHNICAL_CONTEXT_TERMS = (
    "track",
    "circuit",
    "layout",
    "corner",
    "straight",
    "full-throttle",
    "full throttle",
    "high-speed",
    "high speed",
    "low-speed",
    "low speed",
    "street",
    "power",
    "altitude",
    "elevation",
    "launch",
    "braking",
    "traction",
    "silverstone",
    "monaco",
    "miami",
    "suzuka",
    "barcelona",
    "red bull ring",
    "canada",
    "montreal",
    "australia",
    "melbourne",
)


@dataclass(frozen=True)
class FactorMetricContract:
    metric: str
    targets: tuple[str, ...]
    valid_claim_types: tuple[str, ...]
    notes: str
    mechanism_terms: tuple[str, ...] = ()
    context_terms: tuple[str, ...] = ()

    def to_guidance(self) -> dict[str, Any]:
        route = FACTOR_ROUTES.get(self.metric)
        profile = technical_factor_profile(self.metric)
        return {
            "targets": list(self.targets),
            "valid_claim_types": list(self.valid_claim_types),
            "notes": self.notes,
            "route": route.route if route else "unsupported_metric",
            "model_surface": route.model_surface if route else "not routed",
            "route_notes": list(route.notes) if route else ["Metric has no simulator route."],
            "technical_contextual": self.metric in TRACK_CONTEXTUAL_METRICS,
            "technical_mechanism": profile.mechanism if profile else None,
            "track_demand_component": profile.demand_component if profile else None,
            "required_mechanism_terms": list(self.mechanism_terms),
            "required_context_terms": list(self.context_terms),
        }


@dataclass(frozen=True)
class FactorContractIssue:
    severity: str
    code: str
    detail: str


_CONTRACTS: dict[str, FactorMetricContract] = {
    "race_pace": FactorMetricContract(
        metric="race_pace",
        targets=("team", "driver"),
        valid_claim_types=(
            "upgrade",
            "track_fit",
            "long_run",
            "setup",
            "form",
            "session_pace",
            "race_week_pace_signal",
            "race_week_qualifying_signal",
            *GENERIC_CLAIM_TYPES,
        ),
        notes="Use for clean-air or long-run speed. Do not use headline practice fastest laps alone.",
    ),
    "qualifying_pace": FactorMetricContract(
        metric="qualifying_pace",
        targets=("team", "driver"),
        valid_claim_types=(
            "single_lap",
            "traffic",
            "warmup",
            "grid_penalty",
            "session_pace",
            "sector_pace",
            "race_week_qualifying_signal",
            "qualifying_signal",
            *GENERIC_CLAIM_TYPES,
        ),
        notes="Use for low-fuel or grid-position signals; keep separate from race pace.",
    ),
    "tyre_deg": FactorMetricContract(
        metric="tyre_deg",
        targets=("team", "driver", "event"),
        valid_claim_types=(
            "long_run",
            "track_temperature",
            "compound",
            "thermal_deg",
            "tyre_deg",
            "tyre_degradation",
            *GENERIC_CLAIM_TYPES,
        ),
        notes="Positive direction means better tyre management or lower degradation.",
    ),
    "reliability": FactorMetricContract(
        metric="reliability",
        targets=("team", "driver"),
        valid_claim_types=(
            "mechanical_issue",
            "power_unit",
            "gearbox",
            "crash_risk",
            "reliability",
            "race_control",
            *GENERIC_CLAIM_TYPES,
        ),
        notes="Positive direction means lower DNF or penalty risk.",
    ),
    "wet_skill": FactorMetricContract(
        metric="wet_skill",
        targets=("driver", "event"),
        valid_claim_types=(
            "weather",
            "weather_forecast",
            "rain_timing",
            "wind",
            "track_condition",
            *GENERIC_CLAIM_TYPES,
        ),
        notes="Event-level weather changes wet probability; driver-level claims affect relative wet performance.",
    ),
    "strategy": FactorMetricContract(
        metric="strategy",
        targets=("team", "event", "market"),
        valid_claim_types=(
            "pit_window",
            "safety_car",
            "compound",
            "market_rules",
            "settlement",
            "candidate_market",
            "strategy",
            *GENERIC_CLAIM_TYPES,
        ),
        notes="Use for pit-loss, safety-car optionality, compound constraints, or settlement interpretation.",
    ),
    "power_unit": FactorMetricContract(
        metric="power_unit",
        targets=("team", "driver"),
        valid_claim_types=("power_unit", "engine_mode", "turbo", "deployment", "track_fit", *GENERIC_CLAIM_TYPES),
        notes="Use for combustion/turbo/power-unit strength. The simulator weights this more on power and high-speed tracks.",
        mechanism_terms=("power unit", "engine", "turbo", "combustion", "deployment", "cooling", "horsepower", "pu"),
        context_terms=TECHNICAL_CONTEXT_TERMS,
    ),
    "energy_recovery": FactorMetricContract(
        metric="energy_recovery",
        targets=("team", "driver"),
        valid_claim_types=("ers", "battery", "clipping", "deployment", "harvesting", *GENERIC_CLAIM_TYPES),
        notes="Use for battery, harvesting, and clipping claims. Positive means stronger deployment or less clipping.",
        mechanism_terms=("ers", "battery", "clipping", "deployment", "deploy", "harvesting", "harvest", "recovery"),
        context_terms=TECHNICAL_CONTEXT_TERMS,
    ),
    "straight_line_speed": FactorMetricContract(
        metric="straight_line_speed",
        targets=("team", "driver"),
        valid_claim_types=("speed_trap", "drag", "deployment", "track_fit", "power_unit", *GENERIC_CLAIM_TYPES),
        notes="Use for straight-line pace that is not purely power-unit reliability. Weighted higher on power/high-speed circuits.",
        mechanism_terms=("straight-line", "straight line", "speed trap", "full-throttle", "full throttle", "drag", "deployment", "top speed"),
        context_terms=TECHNICAL_CONTEXT_TERMS,
    ),
    "drag_efficiency": FactorMetricContract(
        metric="drag_efficiency",
        targets=("team", "driver"),
        valid_claim_types=("aero_efficiency", "rear_wing", "drag", "upgrade", "aero", *GENERIC_CLAIM_TYPES),
        notes="Positive means better speed for a given downforce; negative captures draggy packages or clipping-sensitive setups.",
        mechanism_terms=("drag", "aero", "rear wing", "beam wing", "downforce", "efficiency", "wing level"),
        context_terms=TECHNICAL_CONTEXT_TERMS,
    ),
    "low_speed_traction": FactorMetricContract(
        metric="low_speed_traction",
        targets=("team", "driver"),
        valid_claim_types=("traction", "mechanical_grip", "launch", "slow_corner", "track_fit", *GENERIC_CLAIM_TYPES),
        notes="Use for starts, traction zones, and slow-corner exits. Weighted higher on street and low-speed tracks.",
        mechanism_terms=("traction", "mechanical grip", "launch", "slow corner", "low-speed", "low speed", "corner exit"),
        context_terms=TECHNICAL_CONTEXT_TERMS,
    ),
    "launch_performance": FactorMetricContract(
        metric="launch_performance",
        targets=("team", "driver"),
        valid_claim_types=(
            "launch",
            "start",
            "clutch",
            "turbo",
            "power_unit",
            "deployment",
            "track_fit",
            *GENERIC_CLAIM_TYPES,
        ),
        notes=(
            "Use for sourced launch/start advantages, clutch bite, initial deployment, or low-altitude turbo response. "
            "The simulator applies this to start and first-lap race-time conversion rather than generic pace."
        ),
        mechanism_terms=(
            "launch",
            "start",
            "clutch",
            "bite point",
            "anti-stall",
            "turbo",
            "initial deployment",
            "first corner",
            "turn 1",
        ),
        context_terms=TECHNICAL_CONTEXT_TERMS,
    ),
    "weight": FactorMetricContract(
        metric="weight",
        targets=("team", "driver"),
        valid_claim_types=("overweight", "minimum_weight", "weight_saving", "weight", *GENERIC_CLAIM_TYPES),
        notes="Positive means lighter or closer to minimum weight; negative means overweight or ballast-related loss.",
        mechanism_terms=("weight", "mass", "overweight", "ballast", "minimum weight", "heavy", "lighter", "weight saving"),
        context_terms=TECHNICAL_CONTEXT_TERMS,
    ),
    "upgrade_effect": FactorMetricContract(
        metric="upgrade_effect",
        targets=("team", "driver"),
        valid_claim_types=(
            "upgrade",
            "floor",
            "sidepod",
            "beam_wing",
            "package_validation",
            "aero",
            "track_fit",
            *GENERIC_CLAIM_TYPES,
        ),
        notes="Use only when a specific upgrade is linked to observed or stated performance. Keep review_required for rumors.",
        mechanism_terms=("upgrade", "package", "floor", "sidepod", "beam wing", "front wing", "new part", "validation", "validated", "run-tested", "run tested"),
        context_terms=TECHNICAL_CONTEXT_TERMS,
    ),
}


def factor_metric_contracts() -> dict[str, FactorMetricContract]:
    return dict(_CONTRACTS)


def factor_metric_guidance() -> dict[str, dict[str, Any]]:
    return {metric: contract.to_guidance() for metric, contract in sorted(_CONTRACTS.items())}


def factor_contract_for_metric(metric: str) -> FactorMetricContract | None:
    return _CONTRACTS.get(metric)


def validate_factor_claim_contract(claim: EvidenceClaim) -> tuple[FactorContractIssue, ...]:
    contract = factor_contract_for_metric(claim.metric)
    if contract is None:
        return (
            FactorContractIssue(
                "warning",
                "factor_contract_missing",
                f"metric={claim.metric!r} has no Codex factor contract; routing may be diagnostic only.",
            ),
        )

    issues: list[FactorContractIssue] = []
    if claim.target_type not in contract.targets:
        issues.append(
            FactorContractIssue(
                "error",
                "factor_contract_target_mismatch",
                f"metric={claim.metric!r} accepts target_type in {list(contract.targets)}, got {claim.target_type!r}.",
            )
        )
    if claim.claim_type not in contract.valid_claim_types:
        issues.append(
            FactorContractIssue(
                "error",
                "factor_contract_claim_type_mismatch",
                f"metric={claim.metric!r} accepts claim_type in {list(contract.valid_claim_types)}, got {claim.claim_type!r}.",
            )
        )
    if claim.metric in TRACK_CONTEXTUAL_METRICS:
        claim_text = " ".join(
            [
                claim.evidence_text,
                claim.reasoning,
            ]
        ).lower()
        if contract.mechanism_terms and not _contains_any_term(claim_text, contract.mechanism_terms):
            issues.append(
                FactorContractIssue(
                    "error",
                    "factor_contract_missing_technical_mechanism",
                    (
                        f"metric={claim.metric!r} requires an explicit technical mechanism term "
                        f"such as {list(contract.mechanism_terms[:6])} in evidence_text or reasoning."
                    ),
                )
            )
        if contract.context_terms and not _contains_any_term(claim_text, contract.context_terms):
            issues.append(
                FactorContractIssue(
                    "error",
                    "factor_contract_missing_track_context",
                    (
                        f"metric={claim.metric!r} requires circuit/track context explaining why the mechanism "
                        "matters for this event."
                    ),
                )
            )
    return tuple(issues)


def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(term.lower() in text for term in terms)
