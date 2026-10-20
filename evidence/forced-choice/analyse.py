#!/usr/bin/env python3
"""Recompute every number in report/probe-3.md and check it against the report.

Reads probe-3's artefacts plus probe 2's situations, main-phase answers and
materially_different judgments. Exit 0 only when every recomputed value equals
the value written in the report and all blindness / verbatim checks pass.
Exit 1 on a mismatch, with the differing numbers printed.
"""

import hashlib
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import shared  # noqa: E402

PROBE2 = shared.PROBE2
SEED = shared.SEED
Z = 1.959963984540054
STRIP = "\"'“”‘’「」`"

EXPECTED = {
    "model": "deepseek-flash",
    "thinking": "disabled",
    "situations": 20,
    "pairs": 20,
    "judge_calls": 20,
    "law_wins": 7,
    "bare_wins": 11,
    "ties": 2,
    "non_ties": 18,
    "law_share": 0.3889,
    "interval": [0.2031, 0.6138],
    "groups": {
        "materially_different": {
            "n": 9, "law": 3, "bare": 6, "ties": 0,
            "non_ties": 9, "law_share": 0.3333, "interval": [0.1206, 0.6458],
        },
        "same": {
            "n": 11, "law": 4, "bare": 5, "ties": 2,
            "non_ties": 9, "law_share": 0.4444, "interval": [0.1888, 0.7333],
        },
    },
    "non_verbatim": [
        {"situation": "SIT03", "clause": "A step that did not run is not a step that passed."},
        {"situation": "SIT07", "clause": "A normalizer is a must-have, not a nicety"},
    ],
    "spend_usd": 0.010132,
    "spend_cny": 0.067818,
    "smoke_projection_cny": 0.069,
    "probe2_saturation": {"ones": 156, "total": 160},
    "probe2_full_dim_means": ["D1_authority", "D2_ask", "D3_phase"],
    "tokens": {"prompt": 407145, "cache_hit": 386560, "cache_miss": 20585, "completion": 1364},
    "rule_output": "unresolved",
}


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def wilson(k, n):
    p = k / n
    denom = 1 + Z * Z / n
    center = (p + Z * Z / (2 * n)) / denom
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / denom
    return center - half, center + half


def decide(law, bare, n_non):
    lo, hi = wilson(law, law + bare)
    if law + bare < 5:
        return "unresolved", lo, hi
    if lo > 0.5:
        return "pass", lo, hi
    if hi < 0.5:
        return "fail", lo, hi
    return "unresolved", lo, hi


def main():
    failures = []

    def check(ok, message):
        print(f"  {'ok  ' if ok else 'FAIL'} {message}")
        if not ok:
            failures.append(message)

    def close(actual, expected, message, digits=4):
        check(round(actual, digits) == round(expected, digits), f"{message}: {round(actual, digits)} vs {expected}")

    from shared import lib

    print("source material is reused verbatim")
    src_bytes = (PROBE2 / "situations.jsonl").read_bytes()
    check((shared.SITUATIONS).read_bytes() == src_bytes, "probe-3 situations are a byte copy of probe 2")
    situations = load_jsonl(shared.SITUATIONS)
    pairs = load_jsonl(shared.PAIRS)
    check(len(situations) == EXPECTED["situations"], f"situations = {len(situations)}")
    check(len(pairs) == EXPECTED["pairs"], f"pairs = {len(pairs)}")

    p2_calls = load_jsonl(PROBE2 / "calls.jsonl")
    source_answers = {}
    for row in p2_calls:
        if row["phase"] == "main":
            source_answers.setdefault(row["situation"], {})[row["arm"]] = row["response"]
    pairs_ok = True
    for row in pairs:
        for arm in ("bare", "law"):
            if row[arm] != source_answers[row["situation"]][arm]:
                pairs_ok = False
            if row[f"{arm}_sha256"] != sha(source_answers[row["situation"]][arm]):
                pairs_ok = False
    check(pairs_ok, "each stored answer and its sha256 equal probe 2's stored main-phase answer")
    check(all(row["bare"] != row["law"] for row in pairs), "no pair has byte-identical answers")

    mapping = json.loads(shared.MAP.read_text(encoding="utf-8"))
    rng = __import__("random").Random(SEED)
    rebuilt_map = {}
    for row in sorted(pairs, key=lambda value: int(value["situation"][3:])):
        arms = ["bare", "law"]
        if rng.random() < 0.5:
            arms.reverse()
        rebuilt_map[row["situation"]] = {"X": arms[0], "Y": arms[1]}
    check(mapping == rebuilt_map, f"map.json equals the seeded ({SEED}) rebuild")

    print("\ncalls and blindness")
    calls = load_jsonl(shared.CALLS)
    check(len(calls) == EXPECTED["judge_calls"], f"one row per forced-choice call = {len(calls)}")
    check(all(row["phase"] == "judge_forced" for row in calls), "every call is a forced-choice judge call")
    check(all(row["arm"] == "blind" for row in calls), "no call carries an arm label")
    check(all(row["model"] == EXPECTED["model"] for row in calls), "model id matches probe 2")
    check(all(row["thinking"] == EXPECTED["thinking"] for row in calls), "thinking disabled on every call")
    check(all(row["temperature"] == 0.0 for row in calls), "temperature 0 on every call")
    check(all(row["usage"] and row["cost"] for row in calls), "every call records usage and cost")

    policy = shared.policy_text()
    policy_sha = sha(policy)
    emitted = {row["situation"]: row for row in load_jsonl(shared.JUDGE_OUT)}
    requests_ok = True
    blind_ok = True
    for row in calls:
        situation = next(item for item in situations if item["id"] == row["situation"])
        user = shared.build_prompt(situation, {item["situation"]: item for item in pairs}, mapping)
        if row["system_sha256"] != policy_sha:
            requests_ok = False
        if row["request_sha256"] != sha(policy + "\x00" + user):
            requests_ok = False
        if row["request_chars"] != len(policy) + len(user):
            requests_ok = False
        if re.search(r"\b(bare|law|arm)\b", user, re.IGNORECASE):
            blind_ok = False
        if row["call_id"] != emitted[row["situation"]]["call_id"]:
            requests_ok = False
    check(requests_ok, "every request hash/chars rebuilds from excerpt + two answers + question")
    check(blind_ok, "no user prompt contains the words bare, law, or arm")
    check(policy_sha == "325f8b3e2d868f91fb43c24dd088ae6e735386c6d5e2aacfc7496d6ff2726ab6",
          "system message is the exact /home/z/vibe/AGENTS.md bytes probe 2 recorded")

    recomputed_usd = sum(lib.call_cost(row["usage"], row["created"])["usd"] for row in calls)
    spent_usd = sum(row["cost"]["usd"] for row in calls)
    close(recomputed_usd, spent_usd, "recomputed cost equals recorded cost (USD)", digits=6)
    close(spent_usd, EXPECTED["spend_usd"], "spend USD", digits=6)
    close(spent_usd * lib.USD_CNY, EXPECTED["spend_cny"], "spend CNY", digits=6)
    check(spent_usd * lib.USD_CNY < 5.0, "spend under the CNY 5 budget")
    prompt_tokens = sum(row["usage"].get("prompt_tokens", 0) for row in calls)
    cache_hit = sum(row["cost"]["cache_hit_tokens"] for row in calls)
    cache_miss = sum(row["cost"]["cache_miss_tokens"] for row in calls)
    completion = sum(row["cost"]["output_tokens"] for row in calls)
    check(prompt_tokens == EXPECTED["tokens"]["prompt"], f"prompt tokens = {prompt_tokens}")
    check(cache_hit == EXPECTED["tokens"]["cache_hit"], f"cache hit tokens = {cache_hit}")
    check(cache_miss == EXPECTED["tokens"]["cache_miss"], f"cache miss tokens = {cache_miss}")
    check(completion == EXPECTED["tokens"]["completion"], f"completion tokens = {completion}")
    check(cache_hit + cache_miss == prompt_tokens, "cache hit + miss equals prompt tokens")
    smoke = [row for row in calls if row.get("smoke")]
    check(len(smoke) == 2, f"smoke calls = {len(smoke)}")
    smoke_usd = sum(row["cost"]["usd"] for row in smoke)
    projection_cny = (smoke_usd + (len(calls) - len(smoke)) * smoke_usd / len(smoke)) * lib.USD_CNY
    close(projection_cny, EXPECTED["smoke_projection_cny"], "smoke-stage projection CNY", digits=3)

    print("\njudge outputs")
    check(len(emitted) == EXPECTED["judge_calls"], f"one judgment per situation = {len(emitted)}")
    check(set(emitted) == {item["id"] for item in situations}, "judgments cover exactly the 20 situations")
    check(all(row["winner"] in ("X", "Y", "tie") for row in emitted.values()), "winner is X, Y, or tie")
    check(all(row["clause"].strip() for row in emitted.values()), "every judgment gives a clause")
    check(all(row["reason"].strip() for row in emitted.values()), "every judgment gives a reason")

    print("\nforced choice, mapped back to arms")
    law = bare = tie = 0
    for sid, row in emitted.items():
        if row["winner"] == "tie":
            tie += 1
        elif mapping[sid][row["winner"]] == "law":
            law += 1
        else:
            bare += 1
    check(law == EXPECTED["law_wins"], f"law wins = {law}")
    check(bare == EXPECTED["bare_wins"], f"bare wins = {bare}")
    check(tie == EXPECTED["ties"], f"ties = {tie}")
    check(law + bare == EXPECTED["non_ties"], f"non-ties = {law + bare}")
    close(law / (law + bare), EXPECTED["law_share"], "law-win share among non-ties")
    lo, hi = wilson(law, law + bare)
    close(lo, EXPECTED["interval"][0], "Wilson 95% lower bound")
    close(hi, EXPECTED["interval"][1], "Wilson 95% upper bound")
    print(f"  law-win share = {law}/{law + bare} = {law / (law + bare):.4f}, "
          f"Wilson 95% interval = [{lo:.4f}, {hi:.4f}]")

    print("\ngroups: materially different vs same (from probe 2)")
    md = {row["situation"]: row["materially_different"]
          for row in load_jsonl(PROBE2 / "judge" / "judge-out.jsonl")}
    p2_judged = load_jsonl(PROBE2 / "judge" / "judge-out.jsonl")
    p2_ones = sum(value for row in p2_judged for side in ("X", "Y")
                  for value in row[side].values() if value == 1)
    p2_total = sum(1 for row in p2_judged for side in ("X", "Y")
                   for value in row[side].values() if value is not None)
    check(p2_ones == EXPECTED["probe2_saturation"]["ones"], f"probe 2 judged ones = {p2_ones}")
    check(p2_total == EXPECTED["probe2_saturation"]["total"], f"probe 2 judged items = {p2_total}")
    for item in EXPECTED["probe2_full_dim_means"]:
        values = [value for row in p2_judged for side in ("X", "Y") for key, value in row[side].items() if key == item and value is not None]
        check(sum(values) / len(values) == 1.0, f"probe 2 {item} mean is exactly 1.0")
    for name, wanted in (("materially_different", 1), ("same", 0)):
        ids = {sid for sid, value in md.items() if value == wanted}
        got_law = sum(1 for sid in ids if emitted[sid]["winner"] != "tie"
                      and mapping[sid][emitted[sid]["winner"]] == "law")
        got_bare = sum(1 for sid in ids if emitted[sid]["winner"] != "tie"
                       and mapping[sid][emitted[sid]["winner"]] == "bare")
        got_tie = sum(1 for sid in ids if emitted[sid]["winner"] == "tie")
        stats = EXPECTED["groups"][name]
        check(len(ids) == stats["n"], f"{name}: n = {len(ids)}")
        check(got_law == stats["law"], f"{name}: law wins = {got_law}")
        check(got_bare == stats["bare"], f"{name}: bare wins = {got_bare}")
        check(got_tie == stats["ties"], f"{name}: ties = {got_tie}")
        check(got_law + got_bare == stats["non_ties"], f"{name}: non-ties = {got_law + got_bare}")
        share = got_law / (got_law + got_bare)
        glo, ghi = wilson(got_law, got_law + got_bare)
        close(share, stats["law_share"], f"{name}: law-win share")
        close(glo, stats["interval"][0], f"{name}: Wilson 95% lower bound")
        close(ghi, stats["interval"][1], f"{name}: Wilson 95% upper bound")
        print(f"  {name}: {got_law} law / {got_bare} bare / {got_tie} tie = {got_law + got_bare} non-ties, "
              f"share {share:.4f} [{glo:.4f}, {ghi:.4f}]")

    print("\nclause is a verbatim policy substring")
    non_verbatim = []
    for sid, row in emitted.items():
        if row["clause"].strip().strip(STRIP).strip() not in policy:
            non_verbatim.append({"situation": sid, "clause": row["clause"]})
    check(non_verbatim == EXPECTED["non_verbatim"], f"non-verbatim clauses = {json.dumps(non_verbatim, ensure_ascii=False)}")
    check("A normalizer is a must-have, not a nicety" not in policy,
          "negative control: an invented phrase is not a policy substring")

    print("\ndecision rule")
    rule_output, lo, hi = decide(law, bare, law + bare)
    control, _, _ = decide(9, 1, 10)
    check(rule_output == EXPECTED["rule_output"], f"rule output = {rule_output}")
    check(control == "pass", "negative control: 9/10 law wins reaches the pass rule")
    check(decide(0, 6, 6)[0] == "fail", "negative control: 0/6 law wins reaches the fail rule")
    print(f"  rule output: {rule_output} (lower bound {lo:.4f} <= 0.5 <= upper bound {hi:.4f})")

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
