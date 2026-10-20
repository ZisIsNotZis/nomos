# 测量结果

类型：结果。所有者：主代理。现有数字都在这里，每个都指向落盘的证据。

## 处境池

- 会话档案：`~/.pi/agent/sessions`，3312 个 JSONL，其中 **275 个是交互会话**；其余是子代理运行与转录。
- 人类用户轮 **1746** 条，工具调用 86 273 次；用户消息里 41% 是 harness 注入，按结构剔除。
- 结构信号命中 455 个候选窗口；以用户轮结尾的合格处境 **242** 条，来自 **51 个不同会话**。
- 证据：`mining/report.md`、`mining/candidates.jsonl`。

## 双答样本

- 183 条处境各两次回答（带法 / 不带法），落 `data/pairs.jsonl`；筛掉两侧同动作 6 条与坏件 3 条后，**174 条**入账，落 `data/pairs-filtered.jsonl`。判据、逐条丢弃与覆盖计数见 [数据质量](data-quality.md)。
- 早先 20 条处境的对照探针里，两条回答实质不同的 9/20 = **45%**；证据：`evidence/bare-baseline/analyse.py`。

## 法的覆盖

- 叶子节点 264；可训练 175，不可训练 89（工具/宿主绑定 28，概念与定义 61）；两可 32。
- 覆盖计数与标注：见 [数据质量](data-quality.md)，数据落 `data/coverage.json`、`data/coverage-counts.json`。
- 证据：`constitution/nodes.json`，重算 `python3 constitution/build_nodes.py`。

## 冲突审计

- 比对 68 对，**真冲突 0**；优先级处境 10，平衡点 4，其余为无关；172 个叶子论证为不碰撞。
- 证据：`docs/method/conflicts.md`。

## 评委可靠性

- 同一对回答换位置各判一次，**不一致率 0.66–0.75**；同条件对照在位置偏好下 Y 胜率 0.913。
- 同一请求重发，回答复现率 89%；换向翻转不对称 35 比 12。
- 结论：这一版成对偏好仪器不可用，判断只能靠可数子级。
- 证据：`evidence/position-swap/`、`evidence/draw-noise/`、`evidence/forced-choice/`。

## 四维 rubric 的分辨力

- 64 组已知水平（带法 vs 不带法）上，四维分与合成分**分不开**：合成分差 **−0.001**，95% 区间 [−0.0265, 0.0255]，逐对胜负 27 比 34，符号检验 p 0.44，置换检验 p 0.96。
- 同一回答判三次的项内标准差：相位 0.090、证据 0.079、提问 0.044、交付 0.055、合成分 0.040；三次总分不一致的回答占 73%。
- 已知更差的对照（追加一条越权强制推送）8 组里 8 组合成分下降，平均 **−0.160**：0.16 量级能分辨，0.03 以下不能。
- 结论与判据、两次判读、逐条件结果：[rubric](rubric.md)。证据：`evidence/rubric/`、`eval/judge.py`、`eval/analyse.py`。

## Qwen3.5-2B 基座

- `Qwen/Qwen3.5-2B`，revision `15852e8c…`，22.1 亿参数，bf16，单张 4090，峰值显存 6.66 GiB。
- 20 条处境、两条件、贪心解码：裸条件 **16/20** 产出可判定动作；带整部法 14/20，且 5 条截断、2 条复读、2 条回显。
- 工具行：裸条件 **0/20**，带法条件 6/20。
- prompt 长度：裸 526 token，带法 19 878 token。
- 证据：`evidence/qwen-base/generations.jsonl`。

## 花费

- 全部 API 调用合计 1504 次、约 ¥4.37；其中 550 次、¥1.65 是覆盖标注（`evidence/coverage/`、`evidence/coverage-cap8/`、`evidence/coverage-uncapped/`）。单价与逐次 usage 在 `evidence/*/calls.jsonl`。
