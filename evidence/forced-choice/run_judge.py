#!/usr/bin/env python3
"""Judge the 20 probe-2 answer pairs by blind forced choice, law in front.

System message: the exact bytes of /home/vibe/AGENTS.md.
User message: the situation excerpt, answer X, answer Y (seeded order), then
the forced-choice question. The judge never sees which arm produced X or Y.

Every API call is appended to report/probe-3/calls.jsonl. A smoke stage of two
situations prints observed usage and cost, projects the remaining spend, and
refuses to continue above CNY 5.
"""

import json
import re
import sys

import shared
from shared import lib

BUDGET_CNY = 5.0
MAX_TOKENS = 500


def parse_answer(text):
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
    return {"winner": winner, "clause": clause, "reason": reason}


def main():
    lib.api_key()
    if not (shared.SITUATIONS.exists() and shared.PAIRS.exists() and shared.MAP.exists()):
        raise SystemExit("run build_pairs.py first")
    situations = shared.load_jsonl(shared.SITUATIONS)
    pairs = shared.load_jsonl(shared.PAIRS)
    pairs_by_id = {row["situation"]: row for row in pairs}
    mapping = json.loads(shared.MAP.read_text(encoding="utf-8"))
    shared.validate_mapping(mapping, pairs)
    system = shared.policy_text()

    done = set()
    if shared.JUDGE_OUT.exists():
        done = {row["situation"] for row in shared.load_jsonl(shared.JUDGE_OUT)}
    sequence = len(shared.load_jsonl(shared.CALLS)) if shared.CALLS.exists() else 0

    def judge(situation, smoke):
        nonlocal sequence
        user = shared.build_prompt(situation, pairs_by_id, mapping)
        body = {
            "model": lib.MODEL,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.0,
            "max_tokens": MAX_TOKENS,
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
        }
        response, latency = lib.post(body)
        usage = response.get("usage", {})
        answer = (response["choices"][0]["message"].get("content") or "").strip()
        sequence += 1
        row = lib.record(
            f"c{sequence:03d}", "judge_forced", situation["id"], "blind", 0, 0.0,
            user, answer, usage, response.get("created", 0), latency,
        )
        row["smoke"] = smoke
        row["finish_reason"] = response["choices"][0].get("finish_reason")
        row["request_chars"] = len(system) + len(user)
        row["system_sha256"] = shared.sha(system)
        row["request_sha256"] = shared.sha(system + "\x00" + user)
        lib.append_rows(shared.CALLS, [row])
        parsed = parse_answer(answer)
        result = {
            "situation": situation["id"],
            "signal": situation["signal"],
            "winner": parsed["winner"],
            "clause": parsed["clause"],
            "reason": parsed["reason"],
            "call_id": row["call_id"],
        }
        lib.append_rows(shared.JUDGE_OUT, [result])
        print(
            f"  {situation['id']} {parsed['winner']:<4} "
            f"prompt={row['usage']['prompt_tokens']:>6} "
            f"out={row['cost']['output_tokens']:>4} ¥{row['cost']['cny']:.5f}"
        )
        return row, result

    pending = [situation for situation in situations if situation["id"] not in done]
    if not pending:
        print("all 20 situations already judged")
        return

    # --- smoke -------------------------------------------------------------
    smoke_rows = []
    for situation in pending[:2]:
        row, _ = judge(situation, smoke=True)
        smoke_rows.append(row)

    if smoke_rows:
        spent_usd = sum(row["cost"]["usd"] for row in smoke_rows)
        avg_usd = spent_usd / len(smoke_rows)
        remaining = len(pending) - len(smoke_rows)
        projected_usd = spent_usd + remaining * avg_usd
        print(
            f"smoke total: ${spent_usd:.5f} / ¥{spent_usd * lib.USD_CNY:.5f} "
            f"over {len(smoke_rows)} calls"
        )
        print(
            f"projection: {remaining} remaining forced-choice calls at the observed average "
            f"= ${projected_usd:.4f} / ¥{projected_usd * lib.USD_CNY:.3f} "
            f"(budget ¥{BUDGET_CNY:.0f})"
        )
        if projected_usd * lib.USD_CNY > BUDGET_CNY:
            raise SystemExit(
                f"projected ¥{projected_usd * lib.USD_CNY:.2f} exceeds ¥{BUDGET_CNY:.0f}; stopping"
            )
        print("projection within budget; continuing\n")

    # --- remaining forced choices -----------------------------------------
    for situation in pending[len(smoke_rows):]:
        judge(situation, smoke=False)

    rows = shared.load_jsonl(shared.CALLS)
    total_usd = sum(row["cost"]["usd"] for row in rows)
    print(f"\ncalls.jsonl rows: {len(rows)}")
    print(f"total spend: ${total_usd:.5f} / ¥{total_usd * lib.USD_CNY:.5f}")
    if total_usd * lib.USD_CNY > BUDGET_CNY:
        sys.exit(f"spend ¥{total_usd * lib.USD_CNY:.2f} exceeded budget ¥{BUDGET_CNY:.0f}")


if __name__ == "__main__":
    main()
