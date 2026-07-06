"""Smoke test for source-backed prediction anomaly audit."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from f1predict.api_v2 import BackendApiV2  # noqa: E402
from f1predict.data_sources.augmented import CalendarAugmentedDataSource  # noqa: E402
from f1predict.domain import DriverRaceProbability, race_probability_rows_for_display  # noqa: E402
from f1predict.prediction_anomaly import PredictionAnomalyAuditor  # noqa: E402
from f1predict.run_tracking import PredictionRunRegistry  # noqa: E402


def _latest_packet_path() -> Path:
    record = PredictionRunRegistry(ROOT / "reports" / "prediction_runs").latest("british_gp")
    assert record is not None, "no registered British GP prediction run found"
    assert record.prediction_packet_path, f"latest run missing prediction packet path: {record.run_id}"
    path = Path(record.prediction_packet_path)
    return path if path.is_absolute() else ROOT / path


def main() -> None:
    display_rows = race_probability_rows_for_display(
        [
            DriverRaceProbability("win_leader", win=0.7, podium=0.7, points=0.7, expected_points=5.0, average_finish=8.0),
            DriverRaceProbability("rank_leader", win=0.2, podium=0.9, points=1.0, expected_points=18.0, average_finish=2.0),
        ]
    )
    assert [row["driver_id"] for row in display_rows] == ["rank_leader", "win_leader"]
    assert [row["expected_rank"] for row in display_rows] == [1, 2]

    api = BackendApiV2(ROOT)
    response = api.handle_get("/api/v2/prediction-packets/latest", {"event_id": ["british_gp"]})
    assert response and response.status == 200
    payload = response.payload
    cache_context = payload.get("cache_context") or {}
    probability_rows = payload["prediction"]["race_probabilities"]
    assert len(probability_rows) == 22
    assert [row.get("expected_rank") for row in probability_rows] == list(range(1, 23))
    average_finishes = [float(row["average_finish"]) for row in probability_rows]
    assert average_finishes == sorted(average_finishes), "API race_probabilities should be expected-rank ordered"

    packet_path = _latest_packet_path()
    season = CalendarAugmentedDataSource().load()
    sidecar = api.impact_trace_store.latest(event_id="british_gp", run_id=cache_context.get("run_id"))
    audit = PredictionAnomalyAuditor().build(season, payload["prediction"], impact_trace_sidecar=sidecar)
    packet_audit = payload.get("prediction_anomaly_audit")
    assert packet_audit, f"latest packet missing prediction_anomaly_audit: {packet_path}"
    assert packet_audit["status"] == audit["status"]
    assert packet_audit["anomaly_count"] == audit["anomaly_count"]
    assert cache_context.get("prediction_anomaly_audit_source") == "api_runtime_recomputed"

    assert audit["coverage"]["driver_count"] == 22
    assert audit["coverage"]["state_update_count"] > 0
    assert audit["coverage"]["seed_or_blocked_update_count"] == 0
    assert audit["coverage"]["impact_trace_source"] == "sidecar"
    assert audit["coverage"]["impact_trace_claim_count"] == audit["coverage"]["state_update_count"]
    assert audit["coverage"]["impact_trace_covered_claim_count"] == audit["coverage"]["impact_trace_claim_count"]
    assert audit["coverage"]["impact_trace_uncovered_claim_count"] == 0
    assert "用户" not in json.dumps(audit, ensure_ascii=False)
    assert "model_input_weight" not in json.dumps(audit, ensure_ascii=False)

    anomalies = audit["anomalies"]
    assert not any(row["code"] == "impact_trace_incomplete_for_material_updates" for row in anomalies)
    assert not any(
        row["code"] == "source_backed_negative_not_reflected" and row.get("target_id") == "alpine"
        for row in anomalies
    ), "Alpine team-level weak negative support has offsetting evidence and should not be a hard anomaly"
    assert any(
        row["code"] == "driver_specific_lift_over_weak_team_support"
        and row.get("target_id") == "gasly"
        and row.get("severity") == "low"
        for row in anomalies
    ), "Gasly P9 over weak Alpine team support should remain visible as a low-priority review item"
    assert not any(
        row["code"] == "teammate_order_conflict" and row.get("target_id") == "bortoleto_vs_hulkenberg"
        for row in anomalies
    ), "Near-tie teammate ordinal ranks should not be reported as material order conflicts"
    for row in anomalies:
        assert row["expected_rank_summary_zh"]
        assert row["evidence_summary_zh"]
        assert row["model_risk_zh"]
        assert row["recommended_action_zh"]
        chain = row.get("source_to_prediction_chain") or []
        assert [stage["stage"] for stage in chain[:5]] == ["原始来源", "信息分析", "状态更新", "模拟路由", "预测变化"]
        assert not any(str(source_id).startswith("seed") for source_id in row.get("supporting_source_ids", []))

    print("prediction anomaly audit smoke ok")


if __name__ == "__main__":
    main()
