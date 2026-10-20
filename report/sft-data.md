# SFT 数据：637 条样本，按会话切出 8 个验证会话

## 结论

735 条带法回答，丢 98 条，留 637 条样本（训练 510 / 验证 127），覆盖 242 条处境、51 个会话。丢的 98 条里 95 条是同一处境内重复的 target，坏件只有 3 条，全是截断；复读、回显、空回答三类检测都跑了，一条没命中。

637 条样本落到 175 条可训练规则上覆盖 77 条，剩下 98 条一条样本都没有。验证集是 8 个会话、127 条，占样本 19.9%、占会话 15.7%，同一会话与同一处境都不跨两侧。

全部数字由 `python3 scripts/build_sft.py` 重算并覆盖写盘，种子固定 20261020，连跑两次四个输出文件 sha256 不变。

## 输入与口径

| 输入 | 用途 | 条数 |
| --- | --- | --- |
| `evidence/densify/answers.jsonl` 的 `arm=law` 行 | target | 735 |
| `evidence/slice-contrast/situations.jsonl` + `evidence/grow/situations.jsonl` 的 `excerpt` | prompt | 242 条处境 / 51 个会话 |
| `constitution/nodes.json` 的 `trainable` 节点 | 可训练规则表与断言短语 | 175 |
| `data/coverage.json` | 处境↔规则标注（沿用，不重标） | 174 条处境 |

一条 law 回答就是一条候选样本：prompt 是它那条处境的 `excerpt` 原文，target 是 `response` 原文，两者都不截断、不改写。归一化（去首尾空白、剥掉整体包住回答的一层代码围栏、压连续空白）只用于重复判定和断言，不写进样本。

计划里写的是「同一处境的 5 次抽样各算一条」，实际这批 law 回答每处境 3 条（233 条处境）或 4 条（9 条处境）：`answers.jsonl` 只装 `--generate` 补出来的那部分，5 抽里其余的在 `evidence/slice-contrast/answers.jsonl`、`evidence/grow/answers.jsonl`、`evidence/resample/answers.jsonl` 三个批次里，`scripts/densify.py` 的 `SOURCES` 记着它们到 law/bare 的映射。本工作包按指定输入只用 densify 批次，没去拼另外三批，所以平均每处境 2.6 条样本而不是 5 条。

## 坏件与丢弃

98 条丢弃记录全部在 `evidence/sft/dropped.jsonl`，每条带 `situation_id`、`session_id`、`draw`、`reason_class` 和一句 `evidence`（触发判据的原文片段或末字），按 `(situation_id, draw)` 能回到 `answers.jsonl` 那一行。

| 类别 | 条数 | 判据 | 命中 |
| --- | --- | --- | --- |
| 空回答 | 0 | 去空白后为空 | 一条都没有 |
| 截断 | 3 | `finish_reason=length`，或末字不在句末字符集，或代码围栏为奇数，或引号外的括号/花括号未闭合 | GRW004 draw3（length，停在 966 字）；SIT120 draw2 与 draw4（`tool: write(...)` 的字符串没正常终止，`({` 未闭合） |
| 复读 | 0 | 同一行或同一段（≥20 字）出现 ≥3 次，或同一 10 词片段出现 ≥3 次 | 实测最大重复次数 2，两个判据都没到 3 |
| 回显 | 0 | 无工具动作，且回答的用词 ≥95% 已在处境里出现，且长度 ≤ 处境的一半 | 172 条无工具动作的回答里用词重合最高 0.891（SIT168 draw3，一条实测结论汇报），没过 0.95 |
| 重复 target | 95 | 同一处境内归一化后逐字相同，只留最早一条 | 735 条里去重后 637 |

重复 target 是这批数据的主要损耗，不是坏件：温度 0.0 下同一条处境的 3 条抽样经常逐字相同，这也是 `evidence/densify/summary.json` 里 `modal_label_stability` 只有 0.81 的同一个事实的两面。

判重只做在同一处境内。跨处境逐字相同的 target 有 104 组额外重复，没有合并：合并会把某条 prompt 与它自己的 target 配错，而样本的价值在这对配对上。

## 切分

`situation` 到 `session` 是一对多，所以按会话切：51 个会话 id 排序后用种子 20261020 打乱，顺次累加会话进验证集，累计样本占比首次越过 0.175 就停。

| 侧 | 会话 | 样本 | 处境 |
| --- | --- | --- | --- |
| 训练 | 43 | 510 | 194 |
| 验证 | 8 | 127 | 48 |

验证集占样本 19.9%、占会话 15.7%，落在计划要求的 15–20% 区间（程序里断言了 0.15–0.20，越界直接退出而不是写下不合格的切分）。

写盘后独立核对过三条：两侧会话交集 0；两侧处境交集也是 0（处境只属于一个会话）；两侧样本数相加等于全量。切分方式、种子、两侧会话 id、输入与输出文件的 sha256 都记在 `evidence/sft/split.json`。

## 覆盖

沿 `data/coverage.json` 的既有标注重算：一条规则被记为覆盖，意思是至少有一条幸存样本的处境被标注到它；没有标注的处境一律按不覆盖记，不重新标注。

| 规则被多少条样本覆盖 | 规则数 |
| --- | --- |
| 0 | 98 |
| 1 | 26 |
| 2–4 | 26 |
| 5–9 | 11 |
| 10+ | 14 |
| **合计** | **175** |

覆盖 77 条，最多的是 `attention.phases.discussion.act_now`（93 条样本），其次 `attention.phases.discussion.round`（63 条）与 `attention.phases.discussion.divergence`（56 条）。98 条一条都没有的包括 `laws.projection`、`laws.no_op`、`laws.top_down`、`intent.objective.product_bar.surface`、`intent.objective.mechanism_triad`、`intent.objective.true_metric`。逐条计数、未覆盖清单、以及 68 条没有标注的处境 id 都在 `data/sft-coverage-counts.json`。

这个 77 是下界而不是实测：242 条处境里 174 条有标注，68 条没有（`SIT` 与 `GRW` 批次之外的都不在标注覆盖范围内），它们带进来的覆盖被记成 0。

## 运行时断言

断言写在 `scripts/build_sft.py` 的 `assert_prompts` 里，构建时无条件执行，失败就退出、一个文件都不写，没有留开关。

- prompt 不含法条原文：拿 175 条可训练规则每条的「长度 ≥30 的首句」当法条独有短语（175 条），在 637 条 prompt 里逐条查，命中 0。
- prompt 不以任何 target 开头：367 个去重后的 target 前 40 字，637 条 prompt 没有一条以它们开头。
- 负控：把一条法条短语接进某条 prompt，断言触发并退出（`1 条 prompt 含法条原文，例：[('GRW001', 'laws.top_down', 'A rule is derived from this roo…']`）；把某条 target 的前 200 字前置到 prompt，断言同样触发（`1 条 prompt 以某条 target 开头`）。两个负控都跑过，所以这两条断言不是恒真的。

## 限制

1. 一条处境只有 3–4 条 law 抽样，不是 5 条；637 条样本摊到 242 条处境，平均 2.6 条，25 条处境只剩 1 条样本。要凑满 5 条得把 densify 之外的三个批次并进来，那是另一个决定。
2. 覆盖 77/175 是下界：68 条处境没有标注，它们的覆盖记为 0；不重标是题面要求。
3. 复读、回显两类 0 命中是判据的结果，不是检测没跑：最大重复次数 2、无动作回答的最大用词重合 0.891 都记在上面。把阈值放松（例如行重复降到 2 次、重合降到 0.85）会开始丢正常的讨论型回答——172 条无工具动作的回答里大部分是有内容的回复，不是回显。
4. 只在同一处境内判重；跨处境逐字相同的 104 组保留。
5. 代码块里的字符串内容不做结构检查。SIT087 draw3 与 SIT121 draw2 的 `newText` 里 JS 少一个 `}`，因为它在引号里，括号扫描看不见，这两条留在样本里。
6. 切分只按会话分层，没有按工具种类或处境难度分层；验证集 8 个会话 127 条，双侧 loss 的方差会不小，读曲线时要带这个前提。
