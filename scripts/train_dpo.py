#!/usr/bin/env python3
"""DPO on the stable preference pairs: QLoRA 4-bit on Qwen3.5-2B, hand-written DPO loss.

Prompt is the situation excerpt alone. The script refuses to run if any prompt
carries constitution text, so a regression in data preparation fails loudly here
instead of teaching the model a leaked law paragraph.

Usage:
  python3 scripts/train_dpo.py
  python3 scripts/train_dpo.py --epochs 1 --limit 8   # smoke run
"""

import argparse
import hashlib
import json
import math
import os
import random
import time

import numpy as np
import torch
import torch.nn.functional as F
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import AutoModelForImageTextToText, AutoTokenizer, BitsAndBytesConfig

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_MODEL = "/home/z/hf/hub/models--Qwen--Qwen3.5-2B/snapshots/15852e8c16360a2fea060d615a32b45270f8a8fc"
PAIRS = os.path.join(ROOT, "data/pairs-stable-v2.jsonl")
SITUATION_SOURCES = [
    os.path.join(ROOT, "evidence/slice-contrast/situations.jsonl"),
    os.path.join(ROOT, "evidence/grow/situations.jsonl"),
]
OUT_DIR = os.path.join(ROOT, "evidence/training")
ADAPTER_DIR = os.path.join(OUT_DIR, "adapter")
LOG_PATH = os.path.join(OUT_DIR, "log.jsonl")

# Sentence-length fragments of the frozen constitution. A prompt that contains one
# of these carries law text verbatim; short tokens (SSOT, projection) are excluded
# on purpose because the user's own turns use that vocabulary innocently.
LAW_PHRASES = [
    "Each node here is a law",
    "A sibling set is the values of one field",
    "keep a rule when omitting it would materially impair orientation",
    "Evidence: a check, measurement, review or document must distinguish",
    "Reason backwards from the end",
    "Depth beats breadth",
    "Reasoning is the scarcest budget",
    "One record: every current fact lives in its SSOT home",
    "the reader pays for it in trust",
    "A transient buffer such as .tmp lives like /tmp",
    "Who may decide: rank the sources",
]

LORA_TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


_state = {"log_path": LOG_PATH}


def log(record):
    """Append one JSON record to the evidence log."""
    with open(_state["log_path"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_pairs():
    rows = [json.loads(line) for line in open(PAIRS, encoding="utf-8") if line.strip()]
    return rows


def session_map():
    mapping = {}
    for path in SITUATION_SOURCES:
        for line in open(path, encoding="utf-8"):
            if not line.strip():
                continue
            row = json.loads(line)
            mapping[row["id"]] = row["session"]
    return mapping


def assert_prompts_clean(rows, sessions):
    """No prompt carries constitution text, and each pair shares one prompt."""
    for row in rows:
        excerpt = row["excerpt"]
        for phrase in LAW_PHRASES:
            if phrase.lower() in excerpt.lower():
                raise AssertionError(
                    f"{row['situation_id']}: prompt contains constitution text {phrase!r}"
                )
        chosen, rejected = row["chosen"], row["rejected"]
        assert chosen.strip() and rejected.strip(), f"{row['situation_id']}: empty completion"
        assert chosen != rejected, f"{row['situation_id']}: chosen equals rejected"
        # Both completions were generated from this excerpt; every pair inherits it
        # from the situations file, so the prompt the two completions share is one string.
        assert isinstance(row["excerpt"], str) and row["excerpt"].strip(), (
            f"{row['situation_id']}: empty prompt"
        )
        assert row["situation_id"] in sessions, f"{row['situation_id']}: no session, cannot split"


def session_split(rows, sessions, holdout_pairs=15, seed=0):
    by_session = {}
    for row in rows:
        by_session.setdefault(sessions[row["situation_id"]], []).append(row)
    names = sorted(by_session)
    random.Random(seed).shuffle(names)
    val, val_sessions = [], []
    for name in names:
        if len(val) >= holdout_pairs:
            break
        val.extend(by_session[name])
        val_sessions.append(name)
    val_ids = {row["situation_id"] for row in val}
    train = [row for row in rows if row["situation_id"] not in val_ids]
    assert not any(sessions[r["situation_id"]] in val_sessions for r in train), "session leak"
    return train, val, val_sessions


def token_stats(tokenizer, rows):
    lens = {"prompt": [], "chosen": [], "rejected": [], "prompt_plus_max": []}
    for row in rows:
        p = len(tokenizer(row["excerpt"], add_special_tokens=False).input_ids)
        c = len(tokenizer(row["chosen"], add_special_tokens=False).input_ids)
        r = len(tokenizer(row["rejected"], add_special_tokens=False).input_ids)
        lens["prompt"].append(p)
        lens["chosen"].append(c)
        lens["rejected"].append(r)
        lens["prompt_plus_max"].append(p + max(c, r))
    stats = {}
    for key, values in lens.items():
        arr = np.array(values)
        stats[key] = {
            "p50": int(np.percentile(arr, 50)),
            "p95": int(np.percentile(arr, 95)),
            "max": int(arr.max()),
            "mean": round(float(arr.mean()), 1),
        }
    return stats


def choose_max_length(stats, tokenizer):
    """Longest pair plus a small margin, rounded up to 128: no pair is truncated."""
    needed = stats["prompt_plus_max"]["max"]
    length = int(math.ceil(needed / 128.0) * 128)
    length = max(length, stats["prompt_plus_max"]["p95"] + 128)
    return min(length, int(tokenizer.model_max_length))


def encode_pair(tokenizer, row, max_length):
    messages = [{"role": "user", "content": row["excerpt"]}]
    prompt_text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    prompt_ids = tokenizer(prompt_text, add_special_tokens=False).input_ids
    eos = tokenizer.eos_token_id
    ids = {}
    for side in ("chosen", "rejected"):
        completion = tokenizer(row[side], add_special_tokens=False).input_ids + [eos]
        full = prompt_ids + completion
        assert len(prompt_ids) + 1 <= max_length, (
            f"{row['situation_id']}: prompt alone exceeds max_length"
        )
        full = full[:max_length]
        ids[side] = (full, len(prompt_ids))
    # The two sides share one prompt prefix: same ids, same length.
    assert ids["chosen"][1] == ids["rejected"][1]
    assert ids["chosen"][0][: ids["chosen"][1]] == ids["rejected"][0][: ids["chosen"][1]]
    return ids


def make_batch(tokenizer, encoded, max_length):
    """Stack prompt+completion sequences, right padded; return input_ids, mask, starts."""
    pad_id = tokenizer.pad_token_id or tokenizer.eos_token_id
    seqs = []
    for side, (ids, plen) in encoded:
        seqs.append((ids, plen))
    width = max(len(ids) for ids, _ in seqs)
    input_ids = torch.full((len(seqs), width), pad_id, dtype=torch.long)
    target_mask = torch.zeros((len(seqs), width), dtype=torch.bool)
    for i, (ids, plen) in enumerate(seqs):
        input_ids[i, : len(ids)] = torch.tensor(ids, dtype=torch.long)
        target_mask[i, plen:] = True
        target_mask[i, len(ids) :] = False
    return input_ids, target_mask


def sequence_logprobs(model, input_ids, target_mask, chunk=256):
    """Sum log p(token) over completion tokens, per sequence.

    Only the completion positions are scored, in row chunks, because a
    float32 softmax over the full vocabulary at every position costs more
    memory than the model itself.
    """
    attention_mask = torch.ones_like(input_ids)  # right padding only
    logits = model(input_ids=input_ids, attention_mask=attention_mask).logits[:, :-1, :]
    mask = target_mask[:, 1:]
    targets = input_ids[:, 1:][mask]
    rows = logits[mask]
    del logits
    picked = torch.empty(rows.shape[0], dtype=torch.float32, device=rows.device)
    for start in range(0, rows.shape[0], chunk):
        block = rows[start : start + chunk].float()
        target_block = targets[start : start + chunk]
        picked[start : start + chunk] = F.cross_entropy(
            block, target_block, reduction="none"
        ).neg()
    seq_index = mask.nonzero()[:, 0]
    totals = torch.zeros(input_ids.shape[0], dtype=torch.float32, device=rows.device)
    totals = totals.index_add(0, seq_index, picked)
    return totals, mask.sum(-1)


def dpo_step(model, batch, beta):
    input_ids = batch["input_ids"].to("cuda")
    target_mask = batch["target_mask"].to("cuda")
    policy_lp, lengths = sequence_logprobs(model, input_ids, target_mask)
    with torch.no_grad(), model.disable_adapter():
        ref_lp, _ = sequence_logprobs(model, input_ids, target_mask)
    n = policy_lp.shape[0] // 2
    pol_c, pol_r = policy_lp[:n], policy_lp[n:]
    ref_c, ref_r = ref_lp[:n], ref_lp[n:]
    logits = beta * ((pol_c - ref_c) - (pol_r - ref_r))
    loss = -F.logsigmoid(logits).mean()
    margin = (pol_c - pol_r).detach()
    return loss, {
        "loss": loss.item(),
        "margin": margin.mean().item(),
        "acc": (margin > 0).float().mean().item(),
        "chosen_logp": pol_c.detach().mean().item(),
        "rejected_logp": pol_r.detach().mean().item(),
        "ref_margin": (ref_c - ref_r).detach().mean().item(),
        "completion_tokens": int(lengths.float().mean().item()),
        "reward_accuracy_gap": (logits.detach() > 0).float().mean().item(),
    }


def evaluate(model, tokenizer, rows, max_length, beta):
    model.eval()
    totals = []
    with torch.no_grad():
        for row in rows:
            ids = encode_pair(tokenizer, row, max_length)
            input_ids, target_mask = make_batch(
                tokenizer, [("chosen", ids["chosen"]), ("rejected", ids["rejected"])], max_length
            )
            input_ids = input_ids.to("cuda")
            target_mask = target_mask.to("cuda")
            lp, _ = sequence_logprobs(model, input_ids, target_mask)
            with model.disable_adapter():
                ref, _ = sequence_logprobs(model, input_ids, target_mask)
            totals.append(
                {
                    "situation_id": row["situation_id"],
                    "chosen_logp": lp[0].item(),
                    "rejected_logp": lp[1].item(),
                    "ref_chosen_logp": ref[0].item(),
                    "ref_rejected_logp": ref[1].item(),
                }
            )
    model.train()
    margin = torch.tensor([t["chosen_logp"] - t["rejected_logp"] for t in totals])
    logits = torch.tensor(
        [
            beta
            * ((t["chosen_logp"] - t["ref_chosen_logp"]) - (t["rejected_logp"] - t["ref_rejected_logp"]))
            for t in totals
        ]
    )
    return {
        "n": len(totals),
        "dpo_loss": float(-F.logsigmoid(logits).mean()),
        "margin": float(margin.mean()),
        "acc": float((margin > 0).float().mean()),
        "reward_margin": float(logits.mean()),
        "pairs": totals,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--pairs-per-step", type=int, default=4)
    parser.add_argument("--micro-pairs", type=int, default=1, help="pairs per forward (memory bound)")
    parser.add_argument("--lr", type=float, default=5e-5)
    parser.add_argument("--beta", type=float, default=0.1)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--holdout-pairs", type=int, default=18)
    parser.add_argument("--eval-every", type=int, default=5)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0, help="smoke run: cap training pairs")
    parser.add_argument(
        "--skip-train-eval",
        action="store_true",
        help="sweep runs: skip the final 73-pair train evaluation, keep the held-out one",
    )
    parser.add_argument("--out-dir", default=OUT_DIR)
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    adapter_dir = os.path.join(args.out_dir, "adapter")
    _state["log_path"] = os.path.join(args.out_dir, "log.jsonl")
    open(_state["log_path"], "w").close()

    torch.manual_seed(args.seed)
    random.seed(args.seed)

    rows = load_pairs()
    sessions = session_map()
    assert_prompts_clean(rows, sessions)

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    stats = token_stats(tokenizer, rows)
    max_length = choose_max_length(stats, tokenizer)
    train, val, val_sessions = session_split(rows, sessions, args.holdout_pairs, args.seed)
    if args.limit:
        train = train[: args.limit]

    free_gib = torch.cuda.mem_get_info(0)[0] / 2**30 if torch.cuda.is_available() else 0.0
    log(
        {
            "type": "setup",
            "rows": len(rows),
            "train_pairs": len(train),
            "val_pairs": len(val),
            "val_sessions": val_sessions,
            "sessions_total": len(set(sessions[r["situation_id"]] for r in rows)),
            "token_stats": stats,
            "max_length": max_length,
            "max_length_reason": (
                f"longest prompt+completion is {stats['prompt_plus_max']['max']} tokens "
                f"(p95 {stats['prompt_plus_max']['p95']}), rounded up to {max_length}: no pair truncated"
            ),
            "law_phrases_checked": LAW_PHRASES,
            "gpu_name": torch.cuda.get_device_name(0),
            "gpu_free_gib_at_start": round(free_gib, 2),
            "hf": {
                "torch": torch.__version__,
                "transformers": __import__("transformers").__version__,
                "peft": __import__("peft").__version__,
                "bitsandbytes": __import__("bitsandbytes").__version__,
            },
        }
    )

    encoded = [(row, encode_pair(tokenizer, row, max_length)) for row in train]
    val_encoded = [(row, encode_pair(tokenizer, row, max_length)) for row in val]

    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForImageTextToText.from_pretrained(
        BASE_MODEL, quantization_config=quant, device_map={"": 0}, dtype=torch.bfloat16
    )
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model.config.use_cache = False
    lora = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=LORA_TARGET_MODULES,
    )
    model = get_peft_model(model, lora)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    log(
        {
            "type": "config",
            "base_model": BASE_MODEL,
            "lora_r": args.lora_r,
            "lora_alpha": args.lora_alpha,
            "lora_dropout": 0.05,
            "lora_targets": LORA_TARGET_MODULES,
            "trainable_params": trainable,
            "total_params": total,
            "trainable_fraction": round(trainable / total, 5),
            "beta": args.beta,
            "lr": args.lr,
            "epochs": args.epochs,
            "pairs_per_step": args.pairs_per_step,
            "optimizer": "paged_adamw_8bit",
            "max_length": max_length,
        }
    )

    import bitsandbytes as bnb

    optim = bnb.optim.PagedAdamW8bit(
        [p for p in model.parameters() if p.requires_grad], lr=args.lr, weight_decay=0.0
    )
    steps_per_epoch = math.ceil(len(encoded) / args.pairs_per_step)
    total_steps = max(1, int(steps_per_epoch * args.epochs))
    warmup = min(5, max(1, total_steps // 10))
    sched = torch.optim.lr_scheduler.LambdaLR(
        optim,
        lambda s: min(1.0, (s + 1) / warmup)
        * max(0.0, 1.0 - max(0, s - warmup) / max(1, total_steps - warmup)),
    )

    model.train()
    torch.cuda.reset_peak_memory_stats()
    started = time.time()
    step = 0
    epoch = 0
    order = list(range(len(encoded)))
    while step < total_steps:
        random.Random(args.seed + epoch).shuffle(order)
        for start in range(0, len(order), args.pairs_per_step):
            if step >= total_steps:
                break
            chunk = [encoded[i] for i in order[start : start + args.pairs_per_step]]
            micro_chunks = [
                chunk[i : i + args.micro_pairs]
                for i in range(0, len(chunk), args.micro_pairs)
            ]
            optim.zero_grad(set_to_none=True)
            accumulated = {}
            for micro in micro_chunks:
                combined = []
                for _row, ids in micro:
                    combined.append(("chosen", ids["chosen"]))
                    combined.append(("rejected", ids["rejected"]))
                input_ids, target_mask = make_batch(tokenizer, combined, max_length)
                batch = {"input_ids": input_ids, "target_mask": target_mask}
                loss, metrics = dpo_step(model, batch, args.beta)
                (loss / len(micro_chunks)).backward()
                for key, value in metrics.items():
                    accumulated[key] = accumulated.get(key, 0.0) + value / len(micro_chunks)
            if step == 0:
                # The LoRA deltas must be attached to the graph: torch.utils.checkpoint
                # prints "None of the inputs have requires_grad=True" from the reference
                # forward under no_grad, so a silent detached adapter is a real risk here.
                lora = [(n, p) for n, p in model.named_parameters() if "lora_" in n]
                with_grad = [(n, p) for n, p in lora if p.grad is not None]
                nonzero = [n for n, p in with_grad if p.grad.norm().item() > 0]
                assert nonzero, "no LoRA parameter received a non-zero gradient"
                log(
                    {
                        "type": "grad_check",
                        "step": 1,
                        "lora_params": len(lora),
                        "lora_params_with_grad": len(with_grad),
                        "lora_params_nonzero_grad": len(nonzero),
                        "lora_grad_norm": round(
                            math.sqrt(sum(p.grad.pow(2).sum().item() for _, p in with_grad)), 4
                        ),
                        "first_nonzero": nonzero[0],
                    }
                )
            torch.nn.utils.clip_grad_norm_(
                [p for p in model.parameters() if p.requires_grad], 1.0
            )
            optim.step()
            sched.step()
            optim.zero_grad(set_to_none=True)
            step += 1
            log(
                {
                    "type": "step",
                    "step": step,
                    "epoch": round(epoch + (start + len(chunk)) / len(order), 3),
                    "lr": round(sched.get_last_lr()[0], 8),
                    "elapsed_s": round(time.time() - started, 1),
                    **{k: round(v, 5) for k, v in accumulated.items()},
                }
            )
            if step % args.eval_every == 0 or step == total_steps:
                val_metrics = evaluate(
                    model, tokenizer, [r for r, _ in val_encoded], max_length, args.beta
                )
                log(
                    {
                        "type": "val",
                        "step": step,
                        "n": val_metrics["n"],
                        "dpo_loss": round(val_metrics["dpo_loss"], 5),
                        "margin": round(val_metrics["margin"], 5),
                        "acc": round(val_metrics["acc"], 5),
                        "reward_margin": round(val_metrics["reward_margin"], 5),
                        "elapsed_s": round(time.time() - started, 1),
                    }
                )
                model.train()
        epoch += 1

    peak_alloc = torch.cuda.max_memory_allocated() / 2**30
    peak_reserved = torch.cuda.max_memory_reserved() / 2**30

    final_val = evaluate(model, tokenizer, [r for r, _ in val_encoded], max_length, args.beta)
    final_train = (
        evaluate(model, tokenizer, [r for r, _ in encoded], max_length, args.beta)
        if not args.skip_train_eval
        else None
    )
    for name, part in (("val", final_val), ("train", final_train)):
        if part is None:
            continue
        log(
            {
                "type": "final_eval",
                "split": name,
                "n": part["n"],
                "dpo_loss": round(part["dpo_loss"], 5),
                "margin": round(part["margin"], 5),
                "acc": round(part["acc"], 5),
                "reward_margin": round(part["reward_margin"], 5),
                "pairs": part["pairs"],
            }
        )

    os.makedirs(adapter_dir, exist_ok=True)
    model.save_pretrained(adapter_dir)
    log(
        {
            "type": "adapter",
            "path": os.path.relpath(adapter_dir, ROOT),
            "retention_reason": (
                "adapter weights are 4-bit QLoRA deltas; regenerated only by rerunning "
                "scripts/train_dpo.py on the GPU session that is already booked"
            ),
        }
    )
    log(
        {
            "type": "peak_memory",
            "peak_allocated_gib": round(peak_alloc, 2),
            "peak_reserved_gib": round(peak_reserved, 2),
            "wall_clock_s": round(time.time() - started, 1),
            "steps": step,
        }
    )
    totals = {
        "val": {k: final_val[k] for k in ("n", "dpo_loss", "margin", "acc", "reward_margin")},
        "train": (
            {k: final_train[k] for k in ("n", "dpo_loss", "margin", "acc", "reward_margin")}
            if final_train
            else None
        ),
        "peak_allocated_gib": round(peak_alloc, 2),
        "peak_reserved_gib": round(peak_reserved, 2),
        "steps": step,
        "max_length": max_length,
        "token_stats": stats,
    }
    with open(os.path.join(args.out_dir, "train-summary.json"), "w", encoding="utf-8") as fh:
        json.dump(totals, fh, indent=2, ensure_ascii=False)
    print(json.dumps(totals, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
