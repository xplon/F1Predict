"""Source-to-prediction anomaly audit for traceable packets.

This module does not tune predictions.  It reads the prediction output and the
traceable state ledger, then flags places where the ranking looks difficult to
justify from the available source-backed inputs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from f1predict.domain import PredictionReport, SeasonState, utc_now
from f1predict.storage import safe_name


PACE_FACTORS = {
    "overall_pace",
    "race_pace",
    "qualifying_pace",
    "qualifying_ceiling",
    "race_execution",
    "long_run_consistency",
    "high_speed_corner",
    "medium_speed_corner",
    "low_speed_corner",
    "traction",
    "mechanical_grip",
    "aero_efficiency",
    "straight_line_speed",
    "power_unit_peak",
    "ers_deployment",
    "ers_recovery",
    "upgrade_delta",
    "first_lap_gain",
    "strategy_quality",
    "reliability",
}

RECENT_SOURCE_MARKERS = (
    "fastf1_form",
    "fastf1_momentum",
    "fastf1_season_form",
    "fastf1-team-strength-reestimate",
    "fastf1_team_strength_reestimate",
    "fastf1-finish-position-reestimate",
    "fastf1_finish_position_reestimate",
    "official_standings",
)

SAME_EVENT_SOURCE_MARKERS = (
    "fastf1_qualifying_result",
    "fastf1-qualifying-result",
    "fastf1_session_laps",
    "fastf1-session-laps",
)

TEAMMATE_CONFLICT_MIN_AVERAGE_FINISH_GAP = 0.40
TEAMMATE_CONFLICT_MIN_EXPECTED_POINTS_GAP = 0.10


@dataclass(frozen=True)
class _PredictionRow:
    driver_id: str
    team_id: str
    rank: int
    average_finish: float
    expected_points: float
    win: float
    podium: float
    points: float


@dataclass
class _TeamSupport:
    team_id: str
    driver_ids: list[str]
    positive_update_count: int = 0
    negative_update_count: int = 0
    source_ids: set[str] | None = None
    claim_ids: set[str] | None = None
    update_ids: list[str] | None = None
    recent_positive_count: int = 0
    recent_negative_count: int = 0
    same_event_positive_count: int = 0
    same_event_negative_count: int = 0
    net_value: float = 0.0
    positive_value: float = 0.0
    negative_value: float = 0.0
    team_positive_update_count: int = 0
    team_negative_update_count: int = 0
    team_recent_positive_count: int = 0
    team_recent_negative_count: int = 0
    team_same_event_positive_count: int = 0
    team_same_event_negative_count: int = 0
    team_net_value: float = 0.0
    team_positive_value: float = 0.0
    team_negative_value: float = 0.0

    def __post_init__(self) -> None:
        self.source_ids = set() if self.source_ids is None else self.source_ids
        self.claim_ids = set() if self.claim_ids is None else self.claim_ids
        self.update_ids = [] if self.update_ids is None else self.update_ids

    @property
    def source_count(self) -> int:
        return len(self.source_ids or set())

    def bucket(self) -> str:
        if self.net_value >= 0.16 and self.positive_update_count >= 4:
            return "strong_positive"
        if self.net_value >= 0.055 and self.positive_update_count >= 2:
            return "positive"
        if self.net_value > 0.018:
            return "slight_positive"
        if self.net_value <= -0.16 and self.negative_update_count >= 4:
            return "strong_negative"
        if self.net_value <= -0.055 and self.negative_update_count >= 2:
            return "negative"
        if self.net_value < -0.018:
            return "slight_negative"
        return "neutral"

    def recent_bucket(self) -> str:
        recent_net = self.recent_positive_count - self.recent_negative_count
        return _count_bucket(recent_net)

    def team_bucket(self) -> str:
        return _support_bucket(
            self.team_net_value,
            self.team_positive_update_count,
            self.team_negative_update_count,
        )

    def team_recent_bucket(self) -> str:
        recent_net = self.team_recent_positive_count - self.team_recent_negative_count
        return _count_bucket(recent_net)

    def team_weak_negative_with_counterevidence(self) -> bool:
        return (
            -0.09 < self.team_net_value <= -0.055
            and self.team_positive_update_count >= 2
            and self.team_positive_value >= 0.02
            and (self.team_recent_positive_count > 0 or self.team_same_event_positive_count > 0)
        )

    def weak_negative_with_counterevidence(self) -> bool:
        return (
            -0.09 < self.net_value <= -0.055
            and self.positive_update_count >= 2
            and self.positive_value >= 0.02
            and (self.recent_positive_count > 0 or self.same_event_positive_count > 0)
        )


@dataclass(frozen=True)
class _ImpactTraceEvidence:
    traces: list[dict[str, Any]]
    source: str
    sidecar_id: str | None = None
    comparison_status: str | None = None
    covered_claim_count: int = 0
    uncovered_claim_count: int = 0
    claim_count: int = 0

    @property
    def diagnostic_only(self) -> bool:
        return self.source == "sidecar" and self.comparison_status != "matched_source_run_iterations"


def _support_bucket(net_value: float, positive_count: int, negative_count: int) -> str:
    if net_value >= 0.16 and positive_count >= 4:
        return "strong_positive"
    if net_value >= 0.055 and positive_count >= 2:
        return "positive"
    if net_value > 0.018:
        return "slight_positive"
    if net_value <= -0.16 and negative_count >= 4:
        return "strong_negative"
    if net_value <= -0.055 and negative_count >= 2:
        return "negative"
    if net_value < -0.018:
        return "slight_negative"
    return "neutral"


def _count_bucket(recent_net: int) -> str:
    if recent_net >= 5:
        return "positive"
    if recent_net <= -5:
        return "negative"
    if recent_net > 0:
        return "slight_positive"
    if recent_net < 0:
        return "slight_negative"
    return "neutral"


class PredictionAnomalyAuditor:
    """Build a Chinese source-backed anomaly report for one prediction."""

    def build(
        self,
        season: SeasonState,
        report: PredictionReport | dict[str, Any],
        *,
        impact_trace_sidecar: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rows = self._prediction_rows(season, report)
        if not rows:
            return self._empty("没有可审计的车手排名。")
        report_dict = report.to_dict() if isinstance(report, PredictionReport) else report
        ledger = _as_list(report_dict.get("state_update_ledger"))
        belief_state = _as_dict(report_dict.get("belief_state"))
        features = _as_list(report_dict.get("feature_adjustments"))
        embedded_impact_trace = _as_list(report_dict.get("prediction_impact_trace"))
        trace_evidence = _impact_trace_evidence(embedded_impact_trace, impact_trace_sidecar)
        impact_trace = trace_evidence.traces
        sources = {
            str(row.get("source_id")): row
            for row in _as_list(belief_state.get("raw_sources"))
            if row.get("source_id")
        }
        team_support = self._team_support(season, rows, ledger, sources)
        qualifying_positions = self._same_event_qualifying_positions(features)
        anomalies: list[dict[str, Any]] = []
        anomalies.extend(self._team_support_anomalies(season, rows, team_support, sources, impact_trace))
        anomalies.extend(
            self._teammate_conflict_anomalies(
                season,
                rows,
                team_support,
                qualifying_positions,
                sources,
                impact_trace,
                ledger,
            )
        )
        anomalies.extend(self._impact_trace_gap_anomalies(ledger, trace_evidence, sources))
        anomalies = self._deduplicate_anomalies(anomalies)
        anomalies.sort(key=lambda row: (_severity_priority(row.get("severity")), row.get("anomaly_id", "")), reverse=True)
        limited = anomalies[:12]
        high_count = sum(1 for row in limited if row.get("severity") == "high")
        medium_count = sum(1 for row in limited if row.get("severity") == "medium")
        return {
            "generated_at": utc_now().replace(microsecond=0).isoformat(),
            "status": "requires_model_review" if high_count else "review_recommended" if limited else "no_major_anomaly_detected",
            "summary_zh": self._summary_zh(limited, high_count, medium_count),
            "anomaly_count": len(limited),
            "high_severity_count": high_count,
            "medium_severity_count": medium_count,
            "coverage": {
                "driver_count": len(rows),
                "team_count": len(team_support),
                "state_update_count": len(ledger),
                "source_backed_update_count": sum(1 for row in ledger if not _is_seed_or_blocked(row, sources)),
                "seed_or_blocked_update_count": sum(1 for row in ledger if _is_seed_or_blocked(row, sources)),
                "isolated_trace_count": sum(
                    1
                    for row in impact_trace
                    if row.get("trace_type") == "isolated_same_seed_leave_one_information"
                ),
                "embedded_isolated_trace_count": sum(
                    1
                    for row in embedded_impact_trace
                    if row.get("trace_type") == "isolated_same_seed_leave_one_information"
                ),
                "isolated_source_group_trace_count": sum(
                    1
                    for row in impact_trace
                    if row.get("trace_type") == "isolated_same_seed_leave_source_group"
                ),
                "route_only_trace_count": sum(1 for row in impact_trace if row.get("trace_type") == "state_update_route"),
                "impact_trace_source": trace_evidence.source,
                "impact_trace_sidecar_id": trace_evidence.sidecar_id,
                "impact_trace_sidecar_comparison_status": trace_evidence.comparison_status,
                "impact_trace_sidecar_diagnostic_only": trace_evidence.diagnostic_only,
                "impact_trace_claim_count": trace_evidence.claim_count,
                "impact_trace_covered_claim_count": trace_evidence.covered_claim_count,
                "impact_trace_uncovered_claim_count": trace_evidence.uncovered_claim_count,
            },
            "anomalies": limited,
        }

    @staticmethod
    def _empty(summary: str) -> dict[str, Any]:
        return {
            "generated_at": utc_now().replace(microsecond=0).isoformat(),
            "status": "no_major_anomaly_detected",
            "summary_zh": summary,
            "anomaly_count": 0,
            "high_severity_count": 0,
            "medium_severity_count": 0,
            "coverage": {},
            "anomalies": [],
        }

    @staticmethod
    def _prediction_rows(season: SeasonState, report: PredictionReport | dict[str, Any]) -> list[_PredictionRow]:
        probabilities = report.race_probabilities if isinstance(report, PredictionReport) else report.get("race_probabilities", [])
        normalized = []
        for raw in probabilities:
            driver_id = _field(raw, "driver_id")
            if not driver_id or driver_id not in season.drivers:
                continue
            normalized.append(
                {
                    "driver_id": driver_id,
                    "team_id": season.drivers[driver_id].team_id,
                    "average_finish": _float(_field(raw, "average_finish")),
                    "expected_points": _float(_field(raw, "expected_points")),
                    "win": _float(_field(raw, "win")),
                    "podium": _float(_field(raw, "podium")),
                    "points": _float(_field(raw, "points")),
                }
            )
        normalized.sort(key=lambda row: (row["average_finish"], -row["expected_points"]))
        return [
            _PredictionRow(rank=index, **row)
            for index, row in enumerate(normalized, start=1)
        ]

    def _team_support(
        self,
        season: SeasonState,
        rows: list[_PredictionRow],
        ledger: list[dict[str, Any]],
        sources: dict[str, dict[str, Any]],
    ) -> dict[str, _TeamSupport]:
        team_drivers: dict[str, list[str]] = {}
        for row in rows:
            team_drivers.setdefault(row.team_id, []).append(row.driver_id)
        support = {
            team_id: _TeamSupport(team_id=team_id, driver_ids=sorted(driver_ids))
            for team_id, driver_ids in team_drivers.items()
        }
        driver_to_team = {driver_id: driver.team_id for driver_id, driver in season.drivers.items()}
        for update in ledger:
            if _is_seed_or_blocked(update, sources):
                continue
            target_type = str(update.get("target_type") or "")
            target_id = str(update.get("target_id") or "")
            factor = str(update.get("factor") or "")
            if factor not in PACE_FACTORS:
                continue
            team_id = target_id if target_type == "team" else driver_to_team.get(target_id) if target_type == "driver" else None
            if not team_id or team_id not in support:
                continue
            delta = _float(update.get("delta"))
            row = support[team_id]
            row.net_value += delta
            if delta > 0:
                row.positive_update_count += 1
                row.positive_value += delta
            elif delta < 0:
                row.negative_update_count += 1
                row.negative_value += abs(delta)
            source_id = str(update.get("source_id") or "")
            claim_id = str(update.get("claim_id") or "")
            update_id = str(update.get("update_id") or "")
            if source_id:
                row.source_ids.add(source_id)
            if claim_id:
                row.claim_ids.add(claim_id)
            if update_id:
                row.update_ids.append(update_id)
            source_label = _source_label(update, sources)
            if _is_recent_source(source_label):
                if delta > 0:
                    row.recent_positive_count += 1
                elif delta < 0:
                    row.recent_negative_count += 1
            if _is_same_event_source(source_label):
                if delta > 0:
                    row.same_event_positive_count += 1
                elif delta < 0:
                    row.same_event_negative_count += 1
            if target_type == "team":
                row.team_net_value += delta
                if delta > 0:
                    row.team_positive_update_count += 1
                    row.team_positive_value += delta
                    if _is_recent_source(source_label):
                        row.team_recent_positive_count += 1
                    if _is_same_event_source(source_label):
                        row.team_same_event_positive_count += 1
                elif delta < 0:
                    row.team_negative_update_count += 1
                    row.team_negative_value += abs(delta)
                    if _is_recent_source(source_label):
                        row.team_recent_negative_count += 1
                    if _is_same_event_source(source_label):
                        row.team_same_event_negative_count += 1
        return support

    @staticmethod
    def _same_event_qualifying_positions(features: list[dict[str, Any]]) -> dict[str, int]:
        positions: dict[str, int] = {}
        for feature in features:
            source = str(feature.get("source") or feature.get("feature_id") or "")
            if not _is_same_event_source(source):
                continue
            if str(feature.get("metric") or "") != "qualifying_pace":
                continue
            driver_id = str(feature.get("target_id") or "")
            explanation = str(feature.get("explanation") or "")
            match = re.search(r"\bP(\d+)\s*/\s*\d+\b", explanation)
            if driver_id and match:
                positions[driver_id] = int(match.group(1))
        return positions

    def _team_support_anomalies(
        self,
        season: SeasonState,
        rows: list[_PredictionRow],
        support: dict[str, _TeamSupport],
        sources: dict[str, dict[str, Any]],
        impact_trace: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows_by_team: dict[str, list[_PredictionRow]] = {}
        for row in rows:
            rows_by_team.setdefault(row.team_id, []).append(row)
        anomalies: list[dict[str, Any]] = []
        for team_id, team_rows in rows_by_team.items():
            team_rows.sort(key=lambda row: row.rank)
            team_support = support.get(team_id)
            if team_support is None:
                continue
            bucket = team_support.team_bucket()
            recent_bucket = team_support.team_recent_bucket()
            best_rank = team_rows[0].rank
            avg_rank = sum(row.rank for row in team_rows) / max(1, len(team_rows))
            weak_counterevidence = (
                bucket == "negative"
                and best_rank > 8
                and avg_rank > 10.0
                and team_support.team_weak_negative_with_counterevidence()
            )
            if bucket in {"strong_negative", "negative"} and (best_rank <= 12 or avg_rank <= 13.0) and not weak_counterevidence:
                anomalies.append(
                    self._anomaly(
                        code="source_backed_negative_not_reflected",
                        severity="high" if best_rank <= 8 else "medium",
                        target_type="team",
                        target_id=team_id,
                        team_id=team_id,
                        driver_ids=[row.driver_id for row in team_rows],
                        expected_rank_summary_zh=(
                            f"{_team_name(season, team_id)} 当前最好预测为第 {best_rank}，"
                            f"双车平均预测约第 {avg_rank:.1f}。"
                        ),
                        evidence_summary_zh=(
                            f"来源化状态更新整体为{_bucket_zh(bucket)}："
                            f"{team_support.team_positive_update_count} 条车队/赛车正向、"
                            f"{team_support.team_negative_update_count} 条车队/赛车负向，"
                            f"其中近期/同周末信号为{_bucket_zh(recent_bucket)}。"
                        ),
                        model_risk_zh="如果负向的近期成绩、排位或速度信号已经进入状态向量，但预测仍在中游前列，说明旧先验、车手先验或排位到正赛映射可能仍然过强。",
                        recommended_action_zh="检查该队最近 3-5 站、同周末长距离、排位到正赛转换和旧 seed prior 的相对权重；不要按队名手调结果。",
                        support=team_support,
                        sources=sources,
                        impact_trace=impact_trace,
                    )
                )
            if bucket in {"strong_positive", "positive"} and (best_rank > 10 or avg_rank > 12.0):
                anomalies.append(
                    self._anomaly(
                        code="source_backed_positive_under_ranked",
                        severity="high" if best_rank > 14 else "medium",
                        target_type="team",
                        target_id=team_id,
                        team_id=team_id,
                        driver_ids=[row.driver_id for row in team_rows],
                        expected_rank_summary_zh=(
                            f"{_team_name(season, team_id)} 有正向来源化输入，但最好预测只到第 {best_rank}，"
                            f"双车平均预测约第 {avg_rank:.1f}。"
                        ),
                        evidence_summary_zh=(
                            f"来源化状态更新整体为{_bucket_zh(bucket)}："
                            f"{team_support.team_positive_update_count} 条车队/赛车正向、"
                            f"{team_support.team_negative_update_count} 条车队/赛车负向；"
                            f"近期窗口为{_bucket_zh(recent_bucket)}。"
                        ),
                        model_risk_zh="如果近期结构化表现已经转好但排名仍偏低，说明近期动量、升级/调校改善或同周末速度可能没有足够传导到模拟器。",
                        recommended_action_zh="优先复核近期窗口、同周末长距离和车队状态层的传导；需要来源化信息，而不是按主观判断调排名。",
                        support=team_support,
                        sources=sources,
                        impact_trace=impact_trace,
                    )
                )
            if recent_bucket == "positive" and best_rank > 10:
                anomalies.append(
                    self._anomaly(
                        code="recent_form_not_reflected",
                        severity="medium",
                        target_type="team",
                        target_id=team_id,
                        team_id=team_id,
                        driver_ids=[row.driver_id for row in team_rows],
                        expected_rank_summary_zh=f"{_team_name(season, team_id)} 近期来源信号偏正向，但最好预测为第 {best_rank}。",
                        evidence_summary_zh=(
                            f"近期窗口内有 {team_support.recent_positive_count} 条正向更新、"
                            f"{team_support.recent_negative_count} 条负向更新。"
                        ),
                        model_risk_zh="近期走势没有反映到最终排名，可能是衰减策略、历史先验或模拟噪声把新信息稀释了。",
                        recommended_action_zh="增加该队最近几站长距离、排位和可靠性拆分，并做同种子 isolated diff。",
                        support=team_support,
                        sources=sources,
                        impact_trace=impact_trace,
                    )
                )
        return anomalies

    def _teammate_conflict_anomalies(
        self,
        season: SeasonState,
        rows: list[_PredictionRow],
        support: dict[str, _TeamSupport],
        qualifying_positions: dict[str, int],
        sources: dict[str, dict[str, Any]],
        impact_trace: list[dict[str, Any]],
        ledger: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        by_driver = {row.driver_id: row for row in rows}
        team_drivers: dict[str, list[str]] = {}
        for row in rows:
            team_drivers.setdefault(row.team_id, []).append(row.driver_id)
        anomalies: list[dict[str, Any]] = []
        for team_id, driver_ids in team_drivers.items():
            if len(driver_ids) < 2:
                continue
            for driver_id in driver_ids:
                for teammate_id in driver_ids:
                    if driver_id == teammate_id:
                        continue
                    driver_q = qualifying_positions.get(driver_id)
                    teammate_q = qualifying_positions.get(teammate_id)
                    if driver_q is None or teammate_q is None or driver_q >= teammate_q:
                        continue
                    driver_rank = by_driver[driver_id].rank
                    teammate_rank = by_driver[teammate_id].rank
                    if driver_rank - teammate_rank < 2:
                        continue
                    driver_prediction = by_driver[driver_id]
                    teammate_prediction = by_driver[teammate_id]
                    average_finish_gap = driver_prediction.average_finish - teammate_prediction.average_finish
                    expected_points_gap = teammate_prediction.expected_points - driver_prediction.expected_points
                    if (
                        average_finish_gap < TEAMMATE_CONFLICT_MIN_AVERAGE_FINISH_GAP
                        and expected_points_gap < TEAMMATE_CONFLICT_MIN_EXPECTED_POINTS_GAP
                    ):
                        continue
                    relevant_support = support.get(team_id)
                    driver_updates = [
                        row
                        for row in ledger
                        if str(row.get("target_type") or "") == "driver"
                        and str(row.get("target_id") or "") in {driver_id, teammate_id}
                        and not _is_seed_or_blocked(row, sources)
                    ]
                    update_ids = [str(row.get("update_id")) for row in driver_updates if row.get("update_id")]
                    claim_ids = {str(row.get("claim_id")) for row in driver_updates if row.get("claim_id")}
                    source_ids = {str(row.get("source_id")) for row in driver_updates if row.get("source_id")}
                    local_support = _TeamSupport(team_id=team_id, driver_ids=[driver_id, teammate_id])
                    local_support.update_ids.extend(update_ids)
                    local_support.claim_ids.update(claim_ids)
                    local_support.source_ids.update(source_ids)
                    if relevant_support:
                        local_support.update_ids.extend((relevant_support.update_ids or [])[:6])
                        local_support.claim_ids.update(set(list(relevant_support.claim_ids or set())[:6]))
                        local_support.source_ids.update(set(list(relevant_support.source_ids or set())[:6]))
                    anomalies.append(
                        self._anomaly(
                            code="teammate_order_conflict",
                            severity="high" if driver_rank - teammate_rank >= 4 else "medium",
                            target_type="driver_pair",
                            target_id=f"{driver_id}_vs_{teammate_id}",
                            team_id=team_id,
                            driver_ids=[driver_id, teammate_id],
                            expected_rank_summary_zh=(
                                f"{_driver_name(season, driver_id)} 同场排位 P{driver_q}，"
                                f"{_driver_name(season, teammate_id)} 同场排位 P{teammate_q}；"
                                f"但预测中前者第 {driver_rank}，后者第 {teammate_rank}。"
                                f"平均完赛名次差 {average_finish_gap:.2f}，期望积分差 {expected_points_gap:.2f}。"
                            ),
                            evidence_summary_zh="同队比较中，排位/发车位来源化输入与最终正赛预测顺序存在明显张力。",
                            model_risk_zh="这不一定说明排名必错，但当前解释必须证明正赛长距离、保胎、策略或近期状态足以覆盖同场排位差异；否则就是模型校准风险。",
                            recommended_action_zh="复核两名车手的长距离、轮胎衰退、正赛执行和队内策略优先级来源，并补全 isolated same-seed 影响追踪。",
                            support=local_support,
                            sources=sources,
                            impact_trace=impact_trace,
                        )
                    )
        return anomalies

    def _impact_trace_gap_anomalies(
        self,
        ledger: list[dict[str, Any]],
        trace_evidence: _ImpactTraceEvidence,
        sources: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        impact_trace = trace_evidence.traces
        isolated_claims = {
            str(row.get("claim_id"))
            for row in impact_trace
            if row.get("trace_type") == "isolated_same_seed_leave_one_information" and row.get("claim_id")
        }
        grouped_claims = {
            str(claim_id)
            for row in impact_trace
            if row.get("trace_type") == "isolated_same_seed_leave_source_group"
            for claim_id in _as_values(row.get("claim_ids"))
            if claim_id
        }
        covered_claims = isolated_claims | grouped_claims
        if trace_evidence.source == "sidecar" and trace_evidence.uncovered_claim_count == 0 and covered_claims:
            return []
        routed_updates = [
            row
            for row in ledger
            if not _is_seed_or_blocked(row, sources)
            and str(row.get("claim_id") or "") not in covered_claims
        ]
        if len(routed_updates) <= max(8, len(covered_claims) // 3):
            return []
        selected = sorted(routed_updates, key=lambda row: abs(_float(row.get("delta"))), reverse=True)[:8]
        support = _TeamSupport(team_id="all", driver_ids=[])
        support.update_ids.extend(str(row.get("update_id")) for row in selected if row.get("update_id"))
        support.claim_ids.update(str(row.get("claim_id")) for row in selected if row.get("claim_id"))
        support.source_ids.update(str(row.get("source_id")) for row in selected if row.get("source_id"))
        return [
            self._anomaly(
                code="impact_trace_incomplete_for_material_updates",
                severity="medium",
                target_type="prediction_run",
                target_id="all_state_updates",
                team_id=None,
                driver_ids=[],
                expected_rank_summary_zh="当前预测已有状态更新路由，但大量更新还没有逐条同种子隔离重跑。",
                evidence_summary_zh=(
                    f"{len(ledger)} 条状态更新中，{len(isolated_claims)} 组已有单条 isolated 影响追踪，"
                    f"{len(grouped_claims)} 组已被来源组 isolated 影响追踪覆盖；"
                    "其余主要只能证明进入了状态向量，不能证明单条因果影响。"
                ),
                model_risk_zh="解释链条仍可能把“进入模型”误说成“证明改变预测”。",
                recommended_action_zh="提高 isolated-impact-limit 或按来源组批量重跑，把 route-only 记录升级成同种子差异证据。",
                support=support,
                sources=sources,
                impact_trace=impact_trace,
            )
        ]

    def _anomaly(
        self,
        *,
        code: str,
        severity: str,
        target_type: str,
        target_id: str,
        team_id: str | None,
        driver_ids: list[str],
        expected_rank_summary_zh: str,
        evidence_summary_zh: str,
        model_risk_zh: str,
        recommended_action_zh: str,
        support: _TeamSupport,
        sources: dict[str, dict[str, Any]],
        impact_trace: list[dict[str, Any]],
    ) -> dict[str, Any]:
        claim_ids = sorted(support.claim_ids or set())[:10]
        source_ids = sorted(support.source_ids or set())[:10]
        claim_id_set = set(claim_ids)
        source_id_set = set(source_ids)
        impact_ids = []
        for row in impact_trace:
            impact_id = str(row.get("impact_trace_id") or "")
            if not impact_id:
                continue
            row_claim_ids = {
                str(value)
                for value in [row.get("claim_id"), *_as_values(row.get("claim_ids"))]
                if value
            }
            row_source_ids = {
                str(value)
                for value in [row.get("source_id"), *_as_values(row.get("source_ids"))]
                if value
            }
            group_id = str(row.get("update_id_or_group_id") or "")
            if row_claim_ids & claim_id_set or row_source_ids & source_id_set or group_id in claim_id_set:
                impact_ids.append(impact_id)
            if len(impact_ids) >= 8:
                break
        trace_status = "isolated_impact_available" if impact_ids else "state_route_only"
        return {
            "anomaly_id": safe_name(f"anomaly_{code}_{target_id}"),
            "code": code,
            "severity": severity,
            "target_type": target_type,
            "target_id": target_id,
            "team_id": team_id,
            "driver_ids": list(driver_ids),
            "expected_rank_summary_zh": expected_rank_summary_zh,
            "evidence_summary_zh": evidence_summary_zh,
            "model_risk_zh": model_risk_zh,
            "recommended_action_zh": recommended_action_zh,
            "trace_status": trace_status,
            "supporting_update_ids": list(dict.fromkeys(support.update_ids or []))[:10],
            "supporting_claim_ids": claim_ids,
            "supporting_source_ids": source_ids,
            "supporting_sources": [self._source_summary(source_id, sources.get(source_id, {})) for source_id in source_ids[:5]],
            "impact_trace_ids": list(dict.fromkeys(impact_ids)),
            "source_to_prediction_chain": self._chain_zh(support, sources, impact_ids),
        }

    @staticmethod
    def _source_summary(source_id: str, source: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_id": source_id,
            "source_type_zh": _source_type_zh(str(source.get("source_type") or "")),
            "publisher": source.get("publisher"),
            "title": source.get("title"),
            "captured_at": source.get("captured_at"),
        }

    @staticmethod
    def _chain_zh(support: _TeamSupport, sources: dict[str, dict[str, Any]], impact_ids: list[str]) -> list[dict[str, str]]:
        source_titles = [
            str((sources.get(source_id) or {}).get("title") or source_id)
            for source_id in sorted(support.source_ids or set())[:3]
        ]
        return [
            {
                "stage": "原始来源",
                "text_zh": "；".join(source_titles) if source_titles else "没有找到可展示的原始来源摘要。",
            },
            {
                "stage": "信息分析",
                "text_zh": f"这些来源被标准化为 {len(support.claim_ids or set())} 个因子声明。",
            },
            {
                "stage": "状态更新",
                "text_zh": f"相关声明产生 {len(support.update_ids or [])} 条状态更新，方向由来源、时效、机制和冲突门控决定。",
            },
            {
                "stage": "预测变化",
                "text_zh": (
                    f"已关联 {len(impact_ids)} 条同种子影响追踪。"
                    if impact_ids
                    else "目前主要是状态路由证据，还需要 isolated same-seed 重跑证明单条影响。"
                ),
            },
        ]

    @staticmethod
    def _deduplicate_anomalies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for row in rows:
            key = str(row.get("anomaly_id") or "")
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        return unique

    @staticmethod
    def _summary_zh(rows: list[dict[str, Any]], high_count: int, medium_count: int) -> str:
        if not rows:
            return "没有发现高优先级预测异常；这只表示当前规则没有发现明显冲突，不等于预测已具备正式 edge。"
        return (
            f"发现 {len(rows)} 个需要复核的预测异常，其中高优先级 {high_count} 个、中优先级 {medium_count} 个。"
            "这些异常不修改预测，只提示来源事实、状态更新和最终排名之间的张力。"
        )


def _field(row: Any, name: str) -> Any:
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


def _as_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _impact_trace_evidence(
    embedded_impact_trace: list[dict[str, Any]],
    sidecar: dict[str, Any] | None,
) -> _ImpactTraceEvidence:
    if isinstance(sidecar, dict):
        sidecar_traces = _as_list(sidecar.get("traces"))
        if sidecar_traces:
            coverage = _as_dict(sidecar.get("coverage"))
            generation = _as_dict(sidecar.get("trace_generation"))
            return _ImpactTraceEvidence(
                traces=sidecar_traces,
                source="sidecar",
                sidecar_id=str(sidecar.get("sidecar_id") or "") or None,
                comparison_status=str(generation.get("comparison_status") or "") or None,
                claim_count=int(_float(coverage.get("impact_trace_claim_count"))),
                covered_claim_count=int(_float(coverage.get("impact_trace_covered_claim_count"))),
                uncovered_claim_count=int(_float(coverage.get("impact_trace_uncovered_claim_count"))),
            )
    embedded_claims = {
        str(row.get("claim_id"))
        for row in embedded_impact_trace
        if row.get("trace_type") == "isolated_same_seed_leave_one_information" and row.get("claim_id")
    }
    grouped_claims = {
        str(claim_id)
        for row in embedded_impact_trace
        if row.get("trace_type") == "isolated_same_seed_leave_source_group"
        for claim_id in _as_values(row.get("claim_ids"))
        if claim_id
    }
    covered_claims = embedded_claims | grouped_claims
    return _ImpactTraceEvidence(
        traces=embedded_impact_trace,
        source="embedded_packet",
        claim_count=len(covered_claims),
        covered_claim_count=len(covered_claims),
        uncovered_claim_count=0,
    )


def _as_values(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _is_seed_or_blocked(update: dict[str, Any], sources: dict[str, dict[str, Any]]) -> bool:
    if str(update.get("update_permission") or "") == "blocked":
        return True
    reasons = " ".join(str(item) for item in update.get("quality_reasons") or [])
    if "seed_scenario_source" in reasons:
        return True
    source = sources.get(str(update.get("source_id") or ""), {})
    text = " ".join(
        str(source.get(key) or "")
        for key in ("source_id", "source_type", "url", "title", "publisher")
    ).lower()
    return "seed://" in text or "seed scenario" in text


def _source_label(update: dict[str, Any], sources: dict[str, dict[str, Any]]) -> str:
    source = sources.get(str(update.get("source_id") or ""), {})
    return " ".join(
        str(value or "")
        for value in (
            update.get("claim_id"),
            update.get("source_id"),
            source.get("title"),
            source.get("publisher"),
            source.get("source_type"),
        )
    ).lower()


def _is_recent_source(label: str) -> bool:
    lower = label.lower()
    return any(marker in lower for marker in RECENT_SOURCE_MARKERS)


def _is_same_event_source(label: str) -> bool:
    lower = label.lower()
    return any(marker in lower for marker in SAME_EVENT_SOURCE_MARKERS)


def _severity_priority(value: Any) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(str(value), 0)


def _source_type_zh(source_type: str) -> str:
    labels = {
        "structured_feature": "结构化特征",
        "codex_evidence_claim": "非结构化证据声明",
    }
    return labels.get(source_type, source_type or "来源类型未知")


def _bucket_zh(bucket: str) -> str:
    labels = {
        "strong_positive": "明显偏强",
        "positive": "偏强",
        "slight_positive": "略偏强",
        "neutral": "中性",
        "slight_negative": "略偏弱",
        "negative": "偏弱",
        "strong_negative": "明显偏弱",
    }
    return labels.get(bucket, bucket)


def _team_name(season: SeasonState, team_id: str) -> str:
    team = season.teams.get(team_id)
    return team.name if team is not None else team_id


def _driver_name(season: SeasonState, driver_id: str) -> str:
    driver = season.drivers.get(driver_id)
    return driver.name if driver is not None else driver_id
