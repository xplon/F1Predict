# 2026-07-07 关机前收尾总结

这份文档用于今晚暂停前交代当前项目状态。核心结论：F1Predict 已经从早期“分数堆叠 + 前端展示”推进到一个诊断闭环：来源化信息进入状态更新，状态更新进入模拟器，模拟器输出预测包，预测包可以被赛后复盘和影响链路追踪解释。但它仍然不是正式 edge 系统：当前预测仍是 `diagnostic_only`，没有完成正式概率校准，也没有证明稳定盈利能力。

## 1. 当前仓库和运行状态

- 仓库：`E:\1.study\code\AI_Projects\F1Predict`
- 分支：`master`
- 远端：`https://github.com/xplon/F1Predict.git`
- 本地前端：`http://127.0.0.1:8765/`
- 当前页面标题：`F1Predict MVP`
- 当前前端 latest 事件：`british_gp`
- 当前前端 latest 预测包状态：`diagnostic_only`
- 当前前端 latest 预测包生成时间：`2026-07-07T06:51:49+00:00`
- 当前前端 latest 预测知识截止：`2026-07-05T00:00:00+00:00`
- 当前前端 latest 模拟次数：`1200`

最近已经推送到 GitHub 的关键提交：

```text
3858855 Route session setup quality into team state
50b3e6e Route practice tyre degradation to team state
e34a6e5 Add shutdown handoff summary
0a6b0e5 Add source-weighted race window pressure candidate
c4bf2c8 Add probability concentration calibration review
42eb617 Clarify 2026 track map rule context
5965807 Add winner probability calibration probe
8223a34 Add British GP post-event review diagnostics
```

今晚收尾发现的一个重要事实：最新两项代码改动，`team tyre_deg` 和 `setup_quality` 路由，已经提交、推送并通过 smoke test 和 simulator calibration 诊断，但还没有重新生成并注册成新的前端 latest 预测包。因此当前前端展示的是已注册 latest run，不是这两项最新路由全部进入后的新排名。

## 2. 已完成的关键工作

### 2.1 用户反馈不能直接改预测

已经建立来源边界，`user://`、`user-feedback://`、`codex-feedback://`、`prompt://` 这类来源不能进入 `BeliefState`，也不能影响最终预测。用户反馈只允许触发审计、架构修正或数据源补充，不能成为模型证据。

这解决的是底线问题：不能因为你说“某队应该强/弱”就偷偷调数值。预测变化必须来自真实来源、结构化数据，或经过证明的通用模型修订。

### 2.2 可追溯解释链已经打通

British GP 当前 latest run 已有完整 sidecar：

```text
source_run_id = british_gp_20260705T000000_0000_20260707T065149_0000_d76ec2c3e4
sidecar_id = british_gp_e075659cf939_20260707T074125_0000_merged_ca50ec46ef
source_iterations = 1200
trace_iterations = 1200
claim_count = 535
covered_claim_count = 535
uncovered_claim_count = 0
formal_readiness.status = formal_trace_ready
```

这说明当前解释链可以追到：

```text
原始来源/结构化特征
-> 信息分析
-> BeliefState 状态更新
-> 模拟器路由
-> 预测结果变化
```

但这只证明“解释链完整”，不证明“预测准确”。

### 2.3 British GP 赛后复盘已经接入

当前赛后复盘结果：

```text
预测第一 = russell
实际冠军 = leclerc
冠军命中 = False
Leclerc 赛前预测排名 = P4
Leclerc 赛前胜率 = 0.0125
Russell 实际完赛 = P2
领奖台重合率 = 0.6667
积分区重合率 = 0.7
平均绝对排名误差 = 4.6364
```

这说明模型不是完全失真：Russell、Hamilton、Leclerc 都在前部，领奖台重合率也不是零。但失败点同样明确：Leclerc 的冠军概率被压得太低，Antonelli 的风险被明显低估，Mercedes 双车胜率过度集中。

### 2.4 winner probability calibration probe 做了，但没有注册

已经做过一个只基于通用排名/登台支持的 winner 概率平滑 probe。它不读取车手名或车队名，不写回 `BeliefState`，不改变 latest。

British GP 上它把 Leclerc 胜率从 `0.0125` 调到 `0.042145`，但历史回放诊断没有支持注册：

```text
baseline composite_score = 2.1852
winner_rank_podium_calibrated composite_score = 2.2968
status = diagnostic_probe_not_registered
```

结论：winner 概率层确实有问题，但这个候选不能当作正式修正。

### 2.5 相关车队比赛日窗口已注册到当前 latest

已经把模拟器从纯车手独立噪声扩展到“同队共享比赛日窗口噪声”。这反映调校窗口、轮胎窗口、气温适配等车队/赛车层面的相关风险。

当前前端 latest 使用的 simulator config：

```text
config_id = default_pace_separation_track_position_team_window_v3
team_race_window_noise_sd = 4.2
team_race_window_uncertainty_scale = 0.85
team_race_window_noise_cap = 8.5
```

这个修正已经通过模型修订证明注册为 latest diagnostic run，并且解释 sidecar 与该 run 同迭代匹配。

### 2.6 source-weighted race window pressure 候选实现了，但默认关闭

新增了一个通用候选：让来源化状态中的 `car.tyre_deg`、`team_ops.setup_quality`、`team_ops.strategy_quality`、`team_ops.race_execution`、`car.reliability` 影响比赛日窗口压力。

当前没有注册为 latest：

```text
team_race_window_pressure_scale = 0.0
```

原因是 replay/calibration 仍不支持它替换默认模型。最新一次 `setup_quality_v1` 诊断中：

```text
baseline score = 2.3549
source_weighted_team_window_pressure_strong score = 2.3820
source_weighted_team_window_pressure score = 2.3992
recommended = default_pace_separation_track_position_team_window_v3
```

结论：结构已经有了，但目前不能注册为前端 latest。

### 2.7 FastF1 轮胎衰退已经从车手层路由到车队层

之前 Practice long-run 里的 `tyre_deg` 只进入 `driver.tyre_management`。现在新增通用聚合：

```text
FastF1 practice long-run tyre degradation
-> driver.tyre_management
-> team/car tyre_deg
-> race_window_pressure 候选
```

真实 British GP 数据诊断结果：

```text
feature_count = 551
driver tyre_deg features = 16
team tyre_deg features = 10
car tyre updates = 10
```

这个改动已经提交推送，并通过 smoke test。它会影响下一次按当前代码生成的预测包，但当前前端 latest 尚未重新注册到这一版。

### 2.8 FastF1 练习/排位调校质量已经进入车队状态

新增 `setup_quality` 因子，来源包括：

```text
practice team long-run average -> long_run_setup_quality
qualifying team fastest average -> qualifying_setup_quality
```

它进入：

```text
team_ops.setup_quality
-> qualifying_grid_sampler
-> race_pace_score
-> race_window_pressure 候选
```

真实 British GP 数据诊断结果：

```text
feature_count = 571
team setup_quality features = 20
setup_quality ledger rows = 20
```

代表性 team state 方向：

```text
mercedes +0.025980
red_bull +0.024317
mclaren +0.015166
ferrari +0.005117
racing_bulls -0.005671
williams -0.011913
alpine -0.012366
aston_martin -0.016489
cadillac -0.027888
```

这也是通用来源化路由，不是按车队名手调。它已经提交推送并通过 smoke test，但当前前端 latest 尚未重新注册到这一版。

## 3. 当前 British GP 前端预测结果

当前前端 latest top 8：

| 排名 | 车手 | 胜率 | 登台率 | 期望积分 | 平均完赛 |
|---:|---|---:|---:|---:|---:|
| 1 | Russell | 48.25% | 90.58% | 19.942 | 2.618 |
| 2 | Antonelli | 44.00% | 90.33% | 19.575 | 2.769 |
| 3 | Hamilton | 4.58% | 54.92% | 13.212 | 4.367 |
| 4 | Leclerc | 1.25% | 23.67% | 10.348 | 5.741 |
| 5 | Piastri | 0.58% | 10.92% | 8.477 | 6.303 |
| 6 | Norris | 0.58% | 13.25% | 8.852 | 6.317 |
| 7 | Verstappen | 0.58% | 11.33% | 8.419 | 6.634 |
| 8 | Hadjar | 0.17% | 5.00% | 6.912 | 7.343 |

我的判断：

- 比早期版本更像一个真正的分布：强车队、前排、赛道/天气/状态链路都已经开始影响结果。
- 但仍然过度相信 Mercedes 双车争冠，尤其 Antonelli 风险明显不够。
- Leclerc/Ferrari 的冠军尾部概率仍偏低。
- 中游和尾部随机性还不自然，特别是退赛、黄旗、策略窗口对单场排名扰动还需要更强的结构化建模。
- 当前只能作为诊断 MVP 展示，不能作为正式投注 edge。

## 4. 当前前端展示效果

我用应用内浏览器检查了 `http://127.0.0.1:8765/`，观察结果：

- 页面能加载，标题为 `F1Predict MVP`。
- 控制台没有 error/warn。
- 页面没有 `unavailable`。
- British GP 赛道区显示 `official track map + replay overlay`。
- 页面有 `2026规则口径`，说明官方底图可能保留历史 DRS/测速点标注，但本项目不把它作为 2026 模拟输入。
- 分站预测区显示 `1,200 diagnostic sims | replay 312 rows`。
- `Simulation Replay` 已可见。
- 解释区显示 `formal_trace_ready`，来源化状态更新 `535 / 535` 覆盖。
- 页面仍显示 `diagnostic_only`，没有冒充正式 edge。

前端目前仍有问题：

- 内容仍然太多，Prediction、Trace、Replay、Market、Readiness 混在一起，重点不够集中。
- 赛后复盘已经有 API，但前端没有把它放到最显眼的位置。
- 页面加载仍偏慢，用户感知上像在重新计算；下一步需要更明确的静态包缓存和前端版本缓存策略。
- 当前前端 latest 没有体现 `team tyre_deg` 和 `setup_quality` 两个最新路由，因为还没有重新生成并注册新 prediction packet。
- 前端现在是“可用诊断看板”，还不是你想要的“中文第一性原理预测决策面板”。

## 5. 今晚收尾验证

已执行并通过：

```text
.venv\Scripts\python.exe -m compileall -q src scripts
node --check web\app.js
.venv\Scripts\python.exe scripts\source_driven_contract_test.py
.venv\Scripts\python.exe scripts\explainability_smoke_test.py
.venv\Scripts\python.exe scripts\prediction_anomaly_audit_smoke_test.py
.venv\Scripts\python.exe scripts\fastf1_team_tyre_deg_smoke_test.py
.venv\Scripts\python.exe scripts\fastf1_team_setup_quality_smoke_test.py
.venv\Scripts\python.exe scripts\race_window_pressure_smoke_test.py
git diff --check
```

已检查的 API/浏览器状态：

```text
GET /api/v2/prediction-packets/latest?event_id=british_gp
GET /api/v2/prediction-impact-traces/latest?event_id=british_gp&limit=1
GET /api/post-event-review?event_id=british_gp
应用内浏览器页面文本检查
应用内浏览器 console error/warn 检查
```

关键 API 结果：

```text
latest status = diagnostic_only
latest iterations = 1200
impact trace formal_readiness.status = formal_trace_ready
impact trace covered_claim_count = 535
impact trace uncovered_claim_count = 0
post_event predicted_winner = russell
post_event actual_winner = leclerc
post_event winner_hit = false
```

## 6. 不能冒充完成的事情

- 没有证明稳定盈利 edge。
- 没有完成正式概率校准。
- 没有完成 holdout/时间切分的正式 ablation。
- 没有把 winner probability calibration probe 注册为 latest。
- 没有把 source-weighted race window pressure 注册为 latest。
- 没有为最新 `team tyre_deg` 和 `setup_quality` 路由生成并注册新的前端 latest prediction packet。
- 没有为最新代码状态重新生成完整 535+ claim 的同迭代 sidecar。
- 没有把所有影响因素都做成足够强、足够可信的来源化状态输入。
- 没有完成最终中文前端信息架构。
- 没有彻底解决前端缓存和加载慢问题。
- 没有把赛后复盘做成最显眼的前端主模块。

## 7. 暂停后最应该先做什么

下一次恢复时，我建议先做一个“前端 latest 同步收口”，而不是继续扩功能：

1. 用当前代码重新生成 British GP prediction packet，写入新目录，不覆盖旧包。
2. 通过 registry 门禁判断能否注册。如果属于模型修订，必须引用模型修订证明；如果门禁不允许，就不要强行注册。
3. 如果注册成功，重新生成完整同迭代 impact trace sidecar。
4. 重新生成 post-event review。
5. 刷新前端，确认页面 top ranking、trace coverage、replay、post-event review 都指向同一个 run。
6. 再继续做前端瘦身和中文决策面板，把首屏集中到：预测排名、胜/登台/积分概率、最近几站状态、车队/赛车因素、车手因素、赛道/天气/策略风险、以及每个因素的来源到预测变化链路。

今晚可以暂停。当前项目最真实的状态是：诊断系统的骨架、证据边界、解释链、赛后复盘和基础前端都已经能跑；预测质量仍有明显问题；最新两项来源化路由已经进代码但没有进入前端 latest。下一轮优先把“最新代码 -> 注册预测包 -> 完整解释 sidecar -> 前端展示”这条链路收齐。
