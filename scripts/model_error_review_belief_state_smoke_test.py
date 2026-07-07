"""Smoke-test BeliefState-backed model error review diagnostics."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from f1predict.belief_state import BeliefState, EntityState, StateFactor  # noqa: E402
from f1predict.domain import Driver, DriverRaceProbability, RaceEvent, SeasonState, Team  # noqa: E402
from f1predict.model_error_review import ModelErrorReviewBuilder  # noqa: E402
from f1predict.models.pace import PaceModel  # noqa: E402


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
    belief = BeliefState(
        state_id="belief_smoke",
        event_id=event.event_id,
        knowledge_cutoff=None,
        generated_at="2026-01-01T00:00:00+00:00",
        track_state=EntityState(event.event_id, {}),
        car_states={
            "team_a": EntityState("team_a", {"race_pace": StateFactor(0.2), "qualifying_pace": StateFactor(0.1)}),
            "team_b": EntityState("team_b", {"race_pace": StateFactor(-0.1), "qualifying_pace": StateFactor(-0.1)}),
        },
        driver_states={
            "driver_a": EntityState("driver_a", {"race_pace": StateFactor(0.05), "qualifying_ceiling": StateFactor(0.02)}),
            "driver_b": EntityState("driver_b", {"race_pace": StateFactor(0.0), "qualifying_ceiling": StateFactor(0.0)}),
        },
        team_ops_states={"team_a": EntityState("team_a", {}), "team_b": EntityState("team_b", {})},
        event_risk_state=EntityState(event.event_id, {"wet_probability": StateFactor(0.0)}),
        raw_sources=[],
        extracted_units=[],
        normalized_claims=[],
        quality_profiles=[],
        update_ledger=[],
        unsupported_static_priors=[],
        source_fingerprint="source",
        update_fingerprint="update",
    )
    rehydrated = BeliefState.from_dict(belief.to_dict())
    pace = PaceModel(season, [], [], belief_state=rehydrated)
    race_a = pace.score_breakdown(season.drivers["driver_a"], event, mode="race")
    race_b = pace.score_breakdown(season.drivers["driver_b"], event, mode="race")
    if race_a["total"] <= race_b["total"]:
        raise AssertionError("BeliefState-backed race score should favor driver_a")
    if "belief_car_race_pace" not in race_a:
        raise AssertionError("BeliefState-backed breakdown should expose belief components")

    probabilities = [
        DriverRaceProbability("driver_a", win=0.7, podium=0.9, points=1.0, expected_points=20.0, average_finish=1.5),
        DriverRaceProbability("driver_b", win=0.3, podium=0.6, points=0.9, expected_points=12.0, average_finish=3.0),
    ]
    rows = ModelErrorReviewBuilder._candidate_rows(
        season,
        probabilities,
        pace,
        event,
        "driver_b",
    )
    row_a = next(row for row in rows if row["driver_id"] == "driver_a")
    row_b = next(row for row in rows if row["driver_id"] == "driver_b")
    if row_a["model_state_total"] <= row_b["model_state_total"]:
        raise AssertionError("Model error review should use BeliefState totals")
    codes = ModelErrorReviewBuilder._diagnosis_codes({}, row_a, row_b, probabilities[0], probabilities[1])
    if "belief_state_favored_top_pick" not in codes:
        raise AssertionError("BeliefState gap should produce a belief-state diagnosis code")
    print("model error review BeliefState smoke ok")


if __name__ == "__main__":
    main()
