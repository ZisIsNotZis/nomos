#!/usr/bin/env bash
# M6 第 2 条指向的那一包：2-epoch 适配器的全量政策测量（242 条处境 × 3 条），
# 与已落盘的 base 侧配对，再按「训练见过 / 按会话留出」拆开。
#
# 只有 post 一侧是新生成的：base 侧那 726 条是落盘件（320 上限下的生成），直接拷进本目录，
# 逐条断言与落盘件同字节。上限显式给 320，与 base 侧同一上限——落盘的 base 侧按 person
# 2026-10-23 的决定不重抽，所以新侧只能跟它对齐，否则两侧上限不同、差值会把 30 条截断
# 算进 base 一侧的低估里。新套件才用默认的最长合法输出十倍（3110）。
set -u
cd "$(dirname "$0")/../.." || exit 1
REPO=$(pwd)
OUT="$REPO/evidence/measure/e2"
LOGS="$OUT/logs"
mkdir -p "$OUT" "$LOGS" "$REPO/inbox"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

echo "start $(date -u +%FT%TZ) adapter=.tmp/sft/adapter-e2 out=evidence/measure/e2" | tee -a "$LOGS/driver.log"

# 1) 拷 base 侧：只拷、不改、逐字段断言。目标文件已存在时不覆盖（重跑只补 post 侧）。
python3 - "$REPO" <<'PY'
import hashlib, json, sys
from pathlib import Path
repo = Path(sys.argv[1])
src = repo / "evidence" / "measure" / "answers.jsonl"
dst = repo / "evidence" / "measure" / "e2" / "answers.jsonl"
rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
base = [r for r in rows if r["model"] == "base"]
assert len(rows) == 1452, len(rows)
assert len(base) == 726, len(base)
assert len({r["situation"] for r in base}) == 242
assert all(r["model"] == "post" for r in rows if r["model"] != "base")
cap = {r.get("max_new_tokens") for r in rows if r.get("max_new_tokens") is not None}
cap |= {r["completion_tokens"] for r in rows if r.get("truncated")}
assert cap == {320}, cap
if dst.exists():
    have = [json.loads(l) for l in dst.read_text(encoding="utf-8").splitlines() if l.strip()]
    kept = [r for r in have if r["model"] == "base"]
    assert kept == base, "本目录里的 base 行与落盘件不同字节，先查清再跑"
    print(f"base 侧已在 {dst}（{len(kept)} 行），不覆盖")
else:
    dst.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in base), encoding="utf-8")
    print(f"拷入 base 侧 {len(base)} 行 -> {dst}（sha256 {hashlib.sha256(dst.read_bytes()).hexdigest()[:16]}）")
PY

# 2) 生成 post 侧（可续跑：已落盘的键会跳过）。
python3 scripts/measure_actions.py --generate \
  --adapter-dir .tmp/sft/adapter-e2 --answers "$OUT/answers.jsonl" --max-new-tokens 320 \
  > "$LOGS/generate.log" 2>&1
rc_gen=$?
echo "generate rc=$rc_gen $(date -u +%FT%TZ)" | tee -a "$LOGS/driver.log"
if [ "$rc_gen" -ne 0 ]; then
  tail -20 "$LOGS/generate.log" | tee -a "$LOGS/driver.log"
  exit 1
fi

# 3) 分析：与落盘侧同一套重采样代码与种子，写进本目录，不碰 evidence/measure/summary.json。
python3 scripts/measure_actions.py --analyse \
  --adapter-dir .tmp/sft/adapter-e2 --answers "$OUT/answers.jsonl" --out-dir "$OUT" \
  > "$LOGS/analyse.log" 2>&1
rc_an=$?
echo "analyse rc=$rc_an $(date -u +%FT%TZ)" | tee -a "$LOGS/driver.log"

# 2b) 元数据断言：summary 里记的 post 适配器必须是本试验那一个。
#      2026-10-26 第一次跑漏了 --adapter-dir，数字是 e2 的、元数据写的却是 adapter-narrow。
python3 - "$REPO" <<'PY' | tee -a "$LOGS/driver.log"
import json, sys
from pathlib import Path
repo = Path(sys.argv[1])
summary = json.loads((repo / "evidence" / "measure" / "e2" / "summary.json").read_text())
want = str(repo / ".tmp" / "sft" / "adapter-e2")
got = summary["models"]["post"]
print(f"summary.models.post {got}")
if got != want:
    raise SystemExit(f"元数据写的是 {got}，不是 {want}；先重跑 --analyse 并带上正确的 --adapter-dir")
PY
rc_meta=$?
echo "meta rc=$rc_meta $(date -u +%FT%TZ)" | tee -a "$LOGS/driver.log"

# 4) 见过 / 留出拆分。paired_all 必须逐字段复现本目录的 summary.json，否则脚本自己会停。
python3 scripts/measure_split.py \
  --summary "$OUT/summary.json" --per-situation "$OUT/per-situation.jsonl" \
  --out "$OUT/seen-heldout.json" > "$LOGS/split.log" 2>&1
rc_sp=$?
echo "split rc=$rc_sp $(date -u +%FT%TZ)" | tee -a "$LOGS/driver.log"

# 5) 收信（driver 自己写，不靠 watcher；watcher 随它的 turn 回收）。
python3 - "$REPO" "$rc_gen" "$rc_an" "$rc_sp" <<'PY' | tee -a "$LOGS/driver.log"
import json, sys
from pathlib import Path
repo, rc_gen, rc_an, rc_sp = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
out = repo / "evidence" / "measure" / "e2"
lines = ["kind:    report",
         "from:    run-e2-policy-driver",
         "spend:   idle-compute",
         "id:      AGENTS.md M6（第 2 条：2-epoch 适配器的全量政策测量）",
         "",
         "# 2-epoch 适配器的政策测量跑完",
         "",
         f"exit codes: generate={rc_gen} analyse={rc_an} split={rc_sp}",
         ""]
s = out / "summary.json"
if s.exists():
    summary = json.loads(s.read_text())
    keep = {k: summary.get(k) for k in (
        "status", "n_pairs", "coverage", "base_mean", "post_mean", "X", "X_ci",
        "situations_paired", "situations_both_complete", "truncated_answers")}
    keep["delta"] = summary["decomposition"]["delta"]
    keep["delta_ci"] = summary["decomposition"]["delta_ci"]
    keep["post"] = summary["models"]["post"]
    lines.append(f"- `summary.json`: {json.dumps(keep, ensure_ascii=False)}")
else:
    lines.append("- `summary.json`: missing")
sh = out / "seen-heldout.json"
if sh.exists():
    payload = json.loads(sh.read_text())
    for name in ("paired_seen", "paired_held_out"):
        b = payload[name]
        lines.append(f"- `{name}`: n={b['situations_paired']} base={b['base_mean']:.4f} "
                     f"post={b['post_mean']:.4f} delta={b['delta']:+.4f} "
                     f"ci95=[{b['delta_ci'][0]:+.4f},{b['delta_ci'][1]:+.4f}] "
                     f"X={b['X']}")
else:
    lines.append("- `seen-heldout.json`: missing")
lines += ["", "A separate turn reads this and decides whether it is adopt evidence.", ""]
(repo / "inbox" / "2026-10-26-e2-policy-done.md").write_text("\n".join(lines) + "\n")
print("completion written")
PY
echo "done $(date -u +%FT%TZ)" | tee -a "$LOGS/driver.log"
