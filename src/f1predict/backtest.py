"""Point-in-time diagnostic replay harness."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from f1predict.domain import parse_dt
from f1predict.market import after_cutoff_market_count, event_market_snapshots
from f1predict.market_outcomes import SUPPORTED_MARKET_TYPES
from f1predict.models.simulator import POINTS
from f1predict.pipeline import PredictionPipeline


@dataclass(frozen=True)
class BacktestRow:
    event_id: str
    top_pick: str
    actual_winner: str | None
    hit: bool | None
    model_probability: float
    actual_winner_rank: int | None
    full_field_driver_count: int
    mean_abs_rank_error: float | None
    mean_abs_points_error: float | None
    podium_overlap_rate: float | None
    points_overlap_rate: float | None
    market_probability: float | None
    edge_after_cost: float | None
    evidence_count: int
    feature_adjustment_count: int
    market_snapshot_count: int
    market_snapshot_after_cutoff_count: int
    market_edge_count: int


class Backtester:
    def __init__(self, pipeline: PredictionPipeline | None = None) -> None:
        self.pipeline = pipeline or PredictionPipeline(iterations=1500)

    def run_replay(self) -> list[BacktestRow]:
        season = self.pipeline.data_source.load()
        events = [event.__dict__ for event in season.events]
        rows: list[BacktestRow] = []
        for event in events:
            if not event.get("completed"):
                continue
            cutoff = f"{event['date']}T00:00:00+00:00"
            cutoff_dt = parse_dt(cutoff)
            report = self.pipeline.predict_event(str(event["event_id"]), knowledge_cutoff=cutoff)
            top = report.race_probabilities[0]
            actual = event.get("actual_result", [None])[0] if event.get("actual_result") else None
            full_field = self._full_field_metrics(
                event.get("actual_result", []),
                report.race_probabilities,
            )
            edge = next((item for item in report.market_edges if item.outcome_id == top.driver_id), None)
            market_snapshot_count = sum(
                len(event_market_snapshots(season.markets, str(event["event_id"]), cutoff_dt, market_type=market_type))
                for market_type in SUPPORTED_MARKET_TYPES
            )
            market_snapshot_after_cutoff_count = sum(
                after_cutoff_market_count(
                    season.markets,
                    str(event["event_id"]),
                    cutoff_dt,
                    market_type=market_type,
                )
                for market_type in SUPPORTED_MARKET_TYPES
            )
            rows.append(
                BacktestRow(
                    event_id=str(event["event_id"]),
                    top_pick=top.driver_id,
                    actual_winner=str(actual) if actual else None,
                    hit=(top.driver_id == actual) if actual else None,
                    model_probability=round(top.win, 4),
                    actual_winner_rank=full_field["actual_winner_rank"],
                    full_field_driver_count=full_field["full_field_driver_count"],
                    mean_abs_rank_error=full_field["mean_abs_rank_error"],
                    mean_abs_points_error=full_field["mean_abs_points_error"],
                    podium_overlap_rate=full_field["podium_overlap_rate"],
                    points_overlap_rate=full_field["points_overlap_rate"],
                    market_probability=edge.market_probability if edge else None,
                    edge_after_cost=(
                        edge.conservative_edge_after_cost
                        if edge and edge.conservative_edge_after_cost is not None
                        else edge.edge_after_cost if edge else None
                    ),
                    evidence_count=len(report.evidence),
                    feature_adjustment_count=len(report.feature_adjustments),
                    market_snapshot_count=market_snapshot_count,
                    market_snapshot_after_cutoff_count=market_snapshot_after_cutoff_count,
                    market_edge_count=len(report.market_edges),
                )
            )
        return rows

    def run_seed_replay(self) -> list[BacktestRow]:
        return self.run_replay()

    @staticmethod
    def _full_field_metrics(actual_result: object, probabilities: list[object]) -> dict[str, object]:
        if not isinstance(actual_result, list) or not actual_result:
            return {
                "actual_winner_rank": None,
                "full_field_driver_count": 0,
                "mean_abs_rank_error": None,
                "mean_abs_points_error": None,
                "podium_overlap_rate": None,
                "points_overlap_rate": None,
            }
        actual_order = [str(driver_id) for driver_id in actual_result if driver_id]
        predicted_order = [str(row.driver_id) for row in probabilities]
        actual_rank = {driver_id: index for index, driver_id in enumerate(actual_order, start=1)}
        predicted_rank = {driver_id: index for index, driver_id in enumerate(predicted_order, start=1)}
        driver_ids = [driver_id for driver_id in actual_order if driver_id in predicted_rank]
        if not driver_ids:
            return {
                "actual_winner_rank": None,
                "full_field_driver_count": 0,
                "mean_abs_rank_error": None,
                "mean_abs_points_error": None,
                "podium_overlap_rate": None,
                "points_overlap_rate": None,
            }
        actual_points = {
            driver_id: float(POINTS[index - 1]) if index <= len(POINTS) else 0.0
            for driver_id, index in actual_rank.items()
        }
        predicted_points = {
            str(row.driver_id): float(row.expected_points)
            for row in probabilities
        }
        podium_actual = set(actual_order[:3])
        podium_predicted = set(predicted_order[:3])
        points_actual = set(actual_order[:10])
        points_predicted = set(predicted_order[:10])
        return {
            "actual_winner_rank": predicted_rank.get(actual_order[0]) if actual_order else None,
            "full_field_driver_count": len(driver_ids),
            "mean_abs_rank_error": round(
                mean(abs(predicted_rank[driver_id] - actual_rank[driver_id]) for driver_id in driver_ids),
                4,
            ),
            "mean_abs_points_error": round(
                mean(abs(predicted_points.get(driver_id, 0.0) - actual_points.get(driver_id, 0.0)) for driver_id in driver_ids),
                4,
            ),
            "podium_overlap_rate": round(len(podium_actual & podium_predicted) / 3, 4),
            "points_overlap_rate": round(len(points_actual & points_predicted) / 10, 4),
        }
