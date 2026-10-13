---
schema_version: 1
handoff_id: 9976
parent_handoff_ids: [9ec0]
lineage: deterministic
chain: [standalone-dc33]
repo: djbclark-ade
workspace: main
branch: master
head_sha: 4224c73b072a47cdb7b90b065f5a90efab66f4c0
created_at: 2026-10-13T12:20:00-04:00
writer: claude-code
---
# Handoff — Load spike fixes and SkillOpt night chain repair

## The Goal
Started as `/baton "the high load work, then investigate current high load and see how
we can avoid it in future"`. It became two threads: (1) stop agent builds and tests from
thrashing the 16 GB Mac (load 134-183, swap 10.6 of 11.3 GB at 09:27), and (2) repair the
SkillOpt-Sleep nightly chain, whose first unattended night (2026-10-13 03:30) mostly failed.
Parent handoff: `HANDOFF_standalone-dc33_skillopt-sleep-fleet-rollout_2026-10-12_9ec0.md`.

## Where We Are
Everything below is committed and pushed on master (head 4224c73). Nothing has run against a
real model on the new settings: the first real test is tonight's 03:30 launchd night.

**Load thread (done).** Cause of the 09:27 spike: an agy session (hookless) ran a bare
`swift-test --filter CLIUsageFetchSetupTests` in `~/src/CodexBar`: SwiftPM started one
`swift-frontend` per core (8, up to 3.5 GB each), plus a 3.3 GB Gradle daemon; memory thrash
(compressor 7 GB), not CPU. The run finished on its own (the operator chose to leave it).
1. `bg` (site-djbclark 315c67a): `swift build|test|run` and `xcodebuild` take a test slot
   and get `-j`/`-jobs BG_CPUS` (3) unless set; `claude/hooks/bg_test_gate.py` denies them
   bare. Verified with a real tiny Swift package: ran as `swift-build -j 3`, slot held.
2. `bin/heavy-shim` (ade 536ad9c): PATH shim linked as `~/.local/bin/swift` and
   `~/.local/bin/xcodebuild` for hookless TUIs; `BG_SHIM=1` is the loop guard. Row added to
   `docs/apply-toolchain-prompt.md` (a467e0c).
3. `fleet-watch` (site-djbclark aa2d783): one Hermes notice when load1 > 4x cores AND swap
   >= 90%, naming the top 5 memory users and their owning agent; 30 min cooldown, recovery
   notice, notice only (`fleet-watch load` runs just that check). Tested with a Hermes stub.
4. Memory note `site-private/memory/feedback_tests_through_bg_caps_and_slots.md` updated
   (edd68e6, fb8b486, b87b966).

**SkillOpt night thread.** First unattended night (10-13 03:30-05:50): only `zcode` source got
through (1 task, gate reject); claude/codex/cursor/agy/crush hit `chain_exhausted`; 0
proposals. Diagnosis (sub-agent, read-only): all 21 failed attempts died in agent STARTUP
(opencode "Location plugins did not finish activating", 40 s handshake timeouts, agy MCP
servers not up in time), never on quota, entry timeouts or the model; `ask_many` failed the
whole entry on any one failed prompt; an end_turn/rc=124 race discarded two good answers.
Fixes, all pushed:
1. acp-run 80ab66c: race fix (done task result kept); handshake retries transient
   `RequestError` and names the hung phase.
2. failover dbd853a: per-prompt startup-failure retry (2 retries, 20 s/60 s backoff, budget
   max(3, 25%) per round, `retry_budget` entry field); per-spawn load gate (2.0 per core,
   600 s cap, memory pressure stops the night); preflight cache 1 h TTL; `prompt_max_load` /
   `prompt_load_wait_s` night.json keys.
3. acp-run c4a784c, c63b693, 51d8649 (adversary reviewed twice): `--perm deny` strips the
   user's plugins/MCP/hooks for opencode and agy via per-run temp config; sweep of stale
   `acp-run-*-deny-*` dirs; secrets via `{env:}`; deep merge; fail-to-"kept" on parse errors.
   opencode `session/new` 6-7 s -> 1.1 s (free SIPB smoke call).
4. Sources (94ae761): Hermes (`~/.hermes/state.db`, read-only), grok
   (`~/.grok/sessions`), muse, cline and acp-dispatch job reports added; dry-harvest counts
   hermes 174/11/40, grok 46/9/40, muse 2/0/2, cline 19/1/19, acp_dispatch 146/107/40.
5. crush (71ac081): under deny all 29 built-in tools are disabled via per-run config; real
   preflight: probe OK, canary 0 tool calls (strict policy), 42 s.
6. perm (4224c73): per-chain/entry `perm: deny|all`; `perm: all` passes `--perm all`, skips
   canary/tripwire; new `acp-run --strip-user-config` keeps the plugin/MCP strip under any
   perm; Hermes added as a backend (registry entry, out of `failover.DENY`, in
   `DEFAULT_ALLOW`). 463 tests pass on the combined acp-run/failover/night/sources suites.
Live config (outside the repo, `~/.skillopt-sleep/night.json`, backups
`night.json.bak-2026-10-13-{chain,sipb,floors,permall}`): `perm: all`; allow adds `sipb`,
`hermes`; opencode+agy entries have `--handshake-timeout 120 --handshake-tries 3`; SIPB
entries are the direct `sipb` route (qwen3-coder:30b, deepseek-r1:32b); crush then hermes
last; floors 0 for opencode-go/agy/zcode, 5 for claude. `chain-check`: 8 of 10 ready
(agy claude_gpt and zcode not in `aiuse --available`).

## What We Tried
1. Admitting crush with a relaxed canary (`reads_ok`) was the first plan: rejected after
   reading the 03:43 log, which showed `bash` (kind execute) running unasked, not only `glob`.
   Real deny (disable every tool) worked instead, so no admission policy was needed.
2. Removing the crush/opencode temp dir right after `session/new` (adversary finding 1): not
   done, unsafe: opencode reloads config when its config dir changes, agy re-reads
   `$GEMINI_HOME` on every agent rebuild. Mitigated by secrets in env, early removal on
   signal/error, and the stale sweep; agy's dir is removed after `_kill`.
3. Parsing token usage from acp-run logs to price extra backends: the logs carry no token
   counts and the archived night prompts were empty, so tokens per prompt are unmeasured.
4. `skillopt-night status`: not a subcommand (it is `skillopt-sleep status`); night results live in
   `~/.local/state/skillopt-sleep/{nights,attempts}.jsonl`, not in `~/.skillopt-sleep/`.

## Key Decisions
1. Backends stay denied (`cursor, cline, clinepass, opus, fable, muse, pi, grok, codex,
   copilot`), revisit tomorrow with real counts (operator). Hermes is the exception: the
   operator later said "all TUIs and hermes run any tools", so Hermes is admitted last in the chain.
2. SIPB goes direct first, crush ACP as failover (operator); floors: deplete all pools except
   claude (5%) (operator).
3. `perm: all` for the night: every backend may run any tools (operator, 2026-10-13: "I want
   crush to be able to run any tools it wants. I want all of the TUIs and hermes to be able to
   run any tools they want."). `--perm deny` stays the default for acp-dispatch and others.
   Exposure is written into docs/failover.md and docs/skillopt-sleep.md: mined session text can
   carry injected instructions, each prompt starts in an empty temp dir but nothing confines it.
4. Rejected: loosening the crush canary; sending the night through the Claude hook-only guard
   (agy/codex/cursor have no hooks, hence the shim); re-adding the load sampler.
5. `-C` strip gap (agy workspace plugins, opencode skills) and crush deny-mode findings 1-4
   from the third adversary review: noted, not fixed (`docs/queue.md`).

## Evidence & Data
1. Load at 09:27: 134/183/130, swap 10.6/11.3 GB, 60 running, 8 swift-frontend (1.8 GB RSS
   sum, 3.5 GB top footprint). Falling to 5.8 by 09:45.
2. Night failures table: scratchpad copy `chain-report.md` (21 failed attempts); evidence in
   `~/.local/state/skillopt-sleep/{nights,attempts}.jsonl` and
   `~/.local/state/failover/acp-logs/`.
3. Quota at 10:20: opencode-go 8.3% (monthly), claude default 6-7%, antigravity/gemini 1.2%,
   claude Fable 1%; codex, cursor, copilot, grok, pi, muse have no `aiuse` window.
4. Adversary verdicts: strip change FIX-THEN-OK twice (fixed), crush deny FIX-THEN-OK (queued).

## Operator Feedback
1. "Fix the chain after everything else is done."
2. "Do 1 [strip with review]. Also we should always use sipb via crush acp (or the direct
   route, but tell me what that means)"; then "do direct, failover to crush acp".
3. "you are allowed to deplete all pools except claude which can be 5% for now."
4. "Admit 1, get crush to work. Also is hermes being included? Don't leave out anything due to
   security concerns." Then "I want crush ... any tools ... all of the TUIs and hermes ... any tools."
5. Resurface tomorrow: first night result, denied backends, the `-C` gap (queued).

## Where We're Going
1. **2026-10-14 morning, read the first night on the new chain** (03:30 launchd). Read
   `~/.local/state/skillopt-sleep/nights.jsonl` and `attempts.jsonl` (rows now have `perm`,
   `retries`), `skillopt-sleep status`; any staged proposal needs `preadopt-check`, a full diff and
   the operator's per-skill go before adoption. Questions to answer: did retries, the stripped
   startup, direct SIPB and `perm: all` get sources through; did crush, Hermes and the five
   new adapters run; measure prompts and tokens per source (logs have no token counts: add them).
2. Resurface with the operator (also in `docs/queue.md`, "Resurface 2026-10-14"): other
   denied backends, the `-C` strip gap, crush deny-mode findings 1-4.
3. Hermes entry caveat: Hermes' own fallback chain can reach ClinePass and Codex (paid; ClinePass
   quota was exhausted until about 2026-10-16). The Hermes one-word smoke call was skipped for that
   reason. If the operator wants Hermes kept off those, add a check/flag or drop the entry.
4. 2026-10-14: `chain-check --probe` for zcode after the z.ai reset; 2026-10-19: raise
   `max_tasks_per_night` from 20 (parent handoff items).
5. `launchctl list` shows `com.djbclark.skillopt-sleep` last exit status 1 (the 10-13 night ended
   `chain_exhausted`); expected to change after tonight.
6. Old: verify `claude mcp list` connects basic-memory and hermes in a fresh session.

## Detached jobs
none. All sub-agents of this session reported and are closed; no bigteam job records are open.

## Quick Start
```bash
cd ~/src/djbclark-ade && git log --oneline -8 | cat
skillopt-sleep status
tail -n 12 ~/.local/state/skillopt-sleep/nights.jsonl | jq -c '{at,source,status,entry,perm,retries,sessions,tasks,gate,proposals}'
bin/skillopt-night chain-check          # preflight only, no model calls
~/ops/site-private/bin/bg uv run --with pytest python -m pytest tests/test_acp_run_strip_perm_all.py tests/test_failover.py tests/test_skillopt_night.py -q > /tmp/t.log 2>&1; tail -3 /tmp/t.log
```
Dirty tree at handoff is other sessions' edits only (skills/autorename, skills/helm and two
untracked tests): do not stage them.
