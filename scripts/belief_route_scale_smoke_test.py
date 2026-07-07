"""Smoke-test per-route BeliefState scale controls."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from f1predict.belief_state import BeliefStateBuilder  # noqa: E402
from f1predict.domain import Driver, FeatureAdjustment, RaceEvent, SeasonState, Team  # noqa: E402
from f1predict.models.pace import PaceModel  # noqa: E402
from f1predict.models.simulator import SimulatorConfig  # noqa: E402


def main() -> None:
    season = SeasonState(
        season=2026,
        teams={
            "team_a": Team("team_a", "Team A", base_strength=0.0, reliability=0.94, strategy=0.5),
            "team_b": Team("team_b", "Team B", base_strength=0.0, reliability=0.94, strategy=0.5),
        },
        drivers={
            "driver_a": Driver("driver_a", "Driver A", "team_a", 0.5, 0.5, 0.5, 0.5, 0.5),
            "driver_b": Driver("driver_b", "Driver B", "team_b", 0.5, 0.5, 0.5, 0.5, 0.5),
        },
        events=[],
        markets=[],
    )
    event = RaceEvent(
        event_id="route_gp",
        name="Route GP",
        round_number=1,
        date="2026-01-01",
        track_type="high_speed",
        laps=50,
        completed=False,
        weather_prior={"wet_probability": 0.0},
        track_map=[],
    )
    features = [
        FeatureAdjustment(
            feature_id="route-smoke:team_a:race_pace",
            event_id=event.event_id,
            source="route-smoke",
            target_type="team",
            target_id="team_a",
            metric="race_pace",
            value=0.08,
            confidence=0.90,
            observed_at="2026-01-01T00:00:00+00:00",
            explanation="Synthetic car race pace signal.",
        ),
        FeatureAdjustment(
            feature_id="route-smoke:team_a:qualifying_pace",
            event_id=event.event_id,
            source="route-smoke",
            target_type="team",
            target_id="team_a",
            metric="qualifying_pace",
            value=0.08,
            confidence=0.90,
            observed_at="2026-01-01T00:00:00+00:00",
            explanation="Synthetic car qualifying pace signal.",
        ),
    ]
    belief_state = BeliefStateBuilder().build(season, event, [], features)
    default_pace = PaceModel(season, [], [], belief_state=belief_state)
    damped_config = SimulatorConfig(belief_car_race_pace_route_scale=0.50)
    damped_pace = PaceModel(
        season,
        [],
        [],
        belief_state=belief_state,
        belief_component_scales=damped_config.belief_component_scales(),
    )
    driver = season.drivers["driver_a"]
    default_race = default_pace.score_breakdown(driver, event, mode="race")
    damped_race = damped_pace.score_breakdown(driver, event, mode="race")
    default_qualifying = default_pace.score_breakdown(driver, event, mode="qualifying")
    damped_qualifying = damped_pace.score_breakdown(driver, event, mode="qualifying")

    if not damped_race["belief_car_race_pace"] < default_race["belief_car_race_pace"]:
        raise AssertionError("Car race-pace route damping should reduce only the race route component")
    if damped_race["belief_car_overall"] != default_race["belief_car_overall"]:
        raise AssertionError("Car race-pace route damping should not change car overall pace")
    if damped_qualifying["belief_car_qualifying_pace"] != default_qualifying["belief_car_qualifying_pace"]:
        raise AssertionError("Car race-pace route damping should not change qualifying-pace route")
    if damped_qualifying["belief_car_race_pace_carryover"] != default_qualifying["belief_car_race_pace_carryover"]:
        raise AssertionError("Car race-pace route damping should not change race-pace carryover route")
    print("belief route scale smoke ok")


if __name__ == "__main__":
    main()
