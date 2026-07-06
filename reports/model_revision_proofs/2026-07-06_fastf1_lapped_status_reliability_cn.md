# 2026-07-06 FastF1 套圈状态可靠性修订证明

## 结论

这次修订不是新增外部来源，也不是因为用户一句话调整某个车队或车手。它修正的是 FastF1 正赛结果状态字段的通用语义映射：

```text
FastF1/F1 results: Status = Lapped
-> 语义是已分类完赛但被套圈
-> 不应计为 DNF / non-finished
```

旧逻辑只把 `Finished` 和 `+1 Lap` 等字符串视为完赛，没有把 `Lapped` 视为完赛，导致可靠性和 grid-to-finish conversion 特征被系统性污染。

## 旧问题

在 British GP cutoff 前的 2026 赛季 FastF1 结果里，许多正式完赛但被套圈的车手状态是：

```text
Status = Lapped
```

旧逻辑会把这些结果计入 `non-finished classification(s)`，从而产生不合理的可靠性惩罚。例如旧包里 Bortoleto 被解释为：

```text
6 non-finished classification(s) across 8 cutoff-valid FastF1 result(s)
```

这不是合理的事实表达，因为其中大量其实是被套圈完赛，不是退赛。

## 新规则

现在 `ProcessedFeatureProvider._finished_status()` 视以下状态为已完赛/已分类：

```text
Finished
Lapped
Classified
+1 Lap / +2 Laps / ...
```

以下状态仍然不是完赛：

```text
Retired
Did not start
Disqualified
```

## 对预测输入的影响

修订后，同一批 FastF1 结构化来源重新生成特征时，可靠性惩罚明显收敛。例如 British GP 的 Bortoleto：

```text
旧语义：6 non-finished classification(s) across 8 races
新语义：1 non-finished classification(s) across 8 races
```

这会影响：

- driver reliability 状态更新；
- finished-race grid-to-finish conversion；
- 正赛模拟里的 DNF 概率；
- 解释链中“可靠性风险”的事实表述。

## 为什么这是模型/映射修订

本次没有新增 Codex 新闻来源，也没有新增用户标签。变化来自同一批 FastF1 正赛结果字段的语义纠正，因此必须作为“模型/映射修订诊断 run”注册，不能称为新增来源驱动。

## 注册门禁复核

修正 `PredictionRunRegistry` 后，同一批原始来源因为特征行数量或映射语义变化而导致预测改变时，不再被误判为“新来源身份变化”。

对 British GP 新包和上一版 run 的复核结果如下：

```text
base_run = british_gp_20260705T000000_0000_20260706T125327_0000_b732713811
candidate_run = british_gp_20260705T000000_0000_20260706T142235_0000_ab901d489d

不带本证明：
status = model_only_prediction_change_blocked
allow_registration = false
source_identity_changed = false
blocker_codes = non_source_driven_prediction_change, state_mapping_revision_proof_required

带本证明：
status = model_revision_proof_allowed
allow_registration = true
source_identity_changed = false
warning_codes = model_revision_not_source_state_change
```

这意味着：用户指出“不合理”只触发审计；真正允许进入 latest 的原因，是可复核的 FastF1 状态语义修正证明，而不是把用户判断写成数值。

## 验证

新增测试：

```text
scripts/fastf1_status_semantics_smoke_test.py
```

它验证：

- `Lapped`、`+1 Lap`、`Classified` 被视为完赛；
- `Retired`、`Did not start`、`Disqualified` 不被视为完赛；
- British GP cutoff 下 Bortoleto 不再因为最近 3 站的套圈完赛得到 DNF 惩罚；
- Bortoleto 赛季可靠性惩罚变为 `1 non-finished classification(s) across 8 cutoff-valid FastF1 result(s)`。

这仍然不是正式 edge 证明。正式预测能力还需要历史回放、概率校准和市场基线比较。
