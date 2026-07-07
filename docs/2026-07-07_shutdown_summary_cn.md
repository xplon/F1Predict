# 2026-07-07 关机前收尾总结

这份文档用于今晚暂停前交代当前项目状态。核心结论先放前面：今天真正推进最多的是“来源可信边界”和“可追溯解释链”，不是已经证明预测模型有稳定盈利 edge。当前 British GP 最新预测包仍是 `diagnostic_only`，原因是概率校准和历史回放还没有完成正式验证。

## 1. 当前仓库状态

- 仓库：`E:\1.study\code\AI_Projects\F1Predict`
- 分支：`master`
- 远端：`https://github.com/xplon/F1Predict.git`
- 本地状态：`master` 已与 `origin/master` 对齐，收尾前没有未提交改动
- 最新提交：
  - `0d8b3e3 Add full impact trace sidecar coverage`
  - `80da291 Fix belief state feature mapping traces`
  - `bbc11d5 Normalize prediction run fingerprints and trace sidecar`
  - `f4cde99 Block user feedback as prediction evidence`
  - `4daa524 Label direct and indirect impact traces`

## 2. 今天完成了什么

### 2.1 阻断“用户反馈直接变成预测证据”

你反复强调：你的话只能指出系统问题，不能被我偷偷当成预测来源去改数值。今天已把这个边界写进系统：

- `user://`
- `user-feedback://`
- `codex-feedback://`
- `prompt://`

这些来源会被识别为用户反馈类来源，只能触发审计、补数据、改架构，不能作为模型输入，也不能更新 `BeliefState`。对应契约测试已经通过。

这件事的意义是：以后不能因为你说“某队很强/某队很弱”，系统就直接把这个判断写成强约束。系统必须回到外部来源、结构化数据和可追溯信息链里找证据。

### 2.2 修正 PredictionRunRegistry 的注册门禁

之前有一个语义风险：`expected_rank` 是展示字段，不是概率本身。如果只是展示字段重排，系统不应该宣称“预测改变”。今天已修正：

- 正赛预测变化只比较核心预测字段：`win`、`podium`、`points`、`expected_points`、`average_finish`
- `expected_rank` 和数组顺序不再被当成真实预测变化
- 市场边际、概率摘要和 run fingerprint 做了稳定化处理

这不是提升预测准确率的改动，而是防止系统把展示变化包装成模型进步。

### 2.3 修正 BeliefState 到模型特征的映射

今天修了几个会影响预测解释可信度的映射问题：

- `team race_execution` 正确进入 `team_ops.race_execution`
- 车手 `reliability` 正确进入车手状态
- 车手目标里的赛车特征，例如 `straight_line_speed`，会落到该车手所属车队的赛车状态
- ledger 中的 `target_type` 现在反映真实落点，而不是只保留原始声明目标
- `PaceModel` 会读取 `team_ops.race_execution`

这项修复是实质性的，因为它决定“信息进入状态后到底有没有被模型使用”。修复后重新注册了新的 British GP 诊断预测包。

### 2.4 补齐完整 PredictionImpactTrace sidecar

最新 British GP run 的解释链已经补齐到全量覆盖：

```text
run_id = british_gp_20260705T000000_0000_20260707T054040_0000_a96fffb1fc
packet_hash = a96fffb1fcd042b5bcc1a00a4d49c5008b5b88e6c0dd07d8775c8a58e76b928e
status = diagnostic_only
iterations = 1200
knowledge_cutoff = 2026-07-05T00:00:00+00:00
```

对应 sidecar：

```text
sidecar_id = british_gp_f6fd000ef3aa_20260707T060939_0000_merged_f783f87561
formal_readiness.status = formal_trace_ready
source_iterations = 1200
trace_iterations = 1200
covered_claim_count = 535
uncovered_claim_count = 0
```

这说明 535 条来源化状态更新都有同迭代数、同 seed 口径下的边际影响追踪。现在可以追到：

```text
原始来源 -> 信息分析 -> 状态更新 -> 模型特征 -> 模拟结果 -> 预测分布变化
```

注意：这证明解释链补齐了，不证明预测已经准。

## 3. 当前预测结果

最新 British GP 预测包状态：

```text
status = diagnostic_only
formal_edge_ready = false
blocker_codes = probability_calibration_diagnostic_only
warning_codes = codex_claims_require_review, blocked_development_seed_evidence_separated
```

当前 top 8：

| 排名 | 车手 | 平均完赛 | 期望积分 | 冠军概率 | 登台概率 |
|---:|---|---:|---:|---:|---:|
| 1 | Russell | 2.501 | 20.218 | 0.4883 | 0.9267 |
| 2 | Antonelli | 2.678 | 19.840 | 0.4608 | 0.9100 |
| 3 | Hamilton | 4.389 | 12.987 | 0.0283 | 0.5458 |
| 4 | Leclerc | 5.473 | 10.753 | 0.0133 | 0.2692 |
| 5 | Norris | 6.123 | 8.931 | 0.0042 | 0.1250 |
| 6 | Piastri | 6.553 | 8.255 | 0.0025 | 0.0958 |
| 7 | Hadjar | 7.246 | 6.808 | 0.0017 | 0.0358 |
| 8 | Verstappen | 6.624 | 8.224 | 0.0008 | 0.0917 |

我对这个结果的判断：

- 比早期版本更像一个“车队/车手状态进入模型后的结果”，不是随机展示。
- Mercedes 头部优势非常强，Ferrari 在其后，McLaren/Red Bull 处在第二集团附近，这比之前完全不体现车强弱的版本合理。
- 但前两名合计冠军概率接近 95%，这明显偏集中，说明模拟噪声、排位不确定性、策略事件、退赛/安全车等随机性还需要校准。
- 因此当前结果只能作为诊断预测，不应该作为正式有 edge 的预测。

## 4. 当前前端/API 状态

本地服务可访问：

```text
http://127.0.0.1:8765/
```

收尾检查结果：

```text
GET /
StatusCode = 200
Title = F1Predict MVP
ContentLength = 11769
```

关键 API：

```text
GET /api/v2/prediction-packets/latest?event_id=british_gp
cache_context.run_id = british_gp_20260705T000000_0000_20260707T054040_0000_a96fffb1fc
cache_context.prediction_anomaly_audit_source = api_runtime_recomputed
cache_context.prediction_anomaly_audit_sidecar_id = british_gp_f6fd000ef3aa_20260707T060939_0000_merged_f783f87561
```

```text
GET /api/v2/prediction-impact-traces/latest?event_id=british_gp&limit=1
formal_readiness.status = formal_trace_ready
covered_claim_count = 535
uncovered_claim_count = 0
```

异常审计当前只剩 1 个低优先级异常：

```text
code = driver_specific_lift_over_weak_team_support
target = gasly
severity = low
含义 = Gasly 被预测到第 9，但 Alpine 车队整体支持信号偏弱，需要继续复核长距离、轮胎衰退、策略和队友对比。
```

前端展示效果的真实状态：

- 前端页面本身可通过 HTTP 返回。
- 最新预测包和完整 sidecar 可以从 API 读取。
- API 中文内容本身是 UTF-8 正常文本；PowerShell 某些 JSON 输出会显示问号，但 Python 读取确认不是接口数据损坏。
- 今晚没有完成 in-app browser 截图级视觉审计，因为浏览器控制接口没有发现可控制标签页。这个不能谎称已经完成。

## 5. 已执行验证

今晚收尾重新跑过并通过：

```text
.venv\Scripts\python.exe scripts\source_driven_contract_test.py
.venv\Scripts\python.exe scripts\impact_trace_sidecar_smoke_test.py
.venv\Scripts\python.exe scripts\explainability_smoke_test.py
.venv\Scripts\python.exe scripts\prediction_anomaly_audit_smoke_test.py
node --check web\app.js
git diff --check
```

这些验证证明：

- 用户反馈不能直接进入模型证据链。
- latest sidecar 是 535/535 全覆盖。
- 可解释性 smoke 能读通。
- 异常审计能使用 full sidecar。
- 前端 JavaScript 没有语法错误。
- 当前工作区没有 whitespace diff 问题。

## 6. 还没有完成什么

以下内容仍未完成，不能在今晚说已经解决：

- 没有完成正式历史回放。
- 没有证明模型有稳定 edge 或盈利能力。
- 没有完成概率校准，所以 packet 仍是 `diagnostic_only`。
- 没有证明当前 top 2 过高冠军概率是合理的。
- 没有完成全前端视觉审计。
- 预测质量仍需要继续根据真实来源和回放结果改，而不是根据用户一句话改。

## 7. 明天继续时最该做什么

下一步不建议继续堆 UI，也不建议针对单个车手手动修数值。优先顺序应该是：

1. 做 British GP 之前多站历史回放，确认模型在已知 cutoff 下能否复现合理分布。
2. 校准模拟器随机性，重点检查前两名胜率过度集中的问题。
3. 检查最近 3-5 站的 FP、排位、正赛、长距离、退赛、升级信息是否都进入了状态更新。
4. 对“进入状态但几乎不影响预测”的因素，修权重映射和模拟路由。
5. 再生成新的 prediction packet 和 full sidecar，并比较每次改动到底改变了哪些预测。

今晚可以暂停。当前项目状态是：解释链条、证据边界、注册门禁和 full sidecar 已经补齐；预测模型本身仍处于需要校准和历史回放验证的诊断阶段。
