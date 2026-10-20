#!/usr/bin/env python3
"""Shared pieces for probe 2: key check, DeepSeek call, published pricing."""

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
# The law lives in the workspace's agent-policy submodule; the run records under
# evidence/ pin the sha256 they actually used, so reruns against a newer law are honest.
AGENTS_MD = REPO.parent / "agent-policy" / "AGENTS.md"
ENDPOINT = "https://api.deepseek.com/v1/chat/completions"
MODEL = "deepseek-flash"  # exact id from GET /v1/models; operated with thinking disabled

# Published price, https://api-docs.deepseek.com/quick_start/pricing, read 2026-10-20.
# USD per 1M tokens. Off-peak is half of peak for this model.
PRICE = {
    "peak": {"cache_hit": 0.006, "cache_miss": 0.30, "output": 1.20},
    "off_peak": {"cache_hit": 0.003, "cache_miss": 0.15, "output": 0.60},
}
# open.er-api.com, 2026-10-20 00:02 UTC.
USD_CNY = 6.693661


def api_key():
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if len(key) < 20:
        raise SystemExit("DEEPSEEK_API_KEY missing or too short; refusing to run")
    return key


def is_peak(epoch):
    """Peak: 01:00-04:00 and 06:00-10:00 UTC, Monday-Friday (holidays ignored)."""
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


def post(body, retries=3):
    key = api_key()
    payload = json.dumps(body).encode()
    for attempt in range(retries):
        request = urllib.request.Request(
            ENDPOINT,
            data=payload,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
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


def record(call_id, phase, situation, arm, sample, temperature, prompt_text, answer, usage, created, latency, ok=True):
    cost = call_cost(usage, created) if usage else None
    row = {
        "call_id": call_id,
        "phase": phase,
        "situation": situation,
        "arm": arm,
        "sample": sample,
        "temperature": temperature,
        "model": MODEL,
        "thinking": "disabled",
        "request_chars": len(prompt_text),
        "request_sha256": hashlib.sha256(prompt_text.encode()).hexdigest()[:16],
        "created": created,
        "latency_s": round(latency, 2),
        "ok": ok,
        "response": answer,
        "usage": usage,
        "cost": cost,
    }
    return row


def append_rows(path, rows):
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
