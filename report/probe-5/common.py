#!/usr/bin/env python3
"""Pieces shared by probe 5's build, judges and analysis.

Probe 4 measured the policy effect with one generation draw per condition, and
found temperature 0 on this endpoint is not deterministic. Probe 5 asks how much
of the 0.594 full-vs-bare share is draw noise.

It does two cheap things and one measurement:

1. re-judges probe 2's 20 stored answer pairs twice with the probe-4 judge,
   separating judge variance from generation variance;
2. generates three answers per condition (`bare`, `full`) for 60 situations
   drawn from probe 4's pool, so the paired comparison can be repeated within a
   situation;
3. judges three paired comparisons per situation plus one same-condition
   control pair (`full_1` vs `full_2`), where a well-behaved judge has no reason
   to prefer either side.

The probe-4 functions (policy bytes, judge prompt, Wilson interval, situation
loading) are imported as `p4` rather than copied, so the judge and the arm
construction are literally probe 4's.
"""

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
PROBE3 = REPO / "report" / "probe-3"
PROBE2 = REPO / "report" / "probe-2"

_spec = importlib.util.spec_from_file_location("probe4common", PROBE4 / "common.py")
p4 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p4)

sys.path.insert(0, str(PROBE2))
import probe_lib as lib  # noqa: E402  endpoint, key check, pricing, cost

SITUATIONS = HERE / "situations.jsonl"
MAP = HERE / "map.json"
ANSWERS = HERE / "answers.jsonl"
CALLS = HERE / "calls.jsonl"
JUDGE_OUT = HERE / "judge-out.jsonl"
VARIANCE = HERE / "judge-variance.jsonl"

SOURCE_SITUATIONS = PROBE4 / "situations.jsonl"
P3_SITUATIONS = PROBE3 / "situations.jsonl"
P3_PAIRS = PROBE3 / "pairs.jsonl"
P3_MAP = PROBE3 / "map.json"
P3_JUDGE_OUT = PROBE3 / "judge-out.jsonl"
P2_JUDGE_OUT = PROBE2 / "judge" / "judge-out.jsonl"
P2_MAP = PROBE2 / "judge" / "map.json"

MAX_TOKENS_GENERATE = 600
MAX_TOKENS_JUDGE = 500
GENERATED_ARMS = ("bare", "full")
DRAWS = 3

SEED_SELECT = 20261027
SEED_PAIRED_MAP = 20261030
SEED_CONTROL_MAP = 20261031
SEED_BOOTSTRAP = 20261029

# Proportional to probe 4's signal counts (61 / 68 / 24 / 16 / 14 of 183),
# rounded by largest remainder to 60.
SIGNAL_ALLOCATION = {
    "S1_interrupt_after_tool_call": 20,
    "S2_tool_burst_no_checkpoint": 5,
    "S3_repeat_user_turn": 8,
    "S4_negation_lead": 22,
    "S5_quotes_assistant_text": 5,
}
# Scarcest pool first, so a small signal cannot be starved by the two majors.
SELECTION_ORDER = (
    "S2_tool_burst_no_checkpoint",
    "S5_quotes_assistant_text",
    "S3_repeat_user_turn",
    "S1_interrupt_after_tool_call",
    "S4_negation_lead",
)
MAX_PER_SESSION = 2

Z = p4.Z


def sha(text):
    return p4.sha(text)


def load_jsonl(path):
    return p4.load_jsonl(path)


def policy_text():
    return p4.policy_text()


def policy_sha():
    return p4.policy_sha()


def select_situations():
    """60 situations from probe 4's 183, stratified by signal, two per session.

    Within a signal the order is a seeded shuffle of the probe-4 situation ids;
    a situation is taken when its session still has fewer than two situations
    selected across all signals. Signals are visited scarcest first.
    """
    source = {row["id"]: row for row in load_jsonl(SOURCE_SITUATIONS)}
    by_signal = {}
    for row in source.values():
        by_signal.setdefault(row["signal"], []).append(row)

    rng = random.Random(SEED_SELECT)
    per_session = {}
    chosen = []
    for signal in SELECTION_ORDER:
        pool = sorted(by_signal[signal], key=lambda row: int(row["id"][3:]))
        rng.shuffle(pool)
        taken = 0
        for row in pool:
            if taken >= SIGNAL_ALLOCATION[signal]:
                break
            if per_session.get(row["session"], 0) >= MAX_PER_SESSION:
                continue
            per_session[row["session"]] = per_session.get(row["session"], 0) + 1
            chosen.append(row)
            taken += 1
        if taken != SIGNAL_ALLOCATION[signal]:
            raise SystemExit(
                f"{signal}: selected {taken} of {SIGNAL_ALLOCATION[signal]}; "
                "the two-per-session cap cannot be met"
            )
    return chosen


def situations():
    return sorted(load_jsonl(SITUATIONS), key=lambda row: int(row["id"][5:]))


def build_map(situation_rows):
    """Seeded X/Y order for every paired and control comparison.

    Paired comparison `i` puts `full` or `bare` in the X slot by a coin flip;
    the control comparison puts draw 1 or draw 2 of `full` in the X slot. The
    map is the only place arm labels live, and it is written to map.json.
    """
    paired_rng = random.Random(SEED_PAIRED_MAP)
    control_rng = random.Random(SEED_CONTROL_MAP)
    paired = {}
    control = {}
    for row in situation_rows:
        sides = []
        for _ in range(DRAWS):
            arms = ["bare", "full"]
            if paired_rng.random() < 0.5:
                arms.reverse()
            sides.append({"X": arms[0], "Y": arms[1]})
        paired[row["id"]] = sides
        first = 1 if control_rng.random() < 0.5 else 2
        control[row["id"]] = {"X": first, "Y": 2 if first == 1 else 1}
    return {"paired": paired, "control": control}


def paired_side(mapping, situation_id, draw):
    return mapping["paired"][situation_id][draw - 1]


def control_side(mapping, situation_id):
    return mapping["control"][situation_id]


def judge_prompt(excerpt, side_arms, answers):
    """Probe 4's exact judge prompt; `answers` is keyed by X and Y."""
    return (
        f"Conversation excerpt:\n\n{excerpt}\n\n"
        f"=== Answer X ===\n{answers['X']}\n\n"
        f"=== Answer Y ===\n{answers['Y']}\n\n"
        f"{p4.QUESTION}\n{p4.FORMAT}"
    )


def system_for(arm, policy):
    return "" if arm == "bare" else policy


def generation_prompt(situation):
    return situation["excerpt"] + p4.INSTRUCTION


def parse_judge_answer(text, policy):
    """Probe 4's judge JSON parser, unchanged in substance."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        raise SystemExit(f"judge returned no JSON object: {text[:300]}")
    raw = json.loads(match.group(0))
    winner = str(raw.get("winner", "")).strip()
    if winner.lower() == "tie":
        winner = "tie"
    else:
        winner = winner.upper()
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


def wilson(k, n):
    return p4.wilson(k, n)


def session_bootstrap(outcomes_by_session, win_label, lose_label, seed=SEED_BOOTSTRAP, reps=10000):
    """Session-clustered percentile interval for a win share.

    `outcomes_by_session` maps a session to a list of outcome labels; only
    `win_label` and `lose_label` count, ties and identical pairs do not.
    """
    keys = sorted(outcomes_by_session)
    rng = random.Random(seed)
    values = []
    for _ in range(reps):
        wins = losses = 0
        for _ in keys:
            key = keys[rng.randrange(len(keys))]
            for outcome in outcomes_by_session[key]:
                if outcome == win_label:
                    wins += 1
                elif outcome == lose_label:
                    losses += 1
        if wins + losses:
            values.append(wins / (wins + losses))
    values.sort()
    return values[int(0.025 * len(values))], values[int(0.975 * len(values))]


def call_cost(usage, created):
    return lib.call_cost(usage, created)


def append_rows(path, rows):
    with Path(path).open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
