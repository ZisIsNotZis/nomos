#!/usr/bin/env python3
"""Probe 6's pair reconstruction, request construction and statistics.

Probe 5's same-condition control showed the forced-choice judge prefers the
second-listed answer (Y in 42 of 47 decisive control pairs), so probe 4's 0.594
and probe 5's 0.563 are confounded with position. Probe 6 does not generate or
change anything: it takes every stored pair from both probes and judges it twice,
once in the stored X/Y order and once with the two answers swapped. A pair then
counts only if both orders point the same way.

The judge prompt, the situation loading and the interval functions are probe 4's
(`p4`), so the "stored" order here is byte-identical to the stored requests.
"""

import hashlib
import importlib.util
import json
import math
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PROBE4 = REPO / "report" / "probe-4"
PROBE5 = REPO / "report" / "probe-5"
PROBE2 = REPO / "report" / "probe-2"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


p4 = _load("probe6_p4", PROBE4 / "common.py")

sys.path.insert(0, str(PROBE2))
import probe_lib as lib  # noqa: E402  endpoint, key check, pricing, cost

CALLS = HERE / "calls.jsonl"
JUDGE_OUT = HERE / "judge-out.jsonl"

MAX_TOKENS_JUDGE = 500
ORDERS = ("stored", "swapped")

P5_SITUATIONS = PROBE5 / "situations.jsonl"
P5_ANSWERS = PROBE5 / "answers.jsonl"
P5_MAP = PROBE5 / "map.json"
P4_SITUATIONS = PROBE4 / "situations.jsonl"
P4_ANSWERS = PROBE4 / "answers.jsonl"
P4_MAP = PROBE4 / "map.json"

# Execution order; the last one is the block a budget stop drops first.
DATASETS = ("p5_paired", "p5_control", "p4_full_vs_bare", "p4_slice_vs_bare")
CONTROL = "p5_control"
POLICY_ARM = {
    "p5_paired": "full",
    "p4_full_vs_bare": "full",
    "p4_slice_vs_bare": "slice",
}

SEED_BOOTSTRAP = 20261101
Z = p4.Z


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def load_jsonl(path):
    return p4.load_jsonl(path)


def policy_text():
    return p4.policy_text()


def policy_sha():
    return p4.policy_sha()


def _p5_pairs():
    situations = {row["id"]: row for row in load_jsonl(P5_SITUATIONS)}
    answers = {(row["situation"], row["arm"], row["draw"]): row["response"]
               for row in load_jsonl(P5_ANSWERS)}
    mapping = json.loads(P5_MAP.read_text(encoding="utf-8"))
    pairs = []
    for sid in sorted(situations, key=lambda value: int(value[5:])):
        situation = situations[sid]
        for draw in range(1, len(mapping["paired"][sid]) + 1):
            side = mapping["paired"][sid][draw - 1]
            text = {arm: answers[(sid, arm, draw)] for arm in ("bare", "full")}
            pairs.append({
                "dataset": "p5_paired", "situation": sid, "session": situation["session"],
                "excerpt": situation["excerpt"], "draw": draw,
                "stored": {"X": side["X"], "Y": side["Y"]}, "text": text,
            })
        side = mapping["control"][sid]
        text = {f"full#{n}": answers[(sid, "full", n)] for n in (1, 2)}
        stored = {"X": f"full#{side['X']}", "Y": f"full#{side['Y']}"}
        pairs.append({
            "dataset": CONTROL, "situation": sid, "session": situation["session"],
            "excerpt": situation["excerpt"], "draw": 0,
            "stored": stored, "text": text,
        })
    return pairs


def _p4_pairs():
    situations = {row["id"]: row for row in load_jsonl(P4_SITUATIONS)}
    answers = {}
    for row in load_jsonl(P4_ANSWERS):
        answers.setdefault((row["situation"], row["arm"]), row["response"])
    mapping = json.loads(P4_MAP.read_text(encoding="utf-8"))
    pairs = []
    for sid in sorted(situations, key=lambda value: int(value[3:])):
        situation = situations[sid]
        for comparison in ("full_vs_bare", "slice_vs_bare"):
            policy = POLICY_ARM[f"p4_{comparison}"]
            side = mapping[comparison][sid]
            text = {"bare": answers[(sid, "bare")], policy: answers[(sid, policy)]}
            pairs.append({
                "dataset": f"p4_{comparison}", "situation": sid,
                "session": situation["session"], "excerpt": situation["excerpt"],
                "draw": 0, "stored": {"X": side["X"], "Y": side["Y"]}, "text": text,
            })
    return pairs


def pairs():
    """Every stored comparison, with the stored X/Y order and both answer texts."""
    rows = _p5_pairs() + _p4_pairs()
    for row in rows:
        row["identical"] = row["text"][row["stored"]["X"]] == row["text"][row["stored"]["Y"]]
    return rows


def key_of(pair):
    return (pair["dataset"], pair["situation"], pair["draw"])


def labels_for(pair, order):
    """Arm labels in the X and Y slots, for one of the two orders."""
    stored = (pair["stored"]["X"], pair["stored"]["Y"])
    return stored if order == "stored" else (stored[1], stored[0])


def request_for(pair, order):
    """The judge prompt for one order; only the slot labels differ between orders."""
    labels = labels_for(pair, order)
    return p4.build_judge_prompt(pair["excerpt"], {"X": labels[0], "Y": labels[1]},
                                 pair["text"], None)


def winner_label(pair, order, winner):
    """The arm label the judge picked, or `tie`."""
    if winner == "tie":
        return "tie"
    labels = labels_for(pair, order)
    return labels[0] if winner == "X" else labels[1]


def parse_judge_answer(text, policy):
    """Probe 4's judge JSON parser, unchanged in substance."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        raise SystemExit(f"judge returned no JSON object: {text[:300]}")
    raw = json.loads(match.group(0))
    winner = str(raw.get("winner", "")).strip()
    winner = "tie" if winner.lower() == "tie" else winner.upper()
    if winner not in ("X", "Y", "tie"):
        guess = re.search(r"\b(X|Y|tie)\b", cleaned, flags=re.IGNORECASE)
        if not guess:
            raise SystemExit(f"judge winner is not X/Y/tie: {raw!r}")
        winner = "tie" if guess.group(1).lower() == "tie" else guess.group(1).upper()
    clause = str(raw.get("clause", "")).strip()
    reason = str(raw.get("reason", "")).strip()[:500]
    if not clause:
        raise SystemExit(f"judge returned no clause: {raw!r}")
    return {"winner": winner, "clause": clause, "reason": reason,
            "clause_ok": clause in policy}


def pair_status(dataset, first, second):
    """Collapse the two orders' verdicts into one state for the pair."""
    if "tie" in (first, second):
        return "tie"
    if first == second:
        if dataset == CONTROL:
            return "same"
        return "policy" if first == POLICY_ARM[dataset] else "bare"
    return "inconsistent"


def wilson(k, n):
    return p4.wilson(k, n)


def cluster_bootstrap(rows, wins, losses, seed=SEED_BOOTSTRAP, reps=10000):
    """Session-clustered percentile interval for a share of two outcome labels.

    `rows` is a list of (session, outcome_label) pairs; only `wins` and `losses`
    enter the ratio, and whole sessions are resampled so repeated situations in
    one session are not counted as independent.
    """
    by_session = {}
    for session, outcome in rows:
        within = by_session.setdefault(session, [0, 0])
        if outcome == wins:
            within[0] += 1
        elif outcome == losses:
            within[1] += 1
    keys = sorted(by_session)
    rng = random.Random(seed)
    values = []
    for _ in range(reps):
        w = l = 0
        for _ in keys:
            counts = by_session[keys[rng.randrange(len(keys))]]
            w += counts[0]
            l += counts[1]
        if w + l:
            values.append(w / (w + l))
    values.sort()
    return values[int(0.025 * len(values))], values[int(0.975 * len(values))]


def call_cost(usage, created):
    return lib.call_cost(usage, created)


def append_rows(path, rows):
    with Path(path).open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
