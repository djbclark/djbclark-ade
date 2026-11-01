# d1-07a: do agents created by each path open a Desktop tab? (DRAFT checklist, plan T10)

CONTRACT: D1.7a / G3: which creation paths produce a visible tab, so the orchestrator flow can promise one.
SCOPE: needs Paseo Desktop. Run it on a second daemon (`paseo --home <fresh> ...`) added as a host in Desktop
(`paseo host add`), never by creating agents on the live daemon. NOT a script.
ON-FAIL: G1/G3 must open the tab explicitly (`paseo agent open`) instead of relying on creation.

| Path | How | Tab appears? (yes/no) | Notes |
|---|---|---|---|
| `paseo run` (CLI) | `paseo --home H run --no-wait --provider P "reply OK"` | | |
| `paseo run --new-workspace worktree` | same, with `--new-workspace worktree --worktree-slug t1` | | |
| MCP `create_agent` | from an agent on H | | |
| plugin / RPC create | N/A, not scriptable; record N/A | N/A | |
| after `paseo agent open ID` | follow-up on any path with "no" above | | proves the fallback |

Record the table in `docs/d1-results.md` with the daemon version.
