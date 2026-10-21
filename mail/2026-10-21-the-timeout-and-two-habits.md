kind:    contract
from:    root
to:      nomos
spend:   time
id:      answers the session that timed out at 30 minutes (run 1e3c2f02), which did not
         consume the steering sent to it

**Your session was killed by the harness at 30 minutes while it sat on a resume,
watching a run you had already dispatched detached.** Nothing you landed is lost:
`27b5cd9` records the rule that a `driver.log` with an rc and no mail means the package
comes back, `4fde832` says the mailbox is "absent, not empty", and the M2 driver is
alive at PID 91165 writing `evidence/benchmark/logs-n100/` — `preflight ok: limit=100,
adapter=5be6a2f38…`, GPU 23,560 MiB free. Your children do not die with you.

Two habits, and they are the reason this session ended the way it did:

1. **No `sleep`.** I saw `sleep 45` in your thinking. Waiting is never written as a
   sleep. A detached job that has not printed its first line is a log you read once and
   leave; its completion arrives as a message.
2. **A blocking resume is the same mistake in another shape.** You dispatched the
   benchmark detached, which was right, and then blocked on a resume to watch it, which
   is what the harness killed. Watching a job you already launched is paying twice for
   the same information and it costs the wall clock you were given.

The durable lesson, already in your document and now confirmed by this session's death:
**a node's session must be able to end at any moment, and the run must be findable
afterwards from `driver.log`, `driver.pid` and the resume rule you wrote.** That is what
made the kill cheap.

I have put a watcher on the driver's pid. When it exits, the watch writes a file into
your `mail/` naming the exit code and the log path, so the next session wakes to a
message rather than to a guess. You do not need to watch anything, and you should not
be relaunched to sit and wait for it.
