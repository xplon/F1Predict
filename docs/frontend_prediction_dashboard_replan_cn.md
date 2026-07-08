# 前端重构规划：中文、少而重点、围绕影响预测结果的信息展示

生成日期：2026-07-05

这份文档只讨论前端展示。目标是把当前臃肿的诊断后台，改成一个中文预测分析页面。它应该让你一眼看到：为什么这个车手会排在这里，哪些因素最影响预测，哪些信息还缺，预测有没有相比上次变化。

## 1. 当前前端的问题

当前前端存在：

- 内容太多；
- 很多内容是工程审计，不是预测重点；
- 加载慢；
- 没有缓存策略；
- 没有清楚显示当前预测 artifact；
- 没有显示预测相对上一次是否变化；
- completion audit 没进前端；
- 没有真正前后端分离；
- 没有统一端口；
- 中文化不足；
- 用户无法判断“这个结果为什么是这样”。

当前前端更像开发者调试台，而不是预测决策页面。

## 2. 前端设计原则

新的前端应该遵循：

1. 只展示影响预测结果的信息；
2. 默认中文；
3. 第一屏就是预测结论；
4. 每个结论必须能展开看到原因；
5. 每个因素必须显示影响方向和影响大小；
6. 每次预测必须显示 run id、as_of、数据更新时间；
7. 不重新计算静态报告；
8. 后端预计算，前端只读缓存；
9. 不把审计面板塞满首页；
10. 不只关注冠军，要展示全场排名分布。

## 3. 信息架构

建议前端只保留 6 个一级页面：

1. 分站预测；
2. 因素解释；
3. 赛道与天气；
4. 策略与随机事件；
5. 赛季/回放评估；
6. 数据健康。

内部审计报告不放首页，只在“数据健康”里折叠。

## 4. 第一屏：分站预测

第一屏必须回答：

```text
这站比赛每个车手预计排第几？为什么？
```

展示内容：

- 分站名称；
- 预测生成时间；
- cutoff；
- run id；
- iterations；
- 数据新鲜度；
- 模型版本；
- 全部车手 predicted finish distribution；
- expected finish；
- expected points；
- P1/Podium/Top5/Points/DNF 概率；
- 上次预测变化。

表格建议：

| 预测排名 | 车手 | 车队 | 预计完赛 | P1 | 登台 | Top5 | 积分 | DNF | 相比上次 | 最大正面因素 | 最大负面因素 |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|

不要只显示 winner probability。每个车手都要有完整 ranking distribution。

## 5. 第二屏：预测因子解释

这一页回答：

```text
到底哪些因素让这个预测变成现在这样？
```

展示 5 类因素：

1. 赛道适配；
2. 车辆/动力单元；
3. 车手；
4. 车队策略；
5. 天气/随机事件。

每类因素显示：

- 方向：正面/负面；
- 影响值；
- 置信度；
- 来源；
- 是否已过 cutoff 审计；
- 对哪些车手/车队影响最大。

组件：

```text
影响瀑布图：
基础实力 -> 赛道适配 -> 排位/发车 -> 轮胎 -> 策略 -> 天气 -> 随机事件 -> 新闻修正 -> 最终预计排名
```

用户点开某个车手时看到：

- 为什么他预计 P3；
- 哪些因素把他推高；
- 哪些因素压低；
- 如果只使用结构化公开数据 baseline，他会排第几；
- 如果天气变湿，他会排第几；
- 如果安全车出现在 pit window，他收益多少。

## 6. 第三屏：赛道与天气

这一页不是只放赛道图，而是展示赛道如何影响预测。

必须展示：

- 官方赛道图；
- 弯角分类：低速/中速/高速；
- 长直道/短直道；
- 替代 DRS/能量部署区；
- 超车点；
- pit lane loss；
- safety car 历史概率；
- red flag 风险；
- 轮胎退化指数；
- 沥青/抓地 proxy；
- 海拔；
- 比赛时间；
- 历史气温；
- 天气预报；
- 赛道温度 proxy；
- 雨概率。

赛道图上不只画车，而要画：

- 高速弯；
- 低速牵引区；
- 长直道；
- 主要超车点；
- pit entry/exit；
- 高风险黄旗区域。

如果某项数据没有，前端要明确写：

```text
缺失：未获取 corner-level overtake probability，本次使用 track_type 粗略 proxy。
```

不能静默用假数据。

## 7. 第四屏：策略与随机事件

这一页回答：

```text
这场比赛有哪些随机事件会改变排名？
```

展示：

- 预计一停/两停/三停概率；
- 各车队策略倾向；
- 轮胎退化不确定性；
- safety car window；
- VSC window；
- red flag probability；
- 免费进站窗口；
- DNF 风险；
- pit stop error 风险；
- first lap incident risk；
- wet phase probability。

前端应该展示“情景树”：

```text
干地正常赛况 -> 排名分布
湿地前半段 -> 排名分布
中段 safety car -> 排名分布
晚段 safety car -> 排名分布
red flag/restart -> 排名分布
```

这比单独画一条 simulated lap 更重要。

## 8. 第五屏：赛季/回放评估

这一页回答：

```text
这个模型过去到底准不准？
```

展示：

- replay event count；
- top pick hit rate；
- actual winner probability；
- finishing rank error；
- top3 calibration；
- 结构化公开数据 baseline vs Codex 信息摄取版本；
- technical-factor ablation；
- 最近一次模型改动是否提升；
- 每站 miss reason。

必须有一句清楚结论：

```text
当前模型：诊断级；可决策优势证明不是当前 MVP 的验收条件，页面只需要诚实标注“尚未完成优势证明”。
```

## 9. 第六屏：数据健康

这一页折叠展示审计状态：

- source freshness；
- cutoff validity；
- market snapshot coverage；
- track vector completeness；
- weather completeness；
- driver/team vector completeness；
- missing factor warnings；
- report artifacts；
- smoke test status。

不要把这些东西放在首页干扰预测理解。

## 10. 缓存和加载策略

当前前端慢，是因为很多面板直接请求会触发计算，且没有清晰缓存。

新方案：

### 后端预计算

每次生成预测时写：

```text
reports/frontend_cache/{event_id}/{run_id}/summary.json
reports/frontend_cache/{event_id}/{run_id}/driver_table.json
reports/frontend_cache/{event_id}/{run_id}/factor_explain.json
reports/frontend_cache/{event_id}/{run_id}/track_weather.json
reports/frontend_cache/{event_id}/{run_id}/strategy_scenarios.json
reports/frontend_cache/{event_id}/{run_id}/model_eval.json
```

前端默认只读这些缓存，不实时重算。

### API

新增：

- `/api/health`
- `/api/frontend-cache/latest?event_id=...`
- `/api/prediction-runs?event_id=...`
- `/api/prediction-run?run_id=...`
- `/api/prediction-diff?run_id=a&base_run_id=b`
- `/api/mvp-completion-audit`

### 前端显示缓存状态

顶部显示：

```text
预测 Run：british_gp_20260705_001
生成时间：2026-07-05 16:20
数据截止：2026-07-05 12:00
模型版本：...
数据版本：...
缓存状态：已缓存，不在前端重算
```

## 11. 中文页面文案建议

一级导航：

- 分站预测
- 关键因素
- 赛道天气
- 策略风险
- 回放评估
- 数据健康

首页标题：

```text
英国大奖赛预测
```

状态条：

```text
诊断级预测；尚未完成可决策优势证明
```

核心卡片：

- 最可能冠军；
- 最可能登台；
- 最大上升因素；
- 最大风险因素；
- 模型信心；
- 数据缺口。

表格列名：

- 预计排名；
- 车手；
- 车队；
- 平均完赛；
- 冠军概率；
- 登台概率；
- 积分概率；
- 退赛概率；
- 上次变化；
- 主要原因。

## 12. 哪些旧前端内容应该删除或折叠

默认不再展示：

- 大段 raw evidence；
- source replacement 细表；
- readiness action CSV；
- freeze manifest 细节；
- market blocker 长列表；
- completion audit 逐行内部表；
- smoke test 内部断言；
- 巨大的 technical trace 列表。

这些可以放在“数据健康 -> 高级审计”里。

## 13. 验收标准

前端重构完成后，你应该能一眼看到：

1. 每个车手预计排第几；
2. 每个车手为什么排这里；
3. 哪些赛道因素影响最大；
4. 哪些车辆/车手/车队因素影响最大；
5. 哪些随机事件可能改变比赛；
6. 当前预测相比上次变了多少；
7. 当前数据缺什么；
8. 模型过去准不准；
9. 是否已经完成可决策优势证明；如果没有，是否清楚标注为“尚未证明”。

如果这些看不到，前端就还是没有抓住重点。
