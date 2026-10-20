#!/usr/bin/env python3
"""Judge every stored pair from probes 4 and 5 in both X/Y orders.

Each pair is judged twice with the same judge, system message and settings; only
the two answers' positions differ between the two calls. No new answer is
generated. Usage rows go to calls.jsonl, verdicts to judge-out.jsonl, and a
byte-identical pair gets a status row instead of a call.

A budget stop is mechanical: after the four-call smoke the remaining cost is
projected from the measured average; above ¥2.80 the `p4_slice_vs_bare` block is
dropped whole, and a run that reaches ¥3.00 stops before the next dataset.
"""

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import common

sys.path.insert(0, str(common.PROBE2))
import probe_lib as lib  # noqa: E402

BUDGET_CNY = 3.0
PROJECTION_CNY = 2.80
WORKERS = 4
LOCK = threading.Lock()
SEQUENCE = 0


def spent_cny():
    if not common.CALLS.exists():
        return 0.0
    return sum(row.get("cost", {}).get("cny", 0.0) or 0.0 for row in common.load_jsonl(common.CALLS))


def done_keys():
    if not common.JUDGE_OUT.exists():
        return set()
    return {(row["dataset"], row["situation"], row["draw"], row["order"])
            for row in common.load_jsonl(common.JUDGE_OUT) if row.get("order")}


def write_identical(rows):
    """Byte-identical pairs: forced choice undefined in both orders, no call."""
    if not rows:
        return
    common.append_rows(common.JUDGE_OUT, rows)
    for row in rows:
        print(f"  {row['dataset']} {row['situation']} draw {row['draw']}: "
              "byte-identical answers, forced choice undefined")


def judge(task, policy):
    global SEQUENCE
    pair, order = task
    prompt = common.request_for(pair, order)
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
        row = lib.record(f"p6c{SEQUENCE:04d}", f"judge_{pair['dataset']}",
                         pair["situation"], "blind", pair["draw"], 0.0, prompt, answer,
                         usage, response.get("created", 0), latency)
        row["dataset"] = pair["dataset"]
        row["order"] = order
        row["clause_ok"] = parsed["clause_ok"]
        row["system_sha256"] = common.policy_sha()
        row["request_sha256"] = common.sha(policy + "\x00" + prompt)
        common.append_rows(common.CALLS, [row])
        verdict = {
            "dataset": pair["dataset"],
            "situation": pair["situation"],
            "session": pair["session"],
            "draw": pair["draw"],
            "order": order,
            "winner": parsed["winner"],
            "picked": common.winner_label(pair, order, parsed["winner"]),
            "clause_ok": parsed["clause_ok"],
            "reason": parsed["reason"],
            "call_id": row["call_id"],
        }
        common.append_rows(common.JUDGE_OUT, [verdict])
    return verdict


def run(tasks, policy, label):
    started = spent_cny()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for verdict in pool.map(lambda task: judge(task, policy), tasks):
            pass
    print(f"{label}: {len(tasks)} calls, ¥{spent_cny() - started:.4f}, "
          f"cumulative ¥{spent_cny():.4f}")


def main():
    lib.api_key()
    policy = common.policy_text()
    pairs = common.pairs()
    done = done_keys()

    identical = []
    tasks = []
    for pair in pairs:
        if pair["identical"]:
            for order in common.ORDERS:
                if (pair["dataset"], pair["situation"], pair["draw"], order) not in done:
                    identical.append({
                        "dataset": pair["dataset"], "situation": pair["situation"],
                        "session": pair["session"], "draw": pair["draw"],
                        "order": order, "status": "identical",
                        "winner": None, "picked": None, "clause_ok": None, "call_id": None,
                    })
            continue
        for order in common.ORDERS:
            key = (pair["dataset"], pair["situation"], pair["draw"], order)
            if key not in done:
                tasks.append((pair, order))
    write_identical(identical)

    if not tasks:
        print("all judgments already present")
        print(f"total ¥{spent_cny():.4f}")
        return

    order_index = {name: index for index, name in enumerate(common.DATASETS)}
    tasks.sort(key=lambda task: (order_index[task[0]["dataset"]],
                                 int(task[0]["situation"].split("SIT")[-1]),
                                 task[0]["draw"], common.ORDERS.index(task[1])))
    print(f"{len(pairs)} stored pairs, {len(tasks)} judgments pending")

    # --- smoke: one call per dataset ---------------------------------------
    first_per_dataset = {}
    for task in tasks:
        first_per_dataset.setdefault(task[0]["dataset"], task)
    smoke = [first_per_dataset[name] for name in common.DATASETS if name in first_per_dataset]
    smoke_keys = {(task[0]["dataset"], task[0]["situation"], task[0]["draw"], task[1])
                  for task in smoke}
    tasks = [task for task in tasks
             if (task[0]["dataset"], task[0]["situation"], task[0]["draw"], task[1])
             not in smoke_keys]
    before = spent_cny()
    run(smoke, policy, "smoke")
    smoke_cost = spent_cny() - before
    avg = smoke_cost / len(smoke)
    remaining = len(tasks)
    projected = spent_cny() + avg * remaining * 1.15
    print(f"smoke ¥{smoke_cost:.4f} over {len(smoke)} calls; average ¥{avg:.6f}/call; "
          f"projection for the rest ¥{projected:.4f} (budget ¥{BUDGET_CNY}, "
          f"stop threshold ¥{PROJECTION_CNY})")

    dropped = set()
    while projected > PROJECTION_CNY and "p4_slice_vs_bare" not in dropped:
        dropped.add("p4_slice_vs_bare")
        tasks = [task for task in tasks if task[0]["dataset"] not in dropped]
        remaining = len(tasks)
        projected = spent_cny() + avg * remaining * 1.15
        print(f"budget: dropping p4_slice_vs_bare whole; projection now ¥{projected:.4f}")
    if projected > PROJECTION_CNY:
        print(f"budget: projection ¥{projected:.4f} still above ¥{PROJECTION_CNY}; "
              "running the datasets that fit")
    if dropped:
        print(f"NOT MEASURED (budget): {sorted(dropped)}")

    # --- main loop, dataset by dataset, hard stop at the budget ------------
    for dataset in common.DATASETS:
        if dataset in dropped:
            continue
        batch = [task for task in tasks if task[0]["dataset"] == dataset]
        if not batch:
            continue
        if spent_cny() >= BUDGET_CNY:
            print(f"STOP: spent ¥{spent_cny():.4f} reached ¥{BUDGET_CNY}; "
                  f"{dataset} and everything after it not measured")
            break
        run(batch, policy, dataset)

    print(f"total ¥{spent_cny():.4f}")
    rows = common.load_jsonl(common.CALLS)
    print(f"calls {len(rows)}, prompt tokens "
          f"{sum(row['usage']['prompt_tokens'] for row in rows)}, completion "
          f"{sum(row['usage']['completion_tokens'] for row in rows)}")


if __name__ == "__main__":
    main()
