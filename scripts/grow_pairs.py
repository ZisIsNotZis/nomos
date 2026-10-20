#!/usr/bin/env python3
"""把没用过的合格处境长成新的双答对，并给出它们补上的规则覆盖。

183 条合格处境已经取过带法/不带法两答并筛到 174 条（`data/pairs.jsonl`、
`data/pairs-filtered.jsonl`），二次抽样判定可复现的那 66 条在
`data/pairs-stable.jsonl`。`mining/candidates.jsonl` 里还有一批合格但没用的处境，
这是唯一的增长池：处境数量由输入决定，不靠新找材料。

四个阶段，互不依赖网络之外的状态，每一步都可续跑：

  --build     按 evidence/slice-contrast/build.py 的同一条合格规则重算池子，减去
              已用的 window，剩下的处境写 `evidence/grow/situations.jsonl`。同时跑
              请求重建闸：把已用 183 条处境的两种请求按 common.build 同一路径重建，
              与 `evidence/slice-contrast/answers.jsonl` 记下的 request_sha256 逐条
              比对，366 条全中才说明新批次与老批次是同一条提示，否则停。
  --generate  每条处境四次调用：law 抽一次、bare 抽一次、law 再抽一次、bare 再抽
              一次。模型、温度、thinking、max_tokens、INSTRUCTION 全部导入老批次
              的定义，不复制。落在 `evidence/grow/answers.jsonl`。
  --analyse   纯 Python：复用 `scripts/filter_pairs.py` 的实质相同/截断/复读/回显
              判据与 `scripts/resample_actions.py` 的动作签名，把新处境筛成稳定对，
              与老 66 条合并写 `data/pairs-stable-v2.jsonl`（每行记 batch）。
  --annotate  用 `scripts/annotate_coverage.py` 的同一条标注规则（同 system 消息、
              同 temperature、同 max_tags 4）给新处境标可训练规则，落在
              `evidence/grow/coverage/`，system 消息 sha256 与老批次核对。
  --report    纯 Python：把上面所有数字汇总到 `evidence/grow/summary.json` 与
              `report/grow-pairs.md`，并算清哪些此前零覆盖的规则现在有覆盖。

用法：
  python3 scripts/grow_pairs.py --build
  python3 scripts/grow_pairs.py --generate
  python3 scripts/grow_pairs.py --analyse
  python3 scripts/grow_pairs.py --annotate
  python3 scripts/grow_pairs.py --report
"""

import argparse
import importlib.util
import json
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SLICE_CONTRAST = REPO / "evidence" / "slice-contrast"
SOURCE_ANSWERS = SLICE_CONTRAST / "answers.jsonl"
SOURCE_SITUATIONS = SLICE_CONTRAST / "situations.jsonl"
SOURCE_PAIRS = REPO / "data" / "pairs.jsonl"
SOURCE_STABLE = REPO / "data" / "pairs-stable.jsonl"
FILTERED = REPO / "data" / "pairs-filtered.jsonl"
COUNTS = REPO / "data" / "coverage-counts.json"
COVERAGE = REPO / "data" / "coverage.json"

EVIDENCE = REPO / "evidence" / "grow"
SITUATIONS = EVIDENCE / "situations.jsonl"
ANSWERS = EVIDENCE / "answers.jsonl"
POOL = EVIDENCE / "pool.json"
GENERATE_META = EVIDENCE / "generate-meta.json"
SIGNATURES = EVIDENCE / "signatures.jsonl"
METRICS = EVIDENCE / "pair-metrics.jsonl"
DROPPED = EVIDENCE / "dropped.jsonl"
FILTER_COUNTS = EVIDENCE / "filter-counts.json"
COVERAGE_DIR = EVIDENCE / "coverage"
SUMMARY = EVIDENCE / "summary.json"
REPORT = REPO / "report" / "grow-pairs.md"

GROW_PAIRS = REPO / "data" / "pairs-grow.jsonl"
GROW_FILTERED = REPO / "data" / "pairs-grow-filtered.jsonl"
GROW_STABLE = REPO / "data" / "pairs-grow-stable.jsonl"
STABLE_V2 = REPO / "data" / "pairs-stable-v2.jsonl"

BATCH_OLD = "slice-contrast"
BATCH_NEW = "grow"
DRAWS = (("law", 0), ("bare", 0), ("law", 1), ("bare", 1))
WORKERS = 6
MAX_CNY = 5.0


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


p4 = load_module("probe4common", SLICE_CONTRAST / "common.py")
ra = load_module("resample_actions", HERE / "resample_actions.py")
fq = load_module("filter_pairs", HERE / "filter_pairs.py")
ac = load_module("annotate_coverage", HERE / "annotate_coverage.py")
lib = ra.lib

INSTRUCTION = p4.INSTRUCTION
sha = ra.sha
load_jsonl = ra.load_jsonl


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


# --- 池子 ------------------------------------------------------------------

def eligible_pool():
    """evidence/slice-contrast/build.py 的合格规则，原样重算。"""
    eligible, funnel = [], Counter()
    for record in load_jsonl(p4.CANDIDATES):
        if not record["signals"]:
            funnel["no_signal"] += 1
            continue
        if p4.SENSITIVE.search(record["text"]):
            funnel["credential_looking"] += 1
            continue
        if not p4.ends_with_user(record["text"]):
            funnel["not_end_on_user"] += 1
            continue
        eligible.append(record)
    return eligible, dict(funnel)


def run_build():
    eligible, funnel = eligible_pool()
    used = load_jsonl(SOURCE_SITUATIONS)
    used_windows = {row["window_id"] for row in used}
    eligible_windows = {row["window_id"] for row in eligible}
    if not used_windows <= eligible_windows:
        raise SystemExit("已用的 window 不在合格池里，合格规则与老批次不一致")
    new = sorted((row for row in eligible if row["window_id"] not in used_windows),
                 key=lambda row: (row["session"], row["window_id"]))

    situations = []
    for index, record in enumerate(new, start=1):
        excerpt = p4.truncate(record["text"])
        if not p4.ends_with_user(excerpt):
            raise SystemExit(f"{record['window_id']}: 截断后不以用户轮结尾")
        patterns = p4.redaction_patterns() if hasattr(p4, "redaction_patterns") else _patterns()
        for label, pattern in patterns:
            match = pattern.search(excerpt)
            if match:
                raise SystemExit(f"{record['window_id']}: {label}: {match.group(0)[:80]!r}")
        situations.append({
            "id": f"GRW{index:03d}",
            "batch": BATCH_NEW,
            "signal": record["signals"][0],
            "signals": record["signals"],
            "session": record["session"],
            "window_id": record["window_id"],
            "turn_indices": record["turn_indices"],
            "source_chars": len(record["text"]),
            "excerpt_chars": len(excerpt),
            "ends_with_user": True,
            "excerpt": excerpt,
        })
    write_jsonl(SITUATIONS, situations)

    # 请求重建闸：老批次 183 条处境的两种请求必须逐条重建得一模一样。
    law = ra.law_text()
    stored = {(row["situation"], row["arm"]): row for row in load_jsonl(SOURCE_ANSWERS)
              if row["phase"] == "generate"}
    checked, mismatches = 0, []
    for pair in json.loads(SOURCE_PAIRS.read_text(encoding="utf-8")):
        for arm in ("law", "bare"):
            system, prompt, _ = ra.build_messages(pair, arm, law)
            rebuilt = sha(system + "\x00" + prompt)
            origin = stored[(pair["situation_id"], ra.SOURCE_ARM[arm])]["request_sha256"]
            checked += 1
            if rebuilt != origin:
                mismatches.append(pair["situation_id"] + "/" + arm)
    if mismatches:
        raise SystemExit(f"请求重建不一致 {len(mismatches)} 条，新批次不能与老批次比：{mismatches[:5]}")

    per_signal = Counter(row["signal"] for row in situations)
    raw = json.loads(SOURCE_PAIRS.read_text(encoding="utf-8"))
    pool = {
        "rule": "合格 = mining/candidates.jsonl 里 signals 非空、不含凭据样式、正文以用户轮结尾；"
                "已用 = evidence/slice-contrast/situations.jsonl 的 window",
        "candidates": len(load_jsonl(p4.CANDIDATES)),
        "eligibility_funnel": funnel,
        "eligible": len(eligible),
        "eligible_sessions": len({row["session"] for row in eligible}),
        "used_by_previous_batch": len(used),
        "used_windows": len(used_windows),
        "unused": len(situations),
        "unused_sessions": len({row["session"] for row in situations}),
        "unused_new_sessions": len({row["session"] for row in situations}
                                   - {row["session"] for row in used}),
        "per_signal": dict(per_signal),
        "request_gate": {
            "claim": "新批次与老批次是同一条提示构造",
            "method": "用 evidence/slice-contrast/common.build 的同一路径重建 183 条处境 × 2 条件的请求，"
                      "与 evidence/slice-contrast/answers.jsonl 的 request_sha256 逐条比对",
            "pairs_checked": len(raw),
            "requests_checked": checked,
            "mismatches": len(mismatches),
            "law_commit": ra.LAW_COMMIT,
            "law_sha256": ra.LAW_SHA256,
            "instruction_sha256": sha(INSTRUCTION),
            "request_sha256_rule": "sha256(system + '\\x00' + excerpt + INSTRUCTION)",
        },
    }
    POOL.write_text(json.dumps(pool, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"合格处境 {len(eligible)}，老批次用了 {len(used)}，本次增长池 {len(situations)} 条"
          f"（{pool['unused_sessions']} 个会话，其中 {pool['unused_new_sessions']} 个会话此前未出现）")
    print(f"请求重建闸：{checked} 条请求全部与老批次一致（不一致 {len(mismatches)}）")


def _patterns():
    path = REPO / "mining" / "check_redaction.py"
    spec = importlib.util.spec_from_file_location("check_redaction", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PATTERNS


# --- 生成 ------------------------------------------------------------------

def build_messages(situation, arm, law):
    """与 evidence/slice-contrast/run_generate.py 同一构造，arm 只换成 law/bare。"""
    system = law if arm == "law" else ""
    prompt = situation["excerpt"] + INSTRUCTION
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}]
    return system, prompt, messages


def existing_key(row):
    return (row["situation"], row["draw"], row["arm"])


def run_generate():
    law = ra.law_text()
    situations = load_jsonl(SITUATIONS)
    done = {existing_key(row) for row in load_jsonl(ANSWERS)} if ANSWERS.exists() else set()
    pending = [(situation, arm, draw) for situation in situations for arm, draw in DRAWS
               if (situation["id"], draw, arm) not in done]
    if not pending:
        print("四次抽样已全部落盘")
        return

    stored = [row for row in load_jsonl(SOURCE_ANSWERS) if row["phase"] == "generate"]
    per_call = sum(row["cost"]["cny"] for row in stored) / len(stored)
    projected = per_call * len(pending)
    print(f"{len(situations)} 条处境 × 4 次；待调用 {len(pending)} 次；"
          f"按老批次每次 ¥{per_call:.5f} 投影 ¥{projected:.2f}")
    if projected > MAX_CNY:
        raise SystemExit(f"投影 ¥{projected:.2f} 超过上限 ¥{MAX_CNY:.2f}")
    lib.api_key()

    lock = threading.Lock()
    counter = {"n": len(done)}

    def work(item):
        situation, arm, draw = item
        system, prompt, messages = build_messages(situation, arm, law)
        if arm == "bare":
            if system or law[:80] in prompt or law[-80:] in prompt:
                raise SystemExit(f"{situation['id']}: bare 条件的请求里出现了法条原文")
        elif system != law:
            raise SystemExit(f"{situation['id']}: law 条件没有整部法原文作 system 消息")
        body = {"model": lib.MODEL, "messages": messages, "temperature": ra.TEMPERATURE,
                "max_tokens": ra.MAX_TOKENS, "thinking": {"type": "disabled"}}
        response, latency = lib.post(body)
        usage = response.get("usage", {})
        answer = (response["choices"][0]["message"].get("content") or "").strip()
        if not answer:
            raise SystemExit(f"{situation['id']} {arm} 抽 {draw}: 空回答")
        with lock:
            counter["n"] += 1
            row = lib.record(f"w{counter['n']:04d}", "grow", situation["id"], arm, draw,
                             ra.TEMPERATURE, prompt, answer, usage, response.get("created", 0), latency)
            row = dict(row)
            row["draw"] = draw
            row["batch"] = BATCH_NEW
            row["finish_reason"] = response["choices"][0].get("finish_reason")
            row["request_sha256"] = sha(system + "\x00" + prompt)
            row["system_chars"] = len(system)
            row["system_sha256"] = sha(system) if system else None
            ra.append_rows(ANSWERS, [row])
        return row

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(work, item) for item in pending]
        for index, future in enumerate(futures, 1):
            future.result()
            if index % 40 == 0:
                print(f"  {index}/{len(futures)} 次调用完成", flush=True)

    rows = load_jsonl(ANSWERS)
    spend = sum(row["cost"]["cny"] for row in rows)
    GENERATE_META.write_text(json.dumps({
        "model": lib.MODEL, "temperature": ra.TEMPERATURE, "max_tokens": ra.MAX_TOKENS,
        "thinking": "disabled", "arms": {"law": "整部 AGENTS.md 作 system 消息", "bare": "无 system 消息"},
        "draws_per_arm": 2, "law_commit": ra.LAW_COMMIT, "law_sha256": ra.LAW_SHA256,
        "instruction_sha256": sha(INSTRUCTION),
        "situations": len(situations), "calls": len(rows), "spend_cny": round(spend, 6),
        "bare_arm_gate": "bare 请求必须没有 system 消息，且正文里不出现法条原文的首尾片段",
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{ANSWERS.name} {len(rows)} 行，花费 ¥{spend:.3f}")


# --- 分析与合并 ------------------------------------------------------------

def grow_pairs():
    """每行一条处境的两答：chosen = law 抽 1，rejected = bare 抽 1。"""
    situations = load_jsonl(SITUATIONS)
    answers = {(row["situation"], row["draw"], row["arm"]): row for row in load_jsonl(ANSWERS)}
    rows = []
    for situation in situations:
        need = [(situation["id"], draw, arm) for arm, draw in DRAWS]
        missing = [key for key in need if key not in answers]
        if missing:
            raise SystemExit(f"缺 {len(missing)} 条回答，先跑 --generate：{missing[:3]}")
        rows.append({
            "situation_id": situation["id"],
            "batch": BATCH_NEW,
            "window_id": situation["window_id"],
            "session": situation["session"],
            "signals": situation["signals"],
            "excerpt": situation["excerpt"],
            "chosen": answers[(situation["id"], 0, "law")]["response"],
            "rejected": answers[(situation["id"], 0, "bare")]["response"],
        })
    return rows


def run_analyse():
    pairs = grow_pairs()
    write_jsonl(GROW_PAIRS, pairs)
    answers = {(row["situation"], row["draw"], row["arm"]): row for row in load_jsonl(ANSWERS)}
    finish = {key: row.get("finish_reason") for key, row in answers.items()}

    def reproduction(pair, by_answers):
        """四个签名的字典，与两侧是否被自己的第二次抽样复现。"""
        sid = pair["situation_id"]
        draws = {"law_0": ra.signatures(pair["chosen"]), "bare_0": ra.signatures(pair["rejected"]),
                 "law_1": ra.signatures(by_answers[(sid, 1, "law")]["response"]),
                 "bare_1": ra.signatures(by_answers[(sid, 1, "bare")]["response"])}
        main = {draw: value["signature"] for draw, value in draws.items()}
        return {"draws": draws, "main": main,
                "law": main["law_0"] == main["law_1"],
                "bare": main["bare_0"] == main["bare_1"]}

    kept, metrics, dropped = [], [], []
    dropped_ids = set()
    for pair in pairs:
        criterion, why = fq.same_decision(pair["chosen"], pair["rejected"])
        reasons = []
        if criterion:
            reasons.append({"reason": "same_decision", "criterion": criterion, "evidence": why})
        for arm in ("chosen", "rejected"):
            cut = fq.truncation(pair[arm])
            if cut:
                reasons.append({"reason": "truncated", "arms": [arm], "evidence": cut,
                                "finish_reason": finish.get((pair["situation_id"], 0,
                                                             "law" if arm == "chosen" else "bare"))})
                continue
            loop = fq.repetition(pair[arm])
            if loop:
                reasons.append({"reason": "repetition", "arms": [arm], "evidence": loop})
            heard = fq.echo(pair[arm], pair["excerpt"])
            if heard:
                reasons.append({"reason": "echo", "arms": [arm], "evidence": heard})
        metrics.append({"situation_id": pair["situation_id"],
                        "length_ratio": round(min(len(fq.normalize(pair["chosen"])),
                                                  len(fq.normalize(pair["rejected"])))
                                              / max(len(fq.normalize(pair["chosen"])),
                                                    len(fq.normalize(pair["rejected"]))), 4),
                        "identical_after_normalize": fq.normalize(pair["chosen"]) == fq.normalize(pair["rejected"]),
                        "reasons": [reason["reason"] for reason in reasons]})
        if reasons:
            dropped_ids.add(pair["situation_id"])
            dropped.append({**{k: pair[k] for k in ("situation_id", "batch", "signals")},
                            "reasons": reasons})
        else:
            kept.append(pair)

    signature_rows, compare_rows, stable, not_reproduced, both_empty = [], [], [], [], []
    for pair in kept:
        result = reproduction(pair, answers)
        draws, main = result["draws"], result["main"]
        for draw, value in draws.items():
            signature_rows.append({"situation_id": pair["situation_id"], "draw": draw,
                                   "signature": value["signature"], "coarse": value["coarse"],
                                   "actions": value["actions"]})
        law_ok, bare_ok = result["law"], result["bare"]
        compare_rows.append({"situation_id": pair["situation_id"],
                             "signatures": main,
                             "reproduced": {"law": law_ok, "bare": bare_ok},
                             "cross_condition_differs": main["law_0"] != main["bare_0"]})
        if not (law_ok and bare_ok):
            not_reproduced.append({"situation_id": pair["situation_id"],
                                   "law_not_reproduced": not law_ok,
                                   "bare_not_reproduced": not bare_ok})
            continue
        if not main["law_0"] and not main["bare_0"]:
            both_empty.append(pair["situation_id"])
        stable.append({"situation_id": pair["situation_id"], "batch": BATCH_NEW,
                       "window_id": pair["window_id"], "signals": pair["signals"],
                       "excerpt": pair["excerpt"], "chosen": pair["chosen"], "rejected": pair["rejected"],
                       "signatures": {"law": main["law_0"], "bare": main["bare_0"]},
                       "law_second_draw": main["law_1"], "bare_second_draw": main["bare_1"],
                       "cross_condition_differs": main["law_0"] != main["bare_0"]})

    write_jsonl(GROW_FILTERED, kept)
    write_jsonl(METRICS, metrics)
    write_jsonl(DROPPED, dropped)
    write_jsonl(SIGNATURES, signature_rows)
    write_jsonl(GROW_STABLE, stable)

    reasons = Counter(reason["reason"] for row in dropped for reason in row["reasons"])
    filter_counts = {
        "input_pairs": len(pairs),
        "kept_after_quality": len(kept),
        "dropped_quality": {
            "total": len(dropped),
            "same_decision": len({row["situation_id"] for row in dropped
                                  if any(r["reason"] == "same_decision" for r in row["reasons"])}),
            "same_decision_by_criterion": dict(Counter(
                r.get("criterion") for row in dropped for r in row["reasons"] if r["reason"] == "same_decision")),
            "broken": len({row["situation_id"] for row in dropped
                           if any(r["reason"] in ("truncated", "repetition", "echo") for r in row["reasons"])}),
            "broken_by_reason": {name: reasons[name] for name in ("truncated", "repetition", "echo")},
            "broken_by_arm": dict(Counter(arm for row in dropped for r in row["reasons"]
                                          for arm in r.get("arms", []) if r["reason"] != "same_decision")),
        },
        "reproduction": {
            "rule": "存下的 law 回答被第二次 law 抽样复现，且存下的 bare 回答被第二次 bare 抽样复现（动作签名逐项相同）",
            "evaluated_on": len(kept),
            "dropped_total": len(not_reproduced),
            "dropped_law_not_reproduced_only": sum(1 for row in not_reproduced
                                                   if row["law_not_reproduced"] and not row["bare_not_reproduced"]),
            "dropped_bare_not_reproduced_only": sum(1 for row in not_reproduced
                                                    if row["bare_not_reproduced"] and not row["law_not_reproduced"]),
            "dropped_both": sum(1 for row in not_reproduced
                                if row["bare_not_reproduced"] and row["law_not_reproduced"]),
        },
        "surviving": len(stable),
        "surviving_both_sides_without_actions": len(both_empty),
        "quality_dropped_also_not_reproduced": sum(
            1 for pair in pairs if pair["situation_id"] in dropped_ids and
            not (lambda result: result["law"] and result["bare"])(reproduction(pair, answers))),
    }
    FILTER_COUNTS.write_text(json.dumps(filter_counts, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    merged = merge_stable(stable)
    print(f"新处境 {len(pairs)} 条：实质相同/坏件筛掉 {len(dropped)}，"
          f"余 {len(kept)} 条里两侧都由二次抽样复现 {len(stable)} 条")
    print(f"合并后的稳定对 {len(merged)} 条，见 {STABLE_V2.relative_to(REPO)}")
    return filter_counts


def merge_stable(new_stable):
    """老 66 条已经两批可复现，旧行原本不带第二抽签名，从 evidence/resample/signatures.jsonl 接上。"""
    seconds = {}
    for row in load_jsonl(REPO / "evidence" / "resample" / "signatures.jsonl"):
        if row["draw"] in ("law_1", "bare_1"):
            seconds.setdefault(row["situation_id"], {})[row["draw"]] = row["signature"]
    old = load_jsonl(SOURCE_STABLE)
    rows = []
    for row in old:
        second = seconds[row["situation_id"]]
        rows.append({"situation_id": row["situation_id"], "batch": BATCH_OLD, "window_id": None,
                     "signals": row["signals"], "excerpt": row["excerpt"], "chosen": row["chosen"],
                     "rejected": row["rejected"], "signatures": row["signatures"],
                     "law_second_draw": second["law_1"], "bare_second_draw": second["bare_1"],
                     "cross_condition_differs": row["cross_condition_differs"]})
    rows.extend(new_stable)
    if len({row["situation_id"] for row in rows}) != len(rows):
        raise SystemExit("合并后处境重复")
    write_jsonl(STABLE_V2, rows)
    return rows


# --- 覆盖标注 --------------------------------------------------------------

def run_annotate():
    COVERAGE_DIR.mkdir(parents=True, exist_ok=True)
    calls_path = COVERAGE_DIR / "calls.jsonl"
    coverage_path = COVERAGE_DIR / "coverage.json"
    nodes = ac.trainable_nodes()
    allowed = {node["dot_path"] for node in nodes}
    system = ac.system_message(nodes, 4)
    old_meta = json.loads((REPO / "evidence" / "coverage" / "run-meta.json").read_text(encoding="utf-8"))
    if sha(system) != old_meta["system_message_sha256"]:
        raise SystemExit("覆盖标注的 system 消息与老批次不同，标注结果不可比")
    pairs = load_jsonl(GROW_FILTERED)
    coverage = json.loads(coverage_path.read_text(encoding="utf-8")) if coverage_path.exists() else {}
    pending = [pair for pair in pairs if pair["situation_id"] not in coverage]
    if not pending:
        print("覆盖标注已全部落盘")
        return
    ac.api_key()
    print(f"待标注 {len(pending)} 条处境")
    lock = threading.Lock()

    def work(pair):
        paths = ac.annotate(pair, system, allowed, calls_path, 4)
        with lock:
            coverage[pair["situation_id"]] = paths

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(work, pair) for pair in pending]
        for index, future in enumerate(futures, 1):
            future.result()
            if index % 20 == 0:
                print(f"  {index}/{len(futures)} 条标注完成", flush=True)
    coverage_path.write_text(json.dumps(coverage, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    rows = load_jsonl(calls_path)
    (COVERAGE_DIR / "run-meta.json").write_text(json.dumps({
        "model": ac.MODEL, "temperature": ac.TEMPERATURE, "max_tokens": ac.MAX_TOKENS,
        "thinking": "disabled", "max_tags": 4, "rules": len(nodes),
        "system_message_sha256": sha(system), "rules_block_sha256": sha(ac.rules_block(nodes)),
        "old_batch_system_message_sha256": old_meta["system_message_sha256"],
        "situations": len(coverage), "calls": len(rows),
        "spend_cny": round(sum(row["cost_cny"] for row in rows), 6),
        "input_pairs_sha256": sha(GROW_FILTERED.read_text(encoding="utf-8")),
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"标注 {len(coverage)} 条，花费 ¥{sum(row['cost_cny'] for row in rows):.3f}")


# --- 报告 ------------------------------------------------------------------

def coverage_report():
    old = json.loads(COUNTS.read_text(encoding="utf-8"))
    nodes = ac.trainable_nodes()
    paths = [node["dot_path"] for node in nodes]
    grow_coverage = json.loads((COVERAGE_DIR / "coverage.json").read_text(encoding="utf-8"))
    grow_counts = Counter(path for paths_ in grow_coverage.values() for path in paths_)
    merged = {path: old["counts"][path] + grow_counts[path] for path in paths}
    zero_before = [path for path in paths if old["counts"][path] == 0]
    now_covered = [path for path in zero_before if grow_counts[path] > 0]
    still_zero = [path for path in zero_before if grow_counts[path] == 0]
    return {
        "annotated_situations_old": old["situations"],
        "annotated_situations_grow": len(grow_coverage),
        "annotated_situations_merged": old["situations"] + len(grow_coverage),
        "rules": len(paths),
        "grow_tags": sum(grow_counts.values()),
        "zero_before": len(zero_before),
        "now_covered": len(now_covered),
        "still_zero": len(still_zero),
        "merged_zero": sum(1 for path in paths if merged[path] == 0),
        "now_covered_paths": [{"path": path, "grow_count": grow_counts[path],
                               "merged_count": merged[path]} for path in now_covered],
        "still_zero_paths": still_zero,
        "grow_counts": {path: grow_counts[path] for path in paths if grow_counts[path]},
    }


def run_report():
    pool = json.loads(POOL.read_text(encoding="utf-8"))
    filters = json.loads(FILTER_COUNTS.read_text(encoding="utf-8"))
    answers = load_jsonl(ANSWERS)
    grow_meta = json.loads(GENERATE_META.read_text(encoding="utf-8"))
    coverage_meta = json.loads((COVERAGE_DIR / "run-meta.json").read_text(encoding="utf-8"))
    merged = load_jsonl(STABLE_V2)

    flags = [row["cross_condition_differs"] for row in merged]
    low, high = ra.bootstrap_ci(flags)
    wlow, whist = p4.wilson(sum(1 for f in flags if f), len(flags))
    with_actions = [row for row in merged if row["signatures"]["law"] and row["signatures"]["bare"]]
    slow, shigh = ra.bootstrap_ci([row["cross_condition_differs"] for row in with_actions])
    by_batch = {}
    for batch in (BATCH_OLD, BATCH_NEW):
        rows = [row for row in merged if row["batch"] == batch]
        batch_flags = [row["cross_condition_differs"] for row in rows]
        a, b = ra.bootstrap_ci(batch_flags)
        by_batch[batch] = {"n": len(rows), "differ": sum(1 for f in batch_flags if f),
                           "rate": ra.rate(batch_flags), "ci95": [a, b],
                           "both_sides_with_actions": sum(
                               1 for row in rows if row["signatures"]["law"] and row["signatures"]["bare"])}
    coverage = coverage_report()

    summary = {
        "pool": pool,
        "generation": grow_meta,
        "filters": filters,
        "merged_stable": {
            "output": str(STABLE_V2.relative_to(REPO)),
            "n": len(merged),
            "from_slice_contrast": by_batch[BATCH_OLD]["n"],
            "from_grow": by_batch[BATCH_NEW]["n"],
            "both_sides_with_parseable_actions": len(with_actions),
            "cross_condition_disagreement": {
                "n": len(merged), "differ": sum(1 for f in flags if f),
                "rate": ra.rate(flags), "ci95_bootstrap": [low, high],
                "ci95_wilson": [wlow, whist], "bootstrap": ra.BOOTSTRAP, "seed": ra.SEED},
            "cross_condition_disagreement_both_sides_with_actions": {
                "n": len(with_actions),
                "differ": sum(1 for row in with_actions if row["cross_condition_differs"]),
                "rate": ra.rate([row["cross_condition_differs"] for row in with_actions]),
                "ci95_bootstrap": [slow, shigh]},
            "by_batch": by_batch,
            "batch_field": "batch = 这条处境来自哪一批：slice-contrast（老 183 条里可复现的）或 grow（本次新处境）",
        },
        "coverage": coverage,
        "spend_cny": {"generation": round(sum(row["cost"]["cny"] for row in answers), 6),
                      "annotation": coverage_meta["spend_cny"],
                      "total": round(sum(row["cost"]["cny"] for row in answers) + coverage_meta["spend_cny"], 6)},
        "calls": {"generation": len(answers), "annotation": coverage_meta["calls"]},
        "inputs": {"grow_situations_sha256": sha(SITUATIONS.read_text(encoding="utf-8")),
                   "grow_answers_sha256": sha(ANSWERS.read_text(encoding="utf-8")),
                   "pairs_stable_sha256": sha(SOURCE_STABLE.read_text(encoding="utf-8")),
                   "pairs_stable_v2_sha256": sha(STABLE_V2.read_text(encoding="utf-8")),
                   "pairs_grow_filtered_sha256": sha(GROW_FILTERED.read_text(encoding="utf-8")),
                   "law_sha256": ra.LAW_SHA256, "law_commit": ra.LAW_COMMIT},
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    write_report(summary)
    print(f"合并稳定对 {len(merged)} 条，跨条件不一致 {ra.rate(flags):.3f} "
          f"[{low:.3f}, {high:.3f}]；零覆盖规则 {coverage['zero_before']} → 现在有 {coverage['now_covered']} 条有覆盖")
    print(f"花费 ¥{summary['spend_cny']['total']:.3f}")


def pct(value):
    return f"{value * 100:.1f}%"


def write_report(summary):
    pool = summary["pool"]
    filters = summary["filters"]
    merged = summary["merged_stable"]
    coverage = summary["coverage"]
    differ = merged["cross_condition_disagreement"]
    quality = filters["dropped_quality"]
    reproduction = filters["reproduction"]
    old_batch = merged["by_batch"][BATCH_OLD]
    new_batch = merged["by_batch"][BATCH_NEW]
    broken_arms = {"chosen": "law", "rejected": "bare"}
    broken_by_side = {broken_arms[side]: count for side, count in quality["broken_by_arm"].items()}
    broken_arms = ("，按侧计 " + "、".join(f"{side} 侧 {count}" for side, count in broken_by_side.items())
                   if broken_by_side else "，两侧都没有坏件")
    lines = [
        f"# 增长批次：{pool['unused']} 条未用处境长成的新对，与合并后的稳定集",
        "",
        "## 结论",
        "",
        f"增长池 {pool['unused']} 条处境用完了：四次调用（law×2、bare×2）里，"
        f"{filters['input_pairs']} 条对中 {quality['total']} 条被实质相同/坏件筛掉，"
        f"余下 {filters['kept_after_quality']} 条又有 {reproduction['dropped_total']} 条不是两侧都能复现，"
        f"新增稳定对 {filters['surviving']} 条。与老 66 条合并成 {merged['n']} 条（`data/pairs-stable-v2.jsonl`），"
        f"跨条件动作不一致 {pct(differ['rate'])} [{pct(differ['ci95_bootstrap'][0])}, {pct(differ['ci95_bootstrap'][1])}]。"
        f"此前零覆盖的 {coverage['zero_before']} 条可训练规则里，新处境补上了 {coverage['now_covered']} 条，"
        f"仍零覆盖 {coverage['merged_zero']} 条。",
        "",
        "## 池子：合格 242，已用 183，本次 59",
        "",
        f"合格规则与老批次同一段代码路径重算（`evidence/grow/pool.json` 的 `eligibility_funnel`）："
        f"{pool['candidates']} 条候选 → 合格 {pool['eligible']} 条、{pool['eligible_sessions']} 个会话；"
        f"老批次用掉 {pool['used_by_previous_batch']} 条；剩下的 {pool['unused']} 条是本次增长池，"
        f"来自 {pool['unused_sessions']} 个会话，其中 {pool['unused_new_sessions']} 个会话老批次一条都没用过。",
        "",
        "新增处境按会话与 window_id 排序编号 GRW001–GRW{:03d}，原文、截断后的 excerpt、session、"
        "window_id、signals 在 `evidence/grow/situations.jsonl`。".format(pool["unused"]),
        "",
        "## 与老批次可比：请求重建闸 366/366",
        "",
        "新批次不是另起一套构造。用 `evidence/slice-contrast/common.py` 的同一路径把老 183 条处境的 "
        "law/bare 两种请求重建一遍，请求指纹（`sha256(system + '\\x00' + excerpt + INSTRUCTION)`）"
        f"与 `evidence/slice-contrast/answers.jsonl` 记录的 {pool['request_gate']['requests_checked']} 条"
        f"逐条相同，不一致 {pool['request_gate']['mismatches']} 条；法条原文是 agent-policy "
        f"{pool['request_gate']['law_commit']} 上的 AGENTS.md，sha256 `{pool['request_gate']['law_sha256']}`。"
        "模型 deepseek-flash、温度 0.0、thinking 关闭、max_tokens 600 全部导入老批次的定义。",
        "",
        "bare 条件有单独的硬检查：请求必须没有 system 消息，且正文里不出现法条原文的首尾片段，"
        "否则生成直接停（`evidence/grow/generate-meta.json` 的 `bare_arm_gate`）。",
        "",
        "## 四次调用与花费",
        "",
        f"每条处境 law 抽一次、bare 抽一次、law 再抽一次、bare 再抽一次，共 {summary['calls']['generation']} 次生成调用，"
        f"花费 ¥{summary['spend_cny']['generation']:.3f}；覆盖标注 {summary['calls']['annotation']} 次，"
        f"¥{summary['spend_cny']['annotation']:.3f}；合计 ¥{summary['spend_cny']['total']:.3f}。"
        "每次调用的请求指纹、system 指纹、原文回答、usage 与花费都在 `evidence/grow/answers.jsonl`。",
        "",
        "## 逐层筛掉的数目",
        "",
        "| 阶段 | 条数 | 说明 |",
        "| --- | --- | --- |",
        f"| 新处境对 | {filters['input_pairs']} | 每条处境一对（chosen = law 抽 1，rejected = bare 抽 1） |",
        f"| 实质相同 | {quality['same_decision']} | 归一化后相同 {quality['same_decision_by_criterion'].get('A', 0)} 条，"
        f"长度比与词集 Jaccard 双过阈值 {quality['same_decision_by_criterion'].get('B', 0)} 条 |",
        f"| 坏件 | {quality['broken']} | 截断 {quality['broken_by_reason']['truncated']}、"
        f"复读 {quality['broken_by_reason']['repetition']}、回显 {quality['broken_by_reason']['echo']}"
        f"{broken_arms} |",
        f"| 质量筛后 | {filters['kept_after_quality']} | 进入复现判定 |",
        f"| 只有 law 侧没复现 | {reproduction['dropped_law_not_reproduced_only']} | 第二次 law 抽样动作签名不同 |",
        f"| 只有 bare 侧没复现 | {reproduction['dropped_bare_not_reproduced_only']} | 第二次 bare 抽样动作签名不同 |",
        f"| 两侧都没复现 | {reproduction['dropped_both']} | 两侧都不一样 |",
        f"| 新增稳定对 | {filters['surviving']} | 两侧都被自己的第二次抽样复现 |",
        "",
        f"判据与老批次同一段代码：`scripts/filter_pairs.py` 的实质相同/截断/复读/回显，"
        f"`scripts/resample_actions.py` 的动作签名（工具、程序:子命令、目标路径）。"
        f"逐条证据在 `evidence/grow/pair-metrics.jsonl` 与 `evidence/grow/dropped.jsonl`，"
        f"计数在 `evidence/grow/filter-counts.json`。新增稳定对里两侧都解析不出动作的有 "
        f"{filters['surviving_both_sides_without_actions']} 条——它们的稳定只是四次都没动作，"
        "与老批次同一性质，对训练没有偏好信号。",
        "",
        "产出三份可直接用的数据：`data/pairs-grow.jsonl` 是新处境的两答对（一行一条 JSON），"
        "`data/pairs-grow-filtered.jsonl` 是质量筛后的 55 条，`data/pairs-grow-stable.jsonl` 是两侧都可复现的 25 条。",
        "",
        "## 合并后的稳定集",
        "",
        "| 集合 | 条数 | 跨条件动作不一致 | 95% 区间（自助） | 两侧都有可解析动作 |",
        "| --- | --- | --- | --- | --- |",
        f"| 全部（v2） | {merged['n']} | {pct(differ['rate'])} | "
        f"[{pct(differ['ci95_bootstrap'][0])}, {pct(differ['ci95_bootstrap'][1])}] | "
        f"{merged['both_sides_with_parseable_actions']} |",
        f"| 来自 slice-contrast | {old_batch['n']} | {pct(old_batch['rate'])} | "
        f"[{pct(old_batch['ci95'][0])}, {pct(old_batch['ci95'][1])}] | {old_batch['both_sides_with_actions']} |",
        f"| 来自 grow | {new_batch['n']} | {pct(new_batch['rate'])} | "
        f"[{pct(new_batch['ci95'][0])}, {pct(new_batch['ci95'][1])}] | {new_batch['both_sides_with_actions']} |",
        "",
        f"Wilson 区间给出 {pct(differ['ci95_wilson'][0])}–{pct(differ['ci95_wilson'][1])}，与自助区间同量级。"
        f"只看两侧都有可解析动作的 {merged['cross_condition_disagreement_both_sides_with_actions']['n']} 条，"
        f"不一致 {pct(merged['cross_condition_disagreement_both_sides_with_actions']['rate'])} "
        f"[{pct(merged['cross_condition_disagreement_both_sides_with_actions']['ci95_bootstrap'][0])}, "
        f"{pct(merged['cross_condition_disagreement_both_sides_with_actions']['ci95_bootstrap'][1])}]。"
        f"分批判读：grow {pct(new_batch['rate'])} 比 slice-contrast {pct(old_batch['rate'])} 高 "
        f"{abs((new_batch['rate'] - old_batch['rate']) * 100):.1f} 个百分点，两批的区间都宽，"
        "合并值不能代替分批判读。",
        "",
        f"新处境拿到的稳定对更带动作：grow 的 {new_batch['n']} 条里有 {new_batch['both_sides_with_actions']} 条两侧都有可解析动作"
        f"（{pct(new_batch['both_sides_with_actions'] / new_batch['n'])}），老 66 条里只有 {old_batch['both_sides_with_actions']} 条"
        f"（{pct(old_batch['both_sides_with_actions'] / old_batch['n'])}）——供训练用的偏好信号因此从 "
        f"{old_batch['both_sides_with_actions']} 条升到 {merged['both_sides_with_parseable_actions']} 条，这是增长最实在的产出。",
        "",
        "`data/pairs-stable-v2.jsonl` 每行记 `batch`（slice-contrast 或 grow）、两侧原始回答、两侧动作签名、"
        "两侧第二抽签名与 `cross_condition_differs`；`window_id` 只有 grow 行有，老行的第二抽签名从 "
        "`evidence/resample/signatures.jsonl` 接上来。",
        "",
        "## 覆盖：98 条零覆盖降到 " + str(coverage["merged_zero"]),
        "",
        f"标注规则与老批次同一段代码和同一条 system 消息（`sha256` 与 `evidence/coverage/run-meta.json` 相同才继续），"
        f"新处境 {coverage['annotated_situations_grow']} 条、{coverage['grow_tags']} 个标注，"
        f"落在 `evidence/grow/coverage/`。合并 {coverage['annotated_situations_merged']} 条处境后，"
        f"175 条可训练规则里零覆盖从 {coverage['zero_before']} 条降到 {coverage['merged_zero']} 条。",
        "",
        "| 此前零覆盖、现在有覆盖的规则 | 新处境标注次数 | 合并后次数 |",
        "| --- | --- | --- |",
    ]
    for row in coverage["now_covered_paths"]:
        lines.append(f"| `{row['path']}` | {row['grow_count']} | {row['merged_count']} |")
    lines += [
        "",
        "覆盖标注是模型判断，只从 175 条可训练叶子的 dot path 里选 1–4 条，选的是处境里真实出现的"
        "决策点。它说明这些规则在语料里有了可被违反的实例，不说明新处境在这些规则上有可测的法效应——"
        "法效应要按跨条件动作不一致另算。",
        "",
        "## 局限",
        "",
        f"增长池只有 {pool['unused']} 条，且 {pool['unused_sessions'] - pool['unused_new_sessions']} 个会话老批次已经用过，"
        "所以新增处境与老处境有会话重叠，不是独立样本；会话是聚合单位，跨批次的区间不能直接相加。"
        "复现判定仍只有一次第二抽样，一次复现不等于可复现，稳定集在更多抽样后还会缩小。"
        "新处境的小时级证据在 `evidence/grow/`，本文所有数字都能从那里或 `data/` 重算。",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    for name in ("build", "generate", "analyse", "annotate", "report"):
        parser.add_argument(f"--{name}", action="store_true")
    args = parser.parse_args()
    if args.build:
        run_build()
    if args.generate:
        run_generate()
    if args.analyse:
        run_analyse()
    if args.annotate:
        run_annotate()
    if args.report:
        run_report()
    if not any((args.build, args.generate, args.analyse, args.annotate, args.report)):
        parser.print_help()


if __name__ == "__main__":
    main()
