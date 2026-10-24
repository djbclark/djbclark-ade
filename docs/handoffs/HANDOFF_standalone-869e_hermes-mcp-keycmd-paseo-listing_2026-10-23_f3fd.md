---
schema_version: 1
handoff_id: f3fd
parent_handoff_ids: [ce8b]
lineage: inferred
chain: [standalone-869e]
repo: djbclark-ade
workspace: main
branch: master
head_sha: d715d31
created_at: 2026-10-23T19:00:00-0400
writer: claude-code
---
# Handoff — Hermes MCP stall/Signal, key_cmd model listing, Paseo agent listing, pane-route repairs

## The Goal
Four jobs after `ce8b`: (1) stop Hermes MCP stalls and turn Signal off; (2) make Hermes custom-endpoint
model listing honour `key_cmd` (fork `djbclark/hermes-agent`, offer upstream); (3) make `fleet.py` and
`relay.py` list and resolve every Paseo agent (Dann's cline agent was invisible); (4) repair the
round-2 pane-route double-delivery class in `relay.py`.

## Where We Are
All four are shipped and pushed. Nothing of mine is uncommitted. `master` was at `7d912c0` at the last
check and a pull moved it to `d715d31` (other sessions' work); the untracked
`.agents/skills/fastino-glide/` is not mine.

1. Hermes MCP bridge (`~/.local/libexec/hermes-mcp-bridge/hermes_mcp_plus.py`, live): every forwarded call
   has a wall-clock limit (`CALL_TIMEOUT=20`, `LIST_TIMEOUT=15`), `events_wait` capped at 60 s and 16
   concurrent; per-call log `~/.hermes/logs/hermes-mcp-calls.log`; Caddy access log
   `~/.hermes/logs/hermes-mcp-access.log` (headers stripped). Signal is off in `~/.hermes/config.yaml`.
   Backups: `~/.hermes/backups/2026-10-23-mcp-signal/` and `*.bak-20261023-181955`.
2. key_cmd: merged to the Hermes fork `main` (`bdea3a9933`) and pushed; branch
   `fix/validate-custom-key-cmd-upstream` pushed to the fork; comment posted on upstream PR #87641. **The
   gateway has NOT been restarted**, so the live gateway does not have the fix yet.
3. Paseo listing: `72167ff` (fleet.py lists every non-archived Paseo agent of any provider; relay.py
   resolves a Paseo id prefix and refuses a working agent whose provider cannot steer). Dann confirmed.
4. Pane repairs: `a8934b3`. Both adversary rounds ended APPROVE.
Tests: full Hermes suite 2843 passed, 5 environmental failures; djbclark-ade relay/fleet tests pass
(new `tests/test_fleet_paseo_rows.py`). Site-private note updated and pushed (`aa08492`).

## What We Tried
1. Telegram retries as the cause of the Hermes stall: **refuted**. Between 16:47:14 and 17:05 no call
   reached the bridge, and a simulated Telegram outage left reads unaffected. The stall is upstream of the
   bridge (Funnel, Caddy, the client) or the Tailscale client/daemon mismatch (1.104.2 vs 1.104.1, untested).
2. Outage simulation needed three fixes: ports 28792/28793 (default ones in use); a `sitecustomize`
   PYTHONPATH is popped by the hermes launcher (`python -I`), so use a wrapper that prepends `sim.py` to the
   runtime `-c` from `hermes --print-runtime-command`; a fake Telegram token in the child; `import
   hermes_bootstrap` for the right venv.
3. The pane worker's `docs/queue.md` was a stale copy that would have deleted about 250 lines: rebuilt from
   HEAD with only the pane-lows section replaced. Check any worker's queue.md diff before committing.
4. I wrongly said the Hermes full suite never completed (it did), and first framed Dann's bug with the
   wrong cause. Both corrected in the loose audit.
5. Steer on ACP providers (cline, grok, copilot) is "replaced", not queued: only claude, codex, omp,
   opencode and pi queue (`steerActiveTurn`).

## Key Decisions
1. Patch Hermes `key_cmd` in the fork, merge locally and push `main`, comment on #87641 rather than open a
   second PR (djbclark's card answers). The upstream branch has had no adversary review.
2. Instrument first, bound the MCP calls, wait for the next stall (djbclark: "Leave the new logs in place
   and wait for the next stall").
3. Paseo listing: all non-archived agents of any provider, not just cline (djbclark: "way more paseo agents
   than are listed there").
4. Workspace-name ledger (a historical, human-editable list; Paseo keeps one `title` per workspace in
   `workspaces.json`, overwritten on rename) is queued with the rework orchestrator, rejected for this chain.

## Evidence & Data
1. `~/.local/state/bigteam/hermes-mcp-stall/` (REPORT.md, sim.py, results), `hermes-keycmd-models/`
   (reports, upstream-pr-body.md, upstream-comment-87641.md), `relay-pane-lows/`, `paseo-listing/`
   (adversary-report.md), `workspace-name-ledger/brief.md`.
2. Commits: `a8934b3`, `72167ff`, site-private `aa08492`, fork `bdea3a9933`.
3. `docs/queue.md` holds pane Lows P1-P5, Paseo Lows L1-L4 and the Hermes route lows.

## Operator Feedback
1. "Do 1 but there are way more paseo agents then are listed there."
2. "Note that we may need to maintain a list of historical human-readable-and-editable workspace names if
   that isn't something paseo does automatically."
3. Chose "Handoff and continue" at the end of the `/loose` audit.

## Where We're Going
1. **Restart the Hermes gateway once** (`com.stayturgid.hermes-gateway`) to activate the key_cmd fix. It was
   told to djbclark and not done; do it at a quiet moment and verify with `hermes --version` plus a custom-endpoint
   model list.
2. Workspace-name ledger and alias file: brief at `~/.local/state/bigteam/workspace-name-ledger/brief.md`.
   The rework-2 lead accepted it; whichever session resumes that handoff owns it. relay.py and fleet.py have
   landed, so no wait is needed.
3. At the next Hermes MCP stall read `~/.hermes/logs/hermes-mcp-access.log` and `hermes-mcp-calls.log`;
   optional untested suspect: the Tailscale version mismatch.
4. Follow up on upstream #87641 if the author or a maintainer replies.
5. Queued lows in `docs/queue.md`: pane P1-P5, Paseo L1-L4, Hermes route (R1-M2, R1-L4, R1-L5e, R2-L6, R3).
6. Harmless side effects: the sub-agent's `git fetch` moved `upstream/main` in `~/.hermes/hermes-agent/.git`
   and added a generation under `~/.hermes/installs`; live Hermes still reports `bdea3a99`.

## Detached jobs
none open (`hermes-keycmd-models`, `paseo-listing` and `relay-pane-repair` were closed 2026-10-23).

## Quick Start
```bash
cd ~/src/djbclark-ade && git pull --rebase && git status -sb
rg -n 'P1|L1|R1-M2' docs/queue.md
tail -n 20 ~/.hermes/logs/hermes-mcp-calls.log
launchctl list | rg hermes-gateway
```
