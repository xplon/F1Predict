# 预测结果可解释性模块设计

生成日期：2026-07-05

## 1. 目标

这个模块的目标是回答用户对预测结果的自然语言问题，例如：

- 为什么 Russell 在 expected-rank 口径下排第一？
- 为什么 Leclerc 的胜率远低于同队 Hamilton？
- 为什么 Alonso 在所有 podium 概率为 0 的车手里排第一？

它不是重新预测，也不是自由发挥的聊天机器人。它必须先读取已经注册的 prediction run 和 prediction packet，再从里面抽取概率、特征、Codex evidence、factor trace、赛道上下文和 readiness 状态。

## 2. 模块入口

核心实现：

- `src/f1predict/explainability.py`
- `PredictionExplainer.answer(...)`
- `PredictionExplainer.answer_and_write(...)`

CLI：

```powershell
$env:PYTHONPATH='src'
python -m f1predict.cli explain-prediction --event british_gp --question "为什么预测拉塞尔第一？"
```

API：

```http
POST /api/v2/prediction-explanations
```

请求体示例：

```json
{
  "event_id": "british_gp",
  "question": "为什么勒克莱尔的胜率远低于同队的汉密尔顿？",
  "max_evidence": 8,
  "write": true
}
```

## 3. 回答结构

每次回答会返回：

- `answer`：给人看的中文解释；
- `question_type`：问题类型，例如 `rank_explanation`、`driver_comparison`、`group_zero_podium`；
- `detected_entities`：识别到的车手、车队、派生分组；
- `evidence_context`：从 prediction packet 抽出的结构化上下文；
- `supporting_evidence`：最关键的证据行；
- `codex_prompt`：给 Codex/LLM 继续回答同一问题的提示词；
- `codex_context`：Codex 只能使用的 JSON 上下文；
- `limitations`：为什么当前解释仍然是 diagnostic-only。

## 4. Codex 如何参与

Codex 在这里不是随便编解释，而是使用后端准备好的 `codex_context`。

回答合同是：

- 只能使用 `codex_context` 中的事实；
- 不能声称已经证明稳定盈利 edge；
- 必须区分“模型机制解释”和“真实世界强结论”；
- 如果上下文不足，必须说缺少哪类 artifact 或输入；
- 可以根据用户追问继续组织语言、比较因素、指出缺失信息。

也就是说，后端负责证据检索和上下文压缩，Codex 负责把证据组织成可读、可追问的解释。

## 5. 当前能解释什么

当前模块已经能从最新 British GP run 中解释：

- expected-rank 排序和 win-probability 排序不一致；
- 同队车手之间的差异；
- podium=0 的分组排序；
- driver/team/event 级 processed feature 的正负贡献；
- Codex evidence impact 的 same-seed leave-one-claim 影响；
- race score、qualifying score、reliability proxy；
- 排位顺序、赛道类型、天气/安全车/轮胎退化 proxy；
- 当前 prediction packet 的 diagnostic-only blocker。

## 6. 当前不足

这不是正式因果归因，也不是 Shapley/完整反事实归因。

当前解释的限制：

- feature contribution 是模型输入层的可解释分解，不是严格因果贡献；
- Codex evidence impact 只覆盖 Codex claim，不覆盖每条结构化 feature；
- Monte Carlo iterations 为 1200 时，0% 小概率事件可能只是采样分辨率不足；
- 如果 prediction packet 没有注册 run 或没有 packet path，解释模块无法工作；
- 当前 Codex evidence 仍有 weak/review-required 项，所以解释不能用于宣称 edge。

下一步应该做：

- 为每个主要 feature group 增加同 seed counterfactual impact；
- 为前端缓存精简版 explanation summary；
- 支持追问时引用上一轮 explanation_id；
- 把 explanation artifact 纳入 prediction run index；
- 在每次模型改动后自动生成 top-k 异常解释。
