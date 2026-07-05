# 2026-07-05 TrackFeatureVector 与赛道驱动模拟报告

## 1. 本轮目标

本轮优先处理用户反复强调的核心问题：赛道不是前端装饰，而是预测模型的一等输入。

上一版 simulator 已经有轮胎退化、进站损失、安全车、赛道位置惩罚等机制，但这些参数主要来自粗粒度 `track_type` 表。这样会导致两个问题：

1. 有真实赛道几何和天气 profile，却没有充分影响预测；
2. 不同高速度/技术/街道赛道之间的差异过粗，无法解释“为什么这站更重视排位、超车、轮胎、策略或安全车”。

因此本轮新增 `TrackFeatureVector`，并把它接入 simulator、prediction packet 和 API v2。

## 2. 新增后端能力

### 2.1 `TrackFeatureVector`

新增文件：

- `src/f1predict/track_features.py`

它从本地已摄取的 source-backed 数据生成赛道/环境向量：

- OpenF1/Multiviewer circuit profile；
- F1 官方 race profile；
- Open-Meteo 历史天气 profile 或 cutoff-valid forecast；
- event weather prior。

当前输出字段包括：

- 弯角数量；
- 低速/中速/高速弯 proxy；
- 长直道 proxy；
- braking / traction / aero / mechanical grip demand；
- overtaking index；
- track position value；
- pit loss seconds；
- safety car / red flag probability；
- tyre degradation index；
- wet probability、降水 p90、海拔。

重要边界：

这些不是 FIA 官方逐弯速度、DRS 或 2026 替代部署区数据。当前是从角度、弯角进度和天气 profile 推导的 derived proxy，artifact 中会标记为 `source_backed_derived_proxy`。

### 2.2 simulator 接入

修改文件：

- `src/f1predict/models/simulator.py`

以下模拟参数不再只靠 `track_type` 静态表：

- 轮胎退化率；
- pit loss；
- track position penalty；
- safety car probability。

这意味着赛道几何和天气会真正影响比赛排名分布，而不只是出现在审计文本里。

### 2.3 pipeline / packet / API 接入

修改文件：

- `src/f1predict/pipeline.py`
- `src/f1predict/prediction_packet.py`
- `src/f1predict/api_v2.py`
- `docs/backend_api_v2_cn.md`

新增：

- `RaceEvent.feature_refs["track_feature_vector"]`
- prediction packet `model_context.track_feature_vector`
- `GET /api/v2/track-features`

这样每次 prediction run 的 input fingerprint 会包含赛道向量，后续 diff 能识别这是一次输入/模型口径变化。

### 2.4 坏地理字段质量门槛

修改文件：

- `src/f1predict/models/technical_factors.py`
- `src/f1predict/track_features.py`

发现 Monaco 的 weather profile geocoding elevation 为 `9999m`，明显不可信。现在通用规则是：

- 海拔 `< -500m` 或 `> 3000m` 不进入模型；
- `TrackFeatureVector.warning_codes` 记录 `weather_profile_altitude_out_of_model_bounds`。

这不是针对 Monaco 的单点修补，而是防止任何坏 geocoding 字段制造伪高海拔动力单元信号。

## 3. British GP 新预测影响

新 run：

- `reports/prediction_runs/runs/british_gp/british_gp_20260630T120000_0000_20260705T102907_0000_fbbf086270.prediction_run.json`

新 packet：

- `reports/prediction_packets_v2/british_gp/2026-07-05T10_28_51_00_00/british_gp/british_gp_20260630T120000_0000.prediction_packet.json`

新 diff：

- `reports/prediction_diffs/british_gp/british_gp_20260630T120000_0000_f9dda72f3ed8.prediction_diff.json`

Matched diff 结论：

| 字段 | 结果 |
|---|---:|
| input_changed | true |
| evidence_changed | false |
| probability_changed | true |
| information_intake_changed | false |
| changed_driver_count | 22 |
| material_driver_change_count | 15 |
| max_abs_win_delta | 0.020833 |
| max_abs_expected_points_delta | 0.3958 |
| rank_change_count | 6 |

解释：

- Codex evidence 没变；
- information intake 没变；
- 预测变化来自赛道向量进入 simulator；
- 这正是本轮想要验证的链路：同一信息、同一 cutoff 下，模型输入结构变化是否影响最终概率。

British GP 赛道向量摘要：

| 字段 | 值 |
|---|---:|
| track_type | high_speed |
| corner_count | 18 |
| low / medium / high speed corner proxy | 5 / 7 / 6 |
| long_straight_count proxy | 5 |
| aero_efficiency_index | 0.5201 |
| traction_index | 0.3901 |
| overtaking_index | 0.4175 |
| track_position_value | 0.3856 |
| pit_loss_seconds | 19.552 |
| safety_car_probability | 0.4198 |
| tyre_degradation_index | 0.5356 |
| wet_probability | 0.4143 |
| precipitation_p90_mm | 9.0 |

最大概率变化：

| 车手 | win_delta | expected_points_delta |
|---|---:|---:|
| antonelli | +0.0208 | +0.3958 |
| russell | -0.0108 | -0.1800 |
| verstappen | -0.0083 | -0.1492 |
| hamilton | -0.0075 | +0.0333 |
| norris | +0.0025 | +0.1042 |

当前 top win：

| 车手 | win | podium | expected_points | avg_finish |
|---|---:|---:|---:|---:|
| antonelli | 0.4258 | 0.8333 | 18.861 | 2.862 |
| russell | 0.2792 | 0.7383 | 17.135 | 3.038 |
| verstappen | 0.1733 | 0.6258 | 15.068 | 4.125 |
| hamilton | 0.0942 | 0.4858 | 13.433 | 4.567 |
| norris | 0.0192 | 0.1683 | 9.869 | 5.852 |

## 4. 历史 replay 对比

新 replay：

- `reports/chronological_replay_v2_track_features/2026_asof_20260701T000000_0000.chronological_replay.json`
- `reports/chronological_replay_v2_track_features/2026_asof_20260701T000000_0000.chronological_replay.md`

对照上一版：

- `reports/chronological_replay_v2_race_execution/2026_asof_20260701T000000_0000.chronological_replay.json`

同一 cutoff、同一 iterations 下：

| 指标 | race_execution 版 | track_features 版 | 变化 |
|---|---:|---:|---:|
| diagnostic_scored_events | 8 | 8 | 0 |
| top_pick_hit_rate | 0.5000 | 0.5000 | 0.0000 |
| median_actual_winner_rank | 2 | 3 | +1 |
| mean_abs_rank_error | 5.2614 | 5.2273 | -0.0341 |
| mean_abs_points_error | 3.1972 | 3.1915 | -0.0057 |
| mean_podium_overlap_rate | 0.5417 | 0.5417 | 0.0000 |
| mean_points_overlap_rate | 0.6125 | 0.6125 | 0.0000 |

诊断结论：

- full-field rank MAE 小幅改善；
- full-field points MAE 小幅改善；
- top pick hit rate 没变；
- podium/top10 overlap 没变；
- actual winner median rank 变差；
- 因此不能说本轮显著提高了冠军预测能力，只能说赛道向量让整场排名/积分指标略有改善，并且成功把赛道输入接入了可审计预测链路。

## 5. 实验完整性说明

本轮是诊断性模型改进，不是正式 edge 证明。

限制：

- 只有 8 场 replay；
- 赛道向量目前是 derived proxy；
- 还没有 FIA/官方逐弯速度、真实超车热区、2026 替代部署区、逐圈安全车窗口模型；
- 没有完整同一 cutoff 市场快照；
- 当前变化没有经过多 seed 稳定性评估。

可以支持的结论：

> 后端已经把 source-backed 赛道几何和天气信息转成统一赛道向量，并让它影响 simulator 的轮胎、进站、安全车和赛道位置参数。该改动对 British GP 预测产生可观概率变化，并在 8 场历史 replay 上带来轻微 full-field MAE 改善。

不能支持的结论：

> 当前模型已经达到可交易 edge，或赛道向量显著提升冠军预测精度。

## 6. 下一步

下一项更重要的改进应是 race-week pace 数据：

1. 引入练习赛/排位赛/长距离 stint/speed trap/sector 数据；
2. 把它们映射到 qualifying_pace、race_pace、tyre_deg、straight_line_speed、low_speed_traction；
3. 对每个 cutoff 阶段分别融合：赛前、FP 后、排位后、正赛前；
4. 用同一 replay 框架检验 full-field rank/points 是否继续改善。

原因：

赛道向量决定“这站什么能力重要”，但车队/车手在这个周末到底快不快，仍然需要 race-week pace 数据来提供最大信息增益。
