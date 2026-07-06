"""Replay probability calibration diagnostics."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from f1predict.domain import DriverRaceProbability, parse_dt, race_probabilities_by_expected_rank, utc_now
from f1predict.market import event_market_snapshots
from f1predict.pipeline import PredictionPipeline
from f1predict.replay import ReplayCoverageBuilder


EPSILON = 1e-6


@dataclass(frozen=True)
class CalibrationEventRow:
    event_id: str
    event_name: str
    cutoff: str
    top_pick: str
    actual_winner: str
    hit: bool
    top_pick_probability: float
    actual_winner_probability: float
    actual_winner_rank: int
    winner_brier_score: float
    actual_log_loss: float
    market_snapshot_count: int
    market_edge_count: int
    positive_edge_count: int
    paper_trade_candidate_count: int
    paper_trade_hit: bool | None
    best_edge_after_cost: float | None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


@dataclass(frozen=True)
class CalibrationBin:
    lower_bound: float
    upper_bound: float
    count: int
    average_confidence: float | None
    hit_rate: float | None
    calibration_error: float | None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


@dataclass(frozen=True)
class ReplayCalibrationReport:
    year: int
    as_of: str
    generated_at: str
    status: str
    formal_probability_claim_ready: bool
    scored_events: int
    market_scored_events: int
    summary: dict[str, Any]
    bins: tuple[CalibrationBin, ...]
    events: tuple[CalibrationEventRow, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "as_of": self.as_of,
            "generated_at": self.generated_at,
            "status": self.status,
            "formal_probability_claim_ready": self.formal_probability_claim_ready,
            "scored_events": self.scored_events,
            "market_scored_events": self.market_scored_events,
            "summary": self.summary,
            "bins": [item.to_dict() for item in self.bins],
            "events": [item.to_dict() for item in self.events],
            "warnings": list(self.warnings),
        }

    def to_markdown(self) -> str:
        lines = [
            f"# F1Predict Replay Calibration Diagnostics ({self.year})",
            "",
            f"- Generated at: `{self.generated_at}`",
            f"- Replay cutoff: `{self.as_of}`",
            f"- Status: **{self.status}**",
            f"- Formal probability claim ready: **{self.formal_probability_claim_ready}**",
            f"- Scored events: {self.scored_events}",
            f"- Market-scored events: {self.market_scored_events}",
            "",
            "## Summary",
            "",
        ]
        for key, value in self.summary.items():
            lines.append(f"- {key}: {value}")
        if self.warnings:
            lines.extend(["", "## Warnings", ""])
            for warning in self.warnings:
                lines.append(f"- {warning}")
        lines.extend(["", "## Top-Pick Calibration Bins", ""])
        lines.append("| Bin | Count | Avg confidence | Hit rate | Gap |")
        lines.append("|---|---:|---:|---:|---:|")
        for item in self.bins:
            label = f"{item.lower_bound:.1f}-{item.upper_bound:.1f}"
            lines.append(
                "| "
                f"{label} | {item.count} | {self._fmt(item.average_confidence)} | "
                f"{self._fmt(item.hit_rate)} | {self._fmt(item.calibration_error)} |"
            )
        lines.extend(["", "## Event Rows", ""])
        lines.append("| Event | Top pick | Actual | Hit | Top p | Actual p | Brier | Log loss | Market |")
        lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|")
        for row in self.events:
            lines.append(
                "| "
                f"{row.event_name} | {row.top_pick} | {row.actual_winner} | "
                f"{row.hit} | {row.top_pick_probability:.4f} | "
                f"{row.actual_winner_probability:.4f} | {row.winner_brier_score:.4f} | "
                f"{row.actual_log_loss:.4f} | {row.market_snapshot_count} |"
            )
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _fmt(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.4f}"


class ReplayCalibrationBuilder:
    """Computes diagnostic probability-quality metrics over replayable events."""

    def __init__(self, pipeline: PredictionPipeline | None = None) -> None:
        self.pipeline = pipeline or PredictionPipeline(iterations=1200)

    def build(self, year: int, as_of: str) -> ReplayCalibrationReport:
        coverage = ReplayCoverageBuilder(self.pipeline).build(year, as_of)
        season = self.pipeline.data_source.load()
        events_by_id = {event.event_id: event for event in season.events}
        rows: list[CalibrationEventRow] = []
        for replay_row in coverage.rows:
            if replay_row.status != "replayed" or not replay_row.seed_event_id:
                continue
            event = events_by_id.get(replay_row.seed_event_id)
            if event is None or not replay_row.actual_winner:
                continue
            cutoff = f"{event.date}T00:00:00+00:00"
            prediction = self.pipeline.predict_event(event.event_id, cutoff)
            probability_by_driver = {item.driver_id: item for item in prediction.race_probabilities}
            actual_probability = probability_by_driver.get(replay_row.actual_winner)
            if actual_probability is None:
                continue
            top = prediction.race_probabilities[0]
            actual_rank = self._rank_of(prediction.race_probabilities, replay_row.actual_winner)
            cutoff_markets = event_market_snapshots(
                season.markets,
                event.event_id,
                knowledge_cutoff=parse_dt(prediction.knowledge_cutoff),
                market_type="winner",
            )
            winner_edges = [edge for edge in prediction.market_edges if edge.market_type == "winner"]
            positive_edges = [
                edge for edge in winner_edges
                if self._conservative_edge(edge) > 0.0
            ]
            trade_edges = [edge for edge in winner_edges if edge.recommendation != "no_trade"]
            paper_trade_hit = None
            if trade_edges:
                paper_trade_hit = any(edge.outcome_id == replay_row.actual_winner for edge in trade_edges)
            rows.append(
                CalibrationEventRow(
                    event_id=event.event_id,
                    event_name=event.name,
                    cutoff=cutoff,
                    top_pick=top.driver_id,
                    actual_winner=replay_row.actual_winner,
                    hit=top.driver_id == replay_row.actual_winner,
                    top_pick_probability=round(top.win, 4),
                    actual_winner_probability=round(actual_probability.win, 4),
                    actual_winner_rank=actual_rank,
                    winner_brier_score=round(self._winner_brier(prediction.race_probabilities, replay_row.actual_winner), 4),
                    actual_log_loss=round(-math.log(max(EPSILON, actual_probability.win)), 4),
                    market_snapshot_count=len(cutoff_markets),
                    market_edge_count=len(winner_edges),
                    positive_edge_count=len(positive_edges),
                    paper_trade_candidate_count=len(trade_edges),
                    paper_trade_hit=paper_trade_hit,
                    best_edge_after_cost=round(max((self._conservative_edge(edge) for edge in winner_edges), default=0.0), 4)
                    if winner_edges
                    else None,
                )
            )
        bins = self._bins(rows)
        summary = self._summary(rows, bins)
        warnings = self._warnings(rows)
        return ReplayCalibrationReport(
            year=year,
            as_of=as_of,
            generated_at=utc_now().isoformat(),
            status="diagnostic_only",
            formal_probability_claim_ready=False,
            scored_events=len(rows),
            market_scored_events=sum(1 for row in rows if row.market_snapshot_count > 0),
            summary=summary,
            bins=tuple(bins),
            events=tuple(rows),
            warnings=tuple(warnings),
        )

    def write(
        self,
        year: int,
        as_of: str,
        output_dir: Path | str = Path("reports/calibration"),
    ) -> dict[str, Path]:
        report = self.build(year, as_of)
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"{year}_asof_{as_of.replace(':', '').replace('+', '_').replace('-', '')}"
        json_path = directory / f"{stem}.calibration.json"
        markdown_path = directory / f"{stem}.calibration.md"
        json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(report.to_markdown(), encoding="utf-8")
        return {"json": json_path, "markdown": markdown_path}

    @staticmethod
    def _winner_brier(probabilities: list[DriverRaceProbability], actual_winner: str) -> float:
        return sum((item.win - (1.0 if item.driver_id == actual_winner else 0.0)) ** 2 for item in probabilities)

    @staticmethod
    def _conservative_edge(edge: Any) -> float:
        value = getattr(edge, "conservative_edge_after_cost", None)
        return float(value if value is not None else edge.edge_after_cost)

    @staticmethod
    def _rank_of(probabilities: list[DriverRaceProbability], driver_id: str) -> int:
        for index, item in enumerate(race_probabilities_by_expected_rank(probabilities), start=1):
            if item.driver_id == driver_id:
                return index
        return len(probabilities) + 1

    @staticmethod
    def _bins(rows: list[CalibrationEventRow]) -> list[CalibrationBin]:
        boundaries = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.000001)]
        bins: list[CalibrationBin] = []
        for lower, upper in boundaries:
            selected = [
                row for row in rows
                if lower <= row.top_pick_probability < upper
            ]
            if not selected:
                bins.append(CalibrationBin(lower, min(1.0, upper), 0, None, None, None))
                continue
            avg_confidence = mean(row.top_pick_probability for row in selected)
            hit_rate = sum(1 for row in selected if row.hit) / len(selected)
            bins.append(
                CalibrationBin(
                    lower_bound=lower,
                    upper_bound=min(1.0, upper),
                    count=len(selected),
                    average_confidence=round(avg_confidence, 4),
                    hit_rate=round(hit_rate, 4),
                    calibration_error=round(hit_rate - avg_confidence, 4),
                )
            )
        return bins

    @staticmethod
    def _summary(rows: list[CalibrationEventRow], bins: list[CalibrationBin]) -> dict[str, Any]:
        if not rows:
            return {}
        populated_bins = [item for item in bins if item.count > 0 and item.calibration_error is not None]
        weighted_abs_gap = None
        if populated_bins:
            total = sum(item.count for item in populated_bins)
            weighted_abs_gap = sum(abs(float(item.calibration_error)) * item.count for item in populated_bins) / total
        trade_rows = [row for row in rows if row.paper_trade_hit is not None]
        return {
            "top_pick_hits": sum(1 for row in rows if row.hit),
            "top_pick_hit_rate": round(sum(1 for row in rows if row.hit) / len(rows), 4),
            "mean_top_pick_probability": round(mean(row.top_pick_probability for row in rows), 4),
            "mean_actual_winner_probability": round(mean(row.actual_winner_probability for row in rows), 4),
            "mean_winner_brier_score": round(mean(row.winner_brier_score for row in rows), 4),
            "mean_actual_log_loss": round(mean(row.actual_log_loss for row in rows), 4),
            "weighted_top_pick_calibration_gap": None if weighted_abs_gap is None else round(weighted_abs_gap, 4),
            "market_scored_events": sum(1 for row in rows if row.market_snapshot_count > 0),
            "paper_trade_candidate_events": len(trade_rows),
            "paper_trade_candidate_hit_rate": None
            if not trade_rows
            else round(sum(1 for row in trade_rows if row.paper_trade_hit) / len(trade_rows), 4),
        }

    @staticmethod
    def _warnings(rows: list[CalibrationEventRow]) -> list[str]:
        warnings = [
            "diagnostic_only_not_formal_probability_calibration",
            "same_replay_inputs_as_current_diagnostic_pipeline",
        ]
        if len(rows) < 20:
            warnings.append("small_sample_less_than_20_scored_events")
        if sum(1 for row in rows if row.market_snapshot_count > 0) < len(rows):
            warnings.append("market_scored_subset_incomplete")
        return warnings
