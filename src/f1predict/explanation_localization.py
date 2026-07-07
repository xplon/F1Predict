"""Chinese public labels for traceable prediction explanations."""

from __future__ import annotations

import re
from typing import Any


TEAM_LABELS = {
    "aston_martin": "阿斯顿马丁",
    "cadillac": "凯迪拉克",
    "ferrari": "法拉利",
    "haas": "哈斯",
    "mclaren": "迈凯伦",
    "mercedes": "梅赛德斯",
    "red_bull": "红牛",
    "racing_bulls": "小红牛",
    "sauber": "索伯",
    "williams": "威廉姆斯",
    "Aston Martin": "阿斯顿马丁",
    "Cadillac": "凯迪拉克",
    "Ferrari": "法拉利",
    "Haas": "哈斯",
    "McLaren": "迈凯伦",
    "Mercedes": "梅赛德斯",
    "Red Bull": "红牛",
    "Racing Bulls": "小红牛",
    "Sauber": "索伯",
    "Williams": "威廉姆斯",
}

EVENT_LABELS = {
    "British Grand Prix": "英国大奖赛",
    "Barcelona Grand Prix": "巴塞罗那大奖赛",
    "Spanish Grand Prix": "西班牙大奖赛",
    "Monaco Grand Prix": "摩纳哥大奖赛",
    "Canadian Grand Prix": "加拿大大奖赛",
    "Austrian Grand Prix": "奥地利大奖赛",
}

METRIC_LABELS = {
    "overall_pace": "赛车整体速度",
    "race_pace": "正赛速度",
    "qualifying_pace": "排位速度",
    "qualifying_ceiling": "排位上限",
    "qualifying_consistency": "排位稳定性",
    "race_execution": "正赛执行",
    "long_run_consistency": "长距离稳定性",
    "tyre_deg": "轮胎衰退",
    "tyre_management": "保胎能力",
    "wet_skill": "湿地能力",
    "reliability": "可靠性",
    "strategy": "策略能力",
    "strategy_quality": "策略质量",
    "setup_quality": "调校窗口质量",
    "power_unit": "动力单元",
    "power_unit_peak": "动力单元峰值",
    "energy_recovery": "能量回收/部署",
    "ers_deployment": "能量部署",
    "ers_recovery": "能量回收",
    "straight_line_speed": "直道速度",
    "drag": "阻力水平",
    "drag_efficiency": "气动效率",
    "aero_efficiency": "气动效率",
    "low_speed_traction": "低速牵引",
    "traction": "牵引力",
    "mechanical_grip": "机械抓地力",
    "launch_performance": "起步表现",
    "upgrade_effect": "升级效果",
    "upgrade_delta": "升级效果",
    "attack_racecraft": "进攻缠斗",
    "defense_racecraft": "防守缠斗",
    "first_lap_gain": "起步首圈",
    "incident_risk": "事故风险",
    "penalty_risk": "处罚风险",
    "setup_feedback": "调校反馈",
    "team_priority": "队内资源优先级",
    "wet_probability": "湿地概率",
    "safety_car_probability": "安全车概率",
    "red_flag_probability": "红旗概率",
}

DIRECTION_LABELS = {
    "positive": "正向",
    "negative": "负向",
    "neutral": "中性",
}

BUCKET_LABELS = {
    "strong_positive": "明显偏强",
    "positive": "偏强",
    "slight_positive": "略强",
    "neutral": "中性",
    "slight_negative": "略弱",
    "negative": "偏弱",
    "strong_negative": "明显偏弱",
    "large": "大幅",
    "medium": "中等",
    "small": "小幅",
    "very_small": "很小",
    "tiny": "很小",
    "none": "无明显变化",
    "not_isolated_yet": "尚未单条重跑",
}

PERMISSION_LABELS = {
    "blocked": "不允许更新",
    "weak_update": "弱更新",
    "normal_update": "正常更新",
    "strong_update": "强更新",
}

SURFACE_LABELS = {
    "race_pace_score": "正赛速度表面",
    "qualifying_grid_sampler": "排位/发车位采样器",
    "stint_degradation": "轮胎衰退表面",
    "strategy_plan": "策略计划表面",
    "pit_strategy": "进站策略表面",
    "safety_car_window": "安全车窗口表面",
    "safety_car_sampler": "安全车采样器",
    "field_bunching": "车阵压缩表面",
    "red_flag_sampler": "红旗采样器",
    "race_restart_variance": "重启波动表面",
    "race_window_pressure": "比赛日窗口压力表面",
    "dnf_sampler": "退赛采样器",
    "wet_race_branch": "湿地分支",
}

REASON_LABELS = {
    "source_backed_timing_data": "有计时数据来源",
    "specific_event_observation": "本场观测",
    "structured_recent_results": "近期结构化成绩",
    "source_backed_points_or_classification": "有积分或排名来源",
    "recent_window_structured_feature": "近期窗口结构化特征",
    "low_confidence_context_feature": "低置信背景特征",
    "unscored_codex_claim": "待质量评分",
    "claim_requires_review": "声明需要复核",
    "single_source_claim": "单一来源",
    "seed_scenario_source": "种子场景来源，已阻断入模",
    "source_log_missing": "缺少来源日志",
    "seed_only_triangulation": "仅 seed/test 佐证",
    "claim_not_linked_to_source_record": "声明未链接到来源记录",
    "claim_after_cutoff": "声明晚于知识截止",
    "source_after_cutoff": "来源晚于知识截止",
    "snapshot_after_cutoff": "快照晚于知识截止",
}

QUALITY_STATUS_LABELS = {
    "strong": "来源强，可正常更新",
    "medium": "诊断可用",
    "usable_diagnostic": "诊断可用",
    "weak_diagnostic": "弱诊断",
    "review_required": "需要复核",
}

SOURCE_STATUS_LABELS = {
    "within_cutoff": "在知识截止前可用",
    "source_log_missing": "缺少来源日志",
    "unknown_published_at": "发布时间不清，需要复核",
    "source_after_cutoff": "来源晚于知识截止，已阻断",
    "claim_after_cutoff": "声明晚于知识截止，已阻断",
    "snapshot_after_cutoff": "快照晚于知识截止，只能诊断",
}


def localize_prediction_payload_zh(payload: dict[str, Any]) -> dict[str, Any]:
    prediction = payload.get("prediction") if isinstance(payload.get("prediction"), dict) else {}
    _localize_prediction_section(prediction)
    return payload


def localize_sidecar_page_zh(payload: dict[str, Any]) -> dict[str, Any]:
    for row in _list(payload.get("traces")):
        _localize_trace_row(row)
    return payload


def localized_mechanism_zh(
    text: Any,
    *,
    feature_id: str = "",
    source: str = "",
    metric: str = "",
    event_name: str = "",
) -> str:
    raw = str(text or "").strip()
    if not raw:
        return "没有记录机制说明。"
    parsed = _parsed_feature_explanation(raw, feature_id=feature_id, source=source, metric=metric, event_name=event_name)
    if parsed:
        return parsed
    normalized = localize_public_text_zh(raw)
    if _looks_publicly_chinese(normalized):
        return normalized
    return (
        f"{source_label_zh(feature_id=feature_id, source=source, explanation=raw)}；"
        "该结构化特征已转成有界输入，用于移动对应状态先验；"
        f"关键信息：{_compact_english_phrase(normalized)}。"
    )


def localize_public_text_zh(text: Any) -> str:
    output = str(text or "")
    if not output:
        return output
    output = _replace_known_entities(output)
    output = _replace_claim_prefix(output)
    replacements = {
        "Cutoff-valid FastF1 race results": "知识截止前可用的 FastF1 正赛结果",
        "Cutoff-valid FastF1 full-field race classifications": "知识截止前可用的 FastF1 全场正赛排名",
        "Same-event FastF1 qualifying classification": "同一比赛周末 FastF1 排位结果",
        "Same-event FastF1 qualifying team average position": "同一比赛周末 FastF1 车队平均排位",
        "Official driver standings": "官方车手积分榜",
        "Official constructor standings": "官方车队积分榜",
        "Historical OpenF1 analogue rank": "OpenF1 历史相似场景排名",
        "Historical analogue race had meaningful rainfall": "历史相似正赛出现明显降雨",
        "FastF1 recent-vs-older team form": "FastF1 车队近期相对更早窗口状态",
        "FastF1 recent-vs-older form": "FastF1 车手近期相对更早窗口状态",
        "team total points per race": "车队每站积分",
        "average points": "平均积分",
        "driver average points": "车手平均积分",
        "driver recent-window average finish": "车手近期窗口平均完赛名次",
        "team recent-window average finish": "车队近期窗口平均完赛名次",
        "average finish": "平均完赛名次",
        "relative points delta": "相对积分变化",
        "average opportunity-normalized grid-to-finish conversion": "机会归一化发车到完赛转换均值",
        "opportunity-normalized finished-race grid-to-finish conversion": "机会归一化完赛发车到完赛转换",
        "grid-to-finish conversion": "发车到完赛转换",
        "non-finished classification(s)": "次未完赛记录",
        "non-finished classification": "未完赛记录",
        "long-run proxy": "长距离速度代理值",
        "team long-run proxy": "车队长距离速度代理值",
        "Confidence was down-weighted": "置信度被降低",
        "same-weekend qualifying position": "同一比赛周末排位位置",
        "fuel-load, compound, and run-plan comparability remain uncertain": "油量、轮胎配方和跑法可比性仍不确定",
        "team field": "车队全场均值",
        "tyre-degradation proxy": "轮胎衰退代理值",
        "speed-trap average": "测速点均速",
        "best valid lap": "最快有效圈",
        "driver wet-skill prior gets a small confidence-weighted boost": "车手湿地能力先验获得小幅、按置信度折算的正向修正",
        "wet-skill prior": "湿地能力先验",
        "confidence-weighted boost": "按置信度折算的正向修正",
        "qualifying team average position": "车队平均排位名次",
        "qualifying classification": "排位结果",
        "full-field race classifications": "全场正赛排名",
        "full-field finish": "全场完赛顺位",
        "points-only scoring": "只看积分的前十截断计分",
        "P11-P22 outcomes": "第 11 到第 22 名完赛结果",
        "before": "在",
        "vs field": "对比全场均值",
        "confidence": "置信度",
        "race(s)": "场正赛",
        "race result(s)": "场正赛结果",
        "previous": "此前",
        "across": "覆盖",
        "over": "覆盖",
        "driver": "车手",
        "team": "车队",
        "event": "比赛",
        "claim": "信息声明",
        "mechanism": "机制",
        "quality": "质量",
        "source_state": "来源状态",
        "model_surface": "模型表面",
        "route_formula_id": "路由公式",
        "track_context_multiplier": "赛道情境倍率",
        "matched_source_run_iterations": "与源预测迭代数一致",
        "diagnostic_iteration_mismatch": "诊断迭代数不一致",
        "observed_probability_movement": "已观察到预测变化",
        "state_route_only": "仅有状态路由证据",
    }
    for old, new in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        output = output.replace(old, new)
    for raw, label in {**METRIC_LABELS, **DIRECTION_LABELS, **BUCKET_LABELS, **PERMISSION_LABELS, **SURFACE_LABELS}.items():
        output = _replace_token(output, raw, label)
    return _normalize_spacing(output)


def metric_label_zh(value: Any) -> str:
    key = str(value or "")
    return METRIC_LABELS.get(key, key or "未知因子")


def direction_label_zh(value: Any) -> str:
    key = str(value or "")
    return DIRECTION_LABELS.get(key, key or "未知方向")


def bucket_label_zh(value: Any) -> str:
    key = str(value or "")
    return BUCKET_LABELS.get(key, key or "未知幅度")


def permission_label_zh(value: Any) -> str:
    key = str(value or "")
    return PERMISSION_LABELS.get(key, key or "权限未记录")


def surface_label_zh(value: Any) -> str:
    key = str(value or "")
    return SURFACE_LABELS.get(key, metric_label_zh(key) if key else "模型表面未记录")


def reason_label_zh(value: Any) -> str:
    key = str(value or "")
    return REASON_LABELS.get(key, key or "质量理由未记录")


def quality_status_label_zh(value: Any) -> str:
    key = str(value or "")
    return QUALITY_STATUS_LABELS.get(key, key or "质量未知")


def source_status_label_zh(value: Any) -> str:
    key = str(value or "")
    return SOURCE_STATUS_LABELS.get(key, key or "来源时效未知")


def target_text_zh(target_type: Any, target_id: Any) -> str:
    target_type_text = str(target_type or "")
    target_id_text = str(target_id or "")
    if target_type_text == "team":
        return TEAM_LABELS.get(target_id_text, target_id_text or "车队")
    if target_type_text == "event":
        return "本场比赛"
    if target_type_text == "market":
        return "市场价格"
    if target_type_text == "driver":
        return target_id_text or "车手"
    return target_id_text or "未知对象"


def source_label_zh(*, feature_id: str = "", source: str = "", explanation: str = "") -> str:
    raw = f"{feature_id} {source} {explanation}".lower()
    if "fastf1-qualifying-result" in raw or "fastf1_qualifying_result" in raw or "qualifying classification" in raw:
        return "来源：同场 FastF1 排位结果"
    if "fastf1-session-laps" in raw or "fastf1_session_laps" in raw:
        return "来源：同周末 FastF1 圈速摘要"
    if "team-strength-reestimate" in raw or "team total points per race" in raw:
        return "来源：FastF1 本赛季车队强度重估"
    if "official-standings" in raw or "official driver standings" in raw or "official constructor standings" in raw:
        return "来源：F1 官方积分榜"
    if "season-form" in raw or "average points" in raw:
        return "来源：FastF1 赛季累计状态"
    if "momentum" in raw or "recent-vs-older" in raw or "relative points delta" in raw:
        return "来源：FastF1 近期趋势"
    if "fastf1-form" in raw or "race classifications" in raw:
        return "来源：FastF1 最近几站表现"
    if "openf1" in raw or "analogue rank" in raw or "long-run proxy" in raw or "speed-trap" in raw:
        return "来源：OpenF1 圈速、天气或历史相似场景特征"
    return "来源：结构化特征"


def _localize_prediction_section(prediction: dict[str, Any]) -> None:
    for row in _list(prediction.get("state_update_ledger")):
        _localize_update_row(row)
    belief = prediction.get("belief_state") if isinstance(prediction.get("belief_state"), dict) else {}
    for row in _list(belief.get("extracted_units")):
        source_text = row.get("original_snippet") or row.get("paraphrase_zh")
        row["paraphrase_zh"] = localized_mechanism_zh(source_text)
    for row in _list(belief.get("normalized_claims")):
        row["mechanism"] = localized_mechanism_zh(
            row.get("mechanism"),
            feature_id=str(row.get("claim_id") or ""),
            metric=str(row.get("factor") or ""),
        )
        row["factor_label_zh"] = metric_label_zh(row.get("factor"))
        row["direction_label_zh"] = direction_label_zh(row.get("direction"))
    for row in _list(prediction.get("evidence")):
        claim_id = str(row.get("claim_id") or "")
        metric = str(row.get("metric") or "")
        source = str(row.get("source") or "")
        row["evidence_text_zh"] = localized_mechanism_zh(
            row.get("evidence_text"),
            feature_id=claim_id,
            source=source,
            metric=metric,
        )
        row["reasoning_zh"] = localized_mechanism_zh(
            row.get("reasoning") or row.get("evidence_text"),
            feature_id=claim_id,
            source=source,
            metric=metric,
        )
    for row in _list(prediction.get("feature_adjustments")):
        row["explanation_zh"] = localized_mechanism_zh(
            row.get("explanation"),
            feature_id=str(row.get("feature_id") or ""),
            source=str(row.get("source") or ""),
            metric=str(row.get("metric") or ""),
        )
    for row in _list(prediction.get("prediction_impact_trace")):
        _localize_trace_row(row)


def _localize_trace_row(row: dict[str, Any]) -> None:
    if "interpretation_zh" in row:
        row["interpretation_zh"] = localize_public_text_zh(row.get("interpretation_zh"))
    for factor in _list(row.get("changed_factors")):
        if isinstance(factor, dict):
            factor["factor_label_zh"] = metric_label_zh(factor.get("factor"))
            factor["direction_label_zh"] = direction_label_zh(factor.get("direction"))
    for chain_key in ("source_to_prediction_chain", "additional_source_to_prediction_chains"):
        value = row.get(chain_key)
        if chain_key == "additional_source_to_prediction_chains":
            for chain in _list(value):
                _localize_chain(chain)
        else:
            _localize_chain(value)


def _localize_chain(chain: Any) -> None:
    for stage in _list(chain):
        if isinstance(stage, dict) and "text_zh" in stage:
            stage["text_zh"] = localize_public_text_zh(stage.get("text_zh"))


def _localize_update_row(row: dict[str, Any]) -> None:
    row["mechanism"] = localized_mechanism_zh(
        row.get("mechanism"),
        feature_id=str(row.get("claim_id") or row.get("update_id") or ""),
        metric=str(row.get("factor") or ""),
    )
    row["factor_label_zh"] = metric_label_zh(row.get("factor"))
    row["direction_label_zh"] = direction_label_zh(row.get("direction"))
    row["magnitude_bucket_label_zh"] = bucket_label_zh(row.get("magnitude_bucket"))
    row["update_permission_label_zh"] = permission_label_zh(row.get("update_permission"))
    row["affected_model_surface_labels_zh"] = [
        surface_label_zh(item) for item in _list(row.get("affected_model_surfaces"))
    ]


def _parsed_feature_explanation(
    text: str,
    *,
    feature_id: str,
    source: str,
    metric: str,
    event_name: str,
) -> str:
    source_label = source_label_zh(feature_id=feature_id, source=source, explanation=text)
    event = _event_from_text(text) or event_name
    event_phrase = f"{event}前" if event else "知识截止前"
    confidence = _extract_confidence(text)
    confidence_phrase = f"；特征置信度 {confidence}" if confidence else ""
    value = _value_after_colon(text)
    if "qualifying classification" in text:
        return f"{source_label}；{event_phrase}的同场排位名次为 {_clean_value(value)}，作为排位和发车位信号，不直接当作正赛速度{confidence_phrase}。"
    if "Historical analogue race had meaningful rainfall" in text:
        return f"{source_label}；历史相似正赛出现明显降雨，因此车手湿地能力先验获得小幅、按置信度折算的正向修正。"
    if "Open-Meteo forecast snapshot" in text:
        date_match = re.search(r"on (\d{4}-\d{2}-\d{2})", text)
        probability_match = re.search(r"precipitation_probability_max=([^ ]+)", text)
        precipitation_match = re.search(r"precipitation_sum=([^ .]+(?:\.\d+)?mm)", text)
        date = date_match.group(1) if date_match else "比赛日"
        probability = probability_match.group(1) if probability_match else "未记录"
        precipitation = precipitation_match.group(1) if precipitation_match else "未记录"
        return (
            "来源：Open-Meteo 天气预报快照；"
            f"Silverstone 坐标在 {date} 的日最高降水概率为 {probability}，"
            f"预报降水量为 {precipitation}，用于湿地/降雨风险判断。"
        )
    if "qualifying team average position" in text:
        return f"{source_label}；{event_phrase}的车队平均排位名次为 {_clean_value(value)}，作为车队排位状态输入{confidence_phrase}。"
    if "team total points per race" in text:
        value = _after_phrase(text, "team total points per race")
        return f"{source_label}；{event_phrase}的车队每站积分对比为 {_clean_value(value)}，作为赛车/车队强度重估{confidence_phrase}。"
    if "Official constructor standings" in text:
        return f"{source_label}；{event_phrase}官方车队积分榜记录为 {_clean_value(value)}，作为车队状态先验{confidence_phrase}。"
    if "Official driver standings" in text:
        return f"{source_label}；{event_phrase}官方车手积分榜记录为 {_clean_value(value)}，作为车手状态先验{confidence_phrase}。"
    if "team long-run proxy" in text:
        return (
            f"{source_label}；{event_phrase}车队长距离速度代理值为 {_clean_value(value)}，"
            f"作为同一比赛周末的正赛速度信号{confidence_phrase}"
            f"{_practice_conflict_note(text)}。"
        )
    if "long-run proxy" in text:
        return (
            f"{source_label}；{event_phrase}长距离速度代理值为 {_clean_value(value)}，"
            f"作为同一比赛周末的正赛速度信号{confidence_phrase}"
            f"{_practice_conflict_note(text)}。"
        )
    if "tyre-degradation proxy" in text:
        return f"{source_label}；{event_phrase}轮胎衰退代理值为 {_clean_value(value)}，用于影响策略和长距离速度{confidence_phrase}。"
    if "setup window" in text or "setup-window state" in text:
        return (
            f"{source_label}；{event_phrase}调校窗口代理值为 {_clean_value(value)}，"
            f"用于更新车队调校窗口质量，并影响正赛速度、排位采样和比赛日窗口风险{confidence_phrase}"
            f"{_practice_conflict_note(text)}。"
        )
    if "speed-trap average" in text:
        return f"{source_label}；{event_phrase}测速点均速对比为 {_clean_value(value)}，作为直道速度信号{confidence_phrase}。"
    if "best valid lap" in text:
        return f"{source_label}；{event_phrase}最快有效圈对比为 {_clean_value(value)}，作为排位速度信号{confidence_phrase}。"
    if "non-finished classification" in text:
        value = text.split(";", 1)[0]
        return f"{source_label}；近期未完赛记录为 {_clean_value(value)}，作为小幅可靠性风险输入{confidence_phrase}。"
    if "relative points delta" in text:
        value = _after_phrase(text, "relative points delta")
        return f"{source_label}；近期与更早窗口的相对积分变化为 {_clean_value(value)}，作为近期状态信号{confidence_phrase}。"
    if "average points" in text:
        value = _after_phrase(text, "average points")
        return f"{source_label}；近期或赛季窗口的平均积分对比为 {_clean_value(value)}，作为正赛状态输入{confidence_phrase}。"
    if "analogue rank" in text:
        value = _after_phrase(text, "analogue rank")
        return f"{source_label}；历史相似场景排名为 {_clean_value(value)}，作为低置信度参考{confidence_phrase}。"
    if "grid-to-finish conversion" in text or "grid conversion" in text:
        return f"{source_label}；发车位到完赛名次转换表现为 {_clean_value(value)}，作为正赛执行输入{confidence_phrase}。"
    if "race classifications" in text:
        return (
            f"{source_label}；{event_phrase}全场正赛排名被汇总为 {_clean_value(value)}，"
            f"用于近期完赛位置重估，并补充只看积分时看不见的第 11 到第 22 名信息{confidence_phrase}。"
        )
    if "recent" in text.lower() or "window" in text.lower():
        return f"{source_label}；近期窗口表现被压缩成有界输入，用于移动当前状态先验{confidence_phrase}。"
    return ""


def _replace_known_entities(text: str) -> str:
    output = text
    for old, new in {**EVENT_LABELS, **TEAM_LABELS}.items():
        output = output.replace(old, new)
    return output


def _replace_claim_prefix(text: str) -> str:
    return re.sub(r"\bclaim ([A-Za-z0-9_.:-]+) 被解析为", r"信息声明 \1 被解析为", text)


def _replace_token(text: str, old: str, new: str) -> str:
    return re.sub(rf"(?<![A-Za-z0-9_]){re.escape(old)}(?![A-Za-z0-9_])", new, text)


def _normalize_spacing(text: str) -> str:
    text = text.replace(" ,", "，").replace(", ", "，").replace(";", "；")
    text = re.sub(r"\s+", " ", text)
    text = text.replace(" 。", "。").replace(" ，", "，").replace(" ；", "；")
    return text.strip()


def _looks_publicly_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text)) and not any(
        token in text
        for token in (
            "Cutoff-valid",
            "Same-event",
            "Official driver standings",
            "Official constructor standings",
            "vs field",
            "confidence",
            "race(s)",
            "model_surface",
        )
    )


def _compact_english_phrase(text: str) -> str:
    text = _replace_known_entities(text)
    text = _normalize_spacing(text)
    return text[:220]


def _event_from_text(text: str) -> str:
    for raw, label in EVENT_LABELS.items():
        if raw in text or label in text:
            return label
    match = re.search(r"before ([A-Z][A-Za-z ]+ Grand Prix)", text)
    if match:
        return EVENT_LABELS.get(match.group(1), match.group(1))
    return ""


def _extract_confidence(text: str) -> str:
    match = re.search(r"confidence ([+-]?\d+(?:\.\d+)?)", text)
    return match.group(1) if match else ""


def _value_after_colon(text: str) -> str:
    if ":" not in text:
        return text.split(";", 1)[0]
    return text.split(":", 1)[1].split(";", 1)[0]


def _after_phrase(text: str, phrase: str) -> str:
    if phrase not in text:
        return _value_after_colon(text)
    return text.split(phrase, 1)[1].split(";", 1)[0]


def _clean_value(value: Any) -> str:
    output = str(value or "未解析").strip(" :;")
    output = localize_public_text_zh(output)
    return output or "未解析"


def _practice_conflict_note(text: str) -> str:
    if "Confidence was down-weighted" not in text:
        return ""
    return "；但该练习赛长距离信号与同一比赛周末排位位置明显冲突，因此降低置信度，避免把油量、轮胎配方或跑法差异直接当作正赛速度"


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
