---
schema_version: 1
handoff_id: f961
parent_handoff_ids: []
lineage: none
chain: [standalone-329d]
repo: djbclark-ade
workspace: djbclark-ade
branch: master
head_sha: 9adc552ba5619f49bf9424ad6a4e04fcff4f3ff7
created_at: 2026-10-19T19:40:00-04:00
writer: claude-code
---
# Handoff — ADE everywhere: revise the proposal to v2 from the Codex review

## The Goal

djbclark wants the whole AI development environment to live in (or be referenced from)
`djbclark-ade`, so that on any new machine one clone plus one prompt recreates it; every past
session of every TUI is reachable from every machine; no central node beyond GitHub, Forgejo and
Hyades; Paseo as the universal front end; private data handled well; a second person can use the
public kit with their own private companion. Step one is a proposal document opened in Marked 2.

Delivered so far: proposal v1 plus evidence (commit 8d1cad5). Then djbclark asked for a Codex
`gpt-6-astra` review with extensive web search, and for this session to evaluate its findings,
research more where needed, add its own opinions and changes, regenerate the proposal (v2), and
add a per-step routing table (vendor, model version, effort, context/cache size) based on
`aiuse --available --json`, remembering the $200 Claude plan has more headroom than it looks and
that model-routing is a guideline, not a limit, for this project.

## Where We Are

1. Proposal v1: `docs/ade-everywhere-proposal.md` (5,700 words, 38 citations).
   Evidence: `docs/ade-everywhere-inventory-2026-10-19.md`,
   `docs/ade-everywhere-prior-art-2026-10-19.md`.
2. Codex review done (gpt-6-astra, kind frontier, 18 minutes): 20 findings (2 blockers, 17 major,
   1 minor), 30 citation checks, two citations found wrong. Copied into the repo as
   `docs/ade-everywhere-codex-review-2026-10-19.md`; original plus `evidence/` subdirectory at
   `~/.local/state/agent-reports/ee9e515d-a74a-42f3-ba7f-3289a2417457/codex-review/`.
3. This session ends with a Paseo upgrade to 0.12.0 and a daemon restart that djbclark chose
   ("Upgrade now from the GitHub release"; Homebrew's cask reached 0.12.0 during the session, so
   the route is `brew upgrade --cask paseo`). The v2 revision has NOT been started.

## What We Tried

1. Screen capture of the Marked 2 window for the render check failed ("could not create image"):
   this Paseo-hosted process has no Screen Recording permission. Verified the render through
   pandoc HTML instead; recorded in `skills/report/SKILL.md` (commit 9adc552).
2. `paseo usage` does not exist in 0.11.4 (shipped in 0.12.0, released 2026-10-19), so the
   requested comparison of `paseo usage` against `aiuse --json` could not run yet.
3. `aiuse --available --json` briefly omitted antigravity (a fail-closed frozen reading); a later
   run lists it. My first provider table to djbclark was wrong on that row; corrected.

## Key Decisions

1. djbclark, routing for this project: antigravity (`agy`) allowed on both pools (Gemini and
   Claude/GPT), whichever aiuse shows usable; Paseo's `glm-acp-agent` is the same quota as `zai`;
   copilot, gemini CLI and qwen-code are configured in Paseo but deliberately off for now; cline
   only for Hermes and techno-euphora; respect aiuse's disabled list.
2. djbclark: upgrade Paseo to 0.12.0 now, accepting the daemon restart ends this session.
3. Mine, in v1 (recommendations, not rulings; the review challenges several): own `ade` CLI over
   chezmoi/Nix; Syncthing per-host archive with rebuilt indexes; Paseo replaces Orca and herdr's
   agent plugins after parity; `acp-run` stays the dispatch engine.

## Evidence & Data

1. Quota at 2026-10-19 ~19:00 (`aiuse --available --json`, remaining %): claude default 52 weekly
   / 79 five-hour; claude fable 69 weekly-Fable; codex 82 weekly / 100 five-hour; antigravity
   Gemini 96 weekly / 100 five-hour, Claude-GPT 1 weekly (resets 2026-10-24); cursor auto 69,
   third-party 8; grok 59; grok-bot 88; zai 36; opencode-go monthly 2; omp credits 100 (needs
   operator approval per run). `cswap list`: 5h 21% used, 7d 48% used, Fable 31% used.
2. `route_agent.py plan --kinds judgment,frontier,code,code,research,bulk,mechanical` routes
   judgment to claude opus high, frontier to codex gpt-6-astra high, code to claude sonnet high,
   research/bulk to agy gemini-3.8-flash, mechanical to cursor auto. Agent model menus collected
   in `/tmp/acp-info.log` (agy lists gemini-4-argon-{low,medium,high}, gemini-3.8-flash-*,
   claude-opus-5-5-*; grok-4.7 256k context; cursor exposes a context-size option).
3. Verified facts that change v2: Claude Code `CLAUDE_CODE_PROJECT_DIR_NAME` (with
   `CLAUDE_CONFIG_DIR`, v2.1.234+) names the project directory independently of the path, and
   `--resume` finds sessions under either name; a `SessionEnd` hook receives `transcript_path`
   (https://code.claude.com/docs/en/sessions). Syncthing receive-encrypted folders are marked
   beta (https://docs.syncthing.net/users/untrusted.html). Paseo 0.12.0 adds `paseo usage`,
   background workspaces, and a fix for settings saves replacing a symlinked `config.json`;
   provider entries accept per-provider `env` and a custom binary
   (https://paseo.sh/docs/custom-providers.md); agent profiles are saved per host with no
   documented export (https://paseo.sh/docs/agent-profiles.md).
4. Review headline corrections to carry into v2: F1 a synced lease cannot be a correctness
   boundary (needs identity, generations, acknowledged transfer); F2 Hermes `state.db` is
   canonical and has `hermes sessions export`; F3 T4 overpromises; F5 use Claude's stable project
   key instead of path surgery; F10 provider survey stale; F11 CASS already does SSH multi-host
   collection and search; F13 Paseo already has usage and attention views; F15 an ADE CLI is
   justified, a new general provisioner is not yet; F17 Linux and root of trust too late; F19 prove
   preservation before cleanup. Wrong citations: C10 (LiteFS thread says not discontinued) and C4
   (issue 57920 is about a deleted worktree, not duplicate ids).

## Operator Feedback

1. "Use our model-routing as a guideline, but you do not have to limit yourself to its
   restrictions, this is an important project and we want to get it right."
2. "aiuse --json has a purposefully limited subset of the TUIs/agents available, and you should
   respect those limitations."
3. "aiuse does list it, as agy" (antigravity): verify a tool's full output before reporting a gap.

## Where We're Going

1. **NEXT: compare `paseo usage --json` with `aiuse --available --json`** on the upgraded daemon
   (`paseo daemon status --json` must say 0.12.0): do the numbers agree per provider, which is
   more useful, note that only aiuse carries policy (disabled list, approval gates). Report to
   djbclark in one numbered list.
2. Read `docs/ade-everywhere-codex-review-2026-10-19.md` in full (6,900 words). For each of F1 to
   F20 decide accept / accept with change / reject with reason; research where the review and v1
   disagree (CASS at https://github.com/Dicklesworthstone/coding_agent_session_search, Hermes
   sessions export, Paseo attention views, SQLite online backup, Claude stable project key).
3. Write `docs/ade-everywhere-proposal.md` v2: keep the structure, fix the two wrong citations,
   add a "Review response" section (finding, decision, change), rework §6 (identity model,
   store classification table canonical/derived/cache/mixed, preservation-first), §7 (build the
   ADE delta, not what Paseo 0.12 has), §8 (two-machine restore-and-resume trial and the
   newcomer empty-companion trial before any cleanup; Linux earlier), and add §11 "Routing per
   phase": a table of phase, slice kind, vendor, model version, effort, context/cache size,
   quota pool and headroom, from `aiuse --available --json` and the rulings above. Suggested
   shape: judgment and integration on Claude Opus 5.5 high; frontier reviews on codex
   gpt-6-astra high and Fable 5.1 high (one each per phase gate); code on Claude Sonnet 5.5 high
   with 1M context only for whole-archive refactors; research on agy gemini-3.8-flash high while
   its Gemini pool is near 100; bulk and mechanical on cursor auto or zai GLM-5.3 Flash low;
   never copilot, gemini CLI, qwen-code, cline, hermes.
4. Run the `report` skill checks on v2, open it in Marked 2, commit and push, `hermes-ping`.
5. Then walk the proposal's §9 decisions (Q1 to Q11, plus the review's operator questions) with
   `/steps`.
6. Carried loose ends, not mine to fix here: five broken home-rules links and the untracked
   configs (inventory §1); `vendor/README.md` says helm and the hooks live elsewhere (stale);
   uncommitted Paseo-refresh edits to `skills/paseo*/SKILL.md` and `.paseo-managed-files.json`
   belong to Paseo's managed-skill refresh, leave them for the session that owns Paseo skills.

## Detached jobs

none (the Codex review record `.../codex-review/jobs/ade-everywhere-review.json` is finalized,
status done, exit 0; nothing is running).

## Quick Start

```bash
cd ~/src/djbclark-ade && git pull --ff-only
paseo daemon status --json | python3 -c "import json,sys; print(json.load(sys.stdin).get('daemonVersion'))"
paseo usage --json > /tmp/paseo-usage.json 2>/tmp/paseo-usage.err; echo "rc=$?"
aiuse --available --json > /tmp/aiuse-avail.json 2>/dev/null
gsed -n 1,60p docs/ade-everywhere-codex-review-2026-10-19.md
```
