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
GET /api/v2/track-features
GET /api/v2/information-intake
POST /api/v2/information-intake
GET /api/v2/prediction-runs
POST /api/v2/prediction-runs
GET /api/v2/prediction-runs/latest
GET /api/v2/prediction-runs/{run_id}
GET /api/v2/prediction-diffs
POST /api/v2/prediction-diffs
GET /api/v2/prediction-diffs/{diff_id}
GET /api/v2/prediction-explanations
POST /api/v2/prediction-explanations
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

### GET /api/v2/track-features

用途：返回某一站的后端赛道/环境特征向量，不写 artifact。

参数：

```text
event_id=british_gp
knowledge_cutoff=2026-06-30T12:00:00+00:00
```

当前字段包括：

- 弯角数量和按角度 proxy 划分的低速/中速/高速弯；
- 长直道 proxy、straightness index；
- braking、traction、aero、mechanical grip demand；
- overtaking index、track position value；
- pit loss、safety car probability、red flag probability；
- tyre degradation index、wet probability、历史降水 p90、海拔质量检查。

边界：

- 这些字段来自本地已摄取的 OpenF1/Multiviewer circuit profile、F1 官方 race profile、Open-Meteo 天气 profile；
- 弯速、长直道、超车、部署区目前是 derived proxy，不是 FIA 官方逐弯速度或 2026 替代 DRS/部署区定义；
- 明显异常的天气地理字段，例如超过模型可信范围的海拔，不进入模型，并会出现在 `warning_codes`。

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

### GET /api/v2/prediction-packets/latest

用途：读取某个 event/cutoff 最新已注册 run 指向的 prediction packet JSON。

这个接口是只读缓存接口，不会重新运行模拟，也不会写新的 artifact。前端默认应该优先使用它来展示预测结果和可解释链路；只有找不到已注册 packet 时，才退回旧的实时构建接口。

参数：

```text
event_id=british_gp
knowledge_cutoff=2026-07-05T00:00:00+00:00  # 可选
```

输出会在原始 packet 上追加：

```json
{
  "cache_context": {
    "source": "registered_prediction_packet",
    "run_id": "<run-id>",
    "packet_path": "<relative-path>",
    "packet_payload_sha256": "<sha256>",
    "input_fingerprint": "<sha256>",
    "probability_fingerprint": "<sha256>",
    "prediction_anomaly_audit_source": "api_runtime_recomputed",
    "prediction_anomaly_audit_sidecar_id": "<sidecar-id-or-null>",
    "prediction_anomaly_audit_sidecar_comparison_status": "matched_source_run_iterations | diagnostic_iteration_mismatch | null"
  }
}
```

packet 本体现在包含：

```text
prediction_anomaly_audit
```

用途是展示“来源事实、状态更新和最终排名之间是否存在张力”。它只做诊断和解释，不会反向修改预测概率。前端“预测异常审计”区块读取这个字段，展示中文摘要、支持来源、状态更新链条和需要复核的模型风险。

注意：`GET /prediction-packets/latest` 和 `GET /prediction-runs/{run_id}/packet` 会在读取历史 packet 后，用当前 `PredictionAnomalyAuditor` 重新计算前端可见的 `prediction_anomaly_audit`。如果该 run 有缓存 sidecar，审计会使用 sidecar 的 full trace 覆盖证据。这个刷新不重新运行模拟、不写 artifact、不改变 packet hash，也不会改变预测排名。

### GET /api/v2/prediction-runs/{run_id}/packet

用途：读取指定 run 指向的 prediction packet JSON。它同样是只读接口，不会重新生成预测。

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

## 7. 预测解释接口

### GET /api/v2/prediction-explanations

用途：基于某个已注册 prediction run 回答自然语言解释问题，不写 artifact。

参数：

```text
event_id=british_gp
question=为什么预测拉塞尔第一？
run_id=<可选，默认取 event/cutoff 最新 run>
knowledge_cutoff=<可选>
max_evidence=10
language=zh
write=false
```

### POST /api/v2/prediction-explanations

用途：回答解释问题，并可选写入 explanation artifact。

请求体：

```json
{
  "event_id": "british_gp",
  "question": "为什么勒克莱尔的胜率远低于同队的汉密尔顿？",
  "max_evidence": 8,
  "write": true
}
```

关键返回：

- `answer`：中文解释；
- `question_type`：问题类型；
- `detected_entities`：识别到的车手、车队和派生分组；
- `evidence_context`：从 prediction packet 抽出的概率、特征、证据、赛道和模型分解；
- `supporting_evidence`：最关键的证据行；
- `codex_prompt`：给 Codex/LLM 继续回答同一问题的上下文提示；
- `limitations`：当前解释为什么仍然是 diagnostic-only。

解释接口不会重新预测。它读取已注册 run 的 packet，因此前端可以快速加载，也能保证解释和页面展示的预测结果来自同一个 artifact。

## 8. 当前首版边界

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
## 9. 预测影响追踪 sidecar 接口

主 prediction packet 只保留少量 `prediction_impact_trace`，用于快速页面加载。完整的单条信息隔离重跑会产生几百条 trace，如果直接塞进主包，会让前端重新变慢。因此新增 sidecar 机制：完整 trace 单独写入 `reports/prediction_impact_traces/`，前端按页读取。

### GET /api/v2/prediction-impact-traces/latest

用途：读取某个 event 最新注册 run 对应的已缓存 sidecar，不触发重新预测。

参数：
```text
event_id=british_gp
run_id=<可选；不传则使用该 event 最新注册 run>
limit=40
offset=0
trace_type=<可选>
impact_status=<可选>
claim_id=<可选>
```

如果 sidecar 不存在，返回 404。前端应显示“完整追踪缓存未生成”，不能把主包内嵌的少量 trace 当成全量解释。

### GET /api/v2/prediction-runs/{run_id}/impact-traces

用途：读取指定 run 的已缓存 sidecar。

### POST /api/v2/prediction-impact-traces

用途：生成完整 sidecar。这个接口可能很慢，因为它会做多次同种子隔离重跑；它不会注册新的 latest prediction run，也不会修改默认预测排名。

请求体：
```json
{
  "event_id": "british_gp",
  "run_id": "可选",
  "iterations": 1200,
  "isolated_impact_limit": -1,
  "isolated_impact_offset": 0,
  "isolated_source_group_limit": 0,
  "write": true,
  "limit": 40
}
```

`isolated_impact_offset` 用于分块生成 sidecar。例如 `isolated_impact_limit=50, isolated_impact_offset=100` 表示只生成排序后第 100-149 条状态更新的 isolated trace。分块 sidecar 会标记 `trace_generation.chunk_mode = true`，并且在合并全覆盖前 `formal_readiness.formal_ready = false`。

关键字段：
- `source_run`：sidecar 解释的是哪一个已注册 run，包括 input/evidence/probability fingerprint；
- `trace_generation.comparison_status`：`matched_source_run_iterations` 表示与源 run 同迭代数；`diagnostic_iteration_mismatch` 表示只是低迭代诊断，不可当作正式效果证明；
- `coverage`：状态更新、claim 覆盖率、单条 isolated 覆盖率；
- `pagination`：当前页和过滤后的 trace 数量；
- `traces`：当前页 trace，而不是整包全量 trace。

每条 `traces[]` 还会包含：

- `supporting_sources`：该 trace 能关联到的来源摘要；
- `source_to_prediction_chain`：中文解释链，通常按“原始来源 -> 信息分析 -> 状态更新 -> 预测变化”排列；
- `additional_source_to_prediction_chains`：同一 trace 涉及多个 claim/source 时的补充链路。

响应还包含 `formal_readiness`：

- `formal_ready`：只有 sidecar 与源 run 同迭代数且覆盖全部 claim/update 时才为 `true`；
- `status`：例如 `formal_trace_ready`、`diagnostic_iterations_full_coverage`、`missing_sidecar`；
- `recommended_action_zh`：下一步应补覆盖还是重跑同迭代 sidecar。

注意：这些字段解释的是已有 run 的缓存 sidecar。它们不会注册新的预测 run，也不会让前端默认排名改变。

### GET /api/v2/prediction-impact-traces/readiness

用途：只读取 sidecar 正式解释就绪状态，不返回 trace 页面。

参数：

```text
event_id=british_gp
run_id=<可选>
```

它用于前端和审计脚本区分“完整但低迭代诊断 sidecar”和“与源 run 同迭代的正式解释 sidecar”。
