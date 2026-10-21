kind:    report
from:    nomos
to:      root
spend:   idle-compute
id:      M4 的 completion —— 参考实现的尺子重算同一批 590 份输出，仍是 −12.2pp

**M4 落地：−12.2pp 不是我们自己那把尺子写出来的。** Google 官方 `instruction_following_eval`（commit `e6890f85`，六个文件逐字节）跑在同一批 590 份落盘输出上（不重跑模型）：strict **196/295 → 160/295、−12.2pp、[−17.6, −6.8]、55 掉 / 19 涨、McNemar p 3.38e-5**；lax **−11.2pp [−16.9, −5.4]、p 2.17e-4**。点估计与配对区间跟本仓库那把尺子的对照行（184 → 148、−12.2pp、[−17.6, −6.8]、54/18、p 2.57e-5）一致到端点，换掉的只是 74 条不一致里哪几条。你上一封信要的那一步做完了；**区间不含 0，所以没有触发「跨 0 就停在这里」那条闸**，也没有任何主张被静默改写。

**看这个状态的一条命令**（纯 CPU、一次 6.5–11 s（含 `uv` 启动开销）、不碰 GPU、不写任何网络）：

```
/home/z/.local/bin/uv run --no-project --with nltk --with langdetect --with immutabledict \
  --with absl-py python3 evidence/benchmark/official/grade_official.py
```

它打印三行——官方 strict / 官方 lax / 我们的尺子——每行是 base、adapter、Δ、配对区间、掉/涨、p，再一行 836 个指令槽里 56 槽判得不一样。产物 `evidence/benchmark/official/official-ifeval.json`；我在落盘后的位置连跑三次，逐字节相同（`01d94585…`），六个 vendor 文件 sha256 与 `VENDOR.md` 逐个相符。

**三件你判断时用得上的事，按我的排序：**

1. **参考实现自己不可复现，我钉住了才敢冻结这一行。** 官方 `change_case` 检查器内部调 `langdetect`，而 `DetectorFactory.seed` 默认 `None`、从全局 `random` 抽：同一份输出在两个进程里给出 160 或 159（±1 条 = 0.34pp）。`grade_official.py` 钉 `DetectorFactory.seed = 0` 与 `random.seed(0)`（依赖自己的文档化开关，不改任何检查器逻辑）。任何人引官方 grader 的数都会踩这个；次数不大，但足以让「160 还是 159」这类句子不可复现。
2. **两把尺子的分歧方向与你信里的预期相反。** 836 槽里 56 槽不一致：45 槽我们更严、11 槽更松，整题层两侧各 22 条。最大一族是 `number_paragraphs` **30/40** 槽（我们数空行，官方按指令里点名的 `***` 分），其后 `json_format` 7（官方先剥 ```` ``` ```` 栅栏）、`forbidden_words` 6（子串 vs `\b` 词边界）、`change_case` 7（官方多一道 `langdetect`，这一族我们对）。11 条逐条人读：官方对 7、我们对 3、1 条口径问题。**你点名的两个咬点里，`_words` 只咬了 `ifeval-1072` 一条（398 对 415 词），`_no_comma` 一条也没咬到**——11 条逗号掉点在官方尺子上一条不少、全部仍是整题掉点。
3. **冻结之后还能攻击的只剩口径选择，不是数据缺失。** ① 三行都是同一条 seed-0 贪心路径上的一个点；② 54 条掉点里 11 条 `no_comma` + 7 条 `number_words` 都是格式类指令，拆成「格式/内容」两类后结论只能落在前者；③ 官方 strict 上基座 66.4% 的 Wilson 上沿 71.6%，比判别带 70% 的上沿高 1.6pp（我们那把是 62.4%、上沿 67.7%，在带内）——判别带判定不随尺子翻转，但余量变薄。三条都写进 `report/sft-benchmark.md`「参考实现的尺子」与论文 §4.7。

**要你答的（decision）：接受或否掉 M4** —— 即「−12.2pp + 区间不含 0 + 换尺子不换结论」这一版是不是冻稿能用的那一版。这个我按规矩不自判，独立 review 已派出去，结果附在下面。

**另一件小事仍在等你**（Q7，已记在文档里，不阻塞任何事）：你回信里「33 of 40 个 `number_words` 题仍通过」我在落盘记录上复算不上——实测 40 个里 adapter 19 个（base 24 个）仍在这一条上通过，adapter 整题全对 12 个、base 18 个，没有任何读法给出 33。给我 33 的来源（另一把尺子、另一批题、还是笔误），或者授权按实测改写那句话。

**顺带说明本轮停在哪里**：M4 本身就是这一轮的终止条件（里程碑到达），所以在 120 分钟预算用完之前就停在这里。`work/` 随 WP-5 毕业而不存在（产物进 `evidence/benchmark/official/`）。WP-2（README 那句「约 3.3 秒，随机型负载变化」）仍未做，按 60 分钟规则我没有开这个新包——它是下一步的第一个包，一小时以内能完。WP-3 按约定等下一次碰到那个 lock 的改动。Q1/Q2/Q3 仍在人手里，不阻塞任何事。本轮零 metered、零 GPU、¥0，所有提交都在本机、没有推。

REVIEW: **未返回。** 独立 review 已按九条契约派出（read-only、fresh context，scope 是 `evidence/benchmark/official/` 的产物与上面这些主张），budget 20 分钟已超、我已催一次要它就地交卷，本报告送出时它仍在跑（run id `d62d9490-53c2-4736-ac27-7e5b893ca26d`）。所以「M4 通过独立复核」这句话**我现在不说**：说得出的是我自己能出示的东西——产物在 `evidence/benchmark/official/official-ifeval.json`、命令能重跑、三次运行逐字节相同、六个 vendor 文件 sha256 相符、文档里每个数都能从产物或落盘记录重算。它的裁决回来以后落进 `AGENTS.md`（开着的 Q8）；若判 FAIL，被点到的句子按它的 reproduction 重开，不辩。
