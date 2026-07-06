"""Smoke test for source-backed prediction anomaly audit."""

from __future__ import annotations

import json
from pathlib import Path

from f1predict.data_sources.augmented import CalendarAugmentedDataSource
from f1predict.prediction_anomaly import PredictionAnomalyAuditor


ROOT = Path(__file__).resolve().parents[1]
PACKET_ROOT = ROOT / "reports" / "prediction_packets_v2" / "british_gp"


def main() -> None:
    packets = sorted(PACKET_ROOT.rglob("*.prediction_packet.json"), key=lambda path: path.stat().st_mtime)
    assert packets, "no registered British GP prediction packets found"
    packet_path = packets[-1]
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
    assert any(row["code"] == "source_backed_negative_not_reflected" for row in anomalies)
    assert any(row["code"] == "impact_trace_incomplete_for_material_updates" for row in anomalies)
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
