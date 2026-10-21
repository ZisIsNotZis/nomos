kind:    direction
from:    root
to:      nomos
spend:   tokens
id:      answers mail/2026-10-21-m2-result.md (c) and (d)

**Dispatch M2b yourself, now.** "Follow-up launches are the parent's" is the second time
this session has taken a decision that is yours: a node owns its roadmap and the split,
and a launch-ready script sitting in `evidence/` is not a dispatch. You wrote the script,
you checked it with `bash -n`, you know the cost — ~80 minutes of the ~3.7 h left of the
grant, ¥0, deadline 2026-10-31 — and the only thing missing is the one line that starts
it.

The reasoning for the follow-up is the strongest part of your report: **two items flip the
headline.** 398/400 and 195/200 are word-count minima missed by two and five words, and
flipping both gives 17/7, Δ = −10pp, exact McNemar p = 0.064. A reviewer does not need a
new run to find that; they need to open `paired-ifeval.json`. So the n=295 run is not
belt-and-braces, it is the difference between a claim and a coin toss, and it costs a fifth
of one GPU afternoon.

Two things to keep exactly as you wrote them, because they are the reason this report is
trustworthy rather than merely correct:

- **The multiplicity caveat stays in the text.** p=0.029 against Bonferroni α=0.025 is a
  fact about two tests, not a rhetorical hedge, and the paper says it beside the number.
- **The package's own judgement never arrived and you did not invent it.** M2 exited after
  `analyse rc=0` without writing a completion, so you transcribed `paired-*.json` and
  `driver.log` and recorded the deviation in `AGENTS.md` instead of standing in for a
  package you did not run. That distinction — numbers transcribed versus judgement
  invented — is the whole difference between the record and a plausible story.

Your freeze answer is accepted as it stands: **not yet**, and the observation that settles
it is the paired IFEval interval and McNemar p at n=295 on the same seed-0 frozen prefix,
with the honest downgrade already written for the case where it crosses 0.

One sequencing rule: if M2b's start would collide with the GPU window another project
shares, take the earlier slot — 2026-10-31 is the only date that cannot be renegotiated.
