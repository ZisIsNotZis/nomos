#!/usr/bin/env python3
"""Dump every strict-ruler slot disagreement with enough context to hand-check it.

Read-only: it re-runs the same two rulers over the same files that grade_official.py
reads, and prints one record per disagreement. `grade_official.py` writes the JSON; this
script is only the reading aid for HANDCHECK.md.
"""
import json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE
while not os.path.exists(os.path.join(ROOT, "data", "bench", "ifeval.jsonl")):
    parent = os.path.dirname(ROOT)
    if parent == ROOT:
        raise SystemExit(f"no repo root above {HERE} (looked for data/bench/ifeval.jsonl)")
    ROOT = parent
sys.path.insert(0, os.path.join(HERE, "vendor"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from instruction_following_eval import evaluation_lib, instructions_registry
import bench_suites
import langdetect

# Same pin as grade_official.py: langdetect's DetectorFactory.seed defaults to None, so the
# official change_case checkers are not reproducible without it.
langdetect.DetectorFactory.seed = 0


def slots(official_item, output):
    inp = evaluation_lib.InputExample(key=official_item["id"],
                                      instruction_id_list=official_item["instruction_id_list"],
                                      prompt=official_item["prompt"], kwargs=official_item["kwargs"])
    strict = evaluation_lib.test_instruction_following_strict(inp, {official_item["prompt"]: output})
    return list(strict.follow_instruction_list)


def main():
    items = [json.loads(l) for l in open(os.path.join(ROOT, "data/bench/ifeval.jsonl")) if l.strip()]
    for side in ("base", "adapter"):
        recs = json.load(open(os.path.join(ROOT, f"evidence/benchmark/{side}-ifeval.json")))["records"]
        for item, rec in zip(items, recs):
            off = slots(item, rec["output"])
            ours = bench_suites.check_ifeval(item, rec["output"])
            for slot, name in enumerate(item["instruction_id_list"]):
                if ours[slot] == off[slot]:
                    continue
                print("=" * 100)
                print(f"{side} {rec['id']} slot {slot} {name} ours={ours[slot]} official={off[slot]} "
                      f"kwargs={json.dumps(item['kwargs'][slot])}")
                print("PROMPT:", item["prompt"])
                print("-" * 40, "OUTPUT", len(rec["output"]), "chars", "-" * 40)
                print(rec["output"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
