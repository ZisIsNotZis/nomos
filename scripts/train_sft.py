#!/usr/bin/env python3
"""SFT on the 366 deduplicated situation -> law-answer samples: 4-bit QLoRA on Qwen3.5-2B.

Loss is computed on the target answer alone: every prompt token is masked to -100 and
each row asserts at run time that the first non-masked label position equals the prompt
length, so a template or tokenizer change that shifts the boundary fails here instead of
training on the prompt.

Truncation never cuts the target: the sequence length comes from the measured p95, and a
row longer than that loses tokens from the head of the prompt only, with the count logged.

Usage:
  python3 scripts/train_sft.py                     # full run: 3 epochs, writes adapter
  python3 scripts/train_sft.py --epochs 1 --limit 16   # smoke run
"""

import argparse
import hashlib
import json
import math
import os
import random
import time

# The 248k-token vocabulary at 1088 positions makes a full-vocabulary float32 softmax
# the largest allocation in the run; expandable segments keeps it from fragmenting.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import numpy as np
import torch
import torch.nn.functional as F
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import AutoModelForImageTextToText, AutoTokenizer, BitsAndBytesConfig

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_MODEL = "/home/z/hf/hub/models--Qwen--Qwen3.5-2B/snapshots/15852e8c16360a2fea060d615a32b45270f8a8fc"
TRAIN_PATH = os.path.join(ROOT, "data/sft-train.jsonl")
VAL_PATH = os.path.join(ROOT, "data/sft-val.jsonl")
OUT_DIR = os.path.join(ROOT, "evidence/sft")
LOG_PATH = os.path.join(OUT_DIR, "log.jsonl")
ADAPTER_DIR = os.path.join(ROOT, ".tmp/sft/adapter")

# Every linear projection in the language model: the answer's decision shape is carried
# by all of them, and this base is a hybrid. 6 of the 24 layers are full attention
# (q/k/v/o), 18 are linear attention, whose in_proj_qkv (q,k,v), in_proj_z (gate),
# in_proj_a and in_proj_b (decay scalars) and out_proj are the only projections that
# layer has. The suffixes match by full-name suffix, so the vision tower's `proj`,
# `qkv` and `linear_fc1/2` are not hit; report_lora_coverage() proves that at run time.
LORA_TARGET_MODULES = [
    "q_proj",
    "k_proj",
    "v_proj",
    "o_proj",
    "gate_proj",
    "up_proj",
    "down_proj",
    "in_proj_qkv",
    "in_proj_z",
    "in_proj_a",
    "in_proj_b",
    "out_proj",
]


def report_lora_coverage(model, log_fn):
    """Count the modules that actually carry a LoRA delta, per projection name.

    The expected count comes from the model's own `layer_types`, so a base whose hybrid
    layout differs fails here instead of silently leaving layers uncovered: every full
    attention layer owes q/k/v/o, every linear attention layer owes its five projections,
    and every layer owes the three MLP projections. Anything matched outside those names
    is a target suffix reaching into a part of the model it was not meant for.
    """
    layers = model.config.text_config.layer_types
    n_layers = len(layers)
    n_full = sum(1 for t in layers if t == "full_attention")
    n_linear = sum(1 for t in layers if t == "linear_attention")
    assert n_full + n_linear == n_layers, f"unknown layer type in {set(layers)}"
    expected = {
        "q_proj": n_full,
        "k_proj": n_full,
        "v_proj": n_full,
        "o_proj": n_full,
        "gate_proj": n_layers,
        "up_proj": n_layers,
        "down_proj": n_layers,
        "in_proj_qkv": n_linear,
        "in_proj_z": n_linear,
        "in_proj_a": n_linear,
        "in_proj_b": n_linear,
        "out_proj": n_linear,
    }
    actual = {}
    examples = {}
    for name, module in model.named_modules():
        if not hasattr(module, "lora_A") or not len(module.lora_A):
            continue
        leaf = name.split(".")[-1]
        actual[leaf] = actual.get(leaf, 0) + 1
        examples.setdefault(leaf, name)
    assert actual == {k: v for k, v in expected.items() if v}, (
        f"LoRA coverage {sorted(actual.items())} != expected {sorted(expected.items())}"
    )
    layer_coverage = {}
    for leaf in actual:
        owner = "linear_attn" if leaf in {"in_proj_qkv", "in_proj_z", "in_proj_a", "in_proj_b", "out_proj"} else (
            "self_attn" if leaf in {"q_proj", "k_proj", "v_proj", "o_proj"} else "mlp"
        )
        layer_coverage[owner] = layer_coverage.get(owner, 0) + actual[leaf]
    log_fn(
        {
            "type": "lora_coverage",
            "modules_per_name": dict(sorted(actual.items())),
            "modules_total": sum(actual.values()),
            "lora_tensors": 2 * sum(actual.values()),
            "example_module": dict(sorted(examples.items())),
            "layer_types": {"linear_attention": n_linear, "full_attention": n_full},
            "projections_by_owner": layer_coverage,
            "expected_layers_covered": n_layers,
        }
    )
    print(
        f"LoRA modules {sum(actual.values())} = {dict(sorted(actual.items()))}; "
        f"{n_linear} linear-attention layers x 5 projections + {n_full} full-attention "
        f"layers x 4 + {n_layers} MLP x 3"
    )
    return actual


def log(record):
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_rows(path):
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    for row in rows:
        assert isinstance(row["prompt"], str) and row["prompt"].strip(), "empty prompt"
        assert isinstance(row["target"], str) and row["target"].strip(), "empty target"
        assert row["situation_id"] and row["session_id"], "missing ids"
    return rows


def encode_row(tokenizer, row, max_length):
    """Prompt in the chat template, target as the completion plus end-of-turn.

    Returns (ids, prompt_len, dropped). A row longer than max_length drops `dropped`
    tokens from the head of the prompt; the target is never touched.
    """
    prompt_text = tokenizer.apply_chat_template(
        [{"role": "user", "content": row["prompt"]}], tokenize=False, add_generation_prompt=True
    )
    prompt_ids = tokenizer(prompt_text, add_special_tokens=False).input_ids
    target_ids = tokenizer(row["target"], add_special_tokens=False).input_ids + [tokenizer.eos_token_id]
    assert len(target_ids) < max_length, (
        f"{row['situation_id']}: target alone ({len(target_ids)} tokens) exceeds "
        f"max_length {max_length}; a length chosen from p95 must still hold every target"
    )
    dropped = max(0, len(prompt_ids) + len(target_ids) - max_length)
    prompt_ids = prompt_ids[dropped:]
    assert prompt_ids, f"{row['situation_id']}: truncation consumed the whole prompt"
    ids = prompt_ids + target_ids
    assert len(ids) <= max_length
    assert ids[len(prompt_ids):] == target_ids, "truncation cut into the target"
    return ids, len(prompt_ids), dropped


def length_stats(tokenizer, rows):
    prompt_len, target_len, total_len = [], [], []
    for row in rows:
        prompt_text = tokenizer.apply_chat_template(
            [{"role": "user", "content": row["prompt"]}], tokenize=False, add_generation_prompt=True
        )
        p = len(tokenizer(prompt_text, add_special_tokens=False).input_ids)
        t = len(tokenizer(row["target"], add_special_tokens=False).input_ids) + 1
        prompt_len.append(p)
        target_len.append(t)
        total_len.append(p + t)
    stats = {}
    for key, values in (("prompt", prompt_len), ("target", target_len), ("prompt_plus_target", total_len)):
        arr = np.array(values)
        stats[key] = {
            "p50": int(np.percentile(arr, 50)),
            "p95": int(np.percentile(arr, 95)),
            "max": int(arr.max()),
            "mean": round(float(arr.mean()), 1),
        }
    return stats


def choose_max_length(stats, pad_to=64):
    """p95 of prompt+target, rounded up to a multiple of pad_to."""
    p95 = stats["prompt_plus_target"]["p95"]
    return int(math.ceil(p95 / pad_to) * pad_to)


def choose_lora(free_gib):
    """Rank and scale from the memory actually free before the model is loaded.

    The 2B base in 4-bit nf4 with double quant occupies ~1.4 GiB of weights, and the
    activation peak for a micro-batch of 4 x 1088 tokens under gradient checkpointing
    stays well under 2 GiB, so the rank is set by what is left rather than by the base
    model: r=16 when >=12 GiB is free, r=8 at >=8 GiB, r=4 below that. alpha = 2r keeps
    the delta scale at the ratio the earlier 4-bit DPO run on this GPU used.
    """
    if free_gib >= 12:
        r = 16
    elif free_gib >= 8:
        r = 8
    else:
        r = 4
    return r, 2 * r


def choose_micro_batch(free_gib, max_length, vocab=248320):
    """Largest micro-batch whose logits and their gradient fit in a third of free memory.

    This model emits float32 logits even with a bf16 compute dtype (measured: one
    1088-token sample is [1, 1088, 248320] float32 = 1.08 GiB), and backward needs a
    gradient of the same size, so one sample costs ~2.2 GiB. The 4-bit weights and the
    activation peak are another ~2.8 GiB and are not part of this term; a third of free
    memory on top of that still leaves several GiB for the other project on the card.
    """
    per_sample_gib = 2 * max_length * vocab * 4 / 2**30
    budget = max(per_sample_gib, free_gib * 0.35)
    return max(1, min(4, int(budget // per_sample_gib)))


def collate(rows_enc, tokenizer, max_length):
    """Right-pad a micro-batch; labels are -100 on prompt, pad and beyond-sequence."""
    pad_id = tokenizer.pad_token_id
    width = max(len(ids) for ids, _, _ in rows_enc)
    assert width <= max_length
    input_ids = torch.full((len(rows_enc), width), pad_id, dtype=torch.long)
    attention = torch.zeros((len(rows_enc), width), dtype=torch.long)
    labels = torch.full((len(rows_enc), width), -100, dtype=torch.long)
    for i, (ids, prompt_len, _) in enumerate(rows_enc):
        n = len(ids)
        input_ids[i, :n] = torch.tensor(ids, dtype=torch.long)
        attention[i, :n] = 1
        labels[i, prompt_len:n] = torch.tensor(ids[prompt_len:], dtype=torch.long)
    return input_ids, attention, labels


def assert_mask(labels, attention, prompt_len, situation_id):
    """The first scorable label sits exactly at the prompt boundary, for every row."""
    valid = (labels != -100).nonzero().flatten()
    assert valid.numel() > 0, f"{situation_id}: no target tokens to score"
    first = int(valid[0])
    assert first == prompt_len, (
        f"{situation_id}: first valid label at {first}, prompt length {prompt_len}"
    )
    n = int(attention.sum())
    assert int(valid.min()) == prompt_len and int(valid.max()) == n - 1
    assert int(valid.numel()) == n - prompt_len, f"{situation_id}: gap in target labels"


def target_loss(model, input_ids, attention, prompt_lens, seq_lens, chunk=128):
    """Cross-entropy over target tokens only, summed, with the token count.

    The softmax runs on the positions that carry a label, in row chunks, instead of on
    the full [batch, sequence, vocab] tensor: at 248k vocabulary tokens the single
    full-vocabulary float32 upcast of one batch is several GiB, more than the model.
    Labels are contiguous per row (asserted by assert_mask), so each row's target is the
    slice [prompt_len - 1, n - 1) of the shifted logits.
    """
    out = model(input_ids=input_ids.to("cuda"), attention_mask=attention.to("cuda"))
    logits = out.logits
    total = torch.zeros((), dtype=torch.float32, device=logits.device)
    tokens = 0
    for i, (prompt_len, n) in enumerate(zip(prompt_lens, seq_lens)):
        start, end = prompt_len - 1, n - 1
        for c0 in range(start, end, chunk):
            c1 = min(end, c0 + chunk)
            block = logits[i, c0:c1].float()
            target = input_ids[i, c0 + 1 : c1 + 1].to("cuda")
            total = total + F.cross_entropy(block, target, reduction="sum")
            del block
        tokens += end - start
    del logits, out
    return total, tokens


def evaluate(model, enc_rows, tokenizer, micro_batch, max_length):
    """Mean cross-entropy over target tokens and its perplexity, adapter enabled."""
    model.eval()
    total_loss, total_tokens = 0.0, 0
    with torch.no_grad():
        for start in range(0, len(enc_rows), micro_batch):
            chunk = enc_rows[start : start + micro_batch]
            input_ids, attention, labels = collate(chunk, tokenizer, max_length)
            for i, (_, prompt_len, _) in enumerate(chunk):
                assert_mask(labels[i], attention[i], prompt_len, "eval")
            summed, n = target_loss(
                model,
                input_ids,
                attention,
                [p for _, p, _ in chunk],
                [len(ids) for ids, _, _ in chunk],
            )
            total_loss += float(summed)
            total_tokens += n
    model.train()
    mean_loss = total_loss / total_tokens
    return {"n": len(enc_rows), "tokens": total_tokens, "loss": mean_loss, "ppl": math.exp(mean_loss)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--micro-batch", type=int, default=0, help="0 = choose from free VRAM")
    parser.add_argument("--grad-accum", type=int, default=4)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--lora-r", type=int, default=0, help="0 = choose from free VRAM")
    parser.add_argument("--lora-alpha", type=int, default=0, help="0 = 2r")
    parser.add_argument("--eval-micro-batch", type=int, default=0, help="0 = same as micro-batch")
    parser.add_argument("--limit", type=int, default=0, help="smoke run: cap training rows")
    parser.add_argument("--out-dir", default=OUT_DIR)
    parser.add_argument(
        "--run-name", default="", help="suffix for the evidence files, so a run never overwrites another"
    )
    parser.add_argument("--adapter-dir", default=ADAPTER_DIR)
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    log_path = os.path.join(args.out_dir, f"log{args.run_name and '-' + args.run_name}.jsonl")
    global LOG_PATH
    LOG_PATH = log_path
    open(LOG_PATH, "w").close()
    adapter_dir = args.adapter_dir

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    np.random.seed(args.seed)

    rows = load_rows(TRAIN_PATH)
    val_rows = load_rows(VAL_PATH)
    train_ids = {r["session_id"] for r in rows}
    val_ids = {r["session_id"] for r in val_rows}
    assert not (train_ids & val_ids), "validation session leaked into training"
    if args.limit:
        rows = rows[: args.limit]

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    stats = length_stats(tokenizer, rows + val_rows)
    max_length = choose_max_length(stats)

    free_gib = torch.cuda.mem_get_info(0)[0] / 2**30
    micro_batch = args.micro_batch or choose_micro_batch(free_gib, max_length)
    eval_micro_batch = args.eval_micro_batch or micro_batch
    if args.lora_r:
        lora_r = args.lora_r
        lora_alpha = args.lora_alpha or 2 * lora_r
        lora_rank_reason = (
            f"pinned on the command line to r={lora_r}, alpha={lora_alpha}, so a comparison "
            f"against another LoRA width holds the rank, alpha and fp math equal instead of "
            f"letting the {free_gib:.1f} GiB free at start pick a different rank"
        )
    else:
        lora_r, lora_alpha = choose_lora(free_gib)
        lora_rank_reason = (
            f"{free_gib:.1f} GiB free before load (4090, another project holds the rest); "
            f"r={lora_r}, alpha={lora_alpha} (alpha = 2r); 4-bit weights ~1.4 GiB and "
            f"micro-batch {micro_batch} x {max_length} tokens under gradient checkpointing "
            f"fit, so the rank is set by the free headroom"
        )

    log(
        {
            "type": "setup",
            "train_rows": len(rows),
            "val_rows": len(val_rows),
            "train_sessions": len(train_ids),
            "val_sessions": len(val_ids),
            "token_stats": stats,
            "max_length": max_length,
            "max_length_reason": (
                f"p95 of prompt+target is {stats['prompt_plus_target']['p95']} tokens "
                f"(p50 {stats['prompt_plus_target']['p50']}, max {stats['prompt_plus_target']['max']}); "
                f"rounded up to {max_length}. Rows above it lose the head of the prompt only"
            ),
            "gpu_name": torch.cuda.get_device_name(0),
            "gpu_free_gib_at_start": round(free_gib, 2),
            "versions": {
                "torch": torch.__version__,
                "transformers": __import__("transformers").__version__,
                "peft": __import__("peft").__version__,
                "bitsandbytes": __import__("bitsandbytes").__version__,
            },
        }
    )
    print(f"token stats {stats}")
    print(f"max_length {max_length} (p95), free {free_gib:.1f} GiB")

    train_enc = [encode_row(tokenizer, row, max_length) for row in rows]
    val_enc = [encode_row(tokenizer, row, max_length) for row in val_rows]
    truncated = [
        (row["situation_id"], dropped)
        for row, (_, _, dropped) in zip(rows, train_enc)
        if dropped
    ]
    truncated_val = [(row["situation_id"], d) for row, (_, _, d) in zip(val_rows, val_enc) if d]
    log(
        {
            "type": "truncation",
            "train_rows_truncated": len(truncated),
            "train_tokens_dropped": sum(d for _, d in truncated),
            "val_rows_truncated": len(truncated_val),
            "val_tokens_dropped": sum(d for _, d in truncated_val),
            "max_train_dropped": max([d for _, d in truncated], default=0),
            "note": "tokens dropped from the head of the prompt; target never truncated",
            "train_examples": truncated[:5],
        }
    )
    print(f"truncated {len(truncated)}/{len(train_enc)} train rows (prompt head only)")

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
    model = get_peft_model(
        model,
        LoraConfig(
            r=lora_r,
            lora_alpha=lora_alpha,
            lora_dropout=0.05,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=LORA_TARGET_MODULES,
        ),
    )
    report_lora_coverage(model, log)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    log(
        {
            "type": "config",
            "base_model": BASE_MODEL,
            "quantization": "4-bit nf4, double quant, bf16 compute",
            "lora_targets": LORA_TARGET_MODULES,
            "lora_r": lora_r,
            "lora_alpha": lora_alpha,
            "lora_dropout": 0.05,
            "lora_rank_reason": lora_rank_reason,
            "trainable_params": trainable,
            "total_params": total,
            "trainable_fraction": round(trainable / total, 5),
            "micro_batch": micro_batch,
            "eval_micro_batch": eval_micro_batch,
            "grad_accum": args.grad_accum,
            "effective_batch": micro_batch * args.grad_accum,
            "lr": args.lr,
            "epochs": args.epochs,
            "seed": args.seed,
            "optimizer": "paged_adamw_8bit",
            "max_length": max_length,
        }
    )

    import bitsandbytes as bnb

    optim = bnb.optim.PagedAdamW8bit(
        [p for p in model.parameters() if p.requires_grad], lr=args.lr, weight_decay=0.0
    )
    rows_per_step = micro_batch * args.grad_accum
    steps_per_epoch = math.ceil(len(train_enc) / rows_per_step)
    total_steps = max(1, int(steps_per_epoch * args.epochs))
    warmup = min(5, max(1, total_steps // 10))
    sched = torch.optim.lr_scheduler.LambdaLR(
        optim,
        lambda s: min(1.0, (s + 1) / warmup)
        * max(0.0, 1.0 - max(0, s - warmup) / max(1, total_steps - warmup)),
    )
    print(f"steps/epoch {steps_per_epoch}, total {total_steps}")

    model.train()
    torch.cuda.reset_peak_memory_stats()
    started = time.time()

    baseline = evaluate(model, val_enc, tokenizer, eval_micro_batch, max_length)
    log({"type": "val", "epoch": 0, "step": 0, "split": "val_before_training", **{
        k: (round(v, 6) if isinstance(v, float) else v) for k, v in baseline.items()
    }, "elapsed_s": round(time.time() - started, 1)})
    print(f"baseline val loss {baseline['loss']:.4f} ppl {baseline['ppl']:.2f}")

    grad_checked = False
    step = 0
    epoch = 0
    mask_printed = False
    while epoch < args.epochs and step < total_steps:
        order = list(range(len(train_enc)))
        random.Random(args.seed + epoch).shuffle(order)
        epoch_loss, epoch_tokens = 0.0, 0
        for start in range(0, len(order), rows_per_step):
            chunk = [train_enc[i] for i in order[start : start + rows_per_step]]
            if not chunk:
                continue
            step_loss_sum, step_tokens = 0.0, 0
            for m in range(0, len(chunk), micro_batch):
                micro = chunk[m : m + micro_batch]
                input_ids, attention, labels = collate(micro, tokenizer, max_length)
                for i, (ids, prompt_len, _) in enumerate(micro):
                    assert_mask(labels[i], attention[i], prompt_len, "train")
                if not mask_printed:
                    first = micro[0]
                    print(
                        "mask check: first valid label index",
                        int((labels[0] != -100).nonzero()[0]),
                        "== prompt_len",
                        first[1],
                        "| masked prompt tail",
                        repr(tokenizer.decode(first[0][max(0, first[1] - 12) : first[1]])),
                        "| first target tokens",
                        repr(tokenizer.decode(first[0][first[1] : first[1] + 12])),
                        "| target tokens scored",
                        int((labels[0] != -100).sum()),
                    )
                    log(
                        {
                            "type": "mask_check",
                            "prompt_tokens": first[1],
                            "first_valid_label_index": int((labels[0] != -100).nonzero()[0]),
                            "scored_target_tokens": int((labels[0] != -100).sum()),
                            "masked_to_neg100": int((labels[0] == -100).sum()),
                            "prompt_tail": tokenizer.decode(first[0][max(0, first[1] - 12) : first[1]]),
                            "target_head": tokenizer.decode(first[0][first[1] : first[1] + 12]),
                        }
                    )
                    mask_printed = True
                summed, n_tokens = target_loss(
                    model,
                    input_ids,
                    attention,
                    [p for _, p, _ in micro],
                    [len(ids) for ids, _, _ in micro],
                )
                loss = summed / n_tokens
                assert torch.isfinite(loss), f"step {step}: non-finite loss {loss.item()}"
                (summed / (n_tokens * args.grad_accum)).backward()
                del summed
                if not grad_checked:
                    lora_grads = [
                        (name, p.grad)
                        for name, p in model.named_parameters()
                        if p.requires_grad and p.grad is not None
                    ]
                    nonzero = sum(int((g != 0).sum()) for _, g in lora_grads)
                    nonzero_params = sum(1 for _, g in lora_grads if bool((g != 0).any()))
                    print(
                        f"LoRA grads after first backward: {nonzero_params}/{len(lora_grads)} tensors, "
                        f"{nonzero} nonzero entries"
                    )
                    assert nonzero > 0, "LoRA parameters received no gradient"
                    log(
                        {
                            "type": "gradient_check",
                            "lora_grad_tensors": len(lora_grads),
                            "tensors_with_nonzero_grad": nonzero_params,
                            "nonzero_grad_entries": nonzero,
                        }
                    )
                    grad_checked = True
                step_loss_sum += float(loss.detach()) * n_tokens
                step_tokens += n_tokens
                epoch_loss += float(loss.detach()) * n_tokens
                epoch_tokens += n_tokens
            optim.step()
            sched.step()
            optim.zero_grad(set_to_none=True)
            step += 1
            step_loss = step_loss_sum / max(1, step_tokens)
            log(
                {
                    "type": "train_step",
                    "step": step,
                    "epoch": epoch + 1,
                    "loss": round(step_loss, 6),
                    "rows": len(chunk),
                    "target_tokens": step_tokens,
                    "lr": round(sched.get_last_lr()[0], 8),
                    "elapsed_s": round(time.time() - started, 1),
                }
            )
            if step % 10 == 0:
                print(
                    f"step {step}/{total_steps} loss {step_loss:.4f} "
                    f"({time.time() - started:.0f}s)"
                )
        epoch += 1
        train_metrics = evaluate(model, train_enc, tokenizer, eval_micro_batch, max_length)
        val_metrics = evaluate(model, val_enc, tokenizer, eval_micro_batch, max_length)
        log(
            {
                "type": "epoch",
                "epoch": epoch,
                "step": step,
                "train_loss": round(train_metrics["loss"], 6),
                "train_ppl": round(train_metrics["ppl"], 4),
                "val_loss": round(val_metrics["loss"], 6),
                "val_ppl": round(val_metrics["ppl"], 4),
                "val_minus_train": round(val_metrics["loss"] - train_metrics["loss"], 6),
                "train_tokens": train_metrics["tokens"],
                "val_tokens": val_metrics["tokens"],
                "epoch_mean_step_loss": round(epoch_loss / max(1, epoch_tokens), 6),
                "elapsed_s": round(time.time() - started, 1),
            }
        )
        print(
            f"epoch {epoch}: train loss {train_metrics['loss']:.4f} ppl {train_metrics['ppl']:.2f} "
            f"| val loss {val_metrics['loss']:.4f} ppl {val_metrics['ppl']:.2f}"
        )
        model.train()

    peak_alloc = torch.cuda.max_memory_allocated() / 2**30
    peak_reserved = torch.cuda.max_memory_reserved() / 2**30
    nvidia_used = None
    try:
        import subprocess

        nvidia_used = (
            subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
    except Exception as exc:  # noqa: BLE001 - a missing sampler must not hide the run
        nvidia_used = f"unavailable: {exc}"

    final_train = evaluate(model, train_enc, tokenizer, eval_micro_batch, max_length)
    final_val = evaluate(model, val_enc, tokenizer, eval_micro_batch, max_length)
    log(
        {
            "type": "final_eval",
            "train_loss": round(final_train["loss"], 6),
            "train_ppl": round(final_train["ppl"], 4),
            "val_loss": round(final_val["loss"], 6),
            "val_ppl": round(final_val["ppl"], 4),
            "baseline_val_loss": round(baseline["loss"], 6),
            "baseline_val_ppl": round(baseline["ppl"], 4),
            "val_loss_delta": round(final_val["loss"] - baseline["loss"], 6),
        }
    )

    os.makedirs(adapter_dir, exist_ok=True)
    model.save_pretrained(adapter_dir)
    weights = os.path.join(adapter_dir, "adapter_model.safetensors")
    sha = hashlib.sha256(open(weights, "rb").read()).hexdigest()
    size = os.path.getsize(weights)
    log(
        {
            "type": "adapter",
            "path": os.path.relpath(adapter_dir, ROOT),
            "weights_file": os.path.relpath(weights, ROOT),
            "sha256": sha,
            "size_bytes": size,
            "trainable_params": trainable,
            "retention_reason": (
                "LoRA deltas regenerated only by rerunning scripts/train_sft.py on this GPU"
            ),
        }
    )
    log(
        {
            "type": "peak_memory",
            "peak_allocated_gib": round(peak_alloc, 3),
            "peak_reserved_gib": round(peak_reserved, 3),
            "nvidia_smi_used_mib": nvidia_used,
            "wall_clock_s": round(time.time() - started, 1),
            "steps": step,
            "epochs": epoch,
        }
    )

    summary = {
        "steps": step,
        "epochs": epoch,
        "max_length": max_length,
        "train_rows": len(train_enc),
        "val_rows": len(val_enc),
        "train_loss": round(final_train["loss"], 6),
        "train_ppl": round(final_train["ppl"], 4),
        "val_loss": round(final_val["loss"], 6),
        "val_ppl": round(final_val["ppl"], 4),
        "baseline_val_loss": round(baseline["loss"], 6),
        "baseline_val_ppl": round(baseline["ppl"], 4),
        "adapter_sha256": sha,
        "adapter_size_bytes": size,
        "peak_allocated_gib": round(peak_alloc, 3),
        "peak_reserved_gib": round(peak_reserved, 3),
        "wall_clock_s": round(time.time() - started, 1),
    }
    summary_path = os.path.join(args.out_dir, f"train-summary{args.run_name and '-' + args.run_name}.json")
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
