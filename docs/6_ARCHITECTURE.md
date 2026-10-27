# 架构

## EXPLICIT

无（person 只定了交付物与验收线，没定实现结构）。

## CONFIRMED

- 权重不进 git：`.tmp/` 是可删临时区，适配器只登记 `artifacts.tsv` 里的 sha256 与重生成命令。
- 每一笔测量都有自己的证据目录：`evidence/` 下的产物与跑它的脚本放在一起。

## INFERRED

### 五个子系统（按数据流向）

```
constitution/（冻结的法）    mining/ + evidence/densify/（处境与双答）
        │                              │
        └──────────────┬───────────────┘
                       ▼
              data/（配对、覆盖、SFT 样本）
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

**1. 法的冻结件 `constitution/`。** 法的快照、节点索引（264 叶子）、分类判定程序、形状检查与冲突审计。
本节点只读它；`lock.yaml` 记上游路径与 sha256，冻结副本按哈希校验。
冲突审计的原文与机器可读划分块在 [`constitution/conflicts.md`](../constitution/conflicts.md)，由
`constitution/audit_coverage.py` 解析并核对「完全且不相交」。

**2. 数据 `data/` 与 `mining/`。** 处境来自真实会话的最小片段；`mining/` 抽取与脱敏，`evidence/densify/`
是 735 条带法回答（DeepSeek）。配对（`pairs*.jsonl`）与 SFT 样本（`sft.jsonl` 366 = 训练 288 / 验证 78）
是这一层的产物；切分按**会话**，同一会话不跨两侧。

**3. 训练 `scripts/train_sft.py`。** 4-bit QLoRA，narrow targets（`q/k/v/o` + MLP），单卡 4090。
产出适配器目录与 `evidence/sft/train-summary-*.json`。训练只依赖 `data/sft-train.jsonl`。

**4. 政策测量 `scripts/measure_actions.py`。** 三个水平（base / post / 匹配锚点）共用同一 prompt、
同一解码；参照物是「带法 DeepSeek 的多数动作」。同一脚本负责生成（`--generate`）、分析（`--analyse`）、
自检（`--check`）；分析只读落盘回答，不碰 GPU。见过 / 留出拆分由 `scripts/measure_split.py` 复算，
断言 `paired_all` 与 `summary.json` 头行逐字段相等。

**5. 通用能力 `scripts/run_bench.py` + `evidence/benchmark/analyse_paired.py`。** 两套件（GSM8K 100 条、
IFEval 295 条）在同一个冻结前缀上跑 base / adapter，配对分析按条目比、不按整轮比。
参考实现复核在 `evidence/benchmark/official/`：vendored 的 Google `instruction_following_eval`（pin `e6890f85`）
重算同一批 590 份输出，与本仓库的判分并列。

### 边界与所有权

- **比较只在同一冻结前缀上进行**：`limit`、`seed`、`frozen_sha256`、`decoding` 四项任一不同，
  `analyse_paired.py` 直接拒绝（`check_same_harness`）。
- **试验件不得覆盖落盘件**：新跑用 `--tag` / `--adapter-tag` / `--out-tag` / `--answers` / `--out-dir`
  另开输出名；`evidence/measure/summary.json`、`evidence/benchmark/paired-*.json` 是冻结的交付证据。
- **判分代码只有一处**：`scripts/bench_suites.py` 的检查器是仓库自己的尺子；`per_instruction` 是记录层
  （同名指令会互相覆盖，见 Q6），不作为统计来源。
- **文档只有一个家**：本目录的层文档承载当前事实与决定；`evidence/reports/` 承载推导与逐条明细；
  `mail/` 是授权原件；`inbox/` 是工作收件，读过即删。

### 质量属性与落实手段

| 属性 | 手段 | 落点 |
| --- | --- | --- |
| 可复现 | 固定 seed、贪心解码、冻结前缀哈希、官方 grader 钉 `langdetect` 种子 | `3_REQUIREMENT.md`、`8_DETAIL.md` |
| 不可伪造 | 每个数都从落盘记录重算；分析脚本不重新判分（`correct` 来自记录） | `evidence/reports/`、`9_IMPLEMENTATION.md` |
| 不越界声称 | `check_axes_claim.py`（句法门）、`5_PRODUCT.md` 的边界清单 | `scripts/check_axes_claim.py` |
| 尺子先验证 | 匹配锚点的「带法 − 不带法」区间必须不含 0 才继续 | `evidence/measure/anchor-draws9/` |
| 长跑可恢复 | 生成可续跑（已落盘的键跳过）；driver detached 并自己写完成信 | `evidence/measure/run_e2_policy.sh` |
| 失败不污染 | 预备分析写 `preliminary.*`；证据目录分离；错误状态显式（不写终版） | `scripts/measure_actions.py` |
| 单点事实 | 数值只在 `2_GOAL.md`；明细只在 `evidence/reports/`；授权原话只在 `mail/` | 本目录 |

### 为什么不拆更多

- 测量与训练不共享代码：训练是 transformers+PEFT，测量是同一套解码但只读落盘；共享只会把 GPU 依赖带进分析。
- `evidence/reports/` 归到 `evidence/reports/` 而不是并入层文档：那些文件是**推导与逐条明细**（证明），
  层文档是**当前事实与决定**；两者分开，数值只在一处，明细可追溯到具体运行。
