#!/usr/bin/env python3
"""三点测量：同一批 242 条处境上，训练前基座与窄版适配器的动作一致率。

三个水平共用同一个 prompt：处境原文（excerpt）加上 slice-contrast 的续写指令，
**不含任何法条原文**。带法 DeepSeek 的多数动作是定义上的参照物，不带法 DeepSeek 是
每处境存下来的 3–4 条 bare 回答里与带法多数签名相同的那份比例。参照物只在
「带法侧至少 2 条抽样给出同一签名」且「该签名非空」时才算定下来，口径见
report/sft-measurement.md 的「口径」一节。

  --generate   两个模型（base = 训练前基座，post = 窄版适配器）各对每条处境生成 3 条回答。
  --analyse    纯本地：base / post 的每处境一致率、X = (post_mean - base_mean) / (1 - base_mean)
               与按处境重采样的区间，外加一个不依赖评委的可数对照。只在两侧齐全时写终版输出。
  --preliminary 同上，但只写 evidence/measure/preliminary.*，标 status=preliminary，绝不写终版路径。
  --check      三组假数据自检 X 与区间，写 evidence/measure/selftest.json。

用法：
  python3 scripts/measure_actions.py --generate
  python3 scripts/measure_actions.py --analyse
  python3 scripts/measure_actions.py --analyse --preliminary
  python3 scripts/measure_actions.py --check
"""

import argparse
import importlib.util
import json
import random
from pathlib import Path

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
PRELIMINARY = EVIDENCE / "preliminary.json"
PRELIMINARY_PER_SITUATION = EVIDENCE / "preliminary-per-situation.jsonl"
SELFTEST = EVIDENCE / "selftest.json"

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
MIN_REFERENCE_VOTES = 2  # 带法侧至少 2 条抽样给出同一签名，参照物才定下来
NEAR_CEILING_HEADROOM = 0.2  # 1 - base 小于这个值时报出 X 但标为接近满值


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
    # torch / transformers 只在生成时导入（--analyse / --check 是纯本地统计，不碰 GPU）
    import torch
    from transformers import AutoModelForImageTextToText, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(BASE_MODEL))
    model = AutoModelForImageTextToText.from_pretrained(str(BASE_MODEL), dtype=torch.bfloat16).to("cuda").eval()
    return tokenizer, model


def attach_adapter(model):
    from peft import PeftModel

    if not (ADAPTER / "adapter_config.json").exists():
        raise SystemExit(f"{ADAPTER} 不存在；先按 report/sft-training.md 的复现命令重生成窄版适配器")
    return PeftModel.from_pretrained(model, str(ADAPTER)).eval()


def generate(tokenizer, model, prompt, seed):
    import torch

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


def majority(signatures):
    """出现次数最多的签名，平局取先出现的那条。

    返回 (签名, 票数)。票数 1 不是多数——三条抽样各不相同也走这条路，所以调用方必须看
    票数决定参照物是否定下来（MIN_REFERENCE_VOTES）。
    """
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
    """命中比例；空列表返回 None。少于一条抽样时不是 0 而是一个缺失的值。"""
    values = [1.0 if flag else 0.0 for flag in flags]
    return mean(values)


def mean(values):
    return sum(values) / len(values) if values else None


def percentile_interval(samples):
    """2.5% / 97.5% 分位区间；样本为空时 None。"""
    if not samples:
        return None
    ordered = sorted(samples)
    low = ordered[min(len(ordered) - 1, int(0.025 * len(ordered)))]
    high = ordered[max(0, int(0.975 * len(ordered)) - 1)]
    return [low, high]


def bootstrap_mean(values, seed):
    """单个均值按处境重抽样的区间（自举单位是处境）。"""
    values = [value for value in values if value is not None]
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    n = len(values)
    samples = [sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(BOOTSTRAP)]
    return percentile_interval(samples)


def bootstrap_pair(rows, seed):
    """配对自举：单位是处境，每次重抽处境后重算两侧均值与比率 X。

    X 是比率，不能先按处境各算一条 X 再平均（那样 base=1 的处境要整条丢掉，均值会偏），
    所以每次重抽都重算 (post_mean - base_mean) / (1 - base_mean)；某个重抽样本的
    base_mean 恰好等于 1 时该次 X 无定义，跳过并记数。
    """
    if len(rows) < 2:
        return {"base_ci": None, "post_ci": None, "X_ci": None, "X_replicates_undefined": None}
    rng = random.Random(seed)
    n = len(rows)
    base_samples, post_samples, x_samples = [], [], []
    undefined = 0
    for _ in range(BOOTSTRAP):
        pick = [rows[rng.randrange(n)] for _ in range(n)]
        base = sum(row["base"] for row in pick) / n
        post = sum(row["post"] for row in pick) / n
        base_samples.append(base)
        post_samples.append(post)
        if 1.0 - base <= 0.0:
            undefined += 1
            continue
        x_samples.append((post - base) / (1.0 - base))
    return {
        "base_ci": percentile_interval(base_samples),
        "post_ci": percentile_interval(post_samples),
        "X_ci": percentile_interval(x_samples),
        "X_replicates_undefined": undefined,
    }


def reference_table(densify_rows, ids):
    """参照物：每处境 law 条件的多数签名，以及它是否定下来（票数 ≥ 2）且非空。"""
    by_key = {}
    for row in densify_rows:
        by_key.setdefault((row["situation"], row["arm"]), []).append(signature_of(row["response"]))
    result = {}
    for situation in ids:
        law = by_key.get((situation, "law"), [])
        bare = by_key.get((situation, "bare"), [])
        if len(law) < MIN_DRAWS or len(bare) < MIN_DRAWS:
            raise SystemExit(f"{situation}: {len(law)} 条带法 / {len(bare)} 条不带法，少于 {MIN_DRAWS}")
        signature, votes = majority(law)
        result[situation] = {
            "law_draws": len(law),
            "bare_draws": len(bare),
            "signature": signature,
            "votes": votes,
            "stable": votes >= MIN_REFERENCE_VOTES,
            "nonempty": bool(signature),
            "bare_rate": rate([draw == signature for draw in bare]),
        }
    return result


def usable_reference(reference):
    return reference["stable"] and reference["nonempty"]


def group_answers(rows):
    """(model, situation) → 每条抽样一行；同一 (model, situation, draw) 重复时后写的那条算数。"""
    grouped, duplicates = {}, 0
    for row in rows:
        key = (row["model"], row["situation"])
        slot = grouped.setdefault(key, {})
        if row["draw"] in slot:
            duplicates += 1
        slot[row["draw"]] = row
    return {key: [slot[draw] for draw in sorted(slot)] for key, slot in grouped.items()}, duplicates


def situation_rows(grouped, ids, references):
    """逐处境：两侧一致率、可数对照、以及只作诊断用的单处境 X。"""
    rows, mismatches = [], 0
    for situation in ids:
        reference = references[situation]
        row = {
            "situation": situation,
            "reference_signature": list(reference["signature"]),
            "reference_votes": reference["votes"],
            "reference_usable": usable_reference(reference),
            "law_draws": reference["law_draws"],
            "bare_draws": reference["bare_draws"],
            "bare_deepseek": reference["bare_rate"],
        }
        for name in MODELS:
            draws = grouped.get((name, situation), [])
            signatures = [signature_of(draw["response"]) for draw in draws]
            mismatches += sum(
                1 for draw, signature in zip(draws, signatures)
                if draw.get("action_signature") is not None and tuple(draw["action_signature"]) != signature
            )
            # 只有 3 条抽样全在的一侧才给一致率：生成还在跑时，半条处境的 0/1 会污染均值
            complete = len(draws) == DRAWS
            row[name] = rate([signature == reference["signature"] for signature in signatures]) if complete else None
            row[f"{name}_draws"] = len(draws)
            row[f"{name}_partial"] = 0 < len(draws) < DRAWS
            row[f"{name}_emits_action"] = rate([bool(signature) for signature in signatures]) if complete else None
            row[f"{name}_truncated"] = sum(1 for draw in draws if draw.get("truncated"))
        if row["base"] is None or row["post"] is None or row["base"] >= 1.0:
            row["X_situation"] = None
        else:
            row["X_situation"] = (row["post"] - row["base"]) / (1.0 - row["base"])
        rows.append(row)
    return rows, mismatches


def summarise(per_situation, situations_total):
    """把逐处境行汇总成终版或预备版的结果。X 用两侧都齐全的处境配对算。"""
    used = [row for row in per_situation if row["reference_usable"]]
    paired = [row for row in used if row["base"] is not None and row["post"] is not None]
    base_paired = mean([row["base"] for row in paired])
    post_paired = mean([row["post"] for row in paired])
    headroom = None if base_paired is None else 1.0 - base_paired
    if base_paired is None:
        x, x_status = None, "undefined_adapter_side_missing"
    elif headroom <= 0.0:
        x, x_status = None, "undefined_no_headroom"
    else:
        x, x_status = (post_paired - base_paired) / headroom, "defined"
    bootstrap = bootstrap_pair(paired, SEED + 1)
    bare = [row["bare_deepseek"] for row in used if row["bare_deepseek"] is not None]
    base_actions = [row["base_emits_action"] for row in used if row["base_emits_action"] is not None]
    post_actions = [row["post_emits_action"] for row in used if row["post_emits_action"] is not None]
    excluded = {
        "nonempty_and_stable": len(used),
        "empty_reference": sum(1 for row in per_situation if not row["reference_signature"]),
        "unstable_reference": sum(
            1 for row in per_situation if row["reference_signature"] and not row["reference_usable"]
        ),
    }
    return {
        "situations_total": situations_total,
        "situations_paired": len(paired),
        "situations_reference_usable": len(used),
        "situations_base_complete": sum(1 for row in per_situation if row["base"] is not None),
        "situations_base_partial": sum(1 for row in per_situation if row[f"base_partial"]),
        "situations_post_complete": sum(1 for row in per_situation if row["post"] is not None),
        "situations_post_partial": sum(1 for row in per_situation if row[f"post_partial"]),
        "draws_per_model": DRAWS,
        "decoding": {"temperature": TEMPERATURE, "top_p": TOP_P, "max_new_tokens": MAX_NEW_TOKENS},
        "models": {"base": str(BASE_MODEL), "post": str(ADAPTER)},
        "reference": {
            "source": "evidence/densify/answers.jsonl 的 law 条件",
            "how": "每处境 law 条件里出现次数最多的动作签名，平局取先出现的那条",
            "usable_when": f"票数 ≥ {MIN_REFERENCE_VOTES} 且签名非空",
            "votes": dict(
                (str(votes), sum(1 for row in per_situation if row["reference_votes"] == votes))
                for votes in sorted({row["reference_votes"] for row in per_situation})
            ),
        },
        "reference_selection": excluded,
        "base_mean": mean([row["base"] for row in used if row["base"] is not None]),
        "base_ci": bootstrap_mean([row["base"] for row in used if row["base"] is not None], SEED + 2),
        "post_mean": mean([row["post"] for row in used if row["post"] is not None]),
        "post_ci": bootstrap_mean([row["post"] for row in used if row["post"] is not None], SEED + 3),
        "bare_deepseek_mean": mean(bare),
        "bare_deepseek_ci": bootstrap_mean(bare, SEED + 4),
        "law_deepseek": 1.0,
        "X_definition": "X = (post_mean - base_mean) / (1 - base_mean)，两侧齐全的处境配对，自举单位是处境",
        "X": x,
        "X_ci": bootstrap["X_ci"],
        "X_status": x_status,
        "X_base_paired": base_paired,
        "X_post_paired": post_paired,
        "X_headroom": headroom,
        "X_near_ceiling": None if headroom is None else headroom < NEAR_CEILING_HEADROOM,
        "X_replicates_undefined": bootstrap["X_replicates_undefined"],
        "base_paired_ci": bootstrap["base_ci"],
        "post_paired_ci": bootstrap["post_ci"],
        "countable_control": {
            "what": "回答里有没有可解析动作（签名非空），不经评委、不看参照物",
            "base_emits_action": mean(base_actions),
            "base_emits_action_ci": bootstrap_mean(base_actions, SEED + 5),
            "post_emits_action": mean(post_actions),
            "post_emits_action_ci": bootstrap_mean(post_actions, SEED + 6),
        },
    }


def analyse(answers_rows, densify_rows, ids, preliminary):
    """纯本地分析：给两组行，返回 (summary, per_situation)。"""
    references = reference_table(densify_rows, ids)
    grouped, duplicates = group_answers(answers_rows)
    per_situation, mismatches = situation_rows(grouped, ids, references)
    summary = summarise(per_situation, len(ids))
    summary.update(
        {
            "status": "preliminary" if preliminary else "final",
            "answers_rows": len(answers_rows),
            "answer_duplicates_dropped": duplicates,
            "stored_signature_mismatches": mismatches,
            "truncated_answers": sum(
                row[f"{name}_truncated"] for row in per_situation for name in MODELS
            ),
        }
    )
    if preliminary:
        summary["note"] = (
            "预备：adapter（post）侧还没有抽样，X 不可算；base 侧只覆盖已落盘的处境。"
            "不许当结论引用。"
        )
    return summary, per_situation


def write_outputs(summary, per_situation, preliminary):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    summary_path = PRELIMINARY if preliminary else SUMMARY
    per_situation_path = PRELIMINARY_PER_SITUATION if preliminary else PER_SITUATION
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    per_situation_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in per_situation), encoding="utf-8"
    )
    print(f"写出 {summary_path}")
    return summary_path


def run_analyse(preliminary=False):
    ids = [row["id"] for row in situations()]
    summary, per_situation = analyse(load_jsonl(ANSWERS), load_jsonl(DENSIFY_ANSWERS), ids, preliminary)
    print(
        f"{summary['situations_paired']}/{len(ids)} 条处境两侧各 {DRAWS} 条齐全；"
        f"参照物可用 {summary['situations_reference_usable']} 条"
    )
    if not preliminary and summary["situations_paired"] != len(ids):
        raise SystemExit(
            f"只有 {summary['situations_paired']}/{len(ids)} 条处境两侧齐全，不写终版输出；"
            "先跑 --generate，要看已落盘的部分用 --analyse --preliminary"
        )
    write_outputs(summary, per_situation, preliminary)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return summary


# --- 自检 ------------------------------------------------------------------

ACTION_RESPONSE = "tool: subagent_supervisor()"
NO_ACTION_RESPONSE = "先想清楚再动手，这个方向值得停下来讨论。"

SELFTEST_CASES = (
    {"name": "base=0.2 adapter=0.6", "n": 40, "base_hits": 24, "post_hits": 72, "expect_X": 0.5},
    {"name": "base=0.9 adapter=0.95", "n": 40, "base_hits": 108, "post_hits": 114, "expect_X": 0.5},
    {"name": "base=0 adapter=0", "n": 40, "base_hits": 0, "post_hits": 0, "expect_X": 0.0},
    {"name": "base=1 adapter=1", "n": 40, "base_hits": 120, "post_hits": 120, "expect_X": None},
)


def synthetic_draws(situation, model, hits):
    """每处境 3 条抽样：前 hits 条命中参照签名，其余命中空签名。"""
    return [
        {
            "model": model,
            "situation": situation,
            "draw": draw,
            "response": ACTION_RESPONSE if draw < hits else NO_ACTION_RESPONSE,
            "truncated": False,
        }
        for draw in range(DRAWS)
    ]


def run_check():
    assert signature_of(ACTION_RESPONSE) and not signature_of(NO_ACTION_RESPONSE), "自检用的两条假回答签名不对"
    cases = []
    for case in SELFTEST_CASES:
        ids = [f"ST{index:03d}" for index in range(case["n"])]
        densify_rows = []
        for situation in ids:
            for arm, response in (("law", ACTION_RESPONSE), ("bare", NO_ACTION_RESPONSE)):
                densify_rows.extend(
                    {"situation": situation, "arm": arm, "draw": draw, "response": response}
                    for draw in range(MIN_DRAWS)
                )
        answers_rows = []
        for side, hits_total in (("base", case["base_hits"]), ("post", case["post_hits"])):
            remaining = hits_total
            for situation in ids:
                hits = min(DRAWS, remaining)
                remaining -= hits
                answers_rows.extend(synthetic_draws(situation, side, hits))
            assert remaining == 0, f"{case['name']}: {side} 命中数超过 {len(ids) * DRAWS} 条抽样"
        summary, per_situation = analyse(answers_rows, densify_rows, ids, False)
        expected_base = case["base_hits"] / (case["n"] * DRAWS)
        expected_post = case["post_hits"] / (case["n"] * DRAWS)
        problems = []
        if summary["situations_reference_usable"] != len(ids):
            problems.append(f"参照物可用 {summary['situations_reference_usable']}/{len(ids)}")
        for label, got, want in (
            ("base_mean", summary["base_mean"], expected_base),
            ("post_mean", summary["post_mean"], expected_post),
        ):
            if got is None or abs(got - want) > 1e-9:
                problems.append(f"{label} = {got}，期望 {want}")
        if case["expect_X"] is None:
            if summary["X"] is not None or summary["X_ci"] is not None:
                problems.append(f"X = {summary['X']}，期望无定义（1 - base = 0）")
            if summary["X_replicates_undefined"] != BOOTSTRAP:
                problems.append(f"X_replicates_undefined = {summary['X_replicates_undefined']}，期望 {BOOTSTRAP}")
        else:
            if summary["X"] is None or abs(summary["X"] - case["expect_X"]) > 1e-9:
                problems.append(f"X = {summary['X']}，期望 {case['expect_X']}")
            low, high = summary["X_ci"]
            if not low <= case["expect_X"] <= high:
                problems.append(f"区间 [{low}, {high}] 不含 {case['expect_X']}")
            if summary["X_ci"] == [case["expect_X"], case["expect_X"]] and expected_base not in (0.0,):
                problems.append("区间退化成一点，自举没有起作用")
        cases.append(
            {
                "name": case["name"],
                "situations": case["n"],
                "draws_per_situation": DRAWS,
                "base_mean": summary["base_mean"],
                "base_ci": summary["base_ci"],
                "post_mean": summary["post_mean"],
                "post_ci": summary["post_ci"],
                "X": summary["X"],
                "X_ci": summary["X_ci"],
                "X_status": summary["X_status"],
                "X_replicates_undefined": summary["X_replicates_undefined"],
                "X_situation_defined": sum(1 for row in per_situation if row["X_situation"] is not None),
                "expected_X": case["expect_X"],
                "passed": not problems,
                "problems": problems,
            }
        )
        print(f"{case['name']}: X = {summary['X']}，区间 {summary['X_ci']} → {'通过' if not problems else problems}")
    report = {
        "status": "selftest",
        "what": "用假回答走 analyse() 真路径（动作解析 → 每处境一致率 → 两侧均值 → X → 按处境配对自举），"
                "检查 X 与区间在四种边界上给出预期值",
        "expectations": {
            "base=0.2 adapter=0.6": "X = 0.5",
            "base=0.9 adapter=0.95": "X = 0.5",
            "base=0 adapter=0": "X = 0（分母 1 - base = 1，有定义）",
            "base=1 adapter=1": "X 无定义（分母 0），所有自举重抽样本都无定义",
        },
        "bootstrap_replicates": BOOTSTRAP,
        "bootstrap_unit": "处境（配对重抽，每次重抽同一批处境的两侧）",
        "cases": cases,
        "all_passed": all(case["passed"] for case in cases),
        "does_not_cover": "动作解析器的判定质量、prompt 泄漏、模型抽样本身；自检只证明 X 与区间的算术。",
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    SELFTEST.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"写出 {SELFTEST}：{'全部通过' if report['all_passed'] else '有失败'}")
    if not report["all_passed"]:
        raise SystemExit(1)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true", help="两个模型各生成 3 条回答")
    parser.add_argument("--analyse", action="store_true", help="纯本地统计，不调模型")
    parser.add_argument("--preliminary", action="store_true", help="写 preliminary.* 而不是终版输出")
    parser.add_argument("--check", action="store_true", help="三组假数据自检 X 与区间")
    args = parser.parse_args()
    chosen = [name for name in ("generate", "analyse", "check") if getattr(args, name)]
    if len(chosen) != 1:
        raise SystemExit("选一个：--generate、--analyse 或 --check")
    if args.preliminary and not args.analyse:
        raise SystemExit("--preliminary 只跟 --analyse 一起用")
    if args.generate:
        run_generate()
    elif args.check:
        run_check()
    else:
        run_analyse(args.preliminary)


if __name__ == "__main__":
    main()
