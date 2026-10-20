#!/usr/bin/env python3
"""Deterministically build probe 5's 60 situations and blind X/Y map.

Situations come from report/probe-4/situations.jsonl, stratified by signal and
capped at two per session (see common.select_situations). The map holds the only
arm labels: seed 20261030 orders every paired comparison, seed 20261031 orders
the control comparison.
"""

import json

import common


def main():
    chosen = common.select_situations()
    if len(chosen) != 60:
        raise SystemExit(f"expected 60 situations, selected {len(chosen)}")

    rows = []
    for index, source in enumerate(chosen, start=1):
        rows.append({
            "id": f"P5SIT{index:03d}",
            "source_id": source["id"],
            "signal": source["signal"],
            "session": source["session"],
            "window_id": source["window_id"],
            "excerpt": source["excerpt"],
        })

    per_session = {}
    per_signal = {}
    for row in rows:
        per_session[row["session"]] = per_session.get(row["session"], 0) + 1
        per_signal[row["signal"]] = per_signal.get(row["signal"], 0) + 1
    if max(per_session.values()) > common.MAX_PER_SESSION:
        raise SystemExit("a session exceeds two situations")
    if per_signal != common.SIGNAL_ALLOCATION:
        raise SystemExit(f"signal allocation differs: {per_signal}")
    if len({row["source_id"] for row in rows}) != 60:
        raise SystemExit("duplicate source situation")

    common.SITUATIONS.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    mapping = common.build_map(sorted(rows, key=lambda row: int(row["id"][5:])))
    common.MAP.write_text(json.dumps(mapping, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"selected {len(rows)} situations from {len({row['source_id'] for row in rows})} source rows")
    print(f"sessions: {len(per_session)}, max per session: {max(per_session.values())}")
    print("per signal: " + ", ".join(f"{key} {value}" for key, value in sorted(per_signal.items())))
    print(f"paired comparisons: {len(rows) * common.DRAWS}")
    print(f"control comparisons: {len(rows)}")
    print(f"wrote {common.SITUATIONS.name} and {common.MAP.name}")


if __name__ == "__main__":
    main()
