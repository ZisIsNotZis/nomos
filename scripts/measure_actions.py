#!/usr/bin/env python3
"""三点测量：同一批 242 条处境上，训练前基座与窄版适配器的动作一致率。

三个水平共用同一个 prompt：处境原文（excerpt）加上 slice-contrast 的续写指令，
**不含任何法条原文**。带法 DeepSeek 的多数动作是定义上的参照物，不带法 DeepSeek 是
每处境存下来的 3–4 条 bare 回答里与带法多数签名相同的那份比例。参照物只在
「带法侧至少 2 条抽样给出同一签名」且「该签名非空」时才算定下来，口径见
report/sft-measurement.md 的「口径」一节。

  --generate   两个模型（base = 训练前基座，post = 窄版适配器）各对每条处境生成 3 条回答。
  --analyse    纯本地：base / post 的每处境一致率、X = (post_mean - base_mean) / (1 - base_mean)
               与按处境重采样的区间，外加三个并列口径与一个分解：动作签名一致率（主指标）、
               文字层决策签名一致率（不看工具语法）、动作可比子集上的一致率（只有回答里
               真出现动作的处境），以及主指标变化里格式项与决策项各占多少。
               只在全部处境两侧都生成齐全时写终版输出，并强制报出 n_pairs 与覆盖率。
  --allow-partial-pairs 配 --analyse：生成还没跑满时也允许写终版，只在两侧已经齐全的处境子集上算，
               输出里照样强制带 n_pairs 与覆盖率。默认关闭。
  --preliminary 同上，但只写 evidence/measure/preliminary.*，标 status=preliminary，绝不写终版路径。
  --check      假数据自检 X、区间与格式/决策分解，写 evidence/measure/selftest.json。

用法：
  python3 scripts/measure_actions.py --generate
  python3 scripts/measure_actions.py --analyse
  python3 scripts/measure_actions.py --analyse --allow-partial-pairs
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
# economy.output_cap（agent-policy b33e7fd）：上限是防止回答失控的保险阀，不是回答结束的地方；
# 取该调用合法产出最长长度的十倍。合法回答 = 自己停下来的那些：已落盘的 1452 条本地生成里
# 1422 条 finish_reason: eos，最长 311；另外 30 条在旧的 320 处被截断，它们只给出「≥ 320」的
# 下界，量不出本来多长，所以不进这个最长值。模型自身的输出上限远高于 3110，未触及。
LONGEST_LEGITIMATE_OUTPUT = 311
MAX_NEW_TOKENS = 10 * LONGEST_LEGITIMATE_OUTPUT  # 最长 311 的十倍
SEED = 20261031
BOOTSTRAP = 2000
SITUATIONS = 242
MIN_DRAWS = 3  # evidence/densify/answers.jsonl 每条处境每条件至少 3 条（多数是 3，少数 4）
MIN_REFERENCE_VOTES = 2  # 带法侧至少 2 条抽样给出同一签名，参照物才定下来
NEAR_CEILING_HEADROOM = 0.2  # 1 - base 小于这个值时报出 X 但标为接近满值
# 动作可比子集少于这个处境数时只作参考：n 小时比例的区间宽到分不清「格式」与「决策」
MIN_CONCLUSIVE_SITUATIONS = 30
# 两侧齐全的可用处境（n_pairs）少于这个数时，本页任何数字只作方向参考，不当结论
MIN_CONCLUSIVE_PAIRS = 60


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
judge = load_module("judge", REPO / "eval" / "judge.py")
INSTRUCTION = probe_common.INSTRUCTION

# 文字层决策签名的四种决策动作，判据全部来自 eval/judge.py，这里只组合不另写。
TEXT_FEATURES = ("asks", "stops", "asserts", "artifacts")
TEXT_FEATURE_MEANING = {
    "asks": "有以问号或“吗/呢”收尾的句子（提问），判据 judge.QUESTION_END",
    "stops": "有门前停顿标记，如等确认、请你决定、先不动手（停住等确认），判据 judge.STOP",
    "asserts": "至少一句下断言且既没给依据也没标不确定（下断言），判据 judge.CLAIM / EVIDENCE / HEDGE",
    "artifacts": "给出可核对产物：路径、哈希、行号、带单位数字或反引号原文，判据 judge.ARTIFACT_*",
}
ARTIFACT_PATTERNS = (judge.ARTIFACT_PATH, judge.ARTIFACT_HASH, judge.ARTIFACT_LINE,
                     judge.ARTIFACT_NUMBER, judge.ARTIFACT_QUOTE)


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


def cap_recorded(rows):
    """已落盘回答实际跑的上限：分析/元数据描述的是已经发生的那批生成，不是常量今天的取值。

    economy.output_cap 把本机上限从 320 抬到「最长合法输出的十倍」（3110）以后，已落盘的 1452 条
    仍是 320 下的生成，按 person 2026-10-23 的决定不重抽。这里从行本身读回上限——新行记
    max_new_tokens，旧行由撞上限的行反推（transformer 在撞上限时 completion_tokens 正好等于上限）
    ——所以 --analyse 仍逐字节复现 summary.json，也不会把历史生成写成今天的新上限。
    没有可读的行（一批新生成还没跑）时才回落到常量。
    """
    caps = {row["max_new_tokens"] for row in rows if row.get("max_new_tokens") is not None}
    caps.update(row["completion_tokens"] for row in rows if row.get("truncated"))
    if len(caps) > 1:
        raise SystemExit(f"已落盘回答用了不止一个上限 {sorted(caps)}，分析要写清是哪一版")
    return caps.pop() if caps else MAX_NEW_TOKENS


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
                    "max_new_tokens": MAX_NEW_TOKENS,
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


def text_signature(answer):
    """文字层决策签名：不看工具语法，只看这段文字做了哪几种决策动作。

    四种特征按 TEXT_FEATURES 的定序压成元组，全等才算同一签名，所以“问了又停”与“只问”
    是两个签名，与动作签名一样严。没命中任何一种时是空元组，不是缺失值。
    判据全部取自 eval/judge.py（QUESTION_END / STOP / CLAIM+EVIDENCE+HEDGE / ARTIFACT_*），
    这里只组合，不另写一套，所以与 eval/judge.py 的 count_checks 同一个口径。
    """
    sentences = judge.split_sentences(answer)
    # 与 count_checks 的未标注推断同一过滤：太短的句子和纯招呼语不算断言
    body = [sentence for sentence in sentences if len(sentence) >= 8 and not judge.GREETING.match(sentence)]
    present = {
        "asks": any(judge.QUESTION_END.search(sentence) for sentence in sentences),
        "stops": bool(judge.STOP.search(answer)),
        "asserts": any(
            judge.CLAIM.search(sentence) and not judge.EVIDENCE.search(sentence) and not judge.HEDGE.search(sentence)
            for sentence in body
        ),
        "artifacts": any(pattern.search(answer) for pattern in ARTIFACT_PATTERNS),
    }
    return tuple(name for name in TEXT_FEATURES if present[name])


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


def text_reference_table(densify_rows, ids):
    """文字层参照物：每处境 law 条件里出现次数最多的文字签名，可用性规则与动作参照物相同。

    票数 < 2（三条抽样两两不同）或多数签名是空元组时，这个处境不进文字层一致率。
    """
    by_key = {}
    for row in densify_rows:
        by_key.setdefault((row["situation"], row["arm"]), []).append(text_signature(row["response"]))
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


def situation_rows(grouped, ids, references, text_references):
    """逐处境：三个口径各自的一致率、可数对照、以及只作诊断用的单处境 X。

    动作口径的 `{side}_agrees` / `{side}_emits` 存的是 3 条抽样里的**条数**，因为主指标的
    格式/决策分解要在回答层求和，不能先平均再乘回去。
    """
    rows, mismatches = [], 0
    for situation in ids:
        reference = references[situation]
        text = text_references[situation]
        row = {
            "situation": situation,
            "reference_signature": list(reference["signature"]),
            "reference_votes": reference["votes"],
            "reference_usable": usable_reference(reference),
            "law_draws": reference["law_draws"],
            "bare_draws": reference["bare_draws"],
            "bare_deepseek": reference["bare_rate"],
            "text_reference_signature": list(text["signature"]),
            "text_reference_votes": text["votes"],
            "text_reference_usable": usable_reference(text),
            "bare_text_deepseek": text["bare_rate"],
        }
        for name in MODELS:
            draws = grouped.get((name, situation), [])
            signatures = [signature_of(draw["response"]) for draw in draws]
            text_signatures = [text_signature(draw["response"]) for draw in draws]
            mismatches += sum(
                1 for draw, signature in zip(draws, signatures)
                if draw.get("action_signature") is not None and tuple(draw["action_signature"]) != signature
            )
            # 只有 3 条抽样全在的一侧才给一致率：生成还在跑时，半条处境的 0/1 会污染均值
            complete = len(draws) == DRAWS
            row[name] = rate([signature == reference["signature"] for signature in signatures]) if complete else None
            row[f"{name}_text"] = rate([signature == text["signature"] for signature in text_signatures]) \
                if complete else None
            row[f"{name}_agrees"] = sum(1 for signature in signatures if signature == reference["signature"]) \
                if complete else None
            row[f"{name}_emits"] = sum(1 for signature in signatures if signature) if complete else None
            row[f"{name}_text_emits"] = sum(1 for signature in text_signatures if signature) if complete else None
            row[f"{name}_draws"] = len(draws)
            row[f"{name}_partial"] = 0 < len(draws) < DRAWS
            row[f"{name}_truncated"] = sum(1 for draw in draws if draw.get("truncated"))
        if row["base"] is None or row["post"] is None or row["base"] >= 1.0:
            row["X_situation"] = None
        else:
            row["X_situation"] = (row["post"] - row["base"]) / (1.0 - row["base"])
        rows.append(row)
    return rows, mismatches


def answer_tally(rows, side):
    """一侧在给定处境集上的可数合计：回答数、有可解析动作的回答数、命中参照的回答数。"""
    complete = [row for row in rows if row[f"{side}_emits"] is not None]
    answers = len(complete) * DRAWS
    emits = sum(row[f"{side}_emits"] for row in complete)
    agrees = sum(row[f"{side}_agrees"] for row in complete)
    return {
        "situations": len(complete),
        "answers": answers,
        "emitting_answers": emits,
        "agreeing_answers": agrees,
        "emits_share": emits / answers if answers else None,
        "agreement_given_emit": agrees / emits if emits else None,
        "mean": agrees / answers if answers else None,
    }


def decomposition(rows):
    """主指标拆成格式项与决策项：会不会写可解析动作，与写了之后选得对不对。

    参照物非空时，没有可解析动作的回答永远命中不了，所以逐处境的
    mean 一致率 = P × A，P 是回答里有可解析动作的比例，A 是这些回答里吻合的比例。
    于是 Δ = post_mean - base_mean 可以精确拆开，但拆法不止一种，份额随约定变：

    中点约定（Kitagawa，本页主口径）：

        Δ = (P_post - P_base)·Ā + (A_post - A_base)·P̄，Ā 与 P̄ 取两侧中点

    以 base 为起点的两项加交互项：

        Δ = ΔP·A_base + ΔA·P_base + ΔP·ΔA

    两种拆法都精确等于 Δ（残差只应是浮点误差），第一种把交互项平分成两半，第二种把它单列。
    中点约定下第一项是**格式项**（开始写工具行的比例变了多少带来的那一份），第二项是**决策项**
    （写了之后选的动作对不对带来的那一份）。base 侧 P 与 A 都接近 0 时 ΔP·ΔA 几乎就是 Δ 本身，
    所以只报中点的 62/38 会掩盖一件事：那份「提升」主要落在两项同时变的乘积项上，不是任何单侧。
    """
    base, post = answer_tally(rows, "base"), answer_tally(rows, "post")
    out = {
        "what": "主指标的格式/决策分解：P 是有可解析动作的回答比例，A 是这些回答里吻合的比例",
        "formula": "Δ = (P_post - P_base)·Ā + (A_post - A_base)·P̄，Ā、P̄ 取两侧中点",
        "format_part_meaning": "格式项：回答里出现可解析动作的比例变了多少带来的那一份",
        "decision_part_meaning": "决策项：在有动作的回答里选对比参照动作的比例变了多少带来的那一份",
        "format_share_meaning": "格式项占 Δ 的比例；1 表示提升全来自格式，0 表示全来自决策，介于两者之间表示两件都在动",
        "base": base,
        "post": post,
        "status": "defined",
        "delta": None,
        "format_part": None,
        "decision_part": None,
        "format_share": None,
        "residual": None,
        "format_part_at_base": None,
        "decision_part_at_base": None,
        "interaction_part": None,
        "interaction_share": None,
        "at_base_residual": None,
    }
    if base["mean"] is None or post["mean"] is None:
        out["status"] = "undefined_one_side_missing"
        return out
    if base["agreement_given_emit"] is None or post["agreement_given_emit"] is None:
        # 某一侧一条动作都没有：A 无定义，决策项无从算起，不补一个 0
        out["status"] = "undefined_no_emitting_answer_on_a_side"
        return out
    delta = post["mean"] - base["mean"]
    midpoint_agreement = (base["agreement_given_emit"] + post["agreement_given_emit"]) / 2
    midpoint_emits = (base["emits_share"] + post["emits_share"]) / 2
    format_part = (post["emits_share"] - base["emits_share"]) * midpoint_agreement
    decision_part = (post["agreement_given_emit"] - base["agreement_given_emit"]) * midpoint_emits
    delta_emits = post["emits_share"] - base["emits_share"]
    delta_agreement = post["agreement_given_emit"] - base["agreement_given_emit"]
    format_at_base = delta_emits * base["agreement_given_emit"]
    decision_at_base = delta_agreement * base["emits_share"]
    interaction = delta_emits * delta_agreement
    out.update(
        {
            "delta": delta,
            "format_part": format_part,
            "decision_part": decision_part,
            "residual": delta - format_part - decision_part,
            "format_share": format_part / delta if delta else None,
            "format_part_at_base": format_at_base,
            "decision_part_at_base": decision_at_base,
            "interaction_part": interaction,
            "interaction_share": interaction / delta if delta else None,
            "at_base_residual": delta - format_at_base - decision_at_base - interaction,
        }
    )
    return out


def bootstrap_decomposition(rows, seed):
    """格式项与决策项的按处境配对自举区间；某一重抽样本无定义时计入未定义数。"""
    empty = {"delta_ci": None, "format_part_ci": None, "decision_part_ci": None, "replicates_undefined": None}
    if len(rows) < 2:
        return empty
    rng = random.Random(seed)
    n = len(rows)
    delta_samples, format_samples, decision_samples = [], [], []
    format_at_base_samples, decision_at_base_samples, interaction_samples, interaction_share_samples = [], [], [], []
    undefined = 0
    for _ in range(BOOTSTRAP):
        parts = decomposition([rows[rng.randrange(n)] for _ in range(n)])
        if parts["status"] != "defined":
            undefined += 1
            continue
        delta_samples.append(parts["delta"])
        format_samples.append(parts["format_part"])
        decision_samples.append(parts["decision_part"])
        format_at_base_samples.append(parts["format_part_at_base"])
        decision_at_base_samples.append(parts["decision_part_at_base"])
        interaction_samples.append(parts["interaction_part"])
        if parts["interaction_share"] is not None:
            interaction_share_samples.append(parts["interaction_share"])
    return {
        "delta_ci": percentile_interval(delta_samples),
        "format_part_ci": percentile_interval(format_samples),
        "decision_part_ci": percentile_interval(decision_samples),
        "format_part_at_base_ci": percentile_interval(format_at_base_samples),
        "decision_part_at_base_ci": percentile_interval(decision_at_base_samples),
        "interaction_part_ci": percentile_interval(interaction_samples),
        "interaction_share_ci": percentile_interval(interaction_share_samples),
        "replicates_undefined": undefined,
    }


def bootstrap_delta(rows, seed, keys=("base", "post")):
    """配对自举的一致率差 Δ = 后一列 − 前一列（重抽单位是处境）。"""
    if len(rows) < 2:
        return None
    rng = random.Random(seed)
    n = len(rows)
    samples = []
    for _ in range(BOOTSTRAP):
        total = 0.0
        for _ in range(n):
            row = rows[rng.randrange(n)]  # 同一处境的两侧一起进来，差值才成对
            total += row[keys[1]] - row[keys[0]]
        samples.append(total / n)
    return percentile_interval(samples)


def action_comparable(rows):
    """第三个口径：只在回答里确实出现可解析动作的处境上算一致率。

    一个处境进入该侧子集的条件是该侧 3 条抽样里至少 1 条签名非空。所以子集回答的是
    「已经在写工具行的那些回答里，选的动作对不对」，把「写不出工具行」排除在外；
    子集处境数少于 MIN_CONCLUSIVE_SITUATIONS 时标记 conclusive=false，只作参考。
    """
    def entry(sides):
        picked = [row for row in rows if all(row[f"{side}_emits"] for side in sides)]
        result = {
            "situations": len(picked),
            "answers": len(picked) * DRAWS,
            "conclusive": len(picked) >= MIN_CONCLUSIVE_SITUATIONS,
            "sides": {},
        }
        for side in sides:
            values = [row[side] for row in picked]
            agrees = sum(row[f"{side}_agrees"] for row in picked)
            result["sides"][side] = {
                "mean": agrees / (len(picked) * DRAWS) if picked else None,
                "ci": bootstrap_mean(values, SEED + 7 + MODELS.index(side)),
            }
        if len(sides) == 2 and picked:
            agrees_base = sum(row["base_agrees"] for row in picked) / (len(picked) * DRAWS)
            agrees_post = sum(row["post_agrees"] for row in picked) / (len(picked) * DRAWS)
            result["delta"] = agrees_post - agrees_base
            result["delta_ci"] = bootstrap_delta(picked, SEED + 9)
        return result

    return {
        "what": "只取回答里已有可解析动作的处境，在这个子集上算一致率",
        "rule": f"该侧 3 条抽样里至少 1 条签名非空；子集少于 {MIN_CONCLUSIVE_SITUATIONS} 条处境时"
                "conclusive=false，只能作参考、不能作结论",
        "base": entry(("base",)),
        "post": entry(("post",)),
        "paired": entry(MODELS),
    }


def text_judgement(per_situation):
    """第二个口径：文字层决策签名的一致率，与能不能写出 `tool: name(...)` 无关。"""
    usable = [row for row in per_situation if row["text_reference_usable"]]
    paired = [row for row in usable if row["base_text"] is not None and row["post_text"] is not None]
    base_values = [row["base_text"] for row in usable if row["base_text"] is not None]
    post_values = [row["post_text"] for row in usable if row["post_text"] is not None]
    base_text_actions = [row["base_text_emits"] for row in usable if row["base_text_emits"] is not None]
    bare = [row["bare_text_deepseek"] for row in usable if row["bare_text_deepseek"] is not None]
    selection = {
        "nonempty_and_stable": len(usable),
        "empty_reference": sum(1 for row in per_situation if not row["text_reference_signature"]),
        "unstable_reference": sum(
            1 for row in per_situation if row["text_reference_signature"] and not row["text_reference_usable"]
        ),
    }
    # 参照物签名的丰富度：只有一个特征的签名区分力很弱，一致率高不能当成“选对了”，
    # 所以要报出参照物里单一特征签名占多少、最常出现的是哪几个。
    shapes = {}
    for row in usable:
        key = tuple(row["text_reference_signature"])
        shapes[key] = shapes.get(key, 0) + 1
    return {
        "what": "文字层决策签名一致率：每条回答压成“提了问/停住等确认/下了断言/给了可核对产物”的定序元组，"
                "与带法 DeepSeek 的多数文字签名比",
        "features": TEXT_FEATURE_MEANING,
        "predicates": "eval/judge.py 的 QUESTION_END / STOP / CLAIM+EVIDENCE+HEDGE / ARTIFACT_*，本脚本只组合",
        "reference": {
            "source": "evidence/densify/answers.jsonl 的 law 条件",
            "usable_when": f"票数 ≥ {MIN_REFERENCE_VOTES} 且签名非空",
            "votes": dict(
                (str(votes), sum(1 for row in per_situation if row["text_reference_votes"] == votes))
                for votes in sorted({row["text_reference_votes"] for row in per_situation})
            ),
        },
        "reference_selection": selection,
        "reference_shape": {
            "single_feature_share": (
                sum(count for signature, count in shapes.items() if len(signature) == 1) / len(usable)
                if usable else None
            ),
            "most_common": [[list(signature), count] for signature, count in
                            sorted(shapes.items(), key=lambda item: -item[1])[:8]],
        },
        "situations_reference_usable": len(usable),
        "situations_paired": len(paired),
        "base_mean": mean(base_values),
        "base_ci": bootstrap_mean(base_values, SEED + 12),
        "post_mean": mean(post_values),
        "post_ci": bootstrap_mean(post_values, SEED + 13),
        "base_paired_mean": mean([row["base_text"] for row in paired]) if paired else None,
        "post_paired_mean": mean([row["post_text"] for row in paired]) if paired else None,
        "delta": (
            mean([row["post_text"] for row in paired]) - mean([row["base_text"] for row in paired])
            if paired else None
        ),
        "delta_ci": bootstrap_delta(paired, SEED + 16, ("base_text", "post_text")) if paired else None,
        "bare_deepseek_mean": mean(bare),
        "bare_deepseek_ci": bootstrap_mean(bare, SEED + 14),
        "law_deepseek": 1.0,
        "base_emits_text_signature": mean([count / DRAWS for count in base_text_actions]),
        "base_emits_text_signature_ci": bootstrap_mean(
            [count / DRAWS for count in base_text_actions], SEED + 15
        ),
    }


def summarise(per_situation, situations_total, cap):
    """把逐处境行汇总成终版或预备版的结果。X 用两侧都齐全的处境配对算。"""
    used = [row for row in per_situation if row["reference_usable"]]
    paired = [row for row in used if row["base"] is not None and row["post"] is not None]
    # 两侧都生成齐全的处境数，与参照物是否可用无关：用来分开「生成没跑完」与「参照物定不下来」
    both_complete = sum(1 for row in per_situation if row["base"] is not None and row["post"] is not None)
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
    base_actions = [row["base_emits"] / DRAWS for row in used if row["base_emits"] is not None]
    post_actions = [row["post_emits"] / DRAWS for row in used if row["post_emits"] is not None]
    # 分解与主指标用同一批处境：两侧齐全时用配对集，否则用参照物可用的全部 base 处境
    decomposition_rows = paired if paired else used
    parts = decomposition(decomposition_rows)
    parts.update(bootstrap_decomposition(decomposition_rows, SEED + 10))
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
        "situations_both_complete": both_complete,
        "generation_complete": both_complete == situations_total,
        "n_pairs": len(paired),
        "coverage": len(paired) / situations_total if situations_total else None,
        "coverage_definition": "coverage = n_pairs / situations_total；n_pairs 是参照物可用且两侧各 "
                               f"{DRAWS} 条齐全的处境数，所以覆盖率不足 1 有一部分来自参照物定不下来"
                               "（见 reference_selection），不是生成缺失",
        "n_pairs_insufficient": len(paired) < MIN_CONCLUSIVE_PAIRS,
        "n_pairs_insufficient_below": MIN_CONCLUSIVE_PAIRS,
        "draws_per_model": DRAWS,
        "decoding": {"temperature": TEMPERATURE, "top_p": TOP_P, "max_new_tokens": cap},
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
        "text_signature": text_judgement(per_situation),
        "action_comparable": action_comparable(used),
        "decomposition": parts,
    }


def analyse(answers_rows, densify_rows, ids, preliminary):
    """纯本地分析：给两组行，返回 (summary, per_situation)。"""
    references = reference_table(densify_rows, ids)
    text_references = text_reference_table(densify_rows, ids)
    grouped, duplicates = group_answers(answers_rows)
    per_situation, mismatches = situation_rows(grouped, ids, references, text_references)
    summary = summarise(per_situation, len(ids), cap_recorded(answers_rows))
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
            f"预备：{summary['situations_post_complete']}/{summary['situations_total']} 条处境有 adapter（post）侧 "
            f"{DRAWS} 条抽样，两侧齐全 {summary['situations_paired']} 条；X 只在这批配对处境上算，"
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


def run_analyse(preliminary=False, allow_partial_pairs=False):
    ids = [row["id"] for row in situations()]
    summary, per_situation = analyse(load_jsonl(ANSWERS), load_jsonl(DENSIFY_ANSWERS), ids, preliminary)
    print(
        f"n_pairs {summary['n_pairs']}/{summary['situations_total']}（覆盖率 {summary['coverage']:.3f}）；"
        f"两侧都齐全 {summary['situations_both_complete']}/{summary['situations_total']}；"
        f"参照物可用 {summary['situations_reference_usable']} 条；"
        f"文字层参照物可用 {summary['text_signature']['situations_reference_usable']} 条"
    )
    if not summary["generation_complete"] and not allow_partial_pairs:
        raise SystemExit(
            f"两侧都齐全的处境只有 {summary['situations_both_complete']}/{summary['situations_total']}，"
            "不写终版输出；先跑 --generate，或确认要在子集上出终版时加 --allow-partial-pairs"
        )
    write_outputs(summary, per_situation, preliminary)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return summary


# --- 自检 ------------------------------------------------------------------

ACTION_RESPONSE = "tool: subagent_supervisor()"
WRONG_ACTION_RESPONSE = "tool: bash(command=\"ls\")"
NO_ACTION_RESPONSE = "先想清楚再动手，这个方向值得停下来讨论。"

SELFTEST_CASES = (
    {"name": "base=0.2 adapter=0.6", "n": 40, "base_hits": 24, "post_hits": 72, "expect_X": 0.5},
    {"name": "base=0.9 adapter=0.95", "n": 40, "base_hits": 108, "post_hits": 114, "expect_X": 0.5},
    {"name": "base=0 adapter=0", "n": 40, "base_hits": 0, "post_hits": 0, "expect_X": 0.0},
    {"name": "base=1 adapter=1", "n": 40, "base_hits": 120, "post_hits": 120, "expect_X": None},
)

# 格式/决策分解的自检：两组假数据只动一个变量，看提升落在哪一项上。
DECOMPOSITION_CASES = (
    {
        "name": "格式：动作比例 0.05→0.5，吻合率 0.5→0.5",
        "n": 40,
        "base": {"emits": 0.05, "agreement": 0.5},
        "post": {"emits": 0.5, "agreement": 0.5},
        "expect_dominant": "format_part",
    },
    {
        "name": "决策：动作比例 0.5→0.5，吻合率 0.3→0.9",
        "n": 40,
        "base": {"emits": 0.5, "agreement": 0.3},
        "post": {"emits": 0.5, "agreement": 0.9},
        "expect_dominant": "decision_part",
    },
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


def synthetic_mixed_draws(ids, model, emits_share, agreement_share):
    """造一组 3n 条回答：emits_share 的回答带可解析动作，其中 agreement_share 的命中参照签名。

    命中参照的用 ACTION_RESPONSE，有动作但不吻合的用 WRONG_ACTION_RESPONSE，其余不写动作。
    回答按下标轮流发到各处境（situation = i % n，draw = i // n），所以每处境正好 3 条。
    """
    total = len(ids) * DRAWS
    emitting = round(emits_share * total)
    agreeing = round(agreement_share * emitting)
    rows = []
    for index in range(total):
        if index < agreeing:
            response = ACTION_RESPONSE
        elif index < emitting:
            response = WRONG_ACTION_RESPONSE
        else:
            response = NO_ACTION_RESPONSE
        rows.append(
            {
                "model": model,
                "situation": ids[index % len(ids)],
                "draw": index // len(ids),
                "response": response,
                "truncated": False,
            }
        )
    return rows, emitting, agreeing


def check_decomposition():
    """两组假数据只动一个变量：动动作比例应全部落在格式项，动吻合率应全部落在决策项。"""
    cases = []
    assert signature_of(WRONG_ACTION_RESPONSE) and signature_of(WRONG_ACTION_RESPONSE) != signature_of(ACTION_RESPONSE), \
        "自检用的“有动作但不吻合”回答签名不对"
    for case in DECOMPOSITION_CASES:
        ids = [f"DC{index:03d}" for index in range(case["n"])]
        densify_rows = [
            {"situation": situation, "arm": arm, "draw": draw, "response": response}
            for situation in ids
            for arm, response in (("law", ACTION_RESPONSE), ("bare", NO_ACTION_RESPONSE))
            for draw in range(MIN_DRAWS)
        ]
        answers_rows, tallies = [], {}
        for side in MODELS:
            rows, emitting, agreeing = synthetic_mixed_draws(
                ids, side, case[side]["emits"], case[side]["agreement"]
            )
            answers_rows.extend(rows)
            tallies[side] = (emitting, agreeing)
        summary, _ = analyse(answers_rows, densify_rows, ids, False)
        parts = summary["decomposition"]
        total = len(ids) * DRAWS
        (base_emit, base_agree), (post_emit, post_agree) = tallies["base"], tallies["post"]
        p_base, p_post = base_emit / total, post_emit / total
        a_base, a_post = base_agree / base_emit, post_agree / post_emit
        want_format = (p_post - p_base) * (a_base + a_post) / 2
        want_decision = (a_post - a_base) * (p_base + p_post) / 2
        want_delta = post_agree / total - base_agree / total
        problems = []
        if parts["status"] != "defined":
            problems.append(f"分解状态 {parts['status']}，期望 defined")
        for label, got, want in (
            ("delta", parts["delta"], want_delta),
            ("format_part", parts["format_part"], want_format),
            ("decision_part", parts["decision_part"], want_decision),
            ("residual", parts["residual"], 0.0),
            ("format_part_at_base", parts["format_part_at_base"], (p_post - p_base) * a_base),
            ("decision_part_at_base", parts["decision_part_at_base"], (a_post - a_base) * p_base),
            ("interaction_part", parts["interaction_part"], (p_post - p_base) * (a_post - a_base)),
            ("at_base_residual", parts["at_base_residual"], 0.0),
        ):
            if got is None or abs(got - want) > 1e-9:
                problems.append(f"{label} = {got}，期望 {want}")
        # 两种拆法的关系：中点约定把交互项平分成两半，所以中点两项之和 − 交互项一半 = Δ
        if abs(parts["interaction_part"] / 2 - (want_format - (p_post - p_base) * a_base)) > 1e-9:
            problems.append("中点约定没有把交互项平分成两半，两个视角不可比较")
        dominant = parts["format_part"] if case["expect_dominant"] == "format_part" else parts["decision_part"]
        other = parts["decision_part"] if case["expect_dominant"] == "format_part" else parts["format_part"]
        if abs(other) > 1e-9 or abs(dominant - want_delta) > 1e-9:
            problems.append(f"提升没有全部落在 {case['expect_dominant']}：格式项 {parts['format_part']}，"
                            f"决策项 {parts['decision_part']}")
        want_share = 1.0 if case["expect_dominant"] == "format_part" else 0.0
        if parts["format_share"] is None or abs(parts["format_share"] - want_share) > 1e-9:
            problems.append(f"format_share = {parts['format_share']}，期望 {want_share}")
        cases.append(
            {
                "name": case["name"],
                "situations": case["n"],
                "answers_per_side": total,
                "base": {"emits_share": p_base, "agreement_given_emit": a_base,
                         "emitting_answers": base_emit, "agreeing_answers": base_agree},
                "post": {"emits_share": p_post, "agreement_given_emit": a_post,
                         "emitting_answers": post_emit, "agreeing_answers": post_agree},
                "delta": parts["delta"],
                "format_part": parts["format_part"],
                "decision_part": parts["decision_part"],
                "format_share": parts["format_share"],
                "residual": parts["residual"],
                "format_part_at_base": parts["format_part_at_base"],
                "decision_part_at_base": parts["decision_part_at_base"],
                "interaction_part": parts["interaction_part"],
                "interaction_share": parts["interaction_share"],
                "at_base_residual": parts["at_base_residual"],
                "expected_format_part": want_format,
                "expected_decision_part": want_decision,
                "expect_dominant": case["expect_dominant"],
                "passed": not problems,
                "problems": problems,
            }
        )
        print(
            f"{case['name']}: Δ = {parts['delta']}，格式项 {parts['format_part']}，"
            f"决策项 {parts['decision_part']} → {'通过' if not problems else problems}"
        )
    return cases


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
    decomposition_cases = check_decomposition()
    report = {
        "status": "selftest",
        "what": "用假回答走 analyse() 真路径（动作解析 → 每处境一致率 → 两侧均值 → X → 按处境配对自举），"
                "检查 X 与区间在四种边界上给出预期值；再用两组只动一个变量的假数据"
                "检查主指标的格式/决策分解",
        "expectations": {
            "base=0.2 adapter=0.6": "X = 0.5",
            "base=0.9 adapter=0.95": "X = 0.5",
            "base=0 adapter=0": "X = 0（分母 1 - base = 1，有定义）",
            "base=1 adapter=1": "X 无定义（分母 0），所有自举重抽样本都无定义",
            "格式：动作比例 0.05→0.5，吻合率 0.5→0.5": "Δ 全部落在格式项，决策项 = 0，format_share = 1",
            "决策：动作比例 0.5→0.5，吻合率 0.3→0.9": "Δ 全部落在决策项，格式项 = 0，format_share = 0",
        },
        "bootstrap_replicates": BOOTSTRAP,
        "bootstrap_unit": "处境（配对重抽，每次重抽同一批处境的两侧）",
        "cases": cases,
        "decomposition_cases": decomposition_cases,
        "all_passed": all(case["passed"] for case in cases + decomposition_cases),
        "does_not_cover": "动作解析器的判定质量、文字层签名的语义合理性、prompt 泄漏、模型抽样本身；"
                          "自检只证明 X、区间与格式/决策分解的算术。",
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
    parser.add_argument("--check", action="store_true", help="假数据自检 X、区间与格式/决策分解")
    parser.add_argument(
        "--allow-partial-pairs",
        action="store_true",
        help="生成没跑满时也写终版，只在两侧齐全的处境子集上算（输出强制带 n_pairs 与覆盖率）",
    )
    args = parser.parse_args()
    chosen = [name for name in ("generate", "analyse", "check") if getattr(args, name)]
    if len(chosen) != 1:
        raise SystemExit("选一个：--generate、--analyse 或 --check")
    if args.preliminary and not args.analyse:
        raise SystemExit("--preliminary 只跟 --analyse 一起用")
    if args.allow_partial_pairs and not args.analyse:
        raise SystemExit("--allow-partial-pairs 只跟 --analyse 一起用")
    if args.generate:
        run_generate()
    elif args.check:
        run_check()
    else:
        run_analyse(args.preliminary, args.allow_partial_pairs)


if __name__ == "__main__":
    main()
