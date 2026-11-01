# D0.2 drain scripts (DRAFT, plan task T3)

One script per tool about to be disabled. Each prints one JSON record `{"tool","held","evidence"}` and exits
0 (nothing held), 1 (holds something) or 77 (cannot run). A check that cannot run counts as "not drained".
`check-disabled.sh TOOL` is V6's "still disabled" check; `--self-test` runs it against a stub.
Not run by the prep slice: they read launchd, relay and worktree state. Run them one at a time at D0.2.
