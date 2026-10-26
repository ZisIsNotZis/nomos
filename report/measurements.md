# 测量结果

类型：结果。所有者：主代理。现有数字都在这里，每个都指向落盘的证据。

## 处境池

- 会话档案：`~/.pi/agent/sessions`，3312 个 JSONL，其中 **275 个是交互会话**；其余是子代理运行与转录。
- 人类用户轮 **1746** 条，工具调用 86 273 次；用户消息里 41% 是 harness 注入，按结构剔除。
- 结构信号命中 455 个候选窗口；以用户轮结尾的合格处境 **242** 条，来自 **51 个不同会话**。
- 证据：`mining/report.md`、`mining/candidates.jsonl`。

## 双答样本

- 183 条处境各两次回答（带法 / 不带法），落 `data/pairs.jsonl`；筛掉两侧同动作 6 条与坏件 3 条后，**174 条**入账，落 `data/pairs-filtered.jsonl`。判据、逐条丢弃与覆盖计数见 [数据质量](data-quality.md)。
- 早先 20 条处境的对照探针里，两条回答实质不同的 9/20 = **45%**；证据：`evidence/bare-baseline/analyse.py`。

## 法的覆盖

- 叶子节点 264；可训练 175，不可训练 89（工具/宿主绑定 28，概念与定义 61）；两可 32。
- 覆盖计数与标注：见 [数据质量](data-quality.md)，数据落 `data/coverage.json`、`data/coverage-counts.json`。
- 证据：`constitution/nodes.json`，重算 `python3 constitution/build_nodes.py`。

## 冲突审计

- 比对 68 对，**真冲突 0**；优先级处境 10，平衡点 4，其余为无关；172 个叶子论证为不碰撞。
- 证据：`docs/method/conflicts.md`。

## 评委可靠性

- 同一对回答换位置各判一次，**不一致率 0.66–0.75**；同条件对照在位置偏好下 Y 胜率 0.913。
- 同一请求重发，回答复现率 89%；换向翻转不对称 35 比 12。
- 结论：这一版成对偏好仪器不可用，判断只能靠可数子级。
- 证据：`evidence/position-swap/`、`evidence/draw-noise/`、`evidence/forced-choice/`。

## 四维 rubric 的分辨力

- 64 组已知水平（带法 vs 不带法）上，四维分与合成分**分不开**：合成分差 **−0.001**，95% 区间 [−0.0265, 0.0255]，逐对胜负 27 比 34，符号检验 p 0.44，置换检验 p 0.96。
- 同一回答判三次的项内标准差：相位 0.090、证据 0.079、提问 0.044、交付 0.055、合成分 0.040；三次总分不一致的回答占 73%。
- 已知更差的对照（追加一条越权强制推送）8 组里 8 组合成分下降，平均 **−0.160**：0.16 量级能分辨，0.03 以下不能。
- 结论与判据、两次判读、逐条件结果：[rubric](rubric.md)。证据：`evidence/rubric/`、`eval/judge.py`、`eval/analyse.py`。

## Qwen3.5-2B 基座

- `Qwen/Qwen3.5-2B`，revision `15852e8c…`，22.1 亿参数，bf16，单张 4090，峰值显存 6.66 GiB。
- 20 条处境、两条件、贪心解码：裸条件 **16/20** 产出可判定动作；带整部法 14/20，且 5 条截断、2 条复读、2 条回显。
- 工具行：裸条件 **0/20**，带法条件 6/20。
- prompt 长度：裸 526 token，带法 19 878 token。
- 证据：`evidence/qwen-base/generations.jsonl`。

## 花费

- 全部 DeepSeek API 调用 **9059 次、¥15.6493**（约 ¥15.65），其中 9015 次成功、44 次失败或重试。这是逐次落盘的金额求和，不是估算。
- 口径：一次调用 = 一次 HTTP 请求，含重试；金额取每条调用记录里已经写下的 `cost.cny`（生成批次）或 `cost_cny`（判读与标注批次），脚本按 DeepSeek 官方单价（input 命中缓存 0.006 / 未命中 0.30 / 输出 1.20 USD per Mtok，off-peak 减半）× 汇率 6.693661 与调用时刻计价，单价与汇率来源 `evidence/bare-baseline/run-meta.json`、`scripts/annotate_coverage.py` 的 `PRICE`。本表只求和，不改算。

| 批次 | 调用 | 失败/重试 | 花费 | 落盘 |
| --- | --- | --- | --- | --- |
| slice-contrast 生成（183 处境×2 条件，首轮双答） | 549 | 0 | ¥1.5282 | `evidence/slice-contrast/answers.jsonl` |
| slice-contrast 判读（逐片对照） | 405 | 0 | ¥1.1883 | `evidence/slice-contrast/calls.jsonl` |
| bare-baseline（20 处境对照探针） | 120 | 0 | ¥0.3294 | `evidence/bare-baseline/calls.jsonl` |
| grow（新 59 处境×2 条件×2 条） | 236 | 0 | ¥0.4940 | `evidence/grow/answers.jsonl` |
| resample（174 处境每条件再抽一条） | 348 | 0 | ¥0.6044 | `evidence/resample/answers.jsonl` |
| densify（242 处境×2 条件×3.04 条） | 1470 | 0 | ¥1.2535 | `evidence/densify/answers.jsonl` |
| anchor-matched（148 处境×2 条件×3 条，含 pilot 120） | 888 | 0 | ¥0.7115 | `evidence/measure/anchor-matched/answers.jsonl` |
| anchor-draws9 追加（148 处境×2 条件×第 3–8 条，把匹配锚点抽到每侧 9 条） | 1776 | 0 | ¥1.4184 | `evidence/measure/anchor-draws9/answers.jsonl` |
| position-swap（评委位置偏好） | 1172 | 0 | ¥2.3868 | `evidence/position-swap/calls.jsonl` |
| draw-noise（同条件重发的噪声） | 636 | 0 | ¥1.2404 | `evidence/draw-noise/calls.jsonl` |
| forced-choice（强制二选一对照） | 20 | 0 | ¥0.0678 | `evidence/forced-choice/calls.jsonl` |
| rubric 第一遍（holistic） | 411 | 2 | ¥0.8205 | `evidence/rubric/pass-holistic/calls.jsonl` |
| rubric 第二遍（逐条） | 423 | 14 | ¥1.8375 | `evidence/rubric/calls.jsonl` |
| coverage（242 处境的覆盖标注） | 176 | 2 | ¥0.4777 | `evidence/coverage/calls.jsonl` |
| coverage-cap8（同上，标签上限 8） | 177 | 3 | ¥0.5403 | `evidence/coverage-cap8/calls.jsonl` |
| coverage-uncapped（同上，标签不限） | 197 | 23 | ¥0.6274 | `evidence/coverage-uncapped/calls.jsonl` |
| grow/coverage（新 55 处境的覆盖标注） | 55 | 0 | ¥0.1231 | `evidence/grow/coverage/calls.jsonl` |
| **合计** | **9059** | **44** | **¥15.6493** | 上列 17 个文件 |

按用途分三堆：处境生成 5387 次 ¥6.3395、评委 3067 次 ¥7.5413、覆盖标注 605 次 ¥1.7685，三堆相加即 ¥15.6493（按上表已四舍五入的行值相加是 ¥15.6492，差 0.0001 是四舍五入）。

`anchor-draws9` 这一行是 2026-10-21 追加的抽样，按臂拆开是带法 ¥0.8796 / 不带法 ¥0.5388（均值 ¥0.000799/次），全部落在 off-peak 价档；分项、参数与两目录合计写在 `evidence/measure/anchor-draws9/run-meta.json` 里，本表只取它的求和，不改算。原批 888 次 ¥0.7115 未被改写（追加只在 `range(3, 9)` 上跑），所以两行合计 2 664 次 ¥2.1300 就是整个匹配锚点的花费。

这张表只增行、不重跑：新批次落盘后把它的行插进来、把合计重算一遍，旧行不动。

复算命令（输出就是上面这张表的行）：

```sh
python3 - <<'EOF'
import json
B=[("slice-contrast 生成","evidence/slice-contrast/answers.jsonl"),("slice-contrast 判读","evidence/slice-contrast/calls.jsonl"),("bare-baseline","evidence/bare-baseline/calls.jsonl"),("grow","evidence/grow/answers.jsonl"),("resample","evidence/resample/answers.jsonl"),("densify","evidence/densify/answers.jsonl"),("anchor-matched","evidence/measure/anchor-matched/answers.jsonl"),("anchor-draws9 追加","evidence/measure/anchor-draws9/answers.jsonl"),("position-swap","evidence/position-swap/calls.jsonl"),("draw-noise","evidence/draw-noise/calls.jsonl"),("forced-choice","evidence/forced-choice/calls.jsonl"),("rubric 第一遍","evidence/rubric/pass-holistic/calls.jsonl"),("rubric 第二遍","evidence/rubric/calls.jsonl"),("coverage","evidence/coverage/calls.jsonl"),("coverage-cap8","evidence/coverage-cap8/calls.jsonl"),("coverage-uncapped","evidence/coverage-uncapped/calls.jsonl"),("grow/coverage","evidence/grow/coverage/calls.jsonl")]
N=F=0; S=0.0
for name,p in B:
    rs=[json.loads(l) for l in open(p) if l.strip()]
    c=sum(float(r.get("cost_cny") or (r.get("cost") or {}).get("cny") or 0) for r in rs)
    bad=sum(1 for r in rs if not r.get("ok"))
    N+=len(rs); F+=bad; S+=c
    print(f"{name:22s} {len(rs):5d} {bad:3d} ¥{c:8.4f} {p}")
print(f"TOTAL {N} {F} ¥{S:.4f}")
EOF
```

**含哪些、不含哪些**：上表含 `evidence/` 下所有带逐次 usage 的 DeepSeek 批次，每个批次只算一次（有 `calls.jsonl` 的按它算，只有 `answers.jsonl` 的按它算；`evidence/slice-contrast/` 两者是两批不同的事——生成与判读——所以都算）。不含三类：

- **没有 usage 落盘，无法计价**：`evidence/agent-context/` 的 12 条回答与 6 条判读只存 id 与文本，没有 `usage`/`cost` 字段，因此不在上表里，也不推算（缺的值不拿别的数顶替）。
- **本机生成与训练，不花 API 钱**：`evidence/measure/answers.jsonl` 的 1452 条回答、`evidence/benchmark/` 四格 400 条回答（n=100；另 n=20 的 80 条是前一次估计）跑在单卡 4090 上，`evidence/sft/`、`evidence/training/` 是训练日志。GPU 那一类的墙钟记在下一节，不进钱表。
- **本地分析**：`evidence/rubric-diagnosis/`、`evidence/data-quality/`、`evidence/corrupted2/` 对已存回答做自举与签名比较，没有 API 调用。

### 本机 GPU（不计钱）

这一类不进上面的钱表：花费类是 `idle-compute`，不租卡、不花 API 钱，金额 ¥0。要记的是墙钟，以及它相对派发时那份授权的用量——授权是一次性的，过期不补，所以用量是事实而不是估计。

| 跑 | 格 | 条数 | 墙钟 | 生成时间合计 | 派发时授权 | 用量 |
| --- | --- | --- | --- | --- | --- | --- |
| M2 `m2-n100`（2026-10-21T12:41:08 → 13:59:41） | GSM8K/IFEval × base/adapter | 400 | 78 min 32 s（4713 s） | 8290 s（两路并行） | ≈5 h `idle-compute` | **26%** |
| M3 `m3-ifeval-295`（2026-10-21T14:07:46 → 15:50:56） | IFEval × base/adapter | 590 | **1 h 43 min 10 s（6190 s）** | 11609 s（两路并行） | M2 剩下的 ≈3.7 h | **47%** |
| M6 `e2`（2026-10-23T13:42:03Z → 15:38:43Z） | 训 2-epoch + IFEval 295 / GSM8K 100 × adapter | 395 | **1 h 56 min 40 s（7000 s）** | 训练 341.4 s + 6625.9 s（两格并行；GSM8K 1642.9 s 在影子内） | M3 剩下的 ≈1.97 h | **98%** |

- 起止取自 `evidence/benchmark/logs-n100/driver.log` 的两行时间戳（`preflight ok` 与 `analyse rc=0`），不是估的；`driver.pid` 记的 pid 91165 在 `analyse` 之后退出，watcher 的退出通知在当时的收信目录里（已落地并删信；那个目录现在叫 `inbox/`）。
- 逐格 `elapsed_seconds` 在 `evidence/benchmark/paired-*.json`，单条 14.1–23.4 s；n=100 比 n=20 那一轮的 23.3–35.9 s 快，因为跑的时候卡上是空的（预检 23560 MiB 空闲）。
- 剩 ≈3.7 小时未用。这一轮 **没有 metered 调用**，所以上表的 `TOTAL 9059 44 ¥15.6493` 不变。
- M6 那一行：起止取自 `evidence/benchmark/logs-e2/driver.log` 的 `start` 与 `done` 两行；`train rc=0` 与 `bench rc=…` 把训练（341.4 s，`evidence/sft/train-summary-e2.json`）与两格并行（`adapter-e2-*.json` 的 `elapsed_seconds`）分开。**跑完之后授权只剩 ≈2 min**，所以再要 GPU 得先回上一层要一份新授权。
- M3 那一行先在派发时落账（2026-10-21T14:07:46，`evidence/benchmark/logs-m2b/driver.log` 第一行），跑完后按同一份 log 补完：起止取 `preflight` 与 `completion written` 两行时间戳，逐格耗时取 `paired-ifeval.json` 的 `elapsed_seconds`（base 5436.8 s、adapter 6172.5 s）。两轮合计 3.03 h，是那次 5 h `idle-compute` 授权的 61%。未定就写未定，不填零也不按预估充数——这一次是实测填的，不是预估。

覆盖标注的「550 次、¥1.65」只指 `coverage`、`coverage-cap8`、`coverage-uncapped` 这三遍（550 次请求、¥1.6454），不含 `grow/coverage` 的 55 次 ¥0.1231；[数据质量](data-quality.md) 与 [增长批次](grow-pairs.md) 各报自己那一笔。
