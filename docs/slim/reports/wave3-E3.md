# Wave 3 report E3 (S-finder): the relay shim, claude_identity to bin/, session-finder internals deleted

Writer: one Claude agent, 2026-11-06, in worktree `/home/user/djbclark-ade/.claude/worktrees/agent-a4772e28ffb7daa78`,
branch `worktree-agent-a4772e28ffb7daa78`, based on `claude/determined-maxwell-uvddaz` at 7762c1e (fast-forwarded from
master fb3b9de first, so the brief and this report sit beside each other). Brief: `docs/slim/briefs/wave3-E3-finder.md`.
Not pushed (the lead merges). No Paseo daemon was run: every `paseo` call in the tests is a fake on PATH.

Commits: 3bfeb5a (claude_identity move), 5f8a4a6 (the shim, deadline), 4fb10d1 (deletions, KEEP-file edits), af265dc
(report draft), and the commit with the H3b test fixes and the suite result. Not done here, on purpose: E3b (`fleet.py`, `tests/test_fleet_*.py`), `prompt_line.py`
(E4), AGENTS.md, README.md, docs/skills.md, CHANGELOG.md, docs/queue.md, the settings template.

## A. The shim

A0. Revised after the E3 review (BLOCK, two HIGH; repaired at the head named in the reply). F1 changed the status
contract (A5), F2 made the inspect gate fail closed (A4b), F3 added the steer check (A4c), F4 the sender rule (A4d), F5
the input checks (A4e). Read against Paseo 0.15.3 source (getpaseo/paseo 9f68af0, the clone at `/tmp/claude-0/ps/src`).

A1. `skills/session-finder/relay.py`, 238 lines, stdlib only (the brief said about 100; the rest is the review's gates
and the help epilog). Line 2 carries the removal line, "Shim, removed in the follow-up PR after one live cycle
(PLAN.md F, Wave 6; at the latest 2026-11-20)".

A2. Flow: refuse a retired flag (before argparse) → check `--wait` → read the text (positional or `--message-file`, `-` =
stdin, decoded as UTF-8 from bytes, BOM dropped, one trailing newline dropped, nothing else changed) → refuse a leading `/`
→ settle the sender (A4d) and prefix `[relay from LABEL]` for a sourceless sender → append the `--ack NAME` line → `paseo
ls -a -g --json` → resolve (A3) → `paseo agent inspect ID --json` and the gate (A4b, A4c) → write the text to a private
temp file → `paseo send ID --prompt-file F --behavior steer --no-wait --json` → read `.status` (A5) → with `--wait S`,
`paseo wait ID --timeout S --json`.

A3. Resolution (lead's ruling, 2026-11-06, after this report's first version: the brief's 1a `name` rule is dropped,
since a title comes from the first prompt and is a weak address, adversary L3): the exact `id`, else a prefix of 4+
characters of `shortId`, which must be unique (more than one hit is exit 3 "matches N Paseo agents (ids)"). `self` is
`$PASEO_AGENT_ID` (unset: exit 3). A target that is an agent's name gets exit 3 with "target X is a Paseo agent's
name, not its id: pass the id (`paseo ls -a -g` shows it)"; anything else that resolves to nothing gets the retirement
text. A prefix of the full id longer than the shortId is not accepted. Every caller in this slice passes an id
(deadline: the owner id it recorded; load-watch: the session's id).

A4. Gates beyond the brief's 1b (standing order 6: flagged here):
- a. **Leading `/`** (kept from the old relay; `docs/threat-model.md`): after stripping every Unicode whitespace
  character (`str.isspace`) and the zero-width set U+200B, U+200C, U+200D, U+2060, U+FEFF, U+180E, a text starting with
  `/` or the full-width `／` is refused, exit 64: it would run a built-in in the target.
- b. **Inspect, fail closed** (review F2): the send goes ahead only when `paseo agent inspect ID --json` returns a dict
  whose `Id` equals the resolved id, `Archived` is boolean `false`, `PendingPermissions` is an empty list and `Status` is
  `idle` or `running`. A failed inspect, any other shape (`{}`, a list, a nested object, a string, null), another `Id`,
  `Archived` true or missing, a non-empty or missing `PendingPermissions`, or `Status` `initializing`, `error`, `closed` or
  missing: exit 2, `not sent: <reason>` naming the status. Doubly needed for a sourceless send: the daemon runs it with
  `clearPendingPermissions: true` (server `session.ts:8806`), so a send into a card would answer it with the message text.
  The field names are from `packages/cli/src/commands/agent/inspect.ts:14-49,129-155`.
- c. **No steer, no send into a running turn** (review F3): with `--behavior steer`, a provider that cannot steer has its
  running turn replaced (`agent-prompt.ts:38-60`). Inspect's `Capabilities` has no steer flag (it carries only
  `Streaming`, `Persistence`, `DynamicModes`, `McpServers`: `inspect.ts:33-38,118-127`), so the shim uses the providers
  whose session implements `steerActiveTurn` in 0.15.3 (`claude`, `codex`, `opencode`, `omp`, `pi`: `providers/{claude,omp,
  pi}/agent.ts`, `codex-app-server-agent.ts`, `opencode-agent.ts`). A `running` agent on any other provider (cline, grok,
  kiro, copilot, a plugin provider, an empty provider) is exit 2 "busy, not sent (provider X cannot steer: its running
  turn would be replaced)"; an `idle` one gets the send. A `Capabilities` key naming steer, if a later Paseo adds one,
  wins over the list. Residual: a steer-capable provider can still decline a steer at runtime (compaction, a Codex review
  turn), and Paseo then replaces the turn; a plugin provider that negotiates `prompt.steer` is refused while running.
- d. **No anonymous sends** (review F4; the 2026-10-25 ruling): a sender with no `$PASEO_AGENT_ID` must name itself in
  `$RELAY_SENDER_NAME`, which is cut to letters, digits, `-`, `_`, `.`, `:` and 64 characters before it enters the
  `[relay from LABEL]` header; an empty label is exit 4 before any `paseo` call. `bin/deadline`'s `clean_env` drops
  `PASEO_AGENT_ID` and sets `RELAY_SENDER_NAME` (`deadline` or the plist's `deadline-sweep`); load-watch's `relay_env`
  sets `load-watch`.
- e. **Input** (review F5): a message file or stdin that is not UTF-8 is exit 64; a `--wait` that is NaN, infinite or
  negative is exit 64.
- f. Two deviations from 1b's exact argv: `--behavior steer` (without `$PASEO_AGENT_ID` Paseo's default is interrupt,
  which cancels the target's running turn; the old relay passed steer too) and `--prompt-file` (no message text in `ps`,
  and a text starting with `-` is never read as an option).

A5. Status mapping (review F1). `paseo send` exits 0 for every status, so `$?` is never read as delivery. And Paseo's
daemon **queues every send that carries a source agent**: the CLI passes `sourceAgentId` whenever `$PASEO_AGENT_ID` is set
(`packages/cli/src/commands/agent/send.ts:202-207`), and the server enqueues such a message and sets `deliveryStatus:
"queued"` before dispatch (`packages/server/src/server/session.ts:8774-8793`), reporting no later delivery. So an agent's
send never reads `sent`; the first version's "queued: not yet delivered: the target has not been quiet for 2 s" was wrong
(the "two quiet seconds" is only the CLI's message text, `send.ts:219-221`).

| sender | `paseo` result | shim prints | exit |
|---|---|---|---|
| any | send `.status` `sent` or `completed` | `delivered` | 0 (then `--wait`, if given) |
| an agent (`$PASEO_AGENT_ID` set) | send `.status` `queued` (always, from 0.15.3's daemon) | `queued (accepted by the daemon; Paseo batches every agent-to-agent message and reports no later delivery; proof is the peer's ack)` | **5** |
| sourceless (deadline, load-watch) | send `.status` `queued` | `queued (accepted by the daemon, not delivered)` | 2 |
| any | send `.status` `timeout`, `permission`, `error`, or none | the status word (`no status`) | 2 |
| any | inspect gate (A4b, A4c) | `not sent: <reason>` | 2 |
| after exit 0 | wait `idle` / `timeout` / `permission` | `idle` / `wait timed out after S s` / `permission (...)` | 0 / 2 / 2 (wait failing: 1) |
| after exit 5 | wait, whatever it reads | `target idle`, `target wait timed out after S s`, `target permission ...`, `target wait failed: ...` | 5 (the target's state, never delivery) |
| any | `paseo` non-zero, no binary, unparseable JSON, no answer in time (ls 30 s, inspect 30 s, send 60 s, wait S+30 s) on ls or send | the stderr, on stderr | 1 |
| any | target a name / not exactly one agent by id or shortId prefix | the retirement text plus the reason | 3 |
| sourceless | no usable `$RELAY_SENDER_NAME` | `no sender: ...` | 4 |
| any | usage error, leading `/`, not UTF-8, bad `--wait`, `--via`, the outbox flags | the refusal | 64 |

Usage errors are 64, not argparse's 2, so a typo is never read as "not delivered". `--ack` takes an optional NAME: with
one it appends "Reply with `ack NAME` through relay.py." to the text; bare (as `bin/deadline` used to pass it) it appends
nothing. For an agent sender `--ack <your id>` is the only proof there is: exit 5 is the normal result in
`session-handoff` and `ade-paseo-handoff`, and the ack is read from the sender's own inbox. A bare `--ack` must follow
MESSAGE (argparse would read the text as NAME otherwise; the help says so).

A6. `--help` as committed:

```
usage: relay.py [-h] [--message-file PATH] [--ack [NAME]] [--wait S]
                TARGET [MESSAGE]

Send MESSAGE to one Paseo agent with `paseo send --no-wait --json` and report what Paseo says became of it.

positional arguments:
  TARGET               Paseo agent id, unique shortId prefix, or `self` (not a
                       name)
  MESSAGE              the text (exactly one of MESSAGE and --message-file)

options:
  -h, --help           show this help message and exit
  --message-file PATH  read the text from PATH, UTF-8 (`-`: stdin); for text
                       with backticks, `$` or quotes
  --ack [NAME]         append "Reply with `ack NAME` through relay.py" to the
                       text; bare --ack appends nothing; put MESSAGE before a
                       bare --ack
  --wait S             after a delivered (0) or accepted (5) send, `paseo wait
                       TARGET --timeout S`; for a delivered send exit 0 only
                       when it reads idle; for an accepted one it reports the
                       target's state only

exit status:
  0   delivered: a sourceless send (no $PASEO_AGENT_ID: deadline, load-watch) read `sent` or `completed`
      (with --wait: and `paseo wait` then read `idle`)
  5   accepted: a send from a Paseo agent ($PASEO_AGENT_ID set) read `queued`; the daemon queues every agent-to-agent message
      and reports no later delivery, so the proof is the peer's `ack <id>` (--wait then reports the target's state, never delivery)
  1   paseo failed: not installed, exited non-zero (no daemon, unknown agent), gave no JSON, or did not answer in time
  2   not delivered: `queued` for a sourceless send, `timeout`, `permission`, `error`, or no status; --wait timed out or hit a
      permission; or not sent: `paseo agent inspect` failed, gave another shape or id, shows the target archived, with a pending
      permission or question card, in a status other than idle or running, or running on a provider that cannot steer
  3   TARGET is not exactly one Paseo agent by id or shortId prefix, or is a name (relay.py reaches Paseo agents only since 2026-11-06 (herdr and Orca panes retired 2026-10-31))
  4   no sender: neither $PASEO_AGENT_ID nor $RELAY_SENDER_NAME names who sends (no anonymous sends, 2026-10-25)
  64  usage error, a message file or stdin that is not UTF-8, a --wait that is negative or not finite, a text starting with `/`
      (it would run a built-in in the target), or a retired flag: --via (relay.py reaches Paseo agents only since 2026-11-06 (herdr and Orca panes retired 2026-10-31)); --pending, --sweep, --retire, --transfer-expectations, --expect-ack
      (retired 2026-11-06: Paseo has no outbox; see `paseo permit ls` for pending permissions)
TARGET is a Paseo agent id, a unique prefix (4+ characters) of its shortId, or `self` ($PASEO_AGENT_ID), as `paseo ls -a -g` lists them;
never a name (title): a name is exit 3, pass the id.
A sender with no $PASEO_AGENT_ID (a launchd job) is named in a `[relay from NAME]` prefix, NAME from $RELAY_SENDER_NAME
(letters, digits, `-`, `_`, `.`, `:`; at most 64).
Shim: removed in the follow-up PR after one live cycle, at the latest 2026-11-20.
```

A7. `bin/deadline` (1f): its owner notice passed `--message-file - --ack --wait 20`. All three are in the shim's set, but
`--wait 20` changed meaning (old: verify delivery for 20 s; shim: wait for the owner to go idle), so a busy owner would
read as "not delivered" and the notice would be sent again up to `NOTICE_TRIES` (5) times. The call is now
`relay.py OWNER --message-file -` (`bin/deadline:460`; docstring :451-458 states the exit codes); `docs/deadline.md`
item 3 and `tests/test_deadline.py` follow. `clean_env` drops `PASEO_AGENT_ID`, so the notice is a sourceless send:
`sent` is delivery (exit 0) and it carries `[relay from deadline-sweep]`. Residual risk, flagged: a sourceless `queued`
(exit 2), which 0.15.3's daemon does not produce for a sourceless send, would be retried and could arrive twice.

## B. The import and path search

B1. The brief's command (3a), run before the deletions, gave 296 lines in 52 files (file counts: session-finder/SKILL.md
43, docs/queue.md 36, launch.py 24, fleet.py 15, ...). After this slice it gives 183 lines; minus the exempt
`docs/queue.md` (36), `CHANGELOG.md` (11), `README.md` (8) and `AGENTS.md` (3), 125 lines in 36 files. The brief's
`--include` list misses extensionless scripts and the word `relay.py`, so two more searches were run: the same terms
over files without those extensions (`bin/*`, `tools/acp-run/acp-run`, the template), and `relay\.py` over the same
includes. Every remaining hit, and what it became:

| Hit (after) | Disposition |
|---|---|
| `skills/session-finder/fleet.py` (15), `where.py` (2), `nested_pty.py` (1), `prompt_line.py` (2) | kept files (B2) |
| `bin/route_agent.py:1600` | the read-only `~/.local/state/session-finder` state path the brief exempts |
| `bin/acp-dispatch:846,848,957` (extensionless) | the same read-only state root (`SESSION_FINDER_STATE`); stays; no launch records are written any more |
| `bin/ade_claims.py:431,1480,1854,2025` | reworded by this slice (D3) |
| `skills/session-handoff/SKILL.md:137,179` | reworded by this slice (D9), the shim path is live |
| `skills/session-handoff/SKILL.md:202,227` | exemption B reads old `launch.py` failure lines from `self-slash.log`: E4 (self-slash) / D3 |
| `skills/ade-paseo-handoff/SKILL.md:71,116,121` | reworded by this slice (D10), the shim path |
| `skills/handoff/SKILL.md:323` | reworded by this slice (D8) |
| `skills/handoff/SKILL.md:388` | `self-slash --finish --successor` on herdr runs `launch.py successor`: **E4** (self-slash); that herdr branch is dead now that launch.py is gone |
| `skills/baton/SKILL.md:36` | reworded by this slice (D8) |
| `skills/helm/SKILL.md` (9), `skills/helm/lead.md` (7), `skills/helm/helm.py` (7: `import fleet`, `LAUNCH = .../launch.py`), `docs/helm.md` (6) | **E4** (helm REPLACE). `helm.py` still imports `fleet` (fine until E3b) and builds `launch.py` argv (dead now) |
| `skills/loadwatch/SKILL.md:40,169,175` | **E5** |
| `launchd/com.djbclark.session-history-update.plist:3,18` | **E5** (R2-4: the plist, and the installed LaunchAgent in the Wave 3 operator batch; it now points at a deleted script) |
| `skills/oc-go-key/SKILL.md:97,102` | **E9 / Wave 3b** (relay.py positional call still works with the shim; `fleet.py` until E3b) |
| `skills/ralph-tui-orchestration/SKILL.md:272` | **E2** (DELETE) |
| `skills/bigteam/SKILL.md:86,491,862` | **E6** (bigteam DELETE); :862 runs the old `claude_identity.py` path, which the stub serves for the cycle |
| `skills/todo/SKILL.md:67,70` | **E1** (todo MOVE): it runs the deleted `session-history.py`; reword or drop the step when it moves |
| `docs/skills.md:40,59,63` | merger's (E1 below) |
| `docs/skill-everywhere.md:79,134-135` | :134-135 reworded by this slice (D14); :79 is a general zcode note, not a path |
| `docs/threat-model.md:100,144`, `docs/dispatch-footer.md:16`, `docs/agent-guard-contract.md:39` | reworded by this slice (D11-D13), shim path or a dated deletion note |
| `tools/acp-run/README.md:336`, `tools/acp-run/acp-run:503` | **E6** (acp-run): explains why the marker is not named `ACP_RUN` (launch.py held it); history, harmless |
| `docs/paseo-only-rearchitecture.md` (6) | plan of record, a dated record of the plan; **E11** |
| `docs/tui-lessons-learned.md` (6) | dated evidence (KEEP, E11, B12a); describes what happened, no live instruction |
| `docs/ade-everywhere-*` (21 lines in 5 files), `docs/software-factory-research-digest-2026-10-19.md`, `docs/paseo-plugins-scan-2026-10-19.md`, `docs/apply-toolchain-prompt.md` | MOVE to `docs/history/` (**E2/E11**, E1), exempt there |
| `bin/self-slash:69,75,414,636,645,739,798-882,1406-1411` (extensionless) | **E4**: loads the old relay.py as a module (`pane_transcript`, `_ts`) for its codex receipt, which the shim no longer has, and runs launch.py for the herdr successor. Both paths are herdr/codex-pane only (retired); the Paseo path does not use them. Tests still pass (H) |
| `bin/rumination-watch:26,762-1075` (extensionless) | **E5** (DELETE): calls the shim with `--no-ack --json` and `--why`, all refused now (exit 64) |
| `bin/session-load-watch:21` | **E5** (DELETE); its positional call works with the shim |
| `bin/load-watch:32,49,562,622-661,2170` | :562, :640-661 edited by this slice (D4); the docstrings at :32, :49, :622 and the `--relay` flag text at :2170 are **E5**'s rewrite |
| `bin/context-watch:74` | **E5** (fleet.py path until E5) |
| `bin/skill-everywhere:266` | comment naming `/session-finder` among native skill slashes: **E10** |
| `bin/instruction-lint:28-29,70` | D13 retired-term list: prune `relay.py` after Wave 6 |
| `config/launchd/com.djbclark.deadline-sweep.plist:4` | reworded by this slice (D6) |
| `docs/orchestration-practices.md:133,148` | reworded by this slice (D7) |
| `skills/model-routing/SKILL.md:983` | dated history of a fixed relay.py bug; leave |
| `agents/claude/settings.json.tmpl:508` | merger's (E2 below) |
| `tests/fixtures/context-now.txt` | fixture text, not a path read by code |

B2. Brief 3b listed `where.py` and `nested_pty.py` for deletion; they are **kept for E3b** and deleted with `fleet.py`:
`fleet.py:48` imports `nested_pty` unguarded (deleting it breaks `import fleet`, which `bin/load-watch:266` runs on its
hot path), and `fleet.py:45` imports `where`, whose `paseo_agent` (`fleet.py:747-753`) is how `fleet.sessions()` finds
the Paseo agents load-watch attributes load to. `tests/test_nested_pty.py` (it imports `fleet` and `nested_pty`) is
kept for E3b with them. `nativeid.py` and `jsonl_session.py` did go: the only remaining importer was one case in
`tests/test_fleet_pi.py` (`test_native_transcript_ids_preserve_underscores`), which tested `nativeid` itself and was
removed from that file (the file stays for E3b).

B3. `claude_identity.py` imports nothing from session-finder (stdlib only), so `nativeid.py` was not moved (2a).

## C. Deleted

C1. 52 files, 22,446 lines (`git diff --numstat --diff-filter=D 7762c1e HEAD`), plus 4,874 lines of the old relay.py
replaced by the 166-line shim and 146 lines of claude_identity.py moved (the stub is 5). Whole diff against 7762c1e:
78 files, +692 / -23,320 before this report.

C2. Code and skills (5,071 lines): `skills/session-finder/SKILL.md` 639, `launch.py` 1,105, `session-history.py` 454
(R2-4), `session-find.py` 308, `nativeid.py` 49, `jsonl_session.py` 67, `adapters/` 18 files 1,369 (README 73, agy
113, claude 82, cline 63, codex 62, copilot 69, crush 120, cursor 100, goose 57, grok 87, hermes 48, muse 80, omp 128,
opencode 49, pi 77, qwen 36, todo 84, zcode 41); `skills/peer-relay/SKILL.md` 118; `claude/hooks/relay_prose_nudge.py`
335; `claude/commands/session-finder-all.md` 10; `zcode/commands/session-finder.md` 9 and
`zcode/commands/session-finder-all.md` 11 (the zcode twins of the claude wrapper: their only subject is the deleted
skill; zcode/commands is E9's DECIDE row, so a delete/delete there merges cleanly).

C3. Tests (23 files, 13,375 lines): `test_relay_fallback.py` 4,178, `test_relay_verified.py` 2,099,
`test_relay_paseo.py` 1,121, `test_relay_status.py` 828, `test_relay_prose_nudge.py` 801,
`test_session_history_adapters.py` 676, `test_relay_sender_header.py` 596, `test_relay_card_alert.py` 393,
`test_session_relay.py` 367, `test_launch_turns.py` 303, `test_pi_history_identity.py` 284, `test_relay_retire.py`
261, `test_omp_history_hygiene.py` 248 (subject: session-history.py's omp adapter), `test_relay_requeue.py` 246,
`test_launch_successor.py` 238, `test_launch_dispatch.py` 192, `test_relay_refuse_unknown.py` 184,
`test_launch_orca_close.py` 153, `test_relay_message_file.py` 130, `test_relay_omp_hygiene.py` 120,
`test_launch_model.py` 100, `test_relay_watchers_no_ack.py` 56, `test_zz_relay_real_state_untouched.py` 32.
`test_pi_history_identity.py` is the ledger's E9 row, but every subject it loads (`session-history.py`,
`adapters/pi.py`, `session-find.py`, `nativeid.py`) went here. `test_relay_watchers_no_ack.py`'s subject is the
watchers' `--no-ack` flag against the old relay's delivery watch: that contract is retired (the shim refuses
`--no-ack`), and load-watch's relay argv stays pinned in `tests/test_load_watch.py`.

C4. Test cases removed from KEEP test files (their subjects went): `tests/test_codex_shell_env_policy.py`
`test_a_relay_deliverer_has_no_owner_id_in_its_tools` (the old relay's `deliverer_env`); `tests/test_fleet_pi.py`
`test_native_transcript_ids_preserve_underscores` (nativeid); `tests/test_fleet_paseo_rows.py` two cases that called
the old relay (H3b); `tests/test_claude_identity.py` the fleet/relay halves (see D2). `tests/test_rumination_watch_target.py`
one case marked xfail for E5 (H3b).

## D. Edits in KEEP files

D1. `bin/claude_identity.py` (moved, `git mv`; docstring :2 names its importers). Stub at
`skills/session-finder/claude_identity.py`, 5 lines: it loads `bin/claude_identity.py` with importlib and replaces its
own `sys.modules` entry, and runs `owner_session_id()` when executed. Deviation from 2a, flagged: the brief's
`sys.path.insert(bin/); from claude_identity import *` does not work, because on an old sys.path the stub IS the module
`claude_identity`, already in `sys.modules`, so the star import would copy nothing from itself.

D2. Importers: `bin/acp-dispatch:836`, `bin/ade_claims.py:427,431` (bin/ path; no session-finder path),
`skills/autorename/autorename.py:94-95,122-123`; `skills/handoff/SKILL.md:90` and `skills/baton/SKILL.md:90-91` run
`bin/claude_identity.py` and print an error instead of `|| echo $CLAUDE_CODE_SESSION_ID` (C5/I5). Note: the helper's
`owner_session_id()` itself still falls back to `CLAUDE_CODE_SESSION_ID` when no registry entry matches, so the `||`
only fired when both were empty; the stale-id case the brief names is the helper's, not the `||`'s (C5 known bug,
not fixed here). `tests/test_claude_identity.py` gets its own harness (the old one came from
`test_relay_fallback.py` and `test_relay_sender_header.py`, both deleted), keeps every resolver, ade_claims and
autorename case, runs the script at both paths and adds `test_the_old_path_stub_imports_the_moved_module`; the
fleet/relay assertions and the `TestThePaneCaseStillHolds` subclass went with their subjects (13 tests pass).

D3. `bin/ade_claims.py:1480,1854,2025`: "Ask the owner (a Paseo agent) with `skills/session-finder/relay.py OWNER
--message-file -`" (the word `relay.py` stays: `tests/test_ade_git_guard.py:179` and `tests/test_ade_git_hooks.py:200`
assert it).

D4. `bin/load-watch:559-563` (incident brief) and `:639-643,661` (`send_to`'s relay channel): `--no-defer --no-ack`
dropped (the shim refuses both, exit 64); the `defer` argument no longer changes the relay argv. `tests/test_load_watch.py`
:583, :586-591, :607 pin the new argv. This is E5's file: the edit is three lines so E5's rewrite merges over it.
**For E5, found in passing:** `send_to`'s own Paseo channel (`bin/load-watch:653-668`) runs `paseo send --no-wait --json`
and reads `returncode == 0` as delivered, which research item 1 says is wrong (`queued` also exits 0). E5's rewrite
should read `.status` the way the shim does.

D5. `bin/deadline:417-418,451-458` and `docs/deadline.md:178-181`, `tests/test_deadline.py:563,633-641` (A7).

D6. `config/launchd/com.djbclark.deadline-sweep.plist:4` comment: the sender label now feeds the shim's prefix (the old
"relay.py refuses exit 4" is gone).

D7. `docs/orchestration-practices.md:133-135,146-150`: the deferral and card-alert sentences now describe Paseo's queue
and the shim's `queued`/`permission` statuses.

D8. `skills/handoff/SKILL.md:323-325` and `skills/baton/SKILL.md:36`: `launch.py` named as deleted.

D9. `skills/session-handoff/SKILL.md:136-180` (the trusted-tools paragraph and steps 2, 3 and 5) and `:206-207`: the owner check reads
`paseo ls -a -g --json` (match on `id`/`shortId`/`id` prefix, `provider` fits `writer`, live = not `closed` and not
`Archived` from `paseo agent inspect`, you = the row of your own `$PASEO_AGENT_ID`); a herdr pane, claude transcript
uuid or free text matches no row and falls to step 4's fail-closed ask; step 5 sends with
`relay.py <row id> --message-file - --ack <your id>`. Exemption B's herdr/`launch.py` log-line rules (:195-227) are left
for E4/D3.

D10. `skills/ade-paseo-handoff/SKILL.md:71,101` (peer-relay → the shim) and the section "Peer notices belong to the
successor" (:106-125, was :104-136): no transfer, pending or sweep step; the retiring session sends the successor the
handoff text with the shim (`--message-file BRIEF --ack <own id> --wait S`, which is `paseo send` then `paseo wait`)
and reads its named ack; the successor re-asks peers for open tokens. Minimal, since R2-2 replaces the skill in Wave 3b.

D11. `docs/threat-model.md:99-104,143-150`: the shim's route, its `--prompt-file`, its two refusals (A4).

D12. `docs/dispatch-footer.md:16` (item 14): the relay path is a Paseo agent's.

D13. `docs/agent-guard-contract.md:39-40`: `launch.py` named as deleted.

D14. `docs/skill-everywhere.md:132-135`: `/session-finder` and `/session-finder-all` removed from the Hermes
skill-slash lists.

D15. `tests/conftest.py:72-78`: the old relay's `RELAY_DEFER_DIR` queue setup and `REAL_RELAY_DIR` went; the
`RELAY_LINKS_FILE` scrub stays (fleet.py reads it) and goes with fleet.py in E3b.

## E. The merger's lines

E1. `README.md:44` (the `session-finder` link to the deleted SKILL.md), `:51-52` (`session-finder/launch.py`),
`:83` (drop `/session-finder-all` from the `claude/commands/` row), `:86` (the `relay_prose_nudge.py` row: delete),
`:112` (`session-finder` skill row: delete, or one line "relay shim and fleet.py until 2026-11-20"), `:126` (`peer-relay`
row: delete), `:173` (`helm.py imports fleet`: E4). `docs/skills.md:40` (drop `/session-finder-all`), `:59`
(`peer-relay` row: delete), `:63` (`session-finder` row: delete). AGENTS.md:25 (the retirement box lists
`skills/session-finder` `relay.py`, `launch.py --host`: launch.py is gone) and :121, :123-125 (order 10, G below) are
E11's.

E2. `agents/claude/settings.json.tmpl:504-512`: the whole hook object whose one command is
`"$HOME"/ops/site-private/bin/hook-deadline 2 "$HOME"/src/djbclark-ade/claude/hooks/relay_prose_nudge.py` (delete the
object, keeping the array's commas valid). It points at a deleted file now.

E3. `.github/workflows/test.yml` names none of the deleted tests (checked). A `changelog.d/<branch>.md` fragment was
not written (its file name is the merged branch's); suggested lines: `### Changed` "relay.py is a one-cycle shim over
`paseo send --json` (exit 0 delivered, 2 not delivered, 1 paseo failed, 3 not a Paseo agent, 64 usage); herdr, Orca,
dispatch and launch routes, the outbox and expected-ack ledger are gone, removed by 2026-11-20"; `### Changed`
"`claude_identity.py` moved to `bin/` (a stub at the old path for one cycle)"; `### Removed` "session-finder's
`launch.py`, `session-find.py`, `session-history.py`, adapters and SKILL.md, the `peer-relay` skill, the
`relay_prose_nudge.py` Stop hook and the `/session-finder-all` wrappers".

## F. Operator steps

F1. C2 hook line: remove the `relay_prose_nudge.py` hook entry from the live `~/.claude/settings.json` (the same
object as E2) before the final merge; once merged it would run a missing file on every Stop. Also unlink
`~/.claude/commands/session-finder-all.md` and the `~/.claude/skills/session-finder` and `~/.claude/skills/peer-relay`
links if `skill-everywhere` does not (it reports a linked directory without SKILL.md as "copy of a removed skill"), and
`~/.zcode/commands/session-finder{,-all}.md` if installed.

F2. R2-4 (with E5): `launchctl bootout gui/$UID/com.djbclark.session-history-update` (the plist's script is deleted).

F3. C3 per-file list. tendcf, nix2cf, Plektra, paseo4herdr, sudo-secretspec, aiuse and paseo-runner are **not in this
container** (`~/src` does not exist here), so their exact lines could not be read; the check-in record (I4a, I4d, I4e,
I4g) names only which tools each uses. The lead runs, per repo:
`grep -rn 'relay\.py' ~/src/REPO --include='*' | grep -v '/\.git/'`, and maps each hit by its flags:

| Today | Replacement |
|---|---|
| `relay.py ID "text"` (positional) | unchanged; exit 0 now means `sent`/`completed`, and a `queued` send is exit 2, not 0 |
| `... --message-file PATH\|-` | unchanged |
| `... --ack` (bare) | unchanged (no-op) or drop it |
| `... --wait S` | drop it unless the caller wants "delivered and then idle"; it now waits for idle, not for delivery |
| `... --no-ack`, `--no-defer`, `--idle S`, `--steer`, `--json`, `--plan`, `--defer-for S` | drop the flag (each is exit 64 now); a `--json` reader parses nothing: read the exit code and the one status line |
| `... --via ROUTE`, a herdr pane `wN:pM`, a dispatch record path, a session id that is not a Paseo agent id | no replacement: herdr and Orca panes are retired; for an `acp-dispatch` slice use `acp-dispatch tell RECORD` |
| `relay.py --pending`, `--sweep`, `--retire`, `--transfer-expectations`, `--expect-ack`, `--status`, `--cancel`, `--why` | none; `paseo permit ls --json` for pending cards, `paseo agent inspect ID --json` for a target's state |

F4. One outside consumer **was** readable here, `djbclark/site-djbclark` at d2176af (cloned at `/home/user/site-djbclark`;
fleet-watch's home, which C3 called unverified): it breaks on the shim and needs its own edit before the shim is live.
(a) `bin/fleet-watch:1417` runs `relay.py --sweep` and `:1423` `relay.py --pending --json` on every five-minute check
(both exit 64 now); replacement: drop the ack-sweep block (`:1305-1466`), or read `paseo permit ls --json` instead.
(b) `bin/fleet-watch:1033` and `:1080` run `"$UPSTREAM_RELAY" "$target" "$text" --no-ack` (exit 64 now); replacement:
`"$UPSTREAM_RELAY" "$target" "$text"`, and read exit 2 (`queued`) as "accepted, not yet delivered" rather than
"refused", or the event stays pending and is relayed again. (c) `:212` comment (exit 4) is stale. (d) its tests
`tests/test_fleet_watch_ack.py:19-29` and `tests/test_fleet_watch_upstream.py:76,116,411` stub the old flags.
(e) `home-agents.md:52` and `cursor/home-agents.mdc:41` describe relay.py as the router with fallbacks: reword with G.
`roles/site_agents/README.md:21-26,59` describes the sweep. Order 11: these are proposals for the operator or the lead
(J2b covers the five C3 repos; site-djbclark is not named there).

## G. Standing order 10, the rewrite (AGENTS.md is E11's)

G1. Text for E11 (the review's F1 ruling): "A message is sent with the relay shim (`skills/session-finder/relay.py`, until
2026-11-20) or `paseo send --json`. A sourceless send (deadline, load-watch) is delivered when `.status` reads `sent` or
`completed` (exit 0); an agent's send is accepted (exit 5, queued by the daemon) and proven only by the peer's `ack <id>`;
exit 2 is not delivered; never `$?`." Paseo 0.15.3 queues every agent-to-agent message and reports no later delivery
(A5), so for an agent the named ack is the only proof. PLAN.md E3's draft ("a message is sent with `paseo send` and its
exit status read") is wrong for `paseo send`, which exits 0 for every status.

G2. The rest of order 10 carries over: every message from an agent that needs to be known delivered asks for a named ack
(`--ack <your id>` appends the request), the ack is verified by reading your own inbox, and a peer that does not ack is
reported to the operator, never assumed read. Nothing records an expectation any more.

## H. Tests

H1. `bin/pytest -q tests/test_relay_shim.py`: 40 passed at 99a7ccb; after the A3 ruling, 44; after the review repair,
86; with `tests/test_deadline.py tests/test_deadline_wrappers.py`: 201 passed, 2 failed, both baseline
(`test_deadline_wrappers.py::...[dispatch]`, `ggrep: command not found`). The repair's tests: the fake `paseo` answers
`queued` to every send whose environment carries `PASEO_AGENT_ID` and `sent` otherwise, as 0.15.3's daemon does; an
agent's send is exit 5 with the accepted text and `--wait` after it reports `target ...` with exit 5; a sourceless
`queued` is 2; inspect answers `{}`, `[]`, a list, a nested object, a string, null, a wrong `Id`, `Archived` true, null or
`"false"`, `PendingPermissions` non-empty or null, `Status` error, initializing, closed or null, and a failed inspect are
all exit 2 with no send; a running agent on claude, codex, opencode, omp, pi is sent, on cline, grok, kiro, copilot or no
provider is "busy, not sent", and a `Capabilities` steer key wins; no sender or a label that sanitises to nothing is 4
with no `paseo` call, and a hostile label is cut to the safe set and 64 characters; non-UTF-8 file and stdin are 64;
`--wait` nan, inf, -inf, -1, -0.5 are 64; leading `/` after U+3000, U+2028, U+00A0, U+2003, U+180E, U+2060, U+205F is 64;
`--help` names every exit code and no longer says "quiet for 2 s". The list below is the first version's. It covers: `sent`/`completed` → 0 `delivered` with
`--behavior steer`, `--no-wait`, `--json` and the `[relay from ...]` prefix; `queued` → 2 and no `wait`; `timeout`,
`permission`, `error` → 2; `paseo` exit 1, unparseable JSON, failing `ls` → 1; no `paseo` on PATH → 1; four non-Paseo
targets (a herdr pane, a name, a dispatch record path, `self` unset) → 3 with the retirement text; an ambiguous shortId
prefix → 3; the id and 8-, 6- and 5-character shortId prefixes resolve; a name (`lead`, `twin`) → 3 with "pass the id";
a 12-character id prefix and a 3-character prefix → 3; `self` = `$PASEO_AGENT_ID` with no prefix; `RELAY_SENDER_NAME`
in the prefix; `--wait` → `paseo wait ID --timeout S --json` (`idle` 0, `timeout` 2, `permission` 2, failure 1);
`--message-file -` reads stdin exactly and a file works; `--ack NAME` and bare `--ack`; the five outbox flags (also
`--flag=value`) and `--via` refused 64 before any `paseo` call; usage errors 64; a leading `/` (four forms) refused
64; an archived or card-blocked target refused 2 before `send`, a failing inspect 1; `--help` lists exactly `-h`,
`--message-file`, `--ack`, `--wait` and names the retired flags only in the epilog; the I1 date test
`test_the_shim_is_removed_by_2026_11_20` (`date.today() <= date(2026, 11, 20)`, and line 2 of the shim names the date).

H2. Targeted run (the brief's list plus every KEEP test this slice edited: `test_relay_shim`, `test_claude_identity`,
`test_ade_claims_quote`, `test_ade_git_guard`, `test_acp_dispatch_identity`, `test_context_watch`, `test_load_watch`,
`test_fleet_pi`, `test_codex_shell_env_policy`, `test_nested_pty`): 715 passed, 10 failed, 10 skipped; the 10 are
`test_ade_git_guard.py::test_reset_by_creation_cannot_overwrite_a_claimed_branch[*]`, all baseline rows.
`tests/test_deadline.py tests/test_deadline_wrappers.py`: 115 passed, 2 failed, both baseline
(`test_deadline_wrappers.py::...[dispatch]`, `ggrep: command not found`).

H3. Full suite, run exactly as `docs/slim/baseline.md` ran it (`uv run --with pytest --with pytest-timeout --with pyyaml
--with 'agent-client-protocol>=0.9,<1.0' python -m pytest tests/ -q --timeout=120`):

H3a. Result at 4fb10d1: **166 failed, 9,402 passed, 53 skipped, 1 error, 1,985 subtests passed, 2,817 s**, rc=1 (the
baseline: 166 failed, 10,141 passed, 54 skipped). Compared by test id with the baseline's failure list: three new
failures, three baseline failures gone (they were in deleted files: `test_launch_turns.py` 1, `test_session_relay.py` 2).
The one error is a teardown error of `test_self_slash_codex.py::CodexWaiterTests::test_an_identical_older_message_in_a_session_that_appears_after_the_submit_is_not_a_receipt`,
a baseline failure (the file fails 12 in the baseline). The passed count falls by the 23 deleted test files.

H3b. The three new failures, fixed in the report's commit and rerun (`bin/pytest -q tests/test_fleet_paseo_rows.py
tests/test_rumination_watch_target.py`: 93 passed, 1 xfailed):
- `tests/test_fleet_paseo_rows.py::test_relay_refuses_a_paseo_agent_with_a_pending_card_and_names_the_paseo_ui` and
  `::test_a_paseo_agent_with_no_claude_row_is_not_found_by_its_workspace_title` imported the old relay.py
  (`relay.hard_stop`, `relay.find`). Their subject went, so the two cases were removed from the file (the file stays
  for E3b). The second one carries a finding (adversary L3, 2026-10-2x): a Paseo agent's title comes from its first
  prompt (`/baton`, "say hi"), so the old relay never resolved an agent by title. The brief (1a) asks the shim to
  resolve by `name`; the first version did. Lead's ruling (2026-11-06): drop it, id or unique shortId prefix only (A3).
- `tests/test_rumination_watch_target.py::test_the_relay_send_contract_this_reads_still_exists` reads relay.py's
  source for the send parser's `--json` and the `result`/`state: queued` report fields, which the shim does not have:
  a true signal that `bin/rumination-watch` breaks on the shim (it also passes `--no-ack` and `--why`, exit 64). Marked
  `xfail(strict=True)` with the reason "rumination-watch ... is deleted in E5 (merge E5 before or with E3)", so it
  fails loudly if it ever passes again; E5 deletes the file with rumination-watch.

H3c. Baseline rows to drop (deleted test files): `tests/test_launch_turns.py` (1) and `tests/test_session_relay.py` (2).

## I. Lost on purpose

I1. herdr and Orca pane routes (and tmux, the Claude socket route, the Hermes route, the dispatch and launch routes):
the shim reaches Paseo agents only; anything else is exit 3.
I2. The outbox and expectations ledger: deferred sends (`--pending`, `--sweep`, `--status`, `--cancel`, the deliverer,
the card alert), expected acks (`--expect-ack`, `--retire`, `--transfer-expectations`, OVERDUE/ASSUMED LOST): Paseo
queues for 2 quiet seconds itself and has no outbox to list.
I3. `--via` and route fallback: one route, no fallback.
I4. The prose nudge (`relay_prose_nudge.py`): no Stop hook reminds an agent that a reply written in prose did not reach
the relaying peer.
I5. session-finder's search half (live and ended sessions by topic, the FTS5 history index and its 17 adapters,
`session-find.py`, `/session-finder`, `/session-finder-all`) and `launch.py` (ACP launches with an inbox); `paseo ls`
is the live list.
I6. The old relay's delivery witness (a transcript showing the text upgraded "accepted" to "delivered"): the shim
trusts Paseo's `sent`.
I7. Sending into a running turn of a provider that cannot steer (review F3): the shim refuses it, exit 2 "busy, not
sent (provider cannot steer)", where Paseo would replace the turn; send again when the agent is idle. A steer-capable
provider can still decline one steer at runtime, and then Paseo replaces its turn (A4c).
I8. Delivery proof for an agent's message: Paseo queues every agent-to-agent message and reports no later delivery, so an
agent's send is exit 5, accepted, and only the peer's `ack <id>` proves it (A5, G1).

## J. Review notes (E3 review, 2026-11-06)

J1. F7 (lost unit tests for `where.py` and `fleet.py` internals): the deleted relay tests (`test_relay_paseo.py`,
`test_session_relay.py`, the two `test_fleet_paseo_rows.py` cases, H3b) also exercised `where.paseo_agent` and fleet rows.
Accepted: E3b deletes `fleet.py`, `where.py` and `nested_pty.py` next, after E5; until then `tests/test_fleet_*.py` and
`tests/test_nested_pty.py` still cover what load-watch's hot path imports.
J2. F8 (load-watch's notify target): `notify` sends to `s.get("sid") or s["id"]` from `fleet.sessions()`, which for a
non-Paseo Claude session is a session id the shim cannot resolve (exit 3, "could not reach it", and the fixer line runs).
E5's rewrite of load-watch's attribution to `paseo ls -a -g --json` supersedes this call; this slice only put its flags on
the shim's set (D4). load-watch runs from launchd with no `$PASEO_AGENT_ID`, so its sends are sourceless (exit 0 on `sent`).
J3. F9 (`ade-paseo-handoff` step 2): the retiring session's brief to its successor is an agent's send, so it now expects
exit 5, accepted, and waits for the successor's named `ack <own id>`; `--wait` only says the successor went idle
(`skills/ade-paseo-handoff/SKILL.md:116-120`). The same holds for its peer notices (:71, :101-102) and for
`skills/session-handoff/SKILL.md:178-180`.
