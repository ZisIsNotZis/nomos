#!/usr/bin/env python3
"""Three pre-tuning checks on the DPO implementation: prompt masking, label
alignment, and the loss formula against a hand computation.

Loads the base model plus the trained adapter from the previous run, so the
numbers printed here are the numbers that run produced.

Usage: python3 scripts/diag_dpo_checks.py
Writes: evidence/training/diag/loss-check.json
"""

import json
import math
import os
import sys

import torch
import torch.nn.functional as F
from peft import PeftModel
from transformers import AutoModelForImageTextToText, AutoTokenizer, BitsAndBytesConfig

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import train_dpo as T  # noqa: E402

ADAPTER = os.path.join(T.ROOT, ".tmp/training/adapter-dpo-r16")
OUT = os.path.join(T.ROOT, "evidence/training/diag/loss-check.json")
BETA = 0.1


def load_model():
    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    base = AutoModelForImageTextToText.from_pretrained(
        T.BASE_MODEL, quantization_config=quant, device_map={"": 0}, dtype=torch.bfloat16
    )
    model = PeftModel.from_pretrained(base, ADAPTER)
    model.eval()
    model.config.use_cache = False
    return model


def hand_logp(model, input_ids, plen):
    """Sum log p(completion) from one explicit forward, float32 log_softmax, no mask tricks."""
    with torch.no_grad():
        logits = model(input_ids=input_ids, attention_mask=torch.ones_like(input_ids)).logits
    logprobs = F.log_softmax(logits[0, plen - 1 : -1, :].float(), dim=-1)
    targets = input_ids[0, plen:]
    picked = logprobs.gather(1, targets[:, None]).squeeze(1)
    return float(picked.sum()), picked.tolist()


def main():
    tokenizer = AutoTokenizer.from_pretrained(T.BASE_MODEL)
    rows = T.load_pairs()
    sessions = T.session_map()
    T.assert_prompts_clean(rows, sessions)
    stats = T.token_stats(tokenizer, rows)
    max_length = T.choose_max_length(stats, tokenizer)
    _train, val, _ = T.session_split(rows, sessions, 18, 0)
    model = load_model()

    out = {"beta": BETA, "max_length": max_length}

    # --- check 1 + 3 on one held-out pair -------------------------------------
    row = val[0]
    ids = T.encode_pair(tokenizer, row, max_length)
    plen = ids["chosen"][1]
    probe = {}
    per_side = {}
    for side in ("chosen", "rejected"):
        full, plen_side = ids[side]
        input_ids = torch.tensor([full], dtype=torch.long, device="cuda")
        total, per_token = hand_logp(model, input_ids, plen_side)
        with torch.no_grad(), model.disable_adapter():
            ref_total, _ = hand_logp(model, input_ids, plen_side)
        # what the loss would be if the prompt were scored too
        with torch.no_grad():
            all_lp = F.log_softmax(
                model(
                    input_ids=input_ids, attention_mask=torch.ones_like(input_ids)
                ).logits[0, :-1, :].float(),
                dim=-1,
            )
        prompt_included = float(
            all_lp.gather(1, input_ids[0, 1:, None]).squeeze(1).sum()
        )
        per_side[side] = {
            "prompt_tokens": plen_side,
            "completion_tokens": len(full) - plen_side,
            "completion_logp": total,
            "per_token_logp": total / (len(full) - plen_side),
            "ref_completion_logp": ref_total,
            "prompt_plus_completion_logp": prompt_included,
        }
        probe[side] = (total, ref_total, len(full) - plen_side)

    # --- same pair through the training code path ----------------------------
    input_ids, target_mask = T.make_batch(
        tokenizer, [("chosen", ids["chosen"]), ("rejected", ids["rejected"])], max_length
    )
    input_ids = input_ids.to("cuda")
    target_mask = target_mask.to("cuda")
    with torch.no_grad():
        pol, lengths = T.sequence_logprobs(model, input_ids, target_mask)
        with model.disable_adapter():
            ref, _ = T.sequence_logprobs(model, input_ids, target_mask)
    loss, metrics = T.dpo_step(model, {"input_ids": input_ids, "target_mask": target_mask}, BETA)

    pol_c, pol_r = float(pol[0]), float(pol[1])
    ref_c, ref_r = float(ref[0]), float(ref[1])
    log_ratio_c, log_ratio_r = pol_c - ref_c, pol_r - ref_r
    hand_loss = -math.log(1.0 / (1.0 + math.exp(-BETA * (log_ratio_c - log_ratio_r))))

    out["pair"] = row["situation_id"]
    out["sides"] = per_side
    out["pipeline"] = {
        "scored_tokens_per_side": int(lengths[0]),
        "policy_chosen": pol_c,
        "policy_rejected": pol_r,
        "ref_chosen": ref_c,
        "ref_rejected": ref_r,
        "logratio_chosen": log_ratio_c,
        "logratio_rejected": log_ratio_r,
        "hand_loss": hand_loss,
        "dpo_step_loss": metrics["loss"],
        "loss_abs_diff": abs(hand_loss - metrics["loss"]),
        "logp_abs_diff_vs_hand": [
            abs(pol_c - probe["chosen"][0]),
            abs(pol_r - probe["rejected"][0]),
        ],
        "raw_margin": pol_c - pol_r,
        "raw_margin_per_token": (pol_c - pol_r) / (
            per_side["chosen"]["completion_tokens"] * 0.5
            + per_side["rejected"]["completion_tokens"] * 0.5
        ),
        "reward_margin": BETA * ((pol_c - ref_c) - (pol_r - ref_r)),
    }

    # --- check 2: batch order, chosen first, and the logged run's own numbers -
    pair_a, pair_b = val[0], val[1]
    ids_a = T.encode_pair(tokenizer, pair_a, max_length)
    ids_b = T.encode_pair(tokenizer, pair_b, max_length)
    combined = [
        ("chosen", ids_a["chosen"]),
        ("rejected", ids_a["rejected"]),
        ("chosen", ids_b["chosen"]),
        ("rejected", ids_b["rejected"]),
    ]
    ii, tm = T.make_batch(tokenizer, combined, max_length)
    with torch.no_grad():
        lp, _ = T.sequence_logprobs(model, ii.to("cuda"), tm.to("cuda"))
    order = {"logged_index": [float(x) for x in lp.tolist()], "recomputed_single": {}}
    for k, (row_k, ids_k, side) in enumerate(
        [(pair_a, ids_a, "chosen"), (pair_a, ids_a, "rejected"),
         (pair_b, ids_b, "chosen"), (pair_b, ids_b, "rejected")]
    ):
        full, plen_k = ids_k[side]
        single, _ = hand_logp(
            model, torch.tensor([full], dtype=torch.long, device="cuda"), plen_k
        )
        order["recomputed_single"][f"{k}:{row_k['situation_id']}:{side}"] = single
    order["max_abs_diff"] = max(
        abs(order["logged_index"][k] - v)
        for k, v in enumerate(order["recomputed_single"].values())
    )
    # dpo_step must pair index 0 with index 2 and 1 with 3
    n = lp.shape[0] // 2
    order["pol_c_index0"] = float(lp[0])
    order["pol_r_index_n"] = float(lp[n])
    order["paired_margin"] = float(lp[0] - lp[n])
    out["batch_order"] = order

    # logp of that val pair as the finished run logged it
    logged = None
    for line in open(os.path.join(T.OUT_DIR, "log.jsonl"), encoding="utf-8"):
        rec = json.loads(line)
        if rec.get("type") == "final_eval" and rec.get("split") == "val":
            for entry in rec["pairs"]:
                if entry["situation_id"] == row["situation_id"]:
                    logged = entry
    if logged:
        out["logged_val_pair"] = {
            "chosen_logp": logged["chosen_logp"],
            "rejected_logp": logged["rejected_logp"],
            "ref_chosen_logp": logged["ref_chosen_logp"],
            "ref_rejected_logp": logged["ref_rejected_logp"],
            "reproduced_abs_diff": [
                abs(pol_c - logged["chosen_logp"]),
                abs(pol_r - logged["rejected_logp"]),
                abs(ref_c - logged["ref_chosen_logp"]),
                abs(ref_r - logged["ref_rejected_logp"]),
            ],
        }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
