# OpenCode plugins: the v2 module contract, and the two shimmed plugins

Dated facts: verified 2026-10-11 against opencode **v2.0.26** (the binary at
`~/.local/lib/node_modules/@opencode/cli/node_modules/@opencode/cli-darwin-arm64/bin/opencode`).

## The contract

An OpenCode 2 plugin module must **default-export an object** with an `id`
plus an `effect` or `setup` function:

```js
export default { id: "my-plugin", setup: (ctx) => { /* … */ } }
// or { id, effect } for the Effect-style API
```

Anything else is rejected at load. A bare exported function, or an object with
`server` but no `setup`/`effect`, logs:

```
WARN  failed to load plugin  target=…  cause="Cause([Fail(PluginModule.LoadError:
Plugin must export a default definition with an id and an effect or setup
function. (cause: SchemaError(Expected object at ["default"])))])"
```

The validator lives inside the compiled binary (`PluginModule.make`); the string
is greppable with `strings` on the `opencode` executable. The npm package
`@opencode-ai/plugin` (1.18.11 here) is **stale**: its `v2/promise` types
(`id` + `setup`) are right, but its `PluginContext` does not declare the fields
user plugins actually get at runtime (`session`, `event`, `location`, and the
tool hooks), so read a working plugin rather than the d.ts.

Working local references (`~/.config/opencode/plugins/`):
`orca-opencode-status.js` (object export with `id` + `server` + `setup`;
`setup` uses `ctx.session.hook("prompt", …)` and
`ctx.event.subscribe({ signal })` and returns an async disposer) and
`moshi-hooks.ts`. The `server` field is the old v1 hook factory; OpenCode 2 does
not call it, so keep it only for OpenCode 1 — no v2 functionality may live in it.

The v2 tool hook (used by the built-in plugin `opencode.tool.input.repair`) is
`ctx.tool.hook("execute.before", handler)`, where `handler` receives
`{ tool, input }` and mutates `input` in place. Guard it:
`typeof ctx?.tool?.hook === "function"`, and never throw from `setup` (a throw
fails the plugin).

## The two plugins that broke on 2026-10-11

| Plugin | Cause | Local fix |
|---|---|---|
| `rtk.ts` (auto-discovered) | v1 shape: `export const RtkOpenCodePlugin: Plugin = async …` — no default object at all | Rewritten to `export default { id: "rtk", server: RtkOpenCodePlugin, setup }`; `setup` re-registers the same `rtk rewrite` on `execute.before` |
| `openusage-telemetry.ts` | The file was **missing** (config still pointed at it, ENOENT) and, once restored from `~/.config/opencode/opencode.bak/plugins/`, still exported a bare v1 function | Restored + `export default { id: "openusage-telemetry", server: OpenUsageTelemetry, setup }`; `setup` relays `ctx.event.subscribe` events to the daemon's `/v1/hook/opencode` |

Also removed the redundant `plugin: ["file://…/openusage-telemetry.ts"]` entry
from `~/.config/opencode/opencode.json` (backup:
`opencode.json.bak-2026-10-11-plugins`): a config-declared *file* path logs
`configured plugin path must be a directory`, while the `plugins/` directory is
auto-discovered anyway — `rtk.ts` loads with no config entry, and the log
confirms `openusage-telemetry.ts` still loads after the entry is removed.
Note for the openusage integration: its installer patches that entry back in,
and `openusage integrations status` may then report it uninstalled.

Both upstreams still ship v1 templates
(`rtk init -g --opencode`; `janekbaraniewski_openusage`,
`internal/integrations/assets/opencode-telemetry.ts.tpl`), so the fix is local
and upstream PRs are pending.

Verification: the running OpenCode reloads plugins on file change
(`watcher subscribe … type=file`), so the fix is checkable without a restart —
tail `~/.local/share/opencode/log/opencode.log` for `loading plugin id=…/rtk.ts`
with no following `failed to load plugin` line.
