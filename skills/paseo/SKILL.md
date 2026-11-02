---
name: paseo
description: Paseo reference for managing projects, workspaces, workspace scripts, agents, schedules, and heartbeats.
---

Paseo is a remote daemon that manages coding agents, terminals. Control it through MCP tools or the CLI.

## Projects

Manage the daemon's project registry through the CLI:

```bash
paseo project create [path]
paseo project ls
paseo project rename <project-id> <name>
paseo project rename <project-id> --reset
paseo project delete <project-id>
```

For a local daemon, `project create` defaults to the current directory and resolves relative paths on the CLI machine. With `--host` or `PASEO_HOST`, always provide a path; the target daemon interprets it on its own machine. Deleting a project archives its active workspaces and removes the project from Paseo without deleting the project directory.

## Workspaces

**`create_workspace`** — create a workspace independently of any agent. Required: `isolation` (`local` or `worktree`). Worktree isolation supports `mode: "branch-off" | "checkout-branch" | "checkout-pr"`: use `branchName`/`baseBranch` for a new branch, `branch` for an existing branch, or `prNumber` plus optional `forge` for a change request. Use `path` for a local directory or source checkout and `projectId` for the owning project; when no path is supplied, a worktree may resolve its source from `projectId`. `worktreeSlug` controls the managed path. Returns the workspace descriptor centered on `workspaceId`.

`background: true` hides a workspace from default lists and the sidebar while its contents remain durable and accessible; omit `background` to inherit your current workspace’s value (false without a caller), and override it only when the user explicitly asks.

Choose `baseBranch` explicitly: `origin/main` selects the remote-tracking branch; `refs/heads/main` selects local main. Bare `main` prefers local main when it exists, otherwise origin/main. Paseo retains the resolved ref for workspace comparisons, even after rebasing the branch or changing its PR target.

**`list_workspaces`** — list active workspaces, excluding background workspaces unless `includeBackground: true`.

**`archive_workspace`** — `{ workspaceId }`. Archives the workspace, its agents, and its terminals. Local directories remain; Paseo removes an owned worktree only after its final active workspace reference is archived.

**`rename_workspace`** — `{ workspaceId, name }`. Rename workspace.

## Workspace scripts

Configured `paseo.json` scripts use the same supervised lifecycle from tools and the CLI.

**`list_workspace_scripts`** — `{ workspaceId }`. Lists configured scripts with lifecycle, service port, proxy URLs, health, exit code, and terminal ID.

**`start_workspace_script`** — `{ workspaceId, scriptName }`. Starts one configured script through Paseo's managed workspace-script launcher and returns its status metadata.

**`stop_workspace_script`** — `{ workspaceId, scriptName }`. Stops a running script through its supervised terminal and returns the stopped status metadata.

The matching CLI surface accepts either an explicit workspace ID or resolves the current directory:

```bash
paseo script ls [--cwd <path> | --workspace <workspace-id>]
paseo script start <name> [--cwd <path> | --workspace <workspace-id>]
paseo script stop <name> [--cwd <path> | --workspace <workspace-id>]
```

## Agents

**`create_agent`** — required: `title`, `provider` (`claude/opus`, `codex/gpt-5.4`, …), `initialPrompt`. Optional: `workspaceId`, `notifyOnFinish`, `settings`, `labels`. Returns `{ agentId, workspaceId, … }`.

Initial runtime settings live under `settings`: `modeId`, `thinkingOptionId`, and provider-specific `features`. Agent profiles are the preferred source for these values. For Codex fast mode, pass `settings: { features: { "fast_mode": true } }` when creating the agent.

Agent-scoped creation always creates your subagent. Omit `workspaceId` to use your current workspace; pass a workspace returned by `create_workspace` for isolated delegation. Placement never changes parentage.

Detach is an explicit user action in the subagents track, not an agent tool. A cross-workspace child remains your subagent even though it also appears as a normal tab in its workspace.

**A sibling tab is not a subagent** (verified by failure, 2026-10-30). When djbclark asks for a new tab of the same kind as yours — a successor chat seat, a second worker, anything he expects to see and click in his workspace — `paseo run` inside your agent session silently parents it to you: the CLI inherits `PASEO_AGENT_ID` (and `PASEO_AGENT_CWD`) from the environment, so the result has `ParentAgentId` set and lands in the **subagents track**, not the workspace tab list. It runs, answers, and is invisible to him as a tab. `exit 0` plus `status: running` proves nothing about visibility. To create a real sibling, unset both variables for the child command and then check `paseo inspect <id> --json` reports `"ParentAgentId": null` before saying the tab exists. Reported as "I do not see a <name> tab" after exactly this mistake.

Agent-scoped `create_agent` defaults `notifyOnFinish` to true. Set it to `false` only for truly fire-and-forget agents.

**`send_agent_prompt`** — `{ agentId, prompt, activeTurnBehavior? }`. Use for follow-ups to an existing agent. Agent-scoped calls default to `steer`; top-level calls default to `interrupt`. Set `activeTurnBehavior` to `steer` or `interrupt` to override the default. Steering falls back to interruption when unavailable. CLI agent sends use the same defaults and accept `--behavior steer|interrupt`. Returns after dispatch acknowledgement. Agent-scoped calls default `notifyOnFinish` to true; top-level calls have no parent callback.

**`update_agent`** — `{ agentId, name?, labels?, settings? }`. Use `settings` for runtime changes on an existing agent: `modeId`, `model`, `thinkingOptionId`, and provider-specific `features`. For Codex fast mode, pass `settings: { features: { "fast_mode": true } }`.

**`list_agents`** — filter by `cwd`, `statuses`, `sinceHours`, `includeArchived`; set `includeBackground: true` to include agents in background workspaces.

**`archive_agent`** — `{ agentId }`. Interrupts if running, removes from active list.

## Agent profiles and provider discovery

**`list_profiles`** — named launch bundles configured by the human. Before choosing how to launch a delegated agent, call this tool and read every profile's `notes`. Pick a named profile the user requested, or the profile whose notes best match the work.

There is no `profile` parameter on `create_agent`. Materialize the selected profile into the call:

- combine `provider` and `model` as the `provider/model` value for `create_agent.provider`
- copy `modeId` to `settings.modeId`
- copy `thinkingOptionId` to `settings.thinkingOptionId`
- copy `featureValues` to `settings.features`

Omit absent values. Do not remember a selected profile or infer drift later; a profile is only launch configuration.

If no profile fits, or no profiles are configured, use the provider discovery tools below rather than guessing. Tell the user when you fall back because no configured profile fits.

**`list_providers`** — compact provider availability and modes.

**`list_models`** — full model list for one provider. Use only when you need model IDs or thinking options; the list can be large.

**`inspect_provider`** — compact provider capability and feature inspection. Required: `provider`; pass `cwd` when you are not in an agent-scoped session. Optional: `settings` with draft `model`, `modeId`, `thinkingOptionId`, and `features`.

Only set feature IDs returned by `inspect_provider`. For Codex fast mode, look for `fast_mode` and pass `settings: { features: { "fast_mode": true } }` to `create_agent` or `update_agent`.

## Schedules and heartbeats

**`create_schedule`** — starts a new agent on a cron cadence. Required: `prompt`, `cron`, `provider`. Optional: `timezone`, `name`, `cwd`, `maxRuns`, `expiresIn`. Use when the recurring work should live in fresh agents.

**A schedule run reads `succeeded` when its agent's turn ends, not when its work is done** (2026-11-01: a run delegated four slices, ended its turn, was marked succeeded and archived after 3 minutes; the deliverable was never written). So a scheduled prompt (1) names its deliverable or report path, (2) never delegates and stops: it does the work in its own turn, or waits for each slice's report and `.done` marker within a declared deadline (`acp-dispatch-wait`, bounded), and (3) checks that the deliverable exists before it ends; if it does not, a last line `NO OUTPUT: <why>` helps the reader (advisory: nothing parses it, success is only the deliverable). Upstream: getpaseo/paseo#6189. Read a schedule's log with that in mind: `succeeded` alone proves nothing.

**`create_heartbeat`** — sends you a prompt on a cron cadence. Required: `prompt`, `cron`. Optional: `timezone`, `name`, `maxRuns`, `expiresIn`. Use for reminders, PR/build babysitting, and status checks that should return to this conversation.

**`delete_heartbeat`** stops it. MCP intentionally exposes no heartbeat update tool; delete and recreate when its task or cadence changes.

Schedules have the full list/inspect/update/pause/resume/run-once/log/delete surface. Heartbeats deliberately do not.

## Waiting

Agents take time — 10–30+ minutes is routine. Favor asynchronous workflows.

`create_agent` and `send_agent_prompt` return after startup or dispatch acknowledgement in both MCP scopes. Top-level callers have no parent callback; observe completion through status/activity tools or SDK/RPC subscriptions and wait APIs.

For agent-scoped `create_agent` and `send_agent_prompt`, leave `notifyOnFinish` omitted or set it to `true` unless the work is truly fire-and-forget. You will get notified when the target agent finishes, errors, or needs permission. Move on to other work. The notification arrives on its own.

With finish notifications enabled, don't poll `list_agents` or `get_agent_status` to "check on" a running agent. The notification will tell you.

## CLI semantics

The CLI and tools use the same ownership semantics even where their syntax differs:

```bash
paseo workspace create --isolation worktree --mode branch-off --new-branch fix-x --base origin/main
paseo workspace create --isolation worktree --mode checkout-branch --branch existing-work
paseo workspace create --isolation worktree --mode checkout-pr --pr-number 42
paseo run --provider codex/gpt-5.4 --mode full-access --workspace <workspace-id> "<prompt>"
paseo run --provider codex/gpt-5.4 --mode full-access --new-workspace worktree --worktree-mode branch-off --new-branch fix-x --base origin/main "<prompt>"
paseo send <agent-id> "<follow-up>"
paseo ls
paseo schedule create --cron "*/15 * * * *" "ping main build"
paseo heartbeat create --cron "*/15 * * * *" "check the build"
```

Terminal-only handoff fallback (verified 2026-10-27): first inspect the root CLI command roster (`paseo --help`); the installed CLI may expose no profiles command even though the MCP API has `list_profiles`. If MCP is unavailable, say that profile selection could not be queried and use live provider discovery (`paseo provider ls --json`, then `paseo provider models <provider> --json` as needed), current routing/quota policy, and explicit provider/model/thinking/mode. Do not infer configured profiles from a failed command. Never guess a `paseo profile` command or use a raw socket to bypass the tool surface.

Use an existing workspace explicitly and return promptly:

```text
paseo run --no-wait --workspace <workspace-id> --provider <provider/model> --thinking <id> --mode <mode> --title "[Handoff] <short task>" --json <self-contained-brief>
paseo inspect <returned-agent-id> --json
```

Pass arguments as an argv list when building this command programmatically. `inspect` JSON currently uses capitalized keys such as `Id`, `Provider`, `Model`, `Mode`, `Cwd` and `ParentAgentId`; do not assume the lowercase keys from `paseo ls`. Verify the returned workspace and placement before reporting success. This creates a real Paseo agent, not an ACP slice. Keep default parentage; never call detach to manufacture independence. See **paseo-handoff** for durable chain pointers and verified peer notices.

Discover the root command roster before probing subcommands; obey the machine's rule against `--help` on live-service subcommands.

For product questions, setup, logs, version problems, or troubleshooting, use the **paseo-help** skill.
