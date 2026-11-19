# Coordination plugin loading

`plugins/ade-coord/index.server.ts` imports only modules under `server/`.
Paseo rejects plugin implementation modules at the plugin root. The manifest
version is 0.1.1; the minimum supported API remains 0.16.0-beta.2.

The exact deployed beta.2 source is
`23bae61535542a45ade7196a7b3c152705f16de3`. Its `compiler-build.ts` emits
CommonJS and `bundle-evaluator.ts` evaluates that bundle; `import.meta.url`
does not name the plugin source. `PluginServerContext` provides no source root.
The directory passed to the worker is internal protocol data, not exposed context.

`server/runtime-paths.mjs` resolves plain Node ESM from its real source module.
In the compiled runtime it reads only the `plugins["ade-coord"].path` field of
Paseo's own `config.json` install record. As in beta.2's `paseo-home.ts`,
`PASEO_HOME` selects the daemon home; without it the account home supplies
`.paseo`. Relative home/record paths are refused, not resolved from agent cwd.
There is no shared-checkout or working-directory fallback.

The record must be a bounded, regular, owned, non-writable-by-others file.
Canonical plugin location must be exactly `<root>/plugins/ade-coord`, with
manifest id `ade-coord`. The root, helpers, guard directory/entries, Node CLI and
instructions must be owned by this user or root, not group/world writable,
and resolve inside that same canonical runtime root. The installed `current`
symlink therefore resolves to its actual version directory; driver, controller,
launch PATH and instructions all come from that version. Missing or inconsistent
layout fails before hook/timer registration with one secret-safe error.

The Linux `plugin-loader` job installs current released `@getpaseo/server`
and prints exact package/Node versions. It invokes the package's actual
`compileDirectoryPlugin` and `evaluateBundle` internals, loads the real generated
CommonJS twice with cleanup between, and exercises an actual subprocess to a
synthetic controller/authority endpoint. It verifies installed-record resolution
through a version pointer and checks resulting driver/controller/PATH/docs paths.
It refuses loading with a missing install record. No broker or paid model is used.
These compiler internals are deliberately a conformance dependency: an upstream
layout/API change fails the job for review, rather than silently substituting a
hand-written bundler.

This is actual released compiler/evaluator and contribution disposal/reload
proof, with synthetic hook registration and controller authority. It is not a
running-daemon plugin install/reload, native queued-wake test or provider launch.
The lead performs native beta.2 install/reload in the separately approved pilot.
Latest released CI tooling does not substitute for that exact deployed source
audit or live validation.
