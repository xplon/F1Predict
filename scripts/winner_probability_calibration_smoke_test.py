"""Smoke test for generic winner-probability calibration."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from f1predict.domain import DriverRaceProbability  # noqa: E402
from f1predict.models.simulator import SimulatorConfig, SingleRaceSimulator  # noqa: E402


def main() -> None:
    simulator = SingleRaceSimulator.__new__(SingleRaceSimulator)
    simulator.config = SimulatorConfig(
        winner_probability_calibration_blend=0.40,
        winner_rank_prior_temperature=2.4,
    )
    rows = [
        DriverRaceProbability("front_runner", 0.55, 0.92, 0.98, 20.0, 2.0),
        DriverRaceProbability("second_car", 0.40, 0.88, 0.96, 18.0, 2.8),
        DriverRaceProbability("understated_front_row", 0.01, 0.30, 0.92, 10.0, 4.0),
        DriverRaceProbability("midfield", 0.04, 0.08, 0.45, 1.0, 11.0),
    ]

    calibrated = simulator._calibrated_winner_probabilities(rows)
    by_driver = {row.driver_id: row for row in calibrated}

    assert abs(sum(row.win for row in calibrated) - 1.0) < 1e-9
    assert by_driver["understated_front_row"].win > 0.01
    assert by_driver["front_runner"].win < 0.55
    assert by_driver["understated_front_row"].average_finish == 4.0
    assert by_driver["understated_front_row"].expected_points == 10.0

    disabled = SingleRaceSimulator.__new__(SingleRaceSimulator)
    disabled.config = SimulatorConfig(winner_probability_calibration_blend=0.0)
    assert disabled._calibrated_winner_probabilities(rows) is rows


if __name__ == "__main__":
    main()
