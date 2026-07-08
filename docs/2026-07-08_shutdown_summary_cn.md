# 2026-07-08 关机前收尾总结报告

> 这份报告用于今晚暂停前交接。当前系统仍是 `diagnostic_only`；这表示它是诊断级 MVP，而不是在声明已经具备长期可决策优势。新增候选也没有注册成前端 latest。

## 1. 先说结论

今天收尾前，我完成了一个小范围但可验证的建模补丁：把“近期车队未完赛率”做成默认关闭的来源化可靠性候选，让它能从 FastF1 原始分类结果进入：

```text
FastF1 近几站正赛分类
-> 车队未完赛率 vs 全场未完赛率
-> BeliefState.car.reliability
-> dnf_sampler
-> 预测概率变化
```

它不是根据你的例子手调车队/车手。它对所有车队用同一公式处理，只在显式 `--enable-recent-team-reliability-form` 时启用。

结果是：它确实影响了 British GP 概率，但还不能上线。

## 2. 本轮最后做完的工作

### 2.1 新增近期车队可靠性候选

代码位置：

```text
src/f1predict/features/provider.py
src/f1predict/cli.py
src/f1predict/explanation_localization.py
```

新增开关：

```text
--enable-recent-team-reliability-form
```

默认 `ProcessedFeatureProvider()` 不启用，所以当前前端 latest 不会被污染。

### 2.2 新增中文解释

解释不再只给分数，而是写清楚：

```text
近期车队未完赛率为 0.667 (4/6) 对比全场均值 0.273，
与全场未完赛率对比后作为赛车可靠性输入，并影响退赛采样。
```

### 2.3 新增验证脚本和诊断脚本

```text
scripts/fastf1_recent_team_reliability_smoke_test.py
scripts/recent_team_reliability_replay_diagnostic.py
```

smoke test 验证：

- 默认不生成该候选；
- 显式开关才生成；
- 目标是 `team/car reliability`，不是车手速度；
- BeliefState ledger 中路由到 `dnf_sampler`；
- 中文解释包含“车队未完赛率”和“退赛采样”。

## 3. 生成的结果

British GP 诊断候选包：

```text
reports/prediction_packets_recent_team_reliability_probe/british_gp/british_gp_20260705T000000_0000.prediction_packet.json
packet_payload_sha256 = 43c5871b5fe9589cdfe01f0a80b82ae70b3370b3d81d0f766c873cd3e382083c
feature_count = 582
recent_team_reliability_feature_count = 11
recent_team_reliability_ledger_count = 11
status = diagnostic_only
```

关键输入示例：

```text
Aston Martin 4/6 未完赛 -> reliability -0.0250
Cadillac      4/6 未完赛 -> reliability -0.0250
Ferrari       2/6 未完赛 -> reliability -0.0055
Racing Bulls  0/6 未完赛 -> reliability +0.0120
Mercedes      1/6 未完赛 -> reliability +0.0095
```

相对当前 registered latest 的 British GP 概率变化：

```text
当前 latest:
Russell 47.75%, Antonelli 43.75%, Hamilton 5.33%, Leclerc 1.58%

可靠性候选:
Antonelli 39.08%, Russell 38.75%, Hamilton 9.17%, Leclerc 4.25%
```

这说明它不是“只改文档/解释”：概率确实动了。但它仍没有解决核心问题，top 还是 Mercedes 双车，Leclerc 仍低于 Hamilton。

## 4. Replay 诊断结果

诊断产物：

```text
reports/recent_team_reliability_replay_diagnostic/2026_asof_20260707T000000_0000.recent_team_reliability_replay_diagnostic.md
```

120 次低迭代、小样本 replay：

```text
top_pick_hit_rate: 0.6667 -> 0.7778
mean_actual_winner_probability: 0.3472 -> 0.3417
mean_winner_brier_score: 0.6489 -> 0.6574
mean_actual_log_loss: 1.4010 -> 1.3165
weighted_top_pick_calibration_gap: 0.2148 -> 0.3444
British GP Leclerc probability: 0.0167 -> 0.0417
```

读法：

- 正向：top-pick 命中和 log loss 有改善，British GP 实际冠军概率提高；
- 负向：Brier、实际冠军平均概率、top-pick 校准 gap 变差；
- 结论：只能作为下一轮 calibration 候选，不能注册为 latest。

## 5. 当前前端状态

我最后用应用内浏览器和 API 做了只读检查：

```text
URL = http://127.0.0.1:8765/
title = F1Predict MVP
console error/warn = 0
```

页面当前显示的仍是 registered latest：

```text
run_id = british_gp_20260705T000000_0000_20260707T122518_0000_d225707bdb
packet_sha = d225707bdba831e520aff765d5c9535b882d8dbd10edff0386e84a424ec309c1
generated_at = 2026-07-07T12:25:18+00:00
status = diagnostic_only
iterations = 1200
state_update_count = 565
```

前端首屏 British GP 排名：

```text
P1 Russell   47.8%
P2 Antonelli 43.8%
P3 Hamilton   5.3%
P4 Leclerc    1.6%
P5 Piastri    0.6%
P6 Norris     0.3%
P7 Verstappen 0.6%
```

影响追踪 sidecar 状态：

```text
formal_trace_ready = true
covered_claim_count = 565
uncovered_claim_count = 0
trace_count = 576
source_iterations = 1200
trace_iterations = 1200
```

也就是说，前端可用、控制台干净、回放/赛道区域在页面上展示，解释链覆盖是完整的；但前端没有展示今天新增的可靠性候选，因为它没有通过上线门槛。

## 6. 当前整体成果

到现在为止，项目已经具备：

- prediction packet / registered run / latest API；
- 完整 sidecar 影响追踪；
- 中文解释链；
- 赛后复盘；
- 前端官方赛道图和 replay overlay；
- 来源化 BeliefState；
- 来源组/单条来源同种子影响追踪；
- 多个默认关闭的模型候选：红旗尾部、近期全场完赛、近期车队可靠性；
- 对“用户反馈不能直接改数值”的注册门禁和文档约束。

但预测质量仍明显不足：

- British GP 仍偏向 Mercedes 双车；
- Leclerc/Ferrari 仍被压低；
- 随机事件尾部、同周末长距离、轮胎/调校/策略窗口仍不足；
- 现在可以说“解释链和审计能力已基本成型”，但还不能说“预测模型的概率质量已经被充分校准”。这不是当前 MVP 的失败条件，而是下一阶段模型质量优化的方向。

## 7. 今晚停下点

可以在这里暂停：

- 新增可靠性候选已实现、验证、生成诊断；
- 相关中文架构/审计文档已更新；
- 前端 latest 状态已核对；
- 候选没有注册到 latest，避免未校准内容污染前端；
- 接下来应做正式 replay/calibration 和前端候选对比页，而不是继续手动局部修预测。
