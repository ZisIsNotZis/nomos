# 模型卡：nomos-narrow LoRA（Qwen3.5-2B 上的 SFT 适配器）

类型：产物。所有者：主代理。上游：[设计](method/design.md)、[训练报告](../report/sft-training.md)、[数据卡](data-card.md)。

一句话：这是把一个人（法条作者本人）的操作法压进 2B 权重的一次 SFT 适配器，学到的是「开始写工具行」，不是「决策选得更对」。

## 基座

| | 值 | 来源 |
| --- | --- | --- |
| 模型 | `Qwen/Qwen3.5-2B`，revision `15852e8c16360a2fea060d615a32b45270f8a8fc` | `evidence/qwen-base/run-meta.json` |
| 参数 | 2 213 241 664（2.21 B），bf16 | 同上 |
| 架构 | 混合注意力：24 层里 6 层是 `q/k/v/o` 全注意力，18 层是线性注意力（`linear_attn.in_proj_qkv/z/a/b`、`out_proj`） | `report/sft-training.md` |
| 许可 | **Apache-2.0**。核对方式：本机 HF 快照 `models--Qwen--Qwen3.5-2B/snapshots/15852e8c…/LICENSE` 是 Apache License 2.0 全文，同目录 `README.md` 头部写 `license: apache-2.0`、`base_model: Qwen/Qwen3.5-2B-Base` | 本地快照，非网络 |
| 类型标记 | HF 上 `pipeline_tag: image-text-to-text`（该系列是图文模型）；本项目只走纯文本路径 | 同上 |
| 训练时精度 | 4-bit nf4、double quant、bf16 compute（QLoRA） | `report/sft-training.md` |

## 适配器

| | 值 |
| --- | --- |
| 路径 | `.tmp/sft/adapter-narrow/`（`adapter_model.safetensors`、`adapter_config.json`、`README.md`） |
| 字节 | 43 675 104（41.7 MiB） |
| sha256 | `5be6a2f38752025930e6dbca80d3e0092bbfb905c731fbff2f275e1658176a72` |
| 形式 | LoRA，`r=16`、`alpha=32`、`dropout 0.05`、`task_type: CAUSAL_LM`、peft 0.21.2 |
| 目标模块 | `q_proj k_proj v_proj o_proj gate_proj up_proj down_proj`（`--lora-targets narrow`）：96 个模块、192 个张量 |
| 可训练参数 | 10 911 744（占基座 0.79%） |
| 训练 | 288 条训练 / 78 条验证，3 个 epoch、54 步、seed 0、lr 1e-4、有效 batch 16、828.6 秒（单卡 RTX 4090，与另一项目共用） |
| 法版本 | 训练 target 来自带 `AGENTS.md`（93 670 字符，sha256 `325f8b3e2d868f91fb43c24dd088ae6e735386c6d5e2aacfc7496d6ff2726ab6`）的 DeepSeek 回答；法条原文**不进** prompt |

登记在 [`artifacts.tsv`](../artifacts.tsv)：该文件超出 git 的实用尺寸，仓库里只有哈希与重生成命令，权重本体在 `.tmp/`，按约定可被删除。

### 怎么加载

适配器是标准 peft LoRA，叠在上面那个 revision 的基座上：

```python
from peft import PeftModel
from transformers import AutoModelForImageTextToText

base = AutoModelForImageTextToText.from_pretrained(
    "/home/z/hf/hub/models--Qwen--Qwen3.5-2B/snapshots/15852e8c16360a2fea060d615a32b45270f8a8fc"
)
model = PeftModel.from_pretrained(base, ".tmp/sft/adapter-narrow")
```

仓库里两条现成的入口都这么装：`scripts/measure_actions.py`（`ADAPTER = .tmp/sft/adapter-narrow`，`--generate` 生成三点测量）与 `scripts/run_bench.py --model adapter`（benchmark 的 adapter 侧）。两条入口的加载精度不同，读它们的数时要带上：`measure_actions.py` 是 bf16 全精度加载；`run_bench.py` 是 4-bit nf4（与训练同一套量化，base 与 adapter 都走它，所以两侧对比是同一把尺子）。

### 重生成

```
python3 scripts/train_sft.py --epochs 3 --grad-accum 8 --lora-r 16 --lora-alpha 32 \
  --lora-targets narrow --adapter-dir .tmp/sft/adapter-narrow
```

同一 GPU 上约 14 分钟。三个开关都要显式给：脚本默认 `--lora-targets wide`（还挂 18 层线性注意力的 5 个投影，见 [`report/sft-training-wide.md`](../report/sft-training-wide.md)），`--lora-r` / `--lora-alpha` 省略时按开跑前空闲显存选。

## 训练数据

366 条样本（训练 288 / 验证 78），来自 242 条真实处境、51 个会话（47 个会话组）。每条样本 = 处境原文作 prompt、带法 DeepSeek 回答作 target，只对 target 算 loss。覆盖 175 条可训练规则里的 77 条（下界，68 条处境没有规则标注）。细节、去重判据与丢弃计数：[数据卡](data-card.md)、[`report/sft-data.md`](../report/sft-data.md)。

## 结果（全部来自 `report/`，本卡不重算）

- 验证 PPL 11.34 → 6.03（loss 2.4285 → 1.7972），训练/验证 loss 差 0.36 且仍在扩大：跑通并学到回答形态，没有证明学会法。`report/sft-training.md`
- 回答里有可解析工具行的比例 5.6% → 75.2%（444 条对 444 条，不依赖参照物）。动作签名一致率 0.0023 → 0.0968（Δ 0.0946 [0.0586, 0.1351]，n_pairs = 148）。`report/sft-measurement.md`
- 提升的 65.3% 是交互项、5.3% 是决策项独立份额（[−0.0001, 0.0099]，跨 0）：不能说「写了动作之后选得更对」。同文件
- 文字层决策签名一致率 Δ −0.0473 [−0.1085, 0.0118]：不支持「决策变像了」，也不构成「变差了」。同文件
- 通用能力（配对）：GSM8K **n=100** 73.0% → 76.0%（+3.0pp，区间 [−6.0, +12.0] 跨 0）→ 没测到下降；**IFEval n=295 62.4% → 50.2%（−12.2pp，区间 [−17.6, −6.8] 不含 0，54 掉 / 18 涨，McNemar p = 2.57e-5）→ 测到下降**。这个 p 仍是未做多重比较校正的值，但它在 Bonferroni α = 0.025 下**过线**（余量约 970 倍），所以这一格不再是「未校正显著」。n=100 那一版的 −12.0pp [−22.0, −3.0]、p = 0.029 以及「两条差 2 与 5 个词的擦线翻正即 p = 0.064」降为前一次估计（`evidence/benchmark/n100/`）：n=295 上把那两条、甚至 7 条字数掉点全翻正，p 仍 <0.001。这不是第二次独立读数，是同一次读数把分母从 100 加到 295（前 100 条逐字节相同），所以两版之间的一致是算术，不是印证。掉点集中在句式与字数两条表层轴（最大单族 11 条 `no_comma`，其次 7 条 `number_words`）；「回答变短」是已测的背景位移（IFEval 词数中位数 185 → 130、188/295 条更短；GSM8K n=100 中位数 204.0 → 83.0、均值 210.2 → 95.1）但**不是掉点的判别式**：54 条掉点里只有 52% 变短，而两侧都对的 130 条里 68% 变短。n=295 的检出下限是 1.4–1.7pp，n=100 是 4–5pp。`report/sft-benchmark.md`
- **这一个负号不是我们那把尺子写出来的（参考实现复核）。** 用 Google 官方 `instruction_following_eval`（pin `e6890f85`）重算同一批 590 份落盘输出：strict **196/295 → 160/295、−12.2pp、[−17.6, −6.8]、55 掉 / 19 涨、p = 3.38e-5**，lax **−11.2pp [−16.9, −5.4]、p = 2.17e-4**。点估计与区间和本卡的 62.4% → 50.2% 一致到端点，换的只是 74 条不一致里哪几条（我们那把尺子 72 条）；两把尺子在 836 个指令槽上 56 个判得不一样，人读 11 条的结果是官方对 7、我们对 3。产物 `evidence/benchmark/official/official-ifeval.json`（6.5–11 s 纯 CPU，重跑逐字段相同）。`report/sft-benchmark.md`「参考实现的尺子」

## 已知限制

1. **单一用户、单一份法。** 训练 target 只反映一个人与一个代理协作的偏好（`docs/method/limits.md` 第 1–2 节）。法变了，本适配器不自动成立。
2. **单一模型尺寸。** 只有 2B；没有任何依据外推到 7B 或别的架构。
3. **窄版 LoRA 只覆盖部分层。** 18 层线性注意力的 5 个投影没挂 LoRA（这是该架构上「注意力投影」的边界）；宽版重跑验证 PPL 6.09 比窄版 6.03 差且第三轮反弹，所以窄版是选择而不是缺口。
4. **288 条训练样本、242 条处境。** 151 条处境只有一种决策；验证集 10 个会话组 78 条，PPL 差 0.03 在噪声量级。覆盖面 77/175 是下界。
5. **测量口径的边界。** 一致率只在 148/242 条处境上算（94 条参照物定不下来），不能外推全域；参照物是「带法 DeepSeek 的多数签名」，不是正确答案，所以一致率不是正确率。
6. **尺子量的是「离参照物多远」，不是「补上了几成法」。** 同协议下带法侧对它自己 0.3198 [0.2703, 0.3746]、不带法侧 0.2605 [0.2072, 0.3116]，差 0.0593 [0.0263, 0.0923] 不含 0（每处境每侧 9 条）——在这把尺子上「读了法」与「没读法」分得开，但绝对量级只有约 6 个百分点，且参照物自身只有 0.32 的自洽度。3 条抽样时同一条差是 0.0496 [−0.0068, 0.1059]、跨 0，那一份宽度是抽样噪声（区间宽按 1/√3 收缩）。文字层口径二在同批 99 条上仍然跨 0（0.0303 [−0.0180, 0.0819]）。
7. **benchmark 的分辨力：GSM8K 停在 n=100，IFEval 已到全量 n=295。** GSM8K 的 4–5pp 以下的掉幅看不见（200 条只跑了 100 条）；IFEval 现在能看见 1.4–1.7pp（295/295 条已跑尽）。两个套件各检验一次而没有做多重比较校正：IFEval 的 p=2.57e-5 在 Bonferroni α=0.025 下**过线**（余量约 970 倍），所以多重比较这一条现在不削弱结论、但它仍是结论的适用条件（每加一个套件、每换一个 seed 都要重算）。n=100 时那层「压在 2 个词上」的脆弱性（`ifeval-1072` 398/400、`ifeval-2844` 195/200 翻正即 p=0.064）现在只描述 `n100/` 那一版读数：n=295 上把这两条甚至 7 条字数掉点全翻正，p 仍 <0.001，要让 p 回到 0.025 门外得翻正 19 条。GSM8K 基座 73.0% 仍在判别带上沿之外，判别力偏弱。**绝对分取决用哪把尺子**：同一批输出在官方 strict 上是 66.4% → 54.2%、在本仓库那把上是 62.4% → 50.2%，差值区间两边相同，所以与公开 IFEval 数比只能用官方那一行；官方 grader 不钉 `langdetect` 种子时自己也不可复现（±1 条 = 0.34pp）。
8. **权重不在 git 里。** `.tmp/` 是可删的临时区，删了只能按上面的命令重训（约 14 分钟 GPU）。
9. **不构成通用对齐或安全产物。** 不防对抗性使用，不做多用户与权限，见 `docs/method/limits.md`。

## 许可与引用

- 适配器是 **Apache-2.0** 基座 `Qwen/Qwen3.5-2B`（revision `15852e8c16360a2fea060d615a32b45270f8a8fc`）的衍生权重，随基座继承 Apache-2.0 的义务：再分发时须带上许可文本、保留版权与署名声明、并标注改动。该 HF 快照里没有单独的 NOTICE 文件，所以没有额外的 NOTICE 义务可继承。基座许可的核对方式见本卡「基座」表的许可行：本机快照的 `LICENSE` 是 Apache License 2.0 全文，同目录 `README.md` 头部写 `license: apache-2.0`。
- 本仓库自身代码与文档的许可是 **AGPL-3.0-only**（作者 2026-10-21 指定，SPDX 标识符 `AGPL-3.0-only`，原文 <https://www.gnu.org/licenses/agpl-3.0.txt>）。两条并行不冲突：AGPL-3.0-only 覆盖本仓库的代码与文档，适配器权重随基座走 Apache-2.0，AGPL 不改变权重的许可。
