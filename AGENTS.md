# AGENTS.md — djbclark-ade

You are an AI agent on djbclark's machine. This repo is the operating guide
for running AI agents as **graphs** here: read this file, then follow the
pointers. It applies to any agent (Claude Code, Codex, OpenCode, Cline,
Copilot, Grok, Cursor, …).

## What this repo is

The agentic development environment (ADE) for this machine: one operator,
many agent TUIs, herdr/Orca as the terminal fabric, ACP for agent-to-agent
control; since 2026-10-08 also the git home of the orchestration and
session-hygiene skills and tools. Two altitudes, verified by real runs on
2026-08-23: the **micro graph** (Claude Code dynamic workflows, in-process
fan-out) and the **macro graph** (an Orca task DAG across agent CLIs in their
own worktrees). [README.md](README.md): architecture, how they compose, every skill.

## Read before acting

Each doc carries its own summary.

| Doc | For |
|---|---|
| [docs/model-routing.md](docs/model-routing.md) | which AI/service for what work; numbers are dated, re-probe (`aiuse --json`) |
| [docs/orchestration-practices.md](docs/orchestration-practices.md) | rules every orchestration skill follows |
| [docs/jev.md](docs/jev.md) | `bin/jev`, the TypeSafe Jev decision layer (shadow since 2026-10-11) |
| [docs/orca-integration.md](docs/orca-integration.md) | macro-graph commands, live-run lessons; `orca skills get orchestration` is authoritative |
| [docs/queue.md](docs/queue.md) | queued work and blockers: check it before proposing new work |
| [docs/ai-memory-landscape.md](docs/ai-memory-landscape.md) | the six levels of AI memory and their status |
| [docs/coding-factory.md](docs/coding-factory.md) | unattended issue→PR→auto-merge (2026-09-21) |
| [docs/agent-sleep.md](docs/agent-sleep.md) | idle-agent sleep; run `bin/herdr-sleeper list` before calling a pane dead |
| [docs/helm.md](docs/helm.md) | `/helm` ([skills/helm/](skills/helm/)): answer every waiting session from one window |
| [docs/herdr-tidy.md](docs/herdr-tidy.md) | `/herdr-tidy`: close idle panes without losing anything |
| [docs/skillopt-sleep.md](docs/skillopt-sleep.md) | nightly skill-edit cycle, `bin/skillopt-night` |
| [docs/failover.md](docs/failover.md) | `bin/failover.py`: reuse it, never hand-roll a fallback |
| [docs/upstream-issues.md](docs/upstream-issues.md) | unfiled bug drafts for third-party projects |
| [docs/mcp-servers.md](docs/mcp-servers.md) | MCP server roster (`claude mcp list`) |
| [.claude/workflows/graph-audit.js](.claude/workflows/graph-audit.js) | runnable micro-graph example, `/graph-audit` |
| [skills/](skills/), [docs/skills.md](docs/skills.md) | canonical copy of every hand-written skill: **edit and add skills here**, never via a TUI path; wrappers in [claude/commands/](claude/commands/) |
| [tools/acp-run/](tools/acp-run/README.md) | the ACP client every launcher uses (`~/.local/bin/acp-run`) |
| [bin/fleet-watch](bin/fleet-watch) | launchd fleet change notices to Hermes |
| [vendor/README.md](vendor/README.md) | what this repo references that lives elsewhere |

## Standing orders (operator-issued; they bind every agent here)

1. **Continuous operation — never stop work because context is large.**
   Externalize heavy work (subagents, background workflows, Orca workers),
   keep state on disk, let compaction bridge context windows. A handoff
   document is written *without stopping*, for work where the conversation
   itself is the state.
2. **Commit AND push at opportune moments**, after each coherent unit of
   work; on a sweep, also catch artifacts outside any repo that should be
   tracked. Never push secrets or ignored local state.
3. **Never idle on a long-running process — start parallel work by
   default**, on something that cannot contend with it (different files,
   databases, repos), and say what you started. Only exceptions: the next
   step depends on the result, or it would touch the same resource.
4. **Verify against the artifact, not a proxy — and retract loudly.** Check
   the thing itself: exit codes and structured output over string matching,
   config files over filenames, `gh pr view` over memory. When wrong, say so
   plainly and correct the record in the same breath.
5. **Number every set of options, hierarchically and uniquely.** Choices,
   next steps and findings get numbers; with more than one list in a reply,
   **never restart at 1**: `1.1`, `1.2`, … then `2.1`, `2.2`, …. Keep labels
   stable within a conversation.
6. **Flag best-practice deviations** and propose the improvement, but don't
   relitigate decisions the operator made knowingly.
7. **Routing discipline**: route per `skills/model-routing/SKILL.md`
   *Routing policy* (`route_agent.py policy --md`), the one copy. The prepaid
   tier stays retired until an operator top-up; the `agent_stats.py burn`
   alert (every 6h, 48h ahead) governs pool exhaustion: the blanket
   clinepass rule was **retired 2026-08-24**. Watch the alert, not the rule.

## Machine context

- **`acp-run --list` is the agent registry** (since 2026-10-08):
  `bin/route_agent.py` discovers agents from it plus installed headless TUIs;
  Orca's roster is a GUI list only (docs/model-routing.md).
- Ops-suite conventions live in `~/CLAUDE.md` and site-private and govern
  `~/ops`. This repo is ordinary: commit to master, push to
  `djbclark/djbclark-ade`.
- Facts here carry snapshot dates; probes beat memory. When you verify a
  change, update the doc in the same breath (standing order 2).

<!-- graft:start -->
## Graft — repo context graph

This repo is indexed in `graft/`: small linked markdown nodes that explain each
system and carry exact file:line spans, kept in sync with the code through git.

For ANY task here — understanding how something works, finding where code lives,
or scoping a change — get context from the graph before grepping or opening
source files. Re-ask freely (it's cheap) and reuse literal identifiers you
already have (symbol, error string, file name) as the query. New to this repo?
Run `graft map` first — a token-budgeted orientation (dir clusters, hubs,
hotspots), no LLM, no key.

- Run `graft ask "<your question>" --source` → ranked nodes with the relevant
  code spans inlined (each hit's ≤8-line crux by default; `--full` for whole
  definitions when the crux isn't enough). Match the tool to the task shape:
  for understanding or editing, the top node IS the answer — cite its
  `covers:` file:line spans and edit straight from `--source`. For
  exhaustive tasks ("every occurrence / every caller of this pattern"), ranked
  results are top-N, not complete — run `graft grep "<literal>"` instead
  (exhaustive over indexed files, grouped by enclosing symbol), falling back
  to raw `grep -rn` only for unindexed files.
- `graft skeleton <file>` → every definition's signature + span, ~10× cheaper
  than reading the file; use it to skim an API surface.
- `graft callers <symbol>` gives precomputed, exact edges — who calls this.
  Add `--direction out` for what it calls, or `--depth N` to walk
  transitively for the full blast radius. For structural questions, skip
  ranking and use this directly.
- Or browse: `graft/INDEX.md` lists every node; follow the links.
- Monorepos and folders of multiple repos rank fairly across sub-projects —
  hits carry `[scope/]` labels naming which one they're from. Narrow with
  `graft ask "<task>" --in <scope>/` once you know where you're working.

If a returned span is truncated ("+N more lines"), open the file at that exact
range before finalizing. Only open source files when a node genuinely lacks a
needed detail, and then at the exact file:line the node points to — never
re-read whole files.

After big code changes, refresh the graph with `graft build` (deterministic,
no API key, $0).
<!-- graft:end -->

## Code review (what a reviewer checks here)

Read by Codex (`@codex review`, or its automatic review on PR open), Cursor's
Security Agent and Approval Agent checks, and the `adversary` sub-agent. A
pull request here is expected to meet these; flag any it misses.

1. **The PR body quotes the adversary's verdict line** (`APPROVE`, `APPROVE,
   no findings` or `BLOCK ...`) together with the head SHA it reviewed. Flag
   the PR if the quote is missing, says BLOCK, or names a SHA other than the
   PR's current head. Whoever merges uses `gh pr merge --squash
   --match-head-commit <reviewed sha>`, so the head reviewed is the head
   merged.
2. **No exit status or result through a pipe**: `cmd > out.log 2>&1; echo
   "rc=$?" > out.rc`, never `cmd | x; $?`. Local test runs go through the
   operator's `bg` wrapper; CI runs `pytest` directly.
3. **Secrets only via `sudo-secretspec run`**: a key never appears in argv, a
   log, a tracked file or a test fixture. The one place a key is written is a
   third-party tool's own credential store (`bin/zcode-key-auth`); presence
   is proved by length or hash, never by printing the value.
4. **`subprocess` gets argv lists, never `shell=True`** (sole exception:
   acp-run's `--verify`, an operator-supplied command). Where a shell string
   is unavoidable (launchd runner scripts, text typed into a pane, printed
   resume and rearm hints) every interpolated value goes through
   `shlex.quote` or `shlex.join`.
5. **macOS and Linux both**: BSD-only calls (`sysctl kern.boottime`, bare
   `sed`) have a Linux path or use the GNU `g*` tool; CI runs `pytest` on
   both.
6. **Records and state files change atomically** (temp file beside, then
   `os.replace`), and every new record field is read with `.get` so older
   records still load.
7. **Dates, not "now"**: a new fact in a doc carries its snapshot date; a
   claim about behaviour matches the code in the same PR (standing order 4).
8. **Docs move with the code**: a flag, exit code or subcommand added or
   changed appears in the tool's usage text and in the doc that lists it
   (`README.md` roster, `docs/*.md`, `skills/*/SKILL.md`).
