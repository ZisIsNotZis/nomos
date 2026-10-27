# 2-epoch 适配器的政策测量（M6 第 2 条指向的那一包）

同一把尺子（三点测量的 242 条处境、同一 prompt、同一套解码、同一份带法参照物），
只有 post 侧换成了 2-epoch 适配器。读法与注意事项在 `evidence/reports/sft-measurement.md`
的「2-epoch 适配器：同一把尺子上的第二个 post」；IFEval / GSM8K 那一轴在
`evidence/reports/sft-benchmark.md` 与 `AGENTS.md` 的 M6。

## 怎么重跑

```bash
bash evidence/measure/run_e2_policy.sh     # 可续跑：已落盘的键会跳过
```

脚本先拷 base 侧、再生成 post 侧、再分析、再拆见过/留出，最后往 `inbox/` 写完成信。
生成用 `scripts/measure_actions.py --generate --adapter-dir .tmp/sft/adapter-e2
--answers evidence/measure/e2/answers.jsonl --max-new-tokens 320`；分析用
`--analyse --adapter-dir .tmp/sft/adapter-e2 --answers … --out-dir …`。

## 上限为什么是 320

落盘的 base / post 两批是 320 上限下的生成，按 person 2026-10-23 的决定不重抽。
这一包要与落盘的 base 侧逐条配对，所以新生成的 post 侧也只能跑 320——否则两侧上限不同，
差值会把 base 侧那 23 条撞上限算成它的低估。新套件（不配对的生成）才用默认的
「最长合法输出的十倍」3110。

墙钟 **43 min 47 s**（2026-10-26T12:24:20Z → 13:08:07Z，单进程生成 726 条，含加载基座）。

## 产物

| 文件 | 是什么 | 行数/大小 | sha256 |
| --- | --- | --- | --- |
| `answers.jsonl` | base 侧 726 条（与 `evidence/measure/answers.jsonl` 的 base 行逐字节相同）+ 2-epoch post 侧 726 条 | 1452 行 | `d8a7e0f541b0d10d…` |
| `summary.json` | 与落盘 `summary.json` 同一套字段；`models.post` 指向 `.tmp/sft/adapter-e2` | 8.4 KB | `1304f335c5b2dc49…` |
| `per-situation.jsonl` | 逐处境，含 `post` / `post_text` / `post_emits` 与 base 侧同一批字段 | 242 行 | `bd64cf1e9306e49c…` |
| `seen-heldout.json` | 见过 113 / 留出 35 的拆分（`paired_all` 与 `summary.json` 头行逐字段相等是脚本里的断言） | 3.6 KB | `074b61e16648150b…` |
| `logs/` | `generate.log`、`analyse.log`、`split.log`；`driver.log` 是修好之后那次重跑，`driver-first-run.log` 是第一次跑的原文（当时 start 行用 `tee` 而非 `tee -a`，被重跑覆盖） | — | — |

## 两个已修的缺口（不改任何数）

1. **元数据写了别的适配器。** 第一次跑时分析那一步漏了 `--adapter-dir`，数字是 2-epoch 的、
   `summary.json` 的 `models.post` 却写成 `adapter-narrow`。现在 driver 给分析和生成都传
   `--adapter-dir`，并在分析之后断言 `summary.models.post` 等于本试验的适配器路径（不过就退出）。
2. **完成信写不出来。** 收信那一段用了 `summary["delta"]`，而这个脚本把 Δ 放在
   `decomposition` 里，于是 `KeyError: 'delta'`、信没落地（driver 仍以 0 退出）。现在从
   `decomposition` 取，并把 `models.post` 一起写进信里。

两处都只动「怎么把结果写出来」，不动生成与统计；上面五个文件的 sha256 是修好之后重跑出的那一份。
