#!/usr/bin/env python3
"""诊断：rubric 分不开两侧，是"法在四个维度上真的没影响"，还是"仪器看不见动作不同那部分差异"。

只用已落盘的数据，不调 API：

  data/pairs-filtered.jsonl     174 组处境的处境原文与两侧回答
  evidence/rubric/counts.jsonl  174×2 条的可判子级原始计数（由 eval/judge.py --counts 落盘）
  evidence/rubric/judge-out.jsonl  64 组的评委判读（含 control 8 组）
  mining/candidates.jsonl       会话来源，用来给处境归组到会话（见 session_map）

分层：两侧解析出的动作签名不同才算"动作不同"的对。动作签名 = `tool: 名称(参数)`
按出现顺序排成的列表，参数空白压成一个空格后逐字比较。

判据在跑之前写死（SUBITEM_ALPHA、HELDOUT_*）：一个子项算"能分开"，要同时满足
  1. 在动作不同的全部对上，配对符号检验 p < SUBITEM_ALPHA（8 个子项做 Bonferroni）；
  2. 同一批对上 δ 的 95% 自助区间不含 0；
  3. 按会话切两半，在选子项的那一半上取检验 p 最小的子项（要求 p < SELECT_P 且方向为带法
     更好），在另一半上重测得同方向、p < HELDOUT_P、区间不含 0；随机切 HELDOUT_ROUNDS
     次，成功率 ≥ HELDOUT_RATE 才算挺过留出。
三条全过写"仪器可修"，否则写"锚点不成立"。

用法：python3 eval/rubric_diagnosis.py
"""

import json
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import analyse  # noqa: E402  符号检验与自助区间只此一份
import judge   # noqa: E402  动作解析与子项分数只此一份

COUNTS = REPO / "evidence" / "rubric" / "counts.jsonl"
JUDGE_ROWS = REPO / "evidence" / "rubric" / "judge-out.jsonl"
CANDIDATES = REPO / "mining" / "candidates.jsonl"
OUT = REPO / "evidence" / "rubric-diagnosis"
SEED = 20261102
BOOTSTRAP = 10000
SUBITEM_ALPHA = 0.05             # Bonferroni：8 个子项，见 SUBITEM_COUNT
SUBITEM_COUNT = 8
SELECT_P = 0.05
HELDOUT_P = 0.05
HELDOUT_ROUNDS = 200
HELDOUT_RATE = 0.95
TOL = 1e-9

SUBITEMS = (("phase", "unauthorized_actions"), ("phase", "discussion_as_advance"),
            ("evidence", "unlabeled_inferences"), ("evidence", "assert_before_prove"),
            ("question", "environment_questions"), ("question", "stops_before_gate"),
            ("delivery", "checkable_artifacts"), ("delivery", "unrecorded_changes"))


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def signature(answer):
    """两侧"动作是否不同"的比较键：按顺序的 (工具, 参数) 列表。"""
    return tuple((action["tool"], " ".join(action["args"].split()))
                 for action in judge.parse_actions(answer))


def subitem_scores(counts):
    """把一条回答的原始计数换算成 8 个子项分数；不适用记 None。"""
    scores = {}
    for dimension, name in SUBITEMS:
        count = counts[dimension][name]["count"]
        scores[(dimension, name)] = None if count is None else judge.SUBITEM_SCORE[(dimension, name)](count)
    return scores


def scalar(entry, key):
    """一个子项的分数，或（key 为 None）8 个子项分数在适用子项上的等权均值。"""
    if key is not None:
        return entry[key]
    values = [value for value in entry.values() if value is not None]
    return statistics.fmean(values) if values else None


def pair_stats(pairs, scores, key):
    """一个子项（或合成分）在给定对集合上的δ、区间、胜负与符号检验。

    key 为 None 表示合成分：8 个子项分数的等权均值，只在至少一个子项适用时计入。
    一对只在一侧适用时不进比较（两侧不对称另报），两侧都不适用记 null。
    """
    diffs, chosen_values, rejected_values = [], [], []
    both_null = asymmetric = 0
    for situation_id in pairs:
        chosen = scalar(scores[(situation_id, "chosen")], key)
        rejected = scalar(scores[(situation_id, "rejected")], key)
        if chosen is None and rejected is None:
            both_null += 1
            continue
        if chosen is None or rejected is None:
            asymmetric += 1
            continue
        chosen_values.append(chosen)
        rejected_values.append(rejected)
        diffs.append(chosen - rejected)
    if not diffs:
        return {"n": 0, "both_null": both_null, "asymmetric": asymmetric}
    delta = statistics.fmean(diffs)
    rng = random.Random(SEED)
    low, high = analyse.bootstrap_ci(diffs, rng)
    within = [diff for diff in diffs if abs(diff) > TOL]
    wins = sum(1 for diff in within if diff > 0)
    losses = sum(1 for diff in within if diff < 0)
    return {
        "n": len(diffs),
        "both_null": both_null,
        "asymmetric": asymmetric,
        "chosen_mean": round(statistics.fmean(chosen_values), 4),
        "rejected_mean": round(statistics.fmean(rejected_values), 4),
        "delta": round(delta, 4),
        "delta_ci95": [round(low, 4), round(high, 4)],
        "wins": wins,
        "losses": losses,
        "direction_consistent": f"{wins}/{losses}" if wins + losses else "0/0",
        "sign_test_p": round(analyse.sign_test(wins, losses), 6),
        "excluded": len(pairs) - len(diffs),
    }


def win_share(diffs):
    """带法被判更高的比例与自助区间：只在有胜负的对里算，平局单列。"""
    within = [diff for diff in diffs if abs(diff) > TOL]
    wins = sum(1 for diff in within if diff > 0)
    losses = sum(1 for diff in within if diff < 0)
    share = wins / len(within) if within else None
    rng = random.Random(SEED)
    shares = []
    for _ in range(BOOTSTRAP):
        sample = [within[rng.randrange(len(within))] for _ in range(len(within))]
        positive = sum(1 for diff in sample if diff > 0)
        shares.append(positive / len(sample))
    shares.sort()
    return {
        "wins": wins, "losses": losses, "ties": len(diffs) - len(within),
        "share": None if share is None else round(share, 4),
        "share_ci95": None if not shares else [round(shares[int(0.025 * BOOTSTRAP)], 4),
                                               round(shares[int(0.975 * BOOTSTRAP) - 1], 4)],
    }


def session_map(pairs):
    """处境 → 会话。data/ 里没有会话字段，回落到 mining/candidates.jsonl 的 session。

    匹配方式：取处境最后一条 USER 轮的正文，空白全部压掉，找它在候选窗口文本里能匹配
    到的最长前缀；取前缀最长的候选的 session。前缀长度一并落盘，短的是弱匹配。
    """
    candidates = load_jsonl(CANDIDATES)
    texts = ["".join(row["text"].split()) for row in candidates]
    mapping = {}
    for pair in pairs:
        turn = "".join(judge.last_user_turn(pair["excerpt"]).split())
        best_session, best_length = "", 0
        for candidate, text in zip(candidates, texts):
            low, high = 0, len(turn)
            while low < high:
                middle = (low + high + 1) // 2
                if turn[:middle] in text:
                    low = middle
                else:
                    high = middle - 1
            if low > best_length:
                best_session, best_length = candidate["session"], low
        mapping[pair["situation_id"]] = {"session": best_session, "match_chars": best_length}
    return mapping


def heldout(pairs, scores, mapping):
    """按会话切两半：一半选子项，另一半重测。返回每一轮的明细与汇总。"""
    sessions = sorted({entry["session"] for entry in mapping.values()})
    rounds = []
    for index in range(HELDOUT_ROUNDS):
        rng = random.Random(SEED + index)
        order = sessions[:]
        rng.shuffle(order)
        pick = set(order[:len(order) // 2])
        select_ids = [sid for sid in pairs if mapping[sid]["session"] in pick]
        test_ids = [sid for sid in pairs if mapping[sid]["session"] not in pick]
        if len(select_ids) < 10 or len(test_ids) < 10:
            continue
        ranked = []
        for key in SUBITEMS:
            stats = pair_stats(select_ids, scores, key)
            if stats.get("n"):
                ranked.append((stats["sign_test_p"], stats["delta"], key, stats))
        if not ranked:
            rounds.append({"seed": SEED + index, "selected": None, "passed": False,
                           "reason": "选子项那一半没有可用子项"})
            continue
        ranked.sort()
        p_select, delta_select, key, _stats = ranked[0]
        name = f"{key[0]}.{key[1]}"
        if p_select >= SELECT_P or delta_select <= 0:
            rounds.append({"seed": SEED + index, "selected": None, "passed": False,
                           "reason": "选子项那一半没有子项达标",
                           "best": {"subitem": name, "sign_test_p": p_select, "delta": delta_select}})
            continue
        tested = pair_stats(test_ids, scores, key)
        composite_select = pair_stats(select_ids, scores, None)
        composite_test = pair_stats(test_ids, scores, None)
        passed = (tested["delta"] > 0 and tested["delta_ci95"][0] > 0
                  and tested["sign_test_p"] < HELDOUT_P)
        rounds.append({
            "seed": SEED + index,
            "selected": name,
            "select_stats": {k: _stats[k] for k in ("n", "delta", "delta_ci95", "direction_consistent", "sign_test_p")},
            "test_stats": {k: tested[k] for k in ("n", "delta", "delta_ci95", "direction_consistent", "sign_test_p")},
            "composite_select": {k: composite_select[k] for k in ("n", "delta", "delta_ci95", "sign_test_p")},
            "composite_test": {k: composite_test[k] for k in ("n", "delta", "delta_ci95", "sign_test_p")},
            "passed": passed,
        })
    attempted = [item for item in rounds if item.get("selected") or "best" in item]
    return rounds, attempted


def judge_out_pairs():
    """64 组判读的逐对合成分差：正负各多少、最大差在哪，以及子项层面是否两向抵消。"""
    rows = load_jsonl(JUDGE_ROWS)
    pairs = {pair["situation_id"]: pair for pair in judge.load_pairs()}
    by_pair = {}
    gap = 0.0
    for row in rows:
        if row["kind"] != "pair":
            continue
        pair = pairs[row["situation_id"]]
        counts = judge.count_checks(pair, pair[row["side"]])
        score = judge.score_answer(counts, row["conditions"])
        gap = max(gap, abs(score["total"] - row["total"]))
        by_pair.setdefault(row["situation_id"], {}).setdefault(row["side"], []).append(score["total"])
    diffs = {}
    for situation_id, sides in by_pair.items():
        if "chosen" in sides and "rejected" in sides:
            diffs[situation_id] = statistics.fmean(sides["chosen"]) - statistics.fmean(sides["rejected"])
    values = list(diffs.values())
    largest = max(diffs.items(), key=lambda item: abs(item[1]))
    return {
        "n_pairs": len(values),
        "recomputed_vs_stored_max_gap": round(gap, 6),
        "mean_delta": round(statistics.fmean(values), 4),
        "positive": sum(1 for value in values if value > TOL),
        "negative": sum(1 for value in values if value < -TOL),
        "zero": sum(1 for value in values if abs(value) <= TOL),
        "largest_abs": {"situation_id": largest[0], "delta": round(largest[1], 4)},
        "max_gain": round(max(values), 4),
        "max_loss": round(min(values), 4),
        "diffs": {situation_id: round(value, 4) for situation_id, value in sorted(diffs.items())},
    }


def main():
    pairs = judge.load_pairs()
    counts_rows = {(row["situation_id"], row["side"]): row["counts"] for row in load_jsonl(COUNTS)}
    recompute_gap = 0
    for pair in pairs:
        for side in ("chosen", "rejected"):
            fresh = judge.count_checks(pair, pair[side])
            if fresh != counts_rows[(pair["situation_id"], side)]:
                recompute_gap += 1
    scores = {key: subitem_scores(value) for key, value in counts_rows.items()}

    signatures = {pair["situation_id"]: (signature(pair["chosen"]), signature(pair["rejected"]))
                  for pair in pairs}
    differ = [pair["situation_id"] for pair in pairs
              if signatures[pair["situation_id"]][0] != signatures[pair["situation_id"]][1]]
    same = [pair["situation_id"] for pair in pairs
            if signatures[pair["situation_id"]][0] == signatures[pair["situation_id"]][1]]
    length_differs = [sid for sid in differ
                      if len(signatures[sid][0]) != len(signatures[sid][1])]

    table = {}
    for key in SUBITEMS + (None,):
        name = "composite_counts" if key is None else f"{key[0]}.{key[1]}"
        table[name] = {
            "action_differ": pair_stats(differ, scores, key),
            "all_pairs": pair_stats([pair["situation_id"] for pair in pairs], scores, key),
            "action_same": pair_stats(same, scores, key),
        }

    # 一对之内是否两向抵消：有子项偏带法，也有子项偏不带法
    offsets = {"pairs": 0, "with_both_directions": 0, "chosen_only": 0, "rejected_only": 0, "neither": 0}
    for situation_id in differ:
        chosen = scores[(situation_id, "chosen")]
        rejected = scores[(situation_id, "rejected")]
        up = down = False
        offsets["pairs"] += 1
        for key in SUBITEMS:
            if chosen[key] is None or rejected[key] is None:
                continue
            diff = chosen[key] - rejected[key]
            up = up or diff > TOL
            down = down or diff < -TOL
        if up and down:
            offsets["with_both_directions"] += 1
        elif up:
            offsets["chosen_only"] += 1
        elif down:
            offsets["rejected_only"] += 1
        else:
            offsets["neither"] += 1

    # 带法被判更高的比例与区间，两个来源：可判子级合成分，与评委判读的合成分
    composite_diffs = []
    for situation_id in differ:
        chosen = scalar(scores[(situation_id, "chosen")], None)
        rejected = scalar(scores[(situation_id, "rejected")], None)
        if chosen is not None and rejected is not None:
            composite_diffs.append(chosen - rejected)
    judged = judge_out_pairs()
    mapping = session_map(pairs)
    differ_mapping = {sid: mapping[sid] for sid in differ}
    rounds, valid = heldout(differ, scores, differ_mapping)
    confident = [sid for sid in differ if mapping[sid]["match_chars"] >= 30]
    rounds_confident, valid_confident = heldout(confident, scores, {sid: mapping[sid] for sid in confident})
    successes = sum(1 for item in rounds if item["passed"])
    successes_confident = sum(1 for item in rounds_confident if item["passed"])

    sign_alpha = SUBITEM_ALPHA / SUBITEM_COUNT
    discriminating = []
    for name, block in table.items():
        stats = block["action_differ"]
        if not stats.get("n"):
            continue
        if (stats["sign_test_p"] < sign_alpha and stats["delta"] > 0
                and stats["delta_ci95"][0] > 0):
            discriminating.append(name)
    held_out_ok = successes / max(1, len(rounds)) >= HELDOUT_RATE
    verdict = "仪器可修" if (discriminating and held_out_ok) else "锚点不成立"

    differ_set = set(differ)
    judged_differ = [value for situation_id, value in judged["diffs"].items()
                     if situation_id in differ_set]
    # 留出里唯一被选中的子项：差异来自哪些对、哪些会话
    selected_names = [item["selected"] for item in rounds if item.get("selected")]
    signal_pairs = []
    for name in set(selected_names):
        dimension, subitem = name.split(".")
        for situation_id in differ:
            chosen = scores[(situation_id, "chosen")][(dimension, subitem)]
            rejected = scores[(situation_id, "rejected")][(dimension, subitem)]
            if chosen is None or rejected is None or abs(chosen - rejected) <= TOL:
                continue
            signal_pairs.append({"situation_id": situation_id, "subitem": name,
                                 "chosen_score": round(chosen, 4), "rejected_score": round(rejected, 4),
                                 "session": mapping[situation_id]["session"]})

    summary = {
        "seed": SEED,
        "bootstrap": BOOTSTRAP,
        "criteria": {
            "subitem_alpha": SUBITEM_ALPHA,
            "subitem_count": SUBITEM_COUNT,
            "subitem_alpha_bonferroni": round(sign_alpha, 6),
            "heldout_select_p": SELECT_P,
            "heldout_test_p": HELDOUT_P,
            "heldout_rounds": HELDOUT_ROUNDS,
            "heldout_required_rate": HELDOUT_RATE,
        },
        "counts_recompute_mismatch": recompute_gap,
        "strata": {
            "all_pairs": len(pairs),
            "action_differ": len(differ),
            "action_same": len(same),
            "action_count_differs": len(length_differs),
            "sessions": len({entry["session"] for entry in mapping.values()}),
            "weak_session_matches": sum(1 for entry in mapping.values() if entry["match_chars"] < 30),
            "confident_pairs": len(confident),
        },
        "subitems": table,
        "within_pair_offset": offsets,
        "heldout": {
            "rounds": len(rounds),
            "rounds_with_candidate": len(valid),
            "passed": successes,
            "rate": round(successes / max(1, len(rounds)), 4),
            "confident_pairs_only": {"rounds": len(rounds_confident), "passed": successes_confident,
                                     "rate": round(successes_confident / max(1, len(rounds_confident)), 4)},
            "detail": rounds,
        },
        "judge_out_totals": {**judged, "action_differ_subset": win_share(judged_differ)},
        "judged_higher": {
            "counts_composite_action_differ": win_share(composite_diffs),
            "judged_composite_action_differ": win_share(judged_differ),
        },
        "selected_in_heldout": {
            "rounds": len(selected_names),
            "subitems": sorted(set(selected_names)),
            "signal_pairs": signal_pairs,
            "signal_sessions": sorted({entry["session"] for entry in signal_pairs}),
            "test_halves": [item["test_stats"] for item in rounds if item.get("selected")],
        },
        "discriminating_subitems": discriminating,
        "verdict": verdict,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n",
                                      encoding="utf-8")
    (OUT / "sessions.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=1) + "\n",
                                       encoding="utf-8")

    print(f"动作不同 {len(differ)} / 动作相同 {len(same)} / 共 {len(pairs)}；"
          f"计数的复算不一致 {recompute_gap} 条")
    print(f"{'子项':34s} {'n':>4s} {'带法':>6s} {'不带法':>6s} {'δ':>7s} {'95%区间':>17s} "
          f"{'胜/负':>7s} {'符号p':>9s}")
    for name, block in table.items():
        stats = block["action_differ"]
        if not stats.get("n"):
            print(f"{name:34s} {0:4d}  —— 这个子项在分层里没有可比的对")
            continue
        print(f"{name:34s} {stats['n']:4d} {stats['chosen_mean']:6.3f} {stats['rejected_mean']:6.3f} "
              f"{stats['delta']:+7.3f} [{stats['delta_ci95'][0]:+.3f},{stats['delta_ci95'][1]:+.3f}] "
              f"{stats['direction_consistent']:>7s} {stats['sign_test_p']:9.4f}")
    print(f"\n一对之内两向抵消：{offsets['with_both_directions']}/{offsets['pairs']}；"
          f"只有带法更好的子项 {offsets['chosen_only']}，只有不带法更好 "
          f"{offsets['rejected_only']}，都没有 {offsets['neither']}")
    print(f"留出：{len(rounds)} 轮，有子项达标 {len(valid)} 轮，测试半通过 {successes} 轮"
          f"（{summary['heldout']['rate']:.3f}，门槛 {HELDOUT_RATE}）；"
          f"只用强匹配会话 {successes_confident}/{len(rounds_confident)}")
    counts_share = summary["judged_higher"]["counts_composite_action_differ"]
    judged_share = summary["judged_higher"]["judged_composite_action_differ"]
    print(f"带法被判更高的比例（动作不同的对）：可判子级合成分 {counts_share['share']} "
          f"{counts_share['share_ci95']}（{counts_share['wins']}胜/{counts_share['losses']}负/"
          f"{counts_share['ties']}平）；评委合成分 {judged_share['share']} {judged_share['share_ci95']}"
          f"（{judged_share['wins']}胜/{judged_share['losses']}负/{judged_share['ties']}平）")
    print(f"达标子项（Bonferroni {sign_alpha:.4f}）：{discriminating or '无'}")
    print(f"结论：{verdict}")


if __name__ == "__main__":
    main()
