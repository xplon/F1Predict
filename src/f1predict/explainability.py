"""Prediction-result explainability helpers.

The explainer is intentionally artifact-first: it reads an already registered
prediction run and its packet, extracts the smallest relevant evidence context,
then produces both a deterministic Chinese answer and a Codex prompt that can
be used for deeper LLM-assisted follow-up without inventing unsupported facts.
"""

from __future__ import annotations

import hashlib
import json
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
            "evidence_context": self.evidence_context,
            "supporting_evidence": self.supporting_evidence,
            "codex_prompt": self.codex_prompt,
            "codex_context": self.codex_context,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Prediction Explanation: {self.event_name}",
            "",
            f"- Run: `{self.run_id}`",
            f"- Event: `{self.event_id}`",
            f"- Generated at: `{self.generated_at}`",
            f"- Question type: `{self.question_type}`",
            f"- Confidence: `{self.confidence}`",
            "",
            "## Question",
            "",
            self.question,
            "",
            "## Answer",
            "",
            self.answer,
            "",
            "## Limitations",
            "",
        ]
        for item in self.limitations:
            lines.append(f"- {item}")
        lines.extend(["", "## Supporting Evidence", ""])
        for row in self.supporting_evidence[:12]:
            label = row.get("label") or row.get("kind") or "evidence"
            detail = row.get("detail") or row.get("explanation") or row.get("reason") or ""
            lines.append(f"- **{label}**: {detail}")
        lines.extend(["", "## Codex Prompt", "", "```text", self.codex_prompt.rstrip(), "```", ""])
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
        supporting_evidence = self._supporting_evidence(context, max_evidence=max_evidence)
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
            return "当前 run 没有足够概率行来解释这个排名问题。"
        ranked = sorted(rows, key=lambda row: row["expected_rank"] or 999)
        driver = ranked[0]
        driver_id = driver["driver_id"]
        name = driver_lookup.get(driver_id, driver_id)
        top_win = sorted(context["all_probability_rows"], key=lambda row: row["win"], reverse=True)[0]
        feature_lines = self._driver_feature_lines(driver_id, context, team_lookup, limit=4)
        score = context["score_breakdown"].get(driver_id, {})
        quali = self._qualifying_line(driver_id, context, driver_lookup)
        lines = [
            f"这里要先区分两个口径：{name} 是按 expected finish/平均完赛名次排第一，"
            f"不是按冠军概率排第一。当前 run 里 {name} 的平均完赛名次是 {driver['average_finish']:.3f}，"
            f"expected rank 为 P{driver['expected_rank']}；冠军概率第一的是 "
            f"{driver_lookup.get(top_win['driver_id'], top_win['driver_id'])}（{_pct(top_win['win'])}）。",
            f"{name} 能在平均完赛名次上排到第一，主要因为模型给了他很高的领奖台概率 "
            f"({_pct(driver['podium'])}) 和积分区概率 ({_pct(driver['points'])})，坏结果尾部比其他争冠车手略低。",
        ]
        if quali:
            lines.append(quali)
        if score:
            lines.append(
                f"模型分解里，{name} 的 race score 为 {score.get('race_total')}，"
                f"qualifying score 为 {score.get('qualifying_total')}，可靠性 proxy 为 {score.get('reliability')}。"
            )
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
        high_features = self._driver_feature_lines(high["driver_id"], context, team_lookup, limit=3, polarity="positive")
        low_features = self._driver_feature_lines(low["driver_id"], context, team_lookup, limit=3, polarity="negative")
        score_note = self._score_comparison_note(high["driver_id"], low["driver_id"], context, driver_lookup)
        same_team_note = self._same_team_note(high["driver_id"], low["driver_id"], context, team_lookup)
        impact_lines = self._impact_lines(context, driver_lookup, limit=3)
        lines = [
            f"当前 run 中，{high_name} 的胜率是 {_pct(high['win'])}，{low_name} 的胜率是 {_pct(low['win'])}；"
            f"领奖台概率分别是 {_pct(high['podium'])} 和 {_pct(low['podium'])}。"
            f"这不是同一个车队强弱项造成的全部差异，主要来自车手级别的排位、练习赛长距离和近期结果输入。",
        ]
        if same_team_note:
            lines.append(same_team_note)
        if score_note:
            lines.append(score_note)
        lines.append(
            f"{high_name} 这边最强的支撑输入是：" + ("；".join(high_features) if high_features else "当前没有足够特征行。")
        )
        lines.append(
            f"{low_name} 这边最明显的弱项是：" + ("；".join(low_features) if low_features else "当前没有明显负向特征行。")
        )
        if impact_lines:
            lines.append("Codex/证据层对这组对比的可见影响包括：" + "；".join(impact_lines) + "。")
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
            return "当前 run 没有 podium 概率为 0 的车手，所以这个问题不适用于该预测包。"
        leader = zero_rows[0]
        leader_name = driver_lookup.get(leader["driver_id"], leader["driver_id"])
        next_rows = zero_rows[1:4]
        comparison = "、".join(
            f"{driver_lookup.get(row['driver_id'], row['driver_id'])} avg={row['average_finish']:.3f}, EP={row['expected_points']:.3f}"
            for row in next_rows
        )
        feature_lines = self._driver_feature_lines(leader["driver_id"], context, team_lookup, limit=4)
        score = context["score_breakdown"].get(leader["driver_id"], {})
        lines = [
            f"{leader_name} 在 podium 概率为 0 的车手里排第一，是因为这个排序看的是整场完赛分布，"
            f"不是看领奖台尾部的小概率。当前他 podium=0，但 average finish={leader['average_finish']:.3f}、"
            f"expected points={leader['expected_points']:.3f}、积分区概率={_pct(leader['points'])}，"
            f"在零领奖台组里比后面的车手略好。",
        ]
        if comparison:
            lines.append(f"同组后续几名是：{comparison}。这个差距说明他更像是模型里的积分区边缘车手，而不是领奖台候选。")
        if score:
            lines.append(
                f"模型分解里，{leader_name} 的 race score={score.get('race_total')}、"
                f"qualifying score={score.get('qualifying_total')}、可靠性 proxy={score.get('reliability')}。"
            )
        if feature_lines:
            lines.append("相关输入包括：" + "；".join(feature_lines) + "。")
        lines.append(
            "同时要注意：1200 次 Monte Carlo 下 podium=0 也可能是采样分辨率问题，"
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
        feature_lines = self._driver_feature_lines(driver_id, context, team_lookup, limit=5)
        impact_lines = self._impact_lines(context, driver_lookup, limit=3)
        lines = [
            f"{name} 当前预测：expected rank P{row['expected_rank']}，win={_pct(row['win'])}，"
            f"podium={_pct(row['podium'])}，expected points={row['expected_points']:.3f}，"
            f"average finish={row['average_finish']:.3f}。"
        ]
        if feature_lines:
            lines.append("主要输入：" + "；".join(feature_lines) + "。")
        if impact_lines:
            lines.append("Codex/证据影响：" + "；".join(impact_lines) + "。")
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
            f"P{row['expected_rank']} {driver_lookup.get(row['driver_id'], row['driver_id'])} "
            f"win={_pct(row['win'])}, podium={_pct(row['podium'])}, EP={row['expected_points']:.2f}"
            for row in rows
        )
        track = context.get("track_context") or {}
        lines = [
            f"当前预测的前五名 expected-rank 口径是：{top}。",
            f"本 run 的主要信息层包括 processed features、Codex factor trace、same-event qualifying/session laps、"
            f"赛道向量和 race-time simulator。赛道类型为 {track.get('track_type')}，"
            f"安全车概率 proxy={track.get('safety_car_probability')}，湿地概率 proxy={track.get('wet_probability')}。",
            _diagnostic_sentence(packet),
        ]
        return "\n\n".join(lines)

    def _driver_feature_lines(
        self,
        driver_id: str,
        context: dict[str, Any],
        team_lookup: dict[str, str],
        limit: int,
        polarity: str = "strongest",
    ) -> list[str]:
        features = (context.get("feature_context") or {}).get(driver_id, {}).get("top_features") or []
        if polarity == "positive":
            features = [row for row in features if _as_float(row.get("weighted_value")) > 0.0]
            features = sorted(features, key=lambda row: _as_float(row.get("weighted_value")), reverse=True)
        elif polarity == "negative":
            features = [row for row in features if _as_float(row.get("weighted_value")) < 0.0]
            features = sorted(features, key=lambda row: abs(_as_float(row.get("weighted_value"))), reverse=True)
        lines = []
        for row in features[:limit]:
            scope = row.get("scope")
            target = row.get("target_id")
            target_label = team_lookup.get(target, target) if scope == "team" else target
            lines.append(
                f"{scope}:{target_label} {row.get('metric')} 加权值 {row.get('weighted_value'):+.4f}"
                f"（{row.get('explanation')}）"
            )
        return lines

    @staticmethod
    def _score_comparison_note(
        high_driver_id: str,
        low_driver_id: str,
        context: dict[str, Any],
        driver_lookup: dict[str, str],
    ) -> str | None:
        scores = context.get("score_breakdown") or {}
        high = scores.get(high_driver_id)
        low = scores.get(low_driver_id)
        if not high or not low:
            return None
        high_name = driver_lookup.get(high_driver_id, high_driver_id)
        low_name = driver_lookup.get(low_driver_id, low_driver_id)
        high_race = _as_float(high.get("race_total"))
        low_race = _as_float(low.get("race_total"))
        high_quali = _as_float(high.get("qualifying_total"))
        low_quali = _as_float(low.get("qualifying_total"))
        high_rel = _as_float(high.get("reliability"))
        low_rel = _as_float(low.get("reliability"))
        return (
            f"更关键的是模型分解：{high_name} 的 race score={high_race:.5f}，"
            f"{low_name} 的 race score={low_race:.5f}，差值 {high_race - low_race:+.5f}；"
            f"qualifying score 分别是 {high_quali:.5f} / {low_quali:.5f}，"
            f"可靠性 proxy 分别是 {high_rel:.5f} / {low_rel:.5f}。"
            "所以即使较低胜率车手有很强排位输入，如果正赛速度、racecraft、近期 race form 或可靠性分解更弱，"
            "胜率仍会被压低。"
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
                relevant.append(
                    f"{driver_lookup.get(str(item.get('driver_id')), str(item.get('driver_id')))} "
                    f"win_delta={_signed_pct(item.get('win_delta'))}, EP_delta={item.get('expected_points_delta')}"
                )
            lines.append(f"{row.get('claim_id')} / {row.get('metric')}：{'; '.join(relevant)}")
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
            f"两人同队，因此 {team_lookup.get(team_a, team_a)} 的车队级 race_pace/qualifying_pace/strategy "
            "输入会同时作用到两人；两人的差距主要来自车手级排位结果、单圈/长距离 session 特征、"
            "近期 race form 和基础车手属性。"
        )

    @staticmethod
    def _qualifying_line(driver_id: str, context: dict[str, Any], driver_lookup: dict[str, str]) -> str | None:
        rows = context.get("qualifying_context", {}).get("selected_positions") or []
        for row in rows:
            if row.get("driver_id") == driver_id:
                return (
                    f"排位输入方面，{driver_lookup.get(driver_id, driver_id)} 的 same-event qualifying position "
                    f"是 P{row.get('qualifying_position')}，这个输入主要影响发车顺序和起步后的 track position。"
                )
        return None

    @staticmethod
    def _limitations(packet: dict[str, Any], context: dict[str, Any]) -> list[str]:
        readiness = context.get("readiness") or {}
        limitations = []
        if readiness.get("status") != "ready_for_paper_review":
            limitations.append("当前 prediction packet 状态不是正式 edge-ready，只能用于诊断解释。")
        for code in readiness.get("blocker_codes") or []:
            limitations.append(f"正式使用前需要解决 blocker：{code}。")
        codex_counts = context.get("codex_counts") or {}
        if codex_counts.get("weak_evidence_quality_count"):
            limitations.append("部分 Codex evidence 是 weak/review-required，解释中相关 claim 不能当作强事实。")
        if int(packet.get("iterations") or 0) < 5000:
            limitations.append("当前 Monte Carlo iterations 较低，小概率事件和 0% 概率可能受采样分辨率影响。")
        return list(dict.fromkeys(limitations))

    @staticmethod
    def _confidence(packet: dict[str, Any], context: dict[str, Any]) -> str:
        blockers = (context.get("readiness") or {}).get("blocker_codes") or []
        weak = (context.get("codex_counts") or {}).get("weak_evidence_quality_count") or 0
        if blockers or weak:
            return "diagnostic_medium_for_model_mechanics_low_for_real_world_edge"
        return "medium"

    @staticmethod
    def _supporting_evidence(context: dict[str, Any], max_evidence: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for driver_id, payload in (context.get("feature_context") or {}).items():
            for feature in payload.get("top_features") or []:
                rows.append(
                    {
                        "kind": "feature_adjustment",
                        "label": f"{driver_id}:{feature.get('metric')}:{feature.get('scope')}",
                        "detail": feature.get("explanation"),
                        "weighted_value": feature.get("weighted_value"),
                        "source": feature.get("source"),
                    }
                )
        for row in context.get("evidence_impact_context") or []:
            rows.append(
                {
                    "kind": "codex_evidence_impact",
                    "label": row.get("claim_id"),
                    "detail": row.get("interpretation"),
                    "metric": row.get("metric"),
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
            "evidence_context": context,
        }

    @staticmethod
    def _codex_prompt(question: str, codex_context: dict[str, Any], language: str) -> str:
        return (
            "You are Codex working with the F1Predict backend explainability module.\n"
            "Answer the user's prediction-result question using only the JSON context below. "
            "Do not invent sources, do not claim stable betting edge, and distinguish model mechanics from real-world truth. "
            "If the context is insufficient, say exactly what artifact or input is missing.\n"
            f"Language: {language}\n"
            f"Question: {question}\n"
            "Context JSON:\n"
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


def _top_components(breakdown: dict[str, float], limit: int) -> list[dict[str, Any]]:
    rows = [
        {"component": key, "value": round(float(value), 5)}
        for key, value in breakdown.items()
        if key != "total" and abs(float(value)) > 0.00001
    ]
    rows.sort(key=lambda row: abs(row["value"]), reverse=True)
    return rows[:limit]


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
    return f"{_as_float(value) * 100:+.2f}pp"


def _diagnostic_sentence(packet: dict[str, Any]) -> str:
    status = packet.get("status")
    blockers = ", ".join(packet.get("blocker_codes") or [])
    if status == "ready_for_paper_review":
        return "这个解释基于当前 prediction packet；仍应结合 replay 和市场快照验证。"
    return (
        f"注意：这个 run 的状态是 {status}，blocker={blockers or 'none'}。"
        "因此这是一份模型机制解释，不是稳定盈利 edge 证明。"
    )
