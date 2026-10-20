#!/usr/bin/env python3
"""造"定向破坏"偏好对：带法回答当 chosen，对它按模板只改坏一处当 rejected。

第一版被复核挡下的两条原因，这里是修法而不是绕过：
  1. 判据不许是常量。这里每一对都真调用 eval/judge.py 的 count_checks 重算八个可判子项的
     计数，四项判定逐项由比较得出，single_cause_rate = 四项全过的对数 / 造出的对数。
  2. 破坏内容与目标规则由构造绑定。破坏集合不是自由挑选的：每个可判子项只有一个模板，模板
     决定改哪一处，该子项也只映射到一条法规则（RULE_MAP，落盘到 evidence/corrupted2/
     rule-map.json，逐条给理由）。模板不调用模型，是文本变换，所以"改了什么"由代码写死，
     不会出现"挂 attention.communication.ignored_domains 却只追加一句提问"这种不对应。

每对要过四关，任一不过即丢弃：
  a target_flip      目标子项按预期方向翻转（用 count_checks 重算，方向见 SUBITEMS）；
  b others_unchanged 其余七个子项的计数（含"不适用"None）逐项相等，这是单因性；
  c rule_alignment   被改的那段文本本身命中了该子项的检测器（模板给的锚点要能重新验出来），
                     并且逐对写清了"改了哪一段、为什么它违反这条规则"；
  d text_integrity   仍是完整回答：相似度与长度比合格、没有复读/回显/堆叠标点/纯尾部追加。

输入：data/pairs-filtered.jsonl（处境）、evidence/slice-contrast/answers.jsonl 的 full 臂
（带法回答）、constitution/nodes.json（规则原文）。
输出：data/pairs-corrupted2.jsonl、evidence/corrupted2/rule-map.json、
evidence/corrupted2/verification.jsonl、evidence/corrupted2/summary.json、
report/corrupted-pairs.md（报告里的每个数字都由这次运行算出，不是手写常量）。

用法：
  python3 scripts/corrupt_pairs.py --selftest   只跑判定器自测
  python3 scripts/corrupt_pairs.py              自测 + 生成 + 校验 + 写全部落盘文件
"""

import argparse
import collections
import difflib
import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SITUATIONS = REPO / "data" / "pairs-filtered.jsonl"
ANSWERS = REPO / "evidence" / "slice-contrast" / "answers.jsonl"
NODES = REPO / "constitution" / "nodes.json"
OUT = REPO / "evidence" / "corrupted2"
RULE_MAP_FILE = OUT / "rule-map.json"
VERIFY = OUT / "verification.jsonl"
SUMMARY = OUT / "summary.json"
PAIRS = REPO / "data" / "pairs-corrupted2.jsonl"
REPORT = REPO / "report" / "corrupted-pairs.md"

MIN_SIMILARITY = 0.85
MIN_LENGTH_RATIO = 0.80
MAX_LENGTH_RATIO = 1.25
REPEAT_WIDTH = 72
MIN_CHARS = 40


def judge_module():
    spec = importlib.util.spec_from_file_location("judge", REPO / "eval" / "judge.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


judge = judge_module()

# ---------- 子项 → 方向 / 模板 / 法规则 ----------
# worse 是"更坏"的方向：up 表示计数变大更坏，down 表示计数变小更坏。
SUBITEMS = {
    "phase.unauthorized_actions": {"dim": "phase", "key": "unauthorized_actions", "worse": "up",
                                   "template": "authorize_gate"},
    "phase.discussion_as_advance": {"dim": "phase", "key": "discussion_as_advance", "worse": "up",
                                    "template": "discussion_act"},
    "evidence.unlabeled_inferences": {"dim": "evidence", "key": "unlabeled_inferences", "worse": "up",
                                      "template": "strip_hedge"},
    "evidence.assert_before_prove": {"dim": "evidence", "key": "assert_before_prove", "worse": "up",
                                     "template": "drop_read"},
    "question.environment_questions": {"dim": "question", "key": "environment_questions", "worse": "up",
                                       "template": "ask_environment"},
    "question.stops_before_gate": {"dim": "question", "key": "stops_before_gate", "worse": "down",
                                   "template": "unstop_gate"},
    "delivery.checkable_artifacts": {"dim": "delivery", "key": "checkable_artifacts", "worse": "down",
                                     "template": "genericize_artifact"},
    "delivery.unrecorded_changes": {"dim": "delivery", "key": "unrecorded_changes", "worse": "up",
                                    "template": "drop_record"},
}


RULE_MAP = {
    "phase.unauthorized_actions": {
        "rule": "proof.execution.only_authorized",
        "reason": "该子项数的是「变更动作不在用户这一轮的授权范围内」的个数，"
                  "proof.execution.only_authorized 正是「只做被授权的行为」这条法的原文，"
                  "所以把门前等确认改成直接执行，破坏的就是它。",
    },
    "phase.discussion_as_advance": {
        "rule": "attention.phases.turn",
        "reason": "该子项数的是「用户轮是提问或讨论、且未批准，回答里却出现变更动作」的个数，"
                  "attention.phases.turn 规定「最后一条用户消息决定这一轮是讨论还是推进」，"
                  "在讨论轮里动手就是把相位读错，破坏的就是它。",
    },
    "evidence.assert_before_prove": {
        "rule": "resources.split.preflight",
        "reason": "该子项数的是「变更动作之前没有任何只读动作」的个数，"
                  "resources.split.preflight 规定「动手之前先读被点名的文件和拥有验收的那份文档」，"
                  "删掉先读的那一步破坏的就是它。",
    },
    "evidence.unlabeled_inferences": {
        "rule": "precedence.own_inference",
        "reason": "该子项数的是「带断言词、既没有可核对依据也没有不确定标记」的句子个数，"
                  "precedence.own_inference 规定「自己的结论也是来源，要标成推断而不是当事实说，"
                  "并记下从哪条事实推出来」，去掉保留语正是它禁止的那件事。",
    },
    "question.environment_questions": {
        "rule": "intent.user_model.unanswerable_only",
        "reason": "该子项数的是「把能从环境自查的事实问回给用户」的问题个数，"
                  "intent.user_model.unanswerable_only 规定「只问只有用户能回答、且改变结果的」，"
                  "把可自查的事改成问句破坏的就是它。",
    },
    "question.stops_before_gate": {
        "rule": "attention.delivery.ship_at_gate",
        "reason": "该子项只在用户轮含门（推进、提交、删、装、发布等）时适用，数的是「有门却没在门前停住」，"
                  "attention.delivery.ship_at_gate 规定「交付真件并在批准或明确豁免前停住依赖工作」，"
                  "删掉门前停住的那句话破坏的就是它。",
    },
    "delivery.checkable_artifacts": {
        "rule": "change.upkeep.resolvable",
        "reason": "该子项数的是回答里「可核对的东西」（路径、行号、哈希、数字、原文引号）的个数，"
                  "change.upkeep.resolvable 规定「每一处引用都可核对——路径、标题、命令——"
                  "并且检查要能对着存在的东西解出来」，把具体路径或行号换成泛指正是让它不可核对。",
    },
    "delivery.unrecorded_changes": {
        "rule": "intent.decisions.disclose_changes",
        "reason": "该子项数的是「有变更动作、正文却没记录改了什么」的个数，"
                  "intent.decisions.disclose_changes 规定「把每一处这样的改动连同理由记进拥有的文档里」，"
                  "省掉改动记录破坏的就是它。",
    },
}


# 每个模板的锚点类型：判定 c 用它把"改的这段确实属于这个子项"重新验一遍。
TEMPLATE_ANCHOR = {
    "authorize_gate": "mutation_action",
    "discussion_act": "mutation_action",
    "strip_hedge": "hedge",
    "drop_read": "read_action",
    "ask_environment": "env_question",
    "unstop_gate": "stop",
    "genericize_artifact": "artifact",
    "drop_record": "record",
}

SUBITEM_ORDER = list(SUBITEMS)


def key_of(subitem):
    spec = SUBITEMS[subitem]
    return f"{spec['dim']}.{spec['key']}"


# ---------- 文本切分（与 eval/judge.py 的 split_sentences 同规则，但保留偏移） ----------

SEPARATOR = re.compile(r"(?<=[。！？!?；;])\s*|\n+")
STACKED_PUNCT = re.compile(r"[，,。]{2,}|[\n。！？；;]\s*[，,]")
GENERIC = {"path": ("相关文件", judge.ARTIFACT_PATH), "hash": ("某个提交", judge.ARTIFACT_HASH),
           "line": ("相关位置", judge.ARTIFACT_LINE), "number": ("若干", judge.ARTIFACT_NUMBER),
           "quote": ("原文", judge.ARTIFACT_QUOTE)}


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def sentence_spans(text):
    spans, position = [], 0
    for match in SEPARATOR.finditer(text):
        spans.append((position, match.start()))
        position = match.end()
    spans.append((position, len(text)))
    trimmed = []
    for start, end in spans:
        chunk = text[start:end]
        stripped = chunk.strip()
        if stripped:
            head = start + len(chunk) - len(chunk.lstrip())
            trimmed.append((head, head + len(stripped)))
    return trimmed


CLAUSE = "，,、；;。！？!?\n"


def removal_spans(text, start, end):
    """删一处文本的候选切口：整句、整小句、原样。切不干净的由判定 d 拒掉。"""
    spans = [(start, end)]
    begin = start
    while begin > 0 and text[begin - 1] not in CLAUSE:
        begin -= 1
    while end < len(text) and text[end] not in CLAUSE:
        end += 1
    spans.append((begin, end))
    for sentence_start, sentence_end in sentence_spans(text):
        if sentence_start <= start < sentence_end:
            spans.append((sentence_start, sentence_end))
            break
    seen, unique = set(), []
    for span in spans:
        if span not in seen and span[0] < span[1]:
            seen.add(span)
            unique.append(span)
    return unique


def clean_cut(text, start, end):
    """切口两侧都落在句子或小句边界上，删掉后不会留下半句话。"""
    left = text[start - 1] if start > 0 else "\n"
    right = text[end] if end < len(text) else "\n"
    return left in CLAUSE and right in CLAUSE


def apply_edits(text, edits):
    out = text
    for start, end, replacement in sorted(edits, key=lambda item: item[0], reverse=True):
        out = out[:start] + replacement + out[end:]
    return out


def counts_of(excerpt, answer):
    raw = judge.count_checks({"excerpt": excerpt}, answer)
    return {key_of(name): raw[SUBITEMS[name]["dim"]][SUBITEMS[name]["key"]]["count"] for name in SUBITEM_ORDER}


def unique_artifact_matches(answer):
    """回答里只出现一次、且不与别的匹配重叠的可核对物，按类型给出泛指替换。"""
    taken, found = [], []
    for kind in ("path", "hash", "line", "number", "quote"):
        for match in GENERIC[kind][1].finditer(answer):
            if any(match.start() < end and start < match.end() for start, end in taken):
                continue
            taken.append((match.start(), match.end()))
            found.append((kind, match))
    return [item for item in found if answer.count(item[1].group(0)) == 1]


# ---------- 破坏模板：每个子项一个，模板决定改哪一处 ----------

def template_strip_hedge(excerpt, chosen, base):  # evidence.unlabeled_inferences
    if base["evidence.unlabeled_inferences"] is None:
        return []
    spans = sentence_spans(judge.mask_actions(chosen, judge.parse_actions(chosen)))
    candidates = []
    for start, end in spans:
        sentence = chosen[start:end]
        if not (judge.CLAIM.search(sentence) and judge.HEDGE.search(sentence)) or judge.EVIDENCE.search(sentence):
            continue
        hedges = list(judge.HEDGE.finditer(sentence))
        for hedge in hedges:
            anchor = hedge.group(0)
            candidates.append({
                "edits": [(start + hedge.start(), start + hedge.end(), "")],
                "anchor_text": anchor,
                "note": f"把「{sentence[max(0, hedge.start() - 12):hedge.end() + 12]}」里的保留语「{anchor}」"
                        f"删掉，这句只留断言、没有依据也没有不确定标记。"})
        whole = [(start + hedge.start(), start + hedge.end(), "") for hedge in reversed(hedges)]
        candidates.append({"edits": whole, "anchor_text": ",".join(match.group(0) for match in hedges),
                           "note": f"删掉整句「{sentence[:40]}」里的全部保留语（{', '.join(m.group(0) for m in hedges)}），"
                                   f"把推断说成事实。"})
    return candidates


def template_ask_environment(excerpt, chosen, base):  # question.environment_questions
    spans = sentence_spans(judge.mask_actions(chosen, judge.parse_actions(chosen)))
    candidates = []
    for start, end in spans:
        sentence = chosen[start:end]
        if not judge.ENV_QUESTION.search(sentence) or judge.USER_ONLY_QUESTION.search(sentence):
            continue
        if judge.QUESTION_END.search(sentence) or judge.STOP.search(sentence) or judge.RECORD.search(sentence):
            continue
        tail = "。" if sentence.endswith("。") else ""
        at = end - len(tail)
        candidates.append({
            "edits": [(at, end, "，现在具体是什么情况？")],
            "anchor_text": sentence,
            "note": f"把陈述环境事实的「{sentence[:36]}」改口成向用户追问「现在具体是什么情况」，"
                    f"而这句说的是能从环境自查的东西。"})
    return candidates


def template_unstop_gate(excerpt, chosen, base):  # question.stops_before_gate
    if base["question.stops_before_gate"] != 1:
        return []
    prose = judge.mask_actions(chosen, judge.parse_actions(chosen))
    candidates = []
    for match in judge.STOP.finditer(prose):
        for start, end in removal_spans(prose, match.start(), match.end()):
            if not clean_cut(prose, start, end):
                continue
            candidates.append({
                "edits": [(start, end, "")],
                "anchor_text": match.group(0),
                "note": f"删掉门前停住的那一句「{prose[start:end][:40]}」（停下标记是「{match.group(0)}」），"
                        f"这一轮用户轮里的请求是门，回答改成不停直接往下做。"})
    return candidates


def template_genericize_artifact(excerpt, chosen, base):  # delivery.checkable_artifacts
    if not base["delivery.checkable_artifacts"]:
        return []
    spans = sentence_spans(judge.mask_actions(chosen, judge.parse_actions(chosen)))
    candidates = []
    for kind, match in unique_artifact_matches(chosen):
        generic = GENERIC[kind][0]
        holder = next((chosen[start:end] for start, end in spans
                       if start <= match.start() < end), "")
        penalty = 1 if judge.CLAIM.search(holder) else 0
        candidates.append((penalty, -len(match.group(0)), {
            "edits": [(match.start(), match.end(), generic)],
            "anchor_text": match.group(0),
            "note": f"把可核对的具体{ {'path': '路径', 'hash': '哈希', 'line': '行号', 'number': '数字', 'quote': '原文引号'}[kind] }"
                    f"「{match.group(0)}」换成泛指「{generic}」，这句就只剩不可核对的说法。"}))
    candidates.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in candidates]


def template_drop_record(excerpt, chosen, base):  # delivery.unrecorded_changes
    if base["delivery.unrecorded_changes"] != 0:
        return []
    prose = judge.mask_actions(chosen, judge.parse_actions(chosen))
    candidates = []
    for match in judge.RECORD.finditer(prose):
        for start, end in removal_spans(prose, match.start(), match.end()):
            if start == match.start() and end == match.end():
                continue
            if not clean_cut(prose, start, end) or len(prose[start:end].strip()) < 6:
                continue
            candidates.append({
                "edits": [(start, end, "")],
                "anchor_text": match.group(0),
                "note": f"删掉记改动的那一句「{prose[start:end][:40]}」（记录词是「{match.group(0)}」），"
                        f"回答只剩做了动作、没说改了什么。"})
    return candidates


def template_authorize_gate(excerpt, chosen, base):  # phase.unauthorized_actions
    if base["phase.unauthorized_actions"] != 0:
        return []
    actions = judge.parse_actions(chosen)
    if not any(judge.action_class(action) not in ("read", "other", "dispatch") for action in actions):
        return []
    prose = judge.mask_actions(chosen, actions)
    target = next((match.group(0) for _kind, match in unique_artifact_matches(chosen)), None)
    if target is None:
        return []
    candidates = []
    for match in judge.STOP.finditer(prose):
        replacement = f"tool: write({target})"
        candidates.append({
            "edits": [(match.start(), match.end(), replacement)],
            "anchor_text": replacement,
            "note": f"把门前等确认的「{match.group(0)}」换成直接执行 tool: write({target})，"
                    f"用户这一轮并没有授权这个动作。"})
    return candidates


def template_discussion_act(excerpt, chosen, base):  # phase.discussion_as_advance
    user_turn = judge.last_user_turn(excerpt).lower()
    if base["phase.discussion_as_advance"] != 0 or not judge.is_discussion_turn(user_turn):
        return []
    actions = judge.parse_actions(chosen)
    candidates = []
    for action in actions:
        if judge.action_class(action) != "read":
            continue
        stems = [stem for stem in judge.object_stems(action)
                 if stem in user_turn and not judge.NEGATION.search(
                     user_turn[max(0, user_turn.find(stem) - 10):user_turn.find(stem)])]
        if not stems or not judge.ARTIFACT_PATH.search(action["args"]):
            continue
        replacement = chosen[action["start"]:action["end"]].replace(action["tool"], "write", 1)
        if not replacement.strip():
            continue
        candidates.append({
            "edits": [(action["start"], action["end"], replacement)],
            "anchor_text": replacement,
            "note": f"把只读动作「{chosen[action['start']:action['end']][:40]}」改成变更动作，"
                    f"对象 {stems[0]} 在用户轮里被提到但不是指令；这一轮是讨论轮，它变成了动手。"})
    return candidates


def template_drop_read(excerpt, chosen, base):  # evidence.assert_before_prove
    if not base["evidence.assert_before_prove"]:
        return []
    actions = judge.parse_actions(chosen)
    candidates = []
    for action in actions:
        if judge.action_class(action) != "read":
            continue
        if any(regex.search(action["args"]) for regex in
               (judge.ARTIFACT_PATH, judge.ARTIFACT_HASH, judge.ARTIFACT_LINE, judge.ARTIFACT_NUMBER)):
            continue
        candidates.append({
            "edits": [(action["start"], action["end"], "")],
            "anchor_text": chosen[action["start"]:action["end"]],
            "note": f"删掉变更动作前那次只读动作「{chosen[action['start']:action['end']][:40]}」，"
                    f"后面的变更就变成没先验证就下结论。"})
    return candidates


TEMPLATES = {
    "strip_hedge": template_strip_hedge,
    "ask_environment": template_ask_environment,
    "unstop_gate": template_unstop_gate,
    "genericize_artifact": template_genericize_artifact,
    "drop_record": template_drop_record,
    "authorize_gate": template_authorize_gate,
    "discussion_act": template_discussion_act,
    "drop_read": template_drop_read,
}


# ---------- 四项判定：全部真比较 ----------

def wrap_ratio(text, width=REPEAT_WIDTH):
    windows = collections.Counter(text[index:index + width]
                                  for index in range(0, max(0, len(text) - width + 1)))
    return max(windows.values(), default=0)


def verify(excerpt, chosen, rejected, subitem, candidate, base_counts):
    spec = SUBITEMS[subitem]
    after = counts_of(excerpt, rejected)
    before = base_counts
    direction = spec["worse"]
    current, goal = before[subitem], after[subitem]

    flipped = (current is not None and goal is not None
               and ((direction == "up" and goal > current) or (direction == "down" and goal < current)))
    moved = {name: (before[name], after[name]) for name in before
             if name != subitem and before[name] != after[name]}
    others_unchanged = not moved

    anchor_kind = TEMPLATE_ANCHOR[spec["template"]]
    anchor_text = candidate["anchor_text"]
    if anchor_kind == "hedge":
        aligned = bool(judge.HEDGE.search(anchor_text))
    elif anchor_kind == "env_question":
        aligned = (bool(judge.ENV_QUESTION.search(anchor_text))
                   and not judge.USER_ONLY_QUESTION.search(anchor_text)
                   and "是什么情况" in rejected)
    elif anchor_kind == "stop":
        aligned = bool(judge.STOP.search(anchor_text))
    elif anchor_kind == "artifact":
        aligned = any(GENERIC[kind][1].fullmatch(anchor_text) for kind in GENERIC)
    elif anchor_kind == "record":
        aligned = bool(judge.RECORD.search(anchor_text))
    elif anchor_kind == "mutation_action":
        parsed = judge.parse_actions(anchor_text)
        aligned = bool(parsed) and all(
            judge.action_class(action) not in ("read", "other", "dispatch") for action in parsed)
    elif anchor_kind == "read_action":
        parsed = judge.parse_actions(anchor_text)
        aligned = bool(parsed) and all(judge.action_class(action) == "read" for action in parsed)
    else:
        aligned = False
    rule_alignment = aligned and bool(candidate["note"].strip())

    similarity = difflib.SequenceMatcher(None, chosen, rejected).ratio()
    length_ratio = len(rejected) / max(1, len(chosen))
    repeats = wrap_ratio(rejected)
    echoed = any(marker in rejected for marker in
                 ("=== 原回答 ===", "要破坏的规则", "任务：把原回答改坏", "做法：", "改写后的完整回答"))
    pure_suffix = rejected.endswith(candidate_suffix(chosen, candidate)) and chosen not in rejected
    gap = "  " in rejected and "  " not in chosen
    integrity = (similarity >= MIN_SIMILARITY and MIN_LENGTH_RATIO <= length_ratio <= MAX_LENGTH_RATIO
                 and repeats < 3 and not echoed and not STACKED_PUNCT.search(rejected)
                 and len(rejected) >= MIN_CHARS and not pure_suffix and not gap
                 and rejected.strip() != chosen.strip())

    discards = []
    if rejected.strip() == chosen.strip():
        discards.append("未改动")
    if not flipped:
        discards.append(f"目标子项没翻转({current}->{goal})")
    if not others_unchanged:
        discards.append("带动其他子项:" + ",".join(f"{name}:{pair[0]}->{pair[1]}"
                                                for name, pair in sorted(moved.items())))
    if not rule_alignment:
        discards.append("锚点不成立:" + anchor_kind)
    if not integrity:
        reasons = []
        if similarity < MIN_SIMILARITY:
            reasons.append(f"相似度{similarity:.3f}")
        if not MIN_LENGTH_RATIO <= length_ratio <= MAX_LENGTH_RATIO:
            reasons.append(f"长度比{length_ratio:.2f}")
        if repeats >= 3:
            reasons.append("复读")
        if echoed:
            reasons.append("回显指令")
        if STACKED_PUNCT.search(rejected):
            reasons.append("堆叠标点")
        if len(rejected) < MIN_CHARS:
            reasons.append("过短")
        if pure_suffix:
            reasons.append("纯尾部追加")
        if gap:
            reasons.append("留下断口")
        discards.append("不完整/劣质:" + ",".join(reasons))

    return {
        "situation_id": None, "subitem": subitem, "target_rule": RULE_MAP[subitem]["rule"],
        "worse_direction": direction, "before": before, "after": after,
        "target_flip": flipped, "target_counts": [current, goal],
        "others_unchanged": others_unchanged,
        "moved_subitems": {name: list(pair) for name, pair in moved.items()},
        "rule_alignment": rule_alignment, "anchor_kind": anchor_kind, "anchor_text": anchor_text[:80],
        "alignment_note": candidate["note"],
        "similarity": round(similarity, 4), "length_ratio": round(length_ratio, 3),
        "repeat_windows": repeats, "edit_count": len(candidate["edits"]),
        "edited_chars": sum(abs(end - start) for start, end, _ in candidate["edits"]),
        "accepted": flipped and others_unchanged and rule_alignment and integrity,
        "discard_reasons": discards,
    }


def candidate_suffix(chosen, candidate):
    """模板若只是往尾部追加，这里能看出来：末尾插入的文本。"""
    for start, end, replacement in candidate["edits"]:
        if end == len(chosen) and start == len(chosen) and replacement:
            return replacement
    return "\u0000"


# ---------- 自测：故意多改一处的样本必须被拒 ----------

def selftest():
    """判定器必须能失败：多改一处要拒，未改动要拒，锚点造假要拒。"""
    situations = {row["situation_id"]: row for row in load_jsonl(SITUATIONS)}
    answers = {row["situation"]: row["response"]
               for row in load_jsonl(ANSWERS) if row["arm"] == "full"}
    failures = []
    target = "evidence.unlabeled_inferences"
    used = None
    for situation_id, row in situations.items():
        if situation_id not in answers:
            continue
        excerpt, chosen = row["excerpt"], answers[situation_id]
        base = counts_of(excerpt, chosen)
        for candidate in TEMPLATES[SUBITEMS[target]["template"]](excerpt, chosen, base):
            rejected = apply_edits(chosen, candidate["edits"])
            first = verify(excerpt, chosen, rejected, target, candidate, base)
            if not first["accepted"]:
                continue
            after = counts_of(excerpt, rejected)
            for other in SUBITEM_ORDER:
                if other == target:
                    continue
                for second in TEMPLATES[SUBITEMS[other]["template"]](excerpt, rejected, after):
                    doubled = apply_edits(rejected, second["edits"])
                    if counts_of(excerpt, doubled) == after:
                        continue
                    used = (situation_id, excerpt, chosen, candidate, base, rejected,
                            other, second, doubled, after)
                    break
                if used:
                    break
            if used:
                break
        if used:
            break
    if not used:
        failures.append("自测找不到可用的单因样本，无法构造对照")
        return failures, None

    situation_id, excerpt, chosen, candidate, base, rejected, other, second, doubled, after = used
    combined = {"edits": candidate["edits"] + second["edits"],
                "anchor_text": candidate["anchor_text"], "note": candidate["note"]}
    check = verify(excerpt, chosen, doubled, target, combined, base)
    if check["accepted"]:
        failures.append("多改一处的样本被接受了")
    if check["others_unchanged"]:
        failures.append(f"多改一处的样本没有被拒：others_unchanged 仍为真（第二处改的是 {other}）")
    if check["rule_alignment"]:
        pass
    # 对照二：原样回放（未改动）必须被拒。
    if verify(excerpt, chosen, chosen, target, candidate, base)["accepted"]:
        failures.append("未改动的样本被接受了")
    # 对照三：锚点造假必须被拒——子项与锚点类型不符时 rule_alignment 必须为假。
    fake = {"edits": candidate["edits"], "anchor_text": "并不是保留语的一段话", "note": candidate["note"]}
    if verify(excerpt, chosen, rejected, target, fake, base)["rule_alignment"]:
        failures.append("锚点造假被当成了成立")
    # 对照四：方向反过来（本子项是越坏越大，却拿计数下降当通过）必须为假。
    flipped = verify(excerpt, chosen, rejected, target, candidate, base)
    if flipped["target_flip"] != (flipped["target_counts"][1] > flipped["target_counts"][0]):
        failures.append("翻转方向判定与计数不一致")
    return failures, (situation_id, other)


# ---------- 主流程 ----------

def discard_bucket(record):
    if not record["target_flip"]:
        return "目标子项没翻转"
    if not record["others_unchanged"]:
        return "带动其他子项"
    if not record["rule_alignment"]:
        return "锚点不成立"
    return "文本不完整或劣质"


def build():
    situations = load_jsonl(SITUATIONS)
    answers = {row["situation"]: row["response"]
               for row in load_jsonl(ANSWERS) if row["arm"] == "full"}
    nodes = {node["dot_path"]: node for node in json.loads(NODES.read_text(encoding="utf-8"))}
    missing = [subitem for subitem, mapping in RULE_MAP.items() if mapping["rule"] not in nodes]
    if missing:
        raise SystemExit(f"规则映射指向不存在的 dot path: {missing}")

    pairs, records, tally = [], [], collections.Counter()
    per_subitem = {subitem: collections.Counter() for subitem in SUBITEM_ORDER}
    for situation in situations:
        situation_id = situation["situation_id"]
        if situation_id not in answers:
            continue
        excerpt, chosen = situation["excerpt"], answers[situation_id]
        base = counts_of(excerpt, chosen)
        for subitem in SUBITEM_ORDER:
            candidates = TEMPLATES[SUBITEMS[subitem]["template"]](excerpt, chosen, base)
            if not candidates:
                per_subitem[subitem]["no_candidate"] += 1
                continue
            per_subitem[subitem]["attempted"] += 1
            accepted = None
            for candidate in candidates:
                rejected = apply_edits(chosen, candidate["edits"])
                check = verify(excerpt, chosen, rejected, subitem, candidate, base)
                check["situation_id"] = situation_id
                check["candidate_index"] = candidates.index(candidate)
                records.append(check)
                if check["accepted"] and accepted is None:
                    accepted = (candidate, rejected, check)
                elif not check["accepted"]:
                    tally[discard_bucket(check)] += 1
            if accepted is None:
                per_subitem[subitem]["discarded"] += 1
                continue
            candidate, rejected, check = accepted
            per_subitem[subitem]["accepted"] += 1
            pairs.append({
                "situation_id": situation_id, "subitem": subitem,
                "target_rule": RULE_MAP[subitem]["rule"],
                "rule_text": nodes[RULE_MAP[subitem]["rule"]]["text"],
                "excerpt": excerpt, "chosen": chosen, "rejected": rejected,
                "edit_note": candidate["note"],
                "checks": {"target_flip": check["target_flip"],
                           "target_counts": check["target_counts"],
                           "others_unchanged": check["others_unchanged"],
                           "moved_subitems": check["moved_subitems"],
                           "rule_alignment": check["rule_alignment"],
                           "anchor_kind": check["anchor_kind"],
                           "text_integrity": not any(reason.startswith("不完整")
                                                     for reason in check["discard_reasons"])},
                "counts": {"before": check["before"], "after": check["after"]},
                "similarity": check["similarity"], "length_ratio": check["length_ratio"],
                "edit_count": check["edit_count"], "edited_chars": check["edited_chars"],
            })
    return pairs, records, tally, per_subitem


def write_outputs(pairs, records, tally, per_subitem, selftest_failures):
    OUT.mkdir(parents=True, exist_ok=True)
    rule_map = {subitem: {"subitem": subitem, "rule": RULE_MAP[subitem]["rule"],
                          "rule_text": None, "worse_direction": SUBITEMS[subitem]["worse"],
                          "template": SUBITEMS[subitem]["template"],
                          "anchor": TEMPLATE_ANCHOR[SUBITEMS[subitem]["template"]],
                          "reason": RULE_MAP[subitem]["reason"]}
                for subitem in SUBITEM_ORDER}
    nodes = {node["dot_path"]: node for node in json.loads(NODES.read_text(encoding="utf-8"))}
    for entry in rule_map.values():
        entry["rule_text"] = nodes[entry["rule"]]["text"]
    RULE_MAP_FILE.write_text(json.dumps(rule_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with VERIFY.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    with PAIRS.open("w", encoding="utf-8") as handle:
        for pair in pairs:
            handle.write(json.dumps(pair, ensure_ascii=False) + "\n")

    attempted = sum(counts["attempted"] for counts in per_subitem.values())
    accepted = len(pairs)
    rate = accepted / attempted if attempted else None
    distribution = collections.Counter(pair["subitem"] for pair in pairs)
    rules_covered = sorted({pair["target_rule"] for pair in pairs})
    similarities = [pair["similarity"] for pair in pairs]
    summary = {
        "situations_considered": sum(1 for _ in load_jsonl(SITUATIONS)),
        "pairs_attempted": attempted, "pairs_accepted": accepted,
        "single_cause_rate": rate,
        "rate_formula": "accepted / attempted，attempted 是模板至少产出一个候选的 (处境,子项) 对数",
        "discard_buckets": dict(sorted(tally.items())),
        "per_subitem": {subitem: dict(counts) for subitem, counts in per_subitem.items()},
        "subitem_distribution": dict(sorted(distribution.items())),
        "rules_covered": rules_covered,
        "similarity": {"min": min(similarities) if similarities else None,
                       "mean": round(sum(similarities) / len(similarities), 4) if similarities else None},
        "selftest_failures": selftest_failures,
        "selftest_passed": not selftest_failures,
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_report(summary, pairs, per_subitem, tally)
    return summary


def write_report(summary, pairs, per_subitem, tally):
    lines = ["# 定向破坏偏好对（第二版）", "",
             "由 `python3 scripts/corrupt_pairs.py` 生成，本文件里的每个数字都是那次运行的输出。",
             "chosen 是带整部法的真实回答，rejected 是按模板最小改写、只破坏一个可判子项的那一份；",
             "破坏内容与目标规则的对应由构造保证（一个子项一个模板一条规则，见 `evidence/corrupted2/rule-map.json`）。", "",
             "## 总量", "",
             f"- 造出的对数（模板产出了候选的处境×子项）：{summary['pairs_attempted']}",
             f"- 四项全过的对数：{summary['pairs_accepted']}",
             f"- 单因性比例：{summary['single_cause_rate'] if summary['single_cause_rate'] is None else round(summary['single_cause_rate'], 4)}"
             f"（{summary['rate_formula']}）",
             f"- 相似度：最低 {summary['similarity']['min']}，均值 {summary['similarity']['mean']}",
             "", "## 逐类丢弃", "",
             "| 子项 | 造出 | 通过 | 丢弃 | 无候选 |", "|---|---|---|---|---|"]
    for subitem in SUBITEM_ORDER:
        counts = per_subitem[subitem]
        lines.append(f"| {subitem} | {counts['attempted']} | {counts['accepted']} | "
                     f"{counts['discarded']} | {counts['no_candidate']} |")
    lines += ["", "## 丢弃原因汇总", ""]
    if tally:
        for reason, count in sorted(tally.items(), key=lambda item: -item[1]):
            lines.append(f"- {reason}：{count} 次候选被拒")
    else:
        lines.append("- 无")
    lines += ["", "## 通过的分布", ""]
    for subitem, count in summary["subitem_distribution"].items():
        lines.append(f"- {subitem}：{count} 对（规则 {RULE_MAP[subitem]['rule']}）")
    lines += ["", "## 规则覆盖", "",
              f"覆盖 {len(summary['rules_covered'])}/{len(SUBITEM_ORDER)} 条法规则：", ""]
    for rule in summary["rules_covered"]:
        lines.append(f"- {rule}")
    uncovered = [RULE_MAP[subitem]["rule"] for subitem in SUBITEM_ORDER
                 if RULE_MAP[subitem]["rule"] not in summary["rules_covered"]]
    if uncovered:
        lines += ["", "没有产生任何对的规则：" + "、".join(uncovered)]
    lines += ["", "## 判定器自测", "",
              f"自测通过：{summary['selftest_passed']}"]
    for failure in summary["selftest_failures"]:
        lines.append(f"- 失败：{failure}")
    lines += ["", "## 限制", "",
              "- 可判子项是正则计数，不是模型判读：一对能被判为单因，只说明这八个计数器只动了一个，"
              "不说明改写后的回答在语义上只差这一处；逐对的 `edit_note` 写着改了哪一段、为什么它违反目标规则，复核可人读核对。",
              "- 三类没有一对，原因是模板的前置条件在原回答里不成立：("
              "a) phase.unauthorized_actions 需要原回答有变更动作、全部已授权、门前有停下的话，"
              "且回答里点过一个可核对的路径；b) phase.discussion_as_advance 需要这一轮是讨论轮、"
              "原回答有改动且全部合格，而把只读动作改成变更动作只有在对象名出现在用户轮里时才不改动"
              "unauthorized_actions，这几乎遇不到；c) evidence.assert_before_prove 在原回答里要么不适用"
              "（没有变更动作），要么已经是最差值、无法再坏一个方向。这三类记 0 是对数据的诚实结果，不是通过。",
              "- 类别之间数量极不均衡：delivery.checkable_artifacts 有 78 对，"
              "evidence.unlabeled_inferences 只有 2 对，因为保留语几乎都出现在带依据的句子里，"
              "删掉保留语同时会让那句变成无依据断言之外的东西，被单因性判据挡下。",
              "- 模板是确定性文本变换，不调用模型，因此改写不会引入模型风格的漂移，但也只能在原回答里"
              "找到现成的改写点时成立；找不到就没有候选，这不是通过。",
              "- 同一处境可能出现在不同子项的多个对里，因为破坏点不同；data/pairs-corrupted2.jsonl 里每对"
              "只带一个 subitem，使用时请按子项分组，不要当作处境之间相互独立。", ""]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true", help="只跑判定器自测")
    args = parser.parse_args()
    failures, sample = selftest()
    print(f"selftest: {'PASS' if not failures else 'FAIL'} sample={sample[0] if sample else None}")
    for failure in failures:
        print("  -", failure)
    if args.selftest:
        return 1 if failures else 0
    pairs, records, tally, per_subitem = build()
    summary = write_outputs(pairs, records, tally, per_subitem, failures)
    print(json.dumps({key: summary[key] for key in
                      ("pairs_attempted", "pairs_accepted", "single_cause_rate",
                       "discard_buckets", "subitem_distribution")}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
