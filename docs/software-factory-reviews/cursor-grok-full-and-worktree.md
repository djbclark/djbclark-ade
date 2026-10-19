# Raw response: acp-run cursor --model grok-4.7 context=256k fast=false reasoning_effort=high, auth cursor_login (OAuth), full draft incl. section 9 (2026-10-19 ~15:03 EDT)

acp-run applied: {"model": "grok-4.7", "effort": "high", "ctx": 256000, "ctx_source": "option context"}; no cost reported; exit 0

---

MODEL: Grok 4.7

The deterministic orchestrator as the only state writer, with LLMs limited to artifacts via `acp-run`, is the right design. Several rules as written will resume the wrong step, spend the budget on infra failures, or isolate only the happy path.

**State machine first.** `failed → spec` and `paused-quota → spec` re-run the spec after a build, review, or quota hit. Retry and unpause must re-enter the state that stopped. `cancelled`, `approve → failed`, and `approve → paused-quota` are missing. `needs-human → merged` skips `ready`, so “APPROVE means ready” and “human merges” are two paths sharing `factory approve`.

Resume is the serious bug. “If the artifact parses, advance” trusts a file the agent wrote before the orchestrator committed the transition. A crashed reviewer that printed `VERDICT: PASS`, or a `build.md` written before verify, counts as done. Invert it: atomic `job.json` is the only cursor; the in-progress step always reruns; agents write `*.partial` and the orchestrator promotes that file in the same transition as the state change. Store `reviews[round][role]` and the round’s `head_sha`, or round 2 overwrites round 1 and reviewers judge a moving tree.

“First line only” misreads titles. Extract one anchored `VERDICT:` / `APPROVE|ESCALATE` line; on ambiguity, fail the step and retry. Do not guess.

There is no job lock, so overlapping `factory run` and `factory rework` double-write `job.json`. `index.json` is a second writer under parallel jobs. Scan `factory/jobs/*/job.json` at serve time.

A reviewer timeout counted as CHANGES forces a builder rework. Infra failure should retry that reviewer or go to `needs-human`. That is the decision for open question 7.

**Cost.** One `budget.limit` cannot mix USD, tokens, and call counts. If `--json` omits cost, `spent` never moves and the guard never fires. Pick one unit, and treat “cost omitted” as a pause. Enforce the daily cap before every `acp-run`, not only in `factory next`. The sample `roles.toml` puts Opus on spec, security, and approver, which contradicts cheap-first. The expensive loop is `max_rounds` times a failed reviewer. Check the budget before a fallback too. `--timeout` does not reap a stuck child; define how orphans are killed.

**Dashboard.** Static HTML polling `job.json` is the right MVP. Cut SSE, live logs, UI actions, and model comparison: actions need a real server, and comparison needs comparable costs. Bind `serve` to localhost; `runs/` will hold secrets. Render artifacts as text. The unisolated-work banner and stale-worktree list cannot be computed in the browser; precompute them in `factory status` / `gc`, or drop them from the MVP.

**Section 9.** Automatic `git worktree add` and builder `-C` always on that worktree is the factory invariant worth keeping. Put the root outside the primary tree (`../<repo>.wt/<id>`). A `.wt` inside the checkout gets scanned or nested. Pin `base_sha`. `factory run` should set child env to refuse a primary checkout even if the human default is off.

The guard does not match “Daniel forgets to isolate.” `git-dir == git-common-dir` and branch ∈ {main, master} still allows detached HEAD and any other branch in the primary checkout. Compare `realpath`s; relative versus absolute `rev-parse` output false-allows. The check runs only at session start, so a live agent can still `git -C` the primary tree. Default `warn` will be ignored. Use `refuse` plus `--allow-primary` for factory children. Interactive: refuse primary+main, warn primary+other. Keep this out of `acp-run` core; it is a shared runner. A wrapper (or the factory launcher) is the answer to “where does the guard live?” If it must sit in `acp-run`, default `off`.

`factory start` cannot `cd` the parent shell from Python; `fs` has to be a shell function. Record the base explicitly; defaulting to HEAD isolates onto whatever feature branch was checked out. Record whether the primary tree was dirty so uncommitted work is not left behind unnoticed. `session/<slug>` shares the branch namespace with `factory/<id>`.

The pre-commit hook does not stop yolo agents (`--no-verify`, commit plumbing), and worktrees share the common hooks dir. A branch-name check also blocks an intentional main worktree. Prefer session-start `refuse`.

`factory gc`: dry-run and “dirty never removed” are right. “Unpushed” as written never deletes anything, because `factory/<id>` has no upstream. Treat a tip as removable only when the job is `merged` or `abandoned` and the tree is clean. `git branch --merged` misses squash merges, so job state is the authority. Do not gc from git alone while a job is non-terminal; lock the worktree for `build` and `review`. Idle > N days is undefined. Leave it out of v1. `sessions/*.json` is a second registry that gc does not update, so removed worktrees become ghost cards.

Defer jj, and do not add `isolation = "jj"`: rev-parse, merge detection, hooks, and worktree add would all fork. Containers are the boundary that actually matters. Worktrees do not contain env, credentials, docker.sock, network, or writes outside the tree. Scrub inherited secrets for builder subprocesses in v1; do not describe worktrees as isolating yolo agents.

**Cut.** Plain markdown specs until a bake-off; drop `spec_tool`. Local backlog before GitHub labels (`gh` is a second store resume does not reconcile). Reviewers: security and code only. Drop fallbacks and the approver LLM until resume works; the human already merges, and the approver only re-reads reviewer-asserted PASS. Drop M7. Ship M0–M3 with job worktrees (already in M2). `factory start` and the guard are a habit tool after that.

Blocking choices: retry and unpause re-enter the failed state; reviewer infra failure is not CHANGES; never auto-merge; guard in a wrapper, refuse on primary+main; worktree root outside the checkout.
