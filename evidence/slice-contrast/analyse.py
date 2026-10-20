#!/usr/bin/env python3
"""Recompute every number in report/probe-4.md and check it against the report.

Rebuilds situations, slices and the blind map from mining/candidates.jsonl and
AGENTS.yaml, then recomputes arm shares, Wilson and session-clustered bootstrap
intervals, the verified-subset share, the verdict, the clause-integrity rates and
the spend. Exit 0 only when every recomputed value equals the value written in
the report; exit 1 and print the differences otherwise.
"""

import json
import random
import sys
from collections import Counter

import common

EXPECTED = {
    "situations": 183,
    "sessions": 51,
    "max_windows_one_session": 8,
    "capped_sessions": 10,
    "eligible": 242,
    "funnel": {
        "credential_looking": 5,
        "not_end_on_user:S6_assistant_self_flagged_failure": 100,
        "not_end_on_user:S1_interrupt_after_tool_call": 41,
        "not_end_on_user:S5_quotes_assistant_text": 34,
        "not_end_on_user:S4_negation_lead": 20,
        "not_end_on_user:S3_repeat_user_turn": 11,
        "not_end_on_user:S2_tool_burst_no_checkpoint": 2,
    },
    "signals": {
        "S1_interrupt_after_tool_call": 61,
        "S4_negation_lead": 68,
        "S2_tool_burst_no_checkpoint": 14,
        "S3_repeat_user_turn": 24,
        "S5_quotes_assistant_text": 16,
    },
    "leaves": 310,
    "distinctive_terms": 980,
    "policy_chars": 93670,
    "policy_sha256": "325f8b3e2d868f91fb43c24dd088ae6e735386c6d5e2aacfc7496d6ff2726ab6",
    "slice_chars": {"min": 2426, "median": 3813, "max": 5573},
    "slice_leaf_counts": {8: 181, 7: 2},
    "anchors_missed_two": 183,
    "answers": 549,
    "judge_calls": 405,
    "judged": 360,
    "identical": 6,
    "retries": 45,
    "clause_ok_first": 315,
    "clause_ok_retry": 27,
    "clause_ok_final": 342,
    "comparisons": {
        "full_vs_bare": {
            "policy": 107, "bare": 73, "tie": 2, "identical": 1, "non_ties": 180,
            "share": 0.5944, "wilson": [0.5215, 0.6635], "bootstrap": [0.5030, 0.6766],
            "whole_set_share": 0.5847,
            "subset": {"policy": 33, "bare": 17, "tie": 0, "identical": 1, "share": 0.6600},
            "verdict": "pass",
        },
        "slice_vs_bare": {
            "policy": 102, "bare": 71, "tie": 5, "identical": 5, "non_ties": 173,
            "share": 0.5896, "wilson": [0.5151, 0.6602], "bootstrap": [0.5060, 0.6716],
            "whole_set_share": 0.5574,
            "subset": {"policy": 32, "bare": 17, "tie": 1, "identical": 1, "share": 0.6531},
            "verdict": "pass",
        },
    },
    "per_signal": {
        "full_vs_bare": {
            "S1_interrupt_after_tool_call": [41, 19],
            "S2_tool_burst_no_checkpoint": [8, 6],
            "S3_repeat_user_turn": [15, 7],
            "S4_negation_lead": [34, 34],
            "S5_quotes_assistant_text": [9, 7],
        },
        "slice_vs_bare": {
            "S1_interrupt_after_tool_call": [39, 17],
            "S2_tool_burst_no_checkpoint": [6, 7],
            "S3_repeat_user_turn": [16, 7],
            "S4_negation_lead": [30, 35],
            "S5_quotes_assistant_text": [11, 5],
        },
    },
    "mean_answer_chars": {"bare": 355.9, "full": 322.0, "slice": 344.4},
    "generation_spend_usd": 0.228300,
    "judge_spend_usd": 0.177519,
    "total_spend_usd": 0.405819,
    "total_spend_cny": 2.716417,
    "verdict": "neither: both comparisons pass",
}

Z = 1.959963984540054
failures = []


def check(ok, message):
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)


def close(actual, expected, message, digits=4):
    check(round(actual, digits) == round(expected, digits), f"{message}: {round(actual, digits)} vs {expected}")


def rebuild_situations():
    records = common.load_jsonl(common.CANDIDATES)
    funnel = Counter()
    eligible = []
    for record in records:
        if not record["signals"]:
            funnel["no_signal"] += 1
            continue
        if common.SENSITIVE.search(record["text"]):
            funnel["credential_looking"] += 1
            continue
        if not common.ends_with_user(record["text"]):
            funnel[f"not_end_on_user:{record['signals'][0]}"] += 1
            continue
        eligible.append(record)
    funnel["eligible"] = len(eligible)
    funnel["total"] = len(records)
    by_session = {}
    for record in eligible:
        by_session.setdefault(record["session"], []).append(record)
    chosen = []
    capped = 0
    for session in sorted(by_session):
        windows = sorted(by_session[session], key=lambda row: row["window_id"])
        rng = random.Random(f"{common.SEED_SITUATIONS}:{session}")
        rng.shuffle(windows)
        kept, per_signal = [], Counter()
        while windows and len(kept) < common.MAX_PER_SESSION:
            windows.sort(key=lambda row: (per_signal[row["signals"][0]],))
            record = windows.pop(0)
            per_signal[record["signals"][0]] += 1
            kept.append(record)
        if len(by_session[session]) > common.MAX_PER_SESSION:
            capped += 1
        chosen.extend(kept)
    rng = random.Random(common.SEED_SITUATIONS)
    rng.shuffle(chosen)
    return chosen, funnel, capped, len(by_session)


def bootstrap(groups, keys, per_session, seed):
    rng = random.Random(seed)
    values = []
    for _ in range(10000):
        wins = losses = 0
        for _ in keys:
            key = rng.choice(keys)
            for outcome in per_session.get(key, []):
                if outcome == "policy":
                    wins += 1
                elif outcome == "bare":
                    losses += 1
        if wins + losses:
            values.append(wins / (wins + losses))
    values.sort()
    return values[int(0.025 * len(values))], values[int(0.975 * len(values))]


def main():
    situations = common.ordered_situations()
    slices = common.load_jsonl(common.SLICES)
    mapping = json.loads(common.MAP.read_text(encoding="utf-8"))
    answers = common.load_jsonl(common.ANSWERS)
    calls = common.load_jsonl(common.CALLS)
    judgments = common.load_jsonl(common.JUDGE_OUT)

    print("situations rebuild deterministically from mining/candidates.jsonl")
    chosen, funnel, capped, sessions = rebuild_situations()
    check(len(chosen) == EXPECTED["situations"], f"situations = {len(chosen)}")
    check(len(situations) == EXPECTED["situations"], f"situations.jsonl rows = {len(situations)}")
    check(sessions == EXPECTED["sessions"], f"eligible sessions = {sessions}")
    check(capped == EXPECTED["capped_sessions"], f"sessions capped at eight = {capped}")
    check(funnel["eligible"] == EXPECTED["eligible"], f"eligible windows = {funnel['eligible']}")
    for key, value in EXPECTED["funnel"].items():
        check(funnel[key] == value, f"funnel {key} = {funnel[key]}")
    accounted = (funnel["eligible"] + funnel["total"] - funnel["eligible"]
                 if False else funnel["total"])
    check(accounted == 455, f"funnel starts from all {accounted} candidates")
    rebuilt = []
    for index, record in enumerate(chosen, start=1):
        rebuilt.append({
            "id": f"SIT{index:03d}",
            "signal": record["signals"][0],
            "session": record["session"],
            "window_id": record["window_id"],
            "excerpt": common.truncate(record["text"]),
        })
    check(all(row["excerpt"] == stored["excerpt"] for row, stored in zip(rebuilt, situations)),
          "every excerpt is the truncated source window")
    check(all(row["session"] == stored["session"] and row["window_id"] == stored["window_id"]
              for row, stored in zip(rebuilt, situations)),
          "every situation keeps its source window and session")
    check(all(row["ends_with_user"] and common.ends_with_user(row["excerpt"]) for row in situations),
          "every excerpt ends on a USER turn")
    check(len({row["session"] for row in situations}) == EXPECTED["sessions"],
          "sessions used = 51")
    counts = Counter(row["session"] for row in situations)
    check(max(counts.values()) == EXPECTED["max_windows_one_session"],
          f"max windows from one session = {max(counts.values())}")
    signal_counts = Counter(row["signal"] for row in situations)
    for signal, value in EXPECTED["signals"].items():
        check(signal_counts[signal] == value, f"{signal} = {signal_counts[signal]}")
    check(min(signal_counts.values()) >= 2, "every present signal has at least two situations")
    check("S6_assistant_self_flagged_failure" not in signal_counts, "S6 contributes no situation")
    check(all(common.SENSITIVE.search(row["excerpt"]) is None for row in situations),
          "no excerpt matches the credential pattern")

    print("\nslice arm rebuilds from the stated rule")
    leaf_list = common.leaves()
    vocabulary = common.distinctive_vocabulary(leaf_list)
    policy = common.policy_text()
    check(len(leaf_list) == EXPECTED["leaves"], f"policy leaves = {len(leaf_list)}")
    check(len(vocabulary) == EXPECTED["distinctive_terms"], f"distinctive terms = {len(vocabulary)}")
    check(len(policy) == EXPECTED["policy_chars"], f"policy chars = {len(policy)}")
    check(common.policy_sha() == EXPECTED["policy_sha256"], "policy sha256 matches")
    check(all(leaf["text"] in policy for leaf in leaf_list), "every leaf is a verbatim policy substring")
    slice_ok, anchors_missed_two = True, 0
    lengths = []
    leaf_counts = Counter()
    for row in situations:
        indices, missed = common.select_leaves(row["excerpt"], leaf_list, vocabulary)
        stored = next(item for item in slices if item["id"] == row["id"])
        if indices != stored["leaf_indices"]:
            slice_ok = False
        if common.slice_text(indices, leaf_list) != stored["slice"]:
            slice_ok = False
        if common.sha(stored["slice"]) != stored["slice_sha256"]:
            slice_ok = False
        if missed == 2:
            anchors_missed_two += 1
        lengths.append(len(stored["slice"]))
        leaf_counts[stored["leaf_count"]] += 1
    check(slice_ok, "every slice equals the stated rule's output and its recorded hash")
    lengths.sort()
    close(min(lengths), EXPECTED["slice_chars"]["min"], "shortest slice", digits=0)
    close(lengths[len(lengths) // 2], EXPECTED["slice_chars"]["median"], "median slice", digits=0)
    close(max(lengths), EXPECTED["slice_chars"]["max"], "longest slice", digits=0)
    check(dict(leaf_counts) == EXPECTED["slice_leaf_counts"], "slice leaf counts")
    check(anchors_missed_two == EXPECTED["anchors_missed_two"],
          "matching alone never found the two anchor leaves")

    print("\ngenerations and blindness")
    check(len(answers) == EXPECTED["answers"], f"one answer per situation per arm = {len(answers)}")
    check(all(row["phase"] == "generate" for row in answers), "all rows are generation calls")
    check(all(row["temperature"] == 0.0 and row["thinking"] == "disabled" for row in answers),
          "temperature 0 and thinking disabled everywhere")
    check(all(row["model"] == "deepseek-flash" for row in answers), "model id constant")
    per_pair = Counter((row["situation"], row["arm"]) for row in answers)
    check(len(per_pair) == EXPECTED["answers"] and set(per_pair.values()) == {1},
          "each situation generated once per arm")
    slice_by_id = {row["id"]: row for row in slices}
    system_ok = True
    excerpt_by_id = {row["id"]: row["excerpt"] for row in situations}
    for row in answers:
        if row["arm"] == "bare":
            expected_system = ""
        elif row["arm"] == "full":
            expected_system = policy
        else:
            expected_system = slice_by_id[row["situation"]]["slice"]
        if row["system_chars"] != len(expected_system):
            system_ok = False
        if (common.sha(expected_system) if expected_system else None) != row["system_sha256"]:
            system_ok = False
        prompt = excerpt_by_id[row["situation"]] + common.INSTRUCTION
        if row["request_chars"] != len(prompt):
            system_ok = False
        if row["request_sha256"] != common.sha(expected_system + "\x00" + prompt):
            system_ok = False
    check(system_ok, "bare has no system, full is the exact policy bytes, slice is the recorded slice bytes")

    by_id = {}
    for row in answers:
        by_id.setdefault(row["situation"], {})[row["arm"]] = row["response"]
    mean_chars = {arm: round(sum(len(row[arm]) for row in by_id.values()) / len(by_id), 1)
                  for arm in common.GENERATED_ARMS}
    check(mean_chars == EXPECTED["mean_answer_chars"], f"mean answer chars per arm: {mean_chars}")

    check(set(mapping) == set(common.COMPARISONS), "map covers both comparisons")
    map_ok = True
    for comparison in common.COMPARISONS:
        if mapping[comparison] != common.mapping_for(comparison, situations):
            map_ok = False
        for side in mapping[comparison].values():
            if set(side.values()) != {"bare", common.POLICY_ARM[comparison]}:
                map_ok = False
    check(map_ok, "each comparison's X/Y map equals its seeded rebuild and is a bijection")

    print("\njudgments")
    judged = [row for row in judgments if row.get("status") != "identical"]
    check(len(judgments) == EXPECTED["judged"] + EXPECTED["identical"],
          f"judgment rows = {len(judgments)}")
    check(len(judged) == EXPECTED["judged"], f"judged situations = {len(judged)}")
    check(sum(1 for row in judgments if row.get("status") == "identical") == EXPECTED["identical"],
          "identical-answer pairs recorded separately")
    check(all(row["winner"] in ("X", "Y", "tie") for row in judged), "winner is X, Y or tie")
    check(all(row["clause"].strip() and row["reason"].strip() for row in judged),
          "every judgment carries a clause and a reason")
    check(len(calls) == EXPECTED["judge_calls"], f"judge calls = {len(calls)}")
    check(all(row["arm"] == "blind" for row in calls), "no judge call carries an arm label")
    first_clause_by_pair = {(row["situation"], row["comparison"]): row["first_clause"]
                            for row in judgments if row.get("status") != "identical"}
    hash_ok = True
    for row in calls:
        if row["system_sha256"] != EXPECTED["policy_sha256"]:
            hash_ok = False
        situation = next(item for item in situations if item["id"] == row["situation"])
        side = mapping[row["comparison"]][row["situation"]]
        prompt = common.build_judge_prompt(situation["excerpt"], side,
                                           by_id[row["situation"]], row["comparison"])
        if row["attempt"] == 2:
            prompt += common.RETRY_SUFFIX + f"\n上一次的 clause：{first_clause_by_pair[(row['situation'], row['comparison'])]!r}"
        if row["request_sha256"] != common.sha(policy + "\x00" + prompt):
            hash_ok = False
    check(hash_ok, "every judge request hash rebuilds from the map, the answers and the question")
    fixed_text = (common.QUESTION + common.FORMAT + common.RETRY_SUFFIX).lower()
    check(not any(word in fixed_text for word in ("bare", "slice", "full", "policy arm")),
          "the fixed question, format and retry text name no arm")
    order_ok = True
    for comparison in common.COMPARISONS:
        policy_arm = common.POLICY_ARM[comparison]
        for situation in situations:
            side = mapping[comparison][situation["id"]]
            pair = by_id[situation["id"]]
            prompt = common.build_judge_prompt(situation["excerpt"], side, pair, comparison)
            x_block = prompt.split("=== Answer X ===")[1].split("=== Answer Y ===")[0].strip()
            if x_block != pair[side["X"]]:
                order_ok = False
            if pair[side["X"]] == pair[policy_arm] and pair[side["Y"]] != pair["bare"]:
                order_ok = False
    check(order_ok, "Answer X and Answer Y are the map's arms, so the judge cannot tell them apart by position")

    print("\nclause integrity")
    first = [row for row in calls if row["attempt"] == 1]
    retries = [row for row in calls if row["attempt"] == 2]
    check(len(first) == EXPECTED["judged"], f"first attempts = {len(first)}")
    check(len(retries) == EXPECTED["retries"], f"retries = {len(retries)}")
    first_ok = sum(1 for row in first if row["clause_ok"])
    check(first_ok == EXPECTED["clause_ok_first"], f"verbatim clauses before retry = {first_ok}")
    retry_ok = sum(1 for row in retries if row["clause_ok"])
    check(retry_ok == EXPECTED["clause_ok_retry"], f"verbatim clauses on retry = {retry_ok}")
    final_ok = sum(1 for row in judged if row["clause_ok_after_retry"])
    check(final_ok == EXPECTED["clause_ok_final"], f"verbatim clauses after retry = {final_ok}")
    check(all(row["clause_ok_before_retry"] == (row["first_clause"] in policy) for row in judged),
          "recorded pre-retry clause verdicts recompute")
    check(all((row["clause"] in policy) == row["clause_ok_after_retry"] for row in judged),
          "recorded post-retry clause verdicts recompute")
    confab_first = 1 - first_ok / len(first)
    confab_final = 1 - final_ok / len(judged)
    print(f"  clause confabulation before retry = {confab_first:.4f}, after = {confab_final:.4f}")

    print("\nforced choice, mapped back to arms")
    by_judgment = {(row["situation"], row["comparison"]): row for row in judgments}
    stats = {}
    for comparison in common.COMPARISONS:
        policy_arm = common.POLICY_ARM[comparison]
        count = Counter()
        per_session = {}
        for situation in situations:
            row = by_judgment[(situation["id"], comparison)]
            if row.get("status") == "identical":
                count["identical"] += 1
                continue
            if row["winner"] == "tie":
                count["tie"] += 1
                per_session.setdefault(situation["session"], []).append("tie")
                continue
            won = mapping[comparison][situation["id"]][row["winner"]]
            outcome = "policy" if won == policy_arm else "bare"
            count[outcome] += 1
            per_session.setdefault(situation["session"], []).append(outcome)
        non_ties = count["policy"] + count["bare"]
        share = count["policy"] / non_ties
        low, high = common.wilson(count["policy"], non_ties)
        keys = [situation["session"] for situation in situations
                if situation["session"] not in locals().get("_seen", set())]
        keys = list(dict.fromkeys(situation["session"] for situation in situations))
        b_low, b_high = bootstrap(None, keys, per_session, common.SEED_BOOTSTRAP)
        first_per_session = {}
        for situation in situations:
            first_per_session.setdefault(situation["session"], situation["id"])
        subset_ids = set(first_per_session.values())
        sub = Counter()
        for situation in situations:
            if situation["id"] not in subset_ids:
                continue
            row = by_judgment[(situation["id"], comparison)]
            if row.get("status") == "identical":
                sub["identical"] += 1
                continue
            if row["winner"] == "tie":
                sub["tie"] += 1
                continue
            won = mapping[comparison][situation["id"]][row["winner"]]
            sub["policy" if won == policy_arm else "bare"] += 1
        sub_share = sub["policy"] / (sub["policy"] + sub["bare"])
        if low > 0.5 and b_low > 0.5 and sub_share > 0.5:
            verdict = "pass"
        elif high < 0.5 and b_high < 0.5 and sub_share < 0.5:
            verdict = "fail"
        else:
            verdict = "unresolved"
        whole = count["policy"] / len(situations)
        stats[comparison] = {
            "policy": count["policy"], "bare": count["bare"], "tie": count["tie"],
            "identical": count["identical"], "non_ties": non_ties, "share": share,
            "wilson": [low, high], "bootstrap": [b_low, b_high],
            "whole_set_share": whole, "verdict": verdict,
            "subset": {"policy": sub["policy"], "bare": sub["bare"], "tie": sub["tie"],
                       "identical": sub["identical"], "share": sub_share},
        }
        print(f"  {comparison}: {count['policy']} policy / {count['bare']} bare / {count['tie']} tie "
              f"/ {count['identical']} identical; share {share:.4f} "
              f"Wilson [{low:.4f}, {high:.4f}] bootstrap [{b_low:.4f}, {b_high:.4f}] "
              f"subset {sub_share:.4f} -> {verdict}")

    for comparison, want in EXPECTED["comparisons"].items():
        got = stats[comparison]
        for field in ("policy", "bare", "tie", "identical", "non_ties"):
            check(got[field] == want[field], f"{comparison} {field} = {got[field]}")
        close(got["share"], want["share"], f"{comparison} share")
        close(got["wilson"][0], want["wilson"][0], f"{comparison} Wilson lower")
        close(got["wilson"][1], want["wilson"][1], f"{comparison} Wilson upper")
        close(got["bootstrap"][0], want["bootstrap"][0], f"{comparison} bootstrap lower")
        close(got["bootstrap"][1], want["bootstrap"][1], f"{comparison} bootstrap upper")
        close(got["whole_set_share"], want["whole_set_share"], f"{comparison} whole-set share")
        close(got["subset"]["share"], want["subset"]["share"], f"{comparison} subset share")
        for field in ("policy", "bare", "tie", "identical"):
            check(got["subset"][field] == want["subset"][field], f"{comparison} subset {field}")
        check(got["verdict"] == want["verdict"], f"{comparison} verdict = {got['verdict']}")

    print("\nper-signal shares")
    for comparison, wanted in EXPECTED["per_signal"].items():
        policy_arm = common.POLICY_ARM[comparison]
        for signal, expected in wanted.items():
            count = Counter()
            for situation in situations:
                if situation["signal"] != signal:
                    continue
                row = by_judgment[(situation["id"], comparison)]
                if row.get("status") == "identical" or row["winner"] == "tie":
                    continue
                won = mapping[comparison][situation["id"]][row["winner"]]
                count["policy" if won == policy_arm else "bare"] += 1
            got = [count["policy"], count["bare"]]
            check(got == expected, f"{comparison} {signal} = {got}")

    print("\nverdict")
    full = stats["full_vs_bare"]
    slice_ = stats["slice_vs_bare"]
    h2 = (slice_["verdict"] == "pass" and full["verdict"] != "pass"
          and slice_["wilson"][0] > full["wilson"][1])
    h1 = full["verdict"] == "fail" and slice_["verdict"] == "fail"
    both_pass = full["verdict"] == "pass" and slice_["verdict"] == "pass"
    if h2:
        verdict = "H2 supported"
    elif h1:
        verdict = "H1"
    elif both_pass:
        verdict = "neither: both comparisons pass"
    elif full["verdict"] != "pass" and slice_["verdict"] != "pass":
        verdict = "both unresolved in the same direction"
    else:
        verdict = "neither: mixed"
    check(verdict == EXPECTED["verdict"], f"rule output = {verdict}")
    print(f"  {verdict}")

    print("\nspend")
    gen_usd = sum(row["cost"]["usd"] for row in answers)
    judge_usd = sum(row["cost"]["usd"] for row in calls)
    close(gen_usd, EXPECTED["generation_spend_usd"], "generation spend USD", digits=6)
    close(judge_usd, EXPECTED["judge_spend_usd"], "judge spend USD", digits=6)
    close(gen_usd + judge_usd, EXPECTED["total_spend_usd"], "total spend USD", digits=6)
    close((gen_usd + judge_usd) * 6.693661, EXPECTED["total_spend_cny"], "total spend CNY", digits=6)
    check((gen_usd + judge_usd) * 6.693661 < 8.0, "total spend under the CNY 8 budget")

    print()
    if failures:
        print(f"FAIL: {len(failures)} mismatch(es)")
        return 1
    print("OK: every number in report/probe-4.md recomputes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
