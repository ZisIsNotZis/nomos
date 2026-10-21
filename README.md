# nomos

把一份个人操作法（本工作区 `agent-policy` 仓库里的 `AGENTS.yaml`，264 个叶子节点）用 242 条真实处境里筛出的 288 条样本做 SFT 压进一个 2B 模型的权重，并测量它到底有没有进去、代价是不是通用能力。

## 结果一行

适配器学会了写工具行（5.6% → 75.2%），动作一致率 0.0023 → 0.0968，但提升的 65.3% 是交互项、决策项独立份额只有 5.3%（区间跨 0），文字层口径不支持「决策变像了」；通用能力没测到可信下降（n=20）。而参照物在同协议下自身只有 0.3311 的自洽度，所以这把尺量不出「补上了多少法条效果」。

## 一条命令

```
python3 scripts/measure_actions.py --analyse
```

在本机实测 **约 3.3 秒**（Python 3.12，纯 CPU、不碰 GPU、不联网、只用标准库；同一命令在一个全新 `git clone` 里同为约 3.3 秒）。计时条件与两次读数记在 [`docs/plan/plan.md`](docs/plan/plan.md) 的「发布准备」。它从仓库里已提交的证据重算主指标，并打印第一行：

```
n_pairs 148/242（覆盖率 0.612）；两侧都齐全 242/242；参照物可用 148 条；文字层参照物可用 169 条
```

后面跟完整的 `summary.json`（`base_mean` 0.0023、`post_mean` 0.0968、Δ 与按处境配对自举的区间、三个口径与格式/决策分解）。它会把 `evidence/measure/summary.json` 重写一遍：在本仓库里逐字节相同（跑完 `git status` 干净），唯一会变的字段是 `models.*` 的绝对路径，所以从别处 clone 出来跑会看到那里的路径。

需要重训或重新生成会要 GPU：`python3 scripts/train_sft.py --epochs 3 --lora-r 16 --lora-alpha 32 --lora-targets narrow`（单卡 4090 约 14 分钟），`python3 scripts/measure_actions.py --generate`（两个模型各 3 条抽样）。复现的完整说明在各报告里，见下。

## 不是什么

- 不是通用对齐研究，不涉及前沿模型：只有 2B、一个用户、一份法。
- 不是人类偏好标注的 RLHF：偏好对由政策推导。
- 不是「这份法比别的法好」：它是一名用户的操作法，测的是「更接近它」，不是「更正确」。
- 不是 benchmark 论文：外部套件只回答「有没有掉」，n=20，只看得见 ≳20pp。

## 限制

- 单一用户、单一份法、单一模型尺寸（2.21 B）；法变了，本适配器不自动成立。
- 288 条训练样本、242 条处境，151 条处境只有一种决策；覆盖 175 条可训练规则里的 77 条（下界）。
- 窄版 LoRA 只挂 `q/k/v/o`（6 层全注意力）与 MLP（24 层），18 层线性注意力的投影没挂——宽版重跑更差，所以这是选择不是缺口。
- 一致率只在 148/242 条处境上算（94 条参照物定不下来），不能外推全域；一致率是「像不像带法 DeepSeek」，不是正确率。
- 尺子本身量不出法的作用：同协议下带法 0.3311、不带法 0.2815，差 0.0496 [−0.0068, 0.1059] 跨 0。
- 权重不在 git 里（`.tmp/` 是可删临时区），只有 sha256 与重生成命令登记在 [`artifacts.tsv`](artifacts.tsv)。
- 完整清单：[`docs/method/limits.md`](docs/method/limits.md)、[模型卡](docs/model-card.md) 的「已知限制」。

## 许可

- 适配器是 `Qwen/Qwen3.5-2B` 的衍生权重，随基座继承 **Apache-2.0**（本机 HF 快照里的 `LICENSE` 与 `README.md` 头部的 `license: apache-2.0` 核对过）；再分发时基座的 LICENSE/NOTICE 义务一并带上。
- 随仓库分发的第三方数据：`data/bench/gsm8k.jsonl` 是 GSM8K（MIT），`data/bench/ifeval.jsonl` 是 IFEval（Apache-2.0）。许可原文落 `licenses/`，来源、引用、改动声明与冻结件 sha256 见 [THIRD-PARTY.md](THIRD-PARTY.md)。
- 处境与回答来自法条作者本人的私有会话（已脱敏，见[数据卡](docs/data-card.md)），DeepSeek 的回答受其服务条款约束。
- 本仓库自身的代码与文档**尚未声明许可**（作者未指定），因此当前不授予复用许可。这一条是待决项。

## 报告问题

<https://github.com/ZisIsNotZis/nomos/issues>。仓库的公开可见性未在本机验证，若打不开请直接联系作者。

## 读什么

| 路径 | 内容 |
|---|---|
| [模型卡](docs/model-card.md) | 基座与许可、适配器加载、结果摘要、已知限制 |
| [数据卡](docs/data-card.md) | 242 条处境的来源、双答与抽样生成、筛除、脱敏、能说什么 |
| [preprint 草稿](docs/paper/draft.md) | 主张、方法、数据、结果、限制、结论，每个数字指回报告 |
| [设计](docs/method/design.md) / [计划](docs/plan/plan.md) | 主张、刻度、数据、rubric、噪声、停止规则；六个工作包与验收 |
| [边界](docs/method/limits.md) | 法不覆盖什么、本研究不能声称什么 |
| [测量结果](report/sft-measurement.md) | 三点测量：三个口径、格式/决策分解、同协议锚点 |
| [训练](report/sft-training.md) / [宽版对照](report/sft-training-wide.md) | 4-bit QLoRA、PPL 11.34 → 6.03、显存与序列长度的实测 |
| [SFT 数据](report/sft-data.md) | 366 条样本怎么筛出来、切分、覆盖、限制 |
| [benchmark](report/sft-benchmark.md) | GSM8K 75.0% → 65.0%、IFEval 60.0% → 40.0%，n=20 |
| [数据质量](report/data-quality.md) / [rubric](report/rubric.md) | DPO 批次的筛除与覆盖；rubric 的分辨力（分不开两侧） |
| [法的冻结件](constitution/) | 264 个叶子、节点索引、分类判定、形状检查 |

## 目录

| 路径 | 内容 |
|---|---|
| `constitution/` | 冻结的法、节点索引、分类判定程序、形状检查 |
| `data/` | 处境、正负样本、SFT 样本（366/288/78）、规则覆盖标注、benchmark 冻结样本 |
| `docs/` | 模型卡、数据卡、方法、计划、论文草稿 |
| `eval/` | 四维 rubric 评测器与分辨力统计 |
| `evidence/` | 每次测量的原始输出与复算脚本（`evidence/measure/summary.json` 是主结果） |
| `mining/` | 从会话档案抽处境的脚本、脱敏门与计数 |
| `report/` | 结果汇总 |
| `scripts/` | 构建、训练、测量、benchmark 的可重跑脚本 |
