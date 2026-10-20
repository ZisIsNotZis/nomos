#!/usr/bin/env python3
"""分辨力统计：把 eval/judge.py 落盘的判读算成"带法 vs 不带法"的差、噪声与不可能性。

判据在跑之前就写死在这里（见 CRITERIA），跑完不改。输入 evidence/rubric/judge-out.jsonl，
输出 evidence/rubric/summary.json 和终端表。

判据（四个维度与合成分各判一次，全部通过才算"尺子能分开"）：
  差值方向   带法一侧的均值减不带法一侧的均值 δ > 0。
  区间       对处境做 10000 次自助重抽，δ 的 95% 区间下界 > 0。
  稳定       逐对比较里带法赢的处境占多数，双侧符号检验 p < 0.01。
  大于噪声   δ 大于同一条回答判三次的项内标准差 σ_repeat。
"""

import json
import math
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import judge  # noqa: E402  数数规则与合成只此一份
DEFAULT_DIR = REPO / "evidence" / "rubric"
JUDGE_ROWS = DEFAULT_DIR / "judge-out.jsonl"
SUMMARY = DEFAULT_DIR / "summary.json"

DIMENSIONS = ("phase", "evidence", "question", "delivery")
TARGETS = DIMENSIONS + ("total",)
SEED = 20261102
BOOTSTRAP = 10000
SIGN_P = 0.01


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def value(row, target):
    score = row["score"]
    return score["total"] if target == "total" else score["dimensions"][target]


def attach_scores(rows):
    """用当前判据重算每条判读的分数，并核对与判读当时写入的值一致。

    没有条件答案的行来自整体等级版，它按当时写入的维度分统计，重算不了的记 gap 1.0。
    """
    pairs = {row["situation_id"]: row for row in judge.load_pairs()}
    worst, recomputed = 0.0, 0
    for row in rows:
        if "conditions" not in row:
            row["score"] = {"dimensions": row["dimensions"], "total": row["total"]}
            continue
        recomputed += 1
        pair = pairs[row["situation_id"]]
        answer = pair[row["side"]] if row["kind"] == "pair" else judge.degraded(pair["chosen"])
        score = judge.score_answer(judge.count_checks(pair, answer), row["conditions"])
        row["score"] = score
        if "dimensions" in row:
            worst = max(worst, max(abs(score["dimensions"][name] - row["dimensions"][name])
                                   for name in DIMENSIONS))
            worst = max(worst, abs(score["total"] - row["total"]))
    return worst if recomputed else None


def sign_test(wins, losses):
    n = wins + losses
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(max(wins, losses), n + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def bootstrap_ci(diffs, rng):
    means = []
    for _ in range(BOOTSTRAP):
        sample = [diffs[rng.randrange(len(diffs))] for _ in range(len(diffs))]
        means.append(statistics.fmean(sample))
    means.sort()
    return means[int(0.025 * BOOTSTRAP)], means[int(0.975 * BOOTSTRAP) - 1]


def sign_flip_p(diffs, rng, observed, rounds=20000):
    extreme = 0
    for _ in range(rounds):
        total = sum(d if rng.random() < 0.5 else -d for d in diffs)
        if abs(total / len(diffs)) >= abs(observed) - 1e-12:
            extreme += 1
    return (extreme + 1) / (rounds + 1)


def pooled_repeat_sd(rows, target, draws):
    """同一回答判三次的项内合并标准差。"""
    by_answer = {}
    for row in rows:
        if row["kind"] != "pair":
            continue
        by_answer.setdefault((row["situation_id"], row["side"]), []).append(value(row, target))
    residuals = []
    for values in by_answer.values():
        if len(values) < 2:
            continue
        mean = statistics.fmean(values)
        residuals.extend((item - mean) ** 2 for item in values)
    dof = len(by_answer) * (draws - 1)
    return math.sqrt(sum(residuals) / dof), len(by_answer)


def felt_disagreement(rows):
    """同一回答判三次，感觉子级的答案不完全一致的比例；按条件与按维度。"""
    conditions, shares, totals = {}, {}, {}
    for row in rows:
        if row["kind"] != "pair":
            continue
        key = (row["situation_id"], row["side"])
        legacy = "conditions" not in row
        for dimension in DIMENSIONS:
            if legacy:
                shares.setdefault((dimension, key), []).append(row["felt"][dimension]["level"])
            else:
                share = row["felt_share"][dimension]
                if share is not None:
                    shares.setdefault((dimension, key), []).append(share)
                for name, item in row["conditions"][dimension].items():
                    conditions.setdefault((dimension, name, key), []).append(item["answer"])
        totals.setdefault(key, []).append(row["total"])
    condition_rates = {}
    for (dimension, name, key), values in conditions.items():
        condition_rates.setdefault((dimension, name), []).append(values)
    dimension_rates = {}
    for (dimension, key), values in shares.items():
        dimension_rates.setdefault(dimension, []).append(values)
    out = {"conditions": {}, "dimensions": {}, "total": None}
    for (dimension, name), groups in sorted(condition_rates.items()):
        varied = sum(1 for values in groups if len(set(values)) > 1)
        out["conditions"][f"{dimension}.{name}"] = round(varied / len(groups), 4)
    for dimension in DIMENSIONS:
        groups = dimension_rates[dimension]
        varied = sum(1 for values in groups if len(set(values)) > 1)
        out["dimensions"][dimension] = round(varied / len(groups), 4)
    varied = sum(1 for values in totals.values() if len(set(values)) > 1)
    out["total"] = round(varied / len(totals), 4)
    return out


def condition_summary(rows):
    """每条感觉子级条件在两侧的"是"占比与配对符号检验。整体等级版没有条件，返回空。"""
    out = {}
    if any("conditions" not in row for row in rows):
        return out
    pair_ids = sorted({row["situation_id"] for row in rows if row["kind"] == "pair"})
    for dimension in DIMENSIONS:
        for name in rows[0]["conditions"][dimension]:
            rates = {"chosen": [], "rejected": []}
            for situation_id in pair_ids:
                for side in ("chosen", "rejected"):
                    values = [row["conditions"][dimension][name]["answer"] for row in rows
                              if row["kind"] == "pair" and row["situation_id"] == situation_id
                              and row["side"] == side]
                    applicable = [value for value in values if value != "不适用"]
                    if applicable:
                        rates[side].append(sum(1 for value in applicable if value == "是") / len(applicable))
            diffs = [c - r for c, r in zip(rates["chosen"], rates["rejected"])]
            wins = sum(1 for d in diffs if d > 1e-9)
            losses = sum(1 for d in diffs if d < -1e-9)
            out[f"{dimension}.{name}"] = {
                "chosen_yes": round(statistics.fmean(rates["chosen"]), 3) if rates["chosen"] else None,
                "rejected_yes": round(statistics.fmean(rates["rejected"]), 3) if rates["rejected"] else None,
                "win_loss": f"{wins}/{losses}",
                "sign_test_p": round(sign_test(wins, losses), 4),
            }
    return out


def analyse():
    rows = load_jsonl(JUDGE_ROWS)
    rescore_gap = attach_scores(rows)
    draws = max(row["draw"] for row in rows)
    by_answer = {}
    for row in rows:
        by_answer.setdefault((row["situation_id"], row["side"], row["kind"]), []).append(row)
    pair_ids = sorted({row["situation_id"] for row in rows if row["kind"] == "pair"})
    rng = random.Random(SEED)

    results = {}
    for target in TARGETS:
        diffs, chosen_means, rejected_means = [], [], []
        for situation_id in pair_ids:
            chosen = by_answer.get((situation_id, "chosen", "pair"))
            rejected = by_answer.get((situation_id, "rejected", "pair"))
            if not chosen or not rejected:
                continue
            chosen_mean = statistics.fmean(value(row, target) for row in chosen)
            rejected_mean = statistics.fmean(value(row, target) for row in rejected)
            chosen_means.append(chosen_mean)
            rejected_means.append(rejected_mean)
            diffs.append(chosen_mean - rejected_mean)
        delta = statistics.fmean(diffs)
        within = [d for d in diffs if abs(d) > 1e-9]
        wins = sum(1 for d in within if d > 0)
        losses = sum(1 for d in within if d < 0)
        low, high = bootstrap_ci(diffs, rng)
        repeat_sd, answer_count = pooled_repeat_sd(rows, target, draws)
        sample_sd = statistics.stdev(diffs) if len(diffs) > 1 else float("nan")
        results[target] = {
            "n_pairs": len(diffs),
            "chosen_mean": round(statistics.fmean(chosen_means), 4),
            "rejected_mean": round(statistics.fmean(rejected_means), 4),
            "delta": round(delta, 4),
            "delta_ci95": [round(low, 4), round(high, 4)],
            "dominance": f"{wins}/{wins + losses}" if wins + losses else "0/0",
            "dominance_rate": round(wins / (wins + losses), 4) if wins + losses else None,
            "sign_test_p": round(sign_test(wins, losses), 6),
            "sign_flip_p": round(sign_flip_p(diffs, rng, delta), 6),
            "repeat_sd": round(repeat_sd, 4),
            "sample_sd_of_diff": round(sample_sd, 4),
            "se": round(sample_sd / math.sqrt(len(diffs)), 4),
            "repeat_answers": answer_count,
            "delta_over_repeat_sd": round(delta / repeat_sd, 3) if repeat_sd else None,
        }

    criteria = {}
    for target in TARGETS:
        item = results[target]
        checks = {
            "direction": item["delta"] > 0,
            "interval": item["delta_ci95"][0] > 0,
            "stable": (item["dominance_rate"] or 0) > 0.5 and item["sign_test_p"] < SIGN_P,
            "above_noise": item["delta"] > item["repeat_sd"],
        }
        criteria[target] = {"checks": checks, "pass": all(checks.values())}

    control = {}
    control_ids = sorted({row["situation_id"] for row in rows if row["kind"] == "control"})
    if control_ids:
        for target in TARGETS:
            deltas = []
            for situation_id in control_ids:
                base = by_answer.get((situation_id, "chosen", "pair"))
                worse = by_answer.get((situation_id, "degraded", "control"))
                if not base or not worse:
                    continue
                deltas.append(statistics.fmean(value(row, target) for row in worse)
                              - statistics.fmean(value(row, target) for row in base))
            control[target] = {"n": len(deltas), "mean_delta": round(statistics.fmean(deltas), 4),
                               "worse_share": round(sum(1 for d in deltas if d < 0) / len(deltas), 4)}

    summary = {
        "draws": draws, "bootstrap": BOOTSTRAP, "criteria_significance": SIGN_P,
        "rescore_max_gap": None if rescore_gap is None else round(rescore_gap, 6),
        "results": results, "criteria": criteria,
        "all_pass": all(item["pass"] for item in criteria.values()),
        "control_degraded": control,
        "felt_disagreement_rate": felt_disagreement(rows),
        "condition_summary": condition_summary(rows),
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return summary


def main():
    global JUDGE_ROWS, SUMMARY
    if "--dir" in sys.argv:
        directory = Path(sys.argv[sys.argv.index("--dir") + 1])
        JUDGE_ROWS = directory / "judge-out.jsonl"
        SUMMARY = directory / "summary.json"
    summary = analyse()
    print(f"{'目标':10s} {'带法':>7s} {'不带法':>7s} {'δ':>7s} {'95%区间':>17s} "
          f"{'胜场':>7s} {'符号p':>9s} {'σ_repeat':>9s} {'通过':>4s}")
    for target in TARGETS:
        item = summary["results"][target]
        print(f"{target:10s} {item['chosen_mean']:7.3f} {item['rejected_mean']:7.3f} "
              f"{item['delta']:7.3f} [{item['delta_ci95'][0]:6.3f},{item['delta_ci95'][1]:6.3f}] "
              f"{item['dominance']:>7s} {item['sign_test_p']:9.4f} {item['repeat_sd']:9.3f} "
              f"{'是' if summary['criteria'][target]['pass'] else '否':>4s}")
    if summary["control_degraded"]:
        print("\n已知更差的对照（追加一条用户没要求的强制推送）：")
        for target, item in summary["control_degraded"].items():
            print(f"  {target:10s} 平均变化 {item['mean_delta']:+.3f}，变差比例 {item['worse_share']:.2f}")
    print(f"\n三次判读的项内不一致率（维度）：{summary['felt_disagreement_rate']['dimensions']}")
    print(f"三次判读的项内不一致率（合成分）：{summary['felt_disagreement_rate']['total']}")
    print(f"全部判据通过：{summary['all_pass']}")


if __name__ == "__main__":
    main()
