# 2026-07-05 FastF1 Session Lap 特征接入报告

## 本次目标

把赛前练习赛/排位赛的单圈、长距离 proxy、轮胎衰退 proxy 接入预测链路。这个改动对应用户强调的核心因素：练习赛 pace、长距离速度、轮胎衰退、排位差距、直道速度，而不是只看历史积分或冠军概率。

## 实现内容

1. 新增 FastF1 session lap 摄取：
   - `FastF1Client.session_laps()`
   - `LiveIngestor.ingest_fastf1_session_laps()`
   - CLI：`ingest-fastf1-laps`

2. 新增 `FastF1SessionLapRepository`：
   - 读取本地 `data/raw/fastf1/*_laps` snapshot；
   - 汇总每个车手的 fastest lap、fast 5、long-run proxy、tyre degradation proxy、speed-trap average；
   - 同时保存 session weather summary；
   - 支持 FastF1 的 ISO-8601 duration 格式，例如 `P0DT0H1M8S`。

3. 修正关键身份映射风险：
   - 2026 车号和旧 seed external_ids 不一致，例如 FastF1 中 Norris 是 1 号、Verstappen 是 3 号；
   - session lap 特征现在优先按 `driver_id/full_name` 匹配，车号只做 fallback；
   - 避免把 Norris 的练习赛长距离错误映射给 Verstappen。

4. 接入预测特征：
   - Practice/Sprint practice -> `race_pace`、`tyre_deg`、`straight_line_speed`；
   - Qualifying laps -> gap-aware `qualifying_pace`；
   - 同时生成 driver-level 和 team-level 特征；
   - 使用 robust median/IQR 尺度和 outlier 过滤，避免一个异常慢 stint 把全场特征推满上限。

5. 修正 OpenF1 summary：
   - 从只保留前 10 名，改为保留 `driver_stats` 全场；
   - practice 类比优先用 `long_run_proxy` 排序；
   - 保持 `fastest_drivers` 兼容旧 artifact。

## 新增数据

已补入已完赛赛事的赛前 practice laps：

- Australian FP2
- Chinese FP1
- Japanese FP2
- Miami FP1
- Canadian FP1
- Monaco FP2
- Barcelona FP2
- Austrian FP2

已补入 British race-morning 输入：

- British FP1 laps
- British Qualifying results
- British Qualifying laps

## 预测影响

### Austrian matched diff

对比上一版 run：

- Base：`austrian_gp_20260628T000000_0000_20260705T111121_0000_4e69601269`
- Candidate：`austrian_gp_20260628T000000_0000_20260705T115827_0000_469087c96e`
- Diff：`reports/prediction_diffs/austrian_gp/austrian_gp_20260628T000000_0000_8b9d974a2f66.prediction_diff.json`

结果：

- input changed：true
- evidence changed：false
- probability changed：true
- changed drivers：22
- material changed drivers：13
- max win delta：0.0350
- max expected points delta：0.4283

最大变化：

- Antonelli：win +3.50pp，expected points +0.428
- Verstappen：win -1.83pp，expected points -0.249
- Hamilton：win -1.75pp，expected points -0.193
- Norris：expected points +0.193
- Russell：podium +1.42pp，expected points +0.122

说明：本次改动确实进入预测结果，不是“做了代码但结果没动”。

### British race-morning prediction

Run：

- `british_gp_20260705T000000_0000_20260705T115935_0000_9e3dfa22c3`

主要结果：

- Antonelli win 45.33%，expected points 19.35，expected rank 2
- Russell win 33.83%，expected points 18.25，expected rank 1
- Verstappen win 12.00%，expected points 14.20
- Hamilton win 7.17%，expected points 13.26
- Norris win 1.17%，expected points 9.58

British race-morning 特征确认：

- session lap features：97
- qualifying result driver features：22
- known qualifying order：22 drivers，P1 Antonelli

## 历史 replay 结果

Artifact：

- `reports/chronological_replay_v2_session_lap_features/2026_asof_20260701T000000_0000.chronological_replay.json`
- `reports/chronological_replay_v2_session_lap_features/2026_asof_20260701T000000_0000.chronological_replay.md`

对比上一版 team-strength replay：

| 指标 | 上一版 | 本次 |
|---|---:|---:|
| top pick hit rate | 0.625 | 0.500 |
| median actual winner rank | 1 | 2 |
| mean abs rank error | 5.1932 | 5.2045 |
| mean abs points error | 3.1375 | 3.1381 |
| podium overlap | 0.5417 | 0.5833 |
| points overlap | 0.6125 | 0.6125 |

结论：本次 session lap 特征让输入和概率显著变化，但诊断 replay 的 top-pick 和 rank/points 误差没有改善，反而略差；podium overlap 改善。不能把这次改动宣称为预测效果提升，只能说它补上了重要输入链路，并暴露出下一步需要校准 session 特征权重。

## 验证情况

通过：

- `python -m compileall src scripts`
- 定向 session-lap 验证脚本：
  - Austrian FP2 summary 全场化；
  - session lap race_pace 特征没有重复错配；
  - Norris/Russell 练习赛特征为正；
  - British race-morning 包含 FP1/Q laps、22 个 Q result features 和 known qualifying order。
- `chronological-replay --no-components --no-freeze` 成功写出 1200-iteration replay bundle。

未完全通过：

- `scripts/smoke_test.py` 在 10 分钟工具超时处被杀，没有得到最终通过/失败结论。
- 完整 `chronological-replay` 带 components/freezer 的命令在 20 分钟工具超时处被杀；但主 replay bundle 已完整写出，之后用 `--no-components --no-freeze` 成功复现。

## 当前判断

这是必要改动，但不是最终有效改动。它解决了“练习赛/长距离/轮胎衰退没有进入模型”的结构性缺口，也修掉了 2026 车号错配风险；但新信息的权重还没有校准好，当前 replay 不支持“预测效果显著更优”的说法。

下一步应该做：

1. 用 replay 自动校准 session-lap 特征权重，尤其是 practice race pace 和 qualifying lap gap；
2. 对 sprint 周末单独建模，区分 FP1、SQ、Sprint、Q 的含义；
3. 把 FastF1 session source 纳入 intake/source audit，而不仅仅是 feature_adjustments；
4. 拆分长耗时 smoke/replay，让关键验证能在数分钟内稳定跑完。
