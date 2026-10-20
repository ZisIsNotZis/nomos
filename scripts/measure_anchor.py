#!/usr/bin/env python3
"""匹配锚点：把不带法 DeepSeek 的刻度放回 base/post 的那一套解码参数上。

不带法 DeepSeek 原来用的是 evidence/densify 的抽样：temperature 0.0、max_tokens 600、
带法条件把法条原文放在 system 消息里、每条件 3–4 条。base/post 用的是 temperature 0.7、
top_p 0.95、max_new_tokens 320、prompt 是「excerpt + 续写指令」的单轮 user 消息、每条 3 条。
于是「post 0.0968 对不带法 0.3502」跨了两套解码，不是同一把尺子。本脚本按 base/post 那一套
参数重抽 DeepSeek 的带法/不带法两侧，给出同协议的不带法刻度。

  --pilot      20 条处境 × 2 条件 × 3 条抽样 = 120 次调用，验证参数确实生效（记录 usage 与
               finish_reason），写 pilot.json；--generate 没有通过的 pilot 就不跑。
  --generate   148 条参照物可用的处境 × 2 条件 × 3 条抽样（含 pilot 已落盘的），落
               evidence/measure/anchor-matched/answers.jsonl，已落盘的不重抽。
  --analyse    纯本地：用与 measure_actions 同一套签名与参照物，重算三个口径的不带法刻度，
               并与旧抽样在同一批处境上的读数对照；base/post 与 X 不重算，只搬运并核对。

与 base/post 同一条 prompt 是硬条件：重建的 prompt sha256 必须等于 evidence/measure/answers.jsonl
里该处境记录的 prompt_sha256，不相等就停。法条原文只在带法条件进 system 消息，不带法条件
不带任何 system 消息，且断言请求里没有法条原文。

用法：
  python3 scripts/measure_anchor.py --pilot
  python3 scripts/measure_anchor.py --generate
  python3 scripts/measure_anchor.py --analyse
"""

import argparse
import collections
import importlib.util
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
MEASURE = REPO / "evidence" / "measure"
MEASURE_ANSWERS = MEASURE / "answers.jsonl"
MEASURE_SUMMARY = MEASURE / "summary.json"

EVIDENCE = MEASURE / "anchor-matched"
ANSWERS = EVIDENCE / "answers.jsonl"
PILOT = EVIDENCE / "pilot.json"
SUMMARY = EVIDENCE / "summary.json"
PER_SITUATION = EVIDENCE / "per-situation.jsonl"
LOG = EVIDENCE / "generate.log"

ARMS = ("law", "bare")
DRAWS = 3
# 与 scripts/measure_actions.py 的 TEMPERATURE / TOP_P / MAX_NEW_TOKENS 一致，不导入是因为
# 那边的常量是生成本地模型用的，这里要显式在同一行里让两套参数可对照。
TEMPERATURE = 0.7
TOP_P = 0.95
MAX_TOKENS = 320
PILOT_SITUATIONS = 20
WORKERS = 8
MAX_CNY = 4.0


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ra = load_module("resample_actions", HERE / "resample_actions.py")
measure = load_module("measure_actions", HERE / "measure_actions.py")
lib = ra.lib
sha = ra.sha
load_jsonl = ra.load_jsonl


def log(line):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    print(line, flush=True)


# --- 处境 ------------------------------------------------------------------

def situations():
    """148 条参照物可用的处境（action 参照物票数 ≥ 2 且非空），与 measure 的 n_pairs 同一批。"""
    ids = [row["id"] for row in measure.situations()]
    references = measure.reference_table(load_jsonl(measure.DENSIFY_ANSWERS), ids)
    usable = [situation for situation in ids if measure.usable_reference(references[situation])]
    stored = {row["situation"] for row in load_jsonl(measure.PER_SITUATION) if row["reference_usable"]}
    if set(usable) != stored:
        raise SystemExit(f"参照物可用处境与 per-situation.jsonl 不一致：{len(set(usable) ^ stored)} 条差集")
    if len(usable) != 148:
        raise SystemExit(f"参照物可用处境 {len(usable)} 条，期望 148；先核对 evidence/measure 的终版快照")
    return usable, references


def prompt_hashes():
    """每处境 base/post 实际吃到的 prompt sha256，用来断言锚点的 prompt 是同一串字节。"""
    out = {}
    for row in load_jsonl(MEASURE_ANSWERS):
        out.setdefault(row["situation"], set()).add(row["prompt_sha256"])
    return out


def request_for(situation, arm, law):
    """与 base/post 同一条 prompt 构造：excerpt 加续写指令，法条只进带法条件的 system 消息。"""
    return ra.build_messages(situation, arm, law)


def gate(situation_ids, law, hashes):
    """逐处境核对 prompt 与 base/post 同字节，并断言不带法条件里没有法条原文。"""
    checked = 0
    for situation_id in situation_ids:
        situation = {"excerpt": situation_of[situation_id]["excerpt"]}
        for arm in ARMS:
            system, prompt, _ = request_for(situation, arm, law)
            if sha(prompt) not in hashes[situation_id]:
                raise SystemExit(f"{situation_id} {arm}: 重建 prompt 的 sha256 与 base/post 记录的不同")
            if arm == "bare" and (system or law[:80] in prompt or law[-80:] in prompt):
                raise SystemExit(f"{situation_id} bare: 请求里出现了法条原文")
            checked += 1
    return checked


situation_of = {row["id"]: row for row in measure.situations()}


# --- 生成 ------------------------------------------------------------------

def generate(situation, arm, draw, law, sequence):
    system, prompt, messages = request_for(situation, arm, law)
    body = {"model": lib.MODEL, "messages": messages, "temperature": TEMPERATURE,
            "top_p": TOP_P, "max_tokens": MAX_TOKENS, "thinking": {"type": "disabled"}}
    response, latency = lib.post(body)
    usage = response.get("usage", {})
    answer = (response["choices"][0]["message"].get("content") or "").strip()
    if not answer:
        raise SystemExit(f"{situation['id']} {arm} 抽 {draw}: 空回答")
    row = lib.record(f"a{sequence:04d}", "anchor-matched", situation["id"], arm, draw,
                     TEMPERATURE, prompt, answer, usage, response.get("created", 0), latency)
    row["draw"] = draw
    row["top_p"] = TOP_P
    row["max_tokens"] = MAX_TOKENS
    row["finish_reason"] = response["choices"][0].get("finish_reason")
    row["request_sha256"] = sha(system + "\x00" + prompt)
    row["prompt_sha256"] = sha(prompt)
    row["system_chars"] = len(system)
    row["system_sha256"] = sha(system) if system else None
    return row


def done_keys():
    if not ANSWERS.exists():
        return set()
    return {(row["situation"], row["arm"], row["draw"]) for row in load_jsonl(ANSWERS)}


def run_calls(situation_ids, law, tag):
    finished = done_keys()
    plan = [(situation_id, arm, draw) for situation_id in situation_ids for arm in ARMS
            for draw in range(DRAWS) if (situation_id, arm, draw) not in finished]
    if not plan:
        print(f"{tag}: 已全部落盘")
        return []
    stored_cost = [row["cost"]["cny"] for row in load_jsonl(measure.DENSIFY_ANSWERS) if row.get("cost")]
    per_call = sum(stored_cost) / len(stored_cost)
    log(f"{tag}: {len(situation_ids)} 条处境 × {len(ARMS)} 条件 × {DRAWS} 条，待调用 {len(plan)} 次；"
        f"按 densify 单价 ¥{per_call:.5f} 投影 ¥{per_call * len(plan):.2f}；"
        f"解码 temperature {TEMPERATURE}、top_p {TOP_P}、max_tokens {MAX_TOKENS}")
    if per_call * len(plan) > MAX_CNY:
        raise SystemExit(f"投影 ¥{per_call * len(plan):.2f} 超过上限 ¥{MAX_CNY:.2f}")
    lib.api_key()

    lock = threading.Lock()
    state = {"n": len(load_jsonl(ANSWERS)) if ANSWERS.exists() else 0,
             "spend": sum(row["cost"]["cny"] for row in load_jsonl(ANSWERS) if row.get("cost"))
             if ANSWERS.exists() else 0.0}
    written = []

    def work(item):
        situation_id, arm, draw = item
        with lock:
            if state["spend"] > MAX_CNY:
                raise SystemExit(f"本批次已花 ¥{state['spend']:.3f}，超过上限 ¥{MAX_CNY:.2f}，停止")
            state["n"] += 1
            sequence = state["n"]
        row = generate(situation_of[situation_id], arm, draw, law, sequence)
        with lock:
            state["spend"] += row["cost"]["cny"]
            ra.append_rows(ANSWERS, [row])
            written.append(row)
        return row

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(work, item) for item in plan]
        for index, future in enumerate(futures, 1):
            future.result()
            if index % 40 == 0:
                print(f"  {index}/{len(futures)} 次调用完成", flush=True)
    log(f"{tag}: 落盘 {len(written)} 条，{ANSWERS.name} 共 {len(done_keys())} 条，"
        f"花费 ¥{state['spend']:.3f}")
    return written


def run_pilot():
    law = ra.law_text()
    usable, _ = situations()
    pilot_ids = usable[:PILOT_SITUATIONS]
    gate(pilot_ids, law, prompt_hashes())
    run_calls(pilot_ids, law, "pilot")
    rows = [row for row in load_jsonl(ANSWERS) if row["situation"] in set(pilot_ids)]
    if len(rows) != PILOT_SITUATIONS * len(ARMS) * DRAWS:
        raise SystemExit(f"pilot 落盘 {len(rows)} 条，期望 {PILOT_SITUATIONS * len(ARMS) * DRAWS}")
    hashes = prompt_hashes()
    prompt_matches = sum(1 for row in rows if row["prompt_sha256"] in hashes[row["situation"]])
    completions = [row["usage"]["completion_tokens"] for row in rows]
    finish = collections.Counter(row["finish_reason"] for row in rows)
    grouping = collections.defaultdict(list)
    for row in rows:
        grouping[(row["situation"], row["arm"])].append(row["response"])
    diverse = sum(1 for answers in grouping.values() if len(set(answers)) > 1)
    old_grouping = collections.defaultdict(list)
    for row in load_jsonl(measure.DENSIFY_ANSWERS):
        if row["situation"] in set(pilot_ids):
            old_grouping[(row["situation"], row["arm"])].append(row["response"])
    old_diverse = sum(1 for answers in old_grouping.values() if len(set(answers)) > 1)
    pilot = {
        "what": "小批验证：匹配锚点的解码参数是否确实生效，再决定跑不跑全量",
        "situations": len(pilot_ids),
        "arms": list(ARMS),
        "draws": DRAWS,
        "calls": len(rows),
        "params_sent": {"model": lib.MODEL, "temperature": TEMPERATURE, "top_p": TOP_P,
                        "max_tokens": MAX_TOKENS, "thinking": "disabled"},
        "spend_cny": round(sum(row["cost"]["cny"] for row in rows if row.get("cost")), 4),
        "usage_reported": sum(1 for row in rows if row["usage"].get("prompt_tokens") is not None
                              and row["usage"].get("completion_tokens") is not None),
        "completion_tokens": {"min": min(completions), "max": max(completions),
                              "mean": round(sum(completions) / len(completions), 1)},
        "finish_reason": dict(finish),
        "prompt_tokens": {"min": min(row["usage"]["prompt_tokens"] for row in rows),
                          "max": max(row["usage"]["prompt_tokens"] for row in rows)},
        "prompt_matches_base_post": prompt_matches,
        "draw_diversity": {"matched": f"{diverse}/{len(grouping)}", "old_temp_0": f"{old_diverse}/{len(old_grouping)}"},
        "checks": {
            "max_tokens_respected": max(completions) <= MAX_TOKENS,
            "usage_on_every_call": all(row["usage"].get("completion_tokens") is not None for row in rows),
            "finish_reason_on_every_call": all(row["finish_reason"] in ("stop", "length") for row in rows),
            "prompt_identical_to_base_post": prompt_matches == len(rows),
            "bare_has_no_system": all(row["system_chars"] == 0 for row in rows if row["arm"] == "bare"),
            "law_has_system": all(row["system_chars"] > 0 for row in rows if row["arm"] == "law"),
        },
        "note": "API 不回显 temperature 与 top_p，所以这两项只能证明发送成功（无报错）并且在请求体里；"
                "max_tokens 有可观测的上界证据（completion_tokens ≤ 320）",
    }
    passed = all(pilot["checks"].values())
    pilot["passed"] = passed
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    PILOT.write_text(json.dumps(pilot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"pilot: {pilot['calls']} 次调用，完成 token 最大 {pilot['completion_tokens']['max']}，"
        f"finish_reason {dict(finish)}，prompt 与 base/post 同字节 {prompt_matches}/{len(rows)}；"
        f"检查{'全部通过' if passed else '未通过：' + str([k for k, v in pilot['checks'].items() if not v])}")
    if not passed:
        raise SystemExit("pilot 检查未通过，不跑全量")


def run_generate():
    if not PILOT.exists():
        raise SystemExit("先跑 --pilot：没有 pilot 通过的记录就不跑全量")
    pilot = json.loads(PILOT.read_text(encoding="utf-8"))
    if not pilot.get("passed"):
        raise SystemExit("pilot.json 的记录是未通过，先查明参数为什么没生效")
    law = ra.law_text()
    usable, _ = situations()
    gate(usable, law, prompt_hashes())
    run_calls(usable, law, "full")


# --- 分析 ------------------------------------------------------------------

def matched_rate(draws, signature):
    return measure.rate([measure.signature_of(row["response"]) == signature for row in draws])


def matched_text_rate(draws, signature):
    return measure.rate([measure.text_signature(row["response"]) == signature for row in draws])


def reference_readout(usable, references, text_references, base_rows):
    """逐处境的匹配读数：带法/不带法在匹配解码下与旧参照物的吻合率，以及旧抽样同一批的读数。"""
    by_key = collections.defaultdict(list)
    for row in load_jsonl(ANSWERS):
        by_key[(row["situation"], row["arm"])].append(row)
    rows = []
    for situation_id in usable:
        law_draws = sorted(by_key[(situation_id, "law")], key=lambda row: row["draw"])
        bare_draws = sorted(by_key[(situation_id, "bare")], key=lambda row: row["draw"])
        if len(law_draws) != DRAWS or len(bare_draws) != DRAWS:
            raise SystemExit(f"{situation_id}: 匹配锚点 {len(law_draws)} 条带法 / {len(bare_draws)} 条不带法")
        reference = references[situation_id]
        text = text_references[situation_id]
        rows.append({
            "situation": situation_id,
            "reference_signature": list(reference["signature"]),
            "reference_votes": reference["votes"],
            "bare_deepseek_old": reference["bare_rate"],
            "bare_matched": matched_rate(bare_draws, reference["signature"]),
            "law_matched": matched_rate(law_draws, reference["signature"]),
            "text_reference_usable": measure.usable_reference(text),
            "bare_text_deepseek_old": text["bare_rate"],
            "bare_text_matched": matched_text_rate(bare_draws, text["signature"]),
            "law_text_matched": matched_text_rate(law_draws, text["signature"]),
            "base": base_rows[situation_id]["base"],
            "post": base_rows[situation_id]["post"],
            "base_text": base_rows[situation_id]["base_text"],
            "post_text": base_rows[situation_id]["post_text"],
        })
    return rows


def block(rows, old_key, matched_key, seed):
    """同一批处境上「旧抽样 vs 匹配抽样」，配对自举差值。"""
    old = [row[old_key] for row in rows]
    matched = [row[matched_key] for row in rows]
    return {
        "situations": len(rows),
        "old_same_sample": measure.mean(old),
        "old_same_sample_ci": measure.bootstrap_mean(old, seed),
        "matched": measure.mean(matched),
        "matched_ci": measure.bootstrap_mean(matched, seed + 1),
        "delta_matched_minus_old": measure.mean(matched) - measure.mean(old),
        "delta_ci": measure.bootstrap_delta(rows, seed + 2, (old_key, matched_key)),
    }


def run_analyse():
    usable, references = situations()
    ids = [row["id"] for row in measure.situations()]
    text_references = measure.text_reference_table(load_jsonl(measure.DENSIFY_ANSWERS), ids)
    per_situation_source = {row["situation"]: row for row in load_jsonl(measure.PER_SITUATION)}
    rows = reference_readout(usable, references, text_references, per_situation_source)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    PER_SITUATION.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                             encoding="utf-8")

    old_summary = json.loads(MEASURE_SUMMARY.read_text(encoding="utf-8"))
    action = block(rows, "bare_deepseek_old", "bare_matched", measure.SEED + 31)
    old_law_self = measure.mean(
        [per_situation_source[row["situation"]]["reference_votes"]
         / per_situation_source[row["situation"]]["law_draws"] for row in rows]
    )
    action.update({
        "what": "口径一（动作签名一致率）的不带法刻度：与带法多数签名吻合的抽样比例",
        "old_protocol": {"temperature": 0.0, "max_tokens": 600, "draws": "3–4", "law_in": "system"},
        "matched_protocol": {"temperature": TEMPERATURE, "top_p": TOP_P, "max_tokens": MAX_TOKENS,
                             "draws": DRAWS, "law_in": "system"},
        "law_matched_self_agreement": measure.mean([row["law_matched"] for row in rows]),
        "law_matched_self_agreement_ci": measure.bootstrap_mean([row["law_matched"] for row in rows],
                                                               measure.SEED + 33),
        "law_self_agreement_old_protocol": old_law_self,
        "law_self_agreement_old_protocol_meaning": "旧批次同协议下的带法侧自洽度：每处境多数签名的票数 / 带法抽样数，"
                                                      "即「再抽一条带法回答、还是同一个签名」的比例；参照物的 1.0 是定义，这个数才是旧协议下带法侧的量",
        "matched_law_minus_matched_bare": measure.mean([row["law_matched"] for row in rows])
                                          - measure.mean([row["bare_matched"] for row in rows]),
        "matched_law_minus_matched_bare_ci": measure.bootstrap_delta(rows, measure.SEED + 37,
                                                                     ("bare_matched", "law_matched")),
        "matched_law_minus_matched_bare_meaning": "同一批抽样、同一套匹配解码下，带法侧减不带法侧；这才是这个框架里的「法的作用」，"
                                                    "它在匹配解码下很小，所以拿不带法刻度去量适配器补了多少法条效果，尺度本身就很窄",
        "base": old_summary["base_mean"],
        "post": old_summary["post_mean"],
        "old_on_148_situations_by_old_protocol": old_summary["bare_deepseek_mean"],
    })

    text_rows = [row for row in rows if row["text_reference_usable"]]
    text = block(text_rows, "bare_text_deepseek_old", "bare_text_matched", measure.SEED + 34)
    old_text_on_subset = measure.text_judgement(load_jsonl(measure.PER_SITUATION))
    text.update({
        "what": "口径二（文字层决策签名一致率）的不带法刻度",
        "situations_note": f"匹配锚点只覆盖口径一的 148 条可用处境，与本口径可用的 {old_text_on_subset['situations_reference_usable']} 条"
                           f"相交 {len(text_rows)} 条；这里的旧抽样读数也重算在这 {len(text_rows)} 条上，"
                           "所以两边同一样本，可与原 169 条上的读数并存但不相等",
        "old_on_169_situations_by_old_protocol": old_text_on_subset["bare_deepseek_mean"],
        "old_on_169_situations_by_old_protocol_situations": old_text_on_subset["situations_reference_usable"],
        "law_matched_self_agreement": measure.mean([row["law_text_matched"] for row in text_rows]),
        "law_matched_self_agreement_ci": measure.bootstrap_mean(
            [row["law_text_matched"] for row in text_rows], measure.SEED + 36),
        "matched_law_minus_matched_bare": measure.mean([row["law_text_matched"] for row in text_rows])
                                          - measure.mean([row["bare_text_matched"] for row in text_rows]),
        "matched_law_minus_matched_bare_ci": measure.bootstrap_delta(
            text_rows, measure.SEED + 38, ("bare_text_matched", "law_text_matched")),
        "base": old_summary["text_signature"]["base_mean"],
        "post": old_summary["text_signature"]["post_mean"],
    })

    summary = {
        "what": "匹配锚点：用 base/post 的解码参数重抽 DeepSeek 两侧，把不带法刻度放回同一把尺子",
        "situations": len(rows),
        "draws_per_arm": DRAWS,
        "calls": len(load_jsonl(ANSWERS)),
        "spend_cny": round(sum(row["cost"]["cny"] for row in load_jsonl(ANSWERS) if row.get("cost")), 4),
        "prompt": "excerpt + slice-contrast 的续写指令，与 base/post 同一串字节（逐条 sha256 核对）",
        "action_signature": action,
        "text_signature": text,
        "action_comparable_bare": "缺：旧抽样没有在动作可比子集上算不带法读数，匹配批次只有这 148 条处境上的整体读数，不补一个子集值",
        "X": {
            "value": old_summary["X"],
            "ci": old_summary["X_ci"],
            "status": old_summary["X_status"],
            "unchanged_because": "X = (post_mean - base_mean) / (1 - base_mean) 只用 base 与 post，"
                                 "不带法刻度不进入 X；匹配锚点改的是刻度，base/post 与参照物都没动",
        },
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"action_signature": {key: action[key] for key in
                                           ("old_same_sample", "matched", "delta_matched_minus_old",
                                            "law_matched_self_agreement")},
                      "text_signature": {key: text[key] for key in
                                         ("situations", "old_same_sample", "matched",
                                          "delta_matched_minus_old", "law_matched_self_agreement")},
                      "X": summary["X"]["value"]}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--analyse", action="store_true")
    args = parser.parse_args()
    if args.pilot:
        run_pilot()
    elif args.generate:
        run_generate()
    elif args.analyse:
        run_analyse()
    else:
        parser.error("选一个：--pilot / --generate / --analyse")


if __name__ == "__main__":
    main()
