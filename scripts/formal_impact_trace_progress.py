"""Report resumable progress for formal prediction-impact sidecar chunks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from f1predict.impact_trace_sidecar import _run_dir_name  # noqa: E402
from f1predict.run_tracking import PredictionRunRegistry  # noqa: E402
from f1predict.storage import safe_name  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", default="british_gp")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--registry-root", default="reports/prediction_runs")
    parser.add_argument("--sidecar-root", default="reports/prediction_impact_traces")
    parser.add_argument("--chunk-size", type=int, default=1)
    args = parser.parse_args()

    registry = PredictionRunRegistry(ROOT / args.registry_root)
    record = registry.load(args.run_id) if args.run_id else registry.latest(args.event)
    if record is None:
        raise SystemExit(f"No run found for event={args.event}")
    packet = registry.load_packet_for_record(record)
    if packet is None:
        raise SystemExit(f"Run has no readable packet: {record.run_id}")

    claim_order = _claim_order(packet)
    chunk_size = max(1, int(args.chunk_size))
    sidecar_dir = ROOT / args.sidecar_root / safe_name(record.event_id) / _run_dir_name(record.run_id)
    sidecars = _load_sidecars(sidecar_dir)
    formal_sidecars = [
        row
        for row in sidecars
        if _source_run_id(row) == record.run_id
        and _trace_iterations(row) == int(record.iterations)
        and _source_packet_hash(row) == record.packet_payload_sha256
    ]
    covered_claims = {
        str(trace.get("claim_id"))
        for sidecar in formal_sidecars
        for trace in _traces(sidecar)
        if trace.get("trace_type") == "isolated_same_seed_leave_one_information" and trace.get("claim_id")
    }
    missing_offsets = [
        index
        for index, claim_id in enumerate(claim_order)
        if claim_id not in covered_claims
    ]
    chunk_ranges = [_chunk_range(row) for row in formal_sidecars]
    next_offset = missing_offsets[0] if missing_offsets else None
    recommended_command = None
    if next_offset is not None:
        recommended_command = (
            "python -m f1predict.cli prediction-impact-trace-sidecar "
            f"--event {record.event_id} --run-id {record.run_id} --iterations {record.iterations} "
            f"--isolated-impact-limit {chunk_size} --isolated-impact-offset {next_offset} "
            "--isolated-source-group-limit 0 --write --limit 5"
        )

    payload = {
        "event_id": record.event_id,
        "run_id": record.run_id,
        "source_iterations": record.iterations,
        "source_packet_sha256": record.packet_payload_sha256,
        "sidecar_dir": str(sidecar_dir),
        "claim_count": len(claim_order),
        "formal_chunk_count": len(formal_sidecars),
        "covered_claim_count": len(covered_claims),
        "missing_claim_count": len(missing_offsets),
        "coverage_ratio": round(len(covered_claims) / len(claim_order), 6) if claim_order else 0.0,
        "formal_ready_if_merged": bool(claim_order and not missing_offsets),
        "chunk_ranges": chunk_ranges,
        "next_offset": next_offset,
        "next_chunk_size": chunk_size if next_offset is not None else 0,
        "recommended_command": recommended_command,
        "merge_command": _merge_command(formal_sidecars) if formal_sidecars else None,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _claim_order(packet: dict[str, Any]) -> list[str]:
    updates = packet.get("prediction", {}).get("state_update_ledger") or []
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in updates:
        if not isinstance(row, dict):
            continue
        claim_id = str(row.get("claim_id") or "")
        if claim_id:
            groups.setdefault(claim_id, []).append(row)
    scored = []
    for claim_id, rows in groups.items():
        score = max(abs(_float(row.get("delta"))) for row in rows)
        scored.append((score, claim_id))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [claim_id for _, claim_id in scored]


def _load_sidecars(directory: Path) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    output = []
    for path in sorted(directory.glob("*.prediction_impact_trace.json"), key=lambda item: item.stat().st_mtime):
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payload["_path"] = str(path)
            output.append(payload)
    return output


def _source_run_id(sidecar: dict[str, Any]) -> str | None:
    source_run = sidecar.get("source_run") if isinstance(sidecar.get("source_run"), dict) else {}
    return source_run.get("run_id")


def _source_packet_hash(sidecar: dict[str, Any]) -> str | None:
    source_run = sidecar.get("source_run") if isinstance(sidecar.get("source_run"), dict) else {}
    return source_run.get("packet_payload_sha256")


def _trace_iterations(sidecar: dict[str, Any]) -> int:
    generation = sidecar.get("trace_generation") if isinstance(sidecar.get("trace_generation"), dict) else {}
    return int(generation.get("iterations") or 0)


def _traces(sidecar: dict[str, Any]) -> list[dict[str, Any]]:
    traces = sidecar.get("traces")
    return [row for row in traces if isinstance(row, dict)] if isinstance(traces, list) else []


def _chunk_range(sidecar: dict[str, Any]) -> dict[str, Any]:
    generation = sidecar.get("trace_generation") if isinstance(sidecar.get("trace_generation"), dict) else {}
    offset = int(generation.get("isolated_impact_offset") or 0)
    limit = int(generation.get("isolated_impact_limit") or 0)
    return {
        "path": sidecar.get("_path"),
        "sidecar_id": sidecar.get("sidecar_id"),
        "offset": offset,
        "limit": limit,
        "end_exclusive": offset + limit if limit >= 0 else None,
        "covered_claim_count": len(
            {
                str(trace.get("claim_id"))
                for trace in _traces(sidecar)
                if trace.get("trace_type") == "isolated_same_seed_leave_one_information" and trace.get("claim_id")
            }
        ),
    }


def _merge_command(sidecars: list[dict[str, Any]]) -> str:
    paths = [str(row.get("_path")) for row in sidecars if row.get("_path")]
    return (
        "python -m f1predict.cli merge-prediction-impact-trace-sidecars "
        + " ".join(paths)
        + " --write --limit 5"
    )


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    main()
