"""Smoke test for FastF1 session-derived team setup-quality routing."""

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
        weather_prior={},
        track_map=[],
    )
    season = SeasonState(2026, teams, drivers, [event], [])
    provider = ProcessedFeatureProvider()

    practice_features = provider._fastf1_practice_lap_adjustments(
        season,
        event,
        _practice_summary(event),
        "2026-06-30T12:00:00+00:00",
        driver_lookup={},
        by_number={
            "11": "driver_a1",
            "12": "driver_a2",
            "21": "driver_b1",
            "22": "driver_b2",
        },
    )
    qualifying_features = provider._fastf1_qualifying_lap_adjustments(
        season,
        event,
        _qualifying_summary(event),
        "2026-06-30T15:00:00+00:00",
        driver_lookup={},
        by_number={
            "11": "driver_a1",
            "12": "driver_a2",
            "21": "driver_b1",
            "22": "driver_b2",
        },
    )
    setup_features = [
        feature
        for feature in (*practice_features, *qualifying_features)
        if feature.target_type == "team" and feature.metric == "setup_quality"
    ]
    if len(setup_features) != 4:
        raise AssertionError("Practice and qualifying should each produce team setup-quality features")
    values_by_id = {feature.feature_id: feature.value for feature in setup_features}
    if not all(value != 0.0 for value in values_by_id.values()):
        raise AssertionError("Setup-quality features should carry non-zero direction from session timing")
    team_totals = {
        team_id: sum(feature.value for feature in setup_features if feature.target_id == team_id)
        for team_id in teams
    }
    if not (team_totals["team_a"] > 0.0 > team_totals["team_b"]):
        raise AssertionError("Faster same-weekend team timing should produce positive setup quality")

    builder = BeliefStateBuilder()
    baseline = builder.build(season, event, [], [], [], knowledge_cutoff="2026-07-01T00:00:00+00:00")
    belief = builder.build(
        season,
        event,
        [],
        [*practice_features, *qualifying_features],
        [],
        knowledge_cutoff="2026-07-01T00:00:00+00:00",
    )
    if belief.team_ops_value("team_a", "setup_quality") <= baseline.team_ops_value("team_a", "setup_quality"):
        raise AssertionError("Team setup features must update team_ops.setup_quality for the faster team")
    if belief.team_ops_value("team_b", "setup_quality") >= baseline.team_ops_value("team_b", "setup_quality"):
        raise AssertionError("Team setup features must update team_ops.setup_quality for the slower team")
    setup_updates = [
        row
        for row in belief.update_ledger
        if row.target_type == "team" and row.factor == "setup_quality"
    ]
    if len(setup_updates) != 4:
        raise AssertionError("Setup-quality updates must appear in the traceable state update ledger")
    if not all("race_window_pressure" in row.affected_model_surfaces for row in setup_updates):
        raise AssertionError("Setup-quality updates must expose the race-window route")

    baseline_pace = PaceModel(season, [], [], belief_state=baseline)
    updated_pace = PaceModel(season, [], [*practice_features, *qualifying_features], belief_state=belief)
    driver_a = drivers["driver_a1"]
    if updated_pace.driver_score(driver_a, event, mode="race") <= baseline_pace.driver_score(driver_a, event, mode="race"):
        raise AssertionError("Positive setup-quality state must affect race score")
    if updated_pace.driver_score(driver_a, event, mode="qualifying") <= baseline_pace.driver_score(
        driver_a,
        event,
        mode="qualifying",
    ):
        raise AssertionError("Positive setup-quality state must affect qualifying score")


def _practice_summary(event: RaceEvent) -> NormalizedSessionLapSummary:
    return NormalizedSessionLapSummary(
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
            _practice_row("11", 91.0, 0.05),
            _practice_row("12", 91.2, 0.07),
            _practice_row("21", 92.0, 0.35),
            _practice_row("22", 92.1, 0.37),
        ],
        weather_summary={},
    )


def _qualifying_summary(event: RaceEvent) -> NormalizedSessionLapSummary:
    return NormalizedSessionLapSummary(
        year=2026,
        event_name=event.name,
        round_number=1,
        session_name="Qualifying",
        session_key="qualifying",
        session_date="2026-06-30T15:00:00+00:00",
        captured_at="2026-06-30T15:10:00+00:00",
        source="fastf1",
        path="memory://contract-qualifying-laps",
        driver_stats=[
            _qualifying_row("11", 89.0),
            _qualifying_row("12", 89.1),
            _qualifying_row("21", 90.0),
            _qualifying_row("22", 90.2),
        ],
        weather_summary={},
    )


def _practice_row(driver_number: str, long_run_seconds: float, tyre_deg: float) -> dict[str, float | int | str]:
    return {
        "driver_number": driver_number,
        "long_run_proxy_seconds": long_run_seconds,
        "long_run_lap_count": 6,
        "clean_lap_count": 6,
        "tyre_deg_proxy_seconds_per_lap": tyre_deg,
    }


def _qualifying_row(driver_number: str, fastest_lap_seconds: float) -> dict[str, float | int | str]:
    return {
        "driver_number": driver_number,
        "fastest_lap_seconds": fastest_lap_seconds,
        "clean_lap_count": 3,
    }


if __name__ == "__main__":
    main()
