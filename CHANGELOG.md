# Changelog

All notable changes to this repository are recorded here, newest first, in the
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) form. Every pull request adds its line
under **Unreleased** (AGENTS.md, code review rule 10, since 2026-10-20); a tag moves that section
under a dated heading. `ade update` (proposal 4.4 item 9) prints the entries between the commit a
machine last applied and the head it is moving to, so this file is what tells an operator or an
agent what changed and what is new. Entries end with the pull request number.

## Unreleased

### Added

- `load-watch sample` also watches compressor churn: above the `admit` limit (60000 pages/s) for `LW_CHURN_SUSTAIN_S` (180 s) it sends one line with the top
  three commands to the load watcher (at most hourly, cooldown `churn-watcher`) and to Hermes (cooldown `churn`), adds the Grok Bot/Chrome standing exception
  when they lead, never signals anything; `status` lists both cooldowns; test hook `LW_FAKE_COMPRESSOR` (2026-10-23).
- Added `bin/claude-quota-guard` (`check`, `status`, `--install`), which turned the Claude weekly, 5-hour and Fable windows (read from the snapshot when `aiuse --available` drops an exhausted Claude or the exhausted Fable pool, and at least `watch` when aiuse dropped a Claude the snapshot still shows) and aiuse's Claude `conserve` alerts into a level (`ok`, `watch`, `tight`, `critical`; exit 0-3, 10 when Claude appears nowhere, the data is malformed, aiuse is unreadable or another check holds the lock, 64 for a bad thresholds env, 69 for `--install` off macOS), wrote `~/.local/state/ade/quota-guard.json` under a lock, pinged once per level per reset period, and treated data older than 3 hours (the oldest of the payload, each pool and the snapshot) as stale: at least `watch`, no level pings, one ping per stale episode; added the `claude/hooks/quota_nudge.py` UserPromptSubmit hook, which printed the level's advice once per session and level (#29).
- `load-watch admit` also gates on memory: it is hot when compressor churn (macOS `vm_stat` Compressions +
  Decompressions, pages/s) exceeds the new `--max-mem-churn N` (default 60000, calibrated 2026-10-23 from 215
  samples: calm 11-22k, load >=25 median 80k; the first guess, 20000, was below the load<10 median of 34k), so `acp-dispatch` (which calls `admit`) holds new slices during a thrash that load alone does not show; `bg` (site-djbclark `bin/bg`, f370ad7) now also asks `admit` after its own load check and fails open if `load-watch` errors.
  The result and `--json` carry `mem_churn_pages_s`; no `vm_stat` (Linux) means the gate never blocks (2026-10-23).
- `relay.py` picks the best route for the session (Paseo `send`, `acp-dispatch tell`, a live ACP launch's inbox, keys into
  its pane, then the Claude messaging socket) and falls back to the next itself when one fails before sending; it errors
  only when every route has, listing each reason. A send it cannot rule out (text typed but unseen, a `paseo send` that
  may have reached the daemon, a socket frame written) never falls back, so nothing is delivered twice. New `--plan`
  and `--via ROUTE`; `--idle S` now also waits for a working non-Claude pane TUI; the Paseo gate runs whatever `--via`
  says. Text starting with `/` or `!` is no longer typed into a pane (only a socket frame carries it); a Claude with a
  draft in its box now gets the message by socket instead of exit 1, and an idle one is checked in its transcript.
  Text a pane relay left unsent is remembered for an hour with the draft it showed; a retry of the same text types
  nothing (it submits our own leftover, never the operator's draft or paste) and proves delivery in the transcript or
  reports it unverified ("do not resend"). Exit 1 means not sent or sent but unverified; read the message.
  Home item 24 and `session-finder` say agents message peers only this way (2026-10-23).
  Adversary round 7 (2026-10-23): a box whose ❯ row or bottom rule is outside the 14 rows read is "unknown", never
  empty (nothing typed or submitted blind; a retry of our text is unverified), a styled row starting `Try "` is the
  operator's text, only the placeholder seen right after typing is ours, a delivered text recalled into the box is
  never submitted again, a `---` row or a ❯ inside the box no longer hides rows, entries purge after a day.
  Round 8: the input box is the one rule row directly followed by a ❯ row (a rule or ❯ typed into a draft makes it
  unknown, not a smaller empty box), the box is read once, an unsent entry is forgotten only on proof, a delivery is
  a whole user or queued message in the transcript (never a substring), the first placeholder within 6 s of typing is ours.
- `bin/self-slash --finish --successor PROVIDER/MODEL [--thinking ID] [--mode MODE] [--title TEXT]` (Paseo only; exit 2 on herdr and Orca): after the turn it starts a new top-level agent in the same workspace (`paseo run "/baton"`, default mode and `--thinking high` of the old agent), checks it is not a subagent and runs the model asked, then archives the old agent; any failure exits 11, archives nothing and leaves this session usable. The successor always lands in an existing workspace (`--workspace ID`, default this agent's; never `--new-workspace`, and in another workspace it runs in that workspace's own cwd) with a short title. The old workspace was archived after the old agent only when proven unneeded: one cwd match with no workspace above that cwd (never an override of another row or a tie-break), local isolation, no terminals, no other agent in it by workspace id or cwd, and a cwd that neither equals nor contains the successor's (`--keep-workspace` skips that). The successor is polled for up to 20 s and must have a new id, a null `ParentAgentId`, the model asked and status idle, running or initializing, else exit 11. A malformed `SELF_SLASH_SUCCESSOR_SETTLE` is refused before `paseo run`, an inspect that fails after a good look exits 11, and no aborted successor path can fall through to the bare archive (#30).
- `skill-everywhere` gains a `grokbot` target: a rendered copy `ade-<name>/` in `~/agent-data/workflows/` on the
  Grok Bot box (banner, `.skill-everywhere` marker, only marked dirs touched), plus `--dry-run`/`-n`,
  `SKILL_EVERYWHERE_ONLY` and plain-GNU fallbacks so it runs on Linux (2026-10-23). (PR pending)
- `autorename` renames a Paseo-hosted session's workspace to the title in lower-case hyphen form plus `-pw`
  (`paseo-skill-sync-overwrite-fix-pw`; `--auto` keeps a workspace already ending in `-pw`); herdr tab labels keep
  `-t` (2026-10-23).
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
  a source store or sits inside one, a configured store counting whether or not it exists; a source that turns into a symlink mid-copy is never followed, the Hermes export fallback obeys the root-link rule and a dry run survives a store pruned under it; Muse's `tui-history.jsonl` is backed up, the dry run skips an excluded-name database in a SQLite tree like the real copy (and lists `skipped`), and `--check-schemas --strict-stores` exits 1 on a missing database, tree root or file-store path and never opens a credential-named database (`E excluded`); Crush's `crush.json` (provider key and OAuth tokens) is not backed up; a sidecar, a single-file root or a SQLite source swapped for a symlink after its check is refused, never followed; a Cursor session with no `meta.json` is a `sidecar_missing` warning (db copied, store `ok`; an error only under `--strict-stores`), `--check-schemas` counts unopenable databases apart, the `crush-files` store backs up Crush's `projects.json` only, a store is walked by descriptor so a directory swapped for a symlink mid-copy is refused, a skipped optional sidecar is listed under `skipped`, and a store root reached through a symlinked parent directory gets the same root-link gate, and tree stores are opened through the anchored home descriptor too, the Hermes dry run reports a refused `state.db` link like the real run, and a failed per-session or bulk export leaves no partial file, and the dry run reports a missing `hermes` like the real run, and `--only hermes-export --check-schemas --strict-stores` checks the `state.db` source, a WAL-mode copy is made self-contained so the schema guard opens it under every SQLite build, and a symlinked directory in a tree glob is one `symlink` skip, never entered, a configured root of the wrong type (a directory where a single file belongs, or the reverse) and a subdirectory the dry run cannot list are store errors, not copied or silently skipped, and a non-regular Hermes `state.db` or any link above a glob's last component is refused or skipped without being followed, and the Hermes export reads `~/.hermes/config.yaml` anchored at $HOME, without blocking or following links and capped at 64 KiB, else uses the default limit with a warning, and a database or directory that vanishes or is unreadable between listing and `lstat` in a SQLite tree is an error (not silently omitted) while a dangling link at the last component stays a non-match, and `--json --check-schemas` prints one JSON document (the text lines go to stderr; exit status unchanged), `--check-schemas` validates a Cursor session's required sidecar like the copy (`sidecar_missing`, a failure only under `--strict-stores`; a linked one always), the dry run records an entry it cannot lstat like the copy, and a refused `config.yaml` or source leaks no descriptor (#24).
- `session-finder/relay.py` reaches Paseo-hosted agents (`paseo send --behavior steer -- <id> <text>`, labelled as an agent message from the sender; takes a `PASEO_AGENT_ID` as the ident, `--idle S` waits for idle first; refuses archived agents, pending permissions and text starting with `/`) and `where.py` reports `host=paseo agent=<id>` for them, so the "no terminal channel (unknown terminal)" refusal no longer hits a Paseo agent (#25).
- `agents/` templates for `~/.claude/settings.json`, `~/.codex/config.toml`, opencode's `opencode.json` and
  `~/.hermes/config.yaml` (secrets, home paths and host or account ids as placeholders, listed in
  `agents/README.md`), `bin/ade-template-check` (credential scan, render-and-parse with plain and hostile values, `--diff` by key path) and its
  tests; CI now installs PyYAML for them (#23).
- `loadwatch` skill and `load-watch watcher set|show|clear|test`: one registered agent session (a Paseo
  agent by `paseo send`, else relay.py) also hears every load incident, unexplained sustained load and
  job-guard trip, and investigates; `set` replaces the old watcher and tells it (2026-10-20).
- `cfenginewatch` skill (with `fleet-watch upstream --relay-to|--relay-test|--relay-off|--relay-status`, in
  site-djbclark): one registered agent session hears every reviewer event on djbclark's upstream CFEngine
  PRs and works it through `/bigteam`, prepare-and-stop; `--relay-to` replaces and tells the old watcher
  (2026-10-23).
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

- Routing: moved lead / orchestrator sessions to Opus 5.5 at high (Sonnet 5.5 at high only to drive a pipeline), never Fable (`config/routing.toml` `[lead]`, printed by `route_agent.py policy --md`); sent adversary rounds first to `acp-dispatch omp --model anthropic/claude-opus-5-5 --kind judgment --effort high` (omp became eligible for `judgment`), and had the Agent-tool `adversary` take a `model: "sonnet"` override when the guard says `tight` or worse (#29).
- `self-slash`'s 30-minute gap check read any log line that merely contained `<host> <pane>: sent /compact`; it now matches only lines that start with the timestamp, and a value flag as the last argument is a usage error (exit 2) instead of an endless loop (#30).
- `handoff` Step 9 runs `self-slash --finish --successor claude/claude-opus-5-5 --thinking high` (Sonnet 5.5 when the quota guard says `tight`) instead of `/new` on Paseo when the session runs on Fable, `~/.local/state/ade/quota-guard.json` says `tight` or `critical`, or the operator asks for a model change, and the context-size hook names that form in its boundary and ask messages; a quota guard only moves a session down from a model known to be above the target, an unknown or lower model gets plain `/new` (#30).
- `loose` gains an "On Grok Bot" section (G1-G7) with pointers from Rule 2, 3 and 4: box paths, GitHub reads via `gh`/
  `GITHUB_TOKEN_DJBCLARK` or the connector, the box's own jobs instead of a Mac process list, a chat reply instead of
  `hermes-ping`, no `handoff`/`self-slash`/`/compact` there; still walks the findings with `/steps`. Other runtimes'
  rules are unchanged (2026-10-23).
- `steps` gains a Grok Bot branch: Prompt tool rule 5 and section 2d use Grok Bot's `SendToUser` question widget
  (context in a text message first, one-line numbered labels, recommendation `primary`, destructive `danger`,
  `allowCustom` for `stop`, a dismissal is a decline; no `/compact` or `self-slash` there). Other runtimes'
  rules are unchanged (2026-10-23).
- `acp-dispatch --detach`: a `waiter:` line above `rearm:` says to run the waiter in the background with a long tool timeout (Claude Code Bash: `timeout 7200000`); at the 30 min default a lead's harness killed it mid-slice. `rearm:` stays the last line (#28).
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

- `acp-dispatch` refuses `--perm read-only` or `--perm deny` (exit 2, before any record or preflight) for an agent
  whose `acp-run <agent> --info` `perm_modes` lacks that mode; before, acp-run's own refusal came after the
  record was written and surfaced as a no-report (an omp adversary round, 2026-10-23).
- Paseo's start-up skill sync no longer overwrites the six vendored `paseo*` skills in this repo through the
  `~/.claude/skills` and `~/.agents/skills` links: the daemon's skill selection is now `custom` with no skills;
  how it works and what to avoid in Paseo's settings are in docs/skill-everywhere.md section 3a (2026-10-23).
- `acp-run` classifies zcode's `token_login_failed` error code (inside its "Internal error" envelope) as `auth`, never retried, instead of `transient` (#26).
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
- `firecrawl-router`: tokenless serving answers only a `Host` header that names the bound
  loopback server (DNS-rebinding allow-list), and the bearer compare is constant-time
  (`hmac.compare_digest`) (2026-10-22).

  run" instead of "sent" (2026-10-20).

### Security

- `firecrawl-router`: the serve-only form refuses a non-loopback `--listen` like `--open` does,
  and the address actually bound is checked before the first request is served (#14).
- `cursor-cloud` and `firecrawl-router`: endpoint variables must be https or loopback, bearer
  keys never follow a redirect or a client-chosen request target, and `cursor-cloud` runs under
  `python3 -I` with proxy, CA and `PYTHON*` variables scrubbed from the key-holding process (#15).
