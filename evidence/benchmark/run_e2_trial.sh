#!/usr/bin/env bash
# M6 trial (pre-registered in AGENTS.md, 2026-10-23): retrain the narrow adapter at 2 epochs and
# measure the two axes the acceptance line covers, against the same landed base records.
#
# Runs detached (setsid) because a watcher dies with its turn; the completion is the file this
# script writes into inbox/ at the end. Everything except --epochs is the delivered recipe:
# same seed 0, same lr/warmup, same rank/alpha/targets, same data and session split.
set -u
cd "$(dirname "$0")/../.." || exit 1
REPO=$(pwd)
LOGS="$REPO/evidence/benchmark/logs-e2"
mkdir -p "$LOGS" "$REPO/.tmp/sft" "$REPO/inbox"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

echo "start $(date -u +%FT%TZ) epochs=2 adapter=.tmp/sft/adapter-e2" | tee "$LOGS/driver.log"

python3 scripts/train_sft.py --epochs 2 --grad-accum 8 --lora-r 16 --lora-alpha 32 \
  --lora-targets narrow --run-name e2 --adapter-dir .tmp/sft/adapter-e2 \
  > "$LOGS/train.log" 2>&1
rc_train=$?
echo "train rc=$rc_train $(date -u +%FT%TZ)" | tee -a "$LOGS/driver.log"
if [ "$rc_train" -ne 0 ]; then
  python3 - "$LOGS" <<'PY' | tee -a "$LOGS/driver.log"
import sys
print("training failed; see", sys.argv[1] + "/train.log")
PY
  exit 1
fi

# Two suites, one process each, both against the frozen seed-0 prefix (IFEval 295, GSM8K 100).
python3 scripts/run_bench.py --suite ifeval --model adapter --adapter-dir .tmp/sft/adapter-e2 \
  --limit 295 --tag adapter-e2-ifeval > "$LOGS/adapter-ifeval.log" 2>&1 &
pid_if=$!
python3 scripts/run_bench.py --suite gsm8k --model adapter --adapter-dir .tmp/sft/adapter-e2 \
  --limit 100 --tag adapter-e2-gsm8k > "$LOGS/adapter-gsm8k.log" 2>&1 &
pid_gm=$!
echo "$pid_if $pid_gm" > "$LOGS/cell.pids"

wait "$pid_if"; rc_if=$?
wait "$pid_gm"; rc_gm=$?
echo "bench rc ifeval=$rc_if gsm8k=$rc_gm $(date -u +%FT%TZ)" | tee -a "$LOGS/driver.log"

if [ "$rc_if" -eq 0 ] && [ "$rc_gm" -eq 0 ]; then
  python3 evidence/benchmark/analyse_paired.py ifeval --adapter-tag adapter-e2-ifeval \
    --out-tag paired-e2-ifeval > "$LOGS/paired-ifeval.log" 2>&1
  rc_pair=$?
  python3 evidence/benchmark/analyse_paired.py gsm8k --adapter-tag adapter-e2-gsm8k \
    --out-tag paired-e2-gsm8k > "$LOGS/paired-gsm8k.log" 2>&1 || rc_pair=1
else
  rc_pair=1
fi
echo "paired rc=$rc_pair $(date -u +%FT%TZ)" | tee -a "$LOGS/driver.log"

python3 - "$REPO" "$rc_if" "$rc_gm" "$rc_pair" <<'PY'
import json, sys
from pathlib import Path
repo, rc_if, rc_gm, rc_pair = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
lines = ["kind:    report",
         "from:    run-e2-driver",
         "spend:   idle-compute",
         "id:      AGENTS.md M6（2-epoch 试验的预登记）",
         "",
         "# M6 试验跑完：2-epoch 适配器的两格",
         "",
         f"exit codes: ifeval={rc_if} gsm8k={rc_gm} paired={rc_pair}",
         ""]
for name in ("adapter-e2-ifeval", "adapter-e2-gsm8k", "paired-e2-ifeval", "paired-e2-gsm8k"):
    path = repo / "evidence" / "benchmark" / f"{name}.json"
    if not path.exists():
        lines.append(f"- `{name}.json`: missing")
        continue
    payload = json.loads(path.read_text())
    if name.startswith("paired"):
        pair = payload.get("paired", {})
        lines.append(
            f"- `{name}.json`: n={payload.get('n')} "
            f"base {payload['base']['correct']} adapter {payload['adapter']['correct']} "
            f"delta {payload.get('delta_adapter_minus_base')} "
            f"paired_ci {payload.get('delta_ci95_paired_bootstrap')} "
            f"drops {pair.get('drops')} gains {pair.get('gains')} "
            f"mcnemar_p {pair.get('mcnemar_exact_p')}"
        )
    else:
        summary = payload.get("summary", payload)
        keep = {k: summary[k] for k in ("items", "correct", "accuracy", "accuracy_ci95", "unscorable") if k in summary}
        lines.append(f"- `{name}.json`: {json.dumps(keep, ensure_ascii=False)} elapsed={payload.get('elapsed_seconds')}")
lines.append("")
lines.append("A separate turn reads these two and applies the pre-registered stop/continue rule.")
lines.append("")
(repo / "inbox" / "2026-10-23-e2-trial-done.md").write_text("\n".join(lines) + "\n")
print("completion written")
PY
echo "done $(date -u +%FT%TZ)" | tee -a "$LOGS/driver.log"
