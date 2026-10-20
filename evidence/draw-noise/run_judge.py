#!/usr/bin/env python3
"""Judge probe 5's paired and control comparisons.

Per situation: three paired comparisons (full_i vs bare_i, i = 1..3) and one
same-condition control (full_1 vs full_2). The judge receives the full policy as
its system message, the situation excerpt and the two answers in seeded X/Y
order; no request carries an arm label. A byte-identical answer pair is recorded
as `identical` without a call, because a forced choice between it and itself is
undefined.

Every usage row goes to calls.jsonl; verdicts go to judge-out.jsonl.
"""

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import common

sys.path.insert(0, str(common.PROBE2))
import probe_lib as lib  # noqa: E402

BUDGET_CNY = 8.0
WORKERS = 4
LOCK = threading.Lock()
SEQUENCE = 0


def answers_by_key():
    out = {}
    for row in common.load_jsonl(common.ANSWERS):
        out[(row["situation"], row["arm"], row["draw"])] = row["response"]
    return out


def tasks_for(situations, mapping, answers):
    tasks = []
    for situation in situations:
        sid = situation["id"]
        for draw in range(1, common.DRAWS + 1):
            side = common.paired_side(mapping, sid, draw)
            pair = {"X": answers[(sid, side["X"], draw)], "Y": answers[(sid, side["Y"], draw)]}
            if pair["X"] == pair["Y"]:
                tasks.append({"situation": situation, "kind": "paired", "draw": draw,
                              "side": side, "status": "identical"})
            else:
                tasks.append({"situation": situation, "kind": "paired", "draw": draw,
                              "side": side, "answers": pair})
        side = common.control_side(mapping, sid)
        pair = {"X": answers[(sid, "full", side["X"])], "Y": answers[(sid, "full", side["Y"])]}
        if pair["X"] == pair["Y"]:
            tasks.append({"situation": situation, "kind": "control", "draw": 0,
                          "side": side, "status": "identical"})
        else:
            tasks.append({"situation": situation, "kind": "control", "draw": 0,
                          "side": side, "answers": pair})
    return tasks


def done_keys():
    if not common.JUDGE_OUT.exists():
        return set()
    return {(row["situation"], row.get("kind"), row.get("draw"))
            for row in common.load_jsonl(common.JUDGE_OUT)}


def judge(task, policy, smoke):
    global SEQUENCE
    situation = task["situation"]
    prompt = common.judge_prompt(situation["excerpt"], task["side"], task["answers"])
    body = {
        "model": lib.MODEL,
        "messages": [{"role": "system", "content": policy},
                     {"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": common.MAX_TOKENS_JUDGE,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
    }
    response, latency = lib.post(body)
    usage = response.get("usage", {})
    answer = (response["choices"][0]["message"].get("content") or "").strip()
    parsed = common.parse_judge_answer(answer, policy)
    with LOCK:
        SEQUENCE += 1
        row = lib.record(f"p5c{SEQUENCE:04d}", f"judge_{task['kind']}", situation["id"],
                         "blind", task["draw"], 0.0, prompt, answer, usage,
                         response.get("created", 0), latency)
        row["smoke"] = smoke
        row["comparison"] = task["kind"]
        row["clause_ok"] = parsed["clause_ok"]
        row["system_sha256"] = common.policy_sha()
        row["request_sha256"] = common.sha(policy + "\x00" + prompt)
        common.append_rows(common.CALLS, [row])
        common.append_rows(common.JUDGE_OUT, [{
            "situation": situation["id"],
            "session": situation["session"],
            "signal": situation["signal"],
            "kind": task["kind"],
            "draw": task["draw"],
            "status": "judged",
            "winner": parsed["winner"],
            "clause": parsed["clause"],
            "reason": parsed["reason"],
            "clause_ok": parsed["clause_ok"],
            "call_id": row["call_id"],
        }])
    return row


def main():
    key = lib.api_key()
    del key
    policy = common.policy_text()
    situations = common.situations()
    mapping = json.loads(common.MAP.read_text(encoding="utf-8"))
    answers = answers_by_key()
    tasks = tasks_for(situations, mapping, answers)

    for task in tasks:
        if task.get("status") == "identical":
            sid = task["situation"]["id"]
            if (sid, task["kind"], task["draw"]) in done_keys():
                continue
            common.append_rows(common.JUDGE_OUT, [{
                "situation": sid,
                "session": task["situation"]["session"],
                "signal": task["situation"]["signal"],
                "kind": task["kind"],
                "draw": task["draw"],
                "status": "identical",
                "winner": None,
                "clause": None,
                "reason": None,
                "clause_ok": None,
                "call_id": None,
            }])
            print(f"  {sid} {task['kind']} draw {task['draw']}: byte-identical, forced choice undefined")

    done = done_keys()
    pending = [task for task in tasks if task.get("status") != "identical"
               and (task["situation"]["id"], task["kind"], task["draw"]) not in done]
    if not pending:
        print("all judgments already present")
        return
    print(f"{len(pending)} forced choices pending "
          f"({sum(1 for t in pending if t['kind'] == 'paired')} paired, "
          f"{sum(1 for t in pending if t['kind'] == 'control')} control)")

    sequence_base = len(common.load_jsonl(common.CALLS)) if common.CALLS.exists() else 0
    SEQUENCE = sequence_base

    smoke_rows = []
    for task in pending[:3]:
        smoke_rows.append(judge(task, policy, smoke=True))
    if smoke_rows:
        spent = sum(row["cost"]["usd"] for row in smoke_rows)
        avg = spent / len(smoke_rows)
        remaining = len(pending) - len(smoke_rows)
        projected = spent + remaining * avg
        print(f"smoke: ${spent:.6f} / ¥{spent * lib.USD_CNY:.5f}; {remaining} remaining; "
              f"projected ${projected:.5f} / ¥{projected * lib.USD_CNY:.3f}")
        if projected * lib.USD_CNY > BUDGET_CNY:
            raise SystemExit(f"projected spend exceeds ¥{BUDGET_CNY:.0f}; stopping")

    done = done_keys()
    remaining = [task for task in pending
                 if (task["situation"]["id"], task["kind"], task["draw"]) not in done]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(judge, task, policy, False) for task in remaining]
        for count, future in enumerate(futures, 1):
            future.result()
            if count % 30 == 0:
                print(f"  {count}/{len(futures)} judgments done", flush=True)

    rows = common.load_jsonl(common.JUDGE_OUT)
    spend = sum(row["cost"]["usd"] for row in common.load_jsonl(common.CALLS))
    print(f"\njudge-out.jsonl rows: {len(rows)}")
    print(f"calls.jsonl spend so far: ${spend:.6f} / ¥{spend * lib.USD_CNY:.5f}")


if __name__ == "__main__":
    main()
