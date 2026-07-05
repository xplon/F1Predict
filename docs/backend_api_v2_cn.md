# F1Predict 后端 API v2 设计与使用说明

生成日期：2026-07-05

本文件定义新版本后端 API 的首版契约。当前只实现后端，不改前端。

API v2 的目标不是多做几个接口，而是让预测系统具备稳定的后端工作流：

```text
信息摄取快照 -> 预测 artifact -> prediction run 注册 -> matched diff -> replay/前端读取
```

## 1. 设计原则

- API 不能假设 20 名车手；车手数量必须来自 season roster。
- 所有真实事实必须可溯源，不能凭旧印象修改数据。
- GET 默认只读取或预览；POST 才写入新的 artifact。
- 预测结果必须注册成 run，不能只返回一次临时 JSON。
- 新预测应尽可能和同 cutoff 的上一版 run 做 diff。
- diff 必须区分：原始 evidence 是否变了、输入是否变了、概率是否变了。

## 2. API 总览

基础路径：

```text
/api/v2
```

接口定义：

```text
GET /api/v2/openapi.json
GET /api/v2/health
GET /api/v2/verified-facts
GET /api/v2/season-state
GET /api/v2/information-intake
POST /api/v2/information-intake
GET /api/v2/prediction-runs
POST /api/v2/prediction-runs
GET /api/v2/prediction-runs/latest
GET /api/v2/prediction-runs/{run_id}
GET /api/v2/prediction-diffs
POST /api/v2/prediction-diffs
GET /api/v2/prediction-diffs/{diff_id}
```

## 3. 事实和赛季状态接口

### GET /api/v2/health

用途：检查后端是否可用，同时返回当前 season roster 计数。

关键返回：

- `team_count`
- `driver_count`
- `event_count`
- `latest_british_gp_run_id`
- 项目期望文档路径
- API 文档路径
- 已核验事实文档路径

### GET /api/v2/verified-facts

用途：返回已经核验的现实事实。

当前包含：

- 2026 赛季官方车队页显示 11 支车队、22 名车手；
- 来源为 Formula 1 官方车队页；
- 本地文档为 `docs/verified_facts_2026_cn.md`。

### GET /api/v2/season-state

用途：返回本地 season state 的 roster 和赛程摘要。

关键返回：

- `season`
- `team_count`
- `driver_count`
- `teams`
- `events`
- `verified_fact_refs`

## 4. 信息摄取接口

### GET /api/v2/information-intake

用途：预览某个 event/cutoff 下可用的结构化信息，不写文件。

参数：

```text
event_id=british_gp
knowledge_cutoff=2026-06-30T12:00:00+00:00
```

### POST /api/v2/information-intake

用途：构建并写入 information intake artifact。

请求体：

```json
{
  "event_id": "british_gp",
  "knowledge_cutoff": "2026-06-30T12:00:00+00:00"
}
```

输出：

- intake 摘要；
- claim/source fingerprint；
- metric/target/direction 分布；
- artifact 路径。

## 5. 预测 run 接口

### GET /api/v2/prediction-runs

用途：列出已经注册的 prediction run。

参数：

```text
event_id=british_gp
```

### GET /api/v2/prediction-runs/latest

用途：读取某个 event/cutoff 最新 run。

### GET /api/v2/prediction-runs/{run_id}

用途：读取指定 run。

### POST /api/v2/prediction-runs

用途：执行一次完整后端预测工作流。

请求体：

```json
{
  "event_id": "british_gp",
  "knowledge_cutoff": "2026-06-30T12:00:00+00:00",
  "iterations": 1200,
  "register": true,
  "write_information_intake": true,
  "compare_to_latest": true
}
```

工作流：

1. 写入 information intake；
2. 生成 prediction packet；
3. 注册 prediction run；
4. 如果存在同 event/cutoff 的上一版 run，自动生成 matched diff。

注意：这是写 artifact 的接口，会改变 `data/intake`、`reports/prediction_packets_v2`、`reports/prediction_runs` 和可能的 `reports/prediction_diffs`。

API v2 默认把每次 prediction packet 写入唯一时间戳目录，避免同一个 event/cutoff 重复预测时覆盖旧 artifact。旧版 `prediction-packet` CLI 仍保留原行为，后续应该逐步迁移到 run-aware 输出。

## 6. 预测 diff 接口

### GET /api/v2/prediction-diffs

用途：列出已经存在的 prediction diff artifact。

### GET /api/v2/prediction-diffs/{diff_id}

用途：读取指定 diff。

### POST /api/v2/prediction-diffs

用途：对两个已注册 run 生成 matched diff。

请求体：

```json
{
  "base_run_id": "old_run_id",
  "candidate_run_id": "new_run_id",
  "write": true
}
```

diff 必须回答：

- `input_changed`
- `evidence_changed`
- `probability_changed`
- `information_intake_changed`
- 每个车手 win/podium/expected_points/average_finish/expected_rank 的变化；
- 最大变化车手；
- cutoff、iterations、status 是否匹配。

## 7. 当前首版边界

这次 API v2 是架构层改进，不等同于预测精度提升。

它解决的是：

- 后端有稳定接口；
- 预测结果不再只是临时 JSON；
- 信息摄取、预测和 diff 能形成闭环；
- 后续每次模型改动都可以自动留下预测影响证据。

下一步才应该在这个 API 上继续改进预测模型本身，包括：

- 引入结构化公开数据 baseline；
- 强化练习赛/排位/长距离 pace；
- 扩展赛车/赛道/车手 ontology；
- 做历史 replay matched comparison。
