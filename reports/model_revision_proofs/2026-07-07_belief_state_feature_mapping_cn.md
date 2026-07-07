# 2026-07-07 BeliefState 特征映射修订证明

## 结论

这次 British GP 候选预测包的变化不是新增外部来源，也不是因为用户说某个车队或车手应该更强/更弱而手动调整数值。

本次修订解决的是一个通用链路问题：部分已经存在的结构化特征能够生成出来，但在进入 `BeliefState` 时因为目标对象映射不正确而被静默丢弃，或者没有进入会被模拟器消费的状态表。

因此，本次变化应被归类为：

```text
用户指出预测异常
-> 触发模型链路审计
-> 发现已存在结构化特征没有完整进入状态更新账本
-> 修复通用目标映射和模拟器消费路径
-> 使用同一批结构化来源重新生成诊断预测包
```

## 本次没有做什么

- 没有把用户关于梅奔、法拉利、红牛、阿斯顿马丁、奥迪、小红牛等判断写成实体级强约束。
- 没有新增 `if team == ...` 或 `if driver == ...` 这类按名称调排名的规则。
- 没有把用户反馈当作模型证据、训练标签或状态更新来源。
- 没有声称预测已经具备稳定盈利 edge。

## 旧问题

候选包审计发现，部分非零结构化特征没有进入状态更新账本，原因是目标类型和状态表类型不一致。

典型问题包括：

```text
driver reliability feature
-> 旧映射默认进入 car.reliability
-> target_id 仍是 driver_id
-> car_states 中找不到该 driver_id
-> 该特征被丢弃
```

```text
driver straight_line_speed feature
-> 旧映射默认进入 car.straight_line_speed
-> target_id 仍是 driver_id
-> car_states 中找不到该 driver_id
-> 该特征被丢弃
```

```text
team race_execution feature
-> 旧映射默认进入 driver.race_execution
-> target_id 是 team_id
-> driver_states 中找不到该 team_id
-> 该特征被丢弃
```

这类问题会造成一个很危险的现象：信息源已经被提取出来，但没有真正影响最终模拟；前端和解释模块看起来有很多因素，实际预测却没有吃到这些因素。

## 新规则

本次修订后的通用映射规则是：

```text
team + race_execution
-> team_ops.race_execution
-> PaceModel 的 belief_team_race_execution
-> race_pace_score / traffic_conversion / strategy_plan
```

```text
driver + reliability
-> driver.reliability
-> PaceModel.reliability
-> dnf_sampler
```

```text
driver + car-level technical metric
例如 straight_line_speed
-> 先通过 driver_id 找到 team_id
-> 更新该车手所属车队的 car state
-> race_pace_score / qualifying_grid_sampler
```

账本中的 `target_type` 现在表示真正被更新的状态对象。例如车手速度陷阱观测会被记为影响该车手所属车队的车状态，而不是错误地记为更新了一个不存在的 driver car state。

## 对候选预测包的影响

使用同一场 British GP、同一知识截止时间、同一批结构化来源重新生成候选包：

```text
event_id = british_gp
knowledge_cutoff = 2026-07-05T00:00:00+00:00
iterations = 1200
candidate_packet_sha = c5476c3ad7de6d25726068f71411c7d07ffec5f6a5e7e2e384b435b442be92ed
status = diagnostic_only
```

结构化特征进入状态账本的结果：

```text
feature_count = 541
state_update_ledger_count = 535
missing_nonzero_features = 0
```

新增/修正后能够进入账本的关键类别：

```text
team race_execution updates = 27
driver reliability updates = 30
team straight_line_speed updates = 22
```

账本目标类型现在可解释为真实状态目标：

```text
driver qualifying_ceiling = 131
driver race_pace = 100
driver race_execution = 80
team race_pace = 75
team qualifying_pace = 31
driver reliability = 30
team race_execution = 27
team straight_line_speed = 22
driver wet_skill = 22
driver tyre_management = 16
event wet_probability = 1
```

## 对排名的实际影响

这次修订对排名有小幅影响，但没有大幅重排。最明显的变化是：

```text
Hadjar average_finish: 7.717 -> 7.246
Hamilton average_finish: 4.545 -> 4.389
Leclerc average_finish: 5.630 -> 5.473
Antonelli average_finish: 2.428 -> 2.678
Bortoleto / Hulkenberg 中下游顺序发生小幅交换
```

这符合本次修订的性质：它不是新增大信息源，也不是手调强弱，而是让此前已经存在但没有进入模型的若干特征真正进入状态和模拟。

## 为什么这不是“用户一句话改数值”

本次修订只使用通用条件：

```text
target_type
metric
driver_id -> team_id 映射
state_scope
```

代码不读取用户判断中的车队名称或车手名称，也没有针对单个实体设置特殊权重。用户反馈的作用是触发审计；真正进入模型的仍然是结构化来源生成的特征。

## 验证

合同测试：

```text
python scripts/source_driven_contract_test.py
```

该测试验证：

- 用户反馈来源不能更新预测。
- 同源模型/映射变化若没有证明，默认不能注册成 latest。
- `team race_execution` 能进入 `team_ops.race_execution` 并影响 `race_pace_score`。
- `driver straight_line_speed` 能通过车手所属车队进入车队 `car.straight_line_speed`。
- `driver reliability` 能进入车手可靠性状态，并影响模拟器可靠性。

当前结论仍是诊断性结论。它证明信息链路被修复，不证明模型已经具备稳定 edge。真正的预测能力证明仍需要历史回放、概率校准和市场基线比较。
