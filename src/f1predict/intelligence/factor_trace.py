"""Route normalized Codex claims into simulator-facing factor traces."""

from __future__ import annotations

from dataclasses import dataclass

from f1predict.domain import EvidenceClaim, EvidenceImpact, EvidenceQuality, FactorTrace, RaceEvent, SeasonState
from f1predict.models.technical_factors import (
    technical_context_breakdown,
    technical_context_multiplier,
    technical_context_reason,
)


@dataclass(frozen=True)
class FactorRoute:
    route: str
    model_surface: str
    notes: tuple[str, ...]


TRACK_CONTEXTUAL_METRICS = {
    "power_unit",
    "energy_recovery",
    "straight_line_speed",
    "drag_efficiency",
    "low_speed_traction",
    "launch_performance",
    "weight",
    "upgrade_effect",
}


FACTOR_ROUTES: dict[str, FactorRoute] = {
    "race_pace": FactorRoute(
        route="race_pace_score",
        model_surface="race pace score",
        notes=("Adds to driver/team race score before race-time sampling.",),
    ),
    "race_execution": FactorRoute(
        route="race_execution_score",
        model_surface="race execution score",
        notes=("Adds to the race score as grid-to-finish conversion, racecraft, and clean-race execution signal.",),
    ),
    "qualifying_pace": FactorRoute(
        route="qualifying_grid_score",
        model_surface="qualifying grid sampler",
        notes=("Adds to qualifying score before sampled grid order.",),
    ),
    "tyre_deg": FactorRoute(
        route="tyre_degradation",
        model_surface="stint degradation rate",
        notes=("Changes the per-lap tyre degradation term used in replay and race-time sampling.",),
    ),
    "reliability": FactorRoute(
        route="reliability",
        model_surface="DNF and race reliability",
        notes=("Changes the reliability probability used before race-time sampling.",),
    ),
    "wet_skill": FactorRoute(
        route="wet_weather",
        model_surface="wet-race branch",
        notes=("Changes wet probability or wet-performance contribution depending on target scope.",),
    ),
    "safety_car_probability": FactorRoute(
        route="safety_car_sampler",
        model_surface="safety-car event sampler",
        notes=("Changes the event-level safety-car probability used by pit-window and field-bunching simulation.",),
    ),
    "red_flag_probability": FactorRoute(
        route="red_flag_sampler",
        model_surface="red-flag event sampler",
        notes=("Changes the event-level red-flag tail used by pit-window, tyre-relief, and restart-variance diagnostics.",),
    ),
    "strategy": FactorRoute(
        route="pit_strategy",
        model_surface="pit strategy plan",
        notes=("Changes stop selection, operational noise, and pit-window behavior.",),
    ),
    "setup_quality": FactorRoute(
        route="race_window_setup",
        model_surface="race-week setup window",
        notes=("Changes same-weekend setup/window state used by race score and team race-window pressure.",),
    ),
    "power_unit": FactorRoute(
        route="track_contextual_pace",
        model_surface="track-weighted pace score",
        notes=("Scaled by circuit type; strongest on power and high-speed circuits.",),
    ),
    "energy_recovery": FactorRoute(
        route="track_contextual_pace",
        model_surface="track-weighted pace score",
        notes=("Scaled by circuit type; captures ERS deployment and clipping sensitivity.",),
    ),
    "straight_line_speed": FactorRoute(
        route="track_contextual_pace",
        model_surface="track-weighted pace score",
        notes=("Scaled by circuit type; strongest where long straights dominate lap time.",),
    ),
    "drag_efficiency": FactorRoute(
        route="track_contextual_pace",
        model_surface="track-weighted pace score",
        notes=("Scaled by circuit type; rewards efficient high-speed aero packages.",),
    ),
    "low_speed_traction": FactorRoute(
        route="track_contextual_pace",
        model_surface="track-weighted pace score",
        notes=("Scaled by circuit type; strongest on street and low-speed tracks.",),
    ),
    "launch_performance": FactorRoute(
        route="race_start_launch",
        model_surface="start and first-lap race-time sampler",
        notes=("Scaled by launch importance; changes start/first-lap race-time conversion after the sampled grid.",),
    ),
    "weight": FactorRoute(
        route="track_contextual_pace",
        model_surface="track-weighted pace score",
        notes=("Scaled by circuit type; penalizes excess mass across acceleration and tyre-load phases.",),
    ),
    "upgrade_effect": FactorRoute(
        route="track_contextual_pace",
        model_surface="track-weighted pace score",
        notes=("Applies a broad package delta to race and qualifying pace context.",),
    ),
}


class FactorTraceBuilder:
    """Builds an auditable bridge from normalized claims to model impact."""

    def build(
        self,
        season: SeasonState,
        event: RaceEvent,
        evidence: list[EvidenceClaim],
        evidence_impact: list[EvidenceImpact],
        evidence_quality: list[EvidenceQuality],
    ) -> list[FactorTrace]:
        impact_by_claim = {row.claim_id: row for row in evidence_impact}
        quality_by_claim = {row.claim_id: row for row in evidence_quality}
        rows = [
            self._row(season, event, claim, impact_by_claim.get(claim.claim_id), quality_by_claim.get(claim.claim_id))
            for claim in evidence
        ]
        return sorted(
            rows,
            key=lambda row: (
                abs(row.max_win_probability_delta or 0.0),
                abs(row.signed_input_impact),
            ),
            reverse=True,
        )

    def _row(
        self,
        season: SeasonState,
        event: RaceEvent,
        claim: EvidenceClaim,
        impact: EvidenceImpact | None,
        quality: EvidenceQuality | None,
    ) -> FactorTrace:
        route = FACTOR_ROUTES.get(
            claim.metric,
            FactorRoute(
                route="unsupported_metric",
                model_surface="not routed",
                notes=("Metric is valid in the evidence schema but has no simulator route.",),
            ),
        )
        target_note = self._target_note(season, event, claim)
        max_delta = impact.max_win_probability_delta if impact is not None else None
        affected = list(impact.affected_outcomes) if impact is not None else []
        route_status = self._route_status(route, target_note, affected, max_delta)
        raw_signed_impact = round(claim.signed_impact(), 4)
        model_input_weight = quality.model_input_weight if quality is not None else 1.0
        weighted_input_impact = round(
            impact.signed_input_impact if impact is not None else claim.signed_impact() * model_input_weight,
            4,
        )
        notes = [
            *route.notes,
            f"target_scope={claim.target_type}:{claim.target_id}",
            f"track_type={event.track_type}",
        ]
        context_multiplier = None
        qualifying_context_multiplier = None
        context_multiplier_reason = None
        context_breakdown = technical_context_breakdown(claim.metric, event.track_type, feature_refs=event.feature_refs)
        track_demand_component = None
        track_demand_value = None
        track_demand_profile = None
        effective_race_input = weighted_input_impact
        effective_qualifying_input = None
        if claim.metric in TRACK_CONTEXTUAL_METRICS:
            context_multiplier = round(
                technical_context_multiplier(claim.metric, event.track_type, feature_refs=event.feature_refs),
                4,
            )
            qualifying_context_multiplier = round(
                technical_context_multiplier(
                    claim.metric,
                    event.track_type,
                    mode="qualifying",
                    feature_refs=event.feature_refs,
                ),
                4,
            )
            context_multiplier_reason = technical_context_reason(
                claim.metric,
                event.track_type,
                feature_refs=event.feature_refs,
            )
            if context_breakdown:
                track_demand_component = str(context_breakdown.get("demand_component") or "") or None
                raw_demand_value = context_breakdown.get("demand_value")
                track_demand_value = float(raw_demand_value) if raw_demand_value is not None else None
                profile = context_breakdown.get("track_demand_profile")
                track_demand_profile = profile if isinstance(profile, dict) else None
            effective_race_input = round(weighted_input_impact * context_multiplier, 4)
            effective_qualifying_input = round(weighted_input_impact * qualifying_context_multiplier, 4)
            notes.append("track_context_multiplier_applied=true")
            notes.append(f"context_multiplier={context_multiplier:.4f}")
            notes.append(f"qualifying_context_multiplier={qualifying_context_multiplier:.4f}")
            notes.append(f"effective_race_input={effective_race_input:+.4f}")
            if track_demand_component:
                notes.append(f"track_demand_component={track_demand_component}")
            if track_demand_value is not None:
                notes.append(f"track_demand_value={track_demand_value:.4f}")
            if context_multiplier_reason:
                notes.append(context_multiplier_reason)
        elif route.route == "qualifying_grid_score":
            effective_qualifying_input = weighted_input_impact
        elif route.route in {
            "race_pace_score",
            "race_execution_score",
            "tyre_degradation",
            "reliability",
            "pit_strategy",
            "wet_weather",
        }:
            effective_race_input = weighted_input_impact
        if quality is not None:
            notes.append(f"model_input_weight={quality.model_input_weight:.2f}")
        notes.append(f"raw_signed_impact={raw_signed_impact:+.4f}")
        notes.append(f"weighted_input_impact={weighted_input_impact:+.4f}")
        if target_note:
            notes.append(target_note)
        if impact is None:
            notes.append("impact_diagnostic_missing=true")
        elif not affected:
            notes.append("same_seed_comparison_found_no_target_outcomes=true")
        elif max_delta is not None:
            notes.append(f"same_seed_max_win_delta={max_delta:+.4f}")

        return FactorTrace(
            claim_id=claim.claim_id,
            target_type=claim.target_type,
            target_id=claim.target_id,
            claim_type=claim.claim_type,
            metric=claim.metric,
            direction=claim.direction,
            route=route.route,
            model_surface=route.model_surface,
            route_status=route_status,
            raw_signed_impact=raw_signed_impact,
            weighted_input_impact=weighted_input_impact,
            effective_race_input=effective_race_input,
            effective_qualifying_input=effective_qualifying_input,
            signed_input_impact=weighted_input_impact,
            max_win_probability_delta=round(max_delta, 4) if max_delta is not None else None,
            affected_outcome_count=len(affected),
            affected_outcomes=affected,
            quality_status=quality.quality_status if quality is not None else None,
            source_status=quality.source_status if quality is not None else None,
            triangulation_status=quality.triangulation_status if quality is not None else None,
            conflict_status=quality.conflict_status if quality is not None else None,
            source_reliability=quality.source_reliability if quality is not None else None,
            model_input_weight=quality.model_input_weight if quality is not None else None,
            context_multiplier=context_multiplier,
            context_multiplier_reason=context_multiplier_reason,
            track_demand_component=track_demand_component,
            track_demand_value=round(track_demand_value, 4) if track_demand_value is not None else None,
            track_demand_profile=track_demand_profile,
            risk_flags=quality.risk_flags if quality is not None else (),
            route_notes=tuple(notes),
        )

    @staticmethod
    def _target_note(season: SeasonState, event: RaceEvent, claim: EvidenceClaim) -> str | None:
        if claim.target_type == "driver" and claim.target_id not in season.drivers:
            return "target_not_in_driver_roster"
        if claim.target_type == "team" and claim.target_id not in season.teams:
            return "target_not_in_team_roster"
        if claim.target_type == "event" and claim.target_id != event.event_id:
            return "target_event_does_not_match_prediction_event"
        if claim.target_type == "market":
            return "market_target_not_used_by_simulator"
        return None

    @staticmethod
    def _route_status(
        route: FactorRoute,
        target_note: str | None,
        affected_outcomes: list[dict[str, object]],
        max_delta: float | None,
    ) -> str:
        if route.route == "unsupported_metric":
            return "unsupported_metric"
        if target_note and target_note.startswith("target_not"):
            return "target_not_in_model"
        if target_note == "market_target_not_used_by_simulator":
            return "not_simulator_input"
        if max_delta is None:
            return "routed_impact_not_measured"
        if not affected_outcomes:
            return "routed_no_target_outcomes"
        if abs(max_delta) < 0.001:
            return "routed_low_observed_movement"
        return "observed_probability_movement"
