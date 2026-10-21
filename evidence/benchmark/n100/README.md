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

Caveats that travel with *this* n=100 reading (added by the node, not the package), and where
they stand after M3:

- p=0.029 is one test per suite with no multiplicity correction; under Bonferroni α=0.025
  (two suites) it does not pass. **Still true of this file. It is not true of n=295**: that
  p is 2.57e-5 and passes 0.025 by three orders of magnitude.
- Flipping the two word-floor near-misses (`ifeval-1072`, 398/400; `ifeval-2844`, 195/200)
  gives 17 drops / 7 gains, Δ=−10.0pp, exact McNemar p=0.064. **This is the fragility of the
  n=100 reading specifically.** At n=295 the same two flips give 52/18, Δ=−11.5pp, p=5.85e-5,
  and flipping all seven `number_words` drops gives 47/18, p=4.22e-4.
- The mechanism claim that used to sit next to this number ("the adapter writes shorter
  answers, so 'at least N words' fails first") is **narrower than it was written**. Median
  words do drop (212.5 → 169.0 on these 100 items; 185 → 130 over all 295), but at n=295 the
  adapter is shorter on only 52% of the 54 drops versus 68% of the 130 items both got right,
  so brevity is a background shift and not what selects the drops. The largest single family
  of drops at n=295 is `punctuation:no_comma` (11), and 7 of those 11 got *longer*.

The n=295 reading that supersedes this one for IFEval: 184/295 → 148/295, −12.2pp
[−17.6, −6.8], 54 drops / 18 gains, McNemar p=2.57e-5, floors 5 items / 1.7pp (McNemar) and
4 items / 1.4pp (interval), `unscorable=0`. See report/sft-benchmark.md.
