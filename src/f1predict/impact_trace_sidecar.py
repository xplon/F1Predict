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
        if key != "traces"
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
    payload["traces"] = page_rows
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
