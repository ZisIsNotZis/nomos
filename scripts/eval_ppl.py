#!/usr/bin/env python3
"""Per-token perplexity of the completions, base model vs LoRA adapter, on the held-out pairs.

PPL is exp(total completion NLL / total completion tokens) over the validation split, the
same split and the same prompt encoding scripts/train_dpo.py trains and evaluates with.

Usage:
  python3 scripts/eval_ppl.py --adapter evidence/training/adapter
"""

import argparse
import json
import os
import sys

import torch
from transformers import AutoModelForImageTextToText, AutoTokenizer, BitsAndBytesConfig

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_dpo import (  # noqa: E402
    BASE_MODEL,
    ROOT,
    assert_prompts_clean,
    choose_max_length,
    encode_pair,
    load_pairs,
    session_map,
    session_split,
    token_stats,
)
from train_dpo import sequence_logprobs  # noqa: E402


def score(model, tokenizer, rows, max_length):
    """Return per-pair completion log-probabilities under the model as loaded."""
    out = []
    with torch.no_grad():
        for row in rows:
            ids = encode_pair(tokenizer, row, max_length)
            totals = {}
            for side in ("chosen", "rejected"):
                cur, plen = ids[side]
                input_ids = torch.tensor([cur], dtype=torch.long, device="cuda")
                target_mask = torch.zeros_like(input_ids, dtype=torch.bool)
                target_mask[:, plen:] = True
                lp, n = sequence_logprobs(model, input_ids, target_mask)
                totals[side] = {"logp": lp[0].item(), "tokens": int(n[0].item())}
            out.append(
                {
                    "situation_id": row["situation_id"],
                    "chosen": totals["chosen"],
                    "rejected": totals["rejected"],
                }
            )
    return out


def summarise(records):
    def ppl(side):
        nll = -sum(r[side]["logp"] for r in records)
        tokens = sum(r[side]["tokens"] for r in records)
        return {"ppl": float(torch.exp(torch.tensor(nll / tokens))), "nll": nll, "tokens": tokens}

    chosen, rejected = ppl("chosen"), ppl("rejected")
    margin = [r["chosen"]["logp"] / r["chosen"]["tokens"] - r["rejected"]["logp"] / r["rejected"]["tokens"] for r in records]
    return {
        "n_pairs": len(records),
        "chosen": chosen,
        "rejected": rejected,
        "per_token_margin": sum(margin) / len(margin),
        "acc": sum(1 for m in margin if m > 0) / len(margin),
        "pairs": records,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", default=os.path.join(ROOT, "evidence/training/adapter"))
    parser.add_argument("--holdout-pairs", type=int, default=18)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default=os.path.join(ROOT, "evidence/training/ppl.json"))
    args = parser.parse_args()

    rows = load_pairs()
    sessions = session_map()
    assert_prompts_clean(rows, sessions)
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    stats = token_stats(tokenizer, rows)
    max_length = choose_max_length(stats, tokenizer)
    _train, val, val_sessions = session_split(rows, sessions, args.holdout_pairs, args.seed)

    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForImageTextToText.from_pretrained(
        BASE_MODEL, quantization_config=quant, device_map={"": 0}, dtype=torch.bfloat16
    )
    model.eval()

    before = summarise(score(model, tokenizer, val, max_length))

    from peft import PeftModel

    model = PeftModel.from_pretrained(model, args.adapter)
    model.eval()
    after = summarise(score(model, tokenizer, val, max_length))

    payload = {
        "adapter": os.path.relpath(args.adapter, ROOT),
        "val_pairs": len(val),
        "val_sessions": val_sessions,
        "max_length": max_length,
        "definition": (
            "PPL = exp(total completion NLL / total completion tokens) over the held-out "
            "pairs, prompt and completion encoded exactly as training encodes them"
        ),
        "before": before,
        "after": after,
        "delta_ppl_chosen": after["chosen"]["ppl"] - before["chosen"]["ppl"],
        "delta_ppl_rejected": after["rejected"]["ppl"] - before["rejected"]["ppl"],
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    print(
        json.dumps(
            {
                "before_chosen_ppl": before["chosen"]["ppl"],
                "before_rejected_ppl": before["rejected"]["ppl"],
                "after_chosen_ppl": after["chosen"]["ppl"],
                "after_rejected_ppl": after["rejected"]["ppl"],
                "before_acc": before["acc"],
                "after_acc": after["acc"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
