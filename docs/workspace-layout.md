# Workspace and tab naming (Paseo)

Trimmed 2026-11-06 (slim-down E4, ruling 12) from `skills/autorename/workspace-layout.md`. The herdr workspace/tab/pane layout pass
(`-t`/`-p` labels, `/autorename all`, `herdr_place.py`, configured workspaces, sleeper cycling) is gone; `git log -- skills/autorename/workspace-layout.md`
has it. Paseo is the only harness.

Operator hierarchy (2026-11-07, three levels spelled out 2026-11-13): a **project** groups one repo or a deliberately
named repo set (`djbclark-ade`); a **window** is a Paseo "workspace" (`wks_…` in `paseo workspace ls --json`:
`workspaceId`, `project`, `cwd`, …), e.g. "MAIN djbclark-ade Wave 7"; a **tab** is one Paseo agent in a window, e.g.
"LEAD djbclark-ade Wave 7". Git worktree isolation and one writer per claimed checkout stay mandatory (AGENTS.md order 9);
a window is a sidebar grouping, not a git worktree, so a worker's claimed worktree is named in its brief, not by its window.

## Naming

1. **One window per genuine new isolated writing task, and one workers window per lead** (next section) — create it with
   `paseo workspace create` or `paseo run --new-workspace …`, not per advisor, review round, report folder or worker launch.
2. **Reuse the window** for implementer, reviewer, and advisor tabs
   (`paseo run --workspace wks_…`, with `PASEO_WORKSPACE_ID` validated against `paseo workspace ls` when needed).
3. **Agent titles** stay short and identifiable; `paseo agent update ID --name "…"` (after launch; `paseo run --title T` also works, with the caps below).
4. **Closing a tab** you mean to end: archive that agent (`paseo agent archive ID`). Archiving an agent keeps its
   window, so end a workers window with `paseo workspace archive` (below).

The name shortener (`bin/seat-name`) was deleted 2026-11-06 (slim-down E2); keep names readable without an automatic cap.

## Worker placement: one workers window per lead (operator ruling, 2026-11-13)

A lead's workers and reviewers all go in **one new window per lead**, never one window per launch:

1. **Window name:** `workers <middle> <lead agent id>`. **Tab name** (every worker, reviewer, advisor in that window):
   `worker <middle> <lead agent id>` (singular). `<middle>` is the lead's choice (project and wave, e.g.
   `djbclark-ade Wave 7`); `<lead agent id>` is the **full** id of the lead's own tab, so a sidebar line names its
   owner. Example: window `workers djbclark-ade Wave 7 8cd86203-d33b-49db-abde-9baba52bcf61`, tab
   `worker placement-docs 8cd86203-d33b-49db-abde-9baba52bcf61`.
2. **Why:** a top-level `paseo run` with the agent environment stripped (`skills/fan-out` section 3) creates a new
   "master" window per launch, because its cwd is the repo's `master` checkout; 11 piled up on 2026-11-13 and archiving an
   agent does not remove its window.
3. **Length:** keep a window or tab name under about 100 characters, so `<middle>` is at most about 55 characters
   (the prefix and the 36-character id use the rest). Measured limits, Paseo 0.16.0-beta.2, 2026-11-13: `paseo workspace rename`
   and `paseo agent update --name` read back unchanged at 60, 100, 200 and 400 characters (no server cap seen); the
   source (read at v0.13.0+29) caps an explicit `paseo run --title` at 200 (`packages/protocol/src/agent-title-limits.ts`)
   and an agent-tool (MCP) `create_agent` title at 60 (`packages/server/src/server/agent/tools/paseo-tools.ts:1177`); the
   sidebar shows only the first words. Name tabs after launch with `paseo agent update`, not `--title`, so the 60/200
   launch caps never bite.
4. **Mechanics** (launch recipe in `skills/fan-out` section 3): the first launch has no window yet, so it creates one
   (`paseo run --new-workspace local …`). **Read the new window's id from that launch, never guess it:** `paseo run --json`
   returns no `workspaceId` (Paseo 0.16.0-beta.2, 2026-11-13), and `paseo workspace ls` cannot tell the new window from other
   leads' windows that share its cwd and branch name. Take it from the `Created workspace wks_… - <name>` line `paseo run`
   prints on stderr (capture stderr to a file, not a pipe), or from the new agent's state file,
   `$PASEO_HOME/agents/*/<agent id>.json` `workspaceId` (verified 2026-11-13). Record the `wks_…` in the lead's own state,
   then `paseo workspace rename <wks> "workers <middle> <lead id>"`, and give every later launch `--workspace <wks>`. Rename
   each tab with `paseo agent update <full agent id> --name "worker <middle> <lead id>"` (tabs share a name, so always pass
   a full agent id, never a tab name). **Archive the window with `paseo workspace archive <wks>` only when all hold:** every
   agent labelled `ade.lead=<own id>` is archived or idle with its DONE/BLOCKED handled (`paseo ls -a -g --json --label
   ade.lead=<own id>`); no other live agent sits in the window (`paseo ls -a -g --json`, match its workspace; the archive
   stops every live agent and terminal in the window, labelled or not); and the recorded `<wks>`'s name reads `workers …
   <own lead id>`. Otherwise leave the window.
5. **cwd:** a window's `cwd` is the session directory its first launch gave it (the repo's primary checkout). Later tabs
   launch with `--workspace <wks> --cwd <that same directory>` (with `--workspace`, Paseo takes the agent's cwd from the
   window). Because that directory is the shared primary checkout, where nothing may be edited (AGENTS.md order 9), each
   brief gives the claimed worktree as an absolute path and every writer runs every repository operation there (`git -C
   <worktree>`, absolute file paths); `-C`/`--dir` keeps its session-directory meaning. Tools that infer a target from cwd
   must receive an explicit supported target or not be used. Reports and scratch folders are artifact locations, never
   reasons to create a project or window.
6. **Not a worker:** a handoff **successor** is a new lead, not a worker. It keeps its own placement (a top-level
   `paseo run` of its own, `skills/handoff`) and, once it answers, archives its predecessor; it opens its own workers
   window with its own id when it dispatches. Workers still carry `--label ade.lead=<lead id>` (#623), and an
   env-stripped launch still drops `PASEO_AGENT_ID`, `PASEO_AGENT_CWD` and `PASEO_WORKSPACE_ID`.

This supersedes the 2026-11-07 "temporary shared-tab arrangement" (workers as tabs in the lead's own window).

## Renaming

- Workspace title: `paseo workspace rename "$PASEO_WORKSPACE_ID" "<task worktree>"`.
- Agent title: `paseo agent update "$PASEO_AGENT_ID" --name "<name>"` (read in the Paseo 0.15.3 source,
  `packages/cli/src/commands/agent/index.ts`, 2026-11-06; run against 0.16.0-beta.2 on 2026-11-13), or set it at launch with `paseo run --title T`.
