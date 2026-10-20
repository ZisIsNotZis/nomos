#!/usr/bin/env python3
"""Refuse a node index whose class contradicts the leaf's textual shape.

The check is the mechanical arm of `constitution/CLASSIFY.md`: it cannot repeat
the audit's judgement, but it can catch the two directional misfiles that made
the training hole silent.

  A. a leaf classed `definitional` or `conceptual` that still carries an
     executable action clause on task state is refused: it prescribes an act and
     is nevertheless filed as untrainable.
  B. a leaf classed `behavior` whose text names neither an action form nor any
     observable object is refused: nothing can be marked done or missed on it.

Both directions exempt a clause that names a law-ontology object (node, rule,
layer, source, class, home, document kind, fact): a leaf about the law's own
constitution is definitional even when phrased as an instruction
(`precedence.source_order`: "Rank, highest first: ..."). Optimisation verbs
(minimise, prefer, balance) are not closable acts and are left to step 4, so
`intent.objective.cost_function` is not flagged.

That exemption is the check's blind spot: an imperative clause that also names a
law-ontology object is not decidable mechanically, so `find_warnings` emits it
with its path and clause instead of letting it pass silently. Warnings do not
fail the check; they are the escalation route in `constitution/CLASSIFY.md`.

Reads `constitution/nodes.json` unless a path is given; `--from-git REV` reads
`constitution/nodes.json` at that revision instead, which reproduces the
negative control recorded in CLASSIFY.md.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_NODES = HERE / "nodes.json"

# Imperative mood: a base-form verb that opens a clause, or a coordinated bare
# infinitive after a comma. Optimisation verbs are deliberately absent.
IMPERATIVES = (
    "Add", "Agree", "Answer", "Apply", "Ask", "Bind", "Bring", "Build", "Check",
    "Choose", "Close", "Commit", "Compare", "Confirm", "Declare", "Decide",
    "Define", "Delete", "Derive", "Design", "Disclose", "Distinguish", "Do",
    "Drop", "Escalate", "Exclude", "Fetch", "Find", "Follow", "Freeze", "Give",
    "Hand", "Include", "Judge", "Keep", "Land", "Leave", "Let", "List", "Make",
    "Mark", "Measure", "Migrate", "Name", "Note", "Open", "Parse", "Preserve",
    "Propose", "Push", "Put", "Quote", "Rank", "Read", "Record", "Refuse",
    "Remove", "Report", "Replace", "Resolve", "Revert", "Rerun", "Run", "Say",
    "Scan", "Send", "Separate", "Set", "Ship", "Spawn", "Split", "Start",
    "Stop", "Store", "Take", "Tell", "Test", "Track", "Treat", "Turn", "Use",
    "Verify", "Wait", "Write",
)
_VERBS = "|".join(IMPERATIVES)
# I1: clause-initial imperative, either case.
IMPERATIVE_RE = re.compile(r"(?:^|[.;:]\s+)(%s)\b" % _VERBS, re.IGNORECASE)
# I2: coordinated bare infinitive after a comma or semicolon. Nouns double as
# imperatives in English (test, check, run, list, mark, name), so I2 keeps only
# verbs that cannot be read as the object of the preceding clause.
COORDINATED = (
    "write", "treat", "record", "ask", "delete", "keep", "remove", "stop",
    "choose", "quote", "spawn", "escalate", "preserve", "revert", "migrate",
    "ship", "disclose", "propose", "report", "replace", "resolve",
    "distinguish", "verify", "read", "commit", "push", "fetch", "drop",
    "refuse", "rerun",
)
COORDINATED_RE = re.compile(r"[,;]\s+(%s)\b" % "|".join(COORDINATED))

# Obligation or prohibition stated in the indicative rather than the imperative.
DEONTIC_RE = re.compile(
    r"\b(?:never|must|all require|required?\b|shall|forbidden|do not|does not|"
    r"cannot|is not a licence)\b",
    re.IGNORECASE,
)

# Nouns that name an object a trajectory can observe.
TASK_OBJECTS = {
    "action", "agent", "answer", "artefact", "artifact", "audience", "baseline",
    "branch", "candidate", "capacity", "check", "child", "ci", "code",
    "command", "commit", "comparison", "consent", "cost", "criterion", "dataset",
    "decision", "defect", "demo", "device", "diff", "draft", "error", "evidence",
    "expertise", "failure", "fixture", "gate", "goal", "gpu", "hardware", "input",
    "job", "language", "licence", "license", "log", "measurement", "memory",
    "message", "milestone", "mirror", "model", "network", "number", "output",
    "patch", "path", "permission", "picture", "plan", "phase", "probe", "claim",
    "conflict", "behaviour",
    "prompt", "question", "reading", "record", "regression", "release", "repo",
    "report", "reproduction", "request", "requirement", "resource", "result",
    "review", "risk", "run", "safety", "sample", "scenario", "schema", "scope",
    "script", "secret", "session", "skill", "spec", "spend", "statement", "table",
    "task", "test", "thread", "tool", "token", "usage", "user", "version",
    "wallet", "work",
}
# Nouns that name a part of the law itself.
LAW_OBJECTS = {
    "chain", "citation", "class", "continuation", "doc", "document", "fact",
    "file", "home", "kind", "layer", "line", "node",
    "policy", "rank", "render", "rule", "router", "source", "stereotype", "term",
}


def has_imperative(clause):
    return bool(IMPERATIVE_RE.search(clause) or COORDINATED_RE.search(clause))


def clauses(text):
    return [c for c in re.split(r"(?<=[.;:])\s+|\s+ - ", text) if c.strip()]


def words(clause):
    tokens = re.findall(r"[a-z]+", clause.lower())
    return {t[:-1] if len(t) > 3 and t.endswith("s") else t for t in tokens} | set(tokens)


def find_warnings(records):
    """Imperative clauses the law-ontology exemption keeps from a verdict.

    A definitional or conceptual clause that names a law-ontology object is
    exempt from direction A, so an instruction phrased about the law's own
    parts (`Record the fact in the layer document, then write the file.`) would
    pass silently. It is emitted here instead, for a reader to decide with the
    procedure; the check itself will not approve it.
    """
    warnings = []
    for record in records:
        if record["classification"] == "behavior":
            continue
        for clause in clauses(record["text"]):
            if words(clause) & LAW_OBJECTS and has_imperative(clause):
                warnings.append(
                    f"{record['dot_path']}: clause names a law-ontology object and "
                    f"carries an imperative, undecidable mechanically: "
                    f"{clause.strip()[:100]!r}"
                )
    return warnings


def find_violations(records):
    violations = []
    for record in records:
        path, text, cls = record["dot_path"], record["text"], record["classification"]
        if cls in ("definitional", "conceptual"):
            text_imperative = has_imperative(text)
            for clause in clauses(text):
                names = words(clause)
                if names & LAW_OBJECTS:
                    continue
                if not names & TASK_OBJECTS:
                    continue
                if text_imperative or has_imperative(clause) or DEONTIC_RE.search(clause):
                    violations.append(
                        f"{path}: classed {cls} but carries an executable clause: "
                        f"{clause.strip()[:100]!r}"
                    )
                    break
        elif cls == "behavior":
            if words(text) & TASK_OBJECTS:
                continue
            if has_imperative(text) or DEONTIC_RE.search(text):
                continue
            violations.append(
                f"{path}: classed behavior but names no action form and no observable object"
            )
    return violations


def load(records_path=None, revision=None):
    if revision:
        raw = subprocess.run(
            ["git", "show", f"{revision}:constitution/nodes.json"],
            capture_output=True, text=True, check=True,
        ).stdout
        return json.loads(raw)
    origin = Path(records_path) if records_path else DEFAULT_NODES
    return json.loads(origin.read_text(encoding="utf-8"))


def main(argv):
    revision = None
    records_path = None
    args = list(argv[1:])
    while args:
        arg = args.pop(0)
        if arg == "--from-git":
            revision = args.pop(0)
        else:
            records_path = arg
    records = load(records_path, revision)
    violations = find_violations(records)
    warnings = find_warnings(records)
    if violations:
        print(f"FAIL: {len(violations)} leaf(ves) contradict their class", file=sys.stderr)
        for line in violations:
            print(f"  {line}", file=sys.stderr)
        return 1
    for line in warnings:
        print(f"  WARN: {line}", file=sys.stderr)
    print(f"class shape: {len(records)} leaves agree with their class")
    print(f"class warnings: {len(warnings)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
