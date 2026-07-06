# 当前预测失败审计与修正状态

生成日期：2026-07-06

这份文档记录 British GP 预测与可解释性模块的真实问题、已经完成的修正、仍未完成的缺口。它不是辩护文档，也不是正式盈利优势证明。当前所有结论仍是诊断级。

## 1. 不能按用户举例手调结果

用户指出 Mercedes、Ferrari、Red Bull、Aston Martin、Cadillac、Racing Bulls、Audi、Leclerc、Hamilton、Alonso 等例子时，含义是暴露模型错误，而不是给模型贴标签。

因此当前工程约束是：

- 不允许因为用户一句话直接修改某个车队或车手的预测结果；
- 不允许在预测更新代码里写 `if team == ...` 或 `if driver == ...` 这类实体特判来迎合预期；
- 所有预测变化必须来自可追溯来源，例如 FastF1、F1 official standings、同场排位、练习赛圈速、近期分站结果、质量审计后的 Codex 证据；
- 用户例子只能触发“检查信息链路/状态更新/模型权重是否合理”，不能成为模型输入。

新增验证脚本：

```text
scripts/source_driven_contract_test.py
```

它扫描预测更新核心文件，阻止车队/车手 id 级硬编码进入 `BeliefState`、`PaceModel`、`PredictionPipeline` 和模拟器。这个检查不能证明模型已经公平，但能阻止最危险的手动补丁路径。

## 2. 已修正：解释层不能再把内部裸分数当原因

旧问题：

解释模块曾经把内部正赛能力分拆成一串数值，例如车手基础能力、正赛攻防、保胎、湿地能力等，然后把这些数值当作原因。这是错误的，因为很多项目来自 `data/seed/demo_season.json` 的静态 seed prior，不是由本场新闻、排位、练习赛、近期分站成绩、车队升级或技术信息计算出来的事实。

当前修正：

- 面向人的解释不再展示无事实来源的内部权重数值；
- API JSON 和 Codex 追问上下文会移除 `score_breakdown`、原始权重、原始概率 delta 等内部字段；
- 弱 seed prior 只作为高不确定度初始状态，并在公开上下文中标成模型风险；
- 如果可追溯事实和预测方向冲突，解释模块必须直说这是模型校准问题。

验证：

```text
scripts/explainability_smoke_test.py
```

已检查公开解释、API 响应和 Codex prompt 中不暴露旧裸分数字段，并且必须包含 `BeliefState`、状态更新和预测影响记录。

## 3. 已新增：全流程可追溯链路的基础实现

当前已经新增并接入：

- `BeliefState`
- `StateUpdateLedgerRow`
- `PredictionImpactTrace`
- `unsupported_static_priors`
- `belief_state_id`
- `source_fingerprint`
- `update_fingerprint`

现在的解释主线变成：

```text
原始来源
-> 信息抽取单元
-> 标准化因子声明
-> 证据质量门控
-> 状态向量更新
-> PaceModel/Simulator 读取状态
-> 预测影响记录
-> 中文解释/API 公开上下文
```

这解决了旧系统最大的问题：解释不再从最终分数反推原因，而是从来源和状态更新正向追踪。

## 4. 当前 British GP 诊断预测状态

最新诊断预测包：

```text
reports/prediction_packets/british_gp/british_gp_20260705T000000_0000.prediction_packet.json
```

注册 run：

```text
reports/prediction_runs/runs/british_gp/british_gp_20260705T000000_0000_20260706T054134_0000_b3062a6f70.prediction_run.json
```

本次预测状态：

```text
belief_state_id = british_gp_7cc88d5b1b_dc9778fdc5
state_update_count = 471
prediction_impact_trace_count = 23
isolated_prediction_impact_count = 12
status = diagnostic_only
```

按平均完赛名次排序的诊断结果：

```text
01 Russell
02 Antonelli
03 Hamilton
04 Norris
05 Leclerc
06 Piastri
07 Verstappen
08 Hadjar
09 Gasly
10 Colapinto
11 Lindblad
12 Sainz
13 Lawson
14 Albon
15 Alonso
16 Ocon
17 Bearman
18 Stroll
19 Hulkenberg
20 Bortoleto
21 Bottas
22 Perez
```

这比旧版本更合理的地方是：Aston Martin 和 Cadillac 已回到底部区间，Mercedes/Ferrari/McLaren/Red Bull 大致进入前部竞争区间。这里的变化不是按用户例子手调，而是现有来源化结构化输入通过通用 `BeliefState` 机制重新进入模型。

示例来源：

- Aston Martin 被压低：FastF1 同场车队平均排位 P21.5、赛前每站积分 0.12 vs 全场 9.18、F1 官方车队积分榜 P10/1 分；
- Cadillac 被压低：FastF1 赛前每站积分 0.00 vs 全场 9.18、同场平均排位 P19、F1 官方车队积分榜 P11/0 分；
- Ferrari 被抬高：FastF1 赛前每站积分 22.00 vs 全场 9.18、同场平均排位 P2.5、F1 官方车队积分榜 P2/204 分；
- Leclerc 有同场排位 P2 的正向更新；Hamilton 有同场排位 P3、官方车手积分 P3/125 分、近 3 场平均积分较高等正向更新。

## 5. 部分完成：单条信息的 isolated 影响追踪

当前 `PredictionImpactTrace` 已经实现三类记录：

- 弱 seed 初始状态 vs 完整 BeliefState 的同种子整体前后对比；
- 影响最大的 12 条来源化信息的单条 isolated same-seed 重跑；
- 其他高影响状态更新进入哪个模型表面的路由记录。

新增 CLI 参数：

```text
--isolated-impact-limit N
```

本次 British GP 诊断包使用：

```text
--isolated-impact-limit 12
```

这使系统能对 top-N 信息严格回答：

```text
只移除这一条信息，其他输入、随机种子、模拟配置完全不变时，
每个车手的排名分布、期望积分、领奖台概率具体变化多少？
```

仍未完成的部分是：还没有对全部 571 条来源化信息都做 isolated rerun。原因不是架构不支持，而是全量运行会显著增加生成预测包的时间。当前实现必须在解释中明确区分：

- `isolated_same_seed_leave_one_information`：已经做了单条同种子重跑；
- `state_update_route`：只证明信息进入状态向量和模拟表面，不能当作单条因果实验。

## 6. Ham/Lec 问题的当前状态

旧问题：

系统曾经试图用一串内部分数解释 Hamilton 明显高于 Leclerc，这是不合格的。

当前状态：

- Ferrari 的车队级输入会同时作用于两名车手；
- Leclerc 的同场排位 P2 是明确正向输入；
- Hamilton 的官方车手积分、近 3 场平均积分、同场排位 P3 是正向输入；
- 当前差距仍可能偏大，需要继续检查车手级近期状态映射、练习赛长距离代理值、排位到正赛转换权重是否放大。

正确解释应该是：

```text
当前模型能说明哪些来源化输入推高/压低了两人状态，
但不能再说“某个内部 race score 高，所以预测合理”。
如果可追溯输入不足以证明这么大的队内差距，解释模块必须标记为模型校准风险。
```

## 7. Alonso/Aston Martin 问题的当前状态

旧问题：

Alonso 曾被放在“领奖台概率为 0 的车手”中的第一，这与 Aston Martin 的同场排位、赛季积分、近期速度信号冲突。

当前状态：

- Alonso 在最新诊断预测中为第 15；
- Stroll 为第 18；
- Aston Martin 不再被旧 seed prior 抬到中游前列；
- 如果用户继续问“为什么 Alonso 是零领奖台组第一”，解释模块会先纠正前提，而不是顺着旧错误解释。

这说明旧问题已有明显缓解，但仍需要历史回放验证，不能只凭一站诊断结果宣布完成。

## 8. 仍需改进：整体排名仍不是最终可信模型

当前结果仍有明显需要复核的地方：

- Russell 和 Antonelli 的领先幅度可能过大；
- Hamilton/Leclerc 的队内差距仍需校准；
- Racing Bulls、Audi/Sauber、中游车队排序需要更多最近 3-5 站和同周末长距离信息支撑；
- Gasly/Colapinto/Lindblad/Sainz 等中下游排序需要异常审计；
- 单站 1200 次蒙特卡洛采样仍不足以支撑小概率尾部结论；
- 当前预测仍是 `diagnostic_only`，不具备稳定盈利 edge 的证明。

## 9. 下一步必须继续做的模型方向

优先级从高到低：

1. 实现每条状态更新的 isolated same-seed rerun，生成真正逐条 `PredictionImpactTrace`。
2. 把最近 3-5 站的车队积分、完赛顺位、排位、长距离速度、可靠性做成更明确的车队状态层。
3. 增加异常审计：垫底车队被抬高中游、同队排位更好者预测明显更差、近期变强车队被压低、信息更新没有改变预测。
4. 继续降低无来源 seed prior 在单站预测中的影响，并要求 seed prior 逐步来源化。
5. 前端改为展示预测结果、关键状态、来源链路、影响记录和异常审计，不展示裸内部权重。
6. 用历史回放验证“结构化信息进入 BeliefState 后是否真的提高预测质量”，并严格标注诊断/正式比较的边界。
