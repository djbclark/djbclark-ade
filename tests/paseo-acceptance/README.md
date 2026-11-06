# tests/paseo-acceptance (DRAFT, plan `docs/d1-implementation-plan.md`)

Probe scripts that prove the contracts of `docs/paseo-only-rearchitecture.md` D1. Each has a header with
CONTRACT, EXPECT, ON-FAIL, SCOPE, HOW, NEEDS. Exit 0 pass, 1 fail, 77 precondition missing, 2 usage or refused.
Results go to `$ADE_ACCEPTANCE_RESULTS` (default `~/.local/state/ade/acceptance`) as JSON lines with the CLI and daemon versions.

| Directory or file | Scope |
|---|---|
| `readonly/ro-*.sh` | read-only against the live daemon; safe |
| `isolated-smoke.sh` | second daemon only: proves `lib/common.sh` `isolated_up`/`isolated_down` (own serverId, password enforced, no plugins, no speech download, live daemon and config untouched, nothing left behind); run by hand, about 25 s |
| `d1-02-card-option.sh` | second daemon only: answers an omp `ask` question card's option 2 by CLI (`permit allow --input`) and by the paseo MCP tool `respond_to_permission` (`lib/mcp_call.py`, over the socket: a Unix-socket daemon injects no MCP into agents); two haiku turns, never the Claude subscription; passed 2026-11-02, about 2 min |
| `lib/common.sh` `isolated_restart_guard` / `isolated_restart_now` / `isolated_restart` | `paseo --home <isolated home> restart` of the isolated daemon only: asserts on physical paths that the home is `$ACC_BASE/home` (never `~/.paseo`) and that the daemon there is the one `isolated_up` started; the supervisor survives, the worker is replaced (T8) |
| `lib/mcp_call_as.py` | agent-scoped MCP call over the isolated daemon's socket (`/mcp/agents?callerAgentId=ID`): `create_agent` with `notifyOnFinish`, `send_agent_prompt`; needs `daemon.mcp.injectIntoAgents=true` in the isolated config (T8) |
| `d1-*.sh` marked `DESTRUCTIVE: second daemon only` | restart, hang or kill a daemon (plan B10); refuse unless `PASEO_HOME` is a fresh test home |
| `watchdog-selftest.sh`, `d1-09-deadman.sh`, `drain/check-disabled.sh --self-test` | hermetic, no daemon |
| `drain/*.sh` | D0.2 drain records; read-only |
| `deadman/` | D1.9 scripts for vps-primary and the Mac sender; not installed |
| `fixtures/origin-probe-plugin/` | stub plugin, SDK names UNVERIFIED |
| `d1-07a-tabs.md`, `d1-11-push-off-tailnet.md` | manual checklists |

`run-all.sh --list` shows scopes; `--readonly` runs only the safe ones. Nothing here is wired into CI.
