#!/usr/bin/env python3
"""只读检查：发布文本有没有把没测过的轴当已测讲。

用法：python3 scripts/check_axes_claim.py
退出码 0 = 两件事都成立；1 = 有违规（逐条打印）。

A. 任何一句提到 `agentic` 的话，同一句里必须有一个「没测」类标记
   （未测 / 没测 / 没有测 / 不测 / 未验证 / 不可证伪 / 不声称 / 不在这条主张里）。
   只读发布面，不读证据、脚本、vendor 与 `mail/`。
B. 主张面（`docs/5_PRODUCT.md`「主张」、`paper/draft.md` §1）必须点名
   本轮实测的两条轴（GSM8K、IFEval）。

这个检查是给「§1 收窄成实测的两轴」那条决定用的：它失败时会指出具体哪一句
把没测的轴讲了进去，所以写回一句含糊话也过不去。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 发布面：读者会当成「本研究的主张」来读的文本。
SURFACES = [
    "README.md",
    "card/model-card.md",
    "paper/draft.md",
    "docs/5_PRODUCT.md",
    "evidence/reports/sft-benchmark.md",
]

# 一句里出现任何一个，就算这一句说清了状态。
MARKERS = ("未测", "没测", "没有测", "不测", "未验证", "不可证伪", "不声称", "不在这条主张里")

AXIS = "agentic"

# (文件, 主张段起始行前缀, 主张段结束行前缀)
CLAIM_SECTIONS = [
    ("docs/5_PRODUCT.md", "### 主张（发布文本里唯一被允许的说法）", "### 不是什么"),
    ("paper/draft.md", "## 1 ", "## 2 "),
]

MEASURED_AXES = ("GSM8K", "IFEval")

# 只按句末标点切；分号留在同一句里，免得把一个分句的标记借给另一句。
SENTENCE_END = re.compile(r"(?<=[。！？])")


def sentences(text: str):
    """逐句产出 (行号, 句子)。句子不跨行，行号就是它起点所在的行。"""
    for line_no, line in enumerate(text.splitlines(), start=1):
        for part in SENTENCE_END.split(line):
            part = part.strip()
            if part:
                yield line_no, part


def section(text: str, start: str, end: str):
    """取第一个以 start 开头的行，到第一个以 end 开头的行之前（都不含）。"""
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        if not inside:
            if line.startswith(start):
                inside = True
            continue
        if line.startswith(end):
            return "\n".join(out)
        out.append(line)
    return "\n".join(out) if inside else None


def main() -> int:
    problems: list[tuple[str, int, str]] = []
    mentions = 0

    for rel in SURFACES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        for line_no, sentence in sentences(text):
            if AXIS not in sentence.lower():
                continue
            mentions += 1
            if any(marker in sentence for marker in MARKERS):
                continue
            problems.append((rel, line_no, sentence))

    for rel, start, end in CLAIM_SECTIONS:
        body = section((ROOT / rel).read_text(encoding="utf-8"), start, end)
        if body is None:
            problems.append((rel, 0, f"找不到主张段的起止标记（{start.strip()} / {end.strip()}）"))
            continue
        missing = [axis for axis in MEASURED_AXES if axis not in body]
        if missing:
            problems.append((rel, 0, "主张段没有点名实测轴：" + "、".join(missing)))

    print(f"发布面 {len(SURFACES)} 个文件，提到 {AXIS} 的句子 {mentions} 句，违规 {len(problems)} 处")
    for rel, line_no, sentence in problems:
        where = f"{rel}:{line_no}" if line_no else rel
        print(f"FAIL {where}: {sentence[:200]}")
    if not problems:
        print("PASS：每一句提到 agentic 的话都写明它没测；两处主张段都点名 GSM8K 与 IFEval。")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
