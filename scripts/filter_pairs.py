#!/usr/bin/env python3
"""筛掉没有对比信号、或者本身是坏件的双答对。

输入 `data/pairs.jsonl` 是一个 JSON 数组（183 条），字段为 situation_id /
signals / excerpt / chosen / rejected。输出 `data/pairs-filtered.jsonl` 是一行
一条的 JSONL，字段不变；每条被判丢弃的对连同原因与证据写进
`evidence/data-quality/dropped.jsonl`，全部 183 条对的度量写进
`evidence/data-quality/pair-metrics.jsonl`，好让阈值本身可以被审。

判据（与 report/data-quality.md 的“判据”一节同文）：

实质相同 —— 以下任一条成立：
  A 归一化（删掉 Markdown 围栏标记行、连续空白压成一个空格、去首尾空白）后两串相等；
  B 长度比 min/max >= 0.85 且 词集 Jaccard >= 0.85。
    词集：汉字按单字、ASCII 按 [a-z0-9_]+ 取词并小写。
    阈值 0.85 落在这批数据的空隙里：最高的一批是 1.00 到 0.88，下一条是 0.80。

截断 —— 以下任一条成立：
  A 工具调用 `tool: name(...)` 的参数括号/引号不闭合；
  B 最后一个非空白字符不是终止符（句号、问号、感叹号、右括号、引号、星号等）；
  C Markdown 围栏数为奇数。
  独立核对：`evidence/slice-contrast/answers.jsonl` 里 finish_reason == "length"
  的两条（SIT144 的带法回答、SIT177 的不带法回答）正是这里判出的两条。

复读 —— 同一句（>= 20 字）或同一行（>= 20 字）在一条回答里出现 3 次以上；
  另加一个更宽的检查：8 个词（汉字按单字）的连续片段出现 3 次以上。

回显 —— 回答里没有任何工具调用，且与处境原文的连续重合 >= 40 字、占回答
  归一化长度的 >= 60%，即回答本身只是把处境原文重复一遍而没有行动。
"""

import json
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PAIRS = REPO / "data" / "pairs.jsonl"
KEPT = REPO / "data" / "pairs-filtered.jsonl"
EVIDENCE = REPO / "evidence" / "data-quality"
DROPPED = EVIDENCE / "dropped.jsonl"
METRICS = EVIDENCE / "pair-metrics.jsonl"
SOURCE_ANSWERS = REPO / "evidence" / "slice-contrast" / "answers.jsonl"

LENGTH_RATIO_MIN = 0.85
WORD_JACCARD_MIN = 0.85
REPEAT_MIN_CHARS = 20
REPEAT_MIN_TIMES = 3
REPEAT_GRAM = 8
ECHO_MIN_OVERLAP = 40
ECHO_MIN_SHARE = 0.60

TERMINALS = set("。．！？!?.…、\"'”’）)】》`*_~>")
WORD = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]")
REPEAT_TOKEN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
TOOL_CALL = re.compile(r"(?m)^\s*tool:\s*([A-Za-z_][\w.]*)\s*\(")
SENTENCE_SPLIT = re.compile(r"(?<=[。！？.!?])\s*")


def normalize(text):
    text = re.sub(r"(?m)^\s*```[^\n]*$", "", text)
    return re.sub(r"\s+", " ", text).strip()


def word_set(text):
    return set(WORD.findall(text.lower()))


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def longest_common_substring(a, b):
    a, b = normalize(a), normalize(b)
    previous = [0] * (len(b) + 1)
    best = 0
    for char in a:
        current = [0]
        for index, other in enumerate(b):
            value = previous[index] + 1 if char == other else 0
            current.append(value)
            if value > best:
                best = value
        previous = current
    return best


def tool_call_spans(text):
    """Every `tool: name(` call as (name, closed) pairs.

    A closed call is found with a JSON-aware scan: `(`/`)` inside a double-quoted
    JSON string do not count, and a backslash escapes the next character. The
    escaping run that truncated SIT144 never leaves its string, so its call is
    reported unclosed even though the text contains a stray `)`.
    """
    spans = []
    for match in TOOL_CALL.finditer(text):
        depth, index, in_string, escaped = 1, match.end(), False, False
        while index < len(text):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        spans.append((match.group(1), depth == 0 and not in_string))
    return spans


def truncation(answer):
    """A reason string when the answer is cut off, else None."""
    for name, closed in tool_call_spans(answer):
        if not closed:
            return f"工具调用 {name}(...) 未闭合，尾部为 {answer.strip()[-60:]!r}"
    if answer.count("```") % 2:
        return f"Markdown 围栏未闭合，尾部为 {answer.strip()[-60:]!r}"
    tail = answer.strip()
    if tail and tail[-1] not in TERMINALS:
        return f"回答停在半句，尾部为 {tail[-60:]!r}"
    return None


def repetition(answer):
    """A reason string when a passage repeats 3+ times, else None."""
    units = [line.strip() for line in answer.splitlines()]
    for sentence in SENTENCE_SPLIT.split(normalize(answer)):
        units.append(sentence.strip())
    counts = Counter(unit for unit in units if len(unit) >= REPEAT_MIN_CHARS)
    for unit, count in counts.items():
        if count >= REPEAT_MIN_TIMES:
            return f"同一段出现 {count} 次：{unit[:60]!r}"
    tokens = REPEAT_TOKEN.findall(answer)
    grams = Counter(" ".join(tokens[i:i + REPEAT_GRAM])
                    for i in range(max(0, len(tokens) - REPEAT_GRAM + 1)))
    for gram, count in grams.items():
        if count >= REPEAT_MIN_TIMES:
            return f"同一串 {REPEAT_GRAM} 个词出现 {count} 次：{gram[:60]!r}"
    return None


def echo(answer, excerpt):
    """A reason string when the answer only repeats the situation, else None."""
    if "tool:" in answer:
        return None
    overlap = longest_common_substring(answer, excerpt)
    share = overlap / max(1, len(normalize(answer)))
    if overlap >= ECHO_MIN_OVERLAP and share >= ECHO_MIN_SHARE:
        return f"与处境原文连续重合 {overlap} 字、占回答 {share:.0%}，且无工具调用"
    return None


def same_decision(chosen, rejected):
    """A (criterion, reason) pair when the two answers make the same move."""
    left, right = normalize(chosen), normalize(rejected)
    if left == right:
        return "A", "归一化后两串完全相同"
    ratio = min(len(left), len(right)) / max(len(left), len(right))
    overlap = jaccard(word_set(left), word_set(right))
    if ratio >= LENGTH_RATIO_MIN and overlap >= WORD_JACCARD_MIN:
        return "B", f"长度比 {ratio:.2f}、词集 Jaccard {overlap:.2f}，都过阈值"
    return None, None


def source_finish_reasons():
    """finish_reason per (situation, arm) from the generation log, when present."""
    if not SOURCE_ANSWERS.exists():
        return {}
    rows = [json.loads(line) for line in SOURCE_ANSWERS.read_text(encoding="utf-8").splitlines() if line.strip()]
    arms = {"full": "chosen", "bare": "rejected"}
    return {(row["situation"], arms[row["arm"]]): row.get("finish_reason")
            for row in rows if row.get("arm") in arms}


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    pairs = json.loads(PAIRS.read_text(encoding="utf-8"))
    finish = source_finish_reasons()

    kept, dropped, metrics = [], [], []
    for pair in pairs:
        chosen, rejected = pair["chosen"], pair["rejected"]
        metrics_row = {
            "situation_id": pair["situation_id"],
            "length_ratio": round(min(len(normalize(chosen)), len(normalize(rejected)))
                                  / max(len(normalize(chosen)), len(normalize(rejected))), 4),
            "word_jaccard": round(jaccard(word_set(normalize(chosen)), word_set(normalize(rejected))), 4),
            "identical_after_normalize": normalize(chosen) == normalize(rejected),
            "finish_reason": {arm: finish.get((pair["situation_id"], arm)) for arm in ("chosen", "rejected")},
        }
        reasons = []
        criterion, why = same_decision(chosen, rejected)
        if criterion:
            reasons.append({"reason": "same_decision", "criterion": criterion,
                            "arms": ["chosen", "rejected"], "evidence": why,
                            "similarity": {k: metrics_row[k] for k in ("length_ratio", "word_jaccard")}})
        for arm in ("chosen", "rejected"):
            cut = truncation(pair[arm])
            if cut:
                reasons.append({"reason": "truncated", "arms": [arm], "evidence": cut,
                                "finish_reason": finish.get((pair["situation_id"], arm))})
                continue
            loop = repetition(pair[arm])
            if loop:
                reasons.append({"reason": "repetition", "arms": [arm], "evidence": loop})
            repeat_echo = echo(pair[arm], pair["excerpt"])
            if repeat_echo:
                reasons.append({"reason": "echo", "arms": [arm], "evidence": repeat_echo})
        metrics_row["dropped"] = [reason["reason"] for reason in reasons]
        metrics.append(metrics_row)
        if reasons:
            dropped.append({"situation_id": pair["situation_id"], **{k: pair[k] for k in ("signals", "excerpt")},
                            "reasons": reasons})
        else:
            kept.append(pair)

    KEPT.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in kept), encoding="utf-8")
    DROPPED.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in dropped), encoding="utf-8")
    METRICS.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in metrics), encoding="utf-8")

    counts = Counter(reason["reason"] for row in dropped for reason in row["reasons"])
    print(f"pairs in: {len(pairs)}")
    print(f"kept: {len(kept)}")
    print(f"dropped: {len(dropped)} " + ", ".join(f"{name} {counts[name]}" for name in
                                                  ("same_decision", "truncated", "repetition", "echo")))
    print(f"wrote {KEPT.relative_to(REPO)}, {DROPPED.relative_to(REPO)}, {METRICS.relative_to(REPO)}")

    assert all(row["reasons"] for row in dropped)
    assert len(kept) + len(dropped) == len(pairs)


if __name__ == "__main__":
    main()
