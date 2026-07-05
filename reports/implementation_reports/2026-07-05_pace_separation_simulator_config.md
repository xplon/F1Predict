# 2026-07-05 模拟器 pace separation 默认参数更新报告

## 1. 本轮目标

上一轮 FastF1 season momentum 特征让 top pick 命中率提升到了 50%，但概率质量并不理想：真实冠军概率、Brier、log loss 和 top-pick calibration gap 仍然偏弱。

本轮不是改前端，也不是引入新的事实信息源，而是处理一个更底层的问题：同样的信息输入下，模拟器是否把车队/车手 pace 差异压得过平，导致概率不够分离、校准偏差较大。

## 2. 做了什么

### 2.1 运行模拟器候选参数诊断

运行命令：

```text
.venv\Scripts\python.exe -m f1predict.cli simulator-calibration --year 2026 --as-of 2026-07-01T00:00:00+00:00 --iterations 300 --write --output-dir reports/simulator_calibration_v2_fastf1_momentum
```

生成 artifact：

- `reports/simulator_calibration_v2_fastf1_momentum/2026_asof_20260701T000000_0000.simulator_calibration.json`
- `reports/simulator_calibration_v2_fastf1_momentum/2026_asof_20260701T000000_0000.simulator_calibration.md`

诊断结果推荐 `pace_separation` 候选参数：

| 指标 | 旧默认 | pace_separation | 变化 |
|---|---:|---:|---:|
| top_pick_hit_rate | 0.5000 | 0.5000 | 0.0000 |
| mean_actual_winner_probability | 0.2683 | 0.2917 | +0.0234 |
| mean_winner_brier_score | 0.7104 | 0.6940 | -0.0164 |
| mean_actual_log_loss | 1.4044 | 1.3485 | -0.0559 |
| weighted_top_pick_calibration_gap | 0.1592 | 0.1237 | -0.0355 |

解释：命中率没有提升，但模型给真实冠军的概率更高，Brier 和 log loss 更低，top-pick 概率校准 gap 更小。也就是说，本轮改动主要改善概率校准，不是改善“猜中第一名”的次数。

### 2.2 更新默认模拟器配置

修改文件：

- `src/f1predict/models/simulator.py`

新的默认配置：

- `config_id`: `default_pace_separation_v1`
- `qualifying_noise_sd`: `0.38`
- `race_score_lap_time_scale`: `0.66`
- `race_noise_base_sd`: `4.8`
- `race_noise_per_lap_sd`: `0.045`

直观含义：

- 降低排位和正赛全局噪声；
- 提高 race score 对圈速/完赛时间的区分度；
- 让已有 pace、技术因子、赛季 momentum 的差异更明确地进入排名和积分概率。

### 2.3 保留旧默认作为校准候选

修改文件：

- `src/f1predict/simulator_calibration.py`

因为新的默认值已经是 `pace_separation`，所以候选网格里新增 `legacy_default_current`，保留旧默认参数，方便后续继续做同口径诊断对照。

### 2.4 把模型配置写进 Prediction Packet 和 Run Fingerprint

修改文件：

- `src/f1predict/prediction_packet.py`
- `src/f1predict/run_tracking.py`
- `scripts/smoke_test.py`

新增 `model_context`，其中记录：

- pipeline class；
- 当前 simulator config 的完整参数；
- packet markdown 中展示关键模拟器参数；
- run registry 的 `input_fingerprint` 纳入 `model_context`。

这一步很重要：如果模型参数改变但输入 fingerprint 不变，之后就会再次出现“预测变了，但审计系统不知道为什么变”的问题。本轮修正后，模型配置变化会被 MatchedPredictionDiff 识别为 `input_changed: true`。

## 3. 本轮预测链路影响

重新生成 British GP prediction run：

- run: `reports/prediction_runs/runs/british_gp/british_gp_20260630T120000_0000_20260705T092817_0000_a3e42a5ba0.prediction_run.json`
- packet: `reports/prediction_packets_v2/british_gp/2026-07-05T09_28_11_00_00/british_gp/british_gp_20260630T120000_0000.prediction_packet.json`
- diff: `reports/prediction_diffs/british_gp/british_gp_20260630T120000_0000_a0bf26eec318.prediction_diff.json`

MatchedPredictionDiff 结果：

- `input_changed`: `true`
- `evidence_changed`: `false`
- `probability_changed`: `true`
- `information_intake_changed`: `false`

解释：本轮没有改变 Codex evidence/intake；变化来自模型/模拟器配置，所以这正是预期结果。

British GP 最大变化：

| 车手 | win_delta | expected_points_delta |
|---|---:|---:|
| antonelli | +0.0533 | +0.8433 |
| hamilton | -0.0183 | +0.1100 |
| norris | -0.0133 | -0.2833 |
| piastri | -0.0117 | -0.2067 |
| verstappen | -0.0100 | +0.2567 |
| russell | +0.0050 | +0.4450 |

## 4. 历史 replay 验证

运行命令：

```text
.venv\Scripts\python.exe -m f1predict.cli chronological-replay --year 2026 --as-of 2026-07-01T00:00:00+00:00 --iterations 300 --write --output-dir reports/chronological_replay_v2_pace_separation --no-components --no-freeze
```

生成 artifact：

- `reports/chronological_replay_v2_pace_separation/2026_asof_20260701T000000_0000.chronological_replay.json`
- `reports/chronological_replay_v2_pace_separation/2026_asof_20260701T000000_0000.chronological_replay.md`

与上一版 `reports/chronological_replay_v2_fastf1_momentum/2026_asof_20260701T000000_0000.chronological_replay.json` 的对比：

| 指标 | 上一版 | 本轮 | 变化 |
|---|---:|---:|---:|
| top_pick_hit_rate | 0.5000 | 0.5000 | 0.0000 |
| mean_actual_winner_probability | 0.2683 | 0.2917 | +0.0234 |
| mean_winner_brier_score | 0.7104 | 0.6940 | -0.0164 |
| mean_actual_log_loss | 1.4044 | 1.3485 | -0.0559 |
| weighted_top_pick_calibration_gap | 0.1592 | 0.1237 | -0.0355 |

## 5. 验证

通过：

```text
.venv\Scripts\python.exe scripts\smoke_test.py
```

结果：

```text
smoke_test: ok
```

说明：

- 第一次 124 秒超时，没有失败栈；
- 清理残留 Python 进程后，用更长时间窗口重跑通过，用时约 188 秒；
- 这说明当前 smoke test 已经很重，后续应该拆分成更快的单元 smoke 和较慢的集成 smoke。

## 6. 实验完整性边界

本轮结果仍然只能称为诊断性改进，不能称为正式 edge 证明。

原因：

- 只有 8 场已完成比赛样本；
- 候选参数是手工网格，不是完整优化；
- 选择 `pace_separation` 是 in-sample，没有独立 holdout；
- 市场快照覆盖不足，不能验证真实交易 edge；
- 一些 source snapshot 仍然是 retrospective，需要后续替换或证明 cutoff 前可见。

本轮可以支持的谨慎结论：

> 在同一知识截止时间、同一 replay 口径、同一已完成赛事集合下，把模拟器默认参数更新为 `default_pace_separation_v1` 后，概率校准相关诊断指标变好，并且预测链路能明确记录这是模型配置变化导致的概率变化。

本轮不能支持的结论：

> 当前模型已经具备稳定盈利 edge。

## 7. 下一步建议

1. 拆分 smoke test：保留快速后端健康检查，把慢速全量 smoke 移到集成验证。
2. 继续做信息摄取增强：把练习赛、排位、长距离、升级包、采访、技术分析归入统一 factor ontology。
3. 做 holdout 式 replay：不要只在同一 8 场样本上选参数。
4. 强化市场快照：没有同一 cutoff 的市场价格，就不能验证 edge。
5. 前端只读取最新 run/diff/replay artifact，不在页面实时重算。
