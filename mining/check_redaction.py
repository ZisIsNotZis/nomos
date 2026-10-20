#!/usr/bin/env python3
"""Fail if a mining output carries an unredacted path, credential or URL.

Reads what a consumer reads: JSONL records are checked field by field on their
decoded text, Markdown line by line on the raw text. Checking the raw JSONL line
instead would read an escaped newline as a word character and report hits that
the decoded text does not contain.

The patterns themselves live in scan.py; scanning the scripts would only flag the
redactor. Exit 0 when clean, 1 on any hit.
"""

import json
import re
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
JSONL_TARGETS = ["candidates.jsonl"]
TEXT_TARGETS = ["sample-30.md", "report.md"]

PATTERNS = [
    ("absolute home path", re.compile(r"/home/")),
    ("windows home path", re.compile(r"[A-Za-z]:\\+Users\\+")),
    ("provider api key", re.compile(r"sk-(?:[a-z]+-)?[A-Za-z0-9]{16,}")),
    ("github token", re.compile(r"gh[pousr]_[A-Za-z0-9]{8,}")),
    ("github pat", re.compile(r"github_pat_[A-Za-z0-9_]{8,}")),
    ("aws access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{8,}")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}")),
    ("email address", re.compile(r"[\w.+-]+@(?:[\w-]+\.)+[A-Za-z]{2,}")),
    ("url with query string", re.compile(r"https?://[^\s\"'<>]*\?[^\s\"'<>]*")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]


def scan_string(text):
    for label, pattern in PATTERNS:
        for match in pattern.finditer(text):
            yield label, match.group(0)


def main():
    failures = 0
    checked = 0
    for name in JSONL_TARGETS + TEXT_TARGETS:
        path = OUT_DIR / name
        if not path.exists():
            print(f"missing: {name}", file=sys.stderr)
            failures += 1
            continue
        checked += 1
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for lineno, line in enumerate(fh, 1):
                if name.endswith(".jsonl"):
                    try:
                        record = json.loads(line)
                    except ValueError:
                        print(f"{name}:{lineno}: unparsable JSON line", file=sys.stderr)
                        failures += 1
                        continue
                    fields = [(k, v) for k, v in record.items() if isinstance(v, str)]
                    fields += [(k, item) for k, v in record.items()
                               if isinstance(v, list) for item in v
                               if isinstance(item, str)]
                else:
                    fields = [("line", line)]
                for field, value in fields:
                    for label, hit in scan_string(value):
                        failures += 1
                        print(f"{name}:{lineno}:{field}: {label}: {hit[:80]!r}",
                              file=sys.stderr)
    if failures:
        print(f"FAIL: {failures} hit(s) across {checked} file(s)", file=sys.stderr)
        return 1
    print(f"OK: {checked} file(s) clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
