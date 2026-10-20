#!/usr/bin/env python3
"""Judge two blind forced choices per situation: full vs bare and slice vs bare.

The judge always receives the full policy as its system message, the situation
excerpt and the two answers in seeded X/Y order. A judgment whose `clause` is
not a verbatim AGENTS.md substring is re-asked once with the constraint
restated; both attempts stay in calls.jsonl and judge-out.jsonl.
"""

import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import common

sys.path.insert(0, str(common.NOMOS / "report" / "probe-2"))
import probe_lib as lib  # noqa: E402

MAX_TOKENS = 500
WORKERS = 6
LOCK = threading.Lock()
SEQUENCE = 0


def parse_answer(text, policy):
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


def call_judge(situation, comparison, answers, side, policy, attempt, prior_clause=None):
    global SEQUENCE
    prompt = common.build_judge_prompt(situation["excerpt"], side, answers, comparison)
    if attempt == 2:
        prompt += common.RETRY_SUFFIX + f"\n上一次的 clause：{prior_clause!r}"
    body = {
        "model": lib.MODEL,
        "messages": [{"role": "system", "content": policy}, {"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": MAX_TOKENS,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
    }
    response, latency = lib.post(body)
    usage = response.get("usage", {})
    answer = (response["choices"][0]["message"].get("content") or "").strip()
    parsed = parse_answer(answer, policy)
    with LOCK:
        SEQUENCE += 1
        row = lib.record(f"j{SEQUENCE:04d}", f"judge_{comparison}", situation["id"], "blind",
                         attempt, 0.0, prompt, answer, usage, response.get("created", 0), latency)
        row["comparison"] = comparison
        row["attempt"] = attempt
        row["clause_ok"] = parsed["clause_ok"]
        row["system_sha256"] = common.policy_sha()
        row["request_sha256"] = common.sha(policy + "\x00" + prompt)
        lib.append_rows(common.CALLS, [row])
    return row, parsed


def judge(situation, comparison, answers, side, policy):
    row1, first = call_judge(situation, comparison, answers, side, policy, 1)
    final = first
    second_row = None
    if not first["clause_ok"]:
        second_row, final = call_judge(situation, comparison, answers, side, policy, 2,
                                       prior_clause=first["clause"])
    with LOCK:
        result = {
            "situation": situation["id"],
            "session": situation["session"],
            "signal": situation["signal"],
            "comparison": comparison,
            "winner": final["winner"],
            "clause": final["clause"],
            "reason": final["reason"],
            "clause_ok_before_retry": first["clause_ok"],
            "retried": second_row is not None,
            "clause_ok_after_retry": final["clause_ok"],
            "first_clause": first["clause"],
            "first_winner": first["winner"],
            "call_ids": [row1["call_id"]] + ([second_row["call_id"]] if second_row else []),
        }
        lib.append_rows(common.JUDGE_OUT, [result])
    return result


def main():
    lib.api_key()
    situations = common.ordered_situations()
    policy = common.policy_text()
    mapping = json.loads(common.MAP.read_text(encoding="utf-8"))
    rows = common.load_jsonl(common.ANSWERS)
    by_situation = {}
    for row in rows:
        by_situation.setdefault(row["situation"], {})[row["arm"]] = row["response"]

    done = set()
    if common.JUDGE_OUT.exists():
        done = {(row["situation"], row["comparison"]) for row in common.load_jsonl(common.JUDGE_OUT)}

    tasks = []
    identical = []
    for situation in situations:
        answers = by_situation[situation["id"]]
        for comparison in common.COMPARISONS:
            if (situation["id"], comparison) in done:
                continue
            policy_arm = common.POLICY_ARM[comparison]
            if answers["bare"] == answers[policy_arm]:
                identical.append({"situation": situation["id"], "comparison": comparison,
                                  "status": "identical"})
                continue
            tasks.append((situation, comparison, answers, mapping[comparison][situation["id"]]))
    for row in identical:
        print(f"  {row['situation']} {row['comparison']}: byte-identical answers, forced choice undefined")
    if identical:
        with LOCK:
            lib.append_rows(common.JUDGE_OUT, identical)

    if not tasks:
        print("all judgments already present")
        return
    print(f"{len(tasks)} forced choices pending")

    # --- smoke -------------------------------------------------------------
    smoke = tasks[:2]
    smoke_rows = []
    for situation, comparison, answers, side in smoke:
        result = judge(situation, comparison, answers, side, policy)
        done.add((situation["id"], comparison))
        smoke_rows.append(result)
        print(f"  smoke {situation['id']} {comparison}: {result['winner']} "
              f"retried={result['retried']}")
    smoke_usd = sum(row["cost"]["usd"] for row in common.load_jsonl(common.CALLS))
    smoke_calls = len([row for row in common.load_jsonl(common.CALLS)
                       if row.get("comparison") in common.COMPARISONS])
    avg_usd = smoke_usd / max(1, smoke_calls)
    projected_usd = smoke_usd + (len(tasks) - len(smoke)) * avg_usd * 1.15
    print(f"smoke total ${smoke_usd:.5f} over {smoke_calls} calls; projection for "
          f"{len(tasks) - len(smoke)} more (+15% retries) = ${projected_usd:.4f} / "
          f"¥{projected_usd * lib.USD_CNY:.3f} (budget ¥8)")
    if projected_usd * lib.USD_CNY > 8.0:
        raise SystemExit("projected spend exceeds ¥8; stopping")

    remaining = [task for task in tasks
                 if (task[0]["id"], task[1]) not in done]

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(judge, situation, comparison, answers, side, policy)
                   for situation, comparison, answers, side in remaining]
        for count, future in enumerate(futures, 1):
            future.result()
            if count % 30 == 0:
                print(f"  {count}/{len(futures)} judgments done", flush=True)

    calls = common.load_jsonl(common.CALLS)
    total_usd = sum(row["cost"]["usd"] for row in calls)
    print(f"\ncalls.jsonl rows: {len(calls)}")
    print(f"total judge spend so far: ${total_usd:.5f} / ¥{total_usd * lib.USD_CNY:.5f}")


if __name__ == "__main__":
    main()
