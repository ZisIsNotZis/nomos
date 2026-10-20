#!/usr/bin/env python3
"""三点测量：同一批 242 条处境上，训练前基座与窄版适配器的动作一致率。

三个水平共用同一个 prompt：处境原文（excerpt）加上 slice-contrast 的续写指令，
**不含任何法条原文**。带法 DeepSeek 的多数动作是定义上的参照物（它在带法条件下
自己和自己一致，所以是 1.0），不带法 DeepSeek 是每处境存下来的 5 条 bare 回答里
与带法多数签名相同的那份比例。

  --generate  两个模型（base = 训练前基座，post = 窄版适配器）各对每条处境生成 3 条回答。
  --analyse   纯本地：算每处境的 X = (post - base) / (1 - base)，带按处境重采样的区间，
              并报一个不依赖评委的可数对照（回答里有没有可解析动作）。

用法：
  python3 scripts/measure_actions.py --generate
  python3 scripts/measure_actions.py --analyse
"""

import argparse
import importlib.util
import json
import math
import os
import random
import re
from pathlib import Path

import torch
from transformers import AutoModelForImageTextToText, AutoTokenizer

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SITUATION_FILES = (
    REPO / "evidence" / "slice-contrast" / "situations.jsonl",
    REPO / "evidence" / "grow" / "situations.jsonl",
)
SLICE_CONTRAST = REPO / "evidence" / "slice-contrast"
DENSIFY_ANSWERS = REPO / "evidence" / "densify" / "answers.jsonl"
EVIDENCE = REPO / "evidence" / "measure"
ANSWERS = EVIDENCE / "answers.jsonl"
PER_SITUATION = EVIDENCE / "per-situation.jsonl"
SUMMARY = EVIDENCE / "summary.json"

BASE_MODEL = Path("/home/z/hf/hub/models--Qwen--Qwen3.5-2B/snapshots/15852e8c16360a2fea060d615a32b45270f8a8fc")
ADAPTER = REPO / ".tmp" / "sft" / "adapter-narrow"

MODELS = ("base", "post")  # 训练前基座 / 窄版适配器（report/sft-training.md）
DRAWS = 3
TEMPERATURE = 0.7
TOP_P = 0.95
MAX_NEW_TOKENS = 320  # 与 evidence/qwen-base 同一上限，够 120 词的两倍余量
SEED = 20261031
BOOTSTRAP = 2000
SITUATIONS = 242
MIN_DRAWS = 3  # evidence/densify/answers.jsonl 每条处境每条件至少 3 条（多数是 3，少数 4）


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# 续写指令与动作签名都直接导入已有的家，不复制：指令是 DeepSeek 批次的原字节，
# 签名是 build_sft.py / resample_actions.py 用的同一套解析。
probe_common = load_module("slice_common", SLICE_CONTRAST / "common.py")
resample = load_module("resample_actions", HERE / "resample_actions.py")
build_sft = load_module("build_sft", HERE / "build_sft.py")
INSTRUCTION = probe_common.INSTRUCTION


def sha(text):
    return __import__("hashlib").sha256(text.encode()).hexdigest()


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def append(rows):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with ANSWERS.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def situations():
    """242 条处境：183 条 slice-contrast + 59 条 grow，顺序固定。"""
    rows = []
    for path in SITUATION_FILES:
        rows.extend(load_jsonl(path))
    assert len(rows) == SITUATIONS, f"{len(rows)} 条处境，期望 {SITUATIONS}"
    ids = [row["id"] for row in rows]
    assert len(set(ids)) == len(ids), "处境 id 重复"
    return rows


def prompts():
    """每条处境的 prompt，并断言里面没有法条原文。

    短语取自 build_sft.py 的 law_phrases()：175 条可训练规则里每条长度 ≥30 的首句，
    175 条短语在 242 条 prompt 里逐条查，命中即停。
    """
    phrases = build_sft.law_phrases()
    out = []
    for row in situations():
        prompt = row["excerpt"] + INSTRUCTION
        leaked = [path for path, phrase in phrases if phrase in prompt]
        if leaked:
            raise SystemExit(f"{row['id']}: prompt 含法条原文（{leaked[:3]}），拒绝继续")
        assert law_free_instruction(prompt)
        out.append({"id": row["id"], "prompt": prompt, "prompt_sha256": sha(prompt)})
    print(f"断言：{len(phrases)} 条法条短语 × {len(out)} 条 prompt，全部未出现")
    return out


def law_free_instruction(prompt):
    """prompt 就是 excerpt 加那条指令，一个字都不多，所以接不了第二样东西。

    处境原文本身会提到 `AGENTS.md`、`@ssot` 这类节点名（这些会话就是在改这份法的），
    所以这里只断言结构；法条原文的断言在同一处按 175 条独有短语查。
    """
    assert prompt.endswith(INSTRUCTION), "prompt 不是 excerpt 加同一条续写指令"
    return True


# --- 生成 ------------------------------------------------------------------


def done_keys():
    if not ANSWERS.exists():
        return set()
    return {(row["model"], row["situation"], row["draw"]) for row in load_jsonl(ANSWERS)}


def load_pair():
    tokenizer = AutoTokenizer.from_pretrained(str(BASE_MODEL))
    model = AutoModelForImageTextToText.from_pretrained(str(BASE_MODEL), dtype=torch.bfloat16).to("cuda").eval()
    return tokenizer, model


def attach_adapter(model):
    from peft import PeftModel

    if not (ADAPTER / "adapter_config.json").exists():
        raise SystemExit(f"{ADAPTER} 不存在；先按 report/sft-training.md 的复现命令重生成窄版适配器")
    return PeftModel.from_pretrained(model, str(ADAPTER)).eval()


def generate(tokenizer, model, prompt, seed):
    # 与训练同一条 prompt 模板：chat template + generation prompt，默认留空 think 块，
    # 训练时被掩掉的 assistant 前缀就是这一段（见 evidence/sft/log.jsonl 的 mask_check）。
    text = tokenizer.apply_chat_template(
        [{"role": "user", "content": prompt}], tokenize=False, add_generation_prompt=True
    )
    ids = tokenizer(text, return_tensors="pt", add_special_tokens=False).to("cuda")
    torch.manual_seed(seed)
    with torch.inference_mode():
        output = model.generate(
            **ids,
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=True,
            temperature=TEMPERATURE,
            top_p=TOP_P,
            top_k=None,
            pad_token_id=tokenizer.eos_token_id,
        )
    prompt_tokens = ids["input_ids"].shape[1]
    new_tokens = output.shape[1] - prompt_tokens
    response = tokenizer.decode(output[0, prompt_tokens:], skip_special_tokens=True).strip()
    return {
        "response": response,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": new_tokens,
        "finish_reason": "length" if new_tokens >= MAX_NEW_TOKENS else "eos",
        "truncated": new_tokens >= MAX_NEW_TOKENS,
    }


def run_generate():
    items = prompts()
    finished = done_keys()
    plan = [
        (model_name, item, draw)
        for model_name in MODELS
        for item in items
        for draw in range(DRAWS)
        if (model_name, item["id"], draw) not in finished
    ]
    if not plan:
        print("全部回答已落盘")
        return
    print(f"{len(items)} 条处境 × {len(MODELS)} 模型 × {DRAWS} 次抽样；待生成 {len(plan)} 条")

    tokenizer, model = load_pair()
    current = None
    written = 0
    for model_name, item, draw in plan:
        if model_name != current:
            if model_name == "post":
                print("挂窄版适配器", ADAPTER, flush=True)
                model = attach_adapter(model)
            current = model_name
            print(f"模型 {model_name} 开跑", flush=True)
        seed = SEED + draw
        out = generate(tokenizer, model, item["prompt"], seed)
        signatures = resample.signatures(out["response"])
        append(
            [
                {
                    "model": model_name,
                    "situation": item["id"],
                    "draw": draw,
                    "response": out["response"],
                    "action_signature": signatures["signature"],
                    "coarse_signature": signatures["coarse"],
                    **{key: out[key] for key in ("prompt_tokens", "completion_tokens", "finish_reason", "truncated")},
                    "prompt_sha256": item["prompt_sha256"],
                    "temperature": TEMPERATURE,
                    "top_p": TOP_P,
                    "seed": seed,
                }
            ]
        )
        written += 1
        if written % 25 == 0:
            print(f"  {written}/{len(plan)} 条落盘", flush=True)
    print(f"{ANSWERS} 共 {len(done_keys())} 行")


# --- 分析 ------------------------------------------------------------------


def signature_of(answer):
    return tuple(resample.signatures(answer)["signature"])


def densify_signatures():
    """每处境每条件（law / bare）的 5 条回答签名，以及 law 条件的多数签名。"""
    by_key = {}
    for row in load_jsonl(DENSIFY_ANSWERS):
        by_key.setdefault((row["situation"], row["arm"]), []).append(signature_of(row["response"]))
    result = {}
    for situation in {key[0] for key in by_key}:
        law = by_key.get((situation, "law"), [])
        bare = by_key.get((situation, "bare"), [])
        assert len(law) >= MIN_DRAWS and len(bare) >= MIN_DRAWS, (
            f"{situation}: {len(law)} 条带法 / {len(bare)} 条不带法，少于 {MIN_DRAWS}"
        )
        result[situation] = {"law": law, "bare": bare, "majority": majority(law)}
    return result


def majority(signatures):
    """出现次数最多的签名，平局取先出现的那条。"""
    counts = {}
    order = []
    for signature in signatures:
        if signature not in counts:
            counts[signature] = 0
            order.append(signature)
        counts[signature] += 1
    best = max(order, key=lambda signature: (counts[signature], -order.index(signature)))
    return best, counts[best]


def rate(flags):
    return sum(1 for flag in flags if flag) / len(flags)


def bootstrap_mean(values, seed):
    rng = random.Random(seed)
    n = len(values)
    samples = []
    for _ in range(BOOTSTRAP):
        samples.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    samples.sort()
    return samples[int(0.025 * BOOTSTRAP)], samples[int(0.975 * BOOTSTRAP) - 1]


def run_analyse(allow_partial=False):
    stored = densify_signatures()
    rows = load_jsonl(ANSWERS)
    by_key = {}
    for row in rows:
        by_key.setdefault((row["model"], row["situation"]), []).append(row)

    ids = [item["id"] for item in prompts()]
    complete, missing = [], []
    for situation in ids:
        draws = {name: by_key.get((name, situation), []) for name in MODELS}
        if all(len(draws[name]) == DRAWS for name in MODELS):
            complete.append((situation, draws))
        else:
            missing.append((situation, {name: len(draws[name]) for name in MODELS}))
    if missing and not allow_partial:
        raise SystemExit(f"缺 {len(missing)} 条处境的完整回答，先跑 --generate：{missing[:3]}")
    print(f"{len(complete)}/{len(ids)} 条处境两个模型各 {DRAWS} 条齐全；缺 {len(missing)} 条")

    per_situation = []
    for situation, draws in complete:
        reference = stored[situation]
        hit = {
            name: [signature_of(row["response"]) == reference["majority"][0] for row in draws[name]]
            for name in MODELS
        }
        base = rate(hit["base"])
        post = rate(hit["post"])
        bare_rate = rate([signature == reference["majority"][0] for signature in reference["bare"]])
        x = None if base >= 1.0 else (post - base) / (1.0 - base)
        per_situation.append(
            {
                "situation": situation,
                "law_deepseek": 1.0,
                "bare_deepseek": bare_rate,
                "bare_deepseek_majority_votes": reference["majority"][1],
                "law_draws": len(reference["law"]),
                "bare_draws": len(reference["bare"]),
                "majority_signature": list(reference["majority"][0]),
                "base": base,
                "post": post,
                "X": x,
                "base_emits_action": rate([bool(signature_of(row["response"])) for row in draws["base"]]),
                "post_emits_action": rate([bool(signature_of(row["response"])) for row in draws["post"]]),
                "truncated": sum(1 for name in MODELS for row in draws[name] if row["truncated"]),
            }
        )

    defined = [row for row in per_situation if row["X"] is not None]
    xs = [row["X"] for row in defined]
    bases = [row["base"] for row in per_situation]
    posts = [row["post"] for row in per_situation]
    bares = [row["bare_deepseek"] for row in per_situation]
    base_actions = [row["base_emits_action"] for row in per_situation]
    post_actions = [row["post_emits_action"] for row in per_situation]

    summary = {
        "situations_total": len(ids),
        "situations_complete": len(complete),
        "draws_per_model": DRAWS,
        "decoding": {"temperature": TEMPERATURE, "top_p": TOP_P, "max_new_tokens": MAX_NEW_TOKENS},
        "models": {"base": str(BASE_MODEL), "post": str(ADAPTER)},
        "reference": "evidence/densify/answers.jsonl law 条件的多数动作签名（每处境 3–4 条抽样）",
        "X_definition": "X = (post - base) / (1 - base)，单位是处境；base = 1 的处境 X 无定义",
        "X_mean": (sum(xs) / len(xs)) if xs else None,
        "X_ci": list(bootstrap_mean(xs, SEED + 1)) if xs else None,
        "X_defined": len(xs),
        "X_undefined_base_at_ceiling": len(per_situation) - len(xs),
        "base_mean": (sum(bases) / len(bases)) if bases else None,
        "base_ci": list(bootstrap_mean(bases, SEED + 2)) if bases else None,
        "post_mean": (sum(posts) / len(posts)) if posts else None,
        "post_ci": list(bootstrap_mean(posts, SEED + 3)) if posts else None,
        "bare_deepseek_mean": (sum(bares) / len(bares)) if bares else None,
        "bare_deepseek_ci": list(bootstrap_mean(bares, SEED + 4)) if bares else None,
        "law_deepseek": 1.0,
        "countable_control": {
            "what": "回答里有没有可解析动作（action_signature 非空），不经评委、不看参照物",
            "base_emits_action": (sum(base_actions) / len(base_actions)) if base_actions else None,
            "base_emits_action_ci": list(bootstrap_mean(base_actions, SEED + 5)) if base_actions else None,
            "post_emits_action": (sum(post_actions) / len(post_actions)) if post_actions else None,
            "post_emits_action_ci": list(bootstrap_mean(post_actions, SEED + 6)) if post_actions else None,
        },
        "truncated_answers": sum(row["truncated"] for row in per_situation),
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    PER_SITUATION.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in per_situation), encoding="utf-8"
    )
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true", help="两个模型各生成 3 条回答")
    parser.add_argument("--analyse", action="store_true", help="纯本地统计，不调模型")
    parser.add_argument("--allow-partial", action="store_true", help="分析已落盘的部分处境")
    args = parser.parse_args()
    if args.generate == args.analyse:
        raise SystemExit("选一个：--generate 或 --analyse")
    if args.generate:
        run_generate()
    else:
        run_analyse(args.allow_partial)


if __name__ == "__main__":
    main()
