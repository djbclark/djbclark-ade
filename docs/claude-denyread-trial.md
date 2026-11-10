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
  "enabled": true,
  "allowUnsandboxedCommands": false,
  "failIfUnavailable": true
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
  template and flip it only in the live trial copy. Do **not** bake `enabled: true` into the
  template; the live trial copy still needs A5's escape-hatch closers before claiming an OS wall.
- **A5. Close the unsandboxed-retry escape hatch before treating `denyRead` as the OS wall.** With
  the template's `permissions.defaultMode: "bypassPermissions"` (`docs/secret-deny.md` C2), a
  sandboxed Bash that hits `denyRead` can still be retried with `dangerouslyDisableSandbox` and
  that retry runs **without a prompt**, so `denyRead` is bypassed. Set
  `sandbox.allowUnsandboxedCommands` to `false` (Claude ignores `dangerouslyDisableSandbox`) and
  `sandbox.failIfUnavailable` to `true` (no silent fall-back to unsandboxed when the sandbox cannot
  start). See [Claude sandboxing — unsandboxed retry](https://code.claude.com/docs/en/sandboxing#the-unsandboxed-retry-escape-hatch).
  A trial that only sets `enabled` + `denyRead` is incomplete.

## B. How to trial (operator)

- **B1. Backup.** Copy live settings aside (do not overwrite a previous backup):
  `cp -a ~/.claude/settings.json ~/.claude/settings.json.bak-denyread-$(date +%Y%m%d)`.
- **B2. Merge.** In a **manual** edit of `~/.claude/settings.json` (not by an agent, not by
  `ade-update` alone): set `sandbox.filesystem.denyRead` to the A list, set `sandbox.enabled` to
  `true`, set `sandbox.allowUnsandboxedCommands` to `false`, and set `sandbox.failIfUnavailable` to
  `true` (A5 — required before any B4 refuse counts as the OS wall). Leave every other key alone
  (`permissions`, hooks, `defaultMode`, skill overrides). Prefer a JSON-aware editor; a broken
  settings file takes Claude Code down.
- **B3. Fresh session.** Start a new Claude Code session after the edit (sandbox settings are read at
  process start). Confirm the session is sandboxed (Claude's sandbox indicator / `/sandbox` Overrides
  shows unsandboxed retries off / docs for the installed version). If Claude Code exits at startup
  because the sandbox is unavailable, that is `failIfUnavailable` working — fix deps or roll back
  (D); do not flip it back to false for the trial.
- **B4. Positive probes (must refuse).** In that session, via **Bash** (the wall is for Bash and
  children): attempt reads that should fail **without ever printing secret bytes**. Prefer synthetic
  canaries that match deny patterns, or an open-only check that reports success/fail only:
  - **B4a. Glob canaries (preferred).** Under a disposable dir you own, create non-secret files whose
    names match the A list, e.g. `mkdir -p ~/tmp/denyread-trial && printf 'canary-not-a-secret\n' >
    ~/tmp/denyread-trial/canary.key` (and optionally `…/canary.env`, `…/privkey-canary.pem`). Then
    `cat ~/tmp/denyread-trial/canary.key` (and siblings). Expect refuse; the printed text, if any,
    is only the canary string or the sandbox/hook error — never a live key.
  - **B4b. Exact-path probes (open-only).** For exact entries (`~/.aws/credentials`, `~/.netrc`,
    `~/.ssh/id_ed25519`, …) do **not** `cat` them. Skip any exact path that is absent
    (`test -e …`). For a path that exists, probe open without emitting contents, e.g.
    `python3 -c 'from pathlib import Path; open(Path.home()/".aws"/"credentials","rb").close(); print("opened")'`
    and record only the exit code / sandbox error text (refuse → non-zero or blocked stderr; never
    log or paste file bytes into the session note).
  - **B4c.** Record the error text and whether a non-Bash `Read` tool still hits the hook / static
    deny (different layer — both should refuse; only Bash proves the OS wall). Remove the canary
    dir when done: `rm -rf ~/tmp/denyread-trial`.
- **B5. Negative probes (must still work).** `cat ~/.ssh/known_hosts`, `cat ~/.ssh/config`, read an
  `.env.example` in a project, and ordinary project source (none of these are secret material in the
  deny policy). A false refuse here is a rollback trigger.
- **B6. Scope check.** Confirm sandbox did not break unrelated work you care about (network, writes
  outside the project, nested tools). Note anything surprising beside denyRead.
- **B7. Record.** Write the date, Claude Code version, probe results, and whether B4's Bash refuse
  was actually the sandbox (OS) or only the hook (stderr `secret-read-gate:`) into the Carried #1
  trail (`docs/secret-deny.md` C3 or a dated note). A hook-only refuse means the OS wall is still
  unproven — same caution PR #446 takes for openai/codex#22179.

## C. Risks

- **C1. Broader than denyRead.** `sandbox.enabled = true` turns on Claude's whole sandbox, not only
  the read-deny list. Expect side effects on network, writes, and child processes that have nothing
  to do with secrets. `allowUnsandboxedCommands: false` also means Claude cannot offer an unsandboxed
  retry for those failures — run the command yourself outside the session, or roll back (D).
- **C2. Incomplete mirror of `deny`.** `.env.*` and `~/.ssh/**` stay hook-only so allows keep
  working; a sandboxed Bash that constructs `~/.ssh/other-secret` or `.env.local` may still read it
  at the OS layer. The hook remains required.
- **C3. Enforcement may be weaker than docs claim.** anthropics/claude-code#55288: Bash may ignore
  deny paths that exist only as `permissions.deny` `Read(...)` rules. Always put paths in
  `filesystem.denyRead`. After apply, re-probe — do not assume the template landing (#405) equals a
  working wall.
- **C4. Unsandboxed retry under `bypassPermissions`.** Leaving `allowUnsandboxedCommands` at its
  default while `defaultMode` is `bypassPermissions` keeps the `dangerouslyDisableSandbox` escape
  hatch: a prompt-injected agent can retry a denied Bash unsandboxed with no operator prompt and
  walk past `denyRead`. Closing that hatch (A5 / B2) is a trial precondition, not an optional harden.
- **C5. Codex parallel (#446).** Shipping an inactive profile / template list is not evidence the
  installed binary enforces it. openai/codex#22179 is the same class of trap for Codex; treat the
  Claude trial the same way: measure, then claim.
- **C6. Operator-only apply.** An agent rewriting `~/.claude/settings.json` violates order 11. A
  botched JSON edit or an accidental commit of live settings into this repo are both out of scope
  for this trial doc's automation — there is none.
- **C7. Fail-open elsewhere.** The PreToolUse hook still fails open on bad input / budget
  (`docs/secret-deny.md` C7). The sandbox trial does not fix that; it only adds an OS layer when it
  actually runs.

## D. Rollback

- **D1. Fast.** Set `"sandbox": { "enabled": false }` in `~/.claude/settings.json` (keep or drop
  `denyRead` / `allowUnsandboxedCommands` / `failIfUnavailable`; with enabled false the OS wall is
  off). Restart Claude Code.
- **D2. Clean.** Restore the B1 backup: `cp -a ~/.claude/settings.json.bak-denyread-YYYYMMDD
  ~/.claude/settings.json`, then restart.
- **D3. Template.** Do **not** set `sandbox.enabled` (nor force-on the escape-hatch closers as a
  surprise enable) in `agents/claude/settings.json.tmpl` as part of rollback or trial success; the
  template stays disabled so installs do not surprise other machines. Render-owned `denyRead` in the
  template (PR #405) can remain.

## E. Done when

The trial is done (Carried #1's denyRead bullet can narrow) when the live settings carry A5's
`allowUnsandboxedCommands: false` and `failIfUnavailable: true`, B4 shows a **sandbox** refuse on at
least one denied Bash read, B5 shows no false refuses on allows, and the operator either keeps
`sandbox.enabled` on with the A list (including A5) or rolls back and records why. Template/render
without live apply, or `enabled`+`denyRead` without A5, does not close the item.
