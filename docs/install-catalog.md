# Install catalog (transitional, 2026-11-09)

Typed component / key-reference catalog with print-only `plan`, observe-only
`doctor`, and **bounded user-scoped `apply`**. Doctor does **not** repair or
read secret values. Full ownership-aware reconciliation and `--system` root
effects remain later work (`docs/setup-plan.md` S3).

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
- `install_argv` / `update_argv` are the only executable recipes (argv lists).
  Tokens: `{bin}`, `{root}`, `{home}`, `{prefix}` (default `~/.local/bin` or
  `ADE_INSTALL_PREFIX`).
- `needs_system = true` marks package-manager / root paths; bounded apply
  refuses them until a later `--system` unit.
- `presence` is an optional PATH basename for observe-only doctor.

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
```

- `plan` is print-only: `would-install` (has `install_argv`) / `needs-system` /
  `blocked` / `skip`.
- `doctor` observes PATH presence for recorded basenames. Missing expected
  components fail the command; `unknown` is neither healthy nor absent.
  Doctor does not repair.
- `apply` defaults to **dry-run**. `--yes` executes `install_argv` for expected
  components that are missing (or all selected with `--force`). Writes an
  atomic ledger under `~/.local/state/djbclark-ade/install/ledger.json` (or
  `ADE_INSTALL_STATE_DIR`). Exit 0 ok, 1 blocked/failed, 2 refused (`--system`
  or usage). `--system` is always refused in this unit.
- `ade-user-install uv|just|link <name>` fetches GitHub release binaries or
  symlinks a repo `bin/` tool into the prefix. No `shell=True`, no root.

## E. Recorded recipes (2026-11-09)

| id | apply path |
| --- | --- |
| `just`, `uv` | `ade-user-install` release fetch → `{prefix}` |
| `skill-everywhere`, `firecrawl-router` | `ade-user-install link` into `{prefix}` |
| `graft` | `npm install -g @nanonets/graft` (user npm prefix) |
| `git`, `gh` | `needs_system`; blocked until `--system` unit |
| others | still `UNKNOWN` / no `install_argv` |

## F. Next units

More owner installers (paseo, sudo-secretspec, aiuse, vendor clients), managed
key verify probes, ownership-aware reconcile with `--system` for root effects.
S4 jobs stay explicit later work.
