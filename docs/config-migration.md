# Config migration: schema_version=1 effective tree (2026-11-07; set 2026-11-08)

First bounded S1/S2 unit: effective config loader (`bin/ade_config.py`),
CLI (`bin/ade-config check|get|diff|set`), checked-in JSON Schema (`config/ade.schema.json`),
and thin `just config-check`. Comment-preserving atomic `set` landed 2026-11-08.
**2026-11-09:** `bin/ade_gates.load_frontier` adopts `ade_config.load_effective` (legacy
`gates.toml` / `GATES_TOML` when `ade.toml` is absent). `bin/route_agent.py` still reads
`routing.toml` directly; its adoption is a later unit. Do not ship tracked `config/ade.toml`
yet (`ade-install` refuses while it is present).

## A. Mapping table (one explicit projection)

| Legacy file | Legacy table | Effective path |
| --- | --- | --- |
| `config/routing.toml` | `[routing]` | `[routing]` |
| `config/routing.toml` | `[lead]` | `[lead]` |
| `config/routing.toml` | `[dispatch]` | `[dispatch]` |
| `config/routing.toml` | `[substrate]` | `[substrate]` |
| `config/routing.toml` | `[hermes]` | `[hermes]` |
| `config/routing.toml` | `[calibrate]` | `[calibrate]` |
| `config/routing.toml` | `[[service]]` | `[[service]]` |
| `config/gates.toml` | `[frontier]` | `[gates.frontier]` |
| `config/gates.toml` | `[floors.frontier]` | `[gates.floors.frontier]` |
| `config/model-tiers.toml` | `[meta]` / `[rank]` / `[vendor.*]` / `[model.*]` / `[former]` | `[model_tiers]` |

Routing's current public tables stay at the effective root (not nested under a single
`[routing]` umbrella that would drop `[lead]` / `[[service]]`). Gates nest under
`[gates]` so the frontier allowance does not collide with routing keys. Model tiers project
under `[model_tiers]` (2026-11-09); `bin/ade-model-tiers` is the writer.

`schema_version` is exactly `1`. Unsupported versions fail closed.

## B. Precedence and isolation

B1. **Missing** `config/ade.toml` → project legacy files via the table above.
B2. **Present valid** `config/ade.toml` → that file is the repo base (still schema 1).
B3. **Present invalid / unknown-version** new or local config → error; never silently
    fall back to a permissive legacy policy. Present directories, dangling links,
    nonregular files and unreadable inputs are errors too. Raw new/local trees
    are schema-validated before domain isolation: ignored domain values must still
    be structurally valid. Invalid selected legacy gates keep their separate closed
    fallback; malformed legacy floor leaves are ignored as in `ade_gates`.
B4. **Local override** `~/.config/djbclark-ade/local.toml` (untracked): maps merge
    recursively per leaf; **arrays replace whole** (service lists never concatenate);
    type conflicts and duplicate `[[service]].name` identities are rejected.
    Raw new/local service identities are checked before domain isolation, even
    when `ROUTING_POLICY` selects a different service array.
    Raw gate requests and floor maps merge before a single final clamp, so a
    floor-only overlay evaluates the unchanged requested value against the new floor.
B5. **`ROUTING_POLICY`**: isolated legacy-format override for the routing domain
    (`routing`, `lead`, `dispatch`, `substrate`, `hermes`, `calibrate`, `service`).
    When set, that domain comes only from the chosen file; new/local routing keys for
    that domain are ignored. A missing/malformed selected path errors. Validation and optional
    `pipeline_effort` default match the pure `route_agent.load_policy` contract;
    live routing initialization is never imported.
B6. **`GATES_TOML`**: isolated legacy-format override for `[gates]`. Missing/unreadable
    or bad `[frontier]` uses the **closed** code defaults (same as `ade_gates.load_frontier`),
    never a wider policy. Floor clamping matches `ade_gates` (higher-is-looser keys capped
    at `[floors.frontier].*.bound`; `*_min_left` never looser than the code default).
B7. This unit does **not** ship an automatically adopted `config/ade.toml`. An example
    may live under tests/fixtures only.
B8. **`MODEL_TIERS_TOML`** (2026-11-09): isolated override for `[model_tiers]`. Missing or
    unreadable files fall back to `model_tiers.DEFAULTS` (today's table), same fail-safe as
    `ade_gates`. `bin/ade-model-tiers` is the writer; `ade-config set` does not edit tiers.

## C. CLI

```
ade-config check [--root DIR] [--home DIR] [--json]
ade-config get PATH [--root DIR] [--home DIR] [--json]
ade-config diff [--root DIR] [--home DIR] [--json]
ade-config set PATH VALUE [--target local|repo] [--string] [--dry-run]
               [--root DIR] [--home DIR] [--json]
just config-check
```

`--root` and `--home` may appear before or after any subcommand, or one on
either side. If repeated, the last **explicit** value wins; an omitted option
never replaces an earlier explicit target. For example:
`ade-config --root DIR --home HOME check --json`.

`diff` compares against a baseline with local loading explicitly disabled;
no alternate supposedly absent filename is probed or loaded. The pure loader's
`include_local=False` option disables even local path resolution/presence checks.

### C2. `set` (2026-11-08)

`ade-config set` is the comment-preserving atomic scalar writer (`bin/ade_config_edit.py`).

| Flag | Behaviour |
| --- | --- |
| `--target local` (default) | Write `~/.config/djbclark-ade/local.toml` (create the file if absent). |
| `--target repo` | Write the **current source of that domain**: `config/ade.toml` when present; otherwise the legacy file (`config/routing.toml` for routing-domain keys, `config/gates.toml` for `gates.*` with the `gates.` prefix stripped inside the file). Never creates `config/ade.toml` (a tiny new file would suppress legacy projection). Never writes `ROUTING_POLICY` / `GATES_TOML` paths. |
| `--string` | Treat VALUE as a string even when it looks like a TOML literal. |
| `--dry-run` | Plan and verify the edit; do not replace the file. |

Mechanics: flock on `<file>.lock`, read-modify-validate, temp file beside the real
target, fsync, `os.replace`, mode preservation. A no-op (type-aware equality: bool
is never int, int is never float) leaves mtime untouched. After the text edit,
`tomllib` reparses and must equal the expected tree with exactly that scalar changed.
Symlinks,
arrays, inline tables, multiline strings, `[[service]]` paths and other unsupported
assignment forms are refused clearly. Unrelated complex TOML (including
`[[service]]` arrays) is preserved byte-for-byte outside the value span.

**Recording vs adoption.** Every successful `set` reports `adoption=recorded-only`:
the choice is stored in TOML, but `route_agent` / `ade_gates` still read their
legacy paths directly and have not adopted the effective-config reader. A local
set is therefore not yet a live routing switch for those consumers. check/get/diff
keep their no-write / no-auth / no-network contract.

Python **3.11+** is required for standard-library `tomllib`; bootstrap is a later unit.

check/get/diff validate raw new/local inputs and the effective tree against
`config/ade.schema.json`. The dependency-free evaluator supports that schema's
`type`, `const`, `required`, `properties`, `additionalProperties`, `items` and
`minLength` assertions; unsupported schema keywords fail closed. Gate and floor
names/specs are closed maps, with finite numeric gate values (booleans rejected).
Routing tables retain the declared open object shape; this is not consumer adoption
or new validation of every routing leaf. Selected legacy routing retains its own
reader's required keys, pool/lead/substrate validation and defaults. `set` applies
the same schema (local/unified) or the legacy routing/gates source constraints to
the file it edits.

check/get/diff stay pure: no config writes, no secret resolution, no
network/auth/scheduling probes. `--home` points local.toml resolution at a temp
tree in tests; tests must not write the real HOME config or flip live lead flags.

## D. Install catalog (transitional, 2026-11-09)

Separate from the routing/gates effective tree: `config/install.toml` + `ade-install`
(`docs/install-catalog.md`). Refused when `config/ade.toml` is present so install/keys
are not a second permanent authority beside a unified file.

## E. Provenance

`load_effective(...).provenance` names non-secret paths and domain sources
(`routing_source`, `gates_source`, `local_config`, `gates_info.source`) without
dumping credential-bearing files.
