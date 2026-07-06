"""Monte Carlo single-race simulator."""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from statistics import mean
from typing import Any

from f1predict.domain import Driver, DriverRaceProbability, RaceEvent, SeasonState
from f1predict.market_outcomes import driver_h2h_outcome_id
from f1predict.models.pace import PaceModel
from f1predict.track_features import TrackFeatureVector, track_feature_vector


POINTS = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1]


@dataclass(frozen=True)
class StrategyPlan:
    stops: int
    pit_laps: tuple[int, ...]
    start_compound: str
    alternate_compound: str
    pit_loss: float
    degradation_rate: float
    safety_car_adjusted: bool = False


@dataclass(frozen=True)
class SimulatorConfig:
    """Tunable parameters for the compact race-time simulator."""

    config_id: str = "default_pace_separation_track_position_v2"
    description: str = (
        "Pace-separation simulator defaults with source-backed track-position conversion; "
        "still not formal-ready without holdout validation."
    )
    qualifying_noise_sd: float = 0.38
    race_score_lap_time_scale: float = 0.66
    grid_penalty_scale: float = 1.0
    initial_grid_gap_scale: float = 0.35
    traffic_gap_per_position: float = 0.018
    replay_lap_noise_sd: float = 0.16
    operational_noise_min_sd: float = 0.8
    operational_noise_per_stop: float = 1.05
    race_noise_base_sd: float = 4.8
    race_noise_per_lap_sd: float = 0.045
    strategy_quality_scale: float = 0.65
    safety_car_pit_gain_cap: float = 8.0
    safety_car_pit_gain_fraction: float = 0.38
    safety_car_bunching_per_grid_position: float = 0.16
    launch_time_scale: float = 22.0
    known_qualifying_position_noise_sd: float = 0.32

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


@dataclass(frozen=True)
class RaceSimulationSummary:
    race_probabilities: list[DriverRaceProbability]
    representative_lap: list[dict[str, Any]]
    team_double_podium_probabilities: dict[str, float]
    driver_h2h_probabilities: dict[str, float]
    iterations: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "race_probabilities": [row.__dict__ for row in self.race_probabilities],
            "representative_lap": self.representative_lap,
            "team_double_podium_probabilities": self.team_double_podium_probabilities,
            "driver_h2h_probabilities": self.driver_h2h_probabilities,
            "iterations": self.iterations,
        }


class SingleRaceSimulator:
    """Strategy-aware Monte Carlo race simulator for the MVP.

    This is still a compact model, but each sampled result is now driven by
    race-time components instead of a pure ranking score: grid position, tyre
    degradation, pit loss, weather phase, safety-car pit windows, and
    reliability all contribute to the sampled finishing order.
    """

    def __init__(
        self,
        season_state: SeasonState,
        pace_model: PaceModel,
        iterations: int = 5000,
        seed: int = 7,
        config: SimulatorConfig | None = None,
    ) -> None:
        self.season_state = season_state
        self.pace_model = pace_model
        self.iterations = iterations
        self.random = random.Random(seed)
        self.config = config or SimulatorConfig()
        self._track_feature_cache: dict[str, TrackFeatureVector] = {}

    def simulate(self, event: RaceEvent) -> tuple[list[DriverRaceProbability], list[dict[str, Any]]]:
        summary = self.simulate_summary(event)
        return summary.race_probabilities, summary.representative_lap

    def simulate_summary(self, event: RaceEvent) -> RaceSimulationSummary:
        driver_ids = list(self.season_state.drivers)
        wins = defaultdict(int)
        podiums = defaultdict(int)
        points_finishes = defaultdict(int)
        total_points = defaultdict(float)
        finishes = defaultdict(list)
        team_double_podiums = defaultdict(int)
        driver_h2h = defaultdict(int)
        representative_lap = self.sample_replay(event, max_drivers=6)

        for _ in range(self.iterations):
            result = self._simulate_once(event, driver_ids)
            positions = {driver_id: position for position, driver_id in enumerate(result, start=1)}
            top_three = set(result[:3])
            teams_on_double_podium = {
                team_id
                for team_id in self.season_state.teams
                if sum(
                    1
                    for driver_id in top_three
                    if self.season_state.drivers[driver_id].team_id == team_id
                )
                >= 2
            }
            for team_id in teams_on_double_podium:
                team_double_podiums[team_id] += 1
            for driver_id in driver_ids:
                driver_position = positions[driver_id]
                for opponent_id in driver_ids:
                    if driver_id == opponent_id:
                        continue
                    if driver_position < positions[opponent_id]:
                        driver_h2h[driver_h2h_outcome_id(driver_id, opponent_id)] += 1
            for pos, driver_id in enumerate(result, start=1):
                finishes[driver_id].append(pos)
                if pos == 1:
                    wins[driver_id] += 1
                if pos <= 3:
                    podiums[driver_id] += 1
                if pos <= 10:
                    points_finishes[driver_id] += 1
                    total_points[driver_id] += POINTS[pos - 1]

        probabilities = []
        for driver_id in driver_ids:
            denominator = float(self.iterations)
            probabilities.append(
                DriverRaceProbability(
                    driver_id=driver_id,
                    win=wins[driver_id] / denominator,
                    podium=podiums[driver_id] / denominator,
                    points=points_finishes[driver_id] / denominator,
                    expected_points=total_points[driver_id] / denominator,
                    average_finish=mean(finishes[driver_id]),
                )
            )

        probabilities.sort(key=lambda item: item.win, reverse=True)
        denominator = float(self.iterations)
        team_double_podium_probabilities = {
            team_id: team_double_podiums[team_id] / denominator
            for team_id in self.season_state.teams
        }
        driver_h2h_probabilities = {
            driver_h2h_outcome_id(driver_id, opponent_id): driver_h2h[
                driver_h2h_outcome_id(driver_id, opponent_id)
            ]
            / denominator
            for driver_id in driver_ids
            for opponent_id in driver_ids
            if driver_id != opponent_id
        }
        return RaceSimulationSummary(
            race_probabilities=probabilities,
            representative_lap=representative_lap,
            team_double_podium_probabilities=team_double_podium_probabilities,
            driver_h2h_probabilities=driver_h2h_probabilities,
            iterations=self.iterations,
        )

    def sample_order(self, event: RaceEvent, driver_ids: list[str] | None = None) -> list[str]:
        """Sample one race finishing order using the same strategy-aware model."""

        return self._simulate_once(event, driver_ids or list(self.season_state.drivers))

    def _simulate_once(self, event: RaceEvent, driver_ids: list[str]) -> list[str]:
        grid_order = self._sample_grid(event, driver_ids)
        grid_positions = {driver_id: index for index, driver_id in enumerate(grid_order, start=1)}
        wet_race = self.random.random() < self._wet_probability(event)
        safety_car_lap = self._sample_safety_car_lap(event, wet_race)
        sampled: list[tuple[float, str]] = []
        for driver_id in driver_ids:
            driver = self.season_state.drivers[driver_id]
            plan = self._strategy_plan(event, driver, safety_car_lap=safety_car_lap)
            reliability = self.pace_model.reliability(driver)
            race_time = self._sample_race_time(
                event=event,
                driver=driver,
                plan=plan,
                grid_position=grid_positions[driver_id],
                wet_race=wet_race,
                safety_car_lap=safety_car_lap,
                reliability=reliability,
            )
            sampled.append((race_time, driver_id))
        sampled.sort(key=lambda item: item[0])
        return [driver_id for _, driver_id in sampled]

    def sample_replay(self, event: RaceEvent, max_drivers: int = 8) -> list[dict[str, Any]]:
        """Sample a full-lap race replay for the frontend diagnostic view.

        The replay is intentionally one illustrative draw from the same factor
        model used for probabilities. It exposes how grid, tyres, pit stops,
        weather, safety-car timing, traffic, and reliability shaped that draw.
        """

        random_state = self.random.getstate()
        rows: list[dict[str, Any]] = []
        try:
            driver_ids = list(self.season_state.drivers)
            grid_order = self._sample_grid(event, driver_ids)
            grid_positions = {driver_id: index for index, driver_id in enumerate(grid_order, start=1)}
            visible_drivers = set(grid_order[:max(1, max_drivers)])
            wet_race = self.random.random() < self._wet_probability(event)
            wet_laps = self._sample_wet_laps(event, wet_race)
            safety_car_lap = self._sample_safety_car_lap(event, wet_race)
            plans = {
                driver_id: self._strategy_plan(
                    event,
                    self.season_state.drivers[driver_id],
                    safety_car_lap=safety_car_lap,
                )
                for driver_id in driver_ids
            }
            dnf_laps: dict[str, int] = {}
            reliabilities: dict[str, float] = {}
            for driver_id in driver_ids:
                driver = self.season_state.drivers[driver_id]
                reliability = self.pace_model.reliability(driver)
                reliabilities[driver_id] = reliability
                if self.random.random() > reliability:
                    dnf_laps[driver_id] = self.random.randint(
                        max(2, event.laps // 5),
                        max(3, event.laps),
                    )

            track_penalty = self._track_position_penalty(event)
            cumulative = {}
            for driver_id in driver_ids:
                driver = self.season_state.drivers[driver_id]
                grid_position = grid_positions[driver_id]
                launch_bonus = self._launch_time_bonus(event, driver, grid_position)
                cumulative[driver_id] = (
                    max(0, grid_position - 1)
                    * track_penalty
                    * self.config.initial_grid_gap_scale
                    - launch_bonus
                )
            previous_positions = dict(grid_positions)
            for lap in range(1, event.laps + 1):
                lap_records: dict[str, dict[str, Any]] = {}
                wet_phase = wet_race and lap <= wet_laps
                safety_phase = safety_car_lap is not None and safety_car_lap <= lap <= safety_car_lap + 1
                for driver_id in driver_ids:
                    driver = self.season_state.drivers[driver_id]
                    plan = plans[driver_id]
                    stint, compound, tyre_age, pit_stop = self._lap_strategy_state(lap, plan)
                    base = self._base_lap_time(event, driver)
                    deg = tyre_age * plan.degradation_rate
                    weather = self._wet_lap_penalty(driver, wet_phase, lap, event.laps)
                    traffic = self.config.traffic_gap_per_position * max(
                        0,
                        previous_positions.get(driver_id, grid_positions[driver_id]) - 1,
                    )
                    pit_delta = plan.pit_loss if pit_stop else 0.0
                    safety_delta = 6.5 if safety_phase else 0.0
                    lap_noise = self.random.gauss(0.0, self.config.replay_lap_noise_sd)
                    dnf_lap = dnf_laps.get(driver_id)
                    dnf = dnf_lap is not None and lap >= dnf_lap
                    if dnf_lap is not None and lap == dnf_lap:
                        lap_time = base + 45.0 + self.random.random()
                        cumulative[driver_id] = 1_000_000.0 + (event.laps - dnf_lap) * 100.0
                    elif dnf:
                        lap_time = None
                    else:
                        lap_time = base + deg + weather + traffic + pit_delta + safety_delta + lap_noise
                        cumulative[driver_id] += lap_time
                    track_status = "safety_car" if safety_phase else "wet" if wet_phase else "green"
                    if dnf:
                        track_status = "dnf"
                    lap_records[driver_id] = {
                        "lap_time": round(lap_time, 3) if lap_time is not None else None,
                        "tyre_age": tyre_age,
                        "compound": compound,
                        "stint": stint,
                        "pit_stop": pit_stop and not dnf,
                        "track_status": track_status,
                        "dnf": dnf,
                    }

                if safety_phase:
                    active_order = [
                        driver_id
                        for driver_id in sorted(driver_ids, key=lambda item: (cumulative[item], grid_positions[item]))
                        if not lap_records[driver_id]["dnf"]
                    ]
                    if active_order:
                        leader_time = cumulative[active_order[0]]
                        for index, driver_id in enumerate(active_order[1:12], start=1):
                            bunched_gap = index * 0.95 + self.random.uniform(0.0, 0.2)
                            cumulative[driver_id] = min(cumulative[driver_id], leader_time + bunched_gap)

                ranked = sorted(driver_ids, key=lambda item: (cumulative[item], grid_positions[item]))
                positions = {driver_id: index for index, driver_id in enumerate(ranked, start=1)}
                leader_time = cumulative[ranked[0]]
                previous_positions = positions
                for driver_id in grid_order:
                    if driver_id not in visible_drivers:
                        continue
                    plan = plans[driver_id]
                    record = lap_records[driver_id]
                    gap = None if record["dnf"] else max(0.0, cumulative[driver_id] - leader_time)
                    rows.append(
                        {
                            "lap": lap,
                            "driver_id": driver_id,
                            "grid_position": grid_positions[driver_id],
                            "position": positions[driver_id],
                            "gap_to_leader": round(gap, 3) if gap is not None else None,
                            "cumulative_time": round(cumulative[driver_id], 3),
                            "lap_time": record["lap_time"],
                            "tyre_age": record["tyre_age"],
                            "compound": record["compound"],
                            "stint": record["stint"],
                            "pit_stop": record["pit_stop"],
                            "track_status": record["track_status"],
                            "dnf": record["dnf"],
                            "planned_stops": plan.stops,
                            "pit_laps": list(plan.pit_laps),
                            "wet_race": wet_race,
                            "wet_laps": wet_laps,
                            "safety_car_lap": safety_car_lap,
                            "reliability": round(reliabilities[driver_id], 4),
                        }
                    )
            return rows
        finally:
            self.random.setstate(random_state)

    def _sample_grid(self, event: RaceEvent, driver_ids: list[str]) -> list[str]:
        known_positions = self._known_qualifying_positions(event)
        if len(known_positions) >= max(3, len(driver_ids) // 2):
            sampled_positions: list[tuple[float, str]] = []
            fallback_position = max(known_positions.values(), default=len(driver_ids)) + 1
            for driver_id in driver_ids:
                driver = self.season_state.drivers[driver_id]
                qualifying_score = self.pace_model.driver_score(driver, event, mode="qualifying")
                base_position = known_positions.get(driver_id, fallback_position)
                sampled_positions.append(
                    (
                        base_position
                        - qualifying_score * 0.08
                        + self.random.gauss(0.0, self.config.known_qualifying_position_noise_sd),
                        driver_id,
                    )
                )
            sampled_positions.sort(key=lambda item: item[0])
            return [driver_id for _, driver_id in sampled_positions]

        sampled: list[tuple[float, str]] = []
        for driver_id in driver_ids:
            driver = self.season_state.drivers[driver_id]
            quali = self.pace_model.driver_score(driver, event, mode="qualifying")
            sampled.append((quali + self.random.gauss(0.0, self.config.qualifying_noise_sd), driver_id))
        sampled.sort(reverse=True)
        return [driver_id for _, driver_id in sampled]

    def _sample_race_time(
        self,
        event: RaceEvent,
        driver: Driver,
        plan: StrategyPlan,
        grid_position: int,
        wet_race: bool,
        safety_car_lap: int | None,
        reliability: float,
    ) -> float:
        if self.random.random() > reliability:
            dnf_lap = self.random.randint(max(2, event.laps // 5), max(3, event.laps))
            return 1_000_000.0 + (event.laps - dnf_lap) * 100.0 + self.random.random()

        base_lap = self._base_lap_time(event, driver)
        stint_degradation = self._total_degradation(event.laps, plan)
        pit_time = plan.pit_loss * plan.stops
        if plan.safety_car_adjusted:
            pit_time -= min(
                self.config.safety_car_pit_gain_cap,
                plan.pit_loss * self.config.safety_car_pit_gain_fraction,
            )

        grid_penalty = (
            max(0, grid_position - 1)
            * self._track_position_penalty(event)
            * self.config.grid_penalty_scale
        )
        launch_bonus = self._launch_time_bonus(event, driver, grid_position)
        wet_penalty = self._wet_race_penalty(event, driver, wet_race)
        safety_car_bunching = (
            -self.config.safety_car_bunching_per_grid_position * min(grid_position - 1, 12)
            if safety_car_lap is not None
            else 0.0
        )
        team = self.season_state.teams[driver.team_id]
        strategy_signal = self.pace_model.strategy_signal(driver, event)
        effective_strategy = min(1.0, max(0.0, team.strategy + strategy_signal))
        strategy_quality = effective_strategy * self.config.strategy_quality_scale
        operational_noise = self.random.gauss(
            0.0,
            max(self.config.operational_noise_min_sd, plan.stops * self.config.operational_noise_per_stop),
        )
        race_noise = self.random.gauss(
            0.0,
            self.config.race_noise_base_sd + event.laps * self.config.race_noise_per_lap_sd,
        )

        return (
            base_lap * event.laps
            + stint_degradation
            + pit_time
            + grid_penalty
            - launch_bonus
            + wet_penalty
            + safety_car_bunching
            - strategy_quality
            + operational_noise
            + race_noise
        )

    def _strategy_plan(
        self,
        event: RaceEvent,
        driver: Driver,
        safety_car_lap: int | None = None,
    ) -> StrategyPlan:
        team = self.season_state.teams[driver.team_id]
        strategy_signal = self.pace_model.strategy_signal(driver, event)
        effective_strategy = min(1.0, max(0.0, team.strategy + strategy_signal))
        deg_rate = self._degradation_rate(event, driver)
        base_stops = 2 if deg_rate * event.laps > 3.2 else 1
        if event.track_type in {"street", "street_low_speed"} and deg_rate * event.laps < 4.1:
            base_stops = 1
        if event.laps >= 68 and deg_rate > 0.055:
            base_stops = 2
        if self.random.random() < max(0.03, 0.16 - effective_strategy * 0.04):
            base_stops = max(1, min(3, base_stops + self.random.choice([-1, 1])))

        pit_loss = self._pit_loss(event)
        pit_laps = self._pit_laps(event.laps, base_stops)
        safety_adjusted = False
        if safety_car_lap is not None and pit_laps:
            closest = min(pit_laps, key=lambda lap: abs(lap - safety_car_lap))
            if abs(closest - safety_car_lap) <= 4 and effective_strategy + driver.racecraft > 1.65:
                pit_laps = tuple(sorted(safety_car_lap if lap == closest else lap for lap in pit_laps))
                safety_adjusted = True

        start_compound = "medium"
        alternate = "hard"
        if deg_rate < 0.045 and event.track_type in {"street", "low_speed"}:
            start_compound = "soft"
            alternate = "medium"
        if self._wet_probability(event) > 0.45:
            start_compound = "intermediate"
            alternate = "medium"

        return StrategyPlan(
            stops=base_stops,
            pit_laps=pit_laps,
            start_compound=start_compound,
            alternate_compound=alternate,
            pit_loss=pit_loss,
            degradation_rate=deg_rate,
            safety_car_adjusted=safety_adjusted,
        )

    @staticmethod
    def _pit_laps(laps: int, stops: int) -> tuple[int, ...]:
        if stops <= 0:
            return ()
        return tuple(max(2, min(laps - 1, round(laps * index / (stops + 1)))) for index in range(1, stops + 1))

    @staticmethod
    def _lap_strategy_state(lap: int, plan: StrategyPlan) -> tuple[int, str, int, bool]:
        completed_stops = sum(1 for pit_lap in plan.pit_laps if lap > pit_lap)
        pit_stop = lap in plan.pit_laps
        stint = completed_stops + 1
        last_pit = max((pit_lap for pit_lap in plan.pit_laps if lap > pit_lap), default=0)
        tyre_age = lap - last_pit
        compound = plan.start_compound if completed_stops % 2 == 0 else plan.alternate_compound
        return stint, compound, tyre_age, pit_stop

    def _base_lap_time(self, event: RaceEvent, driver: Driver) -> float:
        race_score = self.pace_model.driver_score(driver, event, mode="race")
        track_base = {
            "high_speed": 91.6,
            "street": 94.2,
            "street_low_speed": 95.1,
            "low_speed": 93.4,
            "balanced": 92.5,
            "power": 92.2,
            "technical": 93.1,
        }.get(event.track_type, 92.8)
        return track_base - race_score * self.config.race_score_lap_time_scale

    def _launch_time_bonus(self, event: RaceEvent, driver: Driver, grid_position: int) -> float:
        launch_adjustment = self.pace_model.launch_adjustment(driver, event)
        if launch_adjustment == 0.0:
            return 0.0
        grid_factor = max(0.35, 1.0 - min(max(grid_position - 1, 0), 14) * 0.045)
        return launch_adjustment * self.config.launch_time_scale * grid_factor

    def _degradation_rate(self, event: RaceEvent, driver: Driver) -> float:
        track_deg = 0.028 + self._track_features(event).tyre_degradation_index * 0.041
        wet_offset = self._wet_probability(event) * 0.008
        codex_tyre_adjustment = self.pace_model.degradation_adjustment(driver, event) * 0.06
        return max(0.018, track_deg + wet_offset - driver.tyre_management * 0.006 - codex_tyre_adjustment)

    def _total_degradation(self, laps: int, plan: StrategyPlan) -> float:
        total = 0.0
        previous = 0
        for stop_lap in (*plan.pit_laps, laps):
            stint_length = max(0, stop_lap - previous)
            total += plan.degradation_rate * stint_length * (stint_length + 1) / 2
            previous = stop_lap
        return total

    def _pit_loss(self, event: RaceEvent) -> float:
        return self._track_features(event).pit_loss_seconds

    def _track_position_penalty(self, event: RaceEvent) -> float:
        return 0.18 + self._track_features(event).track_position_value * 0.55

    def _wet_probability(self, event: RaceEvent) -> float:
        return min(1.0, max(0.0, event.weather_prior.get("wet_probability", 0.0)))

    def _wet_race_penalty(self, event: RaceEvent, driver: Driver, wet_race: bool) -> float:
        if not wet_race:
            return 0.0
        wet_laps = self._sample_wet_laps(event, wet_race)
        return self._wet_lap_penalty(driver, wet_race=True, lap=wet_laps, total_laps=event.laps) * wet_laps

    def _sample_wet_laps(self, event: RaceEvent, wet_race: bool) -> int:
        if not wet_race:
            return 0
        return max(4, round(event.laps * self.random.uniform(0.18, 0.65)))

    @staticmethod
    def _wet_lap_penalty(driver: Driver, wet_race: bool, lap: int, total_laps: int) -> float:
        if not wet_race:
            return 0.0
        intensity = min(1.0, max(0.25, lap / max(1, total_laps)))
        return 1.45 * intensity - driver.wet_skill * 0.42

    def _sample_safety_car_lap(self, event: RaceEvent, wet_race: bool) -> int | None:
        probability = self._track_features(event).safety_car_probability + (0.08 if wet_race else 0.0)
        if self.random.random() >= min(0.65, probability):
            return None
        return self.random.randint(max(4, event.laps // 5), max(5, event.laps - 5))

    @staticmethod
    def _representative_safety_car_lap(event: RaceEvent, wet_race: bool) -> int | None:
        if event.track_type in {"street", "street_low_speed"}:
            return max(4, round(event.laps * 0.42))
        if wet_race:
            return max(4, round(event.laps * 0.35))
        return None

    def _track_features(self, event: RaceEvent) -> TrackFeatureVector:
        cached = self._track_feature_cache.get(event.event_id)
        if cached is not None:
            return cached
        features = track_feature_vector(event)
        self._track_feature_cache[event.event_id] = features
        return features

    @staticmethod
    def _known_qualifying_positions(event: RaceEvent) -> dict[str, int]:
        refs = event.feature_refs if isinstance(event.feature_refs, dict) else {}
        payload = refs.get("fastf1_qualifying_order")
        if not isinstance(payload, dict):
            return {}
        rows = payload.get("driver_positions")
        if not isinstance(rows, list):
            return {}
        output: dict[str, int] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            driver_id = str(row.get("driver_id") or "")
            try:
                position = int(row.get("qualifying_position") or 0)
            except (TypeError, ValueError):
                continue
            if driver_id and position > 0:
                output[driver_id] = position
        return output
