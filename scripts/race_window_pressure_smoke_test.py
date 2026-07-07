"""Smoke test for source-weighted team race-window pressure."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from f1predict.belief_state import BeliefState, EntityState, StateFactor  # noqa: E402
from f1predict.domain import Driver, RaceEvent, SeasonState, Team  # noqa: E402
from f1predict.models.pace import PaceModel  # noqa: E402
from f1predict.models.simulator import SimulatorConfig, SingleRaceSimulator  # noqa: E402


def main() -> None:
    team = Team("team_a", "Team A", 0.5, 0.94, 0.62)
    driver = Driver("driver_a", "Driver A", "team_a", 0.5, 0.5, 0.5, 0.5, 0.5)
    event = RaceEvent(
        event_id="test_gp",
        name="Test Grand Prix",
        round_number=1,
        date="2026-01-01",
        track_type="high_speed",
        laps=50,
        completed=False,
        weather_prior={"wet_probability": 0.2, "safety_car_probability": 0.25},
        track_map=[],
    )
    season = SeasonState(2026, {"team_a": team}, {"driver_a": driver}, [event], [])
    belief = BeliefState(
        state_id="test_state",
        event_id="test_gp",
        knowledge_cutoff=None,
        generated_at="2026-01-01T00:00:00+00:00",
        track_state=EntityState("test_gp", {}),
        car_states={
            "team_a": EntityState(
                "team_a",
                {
                    "tyre_deg": StateFactor(-0.20, 0.25, ["source"]),
                    "reliability": StateFactor(-0.10, 0.25, ["source"]),
                },
            )
        },
        driver_states={"driver_a": EntityState("driver_a", {})},
        team_ops_states={
            "team_a": EntityState(
                "team_a",
                {
                    "setup_quality": StateFactor(-0.15, 0.25, ["source"]),
                    "strategy_quality": StateFactor(-0.05, 0.25, ["source"]),
                    "race_execution": StateFactor(-0.04, 0.25, ["source"]),
                },
            )
        },
        event_risk_state=EntityState(
            "test_gp",
            {
                "wet_probability": StateFactor(0.20, 0.25, ["source"]),
                "tyre_degradation_index": StateFactor(0.50, 0.25, ["source"]),
            },
        ),
        raw_sources=[],
        extracted_units=[],
        normalized_claims=[],
        quality_profiles=[],
        update_ledger=[],
        unsupported_static_priors=[],
        source_fingerprint="source",
        update_fingerprint="update",
    )
    pace = PaceModel(season, [], [], belief_state=belief)
    pressure = pace.race_window_pressure(driver, event)
    assert pressure > 0.0

    disabled = SingleRaceSimulator(season, pace, iterations=1, seed=1, config=SimulatorConfig(team_race_window_noise_sd=0.0))
    assert disabled._sample_team_race_window_offsets(event, ["driver_a"])["team_a"] == 0.0

    enabled = SingleRaceSimulator(
        season,
        pace,
        iterations=1,
        seed=1,
        config=SimulatorConfig(
            team_race_window_noise_sd=0.0,
            team_race_window_pressure_scale=20.0,
            team_race_window_pressure_cap=4.0,
        ),
    )
    assert enabled._sample_team_race_window_offsets(event, ["driver_a"])["team_a"] > 0.0


if __name__ == "__main__":
    main()
