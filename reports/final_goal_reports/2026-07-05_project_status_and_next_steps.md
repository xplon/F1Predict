# 项目整体完成情况、优缺点、不足与后续方向

生成日期：2026-07-05

## 1. 当前状态一句话总结

F1Predict 后端已经从一个难以审计的预测 demo，推进到一个具备 artifact-first、cutoff-aware、full-field prediction、prediction run registry、information intake、matched diff、chronological replay 的诊断系统。

但它还不是稳定盈利 edge 系统，也不是 formal-ready 预测模型。当前最佳说法是：诊断闭环已经基本建立，预测效果仍不稳定。

## 2. 已完成的关键能力

### 2.1 后端架构

已完成：

- `PredictionRunRegistry`
- `InformationIntakeStore`
- `MatchedPredictionDiff`
- `PredictionPacket`
- API v2 服务层
- prediction run 最新读取与 diff artifact
- artifact-first 的后端输出模式

价值：

- 每次预测都有 run id；
- 每次信息摄取有 intake id；
- 每次模型/输入变化都能比较概率变化；
- 可以回答“预测结果到底有没有变”。

### 2.2 事实与 cutoff 约束

已完成：

- 2026 赛季 22 名车手、11 支车队被当成事实，不再按旧 F1 20 人假设处理；
- FastF1/OpenF1/F1 official/Open-Meteo 数据都尽量保留 snapshot 和 captured_at；
- 排位、练习赛、正赛结果按 session_date 与 cutoff 判断可用性；
- replay 中不会把赛后正赛结果泄漏到赛前预测。

仍不足：

- 部分 Codex evidence 仍是 retrospective snapshot；
- 需要更多 cutoff-valid archive proof；
- session data 虽然有 observed_at，但还没有纳入 InformationIntakeStore 的 source audit 汇总。

### 2.3 全场预测

已完成：

- 输出 22 名车手全场排名；
- 输出 win/podium/points/expected points/average finish；
- 输出 team double podium、driver H2H 等概率；
- simulation replay 不再 unavailable；
- replay 指标不再只看冠军，而包含 rank MAE、points MAE、podium overlap、points overlap。

价值：

- 更符合用户要求：预测整场比赛，不只预测冠军。

### 2.4 模型输入

当前已经进入模型的输入包括：

- 官方 standings；
- FastF1 正赛结果；
- FastF1 season form；
- FastF1 momentum；
- FastF1 qualifying classification；
- FastF1 known qualifying order；
- FastF1 session laps；
- OpenF1/Silverstone historical analogue；
- OpenF1/Multiviewer circuit profile；
- F1 official race profile；
- Open-Meteo historical/forecast weather；
- Codex evidence claims；
- track feature vector；
- race execution；
- simulator pace separation config。

这比原始 MVP 明显更接近用户要求的第一性原理方向。

## 3. 当前预测效果

最新 session-lap replay：

- scored events：8
- top-pick hit rate：0.500
- median actual winner rank：2
- mean abs rank error：5.2045
- mean abs points error：3.1381
- podium overlap：0.5833
- points overlap：0.6125

上一版 team-strength replay：

- top-pick hit rate：0.625
- median actual winner rank：1
- mean abs rank error：5.1932
- mean abs points error：3.1375
- podium overlap：0.5417
- points overlap：0.6125

解释：

- 最新 session-lap 输入让信息更完整，但预测效果没有更优；
- 当前最好的 top-pick 版本是 qualifying/team-strength 版本；
- session-lap 权重还需要校准；
- 当前模型可能过度相信某些练习赛 long-run proxy 或没有充分区分 sprint 周末 session 的含义。

## 4. 优点

### 4.1 审计闭环明显变强

现在每次改动都可以留下：

- prediction packet；
- prediction run；
- matched diff；
- replay bundle；
- 中文改进报告；
- git commit。

这解决了之前最严重的问题：做了很多工程但不知道有没有影响最终预测。

### 4.2 cutoff-aware 程度提高

官方 standings、FastF1 result、qualifying、session laps 都在按 cutoff 判断可用性。British race-morning 能用 FP1/Q，但不会用 race result。

### 4.3 预测对象更完整

系统现在能处理 22 名车手全场结果，不再只看 winner market。

### 4.4 赛道与 session 数据开始进入核心模型

TrackFeatureVector、known qualifying order、session laps 都已进入 simulator 或 pace model。这符合用户要求的“所有影响最终结果的信息才重要”。

## 5. 不足

### 5.1 没有证明 edge

当前没有稳定盈利证据。

主要原因：

- replay 样本只有 8 场；
- 市场快照不足；
- no-trade 建议主要来自保守校准，而非真实 edge 发现；
- 没有 CLV 或同 cutoff 市场价格闭环。

### 5.2 Codex 信息摄取还不够真实

虽然架构上 Codex 是信息摄取层，但当前很多 evidence 仍是 seed 或回填来源。

需要继续做：

- 自动/半自动检索 race-week 新闻；
- 技术升级来源；
- 车队采访；
- 轮胎、天气、策略信息；
- 多源交叉验证；
- source log 与 archive 证明。

### 5.3 Session-lap 特征权重未校准

这是最新一次改动暴露出的关键问题。

练习赛/排位赛很重要，但不能简单认为 FP1/FP2 long-run proxy 越快就应该强推正赛胜率。它需要：

- 区分 fuel load；
- 区分 tyre compound；
- 区分 run plan；
- 区分 sprint 周末；
- 区分雨天/干地；
- 对 outlier 做更强处理；
- 与正赛结果做 replay calibration。

### 5.4 Race execution 仍然弱

当前 race execution 主要来自 grid-to-finish 转换，信息量有限。真正需要的是：

- 起步反应；
- 首圈事故概率；
- 缠斗/防守；
- 处罚；
- 安全车窗口；
- 车队策略执行；
- pit crew 表现；
- 事故责任和 DNF 风险。

### 5.5 测试与 replay 太慢

完整 smoke 和 chronological replay 已经非常慢：

- smoke test 曾在 10 分钟工具超时处被杀；
- full chronological-replay with components/freezer 曾在 20 分钟工具超时处被杀；
- `--no-components --no-freeze` 的 replay bundle 仍约 9 分钟。

这会拖慢每次改进后的验证速度，也会让失败定位困难。

## 6. 当前前后端状态

本轮只负责后端。

当前后端状态：

- API v2 已实现；
- prediction runs、diffs、intake、track features 等 endpoint 已有；
- 最新 artifact 已写入；
- 前端如果要展示最新状态，应该读取 prediction packet/run/diff，而不是实时重算。

前端状态：

- 本轮没有继续清理前端；
- 之前用户指出的“前端展示太多、加载慢、显示旧结果”仍需要单独处理；
- 正确方向是让前端只展示中文决策页面：最新预测、关键因素、diff、replay、缺失输入和 edge readiness。

## 7. 后续优先级

### P0：拆分验证命令

目标：

- 快速 smoke：30-60 秒内验证核心；
- 集成 smoke：允许数分钟；
- replay benchmark：显式慢任务。

原因：

没有快速验证，后续每个模型调整都会很痛苦。

### P1：校准 session-lap 权重

目标：

- 用历史 replay 比较不同 session-lap scale；
- 单独调 practice race pace、qualifying lap gap、tyre degradation；
- 特别区分 sprint 周末；
- 不把一次练习赛 proxy 当成过强 race pace。

成功标准：

- 至少不损害 top-pick hit rate；
- rank MAE 或 points MAE 有改善；
- 概率校准不恶化。

### P2：把 FastF1/OpenF1 session 数据纳入 InformationIntakeStore

目标：

- intake 不只记录 Codex claims；
- 还记录结构化数据源：FastF1 results、qualifying、laps、weather、OpenF1 circuit 等；
- 让每个 run 清楚说明“这次到底用了哪些数据源”。

### P3：市场数据闭环

目标：

- 为未来比赛定时保存 winner、podium、H2H、constructor markets；
- 回填已完赛历史市场时必须记录同 cutoff 价格或 archive；
- 只有这样才能验证 edge。

### P4：Codex 非结构化信息摄取

目标：

- 技术升级；
- 车队采访；
- 车手状态；
- 轮胎策略；
- 天气和赛道温度；
- 事故/处罚倾向；
- 信息源多源验证。

这些信息必须归一化到 ontology，而不是散落成不可用文本。

### P5：前端 artifact 页面

目标：

- 中文；
- 快速加载；
- 只读 latest artifact；
- 展示全场预测、关键因素、diff、replay、缺失输入、edge readiness；
- 不展示不必要的调试堆料。

## 8. 是否达到用户最终目标

没有。

还没有达到：

- 极高预测精度；
- 稳定 edge；
- formal-ready replay；
- 完整市场验证；
- 高质量 Codex 自动信息摄取。

已经达到：

- 后端新架构初步建立；
- API v2 已实现；
- run/intake/diff/replay 闭环已建立；
- 每次改动能重新预测、生成 diff、写报告、提交 git；
- 多个重要因素已进入模型；
- 可以诚实判断哪些改动有效，哪些没效果。

当前最重要的结论：

> 项目已经从“无法解释预测有没有变化”进入“能审计每次变化”的阶段，但还没有从“诊断模型”进入“稳定 edge 模型”的阶段。
