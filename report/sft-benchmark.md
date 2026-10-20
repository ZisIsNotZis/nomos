# Benchmark：base 75.0%/60.0%，adapter 65.0%/40.0%，配对差 −10pp / −20pp 都没到检出下限；全量未跑

## 结论

四个格子都跑完了：每套件 n=20、同一条冻结样本前缀、seed 0、贪心解码，base 与 adapter 用同一把尺子（只换模型，不改判分）。

| 套件 | base | adapter | 差值（adapter−base） | 配对 95% 区间 | 配对翻转（掉/涨） | McNemar 精确 p | 判定 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GSM8K | 15/20 = **75.0%** | 13/20 = **65.0%** | **−10.0pp** | [−30.0, +10.0] | 3 / 1 | 0.625 | 没测到下降；也看不见 20pp 以内的下降 |
| IFEval | 12/20 = **60.0%** | 8/20 = **40.0%** | **−20.0pp** | [−40.0, 0.0] | 5 / 1 | 0.219 | 本轮最大的点估计降幅，但区间触 0，够不到 95% 显著 |

读法：「没测到」不等于「没有」。两个差值区间都跨过或触到 0，所以这轮的结论句只能写到「没有可信的下降证据」，不能写成「能力没掉」。IFEval 的 −20pp 恰好压在这个 n 的检出下限上（见「这个 n 能看见多大的掉幅」），再掉一条就是显著。

配对翻转的构成是唯一能指向机制的证据，逐条核过：

- **IFEval 五条掉点全是格式/指令合规逐条翻 false**：`number_placeholders`、`highlighted_sections`（两条）、`no_comma`、`number_words`、`json_format`。与训练目标一致——SFT 只喂了 288 条长中文回答，改的是回答方式，最先受伤的是「按格式写」这类指令跟随。
- **GSM8K 三条掉点是算错数**（gold 150→pred 6、60→5、50→100），不是抽不出数：两套件 `unscorable` 都是 0，40 条全部吐出可判分回答，分母一直是 20。

### headroom 判定（口径不变）

headroom（训练前基座分数是否落在判别带 30–70%）用真模型跑出来了，两个套件各 n=20、贪心解码、seed 0、冻结样本前缀：

| 套件 | n | 正确 | 基座分数 | Wilson 95% | 单条耗时 | headroom 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| GSM8K | 20 | 15 | **75.0%** | [53.1%, 88.8%] | 26.8 s | 边际通过，判别力偏弱（见下） |
| IFEval | 20 | 12 | **60.0%** | [38.7%, 78.1%] | 28.5 s | 通过：落在判别带正中 |

判定按约定阈值读，不按印象读：

- **IFEval 采用。** 点估计 60.0%，区间 [38.7%, 78.1%] 完全覆盖 30–70% 带，离天花板 85% 和地板 15% 都远，掉 20pp 就出带 → 对"掉没掉"敏感。
- **GSM8K 采用但标注判别力偏弱。** 点估计 75.0% 已在 30–70% 带的上沿之外，区间上界 88.8% 越过了 85% 天花板，所以不能排除这个套件已经贴顶。它的用法因此限定为：**只能看见 ≳20pp 的掉幅（实测下限，见「这个 n 能看见多大的掉幅」），不能拿来宣称「没掉」**。按约定若点估计 >85% 就不采用；75.0% 低于 85%，故采用，但结论强度写在这里，不留给读者自己推。
- **base 与 adapter 两格都已跑，差值与区间在本轮已给出（见上表与「配对对照」）。** 未跑的只剩全量（200/295 条）与 n=100 的约定值，逐格列在「未跑与续跑命令」。

**样本量是降过的，这是本轮最大的一处偏离。** 约定跑 `--limit 100`，实测单条 23.3–35.9 s，100 条单套件就要 40–60 分钟，两套件 × base/adapter 更装不进 25 分钟硬预算。于是四个格子统一降到 n=20（base 与 adapter 都是），代价是单格 Wilson 半宽从 ±9pp 变到 ±18pp、配对检出下限站到 20–25pp：GSM8K 的「可能贴顶」和两套件的「没测到显著下降」都是 n 小造成的，不是能力结论。续跑命令见文末，`--limit 100` 与全量都是同一条冻结序列的前缀，所以这 20 条是大跑的前 20 条，不冲突，可直接被覆盖升级。

## 配对对照：base 对 adapter（n=20，同一样本 id）

方法就是「换一个变量」：

- **同一批 20 条。** `data/bench/sources.json` 的 seed 0 按 `sha256("0:<id>")` 升序取前缀，`--limit 20` 永远是同 20 条；`analyse_paired.py` 先比对两次运行的 `limit`、`seed`、`frozen_sha256`、`decoding`，再比对记录里的 id 顺序，不一致直接报错退出，不会算出一个假的配对结果。
- **只换模型。** 解码贪心、`max_new_tokens` 512/640 由 `sources.json` 固定，adapter 走 `PeftModel.from_pretrained` 加载 `.tmp/sft/adapter-narrow`（r=16，41.7 MB）。判分代码一行没改，`correct` 直接读落盘记录。
- **落盘可查。** `evidence/benchmark/paired-<suite>.json` 记两条分数、Wilson 区间、差值、配对自举区间、翻转 id（`drop_ids`/`gain_ids`）、McNemar p、检出下限和两侧耗时。

| 套件 | base | adapter | 差值 | 配对自举 95% | 掉 | 涨 | 不变 | McNemar p |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GSM8K | 15/20 | 13/20 | −10.0pp | [−30.0, +10.0] | 3 | 1 | 16 | 0.625 |
| IFEval | 12/20 | 8/20 | −20.0pp | [−40.0, 0.0] | 5 | 1 | 14 | 0.219 |

配对而不是比两个单格区间，是因为 20 条里只有 4–6 条真正翻转，其余 14–16 条两条模型答案一模一样；把「同一条上翻没翻」当样本，噪声比两个独立比例小得多。McNemar 只看不一致的那几条（GSM8K 4 条、IFEval 6 条），所以 p 值大：n=20 时不一致的样本只有个位数。

### 这个 n 能看见多大的掉幅

用同一套自举和精确检验算出来的检出下限（α=0.05，且掉的那几条没有任何涨来抵消，这是最有利的情形）：

| 判据 | 最少掉几条 | 折成掉幅 |
| --- | --- | --- |
| 配对自举区间不含 0 | 4 | **20pp** |
| McNemar 精确检验 p<0.05 | 5 | **25pp** |

两条合起来的读法：**n=20 只能看见 ≳20pp 的掉幅，而且要求几乎不退不涨地整片掉**。这轮 IFEval 是 5 掉 1 涨，净 −4 条，刚好差在 McNemar 的 5 条门线下一格；GSM8K 是 3 掉 1 涨，净 −2 条，离两条判据的下限都还远。GSM8K 基座 15/20 已贴上沿，顶板效应对它比对 IFEval 更紧：它连 20pp 的掉幅都只能靠 4 条承载。想吃掉 10pp 级别的差异，每格 n 要到 150 左右，那是全量（200/295 条）才做得到的事，本轮没跑。

## 落盘

| 路径 | 内容 |
| --- | --- |
| `evidence/benchmark/base-gsm8k.json` | 20 条完整记录（prompt、输出、判定、是否正确）+ summary + `elapsed_seconds`，`limit: 20`、`seed: 0`、`decoding: greedy`、`max_new_tokens: 512`、`frozen_sha256: def2e3a0…c1d3` |
| `evidence/benchmark/base-ifeval.json` | 同上，`max_new_tokens: 640`、`frozen_sha256: 0cc0fb57…71e` |
| `evidence/benchmark/adapter-gsm8k.json` / `adapter-ifeval.json` | adapter 侧同样 20 条完整记录 + summary；`adapter_dir` 记了 LoRA 路径，`decoding: greedy`、`seed: 0`、`limit: 20` 与 base 逐字段相同 |
| `evidence/benchmark/paired-gsm8k.json` / `paired-ifeval.json` | 配对比较结果：两条分数与 Wilson 区间、差值、配对自举区间、翻转 id、McNemar p、检出下限、两侧耗时 |
| `evidence/benchmark/analyse_paired.py` | 重算上表每个数字；四格任一缺失即退出码 1。配对自举复用 `scripts/resample_actions.py` 的那一份实现，树里不存第二份 |
| `evidence/benchmark/base-gsm8k.log` / `base-ifeval.log` / `adapter-gsm8k.log` / `adapter-ifeval.log` | 四次运行的 stdout（含 `/usr/bin/time` 的耗时） |

四次运行都 `unscorable=0`，即 80 条记录全部吐出了可判分的回答，没有一条因为抽不出数或空回答被排除；`accuracy` 的分母是条数，不是可判分数。

## 实测速度与预算重算

原报告按 30–60 token/s 估出"两套件 × base/adapter 约 1.5–3 小时"。这个估计被实测推翻，现在用实测值替换：

| 观测 | 条数 | 生成时间 | 单条 | 备注 |
| --- | --- | --- | --- | --- |
| GSM8K 单进程 probe | 10 | 246 s（`WALL 258.7 s` 含加载） | 24.6 s | 独占卡时 |
| GSM8K 与 IFEval 并行 | 20 | 536.9 s | 26.8 s | 两路同时跑，互相拖慢约 9% |
| IFEval 与 GSM8K 并行 | 20 | 569.9 s | 28.5 s | 输出更长（均 1423 字符 vs 1104） |
| adapter GSM8K 与 IFEval 并行 | 20 | 465.8 s | 23.3 s | 本轮早段，卡上另一任务较轻 |
| adapter IFEval 与 GSM8K 并行 | 20 | 718.6 s | 35.9 s | 同刻另一任务（动作测量）在跑，慢了 26% |

两路并行合计吞吐 4.2 条/分钟，串行是 2.4 条/分钟，**并行 1.75×**。据此推算（不是实测）：

| 全量单元 | 条数 | 并行两路时的时间 |
| --- | --- | --- |
| base GSM8K | 200 | ≈ 90 min |
| base IFEval | 295 | ≈ 140 min |
| adapter GSM8K | 200 | ≈ 90 min |
| adapter IFEval | 295 | ≈ 140 min |
| 全部四个单元 | 990 | **≈ 4.5–5 h**（GSM8K 路 180 min、IFEval 路 280 min，取长的那条） |

慢的成因是推断而非测量，标出来以免被当成结论：transformers 四次警告 `flash-linear-attention` 与 `causal_conv1d` 未安装，回落到 reference PyTorch 实现；同一时刻卡上还有另一个任务（约 5.2 GiB）和别的项目占用。没有装这两个包（需要网络，本机 PyPI 不可达），也没有改量化、没有加 batch——改了就不是同一把尺子，base 与 adapter 的对比会失去意义。

## 未跑与续跑命令

| 单元 | 状态 | 命令 |
| --- | --- | --- |
| base GSM8K n=20 | 已跑 | — |
| base IFEval n=20 | 已跑 | — |
| base GSM8K n=100（约定值） | **未跑** | `nohup python3 scripts/run_bench.py --suite gsm8k --model base --limit 100 > evidence/benchmark/base-gsm8k.log 2>&1 &` |
| base IFEval n=100（约定值） | **未跑** | `nohup python3 scripts/run_bench.py --suite ifeval --model base --limit 100 > evidence/benchmark/base-ifeval.log 2>&1 &` |
| base GSM8K n=200（全量） | **未跑** | `nohup python3 scripts/run_bench.py --suite gsm8k --model base --limit 200 > evidence/benchmark/base-gsm8k-full.log 2>&1 &` |
| base IFEval n=295（全量） | **未跑** | `nohup python3 scripts/run_bench.py --suite ifeval --model base --limit 295 > evidence/benchmark/base-ifeval-full.log 2>&1 &` |
| adapter GSM8K n=20 | 已跑 | — |
| adapter IFEval n=20 | 已跑 | — |
| adapter GSM8K n=100（约定值） | **未跑** | `nohup python3 scripts/run_bench.py --suite gsm8k --model adapter --limit 100 > evidence/benchmark/adapter-gsm8k.log 2>&1 &` |
| adapter IFEval n=100（约定值） | **未跑** | `nohup python3 scripts/run_bench.py --suite ifeval --model adapter --limit 100 > evidence/benchmark/adapter-ifeval.log 2>&1 &` |
| adapter GSM8K n=200（全量） | **未跑** | `nohup python3 scripts/run_bench.py --suite gsm8k --model adapter --limit 200 > evidence/benchmark/adapter-gsm8k-full.log 2>&1 &` |
| adapter IFEval n=295（全量） | **未跑** | `nohup python3 scripts/run_bench.py --suite ifeval --model adapter --limit 295 > evidence/benchmark/adapter-ifeval-full.log 2>&1 &` |

跑 adapter 侧之前先确认 `.tmp/sft/adapter-narrow/` 还在：它在 `.tmp/` 下，按约定是可删的临时区，删了就只能重训。

**同一把尺子的要求：** base 与 adapter 必须同样的 `--limit`、同样的并行/串行方式。这轮做到了：两套件各自两路并行，base 与 adapter 都是。并行带来的拖慢只影响耗时，不影响分数（贪心解码、同样权重、同样 20 条 id）；但**耗时两轮不可比**——adapter IFEval 那条赶上卡上另一任务最重的时候，35.9 s/条 比 base 的 28.5 s 慢 26%，这不是模型变慢。

## 判读方法：没观察到下降不等于没有下降

这一条是这份报告的边界，不是免责声明：

- 每格分数带 95% Wilson 区间。**两条区间重叠不等于「没有下降」**，只等于「这轮没测到下降」；n=20 时单格 Wilson 半宽约 18pp，10pp 的掉幅在这里看不见；要看见 10pp 需要每格 n≥150 左右。
- 判「掉」看**配对差值区间与配对检验**，不看两条单格区间是否重叠：单格区间的重叠永远是粗略判法，而配对把「同一条上翻没翻」作样本，同样的 n 更灵敏。这轮的 −10pp 与 −20pp 都跨过或触到 0，只能说没测到。
- 解码是贪心、单 seed，残余随机性只有数值实现差别，所以两次真跑之间的小抖动不构成"能力变化"的证据；反过来，贪心也意味着分数是这条固定路径上的一个点，不是分布的期望。
- IFEval 只覆盖 15 类指令（541 条中留 295 条），**不能与公开 IFEval 数比**，只能 base 对 adapter 自比。
- GSM8K 的判别力偏弱（见结论），SFT 只喂了 288 条长中文回答，若它损伤的是"回答方式"而非数学，GSM8K 掉不下来正是预期，不能反推"通用能力没掉"；反过来它掉了 10pp 也一样不能反推"数学变差"——两者都在检出下限以内。

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
