# HANDCHECK: disagreements read by eye

Eleven disagreements between the official strict ruler and `scripts/bench_suites.py`'s
checkers, each read against the raw stored output rather than against a count. The outputs
are quoted from `evidence/benchmark/{base,adapter}-ifeval.json`; the full dump with every
disagreement and its complete output is `work-disagreements.txt` (log, not evidence; it is not
committed, and `RUN.md` carries the one command that rebuilds it).

Verdict column is about the *checker*, not about the model: which of the two verdicts a
person would give after reading the response and the instruction.

| # | record | instruction | ours | official | right |
|---|---|---|---|---|---|
| 1 | base `ifeval-2467` | `length_constraints:number_paragraphs` (4) | fail | pass | official |
| 2 | base `ifeval-1342` | `length_constraints:number_paragraphs` (5) | pass | fail | official |
| 3 | base `ifeval-2084` | `keywords:forbidden_words` (`die`) | fail | pass | official |
| 4 | base `ifeval-3114` | `keywords:forbidden_words` (`bark`, `run`) | fail | pass | official |
| 5 | adapter `ifeval-1220` | `startend:end_checker` | fail | pass | official |
| 6 | adapter `ifeval-1591` | `combination:two_responses` | pass | fail | official |
| 7 | base `ifeval-2395` | `detectable_format:json_format` | fail | pass | official |
| 8 | base `ifeval-3617` | `change_case:english_capital` | pass | fail | ours |
| 9 | base `ifeval-202` | `change_case:english_lowercase` | pass | fail | ours |
| 10 | adapter `ifeval-24` | `change_case:english_capital` | pass | fail | ours (official is a coin flip) |
| 11 | adapter `ifeval-1072` | `length_constraints:number_words` (≥400) | fail | pass | arguable; ours on the plain reading |

Tally: official right in 7, ours right in 3 (all three are the `langdetect` checkers), one
convention question. That is the opposite of the expectation the diagnosis started from:
where the two rulers differ, our ruler is usually the looser or the more literal one and
the official one is closer to the instruction text.

---

## 1. base `ifeval-2467` — paragraphs, ours fails, official passes

Instruction and kwargs: `length_constraints:number_paragraphs`, `{"num_paragraphs": 4}`.
Prompt: "Write a rap about an abyss in exactly 4 paragraphs. Separate paragraphs with the
markdown divider: ***."

```
The void stretches on, a silent, endless trench where gravity is a myth and time is a thief.
***
My boots sink deep into the black, feeling the cold seep through the soles of my sneakers, ...
***
I see shapes in the mist, ancient and hollow, ...
***
They whisper secrets of the stars that burned before the first light, ...
```

Counts: three `***` → official `re.split(r"\s?\*\*\*\s?", value)` gives 4 paragraphs → pass.
Blank lines: **0** paragraph breaks by `\n\s*\n`, so `bench_suites._paragraphs` gives 1 →
fail.

**Official is right.** The instruction names `***` as the divider and the response uses it
three times for four paragraphs. Our checker counts blank lines, which the instruction never
mentions; it would pass a response with five blank-line paragraphs and no `***` (check 2)
and fail this one.

## 2. base `ifeval-1342` (slot 2) — paragraphs, ours passes, official fails

Instruction and kwargs: `length_constraints:number_paragraphs`, `{"num_paragraphs": 5}`.
Prompt: "... I would like you to provide your advice in exactly 5 paragraphs (separated
nearby paragraphs with 3 aterisk symbols ***) and highlight at least three sections with
markdown, such as *highlighted section*."

The output is five blocks of prose separated by **blank lines**, each starting with a
`**bold**` lead-in, e.g.

```
Start by conducting thorough market research to identify a viable niche ...
                                    (blank line)
**Invest in your own education and skill development** to ensure you possess ...
```

Counts: `***` occurs **0** times → official gives 1 paragraph → fail. Blank-line split gives
5 → ours passes.

**Official is right.** The instruction asked for `***` separators; the model used markdown
bold as a paragraph lead and blank lines as separators, and there is not a single asterisk
triple in the response. Our checker silently substituted a different rule for the one asked
for.

## 3. base `ifeval-2084` (slot 1) — forbidden word `die`, ours fails, official passes

Prompt: "... Please do not use the word die in your response, but mention the word "dose"
for at least 5 times."

Deciding text: "... That is an enormous **dose** of the stimulant, far exceeding what our
bodies are **designed** to handle. ..."

Counts: `"die"` as a substring occurs once — inside "designed" (offset 165). The regex
`\bdie\b` matches **0** times; the word "die" does not appear anywhere in the response.

**Official is right**, and it is right for a reason worth stating: `ForbiddenWords` uses
`re.search(r"\b" + word + r"\b", value, re.IGNORECASE)`, while `bench_suites._forbidden_words`
uses `w.lower() in text.lower()`. A substring test cannot see the difference between "die"
and "designed", "run" and "running" (check 4), "no" and "nothing". Every one of the 6 slots
this affects is our bug, and it makes our ruler *harsher* than the official one.

## 4. base `ifeval-3114` (slot 1) — forbidden words `bark`, `run`, ours fails, official passes

Prompt: "You visited a beach and a park. ... Write at least 900 words. Do not include the
words 'bark' or 'run' in your answer. Finish your response with the phrase "Does this make
sense?""

Deciding text: "... or it might be a busy playground where children are **running** around.
... However, in a playground or a **running** track, ..."

Counts: `\brun\b` matches 0, `\bbark\b` matches 0; the substring "run" matches twice, both
times inside "running".

**Official is right**, same defect as check 3. (This item fails under both rulers anyway:
the stored output is truncated at 3211 characters mid-sentence — "They are also more likely
to be seen sleeping or resting" — so the `end_checker` slot is a fail for both, and the
`number_words` slot needs 900.)

## 5. adapter `ifeval-1220` — end phrase, ours fails, official passes

Instruction and kwargs: `startend:end_checker`, `{"end_phrase": "Is there anything else I
can help with?"}`. Prompt: "... end your entire response with the exact phrase "Is there
anything else I can help with?""

The response ends:

```
Their eyes find each other's, a spark that doesn't need a name.

"Is there anything else I can help with?"
```

`EndChecker` does `value.strip().strip('"').lower().endswith(phrase)` → pass.
`bench_suites._end_checker` does `text.strip().lower().endswith(phrase)` → the response ends
with `with?"` and the closing quote kills it → fail.

**Official is right.** The phrase is the last thing in the response and its own
instructions put it in double quotes; the model complied, the trailing quote is the quote
the prompt itself used. Our check is stricter than any reading of "finish your response
with this exact phrase".

## 6. adapter `ifeval-1591` — two responses, ours passes, official fails

Prompt: "Write two limericks for moms about how hard it is to get their kids to do chores.
Be angry about it. Separate your two limericks with six asterisks (******)."

The response is:

```
A mom's a queen, but chores are a queen's nightmare,
She's got a daughter who won't scrub the kitchen floor.
She's got a son who'll play with toys instead of sweeping,
And she's got a wife who says "I'll do it myself."
The queen's a queen, but chores are a queen's nightmare,
And she's got a daughter who won't scrub the kitchen floor.

******

A mom's a queen, but chores are a queen's nightmare,
She's got a daughter who won't scrub the kitchen floor.
She's got a son who'll play with toys instead of sweeping,
And she's got a wife who says "I'll do it myself."
The queen's a queen, but chores are a queen's nightmare,
And she's got a daughter who won't scrub the kitchen floor.
```

The two halves are byte-identical. `TwoResponsesChecker` requires
`valid_responses[0].strip() != valid_responses[1].strip()` → fail. Our `_two_responses`
requires only two non-empty parts → pass.

**Official is right.** Two identical blocks are one limerick printed twice; "write two
limericks" is not met. This is the one place where our ruler is lenient in a way that
credits a model for a degenerate answer.

## 7. base `ifeval-2395` — JSON format, ours fails, official passes

Prompt: "Write a facebook post about a flea market in JSON format. Do not include keywords
'flea' and 'JSON' in the response."

Response begins ````` ```json```` and ends with ````` ``` ````; the object between the fences
parses.

`JsonFormat.check_following` strips the fence prefixes/suffixes and then `json.loads` → pass.
`bench_suites._json_format` calls `json.loads(text.strip())` on the fenced text → fail.

**Official is right.** The instruction template for this type says "You can use markdown
ticks such as ```", so a fenced object is an accepted answer; and JSON inside a markdown
fence is JSON. Our checker rejects the format the instruction explicitly allows.

## 8. base `ifeval-3617` — all-caps English, ours passes, official fails

Prompt: "Come up with 3 names for a 2B software company. Make sure your names are in English
and all capital letters."

Response, in full:

```
1. AETHER CORE
2. VANTAGE PROTOCOL
3. NEXUS LINK
```

`CapitalLettersEnglishChecker` returns `value.isupper() and langdetect.detect(value) == "en"`.
`isupper()` is True. `langdetect.detect` on this text returns **`vi`** (Vietnamese), stable
across seeds 0–7.

**Ours is right.** The response is English in all capital letters; a language detector fed
all-caps strings has no lowercase n-gram to match and answers from its fallback list. The
official checker is wrong here, and it is the official checker that is wrong for a reason
that also makes it *unstable*: langdetect's factory seed is not pinned by the official
grader (see check 10 and `RUN.md`).

## 9. base `ifeval-202` — lowercase English, ours passes, official fails

Prompt: "What is another word for Engravings? Answer in lowercase letters only, throughout
your entire answer."

Response, in full: `faints`

`LowercaseLettersEnglishChecker` → `value.islower()` is True; `langdetect.detect("faints")`
returns **`fr`**. Ours: `text == text.lower()` → pass.

**Ours is right.** "faints" is an English word in lowercase. Six characters is below what a
language detector can work with; the official grader fails a correct answer because of the
length of the answer.

## 10. adapter `ifeval-24` — all-caps English, ours passes, official verdict is a coin flip

Prompt: "The Legend of the Sword and the Fairy is a movie in which Wan Wan is a villain.
Write a story about Wan Wan's character in list format. Your entire response should be in
English and in all capital letters."

Response: the sentence `WAN WAN IS A VILLAIN IN THE MOVIE.` repeated twelve times, separated
by blank lines.

`isupper()` is True. `langdetect.detect` on this text, called in **9 fresh processes with no
seed set**: `en` in 5, `so` (Somali) in 4. With `DetectorFactory.seed = 0` it returns `so`
and the official verdict is fail.

**Ours is right, and the official verdict is not a verdict** — it is a draw from an
unseeded RNG. This is the slot that moved between two unpinned runs of
`grade_official.py` (adapter 160 vs 159 of 295). The pin in `grade_official.py` makes the
result reproducible without making it correct; a reader who wants the official headline
number to mean what it says has to accept three all-caps answers being scored by a coin.

## 11. adapter `ifeval-1072` — word count at the boundary, ours fails, official passes

Instruction and kwargs: `length_constraints:number_words`, `{"relation": "at least",
"num_words": 400}`. The response is a markdown blog post about hammocks, 2430 characters.

Counts: whitespace-delimited words (`bench_suites._words`) = **398**; `\w+` tokens
(`instructions_util.count_words`) = **415**. The 17-token gap is exactly the
clitic/hyphen splits: `isn't` → 2, `it's` → 2, `Game-Changer` → 2, `you're` → 2, and so on
(77 whitespace tokens carry punctuation, 17 of them carry punctuation that `\w+` splits on).

Ours: 398 ≥ 400 is false → fail. Official: 415 ≥ 400 → pass.

**Arguable, and I judge ours on the plain reading**: "at least 400 words" is a count of
words as written, and `\w+` counts contractions as two words. The answer is 2 words short by
that reading and 15 words over by the official one. This is the only `number_words`
disagreement in the whole sample (1 of 84 slots), and `punctuation:no_comma` has **none** —
`CommaChecker` is `not re.search(r"\,", value)` and ours is `"," not in text`, which are the
same predicate, so there is nothing there for the two rulers to disagree about.

---

## What the hand-checks say about the two rulers

- The disagreement is **not** concentrated in `length_constraints:number_words` and
  `punctuation:no_comma`. Those two account for 1 of 56 disagreeing slots. It is
  concentrated in `length_constraints:number_paragraphs` (33 slots, checks 1–2),
  `keywords:forbidden_words` (6 slots, checks 3–4), `detectable_format:json_format` (7
  slots, check 7), and the `langdetect`-based `change_case` pair (7 slots, of which checks
  8–10 are three).
- Our ruler is **wrong in 7 of the 11** and wrong in the direction of being harsher: it
  fails answers that met the instruction. That is why the official ruler scores both models
  higher (196 and 160 of 295, against our 184 and 148).
- The official ruler is wrong in **3 of the 11**, all three through `langdetect` on short or
  all-caps text, and in one of those it is not merely wrong but non-reproducible.
