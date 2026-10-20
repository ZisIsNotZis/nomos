#!/usr/bin/env python3
"""Suite definitions for scripts/run_bench.py: prompt building and code scoring.

Both suites are graded by code, not by a model judge, so a base-vs-adapter score
difference cannot come from judge drift. The frozen item files under data/bench/ carry
the selection; this module never downloads and never reads the original sources.

- gsm8k: free-form solution, the final number after `####` is compared to the gold
  number. Unparseable output is counted unscorable, not silently wrong.
- ifeval: instruction-following. An item is kept only when every instruction it carries
  is one this module can decide, so the score is over fully checked items and the
  /api/kwargs coverage gap is recorded in data/bench/sources.json rather than papered over.

Usage:
  from bench_suites import SUITES, load_items, build_prompt, score
"""

import json
import re

ROOT_SUFFIX = "data/bench"
SUITES = ("gsm8k", "ifeval")
MAX_NEW_TOKENS = {"gsm8k": 512, "ifeval": 640}

GSM8K_INSTRUCTION = (
    "Solve the problem step by step, then write the final numeric answer on the last "
    "line as: #### <number>"
)


def load_items(name, bench_dir):
    """Return the frozen items of one suite in frozen order (hash order, seed-fixed)."""
    path = f"{bench_dir}/{name}.jsonl"
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build_prompt(name, item):
    """Return the user-role text for one item."""
    if name == "gsm8k":
        return f"{item['question']}\n\n{GSM8K_INSTRUCTION}"
    if name == "ifeval":
        return item["prompt"]
    raise ValueError(f"unknown suite {name!r}")


# ---------------------------------------------------------------- gsm8k scoring

_NUM = r"-?\d[\d,]*(?:\.\d+)?"
_HASH_ANSWER = re.compile(r"####\s*(?:" + _NUM + r")")
_ANY_NUM = re.compile(_NUM)


def gsm8k_number(text):
    """Return the answer number as a normalised string, or None if absent.

    The `####` marker wins; otherwise the last bare number in the text is taken, which is
    what a model that solved correctly but skipped the marker still emits.
    """
    marked = _HASH_ANSWER.findall(text)
    raw = marked[-1].replace("####", "") if marked else None
    if raw is None:
        bare = _ANY_NUM.findall(text)
        if not bare:
            return None
        raw = bare[-1]
    return _normalise_number(raw)


def _normalise_number(raw):
    raw = raw.replace(",", "").replace("$", "").strip()
    try:
        value = float(raw)
    except ValueError:
        return None
    if value.is_integer():
        return str(int(value))
    return repr(round(value, 6))


def score_gsm8k(item, output):
    predicted = gsm8k_number(output)
    unscorable = predicted is None
    return {
        "correct": (predicted is not None and predicted == item["answer_number"]),
        "unscorable": unscorable,
        "predicted": predicted,
        "gold": item["answer_number"],
    }


# --------------------------------------------------------------- ifeval scoring

_INSTRUCTION_TYPES = {}


def instruction(name):
    def register(fn):
        _INSTRUCTION_TYPES[name] = fn
        return fn

    return register


def supported_instruction_types():
    return set(_INSTRUCTION_TYPES)


def _relation_ok(value, relation, target):
    if relation == "at least":
        return value >= target
    if relation == "at most":
        return value <= target
    if relation == "less than":
        return value < target
    if relation == "exactly":
        return value == target
    raise ValueError(f"unknown relation {relation!r}")


def _words(text):
    return [w for w in re.split(r"\s+", text.strip()) if w]


def _paragraphs(text):
    return [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]


@instruction("punctuation:no_comma")
def _no_comma(text, kw):
    return "," not in text


@instruction("change_case:english_lowercase")
def _lowercase(text, kw):
    return text == text.lower()


@instruction("change_case:english_capital")
def _capital(text, kw):
    return text == text.upper()


@instruction("keywords:existence")
def _existence(text, kw):
    return all(k.lower() in text.lower() for k in kw["keywords"])


@instruction("keywords:forbidden_words")
def _forbidden(text, kw):
    return not any(w.lower() in text.lower() for w in kw["forbidden_words"])


@instruction("keywords:frequency")
def _frequency(text, kw):
    count = text.lower().count(kw["keyword"].lower())
    return _relation_ok(count, kw["relation"], kw["frequency"])


@instruction("length_constraints:number_words")
def _number_words(text, kw):
    return _relation_ok(len(_words(text)), kw["relation"], kw["num_words"])


@instruction("length_constraints:number_paragraphs")
def _number_paragraphs(text, kw):
    return len(_paragraphs(text)) == kw["num_paragraphs"]


@instruction("detectable_format:number_highlighted_sections")
def _highlights(text, kw):
    return len(re.findall(r"\*[^*\n]+\*", text)) >= kw["num_highlights"]


@instruction("detectable_format:title")
def _title(text, kw):
    return re.search(r"<<[^<>\n]+>>", text) is not None


@instruction("detectable_format:json_format")
def _json_format(text, kw):
    try:
        json.loads(text.strip())
    except (ValueError, TypeError):
        return False
    return True


@instruction("detectable_content:number_placeholders")
def _placeholders(text, kw):
    return len(re.findall(r"\[[^\]\n]+\]", text)) >= kw["num_placeholders"]


@instruction("startend:end_checker")
def _end_checker(text, kw):
    return text.strip().lower().endswith(kw["end_phrase"].strip().lower())


@instruction("startend:quotation")
def _quotation(text, kw):
    t = text.strip()
    return len(t) >= 2 and t.startswith('"') and t.endswith('"')


@instruction("combination:two_responses")
def _two_responses(text, kw):
    parts = text.split("******")
    return len(parts) == 2 and all(p.strip() for p in parts)


def check_ifeval(item, output):
    """Return one bool per instruction on the item, in declaration order.

    An empty answer satisfies nothing: without this guard the capital-case check passes on
    an empty string, which would credit a model that answered nothing.
    """
    if not output.strip():
        return [False] * len(item["instruction_id_list"])
    return [
        bool(_INSTRUCTION_TYPES[name](output, kw))
        for name, kw in zip(item["instruction_id_list"], item["kwargs"])
    ]


def score_ifeval(item, output):
    strict = check_ifeval(item, output)
    return {
        "correct": all(strict),
        "unscorable": False,
        "per_instruction": dict(zip(item["instruction_id_list"], strict)),
        "gold": None,
    }


SCORERS = {"gsm8k": score_gsm8k, "ifeval": score_ifeval}


def score(name, item, output):
    return SCORERS[name](item, output)


# --------------------------------------------------------------- aggregation

def wilson_interval(correct, total, z=1.96):
    """95% Wilson interval for a binomial proportion; (low, high) or (None, None)."""
    if total == 0:
        return (None, None)
    p = correct / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def aggregate(records, unscorable):
    total = len(records)
    correct = sum(1 for r in records if r["correct"])
    low, high = wilson_interval(correct, total)
    return {
        "items": total,
        "correct": correct,
        "accuracy": (correct / total) if total else None,
        "accuracy_ci95": [low, high],
        "unscorable": unscorable,
    }
