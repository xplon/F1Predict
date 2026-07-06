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

2026-07-06 10:40 UTC 自我纠偏：

- 曾经短暂生成过一条 `british_gp_20260705T000000_0000_20260706T104209_0000_c4515f938f` 诊断 run，它来自一次“提高赛车权重、降低车手先验”的通用启发式试验；
- 这次试验不是针对某个车手或车队的实体特判，但也不是由新增外部来源、历史回放校准或已验证参数学习推出，因此不符合“预测变化必须来源驱动”的标准；
- 该 run 已从默认 registry 和未提交预测产物中撤回，不能作为最新前端预测，也不能被描述成“模型已经因为用户指出问题而修正了排名”；
- 后续如果要调整赛车/车手权重，必须通过来源化数据、历史 replay、同口径 diff、校准报告和影响追踪证明，而不是凭用户例子或直觉改常数。

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

2026-07-06 追加实现：impact trace sidecar 的分页行现在不仅给出 `impact_status`，还会公开一条中文链路：

```text
原始来源 -> 信息分析 -> 状态更新 -> 预测变化
```

这条链路从 sidecar 缓存中的 `trace_context` 生成，会尽量连接 `source_id`、`claim_id`、质量审计、状态更新账本和同种子隔离重跑结果。它的目标是回答“这条信息凭什么影响预测”，而不是再展示一串没有来源解释的内部分数。

## 4. 当前 British GP 诊断预测状态

最新诊断预测包：

```text
reports/prediction_packets_v2/british_gp/2026-07-06T09_27_47_00_00/british_gp/british_gp_20260705T000000_0000.prediction_packet.json
```

注册 run：

```text
reports/prediction_runs/runs/british_gp/british_gp_20260705T000000_0000_20260706T092941_0000_b4fa317c0b.prediction_run.json
```

本次预测状态：

```text
belief_state_id = british_gp_6b6cbfd62d_142a1a9878
state_update_count = 453
prediction_impact_trace_count = 27
isolated_prediction_impact_count = 12
isolated_source_group_impact_count = 4
impact_trace_covered_claim_count = 87
impact_trace_uncovered_claim_count = 366
status = diagnostic_only
blocker_codes = codex_evidence_quality_review_required, probability_calibration_diagnostic_only
```

按平均完赛名次排序的诊断结果：

```text
01 Russell
02 Antonelli
03 Hamilton
04 Leclerc
05 Norris
06 Piastri
07 Verstappen
08 Hadjar
09 Gasly
10 Lindblad
11 Lawson
12 Colapinto
13 Sainz
14 Albon
15 Bearman
16 Ocon
17 Hulkenberg
18 Bortoleto
19 Alonso
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

2026-07-06 08:20 UTC 追加修正后，新旧 run diff 显示：

```text
base_run = british_gp_20260705T000000_0000_20260706T074952_0000_841054625f
candidate_run = british_gp_20260705T000000_0000_20260706T082018_0000_fb34cfc5b2
probability_changed = True
changed_driver_count = 22
material_driver_change_count = 17
rank_change_count = 7
max_abs_win_delta = 0.013333
max_abs_expected_points_delta = 0.335
```

这次变化来自两个通用数据口径修正：

- 跨赛季 OpenF1 历史类比没有历史车队上下文时，不再生成当前车手 `race_pace/qualifying_pace` 特征。修正后本包中的跨赛季 OpenF1 pace 特征数量为 `0`，避免把 2024 年旧车表现错误投到 2026 年当前车队；
- 新增 FastF1 全场平均完赛顺位重估，共 11 条车队 `race_pace` 结构化特征。它补充积分只能区分前十的缺陷，让 Racing Bulls、Audi、Haas、Williams、Aston Martin、Cadillac 等中后场排序能读取“第 11 到第 20”的完整分类信息。

这次修正后，异常审计从上一版 4 个降到 2 个：Williams 的负向未反映、Alonso/Stroll 的同队顺序张力已经消失；剩余风险是 Alpine 仍被标记为模型复核项，以及 isolated 影响追踪仍未全量覆盖。

2026-07-06 09:08 UTC 追加修正后，预测排名基本没有被重新手调，主要变化是解释链路更可审计：

```text
run = british_gp_20260705T000000_0000_20260706T090822_0000_81e31b24ea
prediction_impact_trace_count = 27
isolated_prediction_impact_count = 12
isolated_source_group_impact_count = 4
anomaly_count = 2
```

这次不是因为用户说了某个车队应该强或弱而调整数值，而是新增了“来源组同种子隔离重跑”：例如把同一类 FastF1 排位、练习赛圈速或车队强度重估来源整体移除，再用相同随机种子重跑，查看预测分布如何变化。它用于证明“这一组来源整体是否真的改变预测”，不是用于把排名推向某个预设答案。

与 08:20 run 的 matched diff 显示：

```text
base_run = british_gp_20260705T000000_0000_20260706T082018_0000_fb34cfc5b2
candidate_run = british_gp_20260705T000000_0000_20260706T090822_0000_81e31b24ea
evidence_changed = False
information_intake_changed = False
changed_driver_count = 0
rank_change_count = 0
```

也就是说，09:08 这次主要是在补“如何证明来源影响预测”的审计链路，而不是改车手排序。

2026-07-06 09:29 UTC 追加修正后，最新注册包加入了 impact trace 覆盖率字段和每条 trace 的 `impact_status`：

```text
run = british_gp_20260705T000000_0000_20260706T092941_0000_b4fa317c0b
prediction_impact_trace_count = 27
impact_trace_claim_count = 453
impact_trace_covered_claim_count = 87
impact_trace_uncovered_claim_count = 366
```

排名仍然没有被按用户例子手调。这个包的作用是让前端和解释 API 能清楚区分：

- 已做单条 isolated 的信息；
- 已被来源组 isolated 覆盖的信息；
- 仍然只是 route-only 的状态更新；
- 同种子重跑后有实质变化、小变化，还是无明显变化。

示例来源：

- Aston Martin 被压低：FastF1 同场车队平均排位 P21.5、赛前每站积分 0.12 vs 全场 9.18、F1 官方车队积分榜 P10/1 分；
- Cadillac 被压低：FastF1 赛前每站积分 0.00 vs 全场 9.18、同场平均排位 P19、F1 官方车队积分榜 P11/0 分；
- Ferrari 被抬高：FastF1 赛前每站积分 22.00 vs 全场 9.18、同场平均排位 P2.5、F1 官方车队积分榜 P2/204 分；
- Leclerc 有同场排位 P2 的正向更新；Hamilton 有同场排位 P3、官方车手积分 P3/125 分、近 3 场平均积分较高等正向更新。

## 5. 部分完成：单条信息的 isolated 影响追踪

当前 `PredictionImpactTrace` 已经实现四类记录：

- 弱 seed 初始状态 vs 完整 BeliefState 的同种子整体前后对比；
- 影响最大的 12 条来源化信息的单条 isolated same-seed 重跑；
- 影响最大的 4 组同源来源的 source-group isolated same-seed 重跑；
- 其他高影响状态更新进入哪个模型表面的路由记录。

新增 CLI 参数：

```text
--isolated-impact-limit N
```

本次 British GP 诊断包使用：

```text
--isolated-impact-limit 12
--isolated-source-group-limit 4
```

这使系统能对 top-N 信息严格回答：

```text
只移除这一条信息，其他输入、随机种子、模拟配置完全不变时，
每个车手的排名分布、期望积分、领奖台概率具体变化多少？
```

新增全量运行模式：

```text
--isolated-impact-limit -1
```

该模式会对全部 453 条状态更新逐条做 same-seed isolated rerun。已新增验证：

```text
scripts/full_impact_trace_smoke_test.py
```

小迭代 smoke 证明该模式可以生成：

```text
isolated_same_seed_leave_one_information = 453
impact_trace_covered_claim_count = 453
impact_trace_uncovered_claim_count = 0
```

但默认最新前端包暂时不直接塞入 453 条全量 trace。原因是这会显著增大 packet JSON，重新制造前端加载慢的问题。当前默认注册包保留 top-N 单条 isolated 和 top-4 来源组 isolated，同时公开覆盖率字段；下一步应该把全量 trace 做成 sidecar/分页 API，让前端按需读取。

当前实现必须在解释中明确区分：

- `isolated_same_seed_leave_one_information`：已经做了单条同种子重跑；
- `isolated_same_seed_leave_source_group`：已经做了同一来源组整体移除的同种子重跑；
- `state_update_route`：只证明信息进入状态向量和模拟表面，不能当作单条因果实验；
- `impact_status`：说明同种子重跑后是有实质预测变化、小幅变化、无明显变化，还是仍待 isolated。

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

- Alonso 在最新诊断预测中为第 19；
- Stroll 为第 20；
- Aston Martin 不再被旧 seed prior 抬到中游前列；
- 如果用户继续问“为什么 Alonso 是零领奖台组第一”，解释模块会先纠正前提，而不是顺着旧错误解释。

这说明旧问题已有明显缓解，但仍需要历史回放验证，不能只凭一站诊断结果宣布完成。

## 8. 仍需改进：整体排名仍不是最终可信模型

当前结果仍有明显需要复核的地方：

- Russell 和 Antonelli 的领先幅度可能过大；
- Hamilton/Leclerc 的队内差距已比上一版缓和，但仍需要用长距离、保胎、策略和近期状态做历史回放校准；
- Racing Bulls、Audi/Sauber、中游车队排序已补入全场完赛顺位，但仍需要更多同周末长距离和可靠性信息支撑；
- Alpine 的负向同周末来源与 Gasly 第 9 的预测位置仍存在张力；不过 Alpine 的赛季/近期完赛顺位和积分并不差，因此这项应保留为模型复核风险，而不是手动压低排名；
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

历史离线 packet 中曾能抓到的例子包括：

- Alpine：旧审计把车手层和车队/赛车层信号混在一起聚合，曾把 Alpine 标成“负向来源没有反映”。当前审计器已经改为分开计算 team-only 信号与 driver-level 信号；在 team-only 弱负向且存在正向反证时，不再把它当作硬异常；
- 默认注册包 isolated 影响追踪覆盖不足：packet 内嵌 trace 仍只有 12 组单条 isolated 重跑和 4 组来源组 isolated 重跑；但已跟踪 sidecar 对同一个 b4fa run 覆盖 453/453 条状态更新，因此前端/API 不应再把“packet 内嵌 trace 少”说成“完整解释链缺失”。

2026-07-06 追加修正后，`GET /api/v2/prediction-packets/latest` 会在读取历史 packet 时用当前审计器重新计算 `prediction_anomaly_audit`，并把对应 run 的 sidecar 覆盖证据传入审计器。也就是说：

```text
历史 packet 文件本身保持不可变；
前端看到的 anomaly audit 来自 API 运行时刷新；
刷新只改变审计展示，不改变预测概率、排名、packet hash 或 run registry。
```

当前 API 可见状态：

```text
run = british_gp_20260705T000000_0000_20260706T092941_0000_b4fa317c0b
prediction_anomaly_audit_source = api_runtime_recomputed
impact_trace_source = sidecar
impact_trace_covered_claim_count = 453
impact_trace_uncovered_claim_count = 0
anomaly_count = 0
```

上一版异常审计中的 Leclerc/Hamilton 与 Racing Bulls 条目已在 2026-07-06 07:49 UTC 新 run 中消失；Williams 与 Alonso/Stroll 条目已在 2026-07-06 08:20 UTC 新 run 中消失。这不能证明最终模型已经正确，但证明异常审计发现的问题已经至少有一部分通过通用映射修正反馈到了预测结果，而不是只停留在提示文本。

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

1. 把全量 isolated same-seed rerun 从可运行模式升级为前端友好的 sidecar/分页 API，避免默认 packet 过大。
2. 把最近 3-5 站的车队积分、完赛顺位、排位、长距离速度、可靠性做成更明确的车队状态层。
3. 根据异常审计结果继续校准，但校准只能改通用来源映射或通用模拟机制，不能按车队/车手名手调：垫底车队被抬高中游、同队排位更好者预测明显更差、近期变强车队被压低、信息更新没有改变预测。
4. 继续降低无来源 seed prior 在单站预测中的影响，并要求 seed prior 逐步来源化。
5. 继续收敛前端：减少非核心审计面板，把默认视图聚焦到预测结果、关键状态、来源链路、影响记录和异常审计。
6. 用历史回放验证“结构化信息进入 BeliefState 后是否真的提高预测质量”，并严格标注诊断/正式比较的边界。
## 12. 2026-07-06 更新：全量影响追踪 sidecar 已接入，但不等于正式预测达标

针对“默认预测包只展示少量 trace，用户看不到每条信息是否真的改变预测”的问题，当前新增了缓存式 sidecar：

- `src/f1predict/impact_trace_sidecar.py`：生成、写入、分页读取完整 `PredictionImpactTrace`；
- `GET /api/v2/prediction-impact-traces/latest`：读取最新注册 run 的已缓存 sidecar，不触发重新预测；
- `GET /api/v2/prediction-runs/{run_id}/impact-traces`：读取指定 run 的 sidecar；
- `POST /api/v2/prediction-impact-traces`：按需生成 sidecar；
- `web/app.js`：前端会优先读取 sidecar；如果没有 sidecar，会明确显示“完整影响追踪缓存未生成”，不再把主包少量 trace 暗示成全量解释；
- `scripts/impact_trace_sidecar_smoke_test.py`：验证 sidecar API、分页、覆盖率和低迭代诊断标记。

重要边界：

1. sidecar 是解释缓存，不是新的预测结果。它不会注册新的 latest prediction run，也不会手动改变排名。
2. 如果 sidecar 的 `trace_generation.comparison_status` 是 `diagnostic_iteration_mismatch`，说明隔离重跑迭代数与源 run 不一致，只能用于链路诊断，不能作为正式“这条信息精确改变了多少概率”的证明。
3. 用户的例子仍然只能触发排查：代码层继续要求预测更新不能按车手/车队名写死，必须来自来源化数据、结构化特征和通用模拟机制。
4. 当前模型质量仍是 `diagnostic_only`：sidecar 解决的是“能否追溯每条信息的边际影响”，不是“预测已经稳定有 edge”。
5. 当前默认 latest 已确认仍是 `british_gp_20260705T000000_0000_20260706T092941_0000_b4fa317c0b`；由未验证启发式权重试验生成的 `c4515f938f` 不进入默认前端。
6. API/latest 会用当前审计器和对应 sidecar 重新计算前端可见的 `prediction_anomaly_audit`；这不是重新预测，也不会写 artifact。

当前已缓存 sidecar 对 b4fa run 的诊断覆盖为：

```text
state_update_count = 453
impact_trace_covered_claim_count = 453
impact_trace_uncovered_claim_count = 0
trace_generation.comparison_status = diagnostic_iteration_mismatch
formal_readiness.status = diagnostic_iterations_full_coverage
formal_readiness.formal_ready = false
```

这说明“每条状态更新都能被分页追踪”已经可用；但因为该 sidecar 的隔离重跑迭代数与源 run 不一致，它仍只能用于解释链路和方向审计，不能作为正式概率变化证明。

2026-07-06 追加守门：sidecar 和前端/API 现在会公开 `formal_readiness`。当前状态会显示“trace 已全覆盖，但仍是诊断迭代”，从而避免把 5 次迭代的快跑解释误说成 1200 次源 run 的正式同口径解释。

2026-07-06 追加执行能力：`PredictionPipeline`、sidecar API 和 CLI 已支持 `isolated_impact_offset`。这让正式同迭代 sidecar 可以分块生成，而不是一次性对 453 条来源更新全部跑 1200 次迭代。分块结果会被标记为 `chunk_mode`，在合并成全覆盖 sidecar 前不会被认定为正式解释。

下一步不再是“把 sidecar 做出来”，而是：

- 为最新 British GP run 生成同迭代数的正式 sidecar，或继续明确标注低迭代诊断 sidecar；
- 继续减少/替换 `seed://` 开发证据，让默认预测更多来自 FIA/F1 官方、FastF1、天气、赛道、可靠性、长距离和近期窗口数据；
- 用历史回放验证每类状态更新和每类权重修改是否真的改善预测，而不是只改善解释或迎合人工直觉。
