# post-edit-check

Status as of 2026-11-04 (issue #284 item 3). `bin/post-edit-check` is a PostToolUse check: after an agent edits a file, it runs one
fast, narrow syntax check on that file and says nothing unless something is broken.

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

Open question (2026-11-04): whether `hook-deadline` (outside this repo) passes the child's exit 2 through. If it turns a 2 into a 0 the
check is silent in practice; verify on the Mac with a deliberately broken `.py` edit.

Codex and opencode wiring is queued, not done: there is no Codex config and no opencode plugin yet. The Codex patch-header parsing is
already in the script so that wiring needs no code change here.
