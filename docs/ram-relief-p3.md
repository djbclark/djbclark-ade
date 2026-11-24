# RAM Relief Priority 3: End Paseo CLI Polling Storms & Consolidate Daemon Client (Queue #90)

Snapshot date: `2026-11-24`.

This document covers Priority 3 of the RAM relief plan (Queue `#90`, operator directive `2026-11-24`):

1. **Empirical audit** of Paseo's actual loopback daemon API surface and every `paseo` CLI polling loop across `djbclark-ade/bin/`, `launchd` jobs, `site-public-djbclark/bin/fleet-watch`, and Paseo plugins (`~/.paseo/plugins/` and `djbclark-ade/plugins/`).
2. **Consolidation analysis & shared zero-subprocess daemon client (`bin/ade_paseo_client.py`)** unifying loopback HTTP/MCP and WebSocket RPC without Node.js subprocesses.
3. **Converted `djbclark-ade/bin/` pollers** and a concrete follow-up spec for out-of-repo pollers (`fleet-watch`, plugins) and optional `launchd` job consolidation.

---

## 1. Verified Paseo Loopback Daemon API Surface (checked `2026-11-24`)

Inspected `/Users/djbclark/src/paseo` (`packages/server/src/server/{bootstrap.ts,auth.ts,websocket-server.ts,agent/tools/paseo-tools.ts}`, `packages/cli/src/{utils/client.ts,utils/agent-directory.ts,commands/agent/{ls,inspect}.ts,commands/permit/ls.ts,commands/usage/index.ts}`, `packages/protocol/src/{client-capabilities.ts,messages.ts}`), installed `/Applications/Paseo.app` (`0.17.3`), `~/.paseo/config.json`, and the live loopback daemon on `127.0.0.1:7263` (read-only):

1. **Discovery and auth:**
   - Default listen address comes from `<PASEO_HOME>/config.json` -> `daemon.listen` (`127.0.0.1:7263` on bigmac; `PASEO_HOME` defaults to `~/.paseo`). Paseo also supports `unix://` IPC sockets.
   - When `daemon.password` is unset (bigmac's live config), loopback HTTP (`/api/health`, `/api/status`, `/mcp/agents`) and `/ws` require no password. When password auth is enabled, `/ws` accepts `hello.auth = {"kind": "localCredential", "token": ...}` read from `<PASEO_HOME>/local-credential` (mode `0600`) or `{"kind": "password", "password": ...}` (`PASEO_PASSWORD`), and `/mcp/agents` accepts `Authorization: Bearer <password-or-capability-token>` (`packages/server/src/server/auth.ts:129-151`).
   - Every ADE daemon client call is restricted to loopback hosts (`127.0.0.1`, `localhost`, `::1`) or local `unix://` sockets, bypasses HTTP proxies (`urllib.request.ProxyHandler({})`), enforces strict timeouts and response size caps, and never logs or prints credentials.

2. **Two complementary loopback transports (verified empirically against live `127.0.0.1:7263`):**
   - **Stateless HTTP / Agent MCP (`POST /mcp/agents`, `GET /api/health`, `GET /api/status`):**
     - `bootstrap.ts:1537-1630` mounts a stateless Streamable HTTP MCP server (`sessionIdGenerator: undefined`), creating and tearing down the transport per HTTP request so zero session memory accumulates in the daemon.
     - Exposes 65 MCP tools, including `list_pending_permissions`, `respond_to_permission`, `get_agent_status`, `get_agent_activity`, `list_agents`, `list_workspaces`, `list_providers`, `list_models`, `list_schedules`, `update_agent`, `archive_agent`, and `send_agent_prompt`.
     - **Critical MCP limit uncovered by audit (`paseo-tools.ts:2125-2142`):** MCP `list_agents` enforces `limit <= 200` (default `50`) and `sinceHours <= 720` (default `48`). It CANNOT list all archived agents (bigmac had **4,560** agents with `includeArchived=True` on `2026-11-24`) and silently drops live agents older than 48 h under its defaults.
     - Conversely, MCP `list_pending_permissions` returns the **full** permission payload (`kind`, `provider`, `name`, `input`, `detail`, `metadata`), which `paseo permit ls --json` omits, and `get_agent_status` returns the full `AgentSnapshotPayload` including `labels` and `pendingPermissions` in 1 RTT (`~2 ms`).
   - **Loopback WebSocket RPC (`ws://<loopback>:<port>/ws`):**
     - Exact wire protocol used by the `paseo` CLI (`hello` with `protocolVersion: 1` and snake_case capabilities `{"hello_rejection": true, "all_providers": true, "explicit_event_subscriptions": true}` -> `server_info`, followed by `{"type": "session", "message": {..., "requestId": ...}}` envelopes).
     - **Important capability detail (`client-capabilities.ts:8`):** `all_providers` MUST be advertised in `hello.capabilities`; without it, Paseo filters out non-legacy providers (`antigravity`, `pi`, `cursor`, `hermes`) and returned only 8 of 35 live agents in our live probe.
     - Supports cursor-paginated `fetch_agents_request` (`sort: [{key: "created_at", direction: "desc"}]`, `page: {limit: 200, cursor}` — exact parity with CLI `fetchAllAgents`, returning all 35/35 live agents and paginating past 4,560 archived agents with zero truncation), exact server-side label filtering, `fetch_agent_request`, `fetch_workspaces_request`, `fetch_agent_timeline_request`, and `usage.list_reports.request`.

3. **Measured live latency & RAM comparison (`2026-11-24`, bigmac `127.0.0.1:7263`, 35 live agents):**
   - `paseo ls -g --background --json` (Node.js CLI subprocess): **`400.9 ms`**, **`~150 MB` transient Node RSS** per spawn.
   - `ade_paseo_client.PaseoClient().list_agents(...)` (stdlib Python WS): **`5.8 ms`**, **`0` Node spawns** (**69x faster**, exact 35/35 ID parity).
   - Combined 9-call live probe (`health`, `status`, `list_agents`, `list_pending_permissions`, `list_workspaces`, `list_providers`, `list_schedules`, `inspect_agent`, `list_usage_reports`): **`178.5 ms` total**, **`0` Node spawns**.

---

## 2. Complete Empirical Poller Audit Table (checked `2026-11-24`)

Every `launchd` job in `~/Library/LaunchAgents`, every `paseo` caller in `djbclark-ade/bin/`, `~/ops/site-public-djbclark/bin/fleet-watch`, and every plugin under `~/.paseo/plugins/` and `djbclark-ade/plugins/` was inspected read-only.

### A. Periodic / Looping Pollers (the polling storm)

| Tool | Repo | Cadence / Trigger | Previous `paseo` CLI Calls | Est. ~150 MB Node Spawns/hr | Status (`2026-11-24`) |
|---|---|---|---|---|---|
| `bin/ade-auto-permit` | `djbclark-ade` | `launchd` `StartInterval=60` (60/h) | `permit ls`, `ls -a -g` (4,560 archived!), `ls -a -g --label` x N, `agent inspect`, `permit allow` | **180–300+/h** | **CONVERTED** -> `PaseoClient` (1-RTT MCP `list_pending_permissions`; 0 spawns on idle ticks; `inspect_agent` + `respond_to_permission` when pending) |
| `bin/ade-net-resume` | `djbclark-ade` | `launchd` `StartInterval=60` (60/h) | `agent inspect <lead>`, `ls -g --background`, per-candidate `agent inspect`, `ls -a -g` | **120–240+/h** | **CONVERTED** -> `PaseoClient` (`inspect_agent`, `list_agents`; 0 CLI spawns on quiet ticks; rare `logs`/`send` on actual error recovery) |
| `bin/load-watch` | `djbclark-ade` | `launchd` `StartInterval=20` (180/h) + `admit --max-agents` | `ls -g --background --json` on every CPU spike & `admit --max-agents` check | **0–180+/h** | **CONVERTED** -> `PaseoClient` (`paseo_agents()`, `count_agents()`, opt-in short-TTL cache) |
| `bin/ade_approval_window.py` | `djbclark-ade` | `launchd` `StartInterval=60` (2 s inner loop while grant open) | Already loopback HTTP `/mcp/agents` (duplicated client) | 0/h | **UNIFIED** -> `McpDaemon` delegates to `ade_paseo_client.McpClient` |
| `bin/deadline` (`sweep` / `agent_rows`) | `djbclark-ade` | `launchd` `StartInterval=60` (60/h; agent scan every 300 s) | `ls -g --background`, `inspect` per running agent, `agent inspect` before send | **12–60+/h** | **CONVERTED** -> `PaseoClient` (`list_agents` carries `updatedAt`, `inspect_agent` fallback) |
| `bin/ade-progress` (`scan --yes`) | `djbclark-ade` | `launchd` `StartInterval=300` (12/h) | `ls -g --background`, `inspect` per open declaration (+ preflight re-inspect) | **12–60+/h** | **CONVERTED** -> `PaseoClient` (`list_agents`, `inspect_agent`; rare `wake` send stays CLI) |
| `bin/ade-supervisor-scan` + `bin/ade-pi-stuck` | `djbclark-ade` | `launchd` `StartInterval=300` (12/h) | `ade_send_guard.py` (`agent inspect`) + `ade-pi-stuck` (`ls -g --background`) | **24/h** | **CONVERTED** -> `PaseoClient` via `ade_send_guard.py` + `ade-pi-stuck` (0 spawns on quiet ticks) |
| `bin/ade_send_guard.py` + `bin/ade-paseo-guard` | `djbclark-ade` | Invoked by `ade-supervisor-scan`, `ade-subagent-stalls`, `deadline`, every `paseo send` | `agent inspect` + `ls -a -g --label` (canary + lineage) | **24–100+/h** | **CONVERTED** -> `PaseoClient` (`inspect_agent`, `list_agents(labels=...)`) by default (honours `ADE_PASEO_TRANSPORT=cli`) |
| `bin/ade_subagent_stalls.py` | `djbclark-ade` | Periodic / `fleet-watch` hook-in candidate | Up to 40 `agent inspect` + `ade_send_guard` probes per run | **0–40/run** | **CONVERTED** -> `PaseoClient` (`--daemon-url` / default daemon mode; preserves `--paseo` CLI path) |
| `bin/ade-pin-sweep` (`ade-archive-retired` + `ade-pin-interactive` + `ade-pin-workspaces`) | `djbclark-ade` | `launchd` `StartInterval=900` (4/h) | `ade-archive-retired` (`ls -g`, `inspect`, `archive`), `ade-pin-interactive` (`ls -g`, `agent update`), `ade-pin-workspaces` (Electron Node WS client) | **12–32/h** | **CONVERTED** `ade-archive-retired` + `ade-pin-interactive` -> `PaseoClient`; `ade-pin-workspaces` uses `workspace.pin.set` WS RPC (4/h; follow-up candidate) |
| `bin/ade-tidy` (`prune --apply`) | `djbclark-ade` | `launchd` `StartInterval=1800` (2/h) | `agent inspect` only on orphan-candidate PIDs (0 when clean) | **0–8/h** | Kept CLI for rare orphan archive/inspect (2/h low volume); candidate for future `PaseoClient` wiring |
| `bin/fleet-watch` (`phantom_watch`) | `site-public-djbclark` | `launchd` `StartInterval=300` (12/h) | `paseo ls --json` + `paseo inspect <id> --json` per running agent (+ rare `paseo logs` / `fleet_watch_paseo.py`) | **24–120+/h** | **OUT-OF-REPO** — ready-to-implement spec in Section 4 below |

### B. Rare One-Shot Mutations / Interactive CLI Tools (NOT polling storms)

- `bin/ade-self-session`, `bin/ade-worker-run`, `bin/ade-revive`, `bin/ade-request-archive`, `bin/completion-notice`, `bin/xmsg`, `bin/fable-wait`, `bin/ade-recovery-d1`, `bin/ade-sched` (`reconcile`), `bin/ade-install` (`observe_paseo_plugin`), `bin/route_agent.py` (on-demand routing with 30 s memo), `bin/quota_signals.py`, `bin/context-watch`, `bin/paseo-set-model`: invoked on demand or during explicit mutations (`paseo run`, `paseo send`, `paseo schedule create`, `paseo agent reload`), not in background polling loops. Converting their reads later is optional cleanup, not a RAM storm driver.

### C. Paseo Plugins Audit (`~/.paseo/plugins/` and `djbclark-ade/plugins/`, read-only)

- **Enabled third-party plugins** (`baton`, `better-paseo`, `pr-radar`, `resources`, `session-recovery`, `paseo-runner`, `herald`, `forges`, `paseo-cafe`, `progress`, `paseo-sidechat`, `transfer`, `paseo-chat-polish`, `github-board`, `paseo-switcher`, `questions-please`, `switch-provider`, `tell-agent`, `claude-code-entrypoint-env`, `paseo-session-guard`, `reopen-archived`, `skills`, `dann-workspace-accent`, `herdr-harness`): run in-process inside the Paseo daemon via `@getpaseo/plugin/server` APIs and do **not** run periodic `paseo` CLI subprocess loops. (`better-paseo/tools/bench-provider/scripts/verify.mjs` is a manual dev benchmark script; `pr-radar/sandbox/` runs `paseo reload`/`daemon pair` inside Docker sandboxes on container start, not a loop; `baton` runs `spawnHandoffWriter` in-process via Paseo API.)
- **Disabled third-party plugin** `conversation-folders` (`enabled: false`): `server/conversation-actions.ts:15,28` spawns `execFile('paseo', ...)` for user-triggered delete/rename (not a loop).
- **ADE-owned plugin `djbclark-ade/plugins/ade-claim/server/hook.mjs:422`** (`enabled: true`): event-driven (not a periodic loop), but spawns `ctx.spawn(paseo, ["agent", "inspect", "--json", "--", oldOwner])` on workspace-claim collision. Follow-up spec in Section 4 replaces that with in-process plugin API or loopback HTTP `fetch("http://127.0.0.1:7263/mcp/agents")`.

**Net impact of this PR in `djbclark-ade`:** eliminates **~380–900+ Node.js (~150 MB) CLI spawns per hour** across `ade-auto-permit`, `ade-net-resume`, `load-watch`, `ade-progress`, `ade-supervisor-scan`/`ade-pi-stuck`, `ade_send_guard`, `ade-pin-sweep` (`ade-archive-retired` + `ade-pin-interactive`), `deadline`, and `ade-subagent-stalls`, reducing steady-state polling overhead from hundreds of ~400 ms / ~150 MB Node startups per hour to sub-10 ms stdlib Python loopback requests.

---

## 3. Consolidation Analysis

Operator directive (`2026-11-24`): *"also consider if some variety of consolidation would make sense."*

### 3.1 Shared Library Consolidation — **SHIPPED IN THIS PR**

- **Before:** Every poller hand-rolled `subprocess.run(["paseo", ...])`, JSON parsing, timeout handling, and error mapping, while `bin/ade_approval_window.py` carried its own loopback HTTP/MCP client (`McpDaemon`).
- **Now (`bin/ade_paseo_client.py`):** One stdlib-only Python 3.9+ module (macOS + Linux) provides:
  - `discover_daemon_target()` (`ADE_PASEO_URL` -> `<PASEO_HOME>/config.json` -> `127.0.0.1:7263`, strict loopback / `unix://` enforcement).
  - `McpClient` (stateless `/mcp/agents`, `/api/health`, `/api/status`, SSE + JSON decoding, proxy-bypass, bounded reads) — `bin/ade_approval_window.py`'s `McpDaemon` now delegates directly to `McpClient`.
  - `WsClient` (pure stdlib RFC 6455 loopback WebSocket client with `Sec-WebSocket-Accept` verification, fragmentation, ping/pong, cursor-paginated `fetch_agents`, `fetch_agent`, `fetch_workspaces`, `fetch_agent_timeline`, `list_usage_reports`).
  - `PaseoClient` unified facade + CLI-shape mappers (`snapshot_to_ls_row`, `snapshot_to_inspect_dict`, `mcp_permission_to_cli_row`).
  - `transport_mode()` defaulting to `"daemon"` (zero subprocesses, fail-closed on daemon errors) with explicit `"cli"` opt-in (`ADE_PASEO_TRANSPORT=cli` or explicit CLI binary path flags/env vars for backwards compatibility).

### 3.2 Shared Short-TTL Atomic Snapshot Cache — **SHIPPED OPT-IN IN THIS PR**

- `ade_paseo_client.SnapshotCache` writes atomic snapshots (`0700` dir `~/.local/state/djbclark-ade/paseo-cache/`, `0600` temp file + `fsync` + `os.replace`, `O_NOFOLLOW` bounded reads) keyed by daemon target and query parameters.
- **Disabled by default (`ttl_s = 0`)**; operators or launchd jobs can enable it via `ADE_PASEO_CACHE_TTL=<seconds>` (e.g. `5` seconds).
- **Strict safety boundary:** Only advisory read-only pollers (`load-watch`, `ade-pi-stuck`) pass `use_cache=True`. Every safety-critical guard or pre-mutation check (`ade-auto-permit`, `ade-approval-window`, `ade-archive-retired`, `ade-net-resume`, `ade-progress`, `ade_send_guard`, `ade_subagent_stalls`) ALWAYS passes `use_cache=False` and reads live daemon state directly.
- **Why opt-in:** Because a live loopback WS `fetch_agents` call takes only **5.8 ms** and MCP `list_pending_permissions` takes **~2 ms**, removing Node.js subprocesses already eliminates >99% of CPU/RAM cost without introducing cache-staleness risk. The cache is available if multiple 20–60 s pollers later need to coalesce reads under heavy daemon load.

### 3.3 Consolidating Overlapping `launchd` Pollers — **PROPOSAL ONLY (REQUIRES OPERATOR APPROVAL)**

No live `~/Library/LaunchAgents/*.plist` files or external repos are modified in this PR. Based on our live `LaunchAgents` inventory, two targeted consolidations make strong operational sense once approved:

1. **Permission sweepers (`StartInterval=60`): `com.djbclark.ade-auto-permit` + `com.djbclark.ade-approval-window`:**
   - Both run every 60 s against `list_pending_permissions` (and `ade-approval-window` runs an inner 2 s loop for 50 s while `/var/db/sudo-ask/grant` exists).
   - **Recommendation:** Keep their policy modules separate (different trust boundaries: `ade-approval-window` gates on root-owned `/var/db/sudo-ask/grant` and allows `rm` cards; `ade-auto-permit` scopes to lead lineage/labels and holds `HOLD_TOOLS`), OR combine only their launchd tick wrapper once `ade-auto-permit` is verified quiet at 0 CLI spawns/h. Because both are now ~2 ms stateless HTTP calls, the remaining RAM cost of two separate 60 s Python invocations is negligible (~15 MB transient Python for <50 ms).
2. **5-minute fleet/agent health sweepers (`StartInterval=300`): `ade-supervisor-scan`, `ade-progress`, `ade-subagent-stalls`, and `fleet-watch`:**
   - Currently 3 separate `launchd` jobs (`ade-supervisor-scan`, `ade-progress`, `fleet-watch`) fire every 300 s, and `ade-subagent-stalls` is waiting to hook into `fleet-watch`.
   - **Recommendation:** Keep `fleet-watch` (`site-public-djbclark`: phones, VPS, GitHub PRs, S1, load) separate from `djbclark-ade` agent monitors, and consider a single `com.djbclark.ade-agent-sweep` (`StartInterval=300`) that runs `ade-supervisor-scan`, `ade-progress scan --yes`, and `ade-subagent-stalls --notify` sequentially under one `ade-job-run` lock — sharing one `ADE_PASEO_CACHE_TTL=10` snapshot for read-only scans while preserving independent state files and failure isolation (one failing step never aborts the others).
   - **Do NOT merge `load-watch` (`StartInterval=20`)** into a 60 s or 300 s job: `load-watch` needs its 20 s sampling cadence for CPU/swap spike detection and admission control, and its steady-state sample already makes zero Paseo calls unless a spike occurs.
   - **Do NOT introduce a persistent long-running Python watcher daemon yet:** Short-lived `launchd` jobs release 100% of their Python RSS immediately after each 50 ms tick; a persistent Python daemon would add a permanent RSS baseline and crash-recovery surface without saving meaningful RAM once Node.js spawns are gone.

---

## 4. Follow-Up Spec for Out-of-Repo Pollers (Not Edited in This PR)

### 4.1 `~/ops/site-public-djbclark/bin/fleet-watch` (`phantom_watch`) & `bin/fleet_watch_paseo.py`

Currently `fleet-watch` (`StartInterval=300`, 12 runs/h) runs `phantom_watch`, which spawns `paseo ls --json` (`line 1753`) plus `paseo inspect <id> --json` (`line 1762`) for every running agent (24–120+ Node spawns/h), and `fleet_watch_paseo.py` spawns `paseo ls -a -g --json` (`line 57`) + `paseo agent inspect` (`line 67`) on every relay.

**Ready-to-implement patch plan for `site-public-djbclark`:**
1. Import `ade_paseo_client` from `~/src/djbclark-ade/bin` (guarded by `FLEET_WATCH_PASEO` / `ADE_PASEO_TRANSPORT=cli` override so existing tests injecting fake `FLEET_WATCH_PASEO` keep working):
   ```python
   # In phantom_watch (bin/fleet-watch)
   sys.path.insert(0, str(home / "src/djbclark-ade/bin"))
   import ade_paseo_client as paseo_client

   if paseo_client.transport_mode(cli_env_vars=("FLEET_WATCH_PASEO",)) == "daemon":
       client = paseo_client.PaseoClient(timeout=CMD_TIMEOUT)
       listing = client.list_agents(include_background=False, include_archived=False, cli_rows=True)
       # Per running agent:
       info = client.inspect_agent(agent_id, cli_shape=True)
   ```
2. In `bin/fleet_watch_paseo.py`: replace the two read calls (`ls -a -g --json` and `agent inspect`) with `PaseoClient.list_agents(include_background=True, include_archived=True, cli_rows=True)` (or direct `inspect_agent(target)` when `target` is already a full UUID!) while keeping the rare `paseo send --prompt-file` mutation path (or switching to MCP `send_agent_prompt` once receipt semantics are parity-tested).
3. **Expected savings:** eliminates 24–120+ Node.js spawns/h from `com.djbclark.fleet-watch`.

### 4.2 `djbclark-ade/plugins/ade-claim/server/hook.mjs`

Converted. On a claim collision, the hook reads the previous owner through the Paseo plugin
SDK's `context.paseo.agents.ref(ownerId).refresh()`. An exact-ID archived snapshot or the SDK's
explicit missing-agent result permits the existing compare-and-swap rebind. Failed, ambiguous or
cancelled lookups leave the claim in place. Observe mode still only logs the plan.

### 4.3 `bin/ade-pin-workspaces`

Converted. The default sweep uses the stdlib `PaseoClient` to read full WebSocket workspace
descriptors (including pin and archiving state) and send the native `workspace.pin.set.request`
RPC. This removes the four scheduled Electron Node launches per hour. The legacy Electron
launcher remains available through explicit `ADE_PASEO_TRANSPORT=cli`.
