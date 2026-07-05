# 官方积分榜特征接入报告

生成日期：2026-07-05

## 1. 本次改动目的

这次改动解决一个很具体的问题：预测模型不能只依赖手写 seed strength 或零散证据，而应该能从简单、可信、可截止时间审计的信息中自然推断赛季强弱。

本次选择的第一类信息是 Formula 1 官方车手/车队积分榜快照。它不是“把梅奔强、红牛弱写死”，而是把官方 standings 转换成 point-in-time 的结构化 `FeatureAdjustment`，让模型在每站预测时能读取到：

- 车手当前积分和排名；
- 车队当前积分和排名；
- 这些信息在 cutoff 前是否真实可用；
- 它们对 `race_pace` 和较小权重的 `qualifying_pace` 的影响。

## 2. 代码改动

主要改动文件：

- `src/f1predict/features/provider.py`
- `scripts/smoke_test.py`

新增逻辑：

- `ProcessedFeatureProvider` 现在持有 `OfficialStandingsRepository`；
- `load_event_features()` 会在 OpenF1 analogue 和 FastF1 form 之外，额外加载官方 standings 特征；
- 新增 `_official_standings_adjustments()`，将官方积分榜转换成 driver/team 两层特征；
- 如果 standings 快照晚于预测 cutoff，或 standings 与本地 roster 有 warning，则不会进入模型；
- smoke test 明确验证官方 standings 特征进入了完整 pipeline，并且方向合理：
  - Mercedes team race pace 为正；
  - Ferrari team race pace 为正；
  - Cadillac team race pace 为负；
  - Antonelli driver race pace 为正；
  - Perez driver race pace 为负。

## 3. 本次进入模型的信息

British GP cutoff：`2026-06-30T12:00:00+00:00`

官方 standings 快照时间：`2026-06-30T07:44:26+00:00`

本次 British GP prediction packet 中：

- 总特征数：209
- 官方 standings 特征数：66
- 代表性 team 特征：
  - Mercedes `race_pace`: `+0.105`, confidence `0.384`
  - Ferrari `race_pace`: `+0.068`, confidence `0.384`
  - McLaren `race_pace`: `+0.0451`, confidence `0.384`
  - Red Bull `race_pace`: `+0.0226`, confidence `0.384`
  - Cadillac `race_pace`: negative

这些值会再经过 `FeatureAdjustment.weighted_value()` 进入 pace model，因此不是无约束地覆盖原模型。

## 4. 同口径预测 diff

候选 run：

`british_gp_20260630T120000_0000_20260705T085742_0000_18340da940`

对比基线 run：

`british_gp_20260630T120000_0000_20260705T084127_0000_c3e0679d18`

diff artifact：

- `reports/prediction_diffs/british_gp/british_gp_20260630T120000_0000_af27a96c1210.prediction_diff.json`
- `reports/prediction_diffs/british_gp/british_gp_20260630T120000_0000_af27a96c1210.prediction_diff.md`

匹配情况：

- event 相同；
- cutoff 相同；
- iterations 相同：600；
- `match_warnings`: 空；
- `input_changed`: true；
- `evidence_changed`: false；
- `information_intake_changed`: false；
- `probability_changed`: true。

这说明本次概率变化来自模型输入中的结构化 standings 特征，而不是 Codex evidence 变化、intake 变化或模拟次数变化。

主要概率变化：

- Verstappen win：`-0.0250`，expected points：`-0.395`
- Antonelli win：`+0.0200`，expected points：`+0.365`
- Russell win：`+0.0167`，expected points：`+0.3133`
- Hamilton win：`-0.0050`，expected points：`+0.0967`

新 British GP 预测前排：

- Russell：win `0.2800`，expected points `16.585`
- Antonelli：win `0.3300`，expected points `17.4417`
- Verstappen：win `0.2167`，expected points `15.4133`
- Hamilton：win `0.1350`，expected points `13.6483`

解释：Mercedes 的车队和车手 standings 特征被上调后，Russell/Antonelli 整体得到小幅增强；Red Bull 虽然 standings 仍为正向，但相对 Mercedes/Ferrari/McLaren 弱，因此 Verstappen 的胜率被挤压。

## 5. 历史 replay 结果

新 replay artifact：

- `reports/chronological_replay_v2_official_standings/2026_asof_20260701T000000_0000.chronological_replay.json`
- `reports/chronological_replay_v2_official_standings/2026_asof_20260701T000000_0000.chronological_replay.md`

与旧 replay 对比：

- scored events：`8 -> 8`
- top pick hits：`3 -> 3`
- top pick misses：`5 -> 5`
- top pick hit rate：`0.375 -> 0.375`
- median actual winner rank：`2 -> 2`
- weak evidence quality events：`3 -> 3`
- market snapshots events：`2 -> 2`

逐站结果也没有变化。

原因不是改动没有接入模型，而是 cutoff 边界严格生效：当前本地官方 standings 快照捕获于 `2026-06-30T07:44:26+00:00`，对 `2026-07-01` replay 中已经完成的前 8 站来说，该快照都晚于对应赛前 cutoff，不能泄漏进这些历史预测。因此它会影响 British GP 这类快照之后的预测，但不会改变更早历史 replay。

## 6. 结论

本次改动是有效的输入链路改动：

- 它进入了完整 prediction pipeline；
- 它改变了 prediction run 的 input fingerprint；
- 它在同口径 diff 中造成了概率变化；
- 变化方向与官方 standings 信息一致；
- 它没有被伪装成历史准确率提升，因为 replay 指标确实没有改善。

当前预测效果仍然只能标为 `diagnostic_only`。原因是核心瓶颈还在：

- 多数历史赛事缺少赛前同时间市场快照；
- 部分 Codex evidence 仍需要 cutoff 前 archive 证明；
- 还缺少 race-week practice、qualifying、long-run pace、赛道几何、天气、轮胎、升级和策略等更关键的高频特征；
- 当前 standings 特征是赛季形态 prior，不足以单独修正具体赛道/具体比赛周末的真实强弱。

## 7. 下一步

下一步应优先补“赛前周末 session 级别信息”：

1. 为每站建立 cutoff-aware 的 practice/qualifying/long-run pace 特征；
2. 将 sector、speed trap、stint、tyre degradation 映射到统一 ontology；
3. 每次接入后继续生成 prediction run、matched diff 和 replay；
4. 只有当 replay 和校准指标实际改善时，才把它称为预测能力提升。
