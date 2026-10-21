## Verdict: PASS — M4 is met at `5ba9a2e`, with three documentation defects that do not move the headline

### Base revision used, and why
`0b04e04` (`node: 落地「跑官方 grader 再冻」那封信，删信…`) — the parent of `e1cd6d8`, the first commit that lands M4's artefact. The advance is exactly `0b04e04..5ba9a2e`, **12 commits**: `e1cd6d8, 6ede844, e23990b, 38edba4, f8efc84, fd6741f, 2c94f1f, 054f20a, 96d5ef2, acf9a9a, fb9a049, 5ba9a2e`. `e1cd6d8` is the only commit in that range that touches `evidence/benchmark/official/` code or artefact; `grade_official.py` and `official-ifeval.json` have the same blobs at `5ba9a2e` as at `e1cd6d8`.

### Acceptance read from the project's own plan
`AGENTS.md` §roadmap → 里程碑 → **M4**, observation line “观测（决定它成没成）”: artefact gives official strict/lax base/adapter counts, paired diff and interval, McNemar p, per-checker disagreement table; `report/sft-benchmark.md` and the three reference surfaces (`README.md`, `docs/model-card.md`, `docs/paper/draft.md`) write this row. I did **not** use `docs/plan/plan.md` for this: it names no M4 and declares itself a historical work-package snapshot, not the roadmap.

### What I ran (at `5ba9a2e`) and what came back
Exact documented command, run in an extracted copy of `5ba9a2e` (`git archive 5ba9a2e`, `/tmp/m4review`) so the review writes nothing in the project:

```
/home/z/.local/bin/uv run --no-project --with nltk --with langdetect --with immutabledict \
  --with absl-py python3 evidence/benchmark/official/grade_official.py
```

| run | rc | wall | artefact sha256 |
|---|---|---|---|
| 1 (cold uv env) | 0 | 21.72 s | `01d94585…34c145` |
| 2 | 0 | 14.53 s | same |
| 3 | 0 | 11.83 s | same |
| 4 | 0 | 8.86 s | same |
| 5 | 0 | 8.44 s | same |

The committed artefact at `5ba9a2e` is `01d9458544c1773f7a8c06f9fb618c617ed2655e26b70f3341437b99834bc145`; every run reproduced it byte-for-byte, and the source tree is untouched (`git status --short` empty). Also ran `dump_disagreements.py` (the reading aid `RUN.md` names): rc=0, 56 slot-level disagreements printed, matching the artefact’s 56.

**Provenance:** the artefact’s `inputs.*_sha256` match the actual `data/bench/ifeval.jsonl`, `base-ifeval.json`, `adapter-ifeval.json` at this revision; all six vendored-file sha256 match `VENDOR.md`; `ours_ruler_check` is 590/590 with zero mismatches. So the claim rests on an artefact this revision’s code produces.

### Numbers checked against the artefact (all match the report and all three reference surfaces)
| ruler | base | adapter | Δ | paired 95% | drops/gains | McNemar p |
|---|---|---|---|---|---|---|
| official strict | 196/295 | 160/295 | −12.2034pp | [−17.627, −6.780] | 55 / 19 | 3.3768e-5 |
| official lax | 196/295 | 163/295 | −11.1864pp | [−16.949, −5.424] | 55 / 22 | 2.1680e-4 |
| ours (control) | 184/295 | 148/295 | −12.2034pp | [−17.627, −6.780] | 54 / 18 | 2.5687e-5 |

Per-checker table sums to 836 slots: 45 ours-stricter + 11 ours-looser + 780 agree; `number_paragraphs` 30 + 3 = 33/40; `json_format` 7, `forbidden_words` 6, `change_case` 4+3=7, `number_words` 1, plus `startend:end_checker` 1 and `combination:two_responses` 1 = 56. The ours row is identical to `evidence/benchmark/paired-ifeval.json` (184/148, same CI endpoints, 54/18, p 2.5687e-5). The report’s 50/54 survive-as-drops, 0 become-gains, 16/18 survive-as-gains all match `drop_gain_arithmetic`.

### Defects found (documentation; none changes the headline)
1. **`AGENTS.md:23` (the M4 milestone bullet) still says `number_paragraphs` “30 / 40 槽”** — the single-direction count the review ordered fixed elsewhere. With the other families it sums to 51, not the 56 stated in the same bullet. The same file’s fact bullet at line 56 already says 33/40, and the report/paper/README/model-card say 33/40. Reproduction: `grep -n number_paragraphs AGENTS.md` returns both 30/40 (line 23) and 33/40 (line 56); artefact `per_checker_disagreement.by_instruction_type.length_constraints:number_paragraphs` gives 30 + 3.
2. **`AGENTS.md:7` and `AGENTS.md:13` say `mail/` does not exist**, but at `5ba9a2e` `git ls-tree -r --name-only 5ba9a2e mail/` returns `mail/2026-10-21-m4-official-grader.md`. The entry text contradicts the tree.
3. **Timing claim “6.5–11 s” does not hold cold.** Warm runs are 8.4–8.9 s (and the project’s recorded 6.62/9.76 s), inside the claim; the first run on a cold `uv` cache took 21.72 s and the next two 14.53/11.83 s. The claim includes “含 uv 启动开销”, so a first-run reader on an empty cache sees more than 11 s.

### Blocking
None for the M4 headline: the official strict/lax numbers, intervals, p-values and disagreement structure reproduce from the artefact and from the named command. What *would* be unsafe is citing the roadmap as clean while `AGENTS.md:23` keeps the 30/40 that sums to 51 — that sentence should not travel into a release; it does not, however, reopen the acceptance.

### Residual risks
- The three “attack surfaces” the project itself lists remain, and are correctly listed: single seed-0 greedy path; the drop concentrated in format-type instructions; official-strict base Wilson upper bound 71.6% vs the 70% band upper edge. These are judgement/convention, not data loss.
- Timing claims are host-dependent; cold-cache reproducibility is unverified on a clean machine.
- The 11 hand-read rows are a human judgement (7/3/1); I verified the count of 56 slots and the table arithmetic, not the reading of the 11 outputs.