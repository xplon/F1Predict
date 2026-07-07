"""Smoke test for FastF1 practice tyre-degradation team routing."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from f1predict.belief_state import BeliefStateBuilder  # noqa: E402
from f1predict.domain import Driver, RaceEvent, SeasonState, Team  # noqa: E402
from f1predict.features.provider import ProcessedFeatureProvider  # noqa: E402
from f1predict.models.pace import PaceModel  # noqa: E402
from f1predict.session_laps import NormalizedSessionLapSummary  # noqa: E402


def main() -> None:
    teams = {
        "team_a": Team("team_a", "Team A", 0.50, 0.96, 0.50),
        "team_b": Team("team_b", "Team B", 0.50, 0.96, 0.50),
    }
    drivers = {
        "driver_a1": Driver("driver_a1", "Driver A1", "team_a", 0.50, 0.50, 0.50, 0.50, 0.50),
        "driver_a2": Driver("driver_a2", "Driver A2", "team_a", 0.50, 0.50, 0.50, 0.50, 0.50),
        "driver_b1": Driver("driver_b1", "Driver B1", "team_b", 0.50, 0.50, 0.50, 0.50, 0.50),
        "driver_b2": Driver("driver_b2", "Driver B2", "team_b", 0.50, 0.50, 0.50, 0.50, 0.50),
    }
    event = RaceEvent(
        event_id="contract_gp",
        name="Contract Grand Prix",
        round_number=1,
        date="2026-07-01",
        track_type="balanced",
        laps=20,
        completed=False,
        weather_prior={"wet_probability": 0.10},
        track_map=[],
    )
    season = SeasonState(2026, teams, drivers, [event], [])
    summary = NormalizedSessionLapSummary(
        year=2026,
        event_name=event.name,
        round_number=1,
        session_name="Practice 2",
        session_key="practice2",
        session_date="2026-06-30T12:00:00+00:00",
        captured_at="2026-06-30T12:10:00+00:00",
        source="fastf1",
        path="memory://contract-practice2-laps",
        driver_stats=[
            _row("11", 91.0, 0.05),
            _row("12", 91.2, 0.07),
            _row("21", 91.1, 0.35),
            _row("22", 91.3, 0.37),
        ],
        weather_summary={},
    )
    provider = ProcessedFeatureProvider()
    features = provider._fastf1_practice_lap_adjustments(
        season,
        event,
        summary,
        "2026-06-30T12:00:00+00:00",
        driver_lookup={},
        by_number={
            "11": "driver_a1",
            "12": "driver_a2",
            "21": "driver_b1",
            "22": "driver_b2",
        },
    )
    driver_tyre = [
        feature
        for feature in features
        if feature.target_type == "driver" and feature.metric == "tyre_deg"
    ]
    team_tyre = [
        feature
        for feature in features
        if feature.target_type == "team" and feature.metric == "tyre_deg"
    ]
    if len(driver_tyre) != 4:
        raise AssertionError("Practice tyre degradation should still produce driver tyre-management features")
    if len(team_tyre) != 2:
        raise AssertionError("Practice tyre degradation should also produce team car tyre-window features")
    team_values = {feature.target_id: feature.value for feature in team_tyre}
    if not (team_values["team_a"] > 0.0 > team_values["team_b"]):
        raise AssertionError("Lower team degradation should be positive and higher degradation should be negative")

    builder = BeliefStateBuilder()
    baseline = builder.build(season, event, [], [], [], knowledge_cutoff="2026-07-01T00:00:00+00:00")
    belief = builder.build(season, event, [], features, [], knowledge_cutoff="2026-07-01T00:00:00+00:00")
    if belief.car_value("team_a", "tyre_deg") <= baseline.car_value("team_a", "tyre_deg"):
        raise AssertionError("Team tyre feature must update car.tyre_deg for the lower-degradation team")
    if belief.car_value("team_b", "tyre_deg") >= baseline.car_value("team_b", "tyre_deg"):
        raise AssertionError("Team tyre feature must update car.tyre_deg for the higher-degradation team")
    team_update_rows = [
        row
        for row in belief.update_ledger
        if row.target_type == "team" and row.factor == "tyre_deg"
    ]
    if len(team_update_rows) != 2:
        raise AssertionError("Team tyre updates must appear in the traceable state update ledger")
    if not all("stint_degradation" in row.affected_model_surfaces for row in team_update_rows):
        raise AssertionError("Team tyre updates must expose the stint degradation route")

    pace = PaceModel(season, [], features, belief_state=belief)
    pressure_a = pace.race_window_pressure(drivers["driver_a1"], event)
    pressure_b = pace.race_window_pressure(drivers["driver_b1"], event)
    if pressure_a >= pressure_b:
        raise AssertionError("Lower team degradation should reduce race-window pressure relative to higher degradation")


def _row(driver_number: str, long_run_seconds: float, tyre_deg: float) -> dict[str, float | int | str]:
    return {
        "driver_number": driver_number,
        "long_run_proxy_seconds": long_run_seconds,
        "long_run_lap_count": 6,
        "clean_lap_count": 6,
        "tyre_deg_proxy_seconds_per_lap": tyre_deg,
    }


if __name__ == "__main__":
    main()
