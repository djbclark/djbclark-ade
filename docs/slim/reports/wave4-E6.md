# Wave 4 report E6 (S-acp): `acp-dispatch` is a `paseo run` shim; bigteam, dialogue, research decided

Writer: one Claude agent, 2026-11-06, in worktree `/home/user/djbclark-ade/.claude/worktrees/agent-a6556e03497759a25`,
branch `worktree-agent-a6556e03497759a25`. The worktree was created at master fb3b9de; it was fast-forwarded to
`claude/determined-maxwell-uvddaz` at **6942aaf** before any edit, so every commit here sits on the slim branch. Brief:
`docs/slim/briefs/wave4-E6-shim.md`. Not pushed (the lead merges). No Paseo daemon and no Claude login: every `paseo`,
`load-watch` and `review-launch` call in the tests is a fake under `tests/fakes/`. Paseo CLI shapes were read from the
getpaseo/paseo 0.15.3 source clone at 9f68af0 (`/tmp/claude-0/ps/src`, E3's clone): `packages/cli/src/commands/agent/
{run,wait,ls,mode,inspect,send,stop}.ts`, `provider/ls.ts`, `output/json.ts`, and the codex provider's mode table.

Commits: 6dae547 (the shim, its fakes and test), 759679f (deletions), 9496cf7 (fan-out), e17a1e2 (dialogue port),
2cf1cd1 (pointer skills), 1967974 (reference edits), the changelog commit, and the commit of this report.

## A. The shim

A1. `bin/acp-dispatch`: 5,848 lines to 1,306 (the brief said about 600; the rest is the ported frontier guards, the
docstring that carries the whole contract, and the review-launch runner). Line 3 says it is a shim removed with
`tools/acp-run` in the follow-up PR (PLAN E6, Wave 6).

A2. Agent to provider: claude, codex, antigravity, cursor, opencode, hermes, omp map to the Paseo provider of the
same name; any other name (agy, grok, cursor-cloud, ...) exits 2 with that list. `grok` was in the brief's map and was
dropped by the operator's ruling of 2026-11-07 (the grok CLI is retired; grok-bot stays, through peer-link, not the shim). `--model M` becomes `--provider P/M`;
`--effort E` becomes `--thinking E` (not passed to review-launch, whose interface has no effort flag).

A3. The argv per `--perm` (from `launch_argv`; `--dry-run --json` prints it as `argv`):
- **`all`, every provider** (`boundary: paseo`): `paseo run --provider P/M --mode <defaultMode> --no-wait --json --title NAME
  --cwd DIR --label ade.via=acp-dispatch --label ade.kind=KIND --label ade.name=NAME --label ade.lead=LEAD [--thinking E]
  -- PROMPT`. `defaultMode` comes from `paseo provider ls --json` (the row must be `Enabled`/`available`, retried 5 times
  2 s apart while `loading`, else exit 2); Claude's is `auto`. PROMPT is one paragraph naming the brief copy
  `<out>/<name>-brief.md`, the report and the `.done` path, followed by the footer (`footer_text`). Never
  `--prompt-file`, never `--output-schema`. `paseo_json` puts `--json` before the `--`, so the prompt stays a positional
  even when it starts with a dash.
- **`read-only`, claude** (`boundary: review-launch`): `bin/review-launch --mode read-only -C DIR --schema
  config/acp-dispatch-report-schema.json -f <out>/<name>-brief.md --model M [--timeout S] --json`; **`deny`, claude**: the
  same with `--mode review`. The brief copy ends with a note that the report goes in the structured output's `report`
  field (the run can write nothing); the shim writes that string to the report and touches `.done`. review-launch's
  exits map: 0 report (classified), 77 tripwire, 2 refused, 3 no output, 124 timeout; unreadable stdout is 3. Not
  launched by this suite against a real `claude` (no login): the stub in `tests/fakes/review-launch` follows E8's 1a.
- **`read-only`, codex** (`boundary: paseo-mode`): `paseo run ... --mode read-only ... -- "Reply with exactly: ready. Do
  nothing else."`, then `paseo wait ID --timeout 60`, `paseo agent mode ID --list --json` (the mode must be listed) and
  `paseo inspect ID --json` (`Mode` must equal it); only then `paseo send ID --no-wait --json --prompt=<PROMPT>`. On any
  miss: `paseo stop ID`, record `refused`, exit 2. DECIDED (the brief created the agent with the real prompt and checked
  after): a no-op first prompt, so no brief work starts before the mode is verified.
- **`read-only`, any other provider; `deny`, any non-claude provider**: refused, exit 2, nothing launched.

A4. **Finding: codex `--perm read-only` is refused in practice.** In 0.15.3 `CODEX_MODES` lists `auto`, `auto-review`,
`full-access` (`codex-app-server-agent.ts:272-289`); `read-only` exists only as a sandbox preset (`MODE_PRESETS`,
`:329`). So the verification fails and the launch is refused: today only Claude has a working `--perm read-only`. The
tendcf/nix2cf frontier review route on codex read-only (ledger "C3 PRs") will exit 2 after the merge until either the
lead accepts "active mode equals the preset, unlisted" as verified or the review moves to Claude through review-launch.
Lead's call; the shim follows the brief (listed AND active).

A5. The status map of `paseo wait ID [--timeout S] --json` (the status field; `$?` is never read): `idle` → finalize:
the report is classified (0 DONE, 1 unfinished, 4 BLOCKED; an empty report gets `NO-REPORT: idle without a report (agent,
model)` appended and is 3); `timeout` → 124, the record stays unfinished (`last_wait`), the agent keeps running (the
detail names `paseo wait ID` and `paseo stop ID`); `permission` → 4, the record's `status: permission`,
`pending_permissions` = the `tool` names from `paseo inspect ID --json`'s `PendingPermissions`; `error` → a
`NO-REPORT: error (...)` line and 3; no status (a failed wait) → 1, unfinished, rerun `acp-dispatch wait`.

A6. The record (`~/.local/state/bigteam/<task>/jobs/<name>.json`, temp file plus `os.replace`, read with `.get`): name,
agent, provider, model, mode, boundary, perm, kind, role, service, dir, task, out, brief, report, done, record, stderr,
lead, effort, timeout, wait_timeout (`--wait-timeout`, else timeout + 300, 0 none), detached, argv, cmd, prompt, owner,
started, status, paseo_agent_id, pid (the detached review-launch runner), exit, finished, go_advisory, frontier_reason,
frontier_judged, frontier_judged_note, estimated_usage_pct, estimated_usage_windows, estimate_source,
snapshot_remaining_before, snapshot_reading, load_gate, min_headroom; finalize adds detail, report_source,
measured_usage_pct / measured_usage_windows (the pool drop, which `route_agent.py calibrate` and the estimates read), and
`outcome` is written by `acp-dispatch outcome` unchanged.

A7. The count. `load-watch admit --wait S --json --max-agents` (knobs from LW_*, the LW_* scrub, exit 75 and 2-refuses
unchanged) still runs first. **Finding**: E5 kept load-watch's own `count_agents()` (`bin/load-watch:1831`) as a `ps`
count of `acp-run` processes, so it never sees a Paseo agent; releasing the admit reservation at launch would leave the
new agent counted nowhere. So the shim counts its own agents: `paseo ls -g --background --label ade.via=acp-dispatch
--json`, rows whose status is `running` or `initializing` (archived agents are not listed without `-a`; `--background`
because a worktree agent can sit in a background workspace, as load-watch reads it). Under a machine-wide `flock`
(`~/.local/state/acp-dispatch/launch.lock`) it counts, launches when the count is under LW_MAX_AGENTS (default 14, 0
off), waits up to 10 s until the new id shows in that list, and only then releases the lock and the admit reservation.
While over the cap it waits outside the lock, inside the --load-wait budget, then exits 75 with `refused=agents`; an
unreadable list is 75 `refused=agents_unreadable` (fail toward waiting, like load-watch). DECIDED (the brief's
`ade.lead` filter would make the cap per lead): the label is `ade.via=acp-dispatch`, so the cap is machine-wide like
the old acp-run count. Residual: acp-run processes (C3 callers) and shim agents are capped separately, 14 each; a
review-launch run is a `claude -p` that `paseo ls` cannot see, so it holds its admit reservation (renewed every 60 s)
until it ends. The handoff test (20 parallel launches, a fake `paseo` that keeps every agent running, a fake
`load-watch`) gets exactly 14 launches, 6 exits 75, and 20 releases.

## B. Dropped from acp-dispatch

B1. Subcommands `resume`, `reroute`, `auto-resume`, `extend`, `finalize`, `execute`, `reap` (`--install`/`--uninstall`),
`cursor-cloud`: each exits 2 with the replacement (`RETIRED` table). Flags `--checkpoint`, `--no-preflight`,
`--no-auto-resume`, `--acp-arg`, `--context`, `--wrapup-grace`, `--no-model-check`, `--acp-run`, `--tee`,
`--allow-unpushed`: argparse usage errors (exit 2). `wait --once` is gone too (B3).

B2. Machinery gone with them: the launchd runner scripts and `launchctl submit`, `launchd/com.djbclark.acp-dispatch-reap.plist`,
`config/sudoers.d/acp-dispatch-pmset` and the pmset wake, the quota-stop classification and the automatic resume, the
reroute/escalation hints, reap and restart attribution, the acp-run preflight and model/perm/effort probes, the
`--acp-arg` pass-through, final-message recovery, checkpoint mode, the advisor tree snapshot, the plenty and fallback
gates, the old `wait_for_capacity` overload gate, the Claude live-session socket in `tell`. 4,542 lines.

B3. `bin/acp-dispatch-wait` (the cheap rearm waiter) is NOT deleted: the brief does not name it and its ledger row is
DELETE gated on the C7 drain. It calls `acp-dispatch wait --once`, which the shim does not have, so an old rearm line
now exits 2. Only its two comments naming the retired verbs were reworded. It and its `dispatch` cases in
`tests/test_deadline_wrappers.py` go in Wave 6.

## C. Frontier guards kept (ported, not dropped)

`frontier_judged`, `frontier_inflight` (the per-wave cap through `ade_gates.load_frontier`/`judged_pool_block`/
`read_guard_state`), `inflight_cap`, `inflight_records` (live = the record's paseo id is in the live `paseo ls` set, or
its review-launch runner pid lives, or it started under 10 min ago; every running record counts when the list is
unreadable), `reserved_usage`, `estimate_floor_and_cap` with the `-C` repo override, `estimates` (`measured_history`
plus `route_agent.estimate_from_history`/`estimate_windows_from_rows`), the window fit and `--min-headroom` (exit 5),
`is_frontier_model`, the frontier-model/`--kind frontier`/`--role exec`/fable-xhigh/hermes gates, kind eligibility
(route-override), and `bin/agent_guard.py`'s identity policy, applied to the launch argv (`identity_refusal`: for a
guarded agent exactly one `--provider P/M` or review-launch `--model M` and it is the admitted model; no `--env`,
`--settings`, `--mcp-config`). DECIDED: exit 5 (pool unavailable) is kept for the reservation, wont-fit and headroom
refusals although the brief's contract list omits it; callers read 5 as "re-plan".

## D. acp-run trims

None needed: `git log --oneline -5 -- tools/acp-run` shows E9's b93ce69, b21dff9, e88ddd8 already removed the retired
adapters; the brief's grep finds only notes (`:58`, `:330`, `:333`, `:343`) and unrelated words (omp, pypi, Gemini's
`default_api` markup check). `tools/acp-run/README.md`'s "Dispatch slice controls" section was rewritten to say
acp-dispatch no longer runs acp-run (it described extend, resume, reroute, the auto-resume wake and the sudoers rule).

## E. bigteam to fan-out

`skills/bigteam/SKILL.md` (1,012 lines) and `zcode/commands/bigteam.md` deleted; `skills/fan-out/SKILL.md` (69 lines,
name `fan-out`): slice first, in process (Agent tool or a Workflow, the footer), out of process (`acp-dispatch` in a
claimed worktree, or a plain `paseo run --no-wait`), collect (`acp-dispatch wait`/`check`, `paseo ls --label`, `tell`,
`outcome`), one worked example. `bin/diskfree` and `tests/test_bigteam_prune.py` are gone already (E1): confirmed.

## F. The dialogue hour

F1. Result: **KEEP** `skills/dialogue` and `skills/research`. The hour started at 23:38:01 UTC (commit 9496cf7, the
step before); the port and its test passed and were committed at 23:40:40 UTC (e17a1e2), well inside the hour.

F2. What changed (`skills/dialogue/scripts/dialogue.py`): the `acp` route kind (the acp-run one) is now an alias of a
new `paseo` kind; `run_paseo_route` runs `paseo run --provider <agent or provider>/<model> --mode <mode, default the
provider's defaultMode from `paseo provider ls`> --no-wait --json --title dialogue-<prompt> --cwd <cwd> [--thinking E]
-- <pointer>` (the pointer names the turn's prompt file, which is too big for argv, and a reply file beside it), then
`paseo wait ID --timeout S --json`; idle reads the reply file as the turn text, anything else is the route's error (the
second route then runs). A `set` entry with an effort key becomes `--thinking`. `claude` and `cmd` routes unchanged
(note: the `claude` route still passes `--dangerously-skip-permissions`; not changed here). SKILL.md routing items 2, 3,
5 and the description updated. Test: `tests/test_dialogue_paseo.py` (probe through an `acp` route: argv, mode,
thinking, reply file; a permission wait and a missing reply fail the route).

F3. `skills/research`: `research_check.py` does not import or name dialogue; only SKILL.md drove acp-run. Its
`/bigteam` and "see bigteam" lines were reworded; the rest of its dispatch prose (agy, zcode) is E11's.

## G. Pointer skills

`tell-coding-bot` (85 lines) and `tell-chief-of-staff` (40) are 3-line pointers (what it was, where the code went: the
peer-link repository `frdminc/peer-link` per E9j, what to run instead). Code removed: `bin/coding-bot` (601 lines) and
`tests/test_coding_bot.py` (615). `tell-chief-of-staff` had no code here (its sender is Hermes's
`~/.hermes/skills/agent-tooling/tell-chief-of-staff/`); nothing else removed.

## H. Reference edits

H1. Reworded: `bin/watch` (2 comments), `claude/hooks/context_size_nudge.py` (3: `/bigteam` to `/fan-out`, incl. the two
nudge texts), `claude/agents/adversary.md` (1), `claude/commands/skillopt-sleep.md`, `zcode/commands/skillopt-sleep.md`,
`docs/checkpoint.md`, `docs/failover.md`, `docs/orchestration-practices.md` (2), `docs/threat-model.md` (launchd list and
section 4.6), `docs/scheduling.md`, `docs/agent-guard-contract.md` (the shim's argv check, the renamed test),
`skills/cfenginewatch`, `skills/paseowatch`, `skills/research`, `skills/dialogue`, `tools/acp-run/README.md`,
`bin/acp-dispatch-wait` (2 comments), `tests/conftest.py` (the three knobs only the old acp-dispatch read are gone),
`tests/test_ade_sched.py` and `tests/test_acp_run_classify.py` docstrings. `docs/coding-factory.md` names none of the
tokens.

H2. Left on purpose, with the owner:
- `skills/baton/SKILL.md:77,102,106,115` and `skills/handoff/SKILL.md:85,417`: brief section 5 forbids touching them.
- E7 rewrites or deletes: `skills/model-routing/SKILL.md` (196, 214, 253, 298-306, 377, 483, 590, 596, 670, 708, 801),
  `skills/effort-routing/SKILL.md:81` (E7 deletes it), `docs/model-routing.md` (51, 229-261, 319, 371, 412-416),
  `config/routing.toml` (123-124 `auto_resume_max_wait_hours`, now read by nothing; 234; 338), `bin/route_agent.py:190`.
- `bin/deadline:398` and `docs/deadline.md:27,229`: `deadline --on-expire reroute:RECORD` still runs `acp-dispatch
  reroute`, which now exits 2, so its worker takes the existing "reroute FAILED" path (a tracked owner notice and an
  operator ping; the stopped work is not replaced). Fail-safe, but the option is now dead: retiring it (refuse at
  registration, 4 tests in `tests/test_deadline.py`, the two doc lines) is a follow-up outside this brief.
- Dated research and design snapshots, read as history: `docs/software-factory-reviews/*-2026-10-19.md`,
  `docs/software-factory-research-digest-2026-10-19.md`, `docs/paseo-plugins-scan-2026-10-19.md`,
  `docs/model-tiers-design.md`, `docs/tui-lessons-learned.md`, and the plan `docs/paseo-only-rearchitecture.md` (E11).
- `tests/fixtures/context-now.txt:315` (a captured `/context` table) and the shim's own `RETIRED` table, docstring and
  tests, which name the retired verbs to refuse them.
- `~/.local/state/bigteam` stays the state directory (every remaining `bigteam` in code is that path).

## I. Merger's lines

- `README.md:68` (Fan out: `bigteam` link), `:78` (`bin/` row: "wraps `acp-run`, appends the footer, checks `--model`
  against ..."), `:104` (`bigteam` row), `:117` (`tell-coding-bot` row: through `bin/coding-bot`), `:123` (`dialogue`),
  and a new `fan-out` row.
- `docs/skills.md:64` (`bigteam` row), `:68` (`dialogue`), `:79` (`tell-chief-of-staff`), `:80` (`tell-coding-bot`: the
  `ln -s ~/src/djbclark-ade/bin/coding-bot` link), and a `fan-out` row.
- `AGENTS.md:16` ("run the same shape with Paseo workspaces and agents (`skills/ade-paseo`, `skills/bigteam`; ..."):
  `skills/fan-out`.
- The template: `agents/hermes/config.yaml.tmpl:127` ("bigteam skill, Current exclusions").
- With E7: the shim imports these route_agent names: `POLICY["dispatch"]` (operator_gated, fable_gated_efforts,
  inflight_cap, frontier_models, estimate_floor), `KINDS`, `BY_NAME`, `ALIASES`, `DEFAULT_PROFILE`, `map_agent_to_provider`,
  `pool_service`, `load_snapshot`, `history_rows`, `estimate_from_history`, `estimate_windows_from_rows`, `window_fit`,
  `floor_lookup`, `kind_floor_applies`, `repo_of`, `repo_floors`, and from `ade_gates`: `frontier_reason`,
  `load_frontier`, `judged_pool_block`, `read_guard_state`, `iso`. If E7's quota-guard deletion takes
  `read_guard_state`, `frontier_judged` falls into its `except` and grants nothing for the claude family (the closed
  treatment): safe, but the claude frontier allowance then never grants; re-point it at E7's frontier half.

## J. Operator steps

J1. `launchctl bootout gui/$(id -u)/com.djbclark.acp-dispatch-reap` and `rm ~/Library/LaunchAgents/com.djbclark.acp-dispatch-reap.plist`
(after the C7 drain: no `acp-dispatch.*` runner or `auto-resume` one-shot label left in `launchctl list`).
J2. `sudo rm /etc/sudoers.d/acp-dispatch-pmset`.
J3. Repoint `~/.local/bin/coding-bot` to the peer-link install once the transfer lands (E9j); until then it dangles.
J4. The dispatch out directory is outside the agent's cwd: acp-run passed `--add-dir <out>`, `paseo run` has no per-run
equivalent. An `auto`-mode Claude may ask before reading the brief copy or writing the report in
`~/.local/state/bigteam/` (the slice then reads as BLOCKED, exit 4, with the permission named). If the first live run
shows that, add `~/.local/state/bigteam` to the Claude provider's `additionalDirectories` override in Paseo's config.
J5. After the final merge, one live `acp-dispatch claude --model sonnet --kind code --perm read-only --name e6-live -p
"List the top-level files of this repository." -C ~/src/djbclark-ade --task e6-live`, expecting exit 0, `boundary:
review-launch` and a report ending DONE.

## K. Tests

K1. Targeted (the brief's set, `bin/pytest -q tests/test_acp_dispatch.py tests/test_agent_guard*.py tests/test_route_agent.py
tests/test_load_watch_admit.py tests/test_acp_run_*.py`), plus `tests/test_dialogue_paseo.py`, `tests/test_go_model_policy.py`,
`tests/test_omp_operator_gate.py`, `tests/test_acp_not_installed.py`, at 2547a64: **3 failed, 547 passed, 2 skipped**
(4 min 24 s). The 3 are baseline rows: `tests/test_acp_run_git_identity.py::TestGitIdentityGuard::
{test_foreign_local_identity_is_refused_even_with_no_verify, test_hook_path_with_an_apostrophe_still_runs,
test_nested_launch_repairs_stripped_parameters}`. After the grok ruling (K4) the shim, dialogue, agent_guard, Go-policy and
operator-gate files were run again: 79 passed.

K2. Full suite in the detached worktree `/tmp/w4e6-verify` at 1967974 (the code head then; the later commits are the
changelog, this report, the runner-log path, the fan-out example and the grok removal, each covered by K1's reruns), with
the baseline's own command (`uv run --with pytest --with pytest-timeout --with pyyaml --with 'agent-client-protocol>=0.9,<1.0'
python -m pytest tests/ -q --timeout=120`): **70 failed, 7,197 passed, 30 skipped, 1,409 subtests passed, 19 min 0 s**,
rc 1. **No new failure**: every failing test id is a row of `docs/slim/baseline.md`'s full list. 65 baseline rows no
longer fail: their files were deleted or rewritten here or in Waves 2-3 (`test_acp_dispatch.py` 6, `_quota_d2` 2, `_reap` 1,
`test_bigteam_prune.py` 8, `test_self_slash*.py` 41, `test_session_relay.py` 2, `test_ade_scan_state.py` 2,
`test_local_review.py` 2, `test_launch_turns.py` 1).

K4. Operator ruling 2026-11-07 (relayed by the coordinator after K2): the grok CLI is retired, so `grok` left the
provider map (it now exits 2 like any unknown agent), the shim's tests, the fake `paseo`'s provider list, this report and
the changelog line; `tests/test_dialogue_paseo.py` probes through the `cursor` provider instead, and the research skill's
provider list lost it.

K3. Test files: `tests/test_acp_dispatch.py` rewritten (519 lines, 37 tests: surface and retired verbs, the provider map
and argv, the perm boundaries, launch/wait/status map, the admit gate, knobs, reservation release and the 20-launch
burst, frontier gates, the allowance, the per-wave cap, the estimate floor and reservation, classify, check, outcome,
tell); `tests/test_agent_guard.py` new (the pure policy checks of `test_acp_dispatch_identity.py`);
`tests/test_dialogue_paseo.py` new; `tests/fakes/{paseo,load-watch,review-launch}` new. The other 20 `tests/test_acp_dispatch_*.py` are gone (19
deleted; `_identity`'s policy checks moved to `test_agent_guard.py`): `_auto_resume`,
`_brief_footer`, `_classify`, `_credit_refusal`, `_cursor_cloud`, `_effort`, `_frontier_reason`, `_gate`, `_git_identity`,
`_identity`, `_load_gate`, `_outcome`, `_pool_map`, `_quota_d2`, `_reap`, `_refused_resume`, `_routing`, `_tell`,
`_transient_quota`, `_waiter`; plus `tests/test_coding_bot.py`. Trimmed: `tests/test_acp_run_read_only.py` (its
acp-dispatch `TestDispatch` class), `tests/test_acp_not_installed.py` (the acp-dispatch preflight, check and
failure-class classes; the acp-run classes stay), `tests/test_go_model_policy.py` (the bounded Go advisor is now refused:
`test_bounded_advice_is_refused_without_a_verified_read_only_mode`). `.github/workflows/test.yml` names no test file:
nothing to remove there.

## L. Lost on purpose

Auto-resume after a quota stop (Paseo's `usage-auto-resume` plugin is the replacement); reroute and `--escalate`; the
reap sweep and restart attribution; cursor-cloud through dispatch (`bin/cursor-cloud` direct); checkpoint mode;
`extend`; resume in the same ACP session; the per-agent acp-run boundary for non-Claude providers (now provider-mode
strength, and in 0.15.3 not even that for codex: A4); final-message recovery; the acp-run preflight and model/effort
probes; the advisor tree-change check; the plenty and fallback-pool gates (routing, E7); `tell`'s live Claude socket;
the slice deadline (a Paseo agent is not stopped at `--timeout`; the waiter stops waiting); Go advisory slices
(opencode has no verified read-only mode, so the Go advisor path refuses); `wait --once` and with it the cheap rearm
waiter for new records.
