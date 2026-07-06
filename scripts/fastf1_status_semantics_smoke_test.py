"""Smoke test for FastF1 race-result status semantics.

FastF1/F1 result rows use "Lapped" for classified finishers who were one or
more laps down.  Treating that as a DNF corrupts reliability and
grid-to-finish conversion features.
"""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from f1predict.data_sources.augmented import CalendarAugmentedDataSource  # noqa: E402
from f1predict.domain import parse_dt  # noqa: E402
from f1predict.features.provider import ProcessedFeatureProvider  # noqa: E402


def main() -> None:
    provider = ProcessedFeatureProvider()
    assert provider._finished_status("Finished")
    assert provider._finished_status("Lapped")
    assert provider._finished_status("+1 Lap")
    assert provider._finished_status("+ 2 Laps")
    assert provider._finished_status("Classified")
    assert not provider._finished_status("Retired")
    assert not provider._finished_status("Did not start")
    assert not provider._finished_status("Disqualified")

    season = CalendarAugmentedDataSource().load()
    event = next(row for row in season.events if row.event_id == "british_gp")
    features = provider.load_event_features(
        season,
        event,
        parse_dt("2026-07-05T00:00:00+00:00"),
    )
    reliability = [
        feature
        for feature in features
        if feature.metric == "reliability"
        and feature.target_type == "driver"
        and feature.target_id == "bortoleto"
    ]
    assert not any(
        "previous 3 race" in feature.explanation
        for feature in reliability
    ), "Lapped recent finishes must not create a recent DNF reliability penalty"
    season_rows = [
        feature
        for feature in reliability
        if "across 8 cutoff-valid" in feature.explanation
    ]
    assert len(season_rows) == 1
    assert season_rows[0].value == -0.006
    assert "1 non-finished" in season_rows[0].explanation

    print("fastf1 status semantics smoke ok")


if __name__ == "__main__":
    main()
