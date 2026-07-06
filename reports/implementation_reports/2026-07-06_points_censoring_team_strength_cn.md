# 2026-07-06 积分截断修正实现报告

## 背景

用户指出的车队强弱例子被视为异常报告，而不是训练标签。本次没有按车队或车手名字写死目标排名。

问题根源是：分站积分只奖励前十名，是被规则截断后的观测。仅用积分重估车队强度时，会把接近积分区但经常第 11-15 名完赛的中游队，错误压到和长期后排完赛的队接近。

## 修改

修改位置：

- `src/f1predict/features/provider.py`
- `scripts/smoke_test.py`
- `docs/traceable_prediction_update_architecture_cn.md`
- `docs/current_prediction_failure_audit_cn.md`

核心逻辑：

```text
FastF1 赛季/近期积分信号
-> 如果该信号为负，检查同一批 FastF1 全场完赛分类
-> 如果全场完赛分类显示该队没有积分信号那么差，则缓和负向积分信号
-> 所有车队使用同一公式，不按名称特判
```

## 新 run

```text
run_id = british_gp_20260705T000000_0000_20260706T125327_0000_b732713811
packet_sha256 = b73271381102a3c760effd8ca0afc052d7cb15d471d478fa4d10523de3073c62
status = diagnostic_only
blocker = probability_calibration_diagnostic_only
```

## 同口径 diff

```text
base_run = british_gp_20260705T000000_0000_20260706T115913_0000_31f3f052bf
candidate_run = british_gp_20260705T000000_0000_20260706T125327_0000_b732713811
input_changed = true
evidence_changed = false
probability_changed = true
changed_driver_count = 20
material_driver_change_count = 2
rank_change_count = 2
max_abs_expected_points_delta = 0.0992
```

主要变化很小：Hulkenberg 从第 17 到第 16，Ocon 从第 16 到第 17；Racing Bulls 的期望积分略升，Aston Martin 和 Cadillac 仍保持底部区间。

## 正式解释 sidecar

```text
sidecar_id = british_gp_1a7764238906_20260706T131855_0000_merged_1236c64f1a
source_iterations = 1200
trace_iterations = 1200
covered_claim_count = 453
uncovered_claim_count = 0
formal_ready = true
```

这个 sidecar 证明“解释链条同口径可追踪”，不证明“预测已经有稳定 edge”。预测质量仍需历史回放、概率校准和市场 edge 验证。
