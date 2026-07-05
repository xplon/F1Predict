# 2026-07-05 race_execution 特征与 full-field replay 指标报告

## 1. 本轮目标

本轮处理两个问题：

1. 模型缺少“起跑位到完赛位转换能力”的显式因子。用户强调的起步、缠斗、超车、防守、长距离执行力，不能全部塞进泛化的 `race_pace`。
2. 历史 replay 过度关注冠军命中和冠军概率，不能充分回答“整场比赛所有车手排名和积分预测是否更准”。

因此本轮新增 `race_execution` 因子，并补充 full-field replay 指标。

## 2. 新增后端能力

### 2.1 新 metric: `race_execution`

修改文件：

- `src/f1predict/domain.py`
- `src/f1predict/models/pace.py`
- `src/f1predict/intelligence/factor_contract.py`
- `src/f1predict/intelligence/factor_trace.py`
- `src/f1predict/intelligence/evidence_workflow.py`
- `src/f1predict/intelligence/research_plan.py`

语义：

- `race_pace`：清洁空气速度、长距离速度；
- `qualifying_pace`：低油单圈、发车位能力；
- `race_execution`：起跑位到完赛位转换、超车/防守、交通处理、干净正赛执行。

模型接入方式：

- `race_execution` 只进入正赛 race score；
- 不进入 qualifying grid sampler；
- 这样避免把“正赛执行力”错误地当成单圈排位能力。

### 2.2 FastF1 结构化特征

修改文件：

- `src/f1predict/features/provider.py`

新增三类 cutoff-safe 特征：

- `fastf1_form:*:race_execution`：最近窗口历史完赛转换；
- `fastf1_season_form:*:race_execution`：赛季至今历史完赛转换；
- `fastf1_momentum:*:race_execution`：近期相对旧阶段的转换能力变化。

重要修正：

最初的原始公式使用 `grid_position - finish_position`。诊断后发现它有明显偏差：会惩罚“从前排发车并守住位置”的强车手，也会过度奖励后排车手上升到中游。

最终默认采用机会归一化公式：

```text
gain  = (grid - finish) / max(grid - 1, 1)       # 有超车时，除以可超车空间
loss  = (grid - finish) / max(22 - grid, 1)      # 掉位时，除以身后可丢位空间
zero  = 0                                       # 守住位置
```

这让 `race_execution` 的默认贡献非常保守，避免用一个噪声较大的历史位置转换指标破坏主模型。

### 2.3 Full-field replay 指标

修改文件：

- `src/f1predict/backtest.py`
- `src/f1predict/replay.py`
- `src/f1predict/replay_analysis.py`
- `src/f1predict/chronological_replay.py`

新增指标：

- `actual_winner_rank`：真实冠军在预测排序里的名次；
- `mean_abs_rank_error`：整场车手预测排名和真实完赛排名的平均绝对误差；
- `mean_abs_points_error`：每个车手 expected points 与真实积分的平均绝对误差；
- `podium_overlap_rate`：预测领奖台前三与真实前三的重合率；
- `points_overlap_rate`：预测积分区前十与真实前十的重合率。

这一步很关键：以后不能只用“猜没猜中冠军”评价模型。

## 3. British GP prediction run 影响

生成 artifact：

- run: `reports/prediction_runs/runs/british_gp/british_gp_20260630T120000_0000_20260705T100450_0000_0e7a405cb7.prediction_run.json`
- packet: `reports/prediction_packets_v2/british_gp/2026-07-05T10_04_41_00_00/british_gp/british_gp_20260630T120000_0000.prediction_packet.json`
- diff: `reports/prediction_diffs/british_gp/british_gp_20260630T120000_0000_8504e4465b1c.prediction_diff.json`

Matched diff：

- `input_changed`: `true`
- `evidence_changed`: `false`
- `probability_changed`: `true`
- `information_intake_changed`: `false`

解释：

本轮没有改变 Codex evidence，也没有改变 information intake。变化来自结构化 FastF1 特征和模型 ontology，因此 evidence 不变、输入和概率轻微变化是合理结果。

British GP 最大变化：

| 车手 | win_delta | expected_points_delta |
|---|---:|---:|
| verstappen | +0.0033 | +0.0283 |
| russell | -0.0017 | -0.0167 |
| norris | -0.0017 | -0.0117 |
| leclerc | +0.0000 | -0.0067 |
| gasly | +0.0000 | +0.0033 |

这不是一次大幅修正，而是一次保守接入新因子的改动。

## 4. Replay 结果

主 replay artifact：

- `reports/chronological_replay_v2_race_execution/2026_asof_20260701T000000_0000.chronological_replay.json`
- `reports/chronological_replay_v2_race_execution/2026_asof_20260701T000000_0000.chronological_replay.md`

诊断对照 artifact：

- `reports/chronological_replay_v2_without_race_execution/2026_asof_20260701T000000_0000.chronological_replay.json`
- `reports/chronological_replay_v2_without_race_execution/2026_asof_20260701T000000_0000.chronological_replay.md`

同一 cutoff、同一 iterations、同一数据下，对比结果：

| 指标 | 无 race_execution | 归一化 race_execution | 变化 |
|---|---:|---:|---:|
| top_pick_hit_rate | 0.5000 | 0.5000 | 0.0000 |
| mean_actual_winner_probability | 0.2917 | 0.2917 | 0.0000 |
| mean_winner_brier_score | 0.6940 | 0.6940 | 0.0000 |
| mean_actual_log_loss | 1.3485 | 1.3485 | 0.0000 |
| weighted_top_pick_calibration_gap | 0.1237 | 0.1242 | +0.0005 |
| mean_abs_rank_error | 5.2614 | 5.2614 | 0.0000 |
| mean_abs_points_error | 3.1963 | 3.1972 | +0.0009 |
| mean_podium_overlap_rate | 0.5417 | 0.5417 | 0.0000 |
| mean_points_overlap_rate | 0.6125 | 0.6125 | 0.0000 |

结论：

- `race_execution` 作为 ontology 和结构化特征管线是合理的；
- 当前仅靠历史 grid-to-finish 转换，预测收益几乎为零；
- 原始未归一化版本会伤害 winner calibration，因此没有保留；
- 归一化版本被保守保留，因为它不会明显破坏模型，并为后续接入更高质量的起步、缠斗、处罚、事故、交通处理信息留下清晰接口。

## 5. 验证

通过：

```text
.venv\Scripts\python.exe -m compileall src scripts
.venv\Scripts\python.exe scripts\smoke_test.py
```

smoke test 输出：

```text
smoke_test: ok
```

## 6. 实验完整性边界

本轮不是正式 ablation，也不是 edge 证明。

限制：

- 只有 8 场已完成比赛；
- `race_execution` 当前来自历史结果，不包含真实的逐圈缠斗、事故责任、处罚、交通和策略上下文；
- replay 仍缺少同一 cutoff 的完整市场快照；
- Codex evidence 中的部分 source snapshot 仍需替换为 cutoff 前可证明来源。

可支持的结论：

> 后端已经能显式表达 `race_execution` 这类正赛执行力因子，并且 replay 已经能评估整场排名/积分表现，而不是只看冠军。当前历史 grid-to-finish 特征的预测收益不显著，因此应保持低权重，并等待更高质量的 racecraft/incident/strategy 数据进入。

不能支持的结论：

> `race_execution` 当前已经显著提升预测精度。

## 7. 下一步建议

1. 优先接入同一 race weekend 的练习赛、排位赛、长距离 stint、sector/speed trap 数据。
2. 为 `race_execution` 增加更真实的数据来源：起步得失、超车/被超、处罚、事故责任、SC/VSC 策略窗口、队友 H2H。
3. 将 simulator calibration 的目标从冠军概率扩展为 winner + full-field rank/points 的联合目标。
4. 继续把每次预测变化通过 run/diff/replay/report 固化，避免“代码变了但不知道预测为什么变”。
