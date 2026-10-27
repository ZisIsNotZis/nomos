# 模块内部：算法与判据

## EXPLICIT

无。

## CONFIRMED

### 政策轴的三个水平与参照物

- 三个水平：`base`（训练前基座）、`post`（适配器）、匹配锚点（DeepSeek，带法 / 不带法各一批）。
- 参照物 = **带法 DeepSeek 的多数动作签名**。只在「带法侧至少 2 条抽样给出同一签名」且「该签名非空」时才算定下来
  （`MIN_REFERENCE_VOTES = 2`）。
- 动作签名取自 `resample_actions.signatures()`（与造 SFT 数据同一套解析），`action_signature` 与
  `coarse_signature` 都落盘；`per_instruction` 不参与统计。
- 文字层签名（口径二）= `asks / stops / asserts / artifacts` 四位的定序元组，判据全部来自 `eval/judge.py`
  的 `QUESTION_END / STOP / CLAIM+EVIDENCE+HEDGE / ARTIFACT_*`，这里只组合，不另写一套。

### 一致率与 X

- 每处境每侧的一致率 = 3 条抽样里与参照物签名相同的比例（`base` / `post` 字段）。
- 主指标 `post_mean` / `base_mean` = 参照物可用且两侧齐全的处境上的算术平均（`n_pairs = 148`）。
- `X = (post_mean − base_mean) / (1 − base_mean)`，接近满值（`1 − base < 0.2`）时报出但标注；
  `base = 1` 时 X 无定义，写 `undefined`，不拿 0 冒充。
- 口径三（动作可比子集）只取回答里真出现动作的处境；`< 30` 条处境时只作参考，不当结论
  （比例区间宽到分不清「格式」与「决策」）。

### 区间与检验

- 配对区间：按处境重采样 2000 次（`BOOTSTRAP = 2000`），2.5% / 97.5% 分位；
  实现在 `scripts/resample_actions.py`（树里只有这一份）。
- 分解区间：`bootstrap_decomposition(rows, SEED + 10)`，给 Δ、format、decision、interaction 各一条。
- McNemar：精确双侧 `p = 2·Σ_{k=0}^{min(d,g)} C(d+g,k) / 2^(d+g)`，只用不一致对。
- 检出下限：`smallest_detectable_drop(n)`（无涨点时要多少条净掉才过 α=0.05）与
  `smallest_drop_by_interval(n)`（同一条自举区间下要多少条）——n=295 时是 1.7pp / 1.4pp。
- 分解：`Δ = format_part + decision_part + interaction_part`；format 项只看「发出动作的比例」的变化，
  decision 项看「在发出的动作里选对的比例」，交互项是两者的乘积效应。

### 生成与上限

- 解码：`temperature 0.7`、`top_p 0.95`、`top_k None`、按 draw 固定种子（`SEED + draw`）、贪心之外的随机采样。
- 上限：`cap_recorded(rows)` 从行本身读回——新行记 `max_new_tokens`；旧行由撞上限的行反推
  （撞上限时 `completion_tokens` 正好等于上限）。一批里出现两个上限就 `SystemExit`，不猜。
- 与落盘侧配对的新生成沿用落盘侧的上限（320）；新套件才用 `10 × 最长合法输出 = 3110`。

### 见过 / 留出拆分

- 训练 / 验证按**会话**切：`data/sft-train.jsonl`（191 条处境）/ `sft-val.jsonl`（51 条，12 个会话）。
- `measure_split.py` 用与主分析同一套重采样与同一组种子重算两半，并断言 `paired_all` 与
  `summary.json` 头行逐字段相等——否则它自己就是第二把尺子。

### 通用能力

- 冻结前缀：`frozen_sha256 = 0cc0fb57…71e`（IFEval 前 295 条、GSM8K 前 100 条），贪心解码，seed 0。
- 配对分析按条目比：`analyse_paired.py` 检查 `limit`、`seed`、`frozen_sha256`、`decoding` 四项与条目 id 顺序，
  任一不符即拒绝。
- `correct` 来自落盘记录，分析不重新判分。

### 参考实现（Google `instruction_following_eval`，pin `e6890f85`）

- 官方 strict / lax 两套判定；`change_case` 检查器内部调 `langdetect`，`DetectorFactory.seed` 默认 `None`，
  不钉时同一份输出两次运行给 160 与 159。`grade_official.py` 钉 `DetectorFactory.seed = 0` 与 `random.seed(0)`。
- 两把尺子的分歧七族、共 56/836 槽：`number_paragraphs`（33/40，最大一族，我们数空行、官方按指令点名的 `***`）、
  `json_format`、`forbidden_words`（子串 vs `\b`）、`change_case`（官方多一道 `langdetect`）、
  `number_words`（`_words` 空白切分）、`startend:end_checker`、`combination:two_responses`。
  11 条逐条人读：官方对 7、我们对 3（全是 `langdetect`）、1 条口径问题。

### 训练配方（窄版，shipped）

| | 值 |
| --- | --- |
| 基座 | Qwen3.5-2B，4-bit nf4 double-quant，bf16 compute |
| LoRA | `--lora-targets narrow`（`q/k/v/o` + `gate/up/down`），r 16 / alpha 32 |
| batch | micro 2 × 梯度累积 8（有效 16） |
| 优化器 | paged_adamw_8bit，lr 1e-4，暖机 5 步后线性衰减 |
| 序列 | `max_length` 1088（p95 1056 上取整），只从头砍 prompt，target 不动 |
| epoch | 3（54 步）；2-epoch 试件 24 步 |
| 种子 | 0（torch / numpy / random） |

- 混合架构的边界：24 层里 6 层是全注意力（`q/k/v/o`），18 层线性注意力的投影没挂 LoRA；
  宽版（12 个后缀）验证 PPL 6.0923 比窄版 6.0325 差，所以窄版是选择不是缺口。

### 数据构造

- 处境 242 条（183 + 59），来自 51 个会话；735 条带法回答 → 366 条样本（丢弃 369：截断 3、逐字 94、
  同动作签名 244、同文字层决策 28、近重复 0）。
- 覆盖：175 条可训练规则里命中 77 条（下界）；标注落 `data/coverage.json` 与 `coverage-counts.json`。
- prompt 断言：175 条法条短语 × 242 条 prompt 全部未出现，命中即停。

### 法的冲突审计

- `constitution/conflicts.md`：264 个叶子按动作对象分成 10 个已检查簇 + 16 个无候选对桶，
  68 对候选（优先级处境 10 / 平衡点 4 / 无关 54），真冲突 0——这个 0 只覆盖那 68 对。
- 机器可读的 `partition:` 块由 `constitution/audit_coverage.py` 解析，核对「完全且不相交」；
  分类以 `constitution/nodes.json` 为准。

## INFERRED

- **为什么用「签名」而不是文本相似度**：文本相似度会把同一动作的不同措辞判成不同，把不同动作的相同句式判成相同；
  签名把回答压成一个离散动作，才可能在 3 条抽样上算一致率。代价是签名解析失败会把动作读成「无动作」，
  所以 `countable_control`（可解析动作的比例）与主指标分开报——它不需要参照物，也不能被参照物的选择影响。
- **为什么格式与决策要拆开**：发出动作的比例与选对的比例是两个问题；不拆开时，
  「学会写工具行」会被读成「学会判断」。
- **为什么用精确 McNemar 而不是卡方**：不一致对只有 70–80 个，卡方近似在这么小的格子上不可靠。
- **为什么 2000 次自举**：够把区间端点稳定到 0.001 量级；再多的重抽只缩噪声，不缩偏差。
