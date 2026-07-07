# 2026-07-07 关机前收尾总结

这份文档用于今晚暂停前交代当前项目状态。核心结论先放前面：今天收尾完成的是“赛后复盘闭环、未注册胜率校准 probe、前端/API 可见状态复核、文档边界修正”，不是证明模型已经有稳定盈利 edge。当前 British GP 最新预测包仍是 `diagnostic_only`。

## 1. 当前仓库状态

- 仓库：`E:\1.study\code\AI_Projects\F1Predict`
- 分支：`master`
- 远端：`https://github.com/xplon/F1Predict.git`
- 当前本地服务：`http://127.0.0.1:8765/`
- 当前 latest 预测 run：`british_gp_20260705T000000_0000_20260707T065149_0000_d76ec2c3e4`
- 当前 latest prediction packet：`d76ec2c3e444fc48e648dc0208bf31a52b1c5158612b7cf81a386d1989e50478`
- 当前状态：`diagnostic_only`，不是正式 edge。

## 2. 到目前为止真正完成的工作

### 2.1 把用户反馈和预测证据彻底分开

你明确要求：你的例子只能暴露系统问题，不能被系统偷偷当成标签或强约束。现在代码里已经有边界：

```text
user://
user-feedback://
codex-feedback://
prompt://
```

这类来源会被识别为用户反馈，`model_input_weight = 0`，在 `BeliefState` 中被阻断，不能更新车队、车手、赛车或比赛风险状态。

因此，现在允许发生预测变化的路径只有两类：

```text
真实来源/结构化数据 -> 质量审计 -> 状态更新 -> 模拟器 -> 预测变化
```

或：

```text
通用模型修订 -> replay/calibration/模型修订证明 -> registry 门禁 -> diagnostic latest
```

这解决的是项目底线问题：不能因为你一句话把 Leclerc、Aston Martin、Racing Bulls 或任何实体手动调到看起来顺眼。

### 2.2 建立可追溯解释链

当前 British GP latest run 已有完整 sidecar：

```text
sidecar_id = british_gp_e075659cf939_20260707T074125_0000_merged_ca50ec46ef
source_iterations = 1200
trace_iterations = 1200
covered_claim_count = 535
uncovered_claim_count = 0
formal_readiness.status = formal_trace_ready
```

这表示 535 条来源化状态更新都可以追到：

```text
原始来源 -> 信息分析 -> 状态更新 -> 模拟路由 -> 预测变化
```

它证明“解释链补齐了”，不证明“预测已经准”。

### 2.3 注册门禁和模型修订证明

`PredictionRunRegistry` 现在会阻止无来源、无状态变化的预测概率变化直接成为 latest。模型修订可以注册，但必须带证明，并且仍然标记为 `diagnostic_only`。

已注册的通用模拟修订是 `team_race_window_noise`：它让同队两辆车共享一部分比赛日窗口波动，用来表达“同一队当天调校/轮胎窗口不对时双车一起受影响”。这不是按车队名或车手名手调。

### 2.4 新增 British GP 赛后复盘

已经摄取 British GP FastF1 正赛结果，并生成赛后复盘：

```text
reports/post_event_review/british_gp/british_gp_20260705T000000_0000.post_event_review.json
reports/post_event_review/british_gp/british_gp_20260705T000000_0000.post_event_review.md
```

关键结果：

```text
预测第一 = Russell
实际冠军 = Leclerc
冠军命中 = False
实际冠军赛前预计排名 = 4
Leclerc 赛前胜率 = 0.0125
预测第一 Russell 实际完赛 = P2
领奖台重合率 = 0.6667
积分区重合率 = 0.7
平均绝对排名误差 = 4.6364
```

这说明当前模型不是完全乱排：实际领奖台三人里 Russell/Hamilton 在预测前三，Leclerc 在预测第四。但它明显低估了 Leclerc 的冠军尾部概率，也高估了 Antonelli 的单场稳定性。

### 2.5 重跑 2026 已完赛 replay/calibration

British GP 加入评估后，9 场诊断指标是：

```text
scored_events = 9
top_pick_hits = 6
top_pick_hit_rate = 0.6667
median_actual_winner_rank = 1
mean_abs_rank_error = 4.3232
mean_podium_overlap_rate = 0.6667
mean_points_overlap_rate = 0.7222
mean_top_pick_probability = 0.4708
mean_actual_winner_probability = 0.3562
weighted_top_pick_calibration_gap = 0.1959
mean_actual_log_loss = 1.4793
```

这些数字只能叫诊断结果。样本小，市场数据不完整，没有 holdout，不能据此说有稳定 edge。

### 2.6 新增未注册 winner probability calibration probe

今晚新增了一个通用胜率平滑 probe：

```text
config_id = winner_rank_podium_calibrated_probe
status = diagnostic_probe_not_registered
```

它只读取模拟输出里的：

```text
raw win probability
expected rank support
podium probability support
```

它不读取车手名、车队名，不改变平均完赛、期望积分、领奖台概率或积分区概率。

在 British GP 赛后复盘里：

```text
Leclerc 原始胜率 = 0.0125
Leclerc probe 后胜率 = 0.042145
probe 后预测第一 = Russell
Russell probe 后胜率 = 0.423042
```

这个 probe 能缓和“P4 且有领奖台可能的车手胜率被压得过低”的问题，但不能注册成默认模型。

随后我做了目标候选小样本校准：

```text
output = reports/simulator_calibration_winner_probe/2026_asof_20260707T000000_0000.simulator_calibration.md
candidate = winner_rank_podium_calibrated
iterations_per_candidate = 120
events = 9
status = diagnostic_only
```

结果没有支持注册该候选：

| 配置 | 综合分 | 命中率 | 实际冠军均值概率 | Brier | Log loss | Top-pick 校准 gap |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 2.1852 | 55.6% | 35.6% | 0.6776 | 1.5396 | 0.0750 |
| winner_rank_podium_calibrated | 2.2968 | 55.6% | 30.6% | 0.6916 | 1.4457 | 0.1943 |

解释：候选让 log loss 略好，但实际冠军平均概率、Brier 和 top-pick 校准都变差，所以综合评分更差。当前正确结论是“winner 概率层值得继续研究”，不是“应该启用这个参数”。

## 3. 当前前端状态

本地前端已重启并验证：

```text
GET / -> 200
页面标题 = F1Predict MVP
British Grand Prix 可渲染
浏览器 console = 0 errors, 0 warnings
```

API 当前状态：

```text
GET /api/post-event-review?event_id=british_gp
winner_calibration_probe.status = diagnostic_probe_not_registered
winner_calibration_probe.actual_winner_raw_probability = 0.0125
winner_calibration_probe.actual_winner_calibrated_probability = 0.042145
```

```text
GET /api/v2/prediction-packets/latest?event_id=british_gp
prediction_anomaly_audit.status = no_major_anomaly_detected
prediction_anomaly_audit.anomaly_count = 0
impact_trace_claim_count = 535
impact_trace_covered_claim_count = 535
impact_trace_uncovered_claim_count = 0
```

```text
GET /api/v2/prediction-impact-traces/latest?event_id=british_gp&limit=1
formal_readiness.status = formal_trace_ready
trace_count = 546
returned_trace_count = 1
```

Playwright 轻量渲染检查已通过，截图在本地忽略目录：

```text
output/playwright/shutdown_frontend_20260707.png
```

我看到的展示效果：

- 首页能显示 British GP、赛道图、预测排名、中文列名和最新概率。
- Post-event Review 的 API 已经有 probe 数据，前端代码也会展示这一行。
- 不是白屏，控制台没有错误。
- 仍有前端残留问题：赛道图上仍有 `DRS DETECTION ZONE`、`SPEED TRAP` 等英文标注；如果按 2026 无 DRS 的规则口径，这些标注需要下一轮清洗或重新解释。
- 1280px 宽度下，`Verstappen` 这一行和概率列间距偏紧，需要 UI polish。

所以今晚不能说“前端完全完成”。只能说：可用、能展示最新数据、没有 JS/运行时错误，但仍需要视觉和语义清理。

## 4. 当前预测效果判断

我现在对模型效果的判断是：

- 全场结构比早期明显更合理：Mercedes/Ferrari/McLaren/Red Bull 在前部，Aston Martin/Cadillac 在底部区间。
- British GP 赛后看，前排结构部分合理：实际冠军 Leclerc 在预测 P4，Russell/Hamilton 与实际领奖台匹配。
- 最大问题仍然是概率分布：Leclerc 胜率 1.25% 过低，Antonelli 风险尾部不足，头部胜率过度集中。
- 当前解释链已经能说明“预测为什么这么来”，但不能证明“这么预测是对的”。
- 当前所有回放和校准仍是 diagnostic，不具备正式盈利 edge 证明。

## 5. 今晚执行过的验证

通过的命令：

```text
.venv\Scripts\python.exe -m compileall -q src scripts
node --check web\app.js
.venv\Scripts\python.exe scripts\winner_probability_calibration_smoke_test.py
.venv\Scripts\python.exe scripts\post_event_review_smoke_test.py
.venv\Scripts\python.exe scripts\source_driven_contract_test.py
.venv\Scripts\python.exe scripts\prediction_anomaly_audit_smoke_test.py
.venv\Scripts\python.exe scripts\explainability_smoke_test.py
git diff --check
```

浏览器/HTTP 验证：

```text
GET /
GET /api/post-event-review?event_id=british_gp
GET /api/v2/prediction-packets/latest?event_id=british_gp
GET /api/v2/prediction-impact-traces/latest?event_id=british_gp&limit=1
Playwright snapshot + screenshot
```

## 6. 还没有完成的事

这些不能在今晚冒充完成：

- 没有证明稳定 edge 或盈利能力。
- 没有完成正式概率校准。
- `winner_rank_podium_calibrated` 小样本综合评分不支持注册。
- 没有把 winner calibration probe 写入 latest prediction。
- 没有完成所有前端视觉/语义 polish。
- 没有解决 2026 规则口径下赛道图 DRS 标注的展示问题。
- 没有完成更大样本、holdout、市场基线完整对比。

## 7. 暂停后的下一步建议

下一步不要针对单个车手或车队手动修数值。优先顺序应该是：

1. 扩大 replay/calibration 样本，并加入 holdout 或时间切分。
2. 针对“冠军概率过度集中”做多候选校准，但只有综合指标和门禁通过才注册。
3. 补齐同周末 FP、排位、长距离、策略、轮胎衰退、退赛和安全车来源。
4. 检查哪些来源已经进入 `BeliefState` 但对预测几乎没有影响，修通用路由，不修实体特判。
5. 清理前端赛道图语义标注和表格响应式布局。

今晚可以暂停。当前项目状态是：证据边界、解释链、赛后复盘、前端/API 读数已经可用；预测质量仍处在诊断和校准阶段。
