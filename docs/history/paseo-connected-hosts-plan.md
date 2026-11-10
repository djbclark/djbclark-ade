# Paseo connected hosts — plan (snapshot 2026-11-10)

Carried queue item 8. **Plan only** — no live host or daemon changes until the operator says yes (order 11) and Paseo is upgraded in a quiesced window.

## Goal

Register **vps-primary** as a connected Paseo host on the Mac (operator user `djbclark`), so cross-host listing, messaging and remote workspace operations use Paseo's native `list_hosts`, `--host`, and `paseo send --json` with `{serverId, agentId}` (see `docs/old-way-new-way.md` section C) instead of bespoke relays.

## Blocked on

1. **Operator** — explicit approval before pairing credentials, listener changes, or any write on vps-primary or the Mac daemon.
2. **Quiesced Paseo upgrade** — both hosts on a supported release with connected hosts available (shipped 0.13.0+); upgrade only while agents are drained or idle so an unfinished turn is not lost mid-restart (`docs/slim/operator-batch.md` A1, `docs/slim/PLAN.md` Wave 3). Queue item 7 (brew → fork) stays **after** this work.

## Pre-flight inventory (read-only)

On the Mac and on vps-primary, record before any pairing:

| Check | Mac | vps-primary (`user djbclark`, dedicated `PASEO_HOME` per `docs/paseo-only-rearchitecture.md` F3 item 8) |
| --- | --- | --- |
| Daemon version | `paseo version` / health | Same over Tailscale (`wss://vps-primary.greyhound-sidemirror.ts.net:7263` in prior probes) |
| Plugins | `paseo plugin ls --json` | `paseo --host … plugin ls` (credentials via `sudo-secretspec`, not argv) |
| Listener | loopback-only for Mac pilot | Tailnet-bound listener; ACL admits only trusted nodes |
| Skills / MCP | skill dirs on each host stay independent (`docs/old-way-new-way.md` D) | |

Note per-host plugin enablement; do not flip remote settings during inventory. Cross-host **peer ack** and file transfer are **not** proved until a dedicated verify slice runs.

## Connect (when unblocked)

1. Quiesce: no active slice writers; drain or finish turns; snapshot daemon and `~/.paseo` config paths.
2. Align Paseo versions on Mac and vps-primary through the normal deploy path (`deploy-vps-primary` / `just update` pattern in `docs/setup-plan.md`).
3. Set vps-primary daemon password and tailnet listener per F3; run pilot agents only under the dedicated unprivileged user.
4. On the Mac, add the host in Paseo's connected-hosts UI or config; verify with read-only calls: `list_hosts`, `paseo ls -a --host <target>`, one `paseo send --no-wait --json` round-trip with a named ack (order 10).
5. Document the saved `serverId` and connection label in operator state (not in git).

## Rollback

1. Remove the connected-host entry on the Mac (or disable the remote registration).
2. Confirm CLI and Desktop no longer list vps-primary (`list_hosts` empty for that target).
3. Leave vps-primary's daemon running for other uses unless the operator chooses a full stop; no Mac credential on vps-primary for Mac daemon access (F3 item 9).
4. Revert to same-host `paseo send` and the relay shim until its removal date (Carried 33) if cross-host traffic was in use.

## Related docs

- `docs/old-way-new-way.md` — cross-host messaging and handoff rules
- `docs/paseo-only-rearchitecture.md` — F3 vps-primary hardening and janitor/herald checks
- `docs/threat-model.md` — vps-primary trusted-host stance
- Queue item 7 — brew Paseo fork (after connected hosts)
