# nomos

这个节点拥有 `nomos` 这个项目的 roadmap。项目本身是一条线：把一份个人操作法（本工作区 `agent-policy` 里那份 264 个叶子的法）用 242 条真实处境筛出的 288 条样本压进一个 2B 模型的权重，并测量它到底有没有进去、代价是不是通用能力。这个节点存在，是因为尺子这一端已经能分开了——同一批 148 条处境、每处境每侧 9 条抽样，带法减不带法的差是 0.0593 [0.0263, 0.0923]，不含 0，而 3 条时同一条差是 0.0496 [−0.0068, 0.1059]、跨 0。于是留给这个项目的不是「尺子能不能量」，而是「量出来的东西到哪里为止」：尺子两端都低（带法侧对它自己只有 0.3198），文字层口径仍跨 0，通用能力在 IFEval 上测到 −12.2pp 且区间 [−17.6, −6.8] 不含 0（n=295）。这个节点的顺序由这个判断决定：先把已经发出去、读者一测就能反驳的话改对（M2 已把 n=100 的读数落进报告与引用面），再把掉的那一格加宽到能撑住一个结论（M3，2026-10-21 跑完并落地），现在剩下的要么需要新钱、要么需要人给方向：口径二、320 token 截断幅度、agentic 那一半是窄化还是补测。不用钱的事排成工作包自己做完，钱和方向的问题写成报告往上一层送。

## 入口

怎么开始：读本文件，再读 `report/sft-benchmark.md` 开头「结论」那张两格表（GSM8K n=100、IFEval n=295）与「这个 n 能看见多大的掉幅」；口径与主指标读 `report/sft-measurement.md` 的「重估的结论（一句话）」与三个口径表。收信目录是 `inbox/`，约定见本节「与通用约定不一样的地方」；读过的信落地即删，所以那里通常只剩还没被读的几封。

怎么继续：M2、M3、M4 都已落地，引用面（`README.md`、`docs/model-card.md`、`docs/paper/draft.md`、`report/sft-benchmark.md`、`evidence/benchmark/n100/README.md`）已全部换成当前读数，并且都带上了官方 grader 那一行。本节点自己还剩的活是 WP-2、WP-3 两条工作包；Q1/Q2/Q3 都在人手里等答案，**不阻塞任何事，也不该被谁替人答**；Q7 已按上一层的答复关掉（那个数按实测改写，读法与命令见 Q7）。**没有上一层的话不要推**：本轮所有提交都在本机。

与通用约定不一样的地方：`inbox/` 里没有 `README.md`，也不该有——信的四个头行是 `kind:`（resource / cost / direction / contract / report）、`from:`、`spend:`、`id:`（`id:` 写它答的是哪一封），文件名 `inbox/YYYY-MM-DD-<slug>.md`，正文一句结论开头、末尾写 effort；不写 `to:`，收件人由「这是哪一层的 `inbox/`」决定。读信先落地（事实进本文、命令执行、答不了的转投上一层 `inbox/` 并带上 `id:`）再删文件，删信与落地同一次提交，`inbox/` 跟着仓库进版本控制。`docs/plan/plan.md` 是项目**过去**的工作包状态记录，不是本节点的 roadmap，别把它当路线图读、也别为了让报告好看去回填它（它现在仍写着 n=20 那一版，是历史快照）；`report/measurements.md` 的花费表只增行、不改旧行，GPU 墙钟单列在「本机 GPU（不计钱）」一节；许可原文按「字节数 + sha256 + 取回 URL」登记在 `README.md` 的「许可」与 `THIRD-PARTY.md`；`scripts/measure_anchor.py --analyse` 每跑一次会往 `evidence/measure/anchor-draws9/run.log` **追加**一行 `cmd:`，所以那个文件不标 hash，是允许脏着出现在 `git status` 里的路径之一。另一处是 `evidence/benchmark/logs-{n100,m2b}/` 下的 `driver.log`、`driver.out` 与逐格日志：跑的时候它们一直在长，脏着就是「跑着」，不是漂移；现在两轮都跑完了，它们与产物同一次提交落盘，之后不该再变。

哪些不是当前的：`work/` 目录现在不存在（WP-5 的产物在 M4 里毕业进 `evidence/benchmark/official/`，工作区里没有留下的中间件）；`docs/plan/plan.md` 的状态行是历史快照，里面 n=20 的结论句已被 n=100 与 n=295 的读数取代；`evidence/measure/anchor-draws9/run.log` 里重复的 `--analyse` 行是同一批数据的复核，不是第二次分析；**IFEval 的 n=100 读数（57/100 → 45/100、−12.0pp [−22.0, −3.0]、19 掉 / 7 涨、p=0.029）现在是前一次估计**，只在「同一冻结前缀的前 100 条」这个位置上出现，当前读数是 n=295；GSM8K 的 n=100 读数**不是**前一次估计，它就是当前读数（那一格没加宽）。

## roadmap

### 里程碑

**M4（已落地，2026-10-21）：把 IFEval 那一格交给参考实现重算，回答「−12.2pp 是我们的尺子量出来的，还是官方 grader 也量得出来」。**

- 观测（决定它成没成）：`evidence/benchmark/official/official-ifeval.json` 给出官方 strict 与 lax 的 base/adapter 计数、配对差与区间、McNemar p、逐检查器分歧表，并且 `report/sft-benchmark.md` 与三处引用面（`README.md`、`docs/model-card.md`、`docs/paper/draft.md`）都写上这一行。
- **结果**：官方 strict **196/295 → 160/295、−12.2pp、[−17.6, −6.8]、55 掉 / 19 涨、McNemar p 3.38e-5**；lax **−11.2pp [−16.9, −5.4]、p 2.17e-4**；本仓库那把尺子作对照行 184 → 148、−12.2pp、[−17.6, −6.8]、54 / 18、p 2.57e-5。点估计与区间端点两边一致，换的是 74 条不一致里哪几条（我们 72 条）。**所以「−12.2pp 是自己尺子的产物」这条反驳消失了。**
- **两把尺子确实分得开，方向与预计相反**：836 个指令槽里 56 个判得不一样（45 个我们更严、11 个我们更松），整题层两侧各 22 条；分歧是 `number_paragraphs` 33 / 40 槽（30 槽我们判不过、3 槽我们判过；我们数空行、官方按指令点名的 `***`）、`json_format` 7、`forbidden_words` 6（子串 vs `\b` 词边界）、`change_case` 7（官方多一道 `langdetect`）、`number_words` 1（`_words` 空白切分，唯一一条）。11 条逐条人读：官方对 7、我们对 3（3 条全是 `langdetect`）、1 条口径问题。**动手前预计的两个咬点里 `_no_comma` 一条也没咬到**：11 条逗号掉点在官方尺子上全部仍是整题掉点。
- **官方判分器本身不可复现，钉住再用**：`change_case` 检查器内部调 `langdetect`，`DetectorFactory.seed` 默认 `None`，未钉时同一份输出在两个进程里给出 160 与 159；`grade_official.py` 钉 `DetectorFactory.seed = 0` 与 `random.seed(0)`，三次连续运行逐字节相同。
- 花费：`idle-compute`，纯 CPU **热环境 7.5–9.5 s、空 `uv` 缓存首次 14–22 s**（含 `uv` 启动；读数、条件与命令在 `evidence/benchmark/official/RUN.md` 的「Timing」一节），零 metered，¥0；判分不重跑模型、不碰 GPU。产物 41.7 KB，六个 vendor 文件随仓库分发（Apache-2.0，`THIRD-PARTY.md` 有署名与「未改一字」声明）。
- 证据：`evidence/benchmark/official/`（`official-ifeval.json`、`grade_official.py`、`dump_disagreements.py`、`HANDCHECK.md`、`VENDOR.md`、`RUN.md`、`vendor/instruction_following_eval/`），提交 `e1cd6d8`；报告 `6ede844`；引用面 `e23990b`。
- **这条复核之后能攻击的只剩口径选择，不是数据缺失**：① 三行都是同一条 seed-0 贪心路径上的一个点；② 54 条掉点里 11 条 `no_comma` + 7 条 `number_words` 都是格式类指令，拆成「格式/内容」两类后结论只能落在前者；③ 官方 strict 上基座 66.4% 的 Wilson 上沿 71.6%，比判别带 70% 的上沿高 1.6pp（我们那把是 62.4%、上沿 67.7%，在带内）。

**M3（已落地，2026-10-21）**：把 IFEval 那一格从 n=100 加宽到全量 295，回答「−12pp 是 adapter 的性质，还是这 100 条的性质」。

- 观测（决定它成没成）：`evidence/benchmark/paired-ifeval.json` 的 `n` 变成 295，区间与 McNemar p 重算，且 `report/sft-benchmark.md` 把它写成当前读数、把 n=100 那一版移到「前一次估计」。
- **结果**：`n: 295`，base **184/295 = 62.4%**、adapter **148/295 = 50.2%**、Δ **−12.2pp**、配对区间 **[−17.6, −6.8]**、**54 掉 / 18 涨**（不一致 70）、McNemar p **2.57e-5**、检出下限 **5 条 / 1.7pp（McNemar）、4 条 / 1.4pp（区间）**、`unscorable=0`。区间仍不含 0，所以走的是约定里的第一种落法（论文可冻），n=100 那一版降到「前一次估计」。
- **加宽是纯加法，可核**：n=295 的前 1–100 条记录与 `evidence/benchmark/n100/` 那两份**逐字节相同**（两侧各 100/100），n=100 的 19 条掉点全部落在 54 条里。所以点估计只从 −12.0pp 动到 −12.2pp，动的是宽度（19pp → 10.8pp）与 p（0.029 → 2.57e-5）。**这不是两次读数一致，是一次读数把分母从 100 加到 295**：两版之间相同的那 100 条一致是算术结果，不是第二次测量印证了第一次。
- 引用面改完（同一批提交）：`report/sft-benchmark.md`（结论表、headroom、配对对照、逐条读 54 条、检出下限、前一次估计、落盘、实测速度、未跑与续跑、判读方法）、`README.md`（结果一行、不是什么、报告索引）、`docs/model-card.md`（结果、限制 7）、`docs/paper/draft.md`（摘要、§1、§4.7、§4.8、§5、§7、出处表）、`report/measurements.md`（GPU 墙钟 M3 那一行由「未定」补成实测）、`evidence/benchmark/n100/README.md`（把两条 caveat 的现状写清）。
- 花费：`idle-compute`（同一张 4090），实测墙钟 **1 h 43 min 10 s（6190 s）**，是派发时剩余授权（≈3.7 h）的 **47%**；两轮合计 3.03 h / 5 h = 61%。零 metered，¥0。账在 `report/measurements.md`「本机 GPU（不计钱）」。
- 证据：`evidence/benchmark/{base,adapter}-ifeval.json`、`evidence/benchmark/paired-ifeval.json`、`evidence/benchmark/logs-m2b/`，提交 `cbbde88`。

**M2（已报、已被上一层接受，不再欠）**：把通用能力四格从 n=20 补到 n=100，并让所有引用它的发布文本跟着改。GSM8K 73/100 → 76/100、+3.0pp [−6.0, +12.0]、10 掉 13 涨、p=0.678；IFEval 57/100 → 45/100、−12.0pp [−22.0, −3.0]、19 掉 7 涨、p=0.029（这一格现已由 M3 取代）。证据 `evidence/benchmark/paired-{gsm8k,ifeval}.json`、四格 `evidence/benchmark/{base,adapter}-{gsm8k,ifeval}.json`、`evidence/benchmark/logs-n100/`（提交 `6dc8f52`），n=100 的四格与两份配对已拷进 `evidence/benchmark/n100/`。花费 `idle-compute` 4713 s（授权的 26%），零 metered。

**M1（已报、已被上一层接受，不再欠）**：匹配锚点每处境每侧 9 条重估，主指标上「读了法」减「没读法」不含 0。证据：`evidence/measure/anchor-draws9/`（`answers.jsonl` 1776 行、`summary.json`、`per-situation.jsonl`、`run-meta.json`、`run.log`），提交 `fff3441`、`12a4d12`，报告 `report/sft-measurement.md`「复算」一节。**不再重跑，也不再花 metered 钱**：那批证据已结。

### 工作包（我自己执行，不报告）

- **WP-2（F2）**：README 的「约 3.3 秒」要么改写成「约 3–5 秒，随机型负载变化」，要么在一台空机上重录一次并把两次读数一起写进 `docs/plan/plan.md` 的「发布准备」。现状是可被读者一计时就反驳的声明。验收：README 与 plan 的读数一致，且都说明测的条件。**仍未做**。
- **WP-3（F1）**：`constitution/lock.yaml` 的 `upstream:` 还指向一个已经不存在的路径；改成法当前的家 `agent-policy/`，并在同一次提交里写一句「冻结副本仍按 sha256 校验，所以旧路径不伤害任何东西」。**限定条件**：只在下一个碰到这个 lock 的改动里做，不单独为它开一次提交去碰冻结区。
- **WP-4（已完成）**：M2 的四格新读数同步进引用面。
- **WP-5（已完成，2026-10-21；M4 就是它的落地）**：用 Google 官方 `instruction_following_eval`（pin `e6890f85757dd84e27ca6df2dd30651dafad28e0`）重算 590 份落盘输出的 IFEval 判定。验收的五项都过了：官方 strict/lax 的 base/adapter 计数、配对差与区间、McNemar p、逐检查器分歧表；两处预计的分歧（`_words` 空白切分、`_no_comma` 任一字面逗号）现在有了结论——前者只咬 `ifeval-1072` 一条、后者一条也没咬到；重跑复现同一 JSON。产物已毕业进 `evidence/benchmark/official/`（提交 `e1cd6d8`），`work/` 临时区因此不存在了。**官方区间不含 0，所以没有触发「跨 0 就停在这里」那条闸。**

## 现在的事实

### 决定了的

- **IFEval 的读数现在是 n=295，而且它的脆弱性换了性质（本轮最重要的一条）**：184/295 → 148/295、−12.2pp、[−17.6, −6.8]、54 掉 / 18 涨、p=2.57e-5、下限 1.7pp / 1.4pp。三件事同时变了：① 区间从 19pp 宽收到 10.8pp，上界 −6.8pp 连「只掉 5pp」也排除；② **多重比较这一条不再削弱它**——p=2.57e-5 在 Bonferroni α=0.025 下过线，余量约 970 倍，这条 caveat 保留在正文里但写的是「过线」而不是删掉；③ **两条擦线的敏感性不再翻掉标题**——翻正 `ifeval-1072`（398/400）与 `ifeval-2844`（195/200）得 52 掉 / 18 涨、p=5.85e-5，翻正 7 条字数掉点全族得 47 掉 / 18 涨、p=4.22e-4，要让 p 回到 0.025 门外得翻正 19 条。「翻两条就变 p=0.064」现在只描述 n=100 那一版读数。
- **−12.2pp 经得起参考实现（M4 的结论，本轮最重要的一条）**：Google 官方 grader（pin `e6890f85`）在同一批 590 份输出上是 strict **196/295 → 160/295、−12.2pp、[−17.6, −6.8]、55 掉 / 19 涨、p 3.38e-5**、lax **−11.2pp [−16.9, −5.4]、p 2.17e-4**，点估计与配对区间跟本仓库那把尺子的对照行一致到端点（184 → 148、−12.2pp、[−17.6, −6.8]、54 / 18、p 2.57e-5）。所以这一格现在可以说「换尺子不换结论」，只剩口径选择可攻击（三条列在 M4 里）。
- **绝对分取决用哪把尺子，差值区间不取决**：官方 strict 的 base 是 66.4%（我们那把 62.4%）、adapter 是 54.2%（50.2%）。所以与公开 IFEval 数比只能用官方那一行，且仍是 295 条抽样、不能与论文里的 541 条直接比；判别带判定不随尺子翻转（两边点估计都在 30–70% 内），但官方 strict 的 Wilson 上沿 71.6% 比带上沿高 1.6pp。
- **两把尺子的分歧是五族、方向与预计相反**：836 槽里 56 槽不一致，45 槽我们更严、11 槽更松；`number_paragraphs` 33 / 40 是最大一族（其中 30 条我们更严、3 条我们更松；我们数空行，官方按指令点名的分隔符），`json_format` 7（官方先剥栅栏）、`forbidden_words` 6（子串 vs `\b` 词边界）、`change_case` 7（官方多一道 `langdetect`，这三族里官方更贴指令原文）、`number_words` 1。11 条人读：官方对 7、我们对 3、1 条口径问题。**预计的第二个咬点 `_no_comma` 一条也没咬到。**
- **官方 grader 不钉 `langdetect` 种子时自己不可复现**：`change_case` 检查器内部调 `langdetect`、`DetectorFactory.seed` 默认 `None`，未钉时同一份输出在两个进程里给出 160 与 159（±1 条 = 0.34pp）。`grade_official.py` 钉 `DetectorFactory.seed = 0` 与 `random.seed(0)`，三次连续运行逐字节相同；任何引官方 grader 的数的人都要先钉种子。
- **掉点的形状也变了：字数不是最大的一族，而且「回答变短」不是判别式**：n=295 的 54 条掉点里，最大单族是 `punctuation:no_comma` **11 条**（base 全部 0 个逗号，adapter 写出 1–34 个，其中 **7 条 adapter 反而更长**，极端是 `ifeval-2324` 22 → 547 词 / 34 个逗号），其次 `length_constraints:number_words` **7 条**（6 撞下限、1 撞上限），再往下是 highlighted 7、placeholders 6、forbidden_words 5、quotation 5，其余各 1–3 条；51 条只丢一条指令、2 条丢两条、1 条（`ifeval-2069`）因同名指令在 `per_instruction` 里被覆盖而在文件里看不出。词数中位数 IFEval **185 → 130**（均值 218.4 → 177.6，188/295 条更短），但**54 条掉点里只有 28 条更短（52%），而两侧都对的 130 条里 88 条更短（68%）**——变短在每一组里都发生，选不出这 54 条。所以 n=100 那版「机制是回答变短」的写法被降级为「背景位移，不是判别式」，论文与报告都已改过来。GSM8K 那一格的字数位移（中位数 204.0 → 83.0、均值 210.2 → 95.1，n=100）仍是已测事实。
- **一个记录层的缺陷，不修判分**：`scripts/bench_suites.py:226` 的 `per_instruction` 是 `dict(zip(instruction_id_list, strict))`，同名指令（如「100 到 120 词」的上下限）互相覆盖，`ifeval-2069` 因此是 `correct=False` 而所有指令都写 `True`。修它等于换落盘格式、两侧都要重跑；现在的做法是把它写进报告的「逐条读 54 条」与「判读方法」两节，让读者知道它不是完整指令清单。
- **上一层已经接受冻稿的形状，并要求先跑一次官方 grader（2026-10-21 回信，已落地）**：数字可以按原措辞冻（带地板与 `unscorable=0`），但 §4.7 的因果句不能冻（已降级为「背景位移，不是判别式」），且 19-of-54 的算术要进正文（已进）。回信要求的第一步是拿 Google 官方 `instruction_following_eval` 重算 590 份落盘输出（WP-5 已落地，见 M4）；若官方区间跨 0，那是 `cost` 报告而不是静默改写——**它没跨**，所以没有触发那条闸。回信里那个「`number_words` 题仍通过多少」的数没有来源：上一层 2026-10-21 明说那是它自己的数、它给不出读法。记录因此改成实测读法，数与命令只有一处（见 Q7 与 `scripts/number_words_reading.py`）；这一格作为反机制观测比回信那句更强，不是更弱。
- **冻稿的答案：可以冻，而且现在可以带条件说死（本轮回答，等上一层读）**：条件是「IFEval 的 −12.2pp 在 n=295 上区间不含 0、p 过 Bonferroni」。现在最弱的一句不是 IFEval，而是**GSM8K 那一格的用法**（n=100、区间跨 0、只能写「没测到」）与**agentic 那一截仍未测**。要推翻 IFEval 这句，评审不需要新数据——他只要指出：同一把尺子上 adapter 的 −12.2pp 与 base 侧的 62.4% 都发生在一条 seed-0 的固定贪心路径上，而这条路径只跑过一次；或者指出 54 条掉点里 11 条 `no_comma` + 7 条 `number_words` 全是「格式合规」类指令，若把 IFEval 分数拆成「格式类」与「内容类」两类指令，结论只能落在前者。这两条都不是数据缺失，是**口径选择**，所以它们要在正文里说清而不是等评审发现。
- **多重比较与「两条擦线」在每一处都带状态**：`report/sft-benchmark.md`（结论节 + 逐条节 + 前一次估计）、`README.md` 结果一行、`docs/model-card.md` 结果与限制 7、`docs/paper/draft.md` 摘要/§1/§4.7/§5/§7、`evidence/benchmark/n100/README.md`。四处都写明 n=295 过线、n=100 不过线，没有一处把 caveat 删掉。
- **一个用词更正（表达缺口）**：被交代的机制句里把 GSM8K 的 210.2 → 95.1 称作「中位数」，实际它是**均值**；GSM8K 的中位数是 204.0 → 83.0。两个统计量现在都写出来并标清，不再混用。
- **许可**：本仓库自己的代码与文档是 `AGPL-3.0-only`（作者 2026-10-21 指定）；原文已落 `licenses/AGPL-3.0.txt`（34523 字节，sha256 `0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0`，取自 <https://www.gnu.org/licenses/agpl-3.0.txt>，未改一字）。适配器权重不在这条里：它是 `Qwen/Qwen3.5-2B` 的衍生权重，随基座走 Apache-2.0。
- **发布**：已获授权，最后一次推是 `74793ff`（`bdbbe31..74793ff`，10 个提交）。**推完之后在本机做的提交都没推**，包括 M2 那一批（`6dc8f52` 等）、M3 落盘（`cbbde88`）与 M3 的引用面/信这一批（本轮最后一个提交）；下一个推把它们一起带上。本轮**没有推**（上一层的指令）。
- **钱**：DeepSeek 累计 **9059 次 ¥15.6493**（17 批分项在 `report/measurements.md`「花费」）；匹配锚点两批合计 2664 次 ¥2.1300。**GPU 两轮的金额都是 ¥0**：花费类 `idle-compute`，M2 墙钟 1.31 h（授权 5 h 的 26%）、M3 墙钟 1.72 h（剩余授权的 47%），合计 61%。授权里还剩 ≈1.97 h。
- **数字以哪一版为准**：锚点读数是 9 条那一份；3 条那一份只在「同一样本的前一次估计」的位置上出现，并且每次出现都带「跨 0、那份宽度是抽样噪声」的说明。文字层口径二在 99 条相交子集上是 0.0303 [−0.0180, 0.0819]，仍然跨 0。通用能力：**GSM8K 以 n=100 为准、IFEval 以 n=295 为准**；IFEval 的 n=100 与两套件的 n=20 都降为「前一次估计」（`evidence/benchmark/n100/`、`evidence/benchmark/n20/`）。
- **M2 的派发方式留了一条运行时经验**：包内的后台 watcher 会随它的 turn 一起被回收，所以长跑只能长在 `setsid` 的 driver 上；等待必须靠「driver 自己写 completion 到 `inbox/`」或一次带 `waitFor` 的调用，**不能用后台任务加「结束 turn 等通知」，也不能 `sleep`**。M3 按这条跑，两路都 rc=0、driver 把 completion 写进了 `inbox/`。

### 开着的（每条都带做法与重开的观测）

- **Q1（要钱，在人手里）口径二要不要开**：0.0303 [−0.0180, 0.0819]，n=99，区间宽 0.10。**做法**：不是加抽样能解决的——抽样只压噪声、压不出比 0.06 更大的信号；要开它得把处境池从 242 条/51 个会话扩出去（脱敏门现成）+ 新的 metered 生成。**重开的观测**：人给一个明确的 metered 额度，或明确说这一版不要口径二。在这之前不挖、不花。
- **Q2（要钱，在人手里）320 token 截断的压制幅度**：锚点 2664 条里 42 条触顶（1.6%），本地 1452 条里 30 条，压低的幅度未测。**做法**：同一批处境用 `max_tokens 600` 重抽锚点，2664 次 metered；本地那 30 条可以在 4090 上用 idle-compute 重生成。**重开的观测**：一次 metered 授权，或人说不值得测。
- **Q3（方向，在人手里）§1 的 agentic 半句**：`e6f34cc` 只做了不越权的那一半（「本轮未测 + 四个具名缺失依赖 + 选型表位置」），M2/M3 落地后又改了一次 §1：**通用能力那一截不再是「不可证伪」，它有一格反例且现在区间更硬**；agentic 那一截照旧未测。所以现在送在人手里的问题只剩「agentic 这半句是窄化还是补测」。**做法与重开的观测**：答「窄化」→ §1 与 `docs/method/design.md` §1 一起改成只留可测的那半；答「补测」→ `report/sft-benchmark.md` 的选型表已写明补轴代价（BFCL 要 HF 可达 + 上千行 harness），先解依赖再谈跑。
- **Q7（已关，2026-10-21）上一次回信里那个 `number_words` 通过数没有来源**：上一层答得干脆——那是它自己的数、它给不出读法，不必再找。落盘记录上的实测是：40 个带 `length_constraints:number_words` 的题里，adapter 在这一条指令上仍通过 **19** 个（42 个槽里 21 个为真）、base **24** 个（26/42 槽），整题全对 adapter **12** / base **18**。**改法**：记录里那一句按实测写成 19 / 24 与 12 / 18，命令 `python3 scripts/number_words_reading.py` 打出这四个数——它读 `evidence/benchmark/{base,adapter}-ifeval.json` 的 `output` 与 `data/bench/ifeval.jsonl` 的 `instruction_id_list`/`kwargs`，用 `scripts/bench_suites.check_ifeval` 逐槽重算，不信 `per_instruction`（同名指令只留最后一条）。它作为反机制观测比回信那句更强，不是更弱。**重开的观测**：有人拿出一个能与回信那个数对上的读法（另一把尺子、另一批题），那时再改。
- **Q4（已关）GPU 在 2026-10-31 之后还能不能用**：M3 已落盘，那条日期线整条解除（`paired-ifeval.json` 的 `n` 已是 295，`report/measurements.md` 的 M3 行已由「未定」补成实测）。要再跑 GPU 才有这个问题，现在没有要跑的。
- **Q5（已关）公开可读**：2026-10-21 匿名 `curl -sI https://github.com/ZisIsNotZis/nomos` 返回 `HTTP/2 200`。
- **Q8（已关）M4 的独立 review**：reviewer（fresh context、read-only、九条契约，run `d62d9490-53c2-4736-ac27-7e5b893ca26d`）在 `e23990b` 上**判 PASS**：重跑 `grade_official.py` 得到逐字节相同的产物（`01d94585…`），六条头行数字与抽检的每个量化主张全对，A1/A2/A3/A5 与 J1–J4 全过，还从产物的掉/涨 id 集合独立重算三行配对自举、端点与落盘值一致（strict 与 ours 端点相同是 1/295 格点上的巧合，两行分别计算）。它挑出三处、都已按它给的 reproduction 改掉（提交 `acf9a9a`）：① 分歧表 `number_paragraphs` 写「30 / 40」是单向计数，两个方向合计是 **33 / 40**（30 我们判不过 + 3 我们判过），「五族之外只剩两条」因此与 56 对不上——报告、论文 §4.7 与本文「决定了的」一节同改，但本文 M4 里程碑那一行当时漏了，Q9 那次 review 又抓到，2026-10-21 补上；② `RUN.md` 与本文各留一处旧路径 `work/official-ifeval-grader/`，按预登记的 A4 该判 FAIL——两处改写，现在 `grep -rn "work/official-ifeval-grader"` 零命中；③ README 与模型卡的「官方对 7、我们对 3」漏了第 11 条，现写 7 / 3 / 1。
- **Q9（已关，2026-10-21）M4 这一轮的独立 review：判 PASS，带三处文档缺陷**：reviewer（fresh context、read-only）以 `0b04e04` 为基线看 `e1cd6d8..5ba9a2e`（12 个提交），在 `git archive` 出来的副本里重跑 `grade_official.py` 五次，产物与提交件逐字节相同（`01d94585…34c145`），并把报告与三处引用面上的每个量化主张逐条对过产物。三处缺陷都只动文档、不动标题，已按它给的 reproduction 改掉：① M4 里程碑那一行的 `number_paragraphs` 仍是单向计数，与同一句里的 56 加不齐（`d6defd3`）；② 入口写着收信目录不存在，而树里正有一封没读的信（`2cda241`）；③ 判分耗时那句对空 `uv` 缓存的读者不成立，改成热/冷两档并把读数落进 `RUN.md` 的「Timing」（`4e2df7c`；冷启动上界取自两处独立读数，收成 14–22 s 的是 `651ef6f`）。它没有重开 M4 的验收，也没有看到会改变头行数字的东西；M4 的 acceptance 仍在人手里。

- **Q6（新增，低优先，在我手里）`per_instruction` 同名覆盖**：见「决定了的」里那条缺陷。**做法**：下一次要动 `scripts/run_bench.py` 的落盘格式时，把它改成 `list[[name, bool], ...]`，并在同一次提交里重跑两格；不单独为它开跑。**重开的观测**：下一轮真要跑套件的那一刻，或有人拿 `per_instruction` 做指令级统计之前。

## 证据指针

- 主结果：`evidence/measure/summary.json`、`evidence/measure/anchor-matched/`（888 行 / ¥0.7115）、`evidence/measure/anchor-draws9/`（1776 行 / ¥1.4184，`law_matched_self_agreement` 0.3198、`matched_law_minus_matched_bare` 0.0593）。
- 读数与口径：`report/sft-measurement.md`；花费总账：`report/measurements.md`「花费」与「本机 GPU（不计钱）」。
- 通用能力（当前）：`report/sft-benchmark.md`；IFEval n=295 的 `evidence/benchmark/{base,adapter}-ifeval.json` 与 `evidence/benchmark/paired-ifeval.json`（`n: 295`）、运行日志与 pid 在 `evidence/benchmark/logs-m2b/`，提交 `cbbde88`；GSM8K n=100 的四格与 `evidence/benchmark/paired-gsm8k.json`，日志在 `evidence/benchmark/logs-n100/`，提交 `6dc8f52`。
- 参考实现复核（M4）：`evidence/benchmark/official/official-ifeval.json`（官方 strict/lax 与我们的尺子三行、区间、p、逐检查器分歧、掉/涨算术、确定性记录）、`grade_official.py`（一次运行热环境 7.5–9.5 s、空 `uv` 缓存首次 14–22 s，重跑逐字段相同）、`HANDCHECK.md`（11 条分歧逐条人读）、`VENDOR.md` 与 `vendor/instruction_following_eval/`（六个文件逐字节，Apache-2.0，`THIRD-PARTY.md` 有署名），提交 `e1cd6d8`；报告节 `report/sft-benchmark.md`「参考实现的尺子」（`6ede844`）。
- 前一次估计：IFEval n=100 与两套件 n=20 的四格、两份配对与说明在 `evidence/benchmark/n100/`（含 `README.md` 写明哪几条 caveat 只属于它）与 `evidence/benchmark/n20/`。
- 复核这一轮用的命令：所有分数直接读 `evidence/benchmark/paired-ifeval.json`；掉点拆到指令层用 `report/sft-benchmark.md`「逐条读 54 条 IFEval 掉点」里那段只读脚本；词数中位数/均值与「哪一组更短」用 `len(record['output'].split())` 在落盘记录上直接算；敏感性（翻 2 条 / 翻 7 条 / 临界翻 19 条）用精确 McNemar `p = 2·Σ_{k=0}^{min(d,g)} C(d+g,k)/2^(d+g)` 重算，`d/g` 取翻转后的掉/涨数；四个锚点产物的 sha256 见 `report/sft-measurement.md`「复算」表。
- 发布文本：`README.md`、`docs/model-card.md`、`docs/paper/draft.md`、`docs/plan/plan.md`（历史快照）、`THIRD-PARTY.md`、`licenses/`。
