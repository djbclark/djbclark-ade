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
| [docs/queue.md](docs/queue.md) | queued work and blockers: check it before proposing new work |
| [docs/threat-model.md](docs/threat-model.md) | threat model (2026-10-20): assets, actors, entry points, ranked threats; read by Codex's security review |
| [docs/git-guard.md](docs/git-guard.md) | `bin/ade-git-guard` and the claim registry (2026-10-24): commands, exit codes 0/2/77, claim lifecycle, refusal rules, override, integration status |
| [docs/gates.md](docs/gates.md) | `config/gates.toml` and `bin/gate-profile` (2026-10-26): the Claude quota gates' numbers in git, floors, a temporary expiring `away` profile |
| [docs/ai-memory-landscape.md](docs/ai-memory-landscape.md) | the six levels of AI memory and their status |
| [docs/coding-factory.md](docs/coding-factory.md) | unattended issue→PR→auto-merge (2026-09-21) |
| [docs/agent-sleep.md](docs/agent-sleep.md) | idle-agent sleep (herdr plugin `plugins/herdr-sleeper`; herdr retired from djbclark-ade 2026-10-31, a record until the D4/D6 drain): check a pane's journal before calling it dead |
| [docs/helm.md](docs/helm.md) | `/helm` ([skills/helm/](skills/helm/)): answer every waiting session from one window |
| [docs/skillopt-sleep.md](docs/skillopt-sleep.md) | nightly skill-edit cycle, `bin/skillopt-night` |
| [docs/failover.md](docs/failover.md) | `bin/failover.py`: reuse it, never hand-roll a fallback |
| [docs/upstream-issues.md](docs/upstream-issues.md) | unfiled bug drafts for third-party projects |
| [docs/mcp-servers.md](docs/mcp-servers.md) | MCP server roster (`claude mcp list`) |
| [.claude/workflows/graph-audit.js](.claude/workflows/graph-audit.js) | runnable micro-graph example, `/graph-audit` |
| [skills/](skills/), [docs/skills.md](docs/skills.md) | canonical copy of every hand-written skill: **edit and add skills here**, never via a TUI path; wrappers in [claude/commands/](claude/commands/) |
| [skills/autorename/workspace-layout.md](skills/autorename/workspace-layout.md) | naming: -pw/-pt Paseo, -t/-p herdr; tab use |
| [skills/paseo-handoff/](skills/paseo-handoff/SKILL.md) | tab lifecycle (2026-10-30): verify the successor's `ParentAgentId` is null, archive the predecessor, tell every sibling and child the new id |
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
5. **Label every heading and item uniquely, so it can be referred to by a
   short typed designation.** Each top-level heading in a reply gets a
   letter (`A.`, `B.`, …); its items are `A1`, `A2`, …, sub-items `A1a`.
   A reply with no headings uses `1.`, `2.`; question-card options are
   numbered too. Each item is labelled once; keep labels stable within a
   conversation (operator, 2026-10-24).
6. **Flag best-practice deviations** and propose the improvement, but don't
   relitigate decisions the operator made knowingly.
7. **Routing discipline**: route per `skills/model-routing/SKILL.md`
   *Routing policy* (`route_agent.py policy --md`), the one copy. The prepaid
   tier stays retired until an operator top-up; the `agent_stats.py burn`
   alert (every 6h, 48h ahead) governs pool exhaustion: the blanket
   clinepass rule was **retired 2026-08-24**. Watch the alert, not the rule.
8. **Upstream every local change to someone else's source** (operator,
   2026-10-24). A fork, vendored copy or local patch: in the same session,
   search the project's issues and PRs for a duplicate, tidy the change,
   consult a `frontier` agent if it helps, then open the issue/PR, so an
   upgrade never needs a merge. Nothing is version-pinned either: software
   tracks its latest release. Detail and exceptions:
   `site-private/memory/feedback_upstream_local_changes.md`.

9. **All development happens in an exclusively claimed task workspace, never in a shared checkout** (operator, 2026-10-25, after the frontier consult in `docs/queue.md`
   "An absolute ... worktree commandment"; it makes ruling 2 of the 2026-10-23 isolation design absolute). Every source edit, stage, commit, build, test and one-line docs
   or queue change, in every repo, happens in a linked worktree (`git worktree add -b NAME ~/src/djbclark-ade-NAME-wt origin/master`, push there, `git worktree remove` it
   after the merge) or an independent cow pasture (`skills/cow-workspaces`), created from a recorded base. `~/src/<repo>` is a reference and integration checkout: it
   may sit on another session's branch or carry its uncommitted edits (2026-10-24: three sessions collided; an L-D branch carried two foreign commits; 2026-10-25: an
   unrelated session's edit sat in this checkout's tree), so nothing is edited or committed there. **One writer at a time per workspace**: a build slice, its repair slice and
   the adversary share it in turn, and only after the previous writer's processes have exited (a reviewer that runs tests is a writer). **Before dispatching a slice into a
   workspace, run `git status` and `git log -3` and stop on an unresolved merge or rebase or a dirty tree you do not own** (2026-10-25: a slice was dispatched into a worktree
   mid-merge; chaining the merge and the dispatch with `;` hid the conflict). **Exceptions, all named**: (a) read-only inspection; (b) a designated promoter's serialized,
   clean, approved `git merge --ff-only` of a primary checkout or `~/ops` master to a published revision (no commit made there); (c) installs, runtime-health and
   non-repository maintenance under a claim on the real target (edit dotfiles and installed tools in their source repo workspace, then install by the normal path).
   No exception because a change is small. **Transitional, `~/ops` only**: until the ops-promotion pilot in the queue entry passes, the `~/ops` plain-`master`
   practice of `~/CLAUDE.md` item 21 stands (deployments read that checkout); every other repo follows this rule now. Enforcement is staged (queue entry): the launcher
   claims the workspace and refuses a launch into an unresolved merge, then `ade-git-guard` refuses `add` and `commit` in shared checkouts, then CHANGELOG fragments end
   the shared-file conflicts; until those land this is the rule, not a guard. Another session's uncommitted edits in a shared checkout are migrated by their owner
   (through `relay.py`), never stashed or reset by you.

10. **A message to another agent is not sent until it is sent through `session-finder/relay.py`, and not delivered until you have verified it** (operator, 2026-10-25:
   "we always need to verify that the other agent got our message otherwise we may be on a broken one-way receive-only link"; the same day an agreement was written
   only in a reply to the sender and never relayed back). Writing an answer in your own turn does not reach a peer; a relayed message from a peer is answered by `relay.py`
   to that peer, not in prose. Read relay's status word: `delivered` is proof, `queued`, `accepted` or `unverified` is not. After a non-`delivered` status
   check the target's transcript or inbox for the text (`--wait S` blocks for it), ask for a named ack (`ack <your agent id>`), and re-send or switch route
   (`--via`) when none arrives. The first message to a new peer always asks for an ack, to prove the return path. A peer you cannot reach is reported to the operator,
   never assumed read. Checklist for the queue: `docs/queue.md`, "Verified peer messaging".

11. **djbclark-ade is the lead's project; ask before changing code anywhere else** (operator, 2026-10-30: "You should ask me before you make changes to any code not
   in your project, which is djbclark-ade."). The lead of this repo edits, commits and pushes in djbclark-ade (and its worktrees and pastures) on its own judgment
   under the orders above; agents it dispatches here act under the same grant, and ask through the lead for anything outside it. Changing **code or configuration** in
   another repository (`~/ops/*`, `sipb-agent-skills`, forgejo projects, third-party forks) or in installed files outside a repository (`~/.local/bin` scripts,
   dotfiles, live plugin or service settings) waits for the operator's explicit yes for that change. Clarified by the operator the same day: (a) installing or
   relinking djbclark-ade's own artifacts by their normal path (`skill-everywhere`, `ade update`) is part of this project; (b) memory notes and instruction-file
   upkeep keep the standing permission `~/AGENTS.md` gives them; (c) once a change to someone else's fork is approved, filing it upstream (order 8) is covered by
   that yes. Order 9 says how a permitted change is made; this order says whether it may be. Reading, reviewing and reporting on code elsewhere needs no
   permission; a fix found there is reported as a proposal, not applied.

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

Readers as of 2026-10-20: Codex (`@codex review`; its Security Review runs with
each code review; on PR 9 its automatic review on PR open answered "create an
environment", the environment-catalog bug that also blocks task mentions),
Cursor's Security Agent and Approval Agent checks, and the `adversary`
sub-agent. A
pull request here is expected to meet these; flag any it misses.

1. **The PR body carries the adversary's verdict as a MACHINE-READABLE MARKER**, naming the head it
   reviewed:

   ```
   <!-- adversary-verdict:v1 {"verdict":"APPROVE"|"BLOCK","head":"<40-hex>"} -->
   ```

   **Flag the PR if the marker is missing, malformed, says BLOCK, or names a head other than the
   current one.** `pr-wait`'s report-only default is a property of the *tool*, not of this rule: it
   blocks on a missing, other-head or BLOCK marker only when it is asked to, with
   `--adversary-required` or an `adversary-required` label on the PR.

   `pr-wait` reads that marker and reports it as `adversary` / `adversary_warnings`; it does **not**
   read prose, so **prose verdicts do not count**. The first version parsed English and **two**
   adversary rounds found false approvals and false misses, including a BLOCK silently deleted by a
   prose filter, so that parser was deleted rather than patched; a third round, on this marker design,
   found that a shortened head let a BLOCK be stripped away (fixed in PR 66). Match the `:v1` suffix,
   as rule 9 does for `codex-review-state:v1` — a non-`:v1` `adversary-verdict:` marker is
   **malformed**. Five more properties worth knowing:

   1. **An APPROVE must be live, and a BLOCK naming the current head counts wherever it appears** —
      the raw body included, whether the head is the full 40-hex sha or a 7+ hex prefix of it, with or
      without a trailing `…`/`...` — so no code-fence or stripping bug can hide one. "Live" means
      outside the two shapes `pr-wait` blanks: a **fenced block whose fence sits at indent <= 3**, and
      a **single-line inline span**. Three shapes it does not blank read as live too, so an APPROVE
      quoted there counts: a 4-space **indented code block**, a **fence inside a blockquote**, and an
      **inline span broken across a line** (documented limit, `_strip_code`'s C1a/b/c note; it only
      misfires when a human pastes our own template). The asymmetry is deliberate: documentation
      cannot approve, and a BLOCK cannot be hidden.
   2. **The `verdict` value is exactly `APPROVE` or `BLOCK`, in capitals, and an APPROVE's `head` is
      the full 40-hex sha** (a BLOCK may be shortened, property 1). Anything else is **malformed**, and
      `malformed` always blocks: `approve`, "APPROVE, no findings", an APPROVE with any shortened sha
      (a bare `…`/`...` head is the template's placeholder instead, and approves nothing — property 3),
      a BLOCK whose shortened head is not a prefix of this head. A **full 40-hex sha of another commit
      is not malformed**: it is a verdict for a different head, reported as other-head and report-only
      (property 4).
   3. **An APPROVE inside a fenced block or a single-line inline span, or an APPROVE whose head is the
      template's `<40-hex>` placeholder, is documentation and is ignored.** That is what lets a PR
      describe this format without tripping its own gate: nothing in those two blanked shapes can
      approve, and a placeholder approves nothing. A BLOCK is never skipped this way (property 1), and
      a **live** BLOCK whose head is the placeholder is `malformed` rather than documentation; a BLOCK
      in code that does not name this head is documentation too (the accepted limit in `_strip_code`).
   4. **`malformed` and `adversary-fetch-failed` always block**, with or without the opt-in — a
      missing, other-head or BLOCK marker is reported only. Fail closed on an unreadable verdict;
      report a readable bad one.
   5. **The marker's JSON is delimited by its own braces, not by the first `<!--`** (2026-10-27): a
      `note` may quote the format, and a body that documents the marker is not read as a second
      mistyped one. The marker's JSON must also be written where `pr-wait` reads it live — a marker
      whose JSON is partly inside a code span is **malformed**, never approved, because masking code
      cannot "repair" JSON nobody wrote.

   Whoever merges uses `gh pr merge --squash --match-head-commit <reviewed sha>`, so the head reviewed
   is the head merged.
2. **No exit status or result through a pipe**: `cmd > out.log 2>&1; echo
   "rc=$?" > out.rc`, never `cmd | x; $?`. Local test runs go through the
   operator's `bg` wrapper and `bin/pytest`
   (`bg bin/pytest -q tests/test_x.py`: the bare `python3` has no pytest); CI runs `pytest` directly.
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
   Linux, and on macOS only on request (a manual `Tests` dispatch with the `macos` input, 2026-10-29).
6. **Records and state files change atomically** (temp file beside, then
   `os.replace`), and every new record field is read with `.get` so older
   records still load.
7. **Dates, not "now"**: a new fact in a doc carries its snapshot date; a
   claim about behaviour matches the code in the same PR (standing order 4).
8. **Docs move with the code**: a flag, exit code or subcommand added or
   changed appears in the tool's usage text and in the doc that lists it
   (`README.md` roster, `docs/*.md`, `skills/*/SKILL.md`).
9. **Read Codex's result against the head and the open threads, never against a guessed
   clock**: the summary comment's `codex-review-state` names the `commit_sha`
   it covers (for `code_review` and for `security_review`, each read the same way). The findings for that head
   are the Codex inline comments
   (`gh api repos/.../pulls/N/comments`, author `chatgpt-codex-connector[bot]`,
   ending in a finding mark: `codex-code-review-finding:v1` or `codex-security-review-finding:v1`) anchored to it (`original_commit_id`, or the
   `commit_id` of their review in `pulls/N/reviews`), PLUS every unresolved Codex
   review thread from an earlier head, security threads included: a finding stays open until its thread is
   resolved. GraphQL `reviewThreads.isResolved` is the authority, and the marker's
   `has_unresolved_findings` (per review) must agree with it (a disagreement is chased, never
   read as a clean "0"). Case (2026-10-23): on PR 32 Codex left a P1 on head
   3c40470, two pushes followed without the fix, the marker for the new head said
   `has_unresolved_findings: true`, and a head-only filter read "0" past the open
   P1. Check with `bin/pr-wait`: `merge_ready` (false with the reasons in `merge_blockers`) and
   `PREFIX-open-findings.json`.
   Fixing a finding means fixing the code, then resolving its thread. Never select
   by time: a "newest `@codex review` comment" window is moved by Codex's own
   receipts, which quote it (PR 12, 2026-10-20). GitHub re-anchors `commit_id` to the newest head when
   the line is unchanged, so `commit_id` alone cannot tell old from new. A
   waiter that filtered by a hard-coded timestamp missed two findings on
   PR 10 (2026-10-20) and the PR merged past them. The state marker's exact
   form (2026-10-20): `<!-- codex-review-state:v1 {"code_review":
   {"commit_sha":…,"status":"completed",…},"security_review":{…}} -->` on
   the comment that also carries `<!-- codex-pull-request-review-summary -->`;
   that comment is posted at request time and edited in place, so match the
   marker with its `:v1` suffix and read `code_review.commit_sha`, never the
   comment's `created_at`. Each inline finding ends with
   `<!-- codex-code-review-finding:v1 -->`. A waiter whose regex lacked the
   `:v1` suffix saw no state on PR 12 and ran its full 30 min.
10. **The PR adds its line to `CHANGELOG.md` under `Unreleased`** (since 2026-10-20, djbclark:
    "people should know what changes or new features are added"): one line per user-visible
    change (a new or changed command, flag, skill, exit code, service or rule), in the past
    tense, ending with the PR number; `Added`, `Changed`, `Fixed`, `Removed` or `Security`.
    Internal refactors and doc-only edits may skip it; flag a PR that changes behaviour and
    carries no entry.
11. **Codex's review may be the LOCAL one** (2026-10-29, djbclark: "could we just switch to making codex reviews run locally in general"; GitHub's
    Codex review hung on PRs 112 and 124, openai/codex#55890). `bin/local-review PR` runs `codex review --base <base sha>` in a clean detached
    worktree at the exact head and files `~/.local/state/local-review/<owner>__<name>-pr<N>-<head>.json` (exit 0 clean, 1 findings, 3 failed); `bin/pr-wait PR
    --local-codex` then reads that file instead of waiting on the bot (implies `--no-codex`) and makes `merge_ready` need `clean` on THIS head, else the blocker
    is `local-codex-missing`, `-findings`, `-failed` or `-unreadable`, never `codex-skipped`. A push needs a new run: the head is the key, so another head's review
    is never read. Any finding of any priority blocks (fix the code, run it again); a clean local result plus CI plus the adversary verdict is a
    merge-ready PR without the bot, and the PR body quotes the summary line (head SHA and counts). Item 9 still governs the GitHub bot's own review and its open
    threads, which `pr-wait --local-codex` still counts as `open-findings`. `bin/local-review` refuses (exit 2) a PR whose author is neither the repository owner
    nor the authenticated gh user unless `--allow-untrusted`: the PR's own diff and AGENTS.md can steer the reviewing model (Codex Security Review, PR 130); a result filed with `--allow-untrusted` is accepted by `pr-wait --local-codex` as the operator's call.
