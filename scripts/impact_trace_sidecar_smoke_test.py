"""Smoke checks for cached prediction-impact trace sidecars."""

from __future__ import annotations

from pathlib import Path
import sys


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
