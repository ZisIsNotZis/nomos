# RUN: recomputing the IFEval comparison on Google's official graders

Everything here runs on local CPU. No GPU, no model calls, no writes outside
`evidence/benchmark/official/`.

## What was run

```
cd /home/z/vibe/nomos
/usr/bin/time -f "WALL=%e" /home/z/.local/bin/uv run --no-project \
  --with nltk --with langdetect --with immutabledict --with absl-py \
  python3 evidence/benchmark/official/grade_official.py
```

- wall clock: **6.62 s** for the run that produced the current `official-ifeval.json`
  (`/usr/bin/time -f "WALL=%e"`); an earlier run of the same command measured 6.45 s, and
  the run was executed 8 times end to end in this session with every timed one under 7 s.
- `uv` 0.12.13 at `/home/z/.local/bin/uv`; the ephemeral environment resolved
  nltk 3.10.3, langdetect 1.0.9, immutabledict and absl-py from PyPI into
  `~/.cache/uv` and touched nothing in the repo or the shared venv. `--no-project` is
  explicit because this repo has no `pyproject.toml` and the run must not pick up a
  project root by accident.
- exit 0; writes `evidence/benchmark/official/official-ifeval.json`.

### Timing, and what a first run on a clean machine sees

The wall-clock bullet above is a warm-cache measurement on an otherwise idle host. A
reader whose `uv` cache is empty also pays for building the environment, so the number to
quote for a first run comes from an empty cache. Measured on 2026-10-21 in an extracted
copy of the tree at `cf1a466` (`git archive` into `/tmp`, so nothing in the project is
written):

```
cd <extracted copy>
UV_CACHE_DIR=/tmp/uvcold /usr/bin/time -f "WALL=%e" /home/z/.local/bin/uv run --no-project \
  --with nltk --with langdetect --with immutabledict --with absl-py \
  python3 evidence/benchmark/official/grade_official.py
```

| condition | wall clock | artefact sha256 |
| --- | --- | --- |
| warm `uv` cache, 3 consecutive runs | 8.27 / 7.88 / 7.49 s | `01d94585…34c145`, all three |
| empty `UV_CACHE_DIR`, first run | 14.41 s | same |
| empty `UV_CACHE_DIR`, second run | 7.85 s | same |

Quote **7.5–8.3 s** for a warm run and **14–22 s** for a first run on an empty `uv` cache:
14.41 s here, and the independent review of `5ba9a2e` (2026-10-21, its own fresh copy)
measured 21.72 s on its first run, then 14.53 s and 11.83 s. Every run, cold or warm,
reproduces the committed artefact byte for byte. Do not quote a bound below 8 s as what a
reader will see: host load and cache state both move it.

Reading aid, same environment (read-only, prints every strict-ruler disagreement with its
full output so the hand-checks could be made by reading):

```
/home/z/.local/bin/uv run --no-project --with nltk --with langdetect --with immutabledict \
  --with absl-py python3 evidence/benchmark/official/dump_disagreements.py \
  > evidence/benchmark/official/work-disagreements.txt
```

`work-disagreements.txt` is a log, not evidence, and is not committed (the command above
rebuilds it): the numbers in `HANDCHECK.md` and in the
report are quoted from it and from `official-ifeval.json`, and the JSON is the artefact.

## Vendored official grader

- repo `google-research/google-research`, commit
  `e6890f85757dd84e27ca6df2dd30651dafad28e0`, directory `instruction_following_eval/`
- local path `evidence/benchmark/official/vendor/instruction_following_eval/`, unmodified
- per-file sha256 and URLs: `VENDOR.md`; re-hashed at run time into
  `official-ifeval.json` under `vendored.files`

| file | sha256 |
|---|---|
| `instructions.py` | `60e086f5342a03ce8e18b64bbcccf86308f523c08aa826707a562150a52f3edf` |
| `instructions_util.py` | `a73797261eee5bf447e279d82a2b700b1bdd3cb1193412dbab1270a85832bc6b` |
| `instructions_registry.py` | `ec92d72c264f6d906978613085db262356174300370a3fffe6fefd5969ce9cfc` |
| `evaluation_lib.py` | `35decc06000718487f44d7deafa6d3f48a8ec0886281edf40162c0265b7d248c` |
| `README.md` | `fef3c44408e4b39837af345095ccce7da798853fd60ea94a1de63afa9d3d67b3` |
| `requirements.txt` | `1b1716c9ac21b9cc2bd0d7354ed8f7b6982ccf35598529601a7c08508acec94a` |

## Determinism: the official ruler is not reproducible as shipped

`instructions.py` asks `langdetect` whether the response is English inside
`CapitalLettersEnglishChecker`, `LowercaseLettersEnglishChecker` and
`ResponseLanguageChecker`. `langdetect.DetectorFactory.seed` defaults to `None`, so the
detector draws from the global `random` state and the same input can be called English in
one process and Vietnamese in the next.

Observed, before pinning: two runs of `grade_official.py` disagreed on one adapter verdict
(160 vs 159 of 295 on the strict ruler, discordant drops 55 → 56).

Measured over **9 fresh unpinned processes** (each dumping the official strict verdict for
all 590 records, `/tmp/slots_dump.py`), exactly two slots varied:

| record | instruction | unpinned distribution | with `DetectorFactory.seed = 0` |
|---|---|---|---|
| `adapter` `ifeval-24` | `change_case:english_capital` | 4 runs False, 5 runs True | False (`detect` → `so`) |
| `base` `ifeval-218` | `change_case:english_lowercase` | 8 runs True, 1 run False | True |

A third slot moved between grade runs before pinning: `adapter` `ifeval-1843`
(`change_case:english_lowercase`, output `"luxurybeachhomes"`) was False in one unpinned
run and True with the seed pinned; 6 fresh-process `detect` calls on it all returned `en`,
so its flip rate is low and was not captured in the 9-run sample. The only thing these
three slots have in common is the `langdetect` call.

`grade_official.py` therefore pins `langdetect.DetectorFactory.seed = 0` and
`random.seed(0)` before any checker runs, and records the pin in
`official-ifeval.json` under `determinism`. No checker logic is changed: the pin is a
dependency's documented reproducibility switch.

With the pin, three consecutive runs produced byte-identical output:

```
52f58916502f6ff0a9d940c190d34015c4a386f921d7e8411b29958358eb33ae   (runs 1, 2, 3, before the
                                                                    determinism note was edited)
1b2c200653e5679f1988ef449f2de717171b0805b28bf1fc0fb11ff04542ee16   (two runs after)
```

No field in the JSON is a duration, so "re-running reproduces the same JSON" holds
byte-for-byte and not merely modulo timings.

After the landing move into `evidence/benchmark/official/` (2026-10-21) the runner derives its repo root by walking up to `data/bench/ifeval.jsonl`
and writes `vendored.local_path` relative to that root, so the artefact's hash changes in
that one field and nowhere else. Re-run after the move:

```
01d9458544c1773f7a8c06f9fb618c617ed2655e26b70f3341437b99834bc145   (post-move, 9.76 s)
```

A field-by-field diff against the pre-move artefact (`1b2c2006…`) has exactly one
difference, `vendored.local_path`; every count, interval, id list and seed is identical.
This file's own paths were rewritten by the same move.

## What the script asserts before it writes anything

1. `records[].id` of the base file, the adapter file and `data/bench/ifeval.jsonl` are the
   same list in the same order — a `SystemExit` otherwise.
2. Every id in every `instruction_id_list` exists in the official `INSTRUCTION_DICT` —
   otherwise the missing ids are listed and the run stops. (Zero missing.)
3. `scripts/bench_suites.check_ifeval` reproduces the stored `records[].correct` and
   `records[].per_instruction` on all 590 records — otherwise every mismatch is listed and
   the run stops without writing. (Zero mismatches; the JSON states this under
   `ours_ruler_check`.)
4. The recomputed drop/gain id lists equal `evidence/benchmark/paired-ifeval.json`'s.

## Reuse, not reimplementation

- official checkers: `evaluation_lib.test_instruction_following_strict` and
  `..._loose`, called as the official grader calls them (whole instruction list at once);
  on an exception the same official function is re-called on one-instruction inputs only to
  name the raising checker. 0 exceptions occurred.
- our ruler: `scripts/bench_suites.check_ifeval`, imported.
- interval: `scripts/resample_actions.bootstrap_diff`, 10 000 resamples, seed
  `SEED + 1 = 20261104` (the defaults `analyse_paired.py` uses by calling it without
  arguments).
- exact McNemar: `evidence/benchmark/analyse_paired.mcnemar_exact`, imported by path.
- Wilson interval: `scripts/bench_suites.wilson_interval`, imported.

## Files written

| path | what |
|---|---|
| `official-ifeval.json` | the artefact: every number in the report comes from here |
| `grade_official.py` | the runner |
| `dump_disagreements.py` | reading aid that prints each disagreement with its output |
| `work-disagreements.txt` | that program's log (not evidence; not committed, rebuild with the command above) |
| `VENDOR.md` | commit, URLs, per-file sha256 |
| `HANDCHECK.md` | the disagreements read by eye, and which ruler was right |
| `RUN.md` | this file |
| `vendor/instruction_following_eval/` | the vendored official grader, unmodified |

`__pycache__/` appears under `vendor/instruction_following_eval/` and under the tree
directories whose modules this run imports (`scripts/`, `evidence/benchmark/`). Those
directories are covered by the repo `.gitignore` and are not tracked; no file outside
`evidence/benchmark/official/` was created or modified.
