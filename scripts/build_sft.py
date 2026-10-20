#!/usr/bin/env python3
"""把带法回答做成 SFT 样本：处境原文作 prompt，带法回答作 target。

输入只有两处：处境原文来自 evidence/slice-contrast/situations.jsonl 与
evidence/grow/situations.jsonl（共 242 条，51 个会话），回答来自
evidence/densify/answers.jsonl 的 law 条件（735 条，bare 条件不用）。

一条抽样的生命周期，顺序固定：

1. 一行 law 回答就是一个候选样本，prompt = 该处境的 excerpt，target = response；
2. 坏件丢：截断、复读、回显、空回答，各记一条证据到 evidence/sft/dropped.jsonl；
3. 同一处境内去重：动作签名（eval/judge.py 分类出的每个动作的类型，按出现顺序）相同的
   只留一条代表，代表取该处境出现次数最多的那套完整动作（工具名 + 参数），平局取最早出现；
   动作签名为空（回答里没有 `tool:` 行）时改用文字层决策签名：把回答压成「是否提问、是否
   停住等确认、是否下断言、是否有可核对产物」四位，四位相同且 target 词集 Jaccard ≥ 0.9
   才合并，否则各留一条；签名不同但归一化 target 的词集 Jaccard ≥ 0.9 的近重复也只留一条；
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
JACCARD_MIN = 0.9  # 同处境内两条 target 的词集重合到这个值就算近重复

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


def judge_module():
    """动作解析与分类直接用 eval/judge.py 那一份，不复制一份规则到这里。"""
    global _judge
    if _judge is None:
        spec = importlib.util.spec_from_file_location("judge", JUDGE)
        _judge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_judge)
    return _judge


def parse_actions(answer):
    return judge_module().parse_actions(answer)


def action_signature(answer):
    """动作签名：每个动作被判成的类型（read/files/commit/…）按出现顺序拼成一串，参数不参与。

    同一处境的抽样只差措辞与半条 shell 命令，所以判重看动作的类型串而不是命令正文。
    """
    return tuple(judge_module().action_class(action) for action in parse_actions(answer))


def exact_actions(answer):
    """完整动作：工具名 + 压过连续空白的参数，只用来在同签名的几条里挑代表。"""
    return tuple((action["tool"], re.sub(r"\s+", " ", action["args"]).strip())
                 for action in parse_actions(answer))


def signature_text(signature):
    return "→".join(signature) if signature else "无动作"


DECISION_BITS = "提问/停住/断言/产物"


def decision_signature(answer, excerpt):
    """文字层决策签名：是否提问、是否停住等确认、是否下断言、是否有可核对产物。

    四个判定全部取自 eval/judge.py，动作签名说不出空动作回答的区别时由它来判：提问用它
    切句后的 QUESTION_END，停住用它 STOP 的标记词，断言与产物用 count_checks 判出的
    unlabeled_inferences 与 checkable_artifacts 计数。返回四位数字串，位序同上面四个词。
    """
    judge = judge_module()
    actions = judge.parse_actions(answer)
    prose = judge.mask_actions(answer, actions)
    asks = any(judge.QUESTION_END.search(sentence) for sentence in judge.split_sentences(prose))
    waits = bool(judge.STOP.search(prose))
    counts = judge.count_checks({"excerpt": excerpt}, answer)
    asserts = counts["evidence"]["unlabeled_inferences"]["count"] > 0
    artifact = counts["delivery"]["checkable_artifacts"]["count"] > 0
    return "".join("1" if bit else "0" for bit in (asks, waits, asserts, artifact))


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


def drop_record(row, situation_id, session_id, reason_class, evidence, target_chars):
    return {"situation_id": situation_id, "session_id": session_id, "draw": row.get("draw"),
            "reason_class": reason_class, "evidence": evidence, "target_chars": target_chars}


def jaccard(left, right):
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def candidate(situation_id, session_id, excerpt, draw, response):
    """一条抽样变成候选样本，带上判重用的字段（下划线开头，不写盘）。"""
    target = normalize(response)
    return {"situation_id": situation_id, "session_id": session_id, "prompt": excerpt,
            "target": response, "_draw": draw, "_target_sha256": sha256_text(target),
            "_signature": action_signature(response), "_exact": exact_actions(response),
            "_decision": decision_signature(response, excerpt), "_tokens": set(words(target))}


def samples_and_drops(by_id, rows):
    """逐条抽样判坏件，再按签名去重并挡掉近重复；返回样本、丢弃记录与去重前的候选。"""
    candidates, dropped = [], []
    for row in rows:
        situation = by_id[row["situation"]]
        excerpt = situation["excerpt"]
        found = drop_reason(row, excerpt)
        if found is not None:
            reason_class, evidence = found
            dropped.append(drop_record(row, row["situation"], situation["session"], reason_class,
                                       evidence, len(row["response"])))
            continue
        candidates.append(candidate(row["situation"], situation["session"], excerpt,
                                    row.get("draw"), row["response"]))
    samples = dedupe(candidates, dropped)
    return samples, dropped, candidates


def dedupe(candidates, dropped):
    """同处境内按签名只留一条，签名不同的再挡一层 token Jaccard ≥ JACCARD_MIN 的近重复。

    动作签名非空时键是 (处境, 动作签名)，与只按动作去重时一致。动作签名为空时回答里没有
    `tool:` 行，动作说不出两条回答是不是两种行为，键改用 (处境, 文字层决策四位)：四位相同
    且 target 词集 Jaccard ≥ JACCARD_MIN 才合并，否则各留一条，因为同一处境内「自行推进」
    与「问用户 A/B」的动作签名都是空的，合并它们会在 loss 里抹掉这个选择。

    同一处境的 prompt 逐字相同，同一签名里抽样之间只差措辞与半条命令，重复保留只给权重
    不给信息，所以每个签名留一条代表：该处境出现次数最多的完整动作，平局取最早出现；
    文字层组没有完整动作可比，代表取最早出现。
    """
    by_situation = collections.defaultdict(list)
    for sample in candidates:
        by_situation[sample["situation_id"]].append(sample)

    kept = []
    for situation_id in sorted(by_situation):
        rows = by_situation[situation_id]
        modal = collections.Counter(row["_exact"] for row in rows).most_common(1)[0][0]
        survivors = []

        groups = collections.defaultdict(list)
        for row in rows:
            if row["_signature"]:
                groups[row["_signature"]].append(row)
        for group in groups.values():
            keeper = min(group, key=lambda row: row["_exact"] != modal)
            survivors.append((rows.index(keeper), keeper))
            for row in group:
                if row is keeper:
                    continue
                same_text = row["_target_sha256"] == keeper["_target_sha256"]
                dropped.append(drop_record(
                    row, situation_id, row["session_id"],
                    "重复 target" if same_text else "重复动作签名",
                    (f"与本处境 {keeper['_draw']} 号抽样归一化后逐字相同（{len(row['target'])} 字）"
                     if same_text else
                     f"与本处境 {keeper['_draw']} 号抽样动作签名相同（{signature_text(row['_signature'])}），"
                     f"词集 Jaccard {jaccard(row['_tokens'], keeper['_tokens']):.2f}，只留一条"),
                    len(row["target"])))

        decisions = collections.defaultdict(list)
        for row in rows:
            if not row["_signature"]:
                decisions[row["_decision"]].append(row)
        for decision, group in decisions.items():
            chosen_rows = []
            for row in group:
                close = next(((other, jaccard(row["_tokens"], other["_tokens"]))
                              for other in chosen_rows
                              if jaccard(row["_tokens"], other["_tokens"]) >= JACCARD_MIN), None)
                if close is None:
                    chosen_rows.append(row)
                    survivors.append((rows.index(row), row))
                    continue
                other, score = close
                same_text = row["_target_sha256"] == other["_target_sha256"]
                dropped.append(drop_record(
                    row, situation_id, row["session_id"],
                    "重复 target" if same_text else "重复文字层决策",
                    (f"与本处境 {other['_draw']} 号抽样归一化后逐字相同（{len(row['target'])} 字）"
                     if same_text else
                     f"与本处境 {other['_draw']} 号抽样都没有动作，文字层决策四位相同"
                     f"（{decision}，位序 {DECISION_BITS}），词集 Jaccard {score:.2f} ≥ "
                     f"{JACCARD_MIN}，只留一条"),
                    len(row["target"])))

        survivors.sort(key=lambda pair: pair[0])
        chosen = []
        for _, row in survivors:
            close = next(((other, jaccard(row["_tokens"], other["_tokens"])) for other in chosen
                          if other["_signature"] != row["_signature"]
                          and jaccard(row["_tokens"], other["_tokens"]) >= JACCARD_MIN), None)
            if close is not None:
                other, score = close
                dropped.append(drop_record(
                    row, situation_id, row["session_id"], "近重复 target",
                    f"与本处境 {other['_draw']} 号抽样动作签名不同，但 target 词集 Jaccard "
                    f"{score:.2f} ≥ {JACCARD_MIN}，只留一条", len(row["target"])))
                continue
            chosen.append(row)
        kept.extend(chosen)
    return kept


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
    val_sessions, taken, before = [], 0, 0
    for session in order:
        if taken / total >= VAL_SHARE_TARGET:
            break
        before = taken
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
    overshoot = max(per_session.values()) / total  # 跨过目标的那一个会话最多能带过多少占比
    if not before / total < VAL_SHARE_TARGET <= share:
        raise SystemExit(f"验证集停在 {before / total:.1%}→{share:.1%}，没有跨过目标 {VAL_SHARE_TARGET}")
    if share > VAL_SHARE_TARGET + overshoot:
        raise SystemExit(f"验证集占 {share:.1%}，比目标 {VAL_SHARE_TARGET} 多出的部分超过一个会话的 {overshoot:.1%}")
    return train, val, {"train": train_sessions, "val": val_sessions}


def per_situation_summary(samples):
    """每个处境贡献几条样本：去重后同处境里还剩几种不同决策。"""
    counts = collections.Counter(sample["situation_id"] for sample in samples)
    histogram = collections.Counter(counts.values())
    return {"situations": len(counts), "samples": len(samples),
            "min": min(counts.values()), "max": max(counts.values()),
            "mean": round(len(samples) / len(counts), 3),
            "histogram": {str(k): histogram[k] for k in sorted(histogram)}}


def text_layer_stats(samples, candidates):
    """空动作签名的回答现在留几条，与只按动作签名去重时相比重新分开了几条。

    只按动作签名去重时，一个处境的空签名组只留一条代表，所以旧保留数 = 有空签名候选的
    处境数；新的四位文字层签名能把同一处境的这些回答分成几条独立样本，差值就是救回来的。
    """
    old_kept = len({row["situation_id"] for row in candidates if not row["_signature"]})
    new_kept = sum(1 for sample in samples if not sample["_signature"])
    return {"kept_by_action_key": old_kept, "kept_by_text_decision": new_kept,
            "rescued": new_kept - old_kept}


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


def dedupe_cases():
    """三层去重的正反例：同签名的丢一条、近重复的丢一条、签名与文本都不同的两条都留。

    空动作签名那一组单独验：四位相同且文本近重复才合并，四位相同但文本不同、或文本相同
    但四位不同（自行推进 vs 问用户 A/B）都必须各留一条。
    """
    shared = "先确认改法再动手，这段逻辑要保留原来的顺序。" * 2
    read = shared + "tool: read(order.py)"
    other = shared + "tool: commit(order.py)"
    bash_read = "先看一眼文件再动手，确认现在的写法。tool: bash(grep -n order order.py)"
    write = "直接补上缺的那句。tool: edit({\"path\": \"order.py\"})"
    text_same = "这一轮先不动手，等你确认后我再改。" * 3
    text_same_near = text_same + "好"
    text_same_far = "方案先给你看，确认了我再动手。"
    question = "我先看一眼再决定？"
    no_question = "我先看一眼再决定。"
    return (
        ("same-signature", [candidate("S1", "s", "p", 1, read),
                             candidate("S1", "s", "p", 2, bash_read)], [read], ["重复动作签名"]),
        ("near-duplicate", [candidate("S2", "s", "p", 1, read),
                             candidate("S2", "s", "p", 2, other)], [read], ["近重复 target"]),
        ("different-behaviour", [candidate("S3", "s", "p", 1, read),
                                  candidate("S3", "s", "p", 2, write)], [read, write], []),
        ("text-same-decision-near", [candidate("S4", "s", "p", 1, text_same),
                                      candidate("S4", "s", "p", 2, text_same_near)],
         [text_same], ["重复文字层决策"]),
        ("text-same-decision-far", [candidate("S5", "s", "p", 1, text_same),
                                     candidate("S5", "s", "p", 2, text_same_far)],
         [text_same, text_same_far], []),
        ("text-different-decision", [candidate("S6", "s", "p", 1, question),
                                      candidate("S6", "s", "p", 2, no_question)],
         [question, no_question], []),
    )


def self_test():
    """坏件检测器与去重的正反例：每个判据都要在自己那类上响，在好件上不响。"""
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

    for name, candidates, expected, reasons in dedupe_cases():
        dropped = []
        kept = [row["target"] for row in dedupe(candidates, dropped)]
        got = sorted(row["reason_class"] for row in dropped)
        if kept != expected or got != sorted(reasons):
            failures.append(f"{name}: 期望留 {len(expected)} 条并丢 {reasons}，实际留 {len(kept)} 条并丢 {got}")
        print(f"{name}: 留 {len(kept)} 条 — " + ("，".join(got) if got else "无丢弃"))

    if failures:
        raise SystemExit("自检失败：" + "；".join(failures))
    print(f"自检通过：{len(SELF_TEST_CASES)} 个坏件用例 + {len(dedupe_cases())} 个去重用例")


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
    samples, dropped, candidates = samples_and_drops(by_id, rows)
    assertions = assert_prompts(samples)
    train, val, sessions = split(samples)
    coverage = coverage_counts(samples)
    text_layer = text_layer_stats(samples, candidates)

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
        "decisions_per_situation": per_situation_summary(samples),
        "dedupe": {
            "key": "动作签名非空时 (situation_id, 动作签名)；为空时 (situation_id, 文字层决策四位)"
                   f"（位序 {DECISION_BITS}），四位相同且 target 词集 Jaccard ≥ {JACCARD_MIN} 才合并，否则各留一条",
            "text_layer": text_layer,
        },
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
    print(f"文字层签名：空动作回答留 {text_layer['kept_by_text_decision']} 条"
          f"（动作签名键下是 {text_layer['kept_by_action_key']} 条，重新分开 {text_layer['rescued']} 条）")
    print(f"覆盖 {coverage['covered_rules']}/{coverage['trainable_rules']} 条可训练规则，"
          f"{len(coverage['situations_without_annotation'])} 条处境无标注")
    print(f"断言：{assertions['phrases_checked']} 条法条短语 / {assertions['target_heads_checked']} 个 target 前缀，全部未出现在 prompt")


if __name__ == "__main__":
    main()
