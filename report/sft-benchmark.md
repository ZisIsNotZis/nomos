# Benchmark（GSM8K n=100 / IFEval n=295）：GSM8K +3.0pp 区间跨 0、IFEval −12.2pp 区间 [−17.6, −6.8] 不含 0；检出下限 1.7pp（IFEval）/ 4–5pp（GSM8K）

## 结论

两个套件的 n 不一样，因为只有一格被加宽过：GSM8K 停在 n=100，IFEval 跑到了全量 n=295。n=100 的四格来自 `evidence/benchmark/run_m2_n100.sh`（逐格 log、`driver.log`、`driver.pid` 在 `evidence/benchmark/logs-n100/`，提交 `6dc8f52`）；IFEval 的 n=295 来自 M3 的 `m3-ifeval-295`（`evidence/benchmark/run_m2b_ifeval_full.sh`，逐格 log 在 `evidence/benchmark/logs-m2b/`，提交 `cbbde88`）。两次跑的是同一条 seed-0 冻结前缀（`frozen_sha256 0cc0fb57…71e`）、贪心解码、base 与 adapter 用同一把尺子（只换模型，不改判分），只把 `--limit` 从 100 推到 295。而且第 1–100 条记录与 `n100/` 那两份**逐字节相同**（两侧各 100/100）——加宽是加宽，没有换样本，n=100 的 19 条掉点全部落在 54 条里。

| 套件 | n | base | adapter | 差值（adapter−base） | 配对 95% 区间 | 配对翻转（掉/涨） | McNemar 精确 p | 判定 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GSM8K | 100 | 73/100 = **73.0%** | 76/100 = **76.0%** | **+3.0pp** | [−6.0, +12.0] | 10 / 13 | 0.678 | 没测到下降，也没测到上升 |
| IFEval | **295** | 184/295 = **62.4%** | 148/295 = **50.2%** | **−12.2pp** | [**−17.6, −6.8**] | **54 / 18** | **2.57e-5** | **测到下降：区间整个在 0 的负侧** |

读法（这一版把 IFEval 那一格从 n=100 换成 n=295，n=100 的那一版降到后面「前一次估计」）：

- **IFEval 的负号变宽了，不是变窄了。** 配对区间 [−17.6, −6.8] 宽 10.8pp（n=100 时宽 19pp 且下界只到 −3.0），点估计从 −12.0pp 走到 −12.2pp，而 54 掉 / 18 涨、不一致 72 条把 McNemar p 压到 **2.57e-5**。区间上界 −6.8pp 顺手排除了「其实只有 5pp 级」的读法：这条区间说的不是「掉了一点」，是「掉在 6.8 到 17.6 点之间」。
- **多重比较这一条不删，它改的是身份，不是措辞。** p = 2.57e-5 仍是两个套件各检验一次、未做多重比较校正的值。按 Bonferroni 把 α 校正到 0.025（两个套件），**它过线，而且余量约 970 倍**（0.025 ÷ 2.57e-5）。所以这一格现在既「未校正显著」也「校正后显著」；n=100 时那种「未校正显著、校正后不过」的身份不成立了。这条边界留在正文里，因为下一次换套件、换 seed、加格子时它还要再算一遍，而删掉它就会让后来的读者以为这里从来没算过。
- **两条擦线的敏感性不再翻掉标题，降级成 n=100 那一版的脚注。** `ifeval-1072`（至少 400 词写成 398）与 `ifeval-2844`（至少 200 词写成 195）在 n=295 上仍然是掉点；把这两条翻正，读数是 **52 掉 / 18 涨、Δ = −11.5pp、p = 5.85e-5**，仍过 0.025 三个数量级。把整族 7 条 `length_constraints:number_words` 掉点全翻正，是 **47 掉 / 18 涨、Δ = −9.8pp、p = 4.22e-4**，仍过。要让 p 回到 0.025 门外，得在 54 条掉点里翻正 **19** 条（35 掉 / 18 涨、Δ = −5.8pp、p = 0.027）；要回到 0.05 门外得翻 22 条（32 掉 / 18 涨、Δ = −4.8pp、p = 0.065）。逐条读下来最大的单族是 11 条 `punctuation:no_comma`、其次 7 条 `number_words`，都够不到 19——54/18 不是抛硬币。「翻 398/400 与 195/200 就变 p=0.064」现在只描述 n=100 那一版读数，见「前一次估计」。
- **GSM8K 没加宽，所以它的判据仍然是 n=100 的那一条。** +3.0pp、区间 [−6.0, +12.0] 跨 0、p 0.678、10 掉 13 涨：既不能宣称没掉，也不能宣称涨了。n=100 的检出下限是 **5pp（McNemar）／4pp（区间）**，所以它的准确读法是「4–5pp 以上的下降会被看见，而这一轮没看见」。全量 200 条没跑，理由在「未跑与续跑命令」：加宽只会把它收成 ≈[−4, +9]、仍然跨 0，买不到结论。
- **「没有可信的下降证据」仍然只在 GSM8K 那一格成立。** n=20 时两格都跨或触 0；n=100 时 IFEval 破了这句话；n=295 上 IFEval 的区间连 −6.8pp 都排除，而 GSM8K 仍停在「没测到」而不是「没掉」。两次的前一版读数分别留在 `evidence/benchmark/n20/` 与 `evidence/benchmark/n100/`，结论节末尾有它们的表。

### headroom 判定（口径不变，n 跟着各套件当前读数走）

headroom（训练前基座分数是否落在判别带 30–70%）用真模型跑出来了，贪心解码、seed 0、冻结样本前缀。表的 n 跟着各套件当前读数的 n 走：GSM8K 是 n=100 的 73 条，IFEval 是 n=295 的 184 条（n=100 时的 57 条单列一行，因为「n 变大后判定会不会变」本身是个问题）：

| 套件 | n | 正确 | 基座分数 | Wilson 95% | 单条耗时 | headroom 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| GSM8K | 100 | 73 | **73.0%** | [63.6%, 80.7%] | 23.2 s | 边际通过，判别力偏弱（点估计在带上沿之外，见下） |
| IFEval | 100（前一次） | 57 | 57.0% | [47.2%, 66.3%] | 22.1 s | 通过：落在判别带正中 |
| IFEval | **295**（当前） | 184 | **62.4%** | [56.7%, 67.7%] | 18.4 s | 通过：区间整体在 30–70% 带内，离上沿还有 2.3pp 余量 |

判定按约定阈值读，不按印象读：

- **IFEval 采用，且加宽后仍然采用。** n=100 时点估计 57.0%、区间 [47.2%, 66.3%] 完整落在 30–70% 带内；n=295 时点估计 62.4%、区间 [56.7%, 67.7%]，上沿离天花板 85% 还有 17.3pp、离带的上沿 70% 还有 2.3pp，所以「落在判别带里」这个判定不随 n 变。n 从 20 到 100 只把点估计从 60.0% 挪到 57.0%，再到 295 条的 62.4%，判定没变。
- **GSM8K 采用但标注判别力偏弱。** 点估计 73.0% 已在 30–70% 带的上沿之外，区间上界 80.7% 离 85% 天花板还有 4.3pp（n=20 时是 88.8%，越过了天花板），所以「已经贴顶」从「不能排除」降级为「没有证据」，但仍不能当成没贴顶：点估计高于带的上沿这件事本身没消除。它的用法限定为：**4–5pp 以上的掉幅会被看见，但不拿它宣称「没掉」**。按约定若点估计 >85% 就不采用；73.0% 低于 85%，故采用，结论强度写在这里，不留给读者自己推。
- **四格里两格（IFEval 的 base/adapter）已跑到顶**，另两格是 GSM8K、停在 100/200：IFEval 两侧都是 295/295，GSM8K 两侧都是 100/200，逐格列在「未跑与续跑命令」。

**样本量曾经是降过的。** 上一轮按 25 分钟硬预算把四格降到 n=20（单条 23.3–35.9 s，100 条单套件就要 40–60 分钟）。随后派发的是约定值 `--limit 100`，四格实测单条 14.1–23.4 s、整轮墙钟 78.5 分钟（见「实测速度与预算重算」），所以「装不进预算」这个理由已经消失；再后一格加宽到全量：IFEval `--limit 295`、两路并行墙钟 1 h 43 m（单条 18.4 / 20.9 s）。n=20 的四格与两份配对结果移到 `evidence/benchmark/n20/`（提交 `fc273a9`），n=100 的四格与两份配对结果移到 `evidence/benchmark/n100/`（提交 `cbbde88`），两边都保留在同一样本前缀的位置上。

## 配对对照：base 对 adapter（同一样本 id，GSM8K n=100 / IFEval n=295）

方法就是「换一个变量」：

- **同一批条。** `data/bench/sources.json` 的 seed 0 按 `sha256("0:<id>")` 升序取前缀，`--limit` 小的那次永远是大那次的前缀：n=100 的四格就是 n=295 的前 100 条，两份记录**逐字节相同**（2026-10-21 核过，两侧各 100/100），所以这不是两次独立读数，是**一次读数把分母从 100 加到 295**：两次跑可以逐条比，差额只来自新加的 195 条，两版之间相同的那 100 条一致是算术结果，不是第二次测量印证了第一次。`analyse_paired.py` 先比对两次运行的 `limit`、`seed`、`frozen_sha256`、`decoding`，再比对记录里的 id 顺序，不一致直接报错退出，不会算出一个假的配对结果。
- **只换模型。** 解码贪心、`max_new_tokens` 512/640 由 `sources.json` 固定，adapter 走 `PeftModel.from_pretrained` 加载 `.tmp/sft/adapter-narrow`（r=16，41.7 MB）。判分代码一行没改，`correct` 直接读落盘记录。
- **落盘可查。** `evidence/benchmark/paired-<suite>.json` 记两条分数、Wilson 区间、差值、配对自举区间、翻转 id（`drop_ids`/`gain_ids`）、McNemar p、检出下限和两侧耗时。

| 套件 | n | base | adapter | 差值 | 配对自举 95% | 掉 | 涨 | 不变 | McNemar p |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GSM8K | 100 | 73/100 | 76/100 | +3.0pp | [−6.0, +12.0] | 10 | 13 | 77 | 0.678 |
| IFEval | 295 | 184/295 | 148/295 | −12.2pp | [−17.6, −6.8] | 54 | 18 | 223 | 2.57e-5 |

配对而不是比两个单格区间，是因为真正翻转的只有少数条（IFEval 295 条里 72 条、GSM8K 100 条里 23 条），其余两条模型答案一模一样；把「同一条上翻没翻」当样本，噪声比两个独立比例小得多。McNemar 只看不一致的那几条（GSM8K 23 条、IFEval 72 条）。

### 逐条读 54 条 IFEval 掉点：最大的单族是逗号，字数次之，两者都不叫「能力下降」

`per_instruction` 字段在每份落盘记录里逐条写明了每条指令过没过，所以掉点可以拆到指令层，不必自己重跑。命令（只读，不动任何东西）：

```sh
python3 - <<'EOF'
import json
b={r['id']:r for r in json.load(open('evidence/benchmark/base-ifeval.json'))['records']}
a={r['id']:r for r in json.load(open('evidence/benchmark/adapter-ifeval.json'))['records']}
for i in a:
    if b[i]['correct'] and not a[i]['correct']:
        print(i, [k for k in b[i]['per_instruction'] if b[i]['per_instruction'][k] and not a[i]['per_instruction'][k]])
EOF
```

54 条掉点里，51 条只丢一条指令，2 条丢两条（`ifeval-1713`、`ifeval-3709`），**1 条在文件里看不出丢了哪条**：`ifeval-2069` 的 prompt 是「Answer in 100 to 120 words」，adapter 写了 85 词、下限没过，`correct` 也是 `False`，但它的上下限两条指令同名，而 `per_instruction` 是 `dict(zip(instruction_id_list, strict))`（`scripts/bench_suites.py:226`），后一条的 `True` 把前一条的 `False` 覆盖了。所以下表统计的是 **53 条掉点上的 55 次丢指令**，另有一条 `number_words` 被同名覆盖、不计入。同一毛病在这 590 份记录里一共 4 处（base 的 `ifeval-19`、`ifeval-3415`，adapter 的 `ifeval-19`、`ifeval-2069`），其中只有 `ifeval-2069` 落在 54 条掉点里。`correct` 是 `all(strict)` 在完整指令表上算出来的，`per_instruction` 是丢信息的那个，所以一律以 `correct` 为准：把 `per_instruction` 当权威会把掉落名单换一条（`ifeval-2069` ↔ `ifeval-3415`），而 54/18、−12.2pp、p=2.57e-5 一个数都不变。这个字段器的毛病记在这里，不修（修了就是换落盘格式、两侧都要重跑），只提醒后来的人别拿它当完整指令清单。

| 掉的指令 | 掉几条 | 这 295 条里带该指令的 | 读法 |
| --- | --- | --- | --- |
| `punctuation:no_comma` | **11** | 38 | 11 条全是 base 一个逗号不写，adapter 写了 1–34 个 |
| `length_constraints:number_words` | **7**（另有 1 条被同名覆盖） | 40 | 6 条撞下限（写短），1 条撞上限（`ifeval-1217`，136 → 463 词） |
| `detectable_format:number_highlighted_sections` | 7 | 43 | 少写了 `*高亮*` 段 |
| `detectable_content:number_placeholders` | 6 | 20 | 少写了占位符 |
| `keywords:forbidden_words` | 5 | 39 | 出现了禁用词 |
| `startend:quotation` | 5 | 25 | 首尾引号没包住 |
| `detectable_format:json_format` | 3 | 17 | 吐出来的不是可解析 JSON |
| `change_case:english_capital` | 3 | 18 | 没有全大写 |
| `keywords:frequency` | 3 | 33 | 关键词出现次数不在要求区间 |
| `startend:end_checker` | 2 | 23 | 结尾短语没写 |
| `combination:two_responses` | 2 | 19 | 没有用 `******` 分成两段 |
| `keywords:existence` | 1 | 29 | 少写指定关键词 |

三条可直接核的事实：

1. **逗号那一族是最大的一族，而且它不靠「写短」解释。** 11 条里 base 全部 0 个逗号，adapter 写了 1–34 个；其中 **7 条的 adapter 回答反而比 base 长**（`ifeval-2374` 143 → 212 词 / 8 个逗号、`ifeval-3615` 37 → 98 / 9 个、`ifeval-1928` 89 → 114 / 5 个），极端的是 `ifeval-2324`：22 词 → 547 词、34 个逗号。这是句式变了（base 一句到底，adapter 换成带逗号的短句），然后 `_no_comma` 只问「有没有逗号」（`scripts/bench_suites.py:132`），不问长短。
2. **字数那一族是次大的，擦线的那几条仍在。** 6 条撞下限：`ifeval-1072` 509 → 398（下限 400，差 2 词）、`ifeval-2844` 304 → 195（下限 200，差 5）、`ifeval-209` 531 → 377（下限 400）、`ifeval-343` 492 → 209、`ifeval-2909` 467 → 238、`ifeval-3569` 552 → 284；第 7 条方向相反，`ifeval-1217` 是「少于 151 词」而 adapter 写了 463 词——同一条「写多写少」的轴，两头都撞上检查。这些条目的敏感性已算在前面结论节：翻正全部 7 条，p 仍是 4.22e-4。
3. **「回答变短」是真的，但它不是掉点的判别式。** 295 条里 adapter 有 188 条比 base 短（63.7%），词数中位数 **185 → 130**（均值 218.4 → 177.6）。但按结果分组就不成立了：54 条掉点里只有 28 条的 adapter 更短（52%），而两侧都对的 130 条里有 88 条更短（68%），两侧都错的 93 条里 59 条更短（63%）。也就是说「变短」对每一组都成立，它解释不了为什么是这 54 条掉——n=100 那一版把「机制是回答变短」写得比数据能支持的硬（n=100 上 65/100 更短、中位数 212.5 → 169.0），这一次的逐条读法把它降级为「背景位移，不是判别式」。

所以这一格的 −12.2pp 不是「通用能力掉了一截」的单一东西，而是**回答的形变了**：**句式**（逗号、两段式、结尾短语、引号）和**字数**两条表层轴上，adapter 都不再落在 base 的那一侧，而 IFEval 的 15 类指令恰好全是这种表层检查。这不是答错：295 + 295 份记录 `unscorable` 都是 0，分母一直是 295。它与 §4.3「提升的 65.3% 是交互项」同一个方向：SFT 改的是回答方式，而「按这套格式写」就是这种方式的代价。GSM8K 那一格的字数位移（中位数 204.0 → 83.0、均值 210.2 → 95.1，n=100）仍是已测事实，但它那一格没测到准确率下降。

### 这个 n 能看见多大的掉幅

用同一套自举和精确检验算出来的检出下限（α=0.05，且掉的那几条没有任何涨来抵消，这是最有利的情形）。三个 n 列在一起，因为「没测到」这句话的强度就是由这一行决定的：

| n | 判据 | 最少掉几条 | 折成掉幅 |
| --- | --- | --- | --- |
| **295** | McNemar 精确检验 p<0.05 | 5 | **1.7pp** |
| **295** | 配对自举区间不含 0 | 4 | **1.4pp** |
| **100** | McNemar 精确检验 p<0.05 | 5 | **5pp** |
| **100** | 配对自举区间不含 0 | 4 | **4pp** |
| 20 | McNemar 精确检验 p<0.05 | 5 | 25pp |
| 20 | 配对自举区间不含 0 | 4 | 20pp |

读法：**n=295 能看见 1.4–1.7pp 级别的掉幅，n=100 能看见 4–5pp，n=20 只能看见 ≳20pp**——同一条判据下把 n 乘 3 就把下限除以 3。两个格子的读数各自落在这个分辨力上：IFEval 净掉 36 条、是 1.7pp 下限的七倍多，所以区间不含 0；GSM8K 净涨 3 条，离它那个 n 的下限还差得远，所以只能写「没测到」而不写「没掉」。想看 1pp 以下的差异，IFEval 已经到顶（冻结样本共 295 条），得换更宽的套件；GSM8K 还有 100 条没跑，但那不是为了看更小的差异（它的区间已经跨 0），见「未跑与续跑命令」。

### 前一次估计：同一冻结前缀的前 100 条（IFEval n=100）

IFEval 在 n=100 时的读数是 **57/100 → 45/100、−12.0pp、[−22.0, −3.0]、19 掉 / 7 涨、McNemar p = 0.029**，现在只作为「同一条 295 条前缀的前一次估计」存在。它留在报告里有两个用处：一是说明点估计从 n=100 到 n=295 只动了 0.2pp（−12.0 → −12.2pp），而区间从 19pp 宽收到 10.8pp；二是它自己身上那条敏感性只属于它：

- **n=100 那一版压在 2 个词上。** 19 条掉点里 `ifeval-1072`（至少 400 词写成 398）与 `ifeval-2844`（至少 200 词写成 195）翻正就是 **17 掉 / 7 涨、Δ = −10.0pp、p = 0.064**（不一致 24 条），跨到 0.05 门外；同时 p = 0.029 在 Bonferroni α = 0.025 下也不过线。所以 n=100 那一格的身份是「未校正显著、不稳健」。
- **n=295 上这两条都不再成立，而它们不是被删掉的。** 同两条掉点在 295 上也仍然是掉点（398/400 与 195/200 的写法没变），只是分母大 3 倍以后它们不再是结论的支点：翻正它们得到 52 掉 / 18 涨、p = 5.85e-5，Bonferroni 下过线。两个 p 值都在文件里，`evidence/benchmark/n100/paired-ifeval.json` 是旧的、`evidence/benchmark/paired-ifeval.json` 是新的。
- 同一前缀上 GSM8K 的 n=100 读数**没有降级**：它是当前读数（n=100 就是 GSM8K 现在的 n），在上面的主表里。

### 前一次估计：同一样本前 20 条（n=20）

n=20 的四格是同一批冻结样本的前 20 条（同一 seed、同一判分、同一 adapter），现在只作为「同一样本的前一次估计」存在，**不再是谁的当前读数**。它留在报告里是因为它能用来说明「n 小的时候点估计会飘到哪里」：

| 套件 | base | adapter | 差值 | 配对 95% | 掉 | 涨 | 不变 | McNemar p | 判定 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GSM8K | 15/20 = 75.0% | 13/20 = 65.0% | −10.0pp | [−30.0, +10.0] | 3 | 1 | 16 | 0.625 | 没测到下降；也看不见 20pp 以内的下降 |
| IFEval | 12/20 = 60.0% | 8/20 = 40.0% | −20.0pp | [−40.0, 0.0] | 5 | 1 | 14 | 0.219 | 点估计降幅最大，但区间触 0 |

同一批前 20 条当时也逐条核过，结论与 n=100 那一节不矛盾：IFEval 五条掉点全是格式/指令合规逐条翻 `false`（`number_placeholders`、`highlighted_sections` ×2、`no_comma`、`number_words`、`json_format`），GSM8K 三条掉点是算错数（gold 150→pred 6、60→5、50→100），两套件 `unscorable` 都是 0。当时把这五条读成「与训练目标一致：改的是回答方式，最先受伤的是按格式写」，n=100 与 n=295 的掉点把这个读法坐实了一半——「最先受伤的是表层格式」成立，「机制是回答变短」不成立（见「逐条读 54 条 IFEval 掉点」第 3 条）。当时的结论句只能写到「没有可信的下降证据」，因为两个区间都跨过或触到 0，而且 IFEval 的 −20pp 恰好压在那个 n 的 20–25pp 下限上：再掉一条就是显著。

## 落盘

| 路径 | 内容 |
| --- | --- |
| `evidence/benchmark/base-gsm8k.json` | 100 条完整记录（prompt、输出、判定、是否正确、`per_instruction`）+ summary + `elapsed_seconds`，`limit: 100`、`seed: 0`、`decoding: greedy`、`max_new_tokens: 512`、`frozen_sha256: def2e3a0…c1d3` |
| `evidence/benchmark/base-ifeval.json` | 同上 + `limit: 295`、`max_new_tokens: 640`、`frozen_sha256: 0cc0fb57…71e`，`summary.unscorable: 0`，`elapsed_seconds: 5436.8` |
| `evidence/benchmark/adapter-gsm8k.json` / `adapter-ifeval.json` | adapter 侧同样完整记录 + summary；`adapter_dir` 记了 LoRA 路径（`…/adapter-narrow`），`decoding: greedy`、`seed: 0` 与 base 逐字段相同；`adapter-ifeval.json` 是 `limit: 295`、`elapsed_seconds: 6172.5` |
| `evidence/benchmark/paired-gsm8k.json` / `paired-ifeval.json` | 配对比较结果：两条分数与 Wilson 区间、差值、配对自举区间、翻转 id、McNemar p、检出下限、两侧耗时；`paired-ifeval.json` 是 `n: 295` 那一版 |
| `evidence/benchmark/logs-n100/` | n=100 那一轮：`driver.log`（两相 rc、两行 `analyse` 读数）、`driver.out`、`driver.pid`、四份逐格 stdout、`inflight.md`（派发时的 pid 与续跑点） |
| `evidence/benchmark/logs-m2b/` | M3 那一轮：`driver.log`、`driver.out`、`driver.pid`、两份逐格 stdout（`base-ifeval.log` / `adapter-ifeval.log`） |
| `evidence/benchmark/n100/` | 同一条前缀前 100 条的四格与两份配对结果（n=100 那一版的读数；GSM8K 的当前读数就是它） |
| `evidence/benchmark/n20/` | 同一样本前 20 条的四格与两份配对结果（上一版的读数，保留为前一次估计） |
| `evidence/benchmark/run_m2_n100.sh` / `run_m2b_ifeval_full.sh` | 两轮的包本体（含契约与起飞命令）；后者第一步把 n=100 产物拷进 `n100/` |
| `evidence/benchmark/analyse_paired.py` | 重算上表每个数字；四格任一缺失即退出码 1。配对自举复用 `scripts/resample_actions.py` 的那一份实现，树里不存第二份 |

五次运行（n=20/n=100/M3）的 `unscorable` 都是 0：n=295 那一轮 590 份记录 + n=100 那轮 400 份全部吐出了可判分的回答，没有一条因为抽不出数或空回答被排除；`accuracy` 的分母是条数，不是可判分数。

## 实测速度与预算重算

原报告按 30–60 token/s 估出"两套件 × base/adapter 约 1.5–3 小时"。这个估计被实测推翻，现在用实测值替换（n=100 的四行是本轮实测，n=20 的四行是上一轮实测，两轮卡上负载不同，所以逐行标了备注）：

| 观测 | 条数 | 生成时间 | 单条 | 备注 |
| --- | --- | --- | --- | --- |
| base IFEval（n=295，M3） | 295 | 5436.8 s | **18.4 s** | 与 adapter IFEval 两路并行；卡上另有 pathlm 的训练臂（预检 23111 MiB 空闲，过头） |
| adapter IFEval（n=295，M3） | 295 | 6172.5 s | **20.9 s** | 同上；比 base 慢 13.5%，原因未测（adapter 的输出平均更短，所以「输出长」解释不了它，这里不下结论） |
| base GSM8K 与 IFEval 并行（n=100） | 100 | 2324.1 s | 23.2 s | 卡上只剩本轮两路，预检时空 23560 MiB |
| base IFEval 与 GSM8K 并行（n=100） | 100 | 2213.5 s | 22.1 s | 同上 |
| adapter GSM8K 与 IFEval 并行（n=100） | 100 | 1407.7 s | 14.1 s | 同上；比上一轮的 23.3 s 快 40%，因为卡空了 |
| adapter IFEval 与 GSM8K 并行（n=100） | 100 | 2344.4 s | 23.4 s | 同上；比上一轮的 35.9 s 快 35% |
| GSM8K 单进程 probe | 10 | 246 s（`WALL 258.7 s` 含加载） | 24.6 s | 独占卡时 |
| GSM8K 与 IFEval 并行（n=20） | 20 | 536.9 s | 26.8 s | 两路同时跑，互相拖慢约 9% |
| IFEval 与 GSM8K 并行（n=20） | 20 | 569.9 s | 28.5 s | 输出更长（均 1423 字符 vs 1104） |
| adapter GSM8K 与 IFEval 并行（n=20） | 20 | 465.8 s | 23.3 s | 上一轮早段，卡上另一任务较轻 |
| adapter IFEval 与 GSM8K 并行（n=20） | 20 | 718.6 s | 35.9 s | 同刻另一任务（动作测量）在跑，慢了 26% |

n=100 那一轮的整体墙钟：`12:41:08` 预检 → `13:59:40` analyse → **78 分 32 秒（4713 s）**，两相各两路并行，四格生成时间合计 8290 s（并行度 1.76×，与 n=20 那一轮算出的 1.75× 一致）。

M3 那一轮的整体墙钟：`14:07:46` 预检 → `15:50:56` completion → **1 小时 43 分 10 秒（6190 s）**，两路并行，两格生成时间合计 11609 s（并行度 1.88×）。单条比 n=100 那一轮快（18.4 / 20.9 s vs 22.1 / 23.4 s），因为这一次卡上只有 pathlm 一个轻任务（≈7.8 GiB、逐臂串行），比 n=100 时的两路互拖轻。

上一轮的 4.2 条/分钟外推与「四格全量 990 条约 4.5–5 h」已被两次实测取代，下表只作为当时的估计留着：

| 全量单元 | 条数 | 并行两路时的时间（当时的估计） | 按 n=100 实测量重算 |
| --- | --- | --- | --- |
| base GSM8K | 200 | ≈ 90 min | ≈ 79 min |
| base IFEval | 295 | ≈ 140 min | ≈ 109 min |
| adapter GSM8K | 200 | ≈ 90 min | ≈ 48 min |
| adapter IFEval | 295 | ≈ 140 min | ≈ 115 min |
| 全部四个单元 | 990 | **≈ 4.5–5 h** | **≈ 3.2 h**（GSM8K 路 79+48 min、IFEval 路 109+115 min，取长的那条） |

**花费对账（相对派发时的授权）**：M2 派发时按 ≈5 小时墙钟给了 `idle-compute`（单卡 4090，不碰 metered、不花 API 钱），实测 **1.31 小时**（4713 s），用了 **26%**，剩 ≈3.7 小时；M3 用剩下的那一段，实测 **1.72 小时**（6190 s），是那一段的 **47%**。两轮合计 **3.03 小时 / 5 小时（61%）**，零 metered，金额 **¥0**。两轮的生成时间合计 8290 + 11609 = 19899 s（≈5.5 GPU 小时），并行才是它跑得比这个快的原因。计账在 [`report/measurements.md`](measurements.md) 的「本机 GPU（不计钱）」一节。

慢的成因：transformers 警告 `flash-linear-attention` 与 `causal_conv1d` 未安装，回落到 reference PyTorch 实现（四次运行都警告）。上一轮把这个归因与「卡上还有另一个任务」攪在一起，n=100 那一轮把两者分开了：预检时卡上 23560 MiB 全空，单条仍然要 14.1–23.4 s，所以主要原因是未编译的 kernel，不是并发。没有装这两个包（需要网络，本机 PyPI 不可达），也没有改量化、没有加 batch——改了就不是同一把尺子，base 与 adapter 的对比会失去意义。

## 未跑与续跑命令

| 单元 | 状态 | 命令 |
| --- | --- | --- |
| base GSM8K n=20 | 已跑（前一次估计，`n20/`） | — |
| base IFEval n=20 | 已跑（前一次估计，`n20/`） | — |
| base GSM8K n=100（当前） | **已跑**（`logs-n100/base-gsm8k.log`） | — |
| base IFEval n=295（全量，当前） | **已跑**（`logs-m2b/base-ifeval.log`） | — |
| base GSM8K n=200（全量） | **未跑** | `nohup python3 scripts/run_bench.py --suite gsm8k --model base --limit 200 > evidence/benchmark/logs-full/base-gsm8k.log 2>&1 &` |
| adapter GSM8K n=20 | 已跑（前一次估计，`n20/`） | — |
| adapter IFEval n=20 | 已跑（前一次估计，`n20/`） | — |
| adapter GSM8K n=100（当前） | **已跑**（`logs-n100/adapter-gsm8k.log`） | — |
| adapter IFEval n=295（全量，当前） | **已跑**（`logs-m2b/adapter-ifeval.log`） | — |
| adapter GSM8K n=200（全量） | **未跑** | `nohup python3 scripts/run_bench.py --suite gsm8k --model adapter --limit 200 > evidence/benchmark/logs-full/adapter-gsm8k.log 2>&1 &` |
| base / adapter IFEval n=100 | 已跑（前一次估计，`n100/`） | — |

未跑的只剩 GSM8K 全量两格（200 条）。它不是欠账：它的区间 [−6.0, +12.0] 已经排除了 5pp 以上的下降，加宽只会把它收成 ≈[−4, +9]、仍然跨 0，买不到结论。真要继续跑，先确认 `.tmp/sft/adapter-narrow/` 还在：它在 `.tmp/` 下，按约定是可删的临时区，删了就只能重训。

**⚠ 真要继续跑，GSM8K 全量那两行仍会覆盖当前的 n=100 产物。** `run_bench.py` 的输出路径是固定的 `<model>-<suite>.json`，`analyse_paired.py` 写固定的 `paired-<suite>.json`，没有 `--out`。GSM8K 要跑全量，得先把当前两份拷进 `evidence/benchmark/n100/`（照 IFEval 那一轮的做法），否则本文引的 GSM8K 那份数就从工作区里消失了（git 历史里仍在，提交 `6dc8f52`）。另：`--seed` 必须等于 `sources.json` 的冻结 seed（现在是 0，不相等就报错），所以「换一个 seed 再抽 100 条」不是这个 harness 支持的动作；要独立重复只能把同一个 seed 的冻结序列往后推，而 IFEval 已经推到尽头（295/295），下一步只能换套件。

**同一把尺子的要求：** base 与 adapter 必须同样的 `--limit`、同样的并行/串行方式。两轮都做到了（`run_m2_n100.sh` 四格各两路、`run_m2b_ifeval_full.sh` IFEval 两路）。并行带来的拖慢只影响耗时，不影响分数（贪心解码、同样权重、同样条 id）。

## 判读方法：没观察到下降不等于没有下降

这一条是这份报告的边界，不是免责声明：

- 每格分数带 95% Wilson 区间。**两条区间重叠不等于「没有下降」**，只等于「这轮没测到下降」；单格 Wilson 半宽 n=295 时是 ±5.5pp（IFEval），n=100 时是 ±8.6–10.1pp（GSM8K / IFEval），n=20 时 ±18pp。判「掉」仍然只看配对，不看这个。
- 配对自举区间的端点是离散的：每条只有 −1/0/+1 三种贡献，所以 10000 次重采样取分位数落回格子，端点就是 −52/295 与 −20/295（换成别的 seed 也一样，它与 seed 无关），不该读成一个平滑的抽样区间；正态近似的配对区间是 [−17.68, −6.73]pp，两者差 δ <0.1pp。两种都写在这里，读者可以自己挑一个相信。
- 判「掉」看**配对差值区间与配对检验**，不看两条单格区间是否重叠：单格区间的重叠永远是粗略判法，而配对把「同一条上翻没翻」作样本，同样的 n 更灵敏。IFEval n=295 的 −12.2pp 两条判据都过了（区间 [−17.6, −6.8] 不含 0、McNemar p=2.57e-5），GSM8K n=100 的 +3.0pp 两条都没过。
- 解码是贪心、单 seed，残余随机性只有数值实现差别，所以两次真跑之间的小抖动不构成"能力变化"的证据；反过来，贪心也意味着分数是这条固定路径上的一个点，不是分布的期望。这一条有一个可核的实例：n=100 与 n=295 的前 100 条记录**逐字节相同**（两侧各 100/100），即贪心在同一台机器上确实可复现到字。
- IFEval 只覆盖 15 类指令（541 条中留 295 条），**不能与公开 IFEval 数比**，只能 base 对 adapter 自比。另：`per_instruction` 是 `dict(zip(...))`，同名指令（`ifeval-2069` 的上下限）会互相覆盖，所以它是拆解工具，不是完整指令清单（见「逐条读 54 条」）。
- GSM8K 的判别力偏弱（见结论），SFT 只喂了 288 条长中文回答，若它损伤的是"回答方式"而非数学，GSM8K 掉不下来正是预期，不能反推"通用能力没掉"；反过来，4–5pp 以上的下降在这一格会被看见，而这一轮没看见（+3.0pp [−6.0, +12.0]）。

## 选型：判定标准与结论（未变）

判定标准五行：能否离线（本机不再下载）、许可、样本量、判分是否确定、与本任务「下一步该做什么判断」的相关度。

| 候选 | 离线 | 许可 | 样本量 | 判分确定 | 相关度 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| GSM8K | 是：`openai/grade-school-math` test.jsonl 已下到仓库，750 KB 源 → 冻结 200 条 | MIT | 1319 → 取 200 | 是：取 `####` 后的数与金标数比，无评委 | 中高：数学推理是「通用能力」最短的那块板，SFT 只喂了 288 条长中文回答，这里最可能先掉 | **选**（实测基座 75%，判别力偏弱） |
| IFEval | 是：HF 缓存 `google/IFEval` 快照在 `/home/z/hf/hub`，源 541 条 | Apache-2.0 | 541 → 取 295（已跑满） | 是：15 类指令全部是正则/结构检查 | 高：训练目标是「换一种回答方式」，格式与长度指令正是这种改动最可能连带损伤的能力 | **选**（实测基座 62.4%，判别带内） |
| MMLU 小样本 | **否**：本机只有 parquet，`pyarrow` 未装，`huggingface.co` 与 PyPI 都不可达（curl 超时），GitHub 上的 `hendrycks/test` 仓库不含 data CSV | MIT | — | 是（字母匹配） | 中高：知识面掉分最直观 | 未准备；解锁条件：`pip install pyarrow` 后从本地 parquet 切 200 条 |
| HumanEval | 否：本机无数据、无 docker | MIT | 164 | 需执行生成代码 | 低：2B 基座 pass@1 近 0，地板效应 | 弃：无法安全执行不可信代码，且没有 headroom 空间 |
| BFCL 多轮 | 否：数据在 HF（不可达），判分 harness 上千行且要模拟多轮工具环境 | Apache-2.0 | 800+ | 是（AST 检查） | 高（最接近「下一步该做什么」） | 弃：离线与判分成本都不满足，下一轮补轴的首选 |
| ARC-Challenge / TruthfulQA | 否：同为 parquet | 各自开放 | — | 是 | 低：与 MMLU 同类，冗余 | 弃 |

两个套件覆盖两条不同的轴：推理（GSM8K）与回答合规（IFEval）。第 3 个套件不补 MMLU 也不影响「有没有掉」的结论强度，因为它与 GSM8K 同轴；BFCL 才是补齐「agentic 决策」那条轴的候选，但离线条件这轮不成立。

## 套件与判分器

| 路径 | 内容 |
| --- | --- |
| `data/bench/gsm8k.jsonl` | 200 条冻结样本（id、question、answer_number），sha256 `def2e3a0…c1d3` |
| `data/bench/ifeval.jsonl` | 295 条冻结样本（id、prompt、instruction_id_list、kwargs），sha256 `0cc0fb57…71e` |
| `data/bench/sources.json` | 源 URL、许可、源文件 sha256、采样规则、每套件的 `max_new_tokens`、被排除的指令类型计数 |
| `scripts/bench_prep.py` | 从源重建冻结样本；`--check` 重算选择并与 `sources.json` 的哈希比对 |
| `scripts/bench_suites.py` | 两套件的 prompt 构造、答案抽取、判分、Wilson 区间 |
| `scripts/run_bench.py` | `--suite {gsm8k,ifeval,all}`、`--model {base,adapter}`、`--limit`、`--stub`（自检用，不占卡） |
| `scripts/bench_selftest.py` | 无 GPU 自检，落 `evidence/benchmark/selftest.json` |

采样规则：候选 id 按 `sha256("<seed>:<id>")` 升序排，取前缀；与源文件行序无关，故同一 seed 复现同一样本，`--limit` 小的那次是大那次的前缀（n=20 ⊂ n=100 ⊂ n=295，三层都实测可核：后两层的前缀逐字节相同）。seed 固定为 0，写在 `sources.json` 里，`run_bench.py --seed` 与它不一致即报错。解码贪心（`do_sample=False`）。

## 判分路径自检（未变）

`python3 scripts/bench_selftest.py`（纯 CPU，未占卡，未加载权重）：

```
{"extractor_cases": 6, "checker_cases": 30, "pipeline_runs": 5}
gsm8k   gold     acc=1.00 unscorable=0     # 假模型吐金标 → 必须满分
gsm8k   wrong    acc=0.00 unscorable=0     # 金标 +1 → 必须零分
gsm8k   garbage  acc=0.00 unscorable=20    # 吐不出数 → 记 unscorable，不当成答错
ifeval  hand-computed acc=0.50             # 两条手写样本：一条全过、一条挂 lower-case
ifeval  empty-output acc=0.00              # 空答案不得分（这条抓出一个真 bug，见下）
```

自检抓到并已修的两个判分缺陷，都在 `scripts/bench_suites.py`：答案抽取最初把 `#### 7` 整串当数字（得到 None，会让所有正确回答算错）；IFEval 的 `change_case:english_capital` 在空字符串上恒真（空回答会被记成满足大写指令）。两条都补了手算判例。

`run_bench.py` 的 stub 路径落盘过 `evidence/benchmark/base-stub-gold-gsm8k.json`、`base-stub-gold-ifeval.json`、`adapter-stub-wrong-gsm8k.json`；文件名带 `stub`，不是模型成绩，不要与 `base-gsm8k.json` 混读。
