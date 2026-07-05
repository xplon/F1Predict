# FastF1 排位顺序与车队实力重估接入报告

生成时间：2026-07-05

## 这次要解决的问题

本次工作不是做前端展示，而是继续修正后端预测链路：让 cutoff-valid 的真实排位结果和已完成比赛结果进入模型，并且每一步都能通过 PredictionRunRegistry、InformationIntakeStore、MatchedPredictionDiff 和 replay 指标证明“预测有没有被改变”。

## 三个核心概念

### PredictionRunRegistry

PredictionRunRegistry 是“预测运行登记表”。

一次 prediction packet 只是一个预测文件；但如果不登记，就很难回答“这是哪一次模型跑出来的、用的什么 cutoff、输入指纹是什么、概率有没有变”。PredictionRunRegistry 会把每次预测注册成 run，保存：

- run_id；
- event_id / event_name；
- knowledge_cutoff；
- iterations；
- prediction packet 路径；
- 输入指纹、证据指纹、概率指纹；
- 关键概率摘要。

它的作用是让每次预测成为可追踪版本，而不是散落的临时文件。

### InformationIntakeStore

InformationIntakeStore 是“信息摄取快照仓库”。

它记录某个赛事、某个知识截止时间下，本地已经有哪些结构化证据可以用，包括 claim 数量、来源 URL、证据文件路径、source log、research preflight 状态和缺失警告。

它解决的问题是：不能只说“Codex 看过一些资料”，而要能证明这些资料已经变成本地结构化输入，并且能追踪到来源。

### MatchedPredictionDiff

MatchedPredictionDiff 是“同口径预测差异比较器”。

它比较两个已注册 run，检查两者是否是同一个 event、同一个 cutoff、同样 iterations，然后输出：

- 输入是否变化；
- evidence 是否变化；
- information intake 是否变化；
- 概率是否变化；
- 每个车手 win / podium / expected_points / expected_rank 的变化；
- 最大变化和发生变化的车手数。

它的作用是防止“做了很多工程但预测结果没变”这种情况继续发生。

## 本次实现内容

### 1. 接入 FastF1 排位结果

新增/修正内容：

- 给 FastF1 result normalization 增加 `session_date`，用于判断 session 真实发生时间，而不是用抓取时间。
- 批量摄取 2026 已完成分站的 FastF1 Qualifying result snapshot。
- 在 feature provider 中把同事件排位结果转成 driver/team `qualifying_pace` 特征。
- 在 pipeline 中把 cutoff-valid 的排位顺序放进 `event.feature_refs["fastf1_qualifying_order"]`。
- 在 simulator 中优先使用已知排位顺序采样 grid。

关键防泄漏检查：

- British GP 在 `2026-06-30T12:00:00+00:00` cutoff 下不会拿到未来排位。
- Austrian GP 在 `2026-06-28T00:00:00+00:00` race-morning cutoff 下会拿到 22 名车手排位顺序，Russell 为 P1。

### 2. 接入车队当季实力重估

新增 `fastf1_team_strength_reestimate` 特征。

它不手写“Mercedes 强、Red Bull 弱”，而是从 cutoff-valid FastF1 正赛结果中计算：

- 每站双车总积分；
- season-to-date 平均双车积分；
- recent window 平均双车积分；
- 相对全场车队均值的差；
- 有上限、有 confidence 的 team-level `race_pace` 调整。

Austrian race-morning cutoff 下的关键输入：

| Team | value | confidence | weighted_value |
|---|---:|---:|---:|
| Mercedes | 0.1190 | 0.585 | 0.0696 |
| Ferrari | 0.0911 | 0.585 | 0.0533 |
| Red Bull | 0.0370 | 0.585 | 0.0216 |
| McLaren | 0.0276 | 0.585 | 0.0161 |

这正是从已完成比赛结果推断出的“Mercedes 全季强，Ferrari 第二，Red Bull 近期有起色但整体仍低于 Mercedes/Ferrari”的方向。

### 3. 修正 replay provenance

因为现在揭幕战也可能有同事件排位特征，原来用 `feature_adjustment_count == 0` 判断“season opener 没有 prior form”会失效。

已修正为：

- 第 1 站固定记录 `season_opener_no_prior_form`，非阻塞；
- 只有非第 1 站且没有任何 processed features，才记录 `missing_processed_features`。

## 预测变化证据

### Austrian GP 单站 run diff

排位顺序接入后，相比“只把排位当弱 pace 特征”的 run：

- changed_driver_count: 22
- material_driver_change_count: 8
- max_abs_win_delta: 0.005833
- max_abs_expected_points_delta: 0.1000

车队实力重估接入后，相比“已知排位顺序”run：

- changed_driver_count: 22
- material_driver_change_count: 13
- max_abs_win_delta: 0.041667
- max_abs_expected_points_delta: 0.5717

最大变化：

| Driver | win_delta | expected_points_delta | 解释 |
|---|---:|---:|---|
| Verstappen | -0.0417 | -0.572 | Red Bull 个人 seed 被车队当季结果下调 |
| Antonelli | +0.0275 | +0.383 | Mercedes team strength 上调 |
| Russell | +0.0233 | +0.398 | Mercedes team strength + 已知 P1 排位 |

相关 artifact：

- `reports/prediction_diffs/austrian_gp/austrian_gp_20260628T000000_0000_3a11bbd7b979.prediction_diff.md`
- `reports/prediction_diffs/austrian_gp/austrian_gp_20260628T000000_0000_9d3db7970fda.prediction_diff.md`

### 2026 replay 指标

所有 replay 都是 diagnostic only，不是正式 edge 证明。

| 阶段 | top_pick_hit_rate | median_actual_winner_rank | mean_abs_rank_error | mean_abs_points_error |
|---|---:|---:|---:|---:|
| track features | 0.500 | 3 | 5.2273 | 3.1915 |
| qualifying pace features | 0.500 | 3 | 5.2273 | 3.1872 |
| known qualifying order | 0.500 | 2 | 5.2159 | 3.1528 |
| team strength reestimate | 0.625 | 1 | 5.1932 | 3.1375 |

这说明：

- 单纯把排位作为弱 pace 特征，影响很小；
- 把排位顺序真正接入 grid sampling 后，winner rank 和 MAE 有小幅改善；
- 把当季车队实力从正赛结果中重估后，top-pick hit rate、winner rank 和 MAE 都继续改善；
- 但样本只有 8 场，且市场数据不完整，所以仍不能声称存在可交易 edge。

## 当前仍然不足

- 仍缺少 FP1/FP2/FP3、long run、sector、speed trap、轮胎衰退等 session-level pace 数据。
- 排位顺序对比赛结果的影响仍偏保守，需要更正式的 simulator calibration。
- Codex 非结构化新闻/技术分析仍需要继续转成统一 ontology 里的 claim/factor。
- replay 仍有市场数据缺口和 retrospective source snapshot 问题，不能用于正式 edge 结论。
- 前端暂未更新，本次工作只保证后端 artifact 和 run/diff/replay 可追踪。

## 验证

已通过：

- `.venv\Scripts\python.exe -m compileall src scripts`
- `.venv\Scripts\python.exe scripts\smoke_test.py`

