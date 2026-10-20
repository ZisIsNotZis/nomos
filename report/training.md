# DPO 训练：跑通了，但没有学会偏好

类型：结果。所有者：主代理。上游：[计划](../docs/plan/plan.md) 第四、五步。数据：`data/pairs-stable-v2.jsonl`（91 对）。

## 结论

QLoRA DPO 在 Qwen3.5-2B 上跑完 76 步，loss 全程有限、LoRA 梯度确实接在计算图上，但**这一版没有把偏好学进去**：留出集上 chosen 与 rejected 的隐式准确率 0.444（18 对里 8 对 chosen 得分更高），训练前后都低于 0.5；训练集上 margin 改善了 1.17 nat，留出集上反而退化了 0.10 nat，这是在小样本上记住了 direction 之外的噪声，不是学到偏好。按 [计划](../docs/plan/plan.md) 第五步的验收"证明的是数学上跑通了，不是学会了"，**数学跑通这一条成立，学会这一条不成立**。

按 [设计](../docs/method/design.md) 第 7 节的停止规则，训练本来被评委尺子分不开两个已知水平挡住；这次是硬预算内的可行性验证，不是"DPO 能让法进权重"的证据。

## 硬件与内存

| 项 | 数值 | 来源 |
| --- | --- | --- |
| GPU | NVIDIA GeForce RTX 4090，24564 MiB | `evidence/training/log.jsonl` `setup.gpu_name` |
| 启动时可用显存 | 20.84 GiB（另一项目 pathlm 常驻，另有桌面进程） | `setup.gpu_free_gib_at_start` |
| 本次训练峰值（allocated / reserved） | 12.80 / 16.53 GiB | `peak_memory` |
| 墙钟 | 384.8 s / 76 步 | `peak_memory.wall_clock_s` |
| 环境 | torch 2.14.1+cu130，transformers 5.20.1，peft 0.21.2，bitsandbytes 0.50.2 | `setup.hf` |

一次性 OOM 观察：`evidence/training/train.log` 里有 `memory allocation failed ... trying to allocate 4840226816 bytes (free: 4548853760)`，当时另一项目占着显存，PyTorch 分配器回收后重试成功，76 步全部跑完。所以峰值 12.80 GiB 是成功的峰值，不是"刚好卡住"的峰值。

装了 `bitsandbytes` 0.50.2、`peft` 0.21.2（连带 `accelerate` 1.15.0、`psutil` 7.2.2），**没装 `trl`**，DPO loss 手写：`-logsigmoid(beta * ((logπ_c - logπ_ref_c) - (logπ_r - logπ_ref_r)))`，见 `scripts/train_dpo.py` 的 `dpo_step`。

## 序列长度：从数据量出来，不是默认值

| 分量 | p50 | p95 | max |
| --- | --- | --- | --- |
| prompt（excerpt） | 494 | 874 | 930 |
| chosen | 116 | 187 | 347 |
| rejected | 122 | 187 | 354 |
| prompt + max(chosen, rejected) | 631 | 1031 | 1205 |

最长一对 1205 token，向上取到 128 的整数倍得 **`max_length = 1280`**，没有任何一对被截断；理由写在 `log.jsonl` `setup.max_length_reason`。

## Prompt 里没有法条

`assert_prompts_clean` 在加载数据时逐条检查，任何一条命中就抛 `AssertionError` 并中止，不会降级放过：

- 11 条句子级法条片段（"Each node here is a law"、"Reasoning is the scarcest budget" 等，清单见 `log.jsonl` `setup.law_phrases_checked`）在 91 条 excerpt 里命中 0 次。片段只取句子长度，因为 `SSOT`、`projection` 这类词在本用户自己的轮次里是正常词汇，拿它当判据会误报（实测 1 条 excerpt 含 "Single source of truth"，是用户自己在说话）。
- `chosen != rejected`，两侧都非空，且两侧的 prompt token 序列逐 token 相同（`encode_pair` 里断言前缀一致）。

**能断言的与不能断言的**：上述检查排除的是"prompt 里夹带法条"，以及"同一对的两条回答来自两个不同 prompt"。它**不能**从文件本身证明 chosen/rejected 没有被调换——`data/pairs-stable-v2.jsonl` 里没有逐条的方向性证据，能追到的只有 `signatures` 与 `cross_condition_differs`，而 91 对里有 39 对两侧动作签名都为空、跨条件相同（`report/stable-pairs.md` 记过：这批对子本身没有偏好信号）。这批 39 对仍进了训练，是这一版的已知缺陷。

## 超参

| 项 | 值 | 理由 |
| --- | --- | --- |
| 量化 | 4-bit NF4，double quant，bf16 compute | 24 GB 卡上还有别的项目，2B 权重占 1.79 GiB |
| LoRA | r=16，alpha=32，dropout 0.05，q/k/v/o/gate/up/down 七个投影 | 注意力与 MLP 全覆盖；可训练 10.91 M / 1 374 M = 0.79% |
| beta | 0.1 | DPO 常规值；但本数据每对 logp 差约 10–17 nat，乘 beta 后仍在 logsigmoid 的饱和区外沿 |
| lr | 5e-5 | **事后看偏高**：每对 margin 幅度 10²，训练 loss 从首 8 步均值 0.800 升到末 8 步 2.268，单步最高 7.029 |
| 优化器 | paged AdamW 8-bit | 省显存，无额外依赖 |
| 每步对数 | 4 对（2 对一次前向，梯度累积 2） | 显存换时间：一次前向 4 条序列时 fp32 softmax 显存爆过 |
| epochs | 4 → 76 个优化步 | 73 对训练、每步 4 对，共 4×19 步 |
| 划分 | 按会话留出 18 对（9 个会话，31 个会话里剩 22 个训练） | 同一会话绝不同时出现在两侧，`session_split` 里断言 |
| 种子 | 0 | `--seed` |

## Loss 与 margin 曲线

逐步数据全在 `evidence/training/log.jsonl`（76 条 `step`、9 条 `val`）。抽样如下：

| step | lr | train loss | train margin | train acc |
| --- | --- | --- | --- | --- |
| 1 | 2.0e-5 | 0.693 | −35.93 | 0.50 |
| 8 | 4.79e-5 | 1.174 | −283.47 | 0.00 |
| 16 | 4.23e-5 | 1.736 | −145.76 | 0.25 |
| 24 | 3.66e-5 | 3.295 | 156.29 | 0.75 |
| 32 | 3.10e-5 | 1.709 | −50.28 | 0.50 |
| 40 | 2.54e-5 | 3.006 | −99.02 | 0.00 |
| 48 | 1.97e-5 | 1.926 | −182.37 | 0.00 |
| 56 | 1.41e-5 | 4.804 | −115.94 | 0.25 |
| 64 | 8.45e-6 | 2.435 | −75.46 | 0.25 |
| 72 | 2.82e-6 | 7.029 | −190.46 | 0.00 |

整段 loss 在 0.008–7.029 之间抖动，没有下降趋势；这是"每对 margin 幅度 10² × lr 5e-5"的直接结果，不是数值故障（全部有限）。

留出集的整集 DPO loss 与 margin（每 8 步一次）：

| step | val DPO loss | val margin | val acc | val reward margin |
| --- | --- | --- | --- | --- |
| 8 | 0.776 | −15.90 | 0.444 | −0.141 |
| 24 | 0.791 | −15.93 | 0.444 | −0.144 |
| 40 | 0.745 | −15.21 | 0.444 | −0.072 |
| 56 | 0.724 | −14.88 | 0.444 | −0.039 |
| 76 | 0.708 | −14.59 | 0.444 | −0.010 |

留出集 DPO loss 缓慢降到 0.708、reward margin 从 −0.141 收拢到 −0.010，但**原始 margin 一直是负的**（chosen 仍比 rejected 低约 14.6 nat），隐式准确率固定 0.444。

## 训练前的基线：base 模型本来就偏好 rejected

`train 与 val 的 final_eval`（`log.jsonl` `final_eval.*.pairs` 里逐对保存了 policy 与 reference 的 logp）：

| 集合 | 对子数 | reference 偏好 chosen | 训练后偏好 chosen | 平均 Δlogp(chosen) | 平均 Δlogp(rejected) |
| --- | --- | --- | --- | --- | --- |
| 训练 | 73 | 35（48%） | 38（52%） | +0.708 | −0.466 |
| 留出 | 18 | 8（44%） | 8（44%） | +0.669 | +0.765 |

两侧语言不是系统偏置：chosen 以中文为主的 31/91，rejected 34/91，方向不成片。

**这张表是"记住而非学会"的证据**：训练集 margin 改善 ≈ +1.17 nat，留出集 ≈ −0.10 nat，方向相反；同时两侧的 Δlogp 都在涨（训练集 chosen +0.71、留出集两侧各 +0.67 / +0.77），也就是适配器主要在整体提高这批文本的似然，没有把 chosen 抬到 rejected 之上。

## PPL 训练前后（留出 18 对）

定义：`exp(总 completion NLL / 总 completion token)`，prompt 与 completion 的编码与训练完全一致，脚本 `scripts/eval_ppl.py`，落 `evidence/training/ppl.json`。

| 侧 | 训练前 PPL | 训练后 PPL | 差 |
| --- | --- | --- | --- |
| chosen | 11.222 | 11.174 | −0.047 |
| rejected | 9.325 | 9.288 | −0.037 |

两侧同幅度下降 ≈0.4%，两侧差距没有被拉开（训练前 1.90，训练后 1.89）。与上表一致：适配器动的是文本整体似然，不是两侧的相对排序。

## 梯度确实接在图上

`train.log` 里有 `UserWarning: None of the inputs have requires_grad=True` ——那是 reference 前向在 `torch.no_grad()` 下走 gradient checkpointing 的正常产物，不是适配器脱图。为了不靠推断，`scripts/train_dpo.py` 在第 1 步 backward 之后自己断言并记录：

```json
{"type": "grad_check", "step": 1, "lora_params": 192, "lora_params_with_grad": 192,
 "lora_params_nonzero_grad": 96, "lora_grad_norm": 14.3524}
```

（`evidence/training/smoke/log.jsonl`，`--limit 4 --epochs 1` 的小跑，走的是同一段代码。）192 个 LoRA 张量全部拿到 `.grad`，96 个非零：非零的正是 `lora_B`，`lora_A` 在初值处梯度为零（`B=0` 的标准 LoRA 初始化），反向传播一到第二步就会两边都非零。断言不成立时脚本抛 `AssertionError` 中止。

## 复现

```bash
pip install bitsandbytes peft
python3 scripts/train_dpo.py --epochs 4 --pairs-per-step 4 --micro-pairs 2 --eval-every 8
python3 scripts/eval_ppl.py
```

产物：适配器落 `evidence/training/adapter/`（本次已挪到 `.tmp/training/adapter-dpo-r16/` 并记入 `artifacts.tsv`，42 MB 不进 git）：

- `adapter_model.safetensors`，43 675 104 B，sha256 `bfe5dc07841b16abcc3d233087e612657bccb764ebc3fdf471c0b521bd5c0a18`
- 校验：`sha256sum -c <(awk -F'\t' 'NR>2{print $3"  "$1}' artifacts.tsv)`

日志：`evidence/training/log.jsonl`（训练）、`ppl.json`（PPL）、`train-summary.json`（终值）、`train.log`（stdout）、`eval_ppl.log`、`smoke/log.jsonl`（梯度断言）。

## 局限

1. **76 步、73 对**：这个规模只能回答"管道通不通"。偏好没学到，lr 5e-5 对每对 10² 量级的 margin 偏高，下一步该先扫 lr（1e-5 / 2e-5）与 beta，再谈学没学会。
2. **39 对没有动作差信号**：两侧签名都空、跨条件相同，它们只教"这批文本像什么"。
3. **chosen/rejected 是否被调换无法从文件证明**，只能证明 prompt 同源、两侧不同（见上）。
4. **本模型的 hybrid 线性注意力走的是参考实现**（`chunk_gated_delta_rule` 缺 `flash-linear-attention`），所以 384.8 s / 76 步是偏慢的上界；装 `flash-linear-attention` 与 `causal_conv1d` 会更快，未验证提速幅度。
5. **base 模型本身偏好 rejected 侧**（留出集 44% 偏好 chosen），意味着这对子里有相当一部分方向与模型先验相反，小步数下推进更慢。
6. 单次运行、单一种子，没有置信区间；`log.jsonl` 里的 per-step loss 是 4 对的微批均值，抖动量级大于任何趋势。
