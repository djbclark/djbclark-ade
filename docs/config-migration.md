# Config migration: schema_version=1 effective tree (2026-11-07)

First bounded S1/S2 unit: a **read-only** effective config loader (`bin/ade_config.py`),
CLI (`bin/ade-config check|get|diff`), checked-in JSON Schema (`config/ade.schema.json`),
and thin `just config-check`. Existing readers (`bin/route_agent.py`, `bin/ade_gates.py`)
are unchanged. Comment-preserving `set` and reader adoption are later units.

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

Routing's current public tables stay at the effective root (not nested under a single
`[routing]` umbrella that would drop `[lead]` / `[[service]]`). Gates nest under
`[gates]` so the frontier allowance does not collide with routing keys.

`schema_version` is exactly `1`. Unsupported versions fail closed.

## B. Precedence and isolation

B1. **Missing** `config/ade.toml` → project legacy files via the table above.
B2. **Present valid** `config/ade.toml` → that file is the repo base (still schema 1).
B3. **Present invalid / unknown-version** new or local config → error; never silently
    fall back to a permissive legacy policy.
B4. **Local override** `~/.config/djbclark-ade/local.toml` (untracked): maps merge
    recursively per leaf; **arrays replace whole** (service lists never concatenate);
    type conflicts and duplicate `[[service]].name` identities are rejected.
B5. **`ROUTING_POLICY`**: isolated legacy-format override for the routing domain
    (`routing`, `lead`, `dispatch`, `substrate`, `hermes`, `calibrate`, `service`).
    When set, that domain comes only from the chosen file; new/local routing keys for
    that domain are ignored. A missing/malformed selected path errors (same spirit as
    `route_agent.load_policy`).
B6. **`GATES_TOML`**: isolated legacy-format override for `[gates]`. Missing/unreadable
    or bad `[frontier]` uses the **closed** code defaults (same as `ade_gates.load_frontier`),
    never a wider policy. Floor clamping matches `ade_gates` (higher-is-looser keys capped
    at `[floors.frontier].*.bound`; `*_min_left` never looser than the code default).
B7. This unit does **not** ship an automatically adopted `config/ade.toml`. An example
    may live under tests/fixtures only.

## C. CLI

```
ade-config check [--root DIR] [--home DIR] [--json]
ade-config get PATH [--root DIR] [--home DIR] [--json]
ade-config diff [--root DIR] [--home DIR] [--json]
just config-check
```

All pure: no config writes, no secret resolution, no network/auth/scheduling probes.
`--home` points local.toml resolution at a temp tree in tests.

## D. Provenance

`load_effective(...).provenance` names non-secret paths and domain sources
(`routing_source`, `gates_source`, `local_config`, `gates_info.source`) without
dumping credential-bearing files.
