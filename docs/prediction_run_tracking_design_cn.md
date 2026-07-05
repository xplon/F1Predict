# PredictionRunRegistry + InformationIntakeStore + MatchedPredictionDiff 设计说明

生成日期：2026-07-05

这三个对象的目标很简单：以后每次信息、代码、模型、权重或前端 artifact 更新，都必须能证明它有没有影响预测结果。

## 1. PredictionRunRegistry 是什么

PredictionRunRegistry 是“预测运行登记簿”。

现有 Prediction Packet 能说明一次预测的内容，但如果没有 registry，就会出现这些问题：

- 预测文件散落在目录里；
- 前端不知道哪个是最新预测；
- 两次预测之间没有稳定 ID；
- 做了模型或信息更新后，不知道预测结果有没有改变；
- 后续 replay、diff、前端展示都找不到统一入口。

PredictionRunRegistry 做的事：

- 给每一次预测生成 run_id；
- 记录 event_id、knowledge_cutoff、iterations、生成时间；
- 记录 prediction packet 路径；
- 记录输入 fingerprint；
- 记录 evidence fingerprint；
- 记录 probability fingerprint；
- 可选关联 InformationIntakeRecord；
- 维护 `reports/prediction_runs/index.json`。

它回答的问题是：

```text
这一次预测到底是哪一次？
它用了什么 cutoff？
它的输入和上一次是否一样？
它的概率输出和上一次是否一样？
前端应该读哪个 run？
```

## 2. InformationIntakeStore 是什么

InformationIntakeStore 是“信息摄取快照库”。

Codex 的核心价值不是直接输出“我觉得谁会赢”，而是把网上非结构化信息变成本地结构化 claim。InformationIntakeStore 负责把某个 cutoff 下可用的信息状态保存下来。

它记录：

- event_id；
- knowledge_cutoff；
- 可用 claim 数量；
- 唯一 source 数量；
- claim fingerprint；
- source fingerprint；
- metric 分布；
- target 分布；
- direction 分布；
- source_log、research_candidates、research_preflight 是否存在；
- 哪些 claim 仍然 review_required；
- 当前 intake 是否缺少审计 artifact。

它回答的问题是：

```text
这次预测到底读到了哪些信息？
这些信息是不是比上一次多了？
来源是不是变了？
信息是 Codex 真正摄取来的，还是 seed/demo 数据？
信息缺哪些审计环节？
```

## 3. MatchedPredictionDiff 是什么

MatchedPredictionDiff 是“同口径预测差异报告”。

它比较两个已经注册的 prediction run，并输出：

- 输入 fingerprint 是否改变；
- evidence fingerprint 是否改变；
- probability fingerprint 是否改变；
- information intake 是否改变；
- 每个车手 win/podium/expected_points/average_finish/expected_rank 的变化；
- 最大变化来自哪些车手；
- 有多少车手发生 material change；
- cutoff、iterations、event 是否匹配。

它回答的问题是：

```text
这次更新到底有没有改变预测？
改变了哪些车手？
变化幅度是多少？
是不是只是输入变了但输出没变？
是不是输出变了但 evidence 没变，说明模型/随机性/代码变了？
是不是前端没更新，但后端 artifact 已经变了？
```

## 4. 三者如何配合

标准流程应该是：

```text
1. Codex 检索并归一化信息
2. InformationIntakeStore 写入 intake 快照
3. 预测模型生成 prediction packet
4. PredictionRunRegistry 注册 prediction run，并关联 intake
5. MatchedPredictionDiff 对比上一版 run 或 baseline run
6. 前端读取 latest run + latest diff
```

这条链路能把“工程更新”变成“预测影响证明”。

## 5. 当前首版命令

构建信息摄取快照：

```bash
f1predict build-information-intake --event british_gp --knowledge-cutoff 2026-06-30T12:00:00+00:00 --write
```

生成预测包并注册 run：

```bash
f1predict prediction-packet --event british_gp --knowledge-cutoff 2026-06-30T12:00:00+00:00 --iterations 1200 --write --register-run --information-intake data/intake/british_gp/<intake>.information_intake.json
```

注册已有预测包：

```bash
f1predict register-prediction-run --packet reports/prediction_packets/british_gp/<packet>.prediction_packet.json
```

比较两个 run：

```bash
f1predict diff-prediction-runs --base-run <old_run_id> --candidate-run <new_run_id> --write
```

## 6. 当前首版边界

这次实现不是预测模型精度提升。

它的作用是先建立预测追踪底座。只有有了这个底座，之后每次接入新信息源、修改权重、重写模拟器、清理前端，才能证明：

- 预测有没有变；
- 为什么变；
- 变得是否更准；
- 前端展示是不是最新 artifact。

没有这层机制，继续调模型会很容易回到“做了很多，但不知道有没有影响最终预测”的状态。
