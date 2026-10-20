#!/usr/bin/env python3
"""法造成的差异，还是同一条提示重采样就有的抖动。

174 条处境各由一次带法回答（`chosen`）与一次不带法回答（`rejected`）组成，其中 111 对动作
不同。如果同一条件重采样也能差这么多，这对数据携带的是采样抖动而不是法，DPO 就在学噪声。

本程序只做两件事，分两个阶段，都是同一个脚本：

  --generate   对每条处境再取一次 law 回答与一次 bare 回答，共 348 次 DeepSeek 调用。
  --analyse    纯 Python：用 eval/judge.py 的动作解析把每条回答压成动作签名，算三个一致率，
               落盘签名、逐条对比与汇总，并写出两侧都能复现的稳定对到 data/pairs-stable.jsonl。
               不调 API。

重采样必须与存下来的批次同条件，否则比的不是抖动：

- 模型 deepseek-flash、温度 0.0、thinking 关闭、max_tokens 600，与 evidence/slice-contrast
  的生成批次一致；
- 请求正文就是 `pairs-filtered.jsonl` 的 excerpt 加上 evidence/slice-contrast/common.py 的
  INSTRUCTION（直接导入，不复制），law 条件放整部法的原文，bare 条件不放 system 消息；
- 法的原文取自 workspace 的 agent-policy 仓库在 5eafb2e 上的 AGENTS.md（sha256 见 LAW_SHA256），
  这是原批次实际用过的版本；rebuilt 请求的 sha256 在调用前与
  evidence/slice-contrast/answers.jsonl 记录的 request_sha256 逐条核对，不一致就停。

用法：
  python3 scripts/resample_actions.py --generate
  python3 scripts/resample_actions.py --analyse
"""

import argparse
import hashlib
import importlib.util
import json
import random
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PAIRS = REPO / "data" / "pairs-filtered.jsonl"
SLICE_CONTRAST = REPO / "evidence" / "slice-contrast"
SOURCE_ANSWERS = SLICE_CONTRAST / "answers.jsonl"
PROBE_LIB = REPO / "evidence" / "bare-baseline" / "probe_lib.py"
JUDGE = REPO / "eval" / "judge.py"

EVIDENCE = REPO / "evidence" / "resample"
ANSWERS = EVIDENCE / "answers.jsonl"
STABLE_PAIRS = REPO / "data" / "pairs-stable.jsonl"
SIGNATURES = EVIDENCE / "signatures.jsonl"
COMPARE = EVIDENCE / "compare.jsonl"
SUMMARY = EVIDENCE / "summary.json"
RUN_META = EVIDENCE / "run-meta.json"

AGENT_POLICY = REPO.parent / "agent-policy"
LAW_COMMIT = "5eafb2e"  # the law bytes the stored answers were generated against
LAW_SHA256 = "325f8b3e2d868f91fb43c24dd088ae6e735386c6d5e2aacfc7496d6ff2726ab6"

ARMS = ("law", "bare")
SOURCE_ARM = {"law": "full", "bare": "bare"}  # probe 4 called the law arm "full"
TEMPERATURE = 0.0
MAX_TOKENS = 600
WORKERS = 6
MAX_CNY = 5.0

BOOTSTRAP = 10000
SEED = 20261103
PERMUTATION = 10000
PERMUTATION_SEED = 20261104
ALPHA = 0.05


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


p4 = load_module("probe4common", SLICE_CONTRAST / "common.py")
judge = load_module("judge", JUDGE)
lib = load_module("probe_lib", PROBE_LIB)

INSTRUCTION = p4.INSTRUCTION


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def append_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def law_text():
    """本来那一批用的法条原文，从 agent-policy 的 git 对象里取，并按 sha256 核对。"""
    loose = AGENT_POLICY / "AGENTS.md"
    text = None
    if (AGENT_POLICY / ".git").exists():
        result = subprocess.run(["git", "-C", str(AGENT_POLICY), "show", f"{LAW_COMMIT}:AGENTS.md"],
                                capture_output=True, text=True)
        if result.returncode == 0:
            text = result.stdout
    if text is None and loose.exists():
        candidate = loose.read_text(encoding="utf-8")
        if sha(candidate) == LAW_SHA256:
            text = candidate
    if text is None:
        raise SystemExit(f"取不到 agent-policy {LAW_COMMIT}:AGENTS.md；法条原文无法重建，拒绝继续")
    if sha(text) != LAW_SHA256:
        raise SystemExit(f"agent-policy {LAW_COMMIT}:AGENTS.md 的 sha256 是 {sha(text)}，不是 {LAW_SHA256}")
    return text


def pairs():
    rows = load_jsonl(PAIRS)
    if len(rows) != 174:
        raise SystemExit(f"{PAIRS} 有 {len(rows)} 行，期望 174")
    return rows


def stored_requests():
    """原批次每条处境的请求指纹，用来核对重采样是不是同一条提示。"""
    out = {}
    for row in load_jsonl(SOURCE_ANSWERS):
        if row["phase"] != "generate":
            continue
        out[(row["situation"], row["arm"])] = row
    return out


# --- 生成 ------------------------------------------------------------------

def build_messages(pair, arm, law):
    system = law if arm == "law" else ""
    prompt = pair["excerpt"] + INSTRUCTION
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}]
    return system, prompt, messages


def generate(pair, arm, law, stored, sequence):
    sid = pair["situation_id"]
    system, prompt, messages = build_messages(pair, arm, law)
    request_sha = sha(system + "\x00" + prompt)
    origin = stored[(sid, SOURCE_ARM[arm])]
    if request_sha != origin["request_sha256"]:
        raise SystemExit(f"{sid} {arm}: 重建的请求 sha256 {request_sha[:16]} 与原批次 "
                         f"{origin['request_sha256'][:16]} 不同，不是同一条提示，拒绝继续")
    body = {"model": lib.MODEL, "messages": messages, "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS, "thinking": {"type": "disabled"}}
    response, latency = lib.post(body)
    usage = response.get("usage", {})
    answer = (response["choices"][0]["message"].get("content") or "").strip()
    if not answer:
        raise SystemExit(f"{sid} {arm}: 空回答")
    row = lib.record(f"r{sequence:04d}", "resample", sid, arm, 0, TEMPERATURE, prompt, answer,
                     usage, response.get("created", 0), latency)
    row["finish_reason"] = response["choices"][0].get("finish_reason")
    row["request_sha256"] = request_sha
    row["source_request_sha256"] = origin["request_sha256"]
    row["system_chars"] = len(system)
    row["system_sha256"] = sha(system) if system else None
    return row


def run_generate():
    law = law_text()
    rows = pairs()
    stored = stored_requests()
    done = {(row["situation"], row["arm"]) for row in load_jsonl(ANSWERS)} if ANSWERS.exists() else set()
    pending = [(pair, arm) for pair in rows for arm in ARMS if (pair["situation_id"], arm) not in done]
    if not pending:
        print("重采样已全部落盘")
        return

    costs = [stored[(pair["situation_id"], SOURCE_ARM[arm])]["cost"]["cny"] for pair in rows for arm in ARMS]
    projected = sum(costs) / len(costs) * len(pending)
    print(f"{len(rows)} 条处境 × {len(ARMS)} 条件；待调用 {len(pending)} 次；按原批次单价投影 ¥{projected:.2f}")
    if projected > MAX_CNY:
        raise SystemExit(f"投影 ¥{projected:.2f} 超过上限 ¥{MAX_CNY:.2f}")
    lib.api_key()

    lock = threading.Lock()
    counter = {"n": 0}

    def work(item):
        pair, arm = item
        with lock:
            counter["n"] += 1
            sequence = counter["n"]
        row = generate(pair, arm, law, stored, sequence)
        with lock:
            append_rows(ANSWERS, [row])
        return row

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(work, item) for item in pending]
        for index, future in enumerate(futures, 1):
            future.result()
            if index % 30 == 0:
                print(f"  {index}/{len(futures)} 次调用完成", flush=True)

    rows = load_jsonl(ANSWERS)
    total = sum(row["cost"]["cny"] for row in rows)
    print(f"{ANSWERS.name} {len(rows)} 行，花费 ¥{total:.3f}")


# --- 动作签名 --------------------------------------------------------------

PLACEHOLDER = re.compile(r"<[^<>\s][^<>]*>")
PATH_TOKEN = re.compile(r"[\w./~<>*\[\]-]*[/.][\w./~<>*\[\]-]+|<[^<>\s][^<>]*>")
PROGRAM = re.compile(r"^[A-Za-z][\w.+-]*$")
SUB_TOKEN = re.compile(r"^[A-Za-z][\w.-]*$")
SUBCOMMAND_PROGRAMS = {
    "git", "pip", "pip3", "uv", "npm", "pnpm", "yarn", "apt", "apt-get", "conda", "brew",
    "docker", "kubectl", "systemctl", "service", "cargo", "go", "sqlite3", "psql", "mysql",
}


def normalise(text):
    return PLACEHOLDER.sub("<place>", text).strip()


def path_of(args):
    """动作的路径参数；`write`/`edit`/`read` 一类用 path/file 字段，取不到就用第一个像路径的词。"""
    try:
        parsed = json.loads(args)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        for key in ("path", "file_path", "file", "notebook_path", "target"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return normalise(value)
    match = PATH_TOKEN.search(args)
    return normalise(match.group(0)) if match else ""


def split_segments(command):
    """按 &&、||、;、| 切分 shell 命令，引号里的分隔符不算，所以 `sqlite3 x 'a;b'` 是一段。"""
    segments, current = [], []
    quote, escaped, index = None, False, 0
    while index < len(command):
        char = command[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            current.append(char)
            index += 1
            continue
        if char in "\"'":
            quote = char
            current.append(char)
            index += 1
            continue
        pair = command[index:index + 2]
        if pair in ("&&", "||"):
            segments.append("".join(current))
            current = []
            index += 2
            continue
        if char in ";|":
            segments.append("".join(current))
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    segments.append("".join(current))
    return segments


def command_signature(args):
    """一条 bash 命令的签名：每条分段命令的程序、子命令与目标路径。"""
    command = normalise(judge.shell_text(args))
    parts = []
    for segment in split_segments(command):
        tokens = [token for token in segment.strip().split() if token]
        if not tokens:
            continue
        program = tokens[0].rsplit("/", 1)[-1]
        subcommand = ""
        if program in SUBCOMMAND_PROGRAMS and len(tokens) > 1:
            subcommand = tokens[1] if SUB_TOKEN.match(tokens[1]) else ""
        target = ""
        for token in tokens[1:]:
            if token == subcommand or token.startswith("-"):
                continue
            match = PATH_TOKEN.search(token)
            if match and ("/" in match.group(0) or "." in match.group(0) or "<" in match.group(0)):
                target = match.group(0)
                break
        parts.append(":".join(part for part in (program, subcommand) if part) + (f" {target}" if target else ""))
    return " ; ".join(parts)


def signatures(answer):
    """(主签名, 粗签名)：主签名带对象与关键参数，粗签名只记工具名。"""
    actions = judge.parse_actions(answer)
    file_tools = judge.READ_TOOLS | judge.WRITE_TOOLS
    main, coarse = [], []
    for action in actions:
        tool = action["tool"].lower()
        coarse.append(tool)
        if tool == "bash":
            main.append(f"bash {command_signature(action['args'])}")
        elif tool in file_tools:
            target = path_of(action["args"])
            main.append(f"{tool} {target}" if target else tool)
        else:
            main.append(tool)
    return {"signature": main, "coarse": coarse,
            "actions": [{"tool": action["tool"], "class": judge.action_class(action)}
                        for action in actions]}


# --- 统计 ------------------------------------------------------------------

def rate(flags):
    return sum(1 for flag in flags if flag) / len(flags)


def bootstrap_ci(flags):
    rng = random.Random(SEED)
    values = []
    n = len(flags)
    for _ in range(BOOTSTRAP):
        values.append(sum(1 for _ in range(n) if flags[rng.randrange(n)]) / n)
    values.sort()
    return values[int(0.025 * BOOTSTRAP)], values[int(0.975 * BOOTSTRAP) - 1]


def bootstrap_diff(a, b):
    rng = random.Random(SEED + 1)
    n = len(a)
    values = []
    for _ in range(BOOTSTRAP):
        sa = sb = 0
        for _ in range(n):
            index = rng.randrange(n)
            sa += a[index]
            sb += b[index]
        values.append((sa - sb) / n)
    values.sort()
    return values[int(0.025 * BOOTSTRAP)], values[int(0.975 * BOOTSTRAP) - 1]


def permutation_p(slots):
    """同一条处境里四次抽样可交换时，跨条件不一致率减同条件不一致率的零分布。

    每次置换把一条处境的四个动作签名随机重排到 law_0 / law_1 / bare_0 / bare_1 四个位置，
    重算统计量。法没有作用时，这份重排与原排布同分布。
    """
    rng = random.Random(PERMUTATION_SEED)
    observed = permuted_statistic(slots)
    hits = 0
    null_values = []
    for _ in range(PERMUTATION):
        shuffled = []
        for slot in slots:
            items = list(slot)
            rng.shuffle(items)
            shuffled.append(items)
        value = permuted_statistic(shuffled)
        null_values.append(value)
        if abs(value) >= abs(observed) - 1e-12:
            hits += 1
    null_values.sort()
    mean = sum(null_values) / len(null_values)
    variance = sum((value - mean) ** 2 for value in null_values) / (len(null_values) - 1)
    p = (hits + 1) / (PERMUTATION + 1)
    return {"observed": observed, "p": p, "null_mean": mean, "null_sd": variance ** 0.5,
            "null_q025": null_values[int(0.025 * PERMUTATION)],
            "null_q975": null_values[int(0.975 * PERMUTATION) - 1]}


def permuted_statistic(slots):
    """跨条件不一致率减同条件不一致率。

    slots 的四个位置依次是 law_0、law_1、bare_0、bare_1；同条件对比是 law_0-law_1 与
    bare_0-bare_1。
    """
    cross = same = 0
    for slot in slots:
        law0, law1, bare0, bare1 = slot
        cross += law0 != bare0
        same += (law0 != law1) + (bare0 != bare1)
    n = len(slots)
    return cross / n - same / (2 * n)


# --- 分析 ------------------------------------------------------------------

def run_analyse():
    rows = pairs()
    answers = load_jsonl(ANSWERS)
    by_key = {(row["situation"], row["arm"]): row for row in answers}
    missing = [(pair["situation_id"], arm) for pair in rows for arm in ARMS
               if (pair["situation_id"], arm) not in by_key]
    if missing:
        raise SystemExit(f"缺 {len(missing)} 条重采样回答，先跑 --generate：{missing[:5]}")

    signature_rows, compare_rows = [], []
    slots, coarse_slots = [], []
    for pair in rows:
        sid = pair["situation_id"]
        draws = {
            "law_0": signatures(pair["chosen"]),
            "bare_0": signatures(pair["rejected"]),
            "law_1": signatures(by_key[(sid, "law")]["response"]),
            "bare_1": signatures(by_key[(sid, "bare")]["response"]),
        }
        for draw, value in draws.items():
            signature_rows.append({"situation_id": sid, "draw": draw,
                                   "answer_sha256": sha(
                                       pair["chosen"] if draw == "law_0"
                                       else pair["rejected"] if draw == "bare_0"
                                       else by_key[(sid, "law" if draw.startswith("law") else "bare")]["response"]),
                                   "signature": value["signature"], "coarse": value["coarse"],
                                   "actions": value["actions"]})
        main = {draw: value["signature"] for draw, value in draws.items()}
        coarse = {draw: value["coarse"] for draw, value in draws.items()}
        slots.append([main["law_0"], main["law_1"], main["bare_0"], main["bare_1"]])
        coarse_slots.append([coarse["law_0"], coarse["law_1"], coarse["bare_0"], coarse["bare_1"]])
        compare_rows.append({
            "situation_id": sid,
            "signatures": main,
            "agreement": {
                "stored_law_vs_stored_bare": main["law_0"] == main["bare_0"],
                "stored_law_vs_new_law": main["law_0"] == main["law_1"],
                "stored_bare_vs_new_bare": main["bare_0"] == main["bare_1"],
                "new_law_vs_new_bare": main["law_1"] == main["bare_1"],
                "stored_law_vs_new_bare": main["law_0"] == main["bare_1"],
                "new_law_vs_stored_bare": main["law_1"] == main["bare_0"],
            },
            "coarse_agreement": {
                "stored_law_vs_stored_bare": coarse["law_0"] == coarse["bare_0"],
                "stored_law_vs_new_law": coarse["law_0"] == coarse["law_1"],
                "stored_bare_vs_new_bare": coarse["bare_0"] == coarse["bare_1"],
            },
        })

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    SIGNATURES.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in signature_rows),
                          encoding="utf-8")
    COMPARE.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in compare_rows),
                       encoding="utf-8")

    def column(name, field="agreement"):
        return [row[field][name] for row in compare_rows]

    comparisons = {
        "law_vs_bare": column("stored_law_vs_stored_bare"),
        "law_vs_law": column("stored_law_vs_new_law"),
        "bare_vs_bare": column("stored_bare_vs_new_bare"),
    }
    same = [a or b for a, b in zip(comparisons["law_vs_law"], comparisons["bare_vs_bare"])]

    def block(flags):
        low, high = bootstrap_ci(flags)
        return {"n": len(flags), "agree": sum(1 for flag in flags if flag),
                "rate": rate(flags), "ci95": [low, high]}

    result = {name: block(flags) for name, flags in comparisons.items()}
    result["same_condition_pooled"] = block(same)

    cross_disagree = [not flag for flag in comparisons["law_vs_bare"]]
    disagreement_differences = {}
    for name in ("law_vs_law", "bare_vs_bare"):
        same_disagree = [not flag for flag in comparisons[name]]
        low, high = bootstrap_diff(cross_disagree, same_disagree)
        disagreement_differences[name] = {
            "cross_rate": rate(cross_disagree),
            "same_rate": rate(same_disagree),
            "difference": rate(cross_disagree) - rate(same_disagree),
            "ci95": [low, high],
        }

    differences = {}
    for name in ("law_vs_law", "bare_vs_bare"):
        low, high = bootstrap_diff(comparisons["law_vs_bare"], comparisons[name])
        differences[name] = {"difference": rate(comparisons["law_vs_bare"]) - rate(comparisons[name]),
                             "ci95": [low, high]}
    low, high = bootstrap_diff(comparisons["law_vs_bare"], same)
    differences["same_condition_pooled"] = {
        "difference": rate(comparisons["law_vs_bare"]) - rate(same),
        "ci95": [low, high],
        "expected_differing_pairs_under_no_effect": rate(same) * len(same),
        "observed_differing_pairs": sum(1 for flag in comparisons["law_vs_bare"] if not flag),
    }

    permutation = permutation_p(slots)
    coarse = {name: block(column(name, "coarse_agreement")) for name in
              ("stored_law_vs_stored_bare", "stored_law_vs_new_law", "stored_bare_vs_new_bare")}
    coarse_same = [row["coarse_agreement"]["stored_law_vs_new_law"]
                   or row["coarse_agreement"]["stored_bare_vs_new_bare"] for row in compare_rows]
    coarse["same_condition_pooled"] = block(coarse_same)
    coarse_permutation = permutation_p(coarse_slots)

    empty = [row["situation_id"] for row in compare_rows if not row["signatures"]["law_0"]]
    both_empty = [row["situation_id"] for row in compare_rows
                  if not row["signatures"]["law_0"] and not row["signatures"]["bare_0"]]

    joint = {
        "stored_differ_resample_law_reproduces_stored_law": sum(
            1 for row in compare_rows
            if not row["agreement"]["stored_law_vs_stored_bare"] and row["agreement"]["stored_law_vs_new_law"]),
        "stored_differ_resample_bare_reproduces_stored_bare": sum(
            1 for row in compare_rows
            if not row["agreement"]["stored_law_vs_stored_bare"]
            and row["agreement"]["stored_bare_vs_new_bare"]),
        "stored_differ_count": sum(1 for row in compare_rows if not row["agreement"]["stored_law_vs_stored_bare"]),
    }
    joint["resample_reproduces_its_own_side_share"] = (
        joint["stored_differ_resample_law_reproduces_stored_law"]
        + joint["stored_differ_resample_bare_reproduces_stored_bare"]) / (2 * joint["stored_differ_count"])

    verdict = {
        "rule": "法有作用 = 跨条件不一致率分别高于两个同条件重采样不一致率：两个差值的 95% 自助区间下界都 > 0；"
                "置换检验 p 一并报告，不单独决定方向",
        "alpha": ALPHA,
        "law_has_effect": bool(all(
            disagreement_differences[name]["ci95"][0] > 0 for name in ("law_vs_law", "bare_vs_bare"))),
        "permutation_p": permutation["p"],
        "disagreement_differences": disagreement_differences,
    }

    stable_rows = [
        {"situation_id": pair["situation_id"], "signals": pair["signals"], "excerpt": pair["excerpt"],
         "chosen": pair["chosen"], "rejected": pair["rejected"],
         "signatures": {"law": compare["signatures"]["law_0"], "bare": compare["signatures"]["bare_0"]},
         "cross_condition_differs": not compare["agreement"]["stored_law_vs_stored_bare"]}
        for pair, compare in zip(rows, compare_rows)
        if compare["agreement"]["stored_law_vs_new_law"] and compare["agreement"]["stored_bare_vs_new_bare"]]
    STABLE_PAIRS.parent.mkdir(parents=True, exist_ok=True)
    STABLE_PAIRS.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in stable_rows),
                            encoding="utf-8")

    def disagree_block(flags):
        low, high = bootstrap_ci(flags)
        return {"n": len(flags), "differ": sum(1 for flag in flags if flag), "rate": rate(flags),
                "ci95": [low, high]}

    stable_cross = [row["cross_condition_differs"] for row in stable_rows]
    with_actions = [row for row in stable_rows if row["signatures"]["law"] or row["signatures"]["bare"]]
    stable = {
        "rule": "稳定对 = 存下 law 回答被第二次 law 抽样复现，且存下 bare 回答被第二次 bare 抽样复现（同一动作签名）",
        "n": len(stable_rows),
        "dropped": len(rows) - len(stable_rows),
        "dropped_stored_law_not_reproduced_only": sum(
            1 for compare in compare_rows
            if not compare["agreement"]["stored_law_vs_new_law"] and compare["agreement"]["stored_bare_vs_new_bare"]),
        "dropped_stored_bare_not_reproduced_only": sum(
            1 for compare in compare_rows
            if compare["agreement"]["stored_law_vs_new_law"] and not compare["agreement"]["stored_bare_vs_new_bare"]),
        "dropped_both_not_reproduced": sum(
            1 for compare in compare_rows
            if not compare["agreement"]["stored_law_vs_new_law"] and not compare["agreement"]["stored_bare_vs_new_bare"]),
        "both_stored_answers_without_actions": sum(
            1 for row in stable_rows if not row["signatures"]["law"] and not row["signatures"]["bare"]),
        "cross_condition_disagreement": disagree_block(stable_cross),
        "cross_condition_disagreement_with_actions": disagree_block(
            [row["cross_condition_differs"] for row in with_actions]),
        "output": str(STABLE_PAIRS.relative_to(REPO)),
    }

    summary = {
        "pairs": len(rows),
        "answers": len(answers),
        "spend_cny": sum(row["cost"]["cny"] for row in answers),
        "signature_rule": "动作 = (工具, 程序:子命令, 目标路径)；占位符 <PATH>/<REPO>/<HEX> 归一为 "
                          "<place>；签名 = 按顺序的动作列表；签名相同记一致",
        "comparisons": result,
        "differences": differences,
        "disagreement": {name: disagree_block([not flag for flag in flags])
                          for name, flags in comparisons.items()},
        "verdict": verdict,
        "stable_subset": stable,
        "permutation": permutation,
        "coarse": coarse,
        "coarse_permutation": coarse_permutation,
        "joint": joint,
        "stored_law_answer_without_actions": len(empty),
        "stored_both_answers_without_actions": len(both_empty),
        "inputs": {"pairs_sha256": sha(PAIRS.read_text(encoding="utf-8")),
                   "source_answers_sha256": sha(SOURCE_ANSWERS.read_text(encoding="utf-8")),
                   "law_sha256": LAW_SHA256, "law_commit": LAW_COMMIT,
                   "instruction_sha256": sha(INSTRUCTION)},
        "constants": {"bootstrap": BOOTSTRAP, "seed": SEED, "permutation": PERMUTATION,
                      "permutation_seed": PERMUTATION_SEED, "temperature": TEMPERATURE,
                      "model": lib.MODEL, "max_tokens": MAX_TOKENS},
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    RUN_META.write_text(json.dumps({"model": lib.MODEL, "temperature": TEMPERATURE,
                                    "max_tokens": MAX_TOKENS, "thinking": "disabled",
                                    "arms": {"law": "整部 AGENTS.md 作 system 消息", "bare": "无 system 消息"},
                                    "law_commit": LAW_COMMIT, "law_sha256": LAW_SHA256,
                                    "request_gate": "每次调用的 request_sha256 必须等于 "
                                                    "evidence/slice-contrast/answers.jsonl 记录的原批次指纹",
                                    "pairs": len(rows), "calls": len(answers)},
                                   ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"law 对 bare      {result['law_vs_bare']['rate']:.3f}  "
          f"[{result['law_vs_bare']['ci95'][0]:.3f}, {result['law_vs_bare']['ci95'][1]:.3f}]  "
          f"{result['law_vs_bare']['agree']}/{result['law_vs_bare']['n']}")
    print(f"law 对 law       {result['law_vs_law']['rate']:.3f}  "
          f"[{result['law_vs_law']['ci95'][0]:.3f}, {result['law_vs_law']['ci95'][1]:.3f}]  "
          f"{result['law_vs_law']['agree']}/{result['law_vs_law']['n']}")
    print(f"bare 对 bare     {result['bare_vs_bare']['rate']:.3f}  "
          f"[{result['bare_vs_bare']['ci95'][0]:.3f}, {result['bare_vs_bare']['ci95'][1]:.3f}]  "
          f"{result['bare_vs_bare']['agree']}/{result['bare_vs_bare']['n']}")
    print(f"同条件合并       {result['same_condition_pooled']['rate']:.3f}  "
          f"[{result['same_condition_pooled']['ci95'][0]:.3f}, "
          f"{result['same_condition_pooled']['ci95'][1]:.3f}]")
    for name, label in (("law_vs_law", "law 重采样"), ("bare_vs_bare", "bare 重采样")):
        item = disagreement_differences[name]
        print(f"不一致率 跨 {item['cross_rate']:.3f} 对 {label} {item['same_rate']:.3f}；"
              f"差 {item['difference']:+.3f} [{item['ci95'][0]:+.3f}, {item['ci95'][1]:+.3f}]")
    print(f"置换 p {permutation['p']:.4f}  零分布均值 {permutation['null_mean']:+.3f} "
          f"标准差 {permutation['null_sd']:.3f}")
    print(f"法有作用：{verdict['law_has_effect']}"
          "（跨条件不一致率分别高于两个同条件不一致率，两个差值的区间下界都 > 0）")
    print(f"稳定对 {stable['n']}/{len(rows)}，跨条件不一致 {stable['cross_condition_disagreement']['rate']:.3f} "
          f"[{stable['cross_condition_disagreement']['ci95'][0]:.3f}, "
          f"{stable['cross_condition_disagreement']['ci95'][1]:.3f}]，"
          f"其中两侧都无动作 {stable['both_stored_answers_without_actions']} 对")
    print(f"写完 {SIGNATURES.name}、{COMPARE.name}、{SUMMARY.name}、{RUN_META.name}、{STABLE_PAIRS.name}")


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
