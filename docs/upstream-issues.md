# Upstream issues worth filing

Drafts written 2026-08-23 from problems verified on this machine. Not yet
filed — filing is an operator decision (they go to third-party trackers under
the operator's account).

## 1. graft — statusline conflates "built but empty" with "not built"

**Repo:** `@nanonets/graft` (npm; installed globally at
`/opt/homebrew/lib/node_modules/@nanonets/graft`)

**Version seen:** the globally installed build as of 2026-08-23.

**What happens:** In a repo whose indexed languages yield no code symbols —
e.g. a docs/markdown-only repo — `graft build` succeeds and legitimately
reports `✓ wiring: 0 nodes (), 0 edges, 0 cards []`. The Claude Code
statusline then renders:

```
◤ graft · not built · run graft build
```

...forever, because `renderStatusline()` treats `nodeCount === 0` as
"never built" (`dist/claude/format.js:24`), and `resolveStats()` falls back to
`readWiring()` which is also empty (`dist/claude/statusline.js`).

**Why it matters:** the bar tells the user to run a command they *have already
successfully run*, and keeps telling them after every rebuild. It reads as a
broken install. `graft ask` / `graft grep` still work fine, so the message is
actively misleading.

**Correction (2026-08-23):** an earlier revision of this file claimed a
second, broader trigger — that repos with working graphs also report
"not built". **That was wrong**, and it is retracted. It came from grepping
`graft check` output for the string "not built", which matched the unrelated
*deep layer* line (`deep layer: not built (run graft build --deep …)`) — an
optional LLM-built layer, not the wiring graph. Checked properly,
`~/ops/site-djbclark` reports `graph check: OK — the wiring graph is in sync
with the code` with 502 nodes. Two lessons, both ours not graft's: grep for a
substring is not a status check, and the deep-layer line is noise unless you
are actually using `--deep`.

**Why this repo is genuinely empty**, for the record: its only code is three
JS files under `.claude/` (`workflows/graph-audit.js`, two helper `.cjs`).
Graft's walker skips dot-directories, and unlike ordinary skipped dirs this
is not overridable — `graft build --include-dir .claude` refuses with
"dot-directories are never overridable". So the 0-node graph is correct, and
the only wrong thing is the *wording* of the statusline.

**Suggested fix:** distinguish the two states. The build already knows whether
it ran, so persist that (a `builtAt` in `graft/.cache/stats.json`, or simply
the existence of the cache/stamp) and render empty-but-built differently, e.g.
`◤ graft · 0 nodes · no indexed code`. Falling back to "not built" only when
no build artifact exists at all.

**Repro:** `graft build` in any repo containing only `.md` files, then look at
the Claude Code statusline.

## 2. hindsight-coding-agents — documented config keys are a subset of what's read

**Package:** `@vectorize-io/hindsight-coding-agents` (0.3.4 on this machine)

**What happens:** the bundled `hindsight-coding-agent` skill documents a small
set of config keys for `~/.hindsight/coding-agent.json`, but the code reads
several more that are load-bearing for any non-default topology:

`optInOnly`, `optInPaths`, `retainTags`, `retainMetadata`, `bankIdTemplate`,
`resolveWorktrees`, `maxParallelRetains`, `daemonProfile`, `daemonIdleTimeout`,
`apiPort`, `embedPackagePath`, `embedVersion`

Also undocumented: `isOptedIn()` returns true for any path under `optInPaths`
**or** any `mapPathToBank` entry — a coupling that changes what a retention
allowlist actually does.

**Why it matters:** the default single-bank setup is a trap at scale. On this
machine one bank accumulated 1,756 facts across 7 unrelated projects, giving
roughly a 1-in-17 chance that a recalled memory came from the project the
agent was working in. Fixing that requires exactly the keys that aren't
documented, so users can't find the fix from the docs alone.

**Suggested fix:** document the full key set in the bundled skill, and call out
the `gitProjectName()` fallback — when `git rev-parse --git-common-dir` fails
it falls back to the directory basename, so `bankIdTemplate` silently produces
"drain banks" named after non-git parent directories (`::src`, `::tmp`, and
the home directory itself).

**Evidence:** measured on this machine and written up in
`~/ops/site-private/memory/project_hindsight_memory_restructure.md`.

## Not filed — a papercut worth knowing: `graft build` edits tracked `.gitignore`

Every `graft build` appends `/graft/` to the repo's **tracked** `.gitignore`
and drops an untracked `.ignore` file, so a repo that was clean before the
build is dirty after it. It's a helpful default, but it has a real cost:

- It leaks tool-local cache config into shared repos (including public ones).
- In a fork that tracks upstream, it puts a permanent local modification on a
  tracked file.
- **It breaks other tooling.** An uncommitted `.gitignore` blocks git branch
  checkout, which made `cow migrate --all` fail on every candidate in
  `~/.hermes/hermes-agent` (each rolled back cleanly, but nothing migrated
  until the tree was clean).

**What we do instead** — keep the tracked file pristine and put the rules in
the repo's local excludes:

```bash
git checkout -- .gitignore
printf '\n/graft/\n/.ignore\n' >> .git/info/exclude
```

Applied to `~/.hermes/hermes-agent` and all three `~/ops` repos. Re-apply
after any `graft build` in a new repo — or check `git status` afterwards,
which is the cheap habit.

A `--no-gitignore` flag (or writing to `.git/info/exclude` by default) would
remove the papercut; worth raising upstream if it recurs.
