# Changelog

All notable changes to this repository are recorded here, newest first, in the
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) form. Every pull request adds its line
under **Unreleased** (AGENTS.md, code review rule 10, since 2026-10-20); a tag moves that section
under a dated heading. `ade update` (proposal 4.4 item 9) prints the entries between the commit a
machine last applied and the head it is moving to, so this file is what tells an operator or an
agent what changed and what is new. Entries end with the pull request number.

## Unreleased

### Added

- `bin/ade-backup-stores`: Phase 0 backups, a SQLite online-backup copy of every live agent session database, the
  per-session trees and file stores and the Hermes JSONL export (run against a scratch copy of the Hermes
  database), with a hashed `MANIFEST.json`, built in `<dest>.part/` and renamed when complete; `--dry-run`,
  `--only`, `--json`, `--check-schemas`, `--strict-stores`. A configured store that does not exist is
  `"status": "missing"` in the manifest and on stderr (exit 0, so a partly provisioned machine still gets a
  generation; `--strict-stores` exits 1) and a Cursor session whose required `meta.json` is symlinked,
  excluded or gone during the copy is an error that marks its store `partial`. Credential file names and paths (inventory 5.5, plus `mcp-auth.json`),
  the `credential-bak` vault and symlinks inside a store (a linked Cursor `store.db` or a database under a linked session directory included; each skip is printed on stderr and leaves the store `ok`) are not copied (a store root that is a symlink, as Codex's sessions are on this Mac, a per-session tree root that is one, or a configured SQLite path that is one, as Codex's databases are, is followed under one root-link rule when it resolves under `$HOME` to a non-credential path and recorded as `root_symlinks`; a dangling, outside-`$HOME` or credential-path link is an error), OpenCode's credential tables are scrubbed from its
  database copy, and a schema guard fails the run on any other credential-looking table or column; session
  transcripts are copied as they are and can hold pasted secrets. Refuses a destination that exists, holds
  a source store or sits inside one, a configured store counting whether or not it exists; a source that turns into a symlink mid-copy is never followed, the Hermes export fallback obeys the root-link rule and a dry run survives a store pruned under it; Muse's `tui-history.jsonl` is backed up, the dry run skips an excluded-name database in a SQLite tree like the real copy (and lists `skipped`), and `--check-schemas --strict-stores` exits 1 on a missing database or tree root; a sidecar, a single-file root or a SQLite source swapped for a symlink after its check is refused, never followed; a Cursor session with no `meta.json` is a `sidecar_missing` warning (db copied, store `ok`; an error only under `--strict-stores`), `--check-schemas` counts unopenable databases apart, Crush's `crush.json` and `projects.json` are backed up (`crush-files`), a store is walked by descriptor so a directory swapped for a symlink mid-copy is refused, and a skipped optional sidecar is listed under `skipped` (#24).
- `session-finder/relay.py` reaches Paseo-hosted agents (`paseo send --behavior steer -- <id> <text>`, labelled as an agent message from the sender; takes a `PASEO_AGENT_ID` as the ident, `--idle S` waits for idle first; refuses archived agents, pending permissions and text starting with `/`) and `where.py` reports `host=paseo agent=<id>` for them, so the "no terminal channel (unknown terminal)" refusal no longer hits a Paseo agent (#25).
- `agents/` templates for `~/.claude/settings.json`, `~/.codex/config.toml`, opencode's `opencode.json` and
  `~/.hermes/config.yaml` (secrets, home paths and host or account ids as placeholders, listed in
  `agents/README.md`), `bin/ade-template-check` (credential scan, render-and-parse with plain and hostile values, `--diff` by key path) and its
  tests; CI now installs PyYAML for them (#23).
- `loadwatch` skill and `load-watch watcher set|show|clear|test`: one registered agent session (a Paseo
  agent by `paseo send`, else relay.py) also hears every load incident, unexplained sustained load and
  job-guard trip, and investigates; `set` replaces the old watcher and tells it (2026-10-20).
- `docs/ade-everywhere-inventory-2026-10-20-stores.md`: Phase 0 slice 1, every installed agent
  session store classified (52 stores, backup plan per store, differences from proposal §6.1) (#16).
- `CHANGELOG.md`, this file, and the rule that every pull request adds a line to it; README
  "Update (this machine)"; proposal v2.4 with `ade update` as a Phase 1 command and acceptance
  test T8 (2026-10-20).
- `self-slash --finish`: end the session; on Paseo it waits for idle and archives the agent without
  `--force`, and `self-slash "/quit"` there is mapped to it (Paseo runs no `/quit`); `/new`, `/clear`,
  `/reset`, `/quit`, `/exit` and `--finish` take a per-agent lifecycle lock, keyed on pid and start
  time (#19).
- `self-slash` exit 9: a dispatched agent (`ACP_RUN_AGENT=1`, set by `acp-run`) is refused every
  lifecycle action and `/compact` (#19).
- `docs/threat-model.md`, the threat model Codex's security review reads (#10).
- AGENTS.md "Code review" section: what a reviewer checks on every pull request here (#9).
- `bin/cursor-cloud`: launch and inspect Cursor Cloud Agents from the terminal, with unit tests
  and a doc page (#5, #8).
- Load gate: no slice starts on a hot machine (`load-watch admit` plus the `acp-dispatch` gate)
  (#7).
- `acp-dispatch`: a `cursor-cloud` place (record, poller, report) and the matching
  `route_agent` service (#11).
- CI runs the pytest suite on ubuntu-latest as well as macOS (#3).
- `herdr-tidy`: Orca host mode (`--host orca`, `/orca-tidy`) (#2).

### Changed

- `acp-run` removes `PASEO_AGENT_ID`, `PASEO_AGENT_CWD` and `ORCA_TERMINAL_HANDLE` from every agent's
  environment and sets `ACP_RUN_AGENT=1`; `self-slash --finish` and `--then /quit` on Paseo are
  rejected with `--then`, and `paseo agent archive` gets `--` before the id (#19).
- The context-size nudge tells a session to run the `handoff` skill (Step 9 does the `/new`) and, on
  Paseo, to offer the `loose` Rule 4 choices instead of archiving itself; the dispatch footer, `handoff`
  Step 9 and `loose` Rule 4 say lifecycle actions run only in the top-level session (#19).
- `handoff` ends in a new Step 9 that clears the session and starts `/baton` by itself; `loose`
  Rule 4 offers handoff and continue, finish and archive, or keep working; `baton` never clears
  a session itself (#19).
- `acp-dispatch check`: a slice whose recorded class is `killed:` or `lost` gets the `resume` hint (no
  "after the reset") and no `--escalate`; a missing agent binary is `NO-REPORT: not-installed` (exit 127
  plus acp-run's own line) with a re-dispatch hint; `acp-run` waits up to 90 s (`ACP_RUN_BIN_WAIT`, clamped
  to 0..600, junk is the default) for a missing binary and preflight allows for that wait; re-dispatching a
  footed brief under a new `--name` carries one delivery contract, cutting only a provably generated tail
  and saying so on stderr (#18).
- `route_agent`: pool state comes from `aiuse --available --json`, with the snapshot file as the
  fallback (#12).
- `steps` skill: prompt-tool table and §2c cover the `question` tool so `/loose → /steps`
  walks via `question` on OpenCode, not just `AskUserQuestion` (Claude class) /
  `clarify` (Hermes) / `request_user_input` (Codex). Universal skills `/loose`,
  `/handoff`, `/baton`, `/steps` were already reachable from every installed TUI
  (`skill-everywhere --check` all green); the change wires the chain on OpenCode.

### Fixed

- `diskfree` skill: the idle check for deleting a cache runs in the same command as the delete; a
  `target-shared` delete approved minutes earlier broke a live maturin build (2026-10-20).
- `load-watch` job guard: a slow crash loop (60 failed restarts in 2 h) now trips too; litellm restarted
  every ~32 s for 19 h, just under the 20-in-10-min rule, and was never stopped (2026-10-20).
- `load-watch`: the registered watcher hears an unexplained sustained load at most hourly; Hermes keeps
  its 6 h cooldown (2026-10-20).
- `skill-everywhere`: the Hermes gateway nudge follows `hermes` wrappers to the real python; since `hermes`
  became a `/bin/sh` wrapper it ran the snippet under sh, where `import os, sys` was ImageMagick (2026-10-20).
- `acp-dispatch`: re-dispatching a footed brief cuts a footer only when each of its items is a line of the
  footer template and its heading is the template's own, so a constraint a lead added to or edited in a
  pasted footer or its heading is kept, in linear time; a `-f` file that is
  only a footer is refused ("no task is left"); the preflight probe and the slice's waiter deadline allow for
  acp-run's binary wait plus its settle polls (`bin_poll_seconds`); a probe that finds an agent not installed
  is remembered for 120 s, and an `ok` entry dated in the future is not trusted; `check` gives an `auth` stop the login hint, not `--escalate` (#22).
- `tests/conftest.py` pins `ROUTE_AGENT_OMP_READY=0`, so the route_agent suite passes on a host with
  an omp login as it does on CI; the omp-ready roster has its own tests (queue item 6) (#17).
- `acp-dispatch`: an unmeasured (stale) quota window is skipped instead of crashing the dispatch
  with a `float(None)` error (#13).
- `self-slash` (herdr): a slash command left on the input line after the first Enter is Entered again, up to 3 times,
  for every TUI and not only cursor-agent; if it never leaves the line the waiter exits 8 and logs "NOT confirmed
  run" instead of "sent" (2026-10-20).

### Security

- `firecrawl-router`: the serve-only form refuses a non-loopback `--listen` like `--open` does,
  and the address actually bound is checked before the first request is served (#14).
- `cursor-cloud` and `firecrawl-router`: endpoint variables must be https or loopback, bearer
  keys never follow a redirect or a client-chosen request target, and `cursor-cloud` runs under
  `python3 -I` with proxy, CA and `PYTHON*` variables scrubbed from the key-holding process (#15).
