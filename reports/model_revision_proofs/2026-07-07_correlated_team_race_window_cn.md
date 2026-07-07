# 2026-07-07 相关车队比赛日窗口模型修订证明

## 结论

本次修订不是因为用户指出某个车队或车手后手动改数值，而是修正一个通用模拟缺口：旧模拟器的大部分随机性是车手独立噪声，这会导致强队双车在同一场比赛里“总有一辆吃到胜利”，从而让双车合计胜率过度集中。

F1 中很多比赛日不确定性是车队/赛车层相关的，例如调校窗口、轮胎工作窗口、风向/温度适配、平衡问题。这类因素通常会同时影响同队两辆车。因此新增 `team_race_window_noise_sd`，按车队抽取相关比赛日窗口偏移，并用 `BeliefState` 中赛车、轮胎、调校和车手状态的不确定性调整幅度。

## 代码改动

- `src/f1predict/models/pace.py`
  - 新增 `PaceModel.race_window_uncertainty(driver)`。
  - 该函数读取 BeliefState 中的赛车 `race_pace`、`tyre_deg`、`setup_window_width`，车队 `setup_quality`，以及车手 `race_pace`、`tyre_management` 的不确定性。

- `src/f1predict/models/simulator.py`
  - 新增 `SimulatorConfig.team_race_window_noise_sd = 4.2`。
  - 新增 `team_race_window_uncertainty_scale = 0.85`。
  - 新增 `team_race_window_noise_cap = 8.5`。
  - 每次 race simulation 会为每个车队抽一个总比赛时间偏移，正值表示该队当天窗口偏慢，负值表示窗口偏快。
  - `simulation_replay` 现在带 `race_window_lap_delta` 和 `team_race_window_offset`，避免前端回放和概率模拟脱节。

- `src/f1predict/simulator_calibration.py`
  - 新增 `no_correlated_team_window` 候选，用于回归对照。
  - 新增 `stronger_team_window` 候选，用于后续过度自信诊断。

## 诊断对比

对比设置：

```text
event = british_gp
knowledge_cutoff = 2026-07-05T00:00:00+00:00
iterations = 1200
旧口径 = default_pace_separation_track_position_v2 / no_correlated_team_window
新口径 = default_pace_separation_track_position_team_window_v3
```

候选包：

```text
reports/prediction_packets_model_revision_probe/team_window_v3/british_gp/british_gp_20260705T000000_0000.prediction_packet.json
packet_payload_sha256 = 30cd0735df2efc78dbd7894d61268395fb868b37a588577f6c5d8602365d8d2e
status = diagnostic_only
```

关键变化：

| 项目 | 旧口径 | 新口径 | 变化 |
|---|---:|---:|---:|
| Russell 胜率 | 48.83% | 48.25% | -0.58pp |
| Antonelli 胜率 | 46.08% | 44.00% | -2.08pp |
| Mercedes 双车合计胜率 | 94.92% | 92.25% | -2.67pp |
| Hamilton 胜率 | 2.83% | 4.58% | +1.75pp |
| Verstappen 胜率 | 0.08% | 0.58% | +0.50pp |
| Piastri 胜率 | 0.25% | 0.58% | +0.33pp |

排名变化很小：

```text
Russell 仍第 1
Antonelli 仍第 2
Hamilton 仍第 3
Leclerc 仍第 4
Piastri / Norris 发生 P5/P6 近似交换
Gasly 从第 9 到第 10
Aston Martin 和 Cadillac 仍在底部区间
```

## 为什么这不是手调

这次改动没有读取用户对 Mercedes、Ferrari、Red Bull、Aston Martin、Cadillac、Racing Bulls、Audi、Leclerc、Hamilton、Alonso 等实体的主观判断，也没有在代码里写任何车队或车手 id 特判。

新机制只依赖：

```text
BeliefState 中已有状态不确定性
-> 每个车队统一抽样
-> 总比赛时间通用偏移
-> 同一队两辆车受到同方向影响
```

它修正的是模拟结构：从“车手独立噪声”补充为“车队相关比赛日窗口噪声”。

## 当前边界

这仍然只是模型修订诊断，不是正式 edge 证明：

- 候选包没有注册为 latest。
- 候选包尚未生成 535/535 full sidecar。
- 历史回放和概率校准仍是 `diagnostic_only`。
- 这次只能说明 top2 过度集中问题被通用机制小幅缓和，不能说明模型已能盈利。

下一步如果要把该候选升级为 latest，必须：

1. 生成或更新历史回放/校准诊断；
2. 通过 `PredictionRunRegistry` 的模型修订证明门禁；
3. 为新 run 生成完整同迭代 sidecar；
4. 确认前端/API 不会把未覆盖 sidecar 的候选包当作完整解释。
