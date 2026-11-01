# tests/paseo-acceptance (DRAFT, plan `docs/d1-implementation-plan.md`)

Probe scripts that prove the contracts of `docs/paseo-only-rearchitecture.md` D1. Each has a header with
CONTRACT, EXPECT, ON-FAIL, SCOPE, HOW, NEEDS. Exit 0 pass, 1 fail, 77 precondition missing, 2 usage or refused.
Results go to `$ADE_ACCEPTANCE_RESULTS` (default `~/.local/state/ade/acceptance`) as JSON lines with the CLI and daemon versions.

| Directory or file | Scope |
|---|---|
| `readonly/ro-*.sh` | read-only against the live daemon; safe |
| `d1-*.sh` marked `DESTRUCTIVE: second daemon only` | restart, hang or kill a daemon (plan B10); refuse unless `PASEO_HOME` is a fresh test home |
| `watchdog-selftest.sh`, `d1-09-deadman.sh`, `drain/check-disabled.sh --self-test` | hermetic, no daemon |
| `drain/*.sh` | D0.2 drain records; read-only |
| `deadman/` | D1.9 scripts for vps-primary and the Mac sender; not installed |
| `fixtures/origin-probe-plugin/` | stub plugin, SDK names UNVERIFIED |
| `d1-07a-tabs.md`, `d1-11-push-off-tailnet.md` | manual checklists |

`run-all.sh --list` shows scopes; `--readonly` runs only the safe ones. Nothing here is wired into CI.
