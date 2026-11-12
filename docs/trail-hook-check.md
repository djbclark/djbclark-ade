# Trail matcher drift check

As of 2026-11-12, Trail 0.29.0's skill-consent matcher rejects inert report,
search, and message text. [Upstream issue 827](https://github.com/trailhq/Trail-Code/issues/827)
tracks the bug. An operator-authorized local compatibility patch accepts narrowly
validated literal data; it is lost when the package is upgraded.

Run `node bin/ade-trail-check` after a Trail/graft upgrade. It imports the pure
`agentGuard` matcher from the installation remembered in `~/.trail/install.json`
(or `$TRAIL_HOME/install.json`) and passes command strings as data. It never
executes fixture commands, changes skills, invokes the hook entrypoint, or
repairs an installation. Its Python AST validation dependency is exercised by
the installed matcher when the compatibility patch is present.

The hook shim can choose a newer package than the remembered installation.
When that happens, select its matcher explicitly with
`node bin/ade-trail-check --matcher /absolute/path/to/dist/skills/risk.js`.
Relative matcher paths are accepted and resolve from the current working
directory; the JSON output always reports the resolved absolute path.
The JSON output names the exact matcher checked. Exit 0 means all inert-data
and execution fixtures passed; 1 means behavior drift; 2 means the dependency
or invocation is unavailable. Missing Node/Python or a changed export needs
investigation, not an automatic hook override. Run with an outer command
deadline if checking an unfamiliar installation.

Coverage includes the original six cases and wrapped commands, command
substitutions, backticks, eval, pipelines, Python subprocess/system/eval/f-string
execution, dynamic activation, renamed binaries, and script-file output. Python
report allowances deliberately cover only a quoted stdin heredoc with literal
`Path.write_text`/`touch` or `print` operations. Other interpreter programs keep
their conservative denials. No `TRAIL_NO_HOOKS` setting is used.
