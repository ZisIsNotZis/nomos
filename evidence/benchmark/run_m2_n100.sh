#!/usr/bin/env bash
# M2 driver: the four capability cells at n=100 (GSM8K/IFEval x base/adapter).
#
# Shape, and why it is this shape: two processes in parallel per model, gsm8k and ifeval,
# one model phase after the other. That is exactly the pairing the n=20 cells used, so base
# and adapter stay under the same harness (same --limit, same parallelism) and
# evidence/benchmark/analyse_paired.py can refuse the comparison if they ever diverge.
#
# Nothing here changes the scorer, the frozen samples or the measurement main metric: it
# calls scripts/run_bench.py as-is, which writes evidence/benchmark/<model>-<suite>.json
# with limit: 100 over the same seed-0 frozen prefix the 20-item cells used.
#
# Detached by design. Launch it with setsid so a dead session does not kill the GPU run:
#   setsid nohup bash evidence/benchmark/run_m2_n100.sh > evidence/benchmark/logs-n100/driver.out 2>&1 &
# Per-process logs and the phase log live in evidence/benchmark/logs-n100/.
#
# Exit codes: 0 all four cells and the pairing ran; 1 a run failed; 2 preflight failed
# (missing adapter, missing frozen data, too little GPU memory); 4 pairing failed.
set -u
cd "$(dirname "$(readlink -f "$0")")/../.." || exit 2

OUT=evidence/benchmark
LOGS="$OUT/logs-n100"
LIMIT=100
mkdir -p "$LOGS"
say() { echo "[$(date -Is)] $*" | tee -a "$LOGS/driver.log"; }

# ---- preflight: every reason to stop before spending GPU time -------------------------
[ -f data/bench/gsm8k.jsonl ] || { say "preflight: data/bench/gsm8k.jsonl missing"; exit 2; }
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

# ---- one model phase: two suites in parallel, hard wall clock per process -------------
run_pair() {  # $1 = base|adapter
  local model=$1
  local cap
  cap="timeout --kill-after=60 10800"   # 3 h per cell: the whole milestone's budget is 5 h
  $cap python3 scripts/run_bench.py --suite gsm8k  --model "$model" --limit "$LIMIT" \
      > "$LOGS/$model-gsm8k.log" 2>&1 &
  local pg=$!
  $cap python3 scripts/run_bench.py --suite ifeval --model "$model" --limit "$LIMIT" \
      > "$LOGS/$model-ifeval.log" 2>&1 &
  local pi=$!
  wait "$pg"; local rg=$?
  wait "$pi"; local ri=$?
  say "phase $model done: gsm8k rc=$rg ifeval rc=$ri"
  tail -n 3 "$LOGS/$model-gsm8k.log" >> "$LOGS/driver.log" 2>/dev/null
  tail -n 3 "$LOGS/$model-ifeval.log" >> "$LOGS/driver.log" 2>/dev/null
  [ "$rg" -eq 0 ] && [ "$ri" -eq 0 ]
}

run_pair base    || exit 1
run_pair adapter || exit 1

# ---- pairing: this is what the milestone reads ---------------------------------------
python3 evidence/benchmark/analyse_paired.py 2>&1 | tee -a "$LOGS/driver.log"
rc=${PIPESTATUS[0]}
say "analyse rc=$rc"
exit $([ "$rc" -eq 0 ] && echo 0 || echo 4)
