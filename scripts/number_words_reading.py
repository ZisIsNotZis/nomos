#!/usr/bin/env python3
"""How many items pass the `length_constraints:number_words` instruction, per side.

Answers one question about the two stored IFEval runs: of the frozen items that carry a
`length_constraints:number_words` instruction, how many does each side still satisfy on
that instruction, and how many does each side get wholly right?

The stored `per_instruction` dict cannot answer it. `bench_suites.score_ifeval` builds it
with `dict(zip(instruction_id_list, strict))`, so an item carrying the same instruction
twice keeps only the last verdict (`ifeval-19`, `ifeval-2069`). This script therefore
re-runs the checker from `scripts/bench_suites.py` against the stored output and never
reads `per_instruction`. Nothing here can change a stored verdict: `whole-item correct` is
read straight from the record.

Usage (from the repo root):
  python3 scripts/number_words_reading.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import bench_suites  # noqa: E402

INSTRUCTION = "length_constraints:number_words"
SIDES = ("base", "adapter")


def main():
    items = bench_suites.load_items("ifeval", os.path.join(ROOT, "data", "bench"))
    picked = [i for i, it in enumerate(items) if INSTRUCTION in it["instruction_id_list"]]
    slots = sum(it["instruction_id_list"].count(INSTRUCTION) for it in items)
    print(f"items carrying {INSTRUCTION}: {len(picked)}; slots: {slots}")
    for side in SIDES:
        path = os.path.join(ROOT, "evidence", "benchmark", f"{side}-ifeval.json")
        if not os.path.exists(path):
            print(f"{side}: {path} is missing")
            return 1
        with open(path, encoding="utf-8") as f:
            records = json.load(f)["records"]
        item_pass = slot_pass = whole = 0
        for i in picked:
            item, rec = items[i], records[i]
            flags = [
                ok
                for name, ok in zip(
                    item["instruction_id_list"],
                    bench_suites.check_ifeval(item, rec["output"]),
                )
                if name == INSTRUCTION
            ]
            slot_pass += sum(flags)
            item_pass += all(flags)
            whole += bool(rec["correct"])
        print(
            f"{side:8s} item-level {item_pass:2d}/{len(picked)} (this instruction alone)"
            f"  slot-level {slot_pass:2d}/{slots}"
            f"  whole-item correct {whole:2d}/{len(picked)}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
