# 2026-07-07 收尾总结

这份记录用于关机前交代当前项目状态：今天的主要工作不是“按用户反馈手动改排名”，而是把系统边界和可追溯解释补上，防止以后把用户举例当成预测证据。

## 1. 今天实际完成了什么

### 1.1 明确阻断“用户反馈作为预测证据”

已在代码层加入约束：

- `user://`
- `user-feedback://`
- `codex-feedback://`
- `prompt://`

这些来源会被识别为用户反馈类来源，只能触发审计和补来源任务，不能作为模型输入，也不能更新 BeliefState。

契约测试已覆盖一个反例：即使用户反馈 claim 写得很强、置信度很高、幅度很大，`model_input_weight` 也必须是 `0`，状态更新权限必须被阻断。

结论：你的例子现在只能被系统理解为“去检查数据/架构/映射/模拟是否错了”，不能被当成“把某个车手或车队数值调到你说的位置”。

### 1.2 修正 PredictionRunRegistry 的注册门禁语义

今天发现一个门禁问题：`expected_rank` 是展示字段，不是新的预测证据，也不是模型概率本身。之前如果历史 packet 新增或重排了 `expected_rank`，注册门禁可能把它误判为“正赛预测变化”。

现在已经修正：

- 正赛预测变化只比较核心字段：`win`、`podium`、`points`、`expected_points`、`average_finish`。
- `expected_rank`、数组展示顺序等派生字段不会被算作预测改变。
- 市场边际和概率摘要也做了稳定化排序与数值归一化，减少展示噪声导致的假变化。

这项修改不提升预测准确率；它提升的是审计可信度：以后不能把展示字段变化包装成“预测变好了”。

### 1.3 注册了新的 British GP 预测 run，但它不是预测质量提升

新的 run：

```text
run_id = british_gp_20260705T000000_0000_20260706T163330_0000_2707c1bcaa
packet_hash = 2707c1bcaaea761f6a840091528e8593fe63621cbd1aec7d9bca32ccf4f3a59f
generated_at = 2026-07-06T16:33:30+00:00
status = diagnostic_only
registration_gate.status = no_race_prediction_change
```

重点：这次注册明确显示 `race_probability_changed = false`。也就是说，本次没有宣称模型预测结果变好了，也没有因为用户反馈改变正赛概率或排名。

它的意义是让 latest packet 与当前展示语义、run registry 语义对齐。

### 1.4 生成并合并了完整 PredictionImpactTrace sidecar

为新的 run 补齐了全量同种子 leave-one-information 影响追踪：

```text
sidecar_id = british_gp_5ef69795281c_20260706T165353_0000_merged_5c22f9dd78
status = formal_trace_ready
source_iterations = 1200
trace_iterations = 1200
covered_claim_count = 456
uncovered_claim_count = 0
trace_count = 467
```

这说明 456 条来源化状态更新都已经有正式同口径影响追踪。每条信息现在可以被追溯为：

```text
原始来源 -> 信息分析 -> 状态更新 -> 模拟路由 -> 预测变化
```

这仍然不等于预测已经准确，只表示解释链条现在可审计。

## 2. 当前前端/API 状态

本地服务已重新启动：

```text
http://127.0.0.1:8765/
```

API 检查结果：

```text
GET /api/v2/prediction-packets/latest?event_id=british_gp
cache_context.run_id = british_gp_20260705T000000_0000_20260706T163330_0000_2707c1bcaa
cache_context.prediction_anomaly_audit_sidecar_id = british_gp_5ef69795281c_20260706T165353_0000_merged_5c22f9dd78
cache_context.prediction_anomaly_audit_sidecar_comparison_status = matched_source_run_iterations
```

```text
GET /api/v2/prediction-impact-traces/latest?event_id=british_gp&limit=3
formal_ready = true
status = formal_trace_ready
covered = 456
uncovered = 0
```

2026-07-07 13:45 追加状态：我又注册了一个新的 British GP 诊断 run，用来承接 BeliefState 特征映射修复。

```text
run_id = british_gp_20260705T000000_0000_20260707T054040_0000_a96fffb1fc
packet_hash = a96fffb1fcd042b5bcc1a00a4d49c5008b5b88e6c0dd07d8775c8a58e76b928e
generated_at = 2026-07-07T05:40:40+00:00
status = diagnostic_only
state_update_count = 535
formal_edge_ready = false
```

本地服务已重新启动：

```text
http://127.0.0.1:8765/
```

API 检查结果：

```text
GET /api/v2/prediction-packets/latest?event_id=british_gp
status = diagnostic_only
state_update_count = 535
top8 = russell, antonelli, hamilton, leclerc, norris, piastri, hadjar, verstappen
```

新 run 的 impact trace sidecar 目前只补了局部同迭代解释，不是全量 formal sidecar：

```text
sidecar_id = british_gp_british_gp_20260705T000000_0000_2026_70e01a6d5581_20260707T054338_0000_fac9fb6641
formal_readiness.status = formal_iterations_incomplete_coverage
same_iterations = true
covered_claim_count = 10
uncovered_claim_count = 525
```

也就是说，前端现在应该能读取 latest packet 和局部 impact trace，不应再直接报 sidecar 缺失；但它不能被称为“完整影响追踪已生成”。

## 3. 展示效果与局限

当前展示效果比之前更清楚：

- 可以展示全场预计排名，而不是把冠军概率顺序误当成预计完赛顺序。
- 可以读取新 run 的局部 impact trace sidecar，不再是 sidecar 文件缺失。
- 异常审计现在会明确暴露 sidecar 覆盖不足；这不是前端展示成功，而是一个还需要补完的状态。
- 用户反馈不会被混入证据链。

但当前预测效果仍然只能称为诊断态：

- packet 状态仍是 `diagnostic_only`。
- 新 latest 的 sidecar 只覆盖 10/535 条状态更新，完整解释链还没有补完。
- 概率校准和真实 edge 还没有通过历史回放证明。
- 当前排名是否足够符合 F1 常识，还不能用今天这次工作宣称已经解决。
- 今天新增的大部分工作解决的是“可信解释和注册边界”，不是“模型性能提升”。

## 4. 已执行验证

通过的验证：

```text
python scripts/source_driven_contract_test.py
python scripts/prediction_anomaly_audit_smoke_test.py
python scripts/explainability_smoke_test.py
python scripts/impact_trace_sidecar_smoke_test.py
node --check web/app.js
git diff --check
```

`prediction_anomaly_audit_smoke_test.py` 已更新为覆盖两种状态：如果 latest sidecar 是全量覆盖，则要求无覆盖缺口；如果 latest sidecar 只是局部覆盖，则必须显式出现 `impact_trace_incomplete_for_material_updates` 异常。当前新 latest 属于后者，测试通过不代表全量 sidecar 已完成，只代表系统没有掩盖这个风险。

`git diff --check` 只有 Windows 换行提示，没有 whitespace error。

## 5. 下一步建议

下一次继续时，优先不要再做展示字段修补，而是进入真正影响预测质量的部分：

1. 把最近 3-5 站 FP、排位、正赛、长距离、退赛、升级信息变成强来源化状态更新。
2. 检查这些状态更新在 sidecar 中是否真的改变合理的车队/车手分布。
3. 对“信息进入了状态但预测几乎不变”的因素，修模拟路由和权重映射。
4. 做历史回放和概率校准，证明预测不是只看起来合理。
5. 再根据回放结果调整模型，而不是根据用户的一句话调整数值。

当前可以暂停。暂停前的项目状态是：解释链条和门禁边界向前推进了一步，预测本身仍需要下一阶段用真实来源和回放验证继续改。
