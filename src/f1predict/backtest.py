"""Point-in-time diagnostic replay harness."""

from __future__ import annotations

from dataclasses import dataclass

from f1predict.domain import parse_dt
from f1predict.market import after_cutoff_market_count, event_market_snapshots
from f1predict.market_outcomes import SUPPORTED_MARKET_TYPES
from f1predict.pipeline import PredictionPipeline


@dataclass(frozen=True)
class BacktestRow:
    event_id: str
    top_pick: str
    actual_winner: str | None
    hit: bool | None
    model_probability: float
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
