# 2026-07-07 收尾总结：来源重复计数门禁与当前前端状态

> 本文是今晚关机前的状态报告。它不是正式 edge 结论，也不是宣布预测模型已经修好。当前所有新结果仍是 `diagnostic_only`。

## 1. 今晚这段工作解决了什么

今晚主要处理的是一个通用建模问题：同一批历史比赛结果，会通过多个派生特征重复进入同一个状态因子。

例如同样来自历史成绩/近期成绩的信号，可能同时以这些路径进入 `car.race_pace`：

- official standings
- FastF1 recent form
- FastF1 season form
- FastF1 momentum
- team strength reestimate
- finish-position reestimate

这些来源不是假的，但它们高度相关。如果全部按独立证据叠加，模型会把“同一段结果历史”当成多条互相独立的事实，从而把某些车队的 race pace 推得过高或过低。

因此我在 `BeliefState` 增加了一个通用门禁：

```text
历史比赛结果派生信号
-> 判断是否属于同一 correlated result family
-> 对同一 target/factor 的同方向累计更新做 soft cap
-> 超过阈值后饱和降权
-> 在 StateUpdateLedger 写入 correlated_result_family_saturation
```

这不是根据你说“某车队强/弱”来调数值。规则不读取车队名、车手名，也没有写死 British GP 或 Leclerc/Russell。它只看来源类型、目标对象、状态因子和更新方向。

## 2. 实际代码改动

新增/修改内容：

- `src/f1predict/belief_state.py`
  - 新增 `CORRELATED_RESULT_FAMILY_SOFT_CAPS`；
  - 新增 `CORRELATED_RESULT_FAMILY_MIN_SCALE`；
  - 新增 `_feature_correlation_family()`；
  - 新增 `_apply_correlated_result_family_saturation()`；
  - 把饱和降权原因写进 `StateUpdateLedger.quality_reasons`；
  - 解释文本改为中文，避免可解释性模块继续出现英文机制说明。

- `scripts/correlated_result_saturation_smoke_test.py`
  - 构造一个合成赛季；
  - 连续输入多条高度相关的历史结果派生信号；
  - 验证同一 `car.race_pace` 不会被无限推高；
  - 同时验证同一比赛周末的 `fastf1-session-laps` 不会被误伤。

## 3. 生成了哪些诊断 artifact

### 3.1 只启用来源饱和门禁的 British GP 候选包

```text
path = reports/prediction_packets_correlated_result_saturation_probe/british_gp/british_gp_20260705T000000_0000.prediction_packet.json
status = diagnostic_only
hash = a9d428b910dc...
BeliefState = british_gp_ca70e1cb3b_f1572f3b3c
saturated_rows = 6
registered_latest = false
```

前 8 名冠军概率：

```text
Russell   38.00%
Antonelli 35.83%
Hamilton  11.17%
Norris     4.67%
Leclerc    3.83%
Piastri    2.50%
Verstappen 2.83%
Hadjar     1.17%
```

效果：相比当前前端 latest，Mercedes 双车概率明显下降，Ferrari/McLaren/Red Bull 尾部概率上升一些。但 Leclerc 仍然没有被合理推到更高位置，所以这只能说明“重复计数问题被缓解”，不能说明 British GP 预测已经修好。

### 3.2 来源饱和 + 更宽比赛方差的 British GP 候选包

```text
path = reports/prediction_packets_saturation_route_scale_probe/british_gp/british_gp_20260705T000000_0000.prediction_packet.json
status = diagnostic_only
hash = 62d1844711b7...
BeliefState = british_gp_ca70e1cb3b_f1572f3b3c
saturated_rows = 6
registered_latest = false
```

前 8 名冠军概率：

```text
Russell   27.83%
Antonelli 27.00%
Hamilton  15.67%
Norris     7.67%
Leclerc    6.17%
Piastri    5.00%
Verstappen 6.17%
Hadjar     4.50%
```

效果：概率分布更分散，Leclerc 概率进一步上升。但这个配置在历史回放评分中不优于当前默认配置，所以不能注册为最新模型。

## 4. 校准结果

校准报告：

```text
reports/simulator_calibration_correlated_result_saturation_v1/2026_asof_20260707T000000_0000.simulator_calibration.md
```

结果：

```text
默认配置 composite score = 2.2358
更宽方差配置 composite score = 2.3931

默认配置 top-pick hit rate = 66.67%
更宽方差配置 top-pick hit rate = 55.56%

默认配置 mean actual winner probability = 34.07%
更宽方差配置 mean actual winner probability = 27.78%

默认配置 log loss = 1.3951
更宽方差配置 log loss = 1.5271
```

结论：更宽方差候选虽然让单站概率看起来更合理，但历史回放整体更差。因此今晚没有把它注册到前端 latest。

## 5. 错误复盘结果

错误复盘报告：

```text
reports/model_error_review_correlated_result_saturation_v1/2026_asof_20260707T000000_0000.model_error_review.md
```

总览：

```text
reviewed_events = 9
missed_events = 3
top_pick_hit_rate = 66.67%
actual_winners_ranked_top3 = 8
mean_actual_winner_probability = 34.07%
belief_state_favored_top_pick = 3
```

British GP 仍然是明显失败样本：

```text
top_pick = Russell
actual_winner = Leclerc
actual_winner_rank = 6
top_pick_probability = 37.50%
actual_winner_probability = 2.08%
race_score_gap_top_minus_actual = +0.4038
feature/state gap top_minus_actual = +0.7530
```

这说明今晚的改动只是修正了一个通用重复计数问题，并没有彻底解决“为什么 Leclerc 被压得过低、为什么 Mercedes 仍过强”的核心预测问题。

## 6. 当前前端状态

我在浏览器中重新打开并刷新了：

```text
http://127.0.0.1:8765/
```

前端当前仍显示已注册 latest：

```text
packet_hash = d225707bdba8...
status = diagnostic_only
simulation count = 1,200
replay rows = 312
sidecar coverage = 565 / 565
formal trace readiness = formal_trace_ready
formal edge ready = no
```

页面刷新后最开始会短暂显示 `Loading prediction`，几秒后完成加载；浏览器控制台没有发现新的 error。

当前前端 British GP 排名仍是旧 latest：

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

这不是忘记更新前端，而是我有意没有把未通过校准的候选包注册成 latest。当前前端展示的是已注册的上一版诊断包，今晚的新候选包只保存在 `reports/` 中。

## 7. 验证命令

已通过：

```text
.venv\Scripts\python.exe -m compileall -q src scripts
.venv\Scripts\python.exe scripts\correlated_result_saturation_smoke_test.py
.venv\Scripts\python.exe scripts\source_driven_contract_test.py
.venv\Scripts\python.exe scripts\model_error_review_belief_state_smoke_test.py
```

收尾前还会再跑一次完整 smoke/test 集合，并提交推送。

## 8. 今晚结论

已完成：

- 找到一个真实、通用、非手调的预测偏差来源：历史结果派生信号重复计数；
- 实现了 BeliefState 层的来源族饱和门禁；
- 生成了两个 British GP 诊断候选包；
- 运行了历史校准和错误复盘；
- 明确证明候选配置不能直接注册到前端；
- 确认当前前端仍是旧 latest，解释覆盖完整，但预测质量仍是诊断级。

未完成：

- 还没有把 British GP 预测修到可信；
- 还没有证明当前模型具备 formal edge；
- 还没有完成你要求的完整“原始非结构化信息 -> 信息分析 -> 权重更新 -> 预测变化”全链路质量闭环；
- 前端加载速度仍需要优化缓存；
- 当前页面标题仍是 `F1Predict MVP`，前端还需要进一步中文化和收敛重点展示。

下一步最应该做的不是继续单站手修，而是：

```text
1. 对 race pace / qualifying / recent form / team strength route scale 做 matched ablation；
2. 把最近几站结果、同周末排位/练习赛、赛车升级和调校窗口统一进入 BeliefState；
3. 用历史回放决定哪些 route scale 能保留；
4. 只有在校准不变差、解释链完整、注册门禁通过时，才更新前端 latest。
```
