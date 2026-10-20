# DPO 训练诊断：实现三项检查干净，失败在目标尺度与步数

类型：结果。所有者：主代理。上游：[训练结果](training.md)、[计划](../docs/plan/plan.md) 第五步。证据：`evidence/training/diag/`。

## 结论

先诊断后调参，三项检查全部干净：prompt 掩码正确、chosen/rejected 没有调换也没有截断、手算 DPO loss 与实现相差 3.3e-6。**这一版训练失败不是实现缺陷。**

真正的机制是**目标尺度**：loss 在 completion 上求 log 概率之和（不按 token 归一），而本数据每对 completion 有 120–350 token、逐 token 的 chosen/rejected 概率差可达 1.4 nat，于是每对的 margin 在 10² 量级，`beta=0.1` 等价于逐 token `beta≈15–35`，logsigmoid 大面积饱和：单步 batch 的 ΔΔ 在 ±70–290 nat 之间来回，loss 在 0.008–7.03 之间跳，76 步下来的净位移只有 −0.096 nat。降低 lr 到 1e-5、同样的 28 步预算内留出 reward margin 从约 −0.12 变成 **+0.003**，方向对了但幅度仍在噪声量级（ΔΔ = 0.03 nat）。

判定句：**实现无误而数据不足**。73 对训练、18 对留出，留出集里 base 模型本身只有 44% 偏好 chosen；扫描里最好的一档（lr 5e-5、beta 0.005）把留出 reward margin 推到 +0.0064、隐式准确率推到 0.500，量级上仍是噪声。要用这个法子把这批偏好写进权重，需要的是更多带方向证据的对子（见"需要什么"），而不是继续调参。

## 检查一：prompt 掩码是正确的

代码路径（`scripts/train_dpo.py`）：

1. `encode_pair` 返回 `(full_ids, len(prompt_ids))`，prompt 是 chat template 渲染后的 user 轮。
2. `make_batch` 写 `target_mask[i, plen:] = True`，再把序列尾部之外的 padding 置 False。
3. `sequence_logprobs` 右移一位对齐：`logits[:, :-1, :]` 与 `mask = target_mask[:, 1:]`，于是位置 `t-1` 的 logits 预测 token `t`，只有 completion 位置进入 loss。

逐 token 实测（留出对 SIT085，`evidence/training/diag/loss-check.json`）：

| 项 | chosen | rejected |
| --- | --- | --- |
| prompt token | 799 | 799 |
| completion token | 186 | 185 |
| 真正进入 loss 的 token | 186 | 185 |
| completion 的 logp | −718.61 | −459.38 |
| prompt+completion 一起算的 logp | −2945.63 | −2686.40 |

prompt 单独贡献 −2227 nat，被完整排除。全 91 对（182 条序列）的审计（`evidence/training/diag/mask-audit.json`）逐条断言"第一个被计分的位置 == plen"以及"被计分的 token id 序列 == completion id 序列"，全部通过：prompt token 74–942，completion token 10–355，计分 token 与 completion token 逐条相等。

**顺带纠正一个诊断假设**：即使掩码错了，把 prompt 算进去也不会稀释偏好信号——同一对的两侧共享同一段 prompt，那 −2227 nat 在 `logπ_c − logπ_r` 里精确抵消。掩码错误的实际后果是给每对加上几千 nat 的 bf16 噪声，而不是稀释。所以"prompt 稀释了信号"这条假设本身不成立，本次也不需要用修复来解释失败。

## 检查二：标签对齐，没有截断

- 全 91 对没有一对跨过 `max_length=1280`（最长 prompt+completion 1205），因此没有 completion 被截断。审计里"计分 token 数 != completion token 数"的序列数为 0；截断若发生会同时出现在这两个计数上，所以这个计数也是截断检测器。
- 顺序：`combined` 按 `chosen` 再 `rejected` 逐对追加，`dpo_step` 取 `pol_c, pol_r = policy_lp[:n], policy_lp[n:]`。用一次 4 条序列的批（2 对）逐条独立重算 logp 验证索引：index 0 = 第 1 对 chosen，index n = 第 1 对 rejected，逐条差最大 1.18 nat（相对 −720 是 0.16%，是 4-bit 量化与 bf16 批内差异的量级；调换会差几百 nat）。
- 同一条代码路径重算 SIT085 的四个 logp，与 `log.jsonl` 里 `final_eval.val` 记录的该对相差 0.60 / 1.28 / 0.30 / 0.67 nat（0.1–0.3%）：说明这里复现的就是那次训练跑出来的模型与数值。
- 因此"chosen 被当成 rejected 打分"这条假设排除。数据里是否存在方向错误的对子仍是另一回事（`report/stable-pairs.md`：39/91 对没有动作差信号），那是数据侧缺陷，不是实现缺陷。

## 检查三：手算 DPO loss 与实现一致

同一对 SIT085，同一批，分开算 policy 与 reference 的 completion logp：

| 量 | 值 |
| --- | --- |
| logπ_c（policy chosen） | −718.9360 |
| logπ_r（policy rejected） | −458.6903 |
| logπ_ref_c | −721.6735 |
| logπ_ref_r | −463.1285 |
| log-ratio chosen `logπ_c − logπ_ref_c` | +2.7375 |
| log-ratio rejected `logπ_r − logπ_ref_r` | +4.4382 |
| 差 ΔΔ | −1.7007 |
| βΔΔ（β=0.1） | −0.17007 |
| 手算 loss `−log σ(βΔΔ)` | 0.7817957 |
| `dpo_step` 返回 loss | 0.7817991 |
| 绝对差 | **3.3e-6** |

差 3.3e-6 是 fp32 舍入量级。公式与实现一致：`-logsigmoid(β[(logπc−logπref_c)−(logπr−logπref_r)])`，chosen 在左、rejected 在右，符号方向正确。

## 三项检查都干净，那失败在哪：目标尺度

检查一里已经看到，每对 margin 是**求和**而不是按 token 平均，所以它的量纲是"整条 completion 的 nat 数"。实测这条留出对的 **逐 token margin = −1.40 nat/token**。把这代进超参：

- `beta=0.1` × margin 10² nat ⇒ 单对 βΔΔ 常常超过 ±4，即 `logsigmoid` 的饱和区；饱和后该对梯度 ≈ 0，进入 loss 的只剩"最不饱和的那一对"，于是 step loss 在 0.008（βΔΔ 极大且符号对）到 7.03（βΔΔ ≈ −70）之间跳。
- 优化器仍在动，而且动得很大：逐步日志里 `margin − ref_margin` 在 −290 到 +400 nat 之间摆动，而 76 步后留出集的净 ΔΔ 只有 −0.096 nat。也就是"每对都被推动了十几到几十 nat，方向互相抵消，净值接近零"。
- 这解释了训练集 +1.17 nat / 留出集 −0.096 nat 的分裂，不需要"过拟合"来解释：噪声幅值远大于信号。
- 也解释了为什么 base 的偏好没被翻过来：base 在留出集上 44% 偏好 chosen，两侧 raw margin 平均 −14.5 nat；想翻过来需要在少数方向上净推进几十 nat，而实际净推进是 0.1 nat 量级。

## 三个配置的扫描

同一会话级留出划分（18 对 / 9 个会话，种子 0），同样 28 个优化步（`epochs 1.5`，每步 4 对），一次只动一个变量，按**留出 reward margin** 选，不看训练 loss：

| 配置 | lr | beta | 步数 | 留出 reward margin | 留出 raw margin | 留出隐式准确率 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 基线（原跑，28 步插值） | 5e-5 | 0.1 | 76 | ≈ −0.12（step 24 −0.144，step 32 −0.090） | −15.93 / −15.39 | 0.444 | 等预算对比的参照点 |
| A | 1e-5 | 0.1 | 28 | +0.0032 | −14.46 | 0.444 | 只降 lr |
| **B** | 5e-5 | 0.005 | 28 | **+0.0064** | **−13.21** | **0.500** | 只降 beta |
| C | 1e-5 | 0.005 | 28 | +0.0012 | −14.27 | 0.444 | 两件一起降 |

被选中的是 **B（lr 5e-5、beta 0.005、28 步）**，留出 reward margin +0.0064（ΔΔ = 0.064 nat），留出 raw margin 从 −14.5 推到 −13.21，隐式准确率 0.500（18 对里 9 对）——比原跑 76 步的 0.444 多 2 对。三个配置的留出 reward margin 都从约 −0.12 转正，说明"降低目标尺度或降 lr"确实修掉了方向，但**幅度只有 0.01 量级，18 对的基础上标准误远大于此，三个配置彼此不可区分**。所以这不是"学会了"，只是"不再越学越差"。

等预算对比的口径：原跑在 step 24 与 step 32 的留出 reward margin 是 −0.144 与 −0.090，可作 28 步基线的插值约 −0.12。

每个配置的完整日志在 `evidence/training/diag/<tag>/log.jsonl`，`train-summary.json` 里有终值，三行汇总在 `evidence/training/diag/sweep.json`。

扫描里同时看到一个副作用：`beta` 从 0.1 降到 0.005 后训练 loss 不再跳到 7（三个配置的终值 val DPO loss 在 0.690–0.695 之间），饱和消失；这与上面的尺度分析一致。

## 被取代的数字

没有数字被取代：三项检查没有发现需要修复的缺陷，主跑没有重跑，`report/training.md` 的 76 步结果、PPL 与内存表继续有效。新增的是诊断事实：掩码逐 token 审计、标签顺序复核、手算 loss 对照，以及 28 步的三配置扫描。

## 需要什么才可能学会

判定是"数据不足"，具体缺口：

1. **带方向证据的对子太少**：91 对里 39 对两侧动作签名都空、跨条件相同，它们只能教"这批文本像什么"。有方向信号的 52 对再按会话切掉 18 对，留出后训练只剩 ~40 对有信号。要把 margin 推到统计可分的程度，需要在这个量级上再上一个数量级（数百对带证据的对子），并且每对要有可判定的偏好来源，而不是靠 retry 关系推断。
2. **或者换掉求和口径**：按 token 平均 logp（DR-DPO/长度归一）后，每对 margin 落到 ~0.1 nat 量级，β 需要相应放大到 1–10 才在有效区间；这样可以避免饱和，但净信号仍是 73 对的量级，不会凭空变大。这是超参修复，不是数据修复。
3. **更多步数只解决饱和后的推进速度**，不解决"留出集 44% 的偏好与 base 先验相反"这个数据事实。

## 复现

```bash
python3 scripts/diag_dpo_checks.py          # 三项检查，写 evidence/training/diag/loss-check.json
python3 scripts/train_dpo.py --lr 5e-5 --beta 0.005 --epochs 1.5 --eval-every 28 \
  --skip-train-eval --out-dir evidence/training/diag/lr5e-05_beta0.005
```

`scripts/diag_dpo_checks.py` 只做 forward（无梯度），需要那次训练留下的适配器 `.tmp/training/adapter-dpo-r16/`；适配器缺失时先跑 `scripts/train_dpo.py`。

## 局限

1. 手算对照只做了 1 对（SIT085）；公式与掩码的结构性断言覆盖了全部 91 对，但数值对照是抽样。
2. 4-bit 量化 + bf16 下逐条 logp 与批量 logp 有 0.1–0.3% 的差异（1.2 nat 级），这是本实现的数值底噪，小于任何要测的信号，但意味着 0.1 nat 级的差异不可信。
3. 扫描每个配置单次运行、单一种子，28 步；留出 18 对，reward margin 的标准误远大于配置间差异（+0.0064 与 +0.0012 无法区分）。因此"B 最好"这个排序不显著，只能说"三个配置都使方向从负转正"。
4. 96 对以外的截断、掩码结论不适用于别的 `max_length` 设置；1280 下没有截断，若把 `max_length` 调小则 completion 会被切断且本审计的计数会变红。
