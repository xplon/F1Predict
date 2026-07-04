# Codex 角色、信息源和项目重置计划

生成日期：2026-07-05

这份文档修正我前面一个重要误解：**Codex 不是一个可以随便拿掉做 ablation 的小模块。Codex 在这个项目里的正确角色，是“信息获取、阅读、筛选、归一化、归因”的入口层。**

如果没有 Codex 或同等的信息摄取层，系统只能依赖结构化公开数据、历史结果和手写 seed prior。那不是完整预测，而是一个弱 baseline。

## 1. Codex 到底应该做什么

Codex 应该承担这些职责：

1. 检索网上赛前、赛中、赛后所有可能影响比赛的信息；
2. 读取非结构化文本、图片、PDF、官网页面、车队公告、采访、技术分析、天气信息、赛道信息；
3. 判断来源可靠性、发布时间、是否在 cutoff 前；
4. 把信息归一化成结构化 claim；
5. 把 claim 映射到预测 ontology；
6. 估计 magnitude、confidence、uncertainty；
7. 解释这个信息为什么影响某个车队/车手/赛道/策略；
8. 把信息写入本地版本化数据层；
9. 让后端模型只读取本地结构化数据，不直接相信自然语言。

所以 Codex 的输出不应该是：

```text
我觉得梅奔会强。
```

而应该是：

```json
{
  "source": "Mercedes technical preview / FIA timing / journalist analysis",
  "cutoff_status": "within_cutoff",
  "target": "mercedes",
  "factor": "ers_deployment",
  "direction": "positive",
  "mechanism": "long deployment zones reduce clipping penalty",
  "magnitude": 0.07,
  "confidence": 0.78,
  "uncertainty": 0.18,
  "applies_to_track_features": ["long_straight", "high_ers_demand"]
}
```

## 2. 为什么“无 Codex ablation”这个说法不准确

你指出得对：如果 Codex 是负责把网上非结构化信息整合到本地的层，那么直接拿掉 Codex，就等于拿掉重要信息来源。这样得到的不是一个公平 ablation，而是一个信息严重缺失的弱模型。

更正确的对照应该是：

| 实验 | 含义 | 目的 |
|---|---|---|
| 结构化公开数据 baseline | 只用赛程、结果、练习/排位、天气、赛道、历史表现等结构化数据 | 测基础模型能力 |
| Codex 信息摄取版本 | 在 baseline 上加入 Codex 检索/归一化的新闻和技术信息 | 测非结构化信息是否带来增益 |
| Codex 技术因子版本 | 只加入被映射到车辆/赛道/车手技术 ontology 的信息 | 测技术信息映射是否有效 |
| 信息质量 ablation | 同样 Codex 信息，但不同来源质量/置信度权重 | 测 source quality 是否有价值 |
| 因子类别 ablation | 只关掉 ERS/轮胎/天气/策略等某类因子 | 测具体因子类别贡献 |

这样才符合你的目标：不是问“没有 Codex 能不能预测”，而是问“Codex 获取并结构化的信息是否提升预测”。

## 3. 赛季强弱判断应该怎么来

你不是要求手写：

```text
Mercedes must be strongest.
Red Bull must be weak.
Ferrari must be second.
```

你真正要求的是：系统应该从信息源中自动推断这些结论。

例如“赛季初梅奔一家独大、法拉利随后、红牛很弱”应该来自：

- 官方 standings；
- practice/qualifying/race pace；
- long-run pace；
- speed trap；
- sector times；
- tyre degradation；
- team upgrade news；
- technical analysis；
- driver/team interviews；
- reliability and setup issues；
- market odds；
- 多个独立信息源的一致性。

这些信息进入系统后，应该形成：

```text
Mercedes race_pace +
Mercedes qualifying_pace +
Mercedes ers_deployment +
Mercedes tyre_deg -
Ferrari race_pace +
Ferrari straight_line_speed -
Red Bull chassis_balance -
Red Bull upgrade_delta recently +
Red Bull early_season_weight_penalty +
```

也就是说，“梅奔强、红牛弱、法拉利第二”不是强行写死，而是信息摄取层和因子模型自然推出的状态向量。

## 4. 当前系统的信息源是什么

当前项目里可以确认存在的信息源包括：

### 已接入或已有本地数据

- `data/seed/demo_season.json`：手工/seed 的车队、车手、少量赛事和市场基础数据；
- `data/seed/evidence/british_gp.jsonl`：British GP seed evidence；
- `data/evidence/*/packets`：每站少量 evidence packet；
- `data/research/*/source_log.json`：研究 source log；
- `data/research/*/draft_evidence.jsonl`：人工/半自动 evidence 草稿；
- `data/processed/calendar/...`：OpenF1 calendar；
- `data/processed/f1_official_standings/...`：F1 official standings；
- `data/cache/fastf1/...`：FastF1 session/result cache，不应提交到 git；
- `data/raw/circuit_profiles/...`：OpenF1 circuit profile，包括 corners、marshal sectors、candidate lap 等；
- `data/raw/weather_profiles/...`：Open-Meteo historical/climate weather profile；
- `data/raw/circuit_images/...`：F1 official track map images；
- `data/market_snapshots/...`：少量 market snapshot；
- `reports/*`：预测、回放、校准、readiness、MVP gate 等生成报告。

### 当前不足

当前信息源远远没有达到“网上所有可能有用的信息”：

- 没有系统性抓取所有车队官网赛前/赛后报告；
- 没有系统性抓取技术媒体/记者观点；
- 没有结构化 speed trap/sector/stint/long-run pace；
- 没有系统化练习赛/排位赛数据进入预测；
- 没有稳定的 cutoff-aware 新闻数据库；
- 没有来源交叉验证后的 team/car state vector；
- 没有把市场 odds 作为信息源健康地进入 prior；
- 没有完整同时间市场快照；
- 没有足够的历史样本做校准。

所以你认为“这么简单的信息都没识别出来，说明信息检索很差”，这个判断基本是对的。当前系统更像是信息规范化框架雏形，不是完整的信息检索系统。

## 5. 当前实现哪些该保留

应该保留但需要重构的部分：

- `domain.py`：保留核心 dataclass 思路，但扩展为 TrackFeatureVector/CarPerformanceVector/DriverPerformanceVector；
- `pipeline.py`：保留 orchestration 入口，但拆小；
- `models/simulator.py`：保留 Monte Carlo 思路，但重写为 event-driven race simulator；
- `models/pace.py`：保留 score breakdown，但重构为 feature vector model；
- `models/technical_factors.py`：保留技术因子方向，但扩展 ontology；
- `intelligence/research_packet.py`：保留 packet/preflight 思路；
- `intelligence/evidence_quality.py`：保留来源质量评分；
- `intelligence/factor_contract.py`：保留合同思路，但重写 taxonomy；
- `prediction_packet.py`：保留 auditable artifact；
- `chronological_replay.py`：保留 replay 思路；
- `server.py`：短期保留，长期替换成更清晰 API；
- `web/assets`：保留官方赛道图资产，但不把图当作真实几何来源。

## 6. 当前实现哪些应该扔掉或降级

应该扔掉/降级/重做的部分：

- 过多内部审计面板：不应作为主前端；
- completion audit 在主流程中的权重过高：只保留为项目管理，不当作预测进展；
- market readiness 大量细表：暂时降级为后端健康检查；
- replay freeze 细节：不要放在主页面；
- 手写 seed strength 作为主要预测依据：必须降级为 cold-start prior；
- 对单赛道单点修复：必须改成整体数据源策略；
- 不带 run id 的预测输出：必须废弃；
- 没有 before/after diff 的“预测改进”说法：必须废弃；
- 前端实时触发重计算：应改成读取缓存 artifact。

## 7. 从崭新状态继续的建议

建议当前 repo 做一次 baseline commit，然后新建重构分支：

```text
codex/rebuild-prediction-core
```

接下来只做三类变更：

1. 信息获取/归一化变更；
2. 预测模型/因子权重变更；
3. 前端展示预测 artifact 的变更。

每次变更都必须产生：

- 输入数据 diff；
- prediction artifact；
- probability diff；
- factor contribution diff；
- replay metrics diff。

这样框架搭完后，每一次代码/信息更新都应该能回答：

```text
这次更新改变了哪些车手的预计排名？
改变了多少？
原因是什么？
是否让历史 replay 更好？
```

## 8. 下一阶段的第一件事

不是继续调前端，也不是继续写审计报告。

第一件事应该是建立：

```text
PredictionRunRegistry + InformationIntakeStore + MatchedPredictionDiff
```

没有这三件事，后续又会回到同一个问题：改了很多，但不知道预测到底有没有变。
