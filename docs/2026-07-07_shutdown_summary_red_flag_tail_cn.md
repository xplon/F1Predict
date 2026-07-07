# 2026-07-07 关机前收尾报告：事件风险尾部、前端状态和当前结论

> 本文是今晚准备停机前的状态报告。所有新模型候选仍是 `diagnostic_only`，没有被注册成正式 latest，也没有声明已经具备稳定 edge。

## 1. 本轮手头工作完成了什么

这轮没有继续扩大战线，只收束了一个正在做的建模缺口：安全车/红旗这类随机事件尾部必须能从来源化事件状态进入模拟器，而不是只停留在解释文本里。

已完成的通路是：

```text
原始来源或结构化事件信息
-> EvidenceClaim / FeatureAdjustment
-> BeliefState.event_risk_state
-> safety_car_probability / red_flag_probability
-> 模拟器事件采样
-> 策略窗口、车阵压缩、轮胎缓解、重启波动
-> sample_replay 可展示事件状态
```

这不是根据用户说“某队强/某人弱”来改数值。代码没有对 Mercedes、Ferrari、Leclerc、Russell、British GP 做实体特判。

## 2. 代码改动

新增/修改的核心文件：

- `src/f1predict/domain.py`：把 `safety_car_probability`、`red_flag_probability` 加入合法模型指标。
- `src/f1predict/belief_state.py`：事件风险因子能写入 StateUpdateLedger，并标注影响表面。
- `src/f1predict/intelligence/factor_trace.py`：新增安全车/红旗的模型路由。
- `src/f1predict/intelligence/factor_contract.py`：新增事件级安全车/红旗 claim 契约。
- `src/f1predict/models/pace.py`：新增事件风险概率读取方法；只有存在真正来源更新时才覆盖赛道派生概率。
- `src/f1predict/models/simulator.py`：新增红旗尾部诊断能力，默认关闭。
- `src/f1predict/simulator_calibration.py`：新增 `red_flag_tail` 和 `red_flag_tail_strong` 两个诊断候选。
- `scripts/red_flag_tail_smoke_test.py`：验证默认关闭、来源状态可改变概率、红旗可改变策略计划。

关键边界：

```text
SimulatorConfig.red_flag_probability_scale = 0.0
```

所以默认预测不会因为这次改动自动加入红旗尾部。只有显式选择诊断候选时才启用。

## 3. 诊断结果

本轮生成了低迭代诊断报告：

```text
reports/red_flag_tail_diagnostics_v1_focus/2026_asof_20260707T000000_0000.simulator_calibration.md
```

配置对比，60 次迭代，9 个 replay event：

```text
baseline composite_score = 2.2128
baseline top_pick_hit_rate = 66.7%
baseline mean_actual_log_loss = 1.4145

red_flag_tail composite_score = 2.1013
red_flag_tail top_pick_hit_rate = 44.4%
red_flag_tail mean_actual_log_loss = 1.3019

red_flag_tail_strong composite_score = 2.3974
red_flag_tail_strong top_pick_hit_rate = 22.2%
red_flag_tail_strong mean_actual_log_loss = 1.4698
```

解释：

- `red_flag_tail` 在 log loss 和综合分上有正向诊断信号；
- 但它的 top-pick 命中率明显变差；
- `red_flag_tail_strong` 整体更差；
- 因此它只能进入下一轮正式验证，不能今晚注册为默认模型。

## 4. 当前前端状态

我检查了应用内浏览器：

```text
URL = http://127.0.0.1:8765/
title = F1Predict MVP
console error/warn = 0
当前选择 = British Grand Prix
```

前端当前仍展示已注册 latest，不是今天新增的红旗诊断候选：

```text
status = diagnostic_only
simulation count = 1,200
replay rows = 312
sidecar coverage = 565 / 565
formal trace readiness = formal_trace_ready
formal edge ready = no
```

当前 British GP 排名仍是：

```text
P1 Russell   47.8%
P2 Antonelli 43.8%
P3 Hamilton   5.3%
P4 Leclerc    1.6%
P5 Piastri    0.6%
P6 Norris     0.3%
P7 Verstappen 0.6%
P8 Hadjar     0.1%
```

模拟回放现在是可用状态，不是 unavailable：

```text
Lap 1/52
leader Antonelli
Status green / safety_car
replay rows = 312
```

赛道区域显示：

```text
official track map + replay overlay
f1_official_circuit_map
verified_visual
Silverstone captured 2026-07-01 10:45:03
```

也就是说，前端能打开、没有控制台错误、英国站回放可用、银石显示官方底图。但前端仍然很重，页面内容很多，并且没有展示今天新做的红旗尾部诊断，因为该诊断没有注册为 latest。

## 5. 累计主线状态

到目前为止，项目已经具备这些主线能力：

- 预测 run 注册和缓存；
- PredictionRunRegistry / 影响 sidecar；
- 565 / 565 条来源化状态更新的完整影响追踪；
- 中文解释链；
- 单条来源隔离重跑；
- 预测异常审计；
- 赛道官方底图和回放叠加；
- BeliefState 路由级诊断；
- 历史结果派生信号的相关来源饱和门禁；
- 红旗尾部诊断能力。

但预测质量仍然没有达到目标：

- British GP 仍然明显偏 Mercedes 双车；
- Leclerc 仍被压低；
- 当前异常审计没有发现高优先级异常，只代表现有规则没抓到，不代表预测正确；
- 当前系统仍是诊断平台，不是可投注 edge 模型。

## 6. 本轮验证

已通过：

```text
python -m compileall src scripts
python scripts/red_flag_tail_smoke_test.py
python scripts/race_window_pressure_smoke_test.py
python scripts/source_driven_contract_test.py
python scripts/prediction_anomaly_audit_smoke_test.py
python scripts/explainability_smoke_test.py
```

已生成并读取：

```text
reports/red_flag_tail_diagnostics_v1_focus/2026_asof_20260707T000000_0000.simulator_calibration.md
```

## 7. 今晚停下点

今晚可以停在这里：

- 代码处于可验证节点；
- 新增能力默认不污染当前前端 latest；
- 红旗尾部有小样本诊断结果；
- 前端当前状态已经记录；
- 下一次继续时应该先做正式回放验证和前端展示收敛，而不是继续手动调某个车队或车手。

下一轮最合理的顺序：

1. 对 `red_flag_tail` 做更高迭代、更严格的 replay/calibration；
2. 把事件风险来源采集任务加入研究包；
3. 前端增加“候选诊断 vs 当前 latest”的明确切换，而不是只显示一个旧 latest；
4. 继续处理 British GP/Leclerc/Mercedes 偏差，但只能通过来源、状态更新、路由验证来改，不能手调。
