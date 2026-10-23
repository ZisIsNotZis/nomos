#!/usr/bin/env python3
"""给每条留下的处境标注它想覆盖哪些可训练规则，并数每个规则被多少条处境覆盖。

输入：
  data/pairs-filtered.jsonl   filter_pairs.py 筛过的处境（一行一条）
  constitution/nodes.json     264 个叶子；只有 trainable 为真的 175 个是候选
输出：
  data/coverage.json          {situation_id: [dot path, ...]}，每条 1–4 条
  data/coverage-counts.json   每个可训练叶子被多少条处境覆盖，0 与 1 的名单
  evidence/coverage/          每次模型调用的完整记录（请求哈希、规则集哈希、
                              原文回答、解析结果、usage），run-meta.json 记本次
                              运行的模型、温度、候选集与系统消息哈希

标注是模型判断：把 175 个叶子的 dot path 与原文一次性放进 system 消息，把处境
放进 user 消息，要求只从候选里选 1–4 条，选的是处境里真实出现的决策点——如果
被违反，下一个回合会走错——而不是关键词重合。system 消息在每次调用里相同，
所以前缀缓存命中；温度 0，thinking 关。

可重跑：脚本读 data/coverage.json，已经标注过的处境直接跳过；--force 重标。
每次调用的请求哈希与原文回答都在 evidence/coverage/calls.jsonl，重跑或换人复核
都能看到标注依据。费用不设外部依赖，累计超过 5 元即停（可续跑）。

`--max-tags` 与 `--tag-dir` 只用于诊断（report/data-quality.md 的“覆盖不足的
诊断”）：把容量提到 8 或不设上限，写进单独的目录，不碰交付用的那两份数据。
`--max-tags 0` 表示不设上限，输出预算相应放大。
"""

import argparse
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PAIRS = REPO / "data" / "pairs-filtered.jsonl"
NODES = REPO / "constitution" / "nodes.json"
COVERAGE = REPO / "data" / "coverage.json"
COUNTS = REPO / "data" / "coverage-counts.json"
EVIDENCE = REPO / "evidence" / "coverage"
CALLS = EVIDENCE / "calls.jsonl"
RUN_META = EVIDENCE / "run-meta.json"

ENDPOINT = "https://api.deepseek.com/v1/chat/completions"
MODEL = "deepseek-flash"
TEMPERATURE = 0.0
# economy.output_cap（agent-policy b33e7fd）：上限是保险阀，取该调用合法产出最长长度的十倍。
# 两类调用分开算，因为它们的合法回答长度差一个量级：
#   选规则（--max-tags 打开）：已落盘 353 次（coverage 176 + coverage-cap8 177），自己停下来
#   的最长回答 149 token（coverage-cap8），所以 1490；旧值 400 没截断过任何一条，但也不是依法取的。
#   不收窄（--max-tags 关闭）：已落盘 197 次（coverage-uncapped），自己停下来的最长 1469 token，
#   所以 14690；旧值 2000 在那一批里截断了 23 条，那 23 条按原样进统计，压制幅度未测。
LONGEST_LEGITIMATE_OUTPUT = 149
MAX_TOKENS = 10 * LONGEST_LEGITIMATE_OUTPUT  # 最长 149 的十倍，只用于 --max-tags
LONGEST_LEGITIMATE_OUTPUT_FULL = 1469
MAX_TOKENS_FULL = 10 * LONGEST_LEGITIMATE_OUTPUT_FULL  # 最长 1469 的十倍
WORKERS = 4
MAX_CNY = 5.0

# Published price, https://api-docs.deepseek.com/quick_start/pricing, read 2026-10-20.
# USD per 1M tokens; off-peak is half of peak.
PRICE = {"peak": {"cache_hit": 0.006, "cache_miss": 0.30, "output": 1.20},
         "off_peak": {"cache_hit": 0.003, "cache_miss": 0.15, "output": 0.60}}
USD_CNY = 6.693661

INSTRUCTION = """下面给你一部操作法的 {count} 个可训练叶子规则（dot path + 原文），和一段真实会话处境。
处境以用户轮结尾，要标注的是：为了把这个处境的下一回合走对，模型必须遵守哪些叶子规则。

{selection}，只从给定 dot path 里选。按处境里真实出现的决策点选：如果这条规则被违反，下一回合会走错的那几条；不要按关键词重合硬凑，也不要选那些在这个处境里没有可违反余地的规则。

只输出一个 JSON 对象：
{{"paths": ["dot.path", ...], "why": "为什么这几条，<=40 字"}}

规则集（一行一条：dot path — 原文）：
{rules}"""

LOCK = threading.Lock()
SEQUENCE = 0
SPENT_CNY = 0.0


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


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
    return usd * USD_CNY


def api_key():
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


def load_pairs():
    return [json.loads(line) for line in PAIRS.read_text(encoding="utf-8").splitlines() if line.strip()]


def trainable_nodes():
    nodes = json.loads(NODES.read_text(encoding="utf-8"))
    return [node for node in nodes if node["trainable"]]


def rules_block(nodes):
    return "\n".join(f"{node['dot_path']} — {node['text']}" for node in nodes)


def system_message(nodes, max_tags):
    selection = (f"选 1 到 {max_tags} 条" if max_tags else
                 "把这个处境里会被违反的规则全列出来，不设上限，但不要为了凑数补条目")
    return INSTRUCTION.format(count=len(nodes), selection=selection, rules=rules_block(nodes))


def parse_answer(text, allowed, max_tags, candidate_count):
    """The dot paths the model returned, kept only where they are in the candidate set.

    A path outside the set is dropped and reported, not fatal: the model
    occasionally writes a plausible path that does not exist (it invented
    `change.record.write_through` for `change.write_through`), and the rest of
    its answer is still usable.
    """
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("no JSON object in answer")
    data = json.loads(match.group(0))
    paths = data.get("paths")
    if not isinstance(paths, list):
        raise ValueError("paths is not a list")
    cleaned, unknown = [], []
    for path in paths:
        path = str(path).strip().strip("`").strip()
        if path not in allowed:
            unknown.append(path)
            continue
        if path not in cleaned:
            cleaned.append(path)
    limit = max_tags or candidate_count
    if not 1 <= len(cleaned) <= limit:
        raise ValueError(f"{len(cleaned)} valid paths, want 1-{limit}")
    return cleaned, str(data.get("why", ""))[:200], unknown


def annotate(situation, system, allowed, calls_path, max_tags, attempt_budget=3):
    global SEQUENCE, SPENT_CNY
    prompt = situation["excerpt"]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    request_sha = sha(json.dumps(messages, ensure_ascii=False))
    last_error = ""
    for attempt in range(1, attempt_budget + 1):
        budget = MAX_TOKENS if max_tags else MAX_TOKENS_FULL
        body = {"model": MODEL, "messages": messages, "temperature": TEMPERATURE,
                "max_tokens": budget, "thinking": {"type": "disabled"}}
        response, latency = post(body)
        raw = (response["choices"][0]["message"].get("content") or "").strip()
        finish = response["choices"][0].get("finish_reason")
        usage = response.get("usage", {})
        created = response.get("created", 0)
        cny = call_cost(usage, created)
        try:
            paths, why, unknown = parse_answer(raw, allowed, max_tags, len(allowed))
            error = None
        except (ValueError, json.JSONDecodeError) as exc:
            paths, why, unknown, error = None, None, [], str(exc)
        with LOCK:
            SEQUENCE += 1
            SPENT_CNY += cny
            row = {"call_id": f"c{SEQUENCE:04d}", "situation_id": situation["situation_id"],
                   "attempt": attempt, "model": MODEL, "temperature": TEMPERATURE,
                   "thinking": "disabled", "system_sha256": sha(system), "request_sha256": request_sha,
                   "finish_reason": finish, "ok": error is None, "error": error,
                   "response": raw, "paths": paths, "unknown_paths": unknown, "why": why,
                   "created": created,
                   "latency_s": round(latency, 2), "usage": usage, "cost_cny": round(cny, 6)}
            with calls_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            if SPENT_CNY > MAX_CNY:
                raise SystemExit(f"spent CNY {SPENT_CNY:.2f} > {MAX_CNY}; stopping for a budget check")
        if error is None:
            return paths
        last_error = error
        messages = messages[:2]
        messages[1] = {"role": "user", "content": prompt + (
            f"\n\n上一次输出无效：{error}。只输出 JSON 对象，paths 必须来自上面的 dot path。")}
    raise RuntimeError(f"{situation['situation_id']}: no valid annotation after {attempt_budget} attempts: {last_error}")


def counts_from(coverage, nodes):
    per_rule = Counter()
    for paths in coverage.values():
        for path in paths:
            per_rule[path] += 1
    paths = [node["dot_path"] for node in nodes]
    distribution = Counter(per_rule[path] for path in paths)
    return {
        "situations": len(coverage),
        "rules": len(paths),
        "tags": sum(len(paths_) for paths_ in coverage.values()),
        "counts": {path: per_rule[path] for path in paths},
        "distribution": {str(k): distribution[k] for k in sorted(distribution)},
        "zero": [path for path in paths if per_rule[path] == 0],
        "one": [path for path in paths if per_rule[path] == 1],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-annotate situations already in data/coverage.json")
    parser.add_argument("--limit", type=int, default=0, help="annotate at most this many situations (smoke runs)")
    parser.add_argument("--workers", type=int, default=WORKERS)
    parser.add_argument("--max-tags", type=int, default=4,
                        help="tag cap per situation; 0 means no cap; anything but 4 is a diagnostic, not the deliverable")
    parser.add_argument("--tag-dir", default="", help="write coverage/counts/evidence here instead of data/ and evidence/coverage/")
    args = parser.parse_args()

    if args.tag_dir:
        tag_dir = REPO / args.tag_dir
        tag_dir.mkdir(parents=True, exist_ok=True)
        coverage_path, counts_path, calls_path, meta_path = (
            tag_dir / "coverage.json", tag_dir / "coverage-counts.json",
            tag_dir / "calls.jsonl", tag_dir / "run-meta.json")
    else:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        coverage_path, counts_path, calls_path, meta_path = COVERAGE, COUNTS, CALLS, RUN_META
    pairs = load_pairs()
    nodes = trainable_nodes()
    allowed = {node["dot_path"] for node in nodes}
    system = system_message(nodes, args.max_tags)

    coverage = {}
    if coverage_path.exists() and not args.force:
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    todo = [pair for pair in pairs if pair["situation_id"] not in coverage]
    if args.limit:
        todo = todo[:args.limit]
    print(f"situations {len(pairs)}, already annotated {len(coverage)}, this run {len(todo)}")
    failures = []

    if todo:
        meta_path.write_text(json.dumps({
            "model": MODEL, "endpoint": ENDPOINT, "temperature": TEMPERATURE, "thinking": "disabled",
            "max_tokens": MAX_TOKENS if args.max_tags else MAX_TOKENS_FULL,
            "max_tags": args.max_tags, "system_message_sha256": sha(system),
            "rules_block_sha256": sha(rules_block(nodes)), "rules": len(nodes),
            "pairs_sha256": sha(PAIRS.read_text(encoding="utf-8")),
            "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

        def run_one(pair):
            try:
                return pair["situation_id"], annotate(pair, system, allowed, calls_path, args.max_tags)
            except RuntimeError as exc:
                failures.append(str(exc))
                return None

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = [result for result in pool.map(run_one, todo) if result]
        for situation_id, paths in results:
            coverage[situation_id] = paths
        coverage_path.write_text(json.dumps(dict(sorted(coverage.items())), ensure_ascii=False, indent=1) + "\n",
                                 encoding="utf-8")

    if failures:
        print(f"{len(failures)} situation(s) had no valid annotation and stay unannotated for the next run:")
        for line in failures:
            print("  " + line)
    counts = counts_from(coverage, nodes)
    missing = set(pair["situation_id"] for pair in pairs) - set(coverage)
    if missing:
        print(f"partial run: {counts['situations']} of {len(pairs)} situations annotated; counts not written")
        return
    counts_path.write_text(json.dumps(counts, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"annotated {counts['situations']} situations with {counts['tags']} tags "
          f"({counts['tags'] / max(1, counts['situations']):.2f} per situation)")
    print("distribution: " + ", ".join(f"{k}->{v}" for k, v in counts["distribution"].items()))
    print(f"rules covered 0: {len(counts['zero'])}, 1: {len(counts['one'])}")
    print(f"spent CNY {SPENT_CNY:.2f} this run")
    assert set(coverage) <= set(pair["situation_id"] for pair in pairs)
    limit = args.max_tags or len(allowed)
    assert all(1 <= len(paths) <= limit and set(paths) <= allowed for paths in coverage.values())


if __name__ == "__main__":
    main()
