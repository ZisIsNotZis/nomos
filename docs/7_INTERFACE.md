# 接口与数据格式

## EXPLICIT

无。

## CONFIRMED

### 处境 `evidence/{slice-contrast,grow}/situations.jsonl`

```json
{"id": "SIT001", "signal": "...", "signals": ["..."], "session": "...", "window_id": "...",
 "turn_indices": [0, 1], "source_chars": 1200, "excerpt_chars": 900,
 "ends_with_user": true, "excerpt": "..."}
```

- `id` 固定且唯一（242 条 = 183 条 slice-contrast + 59 条 grow）；`excerpt` 是处境原文，**不含法条原文**。
- prompt = `excerpt` + `common.INSTRUCTION`（slice-contrast 的续写指令，DeepSeek 批次的原字节）。

### SFT 样本 `data/sft.jsonl`（366 = `sft-train.jsonl` 288 + `sft-val.jsonl` 78）

```json
{"situation_id": "SIT001", "session_id": "...", "prompt": "...", "target": "..."}
```

- 切分按**会话**：同一 `session_id` 不跨训练 / 验证（10 组，种子 20261020）。

### 回答记录 `evidence/measure/answers.jsonl`（每行一条抽样）

```json
{"model": "base|post", "situation": "SIT001", "draw": 0, "response": "...",
 "action_signature": "...", "coarse_signature": "...",
 "prompt_tokens": 812, "completion_tokens": 154, "finish_reason": "eos|length",
 "truncated": false, "prompt_sha256": "...", "temperature": 0.7, "top_p": 0.95, "seed": 20261031}
```

- 新版行还带 `max_new_tokens`；旧 1452 行没有这个字段，上限由撞上限的行反推（`cap_recorded`）。
- 主结果文件 `evidence/measure/answers.jsonl` 是 1452 行（242 × 3 × 2），**只追加**；
  试验件必须另开文件（`--answers`）。

### 逐处境 `evidence/measure/per-situation.jsonl`（242 行）

关键字段：`reference_signature`、`reference_votes`、`reference_usable`、`text_reference_usable`、
`base` / `post`（每处境 3 条抽样的命中率）、`base_text` / `post_text`、`base_agrees` / `post_agrees`、
`base_emits` / `post_emits`、`base_truncated` / `post_truncated`、`X_situation`。

### 汇总 `evidence/measure/summary.json`

字段分五组：

- 完整性：`situations_total`、`situations_paired`、`situations_{base,post}_{complete,partial}`、
  `situations_both_complete`、`generation_complete`、`coverage`、`n_pairs`、`n_pairs_insufficient`。
- 读数：`base_mean`、`base_ci`、`post_mean`、`post_ci`、`X`、`X_ci`、`X_status`、`X_headroom`、
  `bare_deepseek_mean`、`law_deepseek`。
- 口径：`countable_control`、`text_signature`、`action_comparable`、`decomposition`。
- 元数据：`decoding`（含实际上限）、`models`（`base` / `post` 的绝对路径）、`reference`、`reference_selection`。
- 审计：`status`（`final` / `preliminary`）、`answers_rows`、`answer_duplicates_dropped`、
  `stored_signature_mismatches`、`truncated_answers`。

### 见过 / 留出 `evidence/measure/seen-heldout.json`

`what`、`source`、`situation_counts`、`paired_all` / `paired_seen` / `paired_held_out`（每块含
`situations_paired`、`base_mean`、`post_mean`、`delta`、`delta_ci`、`X`、`X_ci`、`decomposition`、
`countable_control`）、`caveat`。脚本断言 `paired_all` 与 `summary.json` 头行逐字段相等。

### 通用能力配对 `evidence/benchmark/paired-<suite>.json`

`suite`、`status`、`n`、`base` / `adapter`（`correct`、`accuracy`、`ci95_wilson`）、
`delta_adapter_minus_base`、`delta_ci95_paired_bootstrap`、`paired`（`drops` / `gains` / `drop_ids` /
`gain_ids` / `unchanged` / `mcnemar_exact_p`）、`detectable`、`harness`（四个配对字段 + `adapter_dir`）、
`elapsed_seconds`。

### 官方 grader `evidence/benchmark/official/official-ifeval.json`

`what`、`vendored`（pin 与文件哈希）、`inputs`、`n`、`rules`、`item_level_ruler_disagreement`、
`per_checker_disagreement`（逐检查器分歧槽数）、`named_detail`、`drop_gain_arithmetic`、
`determinism`（种子与三次运行的产物哈希）、`ours_ruler_check`。

### 命令行契约

| 命令 | 读 | 写 | 退出码 |
| --- | --- | --- | --- |
| `scripts/measure_actions.py --analyse` | `answers.jsonl`、`densify/answers.jsonl` | `summary.json`、`per-situation.jsonl`（仅当两侧齐全；否则拒绝） | 0 / 非 0 |
| `… --generate` | 处境、`densify` | `answers.jsonl`（追加，可续跑） | 0 / 非 0 |
| `… --check` | 假数据 | `selftest.json` | 全过才 0 |
| `… --adapter-dir / --answers / --out-dir / --max-new-tokens` | — | 改写上面四条路径与生成上限 | — |
| `scripts/measure_split.py` | `per-situation.jsonl`、`summary.json`、`data/sft-{train,val}.jsonl` | `seen-heldout.json` | 断言不过则非 0 |
| `evidence/benchmark/analyse_paired.py [suite] [--adapter-tag T] [--out-tag T]` | `base-<suite>.json`、`<adapter-tag>.json` | `<out-tag>.json` | 有未跑格则 1 |
| `scripts/run_bench.py --suite … --model … --tag …` | 冻结样本 `data/bench/` | `evidence/benchmark/<tag>.json` | 0 / 非 0 |
| `scripts/check_axes_claim.py` | 六个发布面 | 无（只打印） | 违规则 1 |
| `evidence/benchmark/official/grade_official.py` | 590 份落盘输出 | `official-ifeval.json` | 0 / 非 0 |

## INFERRED

- **命名规则**：落盘件用 `base-<suite>.json` / `adapter-<suite>.json` / `paired-<suite>.json`；
  试验件在名字里带自己的标签（`adapter-e2-…`、`paired-e2-…`），不许占用落盘名。
- **分析脚本不判分**：`analyse_paired.py` 的 `correct` 直接从记录读，重算判定会变成第二把尺子；
  只有 `official/` 那一路是独立判分，且必须钉种子。
- **`per_instruction` 是记录，不是统计来源**：它是 `dict(zip(...))`，同名指令互相覆盖
  （`ifeval-2069` 因此 `correct=False` 而所有指令都写 `True`）。要做指令级统计得重算（见 Q6）。
- **兼容性**：`summary.json` 的字段只增不删；旧字段一旦改名，`--analyse` 重跑就不再逐字节复现，
  所以改名要走一次版本化的迁移。
