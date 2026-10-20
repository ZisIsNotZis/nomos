# SFT 训练：Qwen3.5-2B 4-bit QLoRA，验证 PPL 11.34 → 6.03

## 结论

288 条训练样本、3 个 epoch、54 步，验证集 PPL 从 11.34 降到 6.03（loss 2.4285 → 1.7972），训练集 PPL 4.21，训练/验证 loss 差 0.36 且仍在扩大——学到了数据里的回答形态，没有过拟合到掉头的程度，也没有证明学会了法。

适配器（窄目标版）：`.tmp/sft/adapter-narrow/adapter_model.safetensors`，43675104 字节，sha256 `5be6a2f38752025930e6dbca80d3e0092bbfb905c731fbff2f275e1658176a72`，已登记进 `artifacts.tsv`。

全部数字由 `python3 scripts/train_sft.py --epochs 3 --grad-accum 8` 落在 `evidence/sft/log.jsonl`，本文件只引用那 66 行记录，不重算。

## 配置与理由

| | 值 | 理由 |
| --- | --- | --- |
| 基座 | Qwen3.5-2B，4-bit nf4、double quant、bf16 compute | 计划要求 4-bit QLoRA |
| LoRA 目标 | `--lora-targets narrow` = `q_proj k_proj v_proj o_proj gate_proj up_proj down_proj` | 注意力与 MLP 的投影层，与仓库里 `train_dpo.py` 同一组；默认值是 `wide`，本版必须显式传 `narrow` |
| r / alpha | 16 / 32 | 加载前卡上剩 13.5 GiB，r=16 是 10 911 744 个可训练参数（0.79%），alpha=2r 沿用同卡上 r=16 的 DPO 跑法 |
| micro-batch × 梯度累积 | 2 × 8（有效 16） | 见下面显存一节：单样本 logits + 梯度约 2.2 GiB |
| 优化器 / lr | paged_adamw_8bit / 1e-4，暖机 5 步后线性衰减 | 288 条的小样本，1e-4 是 QLoRA 的常用档 |
| 种子 | 0（torch / numpy / random 同时固定） | 计划要求固定种子 |
| 步数 | 18 步/epoch × 3 = 54 步 | 288 / 16 = 18 |

注意这个基座是混合架构：24 层里只有每 4 层一层是 `q/k/v/o` 全注意力（共 6 层），另外 18 层是线性注意力（`linear_attn.in_proj_qkv`、`in_proj_z`、`in_proj_a`、`in_proj_b`、`out_proj`）。所以适配器里 192 个张量 = MLP 三类 × 24 层 + `q/k/v/o` × 6 层。线性注意力那几层的投影没有挂 LoRA，这是「注意力投影」在这个架构上的边界，不是漏配；挂上它们重跑的结果见 `report/sft-training-wide.md`——验证 PPL 6.0923 比这里的 6.0325 差，且宽版第三轮反弹（6.0847 → 6.0923），所以后续测量（含 `scripts/measure_actions.py`）用这一版窄版适配器。

## 显存：batch 与 rank 是怎么定的

开跑前 `nvidia-smi` 显示卡上已占 9.1 GiB（另一个项目的 llama-server 与 python 进程），`torch.cuda.mem_get_info` 报剩 13.5 GiB。真正的约束不是权重（4-bit 加载后 1.77 GiB）而是输出：这个模型即使 bf16 compute 也吐 **float32 logits**，一条 1088 token 样本是 `[1, 1088, 248320]` float32 = 1.08 GiB，反向还要同尺寸梯度，单样本约 2.2 GiB。micro-batch 2 时峰值分配 8.74 GiB、峰值保留 9.98 GiB，给同卡另一个项目留了 3 GiB 以上；micro-batch 3 时保留量到 13.1 GiB，贴着剩余量，所以取 2。

同一条原因也决定了 loss 的写法：整批 `[batch, seq, 248320]` 直接过 `cross_entropy` 时，框架要把整个 logits 升成 float32 再算 softmax，一次分配就要 7.77 GiB，第一次冒烟就这么 OOM 了。现在 `target_loss()` 只对有标签的位置按 128 行分块做 softmax，峰值不再随 batch 线性涨。

一次完整的 3 epoch 跑 828.6 秒（进程内计时），结束时 `nvidia-smi` 的整卡占用 19102 MiB（含别的项目）。

## 序列长度

366 条样本（训练 288 + 验证 78）的 token 数，`setup` 记录里报的：

| | p50 | p95 | max | 均值 |
| --- | --- | --- | --- | --- |
| prompt（聊天模板 + generation prompt） | 589 | 901 | 968 | 548.9 |
| target（+ eos） | 119 | 217 | 385 | 119.0 |
| prompt + target | 698 | 1056 | 1201 | 667.9 |

`max_length` 取 p95 1056 向上取整到 64 的倍数 = **1088**。超过的行只从头砍 prompt，target 一律不动：`truncation` 记录里训练集 8/288 行被截、共砍 515 个 token（最多一行 113），验证集 2/78 行、100 个 token。脚本里三处断言守住这条——target 单独就超过 max_length 时直接报错、`ids[prompt_len:] == target_ids`、砍完 prompt 不能空。

## 只对 target 算 loss

prompt 位置全部写成 -100，pad 位置也是 -100。每条样本在 `assert_mask()` 里运行时断言：第一个有效 label 的位置等于 prompt 长度，最后一个等于序列末尾减一，有效 label 个数等于序列长减 prompt 长（粘在一起，没有洞）。训练和验证两条路径都过这个断言。

`mask_check` 记录的那一条（prompt 656 token，得分 159 个 target token）：

```
mask check: first valid label index 656 == prompt_len 656
  masked prompt tail: '死吗？<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
  first target tokens: '先更正：上一条我说“正在发车”是错的，'
  target tokens scored: 159
```

掩掉的是处境原文和聊天模板的 assistant 前缀，从第一个回答 token 开始计分，边界正好在 `<think></think>` 之后。

## 训练在学

第一次 backward 之后统计 LoRA 参数的梯度：192 个可训练张量里 96 个有非零梯度，非零元素 6 193 152 个（`gradient_check`）。有梯度的那 96 个全是 `lora_B`，`lora_A` 在第一步必然是零梯度——B 初始化为 0，`∂L/∂A = Bᵀ·…` 就是 0，这正是 LoRA 初始化的性质，第二步起 A 也有了。断言 `nonzero > 0`，没有梯度就停。

loss 逐 step 落盘，54 步全部有限，从 2.369 走到 1.586，最低 1.265：

```
step  1: 2.369   step  5: 2.308   step 18: 1.990 (epoch 1 结束)
step 36: 1.562   step 46: 1.265   step 54: 1.586
```

| epoch | 训练 loss | 训练 PPL | 验证 loss | 验证 PPL | 验证 − 训练 |
| --- | --- | --- | --- | --- | --- |
| 0（训练前） | — | — | 2.4285 | 11.3418 | — |
| 1 | 1.7593 | 5.8085 | 1.8650 | 6.4562 | 0.1057 |
| 2 | 1.5247 | 4.5939 | 1.8032 | 6.0691 | 0.2785 |
| 3 | 1.4376 | 4.2105 | 1.7972 | 6.0325 | 0.3596 |

验证 PPL 每 epoch 都在降，但第三 epoch 只降 0.037（6.069 → 6.033），训练集还在降 0.087，差距从 0.11 涨到 0.36——收敛在验证侧已经变平，再跑 epoch 大概只买到训练集上的记忆。这个结论只说明跑通并学到东西，不说明学会法：验证集是 12 个会话 78 条样本，会话与处境都不跨两侧，样本量小，PPL 差 0.03 在噪声量级。行为层面的判断留给三点测量那个工作包。

## 复现

```
python3 scripts/train_sft.py --epochs 3 --grad-accum 8 --lora-r 16 --lora-alpha 32 \
  --lora-targets narrow --adapter-dir .tmp/sft/adapter-narrow
```

`--lora-targets narrow` 是这一版的必要开关：脚本默认 `wide`（12 个后缀，见 [挂宽 LoRA](sft-training-wide.md)），不写就会写出另一版适配器。`--lora-r` / `--lora-alpha` 同样要写死，否则按开跑前空闲显存选 rank。

同一 GPU 上约 14 分钟（828.6 秒），写 `evidence/sft/log.jsonl`、`evidence/sft/train-summary.json`、`.tmp/sft/adapter-narrow/`。`--limit N` 与 `--epochs 1` 是冒烟跑法。

不重训的装配级验证（约 1 分钟、不碰数据、不写训练日志）：

```
python3 scripts/train_sft.py --check-lora-targets
```

它对两个取值各加载一次基座并挂一次 LoRA，用同一条 `report_lora_coverage()` 从模型的 `layer_types` 重算命中数并断言：

| 取值 | 命中模块 | LoRA 张量 | 可训练参数 |
| --- | --- | --- | --- |
| `narrow` | 96（q/k/v/o × 6 层 + MLP × 24 层） | 192 | 10 911 744 |
| `wide` | 186（+ 线性注意力 5 个投影 × 18 层） | 372 | 16 819 200 |

断言的口径与 `evidence/sft/log.jsonl`、`evidence/sft/log-wide.jsonl` 的 `config.trainable_params` 以及两个 `adapter_config.json` 一致，结果落 `evidence/sft/log-lora-targets-check.jsonl`。这条命令证明两版适配器都能按清单重生成，但它本身不重训、不产出权重。

## 已知边界

- 验证 PPL 用的是同一个 loss 口径（只算 target），与三点测量的动作一致率不是一回事。
- LoRA 没有挂 18 个线性注意力层的投影（见配置一节）；挂宽的重跑在 `report/sft-training-wide.md`，验证更差，所以这不是缺口而是本数据上的选择。
- 三条与 `train_dpo.py` 相同的环境告警：`flash-linear-attention`、`causal_conv1d` 未安装，这两处走 PyTorch 参考实现；`use_cache` 与梯度检查点冲突，已被 transformers 关掉。三者都只影响速度，不影响数值口径——但要指望这两个内核，得装依赖后重跑。
- 峰值显存 8.74 GiB（分配）/ 9.98 GiB（保留）是在另一个项目同时占卡的情况下测的，换独占的卡会更高、更快。
