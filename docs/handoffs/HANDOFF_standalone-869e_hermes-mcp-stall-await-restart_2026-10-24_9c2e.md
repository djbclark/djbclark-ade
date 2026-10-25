---
schema_version: 1
handoff_id: 9c2e
parent_handoff_ids: [f3fd]
lineage: inferred
chain: [standalone-869e]
repo: djbclark-ade
workspace: main
branch: master
head_sha: 8ff3098
created_at: 2026-10-24T06:10:00-0400
writer: zcode
---
# Handoff — Hermes MCP stall investigation: all fixes shipped/pushed, awaiting gateway restart + next-stall evidence

## The Goal
Resume chain `standalone-869e` (Hermes MCP stall investigation). Everything from handoff `f3fd` is
shipped and pushed; what remains is operational: restart the gateway to activate the `key_cmd` fix,
then capture evidence at the next stall.

## Where We Are
No new investigation work since `f3fd` (2026-10-23). `master` has moved (other sessions) to
`8ff3098`, which equals `origin/master` — **pushed, nothing of this chain unpushed or uncommitted**.
The dirty files in the tree (`skills/graft/*`, `.claude/helpers/graft-*`, `.agents/skills/fastino-glide/`)
belong to other sessions' graft/fastino work, not this chain — do not stage them.

1. Hermes MCP bridge (`~/.local/libexec/hermes-mcp-bridge/hermes_mcp_plus.py`, live): every forwarded
   call has a wall-clock limit (`CALL_TIMEOUT=20`, `LIST_TIMEOUT=15`), `events_wait` capped at 60 s
   and 16 concurrent; per-call log `~/.hermes/logs/hermes-mcp-calls.log`; Caddy access log
   `~/.hermes/logs/hermes-mcp-access.log`. Signal off in `~/.hermes/config.yaml`; stall was NOT
   Telegram (calls never reached the bridge). Backups:
   `~/.hermes/backups/2026-10-23-mcp-signal/`.
2. key_cmd model listing: merged to Hermes fork `djbclark/hermes-agent` `main` (`bdea3a9933`) and
   pushed; branch `fix/validate-custom-key-cmd-upstream` pushed; comment on upstream #87641.
   **Gateway NOT yet restarted as of 2026-10-24 — the live gateway does not run the fix.**
3. Paseo agent listing / pane-route repairs: `72167ff`, `a8934b3` on djbclark-ade master (pushed);
   site-private note `aa08492` (pushed). Full Hermes suite 2843 passed, 5 environmental failures.

## Next Steps
1. Restart `com.stayturgid.hermes-gateway` once to activate the key_cmd fix, then verify a
   custom-endpoint model list appears.
2. At the next Hermes MCP stall, read `~/.hermes/logs/hermes-mcp-access.log` and
   `~/.hermes/logs/hermes-mcp-calls.log` (the bounded-call logging exists precisely for this).
3. Workspace-name ledger: read `~/.local/state/bigteam/workspace-name-ledger/brief.md`
   (owned by the rework-2 handoff resumer — coordinate, don't take over).
4. Queued lows: `~/src/djbclark-ade/docs/queue.md` (pane P1-P5, Paseo L1-L4,
   Hermes route R1-M2/R1-L4/R1-L5e/R2-L6/R3).

## Lineage / identifiers
- Chain: `standalone-869e` — canonical log
  `~/.local/state/handoffs/chains/standalone-869e/SESSION_LOG.md`;
  pointer `~/.local/state/handoffs/djbclark-ade/main/SESSION_LOG.md`.
- Handoff lineage: `ce8b` → `f3fd` → `9c2e` (this file).
- Commits of record: djbclark-ade `72167ff`, `a8934b3` (pushed); fork `bdea3a9933` (pushed);
  site-private `aa08492` (pushed); master head `8ff3098` = origin/master.
