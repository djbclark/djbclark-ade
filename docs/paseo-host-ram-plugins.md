# Paseo host RAM on macOS (2026-11-10)

## Choice

| Host | Plugin | Registry id | Notes |
|------|--------|---------------|--------|
| macOS (this machine) | **Resources** | `zedobaia/resources` | Uses `memory_pressure` and Activity Monitor–style footprints. |
| Linux daemons | **Vitals** optional | `tomgrin10/vitals` | Per-agent `/proc` trees; Linux `MemAvailable` is already correct. |

**Do not rely on vitals host RAM % on macOS before [tomgrin10/paseo-vitals#11](https://github.com/tomgrin10/paseo-vitals/pull/11) ships in the registry.** Vitals used Node `os.freemem()` (~99% false critical).

Pre-launch admission stays **`bin/load-watch admit`** (`vm_stat` reclaimable memory), not either plugin.

## Install / doctor

```bash
paseo plugin add zedobaia/resources   # mac operator default (2026-11-10)
paseo plugin remove vitals            # if still configured
```

`config/install.toml`: `paseo-plugin-resources` chosen; `paseo-plugin-vitals` not chosen (mac).

## App update vs plugin update

Updating **Paseo desktop/daemon** (e.g. 0.16 beta in-app) does **not** reinstall plugins, apply `paseo plugin add` catalog choices, or pull a new vitals npm revision. Plugins change only via:

- `paseo plugin add` / `remove` / `enable` / `disable`
- `paseo plugin update [id]` after the registry pins a new revision

After vitals #11 merges and the registry publishes a new `tomgrin10/vitals` revision, run `paseo plugin update vitals` on hosts that still use vitals (typically Linux). Mac operators can stay on Resources only.

## Upstream

- Issue: https://github.com/tomgrin10/paseo-vitals/issues/10
- PR: https://github.com/tomgrin10/paseo-vitals/pull/11 (maintainer merge; npm/registry bump follows)
