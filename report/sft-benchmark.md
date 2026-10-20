# Benchmark：套件已选好、判分已自检，headroom 未测

## 结论

准备了两个套件：GSM8K（200 条冻结样本）与 IFEval（295 条冻结样本，占原 541 条的 55%，只保留本项目判分器能判的指令类型）。两者都完全离线、许可清楚（MIT / Apache-2.0）、判分由代码决定、无模型评委。判分路径用假模型自检通过：34 个手算判例全过，5 条端到端管线运行全过，**没有跑任何真模型**，所以 headroom（基座分数是否落在 30–70%）**仍是未测量**，不能用这轮的数字判断套件是否可用。

## 选型：判定标准与结论

判定标准五行：能否离线（本机不再下载）、许可、样本量、判分是否确定、与本任务「下一步该做什么判断」的相关度。

| 候选 | 离线 | 许可 | 样本量 | 判分确定 | 相关度 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| GSM8K | 是：`openai/grade-school-math` test.jsonl 已下到仓库，750 KB 源 → 冻结 200 条 | MIT | 1319 → 取 200 | 是：取 `####` 后的数与金标数比，无评委 | 中高：数学推理是「通用能力」最短的那块板，SFT 只喂了 288 条长中文回答，这里最可能先掉 | **选** |
| IFEval | 是：HF 缓存 `google/IFEval` 快照在 `/home/z/hf/hub`，源 541 条 | Apache-2.0 | 541 → 取 295 | 是：15 类指令全部是正则/结构检查 | 高：训练目标是「换一种回答方式」，格式与长度指令正是这种改动最可能连带损伤的能力 | **选** |
| MMLU 小样本 | **否**：本机只有 parquet，`pyarrow` 未装，`huggingface.co` 与 PyPI 都不可达（curl 超时），GitHub 上的 `hendrycks/test` 仓库不含 data CSV | MIT | — | 是（字母匹配） | 中高：知识面掉分最直观 | 本轮不准备；解锁条件：`pip install pyarrow` 后从本地 parquet 切 200 条，工具函数与 MMLU 共用字母匹配判分 |
| HumanEval | 否：本机无数据、无 docker | MIT | 164 | 需执行生成代码 | 低：2B 基座 pass@1 近 0，地板效应，掉了也看不出 | 弃：无法安全执行不可信代码，且没有 headroom 空间 |
| BFCL 多轮 | 否：数据在 HF（不可达），判分 harness 上千行且要模拟多轮工具环境 | Apache-2.0 | 800+ | 是（AST 检查） | 高（最接近「下一步该做什么」） | 弃（本轮）：离线与判分成本都不满足，留作下一轮，若做则是第三个套件的首选 |
| ARC-Challenge / TruthfulQA | 否：同为 parquet | 各自开放 | — | 是 | 低：与 MMLU 同类，冗余 | 弃 |

两个套件覆盖两条不同的轴：知识/推理（GSM8K）与回答合规（IFEval）。第 3 个套件不补 MMLU 也不影响「有没有掉」的结论强度，因为它与 GSM8K 同轴；BFCL 才是补齐「agentic 决策」那条轴的候选，但离线条件这轮不成立。

## 已就绪的文件

| 路径 | 内容 |
| --- | --- |
| `data/bench/gsm8k.jsonl` | 200 条冻结样本（id、question、answer_number），sha256 `def2e3a0…c1d3` |
| `data/bench/ifeval.jsonl` | 295 条冻结样本（id、prompt、instruction_id_list、kwargs），sha256 `0cc0fb57…71e` |
| `data/bench/sources.json` | 源 URL、许可、源文件 sha256、采样规则、每套件的 `max_new_tokens`、被排除的指令类型计数 |
| `scripts/bench_prep.py` | 从源重建冻结样本；`--check` 重算选择并与 `sources.json` 的哈希比对 |
| `scripts/bench_suites.py` | 两套件的 prompt 构造、答案抽取、判分、Wilson 区间 |
| `scripts/run_bench.py` | `--suite {gsm8k,ifeval,all}`、`--model {base,adapter}`、`--limit`、`--stub`（自检用，不占卡） |
| `scripts/bench_selftest.py` | 无 GPU 自检，落 `evidence/benchmark/selftest.json` |
| `evidence/benchmark/selftest.json` | 34 个手算判例 + 5 条管线运行的通过记录 |

采样规则：候选 id 按 `sha256("<seed>:<id>")` 升序排，取前缀；与源文件行序无关，故同一 seed 复现同一样本，`--limit` 小的那次是大那次的前缀（基线 20 条与正式 200 条可直接比）。seed 固定为 0，写在 `sources.json` 里，`run_bench.py --seed` 与它不一致即报错。

解码是贪心（`do_sample=False`），不是多次抽样；残余不确定性只有数值实现的差别，所以判读用区间重叠而不是点估计：同一 seed 下每组数都带 95% Wilson 区间，两条区间重叠就说「没测到掉」。

## 自检结果

`python3 scripts/bench_selftest.py`（纯 CPU，未占卡，未加载任何权重）：

```
{"extractor_cases": 6, "checker_cases": 30, "pipeline_runs": 5}
gsm8k   gold     acc=1.00 unscorable=0     # 假模型吐金标 → 必须满分
gsm8k   wrong    acc=0.00 unscorable=0     # 金标 +1 → 必须零分
gsm8k   garbage  acc=0.00 unscorable=20    # 吐不出数 → 记 unscorable，不当成答错
ifeval  hand-computed acc=0.50             # 两条手写样本：一条全过、一条挂 lower-case
ifeval  empty-output  acc=0.00             # 空答案不得分（这条抓出一个真 bug，见下）
```

自检抓到并已修的两个判分缺陷，都在 `scripts/bench_suites.py`：答案抽取最初把 `#### 7` 整串当数字（得到 None，会让所有正确回答算错）；IFEval 的 `change_case:english_capital` 在空字符串上恒真（空回答会被记成满足大写指令）。两条都补了手算判例。

`run_bench.py` 的 CLI 路径也实跑过（stub 模式）：`evidence/benchmark/base-stub-gold-gsm8k.json`、`base-stub-gold-ifeval.json`、`adapter-stub-wrong-gsm8k.json`。它们的文件名带 `stub`，不是模型成绩。

## 预计运行时间与显存（估算，未实测）

前提：基座 Qwen3.5-2B 4-bit（权重 1.77 GiB，此数是 `report/sft-training.md` 的实测值），batch 1，贪心，序列 ≤1200 token。**解码速度在本机没有实测过**，下面按 30–60 token/s 估，所以时间是数量级，不是承诺；第一次真跑要把实测速度写回本表。

| 套件 | 条数 | prompt token（估） | 生成 token（估） | 时间（估） | 显存（估） |
| --- | --- | --- | --- | --- | --- |
| GSM8K | 200（基线可用 100） | ~60 | ≤512，典型 250–400 | 100 条 10–20 min；200 条 20–40 min | 权重 1.77 GiB + KV ≤0.5 GiB → 峰值 ~2.5 GiB（另加日志/临时量，按 3 GiB 预留） |
| IFEval | 295（基线可用 100） | ~80 | ≤640，典型 200–450 | 100 条 8–15 min；295 条 25–45 min | 同上 ~2.5 GiB |
| 两套件 × base/adapter 全跑 | — | — | — | **约 1.5–3 小时** | 峰值同一时刻只跑一个进程，2.5–3 GiB |

显存前提是 `< 3 GiB`：卡上现有别的项目占 8.8 GiB（`nvidia-smi` 24.5 GiB 卡），剩 15 GiB，跑这个不会挤到它——前提是**不要**一次起两个进程，也不要加 batch。若真跑时 `torch.cuda.mem_get_info` 报剩余不足 4 GiB，先降 `--limit` 而不是改量化。

## 还没做的事

- **headroom 未测**：没有任何真模型跑过，所以不知道基座在 GSM8K/IFEval 上落在 30–70% 的哪一段。若基座 GSM8K 已 >85%（Qwen 系数学偏强，有这个可能），这个套件对「掉没掉」不敏感，要换更难的数学集；若 IFEval <30%（2B 常见），同样没有下降空间，只能看相对掉幅。判定表要等第一个真跑结果再定，这是下一个工作包的第一步。
- 真跑要占卡：本轮按约定不占用，留给 GPU 空出来之后的工作包。
- IFEval 只覆盖 15 类指令（共 25 类），排除的 246 条中 `length_constraints:number_sentences`、`language:response_language`、`number_bullet_lists` 等需要分句器或语言识别，判分器没写；因此本分数不能与公开 IFEval 数比，只能 base vs adapter 自比。
- MMLU 未准备（见上表解锁条件）。
