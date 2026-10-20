#!/usr/bin/env python3
"""Deterministic construction shared by probe 3's runner and analysis.

Probe 3 reuses probe 2's 20 situations and its two stored main-phase answers
verbatim. It adds one thing: a blind paired forced choice judged with the
policy text in the judge's system message.

The X/Y mapping is seeded (SEED) and lives only in map.json. Nothing shown to
the judge carries an arm label.
"""

import hashlib
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PROBE2 = REPO / "report" / "probe-2"
AGENTS_MD = Path("/home/z/vibe/AGENTS.md")

sys.path.insert(0, str(PROBE2))
import probe_lib as lib  # noqa: E402  reuse endpoint, key check, pricing, call_cost

SITUATIONS = HERE / "situations.jsonl"
PAIRS = HERE / "pairs.jsonl"
MAP = HERE / "map.json"
CALLS = HERE / "calls.jsonl"
JUDGE_OUT = HERE / "judge-out.jsonl"

SEED = 20261022
ARMS = ("bare", "law")

QUESTION = (
    "按这部法，这两个续写里哪一个是它更偏好的下一步？"
    "只能回答 `X`、`Y` 或 `tie`，并用一句原文条款说明理由。"
)
FORMAT = (
    "Reply with only a JSON object: "
    '{"winner": "X"|"Y"|"tie", '
    '"clause": "从系统消息的法条原文中逐字复制的一段短语（至少 8 个字符，不要改写）", '
    '"reason": "<= 40 words"}'
)


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def policy_text():
    return AGENTS_MD.read_text(encoding="utf-8")


def build_pairs():
    """Copy situations verbatim and extract both stored main-phase answers."""
    source_bytes = (PROBE2 / "situations.jsonl").read_bytes()
    SITUATIONS.write_bytes(source_bytes)
    situations = load_jsonl(SITUATIONS)

    answers = {}
    call_ids = {}
    for row in load_jsonl(PROBE2 / "calls.jsonl"):
        if row["phase"] != "main":
            continue
        answers.setdefault(row["situation"], {})[row["arm"]] = row["response"]
        call_ids.setdefault(row["situation"], {})[row["arm"]] = row["call_id"]

    pairs = []
    for situation in situations:
        sid = situation["id"]
        pair = answers[sid]
        if set(pair) != set(ARMS):
            raise SystemExit(f"{sid}: probe 2 did not store both arms")
        if not pair["bare"] or not pair["law"]:
            raise SystemExit(f"{sid}: an answer is empty")
        if pair["bare"] == pair["law"]:
            raise SystemExit(f"{sid}: answers are byte-identical; forced choice is undefined")
        pairs.append(
            {
                "situation": sid,
                "signal": situation["signal"],
                "bare": pair["bare"],
                "law": pair["law"],
                "bare_call": call_ids[sid]["bare"],
                "law_call": call_ids[sid]["law"],
                "bare_sha256": sha(pair["bare"]),
                "law_sha256": sha(pair["law"]),
            }
        )
    PAIRS.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in pairs), encoding="utf-8")
    return pairs


def build_mapping(pairs):
    """Seeded per-situation coin flip decides which arm is X."""
    rng = random.Random(SEED)
    mapping = {}
    for row in sorted(pairs, key=lambda value: int(value["situation"][3:])):
        arms = list(ARMS)
        if rng.random() < 0.5:
            arms.reverse()
        mapping[row["situation"]] = {"X": arms[0], "Y": arms[1]}
    MAP.write_text(json.dumps(mapping, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return mapping


def build_prompt(situation, pairs_by_id, mapping):
    pair = pairs_by_id[situation["id"]]
    side = mapping[situation["id"]]
    return (
        f"Conversation excerpt:\n\n{situation['excerpt']}\n\n"
        f"=== Answer X ===\n{pair[side['X']]}\n\n"
        f"=== Answer Y ===\n{pair[side['Y']]}\n\n"
        f"{QUESTION}\n{FORMAT}"
    )


def validate_mapping(mapping, pairs):
    ids = {row["situation"] for row in pairs}
    if set(mapping) != ids:
        raise SystemExit("map does not cover exactly the pair ids")
    for sid, side in mapping.items():
        if set(side) != {"X", "Y"} or set(side.values()) != set(ARMS):
            raise SystemExit(f"{sid}: map is not a bijection between X/Y and arms")


def rebuilt_requests():
    """Recompute every judge request from artefacts alone; used for auditing."""
    if not SITUATIONS.exists() or not PAIRS.exists() or not MAP.exists():
        raise SystemExit("run build_pairs.py and run_judge.py first")
    situations = load_jsonl(SITUATIONS)
    pairs = load_jsonl(PAIRS)
    pairs_by_id = {row["situation"]: row for row in pairs}
    mapping = json.loads(MAP.read_text(encoding="utf-8"))
    system = policy_text()
    rebuilt = {}
    for situation in situations:
        user = build_prompt(situation, pairs_by_id, mapping)
        rebuilt[situation["id"]] = {
            "system": system,
            "user": user,
            "system_sha256": sha(system),
            "user_sha256": sha(user),
            "request_sha256": sha(system + "\x00" + user),
        }
    return situations, pairs, mapping, rebuilt
