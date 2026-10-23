kind:    report
from:    nomos
to:      root
spend:   none（没有新的计费调用、没有重跑生成；只花了本机自检与分析的时间，一分钱没花）
id:      mail/2026-10-23-answer-local-cap.md

# 本机臂上限 3110 已落地，旧 1452 行一条没重抽；"同协议"补了脚注

你那条答复的两件事都做完了，`summary.json` 的历史数字一个没动。

## 1. 本机上限：`scripts/measure_actions.py`

| 位置 | 改动 |
|---|---|
| `scripts/measure_actions.py:62-63` | `LONGEST_LEGITIMATE_OUTPUT = 311`；`MAX_NEW_TOKENS = 10 * LONGEST_LEGITIMATE_OUTPUT  # 最长 311 的十倍`。常量上方四行注明来历：已落盘 1452 条里 1422 条 `finish_reason: eos`、最长 311；另外 30 条在旧的 320 处被截断，只给出「≥ 320」的下界，量不出本来多长，所以不进这个最长值；模型自身的输出上限远高于 3110，未触及 |
| `scripts/measure_actions.py:167-182` | 新增 `cap_recorded(rows)`：分析描述的是**已经发生的那批生成**，上限从行本身读回——新行记 `max_new_tokens`，旧行由撞上限的行反推（撞上限时 `completion_tokens` 正好等于上限）。两版混在盘上就 `SystemExit`，不猜 |
| `scripts/measure_actions.py:271` | 新写入的回答行带 `"max_new_tokens": MAX_NEW_TOKENS`，下一批生成自己记着自己的上限 |
| `scripts/measure_actions.py:808`、`:857` | summary 的 `decoding.max_new_tokens` 改用读回值 `cap`，不再读常量 |

所以历史那 1452 条（30 条截断、自己停下来的最长 311）按原样进统计，`decoding.max_new_tokens` 仍是 320——它们是 320 下的生成，不因为常量今天变了而被写成 3110。重跑本地生成没有做，你要否的也正是这个。

## 2. "同协议"：两处文档补脚注

脚注一处定义、按节挂标记（每节第一个说「同协议」的地方带标记，一节里后面的继承，没有给每张表每一行都加）：

- `report/sft-measurement.md:27, 43, 150, 170, 229, 238, 246, 281, 315`，定义在 `:320`
- `docs/paper/draft.md:15, 24, 56, 91, 124, 175, 182`，定义在 `:205`

脚注文字（两处相同）：上限按 `economy.output_cap` 取「最长合法输出的十倍」（锚点 3170、本机 base/post 3110），历史各 arm 的上限是各自那一版的安全阀（320 / 600 / 400 / 2000），分析时从行本身读回、不读常量；锚点 2664 条里 42 条（1.6%）与本机 1452 条里 30 条同为「未测」，方向为低估。

`report/sft-measurement.md:317` 那条限制原本只写了锚点"上限此后按法取值"，补了一句本机同理（3110）与"那 30 行仍按 320 读回"，否则那一行会读成"本机还停在 320"。

**没动的两处**：`README.md:39` 与 `docs/model-card.md:78` 也说「同协议」，我没有加脚注——它们说的是匹配锚点那一批（320 对 320）的历史读数，字面仍然成立，分歧只在"以后的调用"这一侧，而那两句不谈以后。你要是想让前门也带一句，一个字我就补。

## 测试仍然通过（两条命令）

```
$ python3 scripts/measure_actions.py --check
base=1 adapter=1: X = None，区间 None → 通过
格式：动作比例 0.05→0.5，吻合率 0.5→0.5: Δ = 0.225，格式项 0.225，决策项 0.0 → 通过
决策：动作比例 0.5→0.5，吻合率 0.3→0.9: Δ = 0.30000000000000004，格式项 0.0，决策项 0.30000000000000004 → 通过
写出 evidence/measure/selftest.json：全部通过        # 退出码 0

$ python3 scripts/measure_actions.py --analyse > /tmp/an.out; echo $?
0
$ diff /tmp/sum_before.json evidence/measure/summary.json && echo 逐字节相同
逐字节相同
$ diff /tmp/ps_before.jsonl evidence/measure/per-situation.jsonl && echo 逐字节相同
逐字节相同
```

`/tmp/sum_before.json` 与 `/tmp/ps_before.jsonl` 是改码之前那一跑的拷贝，所以第二条命令是"改码后 `--analyse` 仍逐字节复现终版"，也正是 `measure_anchor.py` 用的那条回归检查。读回值本身也单独验过：

```
$ python3 -c "…cap_recorded([{'completion_tokens':320,'truncated':True},…])"
MAX_NEW_TOKENS 3110 = 10 x 311
cap_recorded(历史行)= 320
混批 -> 已落盘回答用了不止一个上限 [320, 3110]，分析要写清是哪一版
cap_recorded(新行记字段)= 3110
```

## 提交

- `42342ed` 本机臂输出上限 320 → 3110，旧 1452 行不重抽、按行读回 320（`scripts/measure_actions.py`）
- `658a9e6` 报告/论文「同协议」脚注 + `report/sft-measurement.md:317` 的本机那一句
- 这一封与你那条答复（`mail/2026-10-23-answer-local-cap.md` 原样入库）合在下一个提交里

没有 push。

## 没动的

口径二（第二把尺子）、§1 的声明收窄，以及你队列里其他等人的条目，一个字没写；`summary.json`、`per-situation.jsonl`、`answers.jsonl`、`pilot.json` 的历史数字全部原样。

## 残留风险

- 十个倍数是**下界推出来**的：311 只来自自己停下来的那些，真值只会更长，所以 3110 只会偏小不会偏大；哪天真撞到 3110，应当报 bug 而不是调数。
- `cap_recorded()` 对"一位数上限、零条截断"的旧批次读不出上限（行里没有可反推的值），会回落到常量。已落盘的这批有 30 条截断，读得出 320；下一批起每行自己记 `max_new_tokens`，这个洞就封上了。再往前（若出现 320 与 3110 混批且都无截断）没有办法从行本身分辨，那时分析该报错而不是猜——所以混批是 `SystemExit`。
- 旧行不带 `max_new_tokens` 字段，这是历史事实，我没有回填；要回填就得改写 1452 行已落盘的回答，那比缺一个字段更糟。
