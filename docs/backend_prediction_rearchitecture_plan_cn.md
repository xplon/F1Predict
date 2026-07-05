# 后端预测重构规划：按第一性原理建立 F1 分站排名预测模型

生成日期：2026-07-05

这份文档只讨论后端预测本身。目标不是继续给当前 MVP 打补丁，而是把你的预测理念重新组织成一个真正面向“整场比赛每个车手预计排名”的模型架构。

补充说明：关于“原始非结构化信息 -> 信息分析 -> 状态/权重更新 -> 预测结果改变”的全流程可追溯设计，见 `docs/traceable_prediction_update_architecture_cn.md`。这份补充文档定义了状态更新 ledger、BeliefState、PredictionImpactTrace 和前端解释口径。

## 1. 核心判断

当前实现已经有模拟器、Codex evidence、赛道图、天气、市场差异、回放报告，但它没有把 F1 排名的关键原因按第一性原理完整建模。它更像一个“可审计的诊断原型”，不是一个足够强的预测模型。

未来后端应该围绕一个中心问题重建：

```text
每个车手在某一站、某一 cutoff 下，为什么会以某个概率落在 P1/P2/.../DNF？
```

不是只预测冠军，而是输出完整 finishing distribution。

## 2. 预测目标

后端必须输出：

- 每位车手 P1-P20、DNF、DNS 的概率；
- 每位车手 expected finish；
- 每位车手 expected points；
- podium/top5/top10/points 概率；
- 队友比较概率；
- 车队双车积分概率；
- 最可能策略树；
- 关键风险事件；
- 每个预测结果的 factor contribution。

不再只围绕 winner probability 展示。

## 3. 总体架构

建议后端分成 8 层：

1. 原始数据层；
2. 赛道与环境建模层；
3. 车辆/动力单元/车队建模层；
4. 车手建模层；
5. Codex 新闻事实结构化层；
6. 赛前状态融合层；
7. 比赛模拟层；
8. 评估、归因和版本化层。

### 3.1 原始数据层

应该采集并版本化：

- FIA/F1 official classification；
- FastF1/OpenF1 timing；
- practice pace；
- qualifying/sprint；
- lap time distribution；
- stint data；
- tyre compound/stint degradation；
- race control；
- weather forecast；
- historical weather；
- circuit geometry；
- market odds；
- team/driver news；
- technical upgrade news；
- penalty/grid drop；
- parc ferme/setup/news。

每条数据必须有：

- source；
- captured_at；
- cutoff_status；
- event_id；
- confidence；
- raw_path；
- normalized_path；
- hash。

### 3.2 赛道与环境建模层

你指出的赛道信息应该成为一级输入，而不是前端装饰：

| 维度 | 应建模字段 | 用途 |
|---|---|---|
| 几何 | corner list, angle, radius, length, curvature | 判断低/中/高速弯、机械抓地、气动需求 |
| 直道 | straight length, deployment zones, braking zones | 判断 power/ERS/drag/overtaking |
| 超车 | corner-level overtake probability, track position value | 判断排位重要性和策略 aggressiveness |
| 轮胎 | asphalt roughness, lateral load, degradation profile | 判断 stint length 和 tyre offset |
| 进站 | pit lane loss, pit entry risk, pit exit traffic | 判断策略窗口 |
| 随机事件 | safety car/VSC/red flag historical rate | 判断免费进站窗口和压缩场差 |
| 天气 | air temp, track temp proxy, rain probability, wind | 判断 tyre warm-up、cooling、wet skill |
| 时间 | race local time, sun/night, temperature trend | 判断温度窗口 |
| 海拔 | elevation, air density proxy | 判断 power unit/aero/cooling |

当前有 OpenF1 circuit profile 的 corners/marshal sectors，也有 weather profile，但没有充分转成以上字段。后续必须做 `TrackFeatureVector`。

建议新增数据结构：

```python
TrackFeatureVector:
    event_id
    corner_count
    low_speed_corner_count
    medium_speed_corner_count
    high_speed_corner_count
    right_angle_corner_count
    long_straight_count
    max_straight_length_m
    total_full_throttle_distance_m
    deployment_zone_count
    braking_energy_index
    traction_index
    aero_efficiency_index
    mechanical_grip_index
    overtaking_index
    track_position_value
    pit_loss_seconds
    safety_car_probability
    red_flag_probability
    tyre_degradation_index
    tyre_warmup_index
    asphalt_roughness_index
    altitude_m
    air_temp_forecast_c
    track_temp_proxy_c
    rain_probability
```

### 3.3 车辆/动力单元/车队建模层

当前的 `base_strength` 太粗。应该拆成：

```python
CarPerformanceVector:
    team_id
    date_range
    overall_pace
    qualifying_pace
    race_pace
    race_execution
    high_speed_corner
    medium_speed_corner
    low_speed_corner
    traction
    mechanical_grip
    aero_efficiency
    drag
    straight_line_speed
    power_unit_peak
    power_unit_driveability
    ers_deployment
    ers_recovery
    clipping_risk
    cooling_margin
    tyre_deg
    tyre_warmup
    kerb_riding
    ride_height_sensitivity
    dirty_air_sensitivity
    understeer_tendency
    oversteer_tendency
    setup_window_width
    reliability
    upgrade_delta
    upgrade_confidence
```

车队能力也要拆出来：

```python
TeamOpsVector:
    strategy_quality
    pit_stop_mean
    pit_stop_variance
    pit_wall_risk
    development_rate
    upgrade_correlation
    setup_quality
    driver_priority_policy
    internal_conflict_risk
```

Codex 新闻应该主要进入这些字段，而不是直接改变胜率。例如：

- “Mercedes ERS 更强” -> `ers_deployment +`, `clipping_risk -`
- “Ferrari straight-line deficit” -> `straight_line_speed -`, `drag +`
- “Red Bull upgrade works” -> `upgrade_delta +`, `upgrade_confidence +`
- “car overweight” -> `mass_sensitivity penalty`, `tyre_deg +`, `acceleration -`

### 3.4 车手建模层

当前车手模型太粗。建议拆成：

```python
DriverPerformanceVector:
    driver_id
    qualifying_ceiling
    qualifying_consistency
    race_pace
    race_execution
    long_run_consistency
    tyre_management
    tyre_warmup
    wet_skill
    racecraft_attack
    racecraft_defense
    first_lap_gain
    incident_risk
    penalty_risk
    setup_feedback
    adaptability
    mental_pressure
    teammate_comparison
    team_priority
    car_fit_understeer
    car_fit_oversteer
    development_curve
```

车手和车的适配应该成为交互项：

```text
car understeer_tendency + driver understeer_preference -> fit bonus
car oversteer_tendency + driver oversteer_preference -> fit bonus
setup_window narrow + driver setup_feedback weak -> risk
tyre_warmup weak + cold track -> qualifying penalty
```

### 3.5 Codex 新闻事实结构化层

Codex 不应该直接输出“我觉得谁会赢”。它应该输出结构化 claim：

```json
{
  "claim_id": "...",
  "source": "...",
  "published_at": "...",
  "target": "mercedes",
  "factor": "ers_deployment",
  "direction": "positive",
  "magnitude": 0.08,
  "confidence": 0.75,
  "uncertainty": 0.2,
  "mechanism": "less clipping on long deployment zones",
  "track_context": ["long_straight", "high_ers_demand"],
  "valid_until": "...",
  "evidence_quality": "..."
}
```

同时需要把你列出的因素做成 `FactorOntology`：

- track；
- weather；
- car；
- power unit；
- ERS；
- aero；
- chassis；
- tyre；
- driver；
- team operations；
- strategy；
- random event；
- market；
- regulation/penalty。

所有新闻都必须归入这些 ontology，不允许落成“泛泛 optimism”。

### 3.6 赛前状态融合层

每站比赛预测不应该只用 season base strength。需要按 cutoff 分阶段：

| 阶段 | 可用信息 | 模型行为 |
|---|---|---|
| T-14 天 | 历史强度、赛道适配、升级新闻、天气气候 | broad prior |
| T-7 天 | 具体新闻、天气趋势、车队升级包 | update prior |
| FP 后 | 练习长距离、单圈、stint、速度陷阱 | large update |
| Qualifying 后 | 发车位、轮胎、罚退 | very large update |
| Race morning | 天气、pit lane、策略、可靠性 | final update |

当前系统没有清晰区分这些阶段，导致赛季态势和单站新信息融合得不够自然。

### 3.7 比赛模拟层

模拟器应该从“排名采样”升级为“事件驱动的 race simulation”：

1. 采样排位/发车顺序；
2. 采样起步和第一圈；
3. 按 stint 模拟 lap time distribution；
4. 模拟 tyre degradation；
5. 模拟 traffic/dirty air；
6. 模拟 overtaking attempts；
7. 模拟 VSC/SC/red flag；
8. 模拟 pit windows；
9. 模拟 team strategy decisions；
10. 模拟 reliability/DNF；
11. 输出完整 finish distribution。

随机事件不能只是“有没有安全车”。应该输出：

```python
RaceScenario:
    wet_phases
    safety_car_windows
    vsc_windows
    red_flag
    first_lap_incidents
    pit_error_events
    tyre_failure_events
    penalties
```

### 3.8 评估和版本化层

每次改动必须有：

- 结构化公开数据 baseline；
- current model；
- Codex 信息摄取版本；
- technical-factor-only；
- same seed；
- same events；
- same cutoff；
- same metrics。

指标：

- finishing rank MAE；
- winner Brier；
- top3 Brier；
- log loss；
- actual winner probability；
- teammate H2H accuracy；
- points probability calibration；
- market CLV 仅在同时间市场完整时使用。

没有这个层，就不能再说“模型变好了”。

## 4. 对你列出的因素逐项映射

| 你提出的因素 | 当前覆盖 | 后续计划 |
|---|---|---|
| 矢量地图/弯角 | 部分有 OpenF1 corners，但没充分建模 | 建 TrackFeatureVector |
| 低/中/高速弯 | 现在只有粗 geometry metrics | 用曲率/半径/速度 proxy 分类 |
| 长直道/短直道 | 基本缺失 | 从 track polyline/candidate lap 推导 |
| 26 赛季替代 DRS/部署区 | 缺失 | 建 deployment zone/energy zone |
| 超车可能性 | 粗略缺失 | corner/straight-level overtake index |
| 沥青/赛道温度 | 缺失或气候 proxy | weather + historical tyre deg |
| 历史气温/天气预报 | 有原始 weather profile，弱使用 | 转为 temp/rain/track temp feature |
| 黄旗/免费进站 | 有 safety car proxy，不够细 | VSC/SC window model |
| 红旗 | 缺失 | event risk model |
| 退赛 | 有 reliability proxy | 拆机械/事故/处罚 |
| 动力单元/大小涡轮 | 只有 power_unit 粗指标 | PU profile |
| ERS | 有 energy_recovery | 增加 deployment/recovery/clipping |
| 底盘/机械抓地 | 缺失或 low_speed proxy | chassis vector |
| 气动 | 有 drag_efficiency 粗指标 | aero map |
| 推头甩尾 | 缺失 | car balance + driver fit |
| 升级情况 | 有 upgrade_effect | 增加 upgrade validity/confidence/decay |
| 高低温/海拔 | 海拔有部分，温度弱 | temp/altitude interaction |
| 车手极限 | 有 qualifying/base_skill | 拆 ceiling/consistency |
| 车手适配赛车 | 缺失 | driver-car fit |
| 保胎/缠斗/长距离 | 有粗字段 | 拆成多维指标 |
| 一号车手/队内关系 | 缺失 | team priority/internal conflict |
| 车队决策 | 有 strategy 粗字段 | team ops vector |
| 换胎实力 | 缺失 | pit stop distribution |
| 主场/工厂距离 | 缺失 | optional contextual prior |
| 街道赛 vs 传统赛道 | 有 track_type | 加 overtaking/safety car/track position |

## 5. 实施优先级

### P0：先做可证明预测影响的基础设施

- prediction run registry；
- before/after probability diff；
- 结构化公开数据 baseline；
- same-seed matched replay；
- prediction artifact hash；
- frontend 显示当前 run id。

### P1：重建赛道和环境特征

- TrackFeatureVector；
- circuit geometry parser；
- weather/track temp feature；
- overtaking index；
- pit loss/safety car/red flag profile。

### P2：重建车辆/车手/车队 ontology

- CarPerformanceVector；
- DriverPerformanceVector；
- TeamOpsVector；
- Codex claim mapping；
- factor confidence and decay。

### P3：重写模拟器输出

- 完整 P1-P20 distribution；
- event-driven race scenario；
- strategy tree；
- uncertainty decomposition；
- factor contribution。

### P4：重新做前端

前端只展示会影响预测的核心因素，不展示大量内部审计流水账。

## 6. 验收标准

新的后端规划不能以“功能存在”为验收，要以“预测解释和结果变化可证明”为验收：

- 每个 event 有完整 TrackFeatureVector；
- 每个 driver/team 有状态向量；
- 每条 Codex 新闻都归入 ontology；
- 每次预测保存 artifact；
- 前端能看到本次预测相比上次变化；
- 至少跑结构化公开数据 baseline 与 Codex 信息摄取版本的 matched comparison；
- 至少 20 场 replay 后再评估 calibration；
- 不再把没有提升证据的工作称为预测改进。
