# 数据卡：nomos SFT 数据集（366 条样本）

类型：产物。所有者：主代理。上游：[设计](method/design.md)、[数据报告](../report/sft-data.md)、[构建脚本](../scripts/build_sft.py)。

一句话：366 条「一条处境 → 一条带法回答」的样本，来自法条作者本人的 51 个真实会话，用来教一个 2B 模型在没有法条原文的上下文里怎么动手。

## 处境从哪来

| | 值 | 证据 |
| --- | --- | --- |
| 语料 | 本机 agent 会话档案 `~/.pi/agent/sessions`：3312 个 JSONL，其中 275 个是交互会话 | `mining/report.md`、`mining/candidates.jsonl` |
| 人写的用户轮 | 1746 条；工具调用 86 273 次；用户消息里 41% 是 harness 注入，按结构剔除 | 同上 |
| 结构信号 | 455 个候选窗口（六类信号），以用户轮结尾 | 同上 |
| 入账处境 | **242 条，来自 51 个会话**（47 个会话组，fork 与父会话同组） | `evidence/slice-contrast/situations.jsonl`（183 条）+ `evidence/grow/situations.jsonl`（59 条） |
| 一条处境是什么 | 会话的最小片段：工具面清单 + 若干轮对话，以用户轮结尾，含一个决策点 | `evidence/slice-contrast/situations.jsonl` 的 `excerpt` |

处境池封死在 242 条：样本量靠同一处境的多次抽样扩，不靠新增处境。

## 双答与多轮抽样怎么生成

同一批 242 条处境，两种条件各生成多次，模型是 `deepseek-flash`（thinking 关闭）：

| 条件 | system 消息 | 用途 |
| --- | --- | --- |
| `law`（带法） | 整部 `AGENTS.md`（93 670 字符）原文 | SFT 的 target；测量里的参照物 |
| `bare`（不带法） | 无 system 消息 | 参照量表的刻度（不带法强模型）；DPO 的 rejected |

- **双答批次**（`data/pairs.jsonl`）：183 条处境各一对 law/bare，筛掉两侧同动作 6 条与坏件 3 条后 174 条入账，是 DPO 用过的偏好对（[`report/data-quality.md`](../report/data-quality.md)）。
- **加密抽样批次**（SFT 用，`evidence/densify/answers.jsonl`）：242 条处境 × 2 条件 × 3.04 次 = **1470 次调用**（233 条处境每条件 3 条、9 条每条件 4 条），花费 ¥1.253，无失败。其中 `law` 条件的 **735 条**是 SFT 的候选 target。
- **解码**：`temperature 0.0`、`max_tokens 600`、`thinking` 关闭。温度 0 下同一提示重发仍有约 42–51% 的动作差异，这是服务端非确定性，也是整套数据的噪声地板（[`report/resample.md`](../report/resample.md)）。
- **prompt**：处境原文 `excerpt` 接一句续写指令（`INSTRUCTION`），**不含任何法条原文**；构建时用 175 条法条短语逐条查过，命中 0 即通过（[`report/sft-data.md`](../report/sft-data.md) 的「运行时断言」）。

## 筛到什么程度

735 条 law 回答 → **366 条样本**（训练 288 / 验证 78），丢弃 369 条，逐条记录在 `evidence/sft/dropped.jsonl`：

| 类别 | 条数 | 判据 |
| --- | --- | --- |
| 截断 | 3 | `finish_reason=length`、末字不在句末字符集、代码围栏为奇数、引号外括号未闭合 |
| 逐字重复 | 94 | 同处境内归一化 target 完全相同 |
| 重复动作签名 | 244 | 同处境内动作类型串相同（参数不参与），留主流完整动作那条 |
| 重复文字层决策 | 28 | 动作签名都为空、四位决策签名相同且词集 Jaccard ≥ 0.5（命中区间 0.51–0.88） |
| 近重复 | 0 | 签名不同但词集 Jaccard ≥ 0.9，这批数据里不存在 |
| 复读 / 回显 / 空回答 | 0 / 0 / 0 | 判据都跑了，实测最大重复次数 2、无动作回答最大用词重合 0.891，都没到阈值 |

去重只在同一处境内做，因为同一处境的 prompt 逐字相同，抽样之间只差措辞与半条命令——留着它们只给那条处境加权，不给新信息。切分按**会话组**（10 个组 78 条验证，占 21.3%），同一会话组与同一处境都不跨两侧，种子 20261020；写盘后核对两侧会话组交集 0、处境交集 0。输出六个文件的 sha256 在 `evidence/sft/split.json`。

## 脱敏

原始会话**不进仓库**，进仓库的是脱敏后的处境窗口与模型回答：

- **替换（不是删除）**：家目录与其它绝对路径 → `<PATH>`；URL（带查询串的单独标注）→ `<URL>` / `<URL_WITH_QUERY>`；邮箱 → `<EMAIL>`；各家 API key 前缀、GitHub 令牌、云厂商访问键、聊天平台令牌、JWT、私钥块 → `<TOKEN>` / `<CREDENTIAL>`；`key: value` 形态的凭据 → `<CREDENTIAL>`；≥32 位十六进制串 → `<HEX>`；≥44 字节 base64 串 → `<B64>`。
- **整窗丢弃**：含私钥块或高置信凭据形态的窗口不入库，计 `dropped_for_risk`；本轮真实丢掉 **3 条**，里面确有从配置文件抄出来的 API key 与 GitHub 令牌。
- **先脱敏再截断**，免得截断把凭据切成两半、留下认不出的后一半。
- **门**：`mining/check_redaction.py` 解码 JSONL 后逐字段扫描，命中即非零退出。处境批次（`evidence/slice-contrast/build.py`、`scripts/grow_pairs.py`）复用同一份模式表，不另写一套。
- 代价：路径与主机名被抹掉后，处境的上下文少一层（哪个项目、在哪台机器）；模型看不到它们，评测也看不到。

## 能说什么

- 这 366 条覆盖 242 条处境、51 个会话，是「一个人与一个代理协作」的真实处境，不是合成的玩具任务。
- 每条样本带 `situation_id` 与 `session_id`，按 `(situation_id, draw)` 能回到 `evidence/densify/answers.jsonl` 的那一行；丢弃的 369 条带原因与原文片段。
- prompt 不含法条原文，运行时有断言与负控两条证明（把法条短语接进去、把 target 前缀接到 prompt 上，断言都触发）。
- 覆盖 175 条可训练规则中的 77 条，逐条计数在 `data/sft-coverage-counts.json`。

## 不能说什么

- **不能当通用数据集用。** 它是一个人的操作法与一个模型的输出，不含人群、领域、任务多样性的代表性；151 条处境只有一种决策。
- **不能声称「已获数据主体同意」这种程序性事实。** 数据主体就是法条作者本人（会话是他自己的机器上的自己的会话）；这一点是事实，但把它读成「符合某个数据保护法规」不是本仓库能证明的。
- **不能声称覆盖 175 条规则。** 77 是下界：242 条处境里 68 条没有规则标注，它们带进来的覆盖一律记 0。
- **「每处境不同决策数」不是不同行为数。** 它是去重键的取值个数；同动作签名而正文差别大的抽样仍会并成一条（37 条 Jaccard < 0.3 的被丢样本）。
- **文字层判据不是语义判据。** 四位签名（提问/停住/断言/产物）由 `eval/judge.py` 的启发式阈值判，判错时会把两条不同决策并成一条、或把同一决策拆开；没有独立标注可核对。已知漏例：GRW022（同一决定因四位不同全留）、GRW057（同四位但 Jaccard 0.18 全留）。
- **不能与公开数据集比。** 没有可比的对象：这是私有语料上的一次性构造。
- **DeepSeek 的回答受其服务条款约束**，再分发这批回答本身不在本仓库的权限声明范围内（仓库当前未声明许可）。

## 消费方

| 脚本 | 读什么 | 产出 |
| --- | --- | --- |
| `scripts/build_sft.py` | `evidence/densify/answers.jsonl`、处境文件、`constitution/nodes.json`、`data/coverage.json` | `data/sft.jsonl`（366）、`data/sft-train.jsonl`（288）、`data/sft-val.jsonl`（78）、`evidence/sft/dropped.jsonl`、`evidence/sft/split.json` |
| `scripts/train_sft.py` | `data/sft-train.jsonl`、`data/sft-val.jsonl` | `evidence/sft/log.jsonl`、`.tmp/sft/adapter-narrow/` |
| `scripts/measure_actions.py` | 处境文件、`evidence/measure/answers.jsonl`（1452 行：242 × 3 抽样 × 2 侧） | `evidence/measure/summary.json` |

注意区分三个数：**735** 条 law 候选回答（densify 批次）、**366** 条 SFT 样本（去重后）、**1452** 条测量快照（base 与 post 各 3 条抽样，不是训练数据）。
