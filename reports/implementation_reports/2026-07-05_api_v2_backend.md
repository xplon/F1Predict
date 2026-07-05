# 后端 API v2 改进报告

生成时间：2026-07-05

## 1. 本次改进目标

本次改进只做后端，不改前端。目标是建立新版本预测模型继续迭代所需的 API 架构，让后续每次信息更新、模型更新、权重更新都能形成可追踪闭环。

本次改进不是模型精度提升提交，而是后端架构提交。

## 2. 实现内容

新增 `src/f1predict/api_v2.py`：

- 定义 `BackendApiV2` 服务层；
- 定义 `GET /api/v2/openapi.json`；
- 定义 `GET /api/v2/health`；
- 定义 `GET /api/v2/verified-facts`；
- 定义 `GET /api/v2/season-state`；
- 定义 `GET/POST /api/v2/information-intake`；
- 定义 `GET/POST /api/v2/prediction-runs`；
- 定义 `GET /api/v2/prediction-runs/latest`；
- 定义 `GET /api/v2/prediction-runs/{run_id}`；
- 定义 `GET/POST /api/v2/prediction-diffs`；
- 定义 `GET /api/v2/prediction-diffs/{diff_id}`。

修改 `src/f1predict/server.py`：

- 将 `/api/v2/*` GET 请求委托给 `BackendApiV2`；
- 新增 POST 支持；
- POST body 要求为 JSON object；
- 旧 API 保持兼容。

新增 `docs/backend_api_v2_cn.md`：

- 用中文记录 API v2 的接口定义、写 artifact 行为、默认输出目录和使用原则。

## 3. 事实核验

用户提醒不能凭旧印象把 22 名车手当异常。本次已核验：

- Formula 1 官方车队页显示 2026 赛季为 11 支车队、22 名车手；
- 本地 `data/seed/demo_season.json` 也包含 11 支车队、22 名车手；
- 因此 API v2 和后续模型不能假设固定 20 名车手。

本地事实记录见：

- `docs/verified_facts_2026_cn.md`

## 4. 新预测验证

通过 API v2 服务层生成了一次新的 British GP prediction run：

- Event: `british_gp`
- Knowledge cutoff: `2026-06-30T12:00:00+00:00`
- Iterations: `600`
- Run ID: `british_gp_20260630T120000_0000_20260705T084127_0000_c3e0679d18`
- Prediction packet: `reports/prediction_packets_v2/british_gp/2026-07-05T08_41_22_00_00/british_gp/british_gp_20260630T120000_0000.prediction_packet.json`
- Driver rows: `22`
- Status: `diagnostic_only`

Top win probabilities：

| 车手 | Win | Podium | Expected points | Average finish |
|---|---:|---:|---:|---:|
| antonelli | 0.3100 | 0.7267 | 17.077 | 3.538 |
| russell | 0.2633 | 0.6467 | 16.272 | 3.355 |
| verstappen | 0.2417 | 0.6633 | 15.808 | 3.882 |
| hamilton | 0.1400 | 0.4500 | 13.552 | 4.570 |
| norris | 0.0200 | 0.2183 | 9.783 | 5.967 |
| piastri | 0.0183 | 0.1733 | 9.087 | 6.133 |
| leclerc | 0.0067 | 0.1017 | 7.518 | 7.152 |
| hadjar | 0.0000 | 0.0150 | 4.025 | 9.153 |

当前 blocker：

- `codex_evidence_quality_review_required`
- `probability_calibration_diagnostic_only`

当前 warning：

- `codex_claims_require_review`

## 5. Prediction diff 结果

新 run 自动与同 cutoff 最新 run 做了 diff：

- Diff ID: `british_gp_20260630T120000_0000_5d4ca03979ce`
- Evidence changed: `false`
- Probability changed: `true`
- Information intake changed: `false`
- Match warning: `iteration_count_mismatch`
- Changed driver count: `22`
- Material driver change count: `16`
- Max abs win delta: `0.04`
- Max abs expected points delta: `0.8767`

解释：

- 原始 evidence 没有变化；
- information intake 没有变化；
- 概率变化主要来自新 run 的 iterations 与上一个验证 run 不一致，因此不能把这个变化解释为模型进步；
- diff 正确暴露了 `iteration_count_mismatch`，这符合 experiment-integrity 要求。

## 6. 历史回放验证

生成了新的历史回放 bundle：

- Artifact: `reports/chronological_replay_v2/2026_asof_20260701T000000_0000.chronological_replay.json`
- As-of: `2026-07-01T00:00:00+00:00`
- Iterations: `300`
- Status: `diagnostic_only`
- Formal backtest ready: `false`
- Formal probability claim ready: `false`

回放范围：

- Calendar events: `24`
- Cancelled events: `2`
- Due events: `8`
- Replayed events: `8`
- Result available events: `8`
- Missing due events: `0`

诊断指标：

- Top pick hits: `3`
- Top pick misses: `5`
- Top pick hit rate: `0.375`
- Median actual winner rank: `2`
- 7/8 真实赢家位于模型预测前三；
- Events with weak evidence quality: `3`
- Events with market snapshots: `2`
- Events with retrospective source snapshots: `3`

主要 root causes：

| 问题 | 严重性 | 影响 |
|---|---|---|
| market_data_gap | critical | 7 场缺少可用同 cutoff 市场数据，无法证明 edge |
| source_time_integrity_gap | high | 3 场仍依赖 cutoff 后快照或缺少 archive proof |
| model_ranking_calibration_gap | medium | top pick hit rate 只有 0.375，排名校准不足 |
| seed_label_provenance_gap | low | 部分 seed label 被 FastF1 canonical result 覆盖 |
| feature_horizon_boundary | low | 赛季首站缺少同赛季前序 form |

## 7. 是否达到预期

后端 API 架构目标：达到。

证据：

- API v2 服务层可直接调用；
- HTTP GET `/api/v2/health` 返回 `driver_count=22`、`team_count=11`；
- HTTP POST `/api/v2/prediction-diffs` 能返回 matched diff；
- smoke test 通过；
- 新 prediction run、diff、chronological replay artifact 均已生成。

预测精度目标：未达到，且本次不声称提升。

原因：

- 本次主要是 API 和 artifact 架构；
- 原始 evidence 没有变化；
- 模型权重和模拟器没有实质改动；
- diff 的变化主要来自 iterations 不一致，不能作为模型进步证据。

## 8. 下一步最重要改进

按照第一性原理，下一步应优先影响预测准确率，而不是继续堆 API。

优先级：

1. 建立结构化公开数据 baseline，尤其是 practice/qualifying/race pace、long-run pace、sector/speed-trap/stint；
2. 改造 replay，使每次模型改动都自动用 matched iterations 跑历史回放；
3. 修正当前 evidence 质量：替换 seed-only/retrospective source；
4. 将车队强弱状态从 standings、session pace、技术信息中自动归纳，而不是依赖手写 seed strength；
5. 开始做模型权重改进，并用 `PredictionRunDiff + ChronologicalReplay` 判断是否真的改善。
