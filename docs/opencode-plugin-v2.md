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

**Update 2026-10-29:** OpenUsage was uninstalled (djbclark), so the canonical
`openusage-telemetry.ts`, the guard's `openusage` handling and plugin-entry strip, and the
OpenUsage hooks in the Claude and Codex templates are gone. Only `rtk.ts` is guarded now;
the `openusage-telemetry.ts` row below is history.

| Plugin | Cause | Local fix |
|---|---|---|
| `rtk.ts` (auto-discovered) | v1 shape: `export const RtkOpenCodePlugin: Plugin = async …` — no default object at all | Rewritten to `export default { id: "rtk", server: RtkOpenCodePlugin, setup }`; automatic rewriting disabled in both entrypoints on 2026-10-25 (see below) |
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

**Conclusion: the hook runs before permission evaluation.** A rewrite can
change which `deny`/`ask` rule matches the original shell command. The existence
of an upstream adapter or a successful `rtk hook opencode` invocation is not
proof that the supported host preserves those matches.

### Correction and current policy (2026-10-25)

The former local shim was unsafe: `ctx.permission.list()` returns **pending
permission requests**, not effective global, project and managed rules. An empty
request list incorrectly admitted rewrites. Scanning config files cannot prove
the complete native permission contract either. The old claim that the shim
failed closed for effective rules is retracted.

`opencode-plugins/rtk.ts` now registers **no automatic rewriting in either V1
or V2**. Both entrypoints emit a notice and leave shell commands unchanged.
Explicit `rtk <command>` calls remain available: native permissions see that
original command. Re-enable automatic integration only after reviewing and
verifying its permission contract on each supported host.

`bin/opencode-plugin-guard` restores this disabled module after a V1 installer
replaces it and migrates only the exact SHA-256 of our former unsafe managed V2
copy (`8e46510ecdc95d4268838e435d33752d179675a6005b8de2483c7355b5d7da44`).
Unknown V2 RTK copies are preserved with exit 1 and a review notice. An old
`obsolete` sentinel or `upstream-v2-rtk` marker cannot suppress the migration;
the guard never invokes a hook subcommand to infer safety. Replacement follows
symlinks and atomically replaces the real target. `--check` reports the needed
migration without changing plugin bytes. Existing servers may retain loaded
code: verify native loading at a fresh location and do not restart busy agents.
An unsafe canonical source is refused without writing, even if a newer guard
is run from a worktree before the canonical checkout is updated. Dangling or
cyclic plugin symlinks and non-regular entries are preserved for review without
creating a destination.
To clear an unknown-copy warning, review and preserve that copy, then replace it
with the reviewed disabled module; adopting an upstream adapter also requires
updating this guard's documented safety policy.

For native smoke tests, verify the loader's `loading plugin` record and absence
of plugin-load failures alongside the status RPC. OpenCode 2.1.4 did not expose
this module's `console.warn` notice in captured stderr or its log; absence of
that notice is not a failed load. The entrypoint tests verify no hooks.

Offline tests cover both entrypoints with empty, pending, malformed, restrictive
and failing permission responses, plus restore, exact migration, symlink,
unknown-copy and idempotence cases without inference.

Upstream check on 2026-10-25: [RTK PR 4187](https://github.com/rtk-ai/rtk/pull/4187)
was merged and supplies a separate permission-aware adapter. Our former
`permission.list()` shortcut was local; it is not that upstream adapter.
This change disables our local shim and does not patch RTK's Rust source.
Adopting an upstream replacement remains a separate contract review.

## Historical upstream status (2026-10-11; not current safety evidence)

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
   e.g. `git push*` no longer matches after the rewrite). Automatic rewriting was subsequently disabled on 2026-10-25. Review the actual
   released contract before considering any replacement; do not switch merely
   because the subcommand exists.

