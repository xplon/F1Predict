# 2026-07-07 当前代码来源映射同步证明

## 结论

这次候选 prediction packet 的变化不是因为用户指出某个车队或车手后手动调整数值，而是因为同一批 cutoff 内结构化来源经过新的通用映射规则后，产生了更多可追溯状态更新：

```text
FastF1 practice long-run tyre degradation
-> team/car tyre_deg

FastF1 practice / qualifying team lap-time proxy
-> team_ops.setup_quality
```

注册门禁正确地把首次注册尝试挡住了，因为原始来源身份没有变化，但正赛概率发生了变化：

```text
status = model_only_prediction_change_blocked
allow_registration = false
blocker_codes = non_source_driven_prediction_change, state_mapping_revision_proof_required
source_identity_changed = false
belief_state_update_changed = true
race_probability_changed = true
```

因此本文件的作用是把这次变化明确登记为“同源数据的模型/映射修订”，而不是“新增外部来源导致预测改变”。

## 本次没有做什么

- 没有把用户关于 Mercedes、Ferrari、Red Bull、Aston Martin、Cadillac、Racing Bulls、Audi、Leclerc、Hamilton、Alonso 等判断写成实体级强约束。
- 没有新增 `if team == ...` 或 `if driver == ...` 这类按名称调排名的规则。
- 没有把用户反馈当作 evidence claim、训练标签或 BeliefState 输入。
- 没有启用未通过 replay/calibration 的 `source_weighted_team_window_pressure` 作为默认模型。
- 没有声称预测已经具备稳定盈利 edge。

## 候选包

```text
event_id = british_gp
knowledge_cutoff = 2026-07-05T00:00:00+00:00
iterations = 1200
candidate_packet = reports/prediction_packets_current_code_sync/british_gp/british_gp_20260705T000000_0000.prediction_packet.json
candidate_packet_sha = 48a450406e04513887fdda2bd7abde66463d7e6ea98a95f34e5a943ff30fa191
status = diagnostic_only
```

对照的已注册 latest 包：

```text
base_run_id = british_gp_20260705T000000_0000_20260707T065149_0000_d76ec2c3e4
base_packet_sha = d76ec2c3e444fc48e648dc0208bf31a52b1c5158612b7cf81a386d1989e50478
```

## 状态更新变化

```text
base feature_count = 541
candidate feature_count = 571

base state_update_count = 535
candidate state_update_count = 565
```

新增的 30 条状态更新来自：

```text
team tyre_deg = 10
team setup_quality = 20
```

候选包中的状态更新分布：

```text
driver qualifying_ceiling = 131
driver race_pace = 100
driver race_execution = 80
team race_pace = 75
team qualifying_pace = 31
driver reliability = 30
team race_execution = 27
driver wet_skill = 22
team straight_line_speed = 22
team setup_quality = 20
driver tyre_management = 16
team tyre_deg = 10
event wet_probability = 1
```

## 可解释性改进

新增状态更新不是裸分数。ledger mechanism 会保留原始结构化事实，例如：

```text
英国大奖赛前调校窗口代理值为 93.774s vs 车队 field 94.257s from 1 车手 sample(s)，
用于更新车队调校窗口质量，并影响正赛速度、排位采样和比赛日窗口风险。
```

以及：

```text
英国大奖赛前轮胎衰退代理值为 +1.0697s/lap vs 车队 field -0.2196s/lap from 1 车手 sample(s)，
用于影响策略和长距离速度。
```

这满足用户要求的解释边界：除人名/队名外，解释必须说明“分数从什么事实来”，而不是展示一串不可解释的小数。

## 对预测结果的实际影响

候选包没有显著修复 British GP 的核心问题。前八名仍然是：

```text
1. Russell
2. Antonelli
3. Hamilton
4. Leclerc
5. Piastri
6. Verstappen
7. Norris
8. Hadjar
```

关键变化：

```text
Russell win_delta = +0.0025, average_finish_delta = -0.009
Antonelli win_delta = +0.0008, average_finish_delta = -0.005
Hamilton win_delta = +0.0000, average_finish_delta = +0.004
Leclerc win_delta = -0.0017, average_finish_delta = +0.012
Norris win_delta = -0.0016, average_finish_delta = -0.006
```

因此，这次修订只能被描述为“来源化状态链路补齐并同步到候选包”，不能被描述为“预测已经合理化完成”。Leclerc/Ferrari 的低胜率、Mercedes 双车过度集中和 Antonelli 风险不足仍然是后续模型问题。

## replay/calibration 诊断

最新 `setup_quality_v1` simulator calibration 仍是诊断级：

```text
reports/simulator_calibration_setup_quality_v1/2026_asof_20260707T000000_0000.simulator_calibration.md
status = diagnostic_only
small_sample_less_than_20_scored_events
candidate_selection_is_in_sample_no_holdout
```

该诊断中默认 baseline 仍被推荐：

```text
default_pace_separation_track_position_team_window_v3 score = 2.3549
source_weighted_team_window_pressure_strong score = 2.3820
source_weighted_team_window_pressure score = 2.3992
```

这说明：

- 当前新增来源映射可以进入默认状态链路；
- 但 `source_weighted_team_window_pressure` 候选仍不能注册；
- 当前预测仍是 `diagnostic_only`，不是正式 edge。

## 为什么允许注册为 diagnostic latest

允许注册的理由不是“结果更像用户预期”，而是：

1. 这次变化来自通用来源映射修订，修复的是同源结构化数据未进入目标状态的问题。
2. 所有新增状态更新都有 cutoff 内结构化来源事实和 ledger 记录。
3. 注册后仍保持 `diagnostic_only`，不会声称正式概率校准或盈利 edge。
4. 注册门禁要求的模型/映射修订证明已经由本文件提供。
5. 预测结果变化很小，且文档明确承认它没有解决 British GP 核心预测失败。

## 后续必须做的事

注册后必须重新生成同迭代 impact trace sidecar。旧 sidecar 覆盖的是 535 条状态更新；候选包有 565 条状态更新。如果不生成新的 sidecar，前端显示 `535/535` 会对应旧 run，而不是当前代码同步后的 run。

下一步正确流程：

```text
register current-code diagnostic packet
-> build 565 条状态更新的 same-iteration sidecar
-> merge/verify formal_trace_ready
-> regenerate post-event review
-> frontend/API 确认 latest run、sidecar、post-event review 指向同一个 packet
```

在这条链路完成之前，不能把该候选称为“完整 latest 可解释闭环”。
