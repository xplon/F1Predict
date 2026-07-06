"""Smoke test for source-backed prediction anomaly audit."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from f1predict.data_sources.augmented import CalendarAugmentedDataSource  # noqa: E402
from f1predict.prediction_anomaly import PredictionAnomalyAuditor  # noqa: E402
from f1predict.run_tracking import PredictionRunRegistry  # noqa: E402


def _latest_packet_path() -> Path:
    record = PredictionRunRegistry(ROOT / "reports" / "prediction_runs").latest("british_gp")
    assert record is not None, "no registered British GP prediction run found"
    assert record.prediction_packet_path, f"latest run missing prediction packet path: {record.run_id}"
    path = Path(record.prediction_packet_path)
    return path if path.is_absolute() else ROOT / path


def main() -> None:
    packet_path = _latest_packet_path()
    payload = json.loads(packet_path.read_text(encoding="utf-8"))
    season = CalendarAugmentedDataSource().load()
    audit = PredictionAnomalyAuditor().build(season, payload["prediction"])
    packet_audit = payload.get("prediction_anomaly_audit")
    assert packet_audit, f"latest packet missing prediction_anomaly_audit: {packet_path}"
    assert packet_audit["status"] == audit["status"]

    assert audit["coverage"]["driver_count"] == 22
    assert audit["coverage"]["state_update_count"] > 0
    assert audit["coverage"]["seed_or_blocked_update_count"] == 0
    assert audit["anomaly_count"] > 0
    assert "用户" not in json.dumps(audit, ensure_ascii=False)
    assert "model_input_weight" not in json.dumps(audit, ensure_ascii=False)

    anomalies = audit["anomalies"]
    assert any(row["code"] == "impact_trace_incomplete_for_material_updates" for row in anomalies)
    assert not any(
        row["code"] == "source_backed_negative_not_reflected" and row.get("target_id") == "alpine"
        for row in anomalies
    ), "Alpine team-level weak negative support has offsetting evidence and should not be a hard anomaly"
    for row in anomalies:
        assert row["expected_rank_summary_zh"]
        assert row["evidence_summary_zh"]
        assert row["model_risk_zh"]
        assert row["recommended_action_zh"]
        chain = row.get("source_to_prediction_chain") or []
        assert [stage["stage"] for stage in chain[:4]] == ["原始来源", "信息分析", "状态更新", "预测变化"]
        assert not any(str(source_id).startswith("seed") for source_id in row.get("supporting_source_ids", []))

    print("prediction anomaly audit smoke ok")


if __name__ == "__main__":
    main()
