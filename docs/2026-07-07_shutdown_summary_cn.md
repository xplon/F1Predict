# 2026-07-07 关机前收尾总结

这份文档用于今晚暂停前交代当前状态。核心结论：项目已经从“随手分数 + 前端展示”推进到“来源化信息 -> 状态更新 -> 模拟器 -> 预测结果 -> 可追溯解释/赛后复盘”的诊断闭环，但还没有证明稳定盈利 edge，也没有完成正式概率校准。今晚最后没有继续开新模型大坑，只做了当前手头审计、前端状态复核和报告整理。

## 1. 当前仓库和运行状态

- 仓库：`E:\1.study\code\AI_Projects\F1Predict`
- 分支：`master`
- 远端：`https://github.com/xplon/F1Predict.git`
- 本地前端：`http://127.0.0.1:8765/`
- 当前浏览器页标题：`F1Predict MVP`
- 当前 latest British GP 预测状态：`diagnostic_only`
- 当前最新已推送提交：
  - `0a6b0e5 Add source-weighted race window pressure candidate`
  - `c4bf2c8 Add probability concentration calibration review`
  - `42eb617 Clarify 2026 track map rule context`
  - `5965807 Add winner probability calibration probe`

## 2. 今天/当前阶段真正做成的事情

### 2.1 用户反馈不再能直接改预测

你反复强调：你说“梅奔强、红牛弱、法拉利不该这么低、阿斯顿马丁应该垫底”等例子，是用来指出系统问题，不是让我把这些结论手动写死。现在系统里已经加了来源边界：

```text
user://
user-feedback://
codex-feedback://
prompt://
```

这类来源会被识别为用户反馈，`model_input_weight = 0`，不能更新 `BeliefState`，也不能进入最终预测。也就是说，预测变化只允许来自两类路径：

```text
真实来源/结构化数据 -> 质量审计 -> 状态更新 -> 模拟器 -> 预测变化
```

或：

```text
通用模型修订 -> replay/calibration/模型修订证明 -> registry 门禁 -> diagnostic latest
```

这解决的是项目底线问题：不能因为用户一句话偷偷调数值。

### 2.2 可追溯解释链已经打通

British GP latest run 已有完整 impact trace sidecar：

```text
formal_readiness.status = formal_trace_ready
covered_claim_count = 535
uncovered_claim_count = 0
trace_count = 546
```

这说明当前解释链可以追到：

```text
原始来源/结构化特征
-> 信息分析
-> BeliefState 状态更新
-> 模拟器路由
-> 预测结果变化
```

注意：这证明“解释链补齐了”，不证明“预测一定准确”。

### 2.3 British GP 赛后复盘已经接入

British GP 赛后复盘 API 当前可读。关键结果：

```text
预测第一 = Russell
实际冠军 = Leclerc
冠军命中 = False
Leclerc 赛前预测排名 = P4
Leclerc 赛前原始胜率 = 0.0125
领奖台重合率 = 0.6667
积分区重合率 = 0.7
```

这说明模型不是完全乱排：实际冠军 Leclerc 在预测 P4，实际领奖台里 Russell/Hamilton 也在预测前部。但失败点很明确：Leclerc 的冠军尾部概率被压得太低，Mercedes 尤其 Russell/Antonelli 的胜率过度集中。

### 2.4 winner probability calibration probe 做了，但没有注册

新增了一个胜率平滑诊断 probe：

```text
config_id = winner_rank_podium_calibrated_probe
status = diagnostic_probe_not_registered
```

它只读取通用输出：

```text
raw win probability
expected rank support
podium probability support
```

它不读取车手名、车队名，不写回 `BeliefState`，不改变 latest 注册预测。

British GP 赛后复盘里，这个 probe 对 Leclerc 的诊断效果是：

```text
Leclerc 原始胜率 = 0.0125
Leclerc probe 后胜率 = 0.042145
probe 后预测第一仍然 = Russell
```

但是小样本 simulator calibration 不支持把它注册为默认模型：

```text
baseline composite_score = 2.1852
winner_rank_podium_calibrated composite_score = 2.2968
```

结论：winner 概率层确实有问题，但这个候选还不能注册。

### 2.5 概率集中问题做了诊断，没有盲目改 latest

我测试了降低/调整同队比赛窗口相关性的候选。120 次迭代的快速诊断里，`no_correlated_team_window` 看起来更好：

```text
no_correlated_team_window score = 2.0658
baseline score = 2.1852
```

但 400 次复核里只是轻微改善综合分，同时 log loss 变差，并且 British Leclerc 实际冠军概率更差：

```text
no_correlated_team_window score = 2.2476
baseline score = 2.2539
```

结论：这条路线说明“概率集中值得继续查”，但不足以替换当前 latest。

### 2.6 2026 赛道图规则口径已经在前端说明

你指出赛道图不能靠筛掉不正确图来偷懒。现在前端仍优先使用官方赛道图资产，但补了 2026 规则口径说明：

```text
2026规则口径
官方底图可能保留 DRS/测速点等历史视觉标注；
本项目只把它作为赛道形状底图，
模拟输入来自赛道向量、直道/弯角/超车难度和来源化状态更新。
```

浏览器刷新后已经确认页面能看到这个说明。它解决的是“不要把官方图上的旧 DRS 标注当成 2026 模拟输入”，但还没有完成“所有赛道底图彻底重新清洗成完全无歧义视觉资产”。

### 2.7 source-weighted race window pressure 候选已实现，但默认关闭

新增了一个通用候选：用来源化的车队/赛车状态来形成比赛日窗口压力。它读取：

```text
car.tyre_deg
team_ops.setup_quality
team_ops.strategy_quality
team_ops.race_execution
car.reliability
```

含义是：如果来源显示某队轮胎窗口、调校窗口、执行或可靠性更差，就让该队双车共享一个更差的比赛日窗口压力。这个设计不是车队/车手特判。

但当前候选默认关闭：

```text
team_race_window_pressure_scale = 0.0
```

160 次迭代的小样本诊断里，强候选只有很小综合改善：

```text
source_weighted_team_window_pressure_strong score = 2.3886
baseline score = 2.4092
```

改善太小，而且 British Leclerc 概率仍很低，所以没有注册为 latest。

## 3. 刚完成的手头审计：为什么新 pressure 候选还没真正改变结果

今晚收尾前，我审计了 British GP latest packet 的特征和状态更新。

当前 prediction packet 里：

```text
feature_count = 541
ledger_count = 535
race_pace updates = 175
qualifying_ceiling updates = 131
race_execution updates = 107
tyre_management updates = 16
car.tyre_deg updates = 0
team_ops.setup_quality updates = 0
```

关键发现：

- 项目已经有 FastF1 Practice 1 的长距离和轮胎衰退特征。
- 当前 16 条 `tyre_deg` 特征进入了车手层面的 `driver.tyre_management`。
- 它们没有进入赛车/车队层面的 `car.tyre_deg`。
- `team_ops.setup_quality` 当前也没有来源化更新。
- 所以我新增的 `race_window_pressure()` 结构虽然存在，但 British latest 里能喂给它的方向性来源太弱。

这解释了一个重要现象：我不是靠你说的结论手调了预测；相反，当前 latest 预测没有明显变化，是因为新的 source-weighted pressure 候选没有足够强的来源化输入，也没有通过 calibration 门禁被注册。

下一步应该修的是通用数据路由：

```text
FastF1 practice long-run tyre degradation
-> driver.tyre_management
-> team/car tyre_deg 聚合
-> race_window_pressure
-> 模拟结果
-> replay/calibration 审查
```

而不是针对 Ferrari、Mercedes、Leclerc 或 Antonelli 写任何特判。

## 4. 当前 British GP 预测效果

当前 latest British GP 前部排序：

| 预测排名 | 车手 | 胜率 | 登台率 | 积分率 | 平均完赛 |
|---:|---|---:|---:|---:|---:|
| 1 | Russell | 0.4825 | 0.9058 | 0.9542 | 2.6175 |
| 2 | Antonelli | 0.4400 | 0.9033 | 0.9467 | 2.7692 |
| 3 | Hamilton | 0.0458 | 0.5492 | 0.9558 | 4.3675 |
| 4 | Leclerc | 0.0125 | 0.2367 | 0.9350 | 5.7408 |
| 5 | Piastri | 0.0058 | 0.1092 | 0.9575 | 6.3025 |
| 6 | Norris | 0.0058 | 0.1325 | 0.9408 | 6.3175 |
| 7 | Verstappen | 0.0058 | 0.1133 | 0.9325 | 6.6342 |
| 8 | Hadjar | 0.0017 | 0.0500 | 0.9283 | 7.3433 |

我的判断：

- 比早期“完全看不出车队强弱”的版本合理很多。
- 但仍然明显过度相信 Mercedes 双车争冠。
- Leclerc/Ferrari 的冠军尾部概率过低。
- 中前场概率区分和随机尾部还不够自然。
- 当前结果可以作为诊断 MVP 展示，不能作为正式 edge。

9 场 replay/calibration 当前结果：

```text
scored_events = 9
top_pick_hits = 6
top_pick_hit_rate = 0.6667
mean_top_pick_probability = 0.4708
mean_actual_winner_probability = 0.3562
mean_actual_log_loss = 1.4793
weighted_top_pick_calibration_gap = 0.1959
market_scored_events = 2
formal_probability_claim_ready = False
```

British GP 单站是当前最刺眼的失败案例：

```text
Top pick = Russell
Actual = Leclerc
Actual p = 0.0125
Log loss = 4.3820
```

## 5. 当前前端展示效果

我用当前打开的应用内浏览器检查了 `http://127.0.0.1:8765/`。

刷新前：

- 页面可显示 British GP、Simulation Replay、trace 信息。
- 控制台 0 error/warn。
- 但没有看到最新的 `2026规则口径` 文案，说明浏览器旧资产/旧页面状态会造成“前端看起来没更新”的错觉。

刷新后：

- 页面标题：`F1Predict MVP`
- 页面已显示 British Grand Prix。
- `Loading prediction` 在约 2.5 秒后消失。
- 页面没有 `Unavailable`。
- 控制台 0 error/warn。
- 页面显示 `2026规则口径`。
- 页面显示 `Simulation Replay/模拟回放`。
- 页面显示 `diagnostic_only`。
- 页面文本里能看到 Russell、Hamilton、Leclerc、Antonelli 等当前预测对象。

当前前端仍有问题：

- 页面内容仍然偏多，信息层级不够集中。
- 赛后复盘 API 是可用的，前端代码也有 `Post-event Review` 模块，但当前页面展开状态下它不够突出，不应该让用户自己找。
- Prediction、Trace、Replay、Market、Readiness 混在一起，中文化和重点筛选还没有达到你想要的“第一性原理影响因素展示”。
- 前端刷新前可能继续显示旧 JS/CSS 资产，需要更明确的版本缓存策略。
- 页面加载不是白屏，但首轮数据请求仍然偏慢，下一步应让前端读已生成缓存包，避免用户感觉每次都在重新计算。

所以今晚前端状态是：可用、能加载、没有运行时错误、能显示最新规则口径和预测，但还不是最终想要的中文决策看板。

## 6. 今晚执行过的验证

命令验证：

```text
node --check web\app.js
.venv\Scripts\python.exe scripts\source_driven_contract_test.py
.venv\Scripts\python.exe scripts\race_window_pressure_smoke_test.py
```

API/浏览器验证：

```text
GET /api/v2/prediction-packets/latest?event_id=british_gp
GET /api/post-event-review?event_id=british_gp
GET /api/v2/prediction-impact-traces/latest?event_id=british_gp&limit=1
浏览器 reload + 页面文本检查
浏览器 console error/warn 检查
```

关键 API 结果：

```text
latest status = diagnostic_only
prediction_anomaly_audit.status = no_major_anomaly_detected
post_event predicted_winner = russell
post_event actual_winner = leclerc
impact_trace formal_readiness.status = formal_trace_ready
```

## 7. 还没有完成，不能冒充完成的事情

- 没有证明稳定盈利 edge。
- 没有正式概率校准。
- 没有注册 winner probability calibration probe。
- 没有注册 source-weighted race window pressure candidate。
- 没有完成 holdout/时间切分的正式 ablation。
- 没有把所有影响因素都做成足够强的来源化状态输入。
- 没有完成最终中文前端信息架构。
- 没有彻底解决前端缓存/加载慢的问题。
- 没有把赛后复盘做成最显眼的前端主模块。

## 8. 暂停后下一步建议

下一轮最应该先做三件事：

1. 修通用数据路由，而不是修单个车队/车手。
   - 把 Practice long-run tyre degradation 从 `driver.tyre_management` 进一步聚合到 `car.tyre_deg`。
   - 用同周末练习、排位、长距离、维修区/策略来源形成 `team_ops.setup_quality` 和 `team_ops.race_execution`。
   - 每一步都必须能追到原始来源。

2. 重新跑 replay/calibration 决定是否注册。
   - 只有通用路由在同一套历史回放上改善综合指标，才允许进入 latest。
   - 如果只改善 British 或只让某个你提到的结论看起来对，不能注册。

3. 重做前端重点展示。
   - 首屏展示：当前预测排名、胜/登台/积分概率、关键来源化因素、最近几站趋势、车队/车手/赛道/天气/策略风险。
   - 每个因素都要能点开看到：原始来源 -> 信息分析 -> 权重更新 -> 预测变化。
   - 把 market/readiness/历史管理类内容移到次级诊断区。

今晚可以暂停。当前项目状态是：诊断 MVP 的证据边界、解释链、赛后复盘、前端基础展示都能跑；预测质量仍处于诊断和校准阶段，最重要的下一步是让来源化同周末信息真正进入车队/赛车层面的状态更新，并用 replay 证明它确实改善预测。
