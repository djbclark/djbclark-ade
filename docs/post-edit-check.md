# post-edit-check

Status as of 2026-11-09 (issue #284 item 3; Codex template wired). `bin/post-edit-check` is a PostToolUse check: after an
agent edits a file, it runs one fast, narrow syntax check on that file and says nothing unless something is broken.

## What it checks

| File | Check |
|---|---|
| `.py`, or a python shebang | `ruff check --isolated --no-cache --select E9,F63,F7,F82 --output-format concise` if ruff is on PATH, else an in-memory `compile()` (no `.pyc`). The `compile()` fallback reports only when the python running the hook is 3.10 or newer (macOS `/usr/bin/python3` is 3.9 and could false-flag newer syntax such as `match`); on older ones it is skipped |
| `.sh`, `.bash`, or an sh/bash shebang | `bash -n` |
| `.json` | `jq empty` if jq is on PATH, else `json.load`. JSONC-capable files are skipped (comments and trailing commas are valid there): `*.jsonc`, `tsconfig*.json`, `jsconfig*.json`, anything under a `.vscode/` directory, `devcontainer.json`, `.devcontainer.json` |
| `.toml` | `tomllib` (skipped on Python older than 3.11) |
| `*.tmpl`, other types, missing or deleted files, files over 2 MB | skipped |

The ruff select list is deliberately narrow (syntax errors, undefined names, invalid `%`-format and `is` literals), so problems already
in a file never nag on every edit.

Usage: `post-edit-check [--hook] [--budget SECONDS] [FILE...]`. `--hook` reads the PostToolUse JSON on stdin: `tool_input.file_path`
(Claude Write, Edit, MultiEdit) plus Codex `apply_patch` headers (`*** Add File:`, `*** Update File:`, `*** Move to:`) found in any string of
`tool_input`; relative paths resolve against the payload `cwd`. Exit codes: 0 clean, skipped or out of budget (and unreadable stdin in hook
mode); 2 problems (up to 40 lines on stderr); 64 usage error (CLI mode). Every subprocess gets the time left in the budget (default 1.5 s) as
its timeout; running out of budget is silent and exits 0.

## Why it never runs tests

Tests and type checkers are slow and heavy, and a hook fires after every edit. `bg_test_gate` exists because unslotted test runs drove the
machine load to 180-220. This hook is a syntax gate only; tests go through `bg bin/pytest` and the gate.

## Registration

Claude Code (`PostToolUse`, matcher `Write|Edit|MultiEdit`):

```
"$HOME"/ops/site-private/bin/hook-deadline 2 <path>/bin/post-edit-check --hook
```

with `timeout` 20. Claude reads stderr when a hook exits 2 and shows it to the model.

**`hook-deadline` exit 2 (verified 2026-11-09; queue Carried #1 residual):** the wrapper lives outside this repo
(canonical source: site-djbclark `bin/hook-deadline`; the Claude template still points at
`$HOME/ops/site-private/bin/hook-deadline`). Its contract and a live run of that script both confirm: when the child
finishes before the deadline, stdout and the child's exit code are forwarded unchanged (so exit 2 reaches Claude and
surfaces stderr); only a deadline hit kills the process group and exits 0 with no output. The 2026-11-04 open question
is closed — a broken `.py` edit behind this wrapper is not silent.

Codex (`agents/codex/config.toml.tmpl`, 2026-11-09): `PostToolUse` matcher `Edit|Write|apply_patch` runs
`{{ .home }}/src/djbclark-ade/bin/post-edit-check --hook` with `timeout` 20 (no `hook-deadline` wrapper: Codex's own
timeout bounds the hook, and the exit-2 passthrough question above stays Claude-only until verified). Codex shows
stderr on exit 2. Applying that template into live `~/.codex/config.toml` needs the operator's yes (order 11); after
apply, trust the new handlers in `/hooks`. OpenCode wiring is skipped (archived/retired transport). The Codex
patch-header parsing was already in the script, so this was a config change only.
