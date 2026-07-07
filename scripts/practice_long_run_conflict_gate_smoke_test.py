"""Smoke-test practice long-run conflict quality gating.

The gate must be source-driven: it may use same-weekend FastF1 practice
long-run proxies and same-weekend qualifying classification, but it must not
branch on a specific team or driver identity.
"""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from f1predict.domain import parse_dt  # noqa: E402
from f1predict.explanation_localization import localized_mechanism_zh  # noqa: E402
from f1predict.pipeline import PredictionPipeline  # noqa: E402


def main() -> None:
    pipeline = PredictionPipeline(iterations=40)
    cutoff = pipeline._normalize_cutoff(parse_dt("2026-07-05T00:00:00+00:00"))
    season = pipeline.data_source.load()
    event = next(item for item in season.events if item.event_id == "british_gp")
    event = pipeline._event_with_cutoff_weather_forecast(event, cutoff)
    event = pipeline._event_with_fastf1_qualifying_order(season, event, cutoff)
    event = pipeline._event_with_track_feature_vector(event)
    features = pipeline.feature_provider.load_event_features(season, event, cutoff)

    qualifying_rows = (
        ((event.feature_refs or {}).get("fastf1_qualifying_order") or {}).get("driver_positions") or []
    )
    qualifying_positions = {
        str(row["driver_id"]): int(row["qualifying_position"])
        for row in qualifying_rows
        if row.get("driver_id") and row.get("qualifying_position")
    }
    if len(qualifying_positions) < 10:
        raise AssertionError("Smoke fixture needs same-event qualifying positions for conflict gating")

    practice_long_run = [
        feature
        for feature in features
        if feature.source.startswith("fastf1_session_laps:")
        and ":practice" in feature.source
        and feature.metric == "race_pace"
    ]
    if not practice_long_run:
        raise AssertionError("Smoke fixture needs FastF1 practice long-run race-pace features")

    damped = [
        feature
        for feature in practice_long_run
        if "Confidence was down-weighted" in feature.explanation
    ]
    if not damped:
        raise AssertionError("At least one contradictory practice long-run signal should be down-weighted")

    for feature in damped:
        if feature.target_type == "driver":
            position = qualifying_positions.get(feature.target_id)
            if position is None or position > 8 or feature.value >= 0.0:
                raise AssertionError("Driver practice dampening must be explained by front-half qualifying conflict")
            if feature.confidence >= 0.16:
                raise AssertionError("Dampened driver practice race-pace confidence should be visibly reduced")
        elif feature.target_type == "team":
            if feature.value >= 0.0:
                raise AssertionError("Team practice dampening should only reduce contradictory negative long-run signals")
            if feature.confidence >= 0.12:
                raise AssertionError("Dampened team practice race-pace confidence should be visibly reduced")
        else:
            raise AssertionError("Practice long-run conflict gate should only target driver or team features")

        localized = localized_mechanism_zh(
            feature.explanation,
            feature_id=feature.feature_id,
            source=feature.source,
            metric=feature.metric,
        )
        if "同周末 FastF1 圈速摘要" not in localized:
            raise AssertionError("FastF1 practice long-run explanations must not be mislabeled as OpenF1")
        if "降低置信度" not in localized:
            raise AssertionError("Localized explanation must disclose the conflict-driven confidence reduction")

    front_positive = [
        feature
        for feature in practice_long_run
        if feature.target_type == "driver"
        and feature.value > 0.0
        and qualifying_positions.get(feature.target_id, 99) <= 4
    ]
    if not front_positive:
        raise AssertionError("Smoke fixture needs a non-conflicting front-row/front-two-row positive long-run signal")
    if any("Confidence was down-weighted" in feature.explanation for feature in front_positive):
        raise AssertionError("Non-conflicting front qualifying plus positive long-run signals must not be dampened")

    print("practice long-run conflict gate ok")


if __name__ == "__main__":
    main()
