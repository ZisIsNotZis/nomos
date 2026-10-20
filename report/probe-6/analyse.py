#!/usr/bin/env python3
"""Recompute every number in report/probe-6.md and check it against the report.

Rebuilds all 606 stored pairs from probes 4 and 5, verifies that the stored order
of every judged pair reproduces the stored request byte for byte, collapses the
two judged orders of each pair into one status, and recomputes the
consistent-pair shares, inconsistency rates, the swapped same-condition control
diagnostics, the Y-slot position reading, the judge's reproducibility against the
stored verdicts, the clause reading and the spend. Exit 0 only when every
recomputed value equals the value written in the report; exit 1 and print the
differences otherwise.
"""

import hashlib
import json
import sys
from collections import Counter

import common


def verify_stored_requests(pairs):
    """The stored order must reproduce probes 4 and 5's recorded prompts exactly."""
    index = {(pair["dataset"], pair["situation"], pair["draw"]): pair for pair in pairs}
    policy = common.policy_text()
    checks = Counter()
    for row in common.load_jsonl(common.PROBE5 / "calls.jsonl"):
        if row["phase"] not in ("judge_paired", "judge_control"):
            continue
        dataset = "p5_paired" if row["phase"] == "judge_paired" else common.CONTROL
        draw = row["sample"] if dataset == "p5_paired" else 0
        pair = index[(dataset, row["situation"], draw)]
        prompt = common.request_for(pair, "stored")
        checks["p5_total"] += 1
        if hashlib.sha256((policy + "\x00" + prompt).encode()).hexdigest() == row["request_sha256"]:
            checks["p5_match"] += 1
    for row in common.load_jsonl(common.PROBE4 / "calls.jsonl"):
        if not row["phase"].startswith("judge_") or row.get("attempt") != 1:
            continue
        pair = index[("p4_" + row["phase"][len("judge_"):], row["situation"], 0)]
        prompt = common.request_for(pair, "stored")
        checks["p4_total"] += 1
        if hashlib.sha256((policy + "\x00" + prompt).encode()).hexdigest() == row["request_sha256"]:
            checks["p4_match"] += 1
    return checks


def stored_verdicts():
    """The verdicts probes 4 and 5 already had, keyed the way probe 6 keys pairs."""
    out = {}
    for row in common.load_jsonl(common.PROBE5 / "judge-out.jsonl"):
        if row.get("winner") is None:
            continue
        dataset = "p5_paired" if row.get("kind") == "paired" else common.CONTROL
        out[(dataset, row["situation"], row["draw"] if dataset == "p5_paired" else 0)] = row["winner"]
    for row in common.load_jsonl(common.PROBE4 / "judge-out.jsonl"):
        if not row.get("winner"):
            continue
        out[("p4_" + row["comparison"], row["situation"], 0)] = row["winner"]
    return out


def statuses(pairs, judged):
    """One status per pair, from its two order verdicts."""
    out = []
    for pair in pairs:
        key = common.key_of(pair)
        if pair["identical"]:
            out.append((pair, "identical", None, None))
            continue
        rows = {order: judged[key + (order,)] for order in common.ORDERS}
        first, second = rows["stored"]["picked"], rows["swapped"]["picked"]
        out.append((pair, common.pair_status(key[0], first, second), first, second))
    return out


def share_block(rows, wins, losses):
    """Ratio of two outcome labels with Wilson and session-clustered intervals."""
    wins_n = sum(1 for _, outcome in rows if outcome == wins)
    losses_n = sum(1 for _, outcome in rows if outcome == losses)
    n = wins_n + losses_n
    if not n:
        return {"wins": 0, "losses": 0, "n": 0, "share": None, "wilson": None, "bootstrap": None}
    low, high = common.wilson(wins_n, n)
    return {"wins": wins_n, "losses": losses_n, "n": n, "share": wins_n / n,
            "wilson": [low, high],
            "bootstrap": list(common.cluster_bootstrap(rows, wins, losses))}


def dataset_stats(dataset, rows):
    """Counts and shares for one paired dataset, computed from the pair statuses."""
    states = Counter(state for _, state, _, _ in rows)
    policy = common.POLICY_ARM[dataset]
    decisive = states["policy"] + states["bare"] + states["inconsistent"]
    consistency_rows = [(pair["session"], "inconsistent" if state == "inconsistent" else "consistent")
                        for pair, state, _, _ in rows]
    pooled = []
    for pair, _, stored, swapped in rows:
        for verdict in (stored, swapped):
            if verdict in (policy, "bare"):
                pooled.append((pair["session"], verdict))
    return {
        "pairs": len(rows),
        "identical": states["identical"],
        "tie": states["tie"],
        "policy": states["policy"],
        "bare": states["bare"],
        "inconsistent": states["inconsistent"],
        "decisive_both_orders": decisive,
        "inconsistency_rate": states["inconsistent"] / decisive if decisive else None,
        "inconsistency_wilson": list(common.wilson(states["inconsistent"], decisive)) if decisive else None,
        "inconsistency_bootstrap": list(common.cluster_bootstrap(
            consistency_rows, "inconsistent", "consistent")),
        # Conservative reading of the same rate: a pair with any tie counts as inconsistent.
        "inconsistency_rate_tie_as_inconsistent": (
            (states["inconsistent"] + states["tie"]) / (decisive + states["tie"])
            if decisive + states["tie"] else None),
        "consistent": share_block([(pair["session"], state) for pair, state, _, _ in rows],
                                  "policy", "bare"),
        "stored_order": share_block([(pair["session"], stored) for pair, _, stored, _ in rows
                                     if stored in (policy, "bare")], policy, "bare"),
        "swapped_order": share_block([(pair["session"], swapped) for pair, _, _, swapped in rows
                                      if swapped in (policy, "bare")], policy, "bare"),
        "two_order_pooled": share_block(pooled, policy, "bare"),
    }


def position_readings(pairs, judged):
    """How often each order's judge picked the Y slot, per dataset and overall."""
    out = {"all": {}, "by_dataset": {}}
    for order in common.ORDERS:
        picks = [judged[common.key_of(pair) + (order,)] for pair in pairs if not pair["identical"]]
        decisive = [row for row in picks if row["winner"] in ("X", "Y")]
        out["all"][order] = {"decisive": len(decisive),
                             "y": sum(1 for row in decisive if row["winner"] == "Y")}
        for dataset in common.DATASETS:
            subset = [row for row in decisive if row["dataset"] == dataset]
            out["by_dataset"].setdefault(dataset, {})[order] = {
                "decisive": len(subset), "y": sum(1 for row in subset if row["winner"] == "Y")}
    return out


def control_stats(rows):
    """The swapped same-condition control: position bias must collapse into disagreement."""
    states = Counter(state for _, state, _, _ in rows)
    decisive = states["same"] + states["inconsistent"]
    by_session = [(pair["session"], state) for pair, state, _, _ in rows]
    side_rows = [(pair["session"], first) for pair, state, first, second in rows
                 if state == "same" and first == second]
    return {
        "pairs": len(rows),
        "identical": states["identical"],
        "tie": states["tie"],
        "same": states["same"],
        "inconsistent": states["inconsistent"],
        "decisive_both_orders": decisive,
        "inconsistency_rate": states["inconsistent"] / decisive if decisive else None,
        "inconsistency_wilson": list(common.wilson(states["inconsistent"], decisive)),
        "inconsistency_bootstrap": list(common.cluster_bootstrap(by_session, "inconsistent", "same")),
        "consistent_side": share_block(side_rows, "full#2", "full#1"),
    }


def reproducibility(pairs, judged, stored):
    """Does the stored order reproduce probe 4/5's own verdict on the same bytes?"""
    counts = Counter()
    flips = Counter()
    for pair in pairs:
        key = common.key_of(pair)
        if pair["identical"] or key not in stored:
            continue
        before = stored[key]
        after = judged[key + ("stored",)]["winner"]
        counts["total"] += 1
        if before == after:
            counts["agree"] += 1
        else:
            counts["disagree"] += 1
            flips[f"{before}->{after}"] += 1
    return {"agree": counts["agree"], "total": counts["total"],
            "rate": counts["agree"] / counts["total"] if counts["total"] else None,
            "flips": dict(flips)}


def artefact_counts():
    """Rows recorded, and how many (pair, order) keys were judged twice."""
    rows = common.load_jsonl(common.JUDGE_OUT)
    verdicts = [row for row in rows if row.get("winner") is not None]
    keys = Counter((row["dataset"], row["situation"], row["draw"], row["order"]) for row in verdicts)
    duplicated = sorted(key for key, count in keys.items() if count > 1)
    disagreements = []
    for key in duplicated:
        winners = {row["winner"] for row in verdicts
                   if (row["dataset"], row["situation"], row["draw"], row["order"]) == key}
        if len(winners) > 1:
            disagreements.append(key)
    return {"rows": len(rows), "verdicts": len(verdicts),
            "identical_rows": len(rows) - len(verdicts),
            "duplicate_keys": len(duplicated), "duplicate_disagreements": len(disagreements)}


def clause_reading():
    rows = common.load_jsonl(common.JUDGE_OUT)
    total = sum(1 for row in rows if row.get("clause_ok") is not None)
    ok = sum(1 for row in rows if row.get("clause_ok") is True)
    return {"ok": ok, "total": total, "rate": ok / total if total else None}


def spend():
    rows = common.load_jsonl(common.CALLS)
    by_dataset = {}
    for row in rows:
        bucket = by_dataset.setdefault(row["dataset"], {"calls": 0, "cny": 0.0, "usd": 0.0})
        bucket["calls"] += 1
        bucket["cny"] += row["cost"]["cny"]
        bucket["usd"] += row["cost"]["usd"]
    return {
        "calls": len(rows),
        "prompt_tokens": sum(row["usage"]["prompt_tokens"] for row in rows),
        "cache_hit_tokens": sum(row["usage"].get("prompt_cache_hit_tokens", 0) or 0 for row in rows),
        "cache_miss_tokens": sum(row["usage"].get("prompt_cache_miss_tokens", 0) or 0 for row in rows),
        "completion_tokens": sum(row["usage"]["completion_tokens"] for row in rows),
        "usd": sum(row["cost"]["usd"] for row in rows),
        "cny": sum(row["cost"]["cny"] for row in rows),
        "by_dataset": by_dataset,
    }


def reading(stats, control):
    """The pre-registered mechanical verdict, per dataset."""
    control_gate = control["inconsistency_wilson"][1] >= 0.5
    side = control["consistent_side"]
    side_gate = side["wilson"][0] <= 0.5 <= side["wilson"][1]
    usable = control_gate and side_gate
    out = {"control_inconsistency_exceeds_half": control_gate,
           "control_side_contains_half": side_gate,
           "instrument_usable": usable, "datasets": {}}
    for dataset, block in stats.items():
        share = block["consistent"]
        bootstrap_excludes = share["bootstrap"][0] > 0.5 or share["bootstrap"][1] < 0.5
        same_direction = ((share["wilson"][0] > 0.5 and share["bootstrap"][0] > 0.5)
                          or (share["wilson"][1] < 0.5 and share["bootstrap"][1] < 0.5))
        gates = {"share_interval_excludes_half": bootstrap_excludes and same_direction,
                 "inconsistency_below_half": block["inconsistency_rate"] < 0.5,
                 "control_unusable_gate": usable}
        established = all(gates.values())
        if not usable:
            outcome = "instrument unusable"
        elif established:
            outcome = "position confound removed and effect established"
        else:
            outcome = "position confound removed, effect not established"
        out["datasets"][dataset] = {"gates": gates, "outcome": outcome}
    return out


def rounded(value, digits=4):
    return None if value is None else round(value, digits)


def summarise(block):
    """Every numeric field of a stats block, rounded, nested blocks kept."""
    out = {}
    for key, value in block.items():
        if isinstance(value, dict):
            out[key] = summarise(value)
        elif isinstance(value, list):
            out[key] = [rounded(part) for part in value]
        else:
            out[key] = rounded(value)
    return out


def compare(expected, actual, path=""):
    differences = []
    if isinstance(expected, dict):
        for key, value in expected.items():
            if key not in actual:
                differences.append(f"{path}/{key}: missing in recomputation")
            else:
                differences.extend(compare(value, actual[key], f"{path}/{key}"))
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            differences.append(f"{path}: {expected!r} != {actual!r}")
        else:
            for index, (left, right) in enumerate(zip(expected, actual)):
                differences.extend(compare(left, right, f"{path}/{index}"))
    elif isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if abs(expected - actual) > 1e-9:
            differences.append(f"{path}: {expected!r} != {actual!r}")
    elif expected != actual:
        differences.append(f"{path}: {expected!r} != {actual!r}")
    return differences


def main():
    pairs = common.pairs()
    checks = verify_stored_requests(pairs)
    judged = {tuple(list(common.key_of(row)) + [row["order"]]): row
              for row in common.load_jsonl(common.JUDGE_OUT) if row.get("order")}
    stored = stored_verdicts()
    rows = statuses(pairs, judged)
    by_dataset = {}
    for pair, state, first, second in rows:
        by_dataset.setdefault(pair["dataset"], []).append((pair, state, first, second))

    stats = {dataset: dataset_stats(dataset, by_dataset[dataset])
             for dataset in common.DATASETS if dataset != common.CONTROL}
    control = control_stats(by_dataset[common.CONTROL])
    position = position_readings(pairs, judged)
    repro = reproducibility(pairs, judged, stored)
    clauses = clause_reading()
    artefacts = artefact_counts()
    money = spend()
    verdict = reading(stats, control)

    print(f"stored-order requests reproducing probes 4/5 byte for byte: "
          f"{checks['p5_match']}/{checks['p5_total']} (probe 5), "
          f"{checks['p4_match']}/{checks['p4_total']} (probe 4)")
    print(f"pairs {len(pairs)}; judged pairs {sum(1 for pair in pairs if not pair['identical'])}")
    print()
    for dataset, block in stats.items():
        print(f"== {dataset}")
        print(f"   pairs {block['pairs']}, identical {block['identical']}, tie {block['tie']}, "
              f"policy {block['policy']}, bare {block['bare']}, "
              f"inconsistent {block['inconsistent']}")
        print(f"   decisive in both orders {block['decisive_both_orders']}, inconsistency "
              f"{rounded(block['inconsistency_rate'])} "
              f"wilson {[rounded(v) for v in block['inconsistency_wilson']]} "
              f"bootstrap {[rounded(v) for v in block['inconsistency_bootstrap']]} "
              f"tie-as-inconsistent {rounded(block['inconsistency_rate_tie_as_inconsistent'])}")
        for name in ("consistent", "stored_order", "swapped_order", "two_order_pooled"):
            share = block[name]
            print(f"   {name}: {share['wins']}/{share['n']} = {rounded(share['share'])} "
                  f"wilson {[rounded(v) for v in share['wilson']]} "
                  f"bootstrap {[rounded(v) for v in share['bootstrap']]}")
    print()
    print("== p5_control")
    print(f"   pairs {control['pairs']}, identical {control['identical']}, tie {control['tie']}, "
          f"same {control['same']}, inconsistent {control['inconsistent']}, "
          f"decisive {control['decisive_both_orders']}")
    print(f"   inconsistency {rounded(control['inconsistency_rate'])} "
          f"wilson {[rounded(v) for v in control['inconsistency_wilson']]} "
          f"bootstrap {[rounded(v) for v in control['inconsistency_bootstrap']]}")
    share = control["consistent_side"]
    print(f"   consistent-side full#2 {share['wins']}/{share['n']} = {rounded(share['share'])} "
          f"wilson {[rounded(v) for v in share['wilson']]} "
          f"bootstrap {[rounded(v) for v in share['bootstrap']]}")
    print()
    for order in common.ORDERS:
        block = position["all"][order]
        print(f"Y-slot picks, {order} order: {block['y']}/{block['decisive']} "
              f"= {rounded(block['y'] / block['decisive'])}")
    for dataset, per in position["by_dataset"].items():
        for order in common.ORDERS:
            block = per[order]
            print(f"   {dataset} {order}: Y {block['y']}/{block['decisive']} "
                  f"= {rounded(block['y'] / block['decisive']) if block['decisive'] else None}")
    print()
    print(f"judge-out rows: {artefacts['rows']} ({artefacts['verdicts']} verdicts + "
          f"{artefacts['identical_rows']} identical status rows); duplicated keys "
          f"{artefacts['duplicate_keys']} with {artefacts['duplicate_disagreements']} disagreements")
    print(f"stored-order verdicts agreeing with probes 4/5: {repro['agree']}/{repro['total']} "
          f"= {rounded(repro['rate'])}; flips {repro['flips']}")
    print(f"clause verbatim {clauses['ok']}/{clauses['total']} = {rounded(clauses['rate'])}")
    print(f"spend: {money['calls']} calls, prompt {money['prompt_tokens']} "
          f"(hit {money['cache_hit_tokens']} / miss {money['cache_miss_tokens']}), "
          f"completion {money['completion_tokens']}, ${money['usd']:.6f} / ¥{money['cny']:.4f}")
    for dataset, block in money["by_dataset"].items():
        print(f"   {dataset}: {block['calls']} calls, ${block['usd']:.6f} / ¥{block['cny']:.4f}")
    print()
    print(f"control inconsistency interval exceeds 0.5: "
          f"{verdict['control_inconsistency_exceeds_half']}; "
          f"control side contains 0.5: {verdict['control_side_contains_half']}; "
          f"instrument usable: {verdict['instrument_usable']}")
    for dataset, block in verdict["datasets"].items():
        print(f"   {dataset}: {block['outcome']} gates={block['gates']}")

    actual = {
        "checks": {"p5_match": checks["p5_match"], "p5_total": checks["p5_total"],
                   "p4_match": checks["p4_match"], "p4_total": checks["p4_total"]},
        "pairs": len(pairs),
        "judged_pairs": sum(1 for pair in pairs if not pair["identical"]),
        "control": summarise(control),
        "datasets": {name: summarise(block) for name, block in stats.items()},
        "position": {order: {"decisive": block["decisive"], "y": block["y"]}
                     for order, block in position["all"].items()},
        "reproducibility": repro,
        "artefacts": artefacts,
        "clauses": {"ok": clauses["ok"], "total": clauses["total"], "rate": rounded(clauses["rate"])},
        "spend": {"calls": money["calls"], "cny": rounded(money["cny"]),
                  "prompt_tokens": money["prompt_tokens"],
                  "cache_hit_tokens": money["cache_hit_tokens"],
                  "cache_miss_tokens": money["cache_miss_tokens"],
                  "completion_tokens": money["completion_tokens"]},
        "reading": verdict,
    }
    if "--dump" in sys.argv:
        print(json.dumps(actual, ensure_ascii=False, indent=1))
        return 0
    EXPECTED = {
        "checks": {
            "p5_match": 224,
            "p5_total": 224,
            "p4_match": 360,
            "p4_total": 360
        },
        "pairs": 606,
        "judged_pairs": 584,
        "control": {
            "pairs": 60,
            "identical": 13,
            "tie": 2,
            "same": 11,
            "inconsistent": 34,
            "decisive_both_orders": 45,
            "inconsistency_rate": 0.7556,
            "inconsistency_wilson": [
                0.6133,
                0.8576
            ],
            "inconsistency_bootstrap": [
                0.6364,
                0.8679
            ],
            "consistent_side": {
                "wins": 5,
                "losses": 6,
                "n": 11,
                "share": 0.4545,
                "wilson": [
                    0.2127,
                    0.7199
                ],
                "bootstrap": [
                    0.1818,
                    0.7273
                ]
            }
        },
        "datasets": {
            "p5_paired": {
                "pairs": 180,
                "identical": 3,
                "tie": 10,
                "policy": 34,
                "bare": 12,
                "inconsistent": 121,
                "decisive_both_orders": 167,
                "inconsistency_rate": 0.7246,
                "inconsistency_wilson": [
                    0.6523,
                    0.7867
                ],
                "inconsistency_bootstrap": [
                    0.5774,
                    0.761
                ],
                "inconsistency_rate_tie_as_inconsistent": 0.7401,
                "consistent": {
                    "wins": 34,
                    "losses": 12,
                    "n": 46,
                    "share": 0.7391,
                    "wilson": [
                        0.5974,
                        0.844
                    ],
                    "bootstrap": [
                        0.5556,
                        0.8889
                    ]
                },
                "stored_order": {
                    "wins": 99,
                    "losses": 72,
                    "n": 171,
                    "share": 0.5789,
                    "wilson": [
                        0.504,
                        0.6504
                    ],
                    "bootstrap": [
                        0.5062,
                        0.6492
                    ]
                },
                "swapped_order": {
                    "wins": 97,
                    "losses": 75,
                    "n": 172,
                    "share": 0.564,
                    "wilson": [
                        0.4892,
                        0.6359
                    ],
                    "bootstrap": [
                        0.4969,
                        0.6358
                    ]
                },
                "two_order_pooled": {
                    "wins": 196,
                    "losses": 147,
                    "n": 343,
                    "share": 0.5714,
                    "wilson": [
                        0.5186,
                        0.6227
                    ],
                    "bootstrap": [
                        0.5197,
                        0.6273
                    ]
                }
            },
            "p4_full_vs_bare": {
                "pairs": 183,
                "identical": 1,
                "tie": 6,
                "policy": 41,
                "bare": 18,
                "inconsistent": 117,
                "decisive_both_orders": 176,
                "inconsistency_rate": 0.6648,
                "inconsistency_wilson": [
                    0.5922,
                    0.7303
                ],
                "inconsistency_bootstrap": [
                    0.5529,
                    0.7238
                ],
                "inconsistency_rate_tie_as_inconsistent": 0.6758,
                "consistent": {
                    "wins": 41,
                    "losses": 18,
                    "n": 59,
                    "share": 0.6949,
                    "wilson": [
                        0.5685,
                        0.7975
                    ],
                    "bootstrap": [
                        0.5741,
                        0.8101
                    ]
                },
                "stored_order": {
                    "wins": 100,
                    "losses": 78,
                    "n": 178,
                    "share": 0.5618,
                    "wilson": [
                        0.4884,
                        0.6326
                    ],
                    "bootstrap": [
                        0.4785,
                        0.6434
                    ]
                },
                "swapped_order": {
                    "wins": 101,
                    "losses": 76,
                    "n": 177,
                    "share": 0.5706,
                    "wilson": [
                        0.497,
                        0.6413
                    ],
                    "bootstrap": [
                        0.4947,
                        0.6425
                    ]
                },
                "two_order_pooled": {
                    "wins": 201,
                    "losses": 154,
                    "n": 355,
                    "share": 0.5662,
                    "wilson": [
                        0.5142,
                        0.6168
                    ],
                    "bootstrap": [
                        0.5235,
                        0.6106
                    ]
                }
            },
            "p4_slice_vs_bare": {
                "pairs": 183,
                "identical": 5,
                "tie": 11,
                "policy": 31,
                "bare": 11,
                "inconsistent": 125,
                "decisive_both_orders": 167,
                "inconsistency_rate": 0.7485,
                "inconsistency_wilson": [
                    0.6776,
                    0.8082
                ],
                "inconsistency_bootstrap": [
                    0.6139,
                    0.7533
                ],
                "inconsistency_rate_tie_as_inconsistent": 0.764,
                "consistent": {
                    "wins": 31,
                    "losses": 11,
                    "n": 42,
                    "share": 0.7381,
                    "wilson": [
                        0.5893,
                        0.847
                    ],
                    "bootstrap": [
                        0.6071,
                        0.8571
                    ]
                },
                "stored_order": {
                    "wins": 93,
                    "losses": 78,
                    "n": 171,
                    "share": 0.5439,
                    "wilson": [
                        0.4691,
                        0.6167
                    ],
                    "bootstrap": [
                        0.4583,
                        0.6257
                    ]
                },
                "swapped_order": {
                    "wins": 100,
                    "losses": 71,
                    "n": 171,
                    "share": 0.5848,
                    "wilson": [
                        0.5099,
                        0.656
                    ],
                    "bootstrap": [
                        0.517,
                        0.6443
                    ]
                },
                "two_order_pooled": {
                    "wins": 193,
                    "losses": 149,
                    "n": 342,
                    "share": 0.5643,
                    "wilson": [
                        0.5113,
                        0.6159
                    ],
                    "bootstrap": [
                        0.5281,
                        0.598
                    ]
                }
            }
        },
        "position": {
            "stored": {
                "decisive": 565,
                "y": 488
            },
            "swapped": {
                "decisive": 566,
                "y": 470
            }
        },
        "reproducibility": {
            "agree": 520,
            "total": 584,
            "rate": 0.8904109589041096,
            "flips": {
                "X->Y": 35,
                "tie->Y": 8,
                "Y->tie": 9,
                "Y->X": 12
            }
        },
        "artefacts": {
            "rows": 1216,
            "verdicts": 1172,
            "identical_rows": 44,
            "duplicate_keys": 4,
            "duplicate_disagreements": 0
        },
        "clauses": {
            "ok": 988,
            "total": 1172,
            "rate": 0.843
        },
        "spend": {
            "calls": 1172,
            "cny": 2.3868,
            "prompt_tokens": 23870300,
            "cache_hit_tokens": 23481780,
            "cache_miss_tokens": 388520,
            "completion_tokens": 82605
        },
        "reading": {
            "control_inconsistency_exceeds_half": True,
            "control_side_contains_half": True,
            "instrument_usable": True,
            "datasets": {
                "p5_paired": {
                    "gates": {
                        "share_interval_excludes_half": True,
                        "inconsistency_below_half": False,
                        "control_unusable_gate": True
                    },
                    "outcome": "position confound removed, effect not established"
                },
                "p4_full_vs_bare": {
                    "gates": {
                        "share_interval_excludes_half": True,
                        "inconsistency_below_half": False,
                        "control_unusable_gate": True
                    },
                    "outcome": "position confound removed, effect not established"
                },
                "p4_slice_vs_bare": {
                    "gates": {
                        "share_interval_excludes_half": True,
                        "inconsistency_below_half": False,
                        "control_unusable_gate": True
                    },
                    "outcome": "position confound removed, effect not established"
                }
            }
        }
    }

    if EXPECTED:
        differences = compare(EXPECTED, actual)
        if differences:
            print("\nMISMATCH against the report:")
            for difference in differences:
                print(f"  {difference}")
            return 1
        print("\nall recomputed values equal the report")
    return 0


if __name__ == "__main__":
    sys.exit(main())