<p align="center"><img src="assets/logo.svg" alt="nomos" width="200"></p>

**简体中文** | [English](README.en.md)

# nomos

把一份个人操作法压进 2B 模型的权重，并量它到底进去没有、代价是不是通用能力。

**一份 264 个叶子的个人操作法（`AGENTS.yaml`），用 242 条真实处境筛出的 288 条样本 SFT 进一个 2.21 B 模型的权重；然后用同一把尺子量三件事——行为离这份法近了多少、这份接近在没见过的处境上还剩多少、通用能力（GSM8K、IFEval）为它付出了什么。** 这不是「让模型更聪明」，是把一个具体的人写下的规矩变成可测量的一次训练：法是可读的文本，训练是可重跑的脚本，结论是带区间与检出下限的读数，每一格都指回落盘的原始输出。

## 快速开始

```
git clone https://github.com/ZisIsNotZis/nomos.git
cd nomos
python3 scripts/measure_actions.py --analyse
```

纯 CPU、只用标准库、不联网、不碰 GPU。在本机实测 **3.17–3.33 秒**（9 次计时，Python 3.12.3、12 核；`/usr/bin/time -f '%e'`，含解释器启动；工作树与全新 `git clone` 都落在这一区间）。机器被别的作业压满时会更慢，那种条件下这条命令本轮没量过，所以这里只给实测过的区间，不给上界；逐次读数与环境记在 [`evidence/reports/plan-historical.md`](evidence/reports/plan-historical.md) 的「发布准备」。

它从仓库里已提交的证据重算主指标，并打印第一行：

```
n_pairs 148/242（覆盖率 0.612）；两侧都齐全 242/242；参照物可用 148 条；文字层参照物可用 169 条
```

后面跟完整的 `summary.json`（`base_mean` 0.0023、`post_mean` 0.0968、Δ 与按处境配对自举的区间、三个口径与格式/决策分解）。它会把 `evidence/measure/summary.json` 重写一遍：在本仓库里逐字节相同（跑完 `git status` 干净），唯一会变的字段是 `models.*` 的绝对路径，所以从别处 clone 出来跑会看到那里的路径。

需要重训或重新生成才要 GPU：`python3 scripts/train_sft.py --epochs 3 --grad-accum 8 --lora-r 16 --lora-alpha 32 --lora-targets narrow --adapter-dir .tmp/sft/adapter-narrow`（单卡 4090 约 14 分钟），`python3 scripts/measure_actions.py --generate`（两个模型各 3 条抽样）。复现的完整说明在 [`docs/9_IMPLEMENTATION.md`](docs/9_IMPLEMENTATION.md) 与各报告里。

## 结果（一行）

适配器学会了写工具行（5.6% → 75.2%），动作一致率 0.0023 → 0.0968（这 148 条处境**全部**来自造训练数据的同一批处境，拆开读：训练见过 113 条 Δ +0.1091 [0.0678, 0.1593]、按会话留出 35 条 Δ +0.0476 [0.0095, 0.0857]；留出侧的可解析工具行 6.7% → 80.0%，所以「写出工具行」迁移了，「选对动作」只迁移了四成多），但提升的 65.3% 是交互项、决策项独立份额只有 5.3%（区间跨 0），文字层口径不支持「决策变像了」；通用能力（配对）分两半：GSM8K **n=100**、+3.0pp、区间跨 0，没测到下降；**IFEval n=295、−12.2pp、区间 [−17.6, −6.8] 不含 0，测到下降**（184/295 → 148/295，54 掉 / 18 涨，McNemar p=2.57e-5；这个 p 是未做多重比较校正的值，而在 Bonferroni α=0.025 下它**过线**、余量约三个数量级。n=100 那一版压在两条只差 2 与 5 个词的「至少 N 词」上、翻正即 p=0.064，那条敏感性现在只属于 n=100；n=295 上把这两条、甚至 7 条字数掉点全翻正，仍然 p<0.001；要让 p 回到 0.025 门外得在 54 条掉点里翻正 19 条，而最大的单族（11 条逗号禁令）够不到这个数。掉点逐条读下来落在句式与字数两条表层轴上（就是那 11 条逗号禁令，其次 7 条字数下限），**不是「回答变短」单独能解释的**：变短在 63.7% 的题上都发生，而 54 条掉点里只有 52% 变短；词数中位数 IFEval 185 → 130；检出下限 1.7pp；n=295 不是第二次独立读数，是同一次读数把分母从 100 加到 295——前 100 条与 n=100 那轮逐字节相同，所以两版之间的一致是算术，不是印证）。同协议下带法 0.3198、不带法 0.2605，差 0.0593 [0.0263, 0.0923] 不含 0（每处境每侧 9 条），所以这把尺分得开「读了法」与「没读法」；但参照物在同一套解码下对它自己只有 0.3198 的自洽度，所以 0.0968 只能读成「离这个具体参照物多远」，不是「补上了几成法条效果」。IFEval 那一格用 Google 官方 grader（pin `e6890f85`）重算同一批 590 份输出仍是 **196/295 → 160/295、−12.2pp、[−17.6, −6.8]、55 掉 / 19 涨、p=3.38e-5**（lax −11.2pp、p=2.17e-4），所以那个负号不是我们自己那把尺子的产物；两把尺子在逐条上确实分得开（836 个指令槽里 56 个判得不一样，11 条人读下来官方对 7 条、我们对 3 条、1 条口径问题），但换尺子只换 74 条不一致里的哪几条，没换结论。

2-epoch 试件（M6，预登记试验）把 IFEval 的掉幅从 −12.2pp 收到 **−7.8pp [−13.2, −2.7]**（第三个 epoch 至少解释 4.4pp），政策主指标两个适配器直接配对差 **−0.0023 [−0.0338, +0.0270]**、分不开；换不换交付物是 person 的判定（Q11），在此之前落盘的仍是 3-epoch 那一份。

## 现在能做什么

- **重算主指标**：`scripts/measure_actions.py --analyse` 只读落盘回答，纯 CPU、3.17–3.33 s，重写 `evidence/measure/summary.json` 并打印头行。
- **分成「训练见过 / 按会话留出」两半**：`scripts/measure_split.py`，同一套重采样代码与种子，断言 `paired_all` 与 `summary.json` 头行逐字段相等。
- **重训窄版 LoRA**：`scripts/train_sft.py`（4-bit QLoRA，`q/k/v/o` + MLP，96 个模块、可训练参数占基座 0.79%）。
- **重生成政策轴抽样**：`scripts/measure_actions.py --generate`（base / post / 匹配锚点共用同一 prompt 与同一解码，可续跑、跳过已落盘的键）。
- **跑通用能力两格并配对**：`scripts/run_bench.py --suite {gsm8k,ifeval} --model {base,adapter}` + `evidence/benchmark/analyse_paired.py`（按条目配对，不按整轮比）。
- **交参考实现复核**：`evidence/benchmark/official/grade_official.py`，用 vendored 的 Google `instruction_following_eval` 重算同一批输出。
- **自检与门**：五个离线检查（见「如何开发」），其中 `scripts/check_axes_claim.py` 只读发布面，逐句检查「没测的轴有没有被当已测讲」。
- **抽新处境**：`mining/scan.py` 从会话档案抽最小片段，`mining/check_redaction.py` 是脱敏门。
- **冻结的法**：`constitution/` 里 264 个叶子、节点索引、分类判定程序、形状检查与冲突审计（`verify_gate.py` 跑五个 fixture）。

## 架构

一条数据流，五个子系统：法被冻结、处境被抽出、配对与 SFT 样本成型、模型被训练、两条轴各量一遍，全部产物带脚本一起落进 `evidence/`，所以每个数字都能从落盘记录重算。分析与训练**不共享代码**：训练是 transformers + PEFT，测量只读落盘回答——共享只会把 GPU 依赖带进分析。

```
constitution/（冻结的法）    mining/ + evidence/densify/（处境与双答）
        │                              │
        └──────────────┬───────────────┘
                       ▼
              data/（配对、覆盖、SFT 样本 366/288/78）
                       ▼
              scripts/train_sft.py ──► .tmp/sft/adapter-*（权重，不入库）
                       ▼
   ┌───────────────────┴────────────────────┐
   ▼                                        ▼
scripts/measure_actions.py            scripts/run_bench.py
（政策轴：base / post / 匹配锚点）      （通用轴：GSM8K / IFEval，base / adapter 四格）
   ▼                                        ▼
evidence/measure/                     evidence/benchmark/
   │                                        │
   └──────────► evidence/reports/（推导与逐条明细）◄── evidence/benchmark/official/（官方 grader 复核）
```

- **比较只在同一冻结前缀上进行**：`limit`、`seed`、`frozen_sha256`、`decoding` 四项任一不同，`analyse_paired.py` 直接拒绝。
- **试验件不得覆盖落盘件**：新跑用 `--tag` / `--adapter-tag` / `--out-tag` 另开输出名；`evidence/measure/summary.json`、`evidence/benchmark/paired-*.json` 是冻结的交付证据。
- **判分代码只有一处**：`scripts/bench_suites.py` 的检查器是仓库自己的尺子；`per_instruction` 只是记录层，不作为统计来源。
- **单点事实**：当前数值只在 [`docs/2_GOAL.md`](docs/2_GOAL.md)，主张与边界只在 [`docs/5_PRODUCT.md`](docs/5_PRODUCT.md)，推导与明细在 `evidence/reports/`。

## 不是什么

- 不是通用对齐研究，不涉及前沿模型：只有 2B、一个用户、一份法。
- 不是人类偏好标注的 RLHF：偏好对由政策推导。
- 不是「这份法比别的法好」：它是一名用户的操作法，测的是「更接近它」，不是「更正确」。
- 不是 benchmark 论文：外部套件只回答「有没有掉」，GSM8K n=100（检出下限 4–5pp）、IFEval n=295（检出下限 1.4–1.7pp），且只有这两条轴，`agentic` 那一条未测。

## 限制

- 单一用户、单一份法、单一模型尺寸（2.21 B）；法变了，本适配器不自动成立。
- 288 条训练样本、242 条处境，151 条处境只有一种决策；覆盖 175 条可训练规则里的 77 条（下界）。
- 窄版 LoRA 只挂 `q/k/v/o`（6 层全注意力）与 MLP（24 层），18 层线性注意力的投影没挂——宽版重跑更差，所以这是选择不是缺口。
- 一致率只在 148/242 条处境上算（94 条参照物定不下来），不能外推全域；一致率是「像不像带法 DeepSeek」，不是正确率。
- IFEval 那一格与公开数值不可比：抽样是 541 条里的 295 条，而且同一批输出的分数取决用哪把尺子——官方 strict 是 66.4% → 54.2%，本仓库那把是 62.4% → 50.2%，差值的区间两边一样。官方 grader 不钉 `langdetect` 种子时自己也不可复现（±1 条）。
- 尺子量的是「离参照物多远」而不是「补上了几成法」：同协议下带法 0.3198、不带法 0.2605，差 0.0593 [0.0263, 0.0923] 不含 0（每处境每侧 9 条）；3 条时同一条差是 0.0496 [−0.0068, 0.1059]、跨 0，那份宽度是抽样噪声（区间宽按 1/√3 收缩）。参照物自身只有 0.32 的自洽度，文字层口径二仍跨 0（0.0303 [−0.0180, 0.0819]）。
- 权重不在 git 里（`.tmp/` 是可删临时区），只有 sha256 与重生成命令登记在 [`artifacts.tsv`](artifacts.tsv)。
- 完整清单：[`docs/5_PRODUCT.md`](docs/5_PRODUCT.md) 的「边界」、[模型卡](card/model-card.md) 的「已知限制」。

## 如何开发

分析侧只要 Python 3.12.3 与标准库，无需安装任何东西。训练与生成要 GPU：单卡 RTX 4090（24 GiB），torch 2.14.1+cu130、transformers 5.20.1、peft 0.21.2、bitsandbytes 0.50.2，基座是本机 HF 快照里的 `Qwen/Qwen3.5-2B`（revision `15852e8c…`，见[模型卡](card/model-card.md)）。环境细节在 [`docs/9_IMPLEMENTATION.md`](docs/9_IMPLEMENTATION.md)。

不碰 GPU 的检查（每个都以非零退出码报失败）：

| 检查 | 覆盖什么 |
| --- | --- |
| `python3 scripts/measure_actions.py --check` | 自举区间、X、格式/决策分解在假数据上的取值 |
| `python3 scripts/measure_split.py --check` | 见过/留出拆分与落盘件逐字段相同 |
| `python3 scripts/bench_selftest.py` | 套件判分器：手算样例、gold/wrong/garbage 三条 stub 通道、空输出记 `unscorable` |
| `python3 scripts/check_axes_claim.py` | 发布面：每一句提到未测轴的话都写明它没测 |
| `python3 constitution/verify_gate.py` | 分类判定程序的五个 fixture |

仓库没有配置 linter 或 formatter（`python3 -m py_compile` 是唯一的语法门）。跑分析会重写 `evidence/measure/summary.json`，在本仓库里逐字节相同；`evidence/measure/anchor-draws9/run.log` 与 `evidence/benchmark/logs-*/driver.*` 在跑的时候会追加，是允许出现在 `git status` 里的路径。

## 如何贡献

见 [`CONTRIBUTING.md`](CONTRIBUTING.md)：能复现的数才是数，改动要带证据指针，长跑走 detached driver。

## 路线图

**已落地**：M1（匹配锚点每处境每侧 9 条，带法减不带法不含 0）、M2（通用能力四格补到 n=100）、M3（IFEval 加宽到 n=295）、M4（官方 grader 复核 590 份输出）、M5（§1 收窄到实测的两轴，`agentic` 移出主张并写明未测）、M6（2-epoch 预登记试验 + 全量政策测量）；工作包 WP-2（一条命令的耗时改成 9 次实测区间）、WP-4（新读数同步进引用面）、WP-5（官方 grader 复核，即 M4）、WP-6（见过/留出拆分）都已收口。细节、判据、花费与每条「被什么推翻」都在 [`docs/0_ROADMAP.md`](docs/0_ROADMAP.md)。

**未落地**：Q11（换不换交付物——2-epoch 替代 3-epoch，在 person 手里）、WP-3（`constitution/lock.yaml` 的 `upstream:` 指向一个已不存在的路径，等下一个碰到该文件的改动一起修）、Q6（`per_instruction` 同名指令覆盖，等下一次改落盘格式）。

**未来方向**：最弱的两个地方是已知的——参照物只有 0.32 的自洽度，所以尺子现在只能回答「离这个参照物多远」；`agentic` 那条轴未测，而且这一轮不买（BFCL 要 HF 可达 + 上千行 harness，两个依赖在本机都不成立）。修前者要把参照物换成能分辨的形式，修后者要先解依赖再谈跑；在解法落地之前，主张只会继续按实测的两轴写。DPO 是备选而非主线，退回它的理由与「什么条件下值得再回来」记在 `docs/0_ROADMAP.md` 的 backlog。

## 许可

- 适配器是 `Qwen/Qwen3.5-2B` 的衍生权重，随基座继承 **Apache-2.0**（本机 HF 快照里的 `LICENSE` 与 `README.md` 头部的 `license: apache-2.0` 核对过）；再分发时基座的 LICENSE/NOTICE 义务一并带上。
- 随仓库分发的第三方数据：`data/bench/gsm8k.jsonl` 是 GSM8K（MIT），`data/bench/ifeval.jsonl` 是 IFEval（Apache-2.0）。许可原文落 `licenses/`，来源、引用、改动声明与冻结件 sha256 见 [THIRD-PARTY.md](THIRD-PARTY.md)。
- 处境与回答来自法条作者本人的私有会话（已脱敏，见[数据卡](card/data-card.md)），DeepSeek 的回答受其服务条款约束。
- 本仓库自身的代码与文档许可是 **AGPL-3.0-only**（作者 2026-10-21 指定，SPDX 标识符 `AGPL-3.0-only`），原文 <https://www.gnu.org/licenses/agpl-3.0.txt>，本仓库副本 [`licenses/AGPL-3.0.txt`](licenses/AGPL-3.0.txt)（34523 字节，sha256 `0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0`，2026-10-21 取回，未改一字）；复用、修改、再分发按该许可的条款。适配器权重不在这一条里：它是 `Qwen/Qwen3.5-2B` 的衍生权重，随基座走 **Apache-2.0**（上一条与[模型卡](card/model-card.md)「许可与引用」）。

## 报告问题

<https://github.com/ZisIsNotZis/nomos/issues>。仓库公开可读：2026-10-21 在本机匿名（不带任何凭据）跑 `curl -sI https://github.com/ZisIsNotZis/nomos | head -1`，返回 `HTTP/2 200`；私有或不存在的仓库在这条命令下返回 404。若打不开请直接联系作者。

## 读什么

| 路径 | 内容 |
|---|---|
| [问题](docs/1_PROBLEM.md) / [目标](docs/2_GOAL.md) | 为什么做；验收线与当前读数（数值只在这一处） |
| [需求](docs/3_REQUIREMENT.md) / [用例](docs/4_USECASE.md) | 功能、非功能、约束；五种使用流程与验收 |
| [产品](docs/5_PRODUCT.md) | 主张、边界、判定树、要 person 判的那一件事 |
| [架构](docs/6_ARCHITECTURE.md) / [接口](docs/7_INTERFACE.md) | 子系统与质量手段；数据格式与命令行契约 |
| [细节](docs/8_DETAIL.md) / [实施](docs/9_IMPLEMENTATION.md) | 算法与判据；环境、命令、测试、记账、仓库布局 |
| [路线图](docs/0_ROADMAP.md) | 里程碑 M1–M6、工作包、闸与开销 |
| [模型卡](card/model-card.md) | 基座与许可、适配器加载、结果摘要、已知限制 |
| [数据卡](card/data-card.md) | 242 条处境的来源、双答与抽样生成、筛除、脱敏、能说什么 |
| [preprint 草稿](paper/draft.md) | 主张、方法、数据、结果、限制、结论，每个数字指回证据 |
| [测量结果](evidence/reports/sft-measurement.md) | 三点测量：三个口径、格式/决策分解、同协议锚点、见过/留出、2-epoch |
| [训练](evidence/reports/sft-training.md) / [宽版对照](evidence/reports/sft-training-wide.md) | 4-bit QLoRA、PPL 11.34 → 6.03、显存与序列长度的实测 |
| [SFT 数据](evidence/reports/sft-data.md) | 366 条样本怎么筛出来、切分、覆盖、限制 |
| [benchmark](evidence/reports/sft-benchmark.md) | GSM8K 73.0% → 76.0%（+3.0pp，跨 0，n=100）、**IFEval 62.4% → 50.2%（−12.2pp，[−17.6, −6.8]，n=295）**；p=2.57e-5（Bonferroni α=0.025 下过线）；**Google 官方 grader 重算同一批 590 份输出：strict 66.4% → 54.2%（−12.2pp，[−17.6, −6.8]，p=3.38e-5）、lax −11.2pp**，结论不换；前一次估计：n=100 时 IFEval −12.0pp [−22.0, −3.0]、19 掉/7 涨、p=0.029 |
| [数据质量](evidence/reports/data-quality.md) / [rubric](evidence/reports/rubric.md) | DPO 批次的筛除与覆盖；rubric 的分辨力（分不开两侧） |
| [法的冻结件](constitution/) | 264 个叶子、节点索引、分类判定、形状检查与冲突审计 |

## 目录

| 路径 | 内容 |
|---|---|
| `constitution/` | 冻结的法、节点索引、分类判定程序、形状检查 |
| `data/` | 处境、正负样本、SFT 样本（366/288/78）、规则覆盖标注、benchmark 冻结样本 |
| `docs/` | 知识库：`0_STAGING`、`0_ROADMAP`、`1_PROBLEM` … `9_IMPLEMENTATION` |
| `card/`、`paper/` | 模型卡与数据卡；preprint 草稿 |
| `mail/` | 与 root / person 的往来信原件（授权的原话在这里） |
| `eval/` | 四维 rubric 评测器与分辨力统计 |
| `evidence/` | 每次测量的原始输出与复算脚本（`evidence/measure/summary.json` 是主结果） |
| `mining/` | 从会话档案抽处境的脚本、脱敏门与计数 |
| `evidence/reports/` | 推导与逐条明细（证明，不是层文档） |
| `scripts/` | 构建、训练、测量、benchmark 的可重跑脚本 |
| `assets/` | logo |
| `licenses/`、`THIRD-PARTY.md` | 许可原文与第三方声明 |
| `artifacts.tsv` | 权重 sha256 与重生成命令（权重不进 git） |
