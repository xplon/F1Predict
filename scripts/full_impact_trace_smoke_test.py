"""Smoke test for full same-seed isolated impact trace coverage.

This is a diagnostic coverage test, not a probability-quality benchmark.  It
uses a tiny iteration count so CI/local checks can prove that every state
update can receive an isolated trace without turning the smoke suite into a
full race forecast.
"""

from __future__ import annotations

from collections import Counter

from f1predict.pipeline import PredictionPipeline
from f1predict.prediction_packet import PredictionPacketBuilder


def main() -> None:
    packet = PredictionPacketBuilder(
        PredictionPipeline(
            iterations=5,
            isolated_impact_limit=-1,
            isolated_source_group_limit=0,
        )
    ).build(
        "british_gp",
        knowledge_cutoff="2026-07-05T00:00:00+00:00",
        iterations=5,
    )
    trace_counts = Counter(
        row.get("trace_type")
        for row in packet.prediction.get("prediction_impact_trace", [])
    )
    assert packet.codex_context["state_update_count"] == 453
    assert packet.codex_context["impact_trace_claim_count"] == 453
    assert packet.codex_context["impact_trace_single_claim_coverage_count"] == 453
    assert packet.codex_context["impact_trace_covered_claim_count"] == 453
    assert packet.codex_context["impact_trace_uncovered_claim_count"] == 0
    assert trace_counts["isolated_same_seed_leave_one_information"] == 453
    assert not any(
        row.get("code") == "impact_trace_incomplete_for_material_updates"
        for row in packet.prediction_anomaly_audit.get("anomalies", [])
    )
    print("full_impact_trace_smoke_test: ok")


if __name__ == "__main__":
    main()
