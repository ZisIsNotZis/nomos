#!/usr/bin/env python3
"""Run one prepared suite against the base model or the SFT adapter and score it by code.

Never runs during preparation: the GPU is shared, so a real run is a separate work package.
`--stub` swaps the model for a fixed-output stub that needs no GPU; scripts/bench_selftest.py
uses it to prove the judging path end to end.

The suite items come from data/bench/<suite>.jsonl, frozen by scripts/bench_prep.py with
seed 0 by hash order, so --limit N is always the same N items and a smaller run is a prefix
of a larger one. Decoding is greedy, so the only remaining randomness is the model's own
numerics; a small difference is reported with its interval instead of being called a drop.

Usage:
  python3 scripts/run_bench.py --suite all --model base --limit 100
  python3 scripts/run_bench.py --suite gsm8k --model adapter --limit 200
  python3 scripts/run_bench.py --suite gsm8k --model base --limit 5 --stub gold   # no GPU
"""

import argparse
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_suites  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH_DIR = os.path.join(ROOT, "data/bench")
OUT_DIR = os.path.join(ROOT, "evidence/benchmark")
BASE_MODEL = "/home/z/hf/hub/models--Qwen--Qwen3.5-2B/snapshots/15852e8c16360a2fea060d615a32b45270f8a8fc"
ADAPTER_DIR = os.path.join(ROOT, ".tmp/sft/adapter-narrow")


class StubModel:
    """Fixed outputs, no weights: proves scoring and aggregation without touching the GPU."""

    def __init__(self, mode, suite, items):
        self.mode = mode
        self.gold = {i["id"]: i.get("answer_number") for i in items}
        self.suite = suite

    def generate(self, prompts, items, max_new_tokens):
        out = []
        for prompt, item in zip(prompts, items):
            if self.mode == "gold":
                out.append(f"#### {self.gold[item['id']]}" if self.suite == "gsm8k" else "42")
            elif self.mode == "wrong":
                gold = int(self.gold[item["id"]])
                out.append(f"#### {gold + 1}" if self.suite == "gsm8k" else "No.")
            elif self.mode == "garbage":
                out.append("I cannot answer this.")
            else:
                raise ValueError(self.mode)
        return out


class HFChatModel:
    """Qwen3.5-2B 4-bit, optionally with the LoRA adapter, greedy decoding, batch 1."""

    def __init__(self, kind, adapter_dir):
        import torch
        from transformers import AutoModelForImageTextToText, AutoTokenizer, BitsAndBytesConfig

        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
        kwargs = dict(
            quantization_config=BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16,
            ),
            device_map={"": 0},
        )
        model = AutoModelForImageTextToText.from_pretrained(BASE_MODEL, **kwargs)
        if kind == "adapter":
            from peft import PeftModel

            model = PeftModel.from_pretrained(model, adapter_dir)
        model.eval()
        self.model = model

    def generate(self, prompts, items, max_new_tokens):
        out = []
        for prompt in prompts:
            text = self.tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt}],
                tokenize=False, add_generation_prompt=True,
            )
            ids = self.tokenizer(text, return_tensors="pt").to("cuda")
            with self.torch.no_grad():
                gen = self.model.generate(
                    **ids, max_new_tokens=max_new_tokens, do_sample=False,
                    temperature=None, top_p=None, top_k=None,
                    pad_token_id=self.tokenizer.pad_token_id,
                )
            out.append(self.tokenizer.decode(gen[0, ids["input_ids"].shape[1]:],
                                             skip_special_tokens=True))
        return out


def run_suite(suite, items, model, limit, max_new_tokens):
    items = items[:limit] if limit else items
    prompts = [bench_suites.build_prompt(suite, item) for item in items]
    started = time.time()
    outputs = model.generate(prompts, items, max_new_tokens)
    elapsed = time.time() - started
    records = []
    for item, prompt, output in zip(items, prompts, outputs):
        verdict = bench_suites.score(suite, item, output)
        records.append({"id": item["id"], "prompt": prompt, "output": output, **verdict})
    unscorable = sum(1 for r in records if r["unscorable"])
    summary = bench_suites.aggregate(records, unscorable)
    return {"records": records, "summary": summary, "elapsed_seconds": round(elapsed, 1)}


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", choices=list(bench_suites.SUITES) + ["all"], default="all")
    ap.add_argument("--model", choices=["base", "adapter"], default="base")
    ap.add_argument("--adapter-dir", default=ADAPTER_DIR)
    ap.add_argument("--limit", type=int, default=0, help="0 runs every frozen item")
    ap.add_argument("--seed", type=int, default=None,
                    help="must match data/bench/sources.json; change it by re-running bench_prep")
    ap.add_argument("--stub", choices=["gold", "wrong", "garbage"], default=None,
                    help="fixed-output model instead of the GPU model (self-test only)")
    ap.add_argument("--tag", default="",
                    help="override the output tag (default <model>-<suite>); a trial run must not "
                         "overwrite a landed artefact, so it gives its own tag")
    args = ap.parse_args()

    manifest = json.load(open(os.path.join(BENCH_DIR, "sources.json"), encoding="utf-8"))
    if args.seed is not None:
        assert args.seed == manifest["seed"], (
            f"--seed {args.seed} differs from the frozen selection seed {manifest['seed']}; "
            "re-run scripts/bench_prep.py --seed to change the sample")
    suites = list(bench_suites.SUITES) if args.suite == "all" else [args.suite]
    os.makedirs(OUT_DIR, exist_ok=True)
    model = None
    for suite in suites:
        items = bench_suites.load_items(suite, BENCH_DIR)
        if args.stub:
            m = StubModel(args.stub, suite, items)
        else:
            model = model or HFChatModel(args.model, args.adapter_dir)
            m = model
        run = run_suite(suite, items, m, args.limit, manifest["suites"][suite]["max_new_tokens"])
        payload = {
            "suite": suite,
            "model": args.model,
            "stub": args.stub,
            "adapter_dir": args.adapter_dir if args.model == "adapter" and not args.stub else None,
            "frozen_sha256": manifest["suites"][suite]["frozen_sha256"],
            "seed": manifest["seed"],
            "limit": args.limit or len(items),
            "max_new_tokens": manifest["suites"][suite]["max_new_tokens"],
            "decoding": "greedy",
            **run,
        }
        tag = args.tag or f"{args.model}{'-stub-' + args.stub if args.stub else ''}-{suite}"
        path = os.path.join(OUT_DIR, f"{tag}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
            f.write("\n")
        s = run["summary"]
        print(f"{suite:7s} {tag:20s} acc={s['accuracy']:.4f} "
              f"ci95=[{s['accuracy_ci95'][0]:.4f},{s['accuracy_ci95'][1]:.4f}] "
              f"n={s['items']} unscorable={s['unscorable']} "
              f"{run['elapsed_seconds']:.0f}s -> {path}")


if __name__ == "__main__":
    main()
