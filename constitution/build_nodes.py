#!/usr/bin/env python3
"""Regenerate constitution/nodes.json from the frozen constitution/AGENTS.yaml.

A leaf node is a node with no non-`_text` children. identities are dot paths;
line numbers are never used as identifiers. The per-leaf class, decision step,
quoted reason and contestable flag come from `constitution/classification.json`,
judged by the procedure in `constitution/CLASSIFY.md`; the prior triage's tables
are bound to a stale AGENTS.yaml revision and are not used.

`trainable` means "can serve as a training sample's target rule":
  behavior and not held out by spec.md §7. conceptual/definitional nodes do not
  enter the sample body (they may explain a chosen answer or a system prompt),
  so they are not trainable but are excluded for that reason, not because they
  are tool- or host-bound.
Before writing, the shape check in `constitution/check_class_shape.py` refuses a
class that contradicts the leaf's text, and `constitution/check_reason_shape.py`
refuses a leaf with no `class_reason`; a reason that cannot carry its class is
printed as a WARN line with the `reason warnings: N` count, and the build still
exits 0. Clauses the class check cannot decide (an imperative that names only a
law-ontology object) are printed as WARN lines with the `class warnings: N`
count.

Exclusion reasons:
  tool-bound/host-bound  - spec.md §7 hold-out (scaffold, CI or outer authority).
  conceptual/definitional - no action directive to train on; not sample body.
"""

import hashlib
import json
import sys
import unicodedata
from pathlib import Path

import yaml

import check_class_shape
import check_reason_shape

HERE = Path(__file__).resolve().parent
FROZEN = HERE / "AGENTS.yaml"
LOCK = HERE / "lock.yaml"
NODES = HERE / "nodes.json"
CLASSIFICATION_FILE = HERE / "classification.json"

# spec.md §7: tool-bound / host-bound / desktop-interface nodes held out of training.
HOLDOUT_PREFIXES = (
    "resources.work_areas.",
    "resources.machine.",
    "attention.communication.open_",
)
HOLDOUT_PATHS = {
    "attention.communication.desktop_courtesy",
    "resources.environment.bootstrap",
    "resources.environment.cleanup_check",
    "change.upkeep.rebuild_after_edit",
    "proof.execution.check_gates",
}

HOLDOUT_REASON = "tool-bound or host-bound; spec.md §7 holds it out of training"


def leaf_nodes(document):
    """Yield (dot_path, text) in document order for nodes with no child nodes."""
    def walk(node, path):
        if isinstance(node, dict):
            children = {k: v for k, v in node.items() if k != "_text"}
            if children:
                for key, value in children.items():
                    yield from walk(value, f"{path}.{key}" if path else key)
            else:
                yield path, node.get("_text", "")
        else:
            yield path, node

    for key, value in document.items():
        yield from walk(value, key)


def normalise_text(text):
    return " ".join(unicodedata.normalize("NFC", text).split())


def text_sha256(text):
    return hashlib.sha256(normalise_text(text).encode("utf-8")).hexdigest()


def load_classification():
    """The audit's per-leaf judgement, produced by the CLASSIFY.md procedure."""
    document = json.loads(CLASSIFICATION_FILE.read_text(encoding="utf-8"))
    return document["nodes"]


def classify(path, classification):
    if path not in classification:
        raise SystemExit(f"unclassified leaf node: {path}")
    return classification[path]


def is_holdout(path):
    return path in HOLDOUT_PATHS or path.startswith(HOLDOUT_PREFIXES)


def build_records():
    document = yaml.safe_load(FROZEN.read_text(encoding="utf-8"))
    classification = load_classification()
    paths = {path for path, _ in leaf_nodes(document)}
    unknown = sorted(set(classification) - paths)
    if unknown:
        raise SystemExit(f"classification.json names non-leaf nodes: {unknown[:5]}")
    records = []
    for path, text in leaf_nodes(document):
        judgement = classify(path, classification)
        cls = judgement["classification"]
        if cls == "behavior" and not is_holdout(path):
            trainable, reason = True, None
        elif is_holdout(path):
            trainable, reason = False, HOLDOUT_REASON
        else:
            trainable, reason = False, (
                f"{cls}; no action directive to train, not sample body"
            )
        records.append(
            {
                "dot_path": path,
                "text": text,
                "text_sha256": text_sha256(text),
                "parent": path.rsplit(".", 1)[0] if "." in path else None,
                "depth": path.count("."),
                "classification": cls,
                "class_step": judgement["class_step"],
                "class_reason": judgement["class_reason"],
                "contestable": judgement["contestable"],
                "alt_class": judgement.get("alt_class"),
                "trainable": trainable,
                "exclusion_reason": reason,
            }
        )
    return records


def serialise(records):
    return json.dumps(records, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def main(argv):
    write = "--write" in argv[1:]
    records = build_records()
    rendered = serialise(records)

    lock = yaml.safe_load(LOCK.read_text(encoding="utf-8"))
    actual = hashlib.sha256(FROZEN.read_bytes()).hexdigest()
    if actual != lock["sha256"]:
        print(
            f"FATAL: frozen copy sha256 {actual} != lock.yaml {lock['sha256']}",
            file=sys.stderr,
        )
        return 1

    violations = check_class_shape.find_violations(records)
    if violations:
        print(
            f"FATAL: {len(violations)} leaf(ves) contradict their class "
            "(see constitution/check_class_shape.py)",
            file=sys.stderr,
        )
        for line in violations:
            print(f"  {line}", file=sys.stderr)
        return 1
    reason_violations = check_reason_shape.find_reason_violations(records)
    if reason_violations:
        print(
            f"FATAL: {len(reason_violations)} leaf(ves) have no class_reason "
            "(see constitution/check_reason_shape.py)",
            file=sys.stderr,
        )
        for line in reason_violations:
            print(f"  {line}", file=sys.stderr)
        return 1
    warnings = check_class_shape.find_warnings(records)
    for line in warnings:
        print(f"  WARN: {line}", file=sys.stderr)
    reason_warnings = check_reason_shape.find_reason_warnings(records)
    for line in reason_warnings:
        print(f"  WARN: {line}", file=sys.stderr)

    counts = {name: sum(r["classification"] == name for r in records)
              for name in ("behavior", "conceptual", "definitional")}
    untrainable = sum(not r["trainable"] for r in records)
    contestable = sum(r["contestable"] for r in records)

    if write or not NODES.exists():
        NODES.write_text(rendered, encoding="utf-8")
    elif NODES.read_text(encoding="utf-8") != rendered:
        print("FATAL: nodes.json differs from regeneration of AGENTS.yaml; "
              "run with --write", file=sys.stderr)
        return 1

    print(f"leaf nodes: {len(records)}")
    print(f"behavior: {counts['behavior']}")
    print(f"conceptual: {counts['conceptual']}")
    print(f"definitional: {counts['definitional']}")
    print(f"untrainable: {untrainable}")
    print(f"trainable: {len(records) - untrainable}")
    print(f"contestable: {contestable}")
    print(f"class warnings: {len(warnings)}")
    print(f"reason warnings: {len(reason_warnings)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
