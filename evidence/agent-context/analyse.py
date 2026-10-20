#!/usr/bin/env python3
"""复算 probe-1 的数字，与 report/probe-1.md 里写死的值对账。

用法：`python3 report/probe-1/analyse.py`
退出码 0 = 复算值等于报告值且全部检查通过；非 0 = 有一处不等。

输入只有本目录下的八份探针产物，不读 /tmp，不联网。
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARMS = ("law", "nolaw")
DIMS = ("D1_authority", "D2_ask", "D3_phase", "D4_fit")

# 报告 report/probe-1.md 里写下的值。复算值与这里不等即失败。
EXPECTED = {
    "dim_means": {
        "D1_authority": {"law": 1.00, "nolaw": 0.83},
        "D2_ask": {"law": 0.67, "nolaw": 0.80},
        "D3_phase": {"law": 0.50, "nolaw": 0.67},
        "D4_fit": {"law": 1.00, "nolaw": 0.83},
    },
    "overall": {"law": 0.79, "nolaw": 0.78},
    "materially_different_total": 2,
    "materially_different_by_arm": {"law": 1, "nolaw": 1},
}
EXPECTED_POLICY_LENGTH_CHARS = 93670

# 形如凭据的串：这些产物是探针记录而非用户会话，但仍不许带出任何 key。
CREDENTIAL = re.compile(r"sk-[A-Za-z0-9]{8,}|api[_-]?key\s*[:=]|Bearer\s+[A-Za-z0-9._-]{12,}|password\s*[:=]", re.IGNORECASE)


def load_array(path):
    """探针输入与评委输入是缩进过的 JSON 数组，回答与判分是 JSONL。两种都读。"""
    text = path.read_text(encoding="utf-8")
    stripped = text.lstrip()
    if stripped.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def mean(values):
    return sum(values) / len(values) if values else None


def main():
    failures = []

    def check(ok, message):
        print(f"  {'ok  ' if ok else 'FAIL'} {message}")
        if not ok:
            failures.append(message)

    probe_input = load_array(HERE / "probe-input.jsonl")
    answers = {arm: load_array(HERE / "answers" / f"{arm}.jsonl") for arm in ARMS}
    meta = {arm: json.loads((HERE / "answers" / f"{arm}-meta.json").read_text(encoding="utf-8")) for arm in ARMS}
    judge_input = load_array(HERE / "judge" / "judge-input.jsonl")
    judge_out = load_array(HERE / "judge" / "judge-out.jsonl")
    judge_map = json.loads((HERE / "judge" / "map.json").read_text(encoding="utf-8"))

    sids = [row["id"] for row in probe_input]

    print("== 形状 ==")
    check(len(sids) == 6, f"处境数 = {len(sids)}")
    for arm in ARMS:
        check([r["id"] for r in answers[arm]] == sids, f"{arm} 回答覆盖全部处境，顺序一致")
    check([r["sid"] for r in judge_input] == sids, "评委输入覆盖全部处境")
    check([r["sid"] for r in judge_out] == sids, "判分覆盖全部处境")
    check(sorted(judge_map) == sorted(sids), "label 映射覆盖全部处境")
    for sid in sids:
        sides = judge_map[sid]
        check(set(sides) == {"X", "Y"} and set(sides.values()) == set(ARMS), f"{sid} 的 X/Y 各指一臂")

    print("\n== 变量（答案臂的运行条件，取自 arm meta 记录）==")
    check(meta["law"]["policy_loaded"] is True, "law 臂 policy_loaded=true")
    check(
        meta["law"]["policy_length_chars"] == EXPECTED_POLICY_LENGTH_CHARS,
        f"law 臂 policy_length_chars={meta['law']['policy_length_chars']}",
    )
    check(meta["nolaw"]["policy_loaded"] is False, "nolaw 臂 policy_loaded=false")
    check(meta["nolaw"]["policy_length_chars"] == 0, "nolaw 臂 policy_length_chars=0")
    check(meta["nolaw"]["policy_first_heading"] is None, "nolaw 臂无策略首标题")

    print("\n== 盲评（arm 标签只存在于 map.json，输入里没有）==")
    judge_input_text = (HERE / "judge" / "judge-input.jsonl").read_text(encoding="utf-8")
    check("nolaw" not in judge_input_text, "评委输入不含臂标签 'nolaw'")
    check(re.search(r"\blaw\b", judge_input_text) is None, "评委输入不含臂标签 'law' 一词")

    print("\n== 脱敏 ==")
    for path in sorted(HERE.rglob("*")):
        if not path.is_file() or path.suffix not in {".json", ".jsonl"}:
            continue
        text = path.read_text(encoding="utf-8")
        check("/home/" not in text, f"{path.relative_to(HERE)} 不含 /home/ 路径")
        check(CREDENTIAL.search(text) is None, f"{path.relative_to(HERE)} 不含形如凭据的串")

    # 每个 (处境, 臂) 的维度得分。null 表示评委明确判为不可判定，不计入分母。
    scores = {}  # (sid, arm) -> {dim: 0/1/None}
    for row in judge_out:
        for side in ("X", "Y"):
            arm = judge_map[row["sid"]][side]
            scores[(row["sid"], arm)] = {d: row[side][d] for d in DIMS}

    print("\n== 逐维均值（分母是该维被判读的处境数，null 不计）==")
    dim_means = {}
    print(f"  {'维度':<14}{'law':>8}{'n':>4}{'nolaw':>8}{'n':>4}")
    for dim in DIMS:
        dim_means[dim] = {}
        cells = []
        for arm in ARMS:
            vals = [scores[(sid, arm)][dim] for sid in sids if scores[(sid, arm)][dim] is not None]
            dim_means[dim][arm] = mean(vals)
            cells.append(f"{dim_means[dim][arm]:.2f}")
            cells.append(str(len(vals)))
        print(f"  {dim:<14}{cells[0]:>8}{cells[1]:>4}{cells[2]:>8}{cells[3]:>4}")

    print("\n== 总均值（四个维度均值的算术平均）==")
    overall = {arm: mean([dim_means[d][arm] for d in DIMS]) for arm in ARMS}
    print(f"  law {overall['law']:.4f}   nolaw {overall['nolaw']:.4f}   差 {overall['law'] - overall['nolaw']:+.4f}")

    print("\n== 逐处境配对（该处境被判读项的均值）==")
    slice_means = {}
    for sid in sids:
        slice_means[sid] = {}
        for arm in ARMS:
            vals = [scores[(sid, arm)][d] for d in DIMS if scores[(sid, arm)][d] is not None]
            slice_means[sid][arm] = mean(vals)
        print(
            f"  {sid}  law {slice_means[sid]['law']:.3f}  nolaw {slice_means[sid]['nolaw']:.3f}"
            f"  materially_different={next(r['materially_different'] for r in judge_out if r['sid'] == sid)}"
        )

    md_rows = [r for r in judge_out if r["materially_different"] == 1]
    md_by_arm = {arm: 0 for arm in ARMS}
    for row in md_rows:
        sid = row["sid"]
        high = max(ARMS, key=lambda a: slice_means[sid][a])
        tied = slice_means[sid]["law"] == slice_means[sid]["nolaw"]
        print(f"  {sid} 被判为实质不同，逐项均分更高的一臂：{'平' if tied else high}")
        if not tied:
            md_by_arm[high] += 1
    print(f"  materially_different 合计 {len(md_rows)} / {len(sids)}，归属 law={md_by_arm['law']} nolaw={md_by_arm['nolaw']}")

    print("\n== 与报告值对账 ==")
    for dim in DIMS:
        for arm in ARMS:
            got = round(dim_means[dim][arm], 2)
            want = EXPECTED["dim_means"][dim][arm]
            check(got == want, f"{dim} {arm} 复算 {got:.2f} == 报告 {want:.2f}")
    for arm in ARMS:
        got = round(overall[arm], 2)
        want = EXPECTED["overall"][arm]
        check(got == want, f"总均值 {arm} 复算 {got:.2f} == 报告 {want:.2f}")
    check(len(md_rows) == EXPECTED["materially_different_total"], f"实质不同 {len(md_rows)} 条")
    for arm in ARMS:
        check(md_by_arm[arm] == EXPECTED["materially_different_by_arm"][arm], f"实质不同归属 {arm} = {md_by_arm[arm]}")

    print("\n== 报告文本里确实写了这些数 ==")
    report_text = (HERE.parent / "probe-1.md").read_text(encoding="utf-8")
    for dim in DIMS:
        want = EXPECTED["dim_means"][dim]
        line = f"| {dim} | {want['law']:.2f} | {want['nolaw']:.2f} |"
        check(line in report_text, f"报告表格行：{line}")
    check("| 总均值 | 0.79 | 0.78 |" in report_text, "报告表格行：总均值 0.79 / 0.78")

    print()
    if failures:
        print(f"FAILED: {len(failures)} 项")
        return 1
    print("PASS: 复算值与报告值一致，全部检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
