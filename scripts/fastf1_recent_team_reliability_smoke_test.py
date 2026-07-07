"""Smoke test for recent team reliability candidate features."""

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
    cutoff_text = "2026-07-05T00:00:00+00:00"
    default_pipeline = PredictionPipeline(iterations=1)
    cutoff = default_pipeline._normalize_cutoff(parse_dt(cutoff_text))
    season = default_pipeline.data_source.load()
    event = next(item for item in season.events if item.event_id == "british_gp")

    default_features = default_pipeline.feature_provider.load_event_features(season, event, cutoff)
    if any(feature.feature_id.startswith("fastf1-form-team-reliability:") for feature in default_features):
        raise AssertionError("Recent team reliability candidate must stay disabled by default")

    candidate_provider = ProcessedFeatureProvider(enable_recent_team_reliability_form=True)
    candidate_features = candidate_provider.load_event_features(season, event, cutoff)
    reliability_features = [
        feature
        for feature in candidate_features
        if feature.feature_id.startswith("fastf1-form-team-reliability:")
    ]
    if not reliability_features:
        raise AssertionError("Recent team reliability features should be generated from FastF1 classifications")
    if not all(feature.target_type == "team" and feature.metric == "reliability" for feature in reliability_features):
        raise AssertionError("Recent team reliability features must update team/car reliability only")
    if not any(feature.value < 0 for feature in reliability_features):
        raise AssertionError("At least one recent team reliability row should express elevated DNF risk")

    for feature in reliability_features:
        if "team non-finished rate" not in feature.explanation or "DNF sampling" not in feature.explanation:
            raise AssertionError("Feature explanation must expose team non-finished rate and DNF-sampling route")
        localized = localized_mechanism_zh(
            feature.explanation,
            feature_id=feature.feature_id,
            source=feature.source,
            metric=feature.metric,
        )
        if "车队未完赛率" not in localized or "退赛采样" not in localized:
            raise AssertionError("Localized explanation must expose reliability evidence and DNF route")

    belief_state = BeliefStateBuilder().build(
        season,
        event,
        [],
        candidate_features,
        knowledge_cutoff=cutoff.isoformat(),
    )
    ledger_rows = [
        row
        for row in belief_state.update_ledger
        if row.claim_id.startswith("fastf1-form-team-reliability:")
    ]
    if not ledger_rows:
        raise AssertionError("Recent team reliability features must enter the BeliefState update ledger")
    if not all(row.target_type == "team" and row.factor == "reliability" for row in ledger_rows):
        raise AssertionError("Recent team reliability rows must map to car reliability state")
    if not all("dnf_sampler" in row.affected_model_surfaces for row in ledger_rows):
        raise AssertionError("Recent team reliability rows must affect the DNF sampler")

    print("fastf1 recent team reliability form ok")


if __name__ == "__main__":
    main()
