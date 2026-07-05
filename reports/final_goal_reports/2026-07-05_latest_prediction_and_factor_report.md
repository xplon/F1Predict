# 最新预测结果与影响因素报告

生成日期：2026-07-05

## 1. 报告范围

本报告对应当前后端最新 artifact，而不是正式 edge 证明。

最新单站预测采用：

- Event：British Grand Prix
- Event ID：`british_gp`
- Knowledge cutoff：`2026-07-05T00:00:00+00:00`
- Prediction run：`british_gp_20260705T000000_0000_20260705T115935_0000_9e3dfa22c3`
- Prediction packet：`reports/prediction_packets_v2/british_gp/british_gp_20260705T000000_0000.prediction_packet.json`
- Status：`diagnostic_only`

当前 blocker：

- `codex_evidence_quality_review_required`
- `probability_calibration_diagnostic_only`

结论先说清楚：当前预测可以用于诊断模型如何处理信息，不能用于宣称已经存在稳定盈利 edge。

## 2. 最新 British GP 全场预测

| 预计排名 | 车手 | Win | Podium | Points | Expected points | Average finish |
|---:|---|---:|---:|---:|---:|---:|
| 1 | Russell | 33.83% | 81.17% | 97.50% | 18.253 | 2.718 |
| 2 | Antonelli | 45.33% | 86.75% | 95.83% | 19.346 | 2.727 |
| 3 | Verstappen | 12.00% | 57.75% | 93.67% | 14.203 | 4.352 |
| 4 | Hamilton | 7.17% | 48.83% | 94.08% | 13.259 | 4.583 |
| 5 | Norris | 1.17% | 13.00% | 94.33% | 9.576 | 5.953 |
| 6 | Piastri | 0.33% | 5.75% | 95.83% | 8.385 | 6.286 |
| 7 | Leclerc | 0.17% | 6.58% | 94.42% | 7.915 | 6.703 |
| 8 | Hadjar | 0.00% | 0.17% | 87.67% | 4.393 | 8.783 |
| 9 | Alonso | 0.00% | 0.00% | 62.50% | 1.645 | 11.013 |
| 10 | Sainz | 0.00% | 0.00% | 60.00% | 1.579 | 11.213 |
| 11 | Albon | 0.00% | 0.00% | 42.83% | 0.982 | 12.169 |
| 12 | Gasly | 0.00% | 0.00% | 25.83% | 0.514 | 13.366 |
| 13 | Ocon | 0.00% | 0.00% | 10.67% | 0.193 | 15.017 |
| 14 | Stroll | 0.00% | 0.00% | 9.17% | 0.158 | 15.533 |
| 15 | Lawson | 0.00% | 0.00% | 6.42% | 0.113 | 15.896 |
| 16 | Lindblad | 0.00% | 0.00% | 5.83% | 0.095 | 16.171 |
| 17 | Perez | 0.00% | 0.00% | 4.25% | 0.085 | 16.204 |
| 18 | Hulkenberg | 0.00% | 0.00% | 5.75% | 0.098 | 16.266 |
| 19 | Colapinto | 0.00% | 0.00% | 4.08% | 0.063 | 16.641 |
| 20 | Bearman | 0.00% | 0.00% | 3.58% | 0.057 | 16.649 |
| 21 | Bottas | 0.00% | 0.00% | 4.50% | 0.068 | 16.863 |
| 22 | Bortoleto | 0.00% | 0.00% | 1.25% | 0.020 | 17.895 |

注意：Antonelli 的胜率最高，但 Russell 的平均完赛名次略好，因此 expected rank 排在 Russell 前面。这说明模型不是只按冠军概率排序，而是在同时输出全场排名、积分和不确定性。

## 3. 当前进入模型的结构化信息

British GP 最新 packet 中共有 `565` 条 `FeatureAdjustment`。

按来源统计：

| 来源 | 数量 | 作用 |
|---|---:|---|
| `fastf1_season_form` | 106 | 赛季至今车手/车队 race pace、qualifying pace、reliability |
| `fastf1_form` | 103 | 最近窗口正赛 form |
| `fastf1_session_laps` | 97 | British FP1/Q laps：长距离、轮胎衰退、直道速度、排位单圈 |
| `fastf1_momentum` | 81 | 近期相对早期的趋势变化 |
| `openf1_summary` | 69 | Silverstone 历史类比 session summary，低置信度 |
| `f1_official_standings` | 66 | 官方积分榜 point-in-time 强弱 prior |
| `fastf1_qualifying_result` | 32 | British Qualifying classification 与 team average |
| `fastf1_team_strength_reestimate` | 11 | 基于 cutoff-valid 正赛积分的车队强度重估 |

按指标统计：

| Metric | 数量 | 含义 |
|---|---:|---|
| `race_pace` | 207 | 正赛长距离/综合速度 |
| `qualifying_pace` | 173 | 排位单圈和发车位能力 |
| `race_execution` | 85 | 起步位到完赛位转换、正赛执行 |
| `reliability` | 40 | 退赛/可靠性风险 |
| `wet_skill` | 22 | 天气和湿地相关 |
| `straight_line_speed` | 22 | 直道速度/阻力效率 proxy |
| `tyre_deg` | 16 | 轮胎衰退 |

## 4. Codex 信息摄取层的影响

当前 British GP 有 6 条 Codex/evidence claim。它们不是人工硬写“谁强谁弱”，而是被路由到统一 ontology 后进入模型。

| Claim | 目标 | Metric | 方向 | 最大胜率影响 | 解释 |
|---|---|---|---|---:|---|
| Mercedes ERS/deployment | Mercedes | `energy_recovery` | 正向 | Antonelli +0.83pp | 高速赛道 ERS 需求会放大 Mercedes 能量部署优势 |
| Ferrari tyre degradation | Ferrari | `tyre_deg` | 负向 | Hamilton -0.67pp | 增加 Ferrari 长距离轮胎衰退风险 |
| Ferrari straight-line speed | Ferrari | `straight_line_speed` | 负向 | Hamilton -0.42pp | Silverstone 高速/长直道环境放大直道速度劣势 |
| Open-Meteo weather forecast | British GP event | `wet_skill` | 负向湿地概率调整 | Antonelli +0.42pp | 改变 wet branch 权重，影响湿地强弱贡献 |
| Red Bull upgrade | Red Bull | `upgrade_effect` | 正向 | Verstappen +0.33pp | 升级包作为 race/qualifying pace 小幅正向项 |
| Ferrari launch | Ferrari | `launch_performance` | 正向 | Hamilton +0.08pp | 进入起步/首圈转换，不是排位速度 |

当前 Codex 层最大问题：

- 多数 seed/Codex claim 仍是 `review_required`；
- 部分 source 仍属于 seed/test-only 或缺少 cutoff 前 source log 证明；
- 所以这些 claim 可用于诊断，但不能支撑正式 edge 结论。

## 5. 模型层最影响结果的信息

从模型影响角度看，当前 British 预测最主要由以下几类驱动：

1. Same-event qualifying order  
   British Qualifying classification 已进入 `fastf1_qualifying_order`，共 22 名车手。P1 Antonelli、P2 Leclerc、P3 Hamilton、P4 Russell、P5 Hadjar。这个信息会强烈影响发车顺序和 grid sampler。

2. Same-weekend session laps  
   British FP1 和 Qualifying laps 产生 97 条 session-lap 特征。它们把长距离 proxy、排位 lap gap、轮胎衰退和 speed trap 纳入模型。

3. Season-to-date FastF1 form  
   赛季至今正赛结果、近期窗口、momentum 和 team strength reestimate 共同把 Mercedes、Ferrari、Red Bull、McLaren 的相对强弱转成 race pace prior。

4. TrackFeatureVector  
   British/Silverstone 被建模为 high-speed track：18 个弯角 proxy、5 个长直道 proxy、aero/ERS/power 需求较高，pit loss 和 safety-car 概率进入 simulator。

5. Race-time simulator  
   排位、发车、长距离 race score、轮胎衰退、进站损失、安全车、天气、可靠性和随机噪声共同采样全场排名。因此输出不是单点排序，而是 Monte Carlo 分布。

## 6. 与上一版相比是否变好

最近一次 matched diff 是 Austrian GP：

- Base：`austrian_gp_20260628T000000_0000_20260705T111121_0000_4e69601269`
- Candidate：`austrian_gp_20260628T000000_0000_20260705T115827_0000_469087c96e`
- changed drivers：22
- material changed drivers：13
- max win delta：3.50pp
- max expected points delta：0.4283

说明 session-lap 改动确实影响了预测链路。

但历史 replay 没有变好：

| 指标 | Team-strength 版 | Session-lap 版 |
|---|---:|---:|
| top pick hit rate | 0.625 | 0.500 |
| median actual winner rank | 1 | 2 |
| mean abs rank error | 5.1932 | 5.2045 |
| mean abs points error | 3.1375 | 3.1381 |
| podium overlap | 0.5417 | 0.5833 |
| points overlap | 0.6125 | 0.6125 |

结论：session-lap 是必须进入模型的重要因素，但当前权重/尺度没有校准好，不能说“预测效果提升”。它改善了 podium overlap，但损害了 top-pick 命中和真实冠军排名。

## 7. Edge 判断

当前不能证明稳定 edge。

原因：

- replay 样本只有 8 场；
- top-pick hit rate 最高诊断版本也只有 0.625，最新版本回落到 0.500；
- 概率校准仍是 diagnostic-only；
- 市场快照覆盖严重不足；
- 同 cutoff 市场价格与 CLV 不完整；
- Codex evidence 仍有 review/source-integrity 风险。

当前可用结论是：

> 后端已经能把赛前结构化数据、Codex 证据、赛道特征、排位/练习赛 session 信息接入完整全场预测，并能通过 run/diff/replay 证明每次改动是否影响预测。当前模型仍处于 diagnostic-only 阶段，下一步核心是校准和市场数据闭环。
