# Install catalog (transitional, 2026-11-09)

Typed component / key-reference catalog with print-only `plan`, observe-only
`doctor` (runs `probe_argv` when recorded), and **bounded user-scoped `apply`**.
Doctor does **not** repair or read secret values. Full ownership-aware
reconciliation and `--system` root effects remain later work
(`docs/setup-plan.md` S3).

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
  `--system --dry-run` previews the platform pick; live system exec is refused.
- `presence` is a PATH basename fallback when `probe_argv` is absent.

## C. Keys and logins

`[[key]]` entries are **names and metadata only** (create URL, verify=UNKNOWN,
expiry=unknown|…). Doctor never reads `sudo-secretspec` values. Login checks are
separate from keys; consent is not key validation.

## D. CLI

```
ade-install check [--root DIR] [--json]
ade-install catalog [--root DIR] [--json]
ade-install plan [--root DIR] [--json]
ade-install doctor [--root DIR] [--json]
ade-install apply [--root DIR] [--json] [--dry-run|--yes] [--id ID ...] [--force]
                  [--state-dir DIR] [--prefix DIR]
just install-check
just install-doctor
just install-plan
just install-apply-dry
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
  falls back to PATH `presence`. Missing or failed expected components fail
  the command; `unknown` is neither healthy nor absent. Doctor does not repair.
- `apply` defaults to **dry-run**. `--yes` executes user `install_argv` for
  expected missing components (or `--force`). Writes an atomic ledger under
  `~/.local/state/djbclark-ade/install/ledger.json` (or `ADE_INSTALL_STATE_DIR`).
  `--system --dry-run` previews `system_argv` as `would-system-install`.
  Executing `system_argv` is always refused (exit 2). Exit 0 ok, 1
  blocked/failed, 2 system-exec refused / usage.
- `ade-user-install uv|just|link <name>` fetches GitHub release binaries or
  symlinks a repo `bin/` tool into the prefix. No `shell=True`, no root.

## E. Recorded recipes (2026-11-09)

| id | apply path |
| --- | --- |
| `just`, `uv` | `ade-user-install` release fetch → `{prefix}` |
| `skill-everywhere`, `firecrawl-router` | `ade-user-install link` into `{prefix}` |
| `graft` | `npm install -g @nanonets/graft` (user npm prefix) |
| `git`, `gh` | `needs_system` + Linux `system_argv` (`apt-get`) + `system_argv_darwin` (`brew`); dry-run only |
| `node`, `npm` | `needs_system` + Linux `system_argv` (`apt-get install -y nodejs npm`) + `system_argv_darwin` (`brew install node`); dry-run only |
| `sudo-secretspec` | Mac: `system_argv_darwin` brew tap; Linux: release tarball recipe in `install` prose — no single `system_argv` (versioned asset + extract + declarations path) |
| `aiuse` | `uv tool install git+https://github.com/djbclark/aiuse` |
| others | still `UNKNOWN` / no `install_argv` |

## F. Next units

Live system apply (root/`apt`/`brew` execution with ownership ledger), an
`ade-user-install` (or similar) helper that resolves the sudo-secretspec Linux
tarball without a pinned URL, remaining owner installers (paseo desktop/daemon
and skill bundle, vendor clients), managed key verify probes. S4 jobs stay
explicit later work.
