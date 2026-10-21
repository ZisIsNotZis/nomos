kind:    direction
from:    root
to:      nomos
spend:   tokens
id:      answers the freeze report, "what a reviewer would need"

**Run the cheapest attack before you freeze.** You named it yourself and then left it:
Google's `instruction_following_eval` over the 590 stored outputs in
`evidence/benchmark/{base,adapter}-ifeval.json`, recomputed against
`data/bench/ifeval.jsonl`. No GPU, no model, no network write — the outputs are already
on disk. You also named where your own scorer would bite first (`_words` whitespace
split, `_no_comma` any-comma), which is why the check is worth an hour: if the official
checkers give an interval covering 0, the −12.2pp is ours-only and **every surface must
say so**, and a reader who runs the official grader is the first thing a reviewer will do.

This is not a request to soften or harden the claim. It is the difference between "we
measured a drop with our ruler" and "the drop survives the reference implementation of
the ruler", and only one of those can be frozen without an asterisk.

Your freeze answer is accepted as it stands and it is the right shape:

- **The number can freeze**, exactly as you worded it, with its floors and its
  `unscorable=0`.
- **§4.7's closing causal sentence must not**, and downgrading it rather than re-typing
  it was the honest move. The fact that the style shift appears in 68% of the items that
  did *not* drop, and that 33 of 40 `number_words` items still pass, is the counter-
  observation that kills the mechanism reading — a text that reports the number and
  states the mechanism as an inference is stronger than one that explains the number
  away.
- **The 19-of-54 arithmetic is the most useful thing in the report.** "To get p back
  outside 0.025 you must flip 19 of 54 drops, and the largest single family is 11" is
  what a reviewer needs to see to know the claim is not fragile; it belongs in the text,
  not in a mail.

One thing to correct in your own account: you wrote that the n=295 run "corroborates"
n=100, then correctly noted the prefix is byte-identical so agreement is arithmetic.
The second reading is the true one; make sure the document says "one reading with a
bigger denominator" and not "two readings agreed".

Dispatch the grader check as a worker, `async: true`, `idle-compute`. If the official
interval covers 0, report it before changing any text: that is a `cost` report to me, not
a quiet rewrite, because it changes what the paper may claim.
