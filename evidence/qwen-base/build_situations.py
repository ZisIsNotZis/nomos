#!/usr/bin/env python3
"""Take 20 situations from probe 4, stratified by signal.

The situation text and the continuation instruction are the exact bytes probe 4
used, so a `bare` output here is comparable with probe 4's `bare` arm. Only the
sample changes: 20 rows, proportional to the signal counts in probe 4's 183,
with every signal that exists there getting at least one row.

Usage: python3 report/gate-base/build_situations.py
"""

import hashlib
import json
import random
from pathlib import Path

NOMOS = Path(__file__).resolve().parents[2]
SOURCE = NOMOS / "report" / "probe-4" / "situations.jsonl"
OUT = Path(__file__).resolve().parent / "situations.jsonl"
SEED = 20261028
TOTAL = 20

# Exact bytes of probe 4's instruction (report/probe-4/common.py: INSTRUCTION).
INSTRUCTION = (
    "\n\n---\n"
    "Write the single next assistant turn for the conversation above: at most 120 words. "
    "If a tool call would be used, render it as `tool: name(args)`."
)


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def allocate(counts, total):
    """Proportional allocation with a floor of one row per signal."""
    usable = [s for s in counts if counts[s] > 0]
    quota = {s: 1 for s in usable}
    remaining = total - len(usable)
    total_rows = sum(counts.values())
    exact = {s: counts[s] / total_rows * remaining for s in usable}
    for s in usable:
        quota[s] += int(exact[s])
    left = total - sum(quota.values())
    for s in sorted(usable, key=lambda s: (-(exact[s] - int(exact[s])), s))[:left]:
        quota[s] += 1
    return quota


def main():
    rows = [json.loads(line) for line in SOURCE.read_text().splitlines() if line.strip()]
    counts = {}
    for row in rows:
        counts[row["signal"]] = counts.get(row["signal"], 0) + 1
    quota = allocate(counts, TOTAL)

    by_signal = {}
    for row in rows:
        by_signal.setdefault(row["signal"], []).append(row)

    rng = random.Random(SEED)
    picked = []
    for signal in sorted(quota):
        pool = sorted(by_signal[signal], key=lambda r: r["id"])
        chosen = rng.sample(pool, quota[signal])
        picked.extend(sorted(chosen, key=lambda r: r["id"]))
    assert len(picked) == TOTAL, len(picked)

    # One row per session where the pool allows it: the same session twice would
    # make two of the twenty non-independent in a count that is reported as n=20.
    sessions = [row["session"] for row in picked]
    out_rows = []
    for index, row in enumerate(picked, 1):
        out_rows.append({
            "id": f"GB{index:03d}",
            "source_id": row["id"],
            "signal": row["signal"],
            "signals": row["signals"],
            "session": row["session"],
            "session_repeated": sessions.count(row["session"]) - 1,
            "excerpt_chars": row["excerpt_chars"],
            "excerpt": row["excerpt"],
            "prompt": row["excerpt"] + INSTRUCTION,
            "prompt_sha256": sha(row["excerpt"] + INSTRUCTION),
        })

    with OUT.open("w") as handle:
        for row in out_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"source rows: {len(rows)}  signals: {counts}")
    print(f"quota: {quota}")
    print(f"written: {OUT} ({len(out_rows)} rows)")
    repeated = {row['source_id']: row['session_repeated'] for row in out_rows if row['session_repeated']}
    print(f"sessions appearing more than once: {repeated if repeated else 'none'}")


if __name__ == "__main__":
    main()
