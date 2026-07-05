# 每次提交/阶段进展与效果报告

生成日期：2026-07-05

## 1. 说明

这份报告按 git 提交和阶段整理。它不是严格的真实工时计量，因为有些工作发生在同一小时内，有些长耗时发生在 replay/smoke 命令中。这里采用当前仓库的 git 提交时间、实现报告、prediction run、diff 和 replay artifact 作为证据。

核心评判标准是：每次提交是否让预测闭环更接近用户目标，是否真的影响预测结果，是否改善历史 replay。

## 2. 提交概览

| 时间 | Commit | 主题 | 是否主要改预测结果 | 效果判断 |
|---|---|---|---|---|
| 2026-07-05 16:33 | `122e666` | Prediction run tracking foundation | 否，架构基础 | 必要；建立 run/intake/diff |
| 2026-07-05 16:46 | `9aef49e` | Backend API v2 workflow | 间接 | 必要；让前端/外部只读 artifact |
| 2026-07-05 17:05 | `3b398b6` | Official standings race features | 是 | British 预测变化；更早 replay 不变，符合 cutoff |
| 2026-07-05 17:18 | `69d1975` | FastF1 season momentum features | 是 | top-pick hit 0.375 -> 0.500，但 log loss 变差 |
| 2026-07-05 17:41 | `8c04c85` | Simulator pace separation calibration | 是 | 概率校准诊断改善，命中率不变 |
| 2026-07-05 18:14 | `6e3e1de` | Race execution + full-field metrics | 很小 | 预测变化很小；新增全场排名/积分评估 |
| 2026-07-05 18:38 | `b3ebfc0` | Track feature vector simulator inputs | 是 | 赛道特征进入 simulator，British diff material |
| 2026-07-05 19:26 | `9e5d93b` | Qualifying + team strength features | 是 | replay hit 0.500 -> 0.625，当前最好的 top-pick 版本 |
| 2026-07-05 20:43 | `348d4ec` | FastF1 session lap pace features | 是 | 输入更完整，但 replay top-pick 回落到 0.500 |

## 3. 各阶段详情

### 3.1 PredictionRunRegistry / InformationIntakeStore / MatchedPredictionDiff

提交：`122e666`

做了什么：

- 建立 `PredictionRunRegistry`；
- 建立 `InformationIntakeStore`；
- 建立 `MatchedPredictionDiff`；
- 每次 prediction packet 可注册为 run；
- run 记录 input/evidence/probability fingerprint；
- diff 能比较同一 event/cutoff 下概率变化。

是否有效：

- 有效，但它本身不是预测精度提升；
- 它解决的是用户指出的核心审计问题：以后不能再出现“结果变没变不知道，前端没更新还是模型没更新也不知道”。

是否影响预测结果：

- 不直接影响预测；
- 影响的是可追踪性。

### 3.2 Backend API v2

提交：`9aef49e`

做了什么：

- 新增 `BackendApiV2`；
- 提供 health、verified facts、season state、information intake、prediction runs、prediction diffs 等接口；
- 旧 server 保持兼容；
- 写了中文 API 文档。

是否有效：

- 有效，后端具备 artifact-first 的读取方式；
- 为前端后续只读 latest run/diff/replay 做基础。

是否影响预测结果：

- 不应直接影响模型；
- 当时生成 British run 和 diff，但有 `iteration_count_mismatch`，所以不能把概率变化归因于模型改进。

### 3.3 官方积分榜特征

提交：`3b398b6`

做了什么：

- 把 F1 官方 standings 快照转成 cutoff-safe `FeatureAdjustment`；
- driver/team standings 进入 `race_pace` 和较小权重 `qualifying_pace`；
- 用 standings 让模型从公开结构化信息推断当前赛季强弱。

证据：

- British GP 总特征数 209；
- 官方 standings 特征 66；
- 同 cutoff diff 中 `input_changed=true`、`probability_changed=true`、`evidence_changed=false`。

是否影响预测结果：

- 影响 British GP；
- 例如 Verstappen win -2.50pp，Antonelli win +2.00pp，Russell win +1.67pp。

是否改善 replay：

- 没有改善更早 replay；
- 原因是 standings 快照捕获于 `2026-06-30T07:44:26+00:00`，对已完成前 8 站赛前 cutoff 来说不可用，不能泄漏。

结论：

- 这是正确的 cutoff-safe 输入链路，不是 replay 提升。

### 3.4 FastF1 season form / momentum

提交：`69d1975`

做了什么：

- 从 FastF1 正赛结果生成长期 form；
- 从 recent-vs-older 生成 momentum；
- team/driver 两层都进入模型。

是否影响预测结果：

- 影响 British GP；
- British GP 特征数增加到 340；
- `fastf1_season_form` 76 条，`fastf1_momentum` 55 条。

是否改善 replay：

- top-pick hit rate：0.375 -> 0.500；
- Monaco 从 Verstappen 改成 Antonelli，实际 Antonelli，命中改善；
- 但 mean log loss 和 calibration gap 变差。

结论：

- 排名方向有帮助，概率校准有副作用；需要后续校准。

### 3.5 Pace separation simulator config

提交：`8c04c85`

做了什么：

- 用诊断网格比较模拟器参数；
- 更新默认 simulator config 为 `default_pace_separation_v1`；
- 把 simulator config 写入 prediction packet 和 run input fingerprint。

是否影响预测结果：

- 影响 British GP；
- Antonelli win +5.33pp，Russell expected points +0.445，Verstappen expected points +0.257。

是否改善 replay：

- top-pick hit rate 不变：0.500；
- mean actual winner probability：0.2683 -> 0.2917；
- Brier：0.7104 -> 0.6940；
- log loss：1.4044 -> 1.3485；
- top-pick calibration gap：0.1592 -> 0.1237。

结论：

- 这是概率校准诊断改善，不是正式参数优化，因为没有 holdout。

### 3.6 Race execution 与 full-field replay metrics

提交：`6e3e1de`

做了什么：

- 新增 `race_execution` metric；
- 把 grid-to-finish 转换归一化后作为正赛执行力；
- 新增 full-field replay 指标：rank MAE、points MAE、podium overlap、points overlap。

是否影响预测结果：

- 很小；
- British GP 最大 win delta 约 0.33pp。

是否改善 replay：

- 基本没有；
- rank/points/podium/top10 指标几乎不变。

结论：

- 预测精度收益不显著，但非常重要，因为以后不再只看冠军命中，而能评价整场比赛。

### 3.7 TrackFeatureVector

提交：`b3ebfc0`

做了什么：

- 新增赛道向量；
- 把赛道几何、pit loss、track position、safety car、tyre degradation、wet probability 等进入 simulator；
- 增加 `/api/v2/track-features`；
- 修正不可信海拔字段，例如 Monaco 9999m 不进入模型。

是否影响预测结果：

- 影响 British GP；
- changed drivers 22；
- material changed drivers 15；
- max win delta 2.083pp；
- max expected points delta 0.3958。

是否改善 replay：

- 不是主要提升项；
- 它的价值在于让赛道真正影响模拟，而不是只显示在前端或审计文本里。

结论：

- 方向正确；仍缺逐弯速度、DRS/2026 替代部署、真实超车点等更细信息。

### 3.8 Qualifying order 与 team strength reestimate

提交：`9e5d93b`

做了什么：

- 摄取 FastF1 2026 已完赛排位结果；
- same-event qualifying classification 进入 `qualifying_pace`；
- race-morning cutoff 允许使用已发生排位，不允许使用正赛结果；
- known qualifying order 进入 simulator grid sampler；
- FastF1 正赛结果重估 team strength。

是否影响预测结果：

- 显著影响 Austrian；
- known qualifying order 让 Russell P1 发车等真实赛前信息进入模拟。

是否改善 replay：

- top-pick hit rate：0.500 -> 0.625；
- median actual winner rank：2 -> 1；
- rank MAE：5.2159 -> 5.1932；
- points MAE：3.1528 -> 3.1375。

结论：

- 这是当前效果最好的后端模型改进之一；
- 但仍是 diagnostic only。

### 3.9 FastF1 session lap features

提交：`348d4ec`

做了什么：

- 新增 FastF1 session laps 摄取；
- 新增 session lap summary；
- practice/Q laps 进入 race pace、tyre deg、straight-line speed、qualifying pace；
- 修正 2026 车号错配：优先按 driver_id/full_name，车号只 fallback；
- British race-morning 接入 FP1、Q laps、Q classification。

是否影响预测结果：

- 显著影响 Austrian；
- changed drivers 22；
- material changed drivers 13；
- max win delta 3.50pp；
- max expected points delta 0.4283。

是否改善 replay：

- 没有；
- top-pick hit rate：0.625 -> 0.500；
- median actual winner rank：1 -> 2；
- podium overlap：0.5417 -> 0.5833。

结论：

- 这是必要信息链路，但权重/尺度尚未校准；
- 不应声称预测效果提升。

## 4. 预测结果修正发生了多少次

如果只数“架构搭建后，产生同 cutoff prediction diff 且 probability_changed=true 的模型/信息更新”，至少包括：

1. 官方 standings 特征；
2. FastF1 season/momentum；
3. pace separation simulator config；
4. race_execution；
5. TrackFeatureVector；
6. qualifying known order；
7. team strength reestimate；
8. session lap features。

其中真正改善 replay 关键指标的阶段：

- FastF1 season/momentum：top-pick hit 0.375 -> 0.500；
- pace separation：校准指标改善；
- qualifying/team strength：top-pick hit 0.500 -> 0.625；

没有改善或效果很弱的阶段：

- official standings：因 cutoff 不影响早期 replay；
- race_execution：当前 grid-to-finish 特征太弱；
- session lap features：输入重要，但未校准导致 top-pick 回落。

## 5. 总体评价

这 3 小时内并不是每个提交都让预测变好。更准确地说：

- 前半段主要补审计闭环；
- 中段补结构化赛季强弱和模拟器校准；
- 后半段补赛道、排位、练习赛等重要信息；
- 当前最有效的 replay 改进来自 FastF1 form/momentum、模拟器 pace separation、qualifying/team strength；
- session lap 接入虽然重要，但当前效果没有达到预期，下一步必须校准。

因此，当前不能说“已经实现稳定 edge”。可以说：后端已经建立了每次改动是否影响预测、是否改善 replay 的证据链。
