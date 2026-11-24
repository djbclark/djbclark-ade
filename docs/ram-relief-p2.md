# RAM Relief Priority 2: Daemon Bloat Tracking & Idle Agent Hibernation (Queue #91 & #96)

Snapshot date: `2026-11-24`.

This document covers Priority 2 of the RAM relief plan (Queue #91 and #96, operator ruling `2026-11-24`):

1. **Report-only macOS system daemon bloat and advisory reboot-due tracking** in `bin/ram-census --daemons`.
2. **Safe idle-agent archiving / hibernation rules** in `bin/ade-tidy --idle-hours N`.
3. **Verified Paseo idle-process mechanics** and how `bin/ram-census --daemons`, `bin/ade-tidy --idle-hours`, `bin/ade-revive`, and `bin/ade-tidy prune` compose.

---

## 1. Verified Paseo Idle-Process Mechanics (checked `2026-11-24`)

Inspected `/Users/djbclark/src/paseo` (read-only) to verify how Paseo manages resident provider OS processes, archiving, and revival:

1. **No separate hibernate/suspend RPC or CLI command exists in Paseo.**
   - `packages/protocol/src/messages.ts` and `packages/cli/src/commands/agent/index.ts` expose `archive` (`archive_agent_request`), `reload`, `stop`, `delete`, `detach`, and `update`. There is no `hibernate` or `suspend` verb.
   - `AgentManager.closeAgent()` (`packages/server/src/server/agent/agent-manager.ts`) is an internal daemon lifecycle primitive invoked by `archiveAgent`, `agent-loading`, `agent-response-loop`, and `import-sessions`; it is not exposed as a standalone CLI command.

2. **`paseo agent archive <id>` terminates the resident OS process tree while preserving the session on disk.**
   - `archiveAgentCommand` (`packages/server/src/server/agent/lifecycle-command.ts:119-149`) calls `agentManager.archiveAgent(agentId)`.
   - `archiveAgentUnlocked` (`packages/server/src/server/agent/agent-manager.ts:1830-1873`) snapshots the agent to storage (`registry.applySnapshot`), stamps `archivedAt` (`markRecordArchived`), calls `closeAgentRuntime(agentId)` -> `agent.session.close()`, syncs native archive state (`syncNativeArchiveState`), discards retained in-memory state (`discardRetainedAgentState`), and cascades to unarchived children carrying `paseo.parent-agent-id`.
   - Provider `close()` implementations terminate the OS process tree:
     - **Claude** (`packages/server/src/server/agent/providers/claude/agent.ts:2934-3010`): closes the SDK query and calls `terminateWithTreeKill(this.childProcess, { gracefulTimeoutMs: 2_000, forceTimeoutMs: 2_000 })`, stopping the resident `claude` process and its MCP/LSP children while keeping the session transcript on disk (unless `persistSession === false`).
     - **JSONL-RPC providers** (Codex/Pi/ACP; `packages/server/src/server/agent/providers/jsonl-rpc-process.ts:226-241`, `codex-app-server-agent.ts:5032-5044`): closes stdin, disposes the client, and terminates the child tree with `terminateWithTreeKill`.
   - Archiving an idle agent therefore acts as **hibernation**: the resident OS process and its child MCP/LSP servers are released immediately, while the `StoredAgentRecord` (`persistence.sessionId` / `nativeHandle`) and provider transcript remain on disk under the exact same agent ID.
   - Any stray provider process that survives an archive (for example after a kill timeout or daemon crash) is caught and cleaned up by `bin/ade-tidy prune` after `ORPHAN_GRACE` (1800 s).

3. **Revival restores the same agent ID from persisted state.**
   - `sendPreparedPromptToAgent` (`packages/server/src/server/agent/agent-prompt.ts:198-208, 323-365`) clears `archivedAt` via `unarchiveAgentState` -> `agentManager.unarchiveSnapshot`, then calls `ensureAgentLoaded` (`packages/server/src/server/agent/agent-loading.ts:70-120`) -> `resumeAgentFromPersistence`, re-spawning the provider process with the preserved session handle and exact same agent ID.
   - In `djbclark-ade`, `bin/ade_send_guard.py` (`docs/archived-send-guard.md`) guards against accidental sends to archived agents, and `bin/ade-revive <id>` (Queue #97) provides the approved explicit revive path.

---

## 2. macOS Daemon Bloat & Reboot-Due Tracking (`bin/ram-census --daemons`)

Long-running macOS hosts accumulate non-reclaimable memory growth in system daemons (observed on bigmac on `2026-11-21`: `loginwindow` 2.85 GB, `corespotlightd` 2.5 GB, `launchservicesd` 830 MB after 11.5 days of uptime).

### Usage

```sh
bin/ram-census --daemons
bin/ram-census --daemons --json
bin/ram-census --daemons --footprint --json
bin/ram-census --daemons --ps-file /path/to/ps.txt --boottime-epoch 1700000000 --json
```

### Tracked Daemons

Matched strictly by exact executable basename from `ps -axo pid,ppid,rss,command` (never matching command arguments):

- `loginwindow`
- `corespotlightd`
- `launchservicesd`
- `WindowServer`
- `mds_stores`
- `mds`
- `distnoted`
- `cfprefsd`

### Advisory Reboot-Due Thresholds (strictly report-only)

When `--footprint` is passed (macOS), each daemon's effective memory is `max(rss_mb, footprint_mb)` so compressed and swapped pages are accounted for while still degrading safely on Linux where `footprint` is absent. Host uptime is read from `sysctl -n kern.boottime` on macOS, `/proc/uptime` (fallback `/proc/stat`) on Linux, or `--boottime-epoch SECONDS` for deterministic testing.

`reboot_due` becomes `true` (with explanatory entries in `reboot_reasons`) if **any** of these advisory thresholds is met:

| Rule | Threshold | Rationale |
|---|---|---|
| Total tracked daemons | `>= 4096 MB` (4.0 GB) | Combined macOS system daemon bloat materially erodes working-set headroom on a 32 GB host |
| Any single tracked daemon | `>= 2048 MB` (2.0 GB) | Single-daemon leak (such as `loginwindow` 2.85 GB or `corespotlightd` 2.5 GB) |
| Long uptime + elevated daemon memory | `uptime_days >= 14.0` **and** `effective_total_mb >= 2560 MB` (2.5 GB) | Cumulative kernel/daemon fragmentation after two weeks without a reboot |

**Strictly report-only:** `bin/ram-census` never restarts daemons and never runs `reboot` or `shutdown`. Deciding when to reboot is always the operator's call.

### JSON Schema (`_daemons` key when `--daemons` is passed)

```json
{
  "_daemons": {
    "daemons": {
      "WindowServer": { "n": 1, "rss_mb": 130.8 },
      "loginwindow": { "n": 1, "rss_mb": 62.7 }
    },
    "effective_total_mb": 193.5,
    "reboot_due": false,
    "reboot_reasons": [],
    "thresholds_mb": {
      "elevated_with_uptime": 2560.0,
      "single": 2048.0,
      "total": 4096.0
    },
    "total_rss_mb": 193.5,
    "uptime_days": 14.5,
    "uptime_threshold_days": 14.0
  }
}
```

---

## 3. Safe Idle-Agent Archiving / Hibernation (`bin/ade-tidy --idle-hours N`)

`bin/ade-tidy` adds `--idle-hours HOURS` (off by default; observe-only unless `--apply` is **also** passed; `--watcher-file PATH` optionally overrides `$LW_STATE_DIR/watcher.json`).

### Usage

```sh
# Observe-only: list idle-hibernation candidates, RSS, and reversibility notes
bin/ade-tidy --repo ~/src/<repo> --lead <full-lead-id> --reports-dir <dir> --idle-hours 4

# Apply: archive only proven-safe own-chain idle workers (re-checks every guard live first)
bin/ade-tidy --repo ~/src/<repo> --lead <full-lead-id> --reports-dir <dir> --idle-hours 4 --apply
```

### Mandatory Safety Guards (fail-closed)

Every guard is evaluated during planning and **re-verified live** right before each `paseo agent archive <id>` (always without `--force`):

1. **Never a running turn:** `status == "running"` is always excluded (`reason: running`). Only `idle` or `closed` agents are eligible.
2. **Never a pending permission card (or unreadable permits):** `paseo permit ls` failing fails closed; any agent with a pending permission or question card (`waiting-on-operator`) is excluded (`permission-pending` / `waiting-on-operator`).
3. **Never a standing watcher:**
   - Registered `load-watch` watcher (`$LW_STATE_DIR/watcher.json` or `--watcher-file`, read fail-closed — a corrupt, symlinked, oversized, or mismatched `paseo_home` watcher file refuses idle-hibernation archiving).
   - `ade.role` or `ade.kind` label containing `watch` (case-insensitive), or truthy `ade.watcher` label.
   - Title matching `\b(load[- ]?watch(?:er)?|watcher|watch[- ]?load)\b`.
4. **Never unreported or unacked paid work (`~/CLAUDE.md` item 9):**
   - All workers (both sliced and ad-hoc) fail closed when `paseo logs` is unreadable/empty (`logstate == "unreadable"`), when an inbound message is unanswered (`logstate == "inbound"`), when `verdict == "waiting-on-lead"` (`BLOCKED:`, trailing `?`, `Please reply: ack`, or unacked completion), or when the log tail contains `STATUS: working`, `BLOCKED:`, `NO-REPORT:`, or `Please reply: ack`.
   - Any own-chain worker with a `slice` label **must** have a verifiable regular report file (`unit-<slice>.md`, `<slice>-report.md`, or `<slice>-N-report.md`) in `--reports-dir` that:
     - does **not** contain `STATUS: working`, `BLOCKED:`, or `NO-REPORT:`,
     - ends in `DONE` with a current `<report>.done` marker,
     - is acked via `<report>.done.ack` (or `--handled`), and
     - has not been re-tasked or active after completion (`scan_log`, `.done.r*`, `lastUserMessageAt`, and `lastActivityAt <= act_base + ACTIVITY_MARGIN`, where `act_base` incorporates `.done.ack` only when the completion notice and ack receipt appear in the log tail).
   - Missing slice reports fail closed (`missing-report`).
   - Ad-hoc own-chain workers without a `slice` label require `status == "idle"` (a `closed` ad-hoc worker without a verified report is rejected as `closed-unverified` unless explicitly passed via `--handled`) and a readable log (`logstate == "ok"`) with no `STATUS: working`, `BLOCKED:`, `NO-REPORT:`, `?`, or `Please reply: ack`.
   - `ade.placement=main` workers are excluded unless explicitly listed in `--handled`.
5. **Never active worktree claims or live children:** agents holding an active claim (`bin/ade_claims.py`) or referenced as `paseo.parent-agent-id` by any unarchived child (which Paseo's archive would cascade to) are excluded; unreadable claim or agent records fail closed.
6. **Never operator-owned sessions or other leads' workers:** `operator`, `other-worker`, and `lead` sessions idle past `--idle-hours` are listed strictly under `idle_operator_candidates` (Section `I#o`) as operator-call items and are **never** archived by `--apply`.

---

## 4. How the Pieces Compose

1. **Measure & detect daemon bloat:** run `bin/ram-census --daemons` (or `--daemons --footprint --json`) to inspect MCP/LSP memory alongside macOS system daemon growth and check whether an advisory `reboot_due` threshold has been crossed.
2. **Observe idle-hibernation candidates:** run `bin/ade-tidy --repo ... --lead ... --reports-dir ... --idle-hours 4` to inspect Section `I` — each candidate shows idle age, best-effort resident RSS (`provider` + direct children), and its exact `bin/ade-revive <id>` reversibility command.
3. **Hibernate proven-safe own-chain workers:** re-run with `--apply` from the top-level lead session. Paseo closes the provider OS process tree (`terminateWithTreeKill`) while retaining the agent record and transcript on disk.
4. **Revive on demand:** when an archived worker's context is needed again, revive it cleanly with `bin/ade-revive <id>` (or, for the lead's own worker, send directly per the `2026-11-21` ruling in `docs/archived-send-guard.md`).
5. **Sweep stray orphans:** scheduled `bin/ade-tidy prune --apply` continues to catch any orphaned provider process left behind after an archive once `ORPHAN_GRACE` (1800 s) elapses.
