#!/usr/bin/env python3
"""标签太稀：同一处境的采样抖动盖过了法的作用，所以把每个条件抽密再取众数。

174 对里跨条件动作不同的有 111 对，但同条件重采样只有 49–58% 能复现同一动作，
DPO 学到的多是噪声。改法不是调参，是标签：每条处境每个条件抽 5 次，各自取众数
动作，只保留两个众数不同的处境，答案取最接近众数的那条原文。

两个阶段，同一个脚本：

  --generate  242 条合格处境（evidence/slice-contrast 与 evidence/grow 的 situations），
              law 与 bare 各补到 5 次抽样。已存批次（slice-contrast 的 generate 行、
              grow、resample）的抽样全部复用，只补缺的，请求 sha256 与已存记录逐条核对。
              落在 evidence/densify/answers.jsonl。
  --analyse   纯 Python，不调 API：用 scripts/resample_actions.py 的动作签名，对每条
              处境每个条件算众数动作与票数占比，两个众数不同的处境写到
              data/pairs-modal.jsonl，汇总写到 evidence/densify/summary.json。

重采样必须与已存批次同条件，否则取到的不是同一分布的抽样：模型、温度、thinking、
max_tokens、INSTRUCTION、system 消息的构造全部直接导入 scripts/resample_actions.py
与 evidence/slice-contrast/common.py，不复制；法的原文由 resample_actions.law_text()
从 agent-policy 5eafb2e 取并按 sha256 核对。
max_tokens 跟着 ``ra.MAX_TOKENS`` 走，所以 economy.output_cap 把那个常量从 600 抬到 5340 时，
本脚本也自动跟上：这一批 1470 条里 6 条被 600 截断、最长自己停下来的 534，新上限不会截；
已落盘的行不重抽，它们的 600 记在行里。

用法：
  python3 scripts/densify.py --generate
  python3 scripts/densify.py --analyse
"""

import argparse
import collections
import importlib.util
import json
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SLICE_CONTRAST = REPO / "evidence" / "slice-contrast"
GROW = REPO / "evidence" / "grow"
RESAMPLE = REPO / "evidence" / "resample"

SITUATION_FILES = (SLICE_CONTRAST / "situations.jsonl", GROW / "situations.jsonl")
# 已存抽样：文件、arm 字段到 law/bare 的映射，按这个顺序复用（analyse 取"最接近众数"时也按它）
SOURCES = (
    (SLICE_CONTRAST / "answers.jsonl", {"law": "full", "bare": "bare"}),
    (GROW / "answers.jsonl", {"law": "law", "bare": "bare"}),
    (RESAMPLE / "answers.jsonl", {"law": "law", "bare": "bare"}),
)

EVIDENCE = REPO / "evidence" / "densify"
ANSWERS = EVIDENCE / "answers.jsonl"
SUMMARY = EVIDENCE / "summary.json"
MODAL_PAIRS = REPO / "data" / "pairs-modal.jsonl"

ARMS = ("law", "bare")
NO_TOOL_ACTION = "(no tool action)"
TARGET_DRAWS = 5
WORKERS = 6
MAX_CNY = 6.0


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ra = load_module("resample_actions", HERE / "resample_actions.py")
lib = ra.lib
sha = ra.sha
load_jsonl = ra.load_jsonl

# 抽样总量与票数占比只在"每个条件几条"这个单位上有意义；密度不够就不给众数结论。

# --- 输入 ------------------------------------------------------------------

def situations():
    """242 条合格处境，id 唯一，按 id 前缀批次排序（SIT… 后 GRW…）。"""
    rows = [row for path in SITUATION_FILES for row in load_jsonl(path)]
    if len(rows) != 242:
        raise SystemExit(f"{len(rows)} 条处境，期望 242")
    ids = [row["id"] for row in rows]
    if len(set(ids)) != len(ids):
        raise SystemExit("处境 id 重复")
    return rows


def stored_draws():
    """(处境, 条件) → 已存抽样行，按 SOURCES 的顺序，同一批次内按文件顺序。"""
    out = collections.defaultdict(list)
    for path, arm_map in SOURCES:
        reverse = {value: key for key, value in arm_map.items()}
        for row in load_jsonl(path):
            arm = reverse.get(row["arm"])
            if arm is not None:
                out[(row["situation"], arm)].append(row)
    return out


def densify_draws():
    out = collections.defaultdict(list)
    for row in (load_jsonl(ANSWERS) if ANSWERS.exists() else []):
        out[(row["situation"], row["arm"])].append(row)
    return out


def draw_index(row):
    """抽样序号；slice-contrast 与 resample 的行只有 sample 字段。"""
    return row.get("draw", row.get("sample", 0))


def draws_for(stored, own, situation_id, arm):
    """一条处境一个条件可用的抽样，已存的在前、本批次补的在后。"""
    rows = list(stored[(situation_id, arm)]) + list(own[(situation_id, arm)])
    return sorted(rows, key=draw_index)


def request_for(situation, arm, law):
    """与已存批次同一条构造：resample_actions.build_messages，只换 system 消息。"""
    return ra.build_messages({"excerpt": situation["excerpt"]}, arm, law)


def gate(rows, law):
    """重建请求与已存记录的 sha256 逐条核对，并断言 bare 条件没有 system 消息。"""
    checked = 0
    for situation in situations():
        for arm in ARMS:
            system, prompt, _ = request_for(situation, arm, law)
            expected = sha(system + "\x00" + prompt)
            for row in rows[(situation["id"], arm)]:
                checked += 1
                if row.get("request_sha256") != expected:
                    raise SystemExit(f"{situation['id']} {arm}: 已存请求 {row.get('request_sha256')} "
                                     f"与重建的 {expected} 不同，不是同一条提示")
                if arm == "bare" and row.get("system_chars") != 0:
                    raise SystemExit(f"{situation['id']} bare: system_chars={row.get('system_chars')}，"
                                     "bare 条件不能有 system 消息")
                if arm == "law" and row.get("system_sha256") != ra.LAW_SHA256:
                    raise SystemExit(f"{situation['id']} law: system 不是核过的法条原文")
    return checked


# --- 生成 ------------------------------------------------------------------

def generate(situation, arm, draw, law, sequence):
    system, prompt, messages = request_for(situation, arm, law)
    if arm == "bare" and (system or law[:80] in prompt or law[-80:] in prompt):
        raise SystemExit(f"{situation['id']} bare: 请求里出现了法条原文")
    body = {"model": lib.MODEL, "messages": messages, "temperature": ra.TEMPERATURE,
            "max_tokens": ra.MAX_TOKENS, "thinking": {"type": "disabled"}}
    response, latency = lib.post(body)
    usage = response.get("usage", {})
    answer = (response["choices"][0]["message"].get("content") or "").strip()
    if not answer:
        raise SystemExit(f"{situation['id']} {arm} 抽 {draw}: 空回答")
    row = lib.record(f"d{sequence:04d}", "densify", situation["id"], arm, draw,
                     ra.TEMPERATURE, prompt, answer, usage, response.get("created", 0), latency)
    row["draw"] = draw
    row["batch"] = "densify"
    row["finish_reason"] = response["choices"][0].get("finish_reason")
    row["request_sha256"] = sha(system + "\x00" + prompt)
    row["system_chars"] = len(system)
    row["system_sha256"] = sha(system) if system else None
    return row


def run_generate():
    law = ra.law_text()
    rows = situations()
    stored = stored_draws()
    checked = gate(stored, law)
    own = densify_draws()
    have = {key: len(draws_for(stored, own, key[0], key[1])) for key in
            ((situation["id"], arm) for situation in rows for arm in ARMS)}
    pending = [(situation, arm, draw) for situation in rows for arm in ARMS
               for draw in range(have[(situation["id"], arm)], TARGET_DRAWS)]
    if not pending:
        print("每个条件的抽样都已到 5 次")
        return

    costs = [row["cost"]["cny"] for draws in stored.values() for row in draws if row.get("cost")]
    per_call = sum(costs) / len(costs)
    projected = per_call * len(pending)
    print(f"242 条处境 × 2 条件，已存抽样核对 {checked} 条；"
          f"待调用 {len(pending)} 次；按已存单价 ¥{per_call:.5f} 投影 ¥{projected:.2f}", flush=True)
    if projected > MAX_CNY:
        raise SystemExit(f"投影 ¥{projected:.2f} 超过上限 ¥{MAX_CNY:.2f}")
    lib.api_key()

    lock = threading.Lock()
    state = {"n": len(load_jsonl(ANSWERS)) if ANSWERS.exists() else 0,
             "spend": sum(row["cost"]["cny"] for rows in own.values() for row in rows if row.get("cost"))}

    def work(item):
        situation, arm, draw = item
        with lock:
            if state["spend"] > MAX_CNY:
                raise SystemExit(f"本批次已花 ¥{state['spend']:.3f}，超过上限 ¥{MAX_CNY:.2f}，停止生成")
            state["n"] += 1
            sequence = state["n"]
        row = generate(situation, arm, draw, law, sequence)
        with lock:
            state["spend"] += row["cost"]["cny"]
            ra.append_rows(ANSWERS, [row])
        return row

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(work, item) for item in pending]
        try:
            for index, future in enumerate(futures, 1):
                future.result()
                if index % 40 == 0:
                    print(f"  {index}/{len(futures)} 次调用完成", flush=True)
        except BaseException:
            for future in futures:
                future.cancel()
            raise

    total = sum(row["cost"]["cny"] for rows in densify_draws().values() for row in rows)
    print(f"{ANSWERS.name} {state['n']} 行，本批次花费 ¥{total:.3f}", flush=True)


# --- 众数分析 --------------------------------------------------------------

def signature_of(answer):
    """(签名键, 可读签名)：键用于比较，字符串写进 pairs-modal.jsonl。"""
    main = ra.signatures(answer)["signature"]
    return tuple(main), (" ; ".join(main) if main else NO_TOOL_ACTION)


def modal(draws):
    """众数签名与它的票数占比；并返回最接近众数的那条抽样（并列时取最早的一条）。"""
    votes = collections.Counter(signature_of(row["response"])[0] for row in draws)
    winner, count = sorted(votes.items(), key=lambda item: (-item[1], item[0]))[0]
    closest = next(row for row in draws if signature_of(row["response"])[0] == winner)
    return winner, count / len(draws), closest


def has_majority(share):
    """5 次抽样里出现 3 次以上，众数才是多数；2 次是并列后按字典序取到的那一个。"""
    return share * TARGET_DRAWS >= 3


def stability(modal_key, keys, rounds=2000, seed=20260903):
    """众数标签自身的稳定性：把观测到的 5 票有放回重采 5 票，众数仍是原众数的比例。

    这是"同条件再抽 5 次、再取众数，会不会得到同一个动作"的估计，量的是标签噪声，不是法的作用。
    """
    rng = random.Random(seed)
    hits = 0
    for _ in range(rounds):
        votes = collections.Counter(rng.choices(keys, k=len(keys)))
        hits += sorted(votes.items(), key=lambda item: (-item[1], item[0]))[0][0] == modal_key
    return hits / rounds


def run_analyse():
    rows = situations()
    stored = stored_draws()
    own = densify_draws()
    short = [(situation["id"], arm, len(draws_for(stored, own, situation["id"], arm)))
             for situation in rows for arm in ARMS
             if len(draws_for(stored, own, situation["id"], arm)) < TARGET_DRAWS]
    if short:
        raise SystemExit(f"{len(short)} 个条件的抽样不足 5 次，先跑 --generate：{short[:5]}")

    pairs, law_shares, bare_shares = [], [], []
    keys = {arm: [] for arm in ARMS}  # 每条处境的众数签名与观测到的 5 个签名，供稳定性重采样
    no_actions = 0
    for situation in rows:
        sid = situation["id"]
        law_draws = draws_for(stored, own, sid, "law")[:TARGET_DRAWS]
        bare_draws = draws_for(stored, own, sid, "bare")[:TARGET_DRAWS]
        law_key, law_share, law_answer = modal(law_draws)
        bare_key, bare_share, bare_answer = modal(bare_draws)
        keys["law"].append((law_key, [signature_of(row["response"])[0] for row in law_draws]))
        keys["bare"].append((bare_key, [signature_of(row["response"])[0] for row in bare_draws]))
        law_shares.append(law_share)
        bare_shares.append(bare_share)
        no_actions += (not law_key) + (not bare_key)
        if law_key == bare_key:
            continue
        pairs.append({
            "situation_id": sid,
            "excerpt": situation["excerpt"],
            "chosen": law_answer["response"],
            "rejected": bare_answer["response"],
            "law_vote_share": round(law_share, 3),
            "bare_vote_share": round(bare_share, 3),
            "law_signature": signature_of(law_answer["response"])[1],
            "bare_signature": signature_of(bare_answer["response"])[1],
        })

    MODAL_PAIRS.parent.mkdir(parents=True, exist_ok=True)
    MODAL_PAIRS.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in pairs),
                           encoding="utf-8")

    def histogram(shares):
        return {f"{count}/{TARGET_DRAWS}": shares.count(count / TARGET_DRAWS)
                for count in range(TARGET_DRAWS, 0, -1)}

    unanimous = sum(1 for law_share, bare_share in zip(law_shares, bare_shares)
                    if law_share == 1.0 and bare_share == 1.0)
    # 众数对里的可信子集：只有这两组数才谈得上"标签本身没噪声"或"至少过半数"。
    pair_unanimous = [row for row in pairs
                      if row["law_vote_share"] == 1.0 and row["bare_vote_share"] == 1.0]
    pair_majority = [row for row in pairs
                     if has_majority(row["law_vote_share"]) and has_majority(row["bare_vote_share"])]
    both_actions = lambda subset: sum(1 for row in subset
                                      if row["law_signature"] != NO_TOOL_ACTION
                                      and row["bare_signature"] != NO_TOOL_ACTION)
    summary = {
        "situations": len(rows),
        "target_draws": TARGET_DRAWS,
        "modal_pairs": len(pairs),
        "modal_pair_share": round(len(pairs) / len(rows), 3),
        "unanimous_both_sides": unanimous,
        "unanimous_modal_pairs": len(pair_unanimous),
        "unanimous_modal_pairs_with_actions": both_actions(pair_unanimous),
        "majority_modal_pairs": len(pair_majority),
        "majority_modal_pairs_with_actions": both_actions(pair_majority),
        "action_bearing_modal_pairs": both_actions(pairs),
        "conditions_without_tool_action": no_actions,
        "vote_share_histogram": {"law": histogram(law_shares), "bare": histogram(bare_shares)},
        "vote_share_mean": {"law": round(sum(law_shares) / len(law_shares), 3),
                            "bare": round(sum(bare_shares) / len(bare_shares), 3)},
        "modal_label_stability": {arm: round(sum(stability(key, draws) for key, draws in keys[arm])
                                             / len(keys[arm]), 3) for arm in ARMS},
        "signature_rule": "动作签名 = resample_actions.signatures 的主签名列表（工具 + 程序:子命令 + 目标路径）；"
                          "众数 = 出现次数最多的签名，并列时取字典序最小；票数占比 = 众数次数 / 5",
        "majority_rule": "众数次数 ≥ 3/5 记为多数；只有 2/5 时众数只是并列后按字典序取到的那一个",
        "share_mean_rule": "vote_share_mean = 单次抽样落在众数动作上的概率，对 242 条处境取平均；"
                           "一次抽样与 5 抽众数标签的一致率就等于它",
        "stability_rule": "modal_label_stability = 把每条处境每个条件观测到的 5 个签名有放回重采 5 个，"
                          "众数仍是原众数的比例，每条件 2000 次、seed 20260903，再对 242 条处境取平均",
        "modal_pair_rule": "保留 law 与 bare 的众数签名不同的处境；chosen/rejected 取各自最接近众数的抽样原文",
        "spend_cny": round(sum(row["cost"]["cny"] for rows in own.values() for row in rows), 6),
        "output": str(MODAL_PAIRS.relative_to(REPO)),
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"众数不同的处境 {len(pairs)}/{len(rows)}，其中两侧都 {TARGET_DRAWS}/{TARGET_DRAWS} 的 {len(pair_unanimous)} 条，"
          f"两侧都过半数的 {len(pair_majority)} 条（带动作 {both_actions(pair_majority)} 条）；"
          f"全 {len(rows)} 条处境里两侧都一致 {unanimous} 条")
    for arm, shares in (("law", law_shares), ("bare", bare_shares)):
        print(f"{arm:4s} 众数票数 " + "  ".join(f"{key}:{value}"
                                               for key, value in histogram(shares).items()))
    print("众数标签稳定性（同条件两次取众数一致率）：" +
          "  ".join(f"{arm}:{summary['modal_label_stability'][arm]:.3f}" for arm in ARMS))
    print(f"任一侧众数为空动作 {no_actions} 个条件")
    print(f"写完 {MODAL_PAIRS.relative_to(REPO)}、{SUMMARY.name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--analyse", action="store_true")
    args = parser.parse_args()
    if args.generate:
        run_generate()
    if args.analyse:
        run_analyse()
    if not (args.generate or args.analyse):
        parser.print_help()


if __name__ == "__main__":
    main()
