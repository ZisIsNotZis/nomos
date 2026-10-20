#!/usr/bin/env python3
"""造"定向破坏"偏好对：带法回答当 chosen，对它只破坏一条目标规则当 rejected。

为什么换这个法子：同一处境分别带法/不带法抽两次得到的偏好对，标签只有约 80% 稳定，
两侧都钉住的对只剩 8 条（report/modal-pairs.md、report/training-diagnosis.md）。
这里改成定向破坏——chosen 是 DeepSeek 带整部法给出的真实回答，rejected 是让它只改
坏一处、恰好违反一条**该处境已被标注**的可训练规则。标签由 eval/judge.py 的可判子
级计数确定性复核，不靠模型投票。

只有能被可判子级看见的规则才能当破坏目标：子级一共八个，能朝"更坏"方向翻转并且
单因的只有三个（见 FAMILIES）。目标规则取自已存在的处境↔规则标注：优先 data/
coverage.json（容量 4 的交付标注），该规则在交付标注里零覆盖时取 evidence/
coverage-uncapped/coverage.json（不设上限的诊断标注）。不自己配规则。

每对要过四关，任一不过即丢弃并记录原因（evidence/corrupted/verification.jsonl）：
  a 目标子项按预期方向翻转；
  b 其余七个可判子级的计数（含"不适用"）全部不变；
  c 文本相似度 >= MIN_SIMILARITY 且长度比在 [0.6, 1.6]（最小改写，不是重写）；
  d 仍是完整回答：finish_reason 为 stop、没有复读、没有回显指令或处境。

输入：data/pairs-filtered.jsonl（处境）、evidence/slice-contrast/answers.jsonl 的
full 臂（带法回答）、data/coverage.json 与 evidence/coverage-uncapped/coverage.json
（处境↔规则标注）、constitution/nodes.json（规则原文）。
输出：evidence/corrupted/calls.jsonl、verification.jsonl、summary.json，
data/pairs-corrupted.jsonl。可重跑：已生成过的处境跳过。

用法：
  python3 scripts/corrupt_pairs.py --plan        只打印选中的 (处境, 规则) 计划
  python3 scripts/corrupt_pairs.py               生成 + 校验，写全部落盘文件
"""

import argparse
import collections
import difflib
import hashlib
import importlib.util
import json
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SITUATIONS = REPO / "data" / "pairs-filtered.jsonl"
ANSWERS = REPO / "evidence" / "slice-contrast" / "answers.jsonl"
COVERAGE = REPO / "data" / "coverage.json"
COVERAGE_WIDE = REPO / "evidence" / "coverage-uncapped" / "coverage.json"
NODES = REPO / "constitution" / "nodes.json"
OUT = REPO / "evidence" / "corrupted"
CALLS = OUT / "calls.jsonl"
VERIFY = OUT / "verification.jsonl"
SUMMARY = OUT / "summary.json"
PAIRS = REPO / "data" / "pairs-corrupted.jsonl"

ENDPOINT = "https://api.deepseek.com/v1/chat/completions"
MODEL = "deepseek-flash"
TEMPERATURE = 0.0
MAX_TOKENS = 900
WORKERS = 6
MAX_ATTEMPTS = 60
MIN_SIMILARITY = 0.75
MIN_LENGTH_RATIO = 0.6
MAX_LENGTH_RATIO = 1.6

# Published price, https://api-docs.deepseek.com/quick_start/pricing, read 2026-10-20.
PRICE = {"peak": {"cache_hit": 0.006, "cache_miss": 0.30, "output": 1.20},
         "off_peak": {"cache_hit": 0.003, "cache_miss": 0.15, "output": 0.60}}
USD_CNY = 6.693661


def judge_module():
    spec = importlib.util.spec_from_file_location("judge", REPO / "eval" / "judge.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


judge = judge_module()

# 三个可判子级是这台仪器唯一能确定性读出"变坏"的地方。每条目标规则落在其中一个：
# 破坏它，就应该只有那个子项动。落不进这三族的规则不可当目标——仪器看不见它的违反。
FAMILIES = {
    "INF": {
        "subitem": ("evidence", "unlabeled_inferences"),
        "worse": "up",
        "rules": [
            "precedence.own_inference",          # 推断当事实说，不标不确定
            "attention.communication.label_confidence",  # 未验证的结论说成已验证
            "precedence.trust_is_earned",        # 把无出处的说法按出处采信
            "precedence.watch_for_poison",       # 没检查信息是否过期/二手就当事实
            "precedence.verify_the_fact",        # 不核对独立证据就下断言
            "practice.research.primary_evidence",  # 结论不回指一手来源
            "intent.objective.true_metric",      # 用代理指标宣称真收益
            "resources.environment.diagnose_network",  # 拿过期观察当现状
            "proof.execution.bind_to_revision",  # 证据不绑修订
            "change.record.keep_evidence",       # 不可重算的值当证据
            "change.entries.fabricated",         # 缺失值补成一个默认值
            "proof.review.unverified",           # 未知验收说成通过
        ],
        "hint": "把原回答里一处推断、判断或结果说成确定的事实，去掉它的不确定标记和依据，"
                "用的语言与原回答相同。这一句必须带 说明/因为/所以/根因/显然/必然/意味着 这类断言词，"
                "并且不带路径、命令、数字、行号、链接或引号原文这些依据；不要新增工具调用。",
    },
    "ENVQ": {
        "subitem": ("question", "environment_questions"),
        "worse": "up",
        "rules": [
            "intent.user_model.unanswerable_only",  # 把能自己查的事问用户
            "intent.decisions.question_frontier",   # 环境事实不自己查，拿去问
            "attention.communication.extraction",   # 问低价值/可自查的问题
            "attention.communication.ask_the_gap",  # 问的不是真正的缺口
            "attention.phases.discussion.consequential_only",  # 问不改变结果的问题
            "attention.communication.ignored_domains",  # 把不该问的决策推给用户
            "resources.efficiency.read_once",       # 该读的没读，改成问
            "intent.user_model.reconcile",          # 冲突不自己判，直接问
        ],
        "hint": "把原回答里一处本可以自己从环境查到的事实，改成向用户提出的一个问题，问号结尾，"
                "用的语言与原回答相同。问题里必须出现 状态/进度/文件/路径/版本/日志/结果/有没有/多少/哪个 "
                "这类可自查的字样，并且不要出现 要不要/你觉得/由你定 这类真正该问用户的话；不新增工具调用。",
    },
    "STOP": {
        "subitem": ("question", "stops_before_gate"),
        "worse": "down",
        "rules": [
            "attention.phases.discussion.wait_for_yes",  # 用户确认前就动手
            "attention.phases.discussion.divergence",    # 偏离用户说法不先问
            "attention.delivery.ship_at_gate",           # 门之前不停
            "attention.delivery.gates_hold",             # 用户不在就自己过门
            "attention.phases.advance.plan_gate",        # 没有计划就推进
            "intent.decisions.fixed_milestones",         # 自行挪动同步点
            "change.entries.assent",                     # 把未确认当确认
        ],
        "hint": "把原回答里表示在门前停住、等用户确认的那处表述，改成不等确认直接往前做，"
                "去掉等你/先不动手/确认后这类说法，不新增工具调用。",
    },
}

RULE_FAMILY = {rule: family for family, spec in FAMILIES.items() for rule in spec["rules"]}

SUBITEMS = [(dim, key) for dim, key in [
    ("phase", "unauthorized_actions"), ("phase", "discussion_as_advance"),
    ("evidence", "unlabeled_inferences"), ("evidence", "assert_before_prove"),
    ("question", "environment_questions"), ("question", "stops_before_gate"),
    ("delivery", "checkable_artifacts"), ("delivery", "unrecorded_changes")]]

LOCK = threading.Lock()
SEQUENCE = 0


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def is_peak(epoch):
    t = time.gmtime(epoch)
    return t.tm_wday < 5 and (1 <= t.tm_hour < 4 or 6 <= t.tm_hour < 10)


def call_cost(usage, created):
    rate = PRICE["peak"] if is_peak(created) else PRICE["off_peak"]
    hit = usage.get("prompt_cache_hit_tokens", 0) or 0
    miss = usage.get("prompt_cache_miss_tokens")
    if miss is None:
        miss = (usage.get("prompt_tokens", 0) or 0) - hit
    out = usage.get("completion_tokens", 0) or 0
    usd = (hit * rate["cache_hit"] + miss * rate["cache_miss"] + out * rate["output"]) / 1_000_000
    return {"cache_hit_tokens": hit, "cache_miss_tokens": miss, "output_tokens": out,
            "rate": "peak" if is_peak(created) else "off_peak", "usd": usd, "cny": usd * USD_CNY}


def api_key():
    import os
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if len(key) < 20:
        raise SystemExit("DEEPSEEK_API_KEY missing or too short; refusing to run")
    return key


def post(body, retries=3):
    key = api_key()
    payload = json.dumps(body).encode()
    for attempt in range(retries):
        request = urllib.request.Request(
            ENDPOINT, data=payload,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        started = time.time()
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                return json.load(response), time.time() - started
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:400]
            if error.code in (429, 500, 502, 503, 504) and attempt + 1 < retries:
                time.sleep(5 * (attempt + 1))
                continue
            raise SystemExit(f"API error {error.code}: {detail}")
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt + 1 < retries:
                time.sleep(5 * (attempt + 1))
                continue
            raise SystemExit(f"network error: {error}")
    raise SystemExit("unreachable")


# ---------- 计划：为每条处境选一条真实相关的规则 ----------

def counts_of(excerpt, answer):
    raw = judge.count_checks({"excerpt": excerpt}, answer)
    return {f"{dim}.{key}": raw[dim][key]["count"] for dim, key in SUBITEMS}


def feasible(family, excerpt, counts):
    """这条处境的原回答能不能被这条族破坏出目标子项的单侧翻转。"""
    subitem = ".".join(FAMILIES[family]["subitem"])
    if family == "INF":
        return counts[subitem] == 0
    if family == "ENVQ":
        return counts[subitem] == 0
    return counts[subitem] == 1 and bool(judge.GATE.search(judge.last_user_turn(excerpt)))


def build_plan(limit):
    situations = load_jsonl(SITUATIONS)
    answers = {row["situation"]: row["response"]
               for row in load_jsonl(ANSWERS) if row["arm"] == "full"}
    narrowed = json.loads(COVERAGE.read_text(encoding="utf-8"))
    wide = json.loads(COVERAGE_WIDE.read_text(encoding="utf-8"))
    nodes = {node["dot_path"]: node for node in json.loads(NODES.read_text(encoding="utf-8"))}
    trainable = {path for path, node in nodes.items() if node["trainable"]}
    delivered = collections.Counter(path for paths in narrowed.values() for path in paths)

    annotated = {}
    for source, table in (("delivered", narrowed), ("wide", wide)):
        for situation, paths in table.items():
            for path in paths:
                annotated.setdefault(path, {}).setdefault(situation, source)

    by_id = {row["situation_id"]: row for row in situations}
    plan, used = [], set()
    # 零覆盖规则优先，其次按标注该规则的处境数从少到多（稀缺先去），再按 dot path 定序。
    order = [rule for rule in RULE_FAMILY
             if rule in trainable and rule in annotated]
    order.sort(key=lambda rule: (delivered.get(rule, 0) > 0, len(annotated[rule]), rule))
    for rule in order:
        family = RULE_FAMILY[rule]
        if len(plan) >= limit:
            break
        hits = sorted(annotated[rule])
        for situation in hits:
            if len(plan) >= limit:
                break
            if situation in used or situation not in by_id or situation not in answers:
                continue
            excerpt = by_id[situation]["excerpt"]
            answer = answers[situation]
            counts = counts_of(excerpt, answer)
            if not feasible(family, excerpt, counts):
                continue
            used.add(situation)
            plan.append({"situation_id": situation, "target_rule": rule, "family": family,
                         "subitem": ".".join(FAMILIES[family]["subitem"]),
                         "annotation_source": annotated[rule][situation],
                         "delivered_coverage": delivered.get(rule, 0),
                         "rule_text": nodes[rule]["text"],
                         "excerpt": excerpt, "chosen": answer, "base_counts": counts})
    return nodes, plan


# ---------- 生成 ----------

def build_prompt(entry):
    family = entry["family"]
    return (
        "下面是一段真实会话处境（以用户轮结尾），以及模型在读到一部操作法之后给出的回答原文。\n\n"
        f"=== 处境 ===\n{entry['excerpt']}\n\n"
        f"=== 原回答 ===\n{entry['chosen']}\n\n"
        f"=== 要破坏的规则 ===\n{entry['target_rule']}\n{entry['rule_text']}\n\n"
        "任务：把原回答改坏一处，让修改后的回答违反上面这条规则。\n"
        f"做法：{FAMILIES[family]['hint']}\n"
        "步骤：(1) 在原回答里找出与这条规则最相关的一处判断；(2) 按上面的做法把它改坏；"
        "(3) 检查改写后的回答确实违反了这条规则，并且与原回答逐字不同。"
        "如果原回答里找不到自然的改写点，就在末尾补一句不超过 40 字的短句来违反这条规则，其余不动。\n"
        "只改这一处，其它内容、工具调用、语言、顺序与格式保持原样。"
        "只输出改写后的完整回答正文：不要解释，不要标题，不要代码围栏，不要复述这段指令。"
    )


def clean(answer):
    text = answer.strip()
    fence = re.match(r"^```[a-zA-Z]*\n(.*)\n```$", text, re.S)
    return fence.group(1).strip() if fence else text


def generate(entry, attempt):
    global SEQUENCE
    prompt = build_prompt(entry)
    body = {"model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "thinking": {"type": "disabled"}}
    response, latency = post(body)
    usage = response.get("usage", {})
    answer = clean(response["choices"][0]["message"].get("content") or "")
    with LOCK:
        SEQUENCE += 1
        row = {"call_id": f"c{SEQUENCE:04d}", "phase": "corrupt", "attempt": attempt, "situation": entry["situation_id"],
               "target_rule": entry["target_rule"], "family": entry["family"],
               "subitem": entry["subitem"], "annotation_source": entry["annotation_source"],
               "model": MODEL, "temperature": TEMPERATURE, "thinking": "disabled",
               "request_chars": len(prompt), "request_sha256": sha(prompt),
               "created": response.get("created", 0), "latency_s": round(latency, 2),
               "finish_reason": response["choices"][0].get("finish_reason"),
               "prompt": prompt, "original": entry["chosen"], "rewritten": answer,
               "usage": usage, "cost": call_cost(usage, response.get("created", 0))}
        OUT.mkdir(parents=True, exist_ok=True)
        with CALLS.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


# ---------- 确定性校验 ----------

def wrap_ratio(text, width=72):
    """复读检测：同一段 width 字符的窗口重复出现 3 次以上。"""
    windows = collections.Counter(text[index:index + width]
                                 for index in range(0, max(0, len(text) - width + 1)))
    return max(windows.values(), default=0)


def verification(entry, row):
    rewritten = row["rewritten"]
    after = counts_of(entry["excerpt"], rewritten)
    before = entry["base_counts"]
    subitem = entry["subitem"]
    family = entry["family"]
    direction = FAMILIES[family]["worse"]

    target_flip = (after[subitem] is not None and before[subitem] is not None
                   and ((direction == "up" and after[subitem] > before[subitem])
                        or (direction == "down" and after[subitem] < before[subitem])))
    moved = [name for name in before if name != subitem and before[name] != after[name]]
    others_unchanged = not moved

    similarity = difflib.SequenceMatcher(None, entry["chosen"], rewritten).ratio()
    length_ratio = len(rewritten) / max(1, len(entry["chosen"]))
    similar = similarity >= MIN_SIMILARITY and MIN_LENGTH_RATIO <= length_ratio <= MAX_LENGTH_RATIO

    repeats = wrap_ratio(rewritten)
    echoed = ("要破坏的规则" in rewritten or "=== 原回答 ===" in rewritten
              or "任务：把原回答改坏" in rewritten or "做法：" in rewritten)
    whole = (row["finish_reason"] == "stop" and len(rewritten) >= 20 * length_ratio
             and repeats < 3 and not echoed)

    unchanged = rewritten.strip() == entry["chosen"].strip()
    reasons = []
    if unchanged:
        reasons.append("未改动(逐字相同)")
    elif not target_flip:
        reasons.append("目标子项没翻转")
    if not others_unchanged:
        reasons.append("带动其他子项:" + ",".join(moved))
    if not similar:
        reasons.append(f"相似度或长度比不合格({similarity:.3f},{length_ratio:.2f})")
    if not whole:
        reasons.append("不完整:" + ",".join(
            name for name, ok in (("finish_reason", row["finish_reason"] == "stop"),
                                  ("复读", repeats < 3), ("回显", not echoed)) if not ok))

    signature = lambda text: " ; ".join(
        f"{action['tool']}/{judge.action_class(action)}" for action in judge.parse_actions(text))
    return {"situation_id": entry["situation_id"], "target_rule": entry["target_rule"],
            "family": family, "subitem": subitem, "call_id": row["call_id"],
            "before": before, "after": after,
            "target_flip": target_flip, "others_unchanged": others_unchanged,
            "moved_subitems": moved, "similarity": round(similarity, 4),
            "length_ratio": round(length_ratio, 3), "repeat_windows": repeats,
            "finish_reason": row["finish_reason"], "complete": whole,
            "unchanged": unchanged,
            "accepted": target_flip and others_unchanged and similar and whole,
            "discard_reasons": reasons,
            "chosen_signature": signature(entry["chosen"]),
            "rejected_signature": signature(rewritten)}


def write_summary(nodes, plan, rows, checks):
    delivered = collections.Counter(path for paths in
                                   json.loads(COVERAGE.read_text(encoding="utf-8")).values()
                                   for path in paths)
    accepted = [check for check in checks if check["accepted"]]
    reasons = collections.Counter(reason.split("(")[0].split(":")[0]
                                  for check in checks for reason in check["discard_reasons"])
    moved_alone = sum(1 for check in checks if check["target_flip"] and check["others_unchanged"])
    flipped = sum(1 for check in checks if check["target_flip"])
    per_rule = collections.Counter(check["target_rule"] for check in accepted)
    per_family = collections.Counter(check["family"] for check in accepted)
    rules = sorted(per_rule)
    totals = [row["cost"]["cny"] for row in rows]
    summary = {
        "attempts": len(rows), "verified": len(accepted),
        "discarded": len(checks) - len(accepted),
        "discard_reasons": dict(reasons),
        "target_flipped": flipped,
        "single_cause_among_flipped": round(moved_alone / flipped, 4) if flipped else None,
        "single_cause_among_verified": 1.0 if accepted else None,
        "similarity_median": sorted(check["similarity"] for check in accepted)[len(accepted) // 2] if accepted else None,
        "rules_covered": len(rules),
        "rules_zero_coverage_before": sum(1 for rule in rules if delivered.get(rule, 0) == 0),
        "rules_covered_list": rules,
        "per_rule_accepted": dict(per_rule),
        "per_family_accepted": dict(per_family),
        "planned_per_rule": dict(collections.Counter(e["target_rule"] for e in plan)),
        "spend_cny": round(sum(totals), 5),
        "model": MODEL, "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS,
        "similarity_threshold": MIN_SIMILARITY,
        "pairs_file": "data/pairs-corrupted.jsonl",
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def accepted_of(by_situation, entry):
    row = by_situation.get(entry["situation_id"])
    return bool(row) and verification(entry, row)["accepted"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--retry", action="store_true")
    parser.add_argument("--limit", type=int, default=MAX_ATTEMPTS)
    args = parser.parse_args()

    nodes, plan = build_plan(args.limit)
    if args.plan:
        for entry in plan:
            print(f"{entry['situation_id']} {entry['family']:<5} {entry['target_rule']:<45} "
                  f"cov={entry['delivered_coverage']:<2} src={entry['annotation_source']:<9} "
                  f"base={entry['base_counts'][entry['subitem']]}")
        print(f"{len(plan)} planned pairs; families "
              f"{dict(collections.Counter(e['family'] for e in plan))}; "
              f"rules {len({e['target_rule'] for e in plan})}")
        return

    OUT.mkdir(parents=True, exist_ok=True)
    if CALLS.exists():
        existing = load_jsonl(CALLS)
        global SEQUENCE
        SEQUENCE = len(existing)
        by_situation = {}
        attempts = collections.Counter()
        for row in existing:
            by_situation[row["situation"]] = row
            attempts[row["situation"]] = max(attempts[row["situation"]], row.get("attempt", 1))
    else:
        by_situation, attempts = {}, collections.Counter()

    def verify_all():
        return [verification(entry, by_situation[entry["situation_id"]])
                for entry in plan if entry["situation_id"] in by_situation]

    # 第一轮：每条处境一次；--retry 时对没过关的处境再补一次（记录 attempt 2，可取回）。
    rounds = [1, 2, 3] if args.retry else [1]
    for attempt in rounds:
        todo = [entry for entry in plan
                if entry["situation_id"] not in by_situation or
                (attempt > 1 and not accepted_of(by_situation, entry))]
        if attempt == 1 and not todo:
            print("all planned situations already generated")
        if attempt > 1:
            todo = [entry for entry in plan
                    if attempts[entry["situation_id"]] < attempt
                    and not accepted_of(by_situation, entry)]
        print(f"attempt {attempt}: {len(todo)} corruptions to generate")
        if not todo:
            continue
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(generate, entry, attempt) for entry in todo]
            for count, future in enumerate(futures, 1):
                row = future.result()
                by_situation[row["situation"]] = row
                attempts[row["situation"]] = attempt
                if count % 10 == 0:
                    print(f"  {count}/{len(futures)} corruptions done", flush=True)

    rows = list(by_situation.values())
    checks = verify_all()
    VERIFY.write_text("".join(json.dumps(check, ensure_ascii=False) + "\n" for check in checks),
                      encoding="utf-8")
    pairs = []
    for entry in plan:
        check = next((item for item in checks if item["situation_id"] == entry["situation_id"]), None)
        if not check or not check["accepted"]:
            continue
        pairs.append({"situation_id": entry["situation_id"], "excerpt": entry["excerpt"],
                      "chosen": entry["chosen"], "rejected": by_situation[entry["situation_id"]]["rewritten"],
                      "target_rule": entry["target_rule"], "subitem": entry["subitem"],
                      "flipped_subitem": check["subitem"], "similarity": check["similarity"],
                      "before": check["before"], "after": check["after"],
                      "chosen_signature": check["chosen_signature"],
                      "rejected_signature": check["rejected_signature"],
                      "call_id": check["call_id"]})
    PAIRS.write_text("".join(json.dumps(pair, ensure_ascii=False) + "\n" for pair in pairs),
                     encoding="utf-8")
    summary = write_summary(nodes, plan, rows, checks)
    print(json.dumps({key: summary[key] for key in
                      ("attempts", "verified", "discarded", "discard_reasons",
                       "single_cause_among_flipped", "rules_covered",
                       "rules_zero_coverage_before", "per_family_accepted", "spend_cny")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
