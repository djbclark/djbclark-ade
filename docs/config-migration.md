# Config migration: schema_version=1 effective tree (2026-11-07; set 2026-11-08)

First bounded S1/S2 unit: effective config loader (`bin/ade_config.py`),
CLI (`bin/ade-config check|get|diff|set`), checked-in JSON Schema (`config/ade.schema.json`),
and thin `just config-check`. Comment-preserving atomic `set` landed 2026-11-08.
**2026-11-09:** `bin/ade_gates.load_frontier` adopts `ade_config.load_effective` (legacy
`gates.toml` / `GATES_TOML` when `ade.toml` is absent). **2026-11-10:** runtime
initialization and default reload in `bin/route_agent.py` also adopt `load_effective`.
The final overlaid routing domain passes the legacy reader's shape/default checks
before becoming routing constants. No new routes or policy values ship with this
adoption. Install/keys metadata also has a bounded reader adoption below. Do not
ship tracked `config/ade.toml` yet: other transitional readers still require
separate adoption.

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
| `config/install.toml` | `[[component]]` | `[[install.component]]` |
| `config/install.toml` | `[[login]]` | `[[install.login]]` |
| `config/install.toml` | `[[install.jobs]]` / `[[install.retired_jobs]]` | unchanged |
| `config/install.toml` | `[[key]]` identified by `name` | `[keys.<NAME>]` (name becomes the table identity) |
| `config/context-budget.toml` | `dirs` / `[budget]` | `[context_budget]` |

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
B9. **Runtime routing adoption (2026-11-10).** `route_agent.load_effective_policy`
    selects only the routing domain from the effective tree and validates it after
    all overlays, including required tables/service fields, service key names,
    pool shape, substrate lifeline and lead keys/efforts. Default module initialization
    and `reload_policy()` use it. `load_policy(path)` and `reload_policy(path)` retain
    their isolated legacy-format behavior and do not read unified/local config.
    `policy` JSON adds `provenance` with the routing base and optional unified/local
    paths; Markdown names a loaded local override too. Frontier gate clamping, quota/acceptance checks and
    estimate floors/caps are unchanged.
B10. **Runtime model-tier adoption (2026-11-10).** The router validates one final
    overlaid `[model_tiers]` tree with `model_tiers.from_dict` and passes that
    snapshot to its existing tier helpers. Policy reporting, frontier tokens,
    sublimit families and the low-frontier-cap judgment fallback use the same
    snapshot; default `reload_policy()` refreshes them together. Invalid effective
    tiers stop initialization/reload before routing state is published. Validation
    reuses the tier contract, with additional checks for the consumed `spell` map
    and `pool_family` string types. Derived tokens/families and source metadata are
    recomputed, never trusted from editable report fields. `MODEL_TIERS_TOML`
    retains domain isolation and the legacy missing/bad-file default fallback;
    `ROUTING_POLICY` isolates routing only, so it does not suppress tier overlays.
    `model_tiers.load(path)` and explicit `reload_policy(path)` retain legacy file
    behavior; writers and `@role` migration are outside this unit. No tracked
    model choices or policy limits changed.
B11. **Joint catalog reader adoption (2026-11-10).** `load_effective(domains=None)`
    exposes every supported domain, including install/keys when present. The
    router and frontier reader explicitly select their existing routing/gates/tiers
    domains and do not start requiring `install.toml`. `ade_install.load_catalog()`
    selects only install/keys, so catalog-only roots do not need routing files.
    Legacy catalog absence is optional for unrelated readers; the catalog consumer
    requires an effective install domain and non-empty component array. A present
    unified file never falls back to legacy catalog data. Missing optional `[keys]`
    means an empty registry, matching legacy optional-key behavior.
    Named keys merge by metadata leaf; component/login/job arrays replace whole.
    Duplicate legacy identities are rejected before projection into named tables.
    Final metadata uses the existing catalog schema and pure semantic validator;
    component choices, plugin observation, key operations and system boundaries
    are unchanged. Explicit `load_catalog(install_path=...)` retains the isolated
    legacy reader, including its refusal when a unified file is present.
    For catalog-only roots without `ade.schema.json`, raw unified/local inputs
    use the bundled full effective schema before domain isolation; if unavailable,
    overlays refuse explicitly. With no overlays, the existing catalog schema is
    sufficient. These readers perform no probes, installs or state writes.

B12. **Context-budget reader adoption (2026-11-10).** Default
    `context-budget-check` reads only effective `[context_budget]`; it does not
    require routing, gates, tiers or install files. Legacy `dirs` and `[budget]`
    project without changing tracked values. Local directory arrays replace whole,
    while default budgets and per-directory override maps merge by leaf. Absent
    legacy input, an omitted unified domain, empty `dirs` or empty `budget` retain
    the CLI's existing code defaults; a unified file never revives legacy context
    data. Explicit `--config PATH` and `load_config(path)` remain isolated legacy
    reads, including their missing-file defaults and parse/type behavior.
    Effective raw inputs and final merged budgets validate directory arrays and
    numeric leaves before measurement/state/ping; booleans, nonfinite values and
    nested override maps refuse (CLI exit 2). The six consumed default budget
    entries must be numeric, not maps. Existing numeric row names, directory map
    names and numeric values are otherwise retained. A configured/selected
    directory label must not also name a scalar budget row: ambiguous lookups
    refuse before effects, including `--dir` and normalized default directories.
    Explicit legacy reads keep their old type behavior. This unit adds no budget
    limits or schedule changes. `ade-config check/get/diff` includes the domain;
    The bounded scalar writer adoption below adds numeric budget edits.

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
Install arrays and unsupported key/context fields explicitly refuse `set`.
Numeric budget leaves and four existing-key string metadata fields are supported below.

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

**Recording vs adoption (2026-11-10).** Every successful `set` still reports
`adoption=recorded-only`: this is the writer's conservative status, not proof that
a running consumer reloaded. `route_agent` adopts routing and model tiers on its next
initialization or default `reload_policy()`; `ade_gates.load_frontier` already
reads the effective gates domain. Existing processes do not hot-reload routing
constants on a `set`. Other consumers and the legacy model-tier CLI retain
their own paths until separately adopted. check/get/diff keep their no-write /
no-auth / no-network contract.

Python **3.11+** is required for standard-library `tomllib`; bootstrap is a later unit.

check/get/diff validate raw new/local inputs and the effective tree against
`config/ade.schema.json`. The dependency-free evaluator supports that schema's
`type`, `const`, `required`, `properties`, `additionalProperties`, `items` and
`minLength` assertions; unsupported schema keywords fail closed. Gate and floor
names/specs are closed maps, with finite numeric gate values (booleans rejected).
Routing tables retain the declared open object shape; config check/get/diff do not
replace consumer validation of every routing leaf. The runtime router applies
the pure legacy shape/default contract to the final overlaid routing domain.
Selected legacy routing retains its own
reader's required keys, pool/lead/substrate validation and defaults. `set` applies
the same schema (local/unified) or the legacy routing/gates source constraints to
the file it edits.

check/get/diff stay pure: no config writes, no secret resolution, no
network/auth/scheduling probes. `--home` points local.toml resolution at a temp
tree in tests; tests must not write the real HOME config or flip live lead flags.

### C3. Bounded metadata writes (2026-11-10)

Supported scalar paths are `context_budget.budget.ROW` and
`context_budget.budget.DIRECTORY.ROW` (finite numbers), and
`keys.NAME.create_url|verify|expiry|notes` (strings, existing registry identities
only). TOML quoted path parts address literal directory/key names, for example:

```sh
ade-config set 'context_budget.budget."~".memory' 14000
ade-config set keys.EXAMPLE_API_KEY.expiry unknown --string --target repo
```

Local writes use `local.toml`; a missing local file may be created. Repo writes
use the existing unified file when present, otherwise `context-budget.toml`
with the prefix stripped or the unique existing `[[key]]` row selected by name
in `install.toml`. A named legacy key edit changes exactly one scalar field;
array creation, ordering, indices, component/job choices and other array edits
remain unsupported. Key identities, new registry rows, credential/value fields,
`components`, `verify_argv` and `context_budget.dirs` are refused. `verify` is a
human annotation; writing it does not record an authenticated verification result.

Before replacement **and before a no-op success**, the writer validates the raw
target and the final merged effective metadata through the normal loader using
one in-memory candidate snapshot. Ignored raw unified/local declarations still
validate; malformed unrelated declarations cannot be hidden by selecting another
domain. Context defaults and directory-label collisions use the same pure
normalizer as the runtime checker. Key edits require an existing valid effective
registry and a final complete catalog satisfying its schema and semantics.
No probes, key retrieval, installs, schedules or acceptance writes occur.

Quoted header/key decoding uses stdlib TOML parsing of a single key chain;
unsupported assignment forms still refuse. Every edit must reparse to exactly
the expected type-aware whole tree, preserving unrelated text. Atomic replacement,
mode preservation, locks, dry runs and unchanged-file mtime on a no-op retain
the existing scalar writer contract. A set remains `recorded-only`; running
consumers adopt it only on their own next load. General quoted `get` path syntax
is separate: `set` reports its result directly, without a `get` round trip.

## D. Install catalog (transitional, 2026-11-09)

`config/install.toml` remains the legacy input when the unified file is absent.
The effective loader projects its complete metadata and `ade-install` adapts that
view back to the existing Catalog interface (`docs/install-catalog.md`). Pure
shared validation lives in `bin/ade_install_catalog.py`, which imports neither
the effective loader nor runtime installer. Explicit legacy path reads retain
their original unified-presence refusal. No tracked unified file or writer
expansion ships with this reader adoption.

## E. Provenance

`load_effective(...).provenance` names non-secret paths and domain sources
(`routing_source`, `gates_source`, `local_config`, `gates_info.source`) without
dumping credential-bearing files.
