# Config migration: schema_version=1 effective tree (2026-11-07; set 2026-11-08)

First bounded S1/S2 unit: effective config loader (`bin/ade_config.py`),
CLI (`bin/ade-config check|get|diff|set|fold`), checked-in JSON Schema (`config/ade.schema.json`),
and thin `just config-check`. Comment-preserving atomic `set` landed 2026-11-08.
**2026-11-09:** `bin/ade_gates.load_frontier` adopts `ade_config.load_effective` (legacy
`gates.toml` / `GATES_TOML` when `ade.toml` is absent). **Same day:** `bin/route_agent.py`
module init and `reload_policy()` (no explicit path) adopt `load_routing_effective` →
`ade_config.load_effective` (legacy `routing.toml` / `ROUTING_POLICY` when `ade.toml` is
absent); `load_policy(path)` remains for tests that feed a temp file. **Same day (stacked):**
`claude/hooks/context_size_nudge.py` reads `[lead].fable_lead` through
`ade_config.load_effective` (same `ROUTING_POLICY` isolation; fail-closed when the effective
load errors). **Same day (stacked):** `bin/context-budget-check` reads the
`context_budget` domain through `ade_config.load_effective` (legacy
`context-budget.toml` / `CONTEXT_BUDGET_TOML` when `ade.toml` is absent; `--config` still
reads an explicit legacy-format file). **Same day (stacked):** `bin/render-secret-deny`
and `bin/review-launch` read the `secret_deny` domain, and `bin/pr-policy` reads the
`pr_policy` domain, through `ade_config.load_effective` (legacy `secret-deny.toml` /
`SECRET_DENY_TOML` and `pr-policy.toml` / `PR_POLICY_TOML` when `ade.toml` is absent;
`--policy` / `--config` / `PR_POLICY_CONFIG` still accept an explicit legacy-format file).
**Same day (stacked, scout gap A1):** tracked `config/ade.toml` is committed via
`ade-config fold --write` (projects every policy domain above). When present it is the
repo base; legacy split TOMLs remain for fallthrough when it is absent.
**2026-11-10 (stacked, scout B1):** `ade-config fold` also projects
`config/install.toml` under `[install]` (component/key/login). `ade-install`
loads the folded catalog through `ade_config.load_effective` (so
`~/.config/djbclark-ade/local.toml` `[install]` overlays apply) and falls
through to transitional `install.toml` when `ade.toml` is absent or lacks
`[install]`; a present but empty or invalid `[install]` fails validation
instead of falling through.

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
| `config/context-budget.toml` | `dirs` | `[context_budget].dirs` |
| `config/context-budget.toml` | `[budget]` | `[context_budget].budget` |
| `config/secret-deny.toml` | `version` / `deny` / `allow` / `[claude]` | `[secret_deny].*` |
| `config/pr-policy.toml` | `[meta]` / `[github]` / `[forgejo]` | `[pr_policy].*` |
| `config/install.toml` | `schema_version` | `[install].schema_version` |
| `config/install.toml` | `[[component]]` | `[[install.component]]` |
| `config/install.toml` | `[[key]]` | `[[install.key]]` |
| `config/install.toml` | `[[login]]` | `[[install.login]]` |

Routing's current public tables stay at the effective root (not nested under a single
`[routing]` umbrella that would drop `[lead]` / `[[service]]`). Gates nest under
`[gates]` so the frontier allowance does not collide with routing keys. Context-budget,
secret-deny, pr-policy and install nest under `[context_budget]`, `[secret_deny]`,
`[pr_policy]` and `[install]` the same way.

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
B7. **`CONTEXT_BUDGET_TOML`**: isolated legacy-format override for `[context_budget]`.
    When set, that domain comes only from the chosen file; new/local `context_budget` keys
    are ignored. A missing/malformed selected path errors. The default legacy path
    (`config/context-budget.toml`) missing projects the same dirs/budget defaults
    `context-budget-check` used before adoption.
B8. **`SECRET_DENY_TOML`**: isolated legacy-format override for `[secret_deny]`.
    When set, that domain comes only from the chosen file; new/local `secret_deny` keys
    are ignored. A missing/malformed selected path errors. The default legacy path
    missing projects an empty deny/allow/static list (review-launch then uses its own
    `DENY_PATHS` alone); a present file still requires a non-empty `deny`.
B9. **`PR_POLICY_TOML`**: isolated legacy-format override for `[pr_policy]`.
    When set, that domain comes only from the chosen file; new/local `pr_policy` keys
    are ignored. A missing/malformed selected path errors. The default legacy path
    missing projects `{meta.schema=1}` with no forge tables. Consumer
    `--config` / `PR_POLICY_CONFIG` remain an explicit legacy-format path (not this
    isolation env).
B10. **Tracked `config/ade.toml`** (2026-11-09; install 2026-11-10): committed by
    `ade-config fold --write` from the legacy domain files (including
    `config/install.toml` → `[install]`). `ade-config fold --check` asserts the file
    still matches that fold while both the unified file and the legacy mirrors are kept.
    Prefer `ade-config set --target repo` for scalar edits (writes `ade.toml` when
    present). The fold emitter writes nested section tables for
    gates/pr_policy/context_budget/secret_deny (e.g. `[gates.frontier]`,
    `[pr_policy.github]`), matching the prior split TOML shape, so scalar set can edit
    those leaves; routing-domain tables may still use compact inline nests, and flat
    floor / `budget."~"` records stay inline. Install emits `[[install.component]]` /
    `[[install.key]]` / `[[install.login]]`. Legacy files stay for fallthrough when
    `ade.toml` is absent; a later PR may drop them once fallthrough is unused.

## C. CLI

```
ade-config check [--root DIR] [--home DIR] [--json]
ade-config get PATH [--root DIR] [--home DIR] [--json]
ade-config diff [--root DIR] [--home DIR] [--json]
ade-config set PATH VALUE [--target local|repo] [--string] [--dry-run]
               [--root DIR] [--home DIR] [--json]
ade-config fold [--root DIR] [--write|--check] [--json]
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
| `--target repo` | Write the **current source of that domain**: `config/ade.toml` when present; otherwise the legacy file (`config/routing.toml` for routing-domain keys, `config/gates.toml` for `gates.*` with the `gates.` prefix stripped inside the file, `config/context-budget.toml` for `context_budget.*`, `config/secret-deny.toml` for `secret_deny.*`, `config/pr-policy.toml` for `pr_policy.*`, each with the domain prefix stripped). Never creates `config/ade.toml` (a tiny new file would suppress legacy projection). Never writes `ROUTING_POLICY` / `GATES_TOML` / `CONTEXT_BUDGET_TOML` / `SECRET_DENY_TOML` / `PR_POLICY_TOML` paths. |
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

**Recording vs adoption.** Every successful `set` reports `adoption=recorded-only`
in the CLI payload (the writer does not re-init live modules). As of 2026-11-09,
`ade_gates.load_frontier`, `route_agent.reload_policy()` (no path) / module init,
`context-budget-check` (default config path), `render-secret-deny` / `review-launch`
(default secret-deny path), and `pr-policy` (default config path) do read through
`ade_config.load_effective`, so a local override is live on the next frontier load,
`reload_policy()` call, budget-check, secret-deny render/launch, or pr-policy run
(not mid-process without a reload).
check/get/diff keep their no-write / no-auth / no-network contract.

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

## D. Install catalog (folded 2026-11-10)

`ade-config fold` projects `config/install.toml` under `[install]`. `ade-install`
(`docs/install-catalog.md`) prefers that folded catalog when present and falls through
to transitional `config/install.toml` when `ade.toml` is absent or lacks `[install]`.
`fold --check` keeps the mirror aligned while both files are kept; there is no second
permanent editable authority once the unified file carries install/keys.

## E. Provenance

`load_effective(...).provenance` names non-secret paths and domain sources
(`routing_source`, `gates_source`, `context_budget_source`, `secret_deny_source`,
`pr_policy_source`, `local_config`, `gates_info.source`) without dumping
credential-bearing files.
