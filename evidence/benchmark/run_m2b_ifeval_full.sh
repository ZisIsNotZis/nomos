#!/usr/bin/env bash
# M3 driver: widen the IFEval cell from n=100 to the full frozen 295 (base + adapter).
#
# Why this shape: IFEval is the one cell M2 moved (57/100 -> 45/100, -12.0pp, [-22.0, -3.0],
# McNemar p=0.029). That p was computed once, in one of two suites, with no multiplicity
# correction, and two of the 19 drops are word-count misses by 2 and 5 words. Widening to
# the full 295 tightens the interval from ~+-10pp to ~+-5pp and puts 195 items the current
# reading has never seen against the same adapter. GSM8K is NOT rerun: its interval
# [-6.0, +12.0] already excludes any 5pp+ drop, and widening it changes nothing but cost.
#
# STATUS: prepared, NOT dispatched. M2's session wrote it and handed the launch to the
# layer above (the parent owns follow-up launches); nothing below has run yet, so
# evidence/benchmark/logs-m2b/ does not exist and no n=100 file has been copied.
#
# Contract (recorded in ../../AGENTS.md, milestone M3):
#   boundary  = the IFEval cell at --limit 295 for base and adapter, plus the paired
#               re-analysis; no scorer change, no frozen-sample change, no main metric.
#   ground    = evidence/benchmark/ only. This script never edits report/ or docs/:
#               landing the text is the node's job, the package's answer is its report.
#   acceptance= evidence/benchmark/paired-ifeval.json has n: 295, and the n=100 reading
#               is preserved under evidence/benchmark/n100/.
#   spend     = idle-compute (one 4090), wall clock ~80 min of the ~3.7 h left of M2's
#               ~5 h grant; no metered, no API money. 3 h timeout per cell.
#   report    = nomos, by a `completion` message written into nomos/inbox/ on exit.
#
# The canonical output path is fixed (scripts/run_bench.py writes <model>-<suite>.json), so
# step 1 copies the current n=100 reading aside. Same move as the n=20 cells got in fc273a9.
#
# Launch it detached (the one command; everything else is inside the script):
#   setsid nohup bash evidence/benchmark/run_m2b_ifeval_full.sh > evidence/benchmark/logs-m2b/driver.out 2>&1 &
# It writes its own `completion` into nomos/inbox/ when it exits, so no watcher is needed and
# nobody has to sit on it. Do not block on it and do not `sleep` waiting for it.
# Exit codes: 0 all done + completion written; 1 a cell failed; 2 preflight failed; 4 pairing failed.
set -u
cd "$(dirname "$(readlink -f "$0")")/../.." || exit 2

OUT=evidence/benchmark
LOGS="$OUT/logs-m2b"
KEEP="$OUT/n100"
LIMIT=295
START=$(date -Is)
mkdir -p "$LOGS" "$KEEP"

say() { echo "[$(date -Is)] $*" | tee -a "$LOGS/driver.log"; }

# ---- preflight: every reason to stop before spending GPU time -------------------------
[ -f data/bench/ifeval.jsonl ] || { say "preflight: data/bench/ifeval.jsonl missing"; exit 2; }
[ -f .tmp/sft/adapter-narrow/adapter_model.safetensors ] || {
  say "preflight: .tmp/sft/adapter-narrow/ missing -- the adapter is the temp region, it is NOT retrained here"
  exit 2
}
free_mib=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1 | tr -d ' ')
say "preflight: gpu free ${free_mib} MiB, used $(nvidia-smi --query-gpu=memory.used --format=csv,noheader | head -1)"
if [ "${free_mib:-0}" -lt 12000 ]; then
  say "preflight: only ${free_mib} MiB free, two 4-bit 2B pipelines need headroom; another project holds the card"
  exit 2
fi
say "preflight ok: limit=$LIMIT, adapter=$(sha256sum .tmp/sft/adapter-narrow/adapter_model.safetensors | cut -c1-16)"

# ---- keep the n=100 reading the report quotes before the canonical path is overwritten --
if [ ! -f "$KEEP/paired-ifeval.json" ]; then
  for f in base-gsm8k base-ifeval adapter-gsm8k adapter-ifeval paired-gsm8k paired-ifeval; do
    cp -p "$OUT/$f.json" "$KEEP/$f.json" || { say "preserve failed on $f; stopping before anything is overwritten"; exit 2; }
  done
  [ "$(sha256sum <"$OUT/paired-ifeval.json")" = "$(sha256sum <"$KEEP/paired-ifeval.json")" ] || {
    say "preserved copy does not match the source; stopping"; exit 2; }
  cat > "$KEEP/README.md" <<'MD'
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
MD
  say "preserved n=100 artefacts in $KEEP"
else
  say "preserved n=100 artefacts already present in $KEEP, left untouched"
fi

# ---- both cells at once: 2 x (4-bit 2B + LoRA), ~4.4 GiB, card had >16 GiB free --------
cap="timeout --kill-after=60 10800"   # 3 h hard cap per cell
$cap python3 scripts/run_bench.py --suite ifeval --model base --limit "$LIMIT" \
    > "$LOGS/base-ifeval.log" 2>&1 &
pb=$!
$cap python3 scripts/run_bench.py --suite ifeval --model adapter --limit "$LIMIT" \
    > "$LOGS/adapter-ifeval.log" 2>&1 &
pa=$!
wait "$pb"; rb=$?
wait "$pa"; ra=$?
say "cells done: base rc=$rb adapter rc=$ra"
tail -n 2 "$LOGS/base-ifeval.log" >> "$LOGS/driver.log" 2>/dev/null
tail -n 2 "$LOGS/adapter-ifeval.log" >> "$LOGS/driver.log" 2>/dev/null
[ "$rb" -eq 0 ] && [ "$ra" -eq 0 ] || { say "a cell failed; pairing not run"; exit 1; }

# ---- pairing: this is what M3 reads ---------------------------------------------------
python3 evidence/benchmark/analyse_paired.py ifeval 2>&1 | tee -a "$LOGS/driver.log"
rc=${PIPESTATUS[0]}
say "analyse rc=$rc"
[ "$rc" -eq 0 ] || exit 4

# ---- the package's report: one file in nomos/inbox/, so the next session wakes to it ----
END=$(date -Is)
read -r BASE_N AD_N DELTA LO HI DROPS GAINS PN <<<"$(python3 - <<'PY'
import json
d = json.load(open("evidence/benchmark/paired-ifeval.json"))
print(d["base"]["correct"], d["adapter"]["correct"],
      f'{d["delta_adapter_minus_base"]:+.3f}',
      f'{d["delta_ci95_paired_bootstrap"][0]:+.3f}', f'{d["delta_ci95_paired_bootstrap"][1]:+.3f}',
      d["paired"]["drops"], d["paired"]["gains"], f'{d["paired"]["mcnemar_exact_p"]:.4f}')
PY
)"
mkdir -p mail
cat > "inbox/$(date +%F)-m2b-ifeval-full-completion.md" <<MD
kind:    completion
from:    package m2b-ifeval-full (M3 driver)
to:      nomos
spend:   idle-compute, ${START} -> ${END}, no metered, ¥0
node:    nomos (M3)
evidence: evidence/benchmark/paired-ifeval.json (n=295), evidence/benchmark/logs-m2b/
decision: none

M3 ran: IFEval at --limit 295 for base and adapter, same seed-0 frozen prefix, greedy,
same scorer; paired re-analysis with evidence/benchmark/analyse_paired.py.

  ifeval  base ${BASE_N}/295  adapter ${AD_N}/295  delta ${DELTA}  paired CI [${LO} ${HI}]  drops ${DROPS} gains ${GAINS}  McNemar p=${PN}
  (unrounded reading is in the JSON; this line is the report, the numbers that matter are
   the interval and the p, and both are in paired-ifeval.json)

The n=100 reading was copied to evidence/benchmark/n100/ before the canonical path was
overwritten, so the number the report currently cites is still on disk.
GSM8K was not rerun (its interval already excludes a 5pp+ drop): base-gsm8k.json /
adapter-gsm8k.json are still the n=100 files.

Landing this (the node's job, not the package's): replace the IFEval row in
report/sft-benchmark.md and every surface that cites it; the n=100 IFEval row moves to
"前一次估计"; then delete this file.
MD
say "completion written: inbox/$(date +%F)-m2b-ifeval-full-completion.md"
exit 0
