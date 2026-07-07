"""Simple pace model for the MVP simulator."""

from __future__ import annotations

from collections import defaultdict

from f1predict.belief_state import BeliefState
from f1predict.domain import Driver, EvidenceClaim, FeatureAdjustment, RaceEvent, SeasonState
from f1predict.models.technical_factors import technical_context_multiplier


class PaceModel:
    """Combines seed strengths, track affinity, and Codex evidence."""

    def __init__(
        self,
        season_state: SeasonState,
        evidence: list[EvidenceClaim],
        feature_adjustments: list[FeatureAdjustment] | None = None,
        evidence_weights: dict[str, float] | None = None,
        belief_state: BeliefState | None = None,
    ) -> None:
        self.season_state = season_state
        self.evidence = evidence
        self.feature_adjustments = feature_adjustments or []
        self.evidence_weights = evidence_weights or {}
        self.belief_state = belief_state
        self._impact = self._aggregate_evidence(evidence, self.evidence_weights)
        self._feature_impact = self._aggregate_features(self.feature_adjustments)

    def driver_score(self, driver: Driver, event: RaceEvent, mode: str = "race") -> float:
        return self.score_breakdown(driver, event, mode=mode)["total"]

    def score_breakdown(self, driver: Driver, event: RaceEvent, mode: str = "race") -> dict[str, float]:
        """Return the additive pace-score components used by the simulator."""

        if self.belief_state is not None:
            return self._belief_score_breakdown(driver, event, mode=mode)

        team = self.season_state.teams[driver.team_id]
        track_bonus = team.track_affinity.get(event.track_type, 0.0)
        weather_wet = self._effective_wet_probability(event)
        components = {
            "team_base_strength": team.base_strength,
            "driver_base_skill": driver.base_skill,
            "track_affinity": track_bonus,
            "racecraft": driver.racecraft,
            "wet_skill": driver.wet_skill * weather_wet,
            "team_strategy": team.strategy * 0.12,
            "tyre_management": 0.0,
            "qualifying": 0.0,
            "evidence_race_pace": (
                self._impact[(driver.driver_id, "race_pace")]
                + self._impact[(driver.team_id, "race_pace")]
            ),
            "feature_race_pace": (
                self._feature_impact[(driver.driver_id, "race_pace")]
                + self._feature_impact[(driver.team_id, "race_pace")]
            ),
            "evidence_race_execution": 0.0,
            "feature_race_execution": 0.0,
            "evidence_qualifying_pace": 0.0,
            "feature_qualifying_pace": 0.0,
            "evidence_wet_skill": self._impact[(driver.driver_id, "wet_skill")] * weather_wet,
            "evidence_strategy": self._impact[(driver.team_id, "strategy")] * 0.2,
            "evidence_power_unit": self._contextual_metric(driver, event, "power_unit", mode),
            "feature_power_unit": self._contextual_metric(driver, event, "power_unit", mode, features=True),
            "evidence_energy_recovery": self._contextual_metric(driver, event, "energy_recovery", mode),
            "feature_energy_recovery": self._contextual_metric(driver, event, "energy_recovery", mode, features=True),
            "evidence_straight_line_speed": self._contextual_metric(driver, event, "straight_line_speed", mode),
            "feature_straight_line_speed": self._contextual_metric(
                driver,
                event,
                "straight_line_speed",
                mode,
                features=True,
            ),
            "evidence_drag_efficiency": self._contextual_metric(driver, event, "drag_efficiency", mode),
            "feature_drag_efficiency": self._contextual_metric(driver, event, "drag_efficiency", mode, features=True),
            "evidence_low_speed_traction": self._contextual_metric(driver, event, "low_speed_traction", mode),
            "feature_low_speed_traction": self._contextual_metric(
                driver,
                event,
                "low_speed_traction",
                mode,
                features=True,
            ),
            "evidence_weight": self._contextual_metric(driver, event, "weight", mode),
            "feature_weight": self._contextual_metric(driver, event, "weight", mode, features=True),
            "evidence_upgrade_effect": self._contextual_metric(driver, event, "upgrade_effect", mode),
            "feature_upgrade_effect": self._contextual_metric(driver, event, "upgrade_effect", mode, features=True),
        }
        if mode == "qualifying":
            components["qualifying"] = driver.qualifying * 0.55
            components["evidence_qualifying_pace"] = (
                self._impact[(driver.driver_id, "qualifying_pace")]
                + self._impact[(driver.team_id, "qualifying_pace")]
            )
            components["feature_qualifying_pace"] = (
                self._feature_impact[(driver.driver_id, "qualifying_pace")]
                + self._feature_impact[(driver.team_id, "qualifying_pace")]
            )
        else:
            components["tyre_management"] = driver.tyre_management * 0.20
            components["evidence_race_execution"] = (
                self._impact[(driver.driver_id, "race_execution")]
                + self._impact[(driver.team_id, "race_execution")]
            )
            components["feature_race_execution"] = (
                self._feature_impact[(driver.driver_id, "race_execution")]
                + self._feature_impact[(driver.team_id, "race_execution")]
            )
        total = sum(components.values())
        return {**components, "total": total}

    def _belief_score_breakdown(self, driver: Driver, event: RaceEvent, mode: str = "race") -> dict[str, float]:
        team_id = driver.team_id
        wet_probability = self._effective_wet_probability(event)
        car_overall = self.belief_state.car_value(team_id, "overall_pace")
        car_race = self.belief_state.car_value(team_id, "race_pace")
        car_qualifying = self.belief_state.car_value(team_id, "qualifying_pace")
        driver_race = self.belief_state.driver_value(driver.driver_id, "race_pace")
        driver_qualifying = self.belief_state.driver_value(driver.driver_id, "qualifying_ceiling")
        driver_execution = self.belief_state.driver_value(driver.driver_id, "race_execution")
        team_execution = self.belief_state.team_ops_value(team_id, "race_execution")
        strategy = self.belief_state.team_ops_value(team_id, "strategy_quality")
        tyre = self.belief_state.driver_value(driver.driver_id, "tyre_management")
        wet_skill = self.belief_state.driver_value(driver.driver_id, "wet_skill") * wet_probability
        technical = self._belief_contextual_technical(driver, event, mode)

        if mode == "qualifying":
            components = {
                "belief_car_overall": car_overall * 0.85,
                "belief_car_qualifying_pace": car_qualifying * 2.15,
                "belief_car_race_pace_carryover": car_race * 0.55,
                "belief_driver_qualifying_ceiling": driver_qualifying * 1.20,
                "belief_driver_race_pace_carryover": driver_race * 0.35,
                "belief_technical_track_fit": technical * 0.90,
            }
        else:
            components = {
                "belief_car_overall": car_overall * 0.85,
                "belief_car_race_pace": car_race * 1.95,
                "belief_driver_race_pace": driver_race * 0.85,
                "belief_driver_race_execution": driver_execution * 0.62,
                "belief_team_race_execution": team_execution * 0.38,
                "belief_team_strategy": strategy * 0.24,
                "belief_driver_tyre_management": tyre * 0.34,
                "belief_driver_wet_skill": wet_skill * 0.55,
                "belief_technical_track_fit": technical,
            }
        total = sum(components.values())
        return {**components, "total": total}

    def reliability(self, driver: Driver) -> float:
        if self.belief_state is not None:
            rel = 0.94
            rel += self.belief_state.car_value(driver.team_id, "reliability")
            rel += self.belief_state.driver_value(driver.driver_id, "reliability")
            return min(0.995, max(0.80, rel))
        team = self.season_state.teams[driver.team_id]
        rel = team.reliability + driver.reliability_modifier
        rel += self._impact[(driver.driver_id, "reliability")]
        rel += self._impact[(driver.team_id, "reliability")]
        rel += self._feature_impact[(driver.driver_id, "reliability")]
        rel += self._feature_impact[(driver.team_id, "reliability")]
        return min(0.995, max(0.80, rel))

    def degradation_adjustment(self, driver: Driver, event: RaceEvent) -> float:
        """Positive values mean lower tyre degradation for this driver/team/event."""

        if self.belief_state is not None:
            return (
                self.belief_state.car_value(driver.team_id, "tyre_deg")
                + self.belief_state.driver_value(driver.driver_id, "tyre_management")
            )
        return self._combined_metric(driver, event, "tyre_deg")

    def strategy_signal(self, driver: Driver, event: RaceEvent) -> float:
        if self.belief_state is not None:
            return self.belief_state.team_ops_value(driver.team_id, "strategy_quality")
        return self._combined_metric(driver, event, "strategy")

    def launch_adjustment(self, driver: Driver, event: RaceEvent) -> float:
        """Positive values improve start and first-lap conversion after the sampled grid."""

        if self.belief_state is not None:
            return self.belief_state.driver_value(driver.driver_id, "first_lap_gain")
        return (
            self._contextual_metric(driver, event, "launch_performance", mode="race")
            + self._contextual_metric(driver, event, "launch_performance", mode="race", features=True)
        )

    def _effective_wet_probability(self, event: RaceEvent) -> float:
        if self.belief_state is not None:
            return min(1.0, max(0.0, self.belief_state.event_value("wet_probability", event.weather_prior.get("wet_probability", 0.0))))
        event_adjustment = self._impact[(event.event_id, "wet_skill")]
        value = event.weather_prior.get("wet_probability", 0.0) + event_adjustment
        return min(1.0, max(0.0, value))

    def _belief_contextual_technical(self, driver: Driver, event: RaceEvent, mode: str) -> float:
        team_id = driver.team_id
        metric_factors = {
            "power_unit": "power_unit_peak",
            "energy_recovery": "ers_deployment",
            "straight_line_speed": "straight_line_speed",
            "drag_efficiency": "aero_efficiency",
            "low_speed_traction": "traction",
            "upgrade_effect": "upgrade_delta",
        }
        total = 0.0
        for metric, factor in metric_factors.items():
            value = self.belief_state.car_value(team_id, factor)
            if value:
                total += value * self._metric_multiplier(metric, event, mode)
        return total

    def _combined_metric(self, driver: Driver, event: RaceEvent, metric: str) -> float:
        return (
            self._impact[(driver.driver_id, metric)]
            + self._impact[(driver.team_id, metric)]
            + self._impact[(event.event_id, metric)]
            + self._feature_impact[(driver.driver_id, metric)]
            + self._feature_impact[(driver.team_id, metric)]
            + self._feature_impact[(event.event_id, metric)]
        )

    def _metric_source_value(
        self,
        driver: Driver,
        event: RaceEvent,
        metric: str,
        features: bool = False,
    ) -> float:
        source = self._feature_impact if features else self._impact
        return source[(driver.driver_id, metric)] + source[(driver.team_id, metric)] + source[(event.event_id, metric)]

    def _contextual_metric(
        self,
        driver: Driver,
        event: RaceEvent,
        metric: str,
        mode: str,
        features: bool = False,
    ) -> float:
        value = self._metric_source_value(driver, event, metric, features=features)
        if value == 0.0:
            return 0.0
        multiplier = self._metric_multiplier(metric, event, mode)
        return value * multiplier

    @staticmethod
    def _metric_multiplier(metric: str, event: RaceEvent, mode: str) -> float:
        return technical_context_multiplier(
            metric,
            event.track_type,
            mode=mode,
            feature_refs=event.feature_refs,
        )

    @staticmethod
    def _aggregate_evidence(
        evidence: list[EvidenceClaim],
        evidence_weights: dict[str, float] | None = None,
    ) -> defaultdict[tuple[str, str], float]:
        impact: defaultdict[tuple[str, str], float] = defaultdict(float)
        weights = evidence_weights or {}
        for claim in evidence:
            impact[(claim.target_id, claim.metric)] += claim.signed_impact() * weights.get(claim.claim_id, 1.0)
        return impact

    @staticmethod
    def _aggregate_features(features: list[FeatureAdjustment]) -> defaultdict[tuple[str, str], float]:
        impact: defaultdict[tuple[str, str], float] = defaultdict(float)
        for feature in features:
            impact[(feature.target_id, feature.metric)] += feature.weighted_value()
        return impact
