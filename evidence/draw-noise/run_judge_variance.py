#!/usr/bin/env python3
"""Re-judge probe 2's 20 stored answer pairs twice with the probe-4 judge.

The request is byte-identical to probe 3's original forced choice: same excerpt,
same two stored answers, same X/Y map (report/probe-3/map.json), same policy in
the system message. Two independent passes at temperature 0 therefore measure
the judge's own variance, with the generated answers held fixed.

Every usage row goes to report/probe-5/calls.jsonl; the parsed verdicts go to
report/probe-5/judge-variance.jsonl.
"""

import json
import sys

import common

sys.path.insert(0, str(common.PROBE2))
import probe_lib as lib  # noqa: E402


def request_for(situation, pair, side, policy):
    answers = {label: pair[arm] for label, arm in side.items()}
    prompt = common.judge_prompt(situation["excerpt"], side, answers)
    return policy, prompt


def judge(situation, pair, side, policy, pass_number, sequence):
    system, prompt = request_for(situation, pair, side, policy)
    body = {
        "model": lib.MODEL,
        "messages": [{"role": "system", "content": system},
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
    row = lib.record(f"p5c{sequence:04d}", "judge_variance", situation["id"], "blind",
                     pass_number, 0.0, prompt, answer, usage,
                     response.get("created", 0), latency)
    row["pass"] = pass_number
    row["comparison"] = "variance"
    row["clause_ok"] = parsed["clause_ok"]
    row["system_sha256"] = common.sha(system)
    row["request_sha256"] = common.sha(system + "\x00" + prompt)
    common.append_rows(common.CALLS, [row])
    result = {
        "situation": situation["id"],
        "signal": situation["signal"],
        "pass": pass_number,
        "winner": parsed["winner"],
        "clause": parsed["clause"],
        "reason": parsed["reason"],
        "clause_ok": parsed["clause_ok"],
        "call_id": row["call_id"],
    }
    common.append_rows(common.VARIANCE, [result])
    print(f"  pass {pass_number} {situation['id']} {parsed['winner']:<4} "
          f"¥{row['cost']['cny']:.5f}")
    return row


def main():
    key = lib.api_key()
    del key
    situations = common.load_jsonl(common.P3_SITUATIONS)
    pairs = {row["situation"]: row for row in common.load_jsonl(common.P3_PAIRS)}
    mapping = json.loads(common.P3_MAP.read_text(encoding="utf-8"))
    policy = common.policy_text()

    done = set()
    if common.VARIANCE.exists():
        done = {(row["situation"], row["pass"]) for row in common.load_jsonl(common.VARIANCE)}
    pending = [(situation, pass_number) for pass_number in (1, 2) for situation in situations
               if (situation["id"], pass_number) not in done]
    if not pending:
        print("all variance judgments already present")
        return

    sequence = len(common.load_jsonl(common.CALLS)) if common.CALLS.exists() else 0

    # Smoke one request per pass, then project.
    smoke = [(situations[0], 1), (situations[0], 2)]
    smoke = [item for item in smoke if (item[0]["id"], item[1]) not in done]
    smoke_rows = []
    for situation, pass_number in smoke:
        sequence += 1
        smoke_rows.append(judge(situation, pairs[situation["id"]], mapping[situation["id"]],
                                policy, pass_number, sequence))
    if smoke_rows:
        spent = sum(row["cost"]["usd"] for row in smoke_rows)
        avg = spent / len(smoke_rows)
        remaining = len(pending) - len(smoke_rows)
        projected = spent + remaining * avg
        print(f"smoke ${spent:.6f} / ¥{spent * lib.USD_CNY:.5f}; "
              f"{remaining} remaining; projected ${projected:.5f} / ¥{projected * lib.USD_CNY:.3f}")
        if projected * lib.USD_CNY > 8.0:
            raise SystemExit("projected spend exceeds the CNY 8 budget")

    for situation, pass_number in pending:
        if (situation["id"], pass_number) in {(row["situation"], row["pass"]) for row in smoke_rows}:
            continue
        sequence += 1
        judge(situation, pairs[situation["id"]], mapping[situation["id"]],
              policy, pass_number, sequence)

    rows = common.load_jsonl(common.VARIANCE)
    spend = sum(row["cost"]["usd"] for row in common.load_jsonl(common.CALLS))
    print(f"\n{len(rows)} variance judgments ({len({row['situation'] for row in rows})} situations x 2 passes)")
    print(f"calls.jsonl spend so far: ${spend:.6f} / ¥{spend * lib.USD_CNY:.5f}")


if __name__ == "__main__":
    main()
