#!/usr/bin/env python3
"""Refuse a class_reason that cannot carry the class it is recorded against.

`check_class_shape.py` reads the leaf's text; this check reads the reason the
audit wrote beside the verdict. The recurring failure is not a wrong verdict but
a reason that quotes an ownership sentence or a preference sentence as if it
were the decisive action, so the class looks decided while nothing decided it.

The rule is one per class, applied to the reason's quoted sentence (the text in
quotation marks, or the text before the `——` gloss):

  behavior      an imperative, or a deontic marker with a task object. A
                copular or possessive sentence (`is`, `are`, `belongs`, `refers`,
                `means`, `consists`, `is a`) cannot decide behavior.
  definitional  copular, possessive, enumerative or rank-shaped. An imperative
                on a task object cannot decide definitional.
  conceptual    a judgement or goal shape (copular stance, minimise, prefer,
                outweigh, a quality comparison). An imperative on a task object
                cannot decide conceptual.

A mismatch is a WARN: the gate may not overrule the audit's judgement, it can
only make an undecidable reason visible with a count. A leaf with no
`class_reason` at all is a FAIL, because an undecided reason is not a judgement.

Reads `constitution/nodes.json` unless a path is given; `--from-git REV` reads
that revision's index.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import check_class_shape

HERE = Path(__file__).resolve().parent
DEFAULT_NODES = HERE / "nodes.json"

# The reason corpus uses imperative verbs the leaf check's narrow list omits
# (an instruction may sit behind a fronted adverbial: "When writing ..., lead
# with ..."). Only verbs that cannot be read as the object of the preceding
# clause belong here.
EXTRA_IMPERATIVES = (
    "Adjust", "Announce", "Ask", "Capture", "Change", "Check", "Classify",
    "Clean", "Complete", "Confirm", "Continue", "Coordinate", "Default",
    "Defuse", "Deliver", "Detach", "Diagnose", "Disclose", "Document",
    "Enumerate", "Enter", "Establish", "Exercise", "Explain", "Falsify", "Fix", "Flag",
    "Hold", "Implement", "Infer", "Inherit", "Inspect", "Isolate", "Kill",
    "Launch", "Lead", "Match", "Monitor", "Move", "Note", "Overlap", "Pause",
    "Persist", "Place", "Prevent", "Quantify", "Rebuild", "Reduce",
    "Regenerate", "Reuse", "Rewrite", "Route", "Schedule", "Serialize",
    "Show", "Spend", "State", "Steer", "Surface", "Think", "Translate",
    "Update", "Validate", "Verify",
)
IMPERATIVES = tuple(dict.fromkeys(check_class_shape.IMPERATIVES + EXTRA_IMPERATIVES))
_VERBS = "|".join(re.escape(verb) for verb in IMPERATIVES)
# Clause-initial imperative, or a bare imperative after a comma or colon. The
# comma arm is what makes a fronted adverbial readable ("In feedback, fix ...").
IMPERATIVE_RE = re.compile(r"(?:^|[.;:,]\s+)(%s)\b(?!-)" % _VERBS, re.IGNORECASE)
# A prohibition written with the verb after the negation.
NEGATED_IMPERATIVE_RE = re.compile(
    r"\b(?:never|do not|don't)\s+(%s)\b" % _VERBS, re.IGNORECASE
)
# Optimisation verbs are judgements, not closable acts (CLASSIFY step 4).
OPTIMISATION_RE = re.compile(
    r"\b(?:minimi[sz]e|maximi[sz]e|prefer|outweigh|balance|avoid)\b",
    re.IGNORECASE,
)

# Deontic markers, plus bare "no" so a possessive prohibition ("needs no
# repeated permission") is readable; CHECK's DEONTIC_RE does not carry it.
DEONTIC_RE = re.compile(
    check_class_shape.DEONTIC_RE.pattern + r"|\bno\b", re.IGNORECASE
)

# Task objects from the leaf check, plus runtime-material nouns (CLASSIFY step
# 1) and a few delivery objects the reason corpus names.
TASK_OBJECTS = check_class_shape.TASK_OBJECTS | {
    "completion", "content", "data", "deadline", "project",
    "recommendation", "repository", "retraction", "summary", "truth",
}

COPULAR_RE = re.compile(
    r"\b(?:is|are|was|were|be|been|being|means?|refers?|consists?|"
    r"counts? as|belongs?|holds?|has|have|carries|owns?|binds?|lives?|"
    r"remains?|stays?)\b",
    re.IGNORECASE,
)
ENUMERATIVE_RE = re.compile(
    r"\b(?:one|two|three|four|five|each|every|all|comprises?|includes?|"
    r"types? of|kinds? of)\b|…|(?:,[^.;:]+){2,}\s+and\b",
    re.IGNORECASE,
)
RANK_RE = re.compile(
    r"\b(?:rank|highest first|wins?|settled by|form one chain|constrains?|"
    r"before|after|order)\b",
    re.IGNORECASE,
)
# A judgement, goal or quality stance: copular stance, an optimisation verb, a
# comparative quality claim, or a modal norm ("should match").
JUDGEMENT_RE = re.compile(
    r"\b(?:is|are|means?|refers?|consists?|counts? as|shapes?|should|must|"
    r"better|worse|fine only|as close (?:to .{0,40})?as|more .{1,20} than|less .{1,20} than|"
    r"matters?|worth|so that|at a time|beats?|minimi[sz]e|maximi[sz]e|prefer|"
    r"outweigh|balance|avoid)\b",
    re.IGNORECASE,
)


def decisive_sentence(class_reason):
    """The text the reason offers as decisive, without its Chinese gloss."""
    quoted = re.findall(r'"([^"]+)"', class_reason)
    if quoted:
        return " ".join(quoted).strip()
    return re.split(r"\s*——\s*", class_reason, maxsplit=1)[0].strip()


def has_imperative(text):
    return bool(IMPERATIVE_RE.search(text) or NEGATED_IMPERATIVE_RE.search(text))


def imperative_on_task_object(text):
    # A clause about the law's own parts is a structural statement, not a task
    # act (the same exemption check_class_shape applies).
    if check_class_shape.words(text) & check_class_shape.LAW_OBJECTS:
        return False
    for match in IMPERATIVE_RE.finditer(text):
        clause = text[match.start():]
        if check_class_shape.words(clause) & TASK_OBJECTS:
            return True
    return bool(NEGATED_IMPERATIVE_RE.search(text)) and bool(
        check_class_shape.words(text) & TASK_OBJECTS
    )


def behavior_carries(text):
    if has_imperative(text):
        return True
    return bool(DEONTIC_RE.search(text) and check_class_shape.words(text) & TASK_OBJECTS)


def _is_enumerative_list(text):
    return text.count(",") >= 2 and " and " in text


def definitional_carries(text):
    if imperative_on_task_object(text):
        return False
    return bool(COPULAR_RE.search(text) or ENUMERATIVE_RE.search(text)
                or _is_enumerative_list(text) or RANK_RE.search(text))


def conceptual_carries(text):
    # An optimisation verb with an object is a judgement, not a task act.
    if imperative_on_task_object(OPTIMISATION_RE.sub("", text)):
        return False
    return bool(JUDGEMENT_RE.search(text))


CARRIES = {
    "behavior": behavior_carries,
    "definitional": definitional_carries,
    "conceptual": conceptual_carries,
}


def find_reason_violations(records):
    return [
        f"{record['dot_path']}: no class_reason; the class is undecided"
        for record in records
        if not (record.get("class_reason") or "").strip()
    ]


def find_reason_warnings(records):
    warnings = []
    for record in records:
        reason = record.get("class_reason") or ""
        if not reason.strip():
            continue
        cls = record["classification"]
        sentence = decisive_sentence(reason)
        carries = CARRIES.get(cls)
        if carries is None or carries(sentence):
            continue
        warnings.append(
            f"{record['dot_path']}: classed {cls} but its reason cannot carry it: "
            f"{sentence[:120]!r}"
        )
    return warnings


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
    violations = find_reason_violations(records)
    warnings = find_reason_warnings(records)
    if violations:
        print(f"FAIL: {len(violations)} leaf(ves) have no class_reason", file=sys.stderr)
        for line in violations:
            print(f"  {line}", file=sys.stderr)
        return 1
    for line in warnings:
        print(f"  WARN: {line}", file=sys.stderr)
    print(f"reason shape: {len(records)} reasons checked")
    print(f"reason warnings: {len(warnings)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
