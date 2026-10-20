#!/usr/bin/env python3
"""Build report/probe-2/situations.jsonl from mining/candidates.jsonl.

Deterministic: seed 20261020, quotas per structural signal, one record per
session, records whose text looks like it carries a credential are excluded.

A situation is a decision point, so it must end on the user's turn: a record
is eligible only when its last non-empty line contains `USER:`. The excerpt
keeps that turn and as much preceding context as fits in 1800 characters,
truncating from the front and marking the cut as `[... N chars omitted ...]`.
The same rule is applied to both conditions.

Signal spread: S6_assistant_self_flagged_failure has no eligible record, because
every S6 window in mining/candidates.jsonl ends on the assistant's own message
rather than on a user turn. Its quota is redistributed over the other five
signals and the gap is recorded here and in report/probe-2.md.
"""

import json
import random
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CANDIDATES = REPO / "mining" / "candidates.jsonl"
OUT = HERE / "situations.jsonl"

SEED = 20261020
MAX_CHARS = 1800

QUOTA = {
    "S1_interrupt_after_tool_call": 6,
    "S4_negation_lead": 5,
    "S2_tool_burst_no_checkpoint": 3,
    "S3_repeat_user_turn": 3,
    "S5_quotes_assistant_text": 3,
}
# S6_assistant_self_flagged_failure: 0 eligible (100 windows, all end on the
# assistant turn).

SENSITIVE = re.compile(
    r"api[_-]?key\s*[:=]|OPENAI_API_KEY|Bearer\s+\S{12,}|password\s*[:=]"
    r"|ghp_|AKIA|sk-[A-Za-z0-9]{8,}|[A-Za-z0-9]{20,}\.lf[A-Za-z0-9]{8,}",
    re.IGNORECASE,
)
HOME_PATH = re.compile(r"/home/[^\s\"'`]+")


def last_nonempty_line(text):
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def ends_with_user(text):
    return "USER:" in last_nonempty_line(text)


def truncate(text):
    text = HOME_PATH.sub("<PATH>", text)
    if len(text) <= MAX_CHARS:
        return text
    tail = text[-(MAX_CHARS - 40):]
    omitted = len(text) - len(tail)
    marker = f"[... {omitted} chars omitted ...]\n"
    if len(marker) + len(tail) > MAX_CHARS:
        tail = text[-(MAX_CHARS - len(marker)):]
        omitted = len(text) - len(tail)
        marker = f"[... {omitted} chars omitted ...]\n"
    return marker + tail


def main():
    records = [json.loads(line) for line in CANDIDATES.read_text(encoding="utf-8").splitlines() if line.strip()]
    rng = random.Random(SEED)

    excluded_credential = 0
    excluded_tail = 0
    pools = {}
    for record in records:
        if not record["signals"]:
            continue
        if SENSITIVE.search(record["text"]):
            excluded_credential += 1
            continue
        if not ends_with_user(record["text"]):
            excluded_tail += 1
            continue
        pools.setdefault(record["signals"][0], []).append(record)
    for pool in pools.values():
        rng.shuffle(pool)

    used_sessions = set()
    chosen = []
    for signal, quota in QUOTA.items():
        taken = 0
        for record in pools.get(signal, []):
            if taken == quota:
                break
            if record["session"] in used_sessions:
                continue
            used_sessions.add(record["session"])
            chosen.append({"signal": signal, "record": record})
            taken += 1
        if taken != quota:
            raise SystemExit(f"only {taken} of {quota} eligible situations for {signal}")

    # A fixed situation order that does not group by signal, so no arm sees a
    # signal order.
    rng.shuffle(chosen)

    rows = []
    for index, item in enumerate(chosen, start=1):
        record = item["record"]
        excerpt = truncate(record["text"])
        if not ends_with_user(excerpt):
            raise SystemExit(f"{record['window_id']}: excerpt does not end on a user turn")
        rows.append(
            {
                "id": f"SIT{index:02d}",
                "signal": item["signal"],
                "signals": record["signals"],
                "window_id": record["window_id"],
                "session": record["session"],
                "turn_indices": record["turn_indices"],
                "source_chars": len(record["text"]),
                "excerpt_chars": len(excerpt),
                "ends_with_user": True,
                "excerpt": excerpt,
            }
        )

    if len({row["session"] for row in rows}) != len(rows):
        raise SystemExit("duplicate session in selection")
    OUT.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    print(f"wrote {len(rows)} situations to {OUT}")
    print(f"excluded {excluded_credential} credential-looking records, {excluded_tail} records not ending on a user turn")
    for row in rows:
        print(f"  {row['id']} {row['signal']:<36} {row['source_chars']:>5} -> {row['excerpt_chars']:>4} chars  {row['excerpt'].splitlines()[-1][:60]}")


if __name__ == "__main__":
    main()
