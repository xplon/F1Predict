"""Smoke test for source-backed red-flag tail diagnostics."""

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
    team = Team("team_a", "Team A", 0.55, 0.96, 0.82)
    driver = Driver("driver_a", "Driver A", "team_a", 0.55, 0.55, 0.82, 0.55, 0.55)
    event = RaceEvent(
        event_id="test_gp",
        name="Test Grand Prix",
        round_number=1,
        date="2026-01-01",
        track_type="street",
        laps=60,
        completed=False,
        weather_prior={"wet_probability": 0.0, "safety_car_probability": 0.25},
        track_map=[],
    )
    season = SeasonState(2026, {"team_a": team}, {"driver_a": driver}, [event], [])
    belief = BeliefState(
        state_id="test_state",
        event_id="test_gp",
        knowledge_cutoff=None,
        generated_at="2026-01-01T00:00:00+00:00",
        track_state=EntityState("test_gp", {}),
        car_states={"team_a": EntityState("team_a", {})},
        driver_states={"driver_a": EntityState("driver_a", {})},
        team_ops_states={"team_a": EntityState("team_a", {})},
        event_risk_state=EntityState(
            "test_gp",
            {
                "wet_probability": StateFactor(0.0, 0.10, ["source"]),
                "safety_car_probability": StateFactor(0.44, 0.10, ["source"]),
                "red_flag_probability": StateFactor(0.40, 0.10, ["source"]),
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

    disabled = SingleRaceSimulator(
        season,
        pace,
        iterations=1,
        seed=1,
        config=SimulatorConfig(red_flag_probability_scale=0.0),
    )
    assert disabled._red_flag_probability(event, wet_race=False) == 0.0

    enabled = SingleRaceSimulator(
        season,
        pace,
        iterations=1,
        seed=1,
        config=SimulatorConfig(red_flag_probability_scale=1.0),
    )
    assert enabled._red_flag_probability(event, wet_race=False) == 0.40
    assert enabled._sample_red_flag_lap(event, wet_race=False) is not None

    plan = enabled._strategy_plan(event, driver, red_flag_lap=30)
    assert plan.red_flag_adjusted
    assert 30 in plan.pit_laps

    replay_rows = enabled.sample_replay(event, max_drivers=1)
    assert replay_rows
    assert "red_flag_lap" in replay_rows[0]


if __name__ == "__main__":
    main()
