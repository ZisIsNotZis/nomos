#!/usr/bin/env python3
"""Assert the class-shape gate's measured behaviour against fixed fixtures.

`constitution/gate_fixtures/*.json` hold the mutations that were run by hand
against `constitution/nodes.json`: a text override or a class override on one
leaf, plus the expected violation count, warning count and build exit code
(the exit `build_nodes.py` gives: 1 when there is a violation, 0 otherwise).

This script applies each mutation to a copy of the index, runs the class-shape
and reason-shape checks, and exits nonzero on any deviation from the recorded
expectation. It exists so the ad-hoc command that measured the gate is not the
only record.
"""

import copy
import json
import sys
from pathlib import Path

import check_class_shape
import check_reason_shape

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "gate_fixtures"


def apply_mutation(records, mutation):
    if not mutation:
        return records
    path = mutation["dot_path"]
    for record in records:
        if record["dot_path"] != path:
            continue
        if "set_text" in mutation:
            record["text"] = mutation["set_text"]
        if "set_class" in mutation:
            record["classification"] = mutation["set_class"]
        if "set_class_reason" in mutation:
            record["class_reason"] = mutation["set_class_reason"]
        if mutation.get("unset_class_reason"):
            record.pop("class_reason", None)
        return records
    raise SystemExit(f"fixture names a leaf not in the index: {path}")


def main(argv):
    fixtures = sorted(FIXTURES.glob("*.json"))
    if not fixtures:
        print(f"FAIL: no fixtures in {FIXTURES}", file=sys.stderr)
        return 1
    records = check_class_shape.load()
    failures = 0
    for origin in fixtures:
        fixture = json.loads(origin.read_text(encoding="utf-8"))
        mutated = apply_mutation(copy.deepcopy(records), fixture["mutation"])
        violations = (
            check_class_shape.find_violations(mutated)
            + check_reason_shape.find_reason_violations(mutated)
        )
        warnings = (
            check_class_shape.find_warnings(mutated)
            + check_reason_shape.find_reason_warnings(mutated)
        )
        actual = {
            "violations": len(violations),
            "warnings": len(warnings),
            "build_exit": 1 if violations else 0,
        }
        expect = fixture["expect"]
        deviation = {key: (expect[key], actual[key])
                     for key in expect if expect[key] != actual[key]}
        status = "PASS" if not deviation else "FAIL"
        if deviation:
            failures += 1
        print(f"{status} {fixture['id']}: violations {actual['violations']}, "
              f"warnings {actual['warnings']}, build_exit {actual['build_exit']}")
        for key, (wanted, got) in deviation.items():
            print(f"  expected {key}={wanted}, got {got}", file=sys.stderr)
    print(f"gate fixtures: {len(fixtures)} run, {failures} deviated")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
