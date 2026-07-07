"""Smoke-test correlated race-result feature saturation in BeliefState."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from f1predict.belief_state import BeliefStateBuilder  # noqa: E402
from f1predict.domain import Driver, FeatureAdjustment, RaceEvent, SeasonState, Team  # noqa: E402


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
        event_id="smoke_gp",
        name="Smoke GP",
        round_number=1,
        date="2026-01-01",
        track_type="high_speed",
        laps=50,
        completed=False,
        weather_prior={"wet_probability": 0.0},
        track_map=[],
    )
    correlated_sources = [
        "f1-official-standings:2026:smoke",
        "fastf1-form:2026:smoke",
        "fastf1-season-form:2026:smoke",
        "fastf1-team-strength-reestimate:2026:smoke",
        "fastf1-finish-position-reestimate:2026:smoke",
    ]
    features = [
        FeatureAdjustment(
            feature_id=f"{source}:team_a:race_pace",
            event_id=event.event_id,
            source=source,
            target_type="team",
            target_id="team_a",
            metric="race_pace",
            value=0.10,
            confidence=0.90,
            observed_at="2026-01-01T00:00:00+00:00",
            explanation="Synthetic correlated result-derived team race pace signal.",
        )
        for source in correlated_sources
    ]
    features.append(
        FeatureAdjustment(
            feature_id="fastf1-session-laps:2026:smoke:team_a:race_pace",
            event_id=event.event_id,
            source="fastf1-session-laps:2026:smoke",
            target_type="team",
            target_id="team_a",
            metric="race_pace",
            value=0.02,
            confidence=0.90,
            observed_at="2026-01-01T00:00:00+00:00",
            explanation="Synthetic same-event timing signal.",
        )
    )
    state = BeliefStateBuilder().build(season, event, [], features)
    race_pace = state.car_value("team_a", "race_pace")
    if race_pace >= 0.30:
        raise AssertionError(f"Correlated result-derived updates were not saturated enough: {race_pace}")
    saturated = [
        row
        for row in state.update_ledger
        if row.target_id == "team_a"
        and row.factor == "race_pace"
        and "correlated_result_family_saturation" in row.quality_reasons
    ]
    if not saturated:
        raise AssertionError("Expected at least one saturated correlated result-derived update")
    timing_rows = [
        row
        for row in state.update_ledger
        if row.claim_id.startswith("fastf1-session-laps") and row.target_id == "team_a"
    ]
    if not timing_rows:
        raise AssertionError("Same-event timing signal should still update the state")
    if any("correlated_result_family_saturation" in row.quality_reasons for row in timing_rows):
        raise AssertionError("Same-event timing signal should not be treated as correlated result-derived history")
    print("correlated result saturation smoke ok")


if __name__ == "__main__":
    main()
