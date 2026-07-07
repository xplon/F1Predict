"""Smoke test for post-event review diagnostics."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from f1predict.post_event_review import PostEventReviewBuilder  # noqa: E402


def main() -> None:
    report = PostEventReviewBuilder().build("british_gp")
    assert report.status == "diagnostic_only"
    assert report.prediction_status == "diagnostic_only"
    assert report.prediction_run_id.startswith("british_gp_20260705T000000")
    assert report.result_captured_after_prediction_cutoff is True
    assert report.actual_winner == "leclerc"
    assert report.predicted_winner == "russell"
    assert report.winner_hit is False
    assert report.actual_winner_predicted_rank == 4
    assert report.predicted_winner_actual_position == 2
    assert report.podium_overlap_rate == 0.6667
    assert report.points_overlap_rate == 0.7
    assert "result_snapshot_after_prediction_cutoff_for_evaluation_only" in report.warnings
    by_driver = {row.driver_id: row for row in report.driver_reviews}
    assert by_driver["lindblad"].result_driver_id == "arvid_lindblad"
    assert by_driver["verstappen"].result_driver_id == "max_verstappen"


if __name__ == "__main__":
    main()
