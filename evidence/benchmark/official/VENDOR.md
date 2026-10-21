# Vendored: google-research/google-research `instruction_following_eval/`

The official IFEval grader, copied byte-for-byte. Nothing in this directory was edited;
`grade_official.py` imports it as the package `instruction_following_eval` (an implicit
namespace package, which is how the upstream tree works — upstream has no `__init__.py`).

- repo: `google-research/google-research`
- commit: `e6890f85757dd84e27ca6df2dd30651dafad28e0`
- upstream directory: `instruction_following_eval/`
- local directory: `evidence/benchmark/official/vendor/instruction_following_eval/`
- licence of the upstream code: Apache-2.0 (`licenses/Apache-2.0.txt` in this repo)

Fetched with:

```
mkdir -p evidence/benchmark/official/vendor/instruction_following_eval
cd evidence/benchmark/official/vendor/instruction_following_eval
BASE=https://raw.githubusercontent.com/google-research/google-research/e6890f85757dd84e27ca6df2dd30651dafad28e0/instruction_following_eval
for f in instructions.py instructions_util.py instructions_registry.py evaluation_lib.py README.md requirements.txt; do
  curl -sS -m 60 -f -o "$f" "$BASE/$f"
done
sha256sum *
```

## Files

| file | bytes | sha256 | url |
|---|---|---|---|
| `instructions.py` | 55162 | `60e086f5342a03ce8e18b64bbcccf86308f523c08aa826707a562150a52f3edf` | https://raw.githubusercontent.com/google-research/google-research/e6890f85757dd84e27ca6df2dd30651dafad28e0/instruction_following_eval/instructions.py |
| `instructions_util.py` | 19538 | `a73797261eee5bf447e279d82a2b700b1bdd3cb1193412dbab1270a85832bc6b` | https://raw.githubusercontent.com/google-research/google-research/e6890f85757dd84e27ca6df2dd30651dafad28e0/instruction_following_eval/instructions_util.py |
| `instructions_registry.py` | 7240 | `ec92d72c264f6d906978613085db262356174300370a3fffe6fefd5969ce9cfc` | https://raw.githubusercontent.com/google-research/google-research/e6890f85757dd84e27ca6df2dd30651dafad28e0/instruction_following_eval/instructions_registry.py |
| `evaluation_lib.py` | 6984 | `35decc06000718487f44d7deafa6d3f48a8ec0886281edf40162c0265b7d248c` | https://raw.githubusercontent.com/google-research/google-research/e6890f85757dd84e27ca6df2dd30651dafad28e0/instruction_following_eval/evaluation_lib.py |
| `README.md` | 1457 | `fef3c44408e4b39837af345095ccce7da798853fd60ea94a1de63afa9d3d67b3` | https://raw.githubusercontent.com/google-research/google-research/e6890f85757dd84e27ca6df2dd30651dafad28e0/instruction_following_eval/README.md |
| `requirements.txt` | 35 | `1b1716c9ac21b9cc2bd0d7354ed8f7b6982ccf35598529601a7c08508acec94a` | https://raw.githubusercontent.com/google-research/google-research/e6890f85757dd84e27ca6df2dd30651dafad28e0/instruction_following_eval/requirements.txt |

`grade_official.py` re-hashes these six files at run time and writes the result into
`official-ifeval.json` under `vendored.files`, so a drifted copy fails the acceptance
check rather than silently changing the numbers.

## Imports, and what that forced into the environment

- `evaluation_lib.py` imports `instructions_registry` only.
- `instructions_registry.py` imports `instructions`.
- `instructions.py` imports `absl.logging`, `langdetect`, `instructions_util`.
- `instructions_util.py` imports `immutabledict`, `nltk`.

`nltk` is used as `nltk.tokenize.RegexpTokenizer(r"\w+")` (`count_words`, no downloaded
corpus) and as `nltk.data.load("nltk:tokenizers/punkt/english.pickle")`
(`count_sentences`). The punkt corpus is not vendored and was not downloaded: nothing in
the 295-item frozen sample carries `length_constraints:number_sentences`, which is the only
instruction type that reaches `count_sentences`. `langdetect` ships its own profiles.

## Files present upstream but deliberately not vendored

- `run.sh` — a shell wrapper that shells out to `launch_evaluation.py`/Docker; not imported
  by any module above. The fetch of this file was attempted and timed out
  (`curl: (28) Operation timed out after 60002 milliseconds with 0 bytes received`) after
  the six files above had landed; it is not needed and was not retried.
- `evaluation_main.py`, `launch_evaluation.py` — the CLI and its launcher; they import
  `evaluation_lib`, which is vendored, but nothing in this check calls them.
- `instructions_test.py`, `instructions_util_test.py` — upstream unit tests; they are not
  the grader and pull `absl.testing`.
- `data/` — upstream's `input_data.jsonl` and `input_data_with_input_instructions.jsonl`.
  This check scores *our* frozen prompts and *our* stored answers, so the upstream data
  would be dead weight; the prompts used are `data/bench/ifeval.jsonl`.
