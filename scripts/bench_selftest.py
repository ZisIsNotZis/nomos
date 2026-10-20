#!/usr/bin/env python3
"""No-GPU proof that the benchmark judging path is correct.

Two layers, because they fail differently:
  1. checker cases: hand-computed verdicts for the answer extractors and for every IFEval
     instruction checker, including the cases that must come out false;
  2. pipeline: scripts/run_bench.py driven by its fixed-output stub on the frozen items,
     so loading, scoring, aggregation and the interval are exercised without a GPU. A stub
     that emits the gold answers must score 1.0 and a stub that emits a wrong number must
     score 0.0; a stub that emits no number must be counted unscorable rather than wrong.

Writes evidence/benchmark/selftest.json.

Usage:
  python3 scripts/bench_selftest.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_suites  # noqa: E402
import run_bench  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "evidence/benchmark/selftest.json")


def check(name, got, want):
    ok = got == want
    assert ok, f"{name}: got {got!r}, want {want!r}"
    return {"case": name, "got": got, "want": want, "passed": True}


def extractor_cases():
    cases = []
    cases.append(check("gsm8k marker", bench_suites.gsm8k_number("so 3+4 = 7\n#### 7"), "7"))
    cases.append(check("gsm8k commas", bench_suites.gsm8k_number("#### 1,200"), "1200"))
    cases.append(check("gsm8k decimal", bench_suites.gsm8k_number("#### 0.50"), "0.5"))
    cases.append(check("gsm8k no marker", bench_suites.gsm8k_number("the answer is 12"), "12"))
    cases.append(check("gsm8k marker after prose",
                       bench_suites.gsm8k_number("steps... 5*3=15\n#### 15"), "15"))
    cases.append(check("gsm8k no number", bench_suites.gsm8k_number("not sure"), None))
    return cases


def _kw(**kwargs):
    return kwargs


def checker_cases():
    S = bench_suites
    cases = [
        ("no_comma true", S._no_comma("a b c", {}), True),
        ("no_comma false", S._no_comma("a, b", {}), False),
        ("lowercase true", S._lowercase("all small words", {}), True),
        ("lowercase false", S._lowercase("Small words", {}), False),
        ("capital true", S._capital("ALL BIG", {}), True),
        ("capital false", S._capital("All big", {}), False),
        ("existence true", S._existence("the cat sat", _kw(keywords=["cat", "sat"])), True),
        ("existence false", S._existence("the cat sat", _kw(keywords=["dog"])), False),
        ("forbidden true", S._forbidden("the cat sat", _kw(forbidden_words=["dog"])), True),
        ("forbidden false", S._forbidden("the dog sat", _kw(forbidden_words=["dog"])), False),
        ("frequency at least", S._frequency("a a a", _kw(keyword="a", frequency=3,
                                                        relation="at least")), True),
        ("frequency less than", S._frequency("a a a", _kw(keyword="a", frequency=3,
                                                          relation="less than")), False),
        ("words at least", S._number_words("one two three", _kw(relation="at least",
                                                               num_words=3)), True),
        ("words at least short", S._number_words("one two", _kw(relation="at least",
                                                               num_words=3)), False),
        ("paragraphs exact", S._number_paragraphs("a\n\nb", _kw(num_paragraphs=2)), True),
        ("paragraphs exact false", S._number_paragraphs("a\nb", _kw(num_paragraphs=2)), False),
        ("highlights", S._highlights("*x* and *y*", _kw(num_highlights=2)), True),
        ("highlights short", S._highlights("*x*", _kw(num_highlights=2)), False),
        ("title", S._title("<<My Title>>\nbody", {}), True),
        ("title absent", S._title("My Title", {}), False),
        ("json", S._json_format('{"a": 1}', {}), True),
        ("json broken", S._json_format("{a: 1", {}), False),
        ("placeholder", S._placeholders("[name] and [city]",
                                        _kw(num_placeholders=2)), True),
        ("end_checker", S._end_checker("text here. Thanks!", _kw(end_phrase="thanks!")), True),
        ("end_checker false", S._end_checker("thanks! more", _kw(end_phrase="thanks!")), False),
        ("quotation", S._quotation('"quoted"', {}), True),
        ("quotation false", S._quotation("quoted", {}), False),
        ("two_responses", S._two_responses("one\n******\ntwo", {}), True),
        ("two_responses false", S._two_responses("one", {}), False),
        ("empty output satisfies nothing",
         S.check_ifeval({"instruction_id_list": ["change_case:english_capital",
                                                "keywords:forbidden_words"],
                         "kwargs": [{}, {"forbidden_words": ["zzz"]}]}, "  "),
         [False, False]),
    ]
    out = []
    for name, got, want in cases:
        out.append(check(name, got, want))
    return out


class DictStub:
    """Outputs fixed by item id, so an IFEval expectation can be hand-computed."""

    def __init__(self, outputs, default=""):
        self.outputs = outputs
        self.default = default

    def generate(self, prompts, items, max_new_tokens):
        return [self.outputs.get(i["id"], self.default) for i in items]


def pipeline_cases():
    """Drive run_suite (prompt -> model -> score -> aggregate) with outputs we can predict."""
    results = []
    gsm = bench_suites.load_items("gsm8k", os.path.join(ROOT, "data/bench"))[:20]
    for stub, expect in (("gold", 1.0), ("wrong", 0.0), ("garbage", 0.0)):
        run = run_bench.run_suite("gsm8k", gsm, run_bench.StubModel(stub, "gsm8k", gsm), 0,
                                  bench_suites.MAX_NEW_TOKENS["gsm8k"])
        summary = run["summary"]
        low, high = summary["accuracy_ci95"]
        assert low is not None and 0.0 <= low <= high <= 1.0, summary
        assert summary["items"] == 20 and summary["accuracy"] == expect, (stub, summary)
        if stub == "garbage":
            # No number anywhere: unscorable, and never credited as correct.
            assert summary["unscorable"] == 20 and summary["correct"] == 0, summary
        results.append({"suite": "gsm8k", "stub": stub, "items": summary["items"],
                        "accuracy": summary["accuracy"],
                        "accuracy_ci95": [low, high], "unscorable": summary["unscorable"],
                        "expectation": f"accuracy {expect}, unscorable "
                                       f"{20 if stub == 'garbage' else 0}"})

    # Hand-computed IFEval items: every verdict below is derivable by reading the text.
    items = [
        {"id": "syn-pass",
         "instruction_id_list": ["punctuation:no_comma", "startend:end_checker"],
         "kwargs": [{}, {"end_phrase": "Thanks"}],
         "prompt": "Respond without commas and end with Thanks"},
        {"id": "syn-fail",
         "instruction_id_list": ["change_case:english_lowercase",
                                "detectable_format:number_highlighted_sections"],
         "kwargs": [{}, {"num_highlights": 2}],
         "prompt": "Answer in lower case with two highlighted sections"},
    ]
    outputs = {
        # no comma, ends with "Thanks" -> passes both instructions.
        "syn-pass": "use plain words and stop here. Thanks",
        # Two highlights but a capital letter -> the lower-case instruction fails.
        "syn-fail": "Here is *one* and *two*.",
    }
    run = run_bench.run_suite("ifeval", items, DictStub(outputs), 0,
                              bench_suites.MAX_NEW_TOKENS["ifeval"])
    summary = run["summary"]
    assert summary["items"] == 2 and summary["correct"] == 1, summary
    assert run["records"][0]["correct"] is True and run["records"][1]["correct"] is False
    assert summary["unscorable"] == 0, summary
    results.append({"suite": "ifeval", "stub": "hand-computed", "items": summary["items"],
                    "accuracy": summary["accuracy"],
                    "accuracy_ci95": list(summary["accuracy_ci95"]),
                    "unscorable": summary["unscorable"],
                    "expectation": "1 of 2 correct: syn-pass passes, syn-fail fails "
                                   "change_case:english_lowercase"})

    # The frozen items must run through the same path without a second code branch.
    frozen = bench_suites.load_items("ifeval", os.path.join(ROOT, "data/bench"))[:20]
    run = run_bench.run_suite("ifeval", frozen, DictStub({}), 0,
                              bench_suites.MAX_NEW_TOKENS["ifeval"])
    s = run["summary"]
    # An empty answer satisfies no instruction, so nothing is credited.
    expected = 0
    assert s["items"] == 20 and s["unscorable"] == 0, s
    assert s["correct"] == expected, (s, expected)
    results.append({"suite": "ifeval", "stub": "empty-output", "items": s["items"],
                    "accuracy": s["accuracy"], "accuracy_ci95": list(s["accuracy_ci95"]),
                    "unscorable": s["unscorable"],
                    "expectation": "an empty output satisfies no instruction, so 0 of 20"})
    return results


def main():
    extractors = extractor_cases()
    checkers = checker_cases()
    pipeline = pipeline_cases()
    report = {
        "what_this_proves": (
            "the scoring and aggregation code is correct and runs end to end on the frozen "
            "items with a fixed-output stub; it does not measure any model, and no real model "
            "was run, so headroom remains unmeasured"),
        "gpu_used": False,
        "instruction_types_checked": sorted(bench_suites.supported_instruction_types()),
        "extractor_cases": extractors,
        "checker_cases": checkers,
        "pipeline_runs": pipeline,
        "counts": {
            "extractor_cases": len(extractors),
            "checker_cases": len(checkers),
            "pipeline_runs": len(pipeline),
        },
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(json.dumps(report["counts"]))
    for row in pipeline:
        print(f"{row['suite']:7s} {row['stub']:8s} acc={row['accuracy']:.2f} "
              f"unscorable={row['unscorable']}")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
