#!/usr/bin/env python3
"""Recompute the IFEval base-vs-adapter comparison on Google's official ruler.

This is a reference-ruler check, not a new benchmark. It answers one question: are the
stored numbers a property of the models or of `scripts/bench_suites.py`'s own checkers?

Three rulers are run on the same 590 stored outputs (295 base, 295 adapter):

- `strict`: `instruction_following_eval.evaluation_lib.test_instruction_following_strict`
            at commit e6890f85757dd84e27ca6df2dd30651dafad28e0 (vendored unmodified in
            `vendor/instruction_following_eval/`).
- `lax`:    the same file's `test_instruction_following_loose`, the official upper bound.
- `ours`:   `scripts/bench_suites.check_ifeval`, imported, never copied.

The paired interval is `scripts/resample_actions.bootstrap_diff` and exact McNemar is
`evidence/benchmark/analyse_paired.mcnemar_exact`, both imported, so the only thing that
changes between a row and the stored evidence is the ruler.

Usage:
  uv run --no-project --with nltk --with langdetect --with immutabledict --with absl-py \
      python3 evidence/benchmark/official/grade_official.py

Exit 0 writes `evidence/benchmark/official/official-ifeval.json`. A non-zero exit means an
input invariant failed (id order, unknown instruction id, or our ruler not reproducing the
stored per-instruction verdicts) and no JSON was written.
"""

import hashlib
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE
while not os.path.exists(os.path.join(ROOT, "data", "bench", "ifeval.jsonl")):
    parent = os.path.dirname(ROOT)
    if parent == ROOT:
        raise SystemExit(f"no repo root above {HERE} (looked for data/bench/ifeval.jsonl)")
    ROOT = parent
VENDOR = os.path.join(HERE, "vendor")
COMMIT = "e6890f85757dd84e27ca6df2dd30651dafad28e0"
REPO = "google-research/google-research"
VENDOR_DIR = "instruction_following_eval"
RAW = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{VENDOR_DIR}"
VENDORED_FILES = (
    "instructions.py",
    "instructions_util.py",
    "instructions_registry.py",
    "evaluation_lib.py",
    "README.md",
    "requirements.txt",
)
JSONL = os.path.join(ROOT, "data", "bench", "ifeval.jsonl")
BASE = os.path.join(ROOT, "evidence", "benchmark", "base-ifeval.json")
ADAPTER = os.path.join(ROOT, "evidence", "benchmark", "adapter-ifeval.json")
STORED_PAIRED = os.path.join(ROOT, "evidence", "benchmark", "paired-ifeval.json")
OUT = os.path.join(HERE, "official-ifeval.json")
SCRIPTS = os.path.join(ROOT, "scripts")

sys.path.insert(0, VENDOR)
sys.path.insert(0, SCRIPTS)

from instruction_following_eval import (  # noqa: E402  (vendored, unmodified)
    evaluation_lib,
    instructions_registry,
    instructions_util,
)
import bench_suites  # noqa: E402  (the tree's own ruler, imported not copied)
import resample_actions  # noqa: E402  (the tree's one paired interval)

# The official grader is not reproducible as shipped. `instructions.py` asks `langdetect`
# whether the response is English in the two `change_case` checkers, and langdetect's
# `DetectorFactory.seed` defaults to None, i.e. its detector draws from the global `random`
# state. Two runs of this file therefore disagreed on one verdict (adapter 160 vs 159 of
# 295) before this line existed. Pinning the seed is the documented way to make langdetect
# deterministic; it changes no checker logic. `random.seed` covers the same module's
# `random.randint`/`random.choice` fallbacks, which fire only when an item's kwargs are
# incomplete (none in the frozen sample are).
import random  # noqa: E402
import langdetect  # noqa: E402

random.seed(0)
langdetect.DetectorFactory.seed = 0


WORDS_ID = "length_constraints:number_words"
COMMA_ID = "punctuation:no_comma"


def fail(message):
    raise SystemExit(f"FATAL: {message}")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ANALYSE = load_module("analyse_paired",
                      os.path.join(ROOT, "evidence", "benchmark", "analyse_paired.py"))


def sha256_of(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ------------------------------------------------------------------ inputs

def load_items():
    items = []
    with open(JSONL, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                items.append(json.loads(line))
    return items


def load_records(path, label):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check_order(items, base, adapter):
    """The jsonl, the base records and the adapter records must be one item order."""
    item_ids = [it["id"] for it in items]
    base_ids = [r["id"] for r in base["records"]]
    adapter_ids = [r["id"] for r in adapter["records"]]
    if base_ids != adapter_ids:
        fail(f"base/adapter ids differ or are out of order (base[:3]={base_ids[:3]} "
             f"adapter[:3]={adapter_ids[:3]})")
    if base_ids != item_ids:
        differing = [i for i, (a, b) in enumerate(zip(base_ids, item_ids)) if a != b]
        fail(f"record ids are not the jsonl order: {len(differing)} positions differ, "
             f"first at index {differing[0] if differing else None}; "
             f"len records={len(base_ids)} len jsonl={len(item_ids)}")
    return item_ids


def check_instruction_ids(items):
    known = set(instructions_registry.INSTRUCTION_DICT)
    missing = sorted({iid for it in items for iid in it["instruction_id_list"]} - known)
    if missing:
        fail(f"{len(missing)} instruction ids are absent from the official INSTRUCTION_DICT: {missing}")
    return known


# ------------------------------------------------------------- official ruler

def _official_input(item, instruction_ids, kwargs):
    return evaluation_lib.InputExample(
        key=item["id"],
        instruction_id_list=list(instruction_ids),
        prompt=item["prompt"],
        kwargs=list(kwargs),
    )


def official_slots(item, output, rule):
    """Per-slot official verdicts for one response, plus any checker that raised.

    The official function is called once on the whole instruction list, which is how the
    official grader aggregates. If it raises, the same official function is called again on
    one-instruction inputs so the raising checker can be named; that slot is recorded False
    and counted in `official_error`. No checker logic is written here.
    """
    fn = (evaluation_lib.test_instruction_following_strict if rule == "strict"
          else evaluation_lib.test_instruction_following_loose)
    responses = {item["prompt"]: output}
    whole = _official_input(item, item["instruction_id_list"], item["kwargs"])
    try:
        return list(fn(whole, responses).follow_instruction_list), []
    except Exception as exc:  # noqa: BLE001  (any checker failure is data, not a crash)
        first = f"{type(exc).__name__}: {exc}".replace("\n", " ")[:200]
    slots, errors = [], []
    for index, (iid, kw) in enumerate(zip(item["instruction_id_list"], item["kwargs"])):
        single = _official_input(item, [iid], [kw])
        try:
            slots.append(bool(fn(single, responses).follow_instruction_list[0]))
        except Exception as exc:  # noqa: BLE001
            slots.append(False)
            errors.append({"id": item["id"], "slot": index, "checker": iid,
                           "error": f"{type(exc).__name__}: {exc}".replace("\n", " ")[:200],
                           "whole_item_error": first})
    return slots, errors


# ----------------------------------------------------------- the named checkers

def our_word_count(text):
    return len(bench_suites._words(text))  # the tree's own splitter, imported


def official_word_count(text):
    return instructions_util.count_words(text)


def _collapse(text):
    return re.sub(r"\s+", " ", text).strip()


def deciding_snippet(text, kind, limit=200):
    """Quote the stretch of `output` that decides the two rulers' answer.

    For word counts it is the first window where the whitespace split (`ours`) and the
    `\\w+` tokenisation (`official`) stop agreeing; when they agree span for span, the
    counts differ only in total and the head of the response is quoted. For commas it is
    the window around the first comma, which is the character the `no_comma` check looks at.
    """
    if kind == "comma":
        at = text.find(",")
        if at < 0:
            return {"snippet": _collapse(text)[:limit], "snippet_note": "no comma in the response"}
        low, high = max(0, at - 80), min(len(text), at + 120)
        return {"snippet": _collapse(text[low:high]), "snippet_note": "window around the first comma"}
    ours_spans = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    official_spans = [(m.start(), m.end()) for m in re.finditer(r"\w+", text)]
    if ours_spans == official_spans:
        return {"snippet": _collapse(text)[:limit],
                "snippet_note": "both rulers tokenise identically; the counts differ only in total"}
    at = next((i for i, (a, b) in enumerate(zip(ours_spans, official_spans)) if a != b),
              min(len(ours_spans), len(official_spans)))
    start = ours_spans[max(0, at - 3)][0] if ours_spans else 0
    end = official_spans[min(len(official_spans) - 1, at + 1)][1] if official_spans else len(text)
    window = text[start:min(end, start + limit)]
    return {"snippet": _collapse(window),
            "snippet_note": f"first token divergence at span {at} of {len(ours_spans)} word / "
                            f"{len(official_spans)} \\w+ tokens"}


# ------------------------------------------------------------------ statistics

def paired_block(base_flags, adapter_flags, ids):
    n = len(ids)
    b_correct, a_correct = sum(base_flags), sum(adapter_flags)
    drops = [i for i in range(n) if base_flags[i] and not adapter_flags[i]]
    gains = [i for i in range(n) if not base_flags[i] and adapter_flags[i]]
    low, high = resample_actions.bootstrap_diff(adapter_flags, base_flags)
    return {
        "n": n,
        "base": {
            "correct": b_correct,
            "accuracy": b_correct / n,
            "ci95_wilson": list(bench_suites.wilson_interval(b_correct, n)),
        },
        "adapter": {
            "correct": a_correct,
            "accuracy": a_correct / n,
            "ci95_wilson": list(bench_suites.wilson_interval(a_correct, n)),
        },
        "delta_adapter_minus_base": (a_correct - b_correct) / n,
        "delta_pp": 100 * (a_correct - b_correct) / n,
        "delta_ci95_paired_bootstrap": [low, high],
        "delta_ci95_paired_bootstrap_pp": [100 * low, 100 * high],
        "paired": {
            "drops": len(drops),
            "gains": len(gains),
            "drop_ids": [ids[i] for i in drops],
            "gain_ids": [ids[i] for i in gains],
            "unchanged": n - len(drops) - len(gains),
            "mcnemar_exact_p": ANALYSE.mcnemar_exact(len(drops), len(gains)),
        },
        "bootstrap": {"resamples": resample_actions.BOOTSTRAP,
                      "seed": resample_actions.SEED + 1,
                      "implementation": "scripts/resample_actions.py:bootstrap_diff"},
    }


# ----------------------------------------------------------------------- main

def main():
    items = load_items()
    base = load_records(BASE, "base")
    adapter = load_records(ADAPTER, "adapter")
    ids = check_order(items, base, adapter)
    known = check_instruction_ids(items)
    n = len(items)

    # Per record: the official slot verdicts under both rules, our slot verdicts, and the
    # stored verdicts our ruler is supposed to reproduce.
    per_record = {}
    official_errors = {"strict": [], "lax": []}
    ours_mismatches = []
    for side, payload in (("base", base), ("adapter", adapter)):
        for item, rec in zip(items, payload["records"]):
            output = rec["output"]
            strict_slots, strict_err = official_slots(item, output, "strict")
            lax_slots, lax_err = official_slots(item, output, "lax")
            official_errors["strict"].extend({**e, "model": side} for e in strict_err)
            official_errors["lax"].extend({**e, "model": side} for e in lax_err)
            our_slots = [bool(x) for x in bench_suites.check_ifeval(item, output)]
            our_correct = bool(our_slots) and all(our_slots)
            # Our ruler must reproduce the stored record exactly; a mismatch is reported,
            # never corrected in place.
            if our_correct != bool(rec["correct"]):
                ours_mismatches.append({"side": side, "id": rec["id"], "field": "correct",
                                        "stored": rec["correct"], "recomputed": our_correct})
            stored_map = rec.get("per_instruction") or {}
            recomputed_map = dict(zip(item["instruction_id_list"], our_slots))
            if stored_map != recomputed_map:
                differing = {k: [stored_map.get(k), recomputed_map.get(k)]
                             for k in set(stored_map) | set(recomputed_map)
                             if stored_map.get(k) != recomputed_map.get(k)}
                ours_mismatches.append({"side": side, "id": rec["id"],
                                        "field": "per_instruction", "stored_vs_recomputed": differing})
            per_record[(side, rec["id"])] = {
                "strict": strict_slots,
                "lax": lax_slots,
                "ours": our_slots,
                "ids": item["instruction_id_list"],
                "output": output,
                "kwargs": item["kwargs"],
                "unscorable": bool(rec["unscorable"]),
            }
    if ours_mismatches:
        fail("our ruler does not reproduce the stored record on "
             f"{len(ours_mismatches)} field(s); first three: {ours_mismatches[:3]}")

    flags_by_rule = {}
    for rule in ("strict", "lax", "ours"):
        flags = {}
        for side in ("base", "adapter"):
            flags[side] = [1 if all(per_record[(side, i)][rule]) else 0 for i in ids]
        flags_by_rule[rule] = flags

    rules = {}
    for rule in ("strict", "lax", "ours"):
        block = paired_block(flags_by_rule[rule]["base"], flags_by_rule[rule]["adapter"], ids)
        for side in ("base", "adapter"):
            block[side]["unscorable"] = sum(per_record[(side, i)]["unscorable"] for i in ids)
            block[side]["official_error_items"] = len({
                e["id"] for e in official_errors.get(rule, []) if e["model"] == side})
        block["official_error"] = {
            "checker_exceptions": len(official_errors.get(rule, [])),
            "detail": official_errors.get(rule, []),
        }
        rules[rule] = block

    # --- item-level disagreement between the official strict ruler and ours
    item_level = {}
    for rule in ("strict", "lax"):
        entry = {}
        for side in ("base", "adapter"):
            ours_pass_official_fail, ours_fail_official_pass, slot_rows = [], [], []
            for i in ids:
                rec = per_record[(side, i)]
                ours_ok = all(rec["ours"])
                off_ok = all(rec[rule])
                if ours_ok and not off_ok:
                    ours_pass_official_fail.append(i)
                elif off_ok and not ours_ok:
                    ours_fail_official_pass.append(i)
                if ours_ok != off_ok:
                    diverging = [name for name, a, b in zip(rec["ids"], rec["ours"], rec[rule]) if a != b]
                    slot_rows.append({"id": i, "ours": ours_ok, "official": off_ok,
                                      "slots_where_they_differ": diverging})
            entry[side] = {
                "ours_pass_official_fail": ours_pass_official_fail,
                "ours_fail_official_pass": ours_fail_official_pass,
                "counts": {"ours_pass_official_fail": len(ours_pass_official_fail),
                           "ours_fail_official_pass": len(ours_fail_official_pass),
                           "total_disagreeing_items": len(ours_pass_official_fail) + len(ours_fail_official_pass)},
                "rows": slot_rows,
            }
        item_level[f"official_{rule}_vs_ours"] = entry

    # --- per-checker disagreement over all 590 records
    by_type = {}
    for side in ("base", "adapter"):
        for i in ids:
            rec = per_record[(side, i)]
            for slot, name in enumerate(rec["ids"]):
                row = by_type.setdefault(name, {
                    "slots": {"base": 0, "adapter": 0, "total": 0},
                    "ours_pass_official_fail": {"base": 0, "adapter": 0, "total": 0},
                    "ours_fail_official_pass": {"base": 0, "adapter": 0, "total": 0},
                    "agree": {"base": 0, "adapter": 0, "total": 0},
                    "ours_pass": {"base": 0, "adapter": 0, "total": 0},
                    "official_pass": {"base": 0, "adapter": 0, "total": 0},
                })
                row["slots"][side] += 1
                row["slots"]["total"] += 1
                a, b = rec["ours"][slot], rec["strict"][slot]
                row["ours_pass"][side] += int(a)
                row["ours_pass"]["total"] += int(a)
                row["official_pass"][side] += int(b)
                row["official_pass"]["total"] += int(b)
                if a and not b:
                    key = "ours_pass_official_fail"
                elif b and not a:
                    key = "ours_fail_official_pass"
                else:
                    key = "agree"
                row[key][side] += 1
                row[key]["total"] += 1
    totals = {
        "slots": {"base": 0, "adapter": 0, "total": 0},
        "ours_pass_official_fail": {"base": 0, "adapter": 0, "total": 0},
        "ours_fail_official_pass": {"base": 0, "adapter": 0, "total": 0},
        "agree": {"base": 0, "adapter": 0, "total": 0},
    }
    for row in by_type.values():
        for key in totals:
            for side in ("base", "adapter", "total"):
                totals[key][side] += row[key][side]
    per_checker = {
        "rule": "strict",
        "records": 2 * n,
        "by_instruction_type": dict(sorted(by_type.items())),
        "totals": totals,
        "types_with_any_disagreement": sorted(
            k for k, v in by_type.items()
            if v["ours_pass_official_fail"]["total"] or v["ours_fail_official_pass"]["total"]),
        "types_with_no_disagreement": sorted(
            k for k, v in by_type.items()
            if not (v["ours_pass_official_fail"]["total"] or v["ours_fail_official_pass"]["total"])),
    }

    # --- named detail for the two instruction types the diagnosis names
    named = {}
    for name, kind in ((WORDS_ID, "words"), (COMMA_ID, "comma")):
        per_rule = {}
        for rule in ("strict", "lax"):
            rows = []
            for side in ("base", "adapter"):
                for i in ids:
                    rec = per_record[(side, i)]
                    for slot, iid in enumerate(rec["ids"]):
                        if iid != name:
                            continue
                        a, b = rec["ours"][slot], rec[rule][slot]
                        if a == b:
                            continue
                        row = {"id": i, "model": side, "slot": slot,
                               "ours_pass": a, "official_pass": b}
                        kw = rec["kwargs"][slot] or {}
                        if kind == "words":
                            row["instruction_args"] = {"relation": kw.get("relation"),
                                                       "num_words": kw.get("num_words")}
                            row["our_word_count"] = our_word_count(rec["output"])
                            row["official_word_count"] = official_word_count(rec["output"])
                        else:
                            row["our_comma_count"] = rec["output"].count(",")
                            row["official_comma_count"] = len(re.findall(r"\,", rec["output"]))
                        row["output_chars"] = len(rec["output"])
                        row.update(deciding_snippet(rec["output"], kind))
                        rows.append(row)
            per_rule[rule] = {
                "disagreeing_slots": len(rows),
                "ours_pass_official_fail": sum(1 for r in rows if r["ours_pass"]),
                "ours_fail_official_pass": sum(1 for r in rows if not r["ours_pass"]),
                "rows": rows,
            }
        named[name] = per_rule

    # --- arithmetic consequence for the stored discordant items
    stored = load_records(STORED_PAIRED, "paired")
    stored_drops = list(stored["paired"]["drop_ids"])
    stored_gains = list(stored["paired"]["gain_ids"])
    if stored_drops != rules["ours"]["paired"]["drop_ids"] or stored_gains != rules["ours"]["paired"]["gain_ids"]:
        fail("our recomputed discordant ids do not match evidence/benchmark/paired-ifeval.json")

    def fate(ids_in):
        """Where each stored discordant item lands on the official strict ruler."""
        out = {"drop": [], "tie": [], "gain": []}
        for i in ids_in:
            b = flags_by_rule["strict"]["base"][ids.index(i)]
            a = flags_by_rule["strict"]["adapter"][ids.index(i)]
            if b and not a:
                out["drop"].append(i)
            elif a and not b:
                out["gain"].append(i)
            else:
                out["tie"].append(i)
        return out

    drop_fate, gain_fate = fate(stored_drops), fate(stored_gains)
    for name, f, want in (("stored_drops", drop_fate, len(stored_drops)),
                          ("stored_gains", gain_fate, len(stored_gains))):
        if len(f["drop"]) + len(f["tie"]) + len(f["gain"]) != want:
            fail(f"{name}: fate partition does not sum to {want}")
    arithmetic = {
        "rule": "strict",
        "stored_drops": {
            "n": len(stored_drops),
            "survive_as_drops": len(drop_fate["drop"]),
            "become_ties": len(drop_fate["tie"]),
            "become_gains": len(drop_fate["gain"]),
            "survive_as_drop_ids": drop_fate["drop"],
            "become_tie_ids": drop_fate["tie"],
            "become_gain_ids": drop_fate["gain"],
        },
        "stored_gains": {
            "n": len(stored_gains),
            "survive_as_gains": len(gain_fate["gain"]),
            "become_ties": len(gain_fate["tie"]),
            "become_drops": len(gain_fate["drop"]),
            "survive_as_gain_ids": gain_fate["gain"],
            "become_tie_ids": gain_fate["tie"],
            "become_drop_ids": gain_fate["drop"],
        },
        "stored_ties_that_flip_on_the_official_ruler": {
            "become_drops": rules["strict"]["paired"]["drops"] - len(drop_fate["drop"]),
            "become_gains": rules["strict"]["paired"]["gains"] - len(gain_fate["gain"]),
        },
        "official_strict_delta_items": rules["strict"]["adapter"]["correct"] - rules["strict"]["base"]["correct"],
        "official_strict_discordant_total": rules["strict"]["paired"]["drops"] + rules["strict"]["paired"]["gains"],
        "stored_discordant_total": len(stored_drops) + len(stored_gains),
    }

    vendored = []
    for name in VENDORED_FILES:
        path = os.path.join(VENDOR, VENDOR_DIR, name)
        if not os.path.exists(path):
            fail(f"vendored file missing: {path}")
        vendored.append({"file": name, "sha256": sha256_of(path), "url": f"{RAW}/{name}"})

    result = {
        "what": ("base-vs-adapter IFEval comparison recomputed on Google's official "
                 "instruction-following graders, with the tree's own ruler as control"),
        "vendored": {"repo": REPO, "commit": COMMIT, "directory": VENDOR_DIR,
                     "local_path": os.path.relpath(os.path.join(VENDOR, VENDOR_DIR), ROOT) + "/",
                     "modified": False, "files": vendored},
        "inputs": {
            "jsonl": "data/bench/ifeval.jsonl",
            "jsonl_sha256": sha256_of(JSONL),
            "base": "evidence/benchmark/base-ifeval.json",
            "base_sha256": sha256_of(BASE),
            "adapter": "evidence/benchmark/adapter-ifeval.json",
            "adapter_sha256": sha256_of(ADAPTER),
            "frozen_sha256": base["frozen_sha256"],
            "record_order_matches_jsonl": True,
            "base_and_adapter_ids_agree": True,
            "instruction_ids_unknown_to_official": [],
            "instruction_types_seen": sorted({t for it in items for t in it["instruction_id_list"]}),
        },
        "n": n,
        "rules": rules,
        "item_level_ruler_disagreement": item_level,
        "per_checker_disagreement": per_checker,
        "named_detail": named,
        "drop_gain_arithmetic": arithmetic,
        "determinism": {
            "langdetect_DetectorFactory_seed": langdetect.DetectorFactory.seed,
            "random_seed": 0,
            "why": ("the vendored change_case checkers call langdetect.detect, whose "
                    "DetectorFactory.seed defaults to None and therefore draws from the "
                    "global random state; unpinned, this file's own two runs disagreed on "
                    "one adapter verdict (160 vs 159 of 295). Which slots flip, measured "
                    "over 9 unpinned processes, is in RUN.md; pinning the seed makes three "
                    "consecutive runs byte-identical"),
            "checkers_that_use_langdetect": [
                "change_case:english_capital",
                "change_case:english_lowercase",
                "language:response_language",
            ],
        },
        "ours_ruler_check": {
            "function": "scripts/bench_suites.py:check_ifeval",
            "records_checked": 2 * n,
            "mismatches": ours_mismatches,
            "reproduces_stored_correct_and_per_instruction": True,
        },
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
        f.write("\n")

    s = rules["strict"]
    print(f"official strict: base {s['base']['correct']}/{n}  adapter {s['adapter']['correct']}/{n}  "
          f"delta {100 * s['delta_adapter_minus_base']:+.1f}pp  "
          f"CI [{100 * s['delta_ci95_paired_bootstrap'][0]:+.1f}, "
          f"{100 * s['delta_ci95_paired_bootstrap'][1]:+.1f}]  "
          f"drops {s['paired']['drops']} gains {s['paired']['gains']}  "
          f"p {s['paired']['mcnemar_exact_p']:.3g}  errors {s['official_error']['checker_exceptions']}")
    l = rules["lax"]
    print(f"official lax   : base {l['base']['correct']}/{n}  adapter {l['adapter']['correct']}/{n}  "
          f"delta {100 * l['delta_adapter_minus_base']:+.1f}pp  "
          f"CI [{100 * l['delta_ci95_paired_bootstrap'][0]:+.1f}, "
          f"{100 * l['delta_ci95_paired_bootstrap'][1]:+.1f}]  "
          f"drops {l['paired']['drops']} gains {l['paired']['gains']}  "
          f"p {l['paired']['mcnemar_exact_p']:.3g}")
    o = rules["ours"]
    print(f"ours (control) : base {o['base']['correct']}/{n}  adapter {o['adapter']['correct']}/{n}  "
          f"delta {100 * o['delta_adapter_minus_base']:+.1f}pp  "
          f"CI [{100 * o['delta_ci95_paired_bootstrap'][0]:+.1f}, "
          f"{100 * o['delta_ci95_paired_bootstrap'][1]:+.1f}]  "
          f"drops {o['paired']['drops']} gains {o['paired']['gains']}  "
          f"p {o['paired']['mcnemar_exact_p']:.3g}")
    print(f"slots: {per_checker['totals']['slots']['total']}  "
          f"ours-pass/official-fail {per_checker['totals']['ours_pass_official_fail']['total']}  "
          f"ours-fail/official-pass {per_checker['totals']['ours_fail_official_pass']['total']}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
