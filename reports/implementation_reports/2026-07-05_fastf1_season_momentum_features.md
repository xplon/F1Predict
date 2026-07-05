# FastF1 赛季趋势与 Momentum 特征接入报告

生成日期：2026-07-05

## 1. 本次改动目的

上一轮已经把官方 standings 接入了预测链路，但它只能影响 standings 快照之后的预测，不能改善更早历史 replay。用户明确指出，模型需要能识别“长期强弱”和“最近几站走势变化”，例如：

- 梅奔长期很强；
- 法拉利是第二梯队；
- 红牛最近几站有所长进；
- 不能只靠手写强约束。

本次改动用已经存在的 cutoff-valid FastF1 正赛结果，新增两类结构化特征：

- `fastf1_season_form`：赛季至今长期 form；
- `fastf1_momentum`：最近窗口相对更早窗口的走势变化。

它们都通过标准 `FeatureAdjustment` 进入 pace model，而不是写死车队结论。

## 2. 代码改动

主要文件：

- `src/f1predict/features/provider.py`
- `scripts/smoke_test.py`

新增逻辑：

- 保留原有最近 3 站 `fastf1_form`；
- 新增赛季至今 driver race pace、driver qualifying pace、driver reliability；
- 新增赛季至今 team race pace；
- 新增 recent-vs-older driver race pace momentum；
- 新增 recent-vs-older driver qualifying momentum；
- 新增 recent-vs-older team race pace momentum；
- smoke test 检查：
  - `fastf1_season_form` 进入完整 pipeline；
  - Mercedes/Ferrari season team prior 为正；
  - Cadillac season team prior 为负；
  - Antonelli season driver prior 为正；
  - Red Bull team momentum 为正；
  - Mercedes team momentum 为负，表示长期强但近期相对优势回落。

## 3. British GP 单站预测影响

新 run：

`british_gp_20260630T120000_0000_20260705T091445_0000_d3dc4862b3`

对比基线：

`british_gp_20260630T120000_0000_20260705T085742_0000_18340da940`

diff artifact：

- `reports/prediction_diffs/british_gp/british_gp_20260630T120000_0000_7c675202e4a1.prediction_diff.json`
- `reports/prediction_diffs/british_gp/british_gp_20260630T120000_0000_7c675202e4a1.prediction_diff.md`

匹配情况：

- event 相同；
- cutoff 相同；
- iterations 相同：600；
- `match_warnings`: 空；
- `input_changed`: true；
- `evidence_changed`: false；
- `information_intake_changed`: false；
- `probability_changed`: true。

本次 British GP prediction packet 中：

- 总特征数：340；
- `fastf1_season_form`: 76 条；
- `fastf1_momentum`: 55 条。

主要概率变化：

- Verstappen win：`-0.0283`，expected points：`-0.4817`
- Antonelli win：`+0.0217`，expected points：`+0.1800`
- Hamilton win：`-0.0150`，expected points：`-0.3617`
- Norris win：`+0.0150`，expected points：`+0.3550`
- Russell win：`+0.0067`，expected points：`+0.3017`

新 British GP 前排预测：

- Antonelli：win `0.3517`，expected points `17.6217`
- Russell：win `0.2867`，expected points `16.8867`
- Verstappen：win `0.1883`，expected points `14.9317`
- Hamilton：win `0.1200`，expected points `13.2867`
- Norris：win `0.0317`，expected points `10.0600`

解释：

- Mercedes 的 season form 很强，因此 Antonelli/Russell 继续增强；
- Red Bull team momentum 为正，但 season form 与 official standings 相对 Mercedes/Ferrari 较弱，所以 Verstappen 被整体下调；
- Norris 获得一定提升，来自赛季/近期 form 对 McLaren 相对表现的补充；
- Hamilton 仍保持前列，但相对 Mercedes 与 McLaren 的新增结构化 form 被挤压。

## 4. 历史 replay 结果

新 replay artifact：

- `reports/chronological_replay_v2_fastf1_momentum/2026_asof_20260701T000000_0000.chronological_replay.json`
- `reports/chronological_replay_v2_fastf1_momentum/2026_asof_20260701T000000_0000.chronological_replay.md`

对比上一轮 official standings replay：

- scored events：`8 -> 8`
- top pick hits：`3 -> 4`
- top pick misses：`5 -> 4`
- top pick hit rate：`0.375 -> 0.500`
- median actual winner rank：`2 -> 2`
- model ranking calibration gap root-cause count：`5 -> 4`

逐站变化：

- Monaco GP：top pick 从 Verstappen 改为 Antonelli，实际冠军 Antonelli，因此由 miss 变为 hit；
- Miami GP：top pick 从 Verstappen 改为 Hamilton，但实际冠军 Antonelli，仍然 miss，实际冠军排名从 2 降到 3；
- Japanese GP、Canadian GP：实际冠军 Antonelli 的模型概率上升；
- Austrian GP：实际冠军 Russell 的排名从 3 升到 2，但 top pick 仍是 Antonelli；
- Barcelona GP：实际冠军 Hamilton 的概率下降，仍然 miss。

## 5. 诚实评估

这次是一个有效的 diagnostic improvement：

- 它进入了预测输入；
- 它改变了 British GP 单站预测；
- 它在历史 replay 中把 top-pick hit rate 从 `0.375` 提升到 `0.500`；
- 它确实表达了长期 form 和近期 momentum 两类不同信号。

但它不是 formal-ready：

- 样本只有 8 站；
- mean actual log loss 从 `1.3815` 变差到 `1.4044`；
- weighted top-pick calibration gap 从 `0.1013` 变差到 `0.1592`；
- 市场快照仍严重不足；
- 部分来源仍需要 cutoff-valid archive proof；
- 本次仍只用了 race result 派生 form，不是 practice/qualifying/long-run pace 本身。

因此结论是：排序命中方向改善，但概率校准变差，下一步必须做校准与更细粒度 session 特征。

## 6. 下一步

最重要的下一步不是继续堆更多派生 prior，而是补真正的 race-week session 数据：

1. 为 completed races 接入 cutoff-valid qualifying/practice/long-run data；
2. 将 qualifying result/grid 与 practice pace 分开进入 `qualifying_pace`、`race_pace`、`tyre_deg`；
3. 给 simulator 参数做 replay calibration，特别是 top-pick confidence 和 log loss；
4. 对新增特征继续执行同口径 run/diff/replay，不把单项指标改善包装成正式 edge。
