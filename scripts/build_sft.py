#!/usr/bin/env python3
"""把带法回答做成 SFT 样本：处境原文作 prompt，带法回答作 target。

输入只有两处：处境原文来自 evidence/slice-contrast/situations.jsonl 与
evidence/grow/situations.jsonl（共 242 条，51 个会话），回答来自
evidence/densify/answers.jsonl 的 law 条件（735 条，bare 条件不用）。

一条抽样的生命周期，顺序固定：

1. 一行 law 回答就是一个候选样本，prompt = 该处境的 excerpt，target = response；
2. 坏件丢：截断、复读、回显、空回答，各记一条证据到 evidence/sft/dropped.jsonl；
3. 同一处境内归一化后文本相同的 target 只留最早的那条（去重后 prompt 与 target 的配对不变）；
4. 按会话切验证集，同一会话只落在一边，切分用固定种子，落 evidence/sft/split.json；
5. 落 data/sft.jsonl（全量）、data/sft-val.jsonl、data/sft-train.jsonl；
6. 用 data/coverage.json 的既有标注重算 175 条可训练规则的覆盖，落
   data/sft-coverage-counts.json。

两次运行时断言，写在程序里、不在事后报告里：prompt 不含法条原文（拿 175 条可训练规则里
长度 ≥30 的首句当独有短语逐条查），且不以任何 target 开头（按前 40 字）。断言失败直接退出，
不写盘。

用法：
  python3 scripts/build_sft.py            # 构建并写盘
  python3 scripts/build_sft.py --self-test  # 只跑坏件检测器的正反例，不写盘
"""

import argparse
import collections
import hashlib
import importlib.util
import json
import random
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SLICE_CONTRAST = REPO / "evidence" / "slice-contrast"
GROW = REPO / "evidence" / "grow"
SITUATION_FILES = (SLICE_CONTRAST / "situations.jsonl", GROW / "situations.jsonl")
ANSWERS = REPO / "evidence" / "densify" / "answers.jsonl"

EVIDENCE = REPO / "evidence" / "sft"
DROPPED = EVIDENCE / "dropped.jsonl"
SPLIT = EVIDENCE / "split.json"

ALL = REPO / "data" / "sft.jsonl"
TRAIN = REPO / "data" / "sft-train.jsonl"
VAL = REPO / "data" / "sft-val.jsonl"

COVERAGE = REPO / "data" / "coverage.json"
NODES = REPO / "constitution" / "nodes.json"
COVERAGE_COUNTS = REPO / "data" / "sft-coverage-counts.json"

SEED = 20261020
VAL_SHARE_TARGET = 0.175  # 会话按种子打乱后顺次取，累计样本占比到这个值以上就停
VAL_SHARE_RANGE = (0.15, 0.20)

SITUATIONS = 242
LAW_ANSWERS = 735
TRAINABLE = 175
PHRASE_MIN_CHARS = 30  # 法条独有短语的最短长度
TARGET_PREFIX_CHARS = 40  # 判 prompt 是否以某条 target 开头时比较的前缀长度
REPEAT_MIN_CHARS = 20  # 复读判定里行/段的最小长度
REPEAT_MIN_COUNT = 3  # 同一行/段出现几次算复读
SHINGLE = 10  # 复读判定里的词 shingle 宽度
ECHO_CONTAINMENT = 0.95  # 回答的用词有多少比例已在处境里出现过，超过就算只复述
ECHO_LENGTH_RATIO = 0.5  # 只复述的回答不会比处境长

_judge = None
SENTENCE_END = set("。！？；.!?;:：）)」”\"'`]>*—-…~、\n")


def load_jsonl(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def words(text):
    return re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text.lower())


def normalize(text):
    """去首尾空白与整体包住回答的一层代码围栏，再把连续空白压成一个空格。"""
    text = text.strip()
    text = re.sub(r"\A```[A-Za-z0-9_+-]*\n", "", text)
    text = re.sub(r"\n```\Z", "", text)
    return re.sub(r"\s+", " ", text).strip()


# --- 坏件检测：每个函数返回一句证据，或 None -----------------------------------

def detect_empty(response):
    if response.strip():
        return None
    return ("空回答", "回答去掉空白后为空，没有可训练内容")


BRACKETS = {"(": ")", "{": "}", "[": "]"}
CLOSING = {v: k for k, v in BRACKETS.items()}


def unclosed_bracket(text):
    """引号里（含 bash 命令字符串）的括号不计，只看代码结构本身的配平。"""
    stack, quote, escaped, prev = [], None, False, ""
    for char in text:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            prev = char
            continue
        if char == '"' or (char == "'" and not prev.isalnum()):
            quote = char
            prev = char
            continue
        if char in BRACKETS:
            stack.append(char)
        elif char in CLOSING and stack and stack[-1] == CLOSING[char]:
            stack.pop()
        prev = char
    return "".join(stack)


def detect_truncated(row):
    """截断：调用方报了 length，或回答在句子、代码围栏、括号中途结束。"""
    text = row["response"].rstrip()
    if row.get("finish_reason") == "length":
        return ("截断", f"finish_reason=length，回答在 {len(text)} 字处被截断")
    if not text:
        return None  # 空回答由 detect_empty 单独记
    if text[-1] not in SENTENCE_END:
        return ("截断", f"回答末字是 {text[-1]!r}，停在句子中途：…{text[-40:]!r}")
    if text.count("```") % 2:
        return ("截断", f"代码围栏未闭合（``` 出现 {text.count('```')} 次），回答停在代码中途：…{text[-40:]!r}")
    left = unclosed_bracket(text)
    if left:
        return ("截断", f"{left} 未闭合，回答停在结构中途：…{text[-40:]!r}")
    return None


def detect_repeated(text):
    """复读：同一行或同一段出现 ≥3 次，或同一个 10 词 shingle 出现 ≥3 次。"""
    units = [(u.strip(), "行") for u in text.split("\n")]
    units += [(u.strip(), "段") for u in re.split(r"\n\s*\n", text)]
    counts = collections.Counter((u) for u, _ in units if len(u) >= REPEAT_MIN_CHARS)
    if counts:
        unit, count = counts.most_common(1)[0]
        if count >= REPEAT_MIN_COUNT:
            kind = "行" if any(u == unit and k == "行" for u, k in units) else "段"
            return ("复读", f"同一{kind}重复 {count} 次：{unit[:60]!r}")
    tokens = words(text)
    shingles = collections.Counter(tuple(tokens[i:i + SHINGLE])
                                   for i in range(len(tokens) - SHINGLE + 1))
    if shingles:
        shingle, count = shingles.most_common(1)[0]
        if count >= REPEAT_MIN_COUNT:
            return ("复读", f"同一 {SHINGLE} 词片段重复 {count} 次：{' '.join(shingle)[:60]!r}")
    return None


JUDGE = REPO / "eval" / "judge.py"


def parse_actions(answer):
    """动作解析直接用 eval/judge.py 那一份，不复制一份规则到这里。"""
    global _judge
    if _judge is None:
        spec = importlib.util.spec_from_file_location("judge", JUDGE)
        _judge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_judge)
    return _judge.parse_actions(answer)


def detect_echo(response, excerpt):
    """回显：只复述处境、没给行动——没有工具动作，词几乎全来自处境，且比处境短。"""
    if parse_actions(response):
        return None
    response_vocabulary = set(words(response))
    if not response_vocabulary:
        return None
    novel = response_vocabulary - set(words(excerpt))
    containment = 1 - len(novel) / len(response_vocabulary)
    if containment < ECHO_CONTAINMENT:
        return None
    if len(response) > ECHO_LENGTH_RATIO * len(excerpt):
        return None
    return ("回显", f"无工具动作，回答 {containment:.0%} 的用词已在处境里且长度只有处境的 "
                    f"{len(response) / len(excerpt):.0%}：…{response[:60]!r}")


def drop_reason(row, excerpt):
    """按空回答、截断、复读、回显的顺序给 (类别, 证据)；好件返回 None。"""
    for found in (detect_empty(row["response"]),
                  detect_truncated(row),
                  detect_repeated(row["response"]),
                  detect_echo(row["response"], excerpt)):
        if found is not None:
            return found
    return None


# --- 输入 ------------------------------------------------------------------

def situations():
    rows = [row for path in SITUATION_FILES for row in load_jsonl(path)]
    if len(rows) != SITUATIONS:
        raise SystemExit(f"{len(rows)} 条处境，期望 {SITUATIONS}")
    by_id = {row["id"]: row for row in rows}
    if len(by_id) != len(rows):
        raise SystemExit("处境 id 重复")
    return by_id


def law_answers():
    rows = [row for row in load_jsonl(ANSWERS) if row["arm"] == "law"]
    if len(rows) != LAW_ANSWERS:
        raise SystemExit(f"{len(rows)} 条带法回答，期望 {LAW_ANSWERS}")
    return rows


def samples_and_drops(by_id, rows):
    """逐条抽样判坏件与去重；返回留下的样本与全部丢弃记录。"""
    samples, dropped, seen = [], [], set()
    for row in rows:
        situation = by_id[row["situation"]]
        excerpt = situation["excerpt"]
        found = drop_reason(row, excerpt)
        if found is not None:
            reason_class, evidence = found
            dropped.append({"situation_id": row["situation"], "session_id": situation["session"],
                            "draw": row.get("draw"), "reason_class": reason_class,
                            "evidence": evidence, "target_chars": len(row["response"])})
            continue
        target = normalize(row["response"])
        key = (row["situation"], target)
        if key in seen:
            dropped.append({"situation_id": row["situation"], "session_id": situation["session"],
                            "draw": row.get("draw"), "reason_class": "重复 target",
                            "evidence": f"与本处境已有样本归一化后逐字相同（{len(target)} 字），只留最早一条",
                            "target_chars": len(row["response"])})
            continue
        seen.add(key)
        samples.append({"situation_id": row["situation"], "session_id": situation["session"],
                        "prompt": excerpt, "target": row["response"],
                        "_draw": row.get("draw"),
                        "_target_sha256": sha256_text(target)})
    return samples, dropped


# --- 运行时断言 ---------------------------------------------------------------

def law_phrases():
    """175 条可训练规则里长度 ≥30 的首句，当法条独有短语用。"""
    nodes = [n for n in json.loads(NODES.read_text(encoding="utf-8")) if n.get("trainable")]
    if len(nodes) != TRAINABLE:
        raise SystemExit(f"{len(nodes)} 条可训练规则，期望 {TRAINABLE}")
    phrases = []
    for node in nodes:
        first = next((normalize(s) for s in re.split(r"(?<=[.。!?！？]) ", node["text"])
                      if len(normalize(s)) >= PHRASE_MIN_CHARS), None)
        if first is None:
            raise SystemExit(f"{node['dot_path']} 取不出 ≥{PHRASE_MIN_CHARS} 字的首句，断言失效")
        phrases.append((node["dot_path"], first))
    return phrases


def assert_prompts(samples):
    """prompt 只含处境：不含法条原文，不以任何 target 开头。失败即停。"""
    phrases = law_phrases()
    leaked = [(s["situation_id"], path, phrase[:40])
              for s in samples for path, phrase in phrases if phrase in s["prompt"]]
    if leaked:
        raise SystemExit(f"{len(leaked)} 条 prompt 含法条原文，例：{leaked[:3]}")

    heads = {normalize(s["target"])[:TARGET_PREFIX_CHARS] for s in samples}
    heads.discard("")
    started = [(s["situation_id"], head)
               for s in samples for head in heads
               if normalize(s["prompt"]).startswith(head)]
    if started:
        raise SystemExit(f"{len(started)} 条 prompt 以某条 target 开头，例：{started[:3]}")
    return {"phrases_checked": len(phrases), "prompts_checked": len(samples),
            "target_heads_checked": len(heads)}


# --- 切分 ------------------------------------------------------------------

def split(samples):
    """按会话切：会话排序后按固定种子打乱，顺次累加到目标验证占比为止。"""
    per_session = collections.Counter(s["session_id"] for s in samples)
    sessions = sorted(per_session)
    order = sessions[:]
    random.Random(SEED).shuffle(order)
    total = len(samples)
    val_sessions, taken = [], 0
    for session in order:
        if taken / total >= VAL_SHARE_TARGET:
            break
        val_sessions.append(session)
        taken += per_session[session]
    val_set = set(val_sessions)
    train_sessions = [s for s in sessions if s not in val_set]
    train = [s for s in samples if s["session_id"] not in val_set]
    val = [s for s in samples if s["session_id"] in val_set]

    if len(train) + len(val) != total:
        raise SystemExit("切分丢了样本")
    if set(s["session_id"] for s in train) & set(s["session_id"] for s in val):
        raise SystemExit("同一会话跨了训练与验证两侧")
    share = len(val) / total
    if not VAL_SHARE_RANGE[0] <= share <= VAL_SHARE_RANGE[1]:
        raise SystemExit(f"验证集占 {share:.1%}，不在 {VAL_SHARE_RANGE} 内")
    return train, val, {"train": train_sessions, "val": val_sessions}


def stable_sample_order(samples):
    return sorted(samples, key=lambda s: (s["situation_id"], s["_target_sha256"]))


# --- 覆盖 ------------------------------------------------------------------

def coverage_counts(samples):
    """沿 data/coverage.json 的标注，重算 175 条可训练规则在这批样本上的覆盖。"""
    annotation = json.loads(COVERAGE.read_text(encoding="utf-8"))
    nodes = [n for n in json.loads(NODES.read_text(encoding="utf-8")) if n.get("trainable")]
    trainable = [n["dot_path"] for n in nodes]
    ids = sorted({s["situation_id"] for s in samples})
    unannotated = [sid for sid in ids if sid not in annotation]
    counts = collections.Counter()
    for sid in ids:
        for rule in annotation.get(sid, []):
            counts[rule] += 1
    covered = [rule for rule in trainable if counts[rule] > 0]
    uncovered = [rule for rule in trainable if counts[rule] == 0]
    return {
        "source": {"annotation": "data/coverage.json", "trainable": "constitution/nodes.json",
                   "samples": "data/sft.jsonl"},
        "trainable_rules": len(trainable),
        "covered_rules": len(covered),
        "uncovered_rules": len(uncovered),
        "samples": len(samples),
        "situations": len(ids),
        "situations_in_annotation": len(annotation),
        "situations_without_annotation": unannotated,
        "rule_counts": {rule: counts[rule] for rule in trainable},
        "uncovered": uncovered,
        "rule": "覆盖数 = 至少有一条样本的处境被 data/coverage.json 标注到该规则的条数；未标注的处境一律按不覆盖记，不重新标注",
    }


# --- 自检（负控） ---------------------------------------------------------------

SELF_TEST_CASES = (
    ("truncated-fence", {"response": "先跑一遍：\n\n```python\nprint(1)\n", "finish_reason": "stop"},
     "截断"),
    ("truncated-length", {"response": "好，我改。", "finish_reason": "length"}, "截断"),
    ("repeated", {"response": ("工具返回的那一行 grep 结果，我贴在这里备查。\n" * 3), "finish_reason": "stop"},
     "复读"),
    ("echo", {"response": "现在是个啥状态？我感觉我们是不是跑偏了。", "finish_reason": "stop"}, "回显"),
    ("good", {"response": "我把 grep 换成 rg 并跑了一遍。\n\ntool: bash({\"command\": \"git status --short\"})",
              "finish_reason": "stop"}, None),
)


def self_test():
    """坏件检测器的正反例：每个检测器都要在自己那类上响，在好件上不响。"""
    failures = []
    for name, row, expect in SELF_TEST_CASES:
        excerpt = "现在是个啥状态？我感觉我们是不是跑偏了。因为我们要的是 AI 有机会介入。" * 2
        found = drop_reason(row, excerpt)
        reason_class, evidence = found if found else (None, "留下")
        if expect is None and reason_class is not None:
            failures.append(f"{name}: 好件被丢，理由 {evidence}")
        elif expect is not None and reason_class != expect:
            failures.append(f"{name}: 期望 {expect}，实际 {reason_class}（{evidence}）")
        print(f"{name}: {reason_class or '留下'} — {evidence}")
    if failures:
        raise SystemExit("自检失败：" + "；".join(failures))
    print(f"自检通过：{len(SELF_TEST_CASES)} 个用例")


# --- 写盘 ------------------------------------------------------------------

def write_jsonl(path, rows, drop_private=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            out = {k: v for k, v in row.items() if not (drop_private and k.startswith("_"))}
            handle.write(json.dumps(out, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return

    by_id = situations()
    rows = law_answers()
    samples, dropped = samples_and_drops(by_id, rows)
    assertions = assert_prompts(samples)
    train, val, sessions = split(samples)
    coverage = coverage_counts(samples)

    write_jsonl(ALL, stable_sample_order(samples))
    write_jsonl(TRAIN, stable_sample_order(train))
    write_jsonl(VAL, stable_sample_order(val))
    write_jsonl(DROPPED, dropped, drop_private=False)
    COVERAGE_COUNTS.write_text(json.dumps(coverage, ensure_ascii=False, indent=1) + "\n",
                               encoding="utf-8")

    reason_counts = collections.Counter(row["reason_class"] for row in dropped)
    SPLIT.write_text(json.dumps({
        "seed": SEED,
        "algorithm": "会话 id 排序后用 seed 打乱，顺次累加会话进验证集，累计样本占比首次 ≥ "
                     f"{VAL_SHARE_TARGET} 即停；同一会话只落一边",
        "sessions_total": len(sessions["train"]) + len(sessions["val"]),
        "sessions_train": len(sessions["train"]),
        "sessions_val": len(sessions["val"]),
        "val_sessions": sorted(sessions["val"]),
        "samples_total": len(samples),
        "samples_train": len(train),
        "samples_val": len(val),
        "val_share": round(len(val) / len(samples), 4),
        "drops": dict(sorted(reason_counts.items())),
        "assertions": assertions,
        "inputs": {str(p.relative_to(REPO)): file_sha256(p) for p in SITUATION_FILES + (ANSWERS, COVERAGE, NODES)},
        "outputs": {str(p.relative_to(REPO)): {"lines": n, "sha256": file_sha256(p)}
                    for p, n in ((ALL, len(samples)), (TRAIN, len(train)), (VAL, len(val)),
                                 (DROPPED, len(dropped)))},
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"样本 {len(samples)}（训练 {len(train)} / 验证 {len(val)}，"
          f"验证 {len(sessions['val'])}/{len(sessions['val']) + len(sessions['train'])} 个会话，"
          f"{len(val) / len(samples):.1%}）")
    print("丢件：" + "，".join(f"{k} {v}" for k, v in sorted(reason_counts.items())))
    print(f"覆盖 {coverage['covered_rules']}/{coverage['trainable_rules']} 条可训练规则，"
          f"{len(coverage['situations_without_annotation'])} 条处境无标注")
    print(f"断言：{assertions['phrases_checked']} 条法条短语 / {assertions['target_heads_checked']} 个 target 前缀，全部未出现在 prompt")


if __name__ == "__main__":
    main()
