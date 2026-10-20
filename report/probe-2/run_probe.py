#!/usr/bin/env python3
"""Run probe 2 generation calls: smoke, main comparison, temperature-1 noise.

Every API call is appended to report/probe-2/calls.jsonl. The smoke stage runs
two situations in both conditions, prints observed usage and cost in CNY and
USD, projects the remaining spend, and refuses to continue if the projection
exceeds the CNY 10 budget.
"""

import hashlib
import json
import sys
from pathlib import Path

import probe_lib as lib

HERE = Path(__file__).resolve().parent
SITUATIONS = HERE / "situations.jsonl"
CALLS = HERE / "calls.jsonl"
META = HERE / "run-meta.json"
BUDGET_CNY = 10.0
NOISE_SITUATIONS = 5
NOISE_SAMPLES = 3

INSTRUCTION = (
    "\n\n---\n"
    "Write the single next assistant turn for the conversation above: at most 120 words. "
    "If a tool call would be used, render it as `tool: name(args)`."
)


def load_situations():
    return [json.loads(line) for line in SITUATIONS.read_text(encoding="utf-8").splitlines() if line.strip()]


def messages_for(condition, prompt, system_text):
    if condition == "bare":
        return [{"role": "user", "content": prompt}]
    return [{"role": "system", "content": system_text}, {"role": "user", "content": prompt}]


def main():
    lib.api_key()
    system_text = lib.AGENTS_MD.read_text(encoding="utf-8")
    situations = load_situations()

    META.write_text(
        json.dumps(
            {
                "endpoint": lib.ENDPOINT,
                "model": lib.MODEL,
                "thinking": "disabled",
                "policy_path": str(lib.AGENTS_MD),
                "policy_chars": len(system_text),
                "policy_sha256": hashlib.sha256(system_text.encode()).hexdigest(),
                "price_usd_per_mtok": lib.PRICE,
                "usd_cny": lib.USD_CNY,
                "price_source": "https://api-docs.deepseek.com/quick_start/pricing read 2026-10-20",
                "fx_source": "open.er-api.com 2026-10-20 00:02 UTC",
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )

    done = set()
    sequence = 0
    if CALLS.exists():
        for line in CALLS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done.add((row["phase"], row["situation"], row["arm"], row["sample"]))
                sequence += 1

    def run(phase, situation, arm, sample, temperature, smoke=False):
        nonlocal sequence
        key = (phase, situation["id"], arm, sample)
        if key in done:
            return None
        prompt = situation["excerpt"] + INSTRUCTION
        body = {
            "model": lib.MODEL,
            "messages": messages_for(arm, prompt, system_text),
            "temperature": temperature,
            "max_tokens": 600,
            "thinking": {"type": "disabled"},
        }
        response, latency = lib.post(body)
        usage = response.get("usage", {})
        answer = (response["choices"][0]["message"].get("content") or "").strip()
        sequence += 1
        row = lib.record(
            f"c{sequence:03d}", phase, situation["id"], arm, sample, temperature,
            prompt, answer, usage, response.get("created", 0), latency,
        )
        row["smoke"] = smoke
        row["finish_reason"] = response["choices"][0].get("finish_reason")
        lib.append_rows(CALLS, [row])
        done.add(key)
        return row

    # --- smoke -------------------------------------------------------------
    smoke_rows = []
    for situation in situations[:2]:
        for arm in ("bare", "law"):
            row = run("main", situation, arm, 0, 0.0, smoke=True)
            if row is not None:
                smoke_rows.append(row)

    if smoke_rows:
        spent_usd = sum(row["cost"]["usd"] for row in smoke_rows)
        print("smoke usage and cost (deepseek-flash, thinking disabled):")
        for row in smoke_rows:
            cost = row["cost"]
            print(
                f"  {row['situation']} {row['arm']:<4} prompt={row['usage']['prompt_tokens']:>6} "
                f"(hit={cost['cache_hit_tokens']:>6} miss={cost['cache_miss_tokens']:>6}) "
                f"completion={cost['output_tokens']:>4} {cost['rate']:<8} "
                f"${cost['usd']:.5f} / ¥{cost['cny']:.5f}"
            )
        print(f"smoke total: ${spent_usd:.5f} / ¥{spent_usd * lib.USD_CNY:.5f}")

        law_rows = [row for row in smoke_rows if row["arm"] == "law"]
        bare_rows = [row for row in smoke_rows if row["arm"] == "bare"]
        law_avg = sum(row["cost"]["usd"] for row in law_rows) / max(1, len(law_rows))
        bare_avg = sum(row["cost"]["usd"] for row in bare_rows) / max(1, len(bare_rows))
        remaining_main = (len(situations) - 2) * 2
        noise_calls = NOISE_SITUATIONS * 2 * NOISE_SAMPLES
        judge_calls = len(situations) + noise_calls
        projected_usd = (
            spent_usd
            + remaining_main * ((law_avg + bare_avg) / 2)
            + noise_calls * ((law_avg + bare_avg) / 2)
            + judge_calls * 0.00015  # a judge call: ~1.5k prompt, ~200 output tokens at peak
        )
        projected_cny = projected_usd * lib.USD_CNY
        print(
            f"projection: {remaining_main} main + {noise_calls} noise + {judge_calls} judge calls "
            f"= ${projected_usd:.4f} / ¥{projected_cny:.3f} (budget ¥{BUDGET_CNY:.0f})"
        )
        if projected_cny > BUDGET_CNY:
            raise SystemExit(
                f"projected ¥{projected_cny:.2f} exceeds ¥{BUDGET_CNY:.0f}; cut situations in build_situations.py, not samples"
            )
        print("projection within budget; continuing\n")

    if "--smoke-only" in sys.argv:
        print("smoke-only: stopping before the main run")
        return

    # --- main comparison, temperature 0 -----------------------------------
    print("main comparison: 20 situations x 2 conditions, temperature 0")
    for index, situation in enumerate(situations, start=1):
        for arm in ("bare", "law"):
            row = run("main", situation, arm, 0, 0.0)
            if row is not None:
                print(f"  {situation['id']} {arm:<4} ok ({row['cost']['output_tokens']} out tokens)")
        if index == 2:
            print(f"  checkpoint: {index}/20 situations")

    # --- noise, temperature 1.0, three samples ----------------------------
    print(f"\nnoise: first {NOISE_SITUATIONS} situations x 2 conditions x {NOISE_SAMPLES} samples, temperature 1.0")
    for situation in situations[:NOISE_SITUATIONS]:
        for arm in ("bare", "law"):
            for sample in (1, 2, 3):
                run("noise", situation, arm, sample, 1.0)

    rows = [json.loads(line) for line in CALLS.read_text(encoding="utf-8").splitlines() if line.strip()]
    total_usd = sum(row["cost"]["usd"] for row in rows)
    phases = {}
    for row in rows:
        phases[row["phase"]] = phases.get(row["phase"], 0) + 1
    print(f"\ncalls.jsonl rows: {len(rows)} {phases}")
    print(f"total spend: ${total_usd:.5f} / ¥{total_usd * lib.USD_CNY:.5f}")
    if total_usd * lib.USD_CNY > BUDGET_CNY:
        sys.exit(f"spend ¥{total_usd * lib.USD_CNY:.2f} exceeded budget ¥{BUDGET_CNY:.0f}")


if __name__ == "__main__":
    main()
