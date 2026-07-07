# 2026-07-07 练习赛长距离冲突门控模型/映射修订证明

## 结论

本次候选预测包的变化不是因为用户要求某个车手或车队变强/变弱，也不是新增了新的原始来源身份。它是一次同一批 FastF1 结构化来源的质量映射修订：当练习赛长距离代理值与同一比赛周末排位名次强烈冲突时，系统不删除该来源，而是降低这条练习赛长距离信号的置信度，并在中文解释链中公开说明原因。

这次修订仍然只能注册为 `diagnostic_only`，不能被解释成正式盈利 edge，也不能证明 British GP 模型已经修好。

## 为什么需要这次修订

当前 FastF1 practice long-run proxy 来自练习赛圈速摘要，但本地摘要没有完整归一化燃油量、轮胎配方、跑法、交通和练习计划。它能作为同周末正赛速度线索，但不能在与同周末排位强烈冲突时仍以原强度进入 `race_pace`。

本次规则使用的来源仍然只有结构化数据：

```text
FastF1 practice long-run proxy
FastF1 same-event qualifying classification
```

规则只读取：

```text
target_type
target_id
practice long-run feature value
same-event qualifying position
team average qualifying position
driver_count
```

它不读取任何具体车队名或车手名，也没有 `if Ferrari`、`if Leclerc`、`if Mercedes` 这类实体分支。

## 实现方式

新增通用门控：

```text
练习赛长距离代理为明显负向
且同一比赛周末排位处于前排/前半区
-> 降低该 practice long-run race_pace/setup_quality 特征置信度
-> 保留来源、保留状态更新、保留解释链
```

对称地，若练习赛长距离代理明显正向但排位处于后排，也会降低置信度。这样规则不是为了照顾某个前排车手，而是在处理“弱归一化练习赛长距离代理与强同周末排位来源冲突”的通用问题。

## 注册门槛审计

候选包第一次不带证明注册时被正确阻止：

```text
status = model_only_prediction_change_blocked
allow_registration = false
blocker_codes = non_source_driven_prediction_change, state_mapping_revision_proof_required
source_identity_changed = false
belief_state_update_changed = true
race_probability_changed = true
```

这说明注册门槛没有把同一来源的映射修订伪装成“新来源驱动变化”。

## 候选包

```text
path = reports/prediction_packets_practice_conflict_gate_probe/british_gp/british_gp_20260705T000000_0000.prediction_packet.json
packet_payload_sha256 = d225707bdba831e520aff765d5c9535b882d8dbd10edff0386e84a424ec309c1
generated_at = 2026-07-07T12:25:18+00:00
iterations = 1200
status = diagnostic_only
state_update_count = 565
old_belief_state_id = british_gp_ca70e1cb3b_0ec7749e17
new_belief_state_id = british_gp_ca70e1cb3b_5c1d96c830
```

## 被门控的来源化状态更新

本次 British GP 候选包中，门控命中三条同周末 FastF1 Practice 1 相关更新：

```text
driver leclerc race_pace
原更新方向：练习赛长距离代理为明显负向
门控原因：同周末排位 P2，与该负向长距离代理冲突
状态更新 delta: -0.01615

team ferrari race_pace
原更新方向：车队练习赛长距离代理为负向
门控原因：同周末车队平均排位处于前部，与该负向长距离代理冲突
状态更新 delta: -0.009991

team ferrari setup_quality
原更新方向：车队练习赛长距离/调校窗口代理为负向
门控原因：同周末车队平均排位处于前部，与该负向长距离代理冲突
状态更新 delta: -0.001852
```

这些实体出现在证明中，是因为数据命中了通用规则；它们没有出现在模型代码的实体分支中。

## 预测变化

相对上一版 latest run：

```text
Russell   win 48.50% -> 47.75%, podium 90.75% -> 90.33%, average_finish 2.609 -> 2.637
Antonelli win 44.08% -> 43.75%, podium 90.50% -> 89.92%, average_finish 2.764 -> 2.795
Hamilton  win  4.58% ->  5.33%, podium 55.00% -> 56.67%, average_finish 4.371 -> 4.272
Leclerc   win  1.08% ->  1.58%, podium 23.75% -> 28.42%, average_finish 5.753 -> 5.516
```

变化方向符合门控机制：被单一练习赛长距离负向信号压低的前排 Ferrari/Leclerc 相关状态被缓和，因此 Ferrari 两位车手的预测尾部有所回升。

## 仍未解决的问题

本次修订只解决“弱归一化练习赛长距离信号与同场排位强烈冲突时不应过度入模”的问题。它没有解决全部 British GP 预测质量问题：

```text
Mercedes 双车胜率仍然过度集中
Leclerc 胜率仍然偏低
Antonelli 风险尾部仍然不足
默认模拟器仍需要历史 replay/calibration 支持后才能调整 race_score_lap_time_scale 或 winner calibration
```

因此，本次修订允许作为 source-mapping diagnostic latest 注册，但不能标记 goal 完成。

## 验证

已通过：

```text
.venv\Scripts\python.exe scripts\practice_long_run_conflict_gate_smoke_test.py
.venv\Scripts\python.exe scripts\explainability_smoke_test.py
.venv\Scripts\python.exe scripts\source_driven_contract_test.py
.venv\Scripts\python.exe scripts\fastf1_team_setup_quality_smoke_test.py
```
