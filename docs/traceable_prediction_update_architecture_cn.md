# 全流程可追溯预测更新架构设计

生成日期：2026-07-06

这份文档回答一个核心问题：

```text
一条原始非结构化信息，怎样可信地改变模型对赛车、车手、车队、赛道和比赛情境的判断，
又怎样证明它最终改变了每个车手的预测排名和概率？
```

它不是“给每条信息加来源和置信度”这么简单。真正需要的是一条完整链路：

```text
原始信息
-> 信息抽取
-> 事实/观点/机制拆分
-> 因子本体映射
-> 质量审计
-> 状态向量更新
-> 模拟参数更新
-> 预测结果改变
-> 前端可解释展示
```

## 1. 设计原则

第一，Codex/LLM 不直接给出“谁会赢”。它的职责是把网页、新闻、采访、技术分析、社交媒体、图片说明、赛事文档等非结构化材料，变成有来源、有机制、有适用范围的结构化信息。

第二，所有预测都先经过“状态向量”，不能让新闻直接改胜率。例如“Mercedes ERS 很强”不能直接写成 George Russell 胜率增加，而应该先进入 `CarPerformanceState.ers_deployment`、`CarPerformanceState.clipping_risk` 等字段，再由赛道需求和模拟器决定它对本场比赛的影响。

第三，每次信息更新都必须留下 before/after。系统必须能回答：

```text
这条信息进入前，模型认为 Mercedes ERS 状态是什么？
这条信息进入后，状态变成什么？
为什么变这么多？
它影响了哪些模拟参数？
同种子重跑后，哪些车手的排名分布发生了变化？
如果没有变化，为什么没有变化？
```

第四，没有来源、没有机制、没有时间戳、没有独立佐证的信息，只能作为弱提示或待复核，不允许强力改变预测。

第五，前端解释不能展示裸的内部权重。可以展示的是：事实、来源、方向、幅度等级、状态变化原因、预测差异结果。

第六，用户举例只能作为错误发现信号，不能作为训练标签或手动调参依据。如果用户指出“某队明显不该排这么高”，系统应该检查信息源、状态更新和模型映射，而不是写入某队/某车手的定向补丁。预测代码里不允许出现按具体车队或车手 id 改变预测结果的特判；实体事实必须进入数据层或证据层，并带来源、时间、质量审计和状态更新记录。

第七，`seed://` 场景包只能用于开发期链路测试和审计占位，不能当作外部事实来源。默认预测中，seed 场景 claim 必须被质量门控标记为 `seed_scenario_source`，模型输入权重为 0，状态更新权限为 `blocked`。只有替换成真实 source log、归档原文、发布时间和可复核证据后，才允许改变预测。

第八，模型权重和模拟常数也不能因为用户一句话直接调整。即使调整是通用的、没有写死某个车队或车手，也必须有来源化证据、历史回放校准、同口径 diff 或参数学习报告支持。否则只能标为 diagnostic probe，不能注册成默认 latest，也不能在前端呈现为正式预测改进。

第九，`PredictionRunRegistry` 必须有注册守门机制。只要候选 run 相对最新 run 改变了正赛概率或排名，但 `evidence_fingerprint` 和 `BeliefState.update_fingerprint` 都没有变化，就说明这次变化不是由新来源、新状态更新或新的来源映射链条驱动的。这类变化默认只能保留为未注册诊断 packet，不能成为前端 latest。只有显式提供模型修订证明，例如历史回放校准报告、参数学习报告或同口径实验报告，才允许注册为“模型修订诊断 run”；即便如此，也不能把它解释成“新增信息导致预测改变”。

这条守门规则不是为了禁止模型迭代，而是为了防止一种最危险的退化：用户指出一个直觉问题后，系统通过改模拟常数让排名看起来更顺眼，然后把它注册成最新预测。正确做法仍然是让变化先进入来源、结构化特征、质量审计、状态更新和 impact trace。

2026-07-06 追加实现状态：默认 prediction packet 已经把 `seed://`/`test://` 开发期证据从公开 `evidence`、`evidence_quality`、`factor_trace` 和 `belief_state.raw_sources` 中分离出去，只保留在 `blocked_development_evidence` 审计区。这样前端和解释 API 展示的“预测依据”只包含真实来源或结构化特征链条；开发 seed 只能说明曾经存在一个被阻断的占位假设，不能被解释成预测变化来源。

## 2. 总体链路

```mermaid
flowchart TD
    A["RawSourceRecord<br/>网页/新闻/采访/数据文件/图片"] --> B["SourceArchive<br/>原文、截图、哈希、cutoff"]
    B --> C["LLM Extraction<br/>候选事实、观点、机制、时间"]
    C --> D["Claim Normalizer<br/>映射到因子本体"]
    D --> E["Evidence Quality Gate<br/>来源、时效、独立性、冲突、机制质量"]
    E --> F["State Update Engine<br/>可信状态向量更新"]
    F --> G["BeliefState Snapshot<br/>车/车手/车队/赛道/环境状态"]
    G --> H["Race Simulation<br/>完整排名分布模拟"]
    H --> I["PredictionRunRegistry<br/>注册预测运行"]
    F --> J["Update Ledger<br/>记录每条信息如何改变状态"]
    I --> K["MatchedPredictionDiff<br/>同口径 before/after 对比"]
    J --> L["Impact Trace<br/>信息->状态->预测变化"]
    K --> L
    L --> M["Frontend Explanation<br/>中文可追溯解释"]
```

## 3. 需要新增的核心对象

### 3.1 RawSourceRecord

记录原始信息本身。

```python
RawSourceRecord:
    source_id
    source_type              # article, interview, timing_data, official_doc, image, social, video_transcript
    url
    title
    publisher
    author
    published_at
    captured_at
    knowledge_cutoff
    raw_text_path
    raw_html_path
    screenshot_path
    archive_url
    content_hash
    license_or_terms_note
```

它解决的问题是：以后不能只说“Codex 看到了某条新闻”，必须能回到原始材料。

### 3.2 ExtractedInformationUnit

LLM 从原始信息中提取出的最小信息单元。

```python
ExtractedInformationUnit:
    unit_id
    source_id
    extracted_at
    original_snippet
    paraphrase_zh
    information_type         # fact, quote, technical_claim, rumour, analysis, timing_observation
    target_text              # 原文中的目标对象
    time_scope               # 本站、最近几站、赛季初、长期
    certainty_language       # confirmed, likely, suggested, rumour
    llm_extraction_confidence
```

它解决的问题是：LLM 先抽取信息，不急着决定它对预测有多大影响。

### 3.3 NormalizedFactorClaim

把信息映射到统一因子本体。

```python
NormalizedFactorClaim:
    claim_id
    unit_id
    event_id
    target_type              # team, driver, car, event, track
    target_id
    factor                   # ers_deployment, tyre_deg, qualifying_pace...
    direction                # positive, negative, neutral
    magnitude_observation    # weak, medium, strong 或结构化观测值
    mechanism                # 为什么这个信息会影响该因子
    applicable_context       # high_speed_track, cold_weather, low_grip, wet_race...
    valid_from
    valid_until
    decay_policy
    extraction_status        # accepted, needs_review, rejected
```

这里要避免“泛泛乐观”。例如：

```text
错误：Red Bull 最近看起来更好了 -> Red Bull 胜率 +X
正确：Red Bull 最近两站低速牵引和轮胎窗口改善 -> low_speed_traction +，tyre_warmup +，适用于低速/中速弯多、低温窗口明显的赛道
```

### 3.4 EvidenceQualityProfile

质量审计不只是一句 confidence。

```python
EvidenceQualityProfile:
    claim_id
    source_reliability       # 来源历史可信度
    source_proximity         # 一手/二手/转述/猜测
    timestamp_validity       # 是否在 cutoff 前，是否过期
    specificity_score        # 是否具体到车队/部件/赛道/时间
    mechanism_score          # 是否解释了作用机制
    triangulation_score      # 是否有独立来源佐证
    conflict_score           # 是否与其他来源冲突
    data_support_score       # 是否被 timing/result 数据支持
    recency_weight           # 最近几站信息权重更高
    review_required
    model_update_permission  # blocked, weak_update, normal_update, strong_update
    reasons
```

这一步决定信息是否允许改变预测状态。

### 3.5 BeliefState

这是模型真正使用的“当前世界状态”。所有来源和信息最终都要更新这里，而不是直接更新胜率。

```python
BeliefState:
    state_id
    event_id
    knowledge_cutoff
    generated_at
    track_state
    car_states
    driver_states
    team_ops_states
    event_risk_state
    source_fingerprint
    update_fingerprint
```

#### CarPerformanceState

```python
CarPerformanceState:
    team_id
    overall_pace
    qualifying_pace
    race_pace
    high_speed_corner
    medium_speed_corner
    low_speed_corner
    traction
    mechanical_grip
    aero_efficiency
    drag
    straight_line_speed
    power_unit_peak
    ers_deployment
    ers_recovery
    clipping_risk
    cooling_margin
    tyre_deg
    tyre_warmup
    dirty_air_sensitivity
    setup_window_width
    reliability
    upgrade_delta
```

#### DriverPerformanceState

```python
DriverPerformanceState:
    driver_id
    qualifying_ceiling
    qualifying_consistency
    race_pace
    long_run_consistency
    tyre_management
    tyre_warmup
    wet_skill
    attack_racecraft
    defense_racecraft
    first_lap_gain
    incident_risk
    penalty_risk
    setup_feedback
    car_fit_understeer
    car_fit_oversteer
    team_priority
```

#### TeamOpsState

```python
TeamOpsState:
    team_id
    strategy_quality
    pit_stop_mean
    pit_stop_variance
    pit_wall_risk
    development_rate
    upgrade_correlation
    setup_quality
    internal_conflict_risk
```

## 4. 可信状态更新机制

### 4.1 状态不是一次性手填，而是逐步更新

每个状态字段都有三个值：

```python
StateFactor:
    value                   # 当前估计
    uncertainty             # 不确定性
    provenance              # 哪些 update 形成了它
```

初始 seed 只能是弱 prior。之后每场比赛、每次练习赛、每次新闻、每次排位都会形成新的 update。

### 4.2 更新分成两类

第一类是结构化观测更新，例如：

- 最近 3-5 站积分；
- 排位名次；
- 排位圈速差距；
- 练习赛长距离；
- speed trap；
- stint degradation；
- DNF/penalty/pit stop 数据。

这类信息可以形成比较强的更新，因为它直接来自比赛数据。

第二类是非结构化信息更新，例如：

- 技术分析；
- 车队采访；
- 升级包评价；
- 车手反馈；
- 媒体 paddock rumor；
- 工程师或记者的赛道适配判断。

这类信息必须经过质量审计和机制映射，通常不能单独强力改变状态，除非来源强、机制清晰、被其他数据佐证。

### 4.3 建议的更新公式

每个 claim 先转成一个观测：

```text
observation_delta = direction_sign * magnitude_scale
update_strength = source_quality * specificity * mechanism * recency * triangulation * conflict_penalty
bounded_delta = clamp(observation_delta * update_strength, -factor_cap, +factor_cap)
new_value = old_value + bounded_delta
new_uncertainty = update_uncertainty(old_uncertainty, update_strength, conflict_score)
```

这不是为了让前端展示公式，而是为了保证更新有边界、有原因、可复现。

更成熟版本可以升级成 Kalman-style 更新：

```text
K = prior_uncertainty^2 / (prior_uncertainty^2 + observation_uncertainty^2)
new_value = old_value + K * (observation_value - old_value)
```

但首版建议先用有上限的 delta update，因为更容易审计，也更容易解释。

### 4.4 更新必须记录 ledger

每次更新写入：

```python
StateUpdateLedgerRow:
    update_id
    claim_id
    source_id
    state_id_before
    state_id_after
    target_type
    target_id
    factor
    old_value_bucket
    new_value_bucket
    direction
    magnitude_bucket
    update_strength_bucket
    update_permission
    quality_reasons
    mechanism
    applicable_context
    affected_model_surfaces
```

前端可以展示 bucket，而不是展示裸的内部小数。

## 5. 从状态更新到预测变化

状态更新本身还不是预测解释。必须证明它怎样改变模拟器输入。

### 5.1 状态到模拟参数的路由

每个 factor 必须有固定路由。

```python
FactorRoute:
    factor
    source_state             # car, driver, team_ops, track, event_risk
    model_surface            # qualifying, race_pace, overtake, tyre, strategy, reliability
    route_formula_id
    track_context_multiplier
    stage_context_multiplier # T-14, FP, Qualifying, Race morning
    explanation_template_zh
```

例子：

```text
ers_deployment
-> race_pace / qualifying_pace
-> 在长直道多、部署区长、ERS 需求高的赛道权重更高
-> 对 Silverstone 这种高速长部署赛道影响更明显
```

```text
tyre_warmup
-> qualifying_pace / first stint pace
-> 在低温、湿地、短 warm-up 窗口下影响更高
```

```text
strategy_quality
-> pit decision / SC window decision / undercut-overcut probability
-> 在安全车概率高、进站损失大、超车困难赛道影响更高
```

### 5.2 预测影响必须用同口径 diff 证明

每次信息摄取后，至少生成三类 run：

```text
base_run:     更新前 belief state
candidate_run: 更新后 belief state
isolated_run: 只应用某条 claim 或某组 claim 的更新
```

所有 run 必须同口径：

- 同 event；
- 同 knowledge cutoff；
- 同 simulation seed；
- 同 iterations；
- 同代码版本；
- 只改变目标信息或目标状态。

然后使用 `MatchedPredictionDiff` 生成：

```python
PredictionImpactTrace:
    impact_trace_id
    update_id_or_group_id
    base_run_id
    candidate_run_id
    isolated_run_id
    changed_factors
    affected_drivers
    finish_distribution_delta
    expected_points_delta
    rank_delta
    probability_delta_bucket
    interpretation_zh
```

这才是“这条信息影响了预测”的证据。

## 6. 用户可读解释应该长什么样

目标解释不是：

```text
Hamilton race score +0.30000，所以更强。
```

目标解释应该是：

```text
来源 A 和来源 B 都提到 Mercedes 在长直道部署和回收上更稳定。
系统把这两条信息映射到 Mercedes 的 ERS 部署能力和 clipping 风险。
因为 British GP 的长直道和高速负载较多，这两个因子会影响排位速度和正赛长距离速度。
质量审计认为这组信息有两个独立来源、机制清楚，但仍缺少官方遥测佐证，因此只允许中等幅度更新。
更新后，同种子重跑预测显示 Mercedes 双车的前排/领奖台分布有小到中等幅度上升。
```

如果模型结果和事实冲突，解释应该是：

```text
可追溯事实不支持这个预测方向。
当前排序主要来自旧 seed prior 或未充分校准的状态更新。
这不是合理预测解释，而是模型风险。
```

## 7. 前端展示设计

前端不应该展示内部权重表。它应该展示四个核心区块。

### 7.1 预测结果

- 每位车手预计排名；
- P1/P2/.../DNF 分布；
- expected points；
- teammate comparison；
- top3/top5/top10/points 概率；
- 当前 run_id、cutoff、数据更新时间。

预计排名和冠军概率必须分开：

- `race_probabilities` 作为全场预计排名表时，必须带 `expected_rank`，并按 `average_finish -> expected_points -> podium -> win` 排列；
- `probability_summary.top_win_probabilities` 作为冠军概率摘要时，才按 `win` 排列；
- 前端不能把冠军概率数组或模拟器内部顺序直接当作 22 名车手预计排名，否则零胜率车手的第 9 名以后展示会错位。

同一规则也适用于回放、校准和错误复盘：

- `top_pick` 可以继续表示冠军概率最高的车手；
- `actual_winner_rank` 必须表示实际冠军在预计完赛排名中的名次；
- `mean_abs_rank_error`、`podium_overlap_rate`、`points_overlap_rate` 必须使用预计完赛顺序；
- 代码层应复用 `race_probabilities_by_expected_rank()`，避免每个模块自己复制排序规则。

也就是说，系统需要同时回答两个不同问题：

```text
谁最可能赢？       -> win probability order
全场预计怎么排？   -> expected finish order
```

历史回放和前端解释不能把前者包装成后者。

### 7.2 本次预测为什么变了

按影响从大到小展示：

```text
信息组：Mercedes ERS/直道效率
来源：2 个独立来源 + 1 个 timing 佐证
状态变化：ERS 部署上调，clipping 风险下调
适用原因：本场为高速长直道赛道
预测变化：Mercedes 双车 expected points 小幅上升
可信状态：可用，但仍需更多遥测/FP 数据确认
```

### 7.3 关键状态向量

只展示 bucket 和解释，不展示内部裸分。

```text
Mercedes 赛车状态：强
证据来源：官方积分榜、最近三站、排位、练习赛、技术信息
主要强项：排位、长直道、ERS、稳定性
主要风险：轮胎窗口、策略波动
```

### 7.4 异常审计

必须主动显示：

- 垫底车队车手被排到中游前列；
- 同队排位更好者预测明显更差；
- 近期表现强的车队被模型压低；
- 预测变化来自无来源先验；
- 信息更新没有改变预测。

这部分很重要，因为它能阻止系统继续为错误预测找借口。

## 8. 与现有模块的关系

现有模块可以保留，但需要改变职责：

| 当前模块 | 保留方式 | 下一步改造 |
|---|---|---|
| `InformationIntakeStore` | 继续记录信息摄取快照 | 增加 raw source、extracted unit、normalized claim、quality profile |
| `PredictionRunRegistry` | 继续登记 run | 增加 belief_state_id、update_fingerprint、model_version |
| `MatchedPredictionDiff` | 继续做同口径差异 | 增加按 update/claim/factor 分组的影响报告 |
| `EvidenceClaim` | 保留为兼容层 | 拆成 RawSource -> ExtractedUnit -> NormalizedFactorClaim |
| `FeatureAdjustment` | 保留结构化数据入口 | 增加来源链和状态更新 ledger |
| `FactorTrace` | 保留路由审计 | 不再作为前端解释主语，只作为内部路由证明 |
| `PaceModel` | 需要重构 | 从 BeliefState 读取状态，不直接吃 seed 静态 prior |
| `PredictionExplainer` | 保留 | 改为读取 ImpactTrace，而不是反推内部 score |

## 9. 落地阶段

### P0：把链路打通

交付目标：

- 新增 RawSourceRecord、ExtractedInformationUnit、NormalizedFactorClaim、StateUpdateLedgerRow 的 schema；
- InformationIntakeStore 能保存完整链路；
- 每条 claim 都能追溯到原始 source；
- 没有来源的 seed prior 自动标记为 `unsupported_static_prior`。

验收：

```text
任意前端解释中的一句话，都能回到原始 source_id 和 claim_id。
```

### P1：可信状态更新引擎

交付目标：

- 新增 BeliefState；
- 实现有上限的 delta update；
- 每次 update 记录 before/after；
- 支持按 source、claim、factor、target 分组查看更新。

验收：

```text
新增一条 Mercedes ERS 信息后，可以看到它怎样改变 Mercedes car_state，
也可以看到为什么没有直接改变某个车手胜率。
```

### P2：预测影响追踪

交付目标：

- 每次信息更新后自动跑 same-seed before/after；
- 生成 PredictionImpactTrace；
- 记录哪些车手的 expected finish、points、podium、rank distribution 变化；
- 如果没有变化，也记录 no_material_prediction_change。

验收：

```text
任何信息更新都不能只停留在“已摄取”。
它必须有 impact trace：有影响、无影响、被阻塞、或待复核。
```

### P3：重构模型输入

交付目标：

- `PaceModel` 不再直接使用强静态 seed prior；
- car/team/driver/track 状态从 BeliefState 读取；
- 最近 3-5 站、FP、Qualifying、官方积分榜等结构化信息作为强状态更新；
- 非结构化信息通过质量门控后作为有边界更新。

验收：

```text
如果 Aston Martin 最近和同周末数据都很弱，旧的 Alonso/车手经验先验不能把他抬到不合理位置。
如果 Racing Bulls 最近几站明显变强，状态向量和预测排序必须能反映这种变化。
```

### P4：前端重做

交付目标：

- 显示当前 run；
- 显示本次预测相比上次的变化；
- 显示影响最大的 source/claim/factor；
- 显示异常审计；
- 不展示裸内部权重。

验收：

```text
用户能从前端看到：
为什么预测变了、哪些信息导致变化、这些信息可信到什么程度、模型哪里仍然可疑。
```

## 10. 最终验收标准

这个架构完成后，每次预测必须能回答六个问题：

1. 这次预测用了哪些原始信息？
2. 每条非结构化信息被 LLM 抽取成了什么 claim？
3. 每个 claim 映射到了哪个赛车/车手/车队/赛道因子？
4. 质量审计为什么允许或阻止它更新模型状态？
5. 它具体改变了哪个状态向量？
6. 同口径重跑后，它怎样改变了每个车手的排名分布和概率？

如果任意一环断掉，这条信息就不能被前端当作预测原因展示。
## 11. Sidecar 化的全量影响追踪

默认预测包不应该无限膨胀。完整解释链需要覆盖每一条来源化状态更新，但每条更新都做同种子隔离重跑会产生大量 trace。因此架构上把 `PredictionImpactTrace` 拆成两层：

1. 主 prediction packet：只保存少量快速 trace 和覆盖率字段，用于页面首屏、异常审计和快速问答。
2. impact trace sidecar：保存完整或更大范围的隔离重跑结果，按页读取，作为“这条信息是否真的改变预测”的审计证据。

sidecar 必须记录：

- 它解释的源 `run_id`；
- 源 run 的 input/evidence/probability fingerprint；
- sidecar 生成时的迭代数；
- 迭代数是否与源 run 匹配；
- 覆盖了多少 claim / state update；
- 每条 trace 的来源 claim、影响的状态因子、受影响车手、预测分布变化和解释文本。
- `formal_readiness`：明确它是否已经满足“同源 run 迭代数 + 全覆盖”的正式解释条件。

分页返回时，每条 trace 还必须尽量生成一条面向人的中文链路：

```text
原始来源 -> 信息分析 -> 状态更新 -> 模拟路由 -> 预测变化
```

其中“原始来源”来自 `RawSourceRecord`，“信息分析”来自 claim/evidence/quality/factor trace，“状态更新”来自 update ledger，“模拟路由”来自 factor route 或 update ledger 的 `affected_model_surfaces`，“预测变化”来自同种子 before/after 或 leave-one-information rerun。当前如果 trace 是整体聚合行，可能只有“预测变化”阶段；如果是单条 claim/source 行，必须展示完整链路或明确说明缺失哪一段。

每条影响 trace 还必须说明“为什么和用户问题相关”。相关性至少分四类：

- `direct_target`：来源或状态更新直接作用于所问车手/车队；
- `event_context`：来源作用于本场比赛环境，例如天气、安全车、赛道温度；
- `global_baseline`：完整状态相对初始状态的整体对比；
- `indirect_competition`：来源作用于竞争对手，但因为排名和概率是全场联合分布，所以间接改变了所问车手。

前端和自然语言解释必须优先展示 `direct_target` 和 `event_context`。`indirect_competition` 可以展示，但必须写明“这不是直接支持所问对象的来源”。否则系统会把“Mercedes 变强导致 Ferrari 分布变化”误写成“Mercedes 来源解释 Ferrari/Leclerc 状态”，这会破坏可解释性。

这解决的是可追溯性问题，不是预测质量问题。只有当 sidecar 使用与源 run 相同的输入、知识截止、随机种子策略和迭代数时，才能把某条 trace 作为更强的影响解释。低迭代 sidecar 只能叫诊断，不能叫正式 ablation 或正式效果证明。

异常审计也必须 sidecar-aware：如果主 prediction packet 只内嵌 top-N trace，但同一个 `run_id` 已有完整 sidecar，前端/API 的异常审计应该使用 sidecar 覆盖证据，而不是继续把“主包内嵌 trace 少”报告成解释链缺失。历史 packet 文件仍保持不可变；API 可以运行时刷新审计视图，但不能借此改变预测概率或排名。

前端/API 必须把 `formal_readiness.formal_ready = false` 的 sidecar 明确展示为诊断解释。即使它已经覆盖 453/453 条更新，只要 `trace_iterations != source_iterations`，就不能写成“正式同口径解释已完成”。这条规则用于防止把快跑 smoke 结果包装成正式证据。

截至 2026-07-06 12:36 UTC，最新 British GP 注册 run 已生成同源 run 迭代数的 sidecar：`trace_iterations = source_iterations = 1200`，覆盖 `453/453` 条状态更新，`formal_readiness.formal_ready = true`。这只表示“解释链条已经同口径可审计”，不表示预测概率已经通过校准或盈利 edge 验证；预测包状态仍必须继续显示 `diagnostic_only`，直到历史回放和概率校准门通过。

正式同迭代 sidecar 允许分块生成。生成接口可以用 `isolated_impact_offset` 和 `isolated_impact_limit` 只重跑一段 claim，例如第 0-49 条、第 50-99 条。分块 sidecar 必须标记 `trace_generation.chunk_mode = true`，并且 `formal_readiness.full_coverage = false`，直到所有分块被合并并覆盖全部 claim。这样可以把昂贵的 1200 次迭代全量 trace 变成可恢复任务，而不是一次性不可控长跑。

分块合并也必须是显式步骤：`POST /api/v2/prediction-impact-traces/merge` 或 `merge-prediction-impact-trace-sidecars` CLI 会读取多个 chunk sidecar，按 `claim_id` / 来源组去重，重新计算 coverage，并把结果标记为 `merge_status = merged_chunks`。如果只合并了部分 chunk，`formal_readiness.formal_ready` 仍然必须是 `false`；只有同迭代且全覆盖的合并结果才能成为正式解释 sidecar。

用户指出“某个车队不合理”时，正确动作仍然是：

```text
检查来源数据是否缺失
-> 检查信息是否被映射到正确状态因子
-> 检查 sidecar 中该信息是否覆盖并产生合理方向
-> 如果没有，修改通用映射或通用模拟机制
-> 重新生成 run/diff/sidecar
```

错误动作仍然是：

```text
因为用户说某队应该更强/更弱，所以在代码里写死该队数值。
```

## 11.4 列表型来源必须处理观测截断

F1 里很多结构化来源不是完整实力观测，而是被规则截断后的结果。例如分站积分和车队积分只奖励前十名，不能完整区分第 11 到第 22 名的赛车状态。如果直接把“最近积分少”映射为“车一定很慢”，模型会系统性压低经常在第 11-15 名附近完赛的中游队，并且把它们和真正垫底、长期第 18-22 名的队混在一起。

因此同类列表数据必须先做来源语义审计：

```text
来源原始字段
-> 这个字段是否只覆盖前十/前三/完赛车手/有转播镜头的车手
-> 如果存在观测截断，寻找同源或近源的完整排序补充
-> 将截断信号与完整排序信号合成状态更新
-> 在解释中说明哪个部分来自积分，哪个部分来自全场完赛/排位/练习分类
```

2026-07-06 的 British GP 修正采用了这个原则：`fastf1_team_strength_reestimate` 仍读取赛季和近期每站积分，但当积分信号为负、而同一批 FastF1 全场完赛分类显示该队没有那么差时，会用一个统一公式缓和负向积分信号。这个规则按所有车队统一计算，不读取用户对某个车队的主观判断，也不写死 Racing Bulls、Audi、Aston Martin 或 Cadillac 的目标排名。

这类修正必须满足三条审计条件：

1. 解释文本必须写清楚“积分是 top-ten-censored”，以及用于缓和的完整排序来源是什么。
2. `MatchedPredictionDiff` 必须显示概率或排名是否真的改变；没有改变就不能宣称预测被修正。
3. 新 run 若要成为 latest，必须通过 `PredictionRunRegistry`：来源/输入/BeliefState 或模型修订证明必须发生变化，不能只因为用户举例而改变数值。

## 14. 用户反馈与真实证据的边界

用户反馈是项目方向和错误发现信号，不是预测证据。系统必须把这两类东西分开：

```text
用户反馈：
“这个排名明显不合理”
“某个车队近期走势没有体现出来”
“解释里出现了不可解释分数”

作用：
触发审计、补来源、检查状态更新、检查模型映射、检查前端解释

不能做的事：
直接改变车手/车队分数
直接写入状态向量
作为 evidence claim 更新模型
```

代码层对应规则：

- `user://`、`user-feedback://`、`codex-feedback://`、`prompt://` 来源只能被识别为 `user_feedback_source`；
- `user_feedback_source` 的 `model_input_weight` 必须是 0；
- `BeliefState` 对这类来源的 `model_update_permission` 必须是 `blocked`；
- 解释层必须说明它只能触发审计，不能更新预测；
- 契约测试必须覆盖“高置信度、大幅度的用户反馈 claim 仍然不能入模”。

真正允许改变预测的是：

```text
真实来源或结构化数据
-> 原文/数据快照
-> cutoff 审计
-> 信息抽取
-> 因子映射
-> 质量评分
-> 状态更新
-> 同种子影响 trace
-> 注册门禁
```

这条边界的目的不是忽略用户判断，而是避免把用户判断偷换成模型证据。用户判断越尖锐，越应该促使系统去找更完整、更可靠、更可追溯的信息，而不是手动调数。
