# Claude `sandbox.filesystem.denyRead` trial (2026-11-10)

Carried #1 / issue #284: the hook and static `permissions.deny` are a speed bump; the OS wall is
`sandbox.filesystem.denyRead` on Bash and its children (`docs/secret-deny.md` C3). This doc is the
**operator trial plan only**. It does **not** mutate live `~/.claude/settings.json` (order 11). Agents
document and propose; the operator applies, measures, and rolls back.

Related: PR #405 renders the same list into `agents/claude/settings.json.tmpl` (when merged) without
setting `sandbox.enabled`. The Codex parallel is PR #446 — an inactive
`[permissions.ade-secret-deny]` profile in `agents/codex/config.toml.tmpl` (no `default_permissions`;
openai/codex#22179 tracked early deny-glob docs that did not enforce — re-probe before treating either
wall as proven).

## A. Proposed `denyRead` entries (mirror `[claude] static`)

Source of truth: `config/secret-deny.toml` `[claude] static`. Exception-bearing patterns (`.env.*`,
`~/.ssh/**`) stay **hook-only**; the sandbox list is the narrower exception-free set. Bare / `**/…`
names are home-anchored as `~/**/…` so Linux has a fixed folder before the wildcard (same form PR
#405's render writes). Exact `~/…` credential paths stay exact.

```json
"sandbox": {
  "filesystem": {
    "denyRead": [
      "~/**/.env",
      "~/**/*.key",
      "~/**/*.p12",
      "~/**/*.pfx",
      "~/**/*-key.pem",
      "~/**/*.key.pem",
      "~/**/privkey*.pem",
      "~/**/id_rsa",
      "~/**/id_ecdsa",
      "~/**/id_ed25519",
      "~/.ssh/id_rsa",
      "~/.ssh/id_ecdsa",
      "~/.ssh/id_ed25519",
      "~/.aws/credentials",
      "~/.netrc",
      "~/.config/gh/hosts.yml",
      "~/.docker/config.json",
      "~/.kube/config"
    ]
  },
  "enabled": true
}
```

Notes:

- **A1.** Do not add `.env.example` / `*.pub` / `~/.ssh/known_hosts` / `~/.ssh/config` to `denyRead`;
  those are `allow` in the policy and must remain readable.
- **A2.** Do not deny `~/.ssh/**` whole in the sandbox list: that would also block allowed
  `known_hosts` / `config` / `*.pub` under `~/.ssh`.
- **A3.** Claude claims `denyRead` also merges from `Read(...)` deny rules, but Bash has been observed
  to honour only the explicit `filesystem.denyRead` list (anthropics/claude-code#55288) — list the
  paths here explicitly.
- **A4.** If PR #405 has already landed, copy `denyRead` from the rendered
  `agents/claude/settings.json.tmpl` rather than retyping; keep `sandbox.enabled` off in the
  template and flip it only in the live trial copy.

## B. How to trial (operator)

- **B1. Backup.** Copy live settings aside (do not overwrite a previous backup):
  `cp -a ~/.claude/settings.json ~/.claude/settings.json.bak-denyread-$(date +%Y%m%d)`.
- **B2. Merge.** In a **manual** edit of `~/.claude/settings.json` (not by an agent, not by
  `ade-update` alone): set `sandbox.filesystem.denyRead` to the A list and set `sandbox.enabled` to
  `true`. Leave every other key alone (`permissions`, hooks, `defaultMode`, skill overrides). Prefer
  a JSON-aware editor; a broken settings file takes Claude Code down.
- **B3. Fresh session.** Start a new Claude Code session after the edit (sandbox settings are read at
  process start). Confirm the session is sandboxed (Claude's sandbox indicator / docs for the
  installed version).
- **B4. Positive probes (must refuse).** In that session, via **Bash** (the wall is for Bash and
  children): attempt reads that should fail, e.g. `cat ~/.aws/credentials`, `cat ~/.netrc`,
  `cat ~/.ssh/id_ed25519` (only if that key exists; otherwise `cat` of a path matching `~/**/*.key`
  you control). Record the error text and whether a non-Bash `Read` tool still hits the hook /
  static deny (different layer — both should refuse; only Bash proves the OS wall).
- **B5. Negative probes (must still work).** `cat ~/.ssh/known_hosts`, `cat ~/.ssh/config`, read an
  `.env.example` in a project, and ordinary project source. A false refuse here is a rollback trigger.
- **B6. Scope check.** Confirm sandbox did not break unrelated work you care about (network, writes
  outside the project, nested tools). Note anything surprising beside denyRead.
- **B7. Record.** Write the date, Claude Code version, probe results, and whether B4's Bash refuse
  was actually the sandbox (OS) or only the hook (stderr `secret-read-gate:`) into the Carried #1
  trail (`docs/secret-deny.md` C3 or a dated note). A hook-only refuse means the OS wall is still
  unproven — same caution PR #446 takes for openai/codex#22179.

## C. Risks

- **C1. Broader than denyRead.** `sandbox.enabled = true` turns on Claude's whole sandbox, not only
  the read-deny list. Expect side effects on network, writes, and child processes that have nothing
  to do with secrets.
- **C2. Incomplete mirror of `deny`.** `.env.*` and `~/.ssh/**` stay hook-only so allows keep
  working; a sandboxed Bash that constructs `~/.ssh/other-secret` or `.env.local` may still read it
  at the OS layer. The hook remains required.
- **C3. Enforcement may be weaker than docs claim.** anthropics/claude-code#55288: Bash may ignore
  deny paths that exist only as `permissions.deny` `Read(...)` rules. Always put paths in
  `filesystem.denyRead`. After apply, re-probe — do not assume the template landing (#405) equals a
  working wall.
- **C4. Codex parallel (#446).** Shipping an inactive profile / template list is not evidence the
  installed binary enforces it. openai/codex#22179 is the same class of trap for Codex; treat the
  Claude trial the same way: measure, then claim.
- **C5. Operator-only apply.** An agent rewriting `~/.claude/settings.json` violates order 11. A
  botched JSON edit or an accidental commit of live settings into this repo are both out of scope
  for this trial doc's automation — there is none.
- **C6. Fail-open elsewhere.** The PreToolUse hook still fails open on bad input / budget
  (`docs/secret-deny.md` C7). The sandbox trial does not fix that; it only adds an OS layer when it
  actually runs.

## D. Rollback

- **D1. Fast.** Set `"sandbox": { "enabled": false }` in `~/.claude/settings.json` (keep or drop
  `denyRead`; with enabled false the OS wall is off). Restart Claude Code.
- **D2. Clean.** Restore the B1 backup: `cp -a ~/.claude/settings.json.bak-denyread-YYYYMMDD
  ~/.claude/settings.json`, then restart.
- **D3. Template.** Do **not** set `sandbox.enabled` in `agents/claude/settings.json.tmpl` as part of
  rollback or trial success; the template stays disabled so installs do not surprise other machines.
  Render-owned `denyRead` in the template (PR #405) can remain.

## E. Done when

The trial is done (Carried #1's denyRead bullet can narrow) when B4 shows a **sandbox** refuse on at
least one denied Bash read, B5 shows no false refuses on allows, and the operator either keeps
`sandbox.enabled` on with the A list or rolls back and records why. Template/render without live
apply does not close the item.
