# 实施：环境、命令、记账与仓库

## EXPLICIT

- 没有上一层的话不推：提交可以只留在本机。
- 花费记账：metered 只增行不改旧行；本机 GPU 墙钟单列（金额 ¥0，`idle-compute`）。
- 读者能自己计时、自己 clone、自己重跑；一条命令的耗时必须写实测区间，不给没有量过的上界。

## CONFIRMED

### 环境

| 项 | 值 |
| --- | --- |
| Python | 3.12.3（纯 CPU 分析只用标准库） |
| GPU | 单卡 RTX 4090（24 GiB），与同机其它项目共享 |
| 训练 | torch 2.14.1+cu130、transformers 5.20.1、peft 0.21.2、bitsandbytes 0.50.2（`evidence/sft/log.jsonl` 的 `setup.hf`） |
| 官方 grader | 用 `uv` 起一次隔离环境；vendored 源码在 `evidence/benchmark/official/vendor/` |
| 网络 | 重算全离线；HF 快照与 Google 源码各取回一次 |

### 命令（按用途）

```bash
# 主指标重算（纯 CPU，3.17–3.33 s）
python3 scripts/measure_actions.py --analyse

# 自检：假数据上的区间与分解
python3 scripts/measure_actions.py --check
python3 scripts/measure_split.py --check

# 训练（窄版，约 14 min / 3 epoch）
python3 scripts/train_sft.py --epochs 3 --grad-accum 8 --lora-r 16 --lora-alpha 32 \
  --lora-targets narrow --run-name narrow --adapter-dir .tmp/sft/adapter-narrow

# 重生成政策轴的抽样（分两臂）
python3 scripts/measure_actions.py --generate

# 通用能力两格（每个进程一个套件）
python3 scripts/run_bench.py --suite ifeval --model adapter --adapter-dir .tmp/sft/adapter-narrow --limit 295 --tag adapter-ifeval
python3 scripts/run_bench.py --suite gsm8k  --model adapter --adapter-dir .tmp/sft/adapter-narrow --limit 100 --tag adapter-gsm8k
python3 evidence/benchmark/analyse_paired.py            # 两套件配对；4 个 label 任一并列

# 官方 grader 复核（热环境 7.5–13 s）
python3 evidence/benchmark/official/grade_official.py

# 主张面检查
python3 scripts/check_axes_claim.py
```

- **长跑必须 detached**：包内的后台 watcher 随它的 turn 回收，所以长跑只能长在 `setsid` 的 driver 上；
  等待靠 driver 自己写完成信到 `inbox/`，或用一次带 `waitFor` 的调用。**不能**用后台任务加「结束 turn 等通知」，也不能 `sleep`。
- **可续跑**：`--generate` 会跳过已落盘的 `(model, situation, draw)`；driver 重跑不会重复生成。
- **试验件另开名字**：`--tag` / `--adapter-tag` / `--out-tag` / `--answers` / `--out-dir`。

### 测试与门

| 检查 | 覆盖什么 | 失败时 |
| --- | --- | --- |
| `measure_actions.py --check` | 自举区间、X、格式/决策分解在假数据上的取值 | 非零退出，写 `selftest.json` |
| `measure_split.py --check` | 拆分结果与落盘件逐字段相同 | 非零退出 |
| `scripts/bench_selftest.py` | 套件判分器的行为（手算样例、空输出） | 非零退出 |
| `scripts/check_axes_claim.py` | 主张面：`agentic` 每句带「没测」、两处主张段点名两轴 | 非零退出并逐条打印 |
| `constitution/verify_gate.py` | 分类判定程序的五个 fixture | 非零退出 |
| `python3 -m py_compile` / 运行即断言 | 生成前断言：法条短语不出现、target 不截断、harness 四项一致 | 直接退出 |

### 记账

- **metered**：DeepSeek 累计 9059 次 ¥15.6493（17 批分项在 `evidence/reports/measurements.md`「花费」）；
  匹配锚点两批 2664 次 ¥2.1300。单价按锚点 ¥0.000799/次记。
- **本机 GPU**：金额 ¥0，按墙钟与授权用量记。

| 跑 | 墙钟 | 授权 | 用量 |
| --- | --- | --- | --- |
| M2 n=100（400 条） | 78 min 32 s | ≈5 h | 26% |
| M3 IFEval n=295（590 条） | 1 h 43 min 10 s | M2 剩 ≈3.7 h | 47% |
| M6 2-epoch（训练 + 395 条） | 1 h 56 min 40 s | M3 剩 ≈1.97 h | 98% |
| M6 政策测量（726 条） | 43 min 47 s | 用户 2026-10-26 给的 ≈1 h | 73% |

### 仓库布局

| 路径 | 内容 |
| --- | --- |
| `docs/` | 知识库：`0_STAGING`、`0_ROADMAP`、`1_PROBLEM` … `9_IMPLEMENTATION`（本文件） |
| `card/` | 模型卡、数据卡（对外交付的卡片） |
| `paper/` | preprint 草稿 |
| `mail/` | 与 root / person 的往来信原件（授权的原话在这里，不删） |
| `inbox/` | 工作收件：四个头行 `kind / from / spend / id`，读过的信落地即删 |
| `constitution/` | 法的冻结件、节点索引、分类与形状检查、冲突审计 |
| `data/` | 处境、配对、SFT 样本、覆盖率、benchmark 冻结样本 |
| `evidence/` | 每次测量的原始输出与复算脚本；`evidence/reports/` 是推导与逐条明细 |
| `eval/` | 四维 rubric 评测器与分辨力统计 |
| `mining/` | 从会话档案抽处境的脚本、脱敏门与计数 |
| `scripts/` | 构建、训练、测量、benchmark 的可重跑脚本 |
| `licenses/`、`THIRD-PARTY.md` | 许可原文与第三方声明 |
| `artifacts.tsv` | 权重 sha256 与重生成命令（权重不进 git） |

**哪些 markdown 不是知识文档**：`README.md`（门面）、`card/*`（交付卡片）、`paper/*`（草稿）、
`mail/*`（授权原件）、`THIRD-PARTY.md`（声明）、`evidence/**/README.md` 与 `evidence/reports/*.md`（证明与推导）、
`constitution/CLASSIFY.md` 与 `constitution/conflicts.md`（法的审计，绑 `nodes.json`）、
`mining/*.md`（抽取过程的产物）、`evidence/benchmark/official/vendor/**`（vendored 上游，未改一字）。

## INFERRED

### 证据指针

- 主结果：`evidence/measure/summary.json`；锚点：`evidence/measure/anchor-matched/`（888 行 / ¥0.7115）、
  `evidence/measure/anchor-draws9/`（1776 行 / ¥1.4184，`law_matched_self_agreement` 0.3198、
  `matched_law_minus_matched_bare` 0.0593）。
- 见过 / 留出：`evidence/measure/seen-heldout.json`；2-epoch 试件：`evidence/measure/e2/`。
- 通用能力：`evidence/benchmark/{base,adapter}-{gsm8k,ifeval}.json`、`paired-ifeval.json`（n: 295）、
  `paired-gsm8k.json`、`logs-n100/`、`logs-m2b/`；2-epoch：`adapter-e2-*`、`paired-e2-*`、`logs-e2/`。
- 参考实现：`evidence/benchmark/official/`（`official-ifeval.json`、`grade_official.py`、
  `dump_disagreements.py`、`HANDCHECK.md`、`VENDOR.md`、`RUN.md`、`vendor/`）。
- 前一次估计：`evidence/benchmark/n100/`（IFEval n=100 与两套件 n=20 的四格与两份配对）。
- 训练：`evidence/sft/log.jsonl`、`train-summary.json`；2-epoch：`log-e2.jsonl`、`train-summary-e2.json`。
- 推导与逐条明细：`evidence/reports/`（`sft-measurement.md`、`sft-benchmark.md`、`sft-training.md`、
  `sft-training-wide.md`、`sft-data.md`、`measurements.md`、`data-quality.md`、`rubric.md` 等）。

### 提交与发布

- 一个原子单元做完就提交；推之前先拉。发布已获授权，最后一次推是 `74793ff`；此后本机的提交（M2、M3、M6、
  文档迁移）都还没推。
- `evidence/measure/anchor-draws9/run.log` 每跑一次 `--analyse` 追加一行 `cmd:`，所以它不标 hash，
  是允许脏着出现在 `git status` 里的路径之一。`evidence/benchmark/logs-*/driver.{log,out}` 只在跑的时候长。
- 工作区必须干净：每个文件要么入库要么忽略，没有第三种状态。

### 已知的记账与记录缺陷（都只影响记录层）

- `scripts/bench_suites.py:226` 的 `per_instruction` 是 `dict(zip(...))`，同名指令互相覆盖
  （`ifeval-2069` 因此 `correct=False` 而所有指令都写 `True`）。修它等于换落盘格式、两侧重跑，见 Q6。
- `measure_actions.py` 的 `models.*` 记的是**当前进程的**适配器路径：分析时不传 `--adapter-dir` 就会写错。
  现在 driver 两处都传并断言 `summary.models.post`。
- `analyse_paired.py` 的 flag 曾只认开头位置；写在套件名后面会被当成四个未跑套件。已改为可前后。
