"""Lightweight smoke checks for prediction explainability."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from f1predict.api_v2 import BackendApiV2  # noqa: E402
from f1predict.explainability import PredictionExplainer  # noqa: E402


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    explainer = PredictionExplainer(ROOT)

    russell = explainer.answer("why is Russell first?", event_id="british_gp", max_evidence=5)
    _assert(russell.question_type == "rank_explanation", "Russell first question should route as rank explanation")
    _assert("russell" in russell.detected_entities["drivers"], "Russell should be detected")
    _assert("冠军概率第一" in russell.answer, "Rank answer should clarify win-probability vs expected-rank")
    _assert(russell.evidence_context["score_breakdown"].get("russell"), "Russell score breakdown should be present")
    russell_public = russell.to_dict()
    _assert(
        "score_breakdown" not in russell_public["evidence_context"],
        "Public explanation context should redact raw score breakdown",
    )
    _assert(
        "model_prior_audit" in russell_public["evidence_context"],
        "Public explanation context should keep a static-prior audit instead",
    )
    russell_public_text = json.dumps(russell_public, ensure_ascii=False)
    for forbidden in ("weighted_value", "raw_signed_impact", "weighted_input_impact", "model_input_weight"):
        _assert(forbidden not in russell_public_text, f"Public explanation should redact {forbidden}")
    _assert("score_breakdown" not in russell.codex_prompt, "Codex prompt should not expose raw score breakdown")
    _assert("weighted_value" not in russell.codex_prompt, "Codex prompt should not expose raw feature weights")

    ferrari = explainer.answer(
        "为什么勒克莱尔的胜率远低于同队的汉密尔顿？",
        event_id="british_gp",
        max_evidence=6,
    )
    _assert(ferrari.question_type == "driver_comparison", "Ferrari teammate question should route as comparison")
    _assert(
        {"hamilton", "leclerc"}.issubset(set(ferrari.detected_entities["drivers"])),
        "Hamilton and Leclerc should be detected",
    )
    _assert("不能再用内部能力分差值来解释" in ferrari.answer, "Comparison should reject raw internal score explanations")
    _assert("race" + " score" not in ferrari.answer, "User-facing answer should not expose raw English labels")
    _assert("最明显的可追溯弱项" in ferrari.answer, "Comparison should separate weak inputs from supporting inputs")
    _assert("静态车手先验" in ferrari.answer, "Comparison should flag amplified static-prior risk")

    zero_podium = explainer.answer(
        "为什么阿隆索在所有podium概率为0的车手中排第一？",
        event_id="british_gp",
        max_evidence=6,
    )
    _assert(zero_podium.question_type == "group_zero_podium", "Zero podium question should route as group explanation")
    _assert(zero_podium.detected_entities["derived_groups"], "Zero podium derived group should be present")
    _assert("采样分辨率" in zero_podium.answer, "Zero podium answer should warn about sampling resolution")

    api = BackendApiV2(ROOT)
    openapi = api.handle_get("/api/v2/openapi.json", {}).payload
    _assert(
        "/api/v2/prediction-explanations" in openapi["paths"],
        "API v2 should expose prediction explanation endpoint",
    )
    response = api.handle_post(
        "/api/v2/prediction-explanations",
        {},
        {"event_id": "british_gp", "question": "why is Russell first?", "max_evidence": 4},
    )
    _assert(response.status == 200, "API explanation POST should succeed")
    _assert(response.payload["question_type"] == "rank_explanation", "API explanation should route correctly")
    _assert("codex_prompt" in response.payload, "API explanation should include Codex prompt")
    _assert(
        "score_breakdown" not in response.payload["evidence_context"],
        "API explanation should not expose raw score breakdown",
    )
    _assert(
        "score_breakdown" not in response.payload["codex_prompt"],
        "API Codex prompt should not expose raw score breakdown",
    )
    response_public_text = json.dumps(response.payload, ensure_ascii=False)
    for forbidden in ("weighted_value", "raw_signed_impact", "weighted_input_impact", "model_input_weight"):
        _assert(forbidden not in response_public_text, f"API explanation should redact {forbidden}")

    print("explainability smoke ok")


if __name__ == "__main__":
    main()
