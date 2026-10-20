#!/usr/bin/env python3
"""Build report/probe-4/situations.jsonl, slices.jsonl and map.json.

Situations come from mining/candidates.jsonl under probe 2's rules: the excerpt
must end on a USER turn, the front is truncated to 1800 characters, and only one
window per session was taken. Probe 4 cannot keep that last rule and reach
n >= 180: the pool holds 242 eligible windows from 51 distinct sessions. So the
cap is eight windows per session, windows are spread across signals inside a
session where the session offers them, and session is the clustering unit that
analyse.py bootstraps over.

Deterministic: seed 20261024. Re-running reproduces the three files byte for byte.
"""

import importlib.util
import json
import random
import sys
from collections import Counter, defaultdict

import common

MIN_PER_SIGNAL = 2


def redaction_patterns():
    path = common.NOMOS / "mining" / "check_redaction.py"
    spec = importlib.util.spec_from_file_location("check_redaction", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PATTERNS


def main():
    records = common.load_jsonl(common.CANDIDATES)
    funnel = Counter()
    eligible = []
    for record in records:
        if not record["signals"]:
            funnel["no_signal"] += 1
            continue
        if common.SENSITIVE.search(record["text"]):
            funnel["credential_looking"] += 1
            continue
        if not common.ends_with_user(record["text"]):
            funnel[f"not_end_on_user:{record['signals'][0]}"] += 1
            continue
        eligible.append(record)
    funnel["eligible"] = len(eligible)

    by_session = defaultdict(list)
    for record in eligible:
        by_session[record["session"]].append(record)
    sessions = sorted(by_session)
    funnel["eligible_sessions"] = len(sessions)

    chosen = []
    capped_sessions = 0
    for session in sessions:
        windows = sorted(by_session[session], key=lambda row: row["window_id"])
        rng = random.Random(f"{common.SEED_SITUATIONS}:{session}")
        rng.shuffle(windows)
        kept, per_signal = [], Counter()
        while windows and len(kept) < common.MAX_PER_SESSION:
            # spread across signals inside the session: least-used signal first
            windows.sort(key=lambda row: (per_signal[row["signals"][0]],))
            record = windows.pop(0)
            per_signal[record["signals"][0]] += 1
            kept.append(record)
        if len(by_session[session]) > common.MAX_PER_SESSION:
            capped_sessions += 1
        chosen.extend(kept)
    funnel["capped_sessions"] = capped_sessions

    signal_counts = Counter(record["signals"][0] for record in chosen)
    for signal, count in signal_counts.items():
        if count < MIN_PER_SIGNAL:
            raise SystemExit(f"{signal}: only {count} situations selected")
    if "S6_assistant_self_flagged_failure" in signal_counts:
        raise SystemExit("S6 should have no eligible window")
    if not 180 <= len(chosen) <= 220:
        raise SystemExit(f"{len(chosen)} situations is outside 180-220")

    rng = random.Random(common.SEED_SITUATIONS)
    rng.shuffle(chosen)

    leaf_list = common.leaves()
    vocabulary = common.distinctive_vocabulary(leaf_list)
    policy = common.policy_text()
    for leaf in leaf_list:
        if leaf["text"] not in policy:
            raise SystemExit(f"leaf is not a verbatim AGENTS.md substring: {leaf['path']}")

    situations, slices = [], []
    for index, record in enumerate(chosen, start=1):
        excerpt = common.truncate(record["text"])
        if not common.ends_with_user(excerpt):
            raise SystemExit(f"{record['window_id']}: excerpt does not end on a user turn")
        sid = f"SIT{index:03d}"
        situations.append({
            "id": sid,
            "signal": record["signals"][0],
            "signals": record["signals"],
            "session": record["session"],
            "window_id": record["window_id"],
            "turn_indices": record["turn_indices"],
            "source_chars": len(record["text"]),
            "excerpt_chars": len(excerpt),
            "ends_with_user": True,
            "excerpt": excerpt,
        })
        indices, anchors_missed = common.select_leaves(excerpt, leaf_list, vocabulary)
        if not indices:
            raise SystemExit(f"{sid}: the slice rule selected no leaf")
        text = common.slice_text(indices, leaf_list)
        slices.append({
            "id": sid,
            "leaf_indices": indices,
            "leaf_paths": [leaf_list[item]["path"] for item in indices],
            "leaf_count": len(indices),
            "anchors_missed": anchors_missed,
            "slice_chars": len(text),
            "slice_sha256": common.sha(text),
            "slice": text,
        })

    sessions_used = {row["session"] for row in situations}
    if len(sessions_used) != len(sessions):
        raise SystemExit("a session with eligible windows was dropped")
    max_session = max(Counter(row["session"] for row in situations).values())

    patterns = redaction_patterns()
    for row in situations:
        for label, pattern in patterns:
            for match in pattern.finditer(row["excerpt"]):
                raise SystemExit(f"{row['id']}: {label}: {match.group(0)[:80]!r}")

    common.SITUATIONS.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in situations), encoding="utf-8")
    common.SLICES.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in slices), encoding="utf-8")

    mapping = {name: common.mapping_for(name, situations) for name in common.COMPARISONS}
    common.MAP.write_text(json.dumps(mapping, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"situations: {len(situations)}  sessions: {len(sessions_used)}  "
          f"max windows from one session: {max_session}")
    print(f"funnel: {dict(funnel)}")
    print(f"signal counts: {dict(signal_counts)}")
    print(f"leaves: {len(leaf_list)}  distinctive terms: {len(vocabulary)}  "
          f"slice chars: min {min(s['slice_chars'] for s in slices)} "
          f"median {sorted(s['slice_chars'] for s in slices)[len(slices) // 2]} "
          f"max {max(s['slice_chars'] for s in slices)}")
    print(f"slice leaves per situation: {dict(Counter(s['leaf_count'] for s in slices))}")
    print(f"policy chars: {len(policy)}  sha256: {common.policy_sha()}")


if __name__ == "__main__":
    main()
