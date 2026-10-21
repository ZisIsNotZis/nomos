# in-flight: m2-n100 (four capability cells at n=100)

- **package id**: `m2-n100`
- **pid**: 91165 (driver `bash evidence/benchmark/run_m2_n100.sh`; its two `timeout` children at launch were 91193/91194)
- **start**: 2026-10-21T12:41:08+08:00
- **exact command**: `setsid nohup bash evidence/benchmark/run_m2_n100.sh > evidence/benchmark/logs-n100/driver.out 2>&1 &`
- **GPU at launch**: RTX 4090, 23560 MiB free / 549 MiB used; preflight passed (adapter `5be6a2f387520259`, limit=100)
- **phases**: `base` (gsm8k + ifeval in parallel, ≤3 h each) → `adapter` (same) → `python3 evidence/benchmark/analyse_paired.py`
- **what is done**: driver launched and preflight passed; nothing else.
- **what is starting**: base GSM8K and base IFEval, 100 items each, greedy, seed 0.
- **what proves it**: `evidence/benchmark/driver.log` phase lines, `evidence/benchmark/base-{gsm8k,ifeval}.json` with `limit: 100`, then `paired-{gsm8k,ifeval}.json`.
- **next step begins**: `tail -f evidence/benchmark/logs-n100/driver.log`; pid in `evidence/benchmark/logs-n100/driver.pid`.

## If this session dies

The run survives it: `setsid` detached the driver from the session, so it keeps the GPU.
A resumed session must:

1. `cat evidence/benchmark/logs-n100/driver.pid` → the driver pid; `ps -p <pid>` says whether it is alive.
2. `tail -f evidence/benchmark/logs-n100/driver.log` until the `analyse rc=` line (blocking watcher; never `sleep`).
3. If the driver is gone and `analyse_paired.py` has not run, run `python3 evidence/benchmark/analyse_paired.py` by hand.
4. Rerun the driver only if a phase line reported a non-zero rc; it rewrites that cell's JSON from scratch, and greedy decoding over a fixed prefix keeps a rerun comparable.
5. The adapter lives only in `.tmp/sft/adapter-narrow/` — do not retrain, do not delete it.
