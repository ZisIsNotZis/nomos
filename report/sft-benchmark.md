# Benchmark（n=100）：GSM8K +3.0pp 区间跨 0、IFEval −12.0pp 区间不含 0；检出下限 4–5pp

## 结论

四个格子都跑完了：每套件 n=100、同一条冻结样本前缀、seed 0、贪心解码，base 与 adapter 用同一把尺子（只换模型，不改判分）。跑的是 `evidence/benchmark/run_m2_n100.sh`，逐格 log、`driver.log`、`driver.pid` 在 `evidence/benchmark/logs-n100/`；`analyse rc=0` 之后 driver 退出，四份 JSON 与两份配对结果由它落盘（提交 `6dc8f52`）。

| 套件 | base | adapter | 差值（adapter−base） | 配对 95% 区间 | 配对翻转（掉/涨） | McNemar 精确 p | 判定 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GSM8K | 73/100 = **73.0%** | 76/100 = **76.0%** | **+3.0pp** | [−6.0, +12.0] | 10 / 13 | 0.678 | 没测到下降，也没测到上升 |
| IFEval | 57/100 = **57.0%** | 45/100 = **45.0%** | **−12.0pp** | [**−22.0, −3.0**] | 19 / 7 | **0.029** | **测到下降：区间整个在 0 的负侧** |

读法（这一版替换掉 n=20 时那句「没有可信的下降证据」）：

- **IFEval 的下降不再只是点估计。** 配对区间 [−22.0, −3.0] 不含 0，McNemar p = 0.029（19 掉 / 7 涨），所以可以写「测到 −12pp」，不能再写「没测到」。同一句话必须带上它的边界：**一次抽样、一个 seed、贪心解码，两个套件各测一次而没有做多重比较校正**——两格里只有一格显著，把 α 校正到 0.025（Bonferroni，两个套件）时 p = 0.029 就不过线——所以这一格是「未校正下显著」，不是「稳健显著」。
- **这个负号有多薄：它压在 2 个词上。** 19 条掉点里有两条是字数下限擦线——`ifeval-1072`「至少 400 词」写成 398 词、`ifeval-2844`「至少 200 词」写成 195 词，只差 2 与 5 个词。把这两条按「差几个词不算没做到」翻正，读数就变成 **17 掉 / 7 涨、Δ = −10.0pp、精确 McNemar p = 0.064**（不一致 24 条，双侧精确检验；算法：`p = 2·Σ_{k=0}^{7} C(24,k)/2²⁴`），跨到 0.05 门外。所以 −12pp 的正确读法是「未校正下显著，且不稳健」：它不需要重算，但读者必须知道换掉两条擦线就没了。
- **GSM8K 仍然没测到下降。** +3.0pp、区间 [−6.0, +12.0] 跨 0、p 0.678、10 掉 13 涨：它既不能宣称没掉，也不能宣称涨了。
- **这个 n 能看见多小的掉幅**：n=100 的检出下限是 **5pp（McNemar 精确检验，且掉点没有涨来抵消）／4pp（配对自举区间不含 0）**（见「这个 n 能看见多大的掉幅」）。所以「GSM8K 没测到」的准确读法是「4–5pp 以上的下降会被看见，而没看见」；「IFEval 测到 −12pp」的准确读法是「它是这个下限的两倍多」。
- **「没有可信的下降证据」从此只在 GSM8K 那一格成立。** 支撑上一版结论的 n=20 读数留在后面「前一次估计」一节：同样本前 20 条是 GSM8K −10.0pp、IFEval −20.0pp；扩到 100 条后 GSM8K 翻正、IFEval 收窄到 −12pp。点估计随 n 变了，没变的是 IFEval 的负号。

### headroom 判定（口径不变，n=100 重算）

headroom（训练前基座分数是否落在判别带 30–70%）用真模型跑出来了，两个套件各 n=100、贪心解码、seed 0、冻结样本前缀：

| 套件 | n | 正确 | 基座分数 | Wilson 95% | 单条耗时 | headroom 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| GSM8K | 100 | 73 | **73.0%** | [63.6%, 80.7%] | 23.2 s | 边际通过，判别力偏弱（点估计在带上沿之外，见下） |
| IFEval | 100 | 57 | **57.0%** | [47.2%, 66.3%] | 22.1 s | 通过：落在判别带正中 |

判定按约定阈值读，不按印象读：

- **IFEval 采用。** 点估计 57.0%，区间 [47.2%, 66.3%] 完整落在 30–70% 带内，离天花板 85% 和地板 15% 都远 → 对「掉没掉」敏感。n 从 20 到 100 只把点估计从 60.0% 挪到 57.0%，判定没变。
- **GSM8K 采用但标注判别力偏弱。** 点估计 73.0% 已在 30–70% 带的上沿之外，区间上界 80.7% 离 85% 天花板还有 4.3pp（n=20 时是 88.8%，越过了天花板），所以「已经贴顶」从「不能排除」降级为「没有证据」，但仍不能当成没贴顶：点估计高于带的上沿这件事本身没消除。它的用法限定为：**4–5pp 以上的掉幅会被看见，但不拿它宣称「没掉」**。按约定若点估计 >85% 就不采用；73.0% 低于 85%，故采用，结论强度写在这里，不留给读者自己推。
- **四格都已跑完。** 未跑的只剩全量（GSM8K 200 条、IFEval 295 条），逐格列在「未跑与续跑命令」。

**样本量曾经是降过的。** 上一轮按 25 分钟硬预算把四格降到 n=20（单条 23.3–35.9 s，100 条单套件就要 40–60 分钟）。这一轮派发的是约定值 `--limit 100`，四格实测单条 14.1–23.4 s、整轮墙钟 78.5 分钟（见「实测速度与预算重算」），所以「装不进预算」这个理由已经消失。n=20 的四格与两份配对结果移到了 `evidence/benchmark/n20/`（提交 `fc273a9`），保留在同一样本前 20 条的位置上。

## 配对对照：base 对 adapter（n=100，同一样本 id）

方法就是「换一个变量」：

- **同一批 100 条。** `data/bench/sources.json` 的 seed 0 按 `sha256("0:<id>")` 升序取前缀，`--limit 100` 永远是同 100 条；`analyse_paired.py` 先比对两次运行的 `limit`、`seed`、`frozen_sha256`、`decoding`，再比对记录里的 id 顺序，不一致直接报错退出，不会算出一个假的配对结果。
- **只换模型。** 解码贪心、`max_new_tokens` 512/640 由 `sources.json` 固定，adapter 走 `PeftModel.from_pretrained` 加载 `.tmp/sft/adapter-narrow`（r=16，41.7 MB）。判分代码一行没改，`correct` 直接读落盘记录。
- **落盘可查。** `evidence/benchmark/paired-<suite>.json` 记两条分数、Wilson 区间、差值、配对自举区间、翻转 id（`drop_ids`/`gain_ids`）、McNemar p、检出下限和两侧耗时。

| 套件 | base | adapter | 差值 | 配对自举 95% | 掉 | 涨 | 不变 | McNemar p |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GSM8K | 73/100 | 76/100 | +3.0pp | [−6.0, +12.0] | 10 | 13 | 77 | 0.678 |
| IFEval | 57/100 | 45/100 | −12.0pp | [−22.0, −3.0] | 19 | 7 | 74 | 0.029 |

配对而不是比两个单格区间，是因为 100 条里只有 29–32 条真正翻转，其余 68–77 条两条模型答案一模一样；把「同一条上翻没翻」当样本，噪声比两个独立比例小得多。McNemar 只看不一致的那几条（GSM8K 23 条、IFEval 26 条）。

### 逐条读 19 条 IFEval 掉点：受伤的是「字数/标点/标记」这类表层指令

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

19 条掉点里，每条只丢一条指令（没有一条是因为同一题上丢两条而多算的），按指令汇总：

| 掉的指令 | 掉几条 | 该指令在这 100 条里出现几条 | 读法 |
| --- | --- | --- | --- |
| `length_constraints:number_words` | 6 | 23 | 5 条是「至少 N 词」没过（adapter 写短了），1 条是「少于 151 词」被超 |
| `punctuation:no_comma` | 4 | 12 | 全是 base 0 个逗号、adapter 冒出 1–8 个 |
| `detectable_format:number_highlighted_sections` | 2 | 16 | 少写了 `*高亮*` 段落 |
| `detectable_content:number_placeholders` | 2 | 5 | 少写了占位符 |
| `startend:quotation` | 2 | 10 | 首尾引号没包住 |
| `detectable_format:json_format` / `change_case:english_capital` / `keywords:forbidden_words` | 各 1 | 4 / 10 / 11 | 各一条 |

三条可直接核的事实：

1. **不是答错，是答短了。** 100 条里 adapter 有 65 条比 base 短，词数中位数 **212.5 → 169.0**（均值 248.3 → 202.8）；GSM8K 更明显，中位数 **204.0 → 83.0**、均值 210.2 → 95.1 词，100 条里 99 条更短。「至少 N 词」这类下限指令因此先受伤：5 条没过里 3 条只差 2–23 词（`ifeval-1072` 398/400、`ifeval-209` 377/400、`ifeval-2844` 195/200），另两条差 62（209 词对 300 下限）与 91 词（238 词对 300 下限）；第 6 条方向相反，`ifeval-1217` 是「少于 151 词」而 adapter 写了 463 词——同一条「写多写少」的轴，两头都撞上检查。
   - 其中两条（`ifeval-1072` 差 2 词、`ifeval-2844` 差 5 词）翻正就把整个读数改写成 **17 掉 / 7 涨、Δ = −10.0pp、精确 McNemar p = 0.064**；这就是「结论压在 2 个词上」那句话的来历，也是 n=295 必须跑的理由。
2. **逗号禁令是另一条独立的伤。** 冻结的 295 条里有 38 条带 `no_comma`；这 100 条里 12 条，其中 base 10 条一个逗号不写，adapter 在 5 条里写出 1–8 个，4 条因此由对变错（`ifeval-2374` 0→8、`ifeval-1928` 0→5、`ifeval-3376` 0→2、`ifeval-2417` 0→1，另一条 `ifeval-1069` 两侧仍对）。
3. **其他 9 条掉点与 GSM8K 一样零散。** 没有一条是「写不出可判分回答」：两套件 200 份记录 `unscorable` 都是 0，分母一直是 100。

所以这一格的 −12pp 不是「通用能力掉了一截」的单一东西，而是**回答变短、并多了逗号**这个风格变化撞在 IFEval 的表层检查上——与 §4.3「提升的 65.3% 是交互项」同一个方向：SFT 改的是回答方式，而「按格式写」的能力是这套方式的代价。

### 这个 n 能看见多大的掉幅

用同一套自举和精确检验算出来的检出下限（α=0.05，且掉的那几条没有任何涨来抵消，这是最有利的情形）。两个 n 列在一起，因为「没测到」这句话的强度就是由这一行决定的：

| n | 判据 | 最少掉几条 | 折成掉幅 |
| --- | --- | --- | --- |
| **100** | 配对自举区间不含 0 | 4 | **4pp** |
| **100** | McNemar 精确检验 p<0.05 | 5 | **5pp** |
| 20 | 配对自举区间不含 0 | 4 | 20pp |
| 20 | McNemar 精确检验 p<0.05 | 5 | 25pp |

读法：**n=100 能看见 4–5pp 级别的掉幅，n=20 只能看见 ≳20pp**——同一条判据下，把 n 乘 5 把下限除以 5。这一轮两个格子的读数各自落在这个分辨力上：IFEval 净掉 12 条，是下限的两倍多，所以区间不含 0；GSM8K 净涨 3 条，离下限还差得远，所以只能写「没测到」而不写「没掉」。想看 3pp 以下的差异，n=100 不够，得跑全量（IFEval 295 条）或把套件加宽——那一步不在这一轮里。

### 前一次估计：同一样本前 20 条（n=20）

n=20 的四格是同一批冻结样本的前 20 条（同一 seed、同一判分、同一 adapter），现在只作为「同一样本的前一次估计」存在，**不再是谁的当前读数**。它留在报告里是因为它能用来说明「n 小的时候点估计会飘到哪里」：

| 套件 | base | adapter | 差值 | 配对 95% | 掉 | 涨 | 不变 | McNemar p | 判定 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GSM8K | 15/20 = 75.0% | 13/20 = 65.0% | −10.0pp | [−30.0, +10.0] | 3 | 1 | 16 | 0.625 | 没测到下降；也看不见 20pp 以内的下降 |
| IFEval | 12/20 = 60.0% | 8/20 = 40.0% | −20.0pp | [−40.0, 0.0] | 5 | 1 | 14 | 0.219 | 点估计降幅最大，但区间触 0 |

同一批前 20 条当时也逐条核过，结论与 n=100 那一节不矛盾：IFEval 五条掉点全是格式/指令合规逐条翻 `false`（`number_placeholders`、`highlighted_sections` ×2、`no_comma`、`number_words`、`json_format`），GSM8K 三条掉点是算错数（gold 150→pred 6、60→5、50→100），两套件 `unscorable` 都是 0。当时把这五条读成「与训练目标一致：改的是回答方式，最先受伤的是按格式写」，n=100 的 19 条掉点把这个读法坐实了（见「逐条读 19 条 IFEval 掉点」）。当时的结论句只能写到「没有可信的下降证据」，因为两个区间都跨过或触到 0，而且 IFEval 的 −20pp 恰好压在那个 n 的 20–25pp 下限上：再掉一条就是显著。

## 落盘

| 路径 | 内容 |
| --- | --- |
| `evidence/benchmark/base-gsm8k.json` | 100 条完整记录（prompt、输出、判定、是否正确、`per_instruction`）+ summary + `elapsed_seconds`，`limit: 100`、`seed: 0`、`decoding: greedy`、`max_new_tokens: 512`、`frozen_sha256: def2e3a0…c1d3` |
| `evidence/benchmark/base-ifeval.json` | 同上，`max_new_tokens: 640`、`frozen_sha256: 0cc0fb57…71e` |
| `evidence/benchmark/adapter-gsm8k.json` / `adapter-ifeval.json` | adapter 侧同样 100 条完整记录 + summary；`adapter_dir` 记了 LoRA 路径，`decoding: greedy`、`seed: 0`、`limit: 100` 与 base 逐字段相同 |
| `evidence/benchmark/paired-gsm8k.json` / `paired-ifeval.json` | 配对比较结果：两条分数与 Wilson 区间、差值、配对自举区间、翻转 id、McNemar p、检出下限、两侧耗时 |
| `evidence/benchmark/logs-n100/` | `driver.log`（两相 rc、两行 `analyse` 读数）、`driver.out`、`driver.pid`、四份逐格 stdout、`inflight.md`（派发时的 pid 与续跑点） |
| `evidence/benchmark/n20/` | 同一样本前 20 条的四格与两份配对结果（上一版的读数，保留为前一次估计） |
| `evidence/benchmark/analyse_paired.py` | 重算上表每个数字；四格任一缺失即退出码 1。配对自举复用 `scripts/resample_actions.py` 的那一份实现，树里不存第二份 |

四次运行都 `unscorable=0`，即 400 条记录全部吐出了可判分的回答，没有一条因为抽不出数或空回答被排除；`accuracy` 的分母是条数，不是可判分数。

## 实测速度与预算重算

原报告按 30–60 token/s 估出"两套件 × base/adapter 约 1.5–3 小时"。这个估计被实测推翻，现在用实测值替换（n=100 的四行是本轮实测，n=20 的四行是上一轮实测，两轮卡上负载不同，所以逐行标了备注）：

| 观测 | 条数 | 生成时间 | 单条 | 备注 |
| --- | --- | --- | --- | --- |
| base GSM8K 与 IFEval 并行（n=100） | 100 | 2324.1 s | 23.2 s | 卡上只剩本轮两路，预检时空 23560 MiB |
| base IFEval 与 GSM8K 并行（n=100） | 100 | 2213.5 s | 22.1 s | 同上 |
| adapter GSM8K 与 IFEval 并行（n=100） | 100 | 1407.7 s | 14.1 s | 同上；比上一轮的 23.3 s 快 40%，因为卡空了 |
| adapter IFEval 与 GSM8K 并行（n=100） | 100 | 2344.4 s | 23.4 s | 同上；比上一轮的 35.9 s 快 35% |
| GSM8K 单进程 probe | 10 | 246 s（`WALL 258.7 s` 含加载） | 24.6 s | 独占卡时 |
| GSM8K 与 IFEval 并行（n=20） | 20 | 536.9 s | 26.8 s | 两路同时跑，互相拖慢约 9% |
| IFEval 与 GSM8K 并行（n=20） | 20 | 569.9 s | 28.5 s | 输出更长（均 1423 字符 vs 1104） |
| adapter GSM8K 与 IFEval 并行（n=20） | 20 | 465.8 s | 23.3 s | 上一轮早段，卡上另一任务较轻 |
| adapter IFEval 与 GSM8K 并行（n=20） | 20 | 718.6 s | 35.9 s | 同刻另一任务（动作测量）在跑，慢了 26% |

n=100 那一轮的整体墙钟：`12:41:08` 预检 → `13:59:40` analyse → **78 分 32 秒（4713 s）**，两相各两路并行，四格生成时间合计 8290 s（并行度 1.76×，与 n=20 那一轮算出的 1.75× 一致）。上一轮拿 4.2 条/分钟外推「四格全量 990 条约 4.5–5 h」；按 n=100 实测的 5.1 条/分钟（400 条 / 78.5 分钟）重算，990 条约 3.2 h，所以那个估计是保守的，不夸大。

上一轮的外推表（保留作为当时的估计，它现在已经可以被实测取代）：

| 全量单元 | 条数 | 并行两路时的时间（当时的估计） | 按 n=100 实测量重算 |
| --- | --- | --- | --- |
| base GSM8K | 200 | ≈ 90 min | ≈ 79 min |
| base IFEval | 295 | ≈ 140 min | ≈ 109 min |
| adapter GSM8K | 200 | ≈ 90 min | ≈ 48 min |
| adapter IFEval | 295 | ≈ 140 min | ≈ 115 min |
| 全部四个单元 | 990 | **≈ 4.5–5 h** | **≈ 3.2 h**（GSM8K 路 79+48 min、IFEval 路 109+115 min，取长的那条） |

**花费对账（相对派发时的授权）**：派发时按 ≈5 小时墙钟给了 `idle-compute`（单卡 4090，不碰 metered、不花 API 钱）。实测 **1.31 小时**（4713 s，包了预检、两相四格与 analyse），用了授权的 **26%**；四格生成时间合计 2.3 GPU 小时（两路并行）。所以这一轮的花费类是 `idle-compute`，金额是 **¥0**，剩下 ≈3.7 小时未用。计账在 [`report/measurements.md`](measurements.md) 的「本机 GPU（不计钱）」一节。

慢的成因：transformers 警告 `flash-linear-attention` 与 `causal_conv1d` 未安装，回落到 reference PyTorch 实现（四次运行都警告）。上一轮把这个归因与「卡上还有另一个任务」攪在一起，n=100 那一轮把两者分开了：预检时卡上 23560 MiB 全空，单条仍然要 14.1–23.4 s，所以主要原因是未编译的 kernel，不是并发。没有装这两个包（需要网络，本机 PyPI 不可达），也没有改量化、没有加 batch——改了就不是同一把尺子，base 与 adapter 的对比会失去意义。

## 未跑与续跑命令

| 单元 | 状态 | 命令 |
| --- | --- | --- |
| base GSM8K n=20 | 已跑（前一次估计，`n20/`） | — |
| base IFEval n=20 | 已跑（前一次估计，`n20/`） | — |
| base GSM8K n=100（约定值） | **已跑**（`logs-n100/base-gsm8k.log`） | — |
| base IFEval n=100（约定值） | **已跑**（`logs-n100/base-ifeval.log`） | — |
| base GSM8K n=200（全量） | **未跑** | `nohup python3 scripts/run_bench.py --suite gsm8k --model base --limit 200 > evidence/benchmark/logs-full/base-gsm8k.log 2>&1 &` |
| base IFEval n=295（全量） | **未跑** | `nohup python3 scripts/run_bench.py --suite ifeval --model base --limit 295 > evidence/benchmark/logs-full/base-ifeval.log 2>&1 &` |
| adapter GSM8K n=20 | 已跑（前一次估计，`n20/`） | — |
| adapter IFEval n=20 | 已跑（前一次估计，`n20/`） | — |
| adapter GSM8K n=100（约定值） | **已跑**（`logs-n100/adapter-gsm8k.log`） | — |
| adapter IFEval n=100（约定值） | **已跑**（`logs-n100/adapter-ifeval.log`） | — |
| adapter GSM8K n=200（全量） | **未跑** | `nohup python3 scripts/run_bench.py --suite gsm8k --model adapter --limit 200 > evidence/benchmark/logs-full/adapter-gsm8k.log 2>&1 &` |
| adapter IFEval n=295（全量） | **未跑** | `nohup python3 scripts/run_bench.py --suite ifeval --model adapter --limit 295 > evidence/benchmark/logs-full/adapter-ifeval.log 2>&1 &` |

跑 adapter 侧之前先确认 `.tmp/sft/adapter-narrow/` 还在：它在 `.tmp/` 下，按约定是可删的临时区，删了就只能重训。

**⚠ 全量那四行会覆盖当前的 n=100 产物。** `run_bench.py` 的输出路径是固定的 `<model>-<suite>.json`，`analyse_paired.py` 写固定的 `paired-<suite>.json`，没有 `--out`。所以要跑全量，得先把当前的 n=100 四格与两份配对结果拷到 `evidence/benchmark/n100/`（照 `n20/` 的做法），否则本文引的那组数字就从工作区里消失了（git 历史里仍在，提交 `6dc8f52`）。另：`--seed` 必须等于 `sources.json` 的冻结 seed（现在是 0，不相等就报错），所以「换一个 seed 再抽 100 条」不是这个 harness 支持的动作；要独立重复，只能把同一个 seed 的冻结序列往后推（n=295 全量，第 101–295 条对当前读数是新的）。

**同一把尺子的要求：** base 与 adapter 必须同样的 `--limit`、同样的并行/串行方式。这轮做到了：两套件各自两路并行（`run_m2_n100.sh`），base 与 adapter 都是。并行带来的拖慢只影响耗时，不影响分数（贪心解码、同样权重、同样 100 条 id）。

## 判读方法：没观察到下降不等于没有下降

这一条是这份报告的边界，不是免责声明：

- 每格分数带 95% Wilson 区间。**两条区间重叠不等于「没有下降」**，只等于「这轮没测到下降」；n=100 时单格 Wilson 半宽约 9–10pp（GSM8K ±8.6pp、IFEval ±10.1pp），比 n=20 的 ±18pp 窄一半，但 4–5pp 以下的掉幅仍然看不见。
- 判「掉」看**配对差值区间与配对检验**，不看两条单格区间是否重叠：单格区间的重叠永远是粗略判法，而配对把「同一条上翻没翻」作样本，同样的 n 更灵敏。这轮 IFEval 的 −12pp 两条判据都过了（区间不含 0、McNemar p=0.029），GSM8K 的 +3pp 两条都没过。
- 解码是贪心、单 seed，残余随机性只有数值实现差别，所以两次真跑之间的小抖动不构成"能力变化"的证据；反过来，贪心也意味着分数是这条固定路径上的一个点，不是分布的期望。
- IFEval 只覆盖 15 类指令（541 条中留 295 条），**不能与公开 IFEval 数比**，只能 base 对 adapter 自比。
- GSM8K 的判别力偏弱（见结论），SFT 只喂了 288 条长中文回答，若它损伤的是"回答方式"而非数学，GSM8K 掉不下来正是预期，不能反推"通用能力没掉"；反过来，4–5pp 以上的下降在这一格会被看见，而这一轮没看见（+3.0pp [−6.0, +12.0]）。

## 选型：判定标准与结论（未变）

判定标准五行：能否离线（本机不再下载）、许可、样本量、判分是否确定、与本任务「下一步该做什么判断」的相关度。

| 候选 | 离线 | 许可 | 样本量 | 判分确定 | 相关度 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| GSM8K | 是：`openai/grade-school-math` test.jsonl 已下到仓库，750 KB 源 → 冻结 200 条 | MIT | 1319 → 取 200 | 是：取 `####` 后的数与金标数比，无评委 | 中高：数学推理是「通用能力」最短的那块板，SFT 只喂了 288 条长中文回答，这里最可能先掉 | **选**（实测基座 75%，判别力偏弱） |
| IFEval | 是：HF 缓存 `google/IFEval` 快照在 `/home/z/hf/hub`，源 541 条 | Apache-2.0 | 541 → 取 295 | 是：15 类指令全部是正则/结构检查 | 高：训练目标是「换一种回答方式」，格式与长度指令正是这种改动最可能连带损伤的能力 | **选**（实测基座 60%，判别带正中） |
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

采样规则：候选 id 按 `sha256("<seed>:<id>")` 升序排，取前缀；与源文件行序无关，故同一 seed 复现同一样本，`--limit` 小的那次是大那次的前缀（这轮的 20 条与正式 200 条可直接比）。seed 固定为 0，写在 `sources.json` 里，`run_bench.py --seed` 与它不一致即报错。解码贪心（`do_sample=False`）。

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
