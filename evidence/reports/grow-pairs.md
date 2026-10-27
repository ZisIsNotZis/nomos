# 增长批次：59 条未用处境长成的新对，与合并后的稳定集

## 结论

增长池 59 条处境用完了：四次调用（law×2、bare×2）里，59 条对中 4 条被实质相同/坏件筛掉，余下 55 条又有 30 条不是两侧都能复现，新增稳定对 25 条。与老 66 条合并成 91 条（`data/pairs-stable-v2.jsonl`），跨条件动作不一致 29.7% [20.9%, 38.5%]。此前零覆盖的 98 条可训练规则里，新处境补上了 7 条，仍零覆盖 91 条。

## 池子：合格 242，已用 183，本次 59

合格规则与老批次同一段代码路径重算（`evidence/grow/pool.json` 的 `eligibility_funnel`）：455 条候选 → 合格 242 条、51 个会话；老批次用掉 183 条；剩下的 59 条是本次增长池，来自 10 个会话，其中 0 个会话老批次一条都没用过。

新增处境按会话与 window_id 排序编号 GRW001–GRW059，原文、截断后的 excerpt、session、window_id、signals 在 `evidence/grow/situations.jsonl`。

## 与老批次可比：请求重建闸 366/366

新批次不是另起一套构造。用 `evidence/slice-contrast/common.py` 的同一路径把老 183 条处境的 law/bare 两种请求重建一遍，请求指纹（`sha256(system + '\x00' + excerpt + INSTRUCTION)`）与 `evidence/slice-contrast/answers.jsonl` 记录的 366 条逐条相同，不一致 0 条；法条原文是 agent-policy 5eafb2e 上的 AGENTS.md，sha256 `325f8b3e2d868f91fb43c24dd088ae6e735386c6d5e2aacfc7496d6ff2726ab6`。模型 deepseek-flash、温度 0.0、thinking 关闭、max_tokens 600 全部导入老批次的定义。

bare 条件有单独的硬检查：请求必须没有 system 消息，且正文里不出现法条原文的首尾片段，否则生成直接停（`evidence/grow/generate-meta.json` 的 `bare_arm_gate`）。

## 四次调用与花费

每条处境 law 抽一次、bare 抽一次、law 再抽一次、bare 再抽一次，共 236 次生成调用，花费 ¥0.494；覆盖标注 55 次，¥0.123；合计 ¥0.617。每次调用的请求指纹、system 指纹、原文回答、usage 与花费都在 `evidence/grow/answers.jsonl`。

## 逐层筛掉的数目

| 阶段 | 条数 | 说明 |
| --- | --- | --- |
| 新处境对 | 59 | 每条处境一对（chosen = law 抽 1，rejected = bare 抽 1） |
| 实质相同 | 4 | 归一化后相同 4 条，长度比与词集 Jaccard 双过阈值 0 条 |
| 坏件 | 0 | 截断 0、复读 0、回显 0，两侧都没有坏件 |
| 质量筛后 | 55 | 进入复现判定 |
| 只有 law 侧没复现 | 13 | 第二次 law 抽样动作签名不同 |
| 只有 bare 侧没复现 | 9 | 第二次 bare 抽样动作签名不同 |
| 两侧都没复现 | 8 | 两侧都不一样 |
| 新增稳定对 | 25 | 两侧都被自己的第二次抽样复现 |

判据与老批次同一段代码：`scripts/filter_pairs.py` 的实质相同/截断/复读/回显，`scripts/resample_actions.py` 的动作签名（工具、程序:子命令、目标路径）。逐条证据在 `evidence/grow/pair-metrics.jsonl` 与 `evidence/grow/dropped.jsonl`，计数在 `evidence/grow/filter-counts.json`。新增稳定对里两侧都解析不出动作的有 3 条——它们的稳定只是四次都没动作，与老批次同一性质，对训练没有偏好信号。

产出三份可直接用的数据：`data/pairs-grow.jsonl` 是新处境的两答对（一行一条 JSON），`data/pairs-grow-filtered.jsonl` 是质量筛后的 55 条，`data/pairs-grow-stable.jsonl` 是两侧都可复现的 25 条。

## 合并后的稳定集

| 集合 | 条数 | 跨条件动作不一致 | 95% 区间（自助） | 两侧都有可解析动作 |
| --- | --- | --- | --- | --- |
| 全部（v2） | 91 | 29.7% | [20.9%, 38.5%] | 48 |
| 来自 slice-contrast | 66 | 25.8% | [15.2%, 36.4%] | 28 |
| 来自 grow | 25 | 40.0% | [20.0%, 60.0%] | 20 |

Wilson 区间给出 21.3%–39.7%，与自助区间同量级。只看两侧都有可解析动作的 48 条，不一致 47.9% [33.3%, 62.5%]。分批判读：grow 40.0% 比 slice-contrast 25.8% 高 14.2 个百分点，两批的区间都宽，合并值不能代替分批判读。

新处境拿到的稳定对更带动作：grow 的 25 条里有 20 条两侧都有可解析动作（80.0%），老 66 条里只有 28 条（42.4%）——供训练用的偏好信号因此从 28 条升到 48 条，这是增长最实在的产出。

`data/pairs-stable-v2.jsonl` 每行记 `batch`（slice-contrast 或 grow）、两侧原始回答、两侧动作签名、两侧第二抽签名与 `cross_condition_differs`；`window_id` 只有 grow 行有，老行的第二抽签名从 `evidence/resample/signatures.jsonl` 接上来。

## 覆盖：98 条零覆盖降到 91

标注规则与老批次同一段代码和同一条 system 消息（`sha256` 与 `evidence/coverage/run-meta.json` 相同才继续），新处境 55 条、205 个标注，落在 `evidence/grow/coverage/`。合并 229 条处境后，175 条可训练规则里零覆盖从 98 条降到 91 条。

| 此前零覆盖、现在有覆盖的规则 | 新处境标注次数 | 合并后次数 |
| --- | --- | --- |
| `attention.communication.report_only_effect` | 1 | 1 |
| `change.upkeep.render` | 2 | 2 |
| `change.upkeep.ops` | 1 | 1 |
| `practice.design.abstraction_cost` | 1 | 1 |
| `proof.review.scoped_review` | 1 | 1 |
| `proof.process.subagent_scope` | 1 | 1 |
| `proof.process.model_cost` | 2 | 2 |

覆盖标注是模型判断，只从 175 条可训练叶子的 dot path 里选 1–4 条，选的是处境里真实出现的决策点。它说明这些规则在语料里有了可被违反的实例，不说明新处境在这些规则上有可测的法效应——法效应要按跨条件动作不一致另算。

## 局限

增长池只有 59 条，且 10 个会话老批次已经用过，所以新增处境与老处境有会话重叠，不是独立样本；会话是聚合单位，跨批次的区间不能直接相加。复现判定仍只有一次第二抽样，一次复现不等于可复现，稳定集在更多抽样后还会缩小。新处境的小时级证据在 `evidence/grow/`，本文所有数字都能从那里或 `data/` 重算。
