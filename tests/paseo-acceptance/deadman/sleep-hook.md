# Sleep and wake markers (DRAFT, plan D1.9, open question 9)

The Mac sends `{"kind":"sleep","ts":N}` just before sleep and `{"kind":"wake","ts":N}` after, through
`mac-heartbeat-sender`, so the dead-man check does not page on a closed lid. Option A: `sleepwatcher`
(`~/.sleep`, `~/.wakeup`), needs `brew install sleepwatcher` (asks djbclark, AGENTS.md order 11). Option B: a
launchd agent on power events. Nothing here is installed. A failed wake hook is harmless: the next heartbeat
removes an older sleep marker (`write-heartbeat`), and `d1-09-deadman.sh` scenario 4 proves it.
