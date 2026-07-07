# 2026-07-07 关机前总结报告

## 1. 先说结论

今晚收尾前，系统已经完成了一个关键闭环：最新 British GP 诊断预测、注册 run、赛后复盘、完整影响追踪 sidecar、API 和前端读取状态已经重新对齐。

当前 latest run 是：

```text
run_id = british_gp_20260705T000000_0000_20260707T122518_0000_d225707bdb
packet_sha = d225707bdba831e520aff765d5c9535b882d8dbd10edff0386e84a424ec309c1
state_update_count = 565
status = diagnostic_only
```

完整解释 sidecar 是：

```text
sidecar_id = british_gp_7db773a15fb8_20260707T131516_0000_merged_239e821a3d
source_iterations = 1200
trace_iterations = 1200
covered_claim_count = 565
uncovered_claim_count = 0
trace_count = 576
formal_readiness.status = formal_trace_ready
```

但预测质量仍没有达到你的目标。它仍是诊断模型，不是正式 edge，也不能用于真实交易。

## 2. 今天主要做了什么

### 2.1 明确了不能按你的例子手调

你强调“我的举例是指出问题，不是让你偷偷把数值调到我说的结果”。今天的实现继续遵守这个边界：

- 没有写死 Leclerc、Ferrari、Aston Martin、Mercedes 或任何具体车手/车队；
- 预测变化必须来自来源映射、状态更新、模型修订证明或同种子 replay；
- 用户反馈只能触发审计和架构修正，不能直接作为预测证据。

### 2.2 定位到一个真实来源映射问题

British GP 中 Leclerc/Ferrari 被压得过低，其中一个原因是：

```text
FastF1 practice1 long-run proxy
-> 被当作同周末正赛速度信号
-> 但 fuel load、轮胎配方、run plan、traffic 没有完全归一化
-> 当它和同周末排位强烈冲突时，原始置信度过高
```

这类信号不是不能用，而是不能在冲突时用同样强度进入模型。

### 2.3 实现了通用的练习赛长距离冲突门禁

新增逻辑在 [src/f1predict/features/provider.py](E:/1.study/code/AI_Projects/F1Predict/src/f1predict/features/provider.py)：

```text
练习赛长距离观测
+ 同周末排位位置
+ 观测方向和幅度
-> 判断是否冲突
-> 冲突时降低 confidence
-> 保留来源和 ledger
```

这不是结果手调，而是来源质量门禁。它适用于所有车手和车队，不包含实体特判。

### 2.4 修正了中文解释

新增/修正了 [src/f1predict/explanation_localization.py](E:/1.study/code/AI_Projects/F1Predict/src/f1predict/explanation_localization.py)：

- FastF1 session lap 不再误标成 OpenF1；
- 练习赛长距离被降权时，中文解释会说明原因；
- 解释中会说“该练习赛长距离信号与同一比赛周末排位位置明显冲突，因此降低置信度”，而不是给出裸分数。

### 2.5 注册门禁正常工作

无证明注册被阻断：

```text
status = model_only_prediction_change_blocked
blocker_codes = non_source_driven_prediction_change, state_mapping_revision_proof_required
source_identity_changed = false
belief_state_update_changed = true
race_probability_changed = true
```

补充证明后才允许注册为 diagnostic latest：

```text
model_revision_proof = reports/model_revision_proofs/2026-07-07_practice_long_run_conflict_gate_cn.md
registration_gate.status = model_revision_proof_allowed
```

这说明 registry 没有把“同来源身份下的模型/映射变化”静默伪装成来源驱动变化。

### 2.6 补齐 full sidecar

新 run 注册后，前端一开始只能看到 prediction packet 内嵌的 10/565 trace。为了让解释链重新完整，我把 565 条来源影响追踪分成 6 个 chunk 生成，再合并成正式 sidecar。

合并后 API 验证：

```text
GET /api/v2/prediction-impact-traces/latest?event_id=british_gp&limit=1
-> formal_trace_ready
-> covered = 565 / 565
-> trace_count = 576
```

这一步的意义是：前端现在能展示“从来源到预测变化”的完整链条，而不是只显示少量内嵌样本。

## 3. 当前预测结果

最新 British GP 诊断预测前四：

```text
Russell   win 47.75%, podium 90.33%, average finish 2.637
Antonelli win 43.75%, podium 89.92%, average finish 2.795
Hamilton  win  5.33%, podium 56.67%, average finish 4.272
Leclerc   win  1.58%, podium 28.42%, average finish 5.516
```

相比上一版：

```text
Leclerc win: 1.08% -> 1.58%
Hamilton win: 4.58% -> 5.33%
Russell + Antonelli combined win: 92.58% -> 91.50%
```

方向有一点修正，但幅度很小。核心问题仍然存在：

- Mercedes 双车胜率仍过度集中；
- Antonelli 风险尾部仍太低；
- Leclerc/Ferrari 仍偏低；
- 当前概率分布仍不像一个可交易的正式模型。

## 4. 赛后复盘状态

British GP 赛后复盘已更新到新 run：

```text
prediction_run_id = british_gp_20260705T000000_0000_20260707T122518_0000_d225707bdb
predicted_winner = russell
actual_winner = leclerc
winner_hit = false
actual_winner_predicted_rank = 4
actual_winner_win_probability = 0.015833
podium_overlap_rate = 0.6667
points_overlap_rate = 0.7
mean_abs_rank_error = 4.6364
```

这说明模型能把 Leclerc 放进前四，但冠军尾部概率仍严重偏低。这个复盘只用于诊断，不会把赛后结果写回赛前预测。

## 5. 当前前端状态

当前本地服务仍在：

```text
http://127.0.0.1:8765/
```

API 验证显示：

```text
prediction latest -> d225707bdb
impact trace latest -> 565/565, formal_trace_ready
post-event review -> d225707bdb
```

也就是说，前端现在应该能看到：

- 最新诊断预测；
- 565 条状态更新；
- 565/565 完整解释覆盖；
- `formal_trace_ready`；
- 赛后复盘对应同一个 latest run；
- 预测仍标记为 `diagnostic_only`。

前端仍然不是最终产品形态。它现在的价值主要是审计和解释，不是简洁的交易决策面板。

## 6. 已更新的关键文件

```text
src/f1predict/features/provider.py
src/f1predict/explanation_localization.py
scripts/practice_long_run_conflict_gate_smoke_test.py
reports/model_revision_proofs/2026-07-07_practice_long_run_conflict_gate_cn.md
reports/prediction_packets_practice_conflict_gate_probe/british_gp/british_gp_20260705T000000_0000.prediction_packet.json
reports/prediction_runs/runs/british_gp/british_gp_20260705T000000_0000_20260707T122518_0000_d225707bdb.prediction_run.json
reports/prediction_impact_traces/british_gp/british_gp_20260705T000000_0000_2026_ce8f7c0874b4/british_gp_20260707T131516_0000_239e821a3d.prediction_impact_trace.json
reports/post_event_review/british_gp/british_gp_20260705T000000_0000.post_event_review.json
reports/post_event_review/british_gp/british_gp_20260705T000000_0000.post_event_review.md
docs/current_prediction_failure_audit_cn.md
docs/traceable_prediction_update_architecture_cn.md
```

## 7. 今晚收尾前的真实评价

可解释性方向：明显变好。现在已经能把原始结构化来源、信息分析、状态更新、模型路由和同种子影响 trace 串起来，而且可以防止“用户一句话直接改预测”的问题。

工程同步方向：今晚已经重新对齐。latest packet、registered run、sidecar、post-event review 和 API 都指向同一个 run。

预测质量方向：仍不达标。今天的修正只解决了一个来源质量问题，没有解决整套模型对于赛车实力、随机事件尾部、近期状态递推、正赛不确定性和概率校准的系统问题。

## 8. 下一次继续时优先做什么

1. 做历史 replay/calibration，而不是继续只看 British GP 单站。
2. 重构赛车实力权重，让“车”成为主导因素，并且由近期分站、排位、正赛、升级、练习赛和技术信息共同递推。
3. 增强随机事件尾部：退赛、安全车、红旗、策略窗口、发车风险、车队双车相关风险。
4. 把前端进一步收敛成中文审计面板：预测排名、关键来源变化、状态向量变化、异常审计、赛后复盘。
5. 继续保持门禁：任何改变如果不是新来源导致，就必须有模型修订证明和 replay/calibration 依据。
