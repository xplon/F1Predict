# 预测结果影响审计：30 小时工作是否真的改变了预测

生成日期：2026-07-05

这份文档专门回答三个问题：

1. 如何证明每个小时完成的内容都是有效的；
2. 每个小时的改动是否真的修正了预测结果；
3. 为什么你在前端看起来很久没有看到预测结果变化。

结论先说在前面：**目前不能证明每个小时的工作都有效，也不能证明每个小时的改动都影响了最终预测结果。** 当前仓库没有 git 提交历史、没有逐小时 prediction snapshot、没有每次改动前后的概率 diff，也没有“同一 cutoff 下的信息摄取策略对照实验”。因此，如果按实验完整性标准，过去 30 小时里“可被严格证明的预测结果修正次数”是 **0 次**。

这不等于所有工作都无效。它的意思是：有些代码路径现在确实会影响预测，但当时没有建立“每次修改都重新跑同一批预测并记录差异”的审计机制，所以不能事后把每小时工作和预测提升一一对应。

## 1. 当前可以证明什么，不能证明什么

### 可以证明的事

当前代码里确实存在会进入预测的因素：

- 车队基础实力、可靠性、策略能力；
- 车手基础能力、排位能力、缠斗能力、保胎能力、雨战能力；
- 赛道类型和车队赛道适配；
- wet probability；
- power unit、energy recovery、straight-line speed、drag efficiency、low-speed traction、launch performance、weight、upgrade effect；
- tyre degradation；
- safety car、pit stop、pit loss、reliability/DNF；
- Codex evidence claim 到 factor trace 的路由；
- market snapshot 只用于差异分析，不应直接训练预测。

当前 British GP prediction packet 显示：

- `factor_route_counts = {'race_start_launch': 1, 'track_contextual_pace': 3, 'tyre_degradation': 1, 'wet_weather': 1}`
- `factor_trace_count = 6`
- `simulation_replay rows = 312`
- `race_probabilities rows = 22`
- Codex 因子最大单项胜率影响大约在 0.7-0.8 个百分点量级。

当前 replay 报告显示：

- 8 场已完成比赛被 replay；
- top pick 命中 3 场；
- hit rate 为 0.375；
- actual winner 平均胜率为 0.2524；
- formal edge 仍未 ready。

### 不能证明的事

现在不能证明：

- 第 1 小时改动让预测提升多少；
- 第 2 小时改动让预测提升多少；
- 任何一个小时的改动是否提高了 top pick hit rate；
- Codex 检索/归一化得到的非结构化信息，相比只用结构化公开数据和历史结果，是否有正向 lift；
- 技术因素加入后是否显著改善 Brier/log loss；
- 前端上每次看到的概率是否对应最新后端代码；
- 预测结果在 30 小时中一共“有效修正”了多少次。

原因不是理论上不能做，而是当时没有做以下记录：

- 每次预测前后的 JSON 归档；
- 同一 event、同一 cutoff、同一 seed、同一 iterations 下的 probability diff；
- 每次代码改动对应的 git commit；
- 每次 smoke/replay 的 metrics artifact；
- 结构化公开数据 baseline；
- Codex technical factor ablation；
- 前端展示版本和后端 artifact hash。

## 2. 预测结果修正在 30 小时里一共发生了多少次

严格答案：**可被证明的次数是 0 次。**

更宽松的工程解释：

- 预测相关代码确实被改过，例如 `pace.py`、`simulator.py`、`technical_factors.py`、`factor_trace.py`、`pipeline.py`、seed evidence、weather profiles、track/circuit profile 接入等；
- 这些改动理论上会改变重新运行后的预测；
- 但没有保存“改动前预测”和“改动后预测”的成对 artifact；
- 因此不能把它们算成已证明的预测修正。

如果一定要分类，我会这样归因：

| 类型 | 是否影响预测输出 | 当前是否有严格证据 | 说明 |
|---|---:|---:|---|
| pace/simulator/technical_factors 改动 | 会 | 没有逐次 diff | 会改变重跑后的概率，但没有成对记录 |
| seed driver/team strength 改动 | 会 | 没有逐次 diff | 会明显改变预测，但没有版本化 |
| evidence/factor trace 改动 | 部分会 | 只有最终 trace | 有最终 factor trace，但缺少前后对照 |
| track asset 修复 | 通常不直接影响预测 | 有资产审计 | 主要影响前端视觉，除非 geometry metrics 被用于 track demand |
| MVP gate/completion audit/readiness 文档 | 不直接影响预测 | 有报告 | 影响审计和交付边界，不改变概率 |
| 前端面板和展示 | 不直接影响预测 | 有代码和截图 | 只改变展示，不改变模型 |

所以过去 30 小时不是“每小时都在修预测结果”。相当一部分时间是在修数据通道、审计、前端展示、报告、边界声明和回归测试。

## 3. 你看到前端预测结果很久没变，最可能是哪种情况

你提出了三种情况：

### 情况一：每个小时新实现的内容修正了预测结果，但是你没发现

这个说法不成立。没有证据支持“每个小时都修正了预测结果”。而且很多工作本来就不影响预测概率，例如：

- MVP gate；
- completion audit；
- readiness intake；
- source replacement queue；
- market readiness；
- replay freeze；
- 前端面板；
- 文档。

这些工作有审计价值，但不会让前端胜率表改变。

### 情况二：很多小时的新实现没有真正影响最终预测结果

这个判断基本成立。

更准确地说：**很多工作没有直接影响最终预测结果，它们影响的是项目可审计性、输入质量检查、前端可视化和 formal edge 边界。**

这部分工作不能说完全无效，但如果你的第一目标是“让预测结果明显更接近真实”，它们不是最高优先级。

### 情况三：预测结果被修正了，但是前端实现很差，没有把最新结果展示出来

这个也部分成立。

当前前端存在这些问题：

- 没有真正前后端分离；
- 没有稳定端口策略；
- 没有前端 build/version；
- 没有 `/api/health`；
- 没有展示当前 prediction artifact hash；
- 没有显示当前 `generated_at`、`as_of`、`iterations` 是否最新；
- completion audit 没进前端；
- 很多 API 面板会重新计算，加载慢；
- 当前复核时 `8811` 已经无法连接，说明服务不是稳定常驻状态。

所以你看到“前端很久没变”，可能同时来自两件事：

1. 很多后端工作本来就不改变最终概率；
2. 前端没有清晰展示“当前加载的是哪一次预测结果”。

## 4. 当前前端显示结果为什么看起来不合理

当前 British GP 的最终 packet 显示前几名胜率大约是：

| 车手 | 胜率 | 登台率 | 预计积分 | 平均完赛 |
|---|---:|---:|---:|---:|
| Antonelli | 0.3380 | 0.7330 | 17.33 | 3.38 |
| Russell | 0.2507 | 0.6657 | 16.24 | 3.35 |
| Verstappen | 0.2210 | 0.6293 | 15.40 | 4.08 |
| Hamilton | 0.1210 | 0.4660 | 13.31 | 4.67 |
| Norris | 0.0330 | 0.2250 | 10.07 | 5.82 |
| Piastri | 0.0243 | 0.1543 | 9.06 | 6.15 |
| Leclerc | 0.0117 | 0.1073 | 7.91 | 6.93 |

这里有两个问题：

1. 前几名差距有，但中后段概率被压到很低，呈现方式不够解释原因；
2. 这个排序主要被 seed 里的基础实力和少量 Codex evidence 驱动，而不是被完整的真实赛季表现、每站 practice/qualifying、车辆升级、长距离 pace、赛道细节和策略风险驱动。

你指出“赛季初梅奔强、红牛弱、红牛最近两站长进、法拉利是梅奔下第二名”这类判断，在当前系统里并没有被充分结构化为强约束。当前 seed 里确实把 Mercedes base strength 设得最高，但 Red Bull 仍因为 Verstappen 个人能力和部分 track/context 因素保持很高概率；Ferrari 的 Hamilton/Leclerc 分布也受 driver seed 和少量负面 evidence 影响。

这说明当前模型不是完全没有这些因素，而是权重体系和输入体系太粗，无法稳定呈现你认为直观的赛季态势。

## 5. 当前预测架构最核心的问题

### 问题一：输入因素太粗

现在的 `track_type` 和少量 geometry metrics 不能等价于真正的赛道理解。用户真正关心的是：

- 低速弯、中速弯、高速弯；
- 长直道、短直道；
- 26 赛季替代 DRS 的部署区/能量策略区；
- 单个弯角超车概率；
- 全赛道超车概率；
- asphalt roughness；
- track temperature；
- historical weather；
- race start time；
- pit lane loss；
- safety car/red flag profile。

当前系统只覆盖了其中一小部分。

### 问题二：车队/车辆因素太粗

当前有：

- base_strength；
- reliability；
- strategy；
- track_affinity；
- power_unit；
- energy_recovery；
- straight_line_speed；
- low_speed_traction；
- drag_efficiency；
- weight；
- upgrade_effect。

但缺：

- turbo/engine deployment profile；
- ERS clipping model；
- chassis balance；
- mechanical grip；
- aero efficiency map；
- understeer/oversteer tendency；
- setup window；
- tyre warm-up/cooling sensitivity；
- high/low temperature performance；
- high/low altitude performance；
- upgrade reliability/validation；
- factory/team development curve。

### 问题三：车手因素太粗

当前有：

- base_skill；
- qualifying；
- racecraft；
- tyre_management；
- wet_skill；
- reliability_modifier。

但缺：

- driver-car fit；
- oversteer/understeer preference；
- long-run pace stability；
- tyre warm-up；
- qualifying ceiling vs race floor；
- wheel-to-wheel aggression and risk；
- mental state；
- team priority/no.1 status；
- internal politics；
- ability to direct setup/development；
- age/development curve。

### 问题四：随机事件太粗

当前模拟有：

- wet race；
- safety car lap；
- pit stop plan；
- reliability/DNF；
- lap noise。

但缺：

- VSC/黄旗分段；
- 免费进站窗口；
- red flag；
- restart；
- first lap incident；
- traffic/dirty air；
- overtake difficulty by corner/straight；
- pit crew error；
- strategy split；
- tyre compound availability；
- tyre wear distribution；
- track evolution；
- penalty/unsafe release。

### 问题五：没有明确 baseline/ablation

现在最大的问题不是“又少一个面板”，而是没有下面这三组对照：

- 结构化公开数据 baseline：只用赛程、结果、练习/排位、天气、赛道、历史表现，不使用 Codex 检索到的非结构化新闻；
- Codex 信息摄取版本：在 baseline 上加入 Codex 检索、筛选、归一化的非结构化信息；
- Codex 技术因子版本：只检验 Codex 信息中被映射到车辆/赛道/车手技术 ontology 的部分。

这里不能叫“无 Codex 也完整预测”，因为 Codex 的职责就是把网上非结构化信息整合到本地。正确问题是：**在结构化公开数据已经存在的前提下，额外加入 Codex 检索和归一化的非结构化信息，是否让预测更好。**

## 6. 下一步必须建立的影响证明机制

后续每次改动都应该强制写入预测 diff：

```text
run_id
code_version
data_version
event_id
cutoff
iterations
seed
changed_component
before_prediction_path
after_prediction_path
probability_delta_by_driver
rank_delta_by_driver
metric_delta
notes
```

每次预测相关 PR/改动必须自动跑：

- same event；
- same cutoff；
- same iterations；
- same random seed；
- before/after；
- 输出 JSON diff；
- 记录 top pick、winner probability、Brier、log loss、expected finishing rank。

前端也必须展示：

- 当前预测 run id；
- 当前 artifact timestamp；
- 当前 code/data hash；
- 与上一个 run 的概率变化；
- 哪些因素导致变化。

只有这样，下一次你问“这一小时到底有没有改进预测”，才能直接回答，而不是靠口头解释。

## 7. 对 30 小时工作的最终判断

不应该说“30 小时每小时都有效地修正了预测”。正确说法是：

- 大约一部分时间在做真正影响预测的模型/数据结构；
- 很大一部分时间在做审计、前端、报告、数据入口和边界控制；
- 这些工作对项目底座有价值，但没有被证明提升预测效果；
- 预测效果当前仍偏弱；
- 继续按旧方向堆报告是不对的；
- 下一阶段必须转向第一性原理因子体系、数据特征工程、预测 diff、baseline/ablation 和前端重点化展示。
