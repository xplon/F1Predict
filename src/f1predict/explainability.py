"""Prediction-result explainability helpers.

The explainer is intentionally artifact-first: it reads an already registered
prediction run and its packet, extracts the smallest relevant evidence context,
then produces both a deterministic Chinese answer and a Codex prompt that can
be used for deeper LLM-assisted follow-up without inventing unsupported facts.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from f1predict.domain import EvidenceClaim, FeatureAdjustment, RaceEvent, utc_now
from f1predict.models.pace import PaceModel
from f1predict.pipeline import PredictionPipeline
from f1predict.run_tracking import PredictionRunRecord, PredictionRunRegistry
from f1predict.storage import safe_name


DRIVER_ALIASES: dict[str, tuple[str, ...]] = {
    "albon": ("阿尔本", "艾尔本"),
    "alonso": ("阿隆索",),
    "antonelli": ("安东内利", "Antonelli"),
    "bearman": ("贝尔曼", "Bearman"),
    "bortoleto": ("博托莱托", "Bortoleto"),
    "bottas": ("博塔斯",),
    "colapinto": ("科拉平托", "Colapinto"),
    "gasly": ("加斯利",),
    "hadjar": ("哈贾尔", "哈加尔", "Hadjar"),
    "hamilton": ("汉密尔顿", "刘易斯", "Hamilton"),
    "hulkenberg": ("霍肯伯格", "霍肯博格", "Hulkenberg"),
    "lawson": ("劳森",),
    "leclerc": ("勒克莱尔", "乐扣", "Leclerc"),
    "lindblad": ("林德布拉德", "Lindblad"),
    "norris": ("诺里斯",),
    "ocon": ("奥康",),
    "perez": ("佩雷兹", "Perez"),
    "piastri": ("皮亚斯特里",),
    "russell": ("拉塞尔", "Russell"),
    "sainz": ("塞恩斯", "赛恩斯", "Sainz"),
    "stroll": ("斯托尔", "Stroll"),
    "verstappen": ("维斯塔潘", "Verstappen"),
}

TEAM_ALIASES: dict[str, tuple[str, ...]] = {
    "aston_martin": ("阿斯顿马丁", "Aston Martin"),
    "cadillac": ("凯迪拉克", "Cadillac"),
    "ferrari": ("法拉利", "Ferrari"),
    "haas": ("哈斯", "Haas"),
    "mclaren": ("迈凯伦", "麦克拉伦", "McLaren"),
    "mercedes": ("梅奔", "梅赛德斯", "Mercedes"),
    "red_bull": ("红牛", "Red Bull"),
    "racing_bulls": ("小红牛", "Racing Bulls"),
    "sauber": ("索伯", "Sauber"),
    "williams": ("威廉姆斯", "Williams"),
}

METRIC_LABELS: dict[str, str] = {
    "race_pace": "正赛速度",
    "race_execution": "正赛执行",
    "qualifying_pace": "排位速度",
    "tyre_deg": "轮胎衰退",
    "reliability": "可靠性",
    "wet_skill": "湿地能力",
    "strategy": "策略",
    "power_unit": "动力单元",
    "energy_recovery": "能量回收",
    "straight_line_speed": "直道速度",
    "drag_efficiency": "低阻效率",
    "low_speed_traction": "低速牵引",
    "launch_performance": "发车表现",
    "weight": "车重",
    "upgrade_effect": "升级效果",
}

COMPONENT_LABELS: dict[str, str] = {
    "team_base_strength": "车队和赛车基础强度先验",
    "driver_base_skill": "车手基础能力先验",
    "track_affinity": "赛车与赛道类型适配",
    "racecraft": "正赛攻防和比赛执行先验",
    "wet_skill": "湿地能力按天气概率折算",
    "team_strategy": "车队策略能力",
    "tyre_management": "保胎能力",
    "qualifying": "排位单圈能力先验",
    "evidence_race_pace": "非结构化证据给出的正赛速度修正",
    "feature_race_pace": "结构化数据给出的正赛速度修正",
    "evidence_race_execution": "非结构化证据给出的正赛执行修正",
    "feature_race_execution": "结构化数据给出的正赛执行修正",
    "evidence_qualifying_pace": "非结构化证据给出的排位速度修正",
    "feature_qualifying_pace": "结构化数据给出的排位速度修正",
    "evidence_wet_skill": "非结构化证据给出的湿地能力修正",
    "evidence_strategy": "非结构化证据给出的策略修正",
    "evidence_power_unit": "非结构化证据给出的动力单元修正",
    "feature_power_unit": "结构化数据给出的动力单元修正",
    "evidence_energy_recovery": "非结构化证据给出的能量回收修正",
    "feature_energy_recovery": "结构化数据给出的能量回收修正",
    "evidence_straight_line_speed": "非结构化证据给出的直道速度修正",
    "feature_straight_line_speed": "结构化数据给出的直道速度修正",
    "evidence_drag_efficiency": "非结构化证据给出的低阻效率修正",
    "feature_drag_efficiency": "结构化数据给出的低阻效率修正",
    "evidence_low_speed_traction": "非结构化证据给出的低速牵引修正",
    "feature_low_speed_traction": "结构化数据给出的低速牵引修正",
    "evidence_weight": "非结构化证据给出的车重修正",
    "feature_weight": "结构化数据给出的车重修正",
    "evidence_upgrade_effect": "非结构化证据给出的升级效果修正",
    "feature_upgrade_effect": "结构化数据给出的升级效果修正",
}

SCOPE_LABELS = {
    "driver": "车手",
    "team": "车队",
    "event": "比赛和赛道",
}

QUESTION_TYPE_LABELS = {
    "rank_explanation": "排名解释",
    "driver_comparison": "车手对比",
    "group_zero_podium": "零领奖台概率分组解释",
    "driver_explanation": "车手解释",
    "general_explanation": "整体解释",
}

CONFIDENCE_LABELS = {
    "diagnostic_medium_for_model_mechanics_low_for_real_world_edge": "模型机制解释可信度中等，真实世界盈利优势可信度较低",
    "medium": "中等",
}

STATUS_LABELS = {
    "diagnostic_only": "诊断专用",
    "ready_for_paper_review": "可进入正式复核",
}

BLOCKER_LABELS = {
    "codex_evidence_quality_review_required": "Codex 证据质量仍需复核",
    "probability_calibration_diagnostic_only": "概率校准仍停留在诊断级",
}

STATIC_PRIOR_COMPONENTS = {
    "team_base_strength",
    "driver_base_skill",
    "track_affinity",
    "racecraft",
    "wet_skill",
    "team_strategy",
    "tyre_management",
    "qualifying",
}


@dataclass(frozen=True)
class PredictionExplanation:
    explanation_id: str
    generated_at: str
    event_id: str
    event_name: str
    run_id: str
    prediction_packet_path: str | None
    question: str
    language: str
    question_type: str
    detected_entities: dict[str, Any]
    answer: str
    confidence: str
    limitations: list[str]
    evidence_context: dict[str, Any]
    supporting_evidence: list[dict[str, Any]]
    codex_prompt: str
    codex_context: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "explanation_id": self.explanation_id,
            "generated_at": self.generated_at,
            "event_id": self.event_id,
            "event_name": self.event_name,
            "run_id": self.run_id,
            "prediction_packet_path": self.prediction_packet_path,
            "question": self.question,
            "language": self.language,
            "question_type": self.question_type,
            "detected_entities": self.detected_entities,
            "answer": self.answer,
            "confidence": self.confidence,
            "limitations": self.limitations,
            "evidence_context": _public_evidence_context(self.evidence_context),
            "supporting_evidence": _public_supporting_evidence(self.supporting_evidence),
            "codex_prompt": self.codex_prompt,
            "codex_context": self.codex_context,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# 预测解释：{self.event_name}",
            "",
            f"- 预测运行：`{self.run_id}`",
            f"- 比赛：`{self.event_id}`",
            f"- 生成时间：`{self.generated_at}`",
            f"- 问题类型：{QUESTION_TYPE_LABELS.get(self.question_type, self.question_type)}",
            f"- 可信度：{CONFIDENCE_LABELS.get(self.confidence, self.confidence)}",
            "",
            "## 问题",
            "",
            self.question,
            "",
            "## 回答",
            "",
            self.answer,
            "",
            "## 限制",
            "",
        ]
        for item in self.limitations:
            lines.append(f"- {item}")
        lines.extend(["", "## 支撑证据", ""])
        for row in self.supporting_evidence[:12]:
            label = row.get("label") or row.get("kind") or "证据"
            detail = row.get("detail") or row.get("explanation") or row.get("reason") or ""
            lines.append(f"- **{label}**: {detail}")
        lines.extend(["", "## 机器追问上下文", "", "配套 JSON 中包含给 Codex 继续追问使用的结构化上下文。", ""])
        return "\n".join(lines).rstrip() + "\n"


class PredictionExplainer:
    """Explains a registered prediction run using packet-grounded evidence."""

    def __init__(
        self,
        root: Path | str | None = None,
        registry: PredictionRunRegistry | None = None,
    ) -> None:
        self.root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
        self.registry = registry or PredictionRunRegistry(self.root / "reports" / "prediction_runs")
        self.pipeline = PredictionPipeline(iterations=1)

    def answer(
        self,
        question: str,
        event_id: str = "british_gp",
        run_id: str | None = None,
        knowledge_cutoff: str | None = None,
        language: str = "zh",
        max_evidence: int = 10,
    ) -> PredictionExplanation:
        if not question.strip():
            raise ValueError("question is required")
        run = self._select_run(event_id=event_id, run_id=run_id, knowledge_cutoff=knowledge_cutoff)
        packet_path = self._packet_path(run)
        packet = _read_json(packet_path)
        season = self.pipeline.data_source.load()
        driver_lookup = _driver_display_lookup(season)
        team_lookup = _team_display_lookup(season)
        entities = self._detect_entities(question, packet, season)
        question_type = self._question_type(question, entities)
        context = self._evidence_context(
            question=question,
            packet=packet,
            season=season,
            entities=entities,
            question_type=question_type,
            max_evidence=max_evidence,
        )
        answer = self._render_answer(
            question=question,
            packet=packet,
            context=context,
            question_type=question_type,
            driver_lookup=driver_lookup,
            team_lookup=team_lookup,
        )
        limitations = self._limitations(packet, context)
        confidence = self._confidence(packet, context)
        supporting_evidence = self._supporting_evidence(context, driver_lookup, max_evidence=max_evidence)
        explanation_id = self._explanation_id(run.run_id, question)
        codex_context = self._codex_context(packet, context)
        return PredictionExplanation(
            explanation_id=explanation_id,
            generated_at=utc_now().replace(microsecond=0).isoformat(),
            event_id=run.event_id,
            event_name=run.event_name,
            run_id=run.run_id,
            prediction_packet_path=run.prediction_packet_path,
            question=question,
            language=language,
            question_type=question_type,
            detected_entities={
                "drivers": entities["drivers"],
                "teams": entities["teams"],
                "derived_groups": entities["derived_groups"],
            },
            answer=answer,
            confidence=confidence,
            limitations=limitations,
            evidence_context=context,
            supporting_evidence=supporting_evidence,
            codex_prompt=self._codex_prompt(question, codex_context, language=language),
            codex_context=codex_context,
        )

    def write(
        self,
        explanation: PredictionExplanation,
        output_dir: Path | str = Path("reports/prediction_explanations"),
    ) -> dict[str, Path]:
        directory = Path(output_dir) / safe_name(explanation.event_id)
        directory.mkdir(parents=True, exist_ok=True)
        stem = safe_name(explanation.explanation_id)
        json_path = directory / f"{stem}.prediction_explanation.json"
        markdown_path = directory / f"{stem}.prediction_explanation.md"
        json_path.write_text(json.dumps(explanation.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(explanation.to_markdown(), encoding="utf-8")
        return {"json": json_path, "markdown": markdown_path}

    def answer_and_write(
        self,
        question: str,
        event_id: str = "british_gp",
        run_id: str | None = None,
        knowledge_cutoff: str | None = None,
        language: str = "zh",
        max_evidence: int = 10,
        output_dir: Path | str = Path("reports/prediction_explanations"),
    ) -> tuple[PredictionExplanation, dict[str, Path]]:
        explanation = self.answer(
            question=question,
            event_id=event_id,
            run_id=run_id,
            knowledge_cutoff=knowledge_cutoff,
            language=language,
            max_evidence=max_evidence,
        )
        return explanation, self.write(explanation, output_dir=output_dir)

    def _select_run(
        self,
        event_id: str,
        run_id: str | None,
        knowledge_cutoff: str | None,
    ) -> PredictionRunRecord:
        if run_id:
            return self.registry.load(run_id)
        run = self.registry.latest(event_id, knowledge_cutoff=knowledge_cutoff)
        if run is None:
            raise ValueError(f"No registered prediction run found for event_id={event_id}")
        return run

    def _packet_path(self, run: PredictionRunRecord) -> Path:
        if not run.prediction_packet_path:
            raise ValueError(f"Prediction run has no packet path: {run.run_id}")
        path = Path(run.prediction_packet_path)
        if path.is_absolute():
            return path
        return self.root / path

    def _detect_entities(self, question: str, packet: dict[str, Any], season: Any) -> dict[str, Any]:
        drivers = self._detect_drivers(question, season)
        teams = self._detect_teams(question, season)
        derived_groups: list[dict[str, Any]] = []
        if _mentions_zero_podium(question):
            zero_rows = [
                row for row in _probability_rows(packet)
                if _as_float(row.get("podium")) <= 0.0
            ]
            zero_ranked = sorted(
                zero_rows,
                key=lambda row: (
                    _as_float(row.get("average_finish"), 99.0),
                    -_as_float(row.get("expected_points")),
                ),
            )
            derived_groups.append(
                {
                    "group": "zero_podium_probability",
                    "driver_ids": [row["driver_id"] for row in zero_ranked],
                    "top_driver_id": zero_ranked[0]["driver_id"] if zero_ranked else None,
                }
            )
            if zero_ranked and zero_ranked[0]["driver_id"] not in drivers:
                drivers.append(zero_ranked[0]["driver_id"])
            for row in zero_ranked[1:4]:
                if row["driver_id"] not in drivers:
                    drivers.append(row["driver_id"])
        if not drivers and _mentions_first_rank(question):
            ranked = _ranked_by_average_finish(packet)
            if ranked:
                drivers.append(ranked[0]["driver_id"])
                if len(ranked) > 1:
                    drivers.append(ranked[1]["driver_id"])
        return {
            "drivers": drivers,
            "teams": teams,
            "derived_groups": derived_groups,
        }

    def _detect_drivers(self, question: str, season: Any) -> list[str]:
        q = _compact(question)
        matches: list[str] = []
        for driver_id, driver in season.drivers.items():
            aliases = [
                driver_id,
                driver.name,
                driver.name.split()[-1] if driver.name.split() else "",
                *DRIVER_ALIASES.get(driver_id, ()),
            ]
            if any(_compact(alias) and _compact(alias) in q for alias in aliases):
                matches.append(driver_id)
        return list(dict.fromkeys(matches))

    def _detect_teams(self, question: str, season: Any) -> list[str]:
        q = _compact(question)
        matches: list[str] = []
        for team_id, team in season.teams.items():
            aliases = [team_id, team.name, *TEAM_ALIASES.get(team_id, ())]
            if any(_compact(alias) and _compact(alias) in q for alias in aliases):
                matches.append(team_id)
        return list(dict.fromkeys(matches))

    @staticmethod
    def _question_type(question: str, entities: dict[str, Any]) -> str:
        q = _compact(question)
        if entities["derived_groups"] and "zero_podium_probability" in {
            row.get("group") for row in entities["derived_groups"]
        }:
            return "group_zero_podium"
        if len(entities["drivers"]) >= 2 and any(token in q for token in ("为什么", "比", "低于", "高于", "差距")):
            return "driver_comparison"
        if _mentions_first_rank(question):
            return "rank_explanation"
        if entities["drivers"]:
            return "driver_explanation"
        return "general_explanation"

    def _evidence_context(
        self,
        question: str,
        packet: dict[str, Any],
        season: Any,
        entities: dict[str, Any],
        question_type: str,
        max_evidence: int,
    ) -> dict[str, Any]:
        selected_drivers = list(entities["drivers"])
        if question_type == "general_explanation":
            selected_drivers = [row["driver_id"] for row in _ranked_by_average_finish(packet)[:5]]
        for team_id in entities["teams"]:
            for driver in season.drivers.values():
                if driver.team_id == team_id and driver.driver_id not in selected_drivers:
                    selected_drivers.append(driver.driver_id)
        selected_drivers = list(dict.fromkeys(selected_drivers))

        probability_rows = _probability_context(packet, selected_drivers)
        all_probability_rows = _probability_context(packet, [row["driver_id"] for row in _probability_rows(packet)])
        features = self._feature_context(packet, season, selected_drivers, max_evidence=max_evidence)
        factor_traces = self._factor_trace_context(packet, season, selected_drivers, max_evidence=max_evidence)
        evidence_impacts = self._evidence_impact_context(packet, season, selected_drivers, max_evidence=max_evidence)
        score_breakdown = self._score_breakdown_context(packet, season, selected_drivers)
        qualifying = self._qualifying_context(packet, selected_drivers)
        track = (packet.get("model_context") or {}).get("track_feature_vector") or {}
        return {
            "question": question,
            "question_type": question_type,
            "selected_driver_ids": selected_drivers,
            "probability_rows": probability_rows,
            "all_probability_rows": all_probability_rows,
            "feature_context": features,
            "factor_trace_context": factor_traces,
            "evidence_impact_context": evidence_impacts,
            "score_breakdown": score_breakdown,
            "qualifying_context": qualifying,
            "track_context": {
                "track_type": track.get("track_type"),
                "corner_count": track.get("corner_count"),
                "high_speed_corner_count": track.get("high_speed_corner_count"),
                "long_straight_count": track.get("long_straight_count"),
                "overtaking_index": track.get("overtaking_index"),
                "track_position_value": track.get("track_position_value"),
                "safety_car_probability": track.get("safety_car_probability"),
                "wet_probability": track.get("wet_probability"),
                "tyre_degradation_index": track.get("tyre_degradation_index"),
                "provenance": track.get("provenance"),
            },
            "readiness": {
                "status": packet.get("status"),
                "formal_edge_ready": packet.get("formal_edge_ready"),
                "blocker_codes": list(packet.get("blocker_codes") or []),
                "warning_codes": list(packet.get("warning_codes") or []),
            },
            "codex_counts": {
                "evidence_count": (packet.get("codex_context") or {}).get("evidence_count"),
                "factor_trace_count": (packet.get("codex_context") or {}).get("factor_trace_count"),
                "weak_evidence_quality_count": (packet.get("codex_context") or {}).get(
                    "weak_evidence_quality_count"
                ),
                "strong_evidence_quality_count": (packet.get("codex_context") or {}).get(
                    "strong_evidence_quality_count"
                ),
            },
        }

    def _feature_context(
        self,
        packet: dict[str, Any],
        season: Any,
        driver_ids: list[str],
        max_evidence: int,
    ) -> dict[str, Any]:
        rows = packet.get("prediction", {}).get("feature_adjustments") or []
        by_driver: dict[str, dict[str, Any]] = {}
        event_id = str(packet.get("event_id") or packet.get("prediction", {}).get("event", {}).get("event_id") or "")
        for driver_id in driver_ids:
            driver = season.drivers.get(driver_id)
            if driver is None:
                continue
            relevant = [
                self._feature_row(row, driver_id, driver.team_id)
                for row in rows
                if isinstance(row, dict)
                and (
                    row.get("target_id") == driver_id
                    or row.get("target_id") == driver.team_id
                    or row.get("target_id") == event_id
                )
            ]
            relevant = [row for row in relevant if row]
            relevant.sort(key=lambda row: abs(float(row["weighted_value"])), reverse=True)
            metric_totals: dict[str, float] = {}
            for row in relevant:
                metric = str(row.get("metric") or "unknown")
                metric_totals[metric] = metric_totals.get(metric, 0.0) + float(row["weighted_value"])
            by_driver[driver_id] = {
                "team_id": driver.team_id,
                "features": relevant,
                "top_features": relevant[:max_evidence],
                "metric_weighted_totals": {
                    key: round(value, 5)
                    for key, value in sorted(metric_totals.items(), key=lambda item: abs(item[1]), reverse=True)
                },
            }
        return by_driver

    @staticmethod
    def _feature_row(row: dict[str, Any], driver_id: str, team_id: str) -> dict[str, Any]:
        weighted = _as_float(row.get("value")) * _as_float(row.get("confidence"), 1.0)
        scope = "driver" if row.get("target_id") == driver_id else "team" if row.get("target_id") == team_id else "event"
        return {
            "kind": "feature_adjustment",
            "scope": scope,
            "feature_id": row.get("feature_id"),
            "source": row.get("source"),
            "target_type": row.get("target_type"),
            "target_id": row.get("target_id"),
            "metric": row.get("metric"),
            "value": _round(row.get("value"), 5),
            "confidence": _round(row.get("confidence"), 5),
            "weighted_value": round(weighted, 5),
            "explanation": row.get("explanation"),
        }

    def _factor_trace_context(
        self,
        packet: dict[str, Any],
        season: Any,
        driver_ids: list[str],
        max_evidence: int,
    ) -> list[dict[str, Any]]:
        traces = (packet.get("codex_context") or {}).get("factor_trace") or []
        selected = set(driver_ids)
        teams = {season.drivers[driver_id].team_id for driver_id in selected if driver_id in season.drivers}
        event_id = str(packet.get("event_id") or "")
        rows = []
        for row in traces:
            if not isinstance(row, dict):
                continue
            affected = [
                item.get("driver_id")
                for item in row.get("affected_outcomes") or []
                if isinstance(item, dict)
            ]
            if (
                row.get("target_id") in selected
                or row.get("target_id") in teams
                or row.get("target_id") == event_id
                or any(driver_id in selected for driver_id in affected)
            ):
                rows.append(row)
        rows.sort(key=lambda row: abs(_as_float(row.get("max_win_probability_delta"))), reverse=True)
        return rows[:max_evidence]

    def _evidence_impact_context(
        self,
        packet: dict[str, Any],
        season: Any,
        driver_ids: list[str],
        max_evidence: int,
    ) -> list[dict[str, Any]]:
        impacts = packet.get("prediction", {}).get("evidence_impact") or []
        selected = set(driver_ids)
        teams = {season.drivers[driver_id].team_id for driver_id in selected if driver_id in season.drivers}
        event_id = str(packet.get("event_id") or "")
        rows = []
        for row in impacts:
            if not isinstance(row, dict):
                continue
            affected = [
                item.get("driver_id")
                for item in row.get("affected_outcomes") or []
                if isinstance(item, dict)
            ]
            if (
                row.get("target_id") in selected
                or row.get("target_id") in teams
                or row.get("target_id") == event_id
                or any(driver_id in selected for driver_id in affected)
            ):
                rows.append(row)
        rows.sort(key=lambda row: abs(_as_float(row.get("max_win_probability_delta"))), reverse=True)
        return rows[:max_evidence]

    def _score_breakdown_context(self, packet: dict[str, Any], season: Any, driver_ids: list[str]) -> dict[str, Any]:
        event_payload = packet.get("prediction", {}).get("event") or {}
        event = _race_event_from_packet(event_payload)
        evidence_rows = packet.get("prediction", {}).get("evidence") or []
        feature_rows = packet.get("prediction", {}).get("feature_adjustments") or []
        quality_rows = packet.get("prediction", {}).get("evidence_quality") or []
        weights = {
            str(row.get("claim_id")): _as_float(row.get("model_input_weight"), 1.0)
            for row in quality_rows
            if isinstance(row, dict) and row.get("claim_id")
        }
        evidence = []
        for row in evidence_rows:
            if not isinstance(row, dict):
                continue
            try:
                evidence.append(EvidenceClaim.from_dict(row))
            except Exception:
                continue
        features = []
        for row in feature_rows:
            if not isinstance(row, dict):
                continue
            try:
                features.append(FeatureAdjustment(**row))
            except TypeError:
                continue
        pace = PaceModel(season, evidence, features, evidence_weights=weights)
        output: dict[str, Any] = {}
        for driver_id in driver_ids:
            driver = season.drivers.get(driver_id)
            if driver is None:
                continue
            race = pace.score_breakdown(driver, event, mode="race")
            qualifying = pace.score_breakdown(driver, event, mode="qualifying")
            output[driver_id] = {
                "race_total": round(race["total"], 5),
                "qualifying_total": round(qualifying["total"], 5),
                "race_components": _components_dict(race),
                "qualifying_components": _components_dict(qualifying),
                "race_top_components": _top_components(race, limit=8),
                "qualifying_top_components": _top_components(qualifying, limit=6),
                "reliability": round(pace.reliability(driver), 5),
                "tyre_degradation_adjustment": round(pace.degradation_adjustment(driver, event), 5),
                "launch_adjustment": round(pace.launch_adjustment(driver, event), 5),
            }
        return output

    @staticmethod
    def _qualifying_context(packet: dict[str, Any], driver_ids: list[str]) -> dict[str, Any]:
        refs = packet.get("prediction", {}).get("event", {}).get("feature_refs") or {}
        order = refs.get("fastf1_qualifying_order") if isinstance(refs, dict) else None
        rows = order.get("driver_positions") if isinstance(order, dict) else []
        selected = []
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and row.get("driver_id") in driver_ids:
                selected.append(row)
        selected.sort(key=lambda row: int(row.get("qualifying_position") or 99))
        return {
            "source": order.get("source") if isinstance(order, dict) else None,
            "observed_at": order.get("observed_at") if isinstance(order, dict) else None,
            "captured_at": order.get("captured_at") if isinstance(order, dict) else None,
            "row_count": order.get("row_count") if isinstance(order, dict) else None,
            "selected_positions": selected,
        }

    def _render_answer(
        self,
        question: str,
        packet: dict[str, Any],
        context: dict[str, Any],
        question_type: str,
        driver_lookup: dict[str, str],
        team_lookup: dict[str, str],
    ) -> str:
        if question_type == "driver_comparison":
            return self._render_driver_comparison(packet, context, driver_lookup, team_lookup)
        if question_type == "group_zero_podium":
            return self._render_zero_podium(packet, context, driver_lookup, team_lookup)
        if question_type == "rank_explanation":
            return self._render_rank_explanation(packet, context, driver_lookup, team_lookup)
        if question_type == "driver_explanation":
            return self._render_driver_explanation(packet, context, driver_lookup, team_lookup)
        return self._render_general_explanation(packet, context, driver_lookup)

    def _render_rank_explanation(
        self,
        packet: dict[str, Any],
        context: dict[str, Any],
        driver_lookup: dict[str, str],
        team_lookup: dict[str, str],
    ) -> str:
        rows = context["probability_rows"]
        if not rows:
            return "当前预测没有足够概率行来解释这个排名问题。"
        ranked = sorted(rows, key=lambda row: row["expected_rank"] or 999)
        driver = ranked[0]
        driver_id = driver["driver_id"]
        name = driver_lookup.get(driver_id, driver_id)
        top_win = sorted(context["all_probability_rows"], key=lambda row: row["win"], reverse=True)[0]
        feature_lines = self._driver_feature_lines(driver_id, context, team_lookup, driver_lookup, limit=4)
        score = context["score_breakdown"].get(driver_id, {})
        quali = self._qualifying_line(driver_id, context, driver_lookup)
        lines = [
            f"这里要先区分两个口径：{name} 是按平均完赛名次排第一，"
            f"不是按冠军概率排第一。当前预测里 {name} 的平均完赛名次是 {driver['average_finish']:.3f}，"
            f"预计排名为第 {driver['expected_rank']}；冠军概率第一的是 "
            f"{driver_lookup.get(top_win['driver_id'], top_win['driver_id'])}（{_pct(top_win['win'])}）。",
            f"{name} 能在平均完赛名次上排到第一，主要因为模型给了他很高的领奖台概率 "
            f"({_pct(driver['podium'])}) 和积分区概率 ({_pct(driver['points'])})，坏结果尾部比其他争冠车手略低。",
        ]
        if quali:
            lines.append(quali)
        if score:
            note = self._single_score_note(driver_id, context, driver_lookup)
            if note:
                lines.append(note)
        if feature_lines:
            lines.append("最直接支撑这个判断的输入包括：" + "；".join(feature_lines) + "。")
        lines.append(_diagnostic_sentence(packet))
        return "\n\n".join(lines)

    def _render_driver_comparison(
        self,
        packet: dict[str, Any],
        context: dict[str, Any],
        driver_lookup: dict[str, str],
        team_lookup: dict[str, str],
    ) -> str:
        rows = context["probability_rows"]
        if len(rows) < 2:
            return "当前问题像是车手对比，但我没有在问题中识别到两个可比较的车手。"
        rows = sorted(rows, key=lambda row: row["win"], reverse=True)
        high, low = rows[0], rows[-1]
        high_name = driver_lookup.get(high["driver_id"], high["driver_id"])
        low_name = driver_lookup.get(low["driver_id"], low["driver_id"])
        high_features = self._driver_feature_lines(
            high["driver_id"], context, team_lookup, driver_lookup, limit=3, polarity="positive"
        )
        low_features = self._driver_feature_lines(
            low["driver_id"], context, team_lookup, driver_lookup, limit=3, polarity="negative"
        )
        score_note = self._score_comparison_note(
            high["driver_id"], low["driver_id"], context, driver_lookup, team_lookup
        )
        same_team_note = self._same_team_note(high["driver_id"], low["driver_id"], context, team_lookup)
        impact_lines = self._impact_lines(context, driver_lookup, limit=3)
        lines = [
            f"当前预测中，{high_name} 的冠军概率是 {_pct(high['win'])}，{low_name} 的冠军概率是 {_pct(low['win'])}；"
            f"领奖台概率分别是 {_pct(high['podium'])} 和 {_pct(low['podium'])}。"
            f"两人同队，所以这不应该被解释成 Ferrari 赛车本身一边强一边弱；更需要检查的是，模型内部是否把静态车手先验、"
            f"同场排位、近期正赛速度特征和可靠性输入混在一起后放大了差距。",
        ]
        if same_team_note:
            lines.append(same_team_note)
        if score_note:
            lines.append(score_note)
        lines.append(
            f"{high_name} 这边最强的可追溯支撑输入是："
            + ("；".join(high_features) if high_features else "当前没有足够可追溯特征行。")
        )
        lines.append(
            f"{low_name} 这边最明显的可追溯弱项是："
            + ("；".join(low_features) if low_features else "当前没有明显负向特征行。")
        )
        if impact_lines:
            lines.append("Codex 证据层对这组对比的可见影响包括：" + "；".join(impact_lines) + "。")
        lines.append(_diagnostic_sentence(packet))
        return "\n\n".join(lines)

    def _render_zero_podium(
        self,
        packet: dict[str, Any],
        context: dict[str, Any],
        driver_lookup: dict[str, str],
        team_lookup: dict[str, str],
    ) -> str:
        zero_rows = [
            row for row in context["all_probability_rows"]
            if row["podium"] <= 0.0
        ]
        zero_rows.sort(key=lambda row: (row["average_finish"], -row["expected_points"]))
        if not zero_rows:
            return "当前预测没有领奖台概率为 0 的车手，所以这个问题不适用于该预测包。"
        leader = zero_rows[0]
        leader_name = driver_lookup.get(leader["driver_id"], leader["driver_id"])
        next_rows = zero_rows[1:4]
        comparison = "、".join(
            f"{driver_lookup.get(row['driver_id'], row['driver_id'])} 平均完赛名次 {row['average_finish']:.3f}，期望积分 {row['expected_points']:.3f}"
            for row in next_rows
        )
        feature_lines = self._driver_feature_lines(leader["driver_id"], context, team_lookup, driver_lookup, limit=4)
        score = context["score_breakdown"].get(leader["driver_id"], {})
        lines = [
            f"{leader_name} 在领奖台概率为 0 的车手里排第一，是因为这个排序看的是整场完赛分布，"
            f"不是看领奖台尾部的小概率。当前他没有在本次采样中抽到领奖台，但平均完赛名次是 {leader['average_finish']:.3f}、"
            f"期望积分是 {leader['expected_points']:.3f}、积分区概率是 {_pct(leader['points'])}，"
            f"在零领奖台组里比后面的车手略好。",
        ]
        if comparison:
            lines.append(f"同组后续几名是：{comparison}。这个差距说明他更像是模型里的积分区边缘车手，而不是领奖台候选。")
        if score:
            note = self._single_score_note(leader["driver_id"], context, driver_lookup)
            if note:
                lines.append(note)
        anomaly = self._zero_podium_anomaly_note(leader["driver_id"], context, driver_lookup, team_lookup)
        if anomaly:
            lines.append(anomaly)
        if feature_lines:
            lines.append("相关输入包括：" + "；".join(feature_lines) + "。")
        lines.append(
            "同时要注意：1200 次蒙特卡洛采样下，领奖台概率为 0 也可能是采样分辨率问题，"
            "它更准确的含义是“在当前采样和权重下没有抽到领奖台”，不是数学上的绝对不可能。"
        )
        lines.append(_diagnostic_sentence(packet))
        return "\n\n".join(lines)

    def _render_driver_explanation(
        self,
        packet: dict[str, Any],
        context: dict[str, Any],
        driver_lookup: dict[str, str],
        team_lookup: dict[str, str],
    ) -> str:
        row = context["probability_rows"][0] if context["probability_rows"] else None
        if row is None:
            return "我没有在问题中识别到可解释的车手。"
        driver_id = row["driver_id"]
        name = driver_lookup.get(driver_id, driver_id)
        feature_lines = self._driver_feature_lines(driver_id, context, team_lookup, driver_lookup, limit=5)
        impact_lines = self._impact_lines(context, driver_lookup, limit=3)
        lines = [
            f"{name} 当前预测：预计排名第 {row['expected_rank']}，冠军概率 {_pct(row['win'])}，"
            f"领奖台概率 {_pct(row['podium'])}，期望积分 {row['expected_points']:.3f}，"
            f"平均完赛名次 {row['average_finish']:.3f}。"
        ]
        if feature_lines:
            lines.append("主要输入：" + "；".join(feature_lines) + "。")
        if impact_lines:
            lines.append("Codex 证据影响：" + "；".join(impact_lines) + "。")
        lines.append(_diagnostic_sentence(packet))
        return "\n\n".join(lines)

    def _render_general_explanation(
        self,
        packet: dict[str, Any],
        context: dict[str, Any],
        driver_lookup: dict[str, str],
    ) -> str:
        rows = sorted(context["all_probability_rows"], key=lambda row: row["expected_rank"] or 999)[:5]
        top = "；".join(
            f"第 {row['expected_rank']} 名 {driver_lookup.get(row['driver_id'], row['driver_id'])}，"
            f"冠军概率 {_pct(row['win'])}，领奖台概率 {_pct(row['podium'])}，期望积分 {row['expected_points']:.2f}"
            for row in rows
        )
        track = context.get("track_context") or {}
        lines = [
            f"当前预测按平均完赛名次排序的前五名是：{top}。",
            f"本次预测的主要信息层包括结构化特征、Codex 因子追踪、同场排位和练习赛圈速、"
            f"赛道向量以及比赛时间模拟器。赛道类型为 {_track_type_label(track.get('track_type'))}，"
            f"安全车概率估计值为 {track.get('safety_car_probability')}，湿地概率估计值为 {track.get('wet_probability')}。",
            _diagnostic_sentence(packet),
        ]
        return "\n\n".join(lines)

    def _driver_feature_lines(
        self,
        driver_id: str,
        context: dict[str, Any],
        team_lookup: dict[str, str],
        driver_lookup: dict[str, str],
        limit: int,
        polarity: str = "strongest",
    ) -> list[str]:
        payload = (context.get("feature_context") or {}).get(driver_id, {})
        features = payload.get("features") or payload.get("top_features") or []
        if polarity == "positive":
            features = [row for row in features if _as_float(row.get("weighted_value")) > 0.0]
            features = sorted(features, key=lambda row: _as_float(row.get("weighted_value")), reverse=True)
        elif polarity == "negative":
            features = [row for row in features if _as_float(row.get("weighted_value")) < 0.0]
            features = sorted(features, key=lambda row: abs(_as_float(row.get("weighted_value"))), reverse=True)
        elif polarity == "strongest":
            features = sorted(features, key=lambda row: abs(_as_float(row.get("weighted_value"))), reverse=True)
        lines = []
        for row in features[:limit]:
            lines.append(_feature_line(row, team_lookup, driver_lookup))
        return lines

    def _single_score_note(
        self,
        driver_id: str,
        context: dict[str, Any],
        driver_lookup: dict[str, str],
    ) -> str:
        scores = context.get("score_breakdown") or {}
        score = scores.get(driver_id)
        if not score:
            return ""
        name = driver_lookup.get(driver_id, driver_id)
        unsupported = _unsupported_prior_labels(score.get("race_components") or {})
        if not unsupported:
            return ""
        return (
            f"我不会再把 {name} 的内部能力分当作解释证据来展示。这个分数里混有"
            f"{'、'.join(unsupported)}等静态 seed 先验；这些先验来自本地种子数据，不是由本场新闻、排位、练习赛、"
            "近期分站结果或车队技术信息直接计算出来的事实。除非这些先验被重新标定并绑定来源，否则它们只能作为模型风险提示，"
            "不能作为“为什么预测如此”的证据。"
        )

    def _score_comparison_note(
        self,
        high_driver_id: str,
        low_driver_id: str,
        context: dict[str, Any],
        driver_lookup: dict[str, str],
        team_lookup: dict[str, str],
    ) -> str | None:
        scores = context.get("score_breakdown") or {}
        high = scores.get(high_driver_id)
        low = scores.get(low_driver_id)
        if not high or not low:
            return None
        high_name = driver_lookup.get(high_driver_id, high_driver_id)
        low_name = driver_lookup.get(low_driver_id, low_driver_id)
        high_static = _unsupported_prior_labels(high.get("race_components") or {})
        low_static = _unsupported_prior_labels(low.get("race_components") or {})
        shared_static = list(dict.fromkeys([*high_static, *low_static]))
        traceable = self._traceable_comparison_summary(high_driver_id, low_driver_id, context, driver_lookup, team_lookup)
        lines = [
            "这里不能再用内部能力分差值来解释结果。那个分数混合了两类东西：一类是排位、练习赛、近期分站、官方积分榜等可追溯输入；"
            "另一类是本地 seed 数据里的静态先验。静态先验没有本场事实来源，不能被当作解释证据。",
        ]
        if traceable:
            lines.append(traceable)
        if shared_static:
            lines.append(
                "不可直接采信的静态先验包括：" + "、".join(shared_static) + "。这些先验来自本地种子数据，"
                "不是由 Ham/Lec 英国站前的同队近期表现自动推导出来的。"
            )
        lines.append(
            f"因此，当前解释不应该说“{high_name} 的内部正赛能力分高，所以 {low_name} 胜率低”。"
            "更准确的结论是：可追溯输入不足以单独证明这么大的队内差距，当前模型很可能把静态车手先验或近期特征映射放大了。"
        )
        return "\n\n".join(lines)

    @staticmethod
    def _traceable_comparison_summary(
        high_driver_id: str,
        low_driver_id: str,
        context: dict[str, Any],
        driver_lookup: dict[str, str],
        team_lookup: dict[str, str],
    ) -> str:
        qualifying_rows = context.get("qualifying_context", {}).get("selected_positions") or []
        positions = {
            row.get("driver_id"): row.get("qualifying_position")
            for row in qualifying_rows
            if isinstance(row, dict)
        }
        parts = []
        if high_driver_id in positions and low_driver_id in positions:
            parts.append(
                f"同场排位里，{driver_lookup.get(low_driver_id, low_driver_id)} 是第 {positions[low_driver_id]}，"
                f"{driver_lookup.get(high_driver_id, high_driver_id)} 是第 {positions[high_driver_id]}；"
                "这条可追溯事实并不支持把前者明显压低。"
            )
        low_features = (context.get("feature_context") or {}).get(low_driver_id, {}).get("features") or []
        notable_negative = [
            row for row in low_features
            if _as_float(row.get("weighted_value")) < 0 and row.get("metric") in {"race_pace", "reliability"}
        ][:3]
        if notable_negative:
            parts.append(
                f"{driver_lookup.get(low_driver_id, low_driver_id)} 的可追溯负面输入主要是："
                + "；".join(_feature_line(row, team_lookup, driver_lookup, include_direction=False) for row in notable_negative)
                + "。"
            )
        return " ".join(parts)

    @staticmethod
    def _zero_podium_anomaly_note(
        driver_id: str,
        context: dict[str, Any],
        driver_lookup: dict[str, str],
        team_lookup: dict[str, str],
    ) -> str:
        feature_context = context.get("feature_context") or {}
        payload = feature_context.get(driver_id) or {}
        features = payload.get("features") or []
        score = (context.get("score_breakdown") or {}).get(driver_id) or {}
        negative_facts = [
            row for row in features
            if _as_float(row.get("weighted_value")) < 0
            and row.get("metric") in {"race_pace", "qualifying_pace", "reliability"}
        ][:5]
        unsupported = _unsupported_prior_labels(score.get("race_components") or {})
        if not negative_facts or not unsupported:
            return ""
        driver_name = driver_lookup.get(driver_id, driver_id)
        team_id = payload.get("team_id")
        team_name = team_lookup.get(team_id, team_id)
        return (
            f"这正是当前预测最值得怀疑的地方：{driver_name} 排在这个分组第一，并不是因为可追溯事实显示 "
            f"{team_name} 近期很强。相反，可追溯输入里有明显负面信号："
            + "；".join(_feature_line(row, team_lookup, driver_lookup, include_direction=False) for row in negative_facts)
            + "。模型仍然把他放到这个分组第一，主要说明静态 seed 先验仍在抬高他，涉及"
            + "、".join(unsupported)
            + "等没有本场事实来源的先验。这个结论应标记为模型校准问题，而不是被解释成合理预测。"
        )

    @staticmethod
    def _impact_lines(context: dict[str, Any], driver_lookup: dict[str, str], limit: int) -> list[str]:
        rows = context.get("evidence_impact_context") or []
        lines = []
        for row in rows[:limit]:
            affected = row.get("affected_outcomes") or []
            relevant = []
            for item in affected:
                if not isinstance(item, dict):
                    continue
                win_delta = _as_float(item.get("win_delta"))
                points_delta = _as_float(item.get("expected_points_delta"))
                relevant.append(
                    f"{driver_lookup.get(str(item.get('driver_id')), str(item.get('driver_id')))} "
                    f"方向为{_delta_direction(win_delta, points_delta)}、幅度为{_delta_bucket(win_delta, points_delta)}"
                )
            lines.append(
                f"{_metric_label(row.get('metric'))}证据的同种子移除对比：{'；'.join(relevant)}"
            )
        return lines

    @staticmethod
    def _same_team_note(
        driver_a: str,
        driver_b: str,
        context: dict[str, Any],
        team_lookup: dict[str, str],
    ) -> str | None:
        feature_context = context.get("feature_context") or {}
        team_a = feature_context.get(driver_a, {}).get("team_id")
        team_b = feature_context.get(driver_b, {}).get("team_id")
        if not team_a or team_a != team_b:
            return None
        return (
            f"两人同队，因此 {team_lookup.get(team_a, team_a)} 的车队级正赛速度、排位速度和策略输入"
            "会同时作用到两人；真正拉开两人的，是车手级排位结果、单圈/长距离练习赛特征、"
            "近期正赛状态和基础车手先验。"
        )

    @staticmethod
    def _qualifying_line(driver_id: str, context: dict[str, Any], driver_lookup: dict[str, str]) -> str | None:
        rows = context.get("qualifying_context", {}).get("selected_positions") or []
        for row in rows:
            if row.get("driver_id") == driver_id:
                return (
                    f"排位输入方面，{driver_lookup.get(driver_id, driver_id)} 的同场排位名次是 "
                    f"第 {row.get('qualifying_position')}，这个输入主要影响发车顺序和起步后的赛道位置。"
                )
        return None

    @staticmethod
    def _limitations(packet: dict[str, Any], context: dict[str, Any]) -> list[str]:
        readiness = context.get("readiness") or {}
        limitations = []
        if readiness.get("status") != "ready_for_paper_review":
            limitations.append("当前预测包状态不是正式可用于盈利优势判断，只能用于诊断解释。")
        for code in readiness.get("blocker_codes") or []:
            limitations.append(f"正式使用前需要解决阻塞项：{_blocker_label(code)}。")
        codex_counts = context.get("codex_counts") or {}
        if codex_counts.get("weak_evidence_quality_count"):
            limitations.append("部分 Codex 证据仍然偏弱或需要复核，解释中相关判断不能当作强事实。")
        if int(packet.get("iterations") or 0) < 5000:
            limitations.append("当前蒙特卡洛采样次数较低，小概率事件和 0% 概率可能受采样分辨率影响。")
        return list(dict.fromkeys(limitations))

    @staticmethod
    def _confidence(packet: dict[str, Any], context: dict[str, Any]) -> str:
        blockers = (context.get("readiness") or {}).get("blocker_codes") or []
        weak = (context.get("codex_counts") or {}).get("weak_evidence_quality_count") or 0
        if blockers or weak:
            return "diagnostic_medium_for_model_mechanics_low_for_real_world_edge"
        return "medium"

    @staticmethod
    def _supporting_evidence(
        context: dict[str, Any],
        driver_lookup: dict[str, str],
        max_evidence: int,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for driver_id, payload in (context.get("feature_context") or {}).items():
            for feature in payload.get("top_features") or []:
                rows.append(
                    {
                        "kind": "feature_adjustment",
                        "label": (
                            f"{driver_lookup.get(driver_id, driver_id)}："
                            f"{_metric_label(feature.get('metric'))}：{_scope_label(feature.get('scope'))}"
                        ),
                        "detail": _feature_explanation_zh(feature),
                        "weighted_value": feature.get("weighted_value"),
                        "source": feature.get("source"),
                    }
                )
        for row in context.get("evidence_impact_context") or []:
            rows.append(
                {
                    "kind": "codex_evidence_impact",
                    "label": f"{_metric_label(row.get('metric'))}证据影响",
                    "detail": "同种子移除该证据后，只展示相关车手影响方向和幅度等级，不把原始内部数值当成解释。",
                    "metric": _metric_label(row.get("metric")),
                    "max_win_probability_delta": row.get("max_win_probability_delta"),
                }
            )
        rows.sort(
            key=lambda row: max(
                abs(_as_float(row.get("weighted_value"))),
                abs(_as_float(row.get("max_win_probability_delta"))),
            ),
            reverse=True,
        )
        return rows[:max_evidence]

    @staticmethod
    def _codex_context(packet: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_id": packet.get("event_id"),
            "event_name": packet.get("event_name"),
            "generated_at": packet.get("generated_at"),
            "knowledge_cutoff": packet.get("knowledge_cutoff"),
            "iterations": packet.get("iterations"),
            "status": packet.get("status"),
            "packet_payload_sha256": packet.get("packet_payload_sha256"),
            "answer_contract": {
                "use_only_context": True,
                "must_state_diagnostic_status": packet.get("status") != "ready_for_paper_review",
                "do_not_claim_stable_edge": True,
                "say_missing_when_context_is_insufficient": True,
            },
            "evidence_context": _public_evidence_context(context),
        }

    @staticmethod
    def _codex_prompt(question: str, codex_context: dict[str, Any], language: str) -> str:
        return (
            "你是和 F1Predict 后端可解释性模块协作的 Codex。\n"
            "请只使用下面 JSON 上下文回答用户关于预测结果的问题。不要编造来源，不要声称已经证明稳定盈利优势，"
            "必须区分模型机制解释和真实世界强结论。如果上下文不足，请明确说明缺少哪类产物或输入。\n"
            f"回答语言：{language}\n"
            f"用户问题：{question}\n"
            "上下文 JSON：\n"
            f"{json.dumps(codex_context, ensure_ascii=False, indent=2)}\n"
        )

    @staticmethod
    def _explanation_id(run_id: str, question: str) -> str:
        digest = hashlib.sha256(question.encode("utf-8")).hexdigest()[:10]
        return safe_name(f"{run_id}_{digest}")


def _read_json(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected JSON object")
    return payload


def _public_evidence_context(context: dict[str, Any]) -> dict[str, Any]:
    """Return the user/API-visible context without raw internal score weights."""

    public = json.loads(json.dumps(context, ensure_ascii=False))
    score_breakdown = public.pop("score_breakdown", None)
    _redact_public_feature_context(public)
    _redact_public_factor_traces(public)
    _redact_public_evidence_impacts(public)
    _redact_public_track_context(public)
    audit: dict[str, Any] = {}
    if isinstance(score_breakdown, dict):
        for driver_id, score in score_breakdown.items():
            if not isinstance(score, dict):
                continue
            components = {}
            components.update(score.get("race_components") or {})
            components.update(score.get("qualifying_components") or {})
            labels = _unsupported_prior_labels(components)
            if labels:
                audit[driver_id] = {
                    "status": "unsupported_static_priors_redacted",
                    "unsupported_static_prior_labels": labels,
                    "note": (
                        "这些静态先验只能作为模型风险提示，不能作为解释证据；"
                        "需要重新标定并绑定信息来源后才能用于回答用户为什么。"
                    ),
                }
    if audit:
        public["model_prior_audit"] = audit
    public["internal_fields_redacted"] = [
        "内部能力分明细",
        "特征归一化数值、置信度和加权影响",
        "指标加权汇总",
        "证据路线原始影响权重",
        "同种子对比原始概率差值",
        "未经来源化解释的归一化赛道指数",
    ]
    return public


def _public_supporting_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    public_rows = []
    for row in rows:
        public = dict(row)
        public.pop("weighted_value", None)
        public.pop("max_win_probability_delta", None)
        public_rows.append(public)
    return public_rows


def _redact_public_feature_context(public: dict[str, Any]) -> None:
    feature_context = public.get("feature_context")
    if not isinstance(feature_context, dict):
        return
    for driver_context in feature_context.values():
        if not isinstance(driver_context, dict):
            continue
        for key in ("features", "top_features"):
            rows = driver_context.get(key)
            if isinstance(rows, list):
                driver_context[key] = [_public_feature_row(row) for row in rows if isinstance(row, dict)]
        driver_context.pop("metric_weighted_totals", None)
        driver_context["redaction_note"] = (
            "公开解释只保留事实来源、指标方向和原始说明；"
            "归一化取值、置信度和加权影响不作为解释证据展示。"
        )


def _public_feature_row(row: dict[str, Any]) -> dict[str, Any]:
    weighted = _as_float(row.get("weighted_value"))
    direction = "positive" if weighted > 0 else "negative" if weighted < 0 else "neutral"
    direction_label = "正向" if weighted > 0 else "负向" if weighted < 0 else "中性"
    return {
        "kind": row.get("kind"),
        "scope": row.get("scope"),
        "feature_id": row.get("feature_id"),
        "source": row.get("source"),
        "target_type": row.get("target_type"),
        "target_id": row.get("target_id"),
        "metric": row.get("metric"),
        "direction": direction,
        "direction_label": direction_label,
        "explanation": row.get("explanation"),
    }


def _redact_public_factor_traces(public: dict[str, Any]) -> None:
    rows = public.get("factor_trace_context")
    if not isinstance(rows, list):
        return
    public["factor_trace_context"] = [
        {
            "claim_id": row.get("claim_id"),
            "target_type": row.get("target_type"),
            "target_id": row.get("target_id"),
            "claim_type": row.get("claim_type"),
            "metric": row.get("metric"),
            "direction": row.get("direction"),
            "route": row.get("route"),
            "model_surface": row.get("model_surface"),
            "route_status": row.get("route_status"),
            "quality_status": row.get("quality_status"),
            "source_status": row.get("source_status"),
            "triangulation_status": row.get("triangulation_status"),
            "conflict_status": row.get("conflict_status"),
            "risk_flags": row.get("risk_flags") or [],
            "redaction_note": (
                "公开解释不展示原始影响值、加权输入值、模型输入权重或上下文乘数；"
                "这些只能用于内部调试。"
            ),
        }
        for row in rows
        if isinstance(row, dict)
    ]


def _redact_public_evidence_impacts(public: dict[str, Any]) -> None:
    rows = public.get("evidence_impact_context")
    if not isinstance(rows, list):
        return
    redacted = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        outcomes = []
        for outcome in row.get("affected_outcomes") or []:
            if not isinstance(outcome, dict):
                continue
            win_delta = _as_float(outcome.get("win_delta"))
            points_delta = _as_float(outcome.get("expected_points_delta"))
            outcomes.append(
                {
                    "driver_id": outcome.get("driver_id"),
                    "direction_label": _delta_direction(win_delta, points_delta),
                    "magnitude_label": _delta_bucket(win_delta, points_delta),
                }
            )
        redacted.append(
            {
                "claim_id": row.get("claim_id"),
                "source": row.get("source"),
                "target_type": row.get("target_type"),
                "target_id": row.get("target_id"),
                "metric": row.get("metric"),
                "direction": row.get("direction"),
                "attribution_method": row.get("attribution_method"),
                "affected_outcomes": outcomes,
                "interpretation": row.get("interpretation"),
                "redaction_note": (
                    "公开解释只展示同种子移除对比的方向和幅度等级，"
                    "不展示原始概率差值或内部输入权重。"
                ),
            }
        )
    public["evidence_impact_context"] = redacted


def _redact_public_track_context(public: dict[str, Any]) -> None:
    track = public.get("track_context")
    if not isinstance(track, dict):
        return
    public["track_context"] = {
        "track_type": track.get("track_type"),
        "corner_count": track.get("corner_count"),
        "high_speed_corner_count": track.get("high_speed_corner_count"),
        "long_straight_count": track.get("long_straight_count"),
        "provenance": track.get("provenance") or {},
        "redaction_note": (
            "公开解释不展示未经来源化解释的归一化赛道指数；"
            "赛道指数需要绑定弯角、直道、DRS/替代系统、天气和沥青来源后才能前端展示。"
        ),
    }


def _probability_rows(packet: dict[str, Any]) -> list[dict[str, Any]]:
    rows = packet.get("prediction", {}).get("race_probabilities") or []
    return [row for row in rows if isinstance(row, dict) and row.get("driver_id")]


def _probability_context(packet: dict[str, Any], driver_ids: list[str]) -> list[dict[str, Any]]:
    all_rows = _probability_rows(packet)
    rank_by_finish = {
        row["driver_id"]: index
        for index, row in enumerate(
            sorted(all_rows, key=lambda item: (_as_float(item.get("average_finish"), 99.0), -_as_float(item.get("expected_points")))),
            start=1,
        )
    }
    win_rank = {
        row["driver_id"]: index
        for index, row in enumerate(sorted(all_rows, key=lambda item: _as_float(item.get("win")), reverse=True), start=1)
    }
    selected = []
    for row in all_rows:
        if row["driver_id"] not in driver_ids:
            continue
        selected.append(
            {
                "driver_id": row["driver_id"],
                "win": _round(row.get("win"), 6),
                "podium": _round(row.get("podium"), 6),
                "points": _round(row.get("points"), 6),
                "expected_points": _round(row.get("expected_points"), 6),
                "average_finish": _round(row.get("average_finish"), 6),
                "expected_rank": rank_by_finish.get(row["driver_id"]),
                "win_rank": win_rank.get(row["driver_id"]),
            }
        )
    return sorted(selected, key=lambda row: row["expected_rank"] or 999)


def _ranked_by_average_finish(packet: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _probability_context(packet, [row["driver_id"] for row in _probability_rows(packet)])
    return sorted(rows, key=lambda row: row["expected_rank"] or 999)


def _race_event_from_packet(raw: dict[str, Any]) -> RaceEvent:
    payload = dict(raw)
    payload.setdefault("actual_result", [])
    payload.setdefault("feature_refs", {})
    payload.setdefault("track_map", [])
    return RaceEvent(
        event_id=str(payload.get("event_id") or ""),
        name=str(payload.get("name") or payload.get("event_name") or payload.get("event_id") or ""),
        round_number=int(payload.get("round_number") or 0),
        date=str(payload.get("date") or ""),
        track_type=str(payload.get("track_type") or "balanced"),
        laps=int(payload.get("laps") or 0),
        completed=bool(payload.get("completed")),
        weather_prior=dict(payload.get("weather_prior") or {}),
        track_map=list(payload.get("track_map") or []),
        actual_result=list(payload.get("actual_result") or []),
        feature_refs=dict(payload.get("feature_refs") or {}),
    )


def _driver_display_lookup(season: Any) -> dict[str, str]:
    return {driver_id: driver.name for driver_id, driver in season.drivers.items()}


def _team_display_lookup(season: Any) -> dict[str, str]:
    return {team_id: team.name for team_id, team in season.teams.items()}


def _components_dict(breakdown: dict[str, float]) -> dict[str, float]:
    return {
        key: round(float(value), 5)
        for key, value in breakdown.items()
        if key != "total" and abs(float(value)) > 0.00001
    }


def _top_components(breakdown: dict[str, float], limit: int) -> list[dict[str, Any]]:
    rows = [
        {"component": key, "value": round(float(value), 5)}
        for key, value in breakdown.items()
        if key != "total" and abs(float(value)) > 0.00001
    ]
    rows.sort(key=lambda row: abs(row["value"]), reverse=True)
    return rows[:limit]


def _component_lines(components: dict[str, Any], limit: int) -> list[str]:
    rows = [
        (key, _as_float(value))
        for key, value in components.items()
        if abs(_as_float(value)) > 0.00001
    ]
    rows.sort(key=lambda item: abs(item[1]), reverse=True)
    return [f"{_component_label(key)} {value:+.5f}" for key, value in rows[:limit]]


def _component_delta_lines(
    high_components: dict[str, Any],
    low_components: dict[str, Any],
    high_name: str,
    low_name: str,
    limit: int,
) -> list[str]:
    keys = set(high_components) | set(low_components)
    rows = []
    for key in keys:
        high_value = _as_float(high_components.get(key))
        low_value = _as_float(low_components.get(key))
        diff = high_value - low_value
        if abs(diff) > 0.005:
            rows.append((key, high_value, low_value, diff))
    rows.sort(key=lambda item: abs(item[3]), reverse=True)
    return [
        (
            f"{_component_label(key)}：{high_name} {high_value:+.5f}，"
            f"{low_name} {low_value:+.5f}，差值 {diff:+.5f}"
        )
        for key, high_value, low_value, diff in rows[:limit]
    ]


def _unsupported_prior_labels(components: dict[str, Any]) -> list[str]:
    rows = []
    for key, value in components.items():
        if key in STATIC_PRIOR_COMPONENTS and abs(_as_float(value)) > 0.00001:
            rows.append((key, abs(_as_float(value))))
    rows.sort(key=lambda item: item[1], reverse=True)
    return [_component_label(key) for key, _ in rows]


def _feature_line(
    row: dict[str, Any],
    team_lookup: dict[str, str],
    driver_lookup: dict[str, str],
    include_direction: bool = True,
) -> str:
    scope = str(row.get("scope") or "")
    target = str(row.get("target_id") or "")
    target_label = team_lookup.get(target, target) if scope == "team" else driver_lookup.get(target, target)
    weighted = _as_float(row.get("weighted_value"))
    direction = "正向" if weighted > 0 else "负向" if weighted < 0 else "中性"
    direction_text = f"，方向为{direction}" if include_direction else ""
    return (
        f"{_scope_label(scope)} {target_label} 的{_metric_label(row.get('metric'))}输入，"
        f"依据是：{_feature_explanation_zh(row)}{direction_text}"
    )


def _feature_explanation_zh(row: dict[str, Any]) -> str:
    explanation = str(row.get("explanation") or "")
    feature_id = str(row.get("feature_id") or "")
    source = str(row.get("source") or "")
    source_label = _source_label(feature_id, source)
    parts = [source_label]
    if "qualifying classification" in explanation:
        position = _clean_feature_phrase(_extract_after(explanation, ": ", ";"))
        parts.append(f"同场排位名次为 {position}，作为排位和发车位信号，不直接当作正赛速度")
    elif "qualifying team average position" in explanation:
        value = _clean_feature_phrase(_extract_after(explanation, "position before British Grand Prix: ", ";"))
        parts.append(f"同场车队平均排位名次为 {value}，作为车队排位状态输入")
    elif "team total points per race" in explanation:
        value = _clean_feature_phrase(_extract_after(explanation, "team total points per race ", ";"))
        parts.append(f"截止本场前车队每站积分对比为 {value}，作为赛车/车队强度重估")
    elif "Official constructor standings" in explanation:
        value = _clean_feature_phrase(
            _extract_after(explanation, "Official constructor standings before British Grand Prix: ", ";")
        )
        parts.append(f"官方车队积分榜信息为 {value}，作为车队状态先验")
    elif "Official driver standings" in explanation:
        value = _clean_feature_phrase(
            _extract_after(explanation, "Official driver standings before British Grand Prix: ", ";")
        )
        parts.append(f"官方车手积分榜信息为 {value}，作为车手状态先验")
    elif "long-run proxy" in explanation:
        value = _clean_feature_phrase(_extract_after(explanation, ": ", ";"))
        parts.append(f"练习赛长距离速度代理值为 {value}，作为同一比赛周末的正赛速度信号")
    elif "best valid lap" in explanation:
        value = _clean_feature_phrase(_extract_after(explanation, ": ", ";"))
        parts.append(f"排位最快有效圈速对比为 {value}，作为排位速度信号")
    elif "speed-trap average" in explanation:
        value = _clean_feature_phrase(_extract_after(explanation, ": ", ";"))
        parts.append(f"测速点均速对比为 {value}，作为直道速度信号")
    elif "tyre-degradation proxy" in explanation:
        value = _clean_feature_phrase(_extract_after(explanation, ": ", ";"))
        parts.append(f"轮胎衰退代理值为 {value}，数值方向会影响策略和长距离速度")
    elif "non-finished classification" in explanation:
        value = _clean_feature_phrase(explanation.split(";")[0])
        parts.append(f"近期未完赛记录为 {value}，作为小幅可靠性风险输入")
    elif "relative points delta" in explanation:
        value = _clean_feature_phrase(_extract_after(explanation, ": ", ";"))
        parts.append(f"近期与更早窗口的积分趋势差为 {value}，作为近期状态信号")
    elif "average points" in explanation:
        value = _clean_feature_phrase(_extract_after(explanation, ": ", ";"))
        parts.append(f"近期平均积分对比为 {value}，作为正赛状态输入")
    elif "analogue rank" in explanation:
        value = _clean_feature_phrase(_extract_after(explanation, "analogue rank ", ";"))
        parts.append(f"历史相似场景排名为 {value}，作为低置信度参考")
    elif "grid-to-finish conversion" in explanation or "grid conversion" in explanation:
        value = _clean_feature_phrase(_extract_after(explanation, ": ", ";"))
        parts.append(f"发车位到完赛名次转换表现为 {value}，作为正赛执行输入")
    elif "recent" in explanation.lower() or "window" in explanation.lower():
        parts.append("近期窗口表现被压缩成有界输入，用于移动当前状态先验")
    else:
        parts.append("原始说明未能可靠翻译，已保留为结构化数值输入而非强事实")
    return "；".join(part for part in parts if part)


def _source_label(feature_id: str, source: str) -> str:
    raw = f"{feature_id} {source}".lower()
    if "fastf1-qualifying-result" in raw or "fastf1_qualifying_result" in raw:
        return "来源：同场 FastF1 排位结果"
    if "team-strength-reestimate" in raw:
        return "来源：FastF1 本赛季车队强度重估"
    if "official-standings" in raw:
        return "来源：F1 官方积分榜"
    if "season-form" in raw:
        return "来源：FastF1 赛季累计状态"
    if "momentum" in raw:
        return "来源：FastF1 近期趋势"
    if "fastf1-form" in raw:
        return "来源：FastF1 最近几站表现"
    if "openf1" in raw:
        return "来源：OpenF1 圈速或天气特征"
    return "来源：结构化特征"


def _extract_after(text: str, start: str, end: str) -> str:
    if start not in text:
        return "未解析"
    tail = text.split(start, 1)[1]
    if end and end in tail:
        tail = tail.split(end, 1)[0]
    return tail.strip()


def _clean_feature_phrase(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("P") and len(cleaned) > 1 and cleaned[1].isdigit():
        rest = cleaned[1:]
        if "," in rest:
            rank, tail = rest.split(",", 1)
            cleaned = f"第 {rank}，{tail.strip()}"
        else:
            cleaned = "第 " + rest
    cleaned = cleaned.replace(" vs field average ", "，全场平均 ")
    cleaned = cleaned.replace(" vs field ", "，全场平均 ")
    cleaned = cleaned.replace(" vs team field ", "，车队样本平均 ")
    cleaned = cleaned.replace("relative points delta", "相对积分变化")
    cleaned = cleaned.replace("average points", "平均积分")
    cleaned = cleaned.replace("average grid", "平均发车位")
    cleaned = cleaned.replace("average opportunity-normalized grid-to-finish conversion", "机会归一化发车到完赛转换均值")
    cleaned = cleaned.replace("non-finished classification(s)", "次未完赛记录")
    cleaned = cleaned.replace("previous", "过去")
    cleaned = cleaned.replace(" over ", "，样本圈数 ")
    cleaned = cleaned.replace(" in ", "，范围为 ")
    cleaned = cleaned.replace("race result(s)", "场正赛结果")
    cleaned = cleaned.replace("finished race result(s)", "场已完赛正赛结果")
    cleaned = cleaned.replace("clean lap(s)", "个干净圈")
    cleaned = cleaned.replace("kph", "公里/小时")
    cleaned = cleaned.replace("points", "分")
    cleaned = cleaned.replace("recent window", "近期窗口")
    cleaned = cleaned.replace("s/lap", " 秒/圈")
    cleaned = re.sub(r"(?<=\d)s\b", " 秒", cleaned)
    return cleaned


def _metric_label(metric: Any) -> str:
    return METRIC_LABELS.get(str(metric), _identifier_to_zh(str(metric)))


def _component_label(component: Any) -> str:
    return COMPONENT_LABELS.get(str(component), _identifier_to_zh(str(component)))


def _scope_label(scope: Any) -> str:
    return SCOPE_LABELS.get(str(scope), _identifier_to_zh(str(scope)))


def _track_type_label(track_type: Any) -> str:
    labels = {
        "high_speed": "高速赛道",
        "balanced": "均衡赛道",
        "street": "街道赛道",
        "low_speed": "低速赛道",
    }
    return labels.get(str(track_type), _identifier_to_zh(str(track_type)))


def _identifier_to_zh(value: str) -> str:
    return value.replace("_", " ")


def _compact(value: str) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _mentions_first_rank(question: str) -> bool:
    q = _compact(question)
    return any(
        token in q
        for token in ("第一", "第1", "p1", "rank1", "第一名", "排第一", "first", "1st", "rankone", "rankedfirst")
    )


def _mentions_zero_podium(question: str) -> bool:
    q = _compact(question)
    return ("podium" in q or "领奖台" in q) and any(token in q for token in ("0", "零", "为0"))


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _round(value: Any, digits: int = 4) -> float:
    return round(_as_float(value), digits)


def _pct(value: Any) -> str:
    return f"{_as_float(value) * 100:.2f}%"


def _signed_pct(value: Any) -> str:
    return f"{_as_float(value) * 100:+.2f} 个百分点"


def _delta_direction(win_delta: float, points_delta: float) -> str:
    combined = win_delta + points_delta / 25.0
    if combined > 0.0005:
        return "正向"
    if combined < -0.0005:
        return "负向"
    return "接近中性"


def _delta_bucket(win_delta: float, points_delta: float) -> str:
    magnitude = max(abs(win_delta), abs(points_delta) / 25.0)
    if magnitude >= 0.02:
        return "中等以上"
    if magnitude >= 0.005:
        return "小幅"
    return "很小"


def _diagnostic_sentence(packet: dict[str, Any]) -> str:
    status = packet.get("status")
    blockers = "、".join(_blocker_label(code) for code in (packet.get("blocker_codes") or []))
    if status == "ready_for_paper_review":
        return "这个解释基于当前预测包；仍应结合历史回放和市场快照验证。"
    return (
        f"注意：这次预测的状态是{_status_label(status)}，阻塞项为：{blockers or '无'}。"
        "因此这是一份模型机制解释，不是稳定盈利优势证明。"
    )


def _status_label(status: Any) -> str:
    return STATUS_LABELS.get(str(status), _identifier_to_zh(str(status)))


def _blocker_label(code: Any) -> str:
    return BLOCKER_LABELS.get(str(code), _identifier_to_zh(str(code)))
