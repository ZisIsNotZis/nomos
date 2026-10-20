#!/usr/bin/env python3
"""Generate three next turns per condition for each of probe 5's 60 situations.

Settings are probe 4's: temperature 0.0, thinking disabled, max_tokens 600, the
same continuation instruction; only the system message differs (`bare` = none,
`full` = the exact AGENTS.md bytes). Each (situation, arm, draw) is one call.

Every usage row goes to calls.jsonl; answers.jsonl keeps the response and the
call id. A smoke stage prints observed usage and projects the spend before the
remaining calls are launched; the run refuses to continue above CNY 8.
"""

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


def done_keys():
    if not common.ANSWERS.exists():
        return set()
    return {(row["situation"], row["arm"], row["draw"]) for row in common.load_jsonl(common.ANSWERS)}


def generate(situation, arm, draw, policy, smoke):
    global SEQUENCE
    system = common.system_for(arm, policy)
    prompt = common.generation_prompt(situation)
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}]
    body = {
        "model": lib.MODEL,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": common.MAX_TOKENS_GENERATE,
        "thinking": {"type": "disabled"},
    }
    response, latency = lib.post(body)
    usage = response.get("usage", {})
    answer = (response["choices"][0]["message"].get("content") or "").strip()
    if not answer:
        raise SystemExit(f"{situation['id']} {arm} draw {draw}: empty answer")
    with LOCK:
        SEQUENCE += 1
        row = lib.record(f"p5c{SEQUENCE:04d}", "generate", situation["id"], arm, draw, 0.0,
                         prompt, answer, usage, response.get("created", 0), latency)
        row["smoke"] = smoke
        row["finish_reason"] = response["choices"][0].get("finish_reason")
        row["system_chars"] = len(system)
        row["system_sha256"] = common.sha(system) if system else None
        row["request_sha256"] = common.sha(system + "\x00" + prompt)
        common.append_rows(common.CALLS, [row])
        common.append_rows(common.ANSWERS, [{
            "call_id": row["call_id"],
            "situation": situation["id"],
            "signal": situation["signal"],
            "session": situation["session"],
            "arm": arm,
            "draw": draw,
            "response": answer,
            "response_sha256": common.sha(answer),
            "finish_reason": row["finish_reason"],
        }])
    return row


def main():
    global SEQUENCE
    key = lib.api_key()
    del key
    SEQUENCE = len(common.load_jsonl(common.CALLS)) if common.CALLS.exists() else 0
    policy = common.policy_text()
    situations = common.situations()
    done = done_keys()
    pending = [(situation, arm, draw) for situation in situations
               for arm in common.GENERATED_ARMS for draw in range(1, common.DRAWS + 1)
               if (situation["id"], arm, draw) not in done]
    if not pending:
        print("all generations already present")
        return
    print(f"{len(situations)} situations x {len(common.GENERATED_ARMS)} arms x "
          f"{common.DRAWS} draws; {len(pending)} calls pending")

    # --- smoke: two situations, every arm and draw -------------------------
    smoke_tasks = [(situation, arm, draw) for situation in situations[:2]
                   for arm in common.GENERATED_ARMS for draw in range(1, common.DRAWS + 1)
                   if (situation["id"], arm, draw) not in done]
    smoke_rows = []
    for situation, arm, draw in smoke_tasks:
        smoke_rows.append(generate(situation, arm, draw, policy, smoke=True))
    if smoke_rows:
        spent = sum(row["cost"]["usd"] for row in smoke_rows)
        per_arm = {}
        for row in smoke_rows:
            per_arm.setdefault(row["arm"], []).append(row["cost"]["usd"])
        avg = sum(sum(values) / len(values) for values in per_arm.values()) / len(per_arm)
        remaining = len(pending) - len(smoke_rows)
        projected = spent + remaining * avg
        for row in smoke_rows:
            print(f"  {row['situation']} {row['arm']:<5} draw{row['sample']} "
                  f"system={row['system_chars']:>6} prompt={row['usage']['prompt_tokens']:>6} "
                  f"(hit={row['cost']['cache_hit_tokens']:>6} miss={row['cost']['cache_miss_tokens']:>5}) "
                  f"out={row['cost']['output_tokens']:>4} ${row['cost']['usd']:.6f}")
        print(f"smoke: ${spent:.6f} / ¥{spent * lib.USD_CNY:.5f}")
        print(f"projection: {remaining} remaining generations + "
              f"{4 * 60} judge calls at about $0.00044 "
              f"= ${projected + 240 * 0.00044:.5f} / "
              f"¥{(projected + 240 * 0.00044) * lib.USD_CNY:.3f} (budget ¥{BUDGET_CNY:.0f})")
        if (projected + 240 * 0.00044) * lib.USD_CNY > BUDGET_CNY:
            raise SystemExit(f"projected spend exceeds ¥{BUDGET_CNY:.0f}; stopping")
        print("projection within budget; continuing\n")

    remaining = [(situation, arm, draw) for situation in situations
                 for arm in common.GENERATED_ARMS for draw in range(1, common.DRAWS + 1)
                 if (situation["id"], arm, draw) not in done_keys()]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(generate, situation, arm, draw, policy, False)
                   for situation, arm, draw in remaining]
        for count, future in enumerate(futures, 1):
            future.result()
            if count % 30 == 0:
                print(f"  {count}/{len(futures)} generations done", flush=True)

    rows = common.load_jsonl(common.ANSWERS)
    spend = sum(row["cost"]["usd"] for row in common.load_jsonl(common.CALLS))
    print(f"\nanswers.jsonl rows: {len(rows)}")
    print(f"calls.jsonl spend so far: ${spend:.6f} / ¥{spend * lib.USD_CNY:.5f}")


if __name__ == "__main__":
    main()
