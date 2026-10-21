kind:    report
from:    nomos
spend:   idle-compute
id:      inbox/2026-10-21-next-contract.md（三处文档缺陷 + Q7）

**三处缺陷都在源头改掉了，Q7 关掉；冻结的那一行一个字没动。** 你这份契约的终止条件到齐了，所以停在这里，不是撞上 120 分钟。

## 谁的 roadmap 变

portfolio 的 `go` 包：这一格不再欠文档债，下一个 workset 可以直接开。本节点自己剩的活没变，仍是 WP-2、WP-3；Q1/Q2/Q3 仍在人手里。

## 证据：每处缺陷的复现，改前与改后

**缺陷 1（`number_paragraphs` 单向计数）**
改前（`cf1a466`）：`grep -n number_paragraphs AGENTS.md` 同时给出 23 行的 `30 / 40` 与 56 行的 `33 / 40`；23 行那句里各族的数只加得出 51，而同一句写着 56。
改后（`d6defd3`）：23 行写 `33 / 40 槽（30 槽我们判不过、3 槽我们判过）`；同一句里 33+7+6+7+1 再加 startend、combination 各 1 = 56，与 `evidence/benchmark/official/official-ifeval.json` 的 `per_checker_disagreement` 逐族相加（33/7/6/4+3/1/1/1）一致。

**缺陷 2（入口说收信目录不存在，而树里有信）**
改前（`cf1a466`）：`git ls-tree -r --name-only cf1a466 mail/` 返回 `mail/2026-10-21-m4-official-grader.md`，而入口两条写着它不存在。
改后（`2cda241`）：那封信里每条事实都已在别处落地（M4 的六条头行数字、三处 review 修正、Q7 的问句、WP-2/WP-3 的状态），落地后删信；约定改成 `inbox/` 的四头行（`kind` / `from` / `spend` / `id`，不写 `to`），`report/measurements.md` 里那处旧路径同改。现在 `git ls-tree -r --name-only HEAD mail/` 为空，`grep -rn "mail/" --include=*.md .` 在 `inbox/` 之外零命中。

**缺陷 3（耗时的上界对空缓存读者不成立）**
改前（`cf1a466`）：`实测 6.5–11 s（含 uv 启动开销）`，写在 `AGENTS.md` 两处、`report/sft-benchmark.md` 两处、`docs/model-card.md` 一处。在同一棵树的 `git archive` 副本里跑那条文档命令：热缓存三次 8.27 / 7.88 / 7.49 s，有一次与别的进程同时跑是 9.53 s，空 `UV_CACHE_DIR` 首次 14.41 s；review 在自己的空环境上首次 21.72 s。两处冷启动都超过 11 s。
改后（`4e2df7c`、`651ef6f`）：五处一律写 `热环境 7.5–9.5 s、空 uv 缓存首次 14–22 s`；读数、命令、三个条件与每次运行的产物 sha256 落进 `evidence/benchmark/official/RUN.md` 的「Timing」一节，钉的是 `cf1a466` 那棵树（`80098eb`）。五次运行产物全部是 `01d94585…34c145`，与提交件逐字节相同。`grep -rn "6.5–11"` 零命中。

**Q7**
按你的答复：那个数没有来源，记录不再复述它。现在写的是实测——40 个带 `length_constraints:number_words` 的题里 adapter 在这一条指令上仍通过 **19** 个（42 槽里 21 个为真）、base **24** 个（26/42 槽），整题全对 adapter **12** / base **18**。命令 `python3 scripts/number_words_reading.py`（新增、只读）一次打出这四个数，它读 `evidence/benchmark/{base,adapter}-ifeval.json` 的 `output` 与 `data/bench/ifeval.jsonl` 的 `instruction_id_list`/`kwargs`，逐槽重算，不信 `per_instruction` 的同名覆盖（`830b4e3`）。实测读数只留这一个家，「决定了的」那一行指过来（`188d702`）。

**冻结的那一行**
`git diff 5ba9a2e..HEAD` 在 `report/sft-benchmark.md`、`docs/paper/draft.md`、`README.md`、`docs/model-card.md` 上只动了耗时那一句、文件表里同一句与新增的脚本行；四面的头行数字一处没碰。这台尺度上的 `number_paragraphs` 33/40 本来就已经在报告、论文 §4.7 与本文「决定了的」里，这次补的是漏掉的 M4 里程碑那一行。

## 动过的文件（`cf1a466..HEAD`，11 个提交）

`AGENTS.md`（M4 里程碑、两处耗时、入口三条、运行时经验一条、Q7 关闭、Q8 一处自相矛盾、新增 Q9）、`report/sft-benchmark.md`（两处耗时、文件表一行）、`docs/model-card.md`（一处耗时）、`report/measurements.md`（一处旧路径）、`evidence/benchmark/official/RUN.md`（新增「Timing」一节）、`scripts/number_words_reading.py`（新增）；删掉 `mail/2026-10-21-m4-official-grader.md` 与读过的两封信。

worktree 干净，`main` 上，没推：本地领先 `origin/main` 55 个提交，与本轮之前同一状态（这一轮的 11 个都在其中）。

## 开销

`idle-compute`，纯 CPU，零 metered、零 GPU、¥0。墙钟约 35 分钟（含一次独立 review 的等待）。判分命令跑了五次，全部 10 秒量级。

## 要你答的（decision）

**无。** 三处修复与 Q7 都已落地、各自有一条可重跑的命令；M4 的 acceptance 按原样仍在人手里，不由你也不由我给。

## 两件要说的

1. 契约写「从 `master` 的 `cf1a466` 起步」，这个仓库的分支叫 `main`。我没切分支，也没有建新的，就在 `main` 上做。
2. WP-2（README 那句「约 3.3 秒，随机型负载变化」）与缺陷 3 是同一类毛病——一个读者一计时就能反驳的数。本轮按「60 分钟起不开新包」没碰它，它仍是下一个包的第一个。
