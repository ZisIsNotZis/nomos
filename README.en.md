<p align="center"><img src="assets/logo.svg" alt="nomos" width="200"></p>

[简体中文](README.md) | **English**

# nomos

SFT a personal operating constitution into a 2B model's weights — then measure whether it actually landed, and what it cost in general ability.

**A 264-leaf personal operating law (an `AGENTS.yaml`) is compressed into a 2.21 B model with 288 samples drawn from 242 real situations, and three things are then measured with one ruler: how much closer the model's behaviour sits to that law, how much of that closeness survives on situations it never saw, and what general ability (GSM8K, IFEval) paid for it.** This is not "make the model smarter". It turns one person's written rules into a measurable training run: the law is readable text, the training is a re-runnable script, and every conclusion is a number with an interval and a detection floor that points back to the raw output on disk.

## Quick start

```
git clone https://github.com/ZisIsNotZis/nomos.git
cd nomos
python3 scripts/measure_actions.py --analyse
```

Pure CPU, standard library only, no network, no GPU. Measured on the author's machine at **3.17–3.33 s** (9 timings, Python 3.12.3, 12 cores; `/usr/bin/time -f '%e'`, including interpreter startup; both the working tree and a fresh `git clone` fall inside that range). It is slower when the machine is loaded, and that case was not measured this round — so this is the measured range, not an upper bound. Per-run readings and conditions are recorded under "发布准备" in [`evidence/reports/plan-historical.md`](evidence/reports/plan-historical.md).

It recomputes the headline metric from the evidence already committed in the repo, and prints as its first line:

```
n_pairs 148/242（覆盖率 0.612）；两侧都齐全 242/242；参照物可用 148 条；文字层参照物可用 169 条
```

followed by the full `summary.json` (`base_mean` 0.0023, `post_mean` 0.0968, Δ with a per-situation paired bootstrap interval, the three readings, and the format/decision decomposition). It rewrites `evidence/measure/summary.json`: inside this repository the result is byte-identical (`git status` is clean afterwards), and the only field that changes is the absolute path in `models.*` — so a clone elsewhere will show that clone's paths.

Retraining or regenerating needs a GPU: `python3 scripts/train_sft.py --epochs 3 --grad-accum 8 --lora-r 16 --lora-alpha 32 --lora-targets narrow --adapter-dir .tmp/sft/adapter-narrow` (about 14 minutes on one 4090), and `python3 scripts/measure_actions.py --generate` (3 samples per model). Full reproduction notes live in [`docs/9_IMPLEMENTATION.md`](docs/9_IMPLEMENTATION.md) and the reports.

## Result (one paragraph)

The adapter learned to write tool lines (5.6% → 75.2%) and action agreement went from 0.0023 to 0.0968. All 148 situations in that number come from the same pool the training data was built from; split apart: **seen in training** 113 pairs, Δ +0.1091 [0.0678, 0.1593]; **held out by session** 35 pairs, Δ +0.0476 [0.0095, 0.0857]. On the held-out side parseable tool lines went 6.7% → 80.0% — so "write the tool line" transferred, while "pick the right action" transferred only about four tenths as much. Of the gain, 65.3% is an interaction term and the decision term alone holds 5.3% with an interval crossing zero, so the text-layer reading does not support "the decisions became the law's". General ability splits in two: GSM8K at **n=100, +3.0pp, interval crossing zero** — no decrease detected; **IFEval at n=295, −12.2pp, [−17.6, −6.8], interval excluding zero — a decrease was detected** (184/295 → 148/295, 54 down / 18 up, McNemar p=2.57e-5; that p is uncorrected for multiple comparisons, and under Bonferroni α=0.025 it clears the line by about three orders of magnitude). The n=100 round hinged on two "at least N words" items that a 2- and a 5-word flip would have turned into p=0.064; that sensitivity now belongs to n=100 only. At n=295, flipping those two items — or all 7 length items — still leaves p<0.001, and pushing p back outside 0.025 would need 19 of the 54 drops flipped, more than the largest single family (11 comma bans) holds. Reading the drops one by one, they sit on two surface axes, punctuation shape and length (the 11 comma bans first, then 7 length floors), and **"the answers got shorter" does not explain them on its own**: shortening happens on 63.7% of items but on only 52% of the 54 drops; median word count for IFEval went 185 → 130; the detection floor is 1.7pp. n=295 is not a second independent reading — it is the same reading with the denominator raised from 100 to 295, and the first 100 items are byte-identical to the n=100 run, so agreement between the two versions is arithmetic, not corroboration.

The ruler is validated before it is used: under the same protocol, law-carrying answers score 0.3198 and bare answers 0.2605, a difference of 0.0593 [0.0263, 0.0923] excluding zero (9 draws per situation per side), so the ruler does separate "read the law" from "did not". But the reference is only 0.3198 self-consistent under that same decoding, so 0.0968 reads as "how far from this particular reference", not "what fraction of the law's effect was recovered".

The IFEval cell was recomputed with Google's official grader (pinned at `e6890f85`) over the same 590 outputs: **196/295 → 160/295, −12.2pp, [−17.6, −6.8], 55 down / 19 up, p=3.38e-5** (lax: −11.2pp, p=2.17e-4), so the negative sign is not an artefact of our own ruler. The two rulers do disagree item by item (56 of 836 instruction slots), and hand-reading 11 of them gives 7 for the official grader, 3 for ours, 1 a wording question — but swapping rulers only changes which of the 74 disagreements you see, not the conclusion.

A 2-epoch trial adapter (M6, a pre-registered trial) narrows the IFEval drop from −12.2pp to **−7.8pp [−13.2, −2.7]** (the third epoch explains at least 4.4pp), while the policy headline for the two adapters directly paired is **−0.0023 [−0.0338, +0.0270]** — indistinguishable. Whether to swap the shipped adapter is the author's call (Q11); until then the 3-epoch adapter is what the repo reports.

## What it can do today

- **Recompute the headline metric** — `scripts/measure_actions.py --analyse` reads committed answers only, pure CPU, 3.17–3.33 s, rewrites `evidence/measure/summary.json` and prints the header line.
- **Split into "seen in training" and "held out by session"** — `scripts/measure_split.py`, same resampling code and seed, asserting that `paired_all` and the `summary.json` header agree field by field.
- **Retrain the narrow LoRA** — `scripts/train_sft.py` (4-bit QLoRA; `q/k/v/o` plus MLP, 96 modules, 0.79% of base parameters trainable).
- **Regenerate the policy-axis samples** — `scripts/measure_actions.py --generate` (base / post / matched anchor share one prompt and one decoding; resumable, already-written keys are skipped).
- **Run both general-ability suites and pair them** — `scripts/run_bench.py --suite {gsm8k,ifeval} --model {base,adapter}` plus `evidence/benchmark/analyse_paired.py` (pairs items, not whole runs).
- **Hand the cell to a reference implementation** — `evidence/benchmark/official/grade_official.py`, using the vendored Google `instruction_following_eval`.
- **Self-checks and gates** — five offline checks (see "Development"), including `scripts/check_axes_claim.py`, which reads only the publish surfaces and fails on any sentence that treats an unmeasured axis as measured.
- **Mine new situations** — `mining/scan.py` pulls minimal fragments out of session archives; `mining/check_redaction.py` is the redaction gate.
- **The frozen law** — `constitution/` holds 264 leaves, the node index, the classification program, shape checks and a conflict audit (`verify_gate.py` runs five fixtures).

## Architecture

One data flow, five subsystems: the law is frozen, situations are mined, pairs and SFT samples are built, the model is trained, and two axes are measured — every artefact lands in `evidence/` next to the script that produced it, so each number can be recomputed from what is on disk. Analysis and training share no code: training is transformers + PEFT, measurement only reads committed answers, and sharing would drag a GPU dependency into analysis.

```
constitution/ (frozen law)    mining/ + evidence/densify/ (situations, dual answers)
        │                              │
        └──────────────┬───────────────┘
                       ▼
              data/ (pairs, coverage, SFT samples 366/288/78)
                       ▼
              scripts/train_sft.py ──► .tmp/sft/adapter-* (weights, not in git)
                       ▼
   ┌───────────────────┴────────────────────┐
   ▼                                        ▼
scripts/measure_actions.py            scripts/run_bench.py
(policy axis: base / post / anchor)   (general axis: GSM8K / IFEval, base / adapter)
   ▼                                        ▼
evidence/measure/                     evidence/benchmark/
   │                                        │
   └──────────► evidence/reports/ (derivations, item by item) ◄── evidence/benchmark/official/ (official grader)
```

- **Comparisons only happen on one frozen prefix**: if `limit`, `seed`, `frozen_sha256` or `decoding` differ at all, `analyse_paired.py` refuses the comparison.
- **Trial runs may not overwrite committed artefacts**: new runs use `--tag` / `--adapter-tag` / `--out-tag` to claim a new output name; `evidence/measure/summary.json` and `evidence/benchmark/paired-*.json` are frozen deliverable evidence.
- **Scoring code has exactly one home**: the checkers in `scripts/bench_suites.py` are the repo's ruler; `per_instruction` is a record layer only and is never a statistical source.
- **One home per fact**: current numbers live only in [`docs/2_GOAL.md`](docs/2_GOAL.md), claims and boundaries only in [`docs/5_PRODUCT.md`](docs/5_PRODUCT.md), derivations in `evidence/reports/`.

## What this is not

- Not general alignment research and not about frontier models: one 2B model, one user, one law.
- Not RLHF on human preference labels: the preference pairs are derived from the policy.
- Not "this law is better than another": it is one user's operating law, and what is measured is "closer to it", not "more correct".
- Not a benchmark paper: the external suites answer only "did anything drop" — GSM8K n=100 (detection floor 4–5pp), IFEval n=295 (detection floor 1.4–1.7pp). Those are the only two axes; the agentic axis was not measured.

## Limitations

- One user, one law, one model size (2.21 B). Change the law and this adapter no longer holds by default.
- 288 training samples over 242 situations; 151 situations carry only one kind of decision; coverage is 77 of 175 trainable rules (a lower bound).
- The narrow LoRA attaches only to `q/k/v/o` (6 full-attention layers) and the MLP (24 layers); the 18 linear-attention projections are left out — the wide variant retrained worse, so this is a choice, not a gap.
- Agreement is computed on 148 of 242 situations (94 have no determinable reference) and cannot be extrapolated beyond them; it measures "how much like the law-carrying DeepSeek answer this is", not correctness.
- The IFEval cell is not comparable with published numbers: the sample is 295 of 541 items, and the score of the same outputs depends on the ruler — official strict 66.4% → 54.2%, this repo's 62.4% → 50.2%, with the same difference interval either way. The official grader is not reproducible on its own unless the `langdetect` seed is pinned (±1 item).
- The ruler measures distance from a reference, not the share of the law's effect recovered: under the same protocol 0.3198 vs 0.2605, difference 0.0593 [0.0263, 0.0923] excluding zero (9 draws per situation per side); at 3 draws the same difference is 0.0496 [−0.0068, 0.1059], crossing zero, and that width is sampling noise (interval width shrinks by 1/√3). The reference is only 0.32 self-consistent, and the second text-layer reading still crosses zero (0.0303 [−0.0180, 0.0819]).
- Weights are not in git (`.tmp/` is a disposable area); only sha256 and regeneration commands are recorded in [`artifacts.tsv`](artifacts.tsv).
- The full list: "边界" in [`docs/5_PRODUCT.md`](docs/5_PRODUCT.md) and "已知限制" in the [model card](card/model-card.md).

## Development

The analysis side needs only Python 3.12.3 and the standard library — nothing to install. Training and generation need a GPU: one RTX 4090 (24 GiB), torch 2.14.1+cu130, transformers 5.20.1, peft 0.21.2, bitsandbytes 0.50.2, with the base model from a local HF snapshot of `Qwen/Qwen3.5-2B` (revision `15852e8c…`, see the [model card](card/model-card.md)). Environment details are in [`docs/9_IMPLEMENTATION.md`](docs/9_IMPLEMENTATION.md).

Checks that need no GPU (each fails with a non-zero exit code):

| Check | What it covers |
| --- | --- |
| `python3 scripts/measure_actions.py --check` | bootstrap interval, X, and the format/decision decomposition on fake data |
| `python3 scripts/measure_split.py --check` | the seen/held-out split against the committed artefact, field by field |
| `python3 scripts/bench_selftest.py` | suite judges: hand-computed cases, the gold/wrong/garbage stub paths, empty output counted `unscorable` |
| `python3 scripts/check_axes_claim.py` | publish surfaces: every sentence about an unmeasured axis says so |
| `python3 constitution/verify_gate.py` | five fixtures for the classification program |

There is no linter or formatter configured (`python3 -m py_compile` is the only syntax gate). Running the analysis rewrites `evidence/measure/summary.json` byte-identically inside this repo; `evidence/measure/anchor-draws9/run.log` and `evidence/benchmark/logs-*/driver.*` append while a run is live, which is why they are allowed to show up in `git status`.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md): a number is only a number if it reproduces, changes come with evidence pointers, and long runs belong on a detached driver.

## Roadmap

**Done**: M1 (matched anchor at 9 draws per situation per side; law minus no-law excludes zero), M2 (general-ability cells raised to n=100), M3 (IFEval widened to n=295), M4 (official grader re-scoring of the 590 outputs), M5 (§1 narrowed to the two measured axes; the agentic axis dropped from the claim and marked unmeasured), M6 (pre-registered 2-epoch trial plus a full policy measurement). Work packages WP-2 (the one-command timing rewritten as a measured 9-run range), WP-4 (new readings synced into every citation surface), WP-5 (the official-grader rescoring, i.e. M4) and WP-6 (seen/held-out split) are closed. Criteria, cost and the "what would overturn it" line for each are in [`docs/0_ROADMAP.md`](docs/0_ROADMAP.md).

**Not done**: Q11 (swap the shipped adapter for the 2-epoch one — the author's call), WP-3 (`constitution/lock.yaml`'s `upstream:` points at a path that no longer exists; to be fixed in the next change that touches that file), Q6 (`per_instruction` overwrites same-named instructions; to be fixed the next time the on-disk format changes).

**Where this goes**: the two weakest points are known. The reference is only 0.32 self-consistent, so the ruler currently answers "how far from this reference" and nothing more; and the agentic axis was neither measured nor bought (BFCL needs HF reachability plus a thousand-line harness, and neither dependency holds on this machine). Fixing the first means replacing the reference with one that discriminates; fixing the second means solving those dependencies before talking about running it. Until either lands, claims stay on the two measured axes. DPO is a fallback, not the main line; why it stepped back and what would bring it back is recorded in the backlog of `docs/0_ROADMAP.md`.

## License

- The adapter is a derivative of `Qwen/Qwen3.5-2B` and inherits **Apache-2.0** from the base (checked against the local HF snapshot: the `LICENSE` file and `license: apache-2.0` in `README.md`); redistribution carries the base's LICENSE/NOTICE obligations.
- Third-party data shipped with the repo: `data/bench/gsm8k.jsonl` is GSM8K (MIT) and `data/bench/ifeval.jsonl` is IFEval (Apache-2.0). Licence texts are in `licenses/`; provenance, citations, modification notices and frozen-file sha256 are in [THIRD-PARTY.md](THIRD-PARTY.md).
- Situations and answers come from the law author's own private sessions (redacted; see the [data card](card/data-card.md)); DeepSeek's answers are subject to its terms of service.
- The repo's own code and documentation are **AGPL-3.0-only** (designated by the author on 2026-10-21, SPDX identifier `AGPL-3.0-only`), text at <https://www.gnu.org/licenses/agpl-3.0.txt>, local copy [`licenses/AGPL-3.0.txt`](licenses/AGPL-3.0.txt) (34523 bytes, sha256 `0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0`, fetched 2026-10-21, unmodified); reuse, modification and redistribution follow that licence. The adapter weights are not covered by it: they are a derivative of `Qwen/Qwen3.5-2B` and travel under **Apache-2.0**.

## Issues

<https://github.com/ZisIsNotZis/nomos/issues>. The repo is publicly readable: on 2026-10-21, anonymously (no credentials), `curl -sI https://github.com/ZisIsNotZis/nomos | head -1` returned `HTTP/2 200`; a private or missing repo returns 404 on the same command. If it does not open, contact the author directly.

## Where to read next

| Path | Content |
|---|---|
| [Problem](docs/1_PROBLEM.md) / [Goal](docs/2_GOAL.md) | Why it exists; the acceptance line and the current numbers (numbers live only here) |
| [Requirements](docs/3_REQUIREMENT.md) / [Use cases](docs/4_USECASE.md) | Functional, non-functional, constraints; five workflows with acceptance |
| [Product](docs/5_PRODUCT.md) | Claims, boundaries, decision tree, the one item only the author can judge |
| [Architecture](docs/6_ARCHITECTURE.md) / [Interface](docs/7_INTERFACE.md) | Subsystems and quality measures; data formats and CLI contracts |
| [Detail](docs/8_DETAIL.md) / [Implementation](docs/9_IMPLEMENTATION.md) | Algorithms and criteria; environment, commands, checks, accounting, repo layout |
| [Roadmap](docs/0_ROADMAP.md) | Milestones M1–M6, work packages, gates and cost |
| [Model card](card/model-card.md) | Base model and licence, adapter loading, result summary, known limits |
| [Data card](card/data-card.md) | Where the 242 situations come from, dual answers and sampling, filtering, redaction, what may be claimed |
| [Preprint draft](paper/draft.md) | Claim, method, data, results, limitations, conclusion — every number points back to evidence |
| [Measurement report](evidence/reports/sft-measurement.md) | Three-point measurement: three readings, format/decision split, same-protocol anchor, seen/held-out, 2-epoch |
| [Training](evidence/reports/sft-training.md) / [wide variant](evidence/reports/sft-training-wide.md) | 4-bit QLoRA, PPL 11.34 → 6.03, measured VRAM and sequence length |
| [SFT data](evidence/reports/sft-data.md) | How the 366 samples were filtered, split, covered, and where they fall short |
| [Benchmark](evidence/reports/sft-benchmark.md) | GSM8K 73.0% → 76.0% (+3.0pp, crossing zero, n=100), **IFEval 62.4% → 50.2% (−12.2pp, [−17.6, −6.8], n=295)**, p=2.57e-5 (clears the line at Bonferroni α=0.025); official grader on the same 590 outputs: strict 66.4% → 54.2% (−12.2pp, [−17.6, −6.8], p=3.38e-5), lax −11.2pp — conclusion unchanged; previous estimate at n=100: −12.0pp [−22.0, −3.0], 19 down / 7 up, p=0.029 |
| [Data quality](evidence/reports/data-quality.md) / [rubric](evidence/reports/rubric.md) | Filtering and coverage of the DPO batch; rubric discrimination (it does not separate the two sides) |
| [Frozen law](constitution/) | 264 leaves, node index, classification, shape checks, conflict audit |

## Layout

| Path | Content |
|---|---|
| `constitution/` | The frozen law, node index, classification program, shape checks |
| `data/` | Situations, positive/negative pairs, SFT samples (366/288/78), rule-coverage labels, frozen benchmark items |
| `docs/` | Knowledge base: `0_STAGING`, `0_ROADMAP`, `1_PROBLEM` … `9_IMPLEMENTATION` |
| `card/`, `paper/` | Model and data cards; preprint draft |
| `mail/` | Original correspondence with the upstream agent and the author (authorisation quotes live here) |
| `eval/` | Four-axis rubric evaluator and discrimination statistics |
| `evidence/` | Raw output and recomputation scripts for every measurement (`evidence/measure/summary.json` is the headline result) |
| `mining/` | Scripts, redaction gate and counts for mining situations out of session archives |
| `evidence/reports/` | Derivations and item-by-item detail (proof, not layer documents) |
| `scripts/` | Re-runnable scripts for building, training, measuring and benchmarking |
| `assets/` | Logo |
| `licenses/`, `THIRD-PARTY.md` | Licence texts and third-party notices |
| `artifacts.tsv` | Weight sha256 and regeneration commands (weights never enter git) |
