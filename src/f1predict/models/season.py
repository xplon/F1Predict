"""Season simulator built from repeated race simulations."""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from statistics import mean
from typing import Any

from f1predict.domain import RaceEvent, SeasonState
from f1predict.models.pace import PaceModel
from f1predict.models.simulator import POINTS
from f1predict.models.simulator import SimulatorConfig, SingleRaceSimulator


@dataclass(frozen=True)
class SeasonDriverForecast:
    driver_id: str
    driver_name: str
    team_id: str
    team_name: str
    base_points: float
    expected_remaining_points: float
    expected_final_points: float
    champion_probability: float
    top3_probability: float
    average_final_rank: float

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


@dataclass(frozen=True)
class SeasonForecastReport:
    generated_at: str
    knowledge_cutoff: str
    iterations: int
    status: str
    formal_ready: bool
    completed_events_counted: int
    remaining_events_simulated: int
    event_sampling_model: str
    base_points_source: str
    base_points_event_sources: dict[str, int]
    warnings: tuple[str, ...]
    rows: tuple[SeasonDriverForecast, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "knowledge_cutoff": self.knowledge_cutoff,
            "iterations": self.iterations,
            "status": self.status,
            "formal_ready": self.formal_ready,
            "completed_events_counted": self.completed_events_counted,
            "remaining_events_simulated": self.remaining_events_simulated,
            "event_sampling_model": self.event_sampling_model,
            "base_points_source": self.base_points_source,
            "base_points_event_sources": self.base_points_event_sources,
            "warnings": list(self.warnings),
            "rows": [row.to_dict() for row in self.rows],
        }


class SeasonForecastSimulator:
    """Cutoff-aware season points forecast using event-specific pace models."""

    def __init__(
        self,
        season_state: SeasonState,
        pace_models: dict[str, PaceModel],
        iterations: int = 2000,
        seed: int = 17,
        simulator_config: SimulatorConfig | None = None,
    ) -> None:
        self.season_state = season_state
        self.pace_models = pace_models
        self.iterations = iterations
        self.random = random.Random(seed)
        self.seed = seed
        self.simulator_config = simulator_config or SimulatorConfig()
        self._race_samplers: dict[str, SingleRaceSimulator] = {}

    def forecast(
        self,
        base_points: dict[str, float],
        remaining_events: list[RaceEvent],
    ) -> tuple[SeasonDriverForecast, ...]:
        driver_ids = list(self.season_state.drivers)
        titles = defaultdict(int)
        top3s = defaultdict(int)
        total_final_points = defaultdict(float)
        final_ranks = defaultdict(list)

        for _ in range(self.iterations):
            points = {driver_id: float(base_points.get(driver_id, 0.0)) for driver_id in driver_ids}
            for event in remaining_events:
                result = self._sample_event_order(event, driver_ids)
                for position, driver_id in enumerate(result[:10]):
                    points[driver_id] += POINTS[position]

            ranked = sorted(driver_ids, key=lambda driver_id: (-points[driver_id], driver_id))
            for rank, driver_id in enumerate(ranked, start=1):
                total_final_points[driver_id] += points[driver_id]
                final_ranks[driver_id].append(rank)
                if rank == 1:
                    titles[driver_id] += 1
                if rank <= 3:
                    top3s[driver_id] += 1

        rows: list[SeasonDriverForecast] = []
        denominator = float(self.iterations)
        for driver_id in driver_ids:
            driver = self.season_state.drivers[driver_id]
            team = self.season_state.teams[driver.team_id]
            expected_final = total_final_points[driver_id] / denominator
            base = float(base_points.get(driver_id, 0.0))
            rows.append(
                SeasonDriverForecast(
                    driver_id=driver_id,
                    driver_name=driver.name,
                    team_id=driver.team_id,
                    team_name=team.name,
                    base_points=round(base, 2),
                    expected_remaining_points=round(expected_final - base, 2),
                    expected_final_points=round(expected_final, 2),
                    champion_probability=round(titles[driver_id] / denominator, 4),
                    top3_probability=round(top3s[driver_id] / denominator, 4),
                    average_final_rank=round(mean(final_ranks[driver_id]), 2),
                )
            )

        return tuple(
            sorted(
                rows,
                key=lambda row: (
                    -row.expected_final_points,
                    -row.champion_probability,
                    row.average_final_rank,
                    row.driver_id,
                ),
            )
        )

    def _sample_event_order(self, event: RaceEvent, driver_ids: list[str]) -> list[str]:
        pace_model = self.pace_models.get(event.event_id)
        if pace_model is None:
            raise ValueError(f"No pace model for event_id={event.event_id}")
        sampler = self._race_samplers.get(event.event_id)
        if sampler is None:
            sampler = SingleRaceSimulator(
                self.season_state,
                pace_model,
                iterations=1,
                seed=self._event_seed(event.event_id),
                config=self.simulator_config,
            )
            self._race_samplers[event.event_id] = sampler
        return sampler.sample_order(event, driver_ids)

    def _event_seed(self, event_id: str) -> int:
        offset = sum((index + 1) * ord(char) for index, char in enumerate(event_id))
        return self.seed * 10_003 + offset


class SeasonSimulator:
    def __init__(
        self,
        season_state: SeasonState,
        pace_model: PaceModel,
        iterations: int = 2000,
        seed: int = 11,
    ) -> None:
        self.season_state = season_state
        self.pace_model = pace_model
        self.iterations = iterations
        self.random = random.Random(seed)

    def champion_probabilities(self, remaining_events: list[RaceEvent]) -> dict[str, float]:
        titles = defaultdict(int)
        driver_ids = list(self.season_state.drivers)
        base_points = {
            driver_id: driver.current_points
            for driver_id, driver in self.season_state.drivers.items()
        }

        for _ in range(self.iterations):
            points = dict(base_points)
            for event in remaining_events:
                result = self._sample_event_order(event, driver_ids)
                for pos, driver_id in enumerate(result[:10]):
                    points[driver_id] += POINTS[pos]
            champion = max(points, key=points.get)
            titles[champion] += 1

        return {
            driver_id: titles[driver_id] / float(self.iterations)
            for driver_id in driver_ids
        }

    def _sample_event_order(self, event: RaceEvent, driver_ids: list[str]) -> list[str]:
        sampled = []
        for driver_id in driver_ids:
            driver = self.season_state.drivers[driver_id]
            score = self.pace_model.driver_score(driver, event)
            score += self.random.gauss(0.0, 0.50)
            if self.random.random() > self.pace_model.reliability(driver):
                score -= 8.0
            sampled.append((score, driver_id))
        sampled.sort(reverse=True)
        return [driver_id for _, driver_id in sampled]
