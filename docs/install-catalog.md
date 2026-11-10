# Install catalog (transitional, 2026-11-09)

Typed component / key-reference catalog with print-only `plan`, observe-only
`doctor` (runs `probe_argv` when recorded), observe-only `keys` (bulk
`sudo-secretspec check` plus per-key `verify_argv` under `sudo-secretspec
run` when recorded), and **bounded `apply`** (user `install_argv` by
default; `system_argv` only with explicit `--apply-system`). Doctor and keys
do **not** repair or read secret values. Full ownership-aware reconciliation
remains later work (`docs/setup-plan.md` S3).

## A. Source

| File | Role |
| --- | --- |
| `config/install.toml` | Transitional editable catalog (`schema_version = 1`) |
| `config/install.schema.json` | Structural schema (checked by `ade-install check`) |
| `bin/ade_install.py` / `bin/ade-install` | Loader, plan, doctor, apply |
| `bin/ade_user_install.py` / `bin/ade-user-install` | User-scoped uv/just fetch and `bin/` symlinks |

Loaded **only while `config/ade.toml` is absent**. If a unified `ade.toml` is
present, `ade-install` refuses the transitional file so there is no permanent
duplicate editable authority. A later fold must carry install/keys into the
unified file with reviewed consumer adoption.

## B. Component classes

`hard` · `offered` · `optional` · `suggested` · `never` (from setup-plan S3.2).

- `offered` / `optional` / `suggested` require an explicit `chosen` boolean.
- `hard` is always expected; `chosen=false` is rejected.
- `install` / `update` / `probe` may be prose or the sentinel `UNKNOWN`.
- `install_argv` / `update_argv` / `probe_argv` are argv lists.
  Tokens: `{bin}`, `{root}`, `{home}`, `{prefix}` (default `~/.local/bin` or
  `ADE_INSTALL_PREFIX`).
- `needs_system = true` marks package-manager / root paths; pair with
  `system_argv` (Linux) and optional `system_argv_darwin` (Homebrew).
  `--system --dry-run` / `--print-system-argv` preview the platform pick;
  live system exec needs `--yes --system --apply-system` (default refuse).
- `presence` is a PATH basename fallback when `probe_argv` is absent.

## C. Keys and logins

`[[key]]` entries are **names and metadata only** (create URL, `verify`,
optional `verify_argv`, expiry=unknown|…). Doctor never reads
`sudo-secretspec` values. Login checks are separate from keys; consent is not
key validation. Recorded login commands (2026-11-09): `claude auth login`,
`codex login`, `agent login` — doctor does not execute them.

`ade-install keys` / `just keys` (2026-11-09 presence; 2026-11-10 verify) is
setup-plan S3b check-then-verify:

1. Lists catalog key/login references.
2. Runs `sudo-secretspec check --reason "ade-install keys"` when the binary is
   on PATH.
3. For each key with a recorded `verify_argv`, runs
   `sudo-secretspec run --reason "ade-install keys verify <NAME>" --
   <verify_argv…>` (argv lists; the probe reads the key from the injected
   environment). Exit contract: `0` ok, `10` invalid, `11` no-quota,
   `12` unreachable, `13` expiring, `14` missing. Optional stderr marker
   `ADE_KEY_VERIFY:expiring:YYYY-MM-DD` may refine an ok or expiring
   outcome (ISO calendar date only; failure exits stay failure).
4. Writes outcomes atomically to `~/.local/state/djbclark-ade/keys.json` (or
   `ADE_KEYS_STATE_PATH` / `--keys-state`); **no values and no hashes**.

It never calls get/export/set, never prints secret values, and never echoes
probe stdout/stderr bodies into observations. Catalog rows may still say
`verify = "UNKNOWN"` until a probe argv is recorded. Exit 1 when `check`
fails or any verify status is invalid/no-quota/unreachable/missing/error; a
missing `sudo-secretspec` is `unknown` (exit 0). Collect/set remains a later
unit.

## D. CLI

```
ade-install check [--root DIR] [--json]
ade-install catalog [--root DIR] [--json]
ade-install plan [--root DIR] [--json]
ade-install doctor [--root DIR] [--json]
ade-install keys [--root DIR] [--json] [--keys-state PATH]
ade-install apply [--root DIR] [--json] [--dry-run|--yes] [--id ID ...] [--force]
                  [--system] [--print-system-argv] [--apply-system]
                  [--state-dir DIR] [--prefix DIR]
just install-check
just install-doctor
just keys
just install-plan
just install-apply-dry
just install-print-system-argv
just doctor                 # alias of install-doctor (setup-plan S2 name)
just install [-- --yes]    # ade-install apply (dry-run by default; --yes for live)
just update [-- --check]   # bin/ade-update for this checkout
```

Daily behind-check (not auto-apply): install
`config/launchd/com.djbclark.ade-update-check.plist` with an explicit log dir
(operator step; queue Carried #15). The same plist is the source of truth for
**macOS launchd** and **Linux systemd** (ade-sched's backends):

```
# Linux (systemd user timer; linger required, else exit 69)
bin/ade-sched --backend systemd install config/launchd/com.djbclark.ade-update-check.plist \
  --set __STATE__=$HOME/.local/state/ade --ade ~/src/djbclark-ade
# or from the canonical checkout: just update-check-install
# (omits --ade so a linked worktree cannot install a job that vanishes after merge)

# macOS (launchd; auto backend also picks this when launchctl is present)
bin/ade-sched --backend launchd install config/launchd/com.djbclark.ade-update-check.plist \
  --set __STATE__=$HOME/.local/state/ade --ade ~/src/djbclark-ade
```

`__ADE__` / `__HOME__` are filled automatically; `__STATE__` is not and exits 2 if left blank.
Pass `--ade` only with a durable checkout (`~/src/djbclark-ade`); never with a linked worktree path.

- `plan` is print-only: `would-install` (has `install_argv`) / `needs-system` /
  `blocked` / `skip`.
- `doctor` prefers `probe_argv` (runs the tool; argv list, short timeout) and
  falls back to PATH `presence`. When `agents/claude/settings.json.tmpl` is
  present under `--root`, it also checks that live `~/.claude/settings.json`
  registers `context_size_nudge.py` under every hook event the template does
  (queue Carried #10, 2026-11-09); a miss prints a hand-apply hint and fails.
  Doctor never mutates live settings (order 11). Missing or failed expected
  components fail the command; `unknown` is neither healthy nor absent.
  Doctor does not repair.
- `keys` is observe-only: bulk presence via `sudo-secretspec check`, then
  per-key `verify_argv` under `sudo-secretspec run` when recorded; no secret
  values.
- `apply` defaults to **dry-run**. `--yes` executes user `install_argv` for
  expected missing components (or `--force`). Writes an atomic ledger under
  `~/.local/state/djbclark-ade/install/ledger.json` (or `ADE_INSTALL_STATE_DIR`).
  `--system --dry-run` previews `system_argv` as `would-system-install`;
  `--print-system-argv` dumps the same argv print-only. Live `system_argv`
  requires `--yes --system --apply-system` (argv list via subprocess, never
  `shell=True`); `--yes --system` alone still exits 2 (`refuse-system-exec`).
  Exit 0 ok, 1 blocked/failed, 2 system-exec refused / usage.
- `ade-user-install uv|just|link <name>` fetches GitHub release binaries or
  symlinks a repo `bin/` tool into the prefix. No `shell=True`, no root.

## E. Recorded recipes (2026-11-09)

| id | apply path |
| --- | --- |
| `just`, `uv` | `ade-user-install` release fetch → `{prefix}` |
| `skill-everywhere`, `firecrawl-router` | `ade-user-install link` into `{prefix}` |
| `graft` | `npm install -g @nanonets/graft` (user npm prefix) |
| `git`, `gh` | `needs_system` + Linux `system_argv` (`apt-get`) + `system_argv_darwin` (`brew`); preview or `--apply-system` |
| `aiuse` | `uv tool install git+https://github.com/djbclark/aiuse` |
| `cswap` | `uv tool install claude-swap` (presence `cswap`) |
| `paseo` | `npm install -g @getpaseo/cli` (CLI only; desktop/daemon later) |
| `pi` | `npm install -g @mariozechner/pi-coding-agent` |
| `claude-code` | `npm install -g @anthropic-ai/claude-code` (presence `claude`) |
| `codex` | `npm install -g @openai/codex` |
| `cursor-cli` | probe/update only (`agent --version` / `agent update`); install is official curl\|bash (no `install_argv` yet) |
| `hermes` (offered) | probe/update only (`hermes doctor` / `hermes update`); install is official curl\|bash (no `install_argv` yet) |
| others | still `UNKNOWN` / no `install_argv` |

## F. Operator path for live system apply (2026-11-09)

Default refuse stays: `ade-install apply --yes --system` → exit 2
`refuse-system-exec`. Opt-in live path (operator machine only; never CI root):

```
# Preview (safe anywhere)
ade-install apply --system --dry-run --id git
ade-install apply --print-system-argv --id git --json

# Live (explicit; writes ledger kind=system_argv)
ade-install apply --yes --system --apply-system --id git
```

`subprocess` uses argv lists only. Prefer `--id` so one package set is
applied at a time. CI must keep using dry-run / print / mocked runners — do
not pass `--apply-system` in automated jobs.

## G. Next units

Ownership-aware reconcile beyond the install ledger (setup-plan S3), remaining
owner installers (sudo-secretspec Linux tarball, curl-free Cursor CLI fetch, Hermes
offered path, Paseo desktop/daemon and skill bundle), recorded provider
`verify_argv` recipes in the catalog, collect/set batch. S4 jobs stay explicit
later work.
Follow-up: tighten `--apply-system` with an ownership generation / read-back
lock if multi-agent installs share a machine.
