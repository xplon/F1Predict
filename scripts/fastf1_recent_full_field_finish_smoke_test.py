"""Smoke test for recent full-field finish form features.

The feature must be source-driven and entity-agnostic: it may use cutoff-valid
FastF1 race classifications, but it must not encode user-provided team or
driver ordering as a manual patch.
"""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from f1predict.belief_state import BeliefStateBuilder  # noqa: E402
from f1predict.domain import parse_dt  # noqa: E402
from f1predict.explanation_localization import localized_mechanism_zh  # noqa: E402
from f1predict.features.provider import ProcessedFeatureProvider  # noqa: E402
from f1predict.pipeline import PredictionPipeline  # noqa: E402


def main() -> None:
    pipeline = PredictionPipeline(
        iterations=30,
        feature_provider=ProcessedFeatureProvider(enable_recent_full_field_finish_form=True),
    )
    cutoff = pipeline._normalize_cutoff(parse_dt("2026-07-05T00:00:00+00:00"))
    season = pipeline.data_source.load()
    event = next(item for item in season.events if item.event_id == "british_gp")
    default_features = PredictionPipeline(iterations=1).feature_provider.load_event_features(season, event, cutoff)
    if any(feature.feature_id.startswith("fastf1-form-full-field-finish:") for feature in default_features):
        raise AssertionError("Recent full-field finish candidate must stay disabled on the default feature provider")

    features = pipeline.feature_provider.load_event_features(season, event, cutoff)

    recent_finish = [
        feature
        for feature in features
        if feature.feature_id.startswith("fastf1-form-full-field-finish:")
    ]
    if not recent_finish:
        raise AssertionError("Recent full-field finish features should be generated from FastF1 race classifications")

    team_features = {
        feature.target_id: feature
        for feature in recent_finish
        if feature.target_type == "team" and feature.metric == "race_pace"
    }
    driver_features = [
        feature
        for feature in recent_finish
        if feature.target_type == "driver"
    ]
    if driver_features:
        raise AssertionError("Recent full-field finish features should update team/car state, not driver race pace")
    if len(team_features) < 8:
        raise AssertionError("Recent full-field finish features should cover most teams")

    if not (
        team_features["ferrari"].value > 0.0
        and team_features["racing_bulls"].value > 0.0
        and team_features["aston_martin"].value < 0.0
        and team_features["cadillac"].value < 0.0
    ):
        raise AssertionError("Recent full-field team finishes should separate front/midfield and backfield form")

    for feature in (team_features["racing_bulls"], team_features["aston_martin"], team_features["ferrari"]):
        if "full-field race classifications" not in feature.explanation or "points-only scoring" not in feature.explanation:
            raise AssertionError("Feature explanation must expose full-field classification and points-censoring rationale")
        localized = localized_mechanism_zh(
            feature.explanation,
            feature_id=feature.feature_id,
            source=feature.source,
            metric=feature.metric,
        )
        if "全场正赛排名" not in localized or "第 11 到第 22 名" not in localized:
            raise AssertionError("Localized explanation must expose the full-field finish rationale")

    belief_state = BeliefStateBuilder().build(
        season,
        event,
        [],
        features,
        knowledge_cutoff=cutoff.isoformat(),
    )
    ledger_rows = [
        row
        for row in belief_state.update_ledger
        if row.claim_id.startswith("fastf1-form-full-field-finish:")
    ]
    if not ledger_rows:
        raise AssertionError("Recent full-field finish features must enter the BeliefState update ledger")
    if not any(row.target_type == "team" and row.target_id == "racing_bulls" for row in ledger_rows):
        raise AssertionError("Team-level recent full-field finish updates should be traceable in the ledger")
    if not all("race_pace_score" in row.affected_model_surfaces for row in ledger_rows):
        raise AssertionError("Recent full-field finish updates should affect the race-pace model surface")

    print("fastf1 recent full-field finish form ok")


if __name__ == "__main__":
    main()
