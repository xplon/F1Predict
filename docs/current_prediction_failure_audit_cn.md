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

2026-07-06 追加修正：

- `seed://codex/...` 这类 seed 场景包不是外部事实来源，不能再被当作正式预测依据；
- seed 场景包可以留在证据审计里，用来提示“这里曾经有一个待替换的开发假设”，但默认模型输入权重为 `0`；
- `BeliefState` 状态更新引擎会把 `seed_scenario_source` 的更新权限设为 `blocked`，因此它不会改变车队、车手、事件风险或模拟参数；
- 用户举例只能触发信息源和模型链路审计，不能被改写成 seed 场景包再进入预测。

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
reports/prediction_packets_v2/british_gp/2026-07-06T07_48_46_00_00/british_gp/british_gp_20260705T000000_0000.prediction_packet.json
```

注册 run：

```text
reports/prediction_runs/runs/british_gp/british_gp_20260705T000000_0000_20260706T074952_0000_841054625f.prediction_run.json
```

本次预测状态：

```text
belief_state_id = british_gp_b3b9b2e20a_e94bcafff3
state_update_count = 489
prediction_impact_trace_count = 23
isolated_prediction_impact_count = 12
status = diagnostic_only
blocker_codes = codex_evidence_quality_review_required, probability_calibration_diagnostic_only
```

按平均完赛名次排序的诊断结果：

```text
01 Antonelli
02 Russell
03 Hamilton
04 Leclerc
05 Norris
06 Piastri
07 Verstappen
08 Hadjar
09 Gasly
10 Lindblad
11 Lawson
12 Sainz
13 Colapinto
14 Albon
15 Bearman
16 Ocon
17 Bortoleto
18 Alonso
19 Hulkenberg
20 Stroll
21 Bottas
22 Perez
```

这比旧版本更合理的地方是：Aston Martin 和 Cadillac 已回到底部区间，Mercedes/Ferrari/McLaren/Red Bull 大致进入前部竞争区间。这里不能再笼统说“新的 seed 研究包让排名更合理”。更准确的说法是：

- 如果某个变化来自 FastF1、官方积分榜、同场排位、近几站结果、天气 API 或已归档 source log，它可以作为诊断级预测依据；
- 如果某个变化只来自 `seed://codex/...`，它只能作为开发链路测试，不能算有效预测进步；
- 本次修正后，`seed-british-*` 的模型输入权重为 `0`，并且不再产生状态更新账本行。

2026-07-06 07:49 UTC 追加修正后，新旧 run diff 显示：

```text
base_run = british_gp_20260705T000000_0000_20260706T072132_0000_66421177e6
candidate_run = british_gp_20260705T000000_0000_20260706T074952_0000_841054625f
probability_changed = True
changed_driver_count = 22
material_driver_change_count = 15
rank_change_count = 11
max_abs_win_delta = 0.038334
max_abs_expected_points_delta = 0.3858
```

这次变化不是因为用户说某个车队或车手应该更强/更弱，而是来自两条通用映射修正：

- FastF1 同场排位分类现在除了进入 `qualifying_pace`，还会产生 `race_execution` 特征，用于表达发车位置带来的清洁空气、交通位置和首段窗口影响；该特征每名车手都有，按排位名次统一计算，不按车手名或车队名特判；
- 模拟器的发车位置惩罚改为更强地读取 `track_feature_vector.track_position_value`，让赛道位置价值真正作用到正赛时间，而不是只在解释里出现。

这次修正后，Leclerc/Hamilton 的同队排位张力从异常审计里消失：Leclerc 由第 5 升到第 4，领奖台概率由 0.2275 升到 0.2483；Hamilton 仍第 3，说明同场 P2/P3 信息已经影响最终概率，但还不足以完全覆盖 Hamilton 的官方积分、近期结果和其他来源化输入。这个结果应被解释为“来源化映射有效但仍不充分”，不能解释为“已经证明模型正确”。

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
- 2026-07-06 07:49 UTC 修正后，同场排位 P2/P3 已经通过 `race_execution` 和赛道位置价值进入正赛模拟，Leclerc 的期望积分和领奖台概率上升，并且 Leclerc/Hamilton 不再被异常审计标为“同队排位顺序张力”；
- 当前 Hamilton 仍排在 Leclerc 前面，说明其他来源化输入仍然覆盖了同场排位优势。这个覆盖是否过强还没有被历史回放证明，仍是模型校准风险。

正确解释应该是：

```text
当前模型能说明哪些来源化输入推高/压低了两人状态，
但不能再说“某个内部 race score 高，所以预测合理”。
如果可追溯输入不足以证明队内差距，解释模块必须标记为模型校准风险。
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
- Hamilton/Leclerc 的队内差距已比上一版缓和，但仍需要用长距离、保胎、策略和近期状态做历史回放校准；
- Racing Bulls、Audi/Sauber、中游车队排序需要更多最近 3-5 站和同周末长距离信息支撑；
- Alpine/Williams 的负向来源化输入仍和中游预测位置存在张力；
- Alonso/Stroll 的同队顺序仍被异常审计标记，需要复核两人的正赛执行、队内策略和同周末数据；
- 单站 1200 次蒙特卡洛采样仍不足以支撑小概率尾部结论；
- 当前预测仍是 `diagnostic_only`，不具备稳定盈利 edge 的证明。

## 9. 已新增：预测异常审计进入预测包和前端

旧缺口：

模型曾经会为错误预测找解释，而不是主动指出“来源事实和最终排序之间有冲突”。这会导致两个问题：

- 用户指出单个例子后，系统容易只围绕这个例子解释，而没有检查同类问题；
- 解释层可能把“信息进入状态向量”误说成“这条信息已经证明改变了预测”。

当前新增：

```text
src/f1predict/prediction_anomaly.py
```

它不修改预测结果，只读取：

- 车手预测排名；
- 车手所属车队；
- `StateUpdateLedgerRow` 状态更新账本；
- `raw_sources`、`normalized_claims` 等来源链条；
- `PredictionImpactTrace` 同种子影响追踪。

然后用通用规则标记以下风险：

- 来源化状态整体偏弱，但车队仍被预测到中游前列；
- 来源化状态整体偏强，但车队仍被压到中后段；
- 近期窗口信号没有反映到最终排名；
- 同队排位/发车位来源和预测顺序存在明显张力；
- 大量状态更新只有 route-only 记录，还没有 isolated same-seed 因果对比。

最新离线审计能抓到的例子包括：

- Alonso/Stroll：同队排位顺序和预测顺序存在张力；
- Alpine/Williams：负向来源化输入与中游预测位置存在张力；
- isolated 影响追踪覆盖不足：489 条状态更新中只有 12 组单条 isolated 重跑，解释必须区分“已进入状态向量”和“已证明单条影响”。

上一版异常审计中的 Leclerc/Hamilton 与 Racing Bulls 条目已在 2026-07-06 07:49 UTC 新 run 中消失。这不能证明最终模型已经正确，但证明异常审计发现的问题已经至少有一部分通过通用映射修正反馈到了预测结果，而不是只停留在提示文本。

前端新增“预测异常审计”区块，默认展示中文摘要、风险原因、支持来源和从“原始来源 -> 信息分析 -> 状态更新 -> 预测变化”的链条。它不会展示内部裸分数，也不会按车队/车手手动改结果。

这项修正的意义：

```text
异常审计不是让预测变准的捷径，而是阻止系统继续为不合理预测辩护。
它把“哪里不合理、应该查哪类来源或映射”变成预测包的一部分。
```

仍需继续做：

- 把异常审计发现的问题反馈到来源获取、状态更新和模拟器校准，而不是停留在提示；
- 把更多 route-only 更新升级为 isolated same-seed diff；
- 针对每类异常建立历史回放统计，验证修正是否真的改善预测。

## 10. 已修正：前端默认读取已注册预测包

旧问题：

前端曾经在页面加载时调用旧版 `/api/prediction-packet`，导致页面打开就重新生成预测包。这会造成三个问题：

- 页面加载慢；
- 前端显示状态容易和已注册 run/artifact 不一致；
- 用户无法判断当前看到的是哪一次可审计预测。

当前修正：

- 新增只读接口 `GET /api/v2/prediction-packets/latest`；
- 新增只读接口 `GET /api/v2/prediction-runs/{run_id}/packet`；
- 前端 `loadPrediction()` 现在优先读取最新已注册 prediction packet，并在页面摘要中显示“已注册缓存”和 run id；
- 只有对应 event 没有已注册 packet 时，前端才退回旧版实时预测接口。

这解决的是前后端展示一致性和加载方式问题，不代表预测质量已经正式达标。

## 11. 下一步必须继续做的模型方向

优先级从高到低：

1. 实现每条状态更新的 isolated same-seed rerun，生成真正逐条 `PredictionImpactTrace`。
2. 把最近 3-5 站的车队积分、完赛顺位、排位、长距离速度、可靠性做成更明确的车队状态层。
3. 根据异常审计结果继续校准，但校准只能改通用来源映射或通用模拟机制，不能按车队/车手名手调：垫底车队被抬高中游、同队排位更好者预测明显更差、近期变强车队被压低、信息更新没有改变预测。
4. 继续降低无来源 seed prior 在单站预测中的影响，并要求 seed prior 逐步来源化。
5. 继续收敛前端：减少非核心审计面板，把默认视图聚焦到预测结果、关键状态、来源链路、影响记录和异常审计。
6. 用历史回放验证“结构化信息进入 BeliefState 后是否真的提高预测质量”，并严格标注诊断/正式比较的边界。
