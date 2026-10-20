#!/usr/bin/env python3
"""Re-derive gate 2 and gate 3 counts from generations.jsonl.

Two kinds of input, kept apart on purpose:

- `generations.jsonl` carries the outputs and their decoding facts.
- `labels.json` carries the one thing a program cannot decide: whether an output
  is on the situation's topic and whether it is a usable next turn, with a
  one-line reason per row. `tasks/handoff` in the plan calls this a human read,
  so it stays visible as data instead of hiding inside a classifier.

Everything else is a mechanical test on the stored text (plus the situation
excerpt and the policy bytes), so the counts in report/gate-base.md can be
recomputed by anyone holding the same files. The report embeds the counts as a
JSON block; this script compares the two and exits nonzero on any mismatch.

Marks:

- `empty`: no non-whitespace output.
- `truncated`: the row stopped at max_new_tokens (`finish_reason == "length"`).
- `repetition`: a line of 20+ chars, or a 6-word shingle, occurs 3+ times.
- `prompt_echo`: 100+ consecutive characters copied verbatim (whitespace
  ignored) from the situation excerpt or from the system message.
- `format_collapse`: a leaked chat-template control token (`<|...|>`), an
  unterminated ``` fence, or a fabricated `user:` / `assistant:` / `system:`
  line inside the turn.
- `duplicate_line`: a 20+ char line occurs exactly twice — reported, not a class.
- `tool_line`: at least one line in the requested form `tool: name(args)`.
- `tool_line_other`: a `tool:` line present but not in that form.
- `token_overlap`: 2+ content tokens shared with the excerpt. This proxy is
  reported as a limit of mechanical topic detection, not used for the class:
  it misses cross-language paraphrase (3 of the 40 rows here).

Class: `garbage` if any of empty/truncated/repetition/prompt_echo/format_collapse;
otherwise `competent` if the read says on-topic and usable and no tool line is
off-form; otherwise `fluent_wrong` (fluent but not a usable answer to this
situation, or an action rendered in the wrong form).

Usage: python3 report/gate-base/check.py
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
GENERATIONS = HERE / "generations.jsonl"
SITUATIONS = HERE / "situations.jsonl"
LABELS = HERE / "labels.json"
REPORT = HERE.parent / "gate-base.md"
POLICY = Path(__file__).resolve().parents[3] / "agent-policy" / "AGENTS.md"

TOOL_LINE = re.compile(r"(?m)^\s*(?:[-*]\s*)?tool:\s*[A-Za-z_][\w.]*\s*\(")
TOOL_ANY = re.compile(r"(?m)^\s*(?:[-*]\s*)?tool:\s*(\S.*)$")
ROLE_LINE = re.compile(r"(?m)^\s*(user|assistant|system)\s*:")
CONTROL_TOKEN = re.compile(r"<\|[a-z_]+\|>")
CJK = re.compile(r"[\u4e00-\u9fff]")
ASCII_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{4,}")
GARBAGE_MARKS = ("empty", "truncated", "repetition", "prompt_echo", "format_collapse")


def content_tokens(text):
    tokens = {word.lower() for word in ASCII_WORD.findall(text)}
    cjk = CJK.findall(text)
    tokens |= {"".join(pair) for pair in zip(cjk, cjk[1:])}
    return tokens


def repetition_mark(text):
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) >= 20]
    if lines and Counter(lines).most_common(1)[0][1] >= 3:
        return True
    words = text.split()
    shingles = Counter(tuple(words[i:i + 6]) for i in range(max(len(words) - 5, 0)))
    return bool(shingles) and shingles.most_common(1)[0][1] >= 3


def echo_mark(text, excerpt, system):
    window = 100
    haystack = re.sub(r"\s+", "", text)
    for source in (re.sub(r"\s+", "", excerpt), re.sub(r"\s+", "", system)):
        if len(haystack) < window:
            return False
        for start in range(0, len(haystack) - window + 1):
            if haystack[start:start + window] in source:
                return True
    return False


def collapse_mark(text):
    if CONTROL_TOKEN.search(text):
        return True
    if text.count("```") % 2 == 1:
        return True
    return bool(ROLE_LINE.search(text))


def marks_for(row, excerpt, system):
    text = row["output"]
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) >= 20]
    tool_line_other = False
    for match in TOOL_ANY.finditer(text):
        payload = match.group(1).strip().strip("`")
        if not re.match(r"^[A-Za-z_][\w.]*\s*\(", payload):
            tool_line_other = True
    return {
        "empty": not text.strip(),
        "truncated": row["finish_reason"] == "length",
        "repetition": repetition_mark(text),
        "prompt_echo": echo_mark(text, excerpt, system),
        "format_collapse": collapse_mark(text),
        "duplicate_line": bool(lines) and Counter(lines).most_common(1)[0][1] == 2,
        "tool_line": bool(TOOL_LINE.search(text)),
        "tool_line_other": tool_line_other,
        "token_overlap": len(content_tokens(text) & content_tokens(excerpt)) >= 2,
    }


def main():
    situations = {row["id"]: row for row in
                  (json.loads(line) for line in SITUATIONS.read_text().splitlines() if line.strip())}
    policy = POLICY.read_text()
    rows = [json.loads(line) for line in GENERATIONS.read_text().splitlines() if line.strip()]
    labels = {(item["situation"], item["condition"]): item
              for item in json.loads(LABELS.read_text())["labels"]}
    expected_rows = 2 * len(situations)
    if len(rows) != expected_rows:
        raise SystemExit(f"expected {expected_rows} rows, found {len(rows)}")
    if set(labels) != {(row["situation"], row["condition"]) for row in rows}:
        raise SystemExit("labels.json does not cover exactly the rows in generations.jsonl")

    detail = []
    for row in rows:
        key = (row["situation"], row["condition"])
        marks = marks_for(row, situations[row["situation"]]["excerpt"], policy)
        tag = labels[key]
        if any(marks[mark] for mark in GARBAGE_MARKS):
            klass = "garbage"
        elif tag["on_topic"] and tag["usable_turn"] and not marks["tool_line_other"]:
            klass = "competent"
        else:
            klass = "fluent_wrong"
        detail.append({"situation": key[0], "condition": key[1], "class": klass,
                       "marks": marks, "reason": tag["reason"]})

    conditions = {}
    for condition in ("bare", "law"):
        subset = [item for item in detail if item["condition"] == condition]
        count = Counter(item["class"] for item in subset)
        conditions[condition] = {
            "n": len(subset),
            "competent": count["competent"],
            "fluent_wrong": count["fluent_wrong"],
            "garbage": count["garbage"],
            "marks": {mark: sum(1 for item in subset if item["marks"][mark])
                      for mark in subset[0]["marks"]},
            "garbage_ratio": f"{count['garbage']}:{count['fluent_wrong']}",
            "garbage_share": round(count["garbage"] / len(subset), 4),
            "situations": {item["situation"]: item["class"] for item in subset},
        }

    summary = {
        "rows": len(rows),
        "situations": len(situations),
        "conditions": conditions,
        "identical_pairs": sum(
            1 for situation in situations
            if (next(row for row in rows
                     if row["situation"] == situation and row["condition"] == "bare")["output"].strip()
                == next(row for row in rows
                        if row["situation"] == situation and row["condition"] == "law")["output"].strip())),
    }

    print(json.dumps(conditions, indent=2, ensure_ascii=False))
    print(f"identical_pairs: {summary['identical_pairs']} of {len(situations)}")
    for item in detail:
        raised = [name for name, value in item["marks"].items() if value]
        print(f"  {item['situation']} {item['condition']:<4} {item['class']:<13} {','.join(raised)}"
              .rstrip())

    report = REPORT.read_text()
    found = re.search(r"<!-- gate-base-counts (\{.*?\}) -->", report, re.S)
    if not found:
        raise SystemExit("report/gate-base.md carries no <!-- gate-base-counts {...} --> block")
    declared = json.loads(found.group(1))
    problems = []
    for condition in ("bare", "law"):
        for key, value in declared[condition].items():
            derived = conditions[condition].get(key)
            if derived != value:
                problems.append(f"{condition}.{key}: report says {value!r}, derived {derived!r}")
    if declared.get("identical_pairs") != summary["identical_pairs"]:
        problems.append(f"identical_pairs: report says {declared.get('identical_pairs')!r}, "
                        f"derived {summary['identical_pairs']!r}")
    if problems:
        print("\nMISMATCH between report/gate-base.md and generations.jsonl:")
        for problem in problems:
            print("  " + problem)
        return 1
    print("\ncounts in report/gate-base.md match generations.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
