# Workspace and tab naming (Paseo)

Trimmed 2026-11-06 (slim-down E4, ruling 12) from `skills/autorename/workspace-layout.md`. The herdr workspace/tab/pane layout pass
(`-t`/`-p` labels, `/autorename all`, `herdr_place.py`, configured workspaces, sleeper cycling) is gone; `git log -- skills/autorename/workspace-layout.md`
has it. Paseo is the only harness.

Operator hierarchy (2026-11-07, three levels spelled out 2026-11-13): a **project** groups one repo or a deliberately
named repo set (`djbclark-ade`); a **window** is a Paseo "workspace" (`wks_…` in `paseo workspace ls --json`:
`workspaceId`, `project`, `cwd`, …), e.g. "LEAD djbclark-ade (Wave 7)"; a **tab** is one Paseo agent in a window, e.g.
"LEAD djbclark-ade Wave 7". Git worktree isolation and one writer per claimed checkout stay mandatory (AGENTS.md order 9);
a window is a sidebar grouping, not a git worktree, so a worker's claimed worktree is named in its brief, and its tab name may
carry it as a hint (`[wt: …]`, below), not by its window.

## Naming

1. **One window per genuine new isolated writing task, and at most three windows ("boxes") per lead and repo: LEAD, WORKER,
   OTHER** (next section) — create one with `paseo workspace create` or `paseo run --new-workspace …`, not per advisor, review
   round, report folder, slice or worker launch.
2. **Reuse the window** for implementer, reviewer, and advisor tabs
   (`paseo run --workspace wks_…`, with `PASEO_WORKSPACE_ID` validated against `paseo workspace ls` when needed).
3. **Agent titles** stay short and identifiable; `paseo agent update ID --name "…"` (after launch; `paseo run --title T` also works, with the caps below).
4. **Closing a tab** you mean to end: archive that agent (`paseo agent archive ID`). Archiving an agent keeps its
   window, so end a WORKER or OTHER window with `paseo workspace archive` (below).

The name shortener (`bin/seat-name`) was deleted 2026-11-06 (slim-down E2); keep names readable without an automatic cap.

## Window names: `<KIND> <repo> (<work>)`, KIND LEAD, WORKER or OTHER (operator ruling, 2026-11-14)

Operator, 2026-11-14, to the tendcf lead ae1f6d65 (verbatim): "Close any unneeded tabs and any unneeded workspaces you or your
predecessors have made. In the future, have at most LEAD, WORKER, and OTHER workspaces and put tabs in the appropriate box. The
tabs can mention the worktree they are in." Root cause: `ade-worker-run --window-middle <work>` opened a new `WORKERS <repo>
(<work>)` window for every new work text, and each successor lead opened its own, so windows piled up one per slice (tendcf had 9,
djbclark-ade about 15 `WORKERS djbclark-ade (...)`). Unit wb-01 implements the ruling; the names are the ruling's own words, singular
because a box is one window, so `<KIND> <repo>` stays recognisable.

This **supersedes the 2026-11-13 scheme**. Operator, 2026-11-13 (first ruling, verbatim; history): "Change the naming scheme for
Workspaces to be MAIN before the subworkspace you are in, and WORKERS (just a change in capitalization) for workers you start by
yourself. Workers I start interactively should go in a tab in the MAIN subworkspace, in the row of tabs that include you. Implement
the new policy retroactively." The same day it became `<KIND> <repo-name> (<current work>)` with USER added. Mapping (the old kinds
are still **found, never duplicated**, and renamed to the current kind when a launch reuses the window):

| 2026-11-13 | 2026-11-14 | holds |
|---|---|---|
| `MAIN` | `LEAD` | the lead's own window, the row of tabs that includes the lead |
| `WORKERS` | `WORKER` | every worker, reviewer and advisor the lead starts on its own initiative |
| `USER` | `OTHER` | probes, side tasks, agents the operator started that the lead connected |

Window names are exactly `<KIND> <repo-name> (<current work>)`, e.g. `LEAD djbclark-ade (Wave 7)`, `WORKER djbclark-ade (Wave 7)`,
`OTHER djbclark-ade (probes)`. **The lead's agent id is not in a window name**; it stays in the tab name and the `ade.lead` label.
`bin/ade_ws_names.py` is the one builder/parser (`build`, `parse`, `parse_legacy`, `migrated_name`, `repo_of`; a parsed `Name.box`
maps both spellings onto LEAD, WORKER, OTHER); `ade-tidy` and `ade-worker-run` reuse it.

1. **`LEAD <repo> (<work>)`**: a lead's own window, the row of tabs that includes the lead. Workers the **operator** asks
   for interactively ("open a new sonnet tab to …") are launched as a tab in this window:
   `ade-worker-run --lead <id> --slice <name> --placement lead -- …` (aliases `--placement main`, `--interactive`; label
   `ade.placement=main`, the label value keeps its 2026-11-13 spelling). It resolves the window from the lead's own agent record
   (never from a possibly-unset `PASEO_WORKSPACE_ID`), refuses unless the window is named `LEAD …` and the caller is the lead
   (a `MAIN …` name is renamed to `LEAD …` by the launch), and never archives it. `ade-worker-run rename-lead --lead <id>
   [--window-middle <work>] [--repo <repo>]` (alias `rename-main`) names the lead's own window `LEAD <repo> (<work>)` (a WORKER or
   OTHER window is refused; a legacy `MAIN <middle>` is renamed too).
2. **`WORKER <repo> (<work>)`**: one box per lead and repo for **every** worker, reviewer and advisor the lead starts on its own
   initiative (the next section). Tab name: `worker <slice> <lead agent id>` (singular), with the **full** lead id, so a sidebar line
   names its owner, plus ` [wt: <worktree dir basename>]` when the worker writes in a worktree (below). Example: window `WORKER
   djbclark-ade (Wave 7)`, tab `worker placement-docs 8cd86203-d33b-49db-abde-9baba52bcf61 [wt: djbclark-ade-placement-docs-wt]`.
3. **`OTHER <repo> (<work>)`**: probes, side tasks and agents the operator started that a lead has connected to. A launch goes in
   with `ade-worker-run … --placement other` (alias `--other`; label `ade.placement=other`; tab prefix `other `, so `other <slice>
   <lead id> [wt: …]`; default `(<work>)` text `other`). `ade-tidy` classes an operator agent of the repo as OTHER. It is the same
   kind of box as WORKER (one per lead and repo, found by ownership); `archive-window --placement other` archives it.
4. **`<repo>`** is `--repo`, else the name of the repo of `--cwd` (the main checkout's name via `git rev-parse
   --git-common-dir`, so a linked worktree `djbclark-ade-x-wt` reads `djbclark-ade`; else the directory's basename);
   **`<work>`** is `--window-middle` (nonempty, trimmed, one line) of the launch that **opens** the box. **Legacy names** recognised and
   renamed in place (same window id, Paseo `workspace rename`): `workers <middle> <lead id>` and `WORKERS <middle> <lead id>` →
   `WORKER <repo> (<middle>)`, `MAIN <middle>` → `LEAD <repo> (<middle>)`, and the 2026-11-13 forms `MAIN|WORKERS|USER <repo>
   (<work>)` → `LEAD|WORKER|OTHER <repo> (<work>)`, where a middle that starts with `<repo> ` drops it (`workers djbclark-ade Wave 7 <id>`
   → `WORKER djbclark-ade (Wave 7)`). The legacy repo is `--repo`, else the repo of the window's own `cwd`. Matching is
   case-sensitive; `Workers …`, `LEAD repo (w) x` and the like are not names.

## Worker placement: three boxes per lead and repo

A lead and repo have **at most three windows**, LEAD, WORKER and OTHER, and every agent goes in the box that fits it; tabs, not
windows, carry the slice, and a tab may mention its worktree. Never one window per launch, slice or `--window-middle`:

1. **Finding the box:** by **ownership evidence, never by name**: with the lead id out of the name, **a name never confers
   ownership**. Evidence: the lead's window record (`$ADE_WORKER_RUN_STATE/<lead id>.windows.json`, written when the helper mints,
   migrates or adopts a window; all finds and archives run under one global lock), a live agent labelled `ade.lead=<lead id>` in it, or
   the lead id in a legacy name. A launch uses the lead's one WORKER box of the repo **whatever the slice and whatever
   `--window-middle` says**. A matched window registered to **another** lead, or holding any agent (closed included) labelled for another
   lead, is refused, as are several owned boxes of the repo when `--window-middle` (a picker, below) does not name one. A name match
   with no evidence either way may be adopted by a launch only when no agent in it (any status) is unlabelled for this lead, and is
   recorded only after that launch succeeded; it is **never archived** before that. A window made by hand is unrecorded, so a lead
   that wants it archivable by the helper launches into it first while it is empty. A legacy or 2026-11-13-kind window is renamed
   to the current form only if its new name is free, after its ownership is recorded. A box of **another repo** is not this launch's
   (the repo is the name's, else a legacy window's cwd's; one whose repo cannot be read still counts, and with no repo known every
   owned box counts): a launch for a repo the lead has no box for opens that repo's box, named and placed from that repo.
   **`--window-middle` is only the `(<work>)` text of a box a launch opens** (default `workers`; `other` in the OTHER box) **and a
   picker** when the lead owns several boxes of the repo (the one whose `(<work>)` equals it); it never opens a second box, and old
   invocations that pass it keep working. With several owned boxes and no `--window-middle`, `--repo` (or the repo of `--cwd`, else
   the current directory) narrows them to that repo's (`archive-window` narrows only by an explicit `--repo`, never a derived one).
   A launch into an inherited box registers it under the successor.
2. **Successors reuse the chain's box** (2026-11-14): a successor lead of a completed self-handoff
   (`bin/ade_lead_succession.py`, [self-session.md](self-session.md) C0a) finds the box its predecessors made by the same
   evidence (their window records, their `ade.lead=<predecessor>` workers, their legacy-named windows) and launches into it; it
   does not open its own box beside it. A window registered to a genuinely different live lead is still refused.
   **Acknowledged, not yet archived (hf-38c, 2026-11-15):** a predecessor whose fresh `acknowledged` (or wait-only `archive-unknown`)
   handoff record names THIS lead as successor (`ade_lead_succession.acknowledged_predecessors`, which applies `_ack_is_fresh`: under
   an hour, no failure but a wait) is adopted the same way (its window records, `ade.lead=<predecessor>` labels and completed chain),
   but only when it is no longer acting: `paseo agent inspect <predecessor> --json` reads `Archived: true`, or `Archived: false`
   with `Status` `idle` or `closed`. A `running` (or any other) status, a failed or unparsable inspect, an answer for another id,
   a stale record or one naming another agent keeps the refusal, and the message names the predecessor and the reason. The send
   redirect ([archived-send-guard.md](archived-send-guard.md)) is unchanged.
3. **Why boxes:** a top-level `paseo run` with the agent environment stripped (`skills/fan-out` section 3) creates a new
   "master" window per launch, because its cwd is the repo's `master` checkout; 11 piled up on 2026-11-13, and archiving an
   agent does not remove its window. The per-work-text window of 2026-11-13 made it worse (tendcf 9, djbclark-ade about 15 by
   2026-11-14), hence the ruling above.
4. **Length:** keep a window or tab name under about 100 characters (`NAME_LIMIT` in `bin/ade_ws_names.py`; the build refuses
   a longer window name, the tab name `worker <slice> <lead id>` is checked too, and the ` [wt: …]` hint is shortened to fit,
   never refused). Measured limits, Paseo 0.16.0-beta.2,
   2026-11-13: `paseo workspace rename`
   and `paseo agent update --name` read back unchanged at 60, 100, 200 and 400 characters (no server cap seen); the
   source (read at v0.13.0+29) caps an explicit `paseo run --title` at 200 (`packages/protocol/src/agent-title-limits.ts`)
   and an agent-tool (MCP) `create_agent` title at 60 (`packages/server/src/server/agent/tools/paseo-tools.ts:1177`); the
   sidebar shows only the first words. Name tabs after launch with `paseo agent update`, not `--title`, so the 60/200
   launch caps never bite.
5. **Mechanics: `bin/ade-worker-run`** (2026-11-13, boxes 2026-11-14; recipe in `skills/fan-out` section 3). `ade-worker-run --lead <lead id>
   --slice <name> [--window-middle <work>] [--repo <repo>] [--cwd <dir>] [--worktree <dir>] [--placement worker|lead|other]
   [--no-footer] -- <paseo run args>` does the steps below and prints `{agentId, workspaceId, windowName, tabName}`. The first
   launch has no box yet, so it creates one (`paseo run --new-workspace local …`; `--window-middle` is optional, default `workers`).
   **The new window's id is read from that launch, never guessed:** `paseo run --json`
   returns no `workspaceId` (Paseo 0.16.0-beta.2, 2026-11-13), and `paseo workspace ls` cannot tell the new window from other
   leads' windows that share its cwd and branch name. The helper takes it from the JSON when present, else from the single
   `Created workspace wks_… - <name>` line `paseo run` prints on stderr (read from a file, not a pipe), cross-checked against
   the new agent's state file, `$PASEO_HOME/agents/*/<agent id>.json` `workspaceId` (verified 2026-11-13); none or two
   different ids fail closed. It then runs `paseo workspace rename <wks> "WORKER <repo> (<work>)"`; every later launch
   finds the box as in item 1 and passes `--workspace <wks>`.
   It adds `--label ade.lead=<lead id>` and `--label slice=<name>` and renames each tab with `paseo agent update <full agent
   id> --name "worker <name> <lead id>"` (tabs share a name, so by hand always pass a full agent id, never a tab name). **The tab
   may mention its worktree** (operator ruling above): `--worktree <dir>`, or a `--cwd` that is itself a linked worktree, appends
   ` [wt: <worktree dir basename>]`; it is a hint (shortened to fit 100 characters), the brief still carries the absolute path. It
   appends one line to the brief (the last argument), `Also follow every item of <repo root>/docs/dispatch-footer.md.`
   (`--no-footer` skips it; added 2026-11-13 after lead-written briefs omitted the footer). It requires
   `--no-wait` and holds a per-lead lock until `paseo run` returns, so launches and `archive-window` of one lead never
   interleave. `--lead` is checked against the
   caller's `PASEO_AGENT_ID` (refused when they differ, unless `--on-behalf-of-lead`). **Archive a box with `ade-worker-run
   archive-window --lead <lead id> [--placement worker|other] [--window-middle <work>]` (it runs `paseo workspace archive <wks>`) only when all hold:** every live agent labelled
   `ade.lead=<own id>` is closed, or idle with its DONE/BLOCKED handled (`--idle-handled`); no other live agent sits in the
   window (the archive stops every live agent and terminal in it, labelled or not; the helper reads each live agent's
   `workspaceId` from its state file and treats one with no usable `workspaceId` there as a blocker); and the window is this lead's
   WORKER (or OTHER) box (current or legacy name; a LEAD or MAIN window is never archived). A live `ade.placement=main` or `other` agent in
   another window (a LEAD tab, an OTHER tab) is not a blocker for the WORKER box. Otherwise it archives nothing and lists the blockers. It does not look at the window's terminals.
6. **cwd:** a window's `cwd` is the repo's primary checkout: a launch that opens a box passes `--new-workspace local --cwd <primary checkout of --cwd's repo>` (`ade_ws_names.primary_checkout_of`), never the claimed worktree `--cwd` names (2026-11-14, wr-01: a worktree there became the default cwd of every later worker of the window, another writer's claimed worktree), and the post-launch check compares the agent's `Cwd` with that directory. The primary checkout of a submodule is its path under its superproject's primary checkout; of a repo whose git dir is not a `.git` the main entry of `git worktree list` when git records one (not for a bare repo or a `--separate-git-dir` repo); with none found the window opens in `--cwd` and a stderr warning says so. Because the worker then starts in the shared checkout, **a launch whose `--cwd` differs from that directory is refused unless the brief names `--cwd` (the worktree) as an absolute path**, the JSON line carries `cwd` and `requestedCwd`, and a stderr note says it. The same applies to a later launch with the same `--cwd` into an existing box whose cwd is that primary checkout: it is placed there, no refusal (any other `--cwd` that differs from the window's is still refused). A `--cwd` in a subdirectory opens the window at the repo root. **No `--cwd` from inside a linked worktree is the same case** (the worker would start in the primary checkout): it gets the same brief check, stderr note and `cwd`/`requestedCwd` fields, but its refusal asks for `--cwd <the worker's own worktree>` named in the brief (or a run from the primary checkout) and never tells the lead to hand over the worktree it stands in. A brief that names the worktree's top directory satisfies the check when `--cwd` is a subdirectory of it. A box also counts as a repo's box by checkout: a box of the lead's whose cwd has the same primary checkout counts as that repo's even when it was named with a different `--repo`, unless the launch passes an explicit `--repo`; a legacy window whose directory is gone names no repo, so it still counts. A directory that is no git checkout (a scratch directory, `~`) never aliases two `--repo` names. A submodule of a linked worktree whose primary copy is uninitialised opens in the submodule path, with the warning. Later tabs
   launch with `--workspace <wks> --cwd <that same directory>` (with `--workspace`, Paseo takes the agent's cwd from the
   window and ignores `--cwd`, getpaseo/paseo#9699: `ade-worker-run` refuses a different `--cwd` and checks the agent's `Cwd` after launch, stopping a worker that landed elsewhere). Because that directory is the shared primary checkout, where nothing may be edited (AGENTS.md order 9), each
   brief gives the claimed worktree as an absolute path and every writer runs every repository operation there (`git -C
   <worktree>`, absolute file paths); `-C`/`--dir` keeps its session-directory meaning. Tools that infer a target from cwd
   must receive an explicit supported target or not be used. Reports and scratch folders are artifact locations, never
   reasons to create a project or window.
7. **Not a worker:** a handoff **successor** is a new lead, not a worker. It keeps its own placement (a top-level
   `paseo run` of its own, `skills/handoff`) and, once it answers, archives its predecessor; it names its own window
   `LEAD <repo> (<work>)` and **reuses the chain's WORKER and OTHER boxes** when it dispatches (item 2). Workers still carry `--label ade.lead=<lead id>` (#623), and an
   env-stripped launch still drops `PASEO_AGENT_ID`, `PASEO_AGENT_CWD` and `PASEO_WORKSPACE_ID`.
   **Windows and workers survive the handoff (2026-11-14):** `ade-worker-run` treats an archived predecessor whose completed
   `ade-self-session` chain ends at `--lead` as that lead: its window record, its `ade.lead=<predecessor>` workers and
   its legacy-named windows are adoptable by the successor, with no hand step; a window registered to a
   genuinely different live lead is still refused. The ledger is `handoff-<predecessor>.json`
   ([self-session.md](self-session.md) C0a).
8. **How tidy enforces the boxes:** `ade-tidy` ([skills/tidy](../skills/tidy/SKILL.md)) names windows `LEAD|WORKER|OTHER`
   (renaming the 2026-11-13 kinds, never archiving a LEAD window), accepts a lead's own worker in any of its boxes, and its
   section H lists **windows beyond the three boxes**: a second window of a box for the same lead chain and repo, or an owned
   window named outside the scheme. `--apply` archives the empty or finished ones of the lead's chain (lineage by completed
   self-handoffs); never another lead's window, a running agent's window or a tab holding an active claim (`bin/ade_claims.py`).

This supersedes the 2026-11-07 "temporary shared-tab arrangement" (workers as tabs in the lead's own window) for own-initiative
workers only; operator-requested ones are tabs in the lead's LEAD window again (item 1 of "Window names").

## Automatic naming of new windows (2026-11-14)

Operator, 2026-11-14: "Some projects are still starting new workspaces without our MAIN/WORKERS/etc repo-name scheme." The
scheme was applied only by `bin/ade-worker-run` (our own launches) and `bin/ade-tidy` (one repo, manual), so a lead in another
repo, the operator's own new chat and a plain `paseo run` kept Paseo's default names. The **`ade-window-name` Paseo plugin**
([plugins/ade-window-name](../plugins/ade-window-name/README.md)) names every default-named window on this host when its first agent is
created (or next ends a turn, so an install also backfills existing ones) (`agent.create.after`, retried on `agent.turn.after` while the agent has no title); `bin/ade_ws_autoname.py` decides, on
`bin/ade_ws_names.py` (the builder `ade-worker-run` and `ade-tidy` share). Rules: a window is **default-named when its Paseo
`title` is null** (or equals the first agent's own title: Paseo's prompt pre-title for a window the app created with a prompt) and is then named `WORKER` for an agent with a parent or an `ade.lead` label, else `LEAD` (`ade.placement`
overrides: `lead`|`main`, `worker`|`workers`, `other`|`user`; `OTHER` is never guessed); `<repo>` as in item 4 of "Window names", `<work>` the agent's title, short; **a window with any other title (a human's, `ade-worker-run`'s, one already in the scheme, in the current or the 2026-11-13 spelling) is
never touched**, only the window's first agent names it, and `ade-worker-run` launches (labels `slice` + `ade.lead`) are left to it. `paseo run --new-workspace` creates the window before the agent and
sends no prompt or label with it, which is why the hook is on the agent, not on `workspace.create.before`. A plugin-made window is
one more box of its lead: `ade-worker-run` and `ade-tidy` find and count it by ownership evidence like any other.

## Renaming

- Workspace title: `paseo workspace rename "$PASEO_WORKSPACE_ID" "<task worktree>"`.
- Agent title: `paseo agent update "$PASEO_AGENT_ID" --name "<name>"` (read in the Paseo 0.15.3 source,
  `packages/cli/src/commands/agent/index.ts`, 2026-11-06; run against 0.16.0-beta.2 on 2026-11-13), or set it at launch with `paseo run --title T`.
- **Name collision (2026-11-14, [getpaseo/paseo#9668](https://github.com/getpaseo/paseo/issues/9668)):** `paseo agent archive ID` resolves client-side from the listing, and an agent whose workspace was deleted is missing from it; the CLI then falls back to a unique partial *title* match, and a worker tab is named `worker <slice> <lead id>`, so a lead's full id can resolve to (and archive) its live worker. `ade-self-session finish` therefore checks the predecessor is in `paseo ls -g --json` (the plain listing archive resolves from; not `-a`, which adds background workspaces) before archiving (`docs/self-session.md` C0).

## Tidying (2026-11-13, boxes 2026-11-14)

`bin/ade-tidy` and [skills/tidy](../skills/tidy/SKILL.md) inventory one repo's agents and windows, reconnect agents with
no proven contact, report who waits on the lead or the operator, rename windows to the convention (LEAD, WORKER, OTHER), report
windows beyond the three boxes (section H) and archive finished workers and empty or extra windows of the lead's chain.
Paseo has **no command to move an agent to another window** (`paseo agent update` takes
`--name`, `--label`, `--thinking`; the MCP `update_agent` and the protocol's `update_agent_request` carry no workspace;
checked 2026-11-13), so a misplaced tab is reported, never relaunched; place agents correctly at launch. A third-party "rehome" (archive an idle agent, re-import it with a `workspaceId` through the daemon client; same agent id and provider session) is described in [paseo-move-chat internals](https://github.com/bigforcegun/dotfiles/blob/e0915023f13e8a393280f147e9baf559a68d52fd/.rulesync-global/.rulesync/skills/paseo-move-chat/references/internals.md) for Paseo 0.7-0.9.2; unverified on 0.16, not adopted.
