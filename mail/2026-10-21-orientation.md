kind:    report
from:    orient-nomos (package launched by root)
to:      root
spend:   idle-compute
id:      none — first contract, answered in the run final message

First orientation report, filed here by root. Body is the run report verbatim.

Report follows. I read only `/home/z/vibe/nomos`, plus the one cited external path (`constitution/lock.yaml` names `/home/z/vibe/AGENTS.yaml`, which does not exist — see finding F4). Nothing was written inside the project.

---

# Nomos — orientation report

**Report kind:** completion (orientation package, no decision pending on the work itself; one charter decision named in §C)
**Node whose roadmap this changes:** `nomos`
**Evidence pointer:** `report/sft-measurement.md:139-160,236-247`, `report/sft-benchmark.md:99-115,132-140`, `docs/method/design.md §1,§7`, `docs/plan/plan.md:3,55`, `evidence/measure/summary.json`, `constitution/lock.yaml`, plus the reproduction in §D.

## A. What the project is

`nomos` (HEAD `bdbbe31`, 39 commits, working tree clean, `origin/main..HEAD` = 0) compresses one person's operating law — `constitution/AGENTS.yaml`, 264 leaves, frozen at sha256 `68801dae…`, verified this session against `constitution/lock.yaml` — into a 2.21 B model (`Qwen/Qwen3.5-2B`, 4-bit QLoRA, narrow LoRA r=16, 10.9 M trainable params), using 288 training / 78 validation samples drawn from 242 real situations, and then measures whether *decision behaviour* moved, not just surface format.

It answers no, mostly, and it says so:

- Format moved hard: parseable tool-line 5.6% → 75.2%.
- Action agreement against the law-bearing reference: 0.0023 → 0.0968, Δ 0.0946 [0.0586, 0.1351], n = 148/242.
- But the gain decomposes 29.4% format / 5.3% decision (interval spans 0) / 65.3% interaction, and the text-level metric does **not** support "decisions got closer" (Δ −0.0473 [−0.1085, 0.0118]).
- The ruler is the binding limit: under matched decoding, the reference *with* the law scores 0.3311 and *without* it 0.2815, diff 0.0496 [−0.0068, 0.1059] — the instrument cannot resolve the law's own effect, so "how much law effect was internalised" has no denominator.
- Generic-capability cost: no credible drop detected, but only n=20 (GSM8K 75.0→65.0, IFEval 60.0→40.0, both intervals span 0), with a stated detection floor of 20–25 pp.

It is a single-user, single-law, single-model study, not alignment research, not RLHF, not a benchmark paper; the README, model card, data card and `docs/method/limits.md` all hold that line. Its state is **publish-ready but undistributed**: adapters live only in `.tmp/` (ignored by git, 274 MB), registered in `artifacts.tsv` by hash plus a regeneration command; all three hashes verified this session.

## B. The milestone it proposes next

The project declares **no milestones at all** — `docs/plan/plan.md:3`: "全线是工作包，不是里程碑：没有用户确认点". All six work packages are marked 完成. So the next milestone is not written down anywhere; I propose it, and I name the two candidates the evidence actually supports.

**Proposed milestone (primary): make the instrument's failure falsifiable before spending anything larger on it.**

Reopen the matched anchor at more draws per situation — 148 situations × 2 conditions × 9 draws ≈ 2 664 calls, ≈ ¥2.1 at the recorded price of the 888-call run (¥0.7115).

- Why this one: the main claim is currently undecidable, and the decision to abandon it rests on a 3-draw estimate. Everything else in the tree is complete; this is the one open question whose answer changes what the project *is*. It is also not a metric swap — it is the same metric with less sampling noise, so it does not violate `docs/method/design.md §7` ("训练后 X_d 的变化盖不过噪声时，如实写负结果，不改题、不换指标").
- Acceptance (observable): the anchor pair re-estimated with ≥9 draws per situation, reported with the same paired bootstrap; either the law-vs-nolaw diff excludes 0 (the ruler is salvageable and the adapter's 0.0968 can be read as "how far toward the law") or it still spans 0 (the project's conclusion stands as final and the paper closes as a negative result on the instrument).
- Evidence pointer that this is the live question: `report/sft-measurement.md:156` (0.3311 vs 0.2815, 0.0496 [−0.0068, 0.1059]) and `:243` ("X 在这份数据上不是独立信息"); noise floor is measured, not assumed — same prompt at temperature 0 differs in 42–51% of resampled actions (`docs/paper/draft.md` limit 8), and 5-draw majority stability is only 0.808 (`docs/plan/backlog.md`).
- Spend: `metered-compute`, ≈¥2.1, plus minutes of wall-clock. **Needs a grant** — this is the one line my contract cannot cross.

**Proposed milestone (fallback, if the above is refused): finish the capability axis to its contracted n.**

- What is missing: the plan says the benchmark work package is "完成本轮约定的一半" — n was cut from the contracted 100 to 20 because 23.3–35.9 s/item did not fit a 25-minute budget (`docs/plan/plan.md:55`). Eight cells are explicitly 未跑 with copy-pasteable commands, estimated ≈4.5–5 h, in `report/sft-benchmark.md:99-115`.
- Acceptance: four cells at n=100, base and adapter on the same `--limit` and same serial/parallel mode, paired intervals plus a stated detection floor; each number recomputable from the committed logs.
- Why it is the fallback and not the primary: it can only ever say "still no credible drop", and the report itself states n=20 sees nothing below ≳20 pp while 10 pp needs n≥150 per cell (`report/sft-benchmark.md:118-124`). Five GPU-hours buy a floor, not a finding.
- Spend: `idle-compute` on a 4090 that is currently free (1 343 MiB of 24 564 MiB used), inside the window before GPU availability becomes unconfirmed (2026-10-31; today is 2026-10-21).

**Explicitly not next:** any further decision measurement on the current instrument. `design.md §7` bars changing the metric, and §B primary is the only remaining move that is neither a metric swap nor a re-run.

## C. What it cannot answer

**Q1 — Publish, and under what licence.** (kind: `cost`, routes to the person.)
Tried: `grep -rn -iE "许可未|尚未声明许可|待决|授权|license" README.md docs artifacts.tsv THIRD-PARTY.md` → 17 hits, of which exactly two record a decision field, and both record it as undecided: `README.md:47` and `docs/model-card.md:85` ("待决项，不是默示授权"). `artifacts.tsv` says durable_location = "none" for all three adapters. The publish commit message states Zenodo / Hugging Face / GitHub release each need authorisation and none was done.
Reopens on: the author stating a licence for the repo's own code and docs, and granting or refusing upload consent. Nothing in the tree can be read as consent.

**Q2 — Is the ruler's failure a property of the law or of the sample size?** (kind: `direction`, needs a metered grant before it can even be asked.)
Tried: three parallel metrics (action signature, text-level decision signature, comparable-action subset), a matched-decoding anchor of 888 calls with prompts sha256-verified identical to base/post, position-swap judging, a draw-noise study, and a rubric that was stopped under §7 when it could not separate the two known levels. None separated law from no-law. Remaining untried lever, stated by the project itself: more draws per situation (3 → 9), which is a sampling fix rather than a new metric.
Reopens on: the §B primary result. If it still spans 0, this closes permanently and the paper ends on the instrument, not the model.

**Q3 — Can an agentic axis be attached offline?** (kind: `contract`.)
Tried: the selection table at `report/sft-benchmark.md:132-140` records a per-candidate offline verdict from actual attempts — `huggingface.co` and PyPI unreachable (curl timeout), MMLU blocked on `pyarrow` with only local parquet, HumanEval blocked on docker/no data, BFCL blocked on HF data plus a thousand-line harness. The claim in `design.md §1` includes "agentic 能力不跌出自身噪声带", so **that half of the claim currently has zero measurement** — the strongest unstated gap in the tree.
Reopens on: network access at package-install time (`pyarrow`), a local BFCL harness, or a decision to narrow the claim in §1 to the two axes actually measured.

**Q4 — Two documentation defects found while orienting** (no decision needed, recorded for the next writer):

- F1: `constitution/lock.yaml` records `upstream: /home/z/vibe/AGENTS.yaml`; that path no longer exists (`ls` → No such file). The frozen copy still validates against the lock's own sha256 (`68801dae…` = `constitution/AGENTS.yaml`), so the pin is sound but its stated origin is stale after the law moved to `agent-policy/`.
- F2: README's constant "约 3.3 秒" does not reproduce today — measured **4.88 s** from a clean `git archive` in `/tmp` (see §D). The numbers it produces do reproduce exactly. Treat 3.3 s as machine-load-dependent, not as a property of the tree.

## D. What I verified (read-only; nothing written inside the project)

| check | command | result |
|---|---|---|
| HEAD reproducible from git alone | `git archive HEAD \| tar -x -C /tmp/…` then `python3 scripts/measure_actions.py --analyse` | printed `n_pairs 148/242（覆盖率 0.612）；两侧都齐全 242/242；参照物可用 148 条；文字层参照物可用 169 条` — byte-for-byte the README's claimed first line |
| headline numbers | same run, `evidence/measure/summary.json` | `base_mean 0.0022522…`, `post_mean 0.0968468…`, `n_pairs 148` — matches README's 0.0023 / 0.0968 |
| timing claim | `/usr/bin/time -f '%e'` on the same command | **4.88 s** vs README's recorded 3.28/3.33 s (F2) |
| adapters still exist and are unmodified | `sha256sum .tmp/sft/adapter-narrow/… .tmp/sft/adapter-wide/… .tmp/training/adapter-dpo-r16/…` | all three match `artifacts.tsv` exactly (`5be6a2f3…`, `580509c8…`, `bfe5dc07…`) |
| law pin intact | `sha256sum constitution/AGENTS.yaml` vs `constitution/lock.yaml` | `68801dae…` — match |
| tree durable | `git status --short`; `git rev-list --count origin/main..HEAD` | empty; 0 — committed and pushed |
| GPU available for the fallback | `nvidia-smi --query-gpu=…` | RTX 4090, 1 343 / 24 564 MiB used |

Temporary archive under `/tmp` removed after use.

## E. Residual risks

- The primary proposal spends metered API money (≈¥2.1); it is a grant, not a unilateral act, and I did not make any call.
- F2 means the README's reproducibility claim should be re-worded to "≈3–5 s, load-dependent" or the two numbers re-recorded; a reader timing it will otherwise think the tree drifted.
- The §1 claim remains half-unmeasured (Q3) regardless of which milestone is chartered, so any release text that repeats "通用与 agentic 能力不跌出噪声带" overstates what exists.
- If GPU availability ends after 2026-10-31, the fallback milestone becomes `resource`-blocked and only the primary (API-only) remains runnable.