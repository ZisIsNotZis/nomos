kind:    report
from:    nomos
spend:   idle-compute
id:      inbox/2026-10-21-next-contract.md（三处文档缺陷 + Q7）

**三处缺陷都在源头改掉了，Q7 关掉；冻结的那一行一个字没动。** 契约的终止条件到齐，所以停在这里，不是撞上 120 分钟。

## 谁的 roadmap 变

portfolio 的 `go` 包：这一格不再欠文档债，下一个 workset 可以直接开。本节点自己剩的活没变，仍是 WP-2、WP-3；Q1/Q2/Q3 仍在人手里。

## 证据：每处缺陷的复现，改前与改后

**缺陷 1（`number_paragraphs` 单向计数）**
改前（`cf1a466`）：`grep -n number_paragraphs AGENTS.md` 在同一个文件里给出两个互相矛盾的计数（M4 里程碑那一行是单向的那一个）；里程碑那一行里各族的数只加得出 51，而同一句写着 56。
改后：里程碑那一行只留七族的族名、总量（56、45 更严 / 11 更松）与最大一族 `number_paragraphs` 的 33（30 判不过 + 3 判过），逐族槽数指到 `report/sft-benchmark.md` 的分歧表——那张表五族加末尾两条本来就等于 56。**没有把 56 的算术再写第二遍**，因为同一个式子已经错过两次（先是 51，后来是 54）。

**缺陷 2（入口说收信目录不存在，而树里有信）**
改前（`cf1a466`）：`git ls-tree -r --name-only cf1a466 mail/` 返回 `mail/2026-10-21-m4-official-grader.md`，而入口两条写着它不存在。
改后（`2cda241`）：那封信里每条事实都已在别处落地（M4 的六条头行数字、三处 review 修正、Q7 的问句、WP-2/WP-3 的状态），落地后删信；约定改成 `inbox/` 的四头行（`kind` / `from` / `spend` / `id`，不写 `to`），`report/measurements.md` 里那处旧路径同改。跟着修掉包本体：`run_m2b_ifeval_full.sh` 现在写 `inbox/`（`3790a86`、`5b78053`，后者补上我第一遍漏掉的那处 `mkdir`）。现在 `git ls-tree -r --name-only HEAD mail/` 为空，`git grep -n "mail/" -- ':!evidence/benchmark/logs-m2b' -- ':!inbox'` 零命中；运行日志 `logs-m2b/` 里那个名字是那次的记录，不改。

**缺陷 3（耗时的上界对空缓存读者不成立）**
改前（`cf1a466`）：`实测 6.5–11 s（含 uv 启动开销）`，写在 `AGENTS.md` 两处、`report/sft-benchmark.md` 两处、`docs/model-card.md` 一处。在树的 `git archive` 副本里跑那条文档命令：热缓存 7.49–13.03 s（13.03 s 那次本机被别的作业压到 load average ≈20），空 `UV_CACHE_DIR` 首次 14.41 / 14.16 s，复核者自己的空环境首次 21.72 s——冷启动两处都超过 11 s。这一段我改过两次上界（8.3 → 9.5 → 13），每次都是新的实测把它推上去的；所以现在只在 RUN.md 那张表里给逐次读数，散文里给一个覆盖全部实测的区间。
改后（`4e2df7c`、`651ef6f`、`019028d`）：五处一律写 `热环境 7.5–13 s（随机器忙闲）、空 uv 缓存首次 14–22 s`；每条读数、命令、条件与每次运行的产物 sha256 落在 `evidence/benchmark/official/RUN.md` 的「Timing」一节，每行钉住它自己所在的 revision。每一次运行（含复核者的五次）产物都是 `01d94585…34c145`，与提交件逐字节相同。

**Q7**
按你的答复：那个数没有来源，记录不再复述它。现在写的是实测——40 个带 `length_constraints:number_words` 的题里 adapter 在这一条指令上仍通过 **19** 个（42 槽里 21 个为真）、base **24** 个（26/42 槽），整题全对 adapter **12** / base **18**。命令 `python3 scripts/number_words_reading.py`（新增、只读）一次打出这四个数：它读 `evidence/benchmark/{base,adapter}-ifeval.json` 的 `output` 与 `data/bench/ifeval.jsonl` 的 `instruction_id_list`/`kwargs`，逐槽重算，不信 `per_instruction` 的同名覆盖。实测读数只留这一个家，「决定了的」那一行指过来。

**冻结的那一行**
`git diff 5ba9a2e..HEAD` 在 `report/sft-benchmark.md`、`docs/paper/draft.md`、`README.md`、`docs/model-card.md` 上只动了耗时那些字、文件表里同一句与新增的脚本行；四面头行数字一处没碰。`number_paragraphs` 33/40 本来就已经在报告、论文 §4.7 与本文「决定了的」里，这次补的是漏掉的 M4 里程碑那一行。

## 独立复核（三轮，fresh context、read-only、我一步没改它的话）

**第一轮判 FAIL，只有 A1 一条**（绑 `16cfc68`）：它重跑了判分命令五次（热 8.65 / 8.02 / 7.91 s、空缓存 19.78 s 后 8.97 s，五次产物同 sha）、跑了 `number_words_reading.py`（与 Q7 逐字相符）、核了两类 grep、核了 `5ba9a2e..16cfc68` 的四面 diff（头行数字一个没动），然后指出 M4 里程碑那一行点名的五族只加到 54，凑不出同一句的 56；另两条非阻塞：`RUN.md` 留着「every timed one under 7 s」这类上界、本文一条「grep 零命中」其实命中它自己。它自己说：这一条是「补一句」的事，不是缺一个检查。
改法（`7498109`）：不补数，把逐族分解收回唯一那个家。两条非阻塞同一次改掉。

**第二轮（窄复核，只判 R1–R5，run `7a44387d…`）判它被绑的两个 revision 各一处 blocker，然后自己写明 HEAD 上都没有了**：① `701be0c` 的 `AGENTS.md:56` 一处写「五族」、另一处写「分七族」——就是第一轮抓的那一行的后半，`c42a8de` 已改；② `3790a86` 的包本体还留着 `mkdir -p mail`（我只改了带斜杠的五处，漏了它），`5b78053` 已改，脚本里再没有旧路径。它在自己重跑的检查里写「`5b78053` 上无 blocker」。它另留两条措辞风险：报告那张表把 56 说成「五族之外只剩两条」、Q8 把 33 说成「两个方向合计」——已按它的话收紧（`40785e5`），两处之后各自重读了一遍，数没有动。

**第三轮（只判 S1–S5，run `0afaef68…`，绑 `8fa49c5`）**：写这份报告时仍在跑，判定未回。它判的是那两处措辞修复与 Q10 这条记录本身；两处修完之后我用 grep 与逐族求和自检过，数没有动——但那是自检，不是独立判定。

## 动过的文件

`git diff --name-status cf1a466..HEAD` 是这份清单的唯一来源（`AGENTS.md`、`report/sft-benchmark.md`、`docs/model-card.md`、`report/measurements.md`、`evidence/benchmark/official/RUN.md`、`evidence/benchmark/run_m2b_ifeval_full.sh`、新增 `scripts/number_words_reading.py`、新增本报告、删 `mail/` 那封与读过的两封信）。提交数是派生值，读 `git log cf1a466..HEAD`。worktree 干净，在 `main` 上，没推（本地领先 `origin/main` 六十余个提交）。

## 开销

`idle-compute`，纯 CPU，零 metered、零 GPU、¥0。墙钟约 25 分钟，其中约 12 分钟是等两轮复核。判分命令一共跑了十次上下，全部十秒量级。

## 要你答的（decision）

**无。** 三处修复与 Q7 都已落地、各自有一条可重跑的命令；M4 的 acceptance 按原样仍在人手里，不由你也不由我给。

## 三件要说的

1. 契约写「从 `master` 的 `cf1a466` 起步」，这个仓库的分支叫 `main`。我没切分支也没建新的，就在 `main` 上做。
2. WP-2（README 那句「约 3.3 秒，随机型负载变化」）与缺陷 3 是同一类毛病——一个读者一计时就能反驳的数。本轮按「60 分钟起不开新包」没碰它，它仍是下一个包的第一个。
3. 「同一句里的数加不齐」这个类在本轮出现了两次（51、然后 54），两次都是补数修好的，也就两次都能再错。现在那一句不再逐族列数，唯一还留着的算术是 33 = 30 + 3 与总数 56 / 45 / 11，都由产物的 `per_checker_disagreement` 直接印出；要根治得有一个拿散文里的数对产物的检查，那是新包，不是本轮。
