#!/usr/bin/env python3
"""Recompute every number in report/probe-2.md and check it against the report.

Reads report/probe-2/{situations.jsonl, calls.jsonl, run-meta.json,
judge/map.json, judge/judge-out.jsonl, judge/noise-out.jsonl} only.

Exit 0 = every recomputed value equals the value written in the report and all
contamination checks pass. Exit 1 = a mismatch, with the differing numbers
printed.
"""

import json
import math
import re
import statistics
import sys
from pathlib import Path

import probe_lib as lib
from run_probe import INSTRUCTION
from judge import ITEMS, RUBRIC, SYSTEM

HERE = Path(__file__).resolve().parent
SITUATIONS = HERE / "situations.jsonl"
CALLS = HERE / "calls.jsonl"
META = HERE / "run-meta.json"
MAP = HERE / "judge" / "map.json"
PAIR_OUT = HERE / "judge" / "judge-out.jsonl"
NOISE_OUT = HERE / "judge" / "noise-out.jsonl"

# Values written in report/probe-2.md. Recomputation must match these.
EXPECTED = {
    "model": "deepseek-flash",
    "thinking": "disabled",
    "situations": 20,
    "signal_spread": {
        "S1_interrupt_after_tool_call": 6,
        "S2_tool_burst_no_checkpoint": 3,
        "S3_repeat_user_turn": 3,
        "S4_negation_lead": 5,
        "S5_quotes_assistant_text": 3,
        "S6_assistant_self_flagged_failure": 0,
    },
    "dim_means": {
        "D1_authority": {"bare": 1.0000, "law": 1.0000},
        "D2_ask": {"bare": 1.0000, "law": 1.0000},
        "D3_phase": {"bare": 1.0000, "law": 1.0000},
        "D4_fit": {"bare": 0.9000, "law": 0.9000},
    },
    "dim_delta": {"D1_authority": 0.0000, "D2_ask": 0.0000, "D3_phase": 0.0000, "D4_fit": 0.0000},
    "overall": {"bare": 0.9750, "law": 0.9750, "delta": 0.0000},
    "materially_different": {"count": 9, "rate": 0.4500},
    "noise_sd": {
        "D1_authority": 0.0000,
        "D2_ask": 0.1826,
        "D3_phase": 0.0000,
        "D4_fit": 0.0000,
        "overall": 0.0456,
    },
    "calls": {"main": 40, "noise": 30, "judge_main": 20, "judge_noise": 30, "total": 120},
    "spend": {"usd": 0.0492, "cny": 0.3294},
    "max_output_cap_hits": 4,
    "materially_different_by_arm_side": {"bare": 4, "law": 5},
    "judged_ones": {"count": 156, "total": 160},
    "registered_rule_output": "fails",
}


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def mean(values):
    return sum(values) / len(values) if values else None


def pooled_sd(series):
    variances = [statistics.variance([value for value in row if value is not None])
                 for row in series
                 if len([value for value in row if value is not None]) >= 2]
    if not variances:
        return 0.0
    return math.sqrt(sum(variances) / len(variances))


def main():
    failures = []

    def check(ok, message):
        print(f"  {'ok  ' if ok else 'FAIL'} {message}")
        if not ok:
            failures.append(message)

    def close(actual, expected, message, digits=4):
        check(round(actual, digits) == round(expected, digits), f"{message}: {round(actual, digits)} vs {expected}")

    situations = load_jsonl(SITUATIONS)
    calls = load_jsonl(CALLS)
    meta = json.loads(META.read_text(encoding="utf-8"))
    mapping = json.loads(MAP.read_text(encoding="utf-8"))
    pairs = load_jsonl(PAIR_OUT)
    noise = load_jsonl(NOISE_OUT)

    print("situations")
    check(len(situations) == EXPECTED["situations"], f"count = {len(situations)}")
    check(all(row["ends_with_user"] for row in situations), "every situation ends on a user turn")
    check(all("USER:" in [line for line in row["excerpt"].splitlines() if line.strip()][-1] for row in situations),
          "last non-empty excerpt line contains USER:")
    check(all(row["excerpt_chars"] <= 1800 for row in situations), "every excerpt <= 1800 chars")
    check(len({row["session"] for row in situations}) == len(situations), "no two situations from one session")
    spread = {signal: sum(1 for row in situations if row["signal"] == signal) for signal in EXPECTED["signal_spread"]}
    check(spread == EXPECTED["signal_spread"], f"signal spread = {spread}")
    credential = re.compile(r"sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}|Bearer\s+\S{8,}|api[_-]?key\s*[:=]"
                            r"|password\s*[:=]|AKIA|/home/", re.IGNORECASE)
    check(not any(credential.search(row["excerpt"]) for row in situations), "no credential or /home/ path in excerpts")

    print("\nrun conditions")
    check(meta["model"] == EXPECTED["model"], f"model = {meta['model']}")
    check(meta["thinking"] == EXPECTED["thinking"], f"thinking = {meta['thinking']}")
    policy = lib.AGENTS_MD.read_text(encoding="utf-8")
    import hashlib
    check(hashlib.sha256(policy.encode()).hexdigest() == meta["policy_sha256"],
          "AGENTS.md bytes match the recorded sha256")
    check(meta["policy_chars"] == len(policy), f"policy chars = {len(policy)}")

    print("\ncalls and spend")
    phases = {}
    for row in calls:
        phases[row["phase"]] = phases.get(row["phase"], 0) + 1
    check(phases == {key: value for key, value in EXPECTED["calls"].items() if key != "total"},
          f"phase counts = {phases}")
    check(len(calls) == EXPECTED["calls"]["total"], f"one row per API call, total = {len(calls)}")
    check(all(row["usage"] and row["cost"] for row in calls), "every call records usage and cost")
    check(all(row["arm"] in ("bare", "law") for row in calls if row["phase"] in ("main", "noise")),
          "generation calls carry an arm")
    check(all(row["arm"] == "blind" for row in calls if row["phase"].startswith("judge")),
          "judge calls carry no arm label")
    recomputed = 0.0
    for row in calls:
        recomputed += lib.call_cost(row["usage"], row["created"])["usd"]
    spent_usd = sum(row["cost"]["usd"] for row in calls)
    close(recomputed, spent_usd, "recomputed cost equals recorded cost (USD)", digits=6)
    close(spent_usd, EXPECTED["spend"]["usd"], "spend USD")
    close(spent_usd * lib.USD_CNY, EXPECTED["spend"]["cny"], "spend CNY")
    check(spent_usd * lib.USD_CNY < 10.0, "spend under CNY 10")
    cap_hits = [row for row in calls if row.get("finish_reason") == "length"]
    check(len(cap_hits) == EXPECTED["max_output_cap_hits"], f"answers hitting the 600-token cap = {len(cap_hits)}")
    main_rows = {(row["situation"], row["arm"]): row for row in calls if row["phase"] == "main"}
    excerpt_chars = {row["id"]: row["excerpt_chars"] for row in situations}
    check(all(main_rows[(sid, arm)]["request_chars"] == excerpt_chars[sid] + len(INSTRUCTION)
              for sid in excerpt_chars for arm in ("bare", "law")),
          "user prompt is the excerpt plus the same instruction in both arms")
    check(all(main_rows[(sid, "bare")]["usage"]["prompt_tokens"] < 1500 for sid in excerpt_chars),
          "bare calls are under 1500 prompt tokens (no policy text)")
    check(all(main_rows[(sid, "law")]["usage"]["prompt_tokens"] > 15000 for sid in excerpt_chars),
          "law calls are over 15000 prompt tokens (policy text present)")

    print("\nblindness")
    check(set(mapping) == {row["situation"] for row in pairs}, "one map entry per judged pair")
    check(all(set(value) == {"X", "Y"} and set(value.values()) == {"bare", "law"} for value in mapping.values()),
          "each pair maps X and Y to one arm each")
    generated = {(row["situation"], row["arm"]): row for row in calls if row["phase"] == "main"}
    rebuilt = {}
    for situation in situations:
        pair = mapping[situation["id"]]
        prompt = (
            f"Conversation excerpt:\n\n{situation['excerpt']}\n\n"
            f"=== Answer X ===\n{generated[(situation['id'], pair['X'])]['response']}\n\n"
            f"=== Answer Y ===\n{generated[(situation['id'], pair['Y'])]['response']}\n\n"
            f"{RUBRIC}\n"
            "Also judge materially_different: 1 if a user would take materially different next steps "
            "depending on which answer they received, 0 if the two answers are effectively the same move.\n"
            'Reply with only a JSON object: {"X": {"D1_authority": 0|1|null, "D2_ask": 0|1|null, '
            '"D3_phase": 0|1|null, "D4_fit": 0|1|null}, "Y": {...same...}, '
            '"materially_different": 0|1, "reason": "<= 40 words"}'
        )
        rebuilt[situation["id"]] = (prompt, hashlib.sha256(prompt.encode()).hexdigest()[:16])
    judge_rows = {row["situation"]: row for row in calls if row["phase"] == "judge_main"}
    check(all(judge_rows[sid]["request_sha256"] == rebuilt[sid][1] for sid in rebuilt),
          "stored judge request hash matches the prompt rebuilt from excerpt + answers only")
    check(not any(re.search(r"\b(bare|law|arm)\b", rebuilt[sid][0], re.IGNORECASE) for sid in rebuilt),
          "no arm word appears in any judge prompt")
    generation_by_id = {row["call_id"]: row for row in calls if row["phase"] == "noise"}
    noise_judge_rows = {row["target_call"]: row for row in calls if row["phase"] == "judge_noise"}
    single_ok = True
    for row in noise:
        source = generation_by_id[row["target_call"]]
        prompt = (
            f"Conversation excerpt:\n\n{next(s for s in situations if s['id'] == row['situation'])['excerpt']}\n\n"
            f"=== Assistant turn ===\n{source['response']}\n\n"
            f"{RUBRIC}\n"
            'Reply with only a JSON object: {"D1_authority": 0|1|null, "D2_ask": 0|1|null, '
            '"D3_phase": 0|1|null, "D4_fit": 0|1|null, "reason": "<= 40 words"}'
        )
        digest = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        if noise_judge_rows[row["target_call"]]["request_sha256"] != digest:
            single_ok = False
    check(single_ok, "each noise judgment is the judgment of its stored generation call")

    print("\nmain comparison")
    arm_of = {}
    for situation_id, pair in mapping.items():
        arm_of[situation_id] = {label: arm for label, arm in pair.items()}
    scores = {item: {"bare": [], "law": []} for item in ITEMS}
    overall = {"bare": [], "law": []}
    material = 0
    for row in pairs:
        situation_id = row["situation"]
        for arm in ("bare", "law"):
            label = next(label for label, value in arm_of[situation_id].items() if value == arm)
            values = [row[label][item] for item in ITEMS if row[label][item] is not None]
            for item in ITEMS:
                if row[label][item] is not None:
                    scores[item][arm].append(row[label][item])
            overall[arm].append(mean(values))
        material += row["materially_different"]
    for item in ITEMS:
        close(mean(scores[item]["bare"]), EXPECTED["dim_means"][item]["bare"], f"{item} bare mean")
        close(mean(scores[item]["law"]), EXPECTED["dim_means"][item]["law"], f"{item} law mean")
        close(mean(scores[item]["law"]) - mean(scores[item]["bare"]), EXPECTED["dim_delta"][item], f"{item} delta")
    close(mean(overall["bare"]), EXPECTED["overall"]["bare"], "overall bare")
    close(mean(overall["law"]), EXPECTED["overall"]["law"], "overall law")
    close(mean(overall["law"]) - mean(overall["bare"]), EXPECTED["overall"]["delta"], "overall delta")
    close(material / len(pairs), EXPECTED["materially_different"]["rate"], "materially different rate")
    check(material == EXPECTED["materially_different"]["count"], f"materially different count = {material}")
    by_side = {
        "bare": sum(row["materially_different"] for row in pairs
                    if next(label for label, value in arm_of[row["situation"]].items() if value == "bare") == "X"),
        "law": sum(row["materially_different"] for row in pairs
                   if next(label for label, value in arm_of[row["situation"]].items() if value == "law") == "X"),
    }
    check(by_side == EXPECTED["materially_different_by_arm_side"],
          f"materially-different pairs by which arm was shown as X = {by_side}")

    print("\nnoise")
    cells = {}
    for row in noise:
        values = [row[item] for item in ITEMS if row[item] is not None]
        cells.setdefault((row["situation"], row["arm"]), []).append((values, mean(values)))
    for item in ITEMS:
        series = [[row[item] for row in noise if (row["situation"], row["arm"]) == cell] for cell in cells]
        close(pooled_sd(series), EXPECTED["noise_sd"][item], f"{item} pooled within-cell SD at temperature 1.0")
    close(pooled_sd([[value for _, value in rows] for rows in cells.values()]), EXPECTED["noise_sd"]["overall"],
          "overall pooled within-cell SD at temperature 1.0")
    check(len(cells) == 10, f"noise cells = {len(cells)}")

    ones = sum(value for item in ITEMS for arm in ("bare", "law") for value in scores[item][arm] if value == 1)
    judged = sum(len(scores[item][arm]) for item in ITEMS for arm in ("bare", "law"))
    check(judged == EXPECTED["judged_ones"]["total"], f"judged items = {judged}")
    check(ones == EXPECTED["judged_ones"]["count"], f"judged items equal to 1 = {ones}")
    check(ones / judged > 0.95, f"instrument saturated: {ones}/{judged} judged items are 1")

    delta = mean(overall["law"]) - mean(overall["bare"])
    noise_sd = pooled_sd([[value for _, value in rows] for rows in cells.values()])
    rule_output = "fails" if abs(delta) <= noise_sd else "passes"
    check(rule_output == EXPECTED["registered_rule_output"],
          f"registered rule output from these numbers = {rule_output} (gate is unresolved, not passed)")

    print("\nnegative control")
    flipped = json.loads(json.dumps(pairs))
    target = flipped[0]
    label = next(name for name, value in arm_of[target["situation"]].items() if value == "law")
    target[label]["D1_authority"] = 0 if target[label]["D1_authority"] == 1 else 1
    flipped_overall = {"bare": [], "law": []}
    for row in flipped:
        for arm in ("bare", "law"):
            side = next(name for name, value in arm_of[row["situation"]].items() if value == arm)
            flipped_overall[arm].append(mean([row[side][item] for item in ITEMS if row[side][item] is not None]))
    flipped_delta = mean(flipped_overall["law"]) - mean(flipped_overall["bare"])
    swing = abs(flipped_delta - delta)
    print(f"  flipping one judged item ({target['situation']} law {label} D1_authority) moves the headline "
          f"from {delta:.4f} to {flipped_delta:.4f}, a swing of {swing:.4f}")
    check(swing > abs(delta),
          f"one-item swing {swing:.4f} exceeds the observed delta {abs(delta):.4f}")
    close(swing, 1 / (4 * len(pairs)), "one-item swing equals 1/(4*n)")

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
