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
separate from keys; consent is not key validation. Recorded login commands
(2026-11-09): `claude auth login`, `codex login`, `agent login` — doctor does
not execute them.

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
```

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
- `ade-user-install uv|just|cursor-cli|hermes|link <name>` fetches release
  binaries / vendor packages or symlinks a repo `bin/` tool into the prefix.
  No `shell=True`, no root. Cursor reads the version pin from
  `https://cursor.com/install` then downloads the lab tarball; Hermes
  urllib-fetches `install.sh` and runs `bash <temp>/install.sh --non-interactive`.

## E. Recorded recipes (2026-11-09)

| id | apply path |
| --- | --- |
| `just`, `uv` | `ade-user-install` release fetch → `{prefix}` |
| `skill-everywhere`, `firecrawl-router` | `ade-user-install link` into `{prefix}` |
| `node` | Mac `system_argv_darwin` `brew install node`; Linux system recipe still UNKNOWN; `node --version` probe |
| `graft` | `npm install -g @nanonets/graft` (user npm prefix) |
| `git`, `gh` | `needs_system` + Linux `system_argv` (`apt-get`) + `system_argv_darwin` (`brew`); dry-run only |
| `aiuse` | `uv tool install git+https://github.com/djbclark/aiuse` |
| `cswap` | `uv tool install claude-swap` (presence `cswap`) |
| `paseo` | `npm install -g @getpaseo/cli` (CLI only; desktop/daemon later) |
| `pi` | `npm install -g @mariozechner/pi-coding-agent` |
| `claude-code` | `npm install -g @anthropic-ai/claude-code` (presence `claude`) |
| `codex` | `npm install -g @openai/codex` |
| `cursor-cli` | `ade-user-install cursor-cli` (lab tarball → `~/.local/share/cursor-agent` + `{prefix}/agent`); update `agent update` |
| `hermes` (offered) | `ade-user-install hermes` (script fetch + `bash … --non-interactive`); update `hermes update` |
| `peer-link` (offered) | prose only — private `frdminc/peer-link` clone (`~/src/peer-link`); no `install_argv` until operator grants access |
| `litellm` (offered) | prose only — operator fork at `~/src/litellm` / site-djbclark `roles/litellm`; no stock auto-apply |
| `grok-bot-setup` (optional) | `npm install -g grok-bot-setup` (`adapters help` probe) |
| `1password` (optional) | Mac `system_argv_darwin` brew casks + `op --version` probe; Linux system recipe still UNKNOWN |
| others | still `UNKNOWN` / no `install_argv` |

## F. Next units

Live system apply (root/`apt`/`brew` execution with ownership ledger), remaining
owner installers (sudo-secretspec Linux tarball, Linux node/`npm` system_argv,
Paseo desktop/daemon and skill bundle), managed key verify probes. S4 jobs stay
explicit later work.
