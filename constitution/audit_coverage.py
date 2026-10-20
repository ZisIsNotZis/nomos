#!/usr/bin/env python3
"""Check that the conflict audit partitions the node index exactly and disjointly.

`docs/method/conflicts.md` carries a machine-readable `partition:` block: every
leaf of `constitution/nodes.json` lands either in an examined cluster or in a
named "no candidate pair" bucket, and no leaf lands in two places. This script
parses that block, sums it, and exits nonzero unless the partition is exact and
disjoint. It also checks the two claims the prose makes on top of the partition:
that each examined cluster member appears in at least one candidate pair, and
that the printed counts agree with the block.
"""

import json
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NODES = HERE / "nodes.json"
CONFLICTS = ROOT / "docs" / "method" / "conflicts.md"

SUMMARY_RE = re.compile(
    r"审计计数：叶子 (\d+) = 已检查簇成员 (\d+) \+ 无候选对成员 (\d+)[。；]"
    r"候选对共 (\d+) = 优先级处境 (\d+) \+ 平衡点 (\d+) \+ 无关 (\d+)"
)
# The true-conflict claim is separate from the partition line: it is a verdict
# on the compared pairs, not on all 264 leaves.
CONFLICT_RE = re.compile(r"这 (\d+) 对里真冲突 (\d+)")


def load_partition(text):
    blocks = re.findall(r"```yaml\n(.*?)```", text, re.S)
    for candidate in blocks:
        data = yaml.safe_load(candidate)
        if isinstance(data, dict) and "partition" in data:
            return data["partition"]
    raise SystemExit("no ```yaml partition block in docs/method/conflicts.md")


def main():
    text = CONFLICTS.read_text(encoding="utf-8")
    partition = load_partition(text)
    nodes = [record["dot_path"] for record in json.loads(NODES.read_text(encoding="utf-8"))]
    node_set = set(nodes)

    clusters = partition["clusters"]
    buckets = partition["no_candidate_pair"]
    pairs = partition["pairs"]

    problems = []
    seen = {}
    examined = set()
    for cluster in clusters:
        for member in cluster["members"]:
            seen.setdefault(member, []).append(cluster["name"])
            examined.add(member)
    for bucket in buckets:
        if not bucket.get("reason", "").strip():
            problems.append(f"bucket {bucket['name']} has no reason")
        for member in bucket["members"]:
            if member in examined:
                problems.append(f"{member} is in bucket {bucket['name']} and an examined cluster")
            seen.setdefault(member, []).append(bucket["name"])

    for member, homes in seen.items():
        if len(homes) > 1:
            problems.append(f"{member} appears in {len(homes)} buckets: {homes}")
    missing = sorted(node_set - set(seen))
    unknown = sorted(set(seen) - node_set)
    if missing:
        problems.append(f"{len(missing)} leaf(ves) in no bucket: {missing[:10]}")
    if unknown:
        problems.append(f"{len(unknown)} bucket member(s) not in nodes.json: {unknown[:10]}")

    pair_members = set()
    verdicts = {"优先级处境": 0, "平衡点": 0, "无关": 0, "真冲突": 0}
    for pair in pairs:
        for side in ("a", "b"):
            if pair[side] not in node_set:
                problems.append(f"pair member not in nodes.json: {pair[side]}")
            pair_members.add(pair[side])
        if pair["verdict"] not in verdicts:
            problems.append(f"unknown verdict {pair['verdict']} on {pair['a']}↔{pair['b']}")
        verdicts[pair["verdict"]] += 1

    if pair_members != examined:
        only_pairs = sorted(pair_members - examined)
        only_clusters = sorted(examined - pair_members)
        if only_pairs:
            problems.append(f"{len(only_pairs)} pair member(s) outside examined clusters: {only_pairs[:10]}")
        if only_clusters:
            problems.append(f"{len(only_clusters)} examined cluster member(s) in no pair: {only_clusters[:10]}")

    total = sum(len(c["members"]) for c in clusters) + sum(len(b["members"]) for b in buckets)
    if total != len(nodes):
        problems.append(f"members sum to {total}, nodes.json holds {len(nodes)}")

    match = SUMMARY_RE.search(text)
    if not match:
        problems.append("printed count line not found")
    else:
        printed = [int(value) for value in match.groups()]
        expected = [
            len(nodes),
            len(examined),
            total - len(examined),
            len(pairs),
            verdicts["优先级处境"],
            verdicts["平衡点"],
            verdicts["无关"],
        ]
        if printed != expected:
            problems.append(f"printed counts {printed} != partition {expected}")
    conflict = CONFLICT_RE.search(text)
    if not conflict:
        problems.append("printed true-conflict line not found")
    else:
        scoped_pairs, true_conflicts = (int(value) for value in conflict.groups())
        if scoped_pairs != len(pairs):
            problems.append(
                f"true-conflict line scopes {scoped_pairs} pairs, partition holds {len(pairs)}"
            )
        if true_conflicts != verdicts["真冲突"]:
            problems.append(
                f"printed true conflicts {true_conflicts} != partition {verdicts['真冲突']}"
            )

    print(f"nodes: {len(nodes)}")
    print(f"clusters: {len(clusters)}, examined members: {len(examined)}")
    print(f"no-candidate-pair buckets: {len(buckets)}, members: {total - len(examined)}")
    print(f"partition sum: {total} (exact={'yes' if total == len(nodes) else 'no'}, "
          f"disjoint={'yes' if len(seen) == total else 'no'})")
    print(f"pairs: {len(pairs)} = 优先级处境 {verdicts['优先级处境']} + 平衡点 {verdicts['平衡点']} "
          f"+ 无关 {verdicts['无关']}; 真冲突 {verdicts['真冲突']}")

    if problems:
        print(f"FAIL: {len(problems)} problem(s)", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print("coverage: exact and disjoint")
    return 0


if __name__ == "__main__":
    sys.exit(main())
