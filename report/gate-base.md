# 基座门与失败构成门：2B 在这个格式里到底能不能出手

类型：结果（门）。所有者：主代理。上游：[实验规格](../method/spec.md) §1、§6 门 2 与门 3，[M1 计划](../plan/m1.md)「效应量测量与基座门」，[探针 4](probe-4.md)（处境与续写指令的字节来源），[探针 6](probe-6.md)（评委仪器已失效，剩余问题不带裁判）。

状态：**门 2 通过，门 3 通过**。20 个处境 × 2 个条件，贪心解码，共 40 次生成，本机 4090，未花 API。裸条件下 16/20 的下一轮可判定，垃圾件 2/20；带条件下 14/20 可判定，垃圾件 5/20，且垃圾形态集中在截断、重复与回声，不是从头就散架。

复算命令：`python3 report/gate-base/check.py`，从 `generations.jsonl`、`situations.jsonl`、`labels.json` 与本文的计数块重算下面每个计数，不等即退出非 0。生成命令：`python3 report/gate-base/run_generate.py`；处境构造：`python3 report/gate-base/build_situations.py`。

## 1 被测对象

| 项 | 值 |
|---|---|
| 模型 | `Qwen/Qwen3.5-2B`（instruct/chat，非 `Qwen3.5-2B-Base`） |
| revision | `15852e8c16360a2fea060d615a32b45270f8a8fc` |
| 类与参数量 | `Qwen3_5ForConditionalGeneration`，2,213,241,664 |
| 精度 | bf16，无量化、无 vllm、无 bitsandbytes |
| 权重位置 | `/home/z/hf/hub/models--Qwen--Qwen3.5-2B/snapshots/15852e8c…`，仓库内无模型文件 |
| 显卡 | RTX 4090 24 GB，单卡，峰值占用 6.66 GiB（带条件 20k token prompt） |
| 栈 | torch 2.14.1+cu130，transformers 5.20.1 |

这个 id 的 pipeline tag 是 `image-text-to-text`：Qwen3.5-2B 是多模态权重，本实验只走文本通路。`AutoProcessor` 需要 torchvision（未安装），因此用 `AutoTokenizer` 加 chat template；模型类 `AutoModelForImageTextToText` 在纯文本输入下正常加载与生成。解码走 transformers 的参考实现：`causal_conv1d` 与 `flash-linear-attention` 未安装，24 层里 18 层线性注意力跑的是 PyTorch 回退核，transformers 在加载时对此明确警告。因此下面的吞吐是**未优化栈**的量，装了优化核会更快，但没有实测，不在此处报数。

## 2 方法

**处境**。`report/probe-4/situations.jsonl` 的 183 条按信号分层取 20 条，比例 S4 7 / S1 6 / S3 3 / S2 2 / S5 2，种子 `20261028`，抽样脚本与配额见 `build_situations.py`。prompt 与续写指令是探针 4 的逐字节原物（`excerpt + INSTRUCTION`，指令 sha256 `f92e401d…79cd`），只换了样本量。S6 在探针 4 里就没有合格窗口，本批同样没有 S6。

**两个条件**，每个处境各一次，`temperature 0`（贪心）、thinking 关闭（模板输出空 `<think></think>`）、`max_new_tokens 320`（120 词请求的余量；触顶记为截断）：

| 条件 | system message |
|---|---|
| `bare` | 无 |
| `law` | `/home/z/vibe/AGENTS.md` 的整字节，93,670 字符，sha256 `325f8b3e…26ab6` |

实测 prompt 长度：`bare` 均值 526 token，`law` 均值 19,878 token。每次调用记录 usage、墙钟时间、单独计时的 prefill、peek 显存与 finish reason，逐行落进 `generations.jsonl`。

**分类怎么来的**。两个来源分开：`generations.jsonl` 是输出与解码事实；`labels.json` 是我逐行读出的两件事——这份输出是否在回答这个处境（`on_topic`），以及它是否是可执行/可判断的下一轮（`usable_turn`），每行一句理由，共 40 行。其余全部机械判定，写在 `check.py` 的 docstring 里：空、截断（触顶）、重复（20 字符以上的行或 6 词滑动窗出现 3 次以上）、回声（忽略空白后 100 字符逐字来自处境摘录或 system message）、格式塌陷（泄漏控制 token、未闭合代码栅栏、伪造 `user:`/`assistant:` 行）、`tool:` 行是否落在请求的 `name(args)` 形式里。

类别按固定规则合成：有任一垃圾标记即 `garbage`；否则若读出为切题且可用、且没有跑偏形式的 `tool:` 行，即 `competent`；其余 `fluent_wrong`（流畅但不是这个处境可用的回答，或动作的形态不对）。

我另外算了一个纯机械的切题代理（与摘录共享 ≥2 个内容词），给 `bare` 17/20、`law` 18/20。它与人工读的差集全是跨语言改写（GB001、GB003、GB010 裸条件：英文输出回答中文处境），所以它只作仪器读数报出，不参与分类。

## 3 门 2：格式能力

| 计数（n=20） | `bare` | `law` |
|---|---|---|
| 可判定且切题的下一轮（competent） | 16 | 14 |
| 含请求形式的 `tool: name(args)` 行 | 0 | 6 |
| 含 `tool:` 行但形态不对 | 1 | 1 |
| 空 | 0 | 0 |
| 截断（触顶 320 token） | 0 | 5 |
| 退化循环（重复 ≥3 次） | 0 | 2 |
| 同一行出现两次（未计入上一行） | 0 | 1 |
| 格式塌陷 | 2 | 3 |
| 回声（逐字复读摘录或 system message） | 0 | 2 |

**判读**：能。裸条件下 16/20 的下一轮是可直接判断的动作或答复，带条件下 14/20。按 §6 门 2 的判据（产不出可判定动作即分母为 0），分母不是 0。

**但请求的工具行只在带条件下出现**：`bare` 0/20，`law` 6/20。裸条件的输出全是散文式"我会去改 X"，没有任何一条按 `tool: name(args)` 出手；即使处境里充斥着 `call bash({...})` 这样的工具记录。这一条是格式门里唯一的坏消息，且指向 M2 的一个具体设计问题：工具行不是 2B 的默认输出形态，需要示范，或者需要把工具行从必答项改成可选项。

**四种失败形态与引文**。

空：本批 0 条，无引文。

截断（5 条，全在 `law`）。GB010-law 在 bash 代码块里断在一句话中间：

> `# Scenario: A system that silently drops data` / `# Step 1: Input` / `echo "User: I need`

GB017-law 断在"最终建议"的列表项之后：`**最终建议**：` / `- `

退化循环（2 条，全在 `law`）。GB004-law 把一个参数一路加长到触顶：

> `git -C learn_draw ls-files --others --exclude-standard --exclude-standard --exclude-standard --exclude-standard …`（同一条命令里该参数重复 12 次以上）

GB008-law 在用户原文与空 `assistant:` 标签之间来回 3 次以上。同一行重复两次的还有 GB001-law，两次一模一样的 `tool: read({"limit": 48, "offset": 16, "path": "contracts.md"})`。

格式塌陷（`bare` 2 条、`law` 3 条）。`bare` 的两条都是伪造出用户轮：GB015-bare 整条就是 `user: 你刚才说"没有落任何改动"…请立刻更新文档`。`law` 的三条跨了三种形态：GB013-law 把 `AGENTS.yaml` 本体当作 yaml 代码块吐出来；GB010-law 起了 ` ```bash ` 栅栏不闭合；GB008-law 伪造 `user:`/`assistant:` 轮。

回声（2 条）。GB013-law 复读法条本体；GB008-law 复读处境里用户那句"加快速度，怎么这么长时间还没好"三次。

**门 2 结论**：通过。可判定率 16/20 与 14/20，不构成"分母为 0"。附带的坏消息是工具行形态为 0/20（`bare`），它是 M2 必须处理的设计项，不是尺寸问题。

## 4 门 3：失败构成

非合格输出按形态分两桶：`fluent_wrong`（流畅、可读、但不是这个处境可用的回答——叙事化描述、追问式空转、动作形态不对）与 `garbage`（重复、回声、截断、格式塌陷）。

| 条件 | competent | fluent_wrong | garbage | garbage : fluent_wrong |
|---|---|---|---|---|
| `bare` | 16 | 2 | 2 | 2 : 2 |
| `law` | 14 | 1 | 5 | 5 : 1 |

`bare` 的两条垃圾都是伪造用户轮（GB008、GB015）；两条流畅但不可用是 GB013（`tool:` 下写 shell 管道 `git diff --cached --numstat | tail -n +100 | head -20`，不是 `name(args)`）与 GB017（用第三人称复述对话"助手需确认当前进度…"而不是写这一轮）。

`law` 的五条垃圾全部是触顶截断；叠在上面的语义失败是重复 2 条（GB004、GB008）、回声 2 条（GB008、GB013）、未闭合栅栏 1 条（GB010）、伪造轮 1 条（GB008）。只有 GB017 是纯截断，没有别的标记。唯一一条流畅但不可用是 GB020 的 `tool: render_policy.py --check`，动作没有参数、也没有指向这个处境。

**判读**：垃圾不占多数。两种条件下都是"多数输出仍是可读、切题、可判断的"，按 §6 门 3 的判据（垃圾占多数说明尺寸不到谈政策的阶段），本尺寸**可以**用政策语言谈论。要同时记下两件事：一是带法条后垃圾从 2 涨到 5，形态是"读进去 20k token 之后开始复读或刹不住"，与探针 4 的 H2（长法条读不进）方向一致；二是 5 条垃圾全部触顶，也就是说这批垃圾的共同条件是刹不住而不是不会写——除了法条回声那条，语义本身并没有垮。

**门 3 结论**：通过，限制是垃圾的多数由长度失控制造，n=20 的区间很宽。

## 5 法条有没有改变输出

`bare` 与 `law` 的 20 对逐字节比较：**0 对相同，20 对都不同**。差异的量级：平均输出 28.9 词（`bare`）对 59.5 词（`law`）；`law` 的 5 条触顶即为长度分布右移的直接证据。

规则的指名或引用，按我逐条读的结果：

- 逐字规则 id：`bare` 0 条，`law` 1 条——GB014-law 写出 `migrate_on_touch` 并给出"最新事实写文档、日志归档到 Tickets"的三条对应。
- SSOT 这一条：`bare` 2 条（GB005、GB014，因为这两个处境本身就在谈本仓的 SSOT），`law` 3 条。GB005-law 用中文复述了"每个事实只有一个家"并据此反问 `Q2/Q3` 标称是否保留。
- 法条自带的检查脚本：`law` 1 条（GB020 的 `render_policy.py --check`）。
- 整条复读：`law` 1 条（GB013）。

**不判优劣**，只报形态：法条进入上下文后，输出从"散文承诺"变成"散文承诺 + 更长的清单"，工具行从 0 变成 6，规则名从 0 变成偶尔出现，代价是多出 3 条截断与 2 条重复。机械读数：`law` 的 prompt 是 `bare` 的 38 倍，输出长度是 2.06 倍。

## 6 一次全量跑的成本

实测（同一张 4090，同一栈，未装优化核）：

| 量 | `bare` | `law` |
|---|---|---|
| 解码速率（中位） | 22.8 tok/s | 23.5 tok/s |
| prefill 速率（20k token prompt 实测） | — | 9,647 tok/s |
| 单次实测墙钟（均值 / 中位） | 2.64 s / 2.47 s | 8.58 s / 7.24 s |
| 单次 prompt / 输出 token | 526 / 58.8 | 19,878 / 149.4 |
| 20 次合计 | 52.8 s | 171.7 s |

120 词的目标长度按实测折算是 187 token（英文输出 1.556 token/词，取自 16 条英文为主的输出）。于是单次生成 = prompt prefill + 187 token 解码：

- `bare`：0.05 s + 8.19 s = **8.2 s/次**，20k 次 ≈ **45.8 小时**（1.9 天）。
- `law`：2.06 s + 7.95 s = **10.0 s/次**，20k 次 ≈ **55.6 小时**（2.3 天）。

一次 20k 的裸条件生成约两昼夜单卡；带法条的一轮再加十小时。这是未装 `flash-linear-attention` / `causal_conv1d` 的数字，装上的加速没有实测，不折进这张表。显存不是瓶颈（峰值 6.66 GiB），2B bf16 在 24 GB 上还剩 17 GiB，与训练侧是否能同时驻留无关本门，但这一行决定了 M2 的排期单位是"天"而不是"小时"。

## 7 限制

- n=20，每格 1 次贪心采样，没有重复采样，因此"重复/回声"这类低频形态的估计区间很宽。
- 20 条来自 17 个会话：3 个会话各贡献两条（对应源处境 `SIT042`/`SIT118`、`SIT098`/`SIT127`、`SIT108`/`SIT115`）。有效独立单位小于 20。
- 只覆盖 S1–S5 五个信号；S6 在探针 4 的候选池里就没有合格窗口。
- `on_topic` 与 `usable_turn` 是人工读，不是裁判模型：判据是"处境最后一条用户轮要什么"。理由逐行写在 `labels.json`，可被逐条反驳。纯机械的切题代理低估 3 条跨语言改写，已单独报出。
- 40 次生成分布在两个进程：前 9 行由一次先崩掉的进程写出（同一代码与同一参数；崩点在带条件 prefill 的显存上，那时还在算全词表 logits）。文本与后 31 行同等有效，本文件所有文本计数不分进程；但那时 `peak_gpu_gib` 字段已不成立，峰值 6.66 GiB 取自后 31 行。同一参数的两次贪心重算（GB003、GB016）与落盘文本逐字节相同。
- 截断被算进垃圾（照任务书的四分法），因此 `law` 的垃圾数受 320 token 上限影响：上限再高，GB017 大概率会变成一条流畅但超长的回答，GB004 的重复则不会消失。
- 栈是未优化核；吞吐不能代表 vllm 或装了 fla 之后的吞吐。下载路径也不在常规路线上：`hf.co` 直连与 Xet CDN 在本机均不可达，权重经 `hf-mirror.com` 取得，4.55 GB 安全张量用 16 路并行 range 拼装，sha256 与仓库元数据一致（`aa33250c…80b1`），再按 HF 缓存布局落地。

## 8 对 M2 的三个直接后果

1. **分母不为 0**：可判定动作的门可以在 2B 上算，不需要先解决"模型根本不出手"。
2. **工具行要教**：`bare` 0/20 的 `tool: name(args)` 命中率意味着格式教学的第一项是工具行，而不是政策条文。它同时说明带法条时工具行会出现，所以这一项与法条内化有交互，M2 的评测要把"工具行是否出现"单独计一列。
3. **长度纪律是独立失败轴**：法条条件下 4/5 的垃圾来自刹不住。训练与评测都要把 120 词上限当硬约束记数，否则可判定动作的计数会被"话多"污染。

<!-- gate-base-counts {"bare": {"n": 20, "competent": 16, "fluent_wrong": 2, "garbage": 2, "marks": {"empty": 0, "truncated": 0, "repetition": 0, "prompt_echo": 0, "format_collapse": 2, "duplicate_line": 0, "tool_line": 0, "tool_line_other": 1, "token_overlap": 17}, "garbage_ratio": "2:2", "garbage_share": 0.1, "situations": {"GB001": "competent", "GB002": "competent", "GB003": "competent", "GB004": "competent", "GB005": "competent", "GB006": "competent", "GB007": "competent", "GB008": "garbage", "GB009": "competent", "GB010": "competent", "GB011": "competent", "GB012": "competent", "GB013": "fluent_wrong", "GB014": "competent", "GB015": "garbage", "GB016": "competent", "GB017": "fluent_wrong", "GB018": "competent", "GB019": "competent", "GB020": "competent"}}, "law": {"n": 20, "competent": 14, "fluent_wrong": 1, "garbage": 5, "marks": {"empty": 0, "truncated": 5, "repetition": 2, "prompt_echo": 2, "format_collapse": 3, "duplicate_line": 1, "tool_line": 6, "tool_line_other": 1, "token_overlap": 18}, "garbage_ratio": "5:1", "garbage_share": 0.25, "situations": {"GB001": "competent", "GB002": "competent", "GB003": "competent", "GB004": "garbage", "GB005": "competent", "GB006": "competent", "GB007": "competent", "GB008": "garbage", "GB009": "competent", "GB010": "garbage", "GB011": "competent", "GB012": "competent", "GB013": "garbage", "GB014": "competent", "GB015": "competent", "GB016": "competent", "GB017": "garbage", "GB018": "competent", "GB019": "competent", "GB020": "fluent_wrong"}}, "identical_pairs": 0} -->
