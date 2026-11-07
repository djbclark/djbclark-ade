# Workspace and tab naming (Paseo)

Trimmed 2026-11-06 (slim-down E4, ruling 12) from `skills/autorename/workspace-layout.md`. The herdr workspace/tab/pane layout pass
(`-t`/`-p` labels, `/autorename all`, `herdr_place.py`, configured workspaces, sleeper cycling) is gone; `git log -- skills/autorename/workspace-layout.md`
has it. Paseo is the only harness.

## Naming

1. **One top-level agent per Paseo workspace**, the workspace named `<topic>-pw`.
2. **Its tab and each worker's tab are `<name>-pt`**, at most 17 characters with the suffix.
3. **Workers and adversary rounds are sub-agent tabs in the lead's workspace**, not new workspaces.
4. **At most 5 tabs in a workspace** (operator, 2026-10-29); the next tab of that kind goes to `<name>-2`, then `<name>-3`.
5. **Closing a top-level agent's tab archives the agent.** To end one on purpose, archive it (`paseo agent archive ID`).

The name shortener (`bin/seat-name`) was deleted 2026-11-06 (slim-down E2); the 17-character limit is a manual rule.

## Renaming

- Workspace: `paseo workspace rename "$PASEO_WORKSPACE_ID" "<topic>-pw"`.
- Agent title: `paseo agent update "$PASEO_AGENT_ID" --name "<name>"` (read in the Paseo 0.15.3 source,
  `packages/cli/src/commands/agent/index.ts`, 2026-11-06; not run against a daemon), or set it at launch with `paseo run --title T`.
