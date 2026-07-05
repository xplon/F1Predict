# 2026 F1 已核验事实记录

更新时间：2026-07-05

这份文档记录实现过程中已经核验过的事实。后续如果要修改由现实事实决定的数据，必须先查证来源，再改代码或数据。

## 1. 2026 赛季车队和车手数量

结论：2026 赛季当前官方车队页显示 **11 支车队、22 名车手**。因此预测输出出现 22 个 driver row 本身不是异常，不能按旧赛季 20 名车手的印象删除。

来源：

- Formula 1 官方车队页：https://www.formula1.com/en/teams
- 查询日期：2026-07-05

官方车队页列出的车队和车手：

| 车队 | 车手 |
|---|---|
| Mercedes | George Russell, Kimi Antonelli |
| Ferrari | Charles Leclerc, Lewis Hamilton |
| McLaren | Lando Norris, Oscar Piastri |
| Red Bull Racing | Max Verstappen, Isack Hadjar |
| Alpine | Pierre Gasly, Franco Colapinto |
| Racing Bulls | Liam Lawson, Arvid Lindblad |
| Haas F1 Team | Esteban Ocon, Oliver Bearman |
| Williams | Carlos Sainz, Alexander Albon |
| Audi | Nico Hulkenberg, Gabriel Bortoleto |
| Aston Martin | Fernando Alonso, Lance Stroll |
| Cadillac | Sergio Perez, Valtteri Bottas |

本地状态：

- `data/seed/demo_season.json` 当前包含 11 支车队；
- `data/seed/demo_season.json` 当前包含 22 名车手；
- Cadillac 车队包含 Sergio Perez 和 Valtteri Bottas。

实现要求：

- 后端 API、预测模型、回放和前端 artifact 不能假设固定 20 名车手；
- 任何 driver_count 相关校验都应该从赛季 roster 读取；
- 如果未来官方 roster 变化，需要重新核验并更新本地数据。
