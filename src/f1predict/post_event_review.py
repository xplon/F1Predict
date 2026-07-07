"""Post-event review for registered prediction packets."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from f1predict.domain import parse_dt, utc_now
from f1predict.pipeline import PredictionPipeline
from f1predict.results import FastF1ResultRepository, NormalizedRaceResult
from f1predict.run_tracking import PredictionRunRecord, PredictionRunRegistry


def _compact(value: str | None) -> str:
    if not value:
        return ""
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", ascii_value.lower())


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class PostEventDriverReview:
    driver_id: str
    predicted_rank: int | None
    actual_position: int | None
    rank_error: int | None
    win_probability: float | None
    podium_probability: float | None
    points_probability: float | None
    expected_points: float | None
    average_finish: float | None
    result_driver_id: str | None
    result_name: str | None
    result_points: float | None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


@dataclass(frozen=True)
class PostEventReviewReport:
    event_id: str
    event_name: str
    generated_at: str
    status: str
    prediction_run_id: str
    prediction_packet_path: str | None
    packet_payload_sha256: str | None
    prediction_status: str
    knowledge_cutoff: str | None
    result_source: str
    result_path: str
    result_captured_at: str
    result_captured_after_prediction_cutoff: bool | None
    actual_winner: str | None
    predicted_winner: str | None
    winner_hit: bool
    actual_winner_predicted_rank: int | None
    actual_winner_win_probability: float | None
    predicted_winner_actual_position: int | None
    podium_overlap_rate: float | None
    points_overlap_rate: float | None
    mean_abs_rank_error: float | None
    top10_actual_position_summary: list[dict[str, Any]]
    driver_reviews: tuple[PostEventDriverReview, ...]
    warnings: tuple[str, ...]
    summary_zh: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_name": self.event_name,
            "generated_at": self.generated_at,
            "status": self.status,
            "prediction_run_id": self.prediction_run_id,
            "prediction_packet_path": self.prediction_packet_path,
            "packet_payload_sha256": self.packet_payload_sha256,
            "prediction_status": self.prediction_status,
            "knowledge_cutoff": self.knowledge_cutoff,
            "result_source": self.result_source,
            "result_path": self.result_path,
            "result_captured_at": self.result_captured_at,
            "result_captured_after_prediction_cutoff": self.result_captured_after_prediction_cutoff,
            "actual_winner": self.actual_winner,
            "predicted_winner": self.predicted_winner,
            "winner_hit": self.winner_hit,
            "actual_winner_predicted_rank": self.actual_winner_predicted_rank,
            "actual_winner_win_probability": self.actual_winner_win_probability,
            "predicted_winner_actual_position": self.predicted_winner_actual_position,
            "podium_overlap_rate": self.podium_overlap_rate,
            "points_overlap_rate": self.points_overlap_rate,
            "mean_abs_rank_error": self.mean_abs_rank_error,
            "top10_actual_position_summary": self.top10_actual_position_summary,
            "driver_reviews": [row.to_dict() for row in self.driver_reviews],
            "warnings": list(self.warnings),
            "summary_zh": self.summary_zh,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# {self.event_name} 赛后预测复盘",
            "",
            f"- 状态：`{self.status}`",
            f"- 预测 run：`{self.prediction_run_id}`",
            f"- 预测状态：`{self.prediction_status}`",
            f"- 知识截止：`{self.knowledge_cutoff}`",
            f"- 预测包 sha：`{self.packet_payload_sha256}`",
            f"- 结果来源：`{self.result_source}`",
            f"- 结果快照：`{self.result_path}`",
            f"- 结果捕获时间：`{self.result_captured_at}`",
            f"- 结果是否晚于预测截止：`{self.result_captured_after_prediction_cutoff}`",
            "",
            "## 摘要",
            "",
            self.summary_zh,
            "",
            "## 指标",
            "",
            f"- 实际冠军：`{self.actual_winner}`",
            f"- 预测第一：`{self.predicted_winner}`",
            f"- 冠军是否命中：`{self.winner_hit}`",
            f"- 实际冠军的预测排名：`{self.actual_winner_predicted_rank}`",
            f"- 实际冠军的预测胜率：`{self.actual_winner_win_probability}`",
            f"- 预测第一的实际完赛位置：`{self.predicted_winner_actual_position}`",
            f"- 领奖台重合率：`{self.podium_overlap_rate}`",
            f"- 积分区重合率：`{self.points_overlap_rate}`",
            f"- 平均绝对排名误差：`{self.mean_abs_rank_error}`",
        ]
        if self.warnings:
            lines.extend(["", "## 警告", ""])
            lines.extend(f"- `{warning}`" for warning in self.warnings)
        lines.extend(["", "## 预测前十赛后位置", ""])
        lines.append("| 预测排名 | 车手 | 实际位置 | 预测胜率 | 预计积分 |")
        lines.append("|---:|---|---:|---:|---:|")
        for row in self.top10_actual_position_summary:
            lines.append(
                "| "
                f"{row['predicted_rank']} | {row['driver_id']} | {row.get('actual_position')} | "
                f"{row.get('win_probability')} | {row.get('expected_points')} |"
            )
        return "\n".join(lines).rstrip() + "\n"


class PostEventReviewBuilder:
    """Compare a registered pre-event prediction packet with a FastF1 result snapshot."""

    def __init__(
        self,
        registry: PredictionRunRegistry | None = None,
        result_repository: FastF1ResultRepository | None = None,
        pipeline: PredictionPipeline | None = None,
    ) -> None:
        self.registry = registry or PredictionRunRegistry()
        self.result_repository = result_repository or FastF1ResultRepository()
        self.pipeline = pipeline or PredictionPipeline(iterations=1)

    def build(self, event_id: str, knowledge_cutoff: str | None = None) -> PostEventReviewReport:
        record = self.registry.latest(event_id, knowledge_cutoff=knowledge_cutoff)
        if record is None:
            raise ValueError(f"No registered prediction run for event_id={event_id}")
        if not record.prediction_packet_path:
            raise ValueError(f"Prediction run {record.run_id} does not reference a packet path")
        packet_path = Path(record.prediction_packet_path)
        packet = json.loads(packet_path.read_text(encoding="utf-8-sig"))
        result = self.result_repository.latest_result_for_event(2026, record.event_name)
        if result is None:
            raise ValueError(f"No FastF1 race result snapshot for {record.event_name}")

        predicted_rows = self._predicted_rows(packet)
        alias_map = self._driver_alias_map()
        actual_rows = self._actual_rows(result, alias_map)
        actual_by_driver = {row["driver_id"]: row for row in actual_rows if row.get("driver_id")}
        predicted_by_driver = {row["driver_id"]: row for row in predicted_rows}
        actual_winner = actual_rows[0]["driver_id"] if actual_rows else result.winner_driver_id
        predicted_winner = predicted_rows[0]["driver_id"] if predicted_rows else None
        actual_winner_row = predicted_by_driver.get(str(actual_winner))
        predicted_winner_result = actual_by_driver.get(str(predicted_winner)) if predicted_winner else None

        driver_reviews = self._driver_reviews(predicted_rows, actual_by_driver)
        matched_errors = [row.rank_error for row in driver_reviews if row.rank_error is not None]
        podium_overlap = self._overlap(predicted_rows, actual_rows, 3)
        points_overlap = self._overlap(predicted_rows, actual_rows, 10)
        cutoff_dt = parse_dt(record.knowledge_cutoff)
        captured_dt = parse_dt(result.captured_at)
        result_after_cutoff = None
        if cutoff_dt is not None and captured_dt is not None:
            result_after_cutoff = captured_dt > cutoff_dt
        warnings = self._warnings(record, result_after_cutoff, predicted_rows, actual_rows)
        summary_zh = self._summary_zh(
            actual_winner=str(actual_winner) if actual_winner else None,
            predicted_winner=predicted_winner,
            actual_winner_rank=int(actual_winner_row["expected_rank"]) if actual_winner_row else None,
            predicted_winner_actual_position=(
                int(predicted_winner_result["position"]) if predicted_winner_result else None
            ),
            podium_overlap_rate=podium_overlap,
            points_overlap_rate=points_overlap,
        )
        return PostEventReviewReport(
            event_id=event_id,
            event_name=record.event_name,
            generated_at=utc_now().replace(microsecond=0).isoformat(),
            status="diagnostic_only",
            prediction_run_id=record.run_id,
            prediction_packet_path=record.prediction_packet_path,
            packet_payload_sha256=record.packet_payload_sha256,
            prediction_status=record.status,
            knowledge_cutoff=record.knowledge_cutoff,
            result_source=result.source,
            result_path=result.path,
            result_captured_at=result.captured_at,
            result_captured_after_prediction_cutoff=result_after_cutoff,
            actual_winner=str(actual_winner) if actual_winner else None,
            predicted_winner=predicted_winner,
            winner_hit=actual_winner == predicted_winner,
            actual_winner_predicted_rank=int(actual_winner_row["expected_rank"]) if actual_winner_row else None,
            actual_winner_win_probability=(
                round(_as_float(actual_winner_row.get("win")), 6) if actual_winner_row else None
            ),
            predicted_winner_actual_position=(
                int(predicted_winner_result["position"]) if predicted_winner_result else None
            ),
            podium_overlap_rate=podium_overlap,
            points_overlap_rate=points_overlap,
            mean_abs_rank_error=round(mean(abs(value) for value in matched_errors), 4) if matched_errors else None,
            top10_actual_position_summary=[
                {
                    "driver_id": row["driver_id"],
                    "predicted_rank": row["expected_rank"],
                    "actual_position": (
                        actual_by_driver.get(row["driver_id"], {}).get("position")
                        if row.get("driver_id")
                        else None
                    ),
                    "win_probability": round(_as_float(row.get("win")), 6),
                    "expected_points": round(_as_float(row.get("expected_points")), 4),
                }
                for row in predicted_rows[:10]
            ],
            driver_reviews=tuple(driver_reviews),
            warnings=tuple(warnings),
            summary_zh=summary_zh,
        )

    def write(
        self,
        event_id: str,
        knowledge_cutoff: str | None = None,
        output_dir: Path | str = Path("reports/post_event_review"),
    ) -> dict[str, Path]:
        report = self.build(event_id, knowledge_cutoff=knowledge_cutoff)
        directory = Path(output_dir) / event_id
        directory.mkdir(parents=True, exist_ok=True)
        cutoff_stem = (report.knowledge_cutoff or "latest").replace(":", "").replace("-", "").replace("+", "_")
        json_path = directory / f"{event_id}_{cutoff_stem}.post_event_review.json"
        md_path = directory / f"{event_id}_{cutoff_stem}.post_event_review.md"
        json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md_path.write_text(report.to_markdown(), encoding="utf-8")
        return {"json": json_path, "markdown": md_path}

    @staticmethod
    def _predicted_rows(packet: dict[str, Any]) -> list[dict[str, Any]]:
        rows = packet.get("prediction", {}).get("race_probabilities")
        if not isinstance(rows, list):
            return []
        normalized = [dict(row) for row in rows if isinstance(row, dict) and row.get("driver_id")]
        for index, row in enumerate(
            sorted(
                normalized,
                key=lambda item: (
                    _as_float(item.get("average_finish"), 999.0),
                    -_as_float(item.get("expected_points")),
                    -_as_float(item.get("podium")),
                    -_as_float(item.get("win")),
                    str(item.get("driver_id")),
                ),
            ),
            start=1,
        ):
            row["expected_rank"] = int(row.get("expected_rank") or index)
        return sorted(normalized, key=lambda item: int(item.get("expected_rank") or 999))

    def _driver_alias_map(self) -> dict[str, str]:
        season = self.pipeline.data_source.load()
        aliases: dict[str, str] = {}
        last_name_counts: dict[str, int] = {}
        last_names: dict[str, str] = {}
        for driver_id, driver in season.drivers.items():
            names = [driver_id, driver.name, *driver.external_ids.values()]
            for name in names:
                compact = _compact(str(name))
                if compact:
                    aliases[compact] = driver_id
            last = _compact(str(driver.name).split()[-1] if driver.name else driver_id)
            if last:
                last_names[driver_id] = last
                last_name_counts[last] = last_name_counts.get(last, 0) + 1
        for driver_id, last in last_names.items():
            if last_name_counts.get(last) == 1:
                aliases[last] = driver_id
        return aliases

    @staticmethod
    def _actual_rows(result: NormalizedRaceResult, alias_map: dict[str, str]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for row in result.classified:
            raw_driver_id = str(row.get("driver_id") or "")
            full_name = str(row.get("full_name") or "")
            mapped = (
                alias_map.get(_compact(raw_driver_id))
                or alias_map.get(_compact(full_name))
                or alias_map.get(_compact(raw_driver_id.split("_")[-1]))
                or raw_driver_id
            )
            output.append(
                {
                    **row,
                    "result_driver_id": raw_driver_id,
                    "driver_id": mapped,
                }
            )
        return sorted(output, key=lambda item: int(item.get("position") or 999))

    @staticmethod
    def _driver_reviews(
        predicted_rows: list[dict[str, Any]],
        actual_by_driver: dict[str, dict[str, Any]],
    ) -> list[PostEventDriverReview]:
        output: list[PostEventDriverReview] = []
        for row in predicted_rows:
            driver_id = str(row.get("driver_id"))
            predicted_rank = int(row.get("expected_rank") or 0) or None
            actual = actual_by_driver.get(driver_id)
            actual_position = int(actual.get("position") or 0) if actual else None
            output.append(
                PostEventDriverReview(
                    driver_id=driver_id,
                    predicted_rank=predicted_rank,
                    actual_position=actual_position,
                    rank_error=(
                        actual_position - predicted_rank
                        if actual_position is not None and predicted_rank is not None
                        else None
                    ),
                    win_probability=round(_as_float(row.get("win")), 6),
                    podium_probability=round(_as_float(row.get("podium")), 6),
                    points_probability=round(_as_float(row.get("points")), 6),
                    expected_points=round(_as_float(row.get("expected_points")), 4),
                    average_finish=round(_as_float(row.get("average_finish")), 4),
                    result_driver_id=str(actual.get("result_driver_id")) if actual else None,
                    result_name=str(actual.get("full_name")) if actual else None,
                    result_points=_as_float(actual.get("points")) if actual else None,
                )
            )
        return output

    @staticmethod
    def _overlap(predicted_rows: list[dict[str, Any]], actual_rows: list[dict[str, Any]], count: int) -> float | None:
        if len(predicted_rows) < count or len(actual_rows) < count:
            return None
        predicted = {str(row.get("driver_id")) for row in predicted_rows[:count]}
        actual = {str(row.get("driver_id")) for row in actual_rows[:count]}
        return round(len(predicted & actual) / count, 4)

    @staticmethod
    def _warnings(
        record: PredictionRunRecord,
        result_after_cutoff: bool | None,
        predicted_rows: list[dict[str, Any]],
        actual_rows: list[dict[str, Any]],
    ) -> list[str]:
        warnings = ["post_event_review_diagnostic_only"]
        if not record.formal_edge_ready:
            warnings.append("prediction_packet_not_formal_edge_ready")
        if result_after_cutoff is True:
            warnings.append("result_snapshot_after_prediction_cutoff_for_evaluation_only")
        if len(predicted_rows) != len(actual_rows):
            warnings.append("predicted_actual_driver_count_mismatch")
        return warnings

    @staticmethod
    def _summary_zh(
        *,
        actual_winner: str | None,
        predicted_winner: str | None,
        actual_winner_rank: int | None,
        predicted_winner_actual_position: int | None,
        podium_overlap_rate: float | None,
        points_overlap_rate: float | None,
    ) -> str:
        if actual_winner == predicted_winner:
            winner_text = f"冠军命中：模型预测第一和实际冠军都是 {actual_winner}。"
        else:
            winner_text = (
                f"冠军未命中：模型预测第一是 {predicted_winner}，实际冠军是 {actual_winner}。"
                f"实际冠军在赛前预测中的预计排名是第 {actual_winner_rank}。"
            )
        return (
            f"{winner_text}"
            f" 预测第一的实际完赛位置是第 {predicted_winner_actual_position}。"
            f" 领奖台重合率为 {podium_overlap_rate}，积分区重合率为 {points_overlap_rate}。"
            " 这份复盘只用于赛后诊断，不会把赛后结果写回赛前预测。"
        )
