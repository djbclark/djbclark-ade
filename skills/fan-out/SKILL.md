---
name: fan-out
description: >-
  Slice parallel work, assign owners and verify reports. Prefer native Paseo agent/workspace
  operations (the Wave 6 dispatch shims were deleted 2026-11-14). Use for "fan this out",
  "parallelize this", or an explicit delegation request. Select the destination host for remote work.
---

# fan-out: slice the work, hand it out, collect the reports

Canonical copy: `~/src/djbclark-ade/skills/fan-out/` (edit it there, never through a TUI path).

## Preferred transport (2026-11-07)

Use native Paseo `create_agent` / `paseo run` for new slices, preserving the routing, claimed
workspaces, report and review requirements below. For another computer, select its host explicitly and
transfer any needed files before launch; a local brief/report path is not shared storage.
See [old way versus new way](../../docs/old-way-new-way.md), including plugin advice and the
cross-host acceptance checks. Keep `{serverId, agentId}` together and prove receipt with an ack.
For native MCP directory results, prefer `structuredContent` and filter to the relevant IDs/fields before emitting output;
`content` often duplicates the same roster. Do not print an entire workspace/agent directory to select one entry.
CLI schemas differ: `paseo ls --json` uses lowercase `id/provider/status`; `agent inspect --json` uses `Id/Provider/Status`.
Do not reuse inspect-field casing to conclude that a list contains no running model/agent.

For Codex tool orchestration, preserve the **whole command result**:
`const r = await tools.exec_command(args); text(r);`. Printing only `r.output`
and `r.exit_code` drops a yielded `session_id`. A yielded command is still
running; resume that exact session with `write_stdin`, forwarding its full
result too. Undefined `exit_code` is not completion or failure. Put this rule
in mechanical/probe briefs even when a deliberate READY-only task uses
`--no-footer`. If a caller already lost the handle, inspect the named owned
PID or durable result/exit artifact; never restart a possibly live operation
or replace its stable ID merely to recover visible output.
For CI, copy workflow IDs/paths from `gh api repos/OWNER/REPO/actions/workflows`
or the workflow/run listing. Do not guess a filename such as `tests.yaml` from
the display name; use a discovered run ID for status and logs.
Recipe detail: [docs/orchestration-practices.md](../../docs/orchestration-practices.md).

## 1. Slice first

Cut the work into slices that touch disjoint files, each with one owner and a check you can run on its result
(a test, a diff, a report section). Shared files (a changelog, an index) stay with the lead. Pick each slice's
agent and model with `~/src/djbclark-ade/bin/route_agent.py plan --kinds KIND` (kinds and pools:
`skills/model-routing/SKILL.md`). Every brief ends with the shared delivery contract,
`docs/dispatch-footer.md`: a report file whose last line is `DONE`, a `.done` marker touched last, and
`BLOCKED: <question>` as the first line instead of a question at the end of a turn. Paste the filled
footer into every Agent-tool or `paseo run` brief (`{report}`, `{lead}`, `{done}`, `{inbox}`, `{replies}`);
`agent_footer_gate` appends it when an Agent-tool prompt lacks it.

**Search first and last (operator, 2026-11-13; footer rule 24).** Every brief carries a required line:

```
Prior art / docs checked: <what was searched, with which tool, and what was found, or "none">   (exempt: "exempt: mechanical", or "exempt: <reason>" when no search could change the answer)
```

The lead fills it by searching before it writes the brief (shared `mcp__firecrawl__*` first, Context7 for library docs, `WebFetch`
as the fallback; `~/CLAUDE.md` item 7) and the worker repeats it in its PR body. Every non-exempt report then has a **`Closing search:`**
field above its final `DONE` line: the search run last against what was built (current docs, changed APIs, new upstream fixes, prices and model ids). Exempt, stated in the line and the field: mechanical edits, and slices no search could change (read-only status probes, reviews of a given diff). The
lead treats a non-exempt report without it as unfinished, and a reviewer flags a non-exempt PR without the line (`docs/code-review.md` rule 12).

## 2. In process: the Agent tool or a Workflow

For lookups, reviews and edits that fit this session's worktree, use the Agent tool (one sub-agent per slice,
launched together) or a Claude Code Workflow (`/graph-audit` is a worked example). Paste the footer into
each prompt (see `docs/dispatch-footer.md`). Read the report file, never the
sub-agent's final message: the harness cuts that at 4,000 characters.

## 3. Out of process: a slice in its own worktree

A slice that edits code gets its own linked worktree (AGENTS.md order 9:
`git worktree add -b NAME ~/src/<repo>-NAME-wt origin/master`); the slice works in that worktree (its absolute path is in
the brief) while its Paseo session sits in the lead's WORKER box (below).
Before **each** `paseo run`, and again before each wave, the launcher runs `~/src/djbclark-ade/bin/load-watch admit --wait N --max-agents --json`
(N in 300-600; machine capacity, not service quota; full path: `load-watch` is not on PATH, and a bare call fails with 127 so the check silently never runs;
a wait that may exceed 10–15 seconds runs in the background with durable stdout, stderr, PID and terminal status; its outer/subprocess timeout must exceed `--wait` by at least 60 seconds. Never wrap a 420-second admission wait in an 8-second timeout. A timeout is UNKNOWN, not refusal or admission: inspect any reservation before retrying and never launch from a partial result. Detached router preflights also need a terminal exit artifact before reading their output; write live progress to a separate `.progress.json` and atomically publish `.result.json` only at termination, not as an in-flight status file. Never assume the default `plan` output is JSON merely because its filename ends in `.json` (use the documented `--json` flag). Then **exit 0 = go, any other exit** (75 = refused, 2 usage, 127 missing) = launch nothing and report; exit 2 is also what a `load-watch` from before 2026-11-14 answers to a flag it does not know, such as `--refused-since EPOCH` ("unrecognized arguments"): a launcher that hands its hold start over with that flag must drop it and retry without it, or report, never treat the exit as a refusal to wait out). `--max-agents` is the live-agent cap, 20 by default (`LW_MAX_AGENTS`),
and it records a reservation: once the agent has spawned, or the launch failed, run `~/src/djbclark-ade/bin/load-watch release <reservation>` (the `reservation` field of the JSON; exit 66 for an unknown id (released over 30 s ago, or expired) is harmless, exit 1 is a lock or write failure (the slot is held until `LW_RESERVE_S`); a launcher that is the only dispatcher on the machine
may pass `--no-reserve`), or the slot is counted twice for 20 minutes (after a failed launch, held as a phantom). The cap is a soft gate: after 300 s of refusal the starvation valve lets one launch through
(one per 120 s machine-wide; docs/orchestration-practices.md rule 4); `--wait 0` gives a strict check. Then take a fresh `route_agent.py plan --kinds KIND` per slice (model-routing D5)
and launch with `Choice.dispatch` unchanged: no extra `--model`, provider or credential flag. Pass the placement to the plan
(`plan --kinds KIND --lead <your id> --slice <name> --cwd <the window's directory, ~/src/<repo>> [--window-middle <work>]` (`--window-middle` is optional: only the `(<work>)` text of a box the launch opens), `--slice` once per
kind; `--lead` defaults to `$PASEO_AGENT_ID`), and its `dispatch` is already an `ade-worker-run` line (section 3): a bare `paseo run`
puts the worker in the caller's own workspace, since Paseo ignores `--cwd` (getpaseo/paseo#9699, #4125). A plan that lacks a
lead or slice keeps a quoted `'<lead>'` / `'<slice>'` placeholder in the line and names it in `dispatch_warnings` (JSON) and on stderr: fix it, never launch it; a missing `--cwd` is advisory (only a lead's first launch takes the current directory). The line is a complete shell command with an absolute launcher path: paste it into the command as it is, then add the labels and the brief (not `$VAR` expansion: a quoted window name would split). Since the dispatch shim left (2026-11-14) no code enforces the load gate, the cap,
the model pin or the per-wave re-check, and no code reserves quota (`docs/slim/log.md`, "Wave 6 follow-up"); they are this instruction.

```bash
# Before EACH launch: ~/src/djbclark-ade/bin/load-watch admit --wait 420 --max-agents --json   (exit 0 only; keep .reservation)
# Re-plan immediately before EACH launch when several slices share one quota pool
# (plan/pool_fits do not yet reserve sibling in-flight usage; see model-routing D5).
ade-worker-run --lead LEAD --slice NAME --cwd ~/src/<repo> -- \
  --provider PROVIDER/MODEL --no-wait \
  --label ade.kind=KIND --label ade.name=NAME --label ade.task=TASK \
  "$(cat brief-with-footer.md)"
# Then (also if the launch failed): ~/src/djbclark-ade/bin/load-watch release <reservation>
# ade-worker-run adds the placement (the WORKER box), --label ade.lead=LEAD and --label slice=NAME (below); by hand that is
# `paseo run … --workspace wks_… --cwd ~/src/<repo> --label ade.lead=LEAD`, or --new-workspace local on the first launch
```

A worker that judges untrusted GitHub artifacts for prompt injection (injection triage, reading an outside PR, issue or comment) takes
`--label ade.kind=external-review` as its `ade.kind` (set it, replacing the dispatch's own value when it has one; never a second label): the peer-trust hook then frames its messages and notifications as evidence, not instruction
(docs/orchestration-practices.md section 3).

`--label ade.lead=LEAD` (LEAD = the lead's own full agent id) is mandatory for every worker, and above all for a
top-level worker the lead starts with `env -u PASEO_AGENT_ID -u PASEO_AGENT_CWD -u PASEO_WORKSPACE_ID paseo run …`:
such a worker has no parent link to the lead, so `bin/ade-auto-permit` can only recognise it by this label
(2026-11-13: worker 2c54cedf, launched env-stripped without the label, stalled 1h40m on a Bash permission prompt
that the watcher skipped as `outside-scope`).

**Placement: at most three windows ("boxes") per lead and repo, LEAD, WORKER and OTHER; tabs go in the fitting box (operator ruling, 2026-11-14, to the tendcf lead ae1f6d65, verbatim: "Close any unneeded tabs and any unneeded workspaces you or your predecessors have made. In the future, have at most LEAD, WORKER, and OTHER workspaces and put tabs in the appropriate box. The tabs can mention the worktree they are in."; supersedes the 2026-11-13 one-WORKERS-window-per-lead, MAIN, USER names; naming and limits in `docs/workspace-layout.md`).** Window names are `<KIND> <repo> (<work>)`, KIND `LEAD` (the lead's own, was MAIN), `WORKER` (every worker and reviewer you start yourself, was WORKERS) or `OTHER` (probes, side tasks, operator-started agents you were connected to, was USER); the lead id is not in a window name.
The env-stripped launch has no caller workspace, so each `--new-workspace` launch made its own "master" window (11 piled up; a window per `--window-middle` text then piled up one per slice, tendcf 9, djbclark-ade about 15; archiving an agent keeps its window). `bin/ade-worker-run` does the whole recipe, so use it for every worker:

```bash
ade-worker-run --lead LEAD --slice NAME [--window-middle "Wave 7"] [--repo NAME] [--cwd ~/src/<repo>] [--worktree <slice worktree>] [--no-footer] -- \
  <the paseo run arguments of the launch above: --provider … --mode … --no-wait "$(cat brief-with-footer.md)">
# a worker the OPERATOR asked you for interactively ("open a new sonnet tab to …"): a tab in your own LEAD window
ade-worker-run --lead LEAD --slice NAME --placement lead -- <the same paseo run arguments>      # alias --interactive
# a probe or side task: the OTHER box
ade-worker-run --lead LEAD --slice NAME --placement other -- <the same paseo run arguments>     # alias --other
ade-worker-run rename-lead --lead LEAD [--window-middle "Wave 7"] [--repo NAME]   # once: name your own window LEAD <repo> (<work>); alias rename-main
```

1. It strips `PASEO_AGENT_ID`, `PASEO_AGENT_CWD` and `PASEO_WORKSPACE_ID` and finds the lead's **one WORKER box of the repo by
   ownership evidence** (window record, a live agent labelled `ade.lead=<LEAD>`, or a legacy name carrying the lead id), **whatever the
   slice and whatever `--window-middle` says** (`<repo>`: `--repo`, else the repo of `--cwd`, also from a linked worktree). A successor
   of a completed self-handoff reuses the box its predecessors made. Two matches, or a match holding a live agent labelled for another
   lead, are refused. A 2026-11-13 or legacy window of this lead (`WORKERS <repo> (<work>)`, `workers <middle> <LEAD>`) is renamed to the
   current form first (same window id). It passes `--workspace` of the window plus `--cwd` (the window's own: a different `--cwd` is refused, because Paseo ignores it with `--workspace`, getpaseo/paseo#9699; the launched agent's `Cwd` is checked afterwards and a worker that landed elsewhere is stopped). With no box yet, the first launch mints one
   (`--new-workspace local --cwd ~/src/<repo>`), reads its id from the launch (JSON `workspaceId` if paseo prints one, else the
   single `Created workspace wks_… - <name>` stderr line, cross-checked with the agent's state file; absent or ambiguous
   fails closed and names the launched agent) and renames it `WORKER <repo> (<work>)`. **`--window-middle` is optional** (default `workers`):
   it is only the `(<work>)` text of a box this launch opens, and a picker when the lead owns several boxes of the repo; it never opens a
   second box, and an old invocation that passes it keeps working. Pass `--cwd ~/src/<repo>` (default: the current directory). A box of
   another repo is not this launch's: a launch for a repo the lead has no box for opens that repo's box.
2. It adds `--label ade.lead=<LEAD>` and `--label slice=<NAME>` itself (so do not pass them, nor `--workspace`,
   `--new-workspace`, `--cwd`, `--dir`, `-C`, `--host`, `--home`, `-o`/`--format`, `-q`/`--quiet`), renames the tab
   `worker <NAME> <LEAD>` with `paseo agent update` (**the tab may mention its worktree**: `--worktree <dir>`, or a `--cwd` that is itself a
   linked worktree, appends ` [wt: <worktree dir basename>]`, shortened to fit 100 characters; a hint, the brief still names the absolute path;
   the OTHER box's tabs start `other `), and prints one JSON line `{agentId, workspaceId, windowName, tabName}`.
   The arguments after `--` are `paseo run`'s own: flags first, then the brief; no leading `paseo run` (the bare
   `paseo run` template that `route --kind K` prints starts with it; `plan`'s `dispatch` is already the whole `ade-worker-run` line
   (rd-01, 2026-11-14), so run it as it stands and append only the brief); no bundled short options
   (`-qd`); and `--no-wait` is required. It holds a per-lead lock while `paseo run --no-wait` returns, so launches and
   `archive-window` of one lead never interleave. `--lead` must be the caller's own agent id: when `PASEO_AGENT_ID` is set
   and differs, both forms refuse unless `--on-behalf-of-lead` is passed (a stale id in a brief would otherwise place, label
   or archive another lead's workers). The brief still names the writer's claimed worktree as an absolute path, and `bin/ade-worker-run` checks the PROMPT ARGUMENT itself for it, only when the worker would start outside `--cwd` (a launch into a box whose cwd is the primary checkout, not `--placement lead`): a brief file that the prompt only points to does not count (a path to a brief inside the worktree does), and that launch is refused (2026-11-21, a lead hit this); put the absolute worktree path in the prompt text. The helper
   appends one line to the brief (the last argument): `Also follow every item of <repo root>/docs/dispatch-footer.md.`
   (skipped by `--no-footer`; refused when the last argument is not recognisably the brief). It does not replace writing
   the footer into the brief (2026-11-13: lead-written briefs omitted it and a worker pushed a changelog fragment with no
   `###` heading).
   `--placement lead` (aliases `main`, `--interactive`) is for a worker the operator asked you for in the chat: it launches a tab into your
   own window (resolved from your own agent record, not `PASEO_WORKSPACE_ID`; you must be the caller), which must be named
   `LEAD <repo> (<work>)` (`rename-lead` names it; a `MAIN …` name is renamed on the first such launch), labels it
   `ade.placement=main`, and never archives it. `--placement other` puts the worker in the OTHER box (label `ade.placement=other`).
3. When the run ends, archive the agents, then `ade-worker-run archive-window --lead LEAD [--placement worker|other] [--window-middle …]
   [--idle-handled]`: it runs `paseo workspace archive` only if every live agent labelled `ade.lead=<LEAD>` is closed (or
   idle, with `--idle-handled` once its report is handled), no other live agent sits in the window, and the window is this
   lead's WORKER (or OTHER) box (current or legacy name); otherwise it lists the blockers and archives nothing (`--dry-run` to only
   check). It archives only a window it can show is this lead's (window record, labelled agent, or legacy name with the lead id), never one found by name alone; a LEAD- or OTHER-placed worker in another window does not block it. A LEAD window is never archived. Extra windows a chain left behind
   (a second WORKER window, a window named outside the scheme) are listed by `bin/ade-tidy` (section H) and archived by `--apply` when empty or finished.

By hand (what the helper does; a hand-made window has no ownership record, so `archive-window` will not archive it until a helper launch adopted it while empty): the same strip, `--new-workspace` on the first launch only, the window id taken from the
launch and never guessed by cwd or name, `paseo workspace rename`, `--workspace wks_…` on later launches, `paseo agent update
<full agent id> --name "worker <NAME> <LEAD>"`.

A handoff **successor** is a new lead, not a worker: it starts as `skills/handoff` says (its own top-level `paseo run`), keeps
its own placement (its own LEAD window), and reuses the chain's WORKER and OTHER boxes when it dispatches (it opens none beside them).

Always pass the provider-native unattended mode at launch (Codex `--mode full-access`): switching with `set_agent_mode full-access` mid-run did not stop repeated approval cards for graft MCP, commits, pushes, gh or bg tests on 2026-11-12; Pi exposes no selectable modes and omits the flag.

Take `Choice.dispatch` from a **fresh** `route_agent.py plan --lead … --slice … --cwd …` **as-is** (an `ade-worker-run --lead … --slice … -- --provider …` line,
rd-01, 2026-11-14; `route --kind K` still prints the bare `paseo run` template, which places nothing), then append
only extra labels and the positional brief (`paseo run` has no `--prompt-file`). Write the footer into
the brief yourself. For parallel same-pool waves, re-plan (or stagger) so combined floor estimates stay under remaining. Create a workspace only with native `paseo workspace create` or
`paseo run --new-workspace …` when deliberate — ordinary dispatch never mints workspaces; the one routine mint is the
lead's first launch of a run, which opens its WORKER box (above).
As verified on 2026-11-07, agent-origin runs, or runs with `PASEO_WORKSPACE_ID` set, must explicitly select a workspace:
`--cwd` alone inherits the parent agent's workspace and directory. Pass `--workspace` (validated against
`paseo workspace ls --json` and `-C` / `--cwd`) and never emit `--new-workspace` on an ordinary launch.
With a caller, unreadable or missing workspace metadata refuses instead of using the ambient workspace.
Paseo 0.15.3 native inspect omitted workspace ids when checked on 2026-11-08; pass `--workspace` explicitly.
Only a launch without `PASEO_AGENT_ID` may use `PASEO_WORKSPACE_ID` as its fallback.
Verify returned `cwd` and `workspaceId` against the assignment before treating a launch as correctly placed.

For a review slice: Claude runs through `bin/review-launch` (the enforced review boundary; `--mode trusted`, YOLO, only for work the
operator (`djbclark`, not the repository owner) authored and pushed the head of, which `bin/review-pr --runtime auto` decides, 2026-11-12). A direct trusted launch needs all of
`--trusted-author <owner's GitHub login> --head <40-hex sha> --schema config/review-schema.json -C <clean worktree>`, else it
refuses with exit 2; give each attempt a fresh `--evidence-dir`. Never use it for input the operator's login did not author: the
launcher does not check the login, it only records it. Every other agent
runs best effort, in its provider-native unattended mode with a brief note to change nothing (launch-mode correction 2026-11-12; review brief ruling 2026-11-07).

The workers-window rule (2026-11-13) replaced the operator's temporary all-tabs-with-the-lead arrangement of 2026-11-07;
naming, limits and `cwd` are in `docs/workspace-layout.md`. Session cwd is the WORKER box's `cwd`, while every writer's
brief names a separate claimed execution worktree and every repository tool call targets it explicitly. Never turn a
report folder into a workspace.

Claiming a worktree for a worker (2026-11-21, queue 87): from inside its worktree, one line is enough,
`~/src/djbclark-ade/bin/ade_claims.py new --path <worktree> --owner-agent <worker Paseo id>` (with no owner flag it takes `$PASEO_AGENT_ID` when that is a Paseo id, else exits 2; it never makes an ownerless claim. An in-process sub-agent inherits its parent's id, so it passes its own `--owner-agent`). A Paseo agent id as
`--owner-agent` also becomes `--owner-record`; `--branch` and `--base-sha` come from the worktree's `HEAD`; `--id` is
generated (the printed claim file's name without `.json`; pass that to `release --id`), so a re-claim after `release` needs nothing new from you (a released claim keeps its id, and an explicit
`--id` that exists exits 3 telling you to omit it). Running it again for the same worker and path supersedes that worker's own active claim (the older is released). Exit 2 means the path is not a git worktree: pass `--branch` and `--base-sha`.

## 4. Collect

- **Re-tasking a worker whose round is finished:** rename its `<report>.done` to `<report>.done.rN` before the `paseo send`
  (`skills/tidy` archives a worker only on a current `.done`; a re-task it cannot see could be archived mid-round).
- `paseo wait <id> --json` blocks until the agent is idle; classify by the report / `.done` artifacts
  (same meanings as orchestration-practices §5): 0 DONE, 1 unfinished / still running, 3 no report,
  4 BLOCKED (or a pending permission), 124 timed out. Poll with short `paseo wait` / `paseo ls` looks when
  you must not block.
- A lead's background waiter on a worker's done marker passes an explicit timeout:
  `~/src/djbclark-ade/bin/wait-file --timeout 7000 /ABS/<report>.done` with the Bash tool's `run_in_background: true`
  and `timeout: 7200000`. The 1200 s default ends before most code slices finish (2026-11-20: a Move 2 waiter exited 124
  while the worker was still testing); a 124 is not a failure, so check the report's `STATUS:` line and re-arm.
- `paseo ls -a -g --json` (filter on your `ade.*` labels) classifies every slice of the task at once
  against its report paths.
- `paseo ls -g --label ade.task=TASK` shows what runs; `paseo permit ls` the permission cards.
- `paseo send --json --no-wait <id> --prompt "…"` reaches a running slice (`accepted`,
  exit 5, is not proof of delivery: ask for an ack).
- **Push on completion (2026-11-09, updated 2026-11-12):** after a slice writes `DONE` and touches `{done}`, it must
  `paseo send --json --no-wait` its requester `done: <title>, <PR URL>` (or
  `done: <title>, <status>[, <report>]`) plus `Please reply: ack <your agent id> <msg-id>`
  (footer rule 22). Prefer `bin/completion-notice --send --requester <lead-id>
  --title TITLE --pr URL` (or `--status` / `--report`) so the shape stays exact.
  This is for `paseo run` slices. An Agent-tool sub-agent (its `{lead}` is `main`) skips it: the Agent tool returns its final
  message, and `completion-notice --send --requester main` is a no-op (2026-11-13).
  The worker ends its turn immediately after sending. Requesters prove delivery via dual routes (operator ruling 2026-11-12):
  (a) prompt `ack <worker id> <msg-id>` sent via `paseo send` only once `paseo agent inspect <id> --json` confirms status is `idle`;
  (b) atomic write of `{done}.ack` on disk next to the worker's done file (`bin/completion-notice --lead-ack --worker <id> --msg-id <msg-id> --done <done-path>`).
- Verify each result against the artifact (the diff, the tests), then record outcomes for
  `route_agent.py calibrate` (ci / review / merged fields in the measured history).

## 5. Worked example

Three independent fixes in one repository, one review:

1. Lead writes `a.md`, `b.md`, `c.md` (one owner per file set, the check each slice runs) and three
   worktrees `~/src/r-a-wt`, `~/src/r-b-wt`, `~/src/r-c-wt`.
2. For each slice, take `route_agent.py plan --kinds code --lead <lead id> --slice <name> --cwd ~/src/r`'s `Choice.dispatch`
   (`ade-worker-run --lead <lead id> --slice <name> --cwd … -- --provider … --no-wait`) and run it with
   `--label ade.name=<name> --label ade.task=fixes` appended
   plus the positional brief (agent and model from the plan; the brief names the slice's worktree `~/src/r-<name>-wt`
   as an absolute path).
3. While they run, the lead does its own part (standing order 3), then `paseo wait` on each agent id.
4. A BLOCKED report: answer with `paseo send --json --no-wait`, or re-brief under a new `--label ade.name=…`.
5. Each DONE slice: review its diff, push its branch, open the PR; one read-only review per PR through
   `bin/review-launch` (Claude) or a judgment `paseo run` brief that says change nothing, in the same
   WORKER box, its brief naming the slice's worktree.

## 6. Avoid operator permission cards (2026-11-12)

Always launch our own Codex agents with `--mode full-access`, Claude with
`--mode bypassPermissions`, and Antigravity with `--mode full-access`.
`CATALOG_MODE_ID` is an exact ID from the target provider catalog, never a display label.
For Pi, ClinePass, or any provider with no modes: **omit --mode**, including
`--mode default`. Add `--mode CATALOG_MODE_ID` to the example only when the provider exposes that exact ID.
`ade-worker-run` drops explicit modes for a ready modeless catalog with a stderr note;
unknown, unavailable, or malformed catalogs fail before launch when a mode is requested.
If the CLI supplies only nonempty display labels, existing explicit modes pass through
with a validation-limitation note; Paseo validates the ID, and failed-create cleanup applies. Set it at
creation; changing a running agent's mode did not reliably remove old cards.
The locally inspected `ProviderOverrideSchema` has no provider default-mode field.
Omitted modes inherit same-provider parents, or fall through to the provider
for a top-level interactive run (`create-agent-mode.ts`). Do not invent keys
in `~/.paseo/config.json`; no config change or restart is required by this helper.
The Claude enforced review boundary remains separate (`bin/review-launch`).

`bin/ade-auto-permit --lead FULL_LEAD_UUID --log /absolute/path/permits.jsonl`
runs one sweep. The lead itself is excluded even if it matches an ADE label.
Add `--watch --duration 3600 --interval 2` for a bounded watcher.
It allows only descendants of the named lead (not the lead itself), agents whose
Paseo labels include `ade.lead=<that lead's id>` (audit reason `lead-label`; checked by default, no flag
needed, so a lead's env-stripped top-level workers qualify), or agents
matching a repeated `--ade-label ade.KEY=VALUE` selector. Any matching selector
qualifies. The installed Paseo inspect/ls JSON omits arbitrary labels; exact server-side
`ls -a -g --label` filters prove selected labels. A wildcard `ade.*` scan is
not available through this CLI. Supply the labels used by the wave, for example
`--ade-label ade.task=wave7`. Titles, cwd and provider names confer no authority.
Labels are trusted local-agent scope markers, not an external security boundary.

`--all-local` (the checked-in launchd template passes it; operator, 2026-11-13) also admits every agent the local
daemon lists, the lead included (audit reason `all-local`; no `--host`, so no remote agent). In every mode a question
or plan approval for the operator (`AskUserQuestion`, `ExitPlanMode`, Pi/OMP `select|input|editor|confirm`, similar
names; a best-effort name denylist, missing names fail closed) is logged `skip` / `operator-question` and left pending,
and agents of providers outside claude/codex/opencode/pi/omp (ACP-backed) keep their prompts (`unclassified-provider`). An agent labelled `ade.kind=external-review` (it reads outside GitHub text, so a steered one could ask for anything) is never approved, in any mode, and neither is its descendant: logged `skip` / `sensitive-sender`, its requests stay for the lead or the operator. Only that label counts: config/peer-trust.toml ids and title patterns are not read here, and no launcher sets the label yet, so today an unlabelled triage agent is still approved; a child that merely carries `ade.lead` is too, so a worker such an agent launches the normal ADE way (top-level through `bin/ade-worker-run`) is still approved; a child whose Paseo parent chain passes through it is held only if it also lacks `ade.lead=<a lead in the lineage>` and a matching `--ade-label` (those are checked before ancestry).

Only explicit pending `(agentId, requestId)` pairs are allowed; no `--all`.
Failed/malformed discovery fails closed. JSONL records skips, attempts, confirmations
and errors, without tool descriptions, arguments or CLI error bodies. Failed or
unconfirmed writes are never retried through another surface; a later watch sweep
can retry only if the request is still listed pending. Watch checks its deadline
before each sweep; a sweep already running may finish after the deadline. Watch
cycles recheck ancestry and labels; a per-log lock prevents overlapping instances
sharing a log.
Use one log per daemon/wave; do not run competing watchers with different logs.
No daemon restart, installed configuration change or scheduler activation occurs.

Codex full-access maps to `approval_policy = "never"` and
`sandbox_mode = "danger-full-access"`. MCP approval settings are separate:
`mcp_servers.<server>.default_tools_approval_mode` and
`mcp_servers.<server>.tools.<tool>.approval_mode` (`"approve"` preapproves a tool).
Paseo's `applyCodexToolPolicy` explicitly writes per-tool approval values for its
preapproved tools. Inspect those when a graft card persists; this helper does not
edit `site-private`'s `codex/config.toml` or broaden MCP tool policies.

Before committing or pushing a changelog fragment whose bullets carry real PR numbers, run `python3 bin/changelog-fold --repo . --check` and inspect its exit status. A failed check stops the dependent commit/push; fix the fragment first. Fragments require a valid section heading as well as a trailing PR reference on every bullet. The PR number is unknown until the PR exists (2026-11-21: ten agent PRs in three days went CI-red on it), so write `(#PR)` at the end of each bullet, push the branch, and open the PR with `bin/ade-pr-open <gh pr create arguments>`: it runs `gh` through the adversary-marker shim, verifies the number with `gh pr view` (head branch and origin repo), fills `(#PR)` with the real number in the branch's own fragment, runs the check, and commits and pushes that file (`--existing N` repairs a failed fill). `changelog-fold --check` still rejects `(#PR)`, so a skipped fill fails CI.

## Opt-in NATS coordination

For explicitly enrolled NATS roles, completion-notice persists stable-ID reports and artifacts; --lead-ack records durable ADE intake plus disk projection and suppresses routine model prompt ack. Processed requires explicit inbox disposition under current authority. See [coordination contract](../../docs/nats-coordination.md); unenrolled paths retain the existing receipt policy.
