#!/usr/bin/env python3
"""Freeze the benchmark samples into data/bench/ so scripts/run_bench.py never downloads.

Selection is a hash order: each candidate is ordered by sha256(f"{seed}:{id}"), and the
first n of that order are kept. The order does not depend on the source file's row order,
so the same seed reproduces the same sample and a smaller --limit is a prefix of a larger
one.

Sources, both offline at build time and both OSI-licensed:
  - gsm8k: openai/grade-school-math grade_school_math/data/test.jsonl (MIT).
  - ifeval: HF dataset google/IFEval ifeval_input_data.jsonl (Apache-2.0); only prompts
    whose every instruction type has a checker in scripts/bench_suites.py are kept, so the
    score covers items this repository can actually decide.

Usage:
  python3 scripts/bench_prep.py --gsm8k-src <test.jsonl> --ifeval-src <ifeval_input_data.jsonl>
  python3 scripts/bench_prep.py --check      # re-derive the selection and compare hashes
"""

import argparse
import glob
import hashlib
import json
import os

import bench_suites

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH_DIR = os.path.join(ROOT, "data/bench")
SOURCES = os.path.join(BENCH_DIR, "sources.json")
DEFAULT_SEED = 0
GSM8K_TAKE = 200
IFEVAL_CACHE = "/home/z/hf/hub/datasets--google--IFEval/snapshots/*/ifeval_input_data.jsonl"


def hash_order(seed, ids):
    return sorted(ids, key=lambda i: hashlib.sha256(f"{seed}:{i}".encode()).hexdigest())


def gsm8k_items(src_path, seed, take):
    rows = [json.loads(line) for line in open(src_path, encoding="utf-8") if line.strip()]
    by_id = {f"gsm8k-test-{i}": r for i, r in enumerate(rows)}
    kept = []
    for item_id in hash_order(seed, list(by_id))[:take]:
        row = by_id[item_id]
        gold = row["answer"].split("####")[-1].strip()
        gold = bench_suites._normalise_number(gold)
        assert gold is not None, item_id
        kept.append({"id": item_id, "question": row["question"].strip(), "answer_number": gold})
    return kept


def ifeval_items(src_path, seed):
    rows = [json.loads(line) for line in open(src_path, encoding="utf-8") if line.strip()]
    supported = bench_suites.supported_instruction_types()
    by_id, skipped = {}, 0
    for row in rows:
        if not set(row["instruction_id_list"]) <= supported:
            skipped += 1
            continue
        by_id[f"ifeval-{row['key']}"] = row
    kept = [
        {
            "id": item_id,
            "prompt": by_id[item_id]["prompt"],
            "instruction_id_list": by_id[item_id]["instruction_id_list"],
            "kwargs": by_id[item_id]["kwargs"],
        }
        for item_id in hash_order(seed, list(by_id))
    ]
    return kept, {"candidates": len(rows), "excluded_unsupported_types": skipped}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def write_jsonl(path, items):
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    return sha256(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gsm8k-src", default="")
    ap.add_argument("--ifeval-src", default="")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--check", action="store_true", help="re-derive and compare to sources.json")
    args = ap.parse_args()

    if args.check:
        manifest = json.load(open(SOURCES, encoding="utf-8"))
        seed = manifest["seed"]
        gsm8k_src = args.gsm8k_src or ""
        ifeval_src = args.ifeval_src or (glob.glob(IFEVAL_CACHE) or [""])[0]
        for name, path in (("gsm8k", gsm8k_src), ("ifeval", ifeval_src)):
            assert path and sha256(path) == manifest["suites"][name]["source_sha256"], (
                f"{name}: source {path!r} does not match the sha256 recorded at build time")
        gsm = gsm8k_items(gsm8k_src, seed, GSM8K_TAKE)
        ife, _ = ifeval_items(ifeval_src, seed)
        for name, items in (("gsm8k", gsm), ("ifeval", ife)):
            path = os.path.join(BENCH_DIR, f"{name}.jsonl")
            got, want = sha256(path), manifest["suites"][name]["frozen_sha256"]
            assert got == want, f"{name}: frozen file {got} != manifest {want}"
            assert len(items) == manifest["suites"][name]["frozen_items"], name
        print(f"OK seed={seed} " + " ".join(
            f"{n}={manifest['suites'][n]['frozen_items']}" for n in ("gsm8k", "ifeval")))
        return

    gsm8k_src = args.gsm8k_src
    ifeval_src = args.ifeval_src or (glob.glob(IFEVAL_CACHE) or [""])[0]
    assert gsm8k_src and os.path.exists(gsm8k_src), "--gsm8k-src required"
    assert ifeval_src and os.path.exists(ifeval_src), "--ifeval-src or the cached IFEval file"
    os.makedirs(BENCH_DIR, exist_ok=True)

    gsm = gsm8k_items(gsm8k_src, args.seed, GSM8K_TAKE)
    ife, ife_stats = ifeval_items(ifeval_src, args.seed)
    manifest = {
        "seed": args.seed,
        "selection_rule": "sort candidate ids by sha256('<seed>:<id>') hex ascending, keep the prefix",
        "suites": {
            "gsm8k": {
                "source_url": "https://raw.githubusercontent.com/openai/grade-school-math/master/grade_school_math/data/test.jsonl",
                "license": "MIT",
                "source_sha256": sha256(gsm8k_src),
                "frozen_items": len(gsm),
                "frozen_sha256": write_jsonl(os.path.join(BENCH_DIR, "gsm8k.jsonl"), gsm),
                "max_new_tokens": bench_suites.MAX_NEW_TOKENS["gsm8k"],
                "scoring": "last number after '####' (else the last bare number) compared to the gold number, exact after normalisation",
            },
            "ifeval": {
                "source_url": "https://huggingface.co/datasets/google/IFEval",
                "license": "Apache-2.0",
                "source_sha256": sha256(ifeval_src),
                "frozen_items": len(ife),
                "frozen_sha256": write_jsonl(os.path.join(BENCH_DIR, "ifeval.jsonl"), ife),
                "max_new_tokens": bench_suites.MAX_NEW_TOKENS["ifeval"],
                "scoring": "an item is kept only when every instruction type it carries has a checker in scripts/bench_suites.py; correct means every instruction on the item holds",
                "supported_instruction_types": sorted(bench_suites.supported_instruction_types()),
                **ife_stats,
            },
        },
    }
    with open(SOURCES, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps({n: {k: manifest["suites"][n][k] for k in
                          ("frozen_items", "frozen_sha256", "source_sha256")}
                      for n in manifest["suites"]}, indent=2))
    if "excluded_unsupported_types" in ife_stats:
        print(f"ifeval excluded {ife_stats['excluded_unsupported_types']} of "
              f"{ife_stats['candidates']} prompts for unsupported instruction types")


if __name__ == "__main__":
    main()
