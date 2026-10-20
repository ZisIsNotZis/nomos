#!/usr/bin/env python3
"""Generate one next turn per situation under `bare`, `full` and `slice`.

Same instruction, temperature 0, thinking disabled for all three arms; only the
system message differs. Every call is appended to answers.jsonl, so a killed run
resumes. A smoke stage of two situations prints observed usage, projects the
remaining spend and refuses to continue above the CNY 8 budget.
"""

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import common
from pathlib import Path

sys.path.insert(0, str(common.NOMOS / "report" / "probe-2"))
import probe_lib as lib  # noqa: E402

BUDGET_CNY = 8.0
MAX_TOKENS = 600
WORKERS = 6
LOCK = threading.Lock()
SEQUENCE = 0


def responses_by_key():
    if not common.ANSWERS.exists():
        return {}
    return {(row["situation"], row["arm"]): row for row in common.load_jsonl(common.ANSWERS)}


def system_for(arm, policy, slice_by_id, situation_id):
    if arm == "bare":
        return ""
    if arm == "full":
        return policy
    return slice_by_id[situation_id]["slice"]


def generate(situation, arm, policy, slice_by_id, smoke):
    global SEQUENCE
    system = system_for(arm, policy, slice_by_id, situation["id"])
    prompt = situation["excerpt"] + common.INSTRUCTION
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}]
    body = {
        "model": lib.MODEL,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": MAX_TOKENS,
        "thinking": {"type": "disabled"},
    }
    response, latency = lib.post(body)
    usage = response.get("usage", {})
    answer = (response["choices"][0]["message"].get("content") or "").strip()
    if not answer:
        raise SystemExit(f"{situation['id']} {arm}: empty answer")
    with LOCK:
        SEQUENCE += 1
        row = lib.record(f"g{SEQUENCE:04d}", "generate", situation["id"], arm, 0, 0.0,
                         prompt, answer, usage, response.get("created", 0), latency)
        row["smoke"] = smoke
        row["finish_reason"] = response["choices"][0].get("finish_reason")
        row["system_chars"] = len(system)
        row["system_sha256"] = common.sha(system) if system else None
        row["request_sha256"] = common.sha(system + "\x00" + prompt)
        lib.append_rows(common.ANSWERS, [row])
    return row


def main():
    lib.api_key()
    situations = common.ordered_situations()
    slices = {row["id"]: row for row in common.load_jsonl(common.SLICES)}
    policy = common.policy_text()
    done = responses_by_key()

    pending = [(situation, arm) for situation in situations for arm in common.GENERATED_ARMS
               if (situation["id"], arm) not in done]
    if not pending:
        print("all generations already present")
        return
    print(f"{len(situations)} situations x 3 arms; {len(pending)} calls pending")

    # --- smoke -------------------------------------------------------------
    smoke_situations = situations[:2]
    smoke_rows = []
    for situation in smoke_situations:
        for arm in common.GENERATED_ARMS:
            if (situation["id"], arm) in done:
                continue
            smoke_rows.append(generate(situation, arm, policy, slices, smoke=True))
    if smoke_rows:
        spent_usd = sum(row["cost"]["usd"] for row in smoke_rows)
        print("smoke usage and cost:")
        for row in smoke_rows:
            cost = row["cost"]
            print(f"  {row['situation']} {row['arm']:<5} system={row['system_chars']:>6} chars "
                  f"prompt={row['usage']['prompt_tokens']:>6} (hit={cost['cache_hit_tokens']:>6} "
                  f"miss={cost['cache_miss_tokens']:>5}) out={cost['output_tokens']:>4} "
                  f"${cost['usd']:.5f} / ¥{cost['cny']:.5f}")
        remaining_gen = len(pending) - len(smoke_rows)
        per_arm = {}
        for row in smoke_rows:
            per_arm.setdefault(row["arm"], []).append(row["cost"]["usd"])
        avg_gen = sum(sum(v) / len(v) for v in per_arm.values()) / len(per_arm)
        judge_calls = 2 * len(situations)
        judge_avg_usd = 0.00051  # probe 3's measured average per full-policy judge call
        projected_usd = spent_usd + remaining_gen * avg_gen + judge_calls * judge_avg_usd
        print(f"smoke total: ${spent_usd:.5f} / ¥{spent_usd * lib.USD_CNY:.5f}")
        print(f"projection: {remaining_gen} remaining generations at ${avg_gen:.5f} average "
              f"+ {judge_calls} judge calls at ${judge_avg_usd:.5f} "
              f"= ${projected_usd:.4f} / ¥{projected_usd * lib.USD_CNY:.3f} "
              f"(budget ¥{BUDGET_CNY:.0f})")
        if projected_usd * lib.USD_CNY > BUDGET_CNY:
            raise SystemExit(f"projected ¥{projected_usd * lib.USD_CNY:.2f} exceeds ¥{BUDGET_CNY:.0f}; stopping")
        print("projection within budget; continuing\n")

    # --- remaining generations --------------------------------------------
    remaining = [(situation, arm) for situation in situations for arm in common.GENERATED_ARMS
                 if (situation["id"], arm) not in responses_by_key()]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(generate, situation, arm, policy, slices, False)
                   for situation, arm in remaining]
        for count, future in enumerate(futures, 1):
            future.result()
            if count % 30 == 0:
                print(f"  {count}/{len(futures)} generations done", flush=True)

    rows = common.load_jsonl(common.ANSWERS)
    total_usd = sum(row["cost"]["usd"] for row in rows)
    print(f"\nanswers.jsonl rows: {len(rows)}")
    print(f"generation spend: ${total_usd:.5f} / ¥{total_usd * lib.USD_CNY:.5f}")


if __name__ == "__main__":
    main()
