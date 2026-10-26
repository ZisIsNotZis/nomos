#!/usr/bin/env python3
"""Split the landed three-point measurement into situations the adapter trained on and
situations held out by session, and recompute the same paired read on each side.

Why this exists: `evidence/measure/answers.jsonl` was generated on the same 242 situations
that produced `data/sft.jsonl`, and the report's headline (post_mean 0.0968, X 0.0948) is
computed over all of them — of which 191 situations are in the training split and 51 are in
the validation split. Without this split the headline cannot be told apart from memorisation.

The per-split numbers are computed with the same resampling code and the same seeds as
`scripts/measure_actions.py --analyse`, so the all-situation block reproduces that file's
headline field by field (asserted, not assumed).

Read-only on inputs: reads `data/sft-{train,val}.jsonl`, `evidence/measure/per-situation.jsonl`
and `evidence/measure/summary.json`, writes `evidence/measure/seen-heldout.json`. Never calls a
model, never touches the GPU.

Usage:
  python3 scripts/measure_split.py            # recompute and write evidence/measure/seen-heldout.json
  python3 scripts/measure_split.py --check    # recompute and compare with that file, no write
"""

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import measure_actions as main_measure  # noqa: E402  (same resampling code and seeds)

EVIDENCE = REPO / "evidence" / "measure"
PER_SITUATION = EVIDENCE / "per-situation.jsonl"
SUMMARY = EVIDENCE / "summary.json"
TRAIN = REPO / "data" / "sft-train.jsonl"
VAL = REPO / "data" / "sft-val.jsonl"
OUT = EVIDENCE / "seen-heldout.json"

SEED = main_measure.SEED
DRAWS = main_measure.DRAWS


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def block(per_situation, situations):
    """One split's read, with the main script's functions and seeds."""
    used = [row for row in per_situation if row["reference_usable"] and row["situation"] in situations]
    paired = [row for row in used if row["base"] is not None and row["post"] is not None]
    if len(paired) < 2:
        return {"situations_paired": len(paired), "status": "too_few_situations"}
    base_values = [row["base"] for row in used if row["base"] is not None]
    post_values = [row["post"] for row in used if row["post"] is not None]
    base_paired = main_measure.mean([row["base"] for row in paired])
    post_paired = main_measure.mean([row["post"] for row in paired])
    headroom = 1.0 - base_paired
    if headroom <= 0.0:
        x, x_status = None, "undefined_no_headroom"
    else:
        x, x_status = (post_paired - base_paired) / headroom, "defined"
    bootstrap = main_measure.bootstrap_pair(paired, SEED + 1)
    parts = main_measure.decomposition(paired)
    parts.update(main_measure.bootstrap_decomposition(paired, SEED + 10))
    base_actions = [row["base_emits"] / DRAWS for row in used if row["base_emits"] is not None]
    post_actions = [row["post_emits"] / DRAWS for row in used if row["post_emits"] is not None]
    return {
        "situations_paired": len(paired),
        "status": "defined",
        "base_mean": main_measure.mean(base_values),
        "base_ci": main_measure.bootstrap_mean(base_values, SEED + 2),
        "post_mean": main_measure.mean(post_values),
        "post_ci": main_measure.bootstrap_mean(post_values, SEED + 3),
        "delta": parts["delta"],
        "delta_ci": parts["delta_ci"],
        "decomposition": {
            "format_part": parts["format_part"],
            "decision_part": parts["decision_part"],
            "interaction_part": parts["interaction_part"],
            "format_share": parts["format_share"],
        },
        "format_part_ci": parts["format_part_ci"],
        "decision_part_ci": parts["decision_part_ci"],
        "X": x,
        "X_status": x_status,
        "X_ci": bootstrap["X_ci"],
        "X_replicates_undefined": bootstrap["X_replicates_undefined"],
        "countable_control": {
            "base_emits_action": main_measure.mean(base_actions),
            "post_emits_action": main_measure.mean(post_actions),
        },
    }


def build():
    per_situation = load_jsonl(PER_SITUATION)
    train_ids = {row["situation_id"] for row in load_jsonl(TRAIN)}
    val_ids = {row["situation_id"] for row in load_jsonl(VAL)}
    if train_ids & val_ids:
        raise SystemExit("train and validation situation ids overlap; the session split is broken")
    measured = {row["situation"] for row in per_situation}
    if not (train_ids | val_ids) <= measured:
        missing = sorted((train_ids | val_ids) - measured)
        raise SystemExit(f"{len(missing)} SFT situations have no measurement row, e.g. {missing[:3]}")
    if measured - (train_ids | val_ids):
        raise SystemExit("measurement has situations outside the SFT data; the premise of this split is wrong")

    payload = {
        "what": (
            "三点测量的主指标按「适配器训练时见过 / 按会话留出」拆开：与 --analyse 同一套重采样代码、"
            "同一组种子，重抽单位是处境；子集只保留参照物可用且两侧齐全的处境"
        ),
        "source": {
            "per_situation": str(PER_SITUATION.relative_to(REPO)),
            "summary": str(SUMMARY.relative_to(REPO)),
            "train": str(TRAIN.relative_to(REPO)),
            "val": str(VAL.relative_to(REPO)),
        },
        "situation_counts": {
            "total": len(measured),
            "seen_in_training": len(train_ids),
            "held_out_by_session": len(val_ids),
        },
        "paired_all": block(per_situation, measured),
        "paired_seen": block(per_situation, train_ids),
        "paired_held_out": block(per_situation, val_ids),
        "caveat": (
            "两半都是同一批落盘回答的子集，不是两次独立读数；held-out 一侧的配对处境少，区间宽，"
            "点估计只能读方向。held-out 是按会话切分的（12 个会话），不是随机 20% 处境。"
        ),
    }
    # The all-situation block must reproduce the landed headline, else this split is a second ruler.
    landed = json.loads(SUMMARY.read_text(encoding="utf-8"))
    checks = [
        ("situations_paired", landed["situations_paired"]),
        ("base_mean", landed["base_mean"]),
        ("post_mean", landed["post_mean"]),
        ("base_ci", landed["base_ci"]),
        ("post_ci", landed["post_ci"]),
        ("X", landed["X"]),
        ("X_ci", landed["X_ci"]),
        ("delta", landed["decomposition"]["delta"]),
        ("delta_ci", landed["decomposition"]["delta_ci"]),
        ("countable_control", {
            "base_emits_action": landed["countable_control"]["base_emits_action"],
            "post_emits_action": landed["countable_control"]["post_emits_action"],
        }),
    ]
    for key, expected in checks:
        got = payload["paired_all"][key] if key != "countable_control" else {
            "base_emits_action": payload["paired_all"]["countable_control"]["base_emits_action"],
            "post_emits_action": payload["paired_all"]["countable_control"]["post_emits_action"],
        }
        if isinstance(expected, float) and isinstance(got, float):
            same = abs(expected - got) < 1e-12
        else:
            same = expected == got
        if not same:
            raise SystemExit(f"paired_all.{key} = {got!r} but summary.json says {expected!r}; the split would be a second ruler")
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="compare against the landed file instead of writing")
    parser.add_argument("--per-situation", default=None, help="默认 evidence/measure/per-situation.jsonl")
    parser.add_argument("--summary", default=None, help="默认 evidence/measure/summary.json")
    parser.add_argument("--out", default=None, help="默认 evidence/measure/seen-heldout.json")
    args = parser.parse_args()
    global PER_SITUATION, SUMMARY, OUT
    if args.per_situation:
        PER_SITUATION = Path(args.per_situation).resolve()
    if args.summary:
        SUMMARY = Path(args.summary).resolve()
    if args.out:
        OUT = Path(args.out).resolve()
    payload = build()
    if args.check:
        if not OUT.exists():
            raise SystemExit(f"{OUT} 不存在；先跑不带 --check 的那一次")
        landed = json.loads(OUT.read_text(encoding="utf-8"))
        differing = [key for key in payload if landed.get(key) != payload[key]]
        if differing:
            raise SystemExit(f"与落盘件不一致：{differing}")
        print(f"落盘件逐字段相同，且 paired_all 与 summary.json 的头行数字一致：{OUT}")
        return
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for name in ("paired_all", "paired_seen", "paired_held_out"):
        b = payload[name]
        print(
            "{:15s} n={:3d} base={:.4f} post={:.4f} delta={:+.4f} ci95=[{:+.4f},{:+.4f}] "
            "X={:<9} emits {:.3f}->{:.3f}".format(
                name,
                b["situations_paired"],
                b["base_mean"],
                b["post_mean"],
                b["delta"],
                b["delta_ci"][0],
                b["delta_ci"][1],
                "undefined" if b["X"] is None else f"{b['X']:.4f}",
                b["countable_control"]["base_emits_action"],
                b["countable_control"]["post_emits_action"],
            )
        )
    print(f"situation_counts {payload['situation_counts']} -> {OUT}")


if __name__ == "__main__":
    main()
