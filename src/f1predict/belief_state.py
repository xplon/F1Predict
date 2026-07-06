"""Traceable belief-state updates for prediction inputs.

This module implements the first production slice of the architecture in
``docs/traceable_prediction_update_architecture_cn.md``.  It turns existing
structured features and Codex claims into a state-update ledger, then exposes a
compact BeliefState that the pace model can consume.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from f1predict.domain import EvidenceClaim, EvidenceQuality, FeatureAdjustment, RaceEvent, SeasonState, utc_now
from f1predict.models.technical_factors import technical_context_breakdown
from f1predict.storage import safe_name


CAR_FACTORS = {
    "overall_pace",
    "qualifying_pace",
    "race_pace",
    "race_execution",
    "high_speed_corner",
    "medium_speed_corner",
    "low_speed_corner",
    "traction",
    "mechanical_grip",
    "aero_efficiency",
    "drag",
    "straight_line_speed",
    "power_unit_peak",
    "ers_deployment",
    "ers_recovery",
    "clipping_risk",
    "cooling_margin",
    "tyre_deg",
    "tyre_warmup",
    "dirty_air_sensitivity",
    "setup_window_width",
    "reliability",
    "upgrade_delta",
}

DRIVER_FACTORS = {
    "qualifying_ceiling",
    "qualifying_consistency",
    "race_pace",
    "race_execution",
    "long_run_consistency",
    "tyre_management",
    "tyre_warmup",
    "wet_skill",
    "attack_racecraft",
    "defense_racecraft",
    "first_lap_gain",
    "incident_risk",
    "penalty_risk",
    "setup_feedback",
    "car_fit_understeer",
    "car_fit_oversteer",
    "team_priority",
    "reliability",
}

TEAM_OPS_FACTORS = {
    "strategy_quality",
    "pit_stop_mean",
    "pit_stop_variance",
    "pit_wall_risk",
    "development_rate",
    "upgrade_correlation",
    "setup_quality",
    "internal_conflict_risk",
}

EVENT_FACTORS = {
    "wet_probability",
    "safety_car_probability",
    "red_flag_probability",
    "tyre_degradation_index",
}

METRIC_FACTOR_MAP = {
    "race_pace": ("car", "race_pace"),
    "race_execution": ("driver", "race_execution"),
    "qualifying_pace": ("car", "qualifying_pace"),
    "tyre_deg": ("car", "tyre_deg"),
    "reliability": ("car", "reliability"),
    "wet_skill": ("driver", "wet_skill"),
    "strategy": ("team_ops", "strategy_quality"),
    "power_unit": ("car", "power_unit_peak"),
    "energy_recovery": ("car", "ers_deployment"),
    "straight_line_speed": ("car", "straight_line_speed"),
    "drag_efficiency": ("car", "aero_efficiency"),
    "low_speed_traction": ("car", "traction"),
    "launch_performance": ("driver", "first_lap_gain"),
    "weight": ("car", "overall_pace"),
    "upgrade_effect": ("car", "upgrade_delta"),
}

FACTOR_CAPS = {
    "overall_pace": 0.18,
    "race_pace": 0.20,
    "qualifying_pace": 0.20,
    "race_execution": 0.12,
    "reliability": 0.045,
    "tyre_deg": 0.075,
    "strategy_quality": 0.08,
    "ers_deployment": 0.11,
    "straight_line_speed": 0.11,
    "aero_efficiency": 0.10,
    "traction": 0.10,
    "upgrade_delta": 0.09,
    "first_lap_gain": 0.07,
    "wet_skill": 0.06,
}


@dataclass
class StateFactor:
    value: float = 0.0
    uncertainty: float = 0.65
    provenance: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": round(self.value, 6),
            "uncertainty": round(self.uncertainty, 6),
            "provenance": list(self.provenance),
            "bucket": bucket_value(self.value),
        }


@dataclass
class EntityState:
    entity_id: str
    factors: dict[str, StateFactor] = field(default_factory=dict)

    def value(self, factor: str, default: float = 0.0) -> float:
        row = self.factors.get(factor)
        return row.value if row is not None else default

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "factors": {key: value.to_dict() for key, value in sorted(self.factors.items())},
        }


@dataclass(frozen=True)
class StateUpdateLedgerRow:
    update_id: str
    claim_id: str
    source_id: str
    state_id_before: str
    state_id_after: str
    target_type: str
    target_id: str
    factor: str
    old_value_bucket: str
    new_value_bucket: str
    direction: str
    magnitude_bucket: str
    update_strength_bucket: str
    update_permission: str
    quality_reasons: tuple[str, ...]
    mechanism: str
    applicable_context: tuple[str, ...]
    affected_model_surfaces: tuple[str, ...]
    old_value: float
    new_value: float
    delta: float
    raw_delta: float

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.__dict__)
        payload["quality_reasons"] = list(self.quality_reasons)
        payload["applicable_context"] = list(self.applicable_context)
        payload["affected_model_surfaces"] = list(self.affected_model_surfaces)
        payload["old_value"] = round(self.old_value, 6)
        payload["new_value"] = round(self.new_value, 6)
        payload["delta"] = round(self.delta, 6)
        payload["raw_delta"] = round(self.raw_delta, 6)
        return payload


@dataclass
class BeliefState:
    state_id: str
    event_id: str
    knowledge_cutoff: str | None
    generated_at: str
    track_state: EntityState
    car_states: dict[str, EntityState]
    driver_states: dict[str, EntityState]
    team_ops_states: dict[str, EntityState]
    event_risk_state: EntityState
    raw_sources: list[dict[str, Any]]
    extracted_units: list[dict[str, Any]]
    normalized_claims: list[dict[str, Any]]
    quality_profiles: list[dict[str, Any]]
    update_ledger: list[StateUpdateLedgerRow]
    unsupported_static_priors: list[dict[str, Any]]
    source_fingerprint: str
    update_fingerprint: str

    def car_value(self, team_id: str, factor: str, default: float = 0.0) -> float:
        state = self.car_states.get(team_id)
        return state.value(factor, default) if state is not None else default

    def driver_value(self, driver_id: str, factor: str, default: float = 0.0) -> float:
        state = self.driver_states.get(driver_id)
        return state.value(factor, default) if state is not None else default

    def team_ops_value(self, team_id: str, factor: str, default: float = 0.0) -> float:
        state = self.team_ops_states.get(team_id)
        return state.value(factor, default) if state is not None else default

    def event_value(self, factor: str, default: float = 0.0) -> float:
        return self.event_risk_state.value(factor, default)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state_id": self.state_id,
            "event_id": self.event_id,
            "knowledge_cutoff": self.knowledge_cutoff,
            "generated_at": self.generated_at,
            "track_state": self.track_state.to_dict(),
            "car_states": {key: value.to_dict() for key, value in sorted(self.car_states.items())},
            "driver_states": {key: value.to_dict() for key, value in sorted(self.driver_states.items())},
            "team_ops_states": {key: value.to_dict() for key, value in sorted(self.team_ops_states.items())},
            "event_risk_state": self.event_risk_state.to_dict(),
            "raw_sources": self.raw_sources,
            "extracted_units": self.extracted_units,
            "normalized_claims": self.normalized_claims,
            "quality_profiles": self.quality_profiles,
            "update_ledger": [row.to_dict() for row in self.update_ledger],
            "unsupported_static_priors": self.unsupported_static_priors,
            "source_fingerprint": self.source_fingerprint,
            "update_fingerprint": self.update_fingerprint,
        }


class BeliefStateBuilder:
    """Build a traceable model state from seed priors, features, and claims."""

    def build(
        self,
        season: SeasonState,
        event: RaceEvent,
        evidence: list[EvidenceClaim],
        feature_adjustments: list[FeatureAdjustment],
        evidence_quality: list[EvidenceQuality] | None = None,
        knowledge_cutoff: str | None = None,
        include_claim_ids: set[str] | None = None,
        include_feature_ids: set[str] | None = None,
    ) -> BeliefState:
        quality_by_claim = {row.claim_id: row for row in evidence_quality or []}
        evidence = [
            row for row in evidence
            if include_claim_ids is None or row.claim_id in include_claim_ids
        ]
        feature_adjustments = [
            row for row in feature_adjustments
            if include_feature_ids is None or row.feature_id in include_feature_ids
        ]
        raw_sources: list[dict[str, Any]] = []
        extracted_units: list[dict[str, Any]] = []
        normalized_claims: list[dict[str, Any]] = []
        quality_profiles: list[dict[str, Any]] = []
        unsupported_static_priors: list[dict[str, Any]] = []
        track_state, car_states, driver_states, team_ops_states, event_risk_state = self._seed_state(
            season,
            event,
            unsupported_static_priors,
        )
        state_before = self._fingerprint_states(car_states, driver_states, team_ops_states, event_risk_state)
        ledger: list[StateUpdateLedgerRow] = []

        for feature in feature_adjustments:
            source_id = self._source_id("feature", feature.source, feature.feature_id)
            raw_sources.append(self._feature_source(source_id, feature))
            unit_id = f"unit-{source_id}"
            extracted_units.append(self._feature_unit(unit_id, source_id, feature))
            normalized_claims.append(self._feature_claim(unit_id, feature))
            quality_profile = self._feature_quality(feature)
            quality_profiles.append(quality_profile)
            self._apply_feature_update(
                feature,
                source_id,
                quality_profile,
                car_states,
                driver_states,
                team_ops_states,
                event_risk_state,
                ledger,
                event,
                state_before,
            )

        for claim in evidence:
            source_id = self._source_id("claim", claim.source_url or claim.source, claim.claim_id)
            raw_sources.append(self._claim_source(source_id, claim))
            unit_id = f"unit-{source_id}"
            extracted_units.append(self._claim_unit(unit_id, source_id, claim))
            normalized_claims.append(self._claim_normalized(unit_id, claim))
            quality = quality_by_claim.get(claim.claim_id)
            profile = self._claim_quality(claim, quality)
            quality_profiles.append(profile)
            self._apply_claim_update(
                claim,
                source_id,
                profile,
                car_states,
                driver_states,
                team_ops_states,
                event_risk_state,
                ledger,
                event,
                state_before,
            )

        state_after = self._fingerprint_states(car_states, driver_states, team_ops_states, event_risk_state)
        source_fingerprint = canonical_hash(raw_sources)
        update_fingerprint = canonical_hash([row.to_dict() for row in ledger])
        state_id = safe_name(f"{event.event_id}_{source_fingerprint[:10]}_{update_fingerprint[:10]}")
        return BeliefState(
            state_id=state_id,
            event_id=event.event_id,
            knowledge_cutoff=knowledge_cutoff,
            generated_at=utc_now().replace(microsecond=0).isoformat(),
            track_state=track_state,
            car_states=car_states,
            driver_states=driver_states,
            team_ops_states=team_ops_states,
            event_risk_state=event_risk_state,
            raw_sources=dedupe_dicts(raw_sources, "source_id"),
            extracted_units=dedupe_dicts(extracted_units, "unit_id"),
            normalized_claims=dedupe_dicts(normalized_claims, "claim_id"),
            quality_profiles=dedupe_dicts(quality_profiles, "claim_id"),
            update_ledger=self._bind_state_after(ledger, state_after),
            unsupported_static_priors=unsupported_static_priors,
            source_fingerprint=source_fingerprint,
            update_fingerprint=update_fingerprint,
        )

    def _seed_state(
        self,
        season: SeasonState,
        event: RaceEvent,
        unsupported_static_priors: list[dict[str, Any]],
    ) -> tuple[EntityState, dict[str, EntityState], dict[str, EntityState], dict[str, EntityState], EntityState]:
        team_base_mean = mean(team.base_strength for team in season.teams.values())
        team_strategy_mean = mean(team.strategy for team in season.teams.values())
        reliability_mean = mean(team.reliability for team in season.teams.values())
        driver_base_mean = mean(driver.base_skill for driver in season.drivers.values())
        driver_qualifying_mean = mean(driver.qualifying for driver in season.drivers.values())
        driver_racecraft_mean = mean(driver.racecraft for driver in season.drivers.values())
        driver_tyre_mean = mean(driver.tyre_management for driver in season.drivers.values())
        driver_wet_mean = mean(driver.wet_skill for driver in season.drivers.values())

        track_vector = technical_context_breakdown("straight_line_speed", event.track_type, feature_refs=event.feature_refs)
        track_profile = track_vector.get("track_demand_profile") if isinstance(track_vector, dict) else None
        track_state = EntityState(
            event.event_id,
            {
                "track_type": StateFactor(0.0, 0.35, ["event.track_type"]),
                "power_demand": StateFactor(_profile_value(track_profile, "power_demand"), 0.45, ["track_feature_vector"]),
                "ers_demand": StateFactor(_profile_value(track_profile, "ers_demand"), 0.45, ["track_feature_vector"]),
                "traction_demand": StateFactor(_profile_value(track_profile, "traction_demand"), 0.45, ["track_feature_vector"]),
                "track_position_value": StateFactor(_profile_value(track_profile, "track_position_value"), 0.45, ["track_feature_vector"]),
            },
        )
        event_risk_state = EntityState(
            event.event_id,
            {
                "wet_probability": StateFactor(event.weather_prior.get("wet_probability", 0.0), 0.38, ["event.weather_prior"]),
                "safety_car_probability": StateFactor(
                    event.weather_prior.get("safety_car_probability", 0.0),
                    0.38,
                    ["event.weather_prior"],
                ),
                "red_flag_probability": StateFactor(0.04, 0.78, ["weak_static_prior"]),
                "tyre_degradation_index": StateFactor(_profile_value(track_profile, "tyre_degradation_index"), 0.55, ["track_feature_vector"]),
            },
        )

        car_states: dict[str, EntityState] = {}
        team_ops_states: dict[str, EntityState] = {}
        for team_id, team in season.teams.items():
            team_seed = team.base_strength - team_base_mean
            strategy_seed = team.strategy - team_strategy_mean
            reliability_seed = team.reliability - reliability_mean
            car_states[team_id] = EntityState(
                team_id,
                {
                    "overall_pace": StateFactor(team_seed * 0.32, 0.72, ["weak_seed_team_base_strength"]),
                    "race_pace": StateFactor(team_seed * 0.26, 0.72, ["weak_seed_team_base_strength"]),
                    "qualifying_pace": StateFactor(team_seed * 0.20, 0.72, ["weak_seed_team_base_strength"]),
                    "high_speed_corner": StateFactor(team.track_affinity.get("high_speed", 0.0) * 0.35, 0.74, ["weak_seed_track_affinity"]),
                    "low_speed_corner": StateFactor(team.track_affinity.get("street", 0.0) * 0.25, 0.78, ["weak_seed_track_affinity"]),
                    "straight_line_speed": StateFactor(team.track_affinity.get("power", 0.0) * 0.28, 0.78, ["weak_seed_track_affinity"]),
                    "reliability": StateFactor(reliability_seed * 0.60, 0.58, ["weak_seed_team_reliability"]),
                    "tyre_deg": StateFactor(0.0, 0.82, ["unobserved_initial_state"]),
                    "ers_deployment": StateFactor(0.0, 0.82, ["unobserved_initial_state"]),
                    "aero_efficiency": StateFactor(0.0, 0.82, ["unobserved_initial_state"]),
                    "traction": StateFactor(0.0, 0.82, ["unobserved_initial_state"]),
                    "upgrade_delta": StateFactor(0.0, 0.85, ["unobserved_initial_state"]),
                },
            )
            team_ops_states[team_id] = EntityState(
                team_id,
                {
                    "strategy_quality": StateFactor(strategy_seed * 0.18, 0.70, ["weak_seed_team_strategy"]),
                    "pit_wall_risk": StateFactor(-strategy_seed * 0.10, 0.78, ["weak_seed_team_strategy"]),
                    "setup_quality": StateFactor(strategy_seed * 0.10, 0.78, ["weak_seed_team_strategy"]),
                    "development_rate": StateFactor(0.0, 0.85, ["unobserved_initial_state"]),
                },
            )
            unsupported_static_priors.append(
                {
                    "target_type": "team",
                    "target_id": team_id,
                    "fields": ["base_strength", "reliability", "strategy", "track_affinity"],
                    "status": "weak_seed_prior_only",
                    "note": "Seed priors initialize belief state with high uncertainty and reduced scale.",
                }
            )

        driver_states: dict[str, EntityState] = {}
        for driver_id, driver in season.drivers.items():
            driver_states[driver_id] = EntityState(
                driver_id,
                {
                    "race_pace": StateFactor((driver.base_skill - driver_base_mean) * 0.18, 0.76, ["weak_seed_driver_base_skill"]),
                    "qualifying_ceiling": StateFactor(
                        (driver.qualifying - driver_qualifying_mean) * 0.18,
                        0.76,
                        ["weak_seed_driver_qualifying"],
                    ),
                    "race_execution": StateFactor(
                        (driver.racecraft - driver_racecraft_mean) * 0.13,
                        0.78,
                        ["weak_seed_driver_racecraft"],
                    ),
                    "tyre_management": StateFactor(
                        (driver.tyre_management - driver_tyre_mean) * 0.10,
                        0.80,
                        ["weak_seed_driver_tyre_management"],
                    ),
                    "wet_skill": StateFactor((driver.wet_skill - driver_wet_mean) * 0.09, 0.80, ["weak_seed_driver_wet_skill"]),
                    "reliability": StateFactor(driver.reliability_modifier * 0.65, 0.72, ["weak_seed_driver_reliability"]),
                    "first_lap_gain": StateFactor(0.0, 0.84, ["unobserved_initial_state"]),
                    "incident_risk": StateFactor(0.0, 0.86, ["unobserved_initial_state"]),
                },
            )
            unsupported_static_priors.append(
                {
                    "target_type": "driver",
                    "target_id": driver_id,
                    "fields": ["base_skill", "qualifying", "racecraft", "tyre_management", "wet_skill"],
                    "status": "weak_seed_prior_only",
                    "note": "Driver seed priors are weak initialization, not explanation evidence.",
                }
            )
        return track_state, car_states, driver_states, team_ops_states, event_risk_state

    def _apply_feature_update(
        self,
        feature: FeatureAdjustment,
        source_id: str,
        quality_profile: dict[str, Any],
        car_states: dict[str, EntityState],
        driver_states: dict[str, EntityState],
        team_ops_states: dict[str, EntityState],
        event_risk_state: EntityState,
        ledger: list[StateUpdateLedgerRow],
        event: RaceEvent,
        state_before: str,
    ) -> None:
        state_scope, factor = self._feature_target(feature)
        target_id = self._state_target_id(feature, state_scope)
        if not target_id:
            return
        raw_delta = feature.weighted_value() * self._feature_update_multiplier(feature)
        update_strength = float(quality_profile.get("update_strength") or 0.0)
        permission = str(quality_profile.get("model_update_permission") or "weak_update")
        self._apply_update(
            row_id=feature.feature_id,
            source_id=source_id,
            claim_id=feature.feature_id,
            state_scope=state_scope,
            target_type=feature.target_type,
            target_id=target_id,
            factor=factor,
            raw_delta=raw_delta,
            update_strength=update_strength,
            update_permission=permission,
            quality_reasons=tuple(quality_profile.get("reasons") or ()),
            mechanism=feature.explanation,
            applicable_context=self._context_tags(event, feature.metric),
            car_states=car_states,
            driver_states=driver_states,
            team_ops_states=team_ops_states,
            event_risk_state=event_risk_state,
            ledger=ledger,
            state_before=state_before,
        )

    def _apply_claim_update(
        self,
        claim: EvidenceClaim,
        source_id: str,
        quality_profile: dict[str, Any],
        car_states: dict[str, EntityState],
        driver_states: dict[str, EntityState],
        team_ops_states: dict[str, EntityState],
        event_risk_state: EntityState,
        ledger: list[StateUpdateLedgerRow],
        event: RaceEvent,
        state_before: str,
    ) -> None:
        if quality_profile.get("model_update_permission") == "blocked":
            return
        state_scope, factor = self._claim_target(claim)
        target_id = self._state_target_id(claim, state_scope)
        if not target_id:
            return
        raw_delta = claim.signed_impact()
        update_strength = float(quality_profile.get("update_strength") or 0.0)
        self._apply_update(
            row_id=claim.claim_id,
            source_id=source_id,
            claim_id=claim.claim_id,
            state_scope=state_scope,
            target_type=claim.target_type,
            target_id=target_id,
            factor=factor,
            raw_delta=raw_delta,
            update_strength=update_strength,
            update_permission=str(quality_profile.get("model_update_permission") or "weak_update"),
            quality_reasons=tuple(quality_profile.get("reasons") or ()),
            mechanism=claim.reasoning or claim.evidence_text,
            applicable_context=self._context_tags(event, claim.metric),
            car_states=car_states,
            driver_states=driver_states,
            team_ops_states=team_ops_states,
            event_risk_state=event_risk_state,
            ledger=ledger,
            state_before=state_before,
        )

    def _apply_update(
        self,
        row_id: str,
        source_id: str,
        claim_id: str,
        state_scope: str,
        target_type: str,
        target_id: str,
        factor: str,
        raw_delta: float,
        update_strength: float,
        update_permission: str,
        quality_reasons: tuple[str, ...],
        mechanism: str,
        applicable_context: tuple[str, ...],
        car_states: dict[str, EntityState],
        driver_states: dict[str, EntityState],
        team_ops_states: dict[str, EntityState],
        event_risk_state: EntityState,
        ledger: list[StateUpdateLedgerRow],
        state_before: str,
    ) -> None:
        state = self._state_for_scope(state_scope, target_id, car_states, driver_states, team_ops_states, event_risk_state)
        if state is None:
            return
        factor_row = state.factors.setdefault(factor, StateFactor())
        old_value = factor_row.value
        cap = FACTOR_CAPS.get(factor, 0.07)
        if update_permission == "strong_update":
            permission_scale = 1.0
        elif update_permission == "normal_update":
            permission_scale = 0.72
        elif update_permission == "weak_update":
            permission_scale = 0.42
        else:
            permission_scale = 0.0
        bounded_delta = clamp(raw_delta * permission_scale, -cap, cap)
        if abs(bounded_delta) < 0.000001:
            return
        factor_row.value = clamp(old_value + bounded_delta, -0.75, 0.75)
        factor_row.uncertainty = clamp(
            factor_row.uncertainty * (1.0 - min(0.55, update_strength * permission_scale * 0.42)),
            0.12,
            0.95,
        )
        factor_row.provenance.append(claim_id)
        ledger.append(
            StateUpdateLedgerRow(
                update_id=safe_name(f"update_{claim_id}_{factor}_{len(ledger) + 1}"),
                claim_id=claim_id,
                source_id=source_id,
                state_id_before=state_before,
                state_id_after="pending",
                target_type=target_type,
                target_id=target_id,
                factor=factor,
                old_value_bucket=bucket_value(old_value),
                new_value_bucket=bucket_value(factor_row.value),
                direction="positive" if bounded_delta > 0 else "negative",
                magnitude_bucket=bucket_delta(bounded_delta),
                update_strength_bucket=bucket_strength(update_strength),
                update_permission=update_permission,
                quality_reasons=quality_reasons,
                mechanism=mechanism,
                applicable_context=applicable_context,
                affected_model_surfaces=self._affected_surfaces(factor),
                old_value=old_value,
                new_value=factor_row.value,
                delta=bounded_delta,
                raw_delta=raw_delta,
            )
        )

    @staticmethod
    def _state_for_scope(
        state_scope: str,
        target_id: str,
        car_states: dict[str, EntityState],
        driver_states: dict[str, EntityState],
        team_ops_states: dict[str, EntityState],
        event_risk_state: EntityState,
    ) -> EntityState | None:
        if state_scope == "car":
            return car_states.get(target_id)
        if state_scope == "driver":
            return driver_states.get(target_id)
        if state_scope == "team_ops":
            return team_ops_states.get(target_id)
        if state_scope == "event":
            return event_risk_state
        return None

    @staticmethod
    def _feature_target(feature: FeatureAdjustment) -> tuple[str, str]:
        state_scope, factor = METRIC_FACTOR_MAP.get(feature.metric, ("car", str(feature.metric)))
        if feature.target_type == "driver" and feature.metric in {"qualifying_pace", "race_pace", "race_execution", "wet_skill", "reliability", "launch_performance", "tyre_deg"}:
            if feature.metric == "qualifying_pace":
                return "driver", "qualifying_ceiling"
            if feature.metric == "race_pace":
                return "driver", "race_pace"
            if feature.metric == "tyre_deg":
                return "driver", "tyre_management"
            if feature.metric == "launch_performance":
                return "driver", "first_lap_gain"
            return state_scope, factor
        if feature.target_type == "event":
            if feature.metric == "wet_skill":
                return "event", "wet_probability"
            return "event", str(feature.metric)
        return state_scope, factor

    @staticmethod
    def _claim_target(claim: EvidenceClaim) -> tuple[str, str]:
        state_scope, factor = METRIC_FACTOR_MAP.get(claim.metric, ("car", str(claim.metric)))
        if claim.target_type == "driver" and claim.metric in {"qualifying_pace", "race_pace", "race_execution", "wet_skill", "reliability", "launch_performance", "tyre_deg"}:
            if claim.metric == "qualifying_pace":
                return "driver", "qualifying_ceiling"
            if claim.metric == "race_pace":
                return "driver", "race_pace"
            if claim.metric == "tyre_deg":
                return "driver", "tyre_management"
            if claim.metric == "launch_performance":
                return "driver", "first_lap_gain"
            return state_scope, factor
        if claim.target_type == "event":
            if claim.metric == "wet_skill":
                return "event", "wet_probability"
            return "event", str(claim.metric)
        return state_scope, factor

    @staticmethod
    def _state_target_id(row: Any, state_scope: str) -> str | None:
        if state_scope == "event":
            return row.event_id
        return str(row.target_id or "") or None

    @staticmethod
    def _feature_update_multiplier(feature: FeatureAdjustment) -> float:
        source = f"{feature.feature_id} {feature.source}".lower()
        if "fastf1-qualifying-result" in source:
            return 2.45
        if "team-strength-reestimate" in source:
            return 3.20
        if "official-standings" in source:
            return 2.15
        if "fastf1-session-laps" in source:
            return 1.90
        if "fastf1-form" in source:
            return 1.75
        if "fastf1-season-form" in source:
            return 1.55
        if "fastf1-momentum" in source:
            return 1.70
        return 1.10

    @staticmethod
    def _feature_quality(feature: FeatureAdjustment) -> dict[str, Any]:
        source = f"{feature.feature_id} {feature.source}".lower()
        if "fastf1-qualifying-result" in source or "fastf1-session-laps" in source:
            permission = "strong_update"
            update_strength = min(0.95, max(0.35, feature.confidence))
            reasons = ("source_backed_timing_data", "specific_event_observation")
        elif "team-strength-reestimate" in source or "official-standings" in source:
            permission = "strong_update"
            update_strength = min(0.88, max(0.34, feature.confidence))
            reasons = ("structured_recent_results", "source_backed_points_or_classification")
        elif "fastf1-form" in source or "season-form" in source or "momentum" in source:
            permission = "normal_update"
            update_strength = min(0.78, max(0.25, feature.confidence))
            reasons = ("recent_window_structured_feature",)
        else:
            permission = "weak_update"
            update_strength = min(0.55, max(0.18, feature.confidence))
            reasons = ("low_confidence_context_feature",)
        return {
            "claim_id": feature.feature_id,
            "source_reliability": round(update_strength, 4),
            "source_proximity": "structured_data",
            "timestamp_validity": "within_cutoff",
            "specificity_score": 0.85,
            "mechanism_score": 0.65,
            "triangulation_score": 0.5,
            "conflict_score": 0.0,
            "data_support_score": round(update_strength, 4),
            "recency_weight": 0.85,
            "review_required": False,
            "model_update_permission": permission,
            "update_strength": round(update_strength, 4),
            "reasons": reasons,
        }

    @staticmethod
    def _claim_quality(claim: EvidenceClaim, quality: EvidenceQuality | None) -> dict[str, Any]:
        if quality is None:
            update_strength = min(0.35, max(0.05, claim.confidence * (1.0 - claim.uncertainty)))
            return {
                "claim_id": claim.claim_id,
                "source_reliability": None,
                "source_proximity": "unknown",
                "timestamp_validity": "unscored",
                "specificity_score": 0.35,
                "mechanism_score": 0.35 if claim.reasoning else 0.15,
                "triangulation_score": 0.0,
                "conflict_score": 0.0,
                "data_support_score": 0.0,
                "recency_weight": 0.5,
                "review_required": True,
                "model_update_permission": "weak_update",
                "update_strength": round(update_strength, 4),
                "reasons": ("unscored_codex_claim",),
            }
        permission = "blocked"
        if quality.quality_status == "strong":
            permission = "strong_update"
        elif quality.quality_status in {"usable_diagnostic", "medium"}:
            permission = "normal_update"
        elif quality.quality_status in {"weak_diagnostic", "review_required"}:
            permission = "weak_update"
        if "seed_scenario_source" in quality.risk_flags:
            permission = "blocked"
        elif "source_log_missing" in quality.risk_flags:
            permission = "weak_update"
        if claim.review_required:
            permission = "weak_update" if permission != "blocked" else permission
        update_strength = clamp(
            quality.model_input_weight
            * max(0.15, quality.evidence_strength)
            * max(0.15, 1.0 - claim.uncertainty),
            0.0,
            0.92,
        )
        return {
            "claim_id": claim.claim_id,
            "source_reliability": quality.source_reliability,
            "source_proximity": "source_registry",
            "timestamp_validity": quality.source_status,
            "specificity_score": quality.quality_score,
            "mechanism_score": 0.65 if claim.reasoning else 0.25,
            "triangulation_score": quality.triangulation_score,
            "conflict_score": quality.conflict_score,
            "data_support_score": quality.evidence_strength,
            "recency_weight": 0.75,
            "review_required": claim.review_required,
            "model_update_permission": permission,
            "update_strength": round(update_strength, 4),
            "reasons": quality.reasons,
        }

    @staticmethod
    def _context_tags(event: RaceEvent, metric: str) -> tuple[str, ...]:
        tags = [f"track_type:{event.track_type}"]
        breakdown = technical_context_breakdown(metric, event.track_type, feature_refs=event.feature_refs)
        if isinstance(breakdown, dict):
            component = breakdown.get("demand_component")
            if component:
                tags.append(f"demand_component:{component}")
        return tuple(tags)

    @staticmethod
    def _affected_surfaces(factor: str) -> tuple[str, ...]:
        if factor in {"qualifying_pace", "qualifying_ceiling"}:
            return ("qualifying_grid_sampler",)
        if factor in {"race_pace", "overall_pace", "straight_line_speed", "ers_deployment", "aero_efficiency", "traction", "upgrade_delta"}:
            return ("race_pace_score", "qualifying_grid_sampler")
        if factor in {"tyre_deg", "tyre_management"}:
            return ("stint_degradation", "strategy_plan")
        if factor == "strategy_quality":
            return ("pit_strategy", "safety_car_window")
        if factor == "reliability":
            return ("dnf_sampler",)
        if factor == "wet_skill":
            return ("wet_race_branch",)
        return ("race_pace_score",)

    @staticmethod
    def _feature_source(source_id: str, feature: FeatureAdjustment) -> dict[str, Any]:
        return {
            "source_id": source_id,
            "source_type": "structured_feature",
            "url": None,
            "title": feature.feature_id,
            "publisher": source_publisher(feature.source),
            "author": None,
            "published_at": feature.observed_at,
            "captured_at": feature.observed_at,
            "knowledge_cutoff": None,
            "raw_text_path": None,
            "raw_html_path": None,
            "screenshot_path": None,
            "archive_url": None,
            "content_hash": canonical_hash({"source": feature.source, "feature_id": feature.feature_id}),
            "license_or_terms_note": "derived local structured feature",
        }

    @staticmethod
    def _claim_source(source_id: str, claim: EvidenceClaim) -> dict[str, Any]:
        return {
            "source_id": source_id,
            "source_type": "codex_evidence_claim",
            "url": claim.source_url,
            "title": claim.source,
            "publisher": claim.source,
            "author": None,
            "published_at": claim.published_at,
            "captured_at": claim.observed_at,
            "knowledge_cutoff": None,
            "raw_text_path": None,
            "raw_html_path": None,
            "screenshot_path": None,
            "archive_url": None,
            "content_hash": canonical_hash({"claim_id": claim.claim_id, "text": claim.evidence_text}),
            "license_or_terms_note": "existing normalized evidence claim; source archive may be required",
        }

    @staticmethod
    def _feature_unit(unit_id: str, source_id: str, feature: FeatureAdjustment) -> dict[str, Any]:
        return {
            "unit_id": unit_id,
            "source_id": source_id,
            "extracted_at": utc_now().replace(microsecond=0).isoformat(),
            "original_snippet": feature.explanation,
            "paraphrase_zh": feature.explanation,
            "information_type": "timing_observation",
            "target_text": feature.target_id,
            "time_scope": "event_or_recent_window",
            "certainty_language": "observed",
            "llm_extraction_confidence": None,
        }

    @staticmethod
    def _claim_unit(unit_id: str, source_id: str, claim: EvidenceClaim) -> dict[str, Any]:
        return {
            "unit_id": unit_id,
            "source_id": source_id,
            "extracted_at": claim.observed_at,
            "original_snippet": claim.evidence_text,
            "paraphrase_zh": claim.reasoning,
            "information_type": claim.claim_type,
            "target_text": claim.target_id,
            "time_scope": claim.event_id,
            "certainty_language": "review_required" if claim.review_required else "claimed",
            "llm_extraction_confidence": claim.confidence,
        }

    @staticmethod
    def _feature_claim(unit_id: str, feature: FeatureAdjustment) -> dict[str, Any]:
        return {
            "claim_id": feature.feature_id,
            "unit_id": unit_id,
            "event_id": feature.event_id,
            "target_type": feature.target_type,
            "target_id": feature.target_id,
            "factor": feature.metric,
            "direction": "positive" if feature.weighted_value() > 0 else "negative" if feature.weighted_value() < 0 else "neutral",
            "magnitude_observation": bucket_delta(feature.weighted_value()),
            "mechanism": feature.explanation,
            "applicable_context": (),
            "valid_from": feature.observed_at,
            "valid_until": None,
            "decay_policy": "source_specific",
            "extraction_status": "accepted",
        }

    @staticmethod
    def _claim_normalized(unit_id: str, claim: EvidenceClaim) -> dict[str, Any]:
        return {
            "claim_id": claim.claim_id,
            "unit_id": unit_id,
            "event_id": claim.event_id,
            "target_type": claim.target_type,
            "target_id": claim.target_id,
            "factor": claim.metric,
            "direction": claim.direction,
            "magnitude_observation": bucket_delta(claim.signed_impact()),
            "mechanism": claim.reasoning,
            "applicable_context": (),
            "valid_from": claim.published_at,
            "valid_until": None,
            "decay_policy": "claim_cutoff_valid",
            "extraction_status": "needs_review" if claim.review_required else "accepted",
        }

    @staticmethod
    def _source_id(kind: str, source: str, row_id: str) -> str:
        digest = hashlib.sha256(f"{kind}:{source}:{row_id}".encode("utf-8")).hexdigest()[:12]
        return safe_name(f"{kind}_{digest}")

    @staticmethod
    def _fingerprint_states(
        car_states: dict[str, EntityState],
        driver_states: dict[str, EntityState],
        team_ops_states: dict[str, EntityState],
        event_risk_state: EntityState,
    ) -> str:
        return canonical_hash(
            {
                "car": {key: value.to_dict() for key, value in car_states.items()},
                "driver": {key: value.to_dict() for key, value in driver_states.items()},
                "team_ops": {key: value.to_dict() for key, value in team_ops_states.items()},
                "event": event_risk_state.to_dict(),
            }
        )

    @staticmethod
    def _bind_state_after(ledger: list[StateUpdateLedgerRow], state_after: str) -> list[StateUpdateLedgerRow]:
        return [
            StateUpdateLedgerRow(
                **{
                    **row.__dict__,
                    "state_id_after": state_after,
                }
            )
            for row in ledger
        ]


class PredictionImpactTraceBuilder:
    """Build same-seed prediction deltas for traceable state updates."""

    def build(
        self,
        base_probabilities: list[Any],
        candidate_probabilities: list[Any],
        belief_state: BeliefState,
        isolated_rows: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        base_by_driver = {row.driver_id: row for row in base_probabilities}
        candidate_by_driver = {row.driver_id: row for row in candidate_probabilities}
        rows = [
            self._overall_row(base_by_driver, candidate_by_driver, belief_state),
        ]
        rows.extend(isolated_rows or [])
        for update in sorted(belief_state.update_ledger, key=lambda row: abs(row.delta), reverse=True)[:10]:
            rows.append(
                {
                    "impact_trace_id": safe_name(f"trace_{update.update_id}"),
                    "update_id_or_group_id": update.update_id,
                    "claim_id": update.claim_id,
                    "source_id": update.source_id,
                    "trace_type": "state_update_route",
                    "changed_factors": [
                        {
                            "target_type": update.target_type,
                            "target_id": update.target_id,
                            "factor": update.factor,
                            "direction": update.direction,
                            "magnitude_bucket": update.magnitude_bucket,
                            "old_value_bucket": update.old_value_bucket,
                            "new_value_bucket": update.new_value_bucket,
                        }
                    ],
                    "affected_drivers": self._affected_driver_hint(update),
                    "finish_distribution_delta": [],
                    "expected_points_delta": [],
                    "rank_delta": [],
                    "probability_delta_bucket": "not_isolated_yet",
                    "interpretation_zh": (
                        "这条记录证明信息已经进入状态向量并路由到模拟表面；"
                        "单条信息的同种子 isolated run 会在后续 P2 扩展中生成。"
                    ),
                }
            )
        return rows

    @staticmethod
    def _overall_row(base_by_driver: dict[str, Any], candidate_by_driver: dict[str, Any], belief_state: BeliefState) -> dict[str, Any]:
        driver_ids = sorted(set(base_by_driver) | set(candidate_by_driver))
        base_rank = rank_by_average_finish(base_by_driver)
        candidate_rank = rank_by_average_finish(candidate_by_driver)
        deltas = []
        for driver_id in driver_ids:
            base = base_by_driver.get(driver_id)
            candidate = candidate_by_driver.get(driver_id)
            if base is None or candidate is None:
                continue
            deltas.append(
                {
                    "driver_id": driver_id,
                    "win_delta": round(candidate.win - base.win, 6),
                    "podium_delta": round(candidate.podium - base.podium, 6),
                    "expected_points_delta": round(candidate.expected_points - base.expected_points, 4),
                    "average_finish_delta": round(candidate.average_finish - base.average_finish, 4),
                    "expected_rank_delta": candidate_rank.get(driver_id, 0) - base_rank.get(driver_id, 0),
                }
            )
        material = [
            row for row in deltas
            if abs(row["expected_points_delta"]) >= 0.1
            or abs(row["podium_delta"]) >= 0.01
            or abs(row["expected_rank_delta"]) >= 1
        ]
        return {
            "impact_trace_id": safe_name(f"trace_{belief_state.state_id}_all_updates"),
            "update_id_or_group_id": "all_state_updates_vs_weak_seed_prior",
            "trace_type": "same_seed_before_after",
            "base_run_id": "weak_seed_prior_state",
            "candidate_run_id": belief_state.state_id,
            "changed_factors": self_changed_factors(belief_state.update_ledger),
            "affected_drivers": sorted({row["driver_id"] for row in material}),
            "finish_distribution_delta": sorted(deltas, key=lambda row: abs(row["average_finish_delta"]), reverse=True)[:12],
            "expected_points_delta": sorted(deltas, key=lambda row: abs(row["expected_points_delta"]), reverse=True)[:12],
            "rank_delta": sorted(deltas, key=lambda row: abs(row["expected_rank_delta"]), reverse=True)[:12],
            "probability_delta_bucket": bucket_delta(max((abs(row["podium_delta"]) for row in deltas), default=0.0)),
            "interpretation_zh": (
                "同种子对比：弱 seed 初始状态与完整信息更新后的 BeliefState。"
                "该记录证明结构化数据和 Codex 信息整体进入状态向量后改变了预测分布。"
            ),
        }

    def isolated_row(
        self,
        counterfactual_probabilities: list[Any],
        candidate_probabilities: list[Any],
        belief_state: BeliefState,
        claim_id: str,
        source_id: str,
        updates: list[StateUpdateLedgerRow],
    ) -> dict[str, Any]:
        counterfactual_by_driver = {row.driver_id: row for row in counterfactual_probabilities}
        candidate_by_driver = {row.driver_id: row for row in candidate_probabilities}
        driver_ids = sorted(set(counterfactual_by_driver) | set(candidate_by_driver))
        counterfactual_rank = rank_by_average_finish(counterfactual_by_driver)
        candidate_rank = rank_by_average_finish(candidate_by_driver)
        deltas = []
        for driver_id in driver_ids:
            counterfactual = counterfactual_by_driver.get(driver_id)
            candidate = candidate_by_driver.get(driver_id)
            if counterfactual is None or candidate is None:
                continue
            deltas.append(
                {
                    "driver_id": driver_id,
                    "win_delta": round(candidate.win - counterfactual.win, 6),
                    "podium_delta": round(candidate.podium - counterfactual.podium, 6),
                    "expected_points_delta": round(candidate.expected_points - counterfactual.expected_points, 4),
                    "average_finish_delta": round(candidate.average_finish - counterfactual.average_finish, 4),
                    "expected_rank_delta": candidate_rank.get(driver_id, 0) - counterfactual_rank.get(driver_id, 0),
                }
            )
        material = [
            row for row in deltas
            if abs(row["expected_points_delta"]) >= 0.05
            or abs(row["podium_delta"]) >= 0.005
            or abs(row["expected_rank_delta"]) >= 1
        ]
        max_delta = max(
            (
                max(
                    abs(row["podium_delta"]),
                    abs(row["win_delta"]),
                    abs(row["expected_points_delta"]) / 25.0,
                )
                for row in deltas
            ),
            default=0.0,
        )
        return {
            "impact_trace_id": safe_name(f"trace_{belief_state.state_id}_{claim_id}_isolated"),
            "update_id_or_group_id": claim_id,
            "claim_id": claim_id,
            "source_id": source_id,
            "trace_type": "isolated_same_seed_leave_one_information",
            "base_run_id": f"without_{safe_name(claim_id)}",
            "candidate_run_id": belief_state.state_id,
            "changed_factors": [
                {
                    "target_type": update.target_type,
                    "target_id": update.target_id,
                    "factor": update.factor,
                    "direction": update.direction,
                    "magnitude_bucket": update.magnitude_bucket,
                    "old_value_bucket": update.old_value_bucket,
                    "new_value_bucket": update.new_value_bucket,
                }
                for update in updates[:12]
            ],
            "affected_drivers": sorted({row["driver_id"] for row in material}),
            "finish_distribution_delta": sorted(deltas, key=lambda row: abs(row["average_finish_delta"]), reverse=True)[:12],
            "expected_points_delta": sorted(deltas, key=lambda row: abs(row["expected_points_delta"]), reverse=True)[:12],
            "rank_delta": sorted(deltas, key=lambda row: abs(row["expected_rank_delta"]), reverse=True)[:12],
            "probability_delta_bucket": bucket_delta(max_delta),
            "interpretation_zh": (
                "同种子隔离对比：完整 BeliefState 与移除这一条来源化信息后的 BeliefState。"
                "该记录用于说明这条信息本身对预测分布的边际影响。"
            ),
        }

    @staticmethod
    def _affected_driver_hint(update: StateUpdateLedgerRow) -> list[str]:
        if update.target_type == "driver":
            return [update.target_id]
        if update.target_type == "team":
            return [f"team:{update.target_id}"]
        if update.target_type == "event":
            return ["all_drivers"]
        return []


def self_changed_factors(ledger: list[StateUpdateLedgerRow]) -> list[dict[str, Any]]:
    rows = []
    for update in ledger:
        rows.append(
            {
                "target_type": update.target_type,
                "target_id": update.target_id,
                "factor": update.factor,
                "direction": update.direction,
                "magnitude_bucket": update.magnitude_bucket,
            }
        )
    return rows[:30]


def rank_by_average_finish(rows: dict[str, Any]) -> dict[str, int]:
    ranked = sorted(rows.values(), key=lambda row: (row.average_finish, -row.expected_points))
    return {row.driver_id: index for index, row in enumerate(ranked, start=1)}


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def dedupe_dicts(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        output[str(row.get(key))] = row
    return [output[item] for item in sorted(output)]


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def bucket_value(value: float) -> str:
    if value >= 0.22:
        return "strong_positive"
    if value >= 0.08:
        return "positive"
    if value <= -0.22:
        return "strong_negative"
    if value <= -0.08:
        return "negative"
    return "neutral"


def bucket_delta(value: float) -> str:
    magnitude = abs(value)
    if magnitude >= 0.08:
        return "large"
    if magnitude >= 0.035:
        return "medium"
    if magnitude >= 0.008:
        return "small"
    return "very_small"


def bucket_strength(value: float) -> str:
    if value >= 0.72:
        return "strong"
    if value >= 0.42:
        return "medium"
    if value >= 0.18:
        return "weak"
    return "very_weak"


def source_publisher(source: str) -> str:
    lowered = source.lower()
    if "fastf1" in lowered:
        return "FastF1"
    if "openf1" in lowered:
        return "OpenF1"
    if "official" in lowered:
        return "F1 official data"
    return source.split(":", 1)[0] if source else "unknown"


def _profile_value(profile: Any, key: str) -> float:
    if isinstance(profile, dict):
        try:
            return float(profile.get(key) or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0
