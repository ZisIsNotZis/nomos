#!/usr/bin/env python3
"""Structural scan of the local pi session corpus for candidate situations.

Rerunnable and deterministic: same corpus in, same counts out.
Writes mining/candidates.jsonl, mining/sample-30.md and mining/report.md.

Method and thresholds are stated in mining/report.md; the six signal ids are
S1_interrupt_after_tool_call, S2_tool_burst_no_checkpoint, S3_repeat_user_turn,
S4_negation_lead, S5_quotes_assistant_text, S6_assistant_self_flagged_failure.
"""

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

CORPUS = Path(os.path.expanduser("~/.pi/agent/sessions"))
OUT_DIR = Path(__file__).resolve().parent

# --- thresholds (documented in report.md) -----------------------------------
BURST_MIN_TOOL_CALLS = 8        # S2: tool calls per assistant segment...
BURST_CHECKPOINT_CHARS = 120    # ...with no assistant paragraph this long inside it
REPEAT_MIN_CHARS = 12           # S3: shortest normalised user turn considered
REPEAT_JACCARD = 0.60           # S3: char 4-gram set overlap
REPEAT_LOOKBACK = 4             # S3: compare against the previous N user turns
QUOTE_MIN_CHARS = 30            # S5: shortest verbatim span quoted from the assistant
INJECTED_MIN_OCCURRENCES = 100  # harness template: repeated this often in the corpus
INJECTED_MIN_PROJECTS = 8       # ... across at least this many project buckets
WINDOW_MAX_TURNS = 4            # a window is 2..4 turns ending at the decision point
STEP_HEAD = 1                   # rendered steps kept from the head of a turn...
STEP_TAIL = 6                   # ...and from its tail, where the decision point is
WINDOW_MAX_CHARS = 4000
SAMPLE_WINDOW_CHARS = 900
SAMPLE_TARGET = 30

SIGNAL_ORDER = [
    "S3_repeat_user_turn",
    "S6_assistant_self_flagged_failure",
    "S5_quotes_assistant_text",
    "S4_negation_lead",
    "S2_tool_burst_no_checkpoint",
    "S1_interrupt_after_tool_call",
]

SIGNAL_LABEL = {
    "S1_interrupt_after_tool_call": "S1 interrupt after tool call",
    "S2_tool_burst_no_checkpoint": "S2 tool burst, no checkpoint",
    "S3_repeat_user_turn": "S3 near-duplicate user turn",
    "S4_negation_lead": "S4 user turn opens with a negation",
    "S5_quotes_assistant_text": "S5 user turn quotes the assistant",
    "S6_assistant_self_flagged_failure": "S6 assistant self-flags a failure",
}

# --- wording-dependent lists (only where the signal is defined by wording) ---
NEGATION_PREFIX_EN = (
    "no", "not", "never", "stop", "wrong", "nope", "incorrect",
    "don't", "dont", "doesn't", "doesnt", "didn't", "didnt", "isn't", "isnt",
)
NEGATION_PREFIX_CJK = ("不", "别", "没", "否", "非", "毋")

SELF_FLAG_PHRASES = (
    "抱歉", "我理解错了", "我错了", "我说错了", "对不起", "是我错了",
    "sorry", "my mistake", "my bad", "apologies", "i was wrong",
    "you're right, i", "i misread", "i misunderstood",
)

# --- redaction --------------------------------------------------------------
ABS_PATH_RE = re.compile(r"(?:/home|/Users|/root|/mnt/[a-z])/[^\s\"'`)\]}>]*")
WIN_PATH_RE = re.compile(r"\b[A-Za-z]:\\Users\\[^\s\"'`)\]}>]*")
URL_RE = re.compile(r"(?:https?|ftp)://[^\s\"'`<>\])]*")
EMAIL_RE = re.compile(r"[\w.+-]+@(?:[\w-]+\.)+[A-Za-z]{2,}")
TOKEN_RES = [
    re.compile(r"sk-(?:[a-z]+-)?[A-Za-z0-9]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]
CREDENTIAL_RE = re.compile(
    r"(?i)\b(api[_-]?key|apikey|secret|token|password|passwd|pwd|access[_-]?key)\b"
    r"\s*[:=]\s*[\"']?[A-Za-z0-9_\-/+]{12,}"
)
HEX_BLOB_RE = re.compile(r"\b[A-Fa-f0-9]{32,}\b")
B64_BLOB_RE = re.compile(r"\b[A-Za-z0-9+/]{44,}={0,2}")

# A window containing any of these is dropped outright, not redacted.
RISK_RES = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"sk-(?:[a-z]+-)?[A-Za-z0-9]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{16,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,}"),
    re.compile(
        r"(?i)\b(api[_-]?key|apikey|secret|password|passwd|access[_-]?key)\b"
        r"\s*[:=]\s*[\"']?[A-Za-z0-9_\-/+]{20,}"
    ),
]

INJECTED_TAG_RE = re.compile(r"^\s*<(skill|system|system-reminder|project|instructions?)\b")


def redact(text):
    text = ABS_PATH_RE.sub("<PATH>", text)
    text = WIN_PATH_RE.sub("<PATH>", text)
    text = URL_RE.sub(lambda m: "<URL_WITH_QUERY>" if "?" in m.group(0) else "<URL>", text)
    text = EMAIL_RE.sub("<EMAIL>", text)
    for rx in TOKEN_RES:
        text = rx.sub("<TOKEN>", text)
    text = CREDENTIAL_RE.sub("<CREDENTIAL>", text)
    text = HEX_BLOB_RE.sub("<HEX>", text)
    text = B64_BLOB_RE.sub("<B64>", text)
    return text


def has_risk(text):
    return any(rx.search(text) for rx in RISK_RES)


def clamp(text, limit):
    """Truncate the middle, keep both ends, mark the cut, never exceed limit."""
    if len(text) <= limit:
        return text
    head = limit * 3 // 5
    tail = limit - head
    while head > 0 or tail > 0:
        cut = len(text) - head - tail
        out = f"{text[:head]}\n[... {cut} chars cut ...]\n{text[-tail:] if tail else ''}"
        if len(out) <= limit:
            return out
        if head >= tail:
            head -= 1
        else:
            tail -= 1
    return text[:limit]


# --- parsing ----------------------------------------------------------------
def iter_records(path):
    try:
        with open(path, "r", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


def text_of(content):
    if isinstance(content, str):
        return content
    out = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            out.append(block.get("text") or "")
    return "\n".join(out)


def normalise(text):
    text = text.replace("\u3000", " ")
    text = re.sub(r"[`*_>#]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


class Turn:
    """A display turn: one user message, or one narrated batch of assistant work.

    An assistant turn ends where the next user message starts, or where the
    assistant stops to write user-facing text, so a turn stays readable and a
    window of two to four turns stays a minimal fragment. Every turn carries
    the segment it belongs to; a segment is the whole user-to-user span and is
    what the burst signals are computed on.
    """

    __slots__ = ("kind", "start", "end", "text", "texts", "tool_calls", "results",
                 "steps", "segment", "injected", "mid")

    def __init__(self, kind, start, segment, mid=None):
        self.kind = kind          # "user" | "assistant"
        self.start = start
        self.end = start
        self.segment = segment
        self.mid = mid
        self.text = ""
        self.texts = []           # [(record index, text)] for assistant text blocks
        self.tool_calls = []
        self.results = []
        self.steps = []           # ("text"|"call"|"result", payload[, args])
        self.injected = False

    @property
    def last_step(self):
        return self.steps[-1][0] if self.steps else None


def build_turns(path):
    """Collapse message records into display turns and segments.

    Returns (turns, segments, record_count) where segments is a list of turn
    index ranges, one per user-to-user span.
    """
    turns = []
    segments = []
    idx = -1
    current = None
    for rec in iter_records(path):
        if rec.get("type") != "message":
            continue
        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role not in ("user", "assistant", "toolResult"):
            continue
        idx += 1
        content = msg.get("content")
        blocks = content if isinstance(content, list) else []
        if role == "user":
            turn = Turn("user", idx, len(segments), rec.get("id"))
            turn.text = text_of(content)
            turns.append(turn)
            segments.append([len(turns) - 1, len(turns) - 1])
            current = None
            continue
        if not segments:
            continue   # work before the first user message belongs to no situation
        if role == "assistant":
            has_text = any(isinstance(b, dict) and b.get("type") == "text"
                           and (b.get("text") or "").strip() for b in blocks)
            if current is None or (has_text and current.steps):
                current = Turn("assistant", idx, len(segments) - 1)
                turns.append(current)
                segments[-1][1] = len(turns) - 1
        elif current is None:
            current = Turn("assistant", idx, len(segments) - 1)
            turns.append(current)
            segments[-1][1] = len(turns) - 1
        turn = current
        turn.end = idx
        segments[-1][1] = len(turns) - 1
        if role == "toolResult":
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text = block.get("text") or ""
                    turn.results.append(text)
                    turn.steps.append(("result", text))
                elif block.get("type") == "image":
                    turn.results.append("<image>")
                    turn.steps.append(("result", "<image>"))
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text":
                text = block.get("text") or ""
                turn.text += ("\n" if turn.text else "") + text
                turn.texts.append((idx, text))
                turn.steps.append(("text", text))
            elif kind == "toolCall":
                args = json.dumps(block.get("arguments") or block.get("input") or {},
                                  ensure_ascii=False, sort_keys=True)
                turn.tool_calls.append((block.get("name") or "?", args))
                turn.steps.append(("call", block.get("name") or "?", args))
    return turns, segments, idx + 1


# --- corpus selection -------------------------------------------------------
def corpus_files():
    """Interactive session files: bucket-root sessions and their forks.

    Excluded, with reasons recorded in report.md: nested subagent runs
    (<session>/<run>/run-0/session.jsonl) and subagent-artifacts transcripts.
    """
    roots, forks, nested, transcripts = [], [], 0, 0
    for path in sorted(CORPUS.rglob("*.jsonl")):
        rel = path.relative_to(CORPUS).as_posix()
        name = path.name
        if name.endswith("_transcript.jsonl"):
            transcripts += 1
        elif name == "session.jsonl":
            nested += 1
        elif "/forks/" in rel:
            forks.append((rel, path))
        else:
            roots.append((rel, path))
    order = sorted(roots) + sorted(forks)
    shapes = {
        "included_root_sessions": len(roots),
        "included_fork_sessions": len(forks),
        "excluded_nested_subagent_runs": nested,
        "excluded_subagent_transcripts": transcripts,
    }
    return order, shapes


def corpus_digest(files):
    """One hash over (relative path, byte size): binds the counts to a snapshot."""
    digest = hashlib.sha1()
    total = 0
    for rel, path in files:
        size = path.stat().st_size
        total += size
        digest.update(f"{rel}\t{size}\n".encode("utf-8"))
    return digest.hexdigest()[:16], total


def project_of(rel):
    return rel.split("/")[0]


def cwd_of(path):
    for rec in iter_records(path):
        if rec.get("type") == "session":
            return rec.get("cwd") or ""
    return ""


# --- signal detection -------------------------------------------------------
def shingles(text):
    s = re.sub(r"[\s\u3000]+", "", text)
    if len(s) < 4:
        return set()
    return {s[i:i + 4] for i in range(len(s) - 3)}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def negation_lead(text):
    head = text.lstrip(" \t\"'([{，。！？,.:：——“")
    low = head.lower()
    if head[:1] in NEGATION_PREFIX_CJK:
        return True
    for word in NEGATION_PREFIX_EN:
        if low.startswith(word):
            rest = low[len(word):len(word) + 1]
            if not rest or not rest.isalpha():
                return True
    return False


def quotes_assistant(user_text, assistant_text):
    if len(user_text) < QUOTE_MIN_CHARS:
        return False
    hay = re.sub(r"\s+", " ", assistant_text)
    needle = re.sub(r"\s+", " ", user_text)
    for start in range(0, len(needle) - QUOTE_MIN_CHARS + 1, 10):
        span = needle[start:start + QUOTE_MIN_CHARS]
        if span.strip() and span in hay:
            return True
    return False


def self_flagged(assistant_text):
    low = assistant_text.lower()
    return any(p in low for p in SELF_FLAG_PHRASES)


# --- windows ----------------------------------------------------------------
def render_window(surface, turns):
    lines = [f"[tool surface: {', '.join(surface) if surface else '(none observed)'}]"]
    cursor = turns[0].start
    for turn in turns:
        if turn.start > cursor:
            lines.append(f"[... records {cursor}-{turn.start - 1} omitted ...]")
        if turn.kind == "user":
            if turn.injected:
                lines.append(f"[{turn.start}] USER: (harness message, body omitted)")
            else:
                lines.append(f"[{turn.start}] USER: {clamp(redact(turn.text.strip()), 1200)}")
            cursor = turn.end + 1
            continue
        lines.append(f"[{turn.start}-{turn.end}] ASSISTANT "
                     f"({len(turn.tool_calls)} tool calls)")
        steps = turn.steps
        omitted = len(steps) - STEP_HEAD - STEP_TAIL
        shown = steps if omitted <= 0 else steps[:STEP_HEAD] + [None] + steps[-STEP_TAIL:]
        # redact before clamping so a cut can never leave half a credential behind
        for step in shown:
            if step is None:
                lines.append(f"    ... {omitted} steps omitted ...")
            elif step[0] == "text":
                body = redact(step[1].strip())
                if body:
                    lines.append(f"    text: {clamp(body, 400)}")
            elif step[0] == "call":
                lines.append(f"    call {step[1]}({clamp(redact(step[2]), 120)})")
            else:
                body = redact(step[1].strip())
                if body:
                    lines.append(f"    result: {clamp(body, 200)}")
        cursor = turn.end + 1
    # session text can carry trailing blanks; they only add diff noise
    return "\n".join(line.rstrip() for line in lines)


def window_parts(turns):
    """Every raw string that will be rendered into a window, before redaction."""
    for turn in turns:
        if turn.kind == "user":
            yield turn.text
            continue
        for step in turn.steps:
            yield step[1] if step[0] == "text" else (step[2] if step[0] == "call" else step[1])


def pick_window(turns, start_pos, end_pos, signal):
    """The last turns ending at the decision point, capped at WINDOW_MAX_TURNS.

    For a burst longer than the window the first turn of the burst is kept
    alongside the last ones so both ends of the burst stay visible.
    """
    span = turns[start_pos:end_pos + 1]
    if len(span) <= WINDOW_MAX_TURNS:
        return span
    if signal == "S2_tool_burst_no_checkpoint":
        return [span[0]] + span[-(WINDOW_MAX_TURNS - 1):]
    return span[-WINDOW_MAX_TURNS:]


def window_id(rel, start, end):
    digest = hashlib.sha1(f"{rel}:{start}:{end}".encode("utf-8")).hexdigest()[:12]
    return f"w-{digest}"


# --- pass 1: harness template census ---------------------------------------
def template_census(files):
    occurrences = {}
    projects = {}
    for rel, path in files:
        proj = project_of(rel)
        seen_here = set()
        for rec in iter_records(path):
            if rec.get("type") != "message":
                continue
            msg = rec.get("message")
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            text = normalise(text_of(msg.get("content")))
            if not text:
                continue
            occurrences[text] = occurrences.get(text, 0) + 1
            seen_here.add(text)
        for text in seen_here:
            projects.setdefault(text, set()).add(proj)
    templates = {
        text for text, count in occurrences.items()
        if count >= INJECTED_MIN_OCCURRENCES
        and len(projects.get(text, ())) >= INJECTED_MIN_PROJECTS
    }
    return templates, len(occurrences)


def main():
    started = time.time()
    files, shapes = corpus_files()
    corpus_hash, corpus_bytes = corpus_digest(files)
    templates, distinct_user_texts = template_census(files)

    counters = {
        "raw_user_turns": 0,
        "injected_template_turns": 0,
        "injected_tag_turns": 0,
        "empty_user_turns": 0,
        "duplicate_fork_turns": 0,
        "human_user_turns": 0,
        "assistant_turns": 0,
        "tool_calls": 0,
        "candidates": 0,
        "dropped_for_risk": 0,
        "s1_loose_user_turns": 0,
    }
    per_signal_primary = {s: 0 for s in SIGNAL_ORDER}
    per_signal_any = {s: 0 for s in SIGNAL_ORDER}
    per_signal_projects = {s: set() for s in SIGNAL_ORDER}
    project_cwds = {}

    seen_user_ids = set()   # (project, message id): a fork copies its parent's turns
    candidates = []
    sample_pool = {s: [] for s in SIGNAL_ORDER}

    for rel, path in files:
        proj = project_of(rel)
        cwd = cwd_of(path)
        project_cwds.setdefault(proj, cwd)
        turns, segments, _ = build_turns(path)
        if not turns:
            continue

        user_turns = [t for t in turns if t.kind == "user"]
        counters["raw_user_turns"] += len(user_turns)
        for turn in user_turns:
            text = turn.text
            if not text.strip():
                counters["empty_user_turns"] += 1
                turn.injected = True
            elif normalise(text) in templates:
                counters["injected_template_turns"] += 1
                turn.injected = True
            elif INJECTED_TAG_RE.match(text):
                counters["injected_tag_turns"] += 1
                turn.injected = True

        human_turns = []
        for turn in user_turns:
            if turn.injected:
                continue
            key = (proj, turn.mid or f"{rel}:{turn.start}")
            if key in seen_user_ids:
                counters["duplicate_fork_turns"] += 1
                continue
            seen_user_ids.add(key)
            human_turns.append(turn)
        counters["human_user_turns"] += len(human_turns)
        counters["assistant_turns"] += sum(1 for t in turns if t.kind == "assistant")
        counters["tool_calls"] += sum(len(t.tool_calls) for t in turns if t.kind == "assistant")

        surface = sorted({name for t in turns if t.kind == "assistant"
                          for name, _ in t.tool_calls})

        seg_calls = {}
        seg_report = {}
        for turn in turns:
            if turn.kind != "assistant":
                continue
            seg_calls[turn.segment] = seg_calls.get(turn.segment, 0) + len(turn.tool_calls)
            seg_report[turn.segment] = max(seg_report.get(turn.segment, 0),
                                           len(turn.text.strip()))

        pos_of = {id(t): i for i, t in enumerate(turns)}
        windows = {}   # (start record, end record) -> set of signal ids
        spans = {}

        def add(anchor_pos, start_pos, signals):
            span = pick_window(turns, start_pos, anchor_pos, min(signals, key=SIGNAL_ORDER.index))
            key = (span[0].start, span[-1].end)
            spans.setdefault(key, span)
            windows.setdefault(key, set()).update(signals)

        prev_human_shingles = []
        for turn in human_turns:
            pos = pos_of[id(turn)]
            if pos == 0:
                prev_human_shingles = [shingles(turn.text)]
                continue
            prev = turns[pos - 1]
            prev_segment = turn.segment - 1
            fired = []

            if seg_calls.get(prev_segment, 0) >= 1:
                counters["s1_loose_user_turns"] += 1

            # S1: user speaks while the assistant's last act was a tool call
            if prev.kind == "assistant" and prev.last_step == "result":
                fired.append("S1_interrupt_after_tool_call")

            # S2: long tool burst with no user-facing checkpoint
            if (prev_segment >= 0
                    and seg_calls.get(prev_segment, 0) >= BURST_MIN_TOOL_CALLS
                    and seg_report.get(prev_segment, 0) < BURST_CHECKPOINT_CHARS):
                fired.append("S2_tool_burst_no_checkpoint")

            # S3: near-duplicate of an earlier user turn
            if len(normalise(turn.text)) >= REPEAT_MIN_CHARS:
                current = shingles(turn.text)
                for earlier in prev_human_shingles[-REPEAT_LOOKBACK:]:
                    if jaccard(current, earlier) >= REPEAT_JACCARD:
                        fired.append("S3_repeat_user_turn")
                        break

            # S4: opens with a negation
            if negation_lead(turn.text):
                fired.append("S4_negation_lead")

            # S5: quotes text the assistant produced, within the last few turns
            for back in range(1, 4):
                if pos - back < 0:
                    break
                earlier = turns[pos - back]
                if earlier.kind != "assistant" or not earlier.text.strip():
                    continue
                if quotes_assistant(turn.text, earlier.text):
                    fired.append("S5_quotes_assistant_text")
                    break

            prev_human_shingles.append(shingles(turn.text))
            if fired:
                start_pos = segments[prev_segment][0] if prev_segment >= 0 else pos
                add(pos, start_pos, fired)

        # S6: the assistant flags its own failure in a segment that used tools
        for turn in turns:
            if (turn.kind == "assistant" and seg_calls.get(turn.segment, 0) >= 1
                    and self_flagged(turn.text)):
                add(pos_of[id(turn)], segments[turn.segment][0],
                    ["S6_assistant_self_flagged_failure"])

        for key in sorted(windows):
            fired = tuple(sorted(windows[key], key=SIGNAL_ORDER.index))
            primary = fired[0]
            span = spans[key]
            if any(has_risk(part) for part in window_parts(span) if part):
                counters["dropped_for_risk"] += 1
                continue
            text = clamp(redact(render_window(surface, span)), WINDOW_MAX_CHARS)
            start, end = key
            record = {
                "window_id": window_id(rel, start, end),
                "session": rel,
                "turn_indices": [start, end],
                "signals": list(fired),
                "text": text,
            }
            candidates.append(record)
            counters["candidates"] += 1
            per_signal_primary[primary] += 1
            for signal in fired:
                per_signal_any[signal] += 1
                per_signal_projects[signal].add(proj)
                sample_pool[signal].append((proj, rel, record))

    candidates.sort(key=lambda r: r["window_id"])
    with open(OUT_DIR / "candidates.jsonl", "w", encoding="utf-8") as fh:
        for record in candidates:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    sample = choose_sample(sample_pool)
    write_sample(sample)
    runtime = time.time() - started
    write_report(shapes, counters, per_signal_primary, per_signal_any,
                 per_signal_projects, project_cwds, sample, runtime,
                 len(templates), distinct_user_texts, corpus_hash, corpus_bytes)

    print_summary(shapes, counters, per_signal_primary, per_signal_any,
                  per_signal_projects, runtime, corpus_hash)
    return 0


# --- sampling ---------------------------------------------------------------
def choose_sample(sample_pool):
    """Round-robin across signals, one window per project per signal.

    Deterministic: within a signal the pool is sorted by (project, session,
    window id), so the chosen windows do not depend on filesystem order.
    """
    ordered = {}
    for signal in SIGNAL_ORDER:
        seen_projects = set()
        picked = []
        for proj, rel, record in sorted(sample_pool[signal],
                                        key=lambda r: (r[0], r[1], r[2]["window_id"])):
            if proj in seen_projects:
                continue
            seen_projects.add(proj)
            picked.append((proj, signal, record))
        ordered[signal] = picked

    quota = max(1, SAMPLE_TARGET // len(SIGNAL_ORDER))
    sample = []
    taken = set()
    for signal in SIGNAL_ORDER:
        for item in ordered[signal][:quota]:
            sample.append(item)
            taken.add(item[2]["window_id"])
    # top up, and shrink if the quota overflowed, in signal order
    if len(sample) > SAMPLE_TARGET:
        sample = sample[:SAMPLE_TARGET]
    if len(sample) < SAMPLE_TARGET:
        for signal in SIGNAL_ORDER:
            for item in ordered[signal][quota:]:
                if len(sample) >= SAMPLE_TARGET:
                    break
                if item[2]["window_id"] in taken:
                    continue
                sample.append(item)
                taken.add(item[2]["window_id"])
    return sample


def write_sample(sample):
    lines = [
        "# 候选处境样本 30 条",
        "",
        "类型：工作记录。所有者：主代理。上游：[扫描脚本](scan.py)、[报告](report.md)。",
        "",
        "选样规则：按信号分层，每个信号最多取 5 条，同一信号内每个项目最多取 1 条，"
        "组内按（项目，会话文件，窗口 id）排序后取前几条，六组轮转拼满 30 条。"
        "不是前 30 条，也不是随机 30 条。窗口正文先按 scan.py 的规则脱敏，"
        "再截到 900 字符（中间截断，两端保留）。",
        "",
    ]
    for i, (proj, signal, record) in enumerate(sample, 1):
        lines.append(f"## {i}. {SIGNAL_LABEL[signal]}")
        lines.append("")
        lines.append(f"- 项目：`{proj}`")
        lines.append(f"- 窗口：`{record['window_id']}`，消息序号 `{record['turn_indices'][0]}–{record['turn_indices'][1]}`")
        lines.append(f"- 信号：{', '.join(record['signals'])}")
        lines.append("")
        lines.append("```text")
        lines.append(clamp(record["text"], SAMPLE_WINDOW_CHARS))
        lines.append("```")
        lines.append("")
    (OUT_DIR / "sample-30.md").write_text("\n".join(lines), encoding="utf-8")


# --- report -----------------------------------------------------------------
def write_report(shapes, counters, per_primary, per_any, per_projects,
                 project_cwds, sample, runtime, template_count, distinct_texts,
                 corpus_hash, corpus_bytes):
    files_scanned = shapes["included_root_sessions"] + shapes["included_fork_sessions"]
    total_files = files_scanned + shapes["excluded_nested_subagent_runs"] + \
        shapes["excluded_subagent_transcripts"]
    human = counters["human_user_turns"]
    primary_sum = sum(per_primary.values())
    precedence = " > ".join(s.split("_")[0] for s in SIGNAL_ORDER)
    loose = 100.0 * counters["s1_loose_user_turns"] / human if human else 0.0

    rows = ["| 信号 | 扫描文件 | 命中（主信号） | 命中（任一信号） | 每 100 条用户轮 | 覆盖项目数 |",
            "|---|---|---|---|---|---|"]
    for signal in SIGNAL_ORDER:
        share = 100.0 * per_any[signal] / human if human else 0.0
        rows.append(
            f"| {SIGNAL_LABEL[signal]} (`{signal}`) | {files_scanned} | {per_primary[signal]} "
            f"| {per_any[signal]} | {share:.1f} | {len(per_projects[signal])} |"
        )
    rows.append(f"| **合计** | {files_scanned} | **{primary_sum}** | — | — | — |")

    lines = [
        "# 结构信号粗筛报告",
        "",
        "类型：工作记录。所有者：主代理。上游：[实验规格](../docs/method/spec.md) §2.4 真实会话切片、§2.5 粗筛细筛差集。",
        "",
        "这份报告只报结构信号的基数（base rate），不做内容判定，也不建纠正措辞词表（S6 与 S4 例外，见 §4）。"
        "产物：`candidates.jsonl`（每条一个窗口）、`sample-30.md`（30 条人读样本）、`check_redaction.py`（脱敏门）。",
        "",
        "## 1 语料",
        "",
        "语料根：`~/.pi/agent/sessions`。目录下共 "
        f"{total_files} 个 JSONL 文件、约 4.8 GB，按 cwd 目录分桶。文件分四种形态，本轮只扫描其中两种：",
        "",
        "| 形态 | 文件数 | 是否扫描 | 理由 |",
        "|---|---|---|---|",
        f"| 桶根会话 `--bucket--/<ts>_<id>.jsonl` | {shapes['included_root_sessions']} | 是 | 真实交互会话，人在这儿说话 |",
        f"| 会话分叉 `--bucket--/<id>/forks/*.jsonl` | {shapes['included_fork_sessions']} | 是 | 同一会话的中途分叉，含主文件没有的尾部 |",
        f"| 子代理运行 `<id>/<run>/run-0/session.jsonl` | {shapes['excluded_nested_subagent_runs']} | 否 | 子代理运行，唯一一条 user 轮是派发提示，不会出现人的纠正 |",
        f"| 子代理转录 `subagent-artifacts/*_transcript.jsonl` | {shapes['excluded_subagent_transcripts']} | 否 | 同上，且记录 schema 不同 |",
        "",
        f"扫描 {files_scanned} 个文件、{corpus_bytes / 2**20:.0f} MiB，覆盖 {len(project_cwds)} 个项目桶。"
        f"语料快照摘要 `{corpus_hash}`（对每个文件路径与字节数取 sha1）：计数绑定这个快照，"
        "语料仍在被写，摘要变了则两次运行的计数本来就不该相同。",
        "",
        f"分叉文件复制了主文件的历史，因此用户轮按（项目，消息 id）去重，共跳过 {counters['duplicate_fork_turns']} 条重复轮，"
        "分叉独有的尾部照常计入。",
        "",
        "## 2 用户轮记账",
        "",
        "| 项 | 条数 |",
        "|---|---|",
        f"| 原始 user 轮 | {counters['raw_user_turns']} |",
        f"| 其中：harness 模板注入 | {counters['injected_template_turns']} |",
        f"| 其中：技能/系统标签块 | {counters['injected_tag_turns']} |",
        f"| 其中：空正文 | {counters['empty_user_turns']} |",
        f"| 其中：分叉重复 | {counters['duplicate_fork_turns']} |",
        f"| **人写的用户轮（下文的分母）** | **{human}** |",
        f"| 助手展示轮 | {counters['assistant_turns']} |",
        f"| 工具调用 | {counters['tool_calls']} |",
        "",
        "harness 注入不靠词表识别：一条 user 轮正文在语料中出现 ≥"
        f"{INJECTED_MIN_OCCURRENCES} 次且横跨 ≥{INJECTED_MIN_PROJECTS} 个项目桶即判为机器模板"
        f"（本轮 {template_count} 个模板、{counters['injected_template_turns']} 条轮），"
        "外加正文以 `<skill`/`<system` 等标签开头的结构规则。"
        f"原始 user 轮里有 {counters['injected_template_turns'] + counters['injected_tag_turns']} 条不是人写的；"
        "不剔除的话 S1 与 S3 会被注入文本刷满，基数失真。剔除后语料里有 "
        f"{distinct_texts} 种不同的用户轮正文。",
        "",
        "## 3 计数",
        "",
        f"分母是上面 {human} 条人写的用户轮。一个窗口可以命中多个信号：`主信号` 每窗口只记一次，其和等于候选总数"
        f"（{primary_sum}）；`任一信号` 允许重叠，故大于候选数。主信号按固定优先级取（{precedence}，越靠前越具体），"
        "即 `candidates.jsonl` 里 `signals` 的第一项。",
        "",
        *rows,
        "",
        f"候选窗口 {counters['candidates']} 条；因疑似密钥丢弃 {counters['dropped_for_risk']} 条（`dropped_for_risk`）。"
        f"主信号合计与候选数一致：{primary_sum} = {counters['candidates']}。",
        "",
        "**一个信号几乎对一切都成立。** 把 S1 读成「用户轮出现在任何用过工具的片段之后」，"
        f"它就命中 {counters['s1_loose_user_turns']} 条用户轮、占 {loose:.1f}%——在 agent 会话里「刚用过工具」几乎是常态，"
        "这个读法不能区分任何东西，只能当上界。所以本轮的 S1 取严格读法：用户发话前，助手在这条工具结果之后没有写过任何文本，"
        f"占 {100.0 * per_any['S1_interrupt_after_tool_call'] / human:.1f}%。同一件事的两种读法差 7 倍，"
        "这是关于信号本身的发现，不是关于语料的。",
        "",
        "## 4 信号定义与它实际测到什么",
        "",
        "窗口按「说话轮」切：一条 user 消息是一轮，助手侧在它写出面向用户的文本处断成新的一轮，"
        "所以一轮是「一段被叙述过的工作」，而不是整段 user 到 user 的跨度。跨度另算，叫片段（segment），"
        "S2 与 S6 在片段上算。窗口取决策点所在片段起点起的最后 2–4 轮；一轮里的步骤只保留开头 "
        f"{STEP_HEAD} 步和结尾 {STEP_TAIL} 步，中间标 `... N steps omitted ...`；被丢掉的轮标 "
        "`[... records X-Y omitted ...]`；整个窗口超过 4000 字符则中间截断、两端保留。",
        "",
        "| 信号 | 结构判据（阈值在 `scan.py` 顶部） | 它比名义定义少测了什么 |",
        "|---|---|---|",
        "| S1 工具调用后立刻发话 | 前一轮助手工作以工具结果结尾，用户接着发话 | 「没给新任务」判不了；含正常汇报后的追问 |",
        "| S2 连续工具调用无检查点 | 前一片段 ≥8 次工具调用，且片段内没有任何 ≥120 字符的助手段落 | 「长」不等于「人被迫介入」；8 与 120 都是取值，未校准 |",
        "| S3 近乎重复同一条指令 | 与前 4 条用户轮之一的字符 4-gram Jaccard ≥0.60，正文 ≥12 字符 | 只认字面重复；换说法重复（「我是说…」）漏检，是下界 |",
        "| S4 用户轮以否定词开头 | 首个 token 是否定词（中英各一小组，语法用词，不是纠正词表） | 「不错」与「不是呀」同族；否定开头不等于纠正 |",
        "| S5 引用助手原文 | 用户轮里有 ≥30 字符片段逐字出现在前 3 轮助手文本里 | 引用被测到，「再纠正」没被验证 |",
        "| S6 助手自陈失败 | 助手轮文本含道歉/认错措辞，且所在片段用过工具 | 唯一依赖措辞的信号；不道歉的失败全漏，是下界 |",
        "",
        "## 5 判为不可靠或不可检出的部分",
        "",
        "- **「没给新任务」（S1 的后半句）**：需要语义判断，结构信号做不到。S1 因此是上界。",
        "- **换说法重复（S3 的漏检面）**：字符 4-gram 只覆盖同义复述的一部分；本轮不做 embedding，不估计漏检量。",
        "- **失败但不道歉（S6 的漏检面）**：不做语义判定，无法估计；要等下一轮读样本。",
        "- **助手是否真的错了**：六个信号都不判对错，只定位「可能是一个决策点」。本轮只产基数，这是刻意的。",
        "- **工具 schema 原文**：会话日志里没有工具定义记录，只有工具调用名。窗口里的 `tool surface` 是"
        "本会话实际用过的工具名集合，不是模型当时看到的 schema；补齐需要宿主的工具注册表，不在本轮范围。",
        "- **否定词的跨语言边界**：否定词表是手写的语法小表，只覆盖中英，法语、日语等全漏。",
        "",
        "## 6 样本 30 条的选样方法",
        "",
        "分层：按信号分组，每组最多 5 条；同组内每个项目最多 1 条，按（项目，会话文件，窗口 id）排序后取前几条；"
        "六组轮转拼满 30 条，不足则按信号顺序补，超出则截尾。所以样本不是前 30 条，也不依赖文件系统顺序。"
        f"实际取到 {len(sample)} 条，每条正文截到 {SAMPLE_WINDOW_CHARS} 字符。",
        "",
        "## 7 脱敏",
        "",
        "窗口正文写入前替换：家目录与其它绝对路径、URL（带查询串的单独标注）、邮箱地址、"
        "各家 API key 前缀、GitHub 令牌前缀、云厂商访问键、聊天平台令牌、JWT、私钥块、"
        "`key: value` 形态的凭据、≥32 位十六进制串、≥44 字节 base64 串。"
        "含私钥块或高置信凭据形态的窗口不入库，直接丢弃并计入 `dropped_for_risk`——本轮真实丢掉了 "
        f"{counters['dropped_for_risk']} 条，里面确实有配置文件里抄出来的 API key 与 GitHub 令牌，不是理论风险。"
        "先脱敏再截断，免得截断把凭据切成两半、留下认不出的后一半。"
        "`check_redaction.py` 解码 JSONL 后逐字段扫描三个产物，命中即非零退出。原始会话不进仓库。",
        "",
        "## 8 运行",
        "",
        "- 命令：`python3 mining/scan.py`（本地、无网络；两遍读语料，第一遍为 harness 模板普查）",
        f"- 本次耗时：{runtime:.1f} 秒。这一行每次会变，上面的计数在语料快照不变时不变。",
        f"- 产物：`candidates.jsonl` {counters['candidates']} 行、`sample-30.md`、本报告",
        "",
        "## 9 下一步",
        "",
        "下一轮是细集：按 `candidates.jsonl` 抽样读 100 条，量这六个信号的精度，"
        "把验证过的模式留下，差集 D = C \\ F 另抽裁决。先导批要 40–100 条处境，"
        f"当前候选池 {counters['candidates']} 条足够，缺的是精度而不是数量。",
        "",
    ]
    (OUT_DIR / "report.md").write_text("\n".join(lines), encoding="utf-8")


def print_summary(shapes, counters, per_primary, per_any, per_projects, runtime,
                  corpus_hash):
    human = counters["human_user_turns"]
    print(f"corpus_digest {corpus_hash}")
    print(f"files_scanned {shapes['included_root_sessions'] + shapes['included_fork_sessions']}")
    print(f"human_user_turns {human}")
    print(f"assistant_turns {counters['assistant_turns']}")
    print(f"tool_calls {counters['tool_calls']}")
    print(f"candidates {counters['candidates']}")
    print(f"dropped_for_risk {counters['dropped_for_risk']}")
    print(f"{'signal':38s} {'primary':>7s} {'any':>7s} {'per100':>7s} {'projects':>8s}")
    for signal in SIGNAL_ORDER:
        share = 100.0 * per_any[signal] / human if human else 0.0
        print(f"{signal:38s} {per_primary[signal]:7d} {per_any[signal]:7d} "
              f"{share:7.1f} {len(per_projects[signal]):8d}")
    print(f"primary_sum {sum(per_primary.values())}")
    print(f"runtime_seconds {runtime:.1f}")


if __name__ == "__main__":
    sys.exit(main())
