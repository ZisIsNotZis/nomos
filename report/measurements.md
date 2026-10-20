# 测量结果

类型：结果。所有者：主代理。现有数字都在这里，每个都指向落盘的证据。

## 处境池

- 会话档案：`~/.pi/agent/sessions`，3312 个 JSONL，其中 **275 个是交互会话**；其余是子代理运行与转录。
- 人类用户轮 **1746** 条，工具调用 86 273 次；用户消息里 41% 是 harness 注入，按结构剔除。
- 结构信号命中 455 个候选窗口；以用户轮结尾的合格处境 **242** 条，来自 **51 个不同会话**。
- 证据：`mining/report.md`、`mining/candidates.jsonl`。

## 双答样本

- 183 条处境各两次回答（带法 / 不带法），其中 **45% 两条实质不同**。
- 证据：`data/pairs.jsonl`、`evidence/slice-contrast/answers.jsonl`。

## 法的覆盖

- 叶子节点 264；可训练 175，不可训练 89（工具/宿主绑定 28，概念与定义 61）；两可 32。
- 证据：`constitution/nodes.json`，重算 `python3 constitution/build_nodes.py`。

## 冲突审计

- 比对 68 对，**真冲突 0**；优先级处境 10，平衡点 4，其余为无关；172 个叶子论证为不碰撞。
- 证据：`docs/method/conflicts.md`。

## 评委可靠性

- 同一对回答换位置各判一次，**不一致率 0.66–0.75**；同条件对照在位置偏好下 Y 胜率 0.913。
- 同一请求重发，回答复现率 89%；换向翻转不对称 35 比 12。
- 结论：这一版成对偏好仪器不可用，判断只能靠可数子级。
- 证据：`evidence/position-swap/`、`evidence/draw-noise/`、`evidence/forced-choice/`。

## Qwen3.5-2B 基座

- `Qwen/Qwen3.5-2B`，revision `15852e8c…`，22.1 亿参数，bf16，单张 4090，峰值显存 6.66 GiB。
- 20 条处境、两条件、贪心解码：裸条件 **16/20** 产出可判定动作；带整部法 14/20，且 5 条截断、2 条复读、2 条回显。
- 工具行：裸条件 **0/20**，带法条件 6/20。
- prompt 长度：裸 526 token，带法 19 878 token。
- 证据：`evidence/qwen-base/generations.jsonl`。

## 花费

- 全部 API 调用合计 954 次、约 ¥2.72；单价与逐次 usage 在 `evidence/*/calls.jsonl`。
