# Wave 3 E5 (S-watch) report, 2026-11-06

Writer: one Claude agent (Opus 5.5) in its own worktree, branch `worktree-agent-af59a42109b4c5868`, based on
`claude/determined-maxwell-uvddaz` at 7762c1e (fast-forwarded from master fb3b9de, docs-only). Nothing pushed. Commits:
5a03c40 (deletions), eecadc3 (load-watch), 9e4f56d (context-watch), a4b3063 (context-budget-check), 1e98908 (a doc
reference), and this report; then one review-repair commit (walk stops at the agent CLI, archived agents out, the
`loose` notice, `completed` delivered, per-row cwd errors, `status` expiries). Brief: `docs/slim/briefs/wave3-E5-watch.md`.

Places where this slice departs from the brief or from a ruling, each argued below: **A7** (load-watch now reads
`paseo ls -g --background`, not the brief's `-a -g`: proposed in the first version, accepted by the review ruling of
2026-11-06), **B3** (context-watch keeps `-g --background`, not `-a -g`), **D3** (`scripts/github-ci-run` is KEPT: it has a live caller outside `skills/loadwatch`, so R2-23's grep was
wrong).

## A. load-watch

A1. **Removed** (line numbers in the file before eecadc3, 2,188 lines): the `SF` session-finder path (:151); `proc_cwd`
(:254-260); the `fleet.sessions()` attribution with `import fleet` (:263-295); the relay.py call in `notify`
(:556-566) and its `where` text (:569); `relay_env` (:621-625); the relay channel in `send_to` (:639-683, now
`paseo_send`); the relay and `sid` paths of `watcher set/clear` (:726-741) and the `--relay`/`--sid` flags (:2170-2171);
the "Investigate per the loadwatch skill" pointers (:694, :1123); the `self-slash` comment (:653); the relay, fleet.py
and pane sentences of the docstring (:17-18, :29-33, :48-54, :66). The file is now 2,404 lines (2,366 before the review repair): it **grew** by 216,
because the cwd join, the two operator notices and their docstrings are new code. The KEEP interfaces are untouched:
`admit` (:1631-1878 then; the exit-75 contract, memory gates, reservations, deadline), `sample`, `release`, `renew`,
`watcher`, `ci`, `guard`, `install`. The plist `launchd/com.djbclark.load-watch.plist` stays where it is (C1); only
its XML comment changed (it said "types one line into its pane" and "2 per core").

A2. **Attribution design** (`paseo_agents`, `attribute`, `top_rows`, `proc_cwds`). `paseo ls -g --background --json`
(archived agents out, background agents in) gives `id, shortId, name, provider, status, cwd` (with `~`), no pid and no
session id (research item 2), so the join is by working directory:
1. every process with at least 0.1 cores over the window, of this uid, has its ancestor chain read from the samples;
2. one cwd read for all of them: `/proc/PID/cwd` on Linux (`PROC_CWD`), one `lsof -a -d cwd -Fpn -p ...` on macOS
   (review rule 5; `work_repos` gets the Linux path too);
3. the process belongs to the agent whose cwd (`~` expanded, realpath) equals its own cwd, else its nearest
   ancestor's (a cargo or brew child in a temp dir); **the walk stops at the first agent CLI** (the process itself
   or an ancestor whose first two argv words' basename is in `AGENT_CLIS` or is a listed provider's head): that
   agent's cwd is the last that may decide, so work is never pinned on the Paseo daemon, a multiplexer or a shell
   above the agent that happens to share a cwd with another agent (review HIGH, 2026-11-06: an agent in `~` running
   rustc in /tmp/build was blamed on the idle agent in wt-a where the daemon started);
4. failing that, to the agent whose cwd is in the same git top-level as the process's own cwd (a Gradle daemon, a
   build in a subdirectory: the old "only session in its git repo" rule);
5. **exactly one** agent at that cwd or repo owns it; **several** make the row `unsure` (not guessed); **none** make it
   loose;
6. an agent whose cwd is `/` or the home directory is never joined (it would own every daemon and app started there);
7. the agent's own CLI (the first two argv words' basename equal to the provider's head, `claude`, `codex`, ...) is
   not counted as build work, as the TUI pid was before.

A3. **Operator notices** (the existing Hermes + watcher path, now one helper `operator_notice`: Hermes at most every
`LW_COOLDOWN_H` per key, the watcher at most hourly per key):
1. `unsure:<cwd>`: for each shared cwd or repo with at least `LW_MIN_CORES`, the process lines (pid, cores, command),
   the cwd and every candidate as `shortId name (provider, status)`;
2. `noattrib`: no `paseo` on PATH, `paseo ls` failing, non-JSON, a non-list, or **any exception inside attribution**
   (cmd_sample now wraps the call, PLAN E5's unguarded :1227-1233): "load N on C cores for 5+ min and load-watch could
   not name the agent behind it: <why>; top: <three process lines>; <not_cpu summary>";
3. `loose`: a process matched to no agent with at least `LW_MIN_CORES`: its process lines (pid, cores, command),
   **whether or not an agent was told in the same sample** (review MEDIUM: a told agent used to suppress this path);
4. `nocpu`: only when attribution worked, no agent was told and no single unmatched process reaches `LW_MIN_CORES`:
   "and no agent's build and no single process above 1.5 cores explains it" (reworded; "no agent build behind it" was
   false when a multi-core unmatched process existed).
One of these per hot episode (`loose_logged`), as before.

A4. **Delivery**: `paseo_send` runs `paseo send --no-wait --json --behavior steer -- ID TEXT` with `PASEO_AGENT_ID`
unset, keeps the DAEMON_* retry rules, and returns the `.status` word from stdout (`sent`, `queued`, another word,
`unknown`, `failed`); the exit code is read only to decide whether to look for a transient error code. `sent` and
`completed` are delivered (`DELIVERED`, one tuple used by `notify`, `send_to`, `tell_watcher` and `watcher test`); `queued` is logged as "queued, not delivered" in `sample.log` (incident line and watcher
line) and the Hermes ping says "paseo send queued it, not delivered" and carries the `acp-dispatch cursor` fixer line.
Incident records gain `delivery` and `agent_id`; `relayed` stays as a bool (`delivery == "sent"`) so older records and
readers still load (review rule 6). `watcher test` prints `sent to`, `queued, not delivered, for` or
`could not reach (<status>)` and exits 0 for sent or queued (the registration check is not time-critical), 1 otherwise.

A5. **Watcher record**: channel `paseo` only. A pre-slice `watcher.json` with `"channel": "relay"` is read as no
watcher (nothing is sent to it), and `watcher show` exits 1 with "uses the relay channel, removed 2026-11-06 ...
Register a Paseo agent: load-watch watcher set --paseo ID". `bin/watch`'s `holder_cmd`/`test_cmd`/`off_cmd`
(`watcher show --json`, `watcher test`, `watcher clear ID`) still work unchanged.

A6. **The message text** (`WATCHER_HOWTO`, appended to every line the watcher gets; R2-11):

> As the load watcher: verify against the processes, not this line (`/bin/ps -axo pid,ppid,%cpu,state,etime,command -r
> | head -20` and `/usr/bin/top -l 2 -s 5 -o cpu -n 20` by full path, since some agent shells shadow ps and top;
> `~/src/djbclark-ade/bin/load-watch status`, `incidents -n 5`, and `admit --json` for memory churn and free memory).
> Map a heavy process to its Paseo agent by working directory (`paseo ls -g --background --json`, `paseo agent inspect ID`); if it
> was not told, send it one line with `paseo send --no-wait --json ID "..."` and read `.status` (`queued` is not
> delivered). Load without CPU is processes stuck in state U, swap, or a pile at background priority. Never kill, stop
> or throttle another agent's or djbclark's work without his yes: steer future runs to CI (`load-watch ci decide`),
> guard a launchd job (`load-watch guard add`), and ask djbclark before creating a CI copy of a repo. Close each
> incident with `load-watch ack ID "what you found and did"`, then tell djbclark in one line (`~/.local/bin/hermes-ping`).

The blamed agent's line is unchanged in substance: "load-watch INC: load N on C cores for 5+ min; your processes used
~X cores (CMD). After your current step, read BRIEF and act on it." The brief file itself already carries the
what-to-do list (only "at your pane" became "watching your session").

A7. **Limits, stated plainly.**
1. **Archived agents are out** (ruling 2026-11-06, accepting this report's first-version proposal):
   `PASEO_LS = ("ls", "-g", "--background", "--json")`. `-a` would have listed archived agents too, with no JSON field
   to tell them apart, turning a checkout with an archived and a live agent into a shared cwd, or sending a
   find-and-tell to an archived agent. Leftover work of an archived agent is now unmatched: the `loose` notice.
2. Several live agents on one worktree (or one repo, for the git-top rule) are never told: by design, the operator is.
3. A process that `cd`s outside every agent's cwd and repo, and whose ancestors up to the nearest agent CLI also do,
   is unmatched (the `loose` notice when it uses LW_MIN_CORES, else only counted in `nocpu`). An agent CLI outside
   `AGENT_CLIS` whose provider is not in the listing is walked past, as before the fix.
6. A `paseo ls` row whose cwd cannot be resolved (a NUL in it) is skipped alone; it never turns the sample into
   `noattrib`. `status` shows every `KEY-watcher` cooldown with its hourly expiry.
4. Another user's processes (root builds through sudo) are never attributed.
5. Paseo agents only: a bare Claude Code or other TUI outside Paseo is invisible to attribution now (fleet.py saw
   herdr panes and bare TUIs). That is the retirement's intent, and is in section I.

## B. context-watch

B1. The `fleet.py` import (old :74, `_fleet()`) is gone: `clean_text`, its `HIDDEN` and `ANSI` patterns
(`fleet.py:701-711`) and `PASEO_ID` (`fleet.py:97`) are copied into `bin/context-watch` (+10 lines net, 387). The
`cannot load` guard now names only the hook.

B2. Tests (`tests/test_context_watch.py`, 45 pass): one pins what the copy strips (CSI, OSC by BEL and by ST, bidi
override and isolates, zero-width, C0/DEL/C1, Hangul fillers, blank braille, variation selectors, U+2028; newline and
tab kept) and that the source no longer loads fleet.py; one checks parity with `fleet.clean_text` and the same
`PASEO_ID` pattern while `fleet.py` exists, and skips once E3b deletes it.

B3. **Deviation**: the brief says "read agents from `paseo ls -a -g --json`". context-watch already read
`paseo ls -g --background --json`, and I kept it: `-a` adds archived agents, which this tool would list as running
Claude agents with their last context size (the JSON carries no archived flag to drop them). The test that pins its
argv (`test_context_watch.py:360`) is unchanged. If the lead wants `-a` anyway, it is a one-word change in
`paseo_agents()`.

## C. context-budget-check

C1. `install`/`uninstall`, `launch_agents`, `_launchctl`, `cmd_install`, `LABEL`, `PLIST_SRC` and the env knobs
`CONTEXT_BUDGET_NO_INSTALL`/`CONTEXT_BUDGET_LAUNCH_AGENTS` are removed; `launchd/com.djbclark.context-budget.plist` is
deleted. `install` and `uninstall` still parse, print "was removed 2026-11-06 ... it runs as a Paseo schedule" and exit
2 (no launchctl call). The check, `--instruction-lint` and PR 289's hook are untouched. 484 -> 460 lines.

C2. `tests/test_context_budget_check.py:285-292` (R2-5) is rewritten: both subcommands exit 2 with the pointer, nothing
is run, the plist is absent, and the usage carries the schedule line. 123 pass with `tests/test_ade_sched.py`.

C3. **The schedule** (in the usage text; flags from paseo.sh/docs/schedules-cli, read 2026-11-06; the old launchd job
ran at 03:50 local time):

```sh
paseo schedule create --cron "50 3 * * *" --timezone "$(readlink /etc/localtime | sed 's|.*/zoneinfo/||')" \
  --name context-budget --provider claude/<model> --cwd ~/src/djbclark-ade \
  "Run ~/src/djbclark-ade/bin/context-budget-check --instruction-lint. Report its exit code and output in one paragraph; change nothing. Exit 1 is a budget breach or a rise, 3 a directory it could not measure."
```

The model is the operator's pick (`docs/model-routing.md`); the script sends its own hermes-ping, so the agent only
reports. `paseo schedule ls` shows it.

## D. Deleted

D1. Code and jobs: `bin/proc-cpu-watch` (with `launchd/com.djbclark.proc-cpu-watch.plist`, the `@TARGET@-cpu-watch`
template: one file), `bin/session-load-watch`, `bin/rumination-watch` and `launchd/com.djbclark.rumination-watch.plist`,
`bin/routing-recalibrate` and `launchd/com.djbclark.routing-recalibrate.plist` (it may return as a Paseo schedule),
`launchd/com.djbclark.session-history-update.plist` (R2-4; `session-history.py` itself is E3's),
`launchd/com.djbclark.context-budget.plist` (C1), `skills/loadwatch/` (R2-11).

D2. Tests: `tests/test_proc_cpu_watch.py`, `tests/test_rumination_watch_{auto_seat,deploy,next_move,pending,stale,target}.py`
(six), `tests/test_routing_recalibrate.py`. `tests/test_relay_watchers_no_ack.py` is **rewritten, not deleted**:
renamed to `tests/test_load_watch_find_and_tell.py` (its two other subjects are gone) and now the hot-path test
(section H). `tests/test_fleet_*.py` are **not** deleted (R2-7 ties them to `fleet.py`, which E3b deletes).

D3. **`scripts/github-ci-run`: KEPT** (R2-23 said DELETE unless a caller outside `skills/loadwatch` exists; one does).
`grep -rn github-ci-run` in this repo finds only `skills/loadwatch/SKILL.md:178` and the CHANGELOG, but the CHANGELOG
line (bg-offload, 2026-10-23) led to site-djbclark, whose `bin/bg-offload` uses it as the generic GitHub runner:
`/home/user/site-djbclark/bin/bg-offload:62` ("The runner is ~/src/djbclark-ade/scripts/github-ci-run") and `:183`
(`generic_default="$ade/scripts/github-ci-run"`), route (4) for any djbclark GitHub repo without its own runner, plus
`tests/test_bg_offload.py` there. R2-23's "nothing in site-djbclark names it" is wrong; correct the ruling's record.

## E. Reference edits in KEEP files

E1. `docs/scheduling.md:63-67` (the placeholder list named the proc-cpu-watch and session-history-update plists; the
rumination-watch comment note), `docs/deadline.md:3` (the "not a section in skills/loadwatch" sentence),
`docs/model-routing.md:553` and `skills/model-routing/SKILL.md:1005` (routing-recalibrate "had" ... "until 2026-11-06";
may return as a Paseo schedule), `docs/apply-toolchain-prompt.md:781` (context-budget-check install -> the schedule).

E2. Tests: `tests/conftest.py` drops the `RW_NO_DEPLOY` guard (rumination-watch's self-deploy);
`tests/test_ade_sched.py:629` rendered the deleted proc-cpu-watch plist and now writes its own templated plist
(`@TARGET@`, `@STATE@`); `tests/test_load_watch_churn.py:119-120` pin the new watcher text.

E3. **Outside my files, flagged**: `tests/test_session_history_adapters.py` (E3's) read the deleted
session-history-update plist in two `render_plist` tests; I removed those two tests (a comment marks the spot) so the
suite stays green until E3 deletes the script. `skills/session-finder/session-history.py:149,195,202` (its `install`)
still reads `launchd/com.djbclark.session-history-update.plist`: until E3 deletes that file, `session-history.py
install` finds no plist (the :195 check fails). `bin/route_agent.py` and `tests/test_route_agent.py` name nothing of
routing-recalibrate (grep, 2026-11-06): no edit needed. `bin/ade-template-check` lists no plists: no edit needed
(`tests/test_ade_template_check.py` passes).

## F. Merger's lines

F1. `README.md:78` (the `bin/proc-cpu-watch` row: delete), `README.md:79` (the `bin/` row: `load-watch` "types one
line into its pane" and "load >= 2 per core" -> "sends the Paseo agent one line by `paseo send`" and 4 per core; drop
the `rumination-watch` entry and its plist link; drop `session-load-watch` and `routing-recalibrate` if named),
`README.md:122` (the `loadwatch` skill row: delete), `docs/skills.md:55` (the `loadwatch` row: delete).

F2. `docs/threat-model.md:49` and `:245-252` (launchd jobs list: drop context-budget and routing-recalibrate; context-budget-check no longer installs), `:92`
(`CONTEXT_BUDGET_LAUNCH_AGENTS` is gone); `docs/queue.md:141-142, :474, :1093` (name the deleted watchers and the
loadwatch skill); `docs/paseo-only-rearchitecture.md:241` (row names session-load-watch and rumination-watch).

F3. **Wave 3b / other slices**: `config/watch.toml:55-56` `[domain.load] skill = "/loadwatch"` now names a deleted
skill, so a `watch up` that launches a load watcher would hand it a missing skill (bin/watch:703-708 builds the first
prompt from it); Wave 3b points it at `load-watch watcher set --paseo` or drops the role. `bin/watch:10`,
`skills/cfenginewatch/SKILL.md:16`, `skills/paseowatch/SKILL.md:15` say "sibling of loadwatch". E3:
`skills/session-finder/SKILL.md:135,143,410,520`, `relay.py:274-275,1675`, `tests/test_relay_verified.py:1402` describe
session-load-watch and rumination-watch as relay callers. E4: `bin/self-slash:593`, `tests/test_self_slash.py:385`,
`skills/autorename/autorename.py:1004` (the `loadwatch` tab name).

F4. Changelog fragment (rule 10; not written, CHANGELOG is the merger's), under `### Removed` and `### Changed`:
- Removed `bin/proc-cpu-watch`, `bin/session-load-watch`, `bin/rumination-watch`, `bin/routing-recalibrate`, the `loadwatch` skill and the proc-cpu-watch, rumination-watch, routing-recalibrate, session-history-update and context-budget launchd plists (slim-down E5).
- Changed `load-watch`: it attributes a spike to a Paseo agent from `paseo ls -g --background --json` by working directory (the walk up stopping at the agent's own CLI), tells it with `paseo send --no-wait --json` (reading `.status`; `queued` is not delivered), sends work that several agents share or that it cannot attribute (no `paseo`) to the operator, and drops the relay.py channel and `watcher set --relay`/`--sid` (slim-down E5).
- Changed `context-budget-check`: `install`/`uninstall` removed (exit 2); it runs as a nightly Paseo schedule (J3).
- Changed `context-watch`: no longer imports session-finder's `fleet.py` (slim-down E5).

## G. Operator steps (on the Mac, after the final merge unless noted)

G1. `for l in $(launchctl list | awk '$3 ~ /^com\.djbclark\..*-cpu-watch$/ {print $3}'); do launchctl bootout gui/$UID/$l; rm -f ~/Library/LaunchAgents/$l.plist; done` (proc-cpu-watch installs one job per target, `com.djbclark.<target>-cpu-watch`, e.g. codexbar).

G2. `launchctl bootout gui/$UID/com.djbclark.rumination-watch; rm -f ~/Library/LaunchAgents/com.djbclark.rumination-watch.plist`

G3. `launchctl bootout gui/$UID/com.djbclark.routing-recalibrate; rm -f ~/Library/LaunchAgents/com.djbclark.routing-recalibrate.plist`

G4. `launchctl bootout gui/$UID/com.djbclark.session-history-update; rm -f ~/Library/LaunchAgents/com.djbclark.session-history-update.plist`

G5. `launchctl bootout gui/$UID/com.djbclark.context-budget; rm -f ~/Library/LaunchAgents/com.djbclark.context-budget.plist` (run it **before** the merge, or by hand after: `context-budget-check uninstall` no longer exists).

G6. The context-budget schedule: the `paseo schedule create` line in C3, then `paseo schedule ls`.

G7. Load watcher registration (C1 B4b): `~/src/djbclark-ade/bin/load-watch watcher show`; if it says "relay channel" or names a dead agent, from the load-watcher Paseo agent run `~/src/djbclark-ade/bin/load-watch watcher set --name "<title>"` (it reads `$PASEO_AGENT_ID`) and `~/src/djbclark-ade/bin/load-watch watcher test` (expect `sent to paseo <id>`).

G8. The `loadwatch` skill links that `skill-everywhere` made now dangle: `find ~ -maxdepth 4 -type l -name loadwatch -path '*skills*' 2>/dev/null` and remove each (C2).

G9. Find-and-tell live check, one synthetic spike: in a Paseo agent's worktree start `timeout 120 sh -c 'while :; do :; done' &`, wait ~20 s, then `LW_STATE_DIR=$(mktemp -d) LW_LOAD_PER_CORE=0 LW_SUSTAIN_S=0 LW_MIN_CORES=0.5 ~/src/djbclark-ade/bin/load-watch sample --dry-run -v`; expect the incident record printed with that agent's `agent_id` and the spinner in `procs` (a second agent on the same worktree prints the "did not guess" operator notice instead). Keep `--dry-run`: a non-dry sample also runs the job guard against the real launchd domain. The delivery half is G7's `watcher test` (a real `paseo send`, `.status` read).

G10. Nothing else on the Mac changes: `com.djbclark.load-watch` keeps running `bin/load-watch sample` from the same path, and needs no reinstall.

## H. Tests

H1. Hot path (`tests/test_load_watch_find_and_tell.py`, 12 tests): `cmd_sample` over three samples of a synthetic
sustained spike (load 40 on 8 cores, 400 s) with a fake `paseo` first on PATH (canned `ls -g --background --json`, argv asserted, with `~` cwds,
broken rows included; `send` logs argv and prints `.status`), a fake `hermes-ping` and a fake process table and cwds.
It asserts: the cargo child in a temp dir is attributed to agent A through its ancestor's cwd; A's own `claude` process
is not counted; one `paseo send --no-wait --json --behavior steer -- A <line with the incident id and brief path>`; the
pytest in a cwd two agents share is **not** sent to either and reaches Hermes and the watcher with both candidates;
the watcher's lines carry WATCHER_HOWTO; `queued` is recorded as `delivery: queued`, logged "queued, not delivered" and
gets the fixer line; **with no `paseo` on PATH every sample returns 0, no incident is written, and the operator ping
names "no `paseo` on PATH" with the process lines, once per episode**; a `RuntimeError` inside attribution is the same
notice ("attribution failed (RuntimeError)"); `paseo ls` failures are reasons, not exceptions; the git-top rule; an
agent in `~` or `/` owns nothing. Added for the review (2026-11-06): the adversary's probe (the walk stops at `claude`
in `~`, or at any `AGENT_CLIS` binary, so rustc in /tmp/build is unmatched, not the idle wt-a agent's; with a plain shell
in between the same chain still joins); a told agent no longer hides unmatched multi-core work (the `loose` ping names
pid, cores and command, once per episode); `completed` is delivered in `notify`; one NUL-cwd row is skipped alone; `status`
prints the hourly expiry of `noattrib-watcher` and `unsure:<cwd>-watcher`. Also new in `tests/test_load_watch.py`: `.status` over exit code, a missing binary is
`failed`, the Linux `/proc` cwd path, the relay-record `show` message, `watcher test` wording.

H2. The brief's list plus the slice's other touched files: `bin/pytest -q tests/test_load_watch.py
tests/test_load_watch_admit.py tests/test_load_watch_churn.py tests/test_load_watch_chrome_alert.py
tests/test_load_watch_find_and_tell.py tests/test_context_watch.py tests/test_context_budget_check.py
tests/test_deadline_wrappers.py tests/test_ade_template_check.py tests/test_route_agent.py tests/test_ade_sched.py
tests/test_session_history_adapters.py`: **2 failed, 616 passed, 1 skipped**, rc=1. The two failures are
`test_deadline_wrappers.py::...[dispatch]` (acp-dispatch-wait), both in `docs/slim/baseline.md`; the same two failed
before any change in this worktree.

H3. Full suite (`bin/pytest -q -p no:cacheprovider tests/`, Linux container, no pytest-timeout, 2026-11-06 21:37-22:25Z;
three other agents' suites ran on the same container at the time): **169 failed, 10,251 passed, 54 skipped, 2 errors,
2,107 subtests passed, 48 min 18 s**, rc=1. The baseline is 166 failed, 10,141 passed. By failing test id (the
summary's `FAILED`/`ERROR` lines against `docs/slim/baseline.md`'s full list): 4 new, 1 gone.
1. New: `tests/test_relay_card_alert.py` (three tests: `TestBusyAlert::test_a_message_past_the_threshold_gets_one_notice_and_one_ping_however_many_looks`,
   `TestCardAlert::test_a_message_that_waited_past_the_threshold_pings_once_naming_target_card_sender_and_message`,
   `TestCardAlert::test_a_ping_that_fails_is_logged_and_never_costs_the_message`) and
   `tests/test_acp_dispatch_reap.py::TestSignalledRunner::test_sigterm_to_the_runner_finalizes_with_143`. This slice
   touches neither relay.py nor acp-dispatch. Re-run alone, `test_relay_card_alert.py` plus the
   `TestSignalledRunner` class passed (27 tests, rc=0; I first wrote "both files pass", which was wrong: I had not run
   the whole of `test_acp_dispatch_reap.py`). Both whole files alone are 71 tests: 70 passed and 1 failed, the
   baseline `TestReap::test_done_report_with_marker_finalizes_as_done` (coordinator's re-run). So the four are timing
   failures under the shared load, not a regression.
2. Gone: `tests/test_local_review.py::test_a_hung_codex_is_killed_with_its_group_and_the_run_is_failed` passed here.
3. The deleted test files had no baseline failures. The passed count is higher than the baseline's because the
   suite moved on (master and the slim branch since `da6b2e7d`), less the ~4,600 lines of deleted tests.

## I. Lost on purpose

I1. Pane delivery: herdr, tmux and Orca panes and bare TUIs are no longer reached by find-and-tell or the watcher; only Paseo agents are.

I2. `proc-cpu-watch`'s per-process (per-app, `--target`) CPU view and its own launchd jobs.

I3. `rumination-watch`: the no-model re-to-the-head prompts and its self-deploy.

I4. `session-load-watch`: the per-session load offload nudge (load-watch's incident brief is what remains).

I5. `routing-recalibrate`: the monthly Opus re-rank of `good_at`, until someone writes its Paseo schedule.

I6. The `loadwatch` skill's long-form guidance (admit gate table, standing exceptions): the gate's own usage text and
WATCHER_HOWTO carry what an agent needs; the admit details stay in `load-watch --help`.

I7. Attribution of a process outside Paseo, and of work in a cwd several agents share (A7).
