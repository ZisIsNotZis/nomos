#!/usr/bin/env python3
"""Gate 2 and 3: can Qwen3.5-2B produce a decidable next turn in this format?

Two conditions per situation, greedy decoding, thinking disabled:

- `bare`: no system message.
- `law`:  system message = the exact bytes of /home/z/vibe/AGENTS.md.

The situation text and the continuation instruction are probe 4's exact bytes
(report/gate-base/build_situations.py). Every call is appended to
generations.jsonl, so a killed run resumes. Timing, prompt/output token counts
and finish reason are recorded per row; run-meta.json carries the model
identity, decoding parameters and the aggregate throughput.

Usage: python3 report/gate-base/run_generate.py
"""

import hashlib
import json
import time
from pathlib import Path

import torch
from transformers import AutoModelForImageTextToText, AutoTokenizer

HERE = Path(__file__).resolve().parent
NOMOS = HERE.parents[1]
SITUATIONS = HERE / "situations.jsonl"
GENERATIONS = HERE / "generations.jsonl"
META = HERE / "run-meta.json"
POLICY_PATH = Path("/home/z/vibe/AGENTS.md")

MODEL_ID = "Qwen/Qwen3.5-2B"
REVISION = "15852e8c16360a2fea060d615a32b45270f8a8fc"
MODEL_DIR = Path("/home/z/hf/hub/models--Qwen--Qwen3.5-2B/snapshots") / REVISION
MAX_NEW_TOKENS = 320  # headroom over the 120-word ask; hitting it is recorded as truncated
CONDITIONS = ("bare", "law")


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def load_rows():
    return [json.loads(line) for line in SITUATIONS.read_text().splitlines() if line.strip()]


def done_keys():
    if not GENERATIONS.exists():
        return set()
    keys = set()
    for line in GENERATIONS.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            keys.add((row["situation"], row["condition"]))
    return keys


def append(row):
    with GENERATIONS.open("a") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main():
    policy = POLICY_PATH.read_text()
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR))
    model = AutoModelForImageTextToText.from_pretrained(
        str(MODEL_DIR), dtype=torch.bfloat16
    ).to("cuda").eval()

    situations = load_rows()
    finished = done_keys()
    pending = [(s, c) for s in situations for c in CONDITIONS if (s["id"], c) not in finished]
    print(f"{len(situations)} situations x {len(CONDITIONS)} conditions; {len(pending)} calls pending")

    rows = []
    for index, (situation, condition) in enumerate(pending, 1):
        system = "" if condition == "bare" else policy
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": situation["prompt"]}]
        text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        ids = tokenizer(text, return_tensors="pt", add_special_tokens=False).to("cuda")
        prompt_tokens = ids["input_ids"].shape[1]

        # Prefill timing on its own, so decode rate can be separated from it.
        torch.cuda.synchronize()
        start = time.time()
        with torch.inference_mode():
            model(**ids, logits_to_keep=1)
        torch.cuda.synchronize()
        prefill_seconds = time.time() - start

        torch.cuda.synchronize()
        start = time.time()
        with torch.inference_mode():
            output = model.generate(
                **ids,
                max_new_tokens=MAX_NEW_TOKENS,
                do_sample=False,
                temperature=None,
                top_p=None,
                top_k=None,
                pad_token_id=tokenizer.eos_token_id,
            )
        torch.cuda.synchronize()
        seconds = time.time() - start

        new_tokens = output.shape[1] - prompt_tokens
        answer = tokenizer.decode(output[0, prompt_tokens:], skip_special_tokens=True)
        truncated = new_tokens >= MAX_NEW_TOKENS
        row = {
            "situation": situation["id"],
            "source_id": situation["source_id"],
            "signal": situation["signal"],
            "condition": condition,
            "system_chars": len(system),
            "system_sha256": sha(system) if system else None,
            "prompt_sha256": situation["prompt_sha256"],
            "output": answer,
            "output_chars": len(answer),
            "output_words": len(answer.split()),
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": new_tokens},
            "finish_reason": "length" if truncated else "eos",
            "truncated": truncated,
            "seconds": round(seconds, 3),
            "prefill_seconds": round(prefill_seconds, 3),
            "decode_seconds": round(max(seconds - prefill_seconds, 1e-6), 3),
            "prefill_tokens_per_second": round(prompt_tokens / max(prefill_seconds, 1e-6), 1),
            "tokens_per_second": round(new_tokens / max(seconds, 1e-6), 2),
            "peak_gpu_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2),
        }
        append(row)
        rows.append(row)
        print(f"[{index}/{len(pending)}] {situation['id']} {condition:<4} "
              f"prompt={prompt_tokens:>6} out={new_tokens:>3} {row['tokens_per_second']:>6} tok/s "
              f"{seconds:>6.1f}s{' TRUNC' if truncated else ''}", flush=True)

    all_rows = [json.loads(line) for line in GENERATIONS.read_text().splitlines() if line.strip()]
    meta = {
        "model_id": MODEL_ID,
        "revision": REVISION,
        "model_dir": str(MODEL_DIR),
        "model_class": type(model).__name__,
        "parameters": sum(p.numel() for p in model.parameters()),
        "dtype": "bfloat16",
        "precision_note": "no quantization; no vllm, no bitsandbytes",
        "kernel_note": "transformers eager path; causal_conv1d and flash-linear-attention "
                       "are not installed, so the linear-attention layers run their reference "
                       "PyTorch implementation (transformers warns about this at load)",
        "decoding": {"temperature": 0.0, "do_sample": False, "max_new_tokens": MAX_NEW_TOKENS},
        "thinking": "disabled (chat template emits an empty <think></think> block)",
        "instruction_sha256": sha(
            "\n\n---\n"
            "Write the single next assistant turn for the conversation above: at most 120 words. "
            "If a tool call would be used, render it as `tool: name(args)`."),
        "policy_sha256": sha(policy),
        "policy_chars": len(policy),
        "conditions": {"bare": "no system message", "law": "system message = AGENTS.md bytes"},
        "situations": len({row["situation"] for row in all_rows}),
        "calls": len(all_rows),
        "gpu": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "transformers": __import__("transformers").__version__,
    }
    for condition in CONDITIONS:
        subset = [row for row in all_rows if row["condition"] == condition]
        meta[f"{condition}_totals"] = {
            "calls": len(subset),
            "seconds": round(sum(row["seconds"] for row in subset), 2),
            "prompt_tokens": sum(row["usage"]["prompt_tokens"] for row in subset),
            "completion_tokens": sum(row["usage"]["completion_tokens"] for row in subset),
            "mean_tokens_per_second": round(
                sum(row["tokens_per_second"] for row in subset) / len(subset), 2),
            "median_tokens_per_second": round(
                sorted(row["tokens_per_second"] for row in subset)[len(subset) // 2], 2),
            "mean_prefill_tokens_per_second": round(
                sum(row["prefill_tokens_per_second"] for row in subset) / len(subset), 1),
        }
    META.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: meta[k] for k in ("bare_totals", "law_totals")}, indent=2))


if __name__ == "__main__":
    main()
