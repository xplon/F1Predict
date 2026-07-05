"""Chronological replay coverage and seed replay reporting."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from f1predict.backtest import Backtester
from f1predict.domain import parse_dt
from f1predict.event_inputs import audit_event_input
from f1predict.features.calendar import CalendarBuilder
from f1predict.pipeline import PredictionPipeline
from f1predict.results import FastF1ResultRepository, normalize_event_name


@dataclass(frozen=True)
class ReplayCoverageRow:
    round_number: int
    racing_sequence_number: int | None
    cancelled_before_count: int
    event_name: str
    date_end: str
    status: str
    is_cancelled: bool = False
    seed_event_id: str | None = None
    prediction_input_source: str | None = None
    event_input_quality: str | None = None
    event_input_risk_codes: tuple[str, ...] = ()
    event_input_verified_fields: tuple[str, ...] = ()
    event_input_derived_fields: tuple[str, ...] = ()
    event_input_heuristic_fields: tuple[str, ...] = ()
    event_input_placeholder_fields: tuple[str, ...] = ()
    top_pick: str | None = None
    actual_winner: str | None = None
    hit: bool | None = None
    actual_winner_rank: int | None = None
    full_field_driver_count: int = 0
    mean_abs_rank_error: float | None = None
    mean_abs_points_error: float | None = None
    podium_overlap_rate: float | None = None
    points_overlap_rate: float | None = None
    evidence_count: int = 0
    feature_adjustment_count: int = 0
    market_snapshot_count: int = 0
    market_snapshot_after_cutoff_count: int = 0
    market_edge_count: int = 0
    result_available: bool = False
    result_source: str | None = None
    result_path: str | None = None
    fastf1_round_number: int | None = None
    fastf1_winner: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReplayCoverageReport:
    year: int
    as_of: str
    calendar_events: int
    cancelled_events: int
    due_events: int
    replayed_events: int
    result_available_events: int
    missing_due_events: int
    rows: list[ReplayCoverageRow]

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "as_of": self.as_of,
            "calendar_events": self.calendar_events,
            "cancelled_events": self.cancelled_events,
            "due_events": self.due_events,
            "replayed_events": self.replayed_events,
            "result_available_events": self.result_available_events,
            "missing_due_events": self.missing_due_events,
            "rows": [row.__dict__ for row in self.rows],
        }


class ReplayCoverageBuilder:
    def __init__(
        self,
        pipeline: PredictionPipeline | None = None,
        calendar_builder: CalendarBuilder | None = None,
        result_repository: FastF1ResultRepository | None = None,
    ) -> None:
        self.pipeline = pipeline or PredictionPipeline(iterations=1200)
        self.calendar_builder = calendar_builder or CalendarBuilder()
        self.result_repository = result_repository or FastF1ResultRepository()

    def build(self, year: int, as_of: str) -> ReplayCoverageReport:
        calendar = self.calendar_builder.build_from_openf1(year)
        as_of_dt = parse_dt(as_of)
        if as_of_dt is None:
            raise ValueError(f"Invalid as_of datetime: {as_of}")

        seed_events = self.pipeline.list_events()
        seed_by_name = {normalize_event_name(str(event["name"])): event for event in seed_events}
        seed_results = {row.event_id: row for row in Backtester(self.pipeline).run_replay()}
        fastf1_results = self.result_repository.latest_results_by_event(year)
        fastf1_schedule = self.result_repository.latest_schedule_by_event(year)

        rows: list[ReplayCoverageRow] = []
        cancelled_events = 0
        due_events = 0
        replayed_events = 0
        result_available_events = 0
        missing_due_events = 0
        non_cancelled_sequence = 0

        for item in calendar:
            end_dt = parse_dt(str(item["date_end"]))
            is_due = end_dt is not None and end_dt <= as_of_dt
            is_cancelled = bool(item.get("is_cancelled", False))
            cancelled_before_count = cancelled_events
            racing_sequence_number = None
            if not is_cancelled:
                non_cancelled_sequence += 1
                racing_sequence_number = non_cancelled_sequence
            key = normalize_event_name(str(item["event_name"]))
            seed_event = seed_by_name.get(key)
            replay = seed_results.get(str(seed_event["event_id"])) if seed_event else None
            result = fastf1_results.get(key)
            schedule_item = fastf1_schedule.get(key)
            warnings = self._row_warnings(
                item,
                seed_event,
                result,
                schedule_item,
                expected_fastf1_round=racing_sequence_number,
                cancelled_before_count=cancelled_before_count,
            )
            result_available = replay is not None or result is not None
            result_source = self._result_source(replay is not None, result is not None)
            actual_winner = replay.actual_winner if replay else result.winner_driver_id if result else None
            input_source = self._prediction_input_source(seed_event)
            event_input_audit = audit_event_input(seed_event) if seed_event else None
            if replay and replay.evidence_count == 0:
                warnings.append("no_codex_evidence_at_cutoff")
            if replay and replay.market_snapshot_count == 0:
                warnings.append("no_market_snapshot_at_cutoff")
            if replay and replay.market_snapshot_after_cutoff_count > 0:
                warnings.append("market_snapshot_after_cutoff")
            if replay and event_input_audit:
                warnings.extend(
                    code for code in event_input_audit.risk_codes if code not in warnings
                )

            if is_cancelled:
                status = "cancelled"
                cancelled_events += 1
            elif is_due:
                due_events += 1
                if result_available:
                    result_available_events += 1
                if replay:
                    status = "replayed"
                    replayed_events += 1
                elif result:
                    status = "result_available_no_prediction"
                    missing_due_events += 1
                else:
                    status = "missing_due_data"
                    missing_due_events += 1
            else:
                status = "not_due"

            rows.append(
                ReplayCoverageRow(
                    round_number=int(item["round_number"]),
                    racing_sequence_number=racing_sequence_number,
                    cancelled_before_count=cancelled_before_count,
                    event_name=str(item["event_name"]),
                    date_end=str(item["date_end"]),
                    status=status,
                    is_cancelled=is_cancelled,
                    seed_event_id=str(seed_event["event_id"]) if seed_event else None,
                    prediction_input_source=input_source,
                    event_input_quality=event_input_audit.quality if event_input_audit else None,
                    event_input_risk_codes=event_input_audit.risk_codes if event_input_audit else (),
                    event_input_verified_fields=event_input_audit.verified_fields if event_input_audit else (),
                    event_input_derived_fields=event_input_audit.derived_fields if event_input_audit else (),
                    event_input_heuristic_fields=event_input_audit.heuristic_fields if event_input_audit else (),
                    event_input_placeholder_fields=event_input_audit.placeholder_fields if event_input_audit else (),
                    top_pick=replay.top_pick if replay else None,
                    actual_winner=actual_winner,
                    hit=replay.hit if replay else None,
                    actual_winner_rank=replay.actual_winner_rank if replay else None,
                    full_field_driver_count=replay.full_field_driver_count if replay else 0,
                    mean_abs_rank_error=replay.mean_abs_rank_error if replay else None,
                    mean_abs_points_error=replay.mean_abs_points_error if replay else None,
                    podium_overlap_rate=replay.podium_overlap_rate if replay else None,
                    points_overlap_rate=replay.points_overlap_rate if replay else None,
                    evidence_count=replay.evidence_count if replay else 0,
                    feature_adjustment_count=replay.feature_adjustment_count if replay else 0,
                    market_snapshot_count=replay.market_snapshot_count if replay else 0,
                    market_snapshot_after_cutoff_count=replay.market_snapshot_after_cutoff_count if replay else 0,
                    market_edge_count=replay.market_edge_count if replay else 0,
                    result_available=result_available,
                    result_source=result_source,
                    result_path=result.path if result else None,
                    fastf1_round_number=self._as_int(schedule_item.get("RoundNumber")) if schedule_item else None,
                    fastf1_winner=result.winner_driver_id if result else None,
                    warnings=tuple(warnings),
                )
            )

        return ReplayCoverageReport(
            year=year,
            as_of=as_of,
            calendar_events=len(calendar),
            cancelled_events=cancelled_events,
            due_events=due_events,
            replayed_events=replayed_events,
            result_available_events=result_available_events,
            missing_due_events=missing_due_events,
            rows=rows,
        )

    def write(self, year: int, as_of: str, output_dir: Path | str = Path("reports/replay")) -> Path:
        report = self.build(year, as_of)
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"{year}_asof_{as_of.replace(':', '').replace('+', '_').replace('-', '')}"
        path = directory / f"{stem}.json"
        path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @staticmethod
    def _result_source(has_seed_replay: bool, has_fastf1_result: bool) -> str | None:
        if has_fastf1_result:
            return "fastf1"
        if has_seed_replay:
            return "seed"
        return None

    @staticmethod
    def _prediction_input_source(seed_event: dict[str, Any] | None) -> str | None:
        if seed_event is None:
            return None
        feature_refs = seed_event.get("feature_refs")
        if isinstance(feature_refs, dict):
            source = feature_refs.get("event_source")
            if source:
                return str(source)
        return "seed"

    @staticmethod
    def _row_warnings(
        calendar_item: dict[str, Any],
        seed_event: dict[str, Any] | None,
        result: Any,
        schedule_item: dict[str, Any] | None,
        expected_fastf1_round: int | None = None,
        cancelled_before_count: int = 0,
    ) -> list[str]:
        warnings: list[str] = []
        if schedule_item is None:
            warnings.append("missing_in_fastf1_schedule_snapshot")
        else:
            calendar_round = ReplayCoverageBuilder._as_int(calendar_item.get("round_number"))
            fastf1_round = ReplayCoverageBuilder._as_int(schedule_item.get("RoundNumber"))
            if calendar_round is not None and fastf1_round is not None and calendar_round != fastf1_round:
                if (
                    expected_fastf1_round is not None
                    and fastf1_round == expected_fastf1_round
                    and cancelled_before_count > 0
                ):
                    warnings.append(
                        "round_sequence_shift_"
                        f"openf1={calendar_round}_fastf1={fastf1_round}_"
                        f"cancelled_before={cancelled_before_count}"
                    )
                else:
                    suffix = (
                        f"_expected_sequence={expected_fastf1_round}"
                        if expected_fastf1_round is not None
                        else ""
                    )
                    warnings.append(f"round_mismatch_openf1={calendar_round}_fastf1={fastf1_round}{suffix}")
        if bool(calendar_item.get("is_cancelled", False)):
            warnings.append("openf1_calendar_cancelled")
        if seed_event is not None and result and result.winner_driver_id:
            feature_refs = seed_event.get("feature_refs")
            source_actual = feature_refs.get("source_actual_result") if isinstance(feature_refs, dict) else None
            if isinstance(source_actual, dict):
                seed_actual = source_actual.get("seed") or []
                if seed_actual and seed_actual[0] != result.winner_driver_id:
                    warnings.append("seed_result_overridden_by_fastf1")
        return warnings

    @staticmethod
    def _as_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None
