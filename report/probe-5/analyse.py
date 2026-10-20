#!/usr/bin/env python3
"""Recompute every number in report/probe-5.md and check it against the report.

Rebuilds the 60-situation sample and the blind X/Y map from
report/probe-4/situations.jsonl and the recorded seeds, verifies every stored
answer and judge request against the artefacts, recomputes the paired and
control shares with Wilson and session-clustered bootstrap intervals, the
per-situation spread, the judge-variance agreement, the position-stratified
reanalysis of probes 3 and 4, and the spend. Exit 0 only when every recomputed
value equals the value written in the report; exit 1 and print the differences
otherwise.
"""

import json
import math
import sys
from collections import Counter, defaultdict

import common

EXPECTED = {
    "situations": 60,
    "sessions": 38,
    "max_per_session": 2,
    "signals": {
        "S1_interrupt_after_tool_call": 20,
        "S2_tool_burst_no_checkpoint": 5,
        "S3_repeat_user_turn": 8,
        "S4_negation_lead": 22,
        "S5_quotes_assistant_text": 5,
    },
    "answers": 360,
    "generation_calls": 372,
    "smoke_generation_calls": 12,
    "judge_calls": 224,
    "variance_calls": 40,
    "total_calls": 636,
    "paired": {
        "comparisons": 180,
        "full": 94,
        "bare": 73,
        "tie": 10,
        "identical": 3,
        "decisive": 167,
        "share": 0.5629,
        "wilson": [0.4871, 0.6359],
        "bootstrap": [0.4857, 0.6404],
        "whole_set_share": 0.5222,
        "full_on_x": {"full": 23, "bare": 62, "tie": 4, "identical": 3, "share": 0.2706},
        "full_on_y": {"full": 71, "bare": 11, "tie": 6, "identical": 0, "share": 0.8659},
    },
    "control": {
        "comparisons": 60,
        "X": 4,
        "Y": 42,
        "tie": 1,
        "identical": 13,
        "decisive": 46,
        "x_share": 0.0870,
        "x_wilson": [0.0343, 0.2032],
        "x_bootstrap": [0.0204, 0.1739],
        "y_share": 0.9130,
        "y_wilson": [0.7968, 0.9657],
        "y_bootstrap": [0.8261, 0.9796],
    },
    "spread": {
        "3_of_3": 9,
        "2_of_3": 19,
        "1_of_3": 22,
        "0_of_3": 1,
        "2_of_2": 3,
        "1_of_2": 1,
        "0_of_2": 2,
        "0_of_1": 2,
        "0_of_0": 1,
    },
    "fully_decisive_situations": 51,
    "flipped_situations": 42,
    "fully_decisive_flipped": 41,
    "variance": {
        "pass1_vs_pass2": 20,
        "pass1_vs_probe3": 19,
        "pass2_vs_probe3": 19,
        "pass1_winners": {"X": 4, "Y": 15, "tie": 1},
        "pass2_winners": {"X": 4, "Y": 15, "tie": 1},
        "probe3_winners": {"X": 4, "Y": 14, "tie": 2},
        "probe2_strict": 4,
        "probe2_agreement": 4,
    },
    "position": {
        "probe5": {"x": [23, 62], "y": [71, 11]},
        "probe4_full": {"x": [22, 66], "y": [85, 7]},
        "probe4_slice": {"x": [26, 64], "y": [76, 7]},
        "probe3": {"x": [2, 9], "y": [5, 2]},
        "probe5_additive": {"delta": 0.0682, "ci": [0.0083, 0.1281]},
        "probe4_full_additive": {"delta": 0.0870, "ci": [0.0342, 0.1397]},
        "probe4_slice_additive": {"delta": 0.1023, "ci": [0.0467, 0.1578]},
        "probe3_additive": {"delta": -0.0519, "ci": [-0.2544, 0.1505]},
    },
    "spend": {
        "generate": 0.095522,
        "judge_paired": 0.062863,
        "judge_control": 0.016484,
        "judge_variance": 0.010444,
        "total_usd": 0.185314,
        "total_cny": 1.2404,
        "prompt_tokens": 9204764,
        "cache_hit_tokens": 9013595,
        "completion_tokens": 61568,
    },
    "judge": {"model": "deepseek-flash", "temperature": 0.0, "thinking": "disabled"},
}

FAILURES = []


def check(ok, message):
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        FAILURES.append(message)


def close(actual, expected, message, digits=4):
    check(round(actual, digits) == round(expected, digits), f"{message}: {round(actual, digits)} vs {expected}")


def position_stats(rows, winner_arm):
    """Conditional policy-win counts per answer position."""
    out = {"x": [0, 0], "y": [0, 0]}
    for row, position, arm in rows:
        if arm == "tie":
            continue
        slot = "y" if position == "y" else "x"
        out[slot][0 if arm == winner_arm else 1] += 1
    return out


def additive(position, name):
    x_wins, x_losses = position["x"]
    y_wins, y_losses = position["y"]
    q = y_wins / (y_wins + y_losses)
    r = x_wins / (x_wins + x_losses)
    delta = (q + r - 1) / 2
    se = 0.5 * math.sqrt(q * (1 - q) / (y_wins + y_losses) + r * (1 - r) / (x_wins + x_losses))
    return {"delta": delta, "ci": [delta - 1.96 * se, delta + 1.96 * se]}


def main():
    policy = common.policy_text()
    situations = common.situations()
    stored_map = json.loads(common.MAP.read_text(encoding="utf-8"))
    calls = common.load_jsonl(common.CALLS)
    answers = common.load_jsonl(common.ANSWERS)
    variance = common.load_jsonl(common.VARIANCE)
    judgments = common.load_jsonl(common.JUDGE_OUT)

    print("sample rebuild")
    rebuilt = common.select_situations()
    check(len(rebuilt) == EXPECTED["situations"], f"situations = {len(rebuilt)}")
    check(len(situations) == EXPECTED["situations"], f"situations.jsonl rows = {len(situations)}")
    check(all(a["source_id"] == b["id"]
              and a["excerpt"] == b["excerpt"] and a["session"] == b["session"]
              and a["window_id"] == b["window_id"] and a["signal"] == b["signal"]
              for a, b in zip(situations, rebuilt)),
          "every situation is the selected probe-4 row")
    check(len({row["source_id"] for row in situations}) == 60, "60 distinct probe-4 situations")

    sessions = {row["session"] for row in situations}
    per_session = Counter(row["session"] for row in situations)
    per_signal = Counter(row["signal"] for row in situations)
    check(len(sessions) == EXPECTED["sessions"], f"sessions = {len(sessions)}")
    check(max(per_session.values()) == EXPECTED["max_per_session"],
          f"max situations per session = {max(per_session.values())}")
    check(dict(per_signal) == EXPECTED["signals"], f"signal counts = {dict(per_signal)}")

    print("blind map")
    rebuilt_map = common.build_map(situations)
    check(rebuilt_map == stored_map, "map.json rebuilds from the two recorded seeds")
    check(all(side["X"] != side["Y"] for sides in stored_map["paired"].values() for side in sides),
          "every paired side puts different arms in X and Y")
    check(all(side["X"] in ("bare", "full") and side["Y"] in ("bare", "full")
              for sides in stored_map["paired"].values() for side in sides),
          "paired map holds only arm labels")

    print("generation integrity")
    generations = [row for row in calls if row["phase"] == "generate"]
    check(len(generations) == EXPECTED["generation_calls"], f"generation calls = {len(generations)}")
    check(sum(1 for row in generations if row.get("smoke")) == EXPECTED["smoke_generation_calls"],
          f"smoke generation calls = {sum(1 for row in generations if row.get('smoke'))}")
    check(len(answers) == EXPECTED["answers"], f"answer rows = {len(answers)}")
    keys = [(row["situation"], row["arm"], row["draw"]) for row in answers]
    check(len(set(keys)) == len(keys) == 360, "one stored answer per situation, arm and draw")
    check(len({row["call_id"] for row in calls}) == len(calls), "call ids are unique")
    call_by_id = {row["call_id"]: row for row in calls}
    situation_by_id = {row["id"]: row for row in situations}
    for row in answers:
        call = call_by_id.get(row["call_id"])
        if call is None:
            check(False, f"{row['situation']}: answer call_id missing")
            break
        system = common.system_for(row["arm"], policy)
        prompt = common.generation_prompt(situation_by_id[row["situation"]])
        rebuilt_sha = common.sha(system + "\x00" + prompt)
        if not (call["request_sha256"] == rebuilt_sha and call["response"] == row["response"]
                and call["arm"] == row["arm"] and call["sample"] == row["draw"]
                and call["situation"] == row["situation"]):
            check(False, f"{row['situation']} {row['arm']} draw {row['draw']}: answer/call mismatch")
            break
        if row["arm"] == "full":
            if not (call["system_chars"] == len(policy) and call["system_sha256"] == common.policy_sha()):
                check(False, f"{row['situation']} full: system message is not the policy")
                break
        elif call["system_chars"] != 0:
            check(False, f"{row['situation']} bare: system message is not empty")
            break
    else:
        check(True, "every stored answer matches its generation call and request hash")

    print("judge-request integrity")
    answers_by_key = {(row["situation"], row["arm"], row["draw"]): row["response"] for row in answers}
    judged = [row for row in judgments if row["status"] == "judged"]
    identical = [row for row in judgments if row["status"] == "identical"]
    check(len(judged) == EXPECTED["judge_calls"], f"judged forced choices = {len(judged)}")
    check(len(identical) == 16, f"identical forced choices = {len(identical)}")
    check(len(judged) + len(identical) == 240, "240 judgments = 180 paired + 60 control")
    check(Counter(row["kind"] for row in judgments) == {"paired": 180, "control": 60},
          "kind counts = 180 paired + 60 control")
    for row in judged:
        call = call_by_id.get(row["call_id"])
        if call is None:
            check(False, f"{row['situation']} {row['kind']}: judge call missing")
            break
        sid = row["situation"]
        if row["kind"] == "paired":
            side = common.paired_side(stored_map, sid, row["draw"])
            pair = {"X": answers_by_key[(sid, side["X"], row["draw"])],
                    "Y": answers_by_key[(sid, side["Y"], row["draw"])]}
        else:
            side = common.control_side(stored_map, sid)
            pair = {"X": answers_by_key[(sid, "full", side["X"])],
                    "Y": answers_by_key[(sid, "full", side["Y"])]}
        prompt = common.judge_prompt(situation_by_id[sid]["excerpt"], side, pair)
        rebuilt_sha = common.sha(policy + "\x00" + prompt)
        parsed = common.parse_judge_answer(call["response"], policy)
        if not (call["request_sha256"] == rebuilt_sha and parsed["winner"] == row["winner"]
                and call["situation"] == sid and call["comparison"] == row["kind"]
                and call["sample"] == row["draw"]):
            check(False, f"{sid} {row['kind']} draw {row['draw']}: judge call mismatch")
            break
        if call["system_sha256"] != common.policy_sha():
            check(False, f"{sid} {row['kind']}: judge system is not the policy")
            break
    else:
        check(True, "every judged row rebuilds to its stored request hash")

    print("judge variance")
    check(len(variance) == 40, f"variance rows = {len(variance)}")
    passes = {(row["situation"], row["pass"]): row["winner"] for row in variance}
    p3_situations = {row["id"]: row for row in common.load_jsonl(common.P3_SITUATIONS)}
    p3_pairs = {row["situation"]: row for row in common.load_jsonl(common.P3_PAIRS)}
    p3_map = json.loads(common.P3_MAP.read_text(encoding="utf-8"))
    p3_calls = {row["situation"]: row for row in common.load_jsonl(common.PROBE3 / "calls.jsonl")}
    p3_winners = {row["situation"]: row["winner"]
                  for row in common.load_jsonl(common.P3_JUDGE_OUT)}
    for sid, side in p3_map.items():
        pair = {label: p3_pairs[sid][arm] for label, arm in side.items()}
        prompt = common.judge_prompt(p3_situations[sid]["excerpt"], side, pair)
        if common.sha(policy + "\x00" + prompt) != p3_calls[sid]["request_sha256"]:
            check(False, f"{sid}: variance request is not probe 3's request")
            break
    else:
        check(True, "every variance request is byte-identical to probe 3's stored request")
    ids = sorted(p3_winners)
    p1p2 = sum(1 for sid in ids if passes[(sid, 1)] == passes[(sid, 2)])
    p1p3 = sum(1 for sid in ids if passes[(sid, 1)] == p3_winners[sid])
    p2p3 = sum(1 for sid in ids if passes[(sid, 2)] == p3_winners[sid])
    check(p1p2 == EXPECTED["variance"]["pass1_vs_pass2"], f"pass1 vs pass2 agreement = {p1p2}/20")
    check(p1p3 == EXPECTED["variance"]["pass1_vs_probe3"], f"pass1 vs probe 3 = {p1p3}/20")
    check(p2p3 == EXPECTED["variance"]["pass2_vs_probe3"], f"pass2 vs probe 3 = {p2p3}/20")
    for label, counts_key in (("pass1_winners", 1), ("pass2_winners", 2)):
        counts = Counter(passes[(sid, counts_key)] for sid in ids)
        check(dict(counts) == EXPECTED["variance"][label],
              f"{label} = {dict(counts)}")
    check(Counter(p3_winners.values()) == EXPECTED["variance"]["probe3_winners"],
          f"probe 3 stored winners = {dict(Counter(p3_winners.values()))}")

    print("probe 2 rubric agreement")
    p2_rows = common.load_jsonl(common.P2_JUDGE_OUT)
    p2_map = json.loads(common.P2_MAP.read_text(encoding="utf-8"))
    items = ["D1_authority", "D2_ask", "D3_phase", "D4_fit"]
    preference = {}
    for row in p2_rows:
        totals = {}
        for label in ("X", "Y"):
            values = [row[label][item] for item in items if row[label][item] is not None]
            totals[p2_map[row["situation"]][label]] = sum(values) / len(values)
        preference[row["situation"]] = (
            "tie" if totals["bare"] == totals["law"]
            else ("bare" if totals["bare"] > totals["law"] else "law"))
    strict = {sid: arm for sid, arm in preference.items() if arm != "tie"}
    agreed = 0
    for sid, arm in strict.items():
        forced = passes[(sid, 1)]
        if forced != "tie" and p3_map[sid][forced] == arm:
            agreed += 1
    check(len(strict) == EXPECTED["variance"]["probe2_strict"],
          f"probe 2 strict rubric preferences = {len(strict)}")
    check(agreed == EXPECTED["variance"]["probe2_agreement"],
          f"pass 1 agrees with probe 2 rubric on {agreed}/{len(strict)} strict pairs")

    print("paired comparison")
    paired_outcomes = []
    by_session = defaultdict(list)
    for situation in situations:
        sid = situation["id"]
        for draw in range(1, common.DRAWS + 1):
            row = next(r for r in judgments if r["situation"] == sid and r["kind"] == "paired"
                       and r["draw"] == draw)
            if row["status"] == "identical":
                outcome = "identical"
            elif row["winner"] == "tie":
                outcome = "tie"
            else:
                outcome = common.paired_side(stored_map, sid, draw)[row["winner"]]
            paired_outcomes.append((sid, draw, outcome))
            by_session[situation["session"]].append(outcome)
    counts = Counter(outcome for _, _, outcome in paired_outcomes)
    full, bare = counts["full"], counts["bare"]
    decisive = full + bare
    check(len(paired_outcomes) == EXPECTED["paired"]["comparisons"],
          f"paired comparisons = {len(paired_outcomes)}")
    check(full == EXPECTED["paired"]["full"], f"full wins = {full}")
    check(bare == EXPECTED["paired"]["bare"], f"bare wins = {bare}")
    check(counts["tie"] == EXPECTED["paired"]["tie"], f"ties = {counts['tie']}")
    check(counts["identical"] == EXPECTED["paired"]["identical"],
          f"identical = {counts['identical']}")
    check(decisive == EXPECTED["paired"]["decisive"], f"decisive = {decisive}")
    share = full / decisive
    close(share, EXPECTED["paired"]["share"], "paired share")
    wilson = common.wilson(full, decisive)
    close(wilson[0], EXPECTED["paired"]["wilson"][0], "paired Wilson low")
    close(wilson[1], EXPECTED["paired"]["wilson"][1], "paired Wilson high")
    boot = common.session_bootstrap(by_session, "full", "bare")
    close(boot[0], EXPECTED["paired"]["bootstrap"][0], "paired bootstrap low")
    close(boot[1], EXPECTED["paired"]["bootstrap"][1], "paired bootstrap high")
    close(full / 180, EXPECTED["paired"]["whole_set_share"], "whole-set share over 180")

    print("position split")
    split = {"x": Counter(), "y": Counter()}
    for sid, draw, outcome in paired_outcomes:
        side = common.paired_side(stored_map, sid, draw)
        slot = "y" if side["Y"] == "full" else "x"
        split[slot][outcome] += 1
    for slot, expected_key in (("x", "full_on_x"), ("y", "full_on_y")):
        expected = EXPECTED["paired"][expected_key]
        c = split[slot]
        check(c["full"] == expected["full"] and c["bare"] == expected["bare"]
              and c["tie"] == expected["tie"] and c["identical"] == expected["identical"],
              f"full on {slot.upper()}: {dict(c)}")
        close(c["full"] / (c["full"] + c["bare"]), expected["share"],
              f"full-on-{slot.upper()} share")

    print("same-condition control")
    control_outcomes = []
    control_by_session = defaultdict(list)
    for situation in situations:
        row = next(r for r in judgments if r["situation"] == situation["id"]
                   and r["kind"] == "control")
        outcome = "identical" if row["status"] == "identical" else row["winner"]
        control_outcomes.append(outcome)
        control_by_session[situation["session"]].append(outcome)
    ccounts = Counter(control_outcomes)
    check(len(control_outcomes) == EXPECTED["control"]["comparisons"],
          f"control comparisons = {len(control_outcomes)}")
    for label in ("X", "Y", "tie", "identical"):
        check(ccounts[label] == EXPECTED["control"][label], f"control {label} = {ccounts[label]}")
    cdecisive = ccounts["X"] + ccounts["Y"]
    check(cdecisive == EXPECTED["control"]["decisive"], f"control decisive = {cdecisive}")
    x_share = ccounts["X"] / cdecisive
    y_share = ccounts["Y"] / cdecisive
    close(x_share, EXPECTED["control"]["x_share"], "control X share")
    close(y_share, EXPECTED["control"]["y_share"], "control Y share")
    x_wilson = common.wilson(ccounts["X"], cdecisive)
    y_wilson = common.wilson(ccounts["Y"], cdecisive)
    close(x_wilson[0], EXPECTED["control"]["x_wilson"][0], "control X Wilson low")
    close(x_wilson[1], EXPECTED["control"]["x_wilson"][1], "control X Wilson high")
    close(y_wilson[0], EXPECTED["control"]["y_wilson"][0], "control Y Wilson low")
    close(y_wilson[1], EXPECTED["control"]["y_wilson"][1], "control Y Wilson high")
    x_boot = common.session_bootstrap(control_by_session, "X", "Y")
    y_boot = common.session_bootstrap(control_by_session, "Y", "X")
    close(x_boot[0], EXPECTED["control"]["x_bootstrap"][0], "control X bootstrap low")
    close(x_boot[1], EXPECTED["control"]["x_bootstrap"][1], "control X bootstrap high")
    close(y_boot[0], EXPECTED["control"]["y_bootstrap"][0], "control Y bootstrap low")
    close(y_boot[1], EXPECTED["control"]["y_bootstrap"][1], "control Y bootstrap high")

    print("per-situation spread")
    per_situation = defaultdict(list)
    for sid, draw, outcome in paired_outcomes:
        per_situation[sid].append(outcome)
    spread = Counter()
    for sid, outcomes in per_situation.items():
        decided = [outcome for outcome in outcomes if outcome in ("full", "bare")]
        spread[(sum(1 for outcome in decided if outcome == "full"), len(decided))] += 1
    named = {
        "3_of_3": spread[(3, 3)], "2_of_3": spread[(2, 3)],
        "1_of_3": spread[(1, 3)], "0_of_3": spread[(0, 3)],
        "2_of_2": spread[(2, 2)], "1_of_2": spread[(1, 2)],
        "0_of_2": spread[(0, 2)], "0_of_1": spread[(0, 1)], "0_of_0": spread[(0, 0)],
    }
    check(named == EXPECTED["spread"], f"spread = {named}")
    flipped = sum(1 for outcomes in per_situation.values()
                  if 0 < sum(1 for outcome in outcomes if outcome == "full")
                  < sum(1 for outcome in outcomes if outcome in ("full", "bare")))
    check(flipped == EXPECTED["flipped_situations"], f"situations that flip = {flipped}")
    fully = [outcomes for outcomes in per_situation.values()
             if sum(1 for outcome in outcomes if outcome in ("full", "bare")) == 3]
    check(len(fully) == EXPECTED["fully_decisive_situations"],
          f"fully decisive situations = {len(fully)}")
    fully_flipped = sum(1 for outcomes in fully
                        if 0 < sum(1 for outcome in outcomes if outcome == "full") < 3)
    check(fully_flipped == EXPECTED["fully_decisive_flipped"],
          f"fully decisive situations that flip = {fully_flipped}")

    print("position-stratified reanalysis of probes 3 and 4")
    check({"x": [split["x"]["full"], split["x"]["bare"]],
           "y": [split["y"]["full"], split["y"]["bare"]]} == EXPECTED["position"]["probe5"],
          "probe 5 conditional counts")
    close(additive(EXPECTED["position"]["probe5"], "probe5")["delta"],
          EXPECTED["position"]["probe5_additive"]["delta"], "probe 5 additive delta")
    p4_map = json.loads((common.PROBE4 / "map.json").read_text(encoding="utf-8"))
    p4_rows = common.load_jsonl(common.PROBE4 / "judge-out.jsonl")
    for comparison, policy_arm, key in (
            ("full_vs_bare", "full", "probe4_full"),
            ("slice_vs_bare", "slice", "probe4_slice")):
        rows = []
        for row in p4_rows:
            if row.get("comparison") != comparison or row.get("status") == "identical":
                continue
            side = p4_map[comparison][row["situation"]]
            if row["winner"] == "tie":
                rows.append((row, "y" if side["Y"] == policy_arm else "x", "tie"))
            else:
                rows.append((row, "y" if side["Y"] == policy_arm else "x", side[row["winner"]]))
        position = position_stats(rows, policy_arm)
        check(position == EXPECTED["position"][key], f"{key} conditional counts = {position}")
        model = additive(position, key)
        close(model["delta"], EXPECTED["position"][key + "_additive"]["delta"],
              f"{key} additive delta")
        close(model["ci"][0], EXPECTED["position"][key + "_additive"]["ci"][0],
              f"{key} additive CI low")
        close(model["ci"][1], EXPECTED["position"][key + "_additive"]["ci"][1],
              f"{key} additive CI high")
    p3_rows = common.load_jsonl(common.P3_JUDGE_OUT)
    rows = []
    for row in p3_rows:
        side = p3_map[row["situation"]]
        position = "y" if side["Y"] == "law" else "x"
        rows.append((row, position, "tie" if row["winner"] == "tie" else side[row["winner"]]))
    position = position_stats(rows, "law")
    check(position == EXPECTED["position"]["probe3"], f"probe3 conditional counts = {position}")
    model = additive(position, "probe3")
    close(model["delta"], EXPECTED["position"]["probe3_additive"]["delta"], "probe3 additive delta")
    close(model["ci"][0], EXPECTED["position"]["probe3_additive"]["ci"][0], "probe3 additive CI low")
    close(model["ci"][1], EXPECTED["position"]["probe3_additive"]["ci"][1], "probe3 additive CI high")

    print("spend")
    phases = Counter(row["phase"] for row in calls)
    for phase in ("generate", "judge_paired", "judge_control", "judge_variance"):
        spent = sum(row["cost"]["usd"] for row in calls if row["phase"] == phase)
        close(spent, EXPECTED["spend"][phase], f"{phase} spend USD", digits=6)
    total = sum(row["cost"]["usd"] for row in calls)
    close(total, EXPECTED["spend"]["total_usd"], "total spend USD", digits=6)
    close(total * common.lib.USD_CNY, EXPECTED["spend"]["total_cny"], "total spend CNY", digits=4)
    check(len(calls) == EXPECTED["total_calls"], f"total calls = {len(calls)}")
    check(sum(1 for row in calls if row["phase"] == "generate") + len(judged) + len(variance)
          == len(calls), "every call belongs to generation, a judgment or a variance pass")
    prompt = sum(row["usage"]["prompt_tokens"] for row in calls)
    hit = sum(row["usage"].get("prompt_cache_hit_tokens", 0) or 0 for row in calls)
    completion = sum(row["usage"].get("completion_tokens", 0) or 0 for row in calls)
    check(prompt == EXPECTED["spend"]["prompt_tokens"], f"prompt tokens = {prompt}")
    check(hit == EXPECTED["spend"]["cache_hit_tokens"], f"cached prompt tokens = {hit}")
    check(completion == EXPECTED["spend"]["completion_tokens"], f"completion tokens = {completion}")
    check(all(row["model"] == EXPECTED["judge"]["model"]
              and row["temperature"] == EXPECTED["judge"]["temperature"]
              and row["thinking"] == EXPECTED["judge"]["thinking"] for row in calls),
          "all calls used the recorded model, temperature and thinking setting")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} mismatch(es)")
        for message in FAILURES:
            print(f"  - {message}")
        sys.exit(1)
    print("all recomputed values match report/probe-5.md")


if __name__ == "__main__":
    main()
