# 当前预测失败审计与修正状态

生成日期：2026-07-06

这份文档记录 British GP 预测与可解释性模块的真实问题、已经完成的修正、仍未完成的缺口。它不是辩护文档，也不是正式盈利优势证明。当前所有结论仍是诊断级。

## 0. 2026-07-06 14:42 UTC 追加：FastF1 `Lapped` 状态语义修正

这次新生成并注册的预测包不是因为用户说了“某个车队应该更强/更弱”而手动调整数值。用户的反馈只被用作异常审计信号：系统必须去检查信息源、映射逻辑和预测链路哪里错了，不能把用户的一句话当作训练标签或人工强约束。

本次实际改动来源是同一批 FastF1 正赛结果数据的语义映射修正：

```text
FastF1/F1 result Status = Lapped
含义：已分类完赛但被套圈
旧逻辑误判：non-finished / DNF
新逻辑：finished/classified
```

旧逻辑只把 `Finished` 和部分 `+1 Lap` 形式识别为完赛，没有把 `Lapped` 识别为分类完赛。这会把大量“被套圈但完赛”的车手错误计入可靠性惩罚，并污染 grid-to-finish conversion 等基于完赛车手的结构化特征。例如 British GP cutoff 前，Bortoleto 的赛季可靠性解释从旧逻辑的：

```text
6 non-finished classification(s) across 8 cutoff-valid FastF1 result(s)
```

修正为：

```text
1 non-finished classification(s) across 8 cutoff-valid FastF1 result(s)
```

因此，这次变化属于“模型/数据映射语义修正”，不是“新增外部来源驱动”，更不是“按用户观点调参”。对应证明文件是：

```text
reports/model_revision_proofs/2026-07-06_fastf1_lapped_status_reliability_cn.md
```

注册门禁复核结果也按这个原则分类：

```text
不带模型修订证明：
status = model_only_prediction_change_blocked
allow_registration = false
source_identity_changed = false
blocker_codes = non_source_driven_prediction_change, state_mapping_revision_proof_required

带模型修订证明：
status = model_revision_proof_allowed
allow_registration = true
warning_codes = model_revision_not_source_state_change
source_identity_changed = false
```

也就是说，同一批原始来源因为解释规则改变而影响预测时，系统不能把它说成“新增来源导致预测改变”；必须明确登记为有证明的模型/映射修订。

最新诊断 run：

```text
run_id = british_gp_20260705T000000_0000_20260706T142235_0000_ab901d489d
packet = reports/prediction_packets/british_gp/british_gp_20260705T000000_0000.prediction_packet.json
state_update_count = 456
status = diagnostic_only
blocker_codes = probability_calibration_diagnostic_only
```

对应完整影响追踪 sidecar 已生成，覆盖全部来源化更新：

```text
sidecar_id = british_gp_british_gp_20260705T000000_0000_2026_b9e5e9b73c4a_20260706T144238_0000_4764d14662
trace_iterations = 1200
impact_trace_claim_count = 456
impact_trace_covered_claim_count = 456
impact_trace_uncovered_claim_count = 0
formal_status = formal_trace_ready
```

本次后续还加固了注册门禁：同一原始来源产生的特征行数量变化，不再被误判为“新来源身份变化”。这避免了“同一份数据被重新解析后，系统却声称来源变了”的错误，也直接防止把用户反馈包装成来源驱动预测变化。

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

2026-07-06 11:35 UTC 追加硬约束：

- 新增 `PredictionRunRegistry.assess_registration_gate()`，在候选 prediction packet 注册前比较最新 run 与候选 run；
- 如果正赛概率/排名发生变化，但 `evidence_fingerprint` 和 `BeliefState.update_fingerprint` 都没有变化，默认判定为 `model_only_prediction_change_blocked`，不能注册成 latest；
- API `POST /api/v2/prediction-runs`、CLI `prediction-packet --register-run` 和 `register-prediction-run` 都已接入这个注册门；
- 如果确实要注册模型修订型 run，必须显式传入模型修订证明文件。这样可以保留历史回放校准、参数学习等正当模型迭代路径，但不会把“没有新增来源或状态更新的概率变化”伪装成来源驱动预测改进；
- `scripts/source_driven_contract_test.py` 现在不仅扫描实体级硬编码，还会构造一个“来源和 BeliefState 没变但正赛概率改变”的候选包，验证它会被注册门拦下。

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
-> 模拟路由
-> PaceModel/Simulator 读取状态
-> 预测影响记录
-> 中文解释/API 公开上下文
```

这解决了旧系统最大的问题：解释不再从最终分数反推原因，而是从来源和状态更新正向追踪。

2026-07-06 追加实现：impact trace sidecar 的分页行现在不仅给出 `impact_status`，还会公开一条中文链路：

```text
原始来源 -> 信息分析 -> 状态更新 -> 模拟路由 -> 预测变化
```

这条链路从 sidecar 缓存中的 `trace_context` 生成，会尽量连接 `source_id`、`claim_id`、质量审计、状态更新账本和同种子隔离重跑结果。它的目标是回答“这条信息凭什么影响预测”，而不是再展示一串没有来源解释的内部分数。

2026-07-06 追加实现：公开 trace 链条现在增加了“模拟路由”阶段。该阶段优先读取 `factor_trace` 的 route/model surface；如果是结构化 FastF1 特征且没有单独 factor trace，则读取状态更新账本中的 `affected_model_surfaces`。这样前端不再从“状态更新”直接跳到“预测变化”，而是会说明该状态进入了 `race_pace_score`、`qualifying_grid_sampler`、`reliability` 等哪个模拟器表面。该改动只增强解释链路，不改变任何预测数值。

## 4. 当前 British GP 诊断预测状态

最新诊断预测包：

```text
reports/prediction_packets_v2/british_gp/2026-07-06T11_58_49_00_00/british_gp/british_gp_20260705T000000_0000.prediction_packet.json
```

注册 run：

```text
reports/prediction_runs/runs/british_gp/british_gp_20260705T000000_0000_20260706T115913_0000_31f3f052bf.prediction_run.json
```

本次预测状态：

```text
belief_state_id = british_gp_6b6cbfd62d_142a1a9878
public_evidence_count = 1
blocked_development_seed_evidence_count = 5
state_update_count = 453
embedded_prediction_impact_trace_count = 11
embedded_isolated_prediction_impact_count = 0
sidecar_id_previous_diagnostic = british_gp_british_gp_20260705T000000_0000_2026_e33fbbd4ba1b_20260706T120008_0000_5228c60b4e
sidecar_id_latest_formal = british_gp_british_gp_20260705T000000_0000_2026_e33fbbd4ba1b_20260706T123600_0000_057974e605
sidecar_trace_iterations = 1200
sidecar_impact_trace_covered_claim_count = 453
sidecar_impact_trace_uncovered_claim_count = 0
sidecar_formal_status = formal_trace_ready
sidecar_formal_ready = true
status = diagnostic_only
blocker_codes = probability_calibration_diagnostic_only
warning_codes = codex_claims_require_review, blocked_development_seed_evidence_separated
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
- 本次修正后，`seed-british-*` 不再出现在默认公开 `evidence`、`evidence_quality`、`factor_trace` 或 `belief_state.raw_sources` 中；它们只保留在 `blocked_development_evidence` 审计区，且不能解释为预测变化来源；
- 注册门记录本次新包为 `no_race_prediction_change`：排名和正赛概率没有改变，变化只是清理公开来源口径。

换句话说，用户说“某队明显不合理”只能作为异常报告，不能作为标签或数值来源。允许发生预测变化的原因只有两类：第一，新增或修正了可追溯来源，并且该来源进入 `RawSourceRecord -> normalized_claim -> quality_profile -> state_update_ledger -> simulation`；第二，做了通用模型修订，并且有历史回放、校准报告或明确的模型修订证明。任何“因为用户一句话所以把某个车手/车队数值调高或调低”的改动，都应被 registration gate 和人工审计视为无效。

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
- Alpine 的车队/赛车层来源整体略偏弱，但 Gasly 的个人积分、近期表现和部分同周末来源把他抬到第 9；这项现在会作为低优先级复核项展示，而不是硬判为模型错误，也不能手动压低排名；
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
- 默认注册包 isolated 影响追踪覆盖不足：packet 内嵌 trace 仍只有少量单条 isolated 重跑和来源组 isolated 重跑；但已跟踪 sidecar 对最新注册 run 覆盖 453/453 条状态更新，因此前端/API 不应再把“packet 内嵌 trace 少”说成“完整解释链缺失”。

2026-07-06 追加修正后，`GET /api/v2/prediction-packets/latest` 会在读取历史 packet 时用当前审计器重新计算 `prediction_anomaly_audit`，并把对应 run 的 sidecar 覆盖证据传入审计器。也就是说：

```text
历史 packet 文件本身保持不可变；
前端看到的 anomaly audit 来自 API 运行时刷新；
刷新只改变审计展示，不改变预测概率、排名、packet hash 或 run registry。
```

当前 API 可见状态：

```text
run = british_gp_20260705T000000_0000_20260706T142235_0000_ab901d489d
prediction_anomaly_audit_source = api_runtime_recomputed
impact_trace_source = sidecar
impact_trace_covered_claim_count = 456
impact_trace_uncovered_claim_count = 0
anomaly_count = 1
anomaly = driver_specific_lift_over_weak_team_support / gasly / low
```

上一版异常审计中的 Leclerc/Hamilton 与 Racing Bulls 条目已在 2026-07-06 07:49 UTC 新 run 中消失；Williams 与 Alonso/Stroll 条目已在 2026-07-06 08:20 UTC 新 run 中消失。当前保留的 Gasly/Alpine 条目不是“车队负向却硬排中游”的高/中优先级异常，而是低优先级复核：Alpine 车队/赛车层来源略偏弱，Gasly 个人来源把他抬入前十附近。这不能证明最终模型已经正确，但证明异常审计会把“来源事实、状态更新和最终排名之间的张力”展示出来，而不是给出“完全无风险”的假象。

前端新增“预测异常审计”区块，默认展示中文摘要、风险原因、支持来源和从“原始来源 -> 信息分析 -> 状态更新 -> 模拟路由 -> 预测变化”的链条。它不会展示内部裸分数，也不会按车队/车手手动改结果。

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
5. 当前默认 latest 已确认是 `british_gp_20260705T000000_0000_20260706T142235_0000_ab901d489d`；由未验证启发式权重试验生成的 `c4515f938f` 不进入默认前端。
6. API/latest 会用当前审计器和对应 sidecar 重新计算前端可见的 `prediction_anomaly_audit`；这不是重新预测，也不会写 artifact。

当前已缓存 sidecar 对最新注册 run 的正式解释覆盖为：

```text
state_update_count = 456
sidecar_id = british_gp_british_gp_20260705T000000_0000_2026_b9e5e9b73c4a_20260706T144238_0000_4764d14662
source_iterations = 1200
trace_iterations = 1200
trace_generation.comparison_status = matched_source_run_iterations
impact_trace_covered_claim_count = 456
impact_trace_uncovered_claim_count = 0
formal_readiness.status = formal_trace_ready
formal_readiness.formal_ready = true
```

这说明“每条状态更新都能被分页追踪”已经可用，并且这一次 sidecar 的隔离重跑迭代数与源 run 一致，可以作为同口径解释证据使用。它仍然不等于预测质量正式达标，因为预测包本身仍是 `diagnostic_only`，阻塞项仍是 `probability_calibration_diagnostic_only`。

2026-07-06 追加守门：sidecar 和前端/API 现在会公开 `formal_readiness`。低迭代 sidecar 会显示“trace 已全覆盖，但仍是诊断迭代”，从而避免把 5 次迭代的快跑解释误说成 1200 次源 run 的正式同口径解释；最新 1200 次 sidecar 则显示为 `formal_trace_ready`。

2026-07-06 追加执行能力：`PredictionPipeline`、sidecar API 和 CLI 已支持 `isolated_impact_offset`。这让正式同迭代 sidecar 可以分块生成，而不是一次性对 453 条来源更新全部跑 1200 次迭代。分块结果会被标记为 `chunk_mode`，在合并成全覆盖 sidecar 前不会被认定为正式解释。

随后新增 chunk merge：`POST /api/v2/prediction-impact-traces/merge` 和 `merge-prediction-impact-trace-sidecars` CLI 可以把多个 chunk sidecar 合并成一个分页 sidecar。当前 smoke 已验证两个 5 条 chunk 合并后覆盖 10/453 条，仍然被标为 `diagnostic_iterations_incomplete_coverage`，不会污染 latest，也不会被误认定为正式解释。

2026-07-06 11:35 UTC 重新生成了 b4fa run 的诊断 sidecar 缓存：

```text
sidecar_id = british_gp_british_gp_20260705T000000_0000_2026_fcd18dabfdfa_20260706T113531_0000_5228c60b4e
trace_generation.iterations = 5
trace_generation.comparison_status = diagnostic_iteration_mismatch
coverage.impact_trace_covered_claim_count = 453
coverage.impact_trace_uncovered_claim_count = 0
formal_readiness.formal_ready = false
```

这次重写没有改变任何预测排名，也没有注册新的 prediction run。它修正的是解释缓存：sidecar 内现在包含 `trace_context`，分页行可以把 FastF1 同场排位、FastF1 近几站车队强度重估、F1 官方积分榜等结构化来源，连接到 `raw_sources -> normalized_claim -> quality_profile -> state_update_ledger -> same-seed impact trace`。也就是说，前端解释不再只能显示“某个 FastF1 claim_id 产生了变化”，而是能说明它来自哪类结构化来源、被映射成哪个状态因子、状态如何变化，以及同种子重跑后是否真的改变了预测分布。

重要边界仍然不变：这个 b4fa sidecar 是 5 次迭代的诊断缓存，不能作为正式 1200 次同口径概率变化证明。它解决的是“链条能否追溯”的前端解释问题，不解决“预测是否已经有稳定 edge”的问题。

2026-07-06 12:36 UTC 又为最新注册 run 生成了 1200 次同迭代正式解释 sidecar：

```text
run_id = british_gp_20260705T000000_0000_20260706T115913_0000_31f3f052bf
sidecar_id = british_gp_british_gp_20260705T000000_0000_2026_e33fbbd4ba1b_20260706T123600_0000_057974e605
source_iterations = 1200
trace_iterations = 1200
covered_claim_count = 453
uncovered_claim_count = 0
formal_readiness.status = formal_trace_ready
formal_readiness.formal_ready = true
```

这次生成没有改变预测排名，也没有注册新的 prediction run。它只是把“每条来源更新到底有没有影响预测”的解释从低迭代诊断，升级为与源 run 同迭代数的正式解释缓存。API/latest 现在会优先选择这个 sidecar，因此前端可以展示正式解释链，但仍必须同时展示预测状态是 `diagnostic_only`。

下一步不再是“把 sidecar 做出来”，而是：

- 继续减少/替换 `seed://` 开发证据，让默认预测更多来自 FIA/F1 官方、FastF1、天气、赛道、可靠性、长距离和近期窗口数据；
- 把正式 sidecar 的链路解释接入前端默认问答和重点面板，而不是让用户看到孤立分数；
- 用历史回放验证每类状态更新和每类权重修改是否真的改善预测，而不是只改善解释或迎合人工直觉。

## 13. 2026-07-06 13:18 UTC：积分截断修正来自来源映射，不来自用户一句话

本轮修正专门回应一个原则问题：用户指出 Mercedes、Ferrari、Red Bull、Aston Martin、Cadillac、Racing Bulls、Audi 等例子，只能作为异常报告，不能作为标签。代码不能因为用户说“某队应该更强/更弱”就偷偷写死数值。

这次实际修改的是通用来源映射问题：分站积分和车队积分只奖励前十名，是 `top-ten-censored` 数据。仅用积分会把经常在第 11-15 名附近完赛的中游车队，错误地压到和长期第 18-22 名的垫底车队接近。新的 `fastf1_team_strength_reestimate` 仍读取 FastF1 赛季/近期每站积分，但当积分信号为负、而同一批 FastF1 全场完赛分类显示该队没有那么差时，会用统一公式缓和负向积分信号。

这不是按车队名硬编码：

```text
Racing Bulls、Alpine、Audi、Haas、Williams：负向积分信号被全场完赛分类不同程度缓和
Aston Martin、Cadillac：全场完赛分类没有支持缓和，因此仍保持更强负向
```

关键来源解释示例：

```text
Racing Bulls:
FastF1 赛前每站积分 5.12 vs 全场 9.18；近期窗口 7.67 vs 全场 9.18。
因为积分只覆盖前十，负向积分信号被同源 FastF1 全场完赛分类信号 +0.0226 缓和，最终 team_strength = -0.0011。

Audi:
FastF1 赛前每站积分 0.25 vs 全场 9.18；近期窗口 0.00 vs 全场 9.18。
因为积分只覆盖前十，负向积分信号被同源 FastF1 全场完赛分类信号 -0.0243 缓和，最终 team_strength = -0.0432。

Aston Martin:
FastF1 赛前每站积分 0.12 vs 全场 9.18；近期窗口 0.33 vs 全场 9.18。
没有触发缓和，最终 team_strength = -0.0563。

Cadillac:
FastF1 赛前每站积分 0.00 vs 全场 9.18；近期窗口 0.00 vs 全场 9.18。
没有触发缓和，最终 team_strength = -0.0577。
```

同口径 diff 显示：

```text
base_run = british_gp_20260705T000000_0000_20260706T115913_0000_31f3f052bf
candidate_run = british_gp_20260705T000000_0000_20260706T125327_0000_b732713811
input_changed = true
evidence_changed = false
probability_changed = true
information_intake_changed = false
changed_driver_count = 20
material_driver_change_count = 2
rank_change_count = 2
max_abs_expected_points_delta = 0.0992
```

这说明它不是新增了用户话语证据；也不是新增了 Codex 非结构化来源。它是结构化特征映射的修正，因此 `input_changed = true`、`evidence_changed = false`。预测变化幅度很小：主要是 Hulkenberg/Audi 从第 17 到第 16，Ocon 从第 16 到第 17；Racing Bulls 的期望积分略升，Aston Martin/Cadillac 仍在底部。这只能叫“方向上更合理一点”，不能叫预测质量已经显著优秀。

最新注册 run：

```text
run_id = british_gp_20260705T000000_0000_20260706T125327_0000_b732713811
packet_sha256 = b73271381102a3c760effd8ca0afc052d7cb15d471d478fa4d10523de3073c62
status = diagnostic_only
blocker = probability_calibration_diagnostic_only
```

正式解释 sidecar 已完成：

```text
sidecar_id = british_gp_1a7764238906_20260706T131855_0000_merged_1236c64f1a
source_iterations = 1200
trace_iterations = 1200
covered_claim_count = 453
uncovered_claim_count = 0
formal_readiness.status = formal_trace_ready
formal_readiness.formal_ready = true
```

API 当前会选择这个 sidecar：

```text
GET /api/v2/prediction-impact-traces/readiness -> formal_trace_ready
GET /api/v2/prediction-impact-traces/latest -> sidecar_id = british_gp_1a7764238906_20260706T131855_0000_merged_1236c64f1a
```

前端应展示的状态是：解释链已经能从来源到状态更新到预测影响做同迭代追踪；但预测包仍是 `diagnostic_only`，还没有通过历史回放、概率校准和 edge 验证。

## 14. 2026-07-06：同队顺序异常需要区分“实质冲突”和“近似平局”

本轮继续修正一个解释层问题：异常审计不能只看整数预测排名。
在 British GP 最新诊断包中，Audi 的 Bortoleto 与 Hulkenberg 曾被标为同队顺序张力：

```text
Bortoleto 同场排位 P11
Hulkenberg 同场排位 P13
预测排序中 Hulkenberg 略靠前
```

如果只看整数 expected rank，会显示成“第 18 vs 第 16”，像是明显冲突。但真实连续预测量是：

```text
Bortoleto average_finish = 15.60
Hulkenberg average_finish = 15.53
average_finish_gap = 0.07
expected_points_gap ~= 0.01
```

这不是实质性预测分歧，而是一个接近同分布的近似平局。把它报成中优先级异常，会误导前端解释，让用户以为模型强烈认为排位更差的一方明显更好。

因此新增通用审计阈值：

```text
TEAMMATE_CONFLICT_MIN_AVERAGE_FINISH_GAP = 0.40
TEAMMATE_CONFLICT_MIN_EXPECTED_POINTS_GAP = 0.10
```

只有当“排位更好的同队车手”在平均完赛名次或期望积分上被预测为实质性更差时，才标记 `teammate_order_conflict`。如果只是整数排名由于近似平局发生跳动，就不再报中优先级异常。

这个修正不改变预测概率、不改变排序、不手调任何车手。它只让异常审计更忠实地表达模型状态：

```text
近似平局 -> 不报明显冲突
实质性被反向预测 -> 报同队顺序张力
```

当前 API 运行时复核：

```text
GET /api/v2/prediction-packets/latest?event_id=british_gp
prediction_anomaly_audit.status = review_recommended
prediction_anomaly_audit.anomaly_count = 1
prediction_anomaly_audit.low_priority = driver_specific_lift_over_weak_team_support / gasly
impact_trace_source = sidecar
impact_trace_covered_claim_count = 456
impact_trace_uncovered_claim_count = 0
```

这不等于预测已经正确，也不等于具备正式 edge；它只表示当前异常审计规则没有发现高/中优先级明显冲突，但会保留低优先级 Gasly/Alpine 复核项。下一步仍然要靠历史回放、概率校准和市场基线比较证明预测质量。

## 15. 2026-07-06：修正 `race_probabilities` 的预计排名展示语义

本轮发现一个前端/packet 展示层问题：`prediction.race_probabilities` 在模拟器内部按冠军概率排序，这对“谁最可能赢”有意义，但不能直接当作“每个车手预计排名”。最新 British GP 包里，前 8 名因为冠军概率和平均完赛名次大致一致，看起来没有问题；但第 9 名以后会出现 Alonso/Stroll 被数组顺序放在 Gasly、Racing Bulls 和 Williams 之前的错觉。实际平均完赛名次显示 Alonso/Stroll 应在第 19/20 左右。

这不是新的模型修订，也不改变任何模拟概率、期望积分或平均完赛名次。修正内容是：

- 后端 `PredictionReport.to_dict()` 输出 `race_probabilities` 时增加 `expected_rank`，并按 `average_finish -> expected_points -> podium -> win` 排列；
- API 读取历史已注册 packet 时运行时补齐同样的 `expected_rank` 和排序，所以旧 JSON 包也不会继续误导前端；
- 前端默认预测表改为中文“全场预计排名”表，展示 22 名车手，而不是只展示冠军概率前 8；
- `probability_summary.top_win_probabilities` 仍然按冠军概率排序，避免把“冠军概率第一”和“平均完赛第一”混为一谈。

当前 API 运行时复核：

```text
GET /api/v2/prediction-packets/latest?event_id=british_gp
race_probabilities[0:8] by expected_rank =
01 Russell
02 Antonelli
03 Hamilton
04 Leclerc
05 Norris
06 Piastri
07 Verstappen
08 Hadjar
...
19 Alonso
20 Stroll
21 Bottas
22 Perez
```

这项修正让前端展示更符合用户“预测整场比赛每个车手预计排名”的要求，但它不应被解释为预测质量提升。模型质量仍然是 `diagnostic_only`，还需要历史回放、概率校准和更多来源化赛车/赛道/长距离信息来证明预测本身更可靠。

## 16. 2026-07-06：修正 replay/calibration 的预计排名口径

在展示层修正之后，还发现同一个语义问题存在于历史回放和校准诊断里：`top_pick = race_probabilities[0]` 用来表示“冠军概率最高的车手”是合理的；但 `actual_winner_rank`、`mean_abs_rank_error`、`podium_overlap_rate` 和 `points_overlap_rate` 这类全场排名指标不能继续沿用冠军概率顺序。

本轮新增了统一函数 `race_probabilities_by_expected_rank()`：

```text
预计排名顺序 =
average_finish 从小到大
-> expected_points 从大到小
-> podium 从大到小
-> win 从大到小
-> driver_id 稳定排序
```

并把它接入：

- `Backtester._full_field_metrics()`：全场排名误差、领奖台重合率、积分区重合率改用预计完赛顺序；
- `ReplayCalibrationBuilder._rank_of()`：`actual_winner_rank` 改为“实际冠军在预计完赛排名中的名次”，不再是“实际冠军在冠军概率数组里的位置”；
- `ModelErrorReviewBuilder._rank_of()`：错误复盘中的 actual-winner-rank 使用同一口径；
- `scripts/prediction_anomaly_audit_smoke_test.py`：新增反例，验证“冠军概率最高但平均完赛更差”的车手不会被错误算作预计排名第一。

这仍然不改变任何概率，也不证明预测更准。它修正的是评价和解释口径：以后如果历史回放说“实际冠军被模型排第 3”，这句话指的是预计完赛排名第 3，而不是冠军概率列表第 3。这样后续做模型修订证明、同口径 diff 或前端解释时，不会把两个不同问题混在一起：

```text
问题 A：谁最可能赢？
问题 B：每个车手预计完赛第几？
```

两者都重要，但不能互相替代。

## 17. 2026-07-07：解释 trace 区分直接证据和间接竞争影响

继续检查中文解释时发现一个容易误导用户的问题：一条影响 trace 只要改变了所问车手的期望积分，就会进入解释；但这条 trace 的来源目标不一定是该车手或同队赛车。例如 Mercedes 车队强度重估被移除时，Ferrari 车手的期望积分也会变化，因为竞争格局变了。这个 trace 可以说明“竞争对手来源会间接改变 Ferrari 分布”，但不能写成“Mercedes 来源直接解释 Hamilton/Leclerc 队内差距”。

本轮修正：

- `PredictionExplainer` 为每条公开 impact trace 增加 `relevance_scope` 和 `relevance_scope_label`；
- 直接作用于所问车手、所问车队或本场事件的 trace 标为“直接作用于所问对象”或“本场比赛环境影响”；
- 只因为改变竞争格局而影响所问车手的 trace 标为“竞争格局间接影响，不是直接支持所问对象的来源”；
- 用户可读回答优先展示直接 trace，再展示本场环境/整体基线，最后才展示间接竞争影响；
- `scripts/explainability_smoke_test.py` 增加断言，确保 Hamilton/Leclerc 对比时 Ferrari/Leclerc/Hamilton 直接 trace 排在 Mercedes 间接竞争 trace 前面。

这项修正不改变预测概率，也不改变 sidecar。它修正的是解释语义：影响到了某个车手，不等于该来源就是解释这个车手/车队状态的直接证据。以后前端如果展示一条 Mercedes 来源影响 Leclerc/Hamilton 的 trace，必须明确这是竞争格局间接影响，而不是 Ferrari 或 Leclerc 的事实来源。

## 18. 2026-07-07：明确阻断“用户反馈作为证据”

用户再次指出一个底线：用户举例只能说明当前预测哪里不合理，不能被系统偷偷当成标签或人工强约束。比如“Leclerc 不该这么低”“Aston Martin 不该这么高”只能触发系统去检查真实来源、状态更新和模拟映射，不能直接写成某个车手/车队的数值修正。

本轮补上代码级约束：

- `EvidenceQualityScorer` 现在识别 `user://`、`user-feedback://`、`codex-feedback://`、`prompt://` 这类来源；
- 这类 claim 会被标记为 `user_feedback_source`；
- `model_input_weight = 0.0`，也就是不会进入模型输入；
- `BeliefStateBuilder` 会把这类来源的状态更新权限设为 `blocked`；
- 中文解释中会显示“用户反馈只能触发审计，不能更新预测”；
- `scripts/source_driven_contract_test.py` 增加契约测试，验证用户反馈 claim 即使有很高置信度和很大幅度，也必须保持零权重。

因此，当前规则是：

```text
用户指出问题
-> 允许创建审计任务/异常检查/来源补全需求
-> 必须重新获取或归档真实来源
-> 真实来源经过质量审计后才能更新状态
-> 只有状态或来源链条改变，预测才允许改变

用户指出问题
-> 不允许直接改某个车手/车队分数
-> 不允许把用户提示伪装成 evidence
-> 不允许把这种变化注册成 latest
```

这项修正仍然不改变当前 British GP 预测数值。它改变的是系统边界：以后即使我误把你的话写成 evidence，也会被质量门控压成 0 权重，并在解释层明确标出它不是预测依据。

## 19. 2026-07-07：最新 run 的解释 sidecar 已补齐到 535/535

在 2026-07-07 的 BeliefState 特征映射修复之后，新的 British GP latest run 变为：

```text
run_id = british_gp_20260705T000000_0000_20260707T054040_0000_a96fffb1fc
status = diagnostic_only
state_update_count = 535
```

一开始这个 run 只有局部 sidecar，覆盖 `10/535` 条状态更新，因此异常审计会正确报告：

```text
impact_trace_incomplete_for_material_updates
```

随后已用同一 `run_id`、同一 `packet_payload_sha256`、同一 `iterations = 1200` 分块补齐并合并 sidecar：

```text
sidecar_id = british_gp_f6fd000ef3aa_20260707T060939_0000_merged_f783f87561
formal_readiness.status = formal_trace_ready
covered_claim_count = 535
uncovered_claim_count = 0
```

这解决的是“每条来源化状态更新是否都有同口径影响追踪”的可解释性缺口。现在前端/API 可以从 sidecar 中追溯：

```text
原始来源 -> 信息分析 -> 状态更新 -> 模拟路由 -> 预测变化
```

但这仍然不等于预测质量已经通过验证。当前预测包依然必须显示 `diagnostic_only`，下一阶段仍要优先处理：

- 最近 3-5 站、同周末 FP/排位/正赛长距离信息是否足够强地进入 BeliefState；
- 进入状态后的信息是否真的通过模拟路由改变合理的车队/车手分布；
- 历史回放、概率校准和市场基线比较是否能证明预测质量改善。

## 20. 2026-07-07：新增相关车队比赛日窗口诊断机制

继续检查 British GP 的概率分布时发现，当前 top2 胜率过度集中不只来自 Mercedes 状态强，也来自模拟结构：旧模拟器的大部分随机性是车手独立噪声。这会导致强队双车在同一场比赛里“总有一辆吃到胜利”，而不能表达“同一辆车或同一队当天调校/轮胎窗口不对，双车一起受影响”的情况。

本轮新增通用机制：

```text
BeliefState 状态不确定性
-> 车队相关 race-window offset
-> 同队两辆车共享同方向比赛日偏移
-> 概率分布小幅打散
```

这不是按用户举例手动压低 Mercedes 或抬高 Ferrari/McLaren/Red Bull。代码没有写任何车队或车手 id 特判。该机制统一读取 BeliefState 中赛车、轮胎、调校和车手状态的不确定性，并为每个车队抽取同一种比赛日窗口偏移。

诊断候选包：

```text
path = reports/prediction_packets_model_revision_probe/team_window_v3/british_gp/british_gp_20260705T000000_0000.prediction_packet.json
packet_payload_sha256 = 30cd0735df2efc78dbd7894d61268395fb868b37a588577f6c5d8602365d8d2e
status = diagnostic_only
config_id = default_pace_separation_track_position_team_window_v3
```

同一输入、1200 次迭代的诊断对比：

```text
旧口径 Mercedes 双车合计胜率 = 94.92%
新口径 Mercedes 双车合计胜率 = 92.25%
Russell 胜率 48.83% -> 48.25%
Antonelli 胜率 46.08% -> 44.00%
Hamilton 胜率 2.83% -> 4.58%
Verstappen 胜率 0.08% -> 0.58%
Piastri 胜率 0.25% -> 0.58%
```

排序变化很小：

```text
Russell、Antonelli、Hamilton、Leclerc 仍保持前四。
Piastri/Norris 发生 P5/P6 近似交换。
Gasly 从第 9 到第 10，低优先级 Alpine 复核项仍然存在。
Aston Martin 和 Cadillac 仍在底部区间。
```

这说明修正方向是“缓和过度集中”，不是“重写排名”。它让预测结果部分更接近 F1 的比赛日不确定性，但还不能当作正式提升证明。

重要边界：

- 该机制先作为未注册候选包生成，用于确认它只是通用模拟结构修订，不是按用户举例手调。
- 随后在提供模型修订证明后，该机制已注册为新的 latest 诊断 run；这不等于来源驱动变化，也不等于正式 edge。
- 该 run 的静态 prediction packet 是在 full sidecar 生成前写出的，因此 JSON/Markdown 快照里仍可能保留“主包内嵌 trace 不完整”的诊断；API 和前端读取 latest 时会叠加最新 sidecar 状态。
- 预测质量仍必须通过历史回放、概率校准和市场基线比较验证；当前只能说解释链完整、模型修订有证明，不能说已经具备稳定盈利能力。

## 21. 2026-07-07：相关车队窗口 v3 已注册，并补齐完整 sidecar

在模型修订证明文件明确说明“这是通用 race-window 噪声修订，不是按用户反馈手调数值”之后，相关车队比赛日窗口机制已注册为 British GP 的最新诊断 run：

```text
run_id = british_gp_20260705T000000_0000_20260707T065149_0000_d76ec2c3e4
packet_payload_sha256 = d76ec2c3e444fc48e648dc0208bf31a52b1c5158612b7cf81a386d1989e50478
config_id = default_pace_separation_track_position_team_window_v3
status = diagnostic_only
blocker_codes = probability_calibration_diagnostic_only
```

本次注册不是“用户说某队该更强/更弱，所以修改结果”。允许注册的依据是：

```text
同一批来源和 BeliefState
-> 通用模拟机制修订
-> 模型修订证明
-> PredictionRunRegistry 记录为 diagnostic_only
-> 再为新 run 补齐 full sidecar
```

最新前端预测排名按平均完赛名次展示为：

```text
01 Russell
02 Antonelli
03 Hamilton
04 Leclerc
05 Piastri
06 Norris
07 Verstappen
08 Hadjar
09 Lindblad
10 Gasly
...
19 Alonso
20 Stroll
21 Bottas
22 Perez
```

新 run 的完整同迭代影响追踪 sidecar 已分块生成并合并：

```text
sidecar_id = british_gp_e075659cf939_20260707T074125_0000_merged_ca50ec46ef
source_iterations = 1200
trace_iterations = 1200
claim_count = 535
covered_claim_count = 535
uncovered_claim_count = 0
formal_readiness.status = formal_trace_ready
```

API 复核结果：

```text
GET /api/v2/prediction-packets/latest?event_id=british_gp
packet_payload_sha256 = d76ec2c3e444fc48e648dc0208bf31a52b1c5158612b7cf81a386d1989e50478
prediction_anomaly_audit.anomaly_count = 1
impact_trace_source = sidecar
impact_trace_covered_claim_count = 535

GET /api/v2/prediction-impact-traces/latest?event_id=british_gp&limit=1
sidecar_id = british_gp_e075659cf939_20260707T074125_0000_merged_ca50ec46ef
formal_readiness.status = formal_trace_ready
covered_claim_count = 535
uncovered_claim_count = 0
```

前端复核结果：

```text
预测依据总览：来源化状态更新 535 / 535
完整追踪缓存：535/535
追踪口径：matched_source_run_iterations
正式解释：已就绪
预测影响追踪：当前页 24 / 546 条
```

剩余异常目前只有一个低优先级复核项：`driver_specific_lift_over_weak_team_support / Gasly-Alpine`。这不是硬冲突，而是提示后续要继续补长距离、轮胎衰退、策略、队友对比等来源，确认 Gasly 的车手层信号是否足以覆盖 Alpine 车队层偏弱信号。

因此当前状态应被表述为：

```text
解释链：已完整同迭代覆盖，可审计
预测包：仍是 diagnostic_only
预测质量：方向比早期版本合理，但尚未通过历史回放/校准/市场基线证明
```

## 22. 2026-07-07：修正 Gasly/Alpine 低优先级异常的归因口径

继续审计 latest run 时发现，上一节保留的低优先级 `driver_specific_lift_over_weak_team_support / Gasly-Alpine` 更像是异常审计的归因口径问题，而不是新的预测数值问题。

当时的异常文案说：

```text
车队/赛车层来源偏弱，但车手层正向来源把 Gasly 抬入前十附近。
```

重新查看 `BeliefState` 和 `StateUpdateLedger` 后，Gasly 本人的来源账本并不是净正向：

```text
Gasly 同场排位 P12/22 -> qualifying_ceiling 明显负向
Gasly 同场排位圈速慢于全场均值 -> qualifying_ceiling 负向
Gasly 赛季/近期积分与官方积分榜 -> race_pace 小幅正向
Gasly 近期/赛季发车到完赛转换 -> race_execution 小幅正向
综合看：车手本人正向信号不足以被描述成“把他抬入前十”的强证据
```

同时 Alpine 车队层也不是单纯强负向：

```text
同场平均排位、排位圈速 -> 负向
近期全场完赛位置重估、练习赛长距离代理 -> 正向
官方车队积分和每站积分 -> 小幅负向
```

因此第 10 名附近的 Gasly 更准确的解释是：

```text
中游车队分布非常密集；
Gasly 相对 Colapinto 的同队排位和历史表现更好；
Alpine 车队层有负向，也有近期完赛/长距离 counterevidence；
当前排序是弱差距下的诊断结果，不应被异常审计误写成“车手个人来源强行覆盖弱车队”。
```

本轮代码修正：

- 新增 `_DriverSupport`，按车手本人统计 `positive/negative/net/source/claim/update`；
- `driver_specific_lift_over_weak_team_support` 只有在“最佳车手本人来源净正向、正向来源超过负向来源、且正向强度超过车队层支持”时才会触发；
- 不再用全队聚合或队友来源来解释某一名车手；
- `scripts/prediction_anomaly_audit_smoke_test.py` 改为验证 Gasly 不会被固定报异常，同时保留真正 driver-specific lift 的解释约束。

这次修正不改变任何预测概率、排名、BeliefState 或 sidecar。它只改变 API 运行时异常审计：

```text
GET /api/v2/prediction-packets/latest?event_id=british_gp
run_id = british_gp_20260705T000000_0000_20260707T065149_0000_d76ec2c3e4
packet_payload_sha256 = d76ec2c3e444fc48e648dc0208bf31a52b1c5158612b7cf81a386d1989e50478
prediction_anomaly_audit.status = no_major_anomaly_detected
prediction_anomaly_audit.anomaly_count = 0
impact_trace_covered_claim_count = 535 / 535
```

这不等于预测已经正确，也不等于具备正式 edge。它只表示当前异常审计规则不再发现高/中/低优先级的明显来源-排名张力。下一阶段仍然要用历史 replay、概率校准和市场基线比较来证明预测质量。

## 23. 2026-07-07：新增 British GP 赛后预测复盘，不把赛后结果写回预测

今天继续推进“预测结果是否大致合理”的目标时，先补了一个缺失证据：British GP 已经结束，但本地此前没有 FastF1 正赛结果快照，所以 `replay-report --as-of 2026-07-07T00:00:00+00:00` 会把 British GP 标为 `missing_due_data`。这意味着我们无法严肃回答“最新赛前预测到底表现怎么样”。

本轮用项目现有 CLI 摄取了 British GP 正赛结果：

```text
python -m f1predict.cli ingest-fastf1-results --year 2026 --event "British Grand Prix" --session R
```

得到的结果快照为：

```text
data/raw/fastf1/2026_British_Grand_Prix_Race_results/2026-07-07/2026_British_Grand_Prix_Race_results_2026-07-07T08_45_13_00_00.json
```

FastF1 结果显示实际前十：

```text
1 Leclerc
2 Russell
3 Hamilton
4 Norris
5 Hadjar
6 Lawson
7 Lindblad
8 Bortoleto
9 Colapinto
10 Gasly
```

随后新增了通用的 `PostEventReviewBuilder` 和 CLI：

```text
python -m f1predict.cli post-event-review --event british_gp --write
```

生成产物：

```text
reports/post_event_review/british_gp/british_gp_20260705T000000_0000.post_event_review.json
reports/post_event_review/british_gp/british_gp_20260705T000000_0000.post_event_review.md
```

这份复盘读取的是最新注册赛前预测包：

```text
run_id = british_gp_20260705T000000_0000_20260707T065149_0000_d76ec2c3e4
knowledge_cutoff = 2026-07-05T00:00:00+00:00
packet_payload_sha256 = d76ec2c3e444fc48e648dc0208bf31a52b1c5158612b7cf81a386d1989e50478
```

关键结果：

```text
预测第一：Russell
实际冠军：Leclerc
冠军命中：False
实际冠军 Leclerc 的赛前预计排名：第 4
Leclerc 的赛前预测胜率：0.0125
预测第一 Russell 的实际完赛位置：第 2
领奖台重合率：0.6667
积分区重合率：0.7
平均绝对排名误差：4.6364
```

这说明当前模型有两个层面的真实状态：

第一，整体前排结构不是完全离谱。实际领奖台 Leclerc/Russell/Hamilton 中，Russell 和 Hamilton 已经在预测前三，Leclerc 也在预测第 4；实际前十里 Hadjar、Lindblad、Gasly 等中游位置也大致进入了预测前十附近。

第二，冠军概率分布仍明显有问题。Leclerc 最终获胜，但赛前胜率只有 `1.25%`；Antonelli 赛前被给到 `44.0%` 冠军概率和第 2 预计排名，实际只完赛第 15。这说明当前模型仍然过度相信部分 Mercedes/Antonelli 的强信号，低估了 Ferrari/Leclerc 在同场排位和正赛执行中的上行空间，也没有充分表达单场事故、策略、退化或比赛执行导致的尾部风险。

这次新增的是评估能力，不是模型调参：

- 没有改变预测概率；
- 没有改变 registered latest run；
- 没有把赛后结果写入赛前 BeliefState；
- 结果快照晚于预测截止，复盘产物明确标记 `result_snapshot_after_prediction_cutoff_for_evaluation_only`；
- `post_event_review_smoke_test.py` 验证了 Leclerc 冠军、Russell 预测第一、领奖台/积分区 overlap、以及 `arvid_lindblad -> lindblad`、`max_verstappen -> verstappen` 这类 FastF1/内部 driver id 映射。

下一步模型方向因此更明确：

```text
不要按 Leclerc 或 Antonelli 手调；
应复查同场排位、长距离、策略、轮胎衰退、可靠性/事故尾部风险和车队近期状态在模拟器中的通用权重；
把 British GP 加入 replay/calibration 以后，再用同口径候选配置比较是否真的降低排名误差和概率过度集中。
```

当前结论：解释链条已经能解释预测从哪里来；赛后复盘证明英国站预测“前排结构部分合理，但冠军概率和 Antonelli 风险明显不合理”。因此 goal 仍不能标记为全部完成，除非后续模型校准能在不手调实体的前提下改善这类错误。

补充：在结果摄取后，已重跑 2026-07-07 的 replay coverage、replay analysis 和 calibration：

```text
python -m f1predict.cli replay-report --year 2026 --as-of 2026-07-07T00:00:00+00:00 --write
python -m f1predict.cli analyze-replay --year 2026 --as-of 2026-07-07T00:00:00+00:00 --iterations 1200 --write
python -m f1predict.cli calibration-report --year 2026 --as-of 2026-07-07T00:00:00+00:00 --iterations 1200 --write
```

新增/刷新产物：

```text
reports/replay/2026_asof_20260707T000000_0000.json
reports/replay_analysis/2026_asof_20260707T000000_0000.analysis.json
reports/replay_analysis/2026_asof_20260707T000000_0000.analysis.md
reports/calibration/2026_asof_20260707T000000_0000.calibration.json
reports/calibration/2026_asof_20260707T000000_0000.calibration.md
```

British GP 在 replay coverage 中已经从缺失结果变成可评分行：

```text
status = replayed
top_pick = russell
actual_winner = leclerc
hit = false
actual_winner_rank = 4
mean_abs_rank_error = 4.6364
podium_overlap_rate = 0.6667
points_overlap_rate = 0.7
```

9 场整体诊断指标：

```text
diagnostic_scored_events = 9
top_pick_hits = 6
top_pick_hit_rate = 0.6667
median_actual_winner_rank = 1
mean_abs_rank_error = 4.3232
mean_podium_overlap_rate = 0.6667
mean_points_overlap_rate = 0.7222
```

概率校准指标：

```text
scored_events = 9
market_scored_events = 2
mean_top_pick_probability = 0.4708
mean_actual_winner_probability = 0.3562
weighted_top_pick_calibration_gap = 0.1959
mean_actual_log_loss = 1.4793
formal_probability_claim_ready = false
```

British GP 单场校准行尤其说明问题：

```text
top_pick = russell
actual_winner = leclerc
top_pick_probability = 0.4825
actual_winner_probability = 0.0125
actual_winner_rank = 4
actual_log_loss = 4.382
paper_trade_hit = false
```

这进一步支持上面的判断：当前模型不是全局排序完全崩坏，而是概率分布过度集中、部分强队/车手风险尾部不足、Ferrari/Leclerc 的胜出可能被压得过低。下一步如果要改变默认预测，必须通过通用模型修订证明或新的来源化状态更新，不能因为这场结果直接把 Leclerc 手动抬高。

2026-07-07 继续追加一个未注册的通用胜率校准 probe：

```text
config_id = winner_rank_podium_calibrated_probe
status = diagnostic_probe_not_registered
```

这个 probe 的规则只读取模拟已经给出的全场分布：

```text
raw sampled win probability
+ expected-rank prior
+ podium-support prior
```

它不读取车手名、车队名，也不改变平均完赛名次、期望积分、领奖台概率或积分区概率。它的目的只是检查“winner 概率是否过度集中在前一两名，导致预测第 3/第 4 且领奖台概率不低的车手胜率过低”。

在 British GP 最新赛前包上，probe 结果为：

```text
Leclerc 原始胜率 = 0.0125
Leclerc probe 后胜率 = 0.042145
变化 = +0.029645
probe 后预测第一 = Russell
Russell probe 后胜率 = 0.423042
```

这说明一个通用校准层可以缓和 Leclerc 被压得过低的问题，但它仍然不能直接成为默认 latest，原因是：

- 这只是单站 post-event diagnostic probe；
- 它没有经过足够大样本、带 holdout 的正式 simulator calibration；
- 随后针对 baseline 与 `winner_rank_podium_calibrated` 做了 2026 已完赛 9 场、每候选 120 次迭代的小样本诊断校准，综合评分仍推荐 baseline；
- 该候选虽然让平均实际冠军 log loss 从 `1.5396` 降到 `1.4457`，但也让实际冠军平均概率从 `35.6%` 降到 `30.6%`，Brier 从 `0.6776` 升到 `0.6916`，top-pick 校准 gap 从 `0.0750` 升到 `0.1943`；
- 因此它只能说明“winner 概率尾部过低”是值得继续研究的问题，不能说明这个平滑参数已经应该注册成默认模型；
- 如果后续要启用，必须生成模型修订证明，并通过 `PredictionRunRegistry` 的模型修订门禁。

当前可采纳的结论不是“应该把 Leclerc 手动调高”，而是“winner probability 层存在过度集中风险，下一轮应优先做通用 winner calibration 的 replay 校准”。

## 24. 2026-07-07：前端赛道图增加 2026 规则口径说明

继续检查前端截图时发现，British GP 使用的是真实 F1 official circuit map，但官方底图本身仍带有 `DRS DETECTION ZONE`、`SPEED TRAP` 等历史视觉标注。这个问题不能通过删除赛道图或退回假图解决，因为赛道形状和官方地图来源仍然是正确的；真正需要修的是前端语义：页面必须说明这些旧规则标注不是 2026 预测模型的输入。

本轮前端修正：

```text
trackMapAudit(event)
-> trackRuleContext(event, source, asset)
-> renderTrackAudit(...)
-> drawTrackRuleBadge(...)
```

当页面读取 2026 赛季的 F1 official circuit map 时，会显示：

```text
2026规则口径
官方底图可能保留 DRS/测速点等历史视觉标注；本项目只把它作为赛道形状底图，模拟输入来自赛道向量、直道/弯角/超车难度和来源化状态更新。
```

canvas 左下角也会显示：

```text
2026：不读取DRS标注
```

这项修正不改变任何预测概率、BeliefState、track feature vector 或模拟器。它只修正前端展示的语义边界：真实官方赛道图可以继续作为视觉底图，但 2026 预测不能把底图里的 DRS 字样当成规则输入。对应浏览器 sanity check 已确认：

```text
Playwright snapshot 中出现 2026规则口径；
console = 0 errors / 0 warnings；
概率表中 Verstappen 行不再挤压概率列。
```

剩余风险：这只是前端规则口径说明，不等于已经为 2026 新规则建立完整的“替代 DRS/能量部署/超车辅助机制”数据源。后续如果要让该机制影响预测，必须作为来源化赛道/赛车技术信息进入 `RawSourceRecord -> NormalizedFactorClaim -> BeliefState -> simulation`，不能从图片文字直接推断。

## 25. 2026-07-07：头部胜率过度集中候选校准复核

British GP 赛后复盘暴露的核心模型问题之一是：头部冠军概率过度集中，Leclerc 这种预测 P4 且领奖台概率不低的车手，赛前冠军概率只有 `1.25%`。上一节的 winner probability probe 不能注册后，本轮继续用现有 simulator calibration 框架复核几类通用概率分散机制，而不是按车手或车队手动修数值。

本轮诊断产物：

```text
reports/simulator_calibration_probability_focus/2026_asof_20260707T000000_0000.simulator_calibration.md
reports/simulator_calibration_no_team_window_review/2026_asof_20260707T000000_0000.simulator_calibration.md
```

120 次迭代的概率集中候选集显示：

```text
no_correlated_team_window: composite_score = 2.0658
stronger_team_window: composite_score = 2.1276
baseline team_window_v3: composite_score = 2.1852
chaos_weighted: composite_score = 2.2923
wider_race_variance: composite_score = 2.2979
```

这说明“相关车队比赛日窗口”本身需要复核：在这个小样本里，完全关闭同队相关窗口反而综合分更好。但 120 次迭代不足以支持模型修订，所以又做了 400 次、只比较 baseline 与 `no_correlated_team_window` 的复核：

```text
no_correlated_team_window composite_score = 2.2476
baseline team_window_v3 composite_score = 2.2539
```

400 次复核仍让 `no_correlated_team_window` 微弱领先，但证据并不稳定，原因是：

```text
no_correlated_team_window 的 mean_actual_winner_probability 更高：+0.0150
no_correlated_team_window 的 Brier 更好：-0.0041
no_correlated_team_window 的 top-pick 校准 gap 更好：-0.0180
但 no_correlated_team_window 的 mean_actual_log_loss 变差：+0.0286
British GP 上 Leclerc 概率从 baseline 的 0.0125 降到 0.0075
```

因此这轮不能得出“应该撤销 team-window v3”或“应该注册 no_correlated_team_window”的结论。正确结论是：

- 相关车队窗口机制并没有被当前小样本稳健证明有效；
- 单纯加大或关闭同队相关波动都不能解决 British GP 的 Leclerc 低胜率问题；
- 下一轮应该把“车队比赛日窗口”拆成更可解释的来源化因素，例如调校窗口、轮胎温度窗口、长距离退化、可靠性、策略窗口，而不是只用一个全局噪声常数；
- 任何默认模型变更仍必须通过 `PredictionRunRegistry` 的模型修订证明，不能因为小样本诊断分数略好就注册。

## 26. 2026-07-07：新增来源化 team-window pressure 候选，但不注册

基于上一节的结论，本轮把粗粒度 `team_race_window_noise` 拆出一个更可解释的方向性候选：

```text
BeliefState.car.tyre_deg
BeliefState.team_ops.setup_quality
BeliefState.team_ops.strategy_quality
BeliefState.team_ops.race_execution
BeliefState.car.reliability
-> PaceModel.race_window_pressure()
-> SingleRaceSimulator._sample_team_race_window_offsets()
```

它和旧的随机 team-window 区别是：

- 旧机制只看不确定性，决定同队共享随机波动有多大；
- 新候选会读取来源化状态的方向，状态显示轮胎/调校/策略/可靠性偏弱时，共享 race-window offset 往“变慢”方向移动；
- 高不确定度会折扣该方向性压力，避免弱 seed prior 直接主导；
- 默认配置 `team_race_window_pressure_scale = 0.0`，所以 latest 预测不变；
- 只有 simulator calibration 候选 `source_weighted_team_window_pressure` / `source_weighted_team_window_pressure_strong` 会启用。

新增验证：

```text
scripts/race_window_pressure_smoke_test.py
```

它验证三件事：

```text
来源化负向 tyre/setup/reliability 状态会产生正的 race_window_pressure；
默认关闭时 shared team-window offset 不变；
启用 pressure scale 后 offset 会按来源化方向变慢。
```

诊断校准产物：

```text
reports/simulator_calibration_source_window_pressure_v2/2026_asof_20260707T000000_0000.simulator_calibration.md
```

160 次小样本结果：

```text
source_weighted_team_window_pressure_strong composite_score = 2.3886
source_weighted_team_window_pressure composite_score = 2.4060
baseline team_window_v3 composite_score = 2.4092
```

看起来 strong 候选略优于 baseline，但这个结果不能注册，原因是：

```text
样本仍只有 9 场；
候选选择仍是 in-sample；
改进幅度很小；
British GP 的 Leclerc 胜率没有改善，仍约为 0.0063；
这说明当前 BeliefState 中 tyre/setup/reliability 等方向性来源仍太弱，无法解决 Ferrari/Leclerc 的低胜率问题。
```

因此这次改动的正确价值是“把 team-window 的来源化路由打通”，不是“预测已经修好”。下一步要让它真正影响合理性，必须补更强的来源化输入：同周末长距离、轮胎退化、调校窗口、可靠性和策略窗口，而不是继续调一个全局 scale。

## 27. 2026-07-07：FastF1 practice 轮胎衰退进入车队/赛车状态

继续追查上一节“方向性来源仍太弱”的原因时，发现 British GP latest packet 里虽然有 FastF1 Practice 1 的轮胎衰退特征，但它们只进入了车手层：

```text
driver.tyre_management updates = 16
car.tyre_deg updates = 0
team_ops.setup_quality updates = 0
```

这意味着 `PaceModel.race_window_pressure()` 已经有读取 `BeliefState.car.tyre_deg` 的能力，但当前来源没有真正喂到赛车/车队轮胎窗口状态。于是本轮修的是通用来源映射，而不是调某个车队：

```text
FastF1 practice long-run tyre-degradation proxy
-> driver tyre_deg feature
-> driver.tyre_management

FastF1 practice long-run tyre-degradation proxy
-> team tyre_deg feature
-> BeliefState.car.tyre_deg
-> stint_degradation / strategy_plan / race_window_pressure 可读状态
```

实现位置：

```text
src/f1predict/features/provider.py
scripts/fastf1_team_tyre_deg_smoke_test.py
scripts/source_driven_contract_test.py
```

新增规则：

- 对同一场 practice session 中有 `tyre_deg_proxy_seconds_per_lap` 的车手，继续生成车手层 `metric=tyre_deg`；
- 同时按车队聚合这些 proxy，生成 `target_type=team, metric=tyre_deg`；
- 低于全场车队中位衰退的队得到正向 `car.tyre_deg`，高于中位衰退的队得到负向 `car.tyre_deg`；
- confidence 会按 session 权重和该队样本覆盖度折算；
- 解释文本说明来自 practice team tyre-degradation proxy，不写任何车队/车手特判。

真实 British GP 本地数据检查：

```text
features = 551
FastF1 session driver tyre_deg features = 16
FastF1 session team tyre_deg features = 10
BeliefState team tyre_deg ledger rows = 10
```

进入 `BeliefState.car.tyre_deg` 的例子：

```text
audi: +0.019884
williams: +0.016008
racing_bulls: +0.006085
mclaren: +0.001058
ferrari: -0.000601
mercedes: -0.001731
red_bull: -0.001822
aston_martin: -0.009205
```

这些数值来自 Practice 1 里可用的长距离衰退 proxy，与用户判断无关。它们可能不完全符合赛后直觉，所以只能作为来源化状态输入，不能被解释成最终事实。

验证：

```text
.venv\Scripts\python.exe -m compileall -q src scripts
.venv\Scripts\python.exe scripts\fastf1_team_tyre_deg_smoke_test.py
.venv\Scripts\python.exe scripts\source_driven_contract_test.py
.venv\Scripts\python.exe scripts\race_window_pressure_smoke_test.py
```

随后重跑 British GP 1200 次诊断预测，结果几乎没有改变：

```text
Russell win = 0.4825, average_finish = 2.6167
Antonelli win = 0.4400, average_finish = 2.7708
Hamilton win = 0.0458, average_finish = 4.3633
Leclerc win = 0.0125, average_finish = 5.7408
```

这说明本轮不是“预测已经修好”，而是“来源链条补上了一个必要缺口”。这个缺口单独太弱，不能解决 Mercedes 双车胜率集中或 Leclerc 胜率过低。

又用新路由重新跑了 source-weighted team-window pressure 候选：

```text
reports/simulator_calibration_team_tyre_route_v1/2026_asof_20260707T000000_0000.simulator_calibration.md
```

120 次小样本结果：

```text
baseline team_window_v3 composite_score = 2.3688
source_weighted_team_window_pressure_strong composite_score = 2.3961
source_weighted_team_window_pressure composite_score = 2.4036
```

本轮推荐仍然是 baseline，不注册 pressure 候选。British GP 在这个低迭代诊断里仍然失败：

```text
top_pick = Antonelli
actual_winner = Leclerc
actual_winner_probability = 0.0083
actual_winner_rank = 6
```

结论：

- team-level `car.tyre_deg` 路由已经实现并可追溯；
- 这让 `race_window_pressure` 具备真实来源输入，不再只有空的 `tyre_deg` 状态；
- 但当前 practice tyre proxy 信号很弱、样本也不完整，不能单独修正 British GP；
- 下一步应继续补 `team_ops.setup_quality`、调校窗口、长距离稳定性、策略窗口和同周末多 session 聚合；
- 任何默认预测注册仍必须经过 replay/calibration 或模型修订证明，不能因为这条链路“看起来更合理”就注册。

## 28. 2026-07-07：同周末 session 数据进入 `team_ops.setup_quality`

上一节结束后，`team_ops.setup_quality` 仍主要来自弱 seed，真实同周末来源没有进入该状态。这个缺口会让“调校窗口/比赛日窗口”解释仍然不完整：模拟器已经有 `race_window_pressure()` 读取 setup 的入口，但没有可靠来源喂进去。

本轮新增通用来源映射：

```text
FastF1 practice long-run team average
-> target_type=team, metric=setup_quality
-> BeliefState.team_ops.setup_quality

FastF1 qualifying best-lap team average
-> target_type=team, metric=setup_quality
-> BeliefState.team_ops.setup_quality
```

这不是按车队名修数值。规则只看同一 session 内“车队平均秒数 vs 全场车队中位秒数”，并用很小尺度更新 setup 状态。`setup_quality` 也加入了 Codex 研究 metric 合同，未来如果非结构化来源明确说某队调校窗口、平衡、温度窗口问题，也可以走同一个因子，而不是写成散乱文本。

实现位置：

```text
src/f1predict/domain.py
src/f1predict/belief_state.py
src/f1predict/models/pace.py
src/f1predict/features/provider.py
src/f1predict/intelligence/factor_contract.py
src/f1predict/intelligence/factor_trace.py
src/f1predict/intelligence/evidence_workflow.py
src/f1predict/intelligence/research_plan.py
src/f1predict/explanation_localization.py
scripts/fastf1_team_setup_quality_smoke_test.py
scripts/source_driven_contract_test.py
```

特别修正了解释文本。新的 ledger mechanism 不再只写“近期窗口表现被压缩成有界输入”，而是保留来源事实，例如：

```text
来源：结构化特征；
英国大奖赛前调校窗口代理值为 93.774s vs 车队 field 94.257s from 1 车手 sample(s)，
用于更新车队调校窗口质量，并影响正赛速度、排位采样和比赛日窗口风险。
```

真实 British GP 本地数据检查：

```text
features = 571
team setup_quality features = 20
BeliefState setup_quality ledger rows = 20
```

进入 `team_ops.setup_quality` 后的部分状态：

```text
mercedes: +0.025980
red_bull: +0.024317
mclaren: +0.015166
ferrari: +0.005117
racing_bulls: -0.005671
williams: -0.011913
alpine: -0.012366
aston_martin: -0.016489
cadillac: -0.027888
```

这和用户直觉不完全一致，尤其 Mercedes 仍然非常强。因此这里必须强调：这些数值是同周末 FP/Q 秒差代理，不是最终赛车实力结论。它们只说明当前来源链条怎样更新状态。

验证：

```text
.venv\Scripts\python.exe -m compileall -q src scripts
.venv\Scripts\python.exe scripts\fastf1_team_setup_quality_smoke_test.py
.venv\Scripts\python.exe scripts\source_driven_contract_test.py
.venv\Scripts\python.exe scripts\explainability_smoke_test.py
```

British GP 1200 次诊断预测没有修复核心问题：

```text
Russell win = 0.4850, average_finish = 2.6092
Antonelli win = 0.4408, average_finish = 2.7642
Hamilton win = 0.0458, average_finish = 4.3708
Leclerc win = 0.0108, average_finish = 5.7533
```

相对上一版 latest，Leclerc 反而略降：

```text
Leclerc win_delta = -0.0017
Leclerc average_finish_delta = +0.0125
```

这说明 setup 路由没有解决 Ferrari/Leclerc 的 British GP 低胜率问题。

同时做了 120 次小样本 simulator calibration：

```text
reports/simulator_calibration_setup_quality_v1/2026_asof_20260707T000000_0000.simulator_calibration.md
```

和上一轮 `team_tyre_route_v1` 诊断相比，baseline composite 从 `2.3688` 变为 `2.3549`，小幅改善；但这仍然是：

```text
diagnostic_only
in-sample
small_sample_less_than_20_scored_events
market_scored_subset_incomplete
```

所以本轮结论是：

- `team_ops.setup_quality` 的来源化链路已经接通；
- 解释文本已经能展示原始秒差事实，而不是裸分数；
- 小样本整体指标略有改善，但不能作为正式模型优越证据；
- British GP 的 Leclerc/Ferrari 问题仍未解决；
- 下一步应继续补多 session 长距离、真实 race-week 天气/赛道温度、策略窗口和 race execution，而不是继续放大 setup 权重。

## 29. 2026-07-07：当前代码来源映射已同步到 latest run，并补齐 565/565 sidecar

上一节的 `team tyre_deg` 与 `team_ops.setup_quality` 已经进入代码，但当时前端 latest 仍指向旧 run。这样会造成一个危险状态：代码已经能生成 565 条状态更新，前端却仍展示旧 run 的 535 条解释链。为避免“新代码、旧预测包、旧 sidecar”混在一起，本轮做了 latest 同步收口。

首先用当前代码生成候选包，写入独立目录，避免覆盖旧包：

```text
candidate_packet = reports/prediction_packets_current_code_sync/british_gp/british_gp_20260705T000000_0000.prediction_packet.json
candidate_packet_sha = 48a450406e04513887fdda2bd7abde66463d7e6ea98a95f34e5a943ff30fa191
generated_at = 2026-07-07T10:48:24+00:00
iterations = 1200
status = diagnostic_only
```

注册门禁首次阻止了它：

```text
status = model_only_prediction_change_blocked
allow_registration = false
blocker_codes = non_source_driven_prediction_change, state_mapping_revision_proof_required
source_identity_changed = false
belief_state_update_changed = true
race_probability_changed = true
```

这是正确行为。因为这次没有新增原始来源身份，而是同一批 FastF1 结构化来源被新的映射规则送进更多状态字段。随后补充模型/映射修订证明：

```text
reports/model_revision_proofs/2026-07-07_current_code_source_mapping_sync_cn.md
```

证明文件明确记录：这不是根据用户观点手调结果，而是以下通用映射进入状态向量：

```text
FastF1 practice long-run tyre degradation -> team/car tyre_deg
FastF1 practice / qualifying team lap-time proxy -> team_ops.setup_quality
```

带证明后注册成功：

```text
run_id = british_gp_20260705T000000_0000_20260707T104824_0000_48a450406e
belief_state_id = british_gp_ca70e1cb3b_0ec7749e17
state_update_count = 565
feature_count = 571
status = diagnostic_only
registration_gate.status = model_revision_proof_allowed
```

新 run 的前部预测：

```text
1. Russell    win 48.5%, average_finish 2.609
2. Antonelli  win 44.1%, average_finish 2.764
3. Hamilton   win 4.6%,  average_finish 4.371
4. Leclerc    win 1.1%,  average_finish 5.753
5. Piastri    win 0.6%,  average_finish 6.302
6. Norris     win 0.4%,  average_finish 6.311
7. Verstappen win 0.6%,  average_finish 6.633
8. Hadjar     win 0.2%,  average_finish 7.344
```

这再次说明：同步当前代码不是“预测修好了”。Leclerc 的胜率反而从上一版 `1.25%` 降到约 `1.08%`，Mercedes 双车仍然过度集中。因此这次只能被记录为“解释/状态链路同步完成”，不能被包装成预测质量改善。

赛后复盘已同步到新 run：

```text
prediction_run_id = british_gp_20260705T000000_0000_20260707T104824_0000_48a450406e
predicted_winner = russell
actual_winner = leclerc
winner_hit = false
actual_winner_predicted_rank = 4
actual_winner_win_probability = 0.010833
podium_overlap_rate = 0.6667
points_overlap_rate = 0.7
mean_abs_rank_error = 4.6364
```

随后为新 run 重新生成完整同迭代 sidecar：

```text
sidecar_id = british_gp_british_gp_20260705T000000_0000_2026_a5f145fbb3a0_20260707T115527_0000_bb41906fe9
source_run_id = british_gp_20260705T000000_0000_20260707T104824_0000_48a450406e
source_iterations = 1200
trace_iterations = 1200
comparison_status = matched_source_run_iterations
formal_readiness.status = formal_trace_ready
claim_count = 565
covered_claim_count = 565
uncovered_claim_count = 0
trace_count = 576
```

这一步修复了一个实际工程 bug：Windows 默认路径长度限制会让旧的 sidecar 文件名超过 260 字符，导致计算完成后写入失败。现在 `PredictionImpactTraceSidecarStore.write()` 使用更短的文件名，同时 JSON 内仍保留完整 `sidecar_id`。

前端也做了首屏负载收口：

```text
旧请求：/api/v2/prediction-impact-traces/latest?event_id=british_gp&limit=24
新请求：/api/v2/prediction-impact-traces/latest?event_id=british_gp&limit=8&trace_type=isolated_same_seed_leave_one_information&impact_status=material_prediction_change
```

这样首屏只取“单条来源的显著影响 trace”，不再把体积很大的整体 all-updates trace 作为首页解释卡片。覆盖率和 formal readiness 仍从同一个 sidecar 元数据展示。

验证结果：

```text
GET /api/v2/prediction-packets/latest?event_id=british_gp
-> packet_sha = 48a450406e04513887fdda2bd7abde66463d7e6ea98a95f34e5a943ff30fa191
-> state_update_count = 565

GET /api/v2/prediction-impact-traces/latest?event_id=british_gp&limit=1
-> source_run = british_gp_20260705T000000_0000_20260707T104824_0000_48a450406e
-> formal_trace_ready
-> covered = 565 / 565

GET /api/post-event-review?event_id=british_gp
-> prediction_run_id = british_gp_20260705T000000_0000_20260707T104824_0000_48a450406e
```

独立 Playwright CLI 截图验证页面可渲染：

```text
output/playwright/f1predict-latest.png
output/playwright/f1predict-latest-full.png
```

全页截图中可以看到：

```text
1,200 diagnostic sims
Russell / Antonelli / Hamilton / Leclerc 当前排名
解释链覆盖 565 / 565
formal_trace_ready
Simulation Replay
来源影响追踪列表
```

当前结论：

- 最新代码、注册 run、post-event review、full sidecar 和前端展示已经重新对齐；
- 可解释链条在当前 latest run 上再次达到同迭代全覆盖；
- 预测质量问题仍未解决，尤其是 Leclerc/Ferrari 胜率过低、Mercedes 双车过度集中、Antonelli 风险不足；
- 下一步应该继续做通用模型改进和来源补充，而不是再做同步类收尾。

## 30. 2026-07-07：练习赛长距离信号冲突门禁已注册，并补齐 565/565 sidecar

本轮继续追查 British GP 中 Leclerc/Ferrari 被压得过低的问题。定位到一个具体来源映射风险：

```text
FastF1 practice1 long-run proxy
-> 确实进入了 driver race_pace / team race_pace / team_ops.setup_quality
-> 但 fuel load、轮胎配方、run plan、traffic 没有完全归一化
-> 当它和同周末排位结果强烈冲突时，不能用原始置信度强力压低正赛速度
```

这不是按用户判断手调 Leclerc 或 Ferrari。实现采用的是通用质量门禁：

```text
同一条练习赛长距离观测
+ 同周末 FastF1 排位位置
+ 观测方向和幅度
-> 判断是否存在强冲突
-> 若存在冲突，只降低该观测的 confidence
-> 原始来源仍保留在 ledger 和 trace 中
```

代码层面只读取 `target_type`、`target_id`、观测值、同周末排位位置和车队平均排位，不包含任何车手或车队特判。也就是说，规则不是“Leclerc 应该更强”，而是“弱归一化练习赛长距离信号如果和更强的同周末排位证据冲突，就必须降低置信度”。

候选包第一次无证明注册被正确阻断：

```text
status = model_only_prediction_change_blocked
blocker_codes = non_source_driven_prediction_change, state_mapping_revision_proof_required
source_identity_changed = false
belief_state_update_changed = true
race_probability_changed = true
```

随后补充模型/来源映射修订证明后注册为新的诊断 latest：

```text
model_revision_proof = reports/model_revision_proofs/2026-07-07_practice_long_run_conflict_gate_cn.md
run_id = british_gp_20260705T000000_0000_20260707T122518_0000_d225707bdb
packet_payload_sha256 = d225707bdba831e520aff765d5c9535b882d8dbd10edff0386e84a424ec309c1
belief_state_id = british_gp_ca70e1cb3b_5c1d96c830
state_update_count = 565
status = diagnostic_only
registration_gate.status = model_revision_proof_allowed
```

预测变化是小幅修正，不是质量达标：

```text
上一版 latest:
Russell win = 48.50%
Antonelli win = 44.08%
Hamilton win = 4.58%
Leclerc win = 1.08%

本版 latest:
Russell win = 47.75%
Antonelli win = 43.75%
Hamilton win = 5.33%
Leclerc win = 1.58%
```

Leclerc/Ferrari 的方向有所缓和，但仍明显偏低；Mercedes 双车仍过度集中；Antonelli 的下行尾部仍不足。因此这次只能称为“来源质量映射修正”，不能称为预测模型已修好。

为新 run 重新生成并合并 full sidecar：

```text
sidecar_id = british_gp_7db773a15fb8_20260707T131516_0000_merged_239e821a3d
source_run_id = british_gp_20260705T000000_0000_20260707T122518_0000_d225707bdb
source_iterations = 1200
trace_iterations = 1200
comparison_status = matched_source_run_iterations
claim_count = 565
covered_claim_count = 565
uncovered_claim_count = 0
trace_count = 576
formal_readiness.status = formal_trace_ready
```

API 验证显示前端 latest 已经重新对齐：

```text
GET /api/v2/prediction-packets/latest?event_id=british_gp
-> run_id = british_gp_20260705T000000_0000_20260707T122518_0000_d225707bdb
-> state_update_count = 565
-> anomaly_audit_sidecar = british_gp_7db773a15fb8_20260707T131516_0000_merged_239e821a3d

GET /api/v2/prediction-impact-traces/latest?event_id=british_gp&limit=1
-> formal_trace_ready
-> covered = 565 / 565
-> trace_count = 576

GET /api/post-event-review?event_id=british_gp
-> prediction_run_id = british_gp_20260705T000000_0000_20260707T122518_0000_d225707bdb
-> predicted_winner = russell
-> actual_winner = leclerc
-> actual_winner_predicted_rank = 4
-> actual_winner_win_probability = 0.015833
```

当前边界：

- 解释链条再次完整；
- 前端/API 已经能读取新 run 的 full sidecar；
- 预测仍是 `diagnostic_only`；
- 这不是正式 edge；
- 下一步仍应优先做历史 replay/calibration、赛车实力权重、随机事件尾部和前几站状态递推，而不是继续靠单站局部修正。

## 31. 2026-07-07 追加：BeliefState 复盘显示错误热门来自状态路由放大，候选配置暂不注册

本轮关机前补了一项诊断完整性修正：`model-error-review` 现在会从预测包的 `belief_state` JSON 中复原 `BeliefState`，并使用与预测相同的 `PaceModel` route scale。此前复盘缺少这一步，因此只能看到 race score / feature score 的旧式差值，无法准确解释“哪一路状态把错误热门推高”。

新增诊断字段：

```text
model_state_total
car_state_total
driver_state_total
team_state_total
technical_state_total
diagnosis_code = belief_state_favored_top_pick
```

新的回放错误复盘结果：

```text
report = reports/model_error_review/2026_asof_20260707T000000_0000.model_error_review.md
reviewed_events = 9
missed_events = 3
top_pick_hit_rate = 66.67%
actual_winners_ranked_top3 = 8
mean_actual_winner_probability = 35.42%
mean_state_gap_on_misses = 0.5921
belief_state_favored_top_pick = 3
```

British GP 的核心错误仍然没有解决：

```text
top_pick = russell
actual_winner = leclerc
actual_winner_rank = 4
top_pick_probability = 46.67%
actual_winner_probability = 1.25%
race_score_gap_top_minus_actual = +0.5874
state_gap_top_minus_actual = +0.9884
```

这说明当前模型不是只差前端展示，而是 BeliefState 里的车队/赛车/车手状态和 race pace 路由确实把错误热门推得过高。

为避免再次用一次性脚本试模型，本轮给 CLI 增加了候选配置入口：

```text
prediction-packet --simulator-config-id <candidate>
predict --simulator-config-id <candidate>
```

默认配置没有改变，当前 registered latest 没有被替换。

本轮候选校准结果：

```text
report = reports/simulator_calibration_belief_route_scale_v1/2026_asof_20260707T000000_0000.simulator_calibration.md
baseline = default_pace_separation_track_position_team_window_v3
candidate = belief_state_damped_wider_race_variance
baseline composite score = 2.2872
candidate composite score = 2.2478
baseline hit rate = 66.7%
candidate hit rate = 55.6%
baseline mean_actual_winner_probability = 35.4%
candidate mean_actual_winner_probability = 29.9%
baseline log loss = 1.4838
candidate log loss = 1.4463
```

候选配置改善了综合诊断分和 log loss，也把 British GP 的 Leclerc 真实冠军概率从校准表中的 1.25% 提高到约 2.92%。但它同时降低了 top-pick hit rate 和真实冠军平均概率，并且样本只有 9 场，没有留出集。因此它只能作为诊断候选，不能注册成 latest，也不能声称模型已修复。

独立候选预测包：

```text
path = reports/prediction_packets_belief_route_scale_probe/british_gp/british_gp_20260705T000000_0000.prediction_packet.json
config = belief_state_damped_wider_race_variance
iterations = 600
status = diagnostic_only
registered_latest = false
```

与当前 latest 的 British GP 胜率对比：

```text
当前 latest:
Russell = 47.75%
Antonelli = 43.75%
Hamilton = 5.33%
Leclerc = 1.58%

候选配置:
Russell = 38.83%
Antonelli = 36.50%
Hamilton = 11.67%
Leclerc = 5.17%
```

判断：

- 候选配置方向上缓解了 Mercedes 双车过度集中和 Leclerc 尾部概率过低；
- 但 Leclerc 仍然只有第 4，说明 Ferrari/近期状态/正赛随机性/赛道适配的结构性建模仍不足；
- 候选配置不能上线，只能作为下一轮正式 calibration 的候选；
- 后续需要把“赛车实力递推”和“随机事件尾部”作为核心建模任务，而不是继续做 British GP 单站局部修正。
