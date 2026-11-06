# Workspace and tab naming (Paseo)

Trimmed 2026-11-06 (slim-down E4, ruling 12) from `skills/autorename/workspace-layout.md`. The herdr workspace/tab/pane layout pass
(`-t`/`-p` labels, `/autorename all`, `herdr_place.py`, configured workspaces, sleeper cycling) is gone; `git log -- skills/autorename/workspace-layout.md`
has it. Paseo is the only harness.

## Naming

1. **One top-level agent per Paseo workspace**, the workspace named `<topic>-pw`.
2. **Its tab and each worker's tab are `<name>-pt`**, at most 17 characters with the suffix.
3. **Workers and adversary rounds are sub-agent tabs in the lead's workspace**, not new workspaces.
4. **Closing a top-level agent's tab archives the agent.** To end one on purpose, archive it (`paseo agent archive ID`).

## Renaming

- Workspace: `paseo workspace rename "$PASEO_WORKSPACE_ID" "<topic>-pw"`.
- There is no agent-title rename command in the Paseo CLI (slim-down research item 5, 2026-11-06); set the title at launch with
  `paseo run --title T`.
