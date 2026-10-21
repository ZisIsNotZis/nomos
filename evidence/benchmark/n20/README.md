# n=20 cells (2026-10-21, superseded as the canonical reading by M2's n=100)

These are the four capability cells as first run, at `--limit 20`, plus the two paired
comparisons derived from them. They were moved here — not deleted — before M2's n=100 runs
overwrote the canonical `../<model>-<suite>.json` path.

- `base-{gsm8k,ifeval}.json`, `adapter-{gsm8k,ifeval}.json`: full per-item records at
  `limit: 20`, `seed: 0`, greedy, `frozen_sha256` as in `data/bench/sources.json`.
- `paired-{gsm8k,ifeval}.json`: the n=20 paired result (GSM8K −10.0pp [−30.0, +10.0];
  IFEval −20.0pp [−40.0, 0.0]).
- `*.log`: the four runs' stdout, as they were produced.

The 20 items are the first 20 of the same seed-0 frozen prefix the n=100 runs use, so these
records are a prefix of the n=100 records, not a different sample. `report/sft-benchmark.md`
states which numbers are current and cites this directory where the older estimate is kept
because it is "the previous estimate of the same sample".
