kind:    report
from:    nomos
to:      root
spend:   none（没有新的计费调用；一分钱没花）
id:      mail-inbox 2026-10-23-nomos-output-cap

# `economy.output_cap` 已落到本项目的五处调用上：320 → 3170，断言改成「没有一条撞上限」

你 2026-10-23 那条答复的四件事都做完了，锚点一个字没重跑，那 42 行还是最终数据。

## 改了什么

上限现在写成「某个已命名长度的十倍」，每个数旁边都有样本和推导：

| 脚本 | 旧上限 | 新上限 | 最长合法输出取自哪批已落盘调用 |
|---|---|---|---|
| `scripts/measure_anchor.py` | 320 | **3170** | 2664 条里自己停下来的 2622 条，最长 317（原批 317、追加批 316）；被 320 砍掉的 42 条只给出「≥ 320」的下界，量不出本来多长，所以不进这个最长值 |
| `scripts/resample_actions.py` | 600 | **5340** | 共用这个常量的四批里最长 534（densify 1470 条）；该常量被 `densify.py`、`grow_pairs.py` 导入，改一处其余随之 |
| `scripts/annotate_coverage.py`（选规则，`--max-tags`） | 400 | **1490** | 353 次已落盘调用里最长 149（`evidence/coverage-cap8`） |
| `scripts/annotate_coverage.py`（不收窄） | 2000 | **14690** | 197 次里自己停下来的最长 1469（`evidence/coverage-uncapped`；旧的 2000 在那批砍掉 23 条） |

四件事逐条对照你的清单：

1. `MAX_TOKENS = 320` 改成 `MAX_TOKENS = 10 * LONGEST_LEGITIMATE_OUTPUT`，常量旁注明「最长 317 的十倍」与样本来源；模型自身上限远高于 3170，未触及。
2. 另四个脚本一并改。你消息里说它们「导入同一个常量」——**细节与实情不同**：`densify.py` 与 `grow_pairs.py` 确实导入 `resample_actions.MAX_TOKENS`（600），但 `annotate_coverage.py` 有自己的 400/2000，`grow_pairs.py` 另有一处导入 `annotate_coverage.MAX_TOKENS`。所以不是一个数改一处，而是「一个数 + 一套导入链 + 两类不同长度的任务」；我按每个调用自己的任务分别量了最长合法输出，`densify.py` 没有数字可改，只在文件头写清它跟着 `ra.MAX_TOKENS` 走。
3. 断言改成「没有任何一条 completion 撞到上限」：`pilot.json` 的 `no_completion_hits_cap = max(completions) < MAX_TOKENS`（旧键 `max_tokens_respected` 是 `<=`，正是「撞上限就算正常」的那种检查）。
4. 「未测」落到三处该落的地方：`report/sft-measurement.md`（解码证据那一段 + 截断清单 + 局限第 9 条前的原文）、`docs/paper/draft.md` §8 第 8 条（原来写「锚点 11 条」，现在写「2664 条里的 42 条，1.6%，方向低估，未测」）、`docs/method/design.md` §5 噪声新增一条。三处都说清：那 42 行按原样进统计、不当完整回答讲、不重画。

## 一条命令看得出「已落盘的数据没被我动过」

`--analyse` 是纯本地、不调 API 的路径。改码后重跑同一批，`summary.json` 与 `per-situation.jsonl` 逐字节相同：

```
$ python3 scripts/measure_anchor.py --analyse
$ git diff --stat evidence/                      # 只有 generate.log 追加了这次的 cmd 与 analyse 两行
$ diff /tmp/sum3.json evidence/measure/anchor-matched/summary.json && echo 逐字节相同
逐字节相同
```

能保住这一点，是因为分析和元数据不再读常量，而是**从已落盘的行里读回那一批实际发出去的上限**（`cap_recorded()`）。否则改常量会顺手把 2026-10-21 那 2664 次调用描述成 3170 下跑的，`summary.json` 也不再可复现。

导入链的实读值（一条命令，无 API 调用）：

```
$ python3 -c "
import importlib.util,sys,pathlib
def L(n,p):
    s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);sys.modules[n]=m;s.loader.exec_module(m);return m
b=pathlib.Path('scripts')
print('measure_anchor',L('a',b/'measure_anchor.py').MAX_TOKENS)
print('resample_actions',L('r',b/'resample_actions.py').MAX_TOKENS)
print('annotate_coverage',L('c',b/'annotate_coverage.py').MAX_TOKENS, L('c2',b/'annotate_coverage.py').MAX_TOKENS_FULL)
print('densify->ra',L('d',b/'densify.py').ra.MAX_TOKENS)
g=L('g',b/'grow_pairs.py');print('grow->ra',g.ra.MAX_TOKENS,'grow->ac',g.ac.MAX_TOKENS)"
measure_anchor 3170
resample_actions 5340
annotate_coverage 1490 14690
densify->ra 5340
grow->ra 5340 grow->ac 1490
```

## 要你决定的两件事

1. **本地 `max_new_tokens = 320` 改不改**（`scripts/measure_actions.py:58`）。那不是计费调用，新法的字面没盖到它，所以我没有动它——动了就得重跑本地 1452 条生成才吃得到新上限，而且 base/post 那 1452 条就成了「320 下抽的」。已落盘的事实：本地 1452 条里 30 条被 320 截断，自己停下来的最长 311，十倍是 3110。我的建议是改（本地不花钱、只花机器时间），但那 1452 条要不要重抽是笔时间和可比性的账，不是我的。一个字就行：改 / 不改。
2. **「同协议」这句话在 max_tokens 这一项上不再逐字成立**。锚点从今天起是 3170，base/post 是 320；旧锚点数据本身仍是 320 下抽的，所以读数不受影响，但再抽的锚点样本不会被砍而 base/post 仍可能被砍。我按「在脚本 docstring 里写明这是有意不一致」处理了，没有改报告里「同协议」的措辞。要不要在报告那几句旁边加一句脚注，还是把 base/post 也重抽到 3110（那要再花一次本地生成的时间）——前者我随时能写，后者要你点头。

## 没动的

口径二（第二把尺子）与 §1 的声明收窄：你队列里那两条我没有替你猜，一个字没写。

## 残留风险

- `no_completion_hits_cap` 只在新抽的 pilot 上跑得到；已落盘的 2664 条里 42 条撞过旧的 320，那个事实是数据的一部分，不会因为断言改了而消失。
- `evidence/measure/anchor-matched/pilot.json` 仍是 320 下的历史记录（键名 `max_tokens_respected`），我没有改写它——它是那次运行的证据，不是今天的检查。
- 每个新上限的数都来自「自己停下来的最长回答」，也就是**下界**：真值只会更长，所以十倍值只会偏小不会偏大；这也意味着上限仍是可被更长的回答撞到的，撞到时应当报 bug 而不是调数。
