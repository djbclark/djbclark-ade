---
schema_version: 1
handoff_id: 9ec0
parent_handoff_ids: [dc33]
lineage: deterministic
chain: [standalone-dc33]
repo: djbclark-ade
workspace: main
branch: master
head_sha: 828dd462e22a72ce884e46f51d27ea6f66b24ea0
created_at: 2026-10-12T20:12:30-0400
writer: claude-code
---
# Handoff — SkillOpt-Sleep fleet rollout, failover chain, acp-run deny fix

## The Goal

Operator ask (2026-10-12): "Implement https://microsoft.github.io/SkillOpt/
across all agent runs / all of my projects." Interpreted and approved as:
SkillOpt-Sleep (the deployment companion) running nightly over every agent
TUI's transcripts on this Mac, staging validation-gated edits to the canonical
skills in this repo, model calls through a long failover chain with a reusable
failover layer, never adopting by itself.

## Where We Are

Live. `launchd` `com.djbclark.skillopt-sleep` runs `bin/skillopt-night` at
03:30 (06:30 wall-clock deadline, load gate before each source and attempt).
`~/.skillopt-sleep/night.json` has `"enabled": true` with the approved
nine-entry chain; `config.json` has `projects: "all"`, `multi_skill_fanout`,
`gate_no_regression`, `max_tasks_per_night: 20`, `exclude_projects: []`
(deliberate). Sources: claude, codex (shim for `~/.codex/sessions/Y/M/D`),
cursor, opencode, copilot_cli natively, plus adapters in
`bin/skillopt_sources.py` for zcode (`~/.zcode/cli/db/db.sqlite`), agy
(`~/.gemini/antigravity*/conversations`, protobuf steps) and crush
(`crush.db`); pi dropped. Every entry runs SkillOpt's `handoff` backend with
`bin/failover.py` answering each prompt via `acp-run <tui> -f <0600 file>
--perm deny` in an empty temp dir, or a SIPB POST (key from sudo-secretspec,
cached per process, https/loopback only, no redirects).

Supervised runs (both exit 0, nothing staged, nothing adopted): A = claude
source, 10 sessions, answered by SIPB deepseek-r1:32b, 6 rounds, 17 prompts,
3 tasks, gate 0.95 to 0.95; B = claude source, 40 sessions, answered by claude
sonnet low, 56 rounds, 141 prompts, 458k tokens, 20 tasks, held-out 0.056 to
0.056. Records: `~/.local/state/skillopt-sleep/nights.jsonl`.

Canary readiness at close: held on opencode minimax-m3, agy gemini-3.8-flash
(reads_ok policy), SIPB qwen3-coder:30b, SIPB deepseek-r1:32b. Not ready:
claude haiku/sonnet (pool at the 15% floor), crush (unasked `glob`, strict),
zcode (z.ai weekly exhausted until 2026-10-14), agy claude_gpt (exhausted).

Tests: 976 pass through `~/ops/site-private/bin/bg uv run pytest -q tests/`
(965 confirmed independently by this session before the last two commits);
ruff and basedpyright clean. All commits pushed. Dirty files in the tree
(`skills/autorename/*`, `skills/helm/*`, two untracked tests) belong to other
sessions.

Upstream: microsoft/SkillOpt issues #312 (per-project checkpoint), #313
(unenforced `max_tokens_per_night`), #314 (pluggable sources/backends, PR
offered); evidence comments + subscriptions on PR 282 and issue 286.
Installed `skillopt` pinned at 343db229dbd5ddaf9df6b1d5540d8bcdb2604d5c; the
runner's `REVIEWED_REV` refuses any other installed commit.

## What We Tried

1. Native SkillOpt backends per chain entry: rejected, `get_backend` is a fixed
   if-chain and an unknown name silently becomes mock, so the handoff backend
   plus acp-run is the single code path (`--native` escape hatch, refused under
   bypassPermissions).
2. `acp-run --perm deny` as the tool boundary: adversary review proved it set
   no restrictive mode for claude (inherited bypassPermissions), zcode (yolo),
   crush (`--yolo` always) and opencode (no permission block); a canary created
   a file with zero prompts. Fixed at the root in `tools/acp-run/acp-run`
   (DENY_SET per agent, `--disallowedTools`/`--tools ""` paths, tripwire exit
   77, `allow_abbrev=False`, `--tripwire-exempt-kinds read,search` for agy
   only). Memory: `feedback_acp_run_perm_deny_was_not_real`.
3. Strict canary for agy: refused it twice (first its writes asked and were
   denied, then an unasked `view_file`); operator chose to allow unasked
   read-only calls for agy only (`reads_ok`, registry-only, chain files cannot
   loosen it). Documented exfiltration risk: a read can leak file content into
   answers and staged edits; `preadopt-check` does not flag content.
4. First supervised run on the native 8-round cap: too low for dependent
   prompts; now a 60-round backstop with a stuck-round guard. A refused answer
   sank a 20-minute opencode attempt; a refusal now counts as an answer. A
   false "staged 1 proposal" ping; proposals now counted from the staging
   manifest.
5. Upstream codex harvester reads only `~/.codex/archived_sessions`; runner
   builds a symlink shim nightly and passes `--codex-home`.
6. Upstream harvest checkpoint is per project, so the second source of a night
   skipped history; runner keeps per-source cursors and swaps them into
   state.json.

## Key Decisions

1. Chain, not one pool (operator): no cursor, cline, hermes, muse, pi, grok,
   codex, copilot, Opus or Fable; roster zcode, agy, OpenCode Go, Claude
   Haiku/Sonnet, crush, SIPB last. Order: opencode minimax-m3 (kimi-k3 slower,
   4x tokens in the 2026-08-22 bake-off), agy gemini-3.8-flash-medium, agy
   claude-sonnet-5-5-low, zcode thought=low, claude haiku low, claude sonnet
   low (floor 15%), crush default, sipb qwen3-coder:30b, sipb deepseek-r1:32b.
2. Exclude no projects from harvest (operator), with strengthened redaction
   (PEM, prose passwords, high-entropy tokens).
3. `max_tasks_per_night` 20 for the first week (lead, on the spend warning);
   raise on 2026-10-19.
4. Adoption requires the operator's per-skill go in the current conversation,
   after `skillopt-night preadopt-check <proposal>`; `auto_adopt` never.
5. Rejected: upstream Claude Code plugin marketplace (duplicates our skill
   chain); SkillOpt's crontab scheduler (launchd convention); LiteLLM prepaid
   models in the chain (operator roster).
6. crush stays refused (strict canary; unasked read `glob`); zcode fail-closed
   until its canary holds after the 2026-10-14 reset.

## Evidence & Data

- Reports (session scratchpad, gone with the session): the worker's and the
  adversary's full reports; their substance is in `docs/skillopt-sleep.md`,
  `docs/failover.md`, `docs/upstream-issues.md` 14-16.
- Harvest over full history, 120-session cap: claude 120/40 tasks, codex
  120/40 via shim, cursor 96/40, opencode 54/32, copilot_cli 31/28; adapters
  zcode 62 digests, agy 275, crush 12.
- Pools at close (aiuse): OpenCode Go 24% monthly; Claude weekly 15% (floor);
  Gemini weekly 15%; z.ai weekly 0% (resets 2026-10-14); Fable sub-cap ~5%.
- Adversary findings: C1 critical, H1-H3, M1-M5, L1-L5, re-verification R10
  (argparse abbreviation bypass) and R3 (zcode tool list, MCP); all fixed.
- Commits this session on djbclark-ade: 06ed46c .. 828dd46 (about 60).
  site-private 7519213 (two memory notes).

## Operator Feedback

1. Failover chains for unattended model work, every pool represented, grok
   then codex last; later narrowed to the roster above. Memory:
   `feedback_background_optimizer_backend_chain`.
2. "Make sure no one else is working on it" before building; "implement so
   it is not super-hard to add fallback to other things and more TUIs"
   (`bin/failover.py` registry).
3. Microsoft's code is trustworthy: confirmed, every security finding was in
   our wrapper, not upstream.
4. Both supervised runs "in succession now", after the adversary review.

## Where We're Going

1. **Next action: morning of 2026-10-13, read the first unattended night**:
   `skillopt-sleep status --project ~/src/djbclark-ade` and
   `tail ~/.local/state/skillopt-sleep/nights.jsonl`; if a proposal is staged,
   run `~/src/djbclark-ade/bin/skillopt-night preadopt-check <proposal>` and
   show the operator the full diff; adopt only with his per-skill go.
2. 2026-10-14 after the z.ai reset: `skillopt-night chain-check --probe`; zcode
   must hold a canary that includes a basic-memory write with 0 tool calls.
3. 2026-10-19: raise `max_tasks_per_night` (config.json and
   `docs/skillopt-sleep-config.example.json`).
4. crush: unasked `glob` under non-yolo in the crush-acp PR 2450 build; search
   upstream (charmbracelet/crush PR 2450 thread, crush-acp) before filing;
   until then it stays refused.
5. agy Claude/GPT entry: fail-closed until that pool returns; then the same
   canary as agy Gemini.
6. Upstream #314: PR offered; if maintainers accept, a plugin interface would
   let `bin/skillopt_sources.py` adapters become plain plugins.
7. Old open item from dc33: verify `claude mcp list` connects basic-memory and
   hermes in a fresh session (tools enumerate in-session; not run).

## Detached jobs

none

## Quick Start

```bash
cd ~/src/djbclark-ade && git pull --ff-only
skillopt-sleep status --project ~/src/djbclark-ade
tail -5 ~/.local/state/skillopt-sleep/nights.jsonl
~/src/djbclark-ade/bin/skillopt-night chain-check --probe
launchctl print gui/$(id -u)/com.djbclark.skillopt-sleep | rg 'runs =|last exit'
aiuse --available --json | jq -r '.available[] | [.provider,(.headroom_percent|floor)] | @tsv'
```
