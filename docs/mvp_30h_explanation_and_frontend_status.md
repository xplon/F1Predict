# F1Predict MVP 30 小时工作复盘与前端状态说明

生成日期：2026-07-03

这份文档是给项目所有者看的中文复盘。它不是宣传稿，而是解释：

- 为什么一个“最小 MVP”最后消耗了约 30 小时 50 分钟和大量 token；
- 从头到尾具体做了哪些工作；
- 哪些工作对 MVP 是必要的，哪些工作可能做重了；
- 为什么预测效果没有显著更优；
- 当前前端到底是什么状态，以及为什么你会感觉前端状态经常没有及时更新。

## 先说结论

这 30 小时没有主要花在“训练出一个显著更准的模型”上。更准确地说，时间主要花在把一个松散的预测想法做成一个可运行、可审计、可回放、可展示、不会胡乱宣称 edge 的诊断级 MVP。

当前项目已经完成的是：

- 数据获取、处理、预测、市场差异分析、时间回溯、问题分析、前端展示这一条链路已经打通。
- Codex/LLM 层不再是随便写自然语言结论，而是被规范成 source candidate、research packet、preflight、evidence claim、evidence quality、factor contract、factor trace。
- 新闻/事实可以进入模拟条件。例如 energy recovery、straight-line speed、launch performance、tyre degradation、wet weather 等因素会被路由到模拟器或 pace model，并留下可审计 trace。
- British Grand Prix 当前已经能返回 F1 官方赛道图资产和 312 行 simulation replay，不再是 replay unavailable。
- 有 MVP gate 和 completion audit 明确说明：诊断级 MVP 完成，但 formal edge/stable edge 没有完成，也没有被宣称完成。

当前没有完成的是：

- 没有证明预测结果显著优于 baseline。
- 没有证明 Codex 检索/归一化的非结构化信息，相比结构化公开数据 baseline，有稳定正向 lift。
- 没有完整同时间市场快照，所以不能做正式 edge、CLV 或交易结论。
- 前端不是独立前端工程；它是 Python 本地服务器同时提供静态页面和 API。这个设计能满足 MVP 展示，但确实不够工程化，也解释了你对端口、状态更新、前端刷新不透明的困惑。

我对预测效果的判断很直接：现在预测效果偏弱，只能算“机制已经跑通”，不能算“模型已经很有 edge”。

## 当前关键数字

这些数字来自当前本地报告和 API 检查：

- completion audit 状态：`mvp_complete_formal_edge_not_ready`
- MVP complete：`true`
- formal edge ready：`false`
- formal edge blockers：`5`
- 2026 截止到 `2026-07-01T00:00:00+00:00` 的 replay 覆盖：8 场 due events，8 场 replayed，0 场 missing
- top pick hit rate：`3/8 = 0.375`
- model error review：8 场检查，5 场 miss
- mean actual winner probability：`0.2524`
- Codex evidence impact 覆盖：8 场
- British GP prediction packet：22 个概率行，312 行 simulation replay
- British GP factor route counts：
  - `track_contextual_pace=3`
  - `race_start_launch=1`
  - `tyre_degradation=1`
  - `wet_weather=1`
- track asset audit：22/22 通过，missing asset 为 0，非赛道来源为 0，未视觉验证为 0
- 当前 8811 API 检查：
  - events：22
  - British GP track asset source：`f1_official_circuit_map`
  - British GP simulation replay rows：312
  - British GP representative lap rows：312
  - MVP gate：`mvp_delivery_ready`
  - formal edge ready：`false`

## 我大致每个阶段做了什么

下面不是精确计时器日志，而是按工作推进顺序折算出来的小时块。真实 30 小时里包含了代码实现、反复读取项目状态、长命令等待、浏览器验证、报告生成、上下文压缩后重新定位，以及修复前端/赛道/replay 的返工。

### 第 0-2 小时：理解目标和拆范围

我先把你的目标拆成几个硬要求：

- 不是只写一个预测函数，而是要有项目架构；
- LLM/Codex 必须是规范化信息层；
- 非结构化新闻和事实必须转成结构化因素；
- 因素必须真的影响模拟；
- 要能做分站预测和全年/回放分析；
- 要能和市场概率比较；
- 要有前端展示赛道图、代表性模拟圈、AI 判断、市场差异；
- 要按时间顺序从第一站测到当前 cutoff；
- MVP 不要求稳定 edge，但不能假装有 edge。

这个阶段的关键决定是：我没有把它做成一个单文件脚本，而是做成一个诊断研究系统。这是 30 小时变长的第一个原因。

### 第 2-5 小时：搭项目骨架和领域对象

我建立/整理了项目的核心结构：

- `src/f1predict/domain.py`
- `src/f1predict/pipeline.py`
- `src/f1predict/models/pace.py`
- `src/f1predict/models/simulator.py`
- `src/f1predict/cli.py`
- `src/f1predict/server.py`

核心对象包括：

- driver/team/event/market snapshot；
- evidence claim；
- feature adjustment；
- probability output；
- market edge；
- evidence impact；
- evidence quality；
- race simulation replay。

这一步的价值是让后面所有模块有共同语言。代价是它比直接写一个 notebook 慢很多。

### 第 5-8 小时：做 Codex 信息层的规范化合同

你的重点不是“让 LLM 讲故事”，而是“让 LLM 处理非格式化信息，然后变成模型输入”。所以我做了这些组件：

- Codex research plan；
- source candidate audit；
- research packet template；
- research packet preflight；
- evidence source log；
- evidence validation；
- evidence quality scoring；
- source conflict/triangulation 检查；
- factor contract。

这些东西让一条新闻不能直接裸奔进模型。它必须说明：

- 来源是什么；
- 发布时间/观察时间是否在 cutoff 前；
- 影响对象是谁；
- metric 是什么；
- magnitude/confidence/uncertainty 是多少；
- 理由是什么；
- 是否符合 target/claim_type/metric 的合同；
- 是否有来源风险、冲突风险、单源风险。

这是合理的，但也耗时。对于一个“只想看到预测结果”的最小 demo，这部分确实做重了；对于你提出的“规范化 LLM 层”目标，这部分是必要的。

### 第 8-11 小时：把技术事实接入模拟因素

你举的例子包括：

- 法拉利动力单元/直道/低海拔发车；
- 梅奔 ERS 和 clipping；
- 红牛引擎、超重、升级有效。

所以我补了 technical factor 路由：

- `energy_recovery`、`power_unit`、`straight_line_speed` 进入 track-contextual pace；
- `launch_performance` 进入起步/第一圈模拟表面；
- `tyre_deg` 进入轮胎退化；
- `wet_skill`/weather 进入湿地表现；
- `upgrade_effect`、`weight` 等进入车辆表现调整。

同时增加 factor trace，让前端/报告能看到：

- route 是什么；
- context multiplier 是多少；
- track demand component 是什么；
- effective race input 是多少；
- effective qualifying input 是多少；
- 该 claim 对胜率变化的影响是多少。

这一步是最贴近你原始目标的工作。问题是：它证明了“新闻事实可以影响模拟”，但没有证明“这样影响后预测更准”。

### 第 11-14 小时：扩展多轮模拟和 replay

为了让前端不是只显示一个胜率表，我把模拟输出扩展成：

- race probabilities；
- podium/points/expected points；
- representative lap；
- selected simulation replay；
- lap-by-lap position；
- gap to leader；
- tyre compound；
- stint；
- pit stop；
- planned stops；
- pit laps；
- track status；
- reliability/DNF trace。

British GP 当前 312 行 replay 就来自这里。后来你看到 `Simulation Replay unavailable`，说明前端和 API 的 replay payload/加载顺序/旧服务状态之间有 bug，我后面又返工修了。

### 第 14-17 小时：接数据源、市场源和赛程/结果

为了时间回溯，我接了或整理了这些输入通道：

- seed data；
- OpenF1/FastF1/F1 official calendar/result；
- weather/circuit profile；
- market snapshot；
- Polymarket discovery/backfill/reviewed packet；
- official standings。

这一步的核心目标不是实时抓尽所有真实数据，而是让项目有可扩展的数据入口。它也产生了大量“不是直接提升预测”的工作，比如 market readiness、source archive proof、after-cutoff market replacement 等。

这部分对正式 edge 很重要，但对最小 MVP 来说有一部分可以延后。

### 第 17-20 小时：做 chronological replay、model error 和 improvement plan

你要求“从第一站比赛开始到今天为止完整测一遍，然后分析项目问题”。所以我做了：

- chronological replay；
- replay analysis；
- model error review；
- calibration report；
- simulator calibration report；
- improvement plan；
- replay freeze manifest。

这些报告给出了当前最重要的事实：

- replay 能跑完 8 场；
- top pick 只中 3 场；
- 预测 miss 有 5 场；
- actual winner 平均只拿到约 25.24% 胜率；
- 最大 evidence win delta 约 0.0092，说明 Codex 因子现在对概率移动很小；
- 最大问题不是“没有链路”，而是输入质量、市场快照、校准、factor 权重和 baseline 对照不足。

这一步对“诚实评估项目有没有用”很必要，但它也让时间继续变长，因为我没有只报一个漂亮 demo，而是把失败也报出来了。

### 第 20-23 小时：做前端展示并清理明显不合理内容

前端做成了一个本地静态 dashboard：

- event selector；
- track map canvas；
- replay controls；
- replay frame；
- replay track canvas；
- model probabilities；
- market edge table；
- AI judgement；
- prediction packet；
- source candidates；
- research preflight；
- evidence quality；
- evidence impact；
- technical factor trace；
- chronological replay；
- replay analysis；
- formal readiness；
- market/source readiness；
- improvement plan；
- calibration；
- model error；
- simulator calibration；
- replay freeze；
- MVP gate。

后来你指出很多前端内容不正常，比如赛道图不真实、Barcelona/Spanish GP 混乱、model probabilities 怪、representative lap 图不对。这里我做了几轮清理：

- 删除/弱化早期不可信的示意图；
- 让事件 payload 携带 track map asset；
- 接本地真实赛道图资产；
- 加 track asset audit；
- 修 replay 使用真实 simulation rows；
- 加 replay unavailable 的诊断文本；
- 修 British GP 的 official map overlay。

但是这里也暴露了一个工程问题：前端没有独立 dev server，没有构建产物版本管理，没有 health/status panel，导致你看到的页面到底是不是当前 API 状态不够透明。

### 第 23-25 小时：修 British Grand Prix 赛道图和 replay unavailable

你明确说 British Grand Prix 还不对，Simulation Replay unavailable。这个阶段我重点查了：

- API 是否返回 British GP；
- track asset 是否是 F1 official circuit map；
- overlay 是否存在；
- simulation replay 是否为空；
- representative lap 是否为空；
- 前端是否用了错误字段；
- 是否有旧端口/旧服务导致页面没更新。

最终确认当前状态：

- `British Grand Prix`
- track asset source：`f1_official_circuit_map`
- overlay source：`auto_fit_official_sector_line_v1`
- simulation replay rows：312
- representative lap rows：312

所以现在 British GP 的问题不是模型没有 replay，而是过去某些时刻前端状态、端口状态、加载顺序或旧服务确实造成了你看到 unavailable。

### 第 25-27 小时：做 MVP gate，避免把诊断 MVP 说成 stable edge

我增加了 `mvp_gate`，把需求拆成：

- data acquisition and processing；
- Codex-normalized intelligence；
- simulation and probabilities；
- market gap analysis；
- chronological replay；
- frontend dashboard；
- problem analysis and improvement plan；
- reproducibility/artifact freeze。

这个 gate 当前结论是：

- `mvp_delivery_ready=true`
- `formal_edge_ready=false`
- `formal_edge_blockers=5`

这一步的价值是诚实边界：MVP 可以交付，但不能说有稳定 edge。

### 第 27-29 小时：做 completion audit 和最终文档化

最后我又做了一个更顶层的 `mvp_completion_audit`，因为单纯的 gate 还是偏工程内部。我把你的原始目标拆成 10 个 completion rows：

- modular architecture；
- Codex normalized LLM layer；
- news/facts to simulation factors；
- multi-round simulation probabilities；
- market gap without execution；
- chronological replay and problem analysis；
- frontend inspection dashboard；
- Codex factor impact diagnostics；
- formal edge boundary；
- verification and artifacts。

当前状态：

- `mvp_complete=true`
- `status=mvp_complete_formal_edge_not_ready`
- `formal_edge_ready=false`

这一步不是为了提高预测，而是为了回答“这个项目到底算不算完成 MVP”。它有价值，但从你的体验看，它也可能显得像“又写了很多报告，预测还是没变准”。

### 第 29-30.8 小时：验证、smoke test、API 检查

最后跑了：

- Python compileall；
- `node --check web/app.js`；
- 完整 `scripts/smoke_test.py`；
- API 检查；
- 前端截图/画布检查。

完整 smoke test 约 4 分多钟一次，且之前迭代中跑过多次。它覆盖 British GP 赛道资产、replay、技术 factor 路由、research preflight、market/readiness plumbing、MVP gate 等。

## 为什么花这么久

可以辩护的部分：

1. 你的目标其实不是一个普通 MVP。

   如果目标只是“给 British GP 输出一个预测表”，几个小时就能做完。但你的目标包含：

   - LLM 信息规范化；
   - source quality；
   - evidence contract；
   - technical factor routing；
   - Monte Carlo；
   - replay；
   - market comparison；
   - frontend；
   - chronological backtest；
   - problem diagnosis；
   - 不冒充 stable edge。

   这已经接近一个小型研究平台的 MVP。

2. 你对“不要偷懒”的要求很高，而且是合理的。

   尤其是赛道图问题。早期如果用假图/示意图，MVP 看起来快，但本质上会误导。你明确要求“把所有赛道都搞正确”，所以必须补 track asset audit 和真实资产验证。

3. 我花了大量时间在防止错误结论上。

   比如 market readiness、formal readiness、freeze manifest、completion audit，本质上是为了避免说“有 edge”但证据不够。

4. 前端问题不是单点 bug，而是数据结构、API payload、canvas 渲染、旧服务、端口、状态缓存一起造成的。

   British GP replay unavailable 的表象背后，涉及 simulation_replay 生成、API 序列化、前端 normalization、replay bounds、canvas draw、服务进程是否最新等多个环节。

不能完全辩护的部分：

1. 对“最小 MVP”的切分可以更激进。

   我把 formal readiness、market backfill、source archive proof、replay freeze 这些偏正式研究/交易级基础设施做得比较早。它们有价值，但如果按“先让预测明显变准”排序，它们不是第一优先级。

2. 前端工程治理不足。

   当前前端没有真正前后端分离，没有独立 dev server，没有明确端口策略，没有热更新，也没有前端显示“当前 API build/report timestamp”的健康栏。你觉得“前端很久没更新”，这个感受是有根据的。

3. 我没有尽早做结构化公开数据 baseline 与 Codex 信息摄取版本的 matched comparison。

   这导致我们现在能说“Codex 因子会影响模拟”，但不能说“Codex 检索和归一化的信息让预测更准”。对于你最关心的“正向帮助”，这是最关键的缺口。

4. 我做了很多报告，但没有同步把 completion audit 放进前端。

   当前前端有 MVP gate，但没有单独显示 completion audit。于是你在页面上看到的状态可能还是旧的 delivery gate 语义，而不是最终 completion audit 语义。

## 当前前端状态

### 运行方式

当前前端不是独立 React/Vite/Next 项目。它是：

- Python `ThreadingHTTPServer`；
- 同一个进程同时提供静态文件和 JSON API；
- 默认端口在代码里是 8765；
- 当前实际运行端口是 8811；
- 当前 8811 进程命令是：

```text
D:\Program\anaconda3\python.exe -m f1predict.server --host 127.0.0.1 --port 8811
```

这说明：测试主要用 `.venv`，但当前前端服务是 Anaconda Python 进程。现在 API 行为是对的，但环境治理确实不干净。后续应该统一成 `.venv` 或一个明确的 `make dev`/`scripts/start_dev.ps1`。

### API 状态

后端 API 在 `src/f1predict/server.py` 中直接按 path 分发。当前主要接口包括：

- `/api/events`
- `/api/prediction`
- `/api/prediction-packet`
- `/api/codex-research-plan`
- `/api/source-candidates`
- `/api/research-preflight`
- `/api/season-forecast`
- `/api/official-standings`
- `/api/chronological-replay`
- `/api/replay-analysis`
- `/api/formal-readiness`
- `/api/readiness-intake`
- `/api/market-readiness`
- `/api/source-readiness`
- `/api/improvement-plan`
- `/api/calibration-report`
- `/api/model-error-review`
- `/api/simulator-calibration`
- `/api/mvp-gate`
- `/api/replay-freeze-manifest`

没有 `/api/mvp-completion-audit`。所以 completion audit 目前是 CLI/report artifact，不在前端。

### 页面状态

前端在 `web/index.html` 和 `web/app.js`。它当前有：

- track canvas；
- simulation replay controls；
- replay frame；
- replay track canvas；
- MVP gate panel；
- prediction packet panel；
- source candidate panel；
- research preflight panel；
- chronological replay panel；
- replay analysis panel；
- model error/calibration/simulator calibration panels；
- market/source readiness panels；
- improvement/freeze panels。

前端现在能展示 British GP replay。当前 API 检查显示：

- British GP 事件可用；
- 官方赛道图资产可用；
- replay rows 为 312；
- probability rows 为 22。

### 前端主要问题

1. 没有前后端分离。

   这不一定影响 MVP 功能，但影响工程清晰度。页面、API、报告生成都挤在一个 Python 服务里。

2. 没有端口治理。

   默认 8765，当前 8811，历史上还有 8785/8793/8878 等截图和验证端口。这会导致“我打开的是不是最新版”变得不直观。

3. 没有构建版本/报告时间显示。

   页面没有清楚告诉用户：

   - 当前服务进程是什么；
   - 当前加载的是哪个 as_of；
   - 当前 prediction packet 的 generated_at；
   - 当前 MVP gate 是 live 还是 disk artifact；
   - 前端 JS 版本和后端 commit/hash 是什么。

4. completion audit 没有进入前端。

   这会让前端看起来仍停留在 MVP gate 状态，而不是最终 completion audit 状态。

5. 部分页面是“诊断后台”，不是产品化 UI。

   它展示很多报告和 blockers，但不是为普通用户快速理解预测结果而设计的。

## 当前预测效果怎么样

不好到不能宣称 edge，但也不是完全没价值。

更具体地说：

### 已经做到的

- 模型能跑；
- 能输出概率；
- 能输出 replay；
- 能按 cutoff 做时间回放；
- 能把 Codex evidence 转成模拟因素；
- 能记录每个因素怎么影响模拟；
- 能检查 source/evidence/market 的质量；
- 能分析 miss 的原因。

### 没做到的

- 没有显著优于 baseline 的证据；
- 没有结构化公开数据 baseline vs Codex 信息摄取版本的正式对照；
- 没有证明技术新闻/事实带来稳定正向 lift；
- 8 场样本太小；
- 3/8 top pick 命中不够强；
- actual winner 平均概率 25.24%，说明模型经常没有充分抬高真正赢家；
- Codex evidence 的最大胜率移动约 0.0092，说明现在新闻因素对最终概率的影响太保守或权重太弱；
- 市场对比缺少同时间 winner market snapshot，所以正式 edge 分析不成立。

我的判断：

```text
当前模型 = 诊断级研究原型
不是 = 可交易 edge 模型
```

如果要让预测显著变好，下一步不应该继续堆更多报告，而应该优先做：

1. 结构化公开数据 baseline vs Codex 信息摄取版本的 matched comparison；
2. Codex-factor-only ablation；
3. 技术因素权重重标定；
4. 输入证据质量提升；
5. 分赛道类型校准；
6. 同时间市场快照补齐；
7. 至少 20+ replay events 后再谈概率校准。

## 哪些工作有必要，哪些可能没必要

### 对当前 MVP 有必要

- 规范化 evidence claim；
- factor contract；
- technical factor routing；
- Monte Carlo simulation；
- selected simulation replay；
- official track assets；
- chronological replay；
- replay analysis；
- frontend dashboard；
- smoke test；
- MVP gate。

### 对正式 edge 有必要，但对最小 MVP 可以延后

- source archive proof 大规模流程；
- market readiness 大规模 backfill；
- replay freeze manifest；
- formal readiness intake；
- simulator calibration 多候选报告；
- completion audit 的完整 10 行审计。

这些东西不是错，但它们不直接提高预测准确率。它们提高的是“不要骗自己”的能力。

### 当时最该更早做但没做够的

- 结构化公开数据 baseline 对照；
- baseline comparison；
- 前端 build/version/status panel；
- 统一 dev server/端口；
- completion audit 前端展示；
- 更明确地告诉你“预测现在还没变准”。

## 为什么你感觉“前端一直没更新”

这个感觉是合理的，原因大概有四个：

1. 很多工作发生在后端、报告、CLI 和 smoke test，不会立刻改变页面主视觉。

2. 前端没有独立工程和版本标识。即使 JS 改了，页面也没有明显告诉你“现在加载的是哪个版本”。

3. 服务端口混乱。历史验证端口和当前端口不同，容易打开旧服务或旧截图。

4. 很多新增内容是诊断面板而不是“预测结果更好”。所以页面内容变多了，但你最关心的预测概率没有明显更可信。

这不是你的误解，是这个 MVP 的工程体验问题。

## 我应该如何为 30 小时负责

我可以为这些时间负责：

- 我把项目从“想法”推进到了“全链路诊断 MVP”；
- 我没有把假的赛道图和假的 replay 留在系统里；
- 我把 LLM 层做成可审计合同，而不是自然语言黑箱；
- 我没有宣称 stable edge；
- 我把模型差、市场缺、source 风险、calibration 弱这些问题都暴露出来；
- 我补了 smoke test，避免 British GP/replay 这类问题回归。

我也应该承认：

- 如果目标被严格解释成“用最短时间做一个能展示预测的 MVP”，30 小时偏长；
- 我过早投入了 formal edge 周边基础设施；
- 我没有把前端工程化做好；
- 我没有把预测效果提升作为最早闭环；
- 我应该更早把“当前预测没有显著变好”这个结论明确告诉你。

## 我建议下一步怎么做

### P0：先修工程体验

- 统一启动命令，只允许一个端口；
- 用 `.venv` 启动服务，不再混用 Anaconda；
- 前端顶部显示 backend status、as_of、generated_at、JS version；
- 增加 `/api/health`；
- 增加 `/api/mvp-completion-audit`；
- 前端显示 completion audit。

### P1：证明 Codex 有没有正向帮助

- 固定同一批 replay events；
- 固定随机种子；
- 跑结构化公开数据 baseline；
- 跑 Codex evidence；
- 跑 Codex technical factors only；
- 比较 top-pick hit rate、Brier、log loss、actual winner probability；
- 只有这个实验过了，才能说 Codex 信息层真的有正向帮助。

### P2：重调模拟权重

当前 evidence 最大胜率移动不到 1 个百分点，说明新闻/技术事实影响可能太弱。要重新看：

- factor magnitude；
- context multiplier；
- track demand profile；
- start/launch 权重；
- tyre degradation 权重；
- reliability/DNF 权重；
- wet weather 权重；
- grid/race pace prior 的相对强度。

### P3：补市场和正式 edge 条件

- 补同时间 winner market；
- 补 cutoff-valid source archive；
- 扩大 replay 样本；
- 做 held-out calibration；
- 再谈 edge。

## 最后一句话

这 30 小时做出来的东西，价值不在于“已经预测得很准”，而在于“终于有了一个不会靠幻觉和假图自欺欺人的 F1 预测研究底座”。但你的质疑是对的：如果下一阶段还继续堆审计和面板，而不做结构化公开数据 baseline 对照、Codex 信息摄取质量提升、权重校准和前端工程化，那么项目会变成一个很会解释自己但预测不强的系统。下一步应该把重心转向预测 lift 和前端状态治理。
