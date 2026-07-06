"""Cached sidecars for full prediction-impact traces."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from f1predict.domain import utc_now
from f1predict.pipeline import PredictionPipeline
from f1predict.prediction_packet import PredictionPacketBuilder
from f1predict.run_tracking import PredictionRunRecord, PredictionRunRegistry
from f1predict.storage import safe_name


SIDECAR_SCHEMA_VERSION = "prediction_impact_trace_sidecar_v1"


class PredictionImpactTraceSidecarStore:
    """Build, persist, and page full isolated impact-trace artifacts.

    The ordinary prediction packet intentionally embeds only a limited number of
    isolated reruns so the frontend can load quickly. This store writes the full
    impact trace into a separate cached artifact that can be fetched in pages.
    """

    def __init__(self, root: Path | str = Path("."), registry: PredictionRunRegistry | None = None) -> None:
        self.root = Path(root)
        self.registry = registry or PredictionRunRegistry(self.root / "reports" / "prediction_runs")
        self.sidecar_root = self.root / "reports" / "prediction_impact_traces"

    def build(
        self,
        *,
        event_id: str = "british_gp",
        run_id: str | None = None,
        knowledge_cutoff: str | None = None,
        iterations: int | None = None,
        isolated_impact_limit: int = -1,
        isolated_source_group_limit: int = 0,
    ) -> dict[str, Any]:
        source_record = self._source_record(event_id, run_id, knowledge_cutoff)
        source_packet = self._load_source_packet(source_record)
        cutoff = knowledge_cutoff if knowledge_cutoff is not None else source_record.knowledge_cutoff
        source_iterations = int(source_packet.get("iterations") or source_record.iterations or 0)
        trace_iterations = int(iterations if iterations is not None else source_iterations)

        builder = PredictionPacketBuilder(
            PredictionPipeline(
                iterations=trace_iterations,
                isolated_impact_limit=isolated_impact_limit,
                isolated_source_group_limit=isolated_source_group_limit,
            ),
            reports_root=self.root / "reports",
        )
        trace_packet = builder.build(
            source_record.event_id,
            knowledge_cutoff=cutoff,
            iterations=trace_iterations,
        ).to_dict()
        prediction = trace_packet.get("prediction") if isinstance(trace_packet.get("prediction"), dict) else {}
        traces = prediction.get("prediction_impact_trace") if isinstance(prediction.get("prediction_impact_trace"), list) else []
        codex_context = trace_packet.get("codex_context") if isinstance(trace_packet.get("codex_context"), dict) else {}
        trace_context = _trace_context(prediction)
        trace_fingerprint = _canonical_hash(traces)
        generated_at = utc_now().replace(microsecond=0).isoformat()
        sidecar_id = safe_name(
            f"{source_record.event_id}_{_run_dir_name(source_record.run_id)}_{_stem_time(generated_at)}_{trace_fingerprint[:10]}"
        )

        comparison_status = (
            "matched_source_run_iterations"
            if trace_iterations == source_iterations
            else "diagnostic_iteration_mismatch"
        )
        sidecar = {
            "sidecar_schema_version": SIDECAR_SCHEMA_VERSION,
            "sidecar_id": sidecar_id,
            "event_id": source_record.event_id,
            "event_name": source_record.event_name,
            "generated_at": generated_at,
            "knowledge_cutoff": cutoff,
            "source_run": {
                "run_id": source_record.run_id,
                "created_at": source_record.created_at,
                "generated_at": source_record.generated_at,
                "iterations": source_iterations,
                "prediction_packet_path": source_record.prediction_packet_path,
                "packet_payload_sha256": source_record.packet_payload_sha256,
                "input_fingerprint": source_record.input_fingerprint,
                "evidence_fingerprint": source_record.evidence_fingerprint,
                "probability_fingerprint": source_record.probability_fingerprint,
                "belief_state_id": source_record.belief_state_id,
                "belief_state_update_fingerprint": source_record.belief_state_update_fingerprint,
            },
            "trace_generation": {
                "iterations": trace_iterations,
                "isolated_impact_limit": isolated_impact_limit,
                "isolated_source_group_limit": isolated_source_group_limit,
                "comparison_status": comparison_status,
                "status_zh": _comparison_status_zh(comparison_status),
                "note_zh": (
                    "这个 sidecar 只用于解释每条来源化信息的边际影响；"
                    "它不会注册为新的最新预测，也不会修改前端默认排名。"
                ),
            },
            "trace_packet": {
                "packet_payload_sha256": trace_packet.get("packet_payload_sha256"),
                "status": trace_packet.get("status"),
                "blocker_codes": trace_packet.get("blocker_codes") or [],
                "warning_codes": trace_packet.get("warning_codes") or [],
            },
            "coverage": _coverage(codex_context, traces),
            "probability_summary": trace_packet.get("probability_summary") or {},
            "trace_context": trace_context,
            "trace_fingerprint": trace_fingerprint,
            "trace_count": len(traces),
            "traces": traces,
        }
        return sidecar

    def write(self, sidecar: dict[str, Any], output_root: Path | str | None = None) -> Path:
        root = Path(output_root) if output_root is not None else self.sidecar_root
        directory = root / safe_name(str(sidecar["event_id"])) / _run_dir_name(str(sidecar["source_run"]["run_id"]))
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{safe_name(str(sidecar['sidecar_id']))}.prediction_impact_trace.json"
        path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def latest(self, *, event_id: str = "british_gp", run_id: str | None = None) -> dict[str, Any] | None:
        record = self._source_record(event_id, run_id, None)
        directory = self.sidecar_root / safe_name(record.event_id) / _run_dir_name(record.run_id)
        if not directory.exists():
            return None
        candidates = sorted(directory.glob("*.prediction_impact_trace.json"), key=lambda path: path.stat().st_mtime)
        if not candidates:
            return None
        return _read_json(candidates[-1])

    def latest_page(
        self,
        *,
        event_id: str = "british_gp",
        run_id: str | None = None,
        limit: int = 40,
        offset: int = 0,
        trace_type: str | None = None,
        impact_status: str | None = None,
        claim_id: str | None = None,
    ) -> dict[str, Any] | None:
        sidecar = self.latest(event_id=event_id, run_id=run_id)
        if sidecar is None:
            return None
        return page_sidecar(
            sidecar,
            limit=limit,
            offset=offset,
            trace_type=trace_type,
            impact_status=impact_status,
            claim_id=claim_id,
        )

    def _source_record(
        self,
        event_id: str,
        run_id: str | None,
        knowledge_cutoff: str | None,
    ) -> PredictionRunRecord:
        if run_id:
            return self.registry.load(run_id)
        record = self.registry.latest(event_id, knowledge_cutoff=knowledge_cutoff)
        if record is None:
            raise ValueError(f"No registered prediction run for event_id={event_id}")
        return record

    def _load_source_packet(self, record: PredictionRunRecord) -> dict[str, Any]:
        if not record.prediction_packet_path:
            raise ValueError(f"Run {record.run_id} has no prediction packet path")
        path = Path(record.prediction_packet_path)
        if not path.is_absolute():
            path = self.root / path
        return _read_json(path)


def page_sidecar(
    sidecar: dict[str, Any],
    *,
    limit: int = 40,
    offset: int = 0,
    trace_type: str | None = None,
    impact_status: str | None = None,
    claim_id: str | None = None,
) -> dict[str, Any]:
    traces = sidecar.get("traces") if isinstance(sidecar.get("traces"), list) else []
    filtered = []
    for row in traces:
        if trace_type and row.get("trace_type") != trace_type:
            continue
        if impact_status and row.get("impact_status") != impact_status:
            continue
        if claim_id:
            row_claim_ids = [row.get("claim_id"), *(row.get("claim_ids") or [])]
            if claim_id not in {str(item) for item in row_claim_ids if item}:
                continue
        filtered.append(row)
    safe_limit = max(1, min(int(limit), 200))
    safe_offset = max(0, int(offset))
    page_rows = filtered[safe_offset : safe_offset + safe_limit]
    payload = {
        key: value
        for key, value in sidecar.items()
        if key not in {"traces", "trace_context"}
    }
    payload["pagination"] = {
        "offset": safe_offset,
        "limit": safe_limit,
        "returned_trace_count": len(page_rows),
        "filtered_trace_count": len(filtered),
        "total_trace_count": len(traces),
        "has_more": safe_offset + safe_limit < len(filtered),
        "filters": {
            "trace_type": trace_type,
            "impact_status": impact_status,
            "claim_id": claim_id,
        },
    }
    context = sidecar.get("trace_context") if isinstance(sidecar.get("trace_context"), dict) else {}
    payload["traces"] = [_public_trace_row(row, context) for row in page_rows]
    return payload


def _coverage(codex_context: dict[str, Any], traces: list[dict[str, Any]]) -> dict[str, Any]:
    trace_type_counts = Counter(str(row.get("trace_type") or "unknown") for row in traces)
    impact_status_counts = Counter(str(row.get("impact_status") or "unknown") for row in traces)
    return {
        "state_update_count": int(codex_context.get("state_update_count") or 0),
        "impact_trace_claim_count": int(codex_context.get("impact_trace_claim_count") or 0),
        "impact_trace_single_claim_coverage_count": int(
            codex_context.get("impact_trace_single_claim_coverage_count") or 0
        ),
        "impact_trace_source_group_claim_coverage_count": int(
            codex_context.get("impact_trace_source_group_claim_coverage_count") or 0
        ),
        "impact_trace_covered_claim_count": int(codex_context.get("impact_trace_covered_claim_count") or 0),
        "impact_trace_uncovered_claim_count": int(codex_context.get("impact_trace_uncovered_claim_count") or 0),
        "isolated_prediction_impact_count": int(codex_context.get("isolated_prediction_impact_count") or 0),
        "isolated_source_group_impact_count": int(codex_context.get("isolated_source_group_impact_count") or 0),
        "trace_type_counts": dict(sorted(trace_type_counts.items())),
        "impact_status_counts": dict(sorted(impact_status_counts.items())),
    }


def _trace_context(prediction: dict[str, Any]) -> dict[str, Any]:
    belief = prediction.get("belief_state") if isinstance(prediction.get("belief_state"), dict) else {}
    evidence = prediction.get("evidence") if isinstance(prediction.get("evidence"), list) else []
    evidence_quality = prediction.get("evidence_quality") if isinstance(prediction.get("evidence_quality"), list) else []
    factor_trace = prediction.get("factor_trace") if isinstance(prediction.get("factor_trace"), list) else []
    updates = prediction.get("state_update_ledger") if isinstance(prediction.get("state_update_ledger"), list) else []
    sources = belief.get("raw_sources") if isinstance(belief.get("raw_sources"), list) else []
    claims = belief.get("normalized_claims") if isinstance(belief.get("normalized_claims"), list) else []
    quality_profiles = belief.get("quality_profiles") if isinstance(belief.get("quality_profiles"), list) else []

    updates_by_claim: dict[str, list[dict[str, Any]]] = {}
    updates_by_source: dict[str, list[dict[str, Any]]] = {}
    for row in updates:
        claim_id = str(row.get("claim_id") or "")
        source_id = str(row.get("source_id") or "")
        compact = _compact_update(row)
        if claim_id:
            updates_by_claim.setdefault(claim_id, []).append(compact)
        if source_id:
            updates_by_source.setdefault(source_id, []).append(compact)

    return {
        "sources_by_id": {
            str(row.get("source_id")): _compact_source(row)
            for row in sources
            if row.get("source_id")
        },
        "claims_by_id": {
            str(row.get("claim_id")): _compact_claim(row)
            for row in claims
            if row.get("claim_id")
        },
        "evidence_by_claim_id": {
            str(row.get("claim_id")): _compact_evidence(row)
            for row in evidence
            if row.get("claim_id")
        },
        "quality_by_claim_id": {
            str(row.get("claim_id")): _compact_quality(row)
            for row in [*quality_profiles, *evidence_quality]
            if row.get("claim_id")
        },
        "factor_trace_by_claim_id": {
            str(row.get("claim_id")): _compact_factor_trace(row)
            for row in factor_trace
            if row.get("claim_id")
        },
        "updates_by_claim_id": updates_by_claim,
        "updates_by_source_id": updates_by_source,
    }


def _public_trace_row(row: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    claim_ids = _trace_claim_ids(row)
    source_ids = _trace_source_ids(row)
    chains = []
    for claim_id in claim_ids[:6]:
        chain = _claim_chain(row, claim_id, context)
        if chain:
            chains.append(chain)
    if not chains:
        for source_id in source_ids[:3]:
            chain = _source_chain(row, source_id, context)
            if chain:
                chains.append(chain)
    if not chains:
        chains.append(
            [
                {
                    "stage": "预测变化",
                    "text_zh": _prediction_change_text(row),
                }
            ]
        )
    supporting_sources = []
    for source_id in source_ids[:6]:
        source = (context.get("sources_by_id") or {}).get(source_id)
        if source:
            supporting_sources.append(source)
    public = dict(row)
    public["supporting_sources"] = supporting_sources
    public["source_to_prediction_chain"] = chains[0]
    if len(chains) > 1:
        public["additional_source_to_prediction_chains"] = chains[1:4]
    return public


def _claim_chain(row: dict[str, Any], claim_id: str, context: dict[str, Any]) -> list[dict[str, str]]:
    claims = context.get("claims_by_id") or {}
    evidence = context.get("evidence_by_claim_id") or {}
    qualities = context.get("quality_by_claim_id") or {}
    updates = context.get("updates_by_claim_id") or {}
    factor_traces = context.get("factor_trace_by_claim_id") or {}
    claim = claims.get(claim_id) or {}
    evidence_row = evidence.get(claim_id) or {}
    quality = qualities.get(claim_id) or {}
    factor_trace = factor_traces.get(claim_id) or {}
    update_rows = updates.get(claim_id) or []
    source = _source_for_claim(row, claim_id, update_rows, context)
    stages = []
    stages.append({"stage": "原始来源", "text_zh": _source_text(source, claim_id)})
    stages.append(
        {
            "stage": "信息分析",
            "text_zh": _analysis_text(claim_id, claim, evidence_row, quality, factor_trace),
        }
    )
    stages.append({"stage": "状态更新", "text_zh": _state_update_text(update_rows, quality)})
    stages.append({"stage": "预测变化", "text_zh": _prediction_change_text(row)})
    return stages


def _source_chain(row: dict[str, Any], source_id: str, context: dict[str, Any]) -> list[dict[str, str]]:
    sources = context.get("sources_by_id") or {}
    updates = context.get("updates_by_source_id") or {}
    source = sources.get(source_id) or {}
    update_rows = updates.get(source_id) or []
    return [
        {"stage": "原始来源", "text_zh": _source_text(source, source_id)},
        {"stage": "信息分析", "text_zh": "该来源组包含多条结构化信息；分页 trace 会列出对应 claim_id。"},
        {"stage": "状态更新", "text_zh": _state_update_text(update_rows, {})},
        {"stage": "预测变化", "text_zh": _prediction_change_text(row)},
    ]


def _trace_claim_ids(row: dict[str, Any]) -> list[str]:
    values = []
    if row.get("claim_id"):
        values.append(str(row["claim_id"]))
    values.extend(str(value) for value in row.get("claim_ids", []) if value)
    return list(dict.fromkeys(values))


def _trace_source_ids(row: dict[str, Any]) -> list[str]:
    values = []
    if row.get("source_id"):
        values.append(str(row["source_id"]))
    values.extend(str(value) for value in row.get("source_ids", []) if value)
    return list(dict.fromkeys(values))


def _source_for_claim(
    row: dict[str, Any],
    claim_id: str,
    update_rows: list[dict[str, Any]],
    context: dict[str, Any],
) -> dict[str, Any]:
    sources = context.get("sources_by_id") or {}
    for update in update_rows:
        source_id = update.get("source_id")
        if source_id and source_id in sources:
            return sources[source_id]
    source_id = row.get("source_id")
    if row.get("claim_id") == claim_id and source_id in sources:
        return sources[source_id]
    return {}


def _source_text(source: dict[str, Any], fallback_id: str) -> str:
    if not source:
        return f"未找到完整来源记录；可用标识为 {fallback_id}。"
    title = source.get("title") or source.get("publisher") or source.get("source_type") or fallback_id
    publisher = source.get("publisher") or source.get("source_type") or "未知发布者"
    timestamp = source.get("published_at") or source.get("captured_at") or "时间未记录"
    url = source.get("url") or "无 URL"
    archive = "；已有归档" if source.get("archive_url") else ""
    return f"{publisher} 的《{title}》，时间 {timestamp}，链接 {url}{archive}。"


def _analysis_text(
    claim_id: str,
    claim: dict[str, Any],
    evidence: dict[str, Any],
    quality: dict[str, Any],
    factor_trace: dict[str, Any],
) -> str:
    target = _target_text(claim.get("target_type") or evidence.get("target_type"), claim.get("target_id") or evidence.get("target_id"))
    factor = claim.get("factor") or evidence.get("metric") or factor_trace.get("metric") or "未知因子"
    direction = claim.get("direction") or evidence.get("direction") or factor_trace.get("direction") or "未知方向"
    mechanism = claim.get("mechanism") or evidence.get("reasoning") or evidence.get("evidence_text") or "没有记录机制说明"
    permission = quality.get("model_update_permission") or "权限未记录"
    quality_text = _quality_text(quality)
    return (
        f"claim {claim_id} 被解析为 {target} 的 {factor} {direction}。"
        f"机制：{mechanism}。质量审计：{quality_text}；更新权限：{permission}。"
    )


def _state_update_text(update_rows: list[dict[str, Any]], quality: dict[str, Any]) -> str:
    if not update_rows:
        permission = quality.get("model_update_permission")
        return f"未找到对应状态更新记录；质量权限为 {permission or '未记录'}。"
    phrases = []
    for update in update_rows[:4]:
        target = _target_text(update.get("target_type"), update.get("target_id"))
        phrases.append(
            f"{target} 的 {update.get('factor', '未知因子')} 从"
            f"{update.get('old_value_bucket', '未知')} 到 {update.get('new_value_bucket', '未知')}"
            f"（{update.get('direction', '未知方向')}，{update.get('magnitude_bucket', '未知幅度')}，"
            f"{update.get('update_permission', '权限未记录')}）"
        )
    suffix = f"；另有 {len(update_rows) - 4} 条同 claim 更新" if len(update_rows) > 4 else ""
    return "；".join(phrases) + suffix + "。"


def _prediction_change_text(row: dict[str, Any]) -> str:
    status = {
        "material_prediction_change": "显著改变预测分布",
        "small_prediction_change": "小幅改变预测分布",
        "no_material_prediction_change": "没有观察到显著预测变化",
        "pending_isolated_rerun": "仍等待隔离重跑",
    }.get(str(row.get("impact_status")), "影响状态未记录")
    bucket = row.get("probability_delta_bucket") or "幅度未记录"
    affected = row.get("affected_drivers") or []
    affected_text = "、".join(str(item) for item in affected[:6]) if affected else "没有显著受影响车手"
    points = row.get("expected_points_delta") or []
    top_point = ""
    if points:
        first = points[0]
        top_point = (
            f"；最大期望积分变化来自 {first.get('driver_id')}，"
            f"方向为 {_delta_direction(first.get('expected_points_delta'))}"
        )
    return f"同种子对比结果：{status}，幅度 {bucket}，{affected_text}{top_point}。"


def _delta_direction(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "未记录"
    if number > 0.03:
        return "上升"
    if number < -0.03:
        return "下降"
    return "接近不变"


def _quality_text(quality: dict[str, Any]) -> str:
    if not quality:
        return "未找到质量审计"
    status = quality.get("quality_status") or quality.get("timestamp_validity") or "未记录"
    source_status = quality.get("source_status") or quality.get("timestamp_validity") or "来源时效未记录"
    reasons = quality.get("risk_flags") or quality.get("reasons") or []
    reason_text = "，".join(str(item) for item in reasons[:3]) if reasons else "无显著风险标记"
    return f"{status}，{source_status}，{reason_text}"


def _target_text(target_type: Any, target_id: Any) -> str:
    if target_type and target_id:
        return f"{target_type}:{target_id}"
    if target_id:
        return str(target_id)
    return "未知对象"


def _compact_source(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": row.get("source_id"),
        "source_type": row.get("source_type"),
        "url": row.get("url"),
        "title": row.get("title"),
        "publisher": row.get("publisher"),
        "published_at": row.get("published_at"),
        "captured_at": row.get("captured_at"),
        "archive_url": row.get("archive_url"),
    }


def _compact_claim(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "claim_id": row.get("claim_id"),
        "target_type": row.get("target_type"),
        "target_id": row.get("target_id"),
        "factor": row.get("factor"),
        "direction": row.get("direction"),
        "magnitude_observation": row.get("magnitude_observation"),
        "mechanism": row.get("mechanism"),
        "valid_from": row.get("valid_from"),
        "extraction_status": row.get("extraction_status"),
    }


def _compact_evidence(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "claim_id": row.get("claim_id"),
        "source": row.get("source"),
        "source_url": row.get("source_url"),
        "target_type": row.get("target_type"),
        "target_id": row.get("target_id"),
        "metric": row.get("metric"),
        "direction": row.get("direction"),
        "evidence_text": row.get("evidence_text"),
        "reasoning": row.get("reasoning"),
        "review_required": row.get("review_required"),
    }


def _compact_quality(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "claim_id": row.get("claim_id"),
        "quality_status": row.get("quality_status"),
        "source_status": row.get("source_status") or row.get("timestamp_validity"),
        "triangulation_status": row.get("triangulation_status"),
        "conflict_status": row.get("conflict_status"),
        "model_update_permission": row.get("model_update_permission"),
        "review_required": row.get("review_required"),
        "risk_flags": row.get("risk_flags") or [],
        "reasons": row.get("reasons") or [],
    }


def _compact_factor_trace(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "claim_id": row.get("claim_id"),
        "metric": row.get("metric"),
        "direction": row.get("direction"),
        "route": row.get("route"),
        "model_surface": row.get("model_surface"),
        "route_status": row.get("route_status"),
        "route_notes": row.get("route_notes") or [],
    }


def _compact_update(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "update_id": row.get("update_id"),
        "claim_id": row.get("claim_id"),
        "source_id": row.get("source_id"),
        "target_type": row.get("target_type"),
        "target_id": row.get("target_id"),
        "factor": row.get("factor"),
        "old_value_bucket": row.get("old_value_bucket"),
        "new_value_bucket": row.get("new_value_bucket"),
        "direction": row.get("direction"),
        "magnitude_bucket": row.get("magnitude_bucket"),
        "update_permission": row.get("update_permission"),
        "quality_reasons": row.get("quality_reasons") or [],
        "mechanism": row.get("mechanism"),
        "affected_model_surfaces": row.get("affected_model_surfaces") or [],
    }


def _comparison_status_zh(status: str) -> str:
    if status == "matched_source_run_iterations":
        return "隔离重跑迭代数与源预测 run 一致，可用于同迭代解释。"
    return "隔离重跑迭代数与源预测 run 不一致，只能作为诊断解释，不能当作正式效果证明。"


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected JSON object")
    return payload


def _stem_time(value: str | None) -> str:
    if not value:
        return "latest"
    return (
        value.replace(":", "")
        .replace("-", "")
        .replace("+", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )


def _run_dir_name(run_id: str) -> str:
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12]
    prefix = safe_name(run_id)[:36].strip("_")
    return safe_name(f"{prefix}_{digest}")
