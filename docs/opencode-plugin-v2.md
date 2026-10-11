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

## The permission order, measured (2026-10-11)

Does the v2 `execute.before` hook run before or after OpenCode evaluates its
permission rules? Measured with a throwaway plugin and a temporary rule, both
reverted afterwards:

1. Probe plugin: logged every `execute.before` event and rewrote one sentinel
   command (`echo PERMTEST-ORIGINAL` → `echo PERMTEST-REWRITTEN`).
2. Temporary config (V2 shape is a list of `{action, resource, effect}` with
   `action: "shell"`):
   `"permissions": [{ "action": "shell", "resource": "*PERMTEST-REWRITTEN*", "effect": "deny" }]`
3. Running the sentinel was **denied** —
   `{"error":{"type":"permission.rejected","message":"Permission denied: shell"}}`.
   The original string does not match that rule, so the permission engine must
   have seen the **rewritten** command.

**Conclusion: the hook runs before permission evaluation**, so a plugin that
rewrites a shell command can move it out from under a `deny`/`ask` rule that
matched the original. That is exactly the gap `rtk rewrite` leaves and the one
`rtk-ai/rtk#4187` closes by delegating to `rtk hook opencode` (which judges the
rules) and by reading OpenCode 2's `permissions` list.

Shape facts confirmed in 2.0.26: `ctx.tool.hook` exists; `execute.before`
receives `{ agent, id, input, messageID, sessionID, tool }` with `tool` =
`shell` for bash and `input.command` the raw command, *pre*-rewrite; a plugin
can mutate `input.command` and the mutation reaches execution. So a
permission-aware shim is possible: read the rules before rewriting.

Our own `~/.config/opencode/opencode.json` has no `permissions` key, so the
local shim is unaffected today; revisit if deny/ask rules are ever added.

**The local shim now fails closed anyway** (2026-10-11, operator's call):
`~/.config/opencode/plugins/rtk.ts` registers no rewrite at all when the
effective config declares any shell permission rules (`permissions`, a v1
`permission` object, or an `experimental.policies` entry with
`action: "permission"`), and says so on stderr. It reads the global config plus
every `opencode.json(c)`/`.opencode/opencode.json(c)` from the session directory
up to the filesystem root, and treats an unparsable file as "rules present". The
canonical copy lives at `djbclark-ade/opencode-plugins/rtk.ts` and is restored by
`djbclark-ade/bin/opencode-plugin-guard` (Jobber 03:45) if a tool upgrade
reverts it.

## Upstream status (2026-10-11)

1. **openusage**: PR opened — `janekbaraniewski/openusage#421`
   (`fix(opencode): support the OpenCode 2 plugin contract in the telemetry
   integration`), after an independent security review (APPROVE, no findings).
2. **rtk**: **no PR by us.** `rtk-ai/rtk#4187` already implements the same fix
   (dual `{ id, setup, server }` export, `ctx.tool.hook("execute.before")`,
   delegating to `rtk hook opencode`), is MERGEABLE and in maintainer review;
   maintainers close duplicates in its favour (#4470, #4311, #3899). Our patch
   is verified and pushed to `djbclark/rtk`, branch
   `fix/opencode-v2-setup-export` (commit `b11bf398`), so a PR is one command
   away if wanted. The recommended next step is a comment on #4187.
3. **`rtk rewrite` vs `rtk hook opencode` — a permissions caveat.** Released rtk
   (0.51.0) has no `hook opencode` subcommand, so the local shim's `rtk rewrite`
   delegation is the only one that works today. Upstream's own review of #4187
   found that a rewrite which does *not* judge OpenCode's rules can change which
   permission rule matches (a MEDIUM authz finding: a `deny`/`ask` pattern for
   e.g. `git push*` no longer matches after the rewrite). Our local shim is
   therefore **unverified** for configs that rely on OpenCode `permissions`
   deny/ask rules for bash. When rtk ships `hook opencode`, switch the shim's
   delegation to it (it judges the rules); #4187 is where that lands.

