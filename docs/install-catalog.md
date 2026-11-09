# Install catalog (transitional, 2026-11-09)

First usable unit after `ade-config set`: a **typed component / key-reference catalog**
with print-only `plan` and observe-only `doctor`. It does **not** install, update,
repair, or read secret values. Full apply/reconciliation remains later work
(`docs/setup-plan.md` S3).

## A. Source

| File | Role |
| --- | --- |
| `config/install.toml` | Transitional editable catalog (`schema_version = 1`) |
| `config/install.schema.json` | Structural schema (checked by `ade-install check`) |
| `bin/ade_install.py` / `bin/ade-install` | Loader, plan, doctor |

Loaded **only while `config/ade.toml` is absent**. If a unified `ade.toml` is
present, `ade-install` refuses the transitional file so there is no permanent
duplicate editable authority. A later fold must carry install/keys into the
unified file with reviewed consumer adoption.

## B. Component classes

`hard` · `offered` · `optional` · `suggested` · `never` (from setup-plan S3.2).

- `offered` / `optional` / `suggested` require an explicit `chosen` boolean.
- `hard` is always expected; `chosen=false` is rejected.
- `install` / `update` / `probe` may be the sentinel `UNKNOWN` until a real
  owner-installer recipe is recorded.
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
just install-check
just install-doctor
```

- `plan` is print-only: `would-install` / `blocked` (UNKNOWN recipe) / `skip`.
- `doctor` observes PATH presence for recorded basenames. Missing expected
  components fail the command; `unknown` is neither healthy nor absent.
  Doctor does not repair.

## E. Next units

Record real install/update recipes (replace UNKNOWN), managed key verify probes,
then ownership-aware apply/reconciliation with `--system` for root effects.
S4 jobs stay explicit later work.
