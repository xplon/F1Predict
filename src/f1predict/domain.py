"""Core domain objects for the F1Predict MVP."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


Metric = Literal[
    "race_pace",
    "race_execution",
    "qualifying_pace",
    "tyre_deg",
    "reliability",
    "wet_skill",
    "strategy",
    "power_unit",
    "energy_recovery",
    "straight_line_speed",
    "drag_efficiency",
    "low_speed_traction",
    "launch_performance",
    "weight",
    "upgrade_effect",
]

TargetType = Literal["team", "driver", "event", "market"]


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Team:
    team_id: str
    name: str
    base_strength: float
    reliability: float
    strategy: float
    track_affinity: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Driver:
    driver_id: str
    name: str
    team_id: str
    base_skill: float
    qualifying: float
    racecraft: float
    tyre_management: float
    wet_skill: float
    reliability_modifier: float = 0.0
    current_points: float = 0.0
    external_ids: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RaceEvent:
    event_id: str
    name: str
    round_number: int
    date: str
    track_type: str
    laps: int
    completed: bool
    weather_prior: dict[str, float]
    track_map: list[tuple[float, float]]
    actual_result: list[str] = field(default_factory=list)
    feature_refs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketSnapshot:
    market_id: str
    event_id: str
    market_type: str
    captured_at: str
    prices: dict[str, float]
    liquidity: float = 0.0
    spread_estimate: float = 0.0

    def is_available(self, cutoff: datetime | None) -> bool:
        if cutoff is None:
            return True
        captured = parse_dt(self.captured_at)
        return captured is not None and captured <= cutoff


@dataclass(frozen=True)
class EvidenceClaim:
    claim_id: str
    event_id: str
    source: str
    source_url: str
    published_at: str
    observed_at: str
    target_type: TargetType
    target_id: str
    claim_type: str
    metric: Metric
    direction: Literal["positive", "negative", "neutral"]
    magnitude: float
    confidence: float
    uncertainty: float
    evidence_text: str
    reasoning: str
    review_required: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "EvidenceClaim":
        missing = [name for name in cls.__dataclass_fields__ if name not in raw]
        if missing:
            raise ValueError(f"Evidence claim missing fields: {', '.join(missing)}")
        return cls(**raw)

    def signed_impact(self) -> float:
        sign = 1.0 if self.direction == "positive" else -1.0 if self.direction == "negative" else 0.0
        return sign * self.magnitude * self.confidence * max(0.0, 1.0 - self.uncertainty)

    def is_available(self, cutoff: datetime | None) -> bool:
        if cutoff is None:
            return True
        published = parse_dt(self.published_at)
        observed = parse_dt(self.observed_at)
        if published is None or observed is None:
            return False
        return published <= cutoff and observed <= cutoff


@dataclass(frozen=True)
class FeatureAdjustment:
    feature_id: str
    event_id: str
    source: str
    target_type: TargetType
    target_id: str
    metric: Metric
    value: float
    confidence: float
    observed_at: str
    explanation: str

    def weighted_value(self) -> float:
        return self.value * self.confidence


@dataclass(frozen=True)
class SeasonState:
    season: int
    teams: dict[str, Team]
    drivers: dict[str, Driver]
    events: list[RaceEvent]
    markets: list[MarketSnapshot]


@dataclass(frozen=True)
class DriverRaceProbability:
    driver_id: str
    win: float
    podium: float
    points: float
    expected_points: float
    average_finish: float


@dataclass(frozen=True)
class MarketEdge:
    market_id: str
    market_type: str
    outcome_id: str
    model_probability: float
    market_probability: float
    edge_before_cost: float
    estimated_cost: float
    edge_after_cost: float
    recommendation: str
    conservative_model_probability: float | None = None
    conservative_edge_after_cost: float | None = None
    calibration_adjustment: float = 0.0
    risk_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceImpact:
    claim_id: str
    source: str
    target_type: TargetType
    target_id: str
    metric: Metric
    direction: str
    signed_input_impact: float
    confidence: float
    uncertainty: float
    attribution_method: str
    affected_outcomes: list[dict[str, Any]]
    max_win_probability_delta: float
    interpretation: str


@dataclass(frozen=True)
class EvidenceQuality:
    claim_id: str
    source: str
    quality_status: str
    quality_score: float
    source_reliability: float | None
    source_status: str
    triangulation_status: str
    triangulation_score: float
    conflict_status: str
    conflict_score: float
    corroborating_claim_count: int
    corroborating_source_count: int
    independent_source_count: int
    conflicting_claim_count: int
    conflicting_source_count: int
    conflicting_independent_source_count: int
    model_input_weight: float
    evidence_strength: float
    impact_level: str
    signed_input_impact: float
    max_win_probability_delta: float | None
    risk_flags: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class FactorTrace:
    claim_id: str
    target_type: TargetType
    target_id: str
    claim_type: str
    metric: Metric
    direction: str
    route: str
    model_surface: str
    route_status: str
    raw_signed_impact: float
    weighted_input_impact: float
    effective_race_input: float
    effective_qualifying_input: float | None
    signed_input_impact: float
    max_win_probability_delta: float | None
    affected_outcome_count: int
    affected_outcomes: list[dict[str, Any]]
    quality_status: str | None
    source_status: str | None
    triangulation_status: str | None
    conflict_status: str | None
    source_reliability: float | None
    model_input_weight: float | None
    context_multiplier: float | None
    context_multiplier_reason: str | None
    track_demand_component: str | None
    track_demand_value: float | None
    track_demand_profile: dict[str, Any] | None
    risk_flags: tuple[str, ...]
    route_notes: tuple[str, ...]


@dataclass(frozen=True)
class PredictionReport:
    event: RaceEvent
    generated_at: str
    knowledge_cutoff: str | None
    iterations: int
    race_probabilities: list[DriverRaceProbability]
    market_edges: list[MarketEdge]
    evidence: list[EvidenceClaim]
    evidence_quality: list[EvidenceQuality]
    evidence_impact: list[EvidenceImpact]
    feature_adjustments: list[FeatureAdjustment]
    representative_lap: list[dict[str, Any]]
    simulation_replay: list[dict[str, Any]]
    ai_judgement: dict[str, Any]
    factor_trace: list[FactorTrace] = field(default_factory=list)
    belief_state: dict[str, Any] = field(default_factory=dict)
    state_update_ledger: list[dict[str, Any]] = field(default_factory=list)
    prediction_impact_trace: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": race_event_to_dict(self.event),
            "generated_at": self.generated_at,
            "knowledge_cutoff": self.knowledge_cutoff,
            "iterations": self.iterations,
            "race_probabilities": [item.__dict__ for item in self.race_probabilities],
            "market_edges": [item.__dict__ for item in self.market_edges],
            "evidence": [item.__dict__ for item in self.evidence],
            "evidence_quality": [
                {
                    **item.__dict__,
                    "risk_flags": list(item.risk_flags),
                    "reasons": list(item.reasons),
                }
                for item in self.evidence_quality
            ],
            "evidence_impact": [item.__dict__ for item in self.evidence_impact],
            "feature_adjustments": [item.__dict__ for item in self.feature_adjustments],
            "representative_lap": self.representative_lap,
            "simulation_replay": self.simulation_replay,
            "ai_judgement": self.ai_judgement,
            "factor_trace": [
                {
                    **item.__dict__,
                    "risk_flags": list(item.risk_flags),
                    "route_notes": list(item.route_notes),
                }
                for item in self.factor_trace
            ],
            "belief_state": self.belief_state,
            "state_update_ledger": self.state_update_ledger,
            "prediction_impact_trace": self.prediction_impact_trace,
        }


def race_event_to_dict(event: RaceEvent) -> dict[str, Any]:
    payload = dict(event.__dict__)
    refs = payload.get("feature_refs")
    if not isinstance(refs, dict):
        return payload

    asset = refs.get("track_map_asset")
    provenance = refs.get("event_input_provenance")
    if asset is None and isinstance(provenance, dict):
        asset = provenance.get("track_map_asset")
    if isinstance(asset, dict):
        payload["track_map_asset"] = asset
    return payload
