kind:    report
from:    orient-nomos (package launched by root)
to:      root
spend:   idle-compute
id:      none — first contract, answered in the run final message

First orientation report, filed here by root. Body is the run report verbatim.

# Report — Contract N2 (anchor re-estimate at 9 draws, `nomos`)

**Node whose roadmap this changes:** `root` (the `nomos` milestone "make the instrument's failure falsifiable").
**Evidence pointer:** `report/sft-measurement.md:139-158` + `:255-266` (new 复算 section); `evidence/measure/anchor-draws9/{answers.jsonl,summary.json,per-situation.jsonl,run-meta.json,run.log}`; commits `fff3441`, `5859afc`, `12a4d12` on top of `a3797c4`.
**Decision needed:** four items in §5 — the stale 3-draw sentences elsewhere in the tree, the push, the missing AGPL text file, the spend-ledger row. The measurement itself needs no decision.

## 1. Verdict — one sentence

On the pre-specified primary metric (动作签名一致率, 148 situations, 9 draws per situation per arm), law-vs-nolaw is **0.0593 [0.0263, 0.0923] — the paired-bootstrap interval excludes 0**, so the ruler is salvageable and 0.0968 is now readable as distance toward the law; the text-level ruler (口径二, 99 situations) still spans 0 at 0.0303 [−0.0180, 0.0819].

| 口径一 (primary), n = 148, 9 draws | rate | 95% CI (paired bootstrap, 2000×, 2.5/97.5) |
|---|---|---|
| 不带法 DeepSeek (matched decoding) | 0.2605 | [0.2072, 0.3116] |
| 带法 DeepSeek (matched decoding) | 0.3198 | [0.2703, 0.3746] |
| **law − bare** | **0.0593** | **[0.0263, 0.0923]** — was 0.0496 [−0.0068, 0.1059] at 3 draws |
| post (adapter) / base | 0.0968 / 0.0023 | unchanged — recomputed from base/post only |

Why the flip is the draws and not a new metric: the point estimate moved 0.0097 while the interval width fell 0.1127 → 0.0661 (ratio 0.587 vs 1/√3 = 0.577), i.e. the old width was draw noise. Robustness: 5 bootstrap seeds all exclude 0 (narrowest [0.0263, 0.0916]); 0.015% of 20 000 replicates ≤ 0; analytic SE 0.0167 gives [0.0266, 0.0920], matching the bootstrap. `X = 0.0948 [0.0564, 0.1332]` and the format/decision decomposition are untouched (they use base/post only).

## 2. Spend — actual, beside the numbers

| | calls | ¥ |
|---|---|---|
| original batch (untouched) | 888 | 0.7115 |
| **this batch (draws 3–8, 1776 rows)** | **1776** | **¥1.4184** (off-peak; law ¥0.8796 / bare ¥0.5388; ¥0.000799/call) |
| whole anchor, 2664 calls | 2664 | **¥2.1300** |

Grant was ≈¥2.1 (2664 × recorded unit price); actual is +1.4%, inside the "more than a fifth" stop line (≈¥2.52). Staged to check price before committing: 20 situations × 2 arms × 6 draws = 240 calls cost ¥0.1983 (¥0.000826/call, cache warm) — projection ¥1.27 for the rest, so the remainder was allowed to run. All 2664 calls landed in the off-peak band. API time 04:23:42–04:28:40 UTC; whole contract ≈25 min wall-clock (limit 4 h).

## 3. What changed

- `scripts/measure_anchor.py`: `--draws N` (append-only, never re-draws the stored 3), `--situations K`, `--max-cny` (hard stop on new spend), `--allow-partial`. Extension rows go to `evidence/measure/anchor-draws<N>/`, so `anchor-matched/`'s 888 rows / ¥0.7115 / `pilot.json` are byte-identical — the paid evidence I was told to add to, not rewrite. `call_id` continues at `a0889`–`a2664` (unique across both files). Regression: `--analyse` (3 draws) still reproduces the committed `summary.json` and `per-situation.jsonl` exactly.
- `report/sft-measurement.md`: state line, protocol table, pilot-evidence paragraph, both metric tables, 结论 5–6, 能说明/不能说明, 修掉的问题 10, and a new 复算 section with commands, four sha256s and the spend paragraph. Every anchor citation in the file moved to the 9-draw number; the 3-draw number is kept inline as the earlier estimate of the same sample.
- Licence: `README.md:47` and `docs/model-card.md:85` now read **AGPL-3.0-only** (SPDX id + canonical URL); the model card names the base model's licence **Apache-2.0** with its obligations and the local-snapshot verification. Two more lines that said "仓库未声明许可" (`THIRD-PARTY.md:32`, `docs/data-card.md:73`) were corrected, because leaving them would state a falsehood in the very commit that decided the licence.

## 4. Verification run

- 296 (situation, arm) pairs, exactly 9 draws each, 2664 unique `call_id`s, 0 empty answers.
- `prompt_sha256` identical to base/post for **2664/2664** (the gate refuses otherwise); params only `0.7 / 0.95 / 320 / deepseek-flash`; bare `system_chars` = 0; law `system_sha256` = law's `325f8b3e…`; 42 truncations at 320 (1.6% vs 1.2% before).
- Re-running `--analyse --draws 9` reproduces all four artefacts byte-identically (`summary.json` `69d27635d832e268`, `per-situation.jsonl` `dfe0137f214deaf8`, `run-meta.json` `c749c1d2bf3d29b4`, `answers.jsonl` `fbd574357f560684`).
- `python3 scripts/measure_actions.py --check` — all 7 self-tests pass (metric unchanged, I did not touch it).

## 5. Decisions needed (nothing else waits on me)

1. **Stale sentences elsewhere still carry the 3-draw cross-0 claim** — `README.md:38`, `docs/model-card.md:77` (limit 6), `docs/paper/draft.md:15,91-92,126-129,174`, `docs/plan/plan.md:45`. They are outside my named scope and each now contradicts the report. Replacement text, ready to paste: 带法 0.3198 [0.2703, 0.3746]、不带法 0.2605 [0.2072, 0.3116]、差 0.0593 [0.0263, 0.0923]（9 条/处境/侧，含不含 0 的翻转说明；旧 0.0496 [−0.0068, 0.1059] 作 3 条时的前次估计保留）. The paper's abstract-level "这把尺子量不出法的作用" is the sentence that must change most carefully.
2. **Push.** My three commits are local, together with your three mail commits (`origin/main..HEAD` = 6). Pushing now would publish the stale README/model-card/paper sentences in (1) — publish is authorised, but I did not take that call.
3. **No AGPL text in the repo.** `licenses/` holds only `Apache-2.0.txt` and `gsm8k-MIT.txt`; the project's own convention ("许可原文落 licenses/") now has no file for the licence it declares. Fetch verified reachable (`https://www.gnu.org/licenses/agpl-3.0.txt` → 200). A new file was not in my named scope, so it is a finding, not done.
4. **Spend ledger.** `report/measurements.md:63` still lists the anchor batch as "888 / ¥0.7115"; the 1776-call ¥1.4184 batch needs its own row and the total recomputed (¥14.23 → ¥15.65 if nothing else changed). That file is another writer's area; `run-meta.json` carries the per-arm/per-price-band split needed for the row.

Minor, no decision: `mail/2026-10-21-answers.md` and `mail/2026-10-21-licence-and-grant.md` are now landed in commits and are addressed to `nomos`, so their deletion is `nomos`'s act, not mine. 口径二 remains unresolved by design — 0.0303 with a CI of width 0.10 at n = 99 would need another order of magnitude of situations, not draws; the 42/2664 truncations at 320 still have no measured suppression.