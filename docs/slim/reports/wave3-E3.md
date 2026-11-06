# Wave 3 report E3 (S-finder): the relay shim, claude_identity to bin/, session-finder internals deleted

Writer: one Claude agent, 2026-11-06, in worktree `/home/user/djbclark-ade/.claude/worktrees/agent-a4772e28ffb7daa78`,
branch `worktree-agent-a4772e28ffb7daa78`, based on `claude/determined-maxwell-uvddaz` at 7762c1e (fast-forwarded from
master fb3b9de first, so the brief and this report sit beside each other). Brief: `docs/slim/briefs/wave3-E3-finder.md`.
Not pushed (the lead merges). No Paseo daemon was run: every `paseo` call in the tests is a fake on PATH.

Commits: 3bfeb5a (claude_identity move), 5f8a4a6 (the shim, deadline), 4fb10d1 (deletions, KEEP-file edits), and the
commit that adds this report. Not done here, on purpose: E3b (`fleet.py`, `tests/test_fleet_*.py`), `prompt_line.py`
(E4), AGENTS.md, README.md, docs/skills.md, CHANGELOG.md, docs/queue.md, the settings template.

## A. The shim

A1. `skills/session-finder/relay.py`, 166 lines, stdlib only (the brief said about 100; the extra lines are A4's two
refusals and the help epilog). Line 2 carries the removal line, "Shim, removed in the follow-up PR after one live cycle
(PLAN.md F, Wave 6; at the latest 2026-11-20)".

A2. Flow: refuse a retired flag (before argparse) → read the text (positional or `--message-file`, `-` = stdin, UTF-8,
BOM dropped, one trailing newline dropped, nothing else changed) → refuse a leading `/` → append the `--ack NAME` line →
prefix `[relay from $RELAY_SENDER_NAME]` when the caller has no `$PASEO_AGENT_ID` → `paseo ls -a -g --json` → resolve →
`paseo agent inspect ID --json` → write the text to a private temp file → `paseo send ID --prompt-file F --behavior
steer --no-wait --json` → read `.status` → with `--wait S`, `paseo wait ID --timeout S --json` → read `.status`.

A3. Resolution order (first rule with any hit wins; more than one hit is exit 3 "matches N Paseo agents (ids)"):
exact `id` or `shortId`; exact `name`; a prefix of 4+ characters of `id` or `shortId`. `self` is `$PASEO_AGENT_ID`
(unset: not a Paseo agent, exit 3).

A4. Two additions to the brief's 1b, both kept from the old relay's Paseo route because `docs/threat-model.md` relies on
them (standing order 6: flagged here): (a) a text that starts with `/` or the full-width slash after the whitespace and
zero-width characters Paseo trims is refused (exit 64), since it would run a built-in in the target; (b) before the
send, `paseo agent inspect` must not show `Archived` or a non-empty `PendingPermissions`: a send answers a pending card
and unarchives an archived agent (exit 2, "not sent"). Two deviations from 1b's exact argv: `--behavior steer`
(without `$PASEO_AGENT_ID`, as for `deadline` and every launchd caller, Paseo's default is interrupt, which cancels the
target's running turn; the old relay passed steer too) and `--prompt-file` (no message text in `ps`, and a text starting
with `-` is never read as an option). The inspect field names (`Archived`, `PendingPermissions`) are from the Wave 3
research (item 2), not from a live daemon: verify them in the first live cycle.

A5. Status mapping. `paseo send` exits 0 for every status (research item 1), so `$?` is never read as delivery:

| `paseo` result | shim prints | exit |
|---|---|---|
| send `.status` `sent` or `completed` | `delivered` | 0 (then `--wait`, if given) |
| send `.status` `queued` | `queued (accepted by the daemon, not yet delivered: the target has not been quiet for 2 s)` | 2 |
| send `.status` `timeout`, `permission`, `error`, or anything else / none | the status word (`no status`) | 2 |
| inspect: archived, or a pending permission or question | `not sent: ... archived ...` / `permission (not sent: ...)` | 2 |
| wait `.status` `idle` | `idle` | 0 |
| wait `.status` `timeout` | `wait timed out after S s` | 2 |
| wait `.status` `permission` | `permission (pending: `paseo permit ls`)` | 2 |
| any `paseo` non-zero exit, no binary, unparseable JSON, no answer in time (ls 30 s, inspect 30 s, send 60 s, wait S+30 s) | the stderr, on stderr | 1 |
| target not exactly one Paseo agent | `relay.py reaches Paseo agents only since 2026-11-06 (herdr and Orca panes retired 2026-10-31); target X is not a Paseo agent` | 3 |
| usage error, leading `/`, `--via`, `--pending`/`--sweep`/`--retire`/`--transfer-expectations`/`--expect-ack` | the refusal | 64 |

Usage errors are 64, not argparse's 2, so a typo is never read as "not delivered". `--ack` takes an optional NAME:
with one it appends "Reply with `ack NAME` through relay.py." to the text; bare (as `bin/deadline` used to pass it) it
appends nothing, since delivery is always read from the status. A bare `--ack` must follow MESSAGE (argparse would read
the text as NAME otherwise; the help says so).

A6. `--help` as committed:

```
usage: relay.py [-h] [--message-file PATH] [--ack [NAME]] [--wait S]
                TARGET [MESSAGE]

Send MESSAGE to one Paseo agent with `paseo send --no-wait --json` and report its delivery status.

positional arguments:
  TARGET               Paseo agent id, id/shortId prefix, name, or `self`
  MESSAGE              the text (exactly one of MESSAGE and --message-file)

options:
  -h, --help           show this help message and exit
  --message-file PATH  read the text from PATH, UTF-8 (`-`: stdin); for text
                       with backticks, `$` or quotes
  --ack [NAME]         append "Reply with `ack NAME` through relay.py" to the
                       text; bare --ack appends nothing (delivery is always
                       read from the status); put MESSAGE before a bare --ack
  --wait S             after a delivered send, `paseo wait TARGET --timeout
                       S`: exit 0 only when it reads idle

exit status:
  0   delivered: `paseo send --json` read `sent` or `completed` (with --wait: and `paseo wait` then read `idle`)
  1   paseo failed: not installed, exited non-zero (no daemon, unknown agent), gave no JSON, or did not answer in time
  2   not delivered: `queued` (accepted by the daemon, not yet delivered), `timeout`, `permission`, `error`; or --wait timed out or hit a permission;
      or not sent, because `paseo agent inspect` shows the target archived or with a pending permission or question card
  3   TARGET is not exactly one Paseo agent (relay.py reaches Paseo agents only since 2026-11-06 (herdr and Orca panes retired 2026-10-31))
  64  usage error, a text starting with `/` (it would run a built-in in the target), or a retired flag: --via (relay.py reaches Paseo agents only since 2026-11-06 (herdr and Orca panes retired 2026-10-31)); --pending, --sweep, --retire, --transfer-expectations, --expect-ack (retired 2026-11-06: Paseo has no outbox; see `paseo permit ls` for pending permissions)
TARGET is a Paseo agent id, a prefix of its id or shortId, its name (title), or `self` ($PASEO_AGENT_ID), as `paseo ls -a -g --json` lists it.
A sender with no $PASEO_AGENT_ID (a launchd job) is named in a `[relay from NAME]` prefix, NAME from $RELAY_SENDER_NAME.
Shim: removed in the follow-up PR after one live cycle, at the latest 2026-11-20.
```

A7. `bin/deadline` (1f): its owner notice passed `--message-file - --ack --wait 20`. All three are in the shim's set, but
`--wait 20` changed meaning (old: verify delivery for 20 s; shim: wait for the owner to go idle), so a busy owner would
read as "not delivered" and the notice would be sent again up to `NOTICE_TRIES` (5) times. The call is now
`relay.py OWNER --message-file -` (`bin/deadline:458`; docstring :451-456 states the new exit codes); `docs/deadline.md`
item 3 and `tests/test_deadline.py` follow. Residual risk, flagged: a `queued` notice (exit 2) is retried and so may
arrive twice once Paseo delivers the first copy. `deadline`'s `clean_env` still strips `PASEO_AGENT_ID`, so the notice
carries `[relay from deadline-sweep]`.

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
`test_native_transcript_ids_preserve_underscores` (nativeid); `tests/test_claude_identity.py` the fleet/relay halves
(see D2).

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

G1. Text for E11: "A message is sent with `paseo send --json` (or the relay shim, `skills/session-finder/relay.py`,
until 2026-11-20); it is delivered when `.status` reads `sent` or `completed`; `queued` is accepted, not delivered; a
timeout or a pending permission also exits 0 and is read from `.status`, never from `$?`." The shim's exit codes say
the same (0 delivered, 2 not delivered), so a caller of the shim may read its `$?`; a caller of `paseo send` may not.
PLAN.md E3's draft ("a message is sent with `paseo send` and its exit status read") is wrong for `paseo send`, as
research item 1 says.

G2. The rest of order 10 carries over: the first message to a new peer asks for a named ack (`--ack <your id>` appends
the request), and the ack is verified by reading your own inbox; nothing records an expectation any more.

## H. Tests

H1. `bin/pytest -q tests/test_relay_shim.py`: 40 passed. It covers: `sent`/`completed` → 0 `delivered` with
`--behavior steer`, `--no-wait`, `--json` and the `[relay from ...]` prefix; `queued` → 2 and no `wait`; `timeout`,
`permission`, `error` → 2; `paseo` exit 1, unparseable JSON, failing `ls` → 1; no `paseo` on PATH → 1; four non-Paseo
targets (a herdr pane, a name, a dispatch record path, `self` unset) → 3 with the retirement text; ambiguous name and
prefix → 3; id, shortId, 12-char prefix, name resolve; `self` = `$PASEO_AGENT_ID` with no prefix; `RELAY_SENDER_NAME`
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

SUITE_RESULT_PLACEHOLDER

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
