# Benchmark：headroom 已实测，两套件都采用；全量与 adapter 侧未跑

## 结论

headroom（训练前基座分数是否落在判别带 30–70%）用真模型跑出来了，两个套件各 n=20、贪心解码、seed 0、冻结样本前缀：

| 套件 | n | 正确 | 基座分数 | Wilson 95% | 单条耗时 | headroom 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| GSM8K | 20 | 15 | **75.0%** | [53.1%, 88.8%] | 26.8 s | 边际通过，判别力偏弱（见下） |
| IFEval | 20 | 12 | **60.0%** | [38.7%, 78.1%] | 28.5 s | 通过：落在判别带正中 |

判定按约定阈值读，不按印象读：

- **IFEval 采用。** 点估计 60.0%，区间 [38.7%, 78.1%] 完全覆盖 30–70% 带，离天花板 85% 和地板 15% 都远，掉 20pp 就出带 → 对"掉没掉"敏感。
- **GSM8K 采用但标注判别力偏弱。** 点估计 75.0% 已在 30–70% 带的上沿之外，区间上界 88.8% 越过了 85% 天花板，所以不能排除这个套件已经贴顶。它的用法因此限定为：**能看见 ≥15pp 的掉幅，不能拿来宣称"没掉"**。按约定若点估计 >85% 就不采用；75.0% 低于 85%，故采用，但结论强度写在这里，不留给读者自己推。
- **base 与 adapter 的分数与差值：一个数字都没有，全部未跑。** 表里没有估计值、没有占位符；未跑的格子在下面"未跑与续跑命令"里逐格写明。

**样本量是降过的，这是本轮最大的一处偏离。** 约定 headroom 用 `--limit 100`，实测单条 26.8–28.5 s，100 条单套件就要 45–48 分钟，两套件 1.5 小时以上，装不进 25 分钟硬预算。于是降到 n=20，代价是 Wilson 半宽从 ±9pp 变到 ±18pp：GSM8K 的"可能贴顶"正是因为 n 小才没能排除。续跑命令见文末，`--limit 100` 与 `--limit 200` 都是同一条冻结序列的前缀，所以这 20 条是大跑的前 20 条，不冲突，可直接被覆盖升级。

## headroom 实测的落盘

| 路径 | 内容 |
| --- | --- |
| `evidence/benchmark/base-gsm8k.json` | 20 条完整记录（prompt、输出、判定、是否正确）+ summary + `elapsed_seconds`，`limit: 20`、`seed: 0`、`decoding: greedy`、`max_new_tokens: 512`、`frozen_sha256: def2e3a0…c1d3` |
| `evidence/benchmark/base-ifeval.json` | 同上，`max_new_tokens: 640`、`frozen_sha256: 0cc0fb57…71e` |
| `evidence/benchmark/base-gsm8k.log` / `base-ifeval.log` | 两次运行的 stdout（含 `/usr/bin/time` 的 `WALL`） |

两条都 `unscorable=0`，即 40 条全部吐出了可判分的回答，没有一条因为抽不出数或空回答被排除；`accuracy` 的分母是条数，不是可判分数。

## 实测速度与预算重算

原报告按 30–60 token/s 估出"两套件 × base/adapter 约 1.5–3 小时"。这个估计被实测推翻，现在用实测值替换：

| 观测 | 条数 | 生成时间 | 单条 | 备注 |
| --- | --- | --- | --- | --- |
| GSM8K 单进程 probe | 10 | 246 s（`WALL 258.7 s` 含加载） | 24.6 s | 独占卡时 |
| GSM8K 与 IFEval 并行 | 20 | 536.9 s | 26.8 s | 两路同时跑，互相拖慢约 9% |
| IFEval 与 GSM8K 并行 | 20 | 569.9 s | 28.5 s | 输出更长（均 1423 字符 vs 1104） |

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
| adapter GSM8K / IFEval | **未跑** | 把上两条的 `--model base` 换成 `--model adapter`（默认读 `.tmp/sft/adapter-narrow`，41.7 MB，已在盘上），日志名相应换 |

跑 adapter 侧之前先确认 `.tmp/sft/adapter-narrow/` 还在：它在 `.tmp/` 下，按约定是可删的临时区，删了就只能重训。

**同一把尺子的要求：** base 与 adapter 必须同样的 `--limit`、同样的并行/串行方式。上面实测里 20 条是两路并行跑的（单条 26.8/28.5 s），若 adapter 改成独占串行，两者的耗时不可比——分数仍可比，时间不可比。建议 base 与 adapter 各自两路并行，保留这个差别。

## 判读方法：没观察到下降不等于没有下降

这一条是这份报告的边界，不是免责声明：

- 每格分数带 95% Wilson 区间。**两条区间重叠不等于"没有下降"**，只等于"这轮没测到下降"。n=20 时 Wilson 半宽约 18pp，10pp 的掉幅在这里基本看不见；要看见 10pp 需要每格 n≥150 左右。
- 判"掉"的正确读法是看**差值区间**，不是看两条单格区间是否重叠：差值 z 检验 `(p1−p2)/sqrt(p1(1−p1)/n1 + p2(1−p2)/n2)`，差值区间跨 0 就是没测到。
- 解码是贪心、单 seed，残余随机性只有数值实现差别，所以两次真跑之间的小抖动不构成"能力变化"的证据；反过来，贪心也意味着分数是这条固定路径上的一个点，不是分布的期望。
- IFEval 只覆盖 15 类指令（541 条中留 295 条），**不能与公开 IFEval 数比**，只能 base 对 adapter 自比。
- GSM8K 的判别力偏弱（见结论），SFT 只喂了 288 条长中文回答，若它损伤的是"回答方式"而非数学，GSM8K 掉不下来正是预期，不能反推"通用能力没掉"。

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
