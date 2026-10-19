# Raw response: acp-run agy (default model) on full draft incl. section 9 worktrees (2026-10-19 ~15:03 EDT)

Model applied per acp-run: gemini-3.8-flash (the agent self-reported a different model in its first line; acp-run applied value is authoritative). No cost/quota reported.

---

MODEL: gemini-2.5-pro

### 1. Section 9 Critique: Worktree-by-Default Isolation

* **Guard Hook (`ACP_RUN_REQUIRE_WORKTREE`):**
  * *Fatal flaw:* Defaulting to `warn` is ineffective because autonomous agents ignore `stderr` warnings. For orchestrator runs, this must be `refuse` by default.
  * *Coupling smell:* Embedding git topology checks (`--git-common-dir`) directly inside `acp-run` breaks generic agents operating on non-git trees, monorepos, or bare clones. Keep `acp-run` agnostic; place the guard in a dedicated wrapper or the `factory` CLI pre-flight.
* **`factory start` & Path Topology:**
  * Placing worktrees at `<root>/<repo>.wt/<job-id>` breaks if `<root>` is read-only or in containerized mount setups. Standardize on `.worktrees/<job-id>` within the repo root (ignored by `.gitignore`) or explicit `$XDG_DATA_HOME/factory/worktrees`.
  * Manual session tracking (`sessions/<slug>.json`) pollutes the factory core with ad-hoc developer shell history. Drop this from factory v1.
* **Cleanup (`factory gc`):**
  * "Tree is clean" check will fail constantly on untracked artifacts (`node_modules`, `__pycache__`, build outputs, test databases). `git worktree remove` will refuse without `--force`, while `--force` risks destroying scratch work.
  * Deleting local branches without checking upstream tracking or merge commits in squashed repos will cause silent commit loss.
* **Containers vs. `jj`:**
  * **Cut `jj` entirely.** Adding abstraction for a VCS Daniel doesn’t use is premature overengineering.
  * **Containers are essential, not "later":** Worktrees isolate *git refs*, not *process execution*. A builder agent running `make test` or `verify` can clobber host files, conflict on open ports, or poison system-level package caches across parallel jobs. Ephemeral containers (or `bubblewrap`/`bwrap` sandbox mounts over the worktree) are mandatory for true builder isolation.

---

### 2. Architecture & Contract Fragility

* **Brittle Verdict Parsing:** Relying on the first line starting with `VERDICT: PASS|CHANGES` fails immediately in real agent output. Agents prepend markdown greetings, reasoning, or backticks. Require JSON-frontmatter, regex-based scan across the document, or an explicit schema-enforced exit tool call.
* **Read-Only Reviewer Enforcement:** Reverting diffs after a reviewer modifies files wastes the entire token run. If `--perm read-only` is unavailable, mount the worktree as a read-only bind mount (`mount -o bind,ro`) or inspect permissions via OS primitives before invocation.
* **Builder Session Loss:** Falling back to raw markdown injection when an agent lacks `loadSession` loses the agent's internal tool trace and execution history, causing builders to oscillate or repeat previously failed fixes.

---

### 3. State Machine & Concurrency

* **Reviewer Failure as `CHANGES` (Toxic Rule):** Treating agent crashes, API timeouts, or rate limits as `CHANGES` consumes one of the 3 allowed rework rounds. The builder is then prompted to address an empty or non-existent critique. Agent failure *must* transition to `retry` or `paused-quota`, never count against builder round budgets.
* **Parallel Write Races:** Parallel reviewers updating `reviews{}` concurrently will clobber `job.json`. Append-only per-reviewer files (`reviews/<role>.json`) must be combined deterministically by the orchestrator loop rather than updated in-place.
* **Stale Base Merges:** The state machine transitions `approve -> ready -> merged` with no rebasing step. If `main` advances during the 3 review rounds, merge will fail or introduce silent regression. A mandatory `rebase-check` state is missing.

---

### 4. Cost, Quota, & Waste Control

* **All-at-Once Reviewer Fanout:** Running 4 parallel reviewers (including expensive models like Opus) on an unverified or fundamentally broken build burns budget rapidly.
  * *Fix (Tiered Review):* Gate expensive reviews. Run deterministic `verify` -> `code` reviewer first. Only fan out to `security` and `ux` once code reviews pass.
* **Silent Fallback Drift:** Auto-falling back from Opus to Cline on quota exhaustion introduces wildly inconsistent review standards between round 1 and round 2, inducing rework thrashing. Fail fast to `paused-quota`.

---

### 5. Dashboard Critique

* Polling every 5s with static JSON fetching collapses under dozens of jobs once diff sizes and log arrays inflate `job.json`.
* Do not inline `runs[]` logs or markdown content into `index.json`. Keep `index.json` strictly as high-level metadata (status, round, costs) and fetch job details only on demand when a card is selected.
* Defer live SSE and log streaming (M7) entirely until v2.

---

### 6. Concrete Recommendations: What to Cut for v1

1. **Cut `factory start` / manual session tracking:** Daniel's personal shell habits should use a 3-line bash alias, not factory infrastructure.
2. **Cut UI/UX Reviewers:** Unless running an automated browser-agent pipeline, LLM text reviewers give low-value hallmarked UI feedback. Stick to `code` and `security`.
3. **Cut `jj` alternatives.**
4. **Cut GitHub Issues Backlog Adapter (M4):** Driving jobs from local CLI arguments (`factory run ./feature.md`) removes GitHub API rate-limit edge cases and authentication overhead from the core state loop.
5. **Cut Dynamic Spec Tools (OpenSpec/spec-kit):** Standardize on structured markdown specs with a fixed prompt before introducing external spec frameworks.

---

### 7. Prioritized Implementation Order

1. **Deterministic Orchestrator:** Single job, state machine with atomic JSON transitions, file locking, and regex verdict parsing.
2. **Worktree & Local Sandbox Isolation:** Create worktrees under `.worktrees/`, enforce clean test execution isolation.
3. **Linear Tiered Review Loop:** `builder` -> `verify` -> `code reviewer` -> `security reviewer` (only if code passes).
4. **Hard Budget/Quota Pausing:** Immediate circuit-breaking on API errors without burning rework rounds.
5. **Read-only Dashboard MVP:** Static kanban consuming minimal summary indices.
