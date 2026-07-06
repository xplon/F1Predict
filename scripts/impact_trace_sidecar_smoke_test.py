"""Smoke checks for cached prediction-impact trace sidecars."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from f1predict.api_v2 import BackendApiV2  # noqa: E402


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    api = BackendApiV2(ROOT)
    openapi = api.handle_get("/api/v2/openapi.json", {}).payload
    _assert(
        "/api/v2/prediction-impact-traces" in openapi["paths"],
        "OpenAPI should expose sidecar build route",
    )
    _assert(
        "/api/v2/prediction-impact-traces/latest" in openapi["paths"],
        "OpenAPI should expose sidecar latest route",
    )
    _assert(
        "/api/v2/prediction-impact-traces/readiness" in openapi["paths"],
        "OpenAPI should expose sidecar readiness route",
    )
    _assert(
        "/api/v2/prediction-impact-traces/merge" in openapi["paths"],
        "OpenAPI should expose sidecar merge route",
    )

    response = api.handle_post(
        "/api/v2/prediction-impact-traces",
        {},
        {
            "event_id": "british_gp",
            "iterations": 3,
            "isolated_impact_limit": -1,
            "isolated_source_group_limit": 0,
            "write": False,
            "limit": 7,
        },
    )
    _assert(response.status == 201, "Sidecar POST should succeed")
    payload = response.payload
    coverage = payload["coverage"]
    generation = payload["trace_generation"]
    pagination = payload["pagination"]
    readiness = payload["formal_readiness"]
    _assert(generation["comparison_status"] == "diagnostic_iteration_mismatch", "Low-iteration smoke is diagnostic")
    _assert(readiness["status"] == "diagnostic_iterations_full_coverage", "Low-iteration full trace is not formal-ready")
    _assert(readiness["formal_ready"] is False, "Diagnostic trace should not be formal-ready")
    _assert(readiness["full_coverage"] is True, "Full isolated smoke should be coverage-complete")
    _assert(coverage["impact_trace_claim_count"] > 100, "Sidecar should inspect many source-backed updates")
    _assert(
        coverage["impact_trace_covered_claim_count"] == coverage["impact_trace_claim_count"],
        "Full isolated mode should cover every claim in the state-update ledger",
    )
    _assert(
        coverage["impact_trace_single_claim_coverage_count"] == coverage["impact_trace_claim_count"],
        "Single-claim isolated mode should cover every claim",
    )
    _assert(pagination["returned_trace_count"] == 7, "Sidecar response should be paginated")
    _assert(pagination["has_more"], "Smoke page should have more rows available")
    _assert(payload["traces"], "Sidecar page should include trace rows")
    claim_trace = next((row for row in payload["traces"] if row.get("claim_id")), None)
    _assert(claim_trace is not None, "Sidecar page should include a claim-level trace")
    chain = claim_trace.get("source_to_prediction_chain") or []
    stage_names = [row.get("stage") for row in chain]
    _assert(
        stage_names[:5] == ["原始来源", "信息分析", "状态更新", "模拟路由", "预测变化"],
        "Claim trace should expose the source-to-state-to-simulator-to-prediction chain",
    )
    route_stage = next((row for row in chain if row.get("stage") == "模拟路由"), {})
    _assert("模拟器表面" in route_stage.get("text_zh", ""), "Simulation route stage should name model surfaces")

    chunk_response = api.handle_post(
        "/api/v2/prediction-impact-traces",
        {},
        {
            "event_id": "british_gp",
            "iterations": 3,
            "isolated_impact_limit": 5,
            "isolated_impact_offset": 10,
            "isolated_source_group_limit": 0,
            "write": False,
            "limit": 20,
        },
    )
    _assert(chunk_response.status == 201, "Chunked sidecar POST should succeed")
    chunk = chunk_response.payload
    _assert(chunk["trace_generation"]["chunk_mode"] is True, "Chunked sidecar should mark chunk mode")
    _assert(chunk["trace_generation"]["isolated_impact_offset"] == 10, "Chunked sidecar should preserve offset")
    _assert(chunk["coverage"]["impact_trace_single_claim_coverage_count"] == 5, "Chunk should cover exactly five claims")
    _assert(chunk["formal_readiness"]["full_coverage"] is False, "Chunked trace is not full coverage")
    _assert(
        chunk["formal_readiness"]["status"] == "diagnostic_iterations_incomplete_coverage",
        "Low-iteration chunk should be diagnostic and incomplete",
    )

    with tempfile.TemporaryDirectory() as tmp:
        chunk_paths = []
        for offset in (0, 5):
            sidecar = api.impact_trace_store.build(
                event_id="british_gp",
                iterations=3,
                isolated_impact_limit=5,
                isolated_impact_offset=offset,
                isolated_source_group_limit=0,
            )
            chunk_paths.append(str(api.impact_trace_store.write(sidecar, output_root=Path(tmp))))
        merge_response = api.handle_post(
            "/api/v2/prediction-impact-traces/merge",
            {},
            {
                "sidecar_paths": chunk_paths,
                "write": False,
                "limit": 30,
            },
        )
        _assert(merge_response.status == 201, "Sidecar merge POST should succeed")
        merged = merge_response.payload
        _assert(merged["trace_generation"]["merge_status"] == "merged_chunks", "Merged sidecar should mark merge status")
        _assert(merged["trace_generation"]["merged_chunk_count"] == 2, "Merged sidecar should track chunk count")
        _assert(
            merged["coverage"]["impact_trace_single_claim_coverage_count"] == 10,
            "Merged chunks should cover ten distinct claims",
        )
        expected_uncovered = merged["coverage"]["impact_trace_claim_count"] - 10
        _assert(expected_uncovered > 0, "Smoke fixture should still have claims outside the two chunks")
        _assert(
            merged["coverage"]["impact_trace_uncovered_claim_count"] == expected_uncovered,
            "Merged chunks should remain partial",
        )
        _assert(merged["formal_readiness"]["formal_ready"] is False, "Partial merged chunks are not formal-ready")

    latest_readiness = api.handle_get(
        "/api/v2/prediction-impact-traces/readiness",
        {"event_id": ["british_gp"]},
    ).payload
    _assert("formal_ready" in latest_readiness, "Readiness route should return a formal_ready field")
    _assert(
        latest_readiness["status"] in {
            "formal_trace_ready",
            "diagnostic_iterations_full_coverage",
            "formal_iterations_incomplete_coverage",
            "diagnostic_iterations_incomplete_coverage",
            "missing_sidecar",
        },
        "Readiness route should return a known status",
    )

    print("impact_trace_sidecar_smoke_test: ok")


if __name__ == "__main__":
    main()
