# nomos

这个节点拥有 `nomos` 这个项目的 roadmap。项目本身是一条线：把一份个人操作法（本工作区 `agent-policy` 里那份 264 个叶子的法）用 242 条真实处境筛出的 288 条样本压进一个 2B 模型的权重，并测量它到底有没有进去、代价是不是通用能力。这个节点存在，是因为上一批工作已经把「可证伪」这件事做出来了——同一批 148 条处境、每处境每侧 9 条抽样，带法减不带法的差是 0.0593 [0.0263, 0.0923]，不含 0，而 3 条时同一条差是 0.0496 [−0.0068, 0.1059]、跨 0。于是留给这个项目的已经不是「尺子能不能量」，而是「量出来的东西到哪里为止」：尺子的两端都低（带法侧对它自己只有 0.3198），文字层口径仍跨 0，通用能力现在测到了 n=100 并且有一格真的掉了。这个节点的顺序由这个判断决定：先把已经发出去、读者一测就能反驳的话改对（M2 已把 n=100 的读数落进报告与引用面），再把掉的那一格加宽到能撑住一个结论（M3，包已备好、等上一层按一次命令派出），最后才是需要新钱的口径二与截断幅度。不用钱的事排成工作包自己做完，钱和方向的问题写成报告往上一层送。

## 入口

怎么开始：读本文件，再读 `report/sft-benchmark.md` 开头那段「结论」的四格表（n=100）与「这个 n 能看见多大的掉幅」；口径与主指标读 `report/sft-measurement.md` 的「重估的结论（一句话）」与三个口径表。`mail/` 现在不存在（两封信落地后删掉了，见「哪些不是当前的」）。

怎么继续：M2 的读数已经落地，M3（IFEval n=100→295）**已在本次会话派发**，run id `m3-ifeval-295`，driver pid 在 `evidence/benchmark/logs-m2b/driver.pid`，日志在 `evidence/benchmark/logs-m2b/`。它跑完自己往 `mail/` 写 `completion`，读到就落地：把 IFEval 的 n=295 读数替换进 `report/sft-benchmark.md` 与引用面（做法照 n=100 那一次：新读数顶掉旧读数，旧的移到「前一次估计」），然后删信。**在 M3 落地之前不要动 §4.7 与引用面里的 IFEval 数**，否则文本与证据会分叉。两种失败各自怎么认：`logs-m2b/driver.log` 有 `analyse rc=` 而 `mail/` 里没有信 → 包没活到写报告那一步，按 `logs-m2b/` 的续跑点把包叫回来（拆出去的东西不能自己再执行）；`driver.log` 末行是 `cells done: base rc=124`（或 `adapter rc=124`）→ 撞上 `timeout 10800` 被杀，`run_bench.py` 只在最后写盘、没有续跑点，被杀的那一路只能整条重跑。

与通用约定不一样的地方：`docs/plan/plan.md` 是项目**过去**的工作包状态记录，不是本节点的 roadmap，别把它当路线图读、也别为了让报告好看去回填它（它现在仍写着 n=20 那一版，是历史快照）；`report/measurements.md` 的花费表只增行、不改旧行，GPU 墙钟单列在「本机 GPU（不计钱）」一节；许可原文按「字节数 + sha256 + 取回 URL」登记在 `README.md` 的「许可」与 `THIRD-PARTY.md`；`scripts/measure_anchor.py --analyse` 每跑一次会往 `evidence/measure/anchor-draws9/run.log` **追加**一行 `cmd:`，所以那个文件不标 hash，也是唯一允许脏着出现在 `git status` 里的路径。

哪些不是当前的：`mail/` 目录现在不存在（两封信都落地到本文件，删完就没了；M3 的包跑完会重建它并写 `completion`）；`docs/plan/plan.md` 的状态行是历史快照，里面 n=20 的结论句已被本轮的 n=100 读数取代；`evidence/measure/anchor-draws9/run.log` 里重复的 `--analyse` 行是同一批数据的复核，不是第二次分析。

## roadmap

### 里程碑

**M2（本轮已报，等上一层读）**：把通用能力四格从 n=20 补到约定的 n=100，并让所有引用它的发布文本跟着改。

- 观测（决定它成没成）：`report/sft-benchmark.md` 出现四格（GSM8K/IFEval × base/adapter）n=100 的配对结果，每格带配对 95% 区间与**重新算过的检出下限**。判定读法只有两种：任一格的配对区间不含 0 且指向负向 → 结论从「没有可信的下降证据」改成「测到这个幅度，其余格仍无可信下降」；四格都含 0 → 只能写「n=100 下仍没测到」，并写明这时能看见的最小掉幅是多少 pp。
- **结果（2026-10-21）**：走的是第一种。GSM8K 73/100 → 76/100，+3.0pp，[−6.0, +12.0]，10 掉 13 涨，p=0.678；**IFEval 57/100 → 45/100，−12.0pp，[−22.0, −3.0]，19 掉 7 涨，p=0.029**。检出下限 n=100 是 5pp（McNemar）/ 4pp（区间），n=20 时是 25pp / 20pp。证据 `evidence/benchmark/paired-{gsm8k,ifeval}.json`、四格 `evidence/benchmark/{base,adapter}-{gsm8k,ifeval}.json`、`evidence/benchmark/logs-n100/`（提交 `6dc8f52`）。
- 引用面改完（本轮）：`report/sft-benchmark.md`、`docs/paper/draft.md`（摘要、§1、§4.7、§4.8、§5.2、§6、§7）、`README.md`（结果一行、不是什么、限制、报告索引）、`docs/model-card.md`（结果、限制 7）、`report/measurements.md`（GPU 墙钟一节）。
- 花费：`idle-compute`（单卡 4090），派发时按 ≈5 小时给；**实测墙钟 1.31 小时（4713 s），用量 26%**，零 metered，¥0。账在 `report/measurements.md`「本机 GPU（不计钱）」。
- 报告对象：root。**报告已写**（本轮最终回答），其中一条偏离要记住：包在 `analyse rc=0` 之后退出，没有往 `mail/` 写 `completion`，所以四格读数是从 `paired-*.json` + `driver.log` 转录的，包自己的叙述没有到达——`report/sft-benchmark.md` 里 n=20 那一段的机制读法（「五条掉点全是格式合规」）是上一轮写下的，n=100 的逐条读法是我按落盘记录重算的，不是包写的。

**M3（包已备好、未派发；派发是上一层的事）**：把 IFEval 那一格从 n=100 加宽到全量 295，回答「−12pp 是 adapter 的性质，还是这 100 条的性质」。

- 为什么是这一格：M2 的唯一负面结论压在两件薄东西上。其一，p=0.029 是**两个套件各检验一次、没有做多重比较校正**的值，Bonferroni α=0.025 下就压线；其二，逐条读 19 条掉点可见 **2 条是字数下限擦线**（398/400、195/200），这 2 条翻正就把 p 推到 0.064、点估计推到 −10pp。n=100 的墙很薄，n=295 能把区间从 ±10pp 收到 ≈±5pp，并且第 101–295 条对当前读数是全新的。
- 观测（决定它成没成）：`evidence/benchmark/paired-ifeval.json` 的 `n` 变成 295，区间与 McNemar p 重算，且 `report/sft-benchmark.md` 把它写成当前读数、把 n=100 那一版移到「前一次估计」。两种可能的落法都要能读：区间仍不含 0 → 论文可以冻；区间回到跨 0（比如 n=295 上 −5pp [−11, +1]）→ 论文的 IFEval 句子要退回「n=100 测到、n=295 没测到」。
- 花费：`idle-compute`（同一张 4090），两格各补 195 条，按 n=100 实测 22–23 s/条算 ≈75 min/格、两路并行 ≈80 min。M2 还剩 ≈3.7 小时授权，所以不需要新授权；**不碰 metered**。
- 期限：2026-10-31（Q4 那条日期对 M3 仍然成立）。
- 报告对象：本节点。
- **派发状态（2026-10-21T14:07Z 起）**：**已派发**，run id `m3-ifeval-295`，driver = `setsid nohup bash evidence/benchmark/run_m2b_ifeval_full.sh > evidence/benchmark/logs-m2b/driver.out 2>&1 &`，pid 在 `logs-m2b/driver.pid`。派发是上一层明确交回来的（`mail/2026-10-21-dispatch-m2b.md` 已落地后删）：一个写好、检过的脚本躺在 `evidence/` 里不算派发，节点拥有自己的 roadmap 和拆法。脚本第一步把当前 n=100 的四格与两份配对结果拷进 `evidence/benchmark/n100/`（照 `n20/` 的做法），因为 `run_bench.py` 与 `analyse_paired.py` 的输出路径固定，全量会覆盖规范名。
- **花费（起飞时更正了契约里的估数）**：契约写「按 n=100 实测 22–23 s/条算 ≈75 min/格、两路并行 ≈80 min」，那个数算的是**补 195 条**；而脚本跑的是**全量 295 条**，所以真实预估是 22.1 s×295 = 6519 s（base）/ 23.4 s×295 = 6903 s（adapter），两路并行 ≈1.9 h。离 `timeout --kill-after=60 10800` 的 3 h 硬上限只有 1.6 倍余量，而这次起飞时卡上不是空的（见下一条），所以这一格有真实的被上限杀掉的可能。
- **起飞时卡不是空的（已记录，不改变派发）**：`nvidia-smi` 显示 16320 MiB 空闲 / 7788 MiB 已用 / util 95%，占用者是 `pathlm` 的 7 臂纵深训练（pid 292712，`axes/1-time/1.2.1-dilated/experiments/2689-longT-layerdil-13m/run.py --stage train --arm dil32-t2048-s0`，2026-10-21T14:02:53+08:00 起，608 MiB + 6.7 GiB 两层进程）。预检的线是 12000 MiB（两路 4-bit 2B 共 ≈4.4 GiB），过了，所以按包里已经检过的判断起飞；代价是算力共用，真实墙钟可能抬到 2.5–3 h。上一层的排序规矩是「撞上就别往后拖，取早的那个窗」，2026-10-31 是唯一不能重新谈的日期，所以不换窗、不排队等卡。
- **没有一起派的东西，以及为什么**：GSM8K 全量（200 条、≈40 min）不派——那一格区间 [−6, +12] 已经排除了 5pp 以上的下降，加宽只会把它收成 ≈[−4, +9]、仍然跨 0，信息量买不到它的时间。

**M1（已报、已被上一层接受，不再欠）**：匹配锚点每处境每侧 9 条重估，主指标上「读了法」减「没读法」不含 0。证据：`evidence/measure/anchor-draws9/`（`answers.jsonl` 1776 行、`summary.json`、`per-situation.jsonl`、`run-meta.json`、`run.log`），提交 `fff3441`、`12a4d12`，报告 `report/sft-measurement.md`「复算」一节。**不再重跑，也不再花 metered 钱**：那批证据已结。

### 工作包（我自己执行，不报告）

- **WP-2（F2）**：README 的「约 3.3 秒」要么改写成「约 3–5 秒，随机型负载变化」，要么在一台空机上重录一次并把两次读数一起写进 `docs/plan/plan.md` 的「发布准备」。现状是可被读者一计时就反驳的声明。验收：README 与 plan 的读数一致，且都说明测的条件。**仍未做**。
- **WP-3（F1）**：`constitution/lock.yaml` 的 `upstream:` 还指向一个已经不存在的路径；改成法当前的家 `agent-policy/`，并在同一次提交里写一句「冻结副本仍按 sha256 校验，所以旧路径不伤害任何东西」。**限定条件**：只在下一个碰到这个 lock 的改动里做，不单独为它开一次提交去碰冻结区。
- **WP-4（已完成）**：M2 的四格新读数同步进引用面。做法与结果见 M2 那一条的「引用面改完」。

## 现在的事实

### 决定了的

- **M2 的读数与它改掉的那句话（本轮最重要的一条）**：`report/sft-benchmark.md` 现在的主表是 n=100 的四格：GSM8K +3.0pp [−6.0, +12.0]、IFEval **−12.0pp [−22.0, −3.0]**、p 分别 0.678 / **0.029**，检出下限 4–5pp。所以「没有可信的下降证据」这句话**只在 GSM8K 那一格成立**；IFEval 上测到了 12 点，而且区间整个在 0 的负侧。论文的 §1 半句因此被**改写而不是删除**：通用能力这一截从「不可证伪」变成「有一格反例、一格未被推翻」，agentic 那一截仍未测。
- **掉的是什么，不是「能力」这个词能盖住的**：19 条 IFEval 掉点逐条读到指令层，6 条丢 `length_constraints:number_words`、4 条丢 `punctuation:no_comma`、2 条丢 `detectable_content:number_placeholders`、2 条丢 `detectable_format:number_highlighted_sections`、2 条丢 `startend:quotation`、余下三条是 `json_format` / `english_capital` / `forbidden_words` 各一；逐条 id 落在 `report/sft-benchmark.md`。机制是 adapter 把回答写短了：IFEval 词数中位数 **212.5 → 169.0**（均值 248.3 → 202.8），GSM8K 中位数 **204.0 → 83.0**（均值 210.2 → 95.1，100 条里 99 条更短）。逗号那一组不靠长短解释（`ifeval-2374` adapter 反而 143 → 212 词），是句式变了。两套件 200 份记录 `unscorable` 都是 0。
- **多重比较与「两条擦线」写到了数字旁边（2026-10-21，本次会话）**：IFEval 的 −12.0pp / p=0.029 出现的每一处，现在都在同一段里带两条：① p=0.029 是两个套件各检验一次、未做多重比较校正的值，Bonferroni α=0.025 下不过线；② `ifeval-1072`（至少 400 词写成 398）与 `ifeval-2844`（至少 200 词写成 195）两条只差 2 与 5 个词，翻正就是 **17 掉 / 7 涨、Δ = −10.0pp、精确 McNemar p = 0.064**（不一致 24 条，`p = 2·Σ_{k=0}^{7} C(24,k)/2²⁴`，已用 `paired-ifeval.json` 重算核对）。落地的面：`report/sft-benchmark.md`（结论节 + 逐条节）、`docs/paper/draft.md`（摘要、§1、§4.7、§5.2、§6、§7 出处表）、`README.md`（结果一行 + 报告索引）、`docs/model-card.md`（结果、限制 7）、`evidence/benchmark/n100/README.md`。此前这些内容只在限制节或脚注里，正文与摘要的 −12pp 是裸的。
- **一个用词更正（表达缺口）**：被交代的机制句里把 GSM8K 的 210.2 → 95.1 称作「中位数」，实际它是**均值**；GSM8K 的中位数是 204.0 → 83.0。两个统计量现在都写出来了，并且各处都标清哪个是哪个，不再混用。
- **许可**：本仓库自己的代码与文档是 `AGPL-3.0-only`（作者 2026-10-21 指定）；原文已落 `licenses/AGPL-3.0.txt`（34523 字节，sha256 `0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0`，取自 <https://www.gnu.org/licenses/agpl-3.0.txt>，未改一字）。适配器权重不在这条里：它是 `Qwen/Qwen3.5-2B` 的衍生权重，随基座走 Apache-2.0。
- **发布**：已获授权，最后一次推是 `74793ff`（`bdbbe31..74793ff`，10 个提交）。**推完之后在本机做的提交都没推**，包括 M2 那一批（`6dc8f52` 等）与本轮这一批；下一个推把它们一起带上。本轮**没有推**（上一层的指令）。
- **钱**：DeepSeek 累计 **9059 次 ¥15.6493**（17 批分项在 `report/measurements.md`「花费」）；匹配锚点两批合计 2664 次 ¥2.1300。**GPU 这一轮的金额是 ¥0**：花费类 `idle-compute`，墙钟 1.31 h / 授权 5 h = 26%。M3 接着用剩下的 ≈3.7 h。
- **数字以哪一版为准**：锚点读数是 9 条那一份；3 条那一份只在「同一样本的前一次估计」的位置上出现，并且每次出现都带「跨 0、那份宽度是抽样噪声」的说明。文字层口径二在 99 条相交子集上是 0.0303 [−0.0180, 0.0819]，仍然跨 0。通用能力以 n=100 那一版为准，n=20 那一版降为「前一次估计」（`evidence/benchmark/n20/`）。
- **M2 的派发方式留了一条运行时经验**：包内的后台 watcher 会随它的 turn 一起被回收，所以长跑只能长在 `setsid` 的 driver 上；等待必须靠「driver 自己写 completion 到 mail/」或一次带 `waitFor` 的调用，**不能用后台任务加「结束 turn 等通知」，也不能 `sleep`**。上一轮就是这样被 30 分钟的 harness 杀掉的（那封 timeout 信已落地，就是本条，原信删了）。

### 开着的（每条都带做法与重开的观测）

- **Q1（要钱，在人手里）口径二要不要开**：0.0303 [−0.0180, 0.0819]，n=99，区间宽 0.10。**这一条已经不在上一层了**：2026-10-21 带着「不要花」的建议送进人手里，答案会以 mail 到达；不阻塞任何事。**做法**：不是加抽样能解决的——抽样只压噪声、压不出比 0.06 更大的信号；要开它得把处境池从 242 条/51 个会话扩出去（脱敏门现成）+ 新的 metered 生成。**重开的观测**：人给一个明确的 metered 额度，或明确说这一版不要口径二。在这之前不挖、不花。
- **Q2（要钱，在人手里）320 token 截断的压制幅度**：锚点 2664 条里 42 条触顶（1.6%），本地 1452 条里 30 条，压低的幅度未测。**做法**：同一批处境用 `max_tokens 600` 重抽锚点，2664 次 metered；本地那 30 条可以在 4090 上用 idle-compute 重生成。**重开的观测**：一次 metered 授权，或人说不值得测。
- **Q3（方向，在人手里，已被本轮改了一半）§1 的 agentic 半句**：`e6f34cc` 只做了不越权的那一半（「本轮未测 + 四个具名缺失依赖 + 选型表位置」）。本轮 M2 落地后又改了一次 §1：**通用能力那一截不再是「不可证伪」，它有一格反例**；agentic 那一截照旧未测。所以现在送在人手里的问题只剩「agentic 这半句是窄化还是补测」。**做法与重开的观测**：答「窄化」→ §1 与 `docs/method/design.md` §1 一起改成只留可测的那半；答「补测」→ `report/sft-benchmark.md` 的选型表已写明补轴代价（BFCL 要 HF 可达 + 上千行 harness），先解依赖再谈跑。
- **Q4（资源）GPU 在 2026-10-31 之后还能不能用**：未知。M2 已经落盘，所以 M2 本身不再依赖答案；**M3 已派发**（run id `m3-ifeval-295`，≈1.9 h 预估，起飞时卡上 pathlm 的臂占着 ≈7.8 GiB / util 95%，预检过 12000 MiB 线时是 23111 MiB 空闲——pathlm 的臂是 ≈4.2 分钟一臂、逐臂串行的，所以共用的代价是分摊而不是独占）。**重开的观测**：M3 写到 `mail/` 的 `completion` 落地即整条日期线解除（`paired-ifeval.json` 的 `n` 变成 295）；若 10-31 前没跑完或被 3 h 上限杀掉，要报一次 shortfall，写清丢的是什么（IFEval 那一格停在 n=100）与还剩几次重跑，不能默默延期。
- **Q5（已关）公开可读**：2026-10-21 匿名 `curl -sI https://github.com/ZisIsNotZis/nomos` 返回 `HTTP/2 200`。

## 证据指针

- 主结果：`evidence/measure/summary.json`、`evidence/measure/anchor-matched/`（888 行 / ¥0.7115）、`evidence/measure/anchor-draws9/`（1776 行 / ¥1.4184，`law_matched_self_agreement` 0.3198、`matched_law_minus_matched_bare` 0.0593）。
- 读数与口径：`report/sft-measurement.md`；花费总账：`report/measurements.md`「花费」与「本机 GPU（不计钱）」。
- 通用能力（M2）：`report/sft-benchmark.md`；四格 n=100 与两份配对：`evidence/benchmark/{base,adapter}-{gsm8k,ifeval}.json`、`evidence/benchmark/paired-{gsm8k,ifeval}.json`；运行日志与 pid：`evidence/benchmark/logs-n100/`；前一次估计：`evidence/benchmark/n20/`。
- 通用能力（M3，未派发）：`evidence/benchmark/run_m2b_ifeval_full.sh`（包本体，含契约与起飞命令）；起飞后日志在 `evidence/benchmark/logs-m2b/`，n=100 那一版会进 `evidence/benchmark/n100/`。
- 发布文本：`README.md`、`docs/model-card.md`、`docs/paper/draft.md`、`docs/plan/plan.md`（历史快照）、`THIRD-PARTY.md`、`licenses/`。
- 复核这一轮用的命令：n=100 的四个数直接读 `evidence/benchmark/paired-*.json`；19 条掉点的指令拆解用 `report/sft-benchmark.md`「逐条读 19 条 IFEval 掉点」里那段只读脚本；鉴别力（区间是否跨 0）用 `python3 -c` 算 McNemar 精确检验；四个锚点产物的 sha256 见 `report/sft-measurement.md`「复算」表。
