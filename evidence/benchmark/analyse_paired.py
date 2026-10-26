#!/usr/bin/env python3
"""Paired base-vs-adapter comparison for the two frozen benchmark suites.

Reads evidence/benchmark/base-<suite>.json and adapter-<suite>.json, checks that both
runs used the same frozen sample, limit, seed and decoding, then compares them per item
instead of per run. Scoring itself is never recomputed here: `correct` comes from the
stored record, so this script cannot change a verdict.

The paired bootstrap reuses scripts/resample_actions.py: there is one implementation of
that interval in the tree. Exact McNemar is written here because nothing else needs it.

Usage:
  python3 evidence/benchmark/analyse_paired.py            # both suites, exit 1 if a cell is unrun
  python3 evidence/benchmark/analyse_paired.py ifeval     # one suite
  python3 evidence/benchmark/analyse_paired.py ifeval --adapter-tag adapter-e2-ifeval \
      --out-tag paired-e2-ifeval                          # trial cell, leaves the landed pair alone

Flags may appear before or after the suite names; anything else starting with -- is an error
rather than a suite name (a mis-ordered call used to be read as four unrun suites).
"""

import importlib.util
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import bench_suites  # noqa: E402
import resample_actions  # noqa: E402  (bootstrap_diff: the tree's one paired implementation)

ALPHA = 0.05
SUITES = ("gsm8k", "ifeval")
PAIR_FIELDS = ("limit", "seed", "frozen_sha256", "decoding")


def load(name):
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check_same_harness(base, adapter):
    for field in PAIR_FIELDS:
        if base[field] != adapter[field]:
            raise SystemExit(f"harness mismatch on {field}: base={base[field]!r} adapter={adapter[field]!r}")
    base_ids = [r["id"] for r in base["records"]]
    adapter_ids = [r["id"] for r in adapter["records"]]
    if base_ids != adapter_ids:
        raise SystemExit("item ids differ or are out of order; this is not a paired comparison")
    return base_ids


def mcnemar_exact(drops, gains):
    """Two-sided exact McNemar p on the discordant pairs alone."""
    n = drops + gains
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(drops, gains) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def smallest_detectable_drop(n):
    """Smallest net drop, in items, that exact McNemar calls significant when no item is gained."""
    for k in range(n + 1):
        if 0.5 ** k <= ALPHA:
            return k
    return None


def smallest_drop_by_interval(n):
    """Smallest drop, in items, whose paired-bootstrap interval excludes zero with no gains.

    Uses the same bootstrap as the reported interval, so the sensitivity statement and the
    interval cannot disagree about what this n can see.
    """
    same = [1] * n
    for k in range(1, n + 1):
        dropped = [0] * k + [1] * (n - k)
        low, high = resample_actions.bootstrap_diff(dropped, same)
        if high < 0:
            return k
    return None


def compare(suite, adapter_tag=None):
    adapter_name = adapter_tag or f"adapter-{suite}"
    base, adapter = load(f"base-{suite}.json"), load(f"{adapter_name}.json")
    if base is None or adapter is None:
        missing = "base" if base is None else "adapter"
        return {"suite": suite, "status": f"unrun: {missing} side has no evidence file"}
    ids = check_same_harness(base, adapter)
    base_flags = [1 if r["correct"] else 0 for r in base["records"]]
    adapter_flags = [1 if r["correct"] else 0 for r in adapter["records"]]
    n = len(ids)
    b_correct = sum(base_flags)
    a_correct = sum(adapter_flags)
    drops = [i for i in range(n) if base_flags[i] and not adapter_flags[i]]
    gains = [i for i in range(n) if not base_flags[i] and adapter_flags[i]]
    low, high = resample_actions.bootstrap_diff(adapter_flags, base_flags)
    detectable = smallest_detectable_drop(n)
    by_interval = smallest_drop_by_interval(n)
    return {
        "suite": suite,
        "status": "ran",
        "n": n,
        "base": {"correct": b_correct, "accuracy": b_correct / n,
                 "ci95_wilson": list(bench_suites.wilson_interval(b_correct, n))},
        "adapter": {"correct": a_correct, "accuracy": a_correct / n,
                    "ci95_wilson": list(bench_suites.wilson_interval(a_correct, n))},
        "delta_adapter_minus_base": (a_correct - b_correct) / n,
        "delta_ci95_paired_bootstrap": [low, high],
        "paired": {
            "drops": len(drops), "gains": len(gains),
            "drop_ids": [ids[i] for i in drops], "gain_ids": [ids[i] for i in gains],
            "unchanged": n - len(drops) - len(gains),
            "mcnemar_exact_p": mcnemar_exact(len(drops), len(gains)),
        },
        "detectable": {
            "smallest_drop_items_with_no_gains": detectable,
            "smallest_drop_pp_with_no_gains": None if detectable is None else detectable / n,
            "smallest_drop_items_by_paired_interval": by_interval,
            "smallest_drop_pp_by_paired_interval": None if by_interval is None else by_interval / n,
            "alpha": ALPHA,
        },
        "harness": {f: base[f] for f in PAIR_FIELDS} | {"adapter_dir": adapter["adapter_dir"]},
        "elapsed_seconds": {"base": base["elapsed_seconds"], "adapter": adapter["elapsed_seconds"]},
    }


def pct(x):
    return "—" if x is None else f"{100 * x:5.1f}%"


def main():
    argv = sys.argv[1:]
    adapter_tag = None
    out_tag = None
    suites = []
    while argv:                            # flags may sit before or after the suite names
        arg = argv.pop(0)
        if arg == "--adapter-tag":
            adapter_tag = argv.pop(0)      # read <tag>.json instead of adapter-<suite>.json
        elif arg == "--out-tag":
            out_tag = argv.pop(0)          # write <out-tag>.json instead of paired-<suite>.json
        elif arg.startswith("--"):
            raise SystemExit(f"unknown flag {arg}")
        else:
            suites.append(arg)
    suites = suites or list(SUITES)
    out = []
    for suite in suites:
        result = compare(suite, adapter_tag)
        out.append(result)
        if result["status"] != "ran":
            print(f"{suite:7s} {result['status']}")
            continue
        p = result["paired"]
        print(f"{suite:7s} base {result['base']['correct']}/{result['n']} = {pct(result['base']['accuracy'])}"
              f"  adapter {result['adapter']['correct']}/{result['n']} = {pct(result['adapter']['accuracy'])}"
              f"  delta {pct(result['delta_adapter_minus_base'])}"
              f"  paired CI [{pct(result['delta_ci95_paired_bootstrap'][0])},"
              f" {pct(result['delta_ci95_paired_bootstrap'][1])}]"
              f"  drops {p['drops']} gains {p['gains']}  McNemar p={p['mcnemar_exact_p']:.3f}"
              f"  min detectable drop {pct(result['detectable']['smallest_drop_pp_with_no_gains'])} (McNemar)"
              f" / {pct(result['detectable']['smallest_drop_pp_by_paired_interval'])} (interval)")
        out_name = out_tag or f"paired-{suite}"
        with open(os.path.join(HERE, f"{out_name}.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
            f.write("\n")
    unrun = [r["suite"] for r in out if r["status"] != "ran"]
    return 1 if unrun else 0


if __name__ == "__main__":
    sys.exit(main())
