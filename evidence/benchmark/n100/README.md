# n=100 cells (2026-10-21, superseded as the canonical reading by M3's IFEval n=295)

These are the four capability cells at `--limit 100` and the two paired comparisons derived
from them — the reading `report/sft-benchmark.md` carried between M2 and M3. They were
copied here before M3's IFEval run at `--limit 295` overwrote the canonical
`../<model>-<suite>.json` path, because `scripts/run_bench.py` and
`evidence/benchmark/analyse_paired.py` write fixed filenames.

- GSM8K is still current: M3 does not rerun it (`../base-gsm8k.json` is this file).
- IFEval here is the n=100 reading: 57/100 -> 45/100, -12.0pp [-22.0, -3.0], 19 drops /
  7 gains, McNemar p=0.029, floors 5pp (McNemar) / 4pp (interval).
- The 100 items are the first 100 of the same seed-0 frozen prefix the n=295 run uses, so
  these records are a prefix of the n=295 records, not a different sample.

Caveat that travels with the IFEval number (added by the node, not the package): p=0.029 is
one test per suite with no multiplicity correction — under Bonferroni α=0.025 (two suites)
it does not pass — and flipping the two word-floor near-misses (`ifeval-1072`, 398/400;
`ifeval-2844`, 195/200) gives 17 drops / 7 gains, Δ=−10.0pp, exact McNemar p=0.064. The
mechanism is that the adapter writes shorter answers (median words 212.5 → 169.0 on IFEval,
204.0 → 83.0 on GSM8K), so "at least N words" fails first. See report/sft-benchmark.md.
