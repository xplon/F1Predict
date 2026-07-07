"""Lightweight smoke checks for traceable prediction explainability."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from f1predict.api_v2 import BackendApiV2  # noqa: E402
from f1predict.explainability import PredictionExplainer  # noqa: E402


KNOWLEDGE_CUTOFF = "2026-07-05T00:00:00+00:00"


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _assert_traceable_context(payload: dict, label: str) -> None:
    context = payload["evidence_context"]
    belief = context.get("belief_state_context") or {}
    updates = context.get("state_update_context") or {}
    impacts = context.get("prediction_impact_trace_context") or {}
    _assert(belief.get("state_id"), f"{label}: BeliefState id should be present")
    _assert(belief.get("raw_source_count", 0) > 0, f"{label}: raw source count should be present")
    _assert(updates.get("top_updates"), f"{label}: state update rows should be present")
    _assert(impacts.get("top_traces"), f"{label}: prediction impact traces should be present")
    _assert(
        impacts.get("isolated_prediction_impact_trace_count", 0) > 0,
        f"{label}: isolated same-seed traces should be present",
    )
    _assert("score_breakdown" not in context, f"{label}: public context should redact score_breakdown")
    _assert("model_prior_audit" in context, f"{label}: public context should include seed-prior audit")


def _assert_no_raw_internal_fields(payload: dict, label: str) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    forbidden = (
        "score_breakdown",
        "weighted_value",
        "raw_signed_impact",
        "weighted_input_impact",
        "model_input_weight",
        "race_top_components",
        "qualifying_top_components",
    )
    for field in forbidden:
        _assert(field not in text, f"{label}: public explanation should redact {field}")


def _assert_public_packet_seed_separation(payload: dict) -> None:
    prediction = payload.get("prediction") or {}
    public_text = json.dumps(
        {
            "evidence": prediction.get("evidence") or [],
            "evidence_quality": prediction.get("evidence_quality") or [],
            "factor_trace": prediction.get("factor_trace") or [],
            "belief_raw_sources": (prediction.get("belief_state") or {}).get("raw_sources") or [],
        },
        ensure_ascii=False,
    )
    _assert("seed://" not in public_text, "Latest packet public evidence should not expose seed:// sources")
    _assert(
        "seed_scenario_source" not in public_text,
        "Latest packet public evidence should not expose seed scenario risk rows",
    )
    blocked = prediction.get("blocked_development_evidence") or {}
    if blocked.get("claim_count", 0):
        blocked_text = json.dumps(blocked, ensure_ascii=False)
        _assert("seed://" in blocked_text, "Blocked seed evidence should remain auditable in a separated section")


def _assert_public_explanation_text_is_localized(payload: dict, label: str) -> None:
    forbidden = (
        "Cutoff-valid",
        "Same-event",
        "Official driver standings",
        "Official constructor standings",
        "team total points per race",
        "qualifying classification",
        "long-run proxy",
        "tyre-degradation proxy",
        "speed-trap average",
        "best valid lap",
        "Historical analogue",
        "wet-skill prior",
        "confidence-weighted",
        "vs field",
        "confidence ",
        "weak_update",
        "normal_update",
        "strong_update",
        "model_surface=",
        "source_state=",
        "claim ",
    )
    texts: list[str] = []

    def add(value) -> None:
        if isinstance(value, str):
            texts.append(value)

    prediction = payload.get("prediction") if isinstance(payload.get("prediction"), dict) else payload
    belief = prediction.get("belief_state") if isinstance(prediction.get("belief_state"), dict) else {}
    for row in prediction.get("state_update_ledger") or []:
        add(row.get("mechanism"))
    for row in belief.get("normalized_claims") or []:
        add(row.get("mechanism"))
    for row in belief.get("extracted_units") or []:
        add(row.get("paraphrase_zh"))
    for trace in prediction.get("prediction_impact_trace") or payload.get("traces") or []:
        add(trace.get("interpretation_zh"))
        for stage in trace.get("source_to_prediction_chain") or []:
            add(stage.get("text_zh"))
        for chain in trace.get("additional_source_to_prediction_chains") or []:
            for stage in chain:
                add(stage.get("text_zh"))

    public_text = "\n".join(texts)
    _assert(public_text.strip(), f"{label}: public explanation text should be present")
    for token in forbidden:
        _assert(token not in public_text, f"{label}: public explanation text should not expose '{token}'")


def main() -> None:
    explainer = PredictionExplainer(ROOT)

    russell = explainer.answer(
        "why is Russell first?",
        event_id="british_gp",
        knowledge_cutoff=KNOWLEDGE_CUTOFF,
        max_evidence=5,
    )
    _assert(russell.question_type == "rank_explanation", "Russell question should route as rank explanation")
    _assert("russell" in russell.detected_entities["drivers"], "Russell should be detected")
    _assert("BeliefState" in russell.answer, "Rank answer should mention the traceable BeliefState chain")
    _assert(
        "来源 -> 信息抽取 -> 因子声明 -> 状态更新 -> 预测分布变化" in russell.answer,
        "Rank answer should describe the full traceability path",
    )
    russell_public = russell.to_dict()
    _assert_traceable_context(russell_public, "Russell")
    _assert_no_raw_internal_fields(russell_public, "Russell")
    _assert("score_breakdown" not in russell.codex_prompt, "Codex prompt should not expose raw score breakdown")
    _assert("weighted_value" not in russell.codex_prompt, "Codex prompt should not expose raw feature weights")

    ferrari = explainer.answer(
        "\u4e3a\u4ec0\u4e48 Leclerc \u6bd4 Hamilton \u4f4e\u8fd9\u4e48\u591a\uff1f",
        event_id="british_gp",
        knowledge_cutoff=KNOWLEDGE_CUTOFF,
        max_evidence=6,
    )
    _assert(ferrari.question_type == "driver_comparison", "Ferrari teammate question should route as comparison")
    _assert(
        {"hamilton", "leclerc"}.issubset(set(ferrari.detected_entities["drivers"])),
        "Hamilton and Leclerc should be detected",
    )
    ferrari_public = ferrari.to_dict()
    _assert_traceable_context(ferrari_public, "Ferrari comparison")
    _assert_no_raw_internal_fields(ferrari_public, "Ferrari comparison")
    _assert("race" + " score" not in ferrari.answer, "User-facing answer should not expose raw English labels")
    _assert(
        "\u53ef\u8ffd\u6eaf\u94fe\u8def" in ferrari.answer,
        "Comparison should explain via the traceable chain",
    )
    ferrari_traces = ferrari_public["evidence_context"]["prediction_impact_trace_context"]["top_traces"]
    _assert(ferrari_traces, "Ferrari comparison should include prediction-impact traces")
    _assert(
        ferrari_traces[0].get("relevance_scope") == "direct_target",
        "Direct Ferrari/Hamilton/Leclerc traces should be prioritized before indirect competition traces",
    )
    _assert(
        "\u76f4\u63a5\u4f5c\u7528\u4e8e\u6240\u95ee\u5bf9\u8c61" in ferrari.answer,
        "Comparison impact lines should label direct target traces",
    )
    for trace in ferrari_traces:
        _assert(trace.get("relevance_scope_label"), "Prediction-impact traces should expose a relevance label")

    zero_podium = explainer.answer(
        "why is Alonso first among zero podium drivers?",
        event_id="british_gp",
        knowledge_cutoff=KNOWLEDGE_CUTOFF,
        max_evidence=6,
    )
    _assert(zero_podium.question_type == "group_zero_podium", "Zero podium question should route as group explanation")
    _assert("alonso" in zero_podium.detected_entities["drivers"], "Alonso should be detected")
    _assert(zero_podium.detected_entities["derived_groups"], "Zero podium derived group should be present")
    _assert(
        "\u4e0d\u662f\u8fd9\u4e2a\u5206\u7ec4\u7b2c\u4e00" in zero_podium.answer,
        "Zero podium answer should correct the stale Alonso premise when needed",
    )
    zero_public = zero_podium.to_dict()
    _assert_traceable_context(zero_public, "Zero podium")
    _assert_no_raw_internal_fields(zero_public, "Zero podium")

    chinese_zero_podium = explainer.answer(
        "\u4e3a\u4ec0\u4e48\u963f\u9686\u7d22\u5728\u96f6\u9886\u5956\u53f0\u7ec4\u91cc\u8fd9\u4e48\u9760\u524d\uff1f",
        event_id="british_gp",
        knowledge_cutoff=KNOWLEDGE_CUTOFF,
        max_evidence=6,
    )
    _assert(
        chinese_zero_podium.question_type == "group_zero_podium",
        "Chinese Alonso zero-podium question should route as group explanation",
    )
    _assert(
        "alonso" in chinese_zero_podium.detected_entities["drivers"],
        "Chinese Alonso alias should be detected",
    )

    chinese_teammates = explainer.answer(
        "\u4e3a\u4ec0\u4e48\u52d2\u514b\u83b1\u5c14\u6bd4\u6c49\u5bc6\u5c14\u987f\u4f4e\uff1f",
        event_id="british_gp",
        knowledge_cutoff=KNOWLEDGE_CUTOFF,
        max_evidence=6,
    )
    _assert(
        chinese_teammates.question_type == "driver_comparison",
        "Chinese Ferrari teammate question should route as comparison",
    )
    _assert(
        {"hamilton", "leclerc"}.issubset(set(chinese_teammates.detected_entities["drivers"])),
        "Chinese Hamilton/Leclerc aliases should be detected",
    )

    chinese_team = explainer.answer(
        "\u6cd5\u62c9\u5229\u73b0\u5728\u4e3a\u4ec0\u4e48\u8fd9\u4e48\u6392\uff1f",
        event_id="british_gp",
        knowledge_cutoff=KNOWLEDGE_CUTOFF,
        max_evidence=6,
    )
    _assert("ferrari" in chinese_team.detected_entities["teams"], "Chinese Ferrari alias should be detected")

    api = BackendApiV2(ROOT)
    openapi = api.handle_get("/api/v2/openapi.json", {}).payload
    _assert(
        "/api/v2/prediction-explanations" in openapi["paths"],
        "API v2 should expose prediction explanation endpoint",
    )
    response = api.handle_post(
        "/api/v2/prediction-explanations",
        {},
        {
            "event_id": "british_gp",
            "knowledge_cutoff": KNOWLEDGE_CUTOFF,
            "question": "why is Russell first?",
            "max_evidence": 4,
        },
    )
    _assert(response.status == 200, "API explanation POST should succeed")
    _assert(response.payload["question_type"] == "rank_explanation", "API explanation should route correctly")
    _assert("codex_prompt" in response.payload, "API explanation should include Codex prompt")
    _assert_traceable_context(response.payload, "API")
    _assert_no_raw_internal_fields(response.payload, "API")
    _assert(
        "score_breakdown" not in response.payload["codex_prompt"],
        "API Codex prompt should not expose raw score breakdown",
    )

    latest_packet = api.handle_get(
        "/api/v2/prediction-packets/latest",
        {"event_id": ["british_gp"]},
    )
    _assert(latest_packet.status == 200, "Latest packet API should succeed")
    _assert_public_packet_seed_separation(latest_packet.payload)
    _assert_public_explanation_text_is_localized(latest_packet.payload, "Latest packet")

    latest_sidecar = api.handle_get(
        "/api/v2/prediction-impact-traces/latest",
        {"event_id": ["british_gp"], "limit": ["20"]},
    )
    _assert(latest_sidecar.status == 200, "Latest impact trace sidecar API should succeed")
    _assert_public_explanation_text_is_localized(latest_sidecar.payload, "Latest sidecar page")

    print("traceable explainability smoke ok")


if __name__ == "__main__":
    main()
