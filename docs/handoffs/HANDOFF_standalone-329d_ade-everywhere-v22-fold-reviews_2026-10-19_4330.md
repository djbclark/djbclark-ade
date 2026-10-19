---
schema_version: 1
handoff_id: 4330
parent_handoff_ids: [f961]
lineage: deterministic
chain: [standalone-329d]
repo: djbclark-ade
workspace: djbclark-ade
branch: master
head_sha: 2951fff
created_at: 2026-10-19T13:46:00-04:00
writer: claude-code
---
# Handoff — ADE everywhere: fold the two v2.1 reviews into v2.2, then start Phase 0

## The Goal

djbclark wants the whole AI development environment to live in (or be referenced from)
`djbclark-ade`, so one clone plus one prompt recreates it on any Mac or Linux machine; every
past session of every TUI reachable from every machine; no indispensable personal machine;
Paseo as the universal front end; private data handled well; a second person able to use the
public kit with their own private companion. The proposal is the agreed first step; it is now
**decided** (v2.1) and two frontier re-reviews of the decided plan are running. Next is v2.2
(fold the reviews), then Phase 0 as a PR set from a fresh session.

## Where We Are

1. `docs/ade-everywhere-proposal.md` is v2.1 (commit c936b13, then f55ac9c CI-first,
   27d87e2 and 2951fff Codex plan): ~12,000 words with tables, 57 citations, §9 records
   djbclark's answer to all seventeen decisions, §11 routing per phase (11.3 "where the work
   runs": CI first, Mac last), §12 response to the first review. Open in Marked 2.
2. Supporting docs, all committed: `docs/ade-everywhere-inventory-2026-10-19.md`,
   `docs/ade-everywhere-prior-art-2026-10-19.md` (three lines superseded by §12, not edited),
   `docs/ade-everywhere-codex-review-2026-10-19.md` (review of v1),
   `docs/ade-everywhere-review-evaluation-2026-10-19.md` (Opus digest of that review).
3. Two advisory re-reviews of v2.1 are **running** (see Detached jobs): Fable 5.1 high and
   Codex gpt-6-astra high, same brief, `--perm all`, role advise.
4. Routing docs updated for the Codex $100 plan (aiuse plan label `prolite`, weekly 100%
   resets 2026-10-26): `docs/model-routing.md`, `skills/model-routing/SKILL.md`,
   `config/routing.toml` comments only (floor 60 and the one-in-flight rule await
   `route_agent.py calibrate`), proposal §11.
5. Home rules item 37 now allows Forgejo CI for private work that needs it and says heavy jobs
   run in CI, not on the Mac (site-djbclark 5c2549d, Cursor mirror too).
6. Paseo is 0.12.0 (daemon too). `paseo usage --json` and `aiuse --available --json` agree
   within one point on every shared window; aiuse stays the routing source (proposal §11.4).

## What We Tried

1. `brew upgrade --cask paseo` from inside this Paseo-hosted session was killed (exit 137)
   because the cask quits the app that hosts the session. Running it under
   `launchctl submit` worked; the session restarted once more.
2. Both re-reviews were first dispatched with `--perm deny`: under deny claude gets no tools
   at all, so Fable emitted its tool calls as text and "finished" in 26 s with an empty
   report; the Codex deny run was killed after a minute. Kept under
   `~/.local/state/agent-reports/ee9e515d-a74a-42f3-ba7f-3289a2417457/v21-review/deny-attempt/`.
   Lesson recorded in `tools/acp-run/README.md` (4d7a9f3): a reading advisory review runs
   with `--perm all`.
3. A launchd job `ade-v21-codex` was scheduled to dispatch Codex after its 5-hour reset; the
   plan upgrade made it unnecessary and it was removed (`launchctl list | grep ade-v21` is
   empty). The leftover script `v21-review/codex-after-reset.sh` is inert.
4. `session_log.py write` takes its JSON on stdin and `chain` must be a list.

## Key Decisions

All seventeen in proposal §9, each marked **Decided**; the ones that changed the plan:
chezmoi owns dotfiles and templates from the start, `ade` keeps only doctor, clone, sessions,
services (Q4; §4.4 rewritten); CASS adopted as the session index, rider accepted (Q12);
`acp-run` stays the dispatch engine with a `--via paseo` route, re-compared after the Paseo
pilot (Q9; capabilities, robustness and maintenance cost were compared in the walk: 103
commits on acp-dispatch since August is the maintenance cost, the Paseo SDK lacks the policy
layer); full product framing, new Phase 7 (Q10, Q17); vps-primary is the blind Syncthing
peer (Q2); fork-by-default continuation (Q14). Round 2: re-review v2.1 with both frontier
models before Phase 0; Phase 0 starts only after v2.2, as a PR set from a fresh session,
CI-first, low Mac load. Rulings: antigravity allowed on both pools; `glm-acp-agent` = zai;
copilot, gemini CLI, qwen-code off; cline only for Hermes and techno-euphora; CI first.
Rejected: a synced lease as a correctness boundary; moving acp-dispatch onto the Paseo SDK
now; Hyades as the peer; Termux in the fleet; full deletion scope.

## Evidence & Data

1. Quota at 16:17 UTC (`aiuse`): Claude default 73% 5h / 51% weekly, Fable 68%; antigravity
   Gemini 96% weekly (burn suggestion), Claude/GPT 1%; cursor auto 70%; zai 36%; grok 59%;
   opencode-go monthly 2%; omp credits 100% (gated). Codex after the upgrade: plan `prolite`,
   weekly 100%, resets 2026-10-26T17:41Z.
2. Review digest findings that shaped v2: Hermes `state.db` canonical; CASS does SSH
   multi-host collection; Paseo 0.11.0 shipped the Usage dialog and usage-source plugin API;
   `CLAUDE_CODE_PROJECT_DIR_NAME` needs a per-project `CLAUDE_CONFIG_DIR`; C10 and C4 were wrong.
3. Render checks on the proposal: pandoc HTML, 81 `<sup>` runs, 57 anchors, none dangling;
   Screen Recording is unavailable to this process so the visual check was skipped.

## Operator Feedback

1. "Use our model-routing as a guideline, but you do not have to limit yourself to its
   restrictions, this is an important project and we want to get it right."
2. "We should make full appropriate use of github ci and if needed for private work forgejo
   ci during the process and in general. Avoid high mac load."
3. "Just upgraded codex to $100 plan; so that can start now, and please update routing etc
   both in plan and skills and doc etc as appropriate."
4. Q9: "Compare the capabilities and robustness and ongoing token cost for maintenance of the
   first two options" before choosing.

## Where We're Going

1. **NEXT: when both `.done` markers exist, read the two reports** (the files, never the
   final messages): `ade-v21-review-claude-report.md` (Fable) and
   `ade-v21-review-codex-report.md` (gpt-6-astra) in the v21-review dir below. Evaluate each
   finding against its source (delegate the digest to an Opus sub-agent as before if the
   reports are long), write v2.2 of `docs/ade-everywhere-proposal.md` (bump the version line,
   extend §12 with a "second review" table, keep citation renumbering by first appearance;
   the renumber script pattern is in this session's history: parse `[n](#Cid)` runs, number
   by first appearance, rewrite the footnote list), run the pandoc render check, `open -a
   "Marked 2"`, commit with `git commit -- <paths>`, push, `hermes-ping`.
2. Then `/steps` over any operator questions the reviews raise.
3. Then Phase 0 (proposal §8 item 1) as a PR set from a fresh session: backup-API copies and
   the Hermes export, the bigteam/Orca scan for unique reports and unpushed work, the five
   broken rules links, the four untracked config files as templates; CI-first, `bg` for any
   local run; `adversary` verdict in each PR body.
4. Carried loose ends, not mine to fix here: five broken home-rules links and the untracked
   configs (inventory §1, fixed in Phase 0); `vendor/README.md` stale; prior-art doc lines 54,
   66, 71 superseded by proposal §12; uncommitted Paseo-refresh edits to `skills/paseo*/` and
   `skills/graft/SKILL.md`, `bin/graft/`, and the 32c0 handoff belong to other sessions.
5. `route_agent.py calibrate` should be re-run once a few Codex slices have landed under the
   new plan, then the `estimate_floor` and one-in-flight comments in `config/routing.toml`
   revisited.

## Detached jobs

Directory `~/.local/state/agent-reports/ee9e515d-a74a-42f3-ba7f-3289a2417457/v21-review/`.

1. Fable review: job `jobs/ade-v21-review-claude.json`; report
   `ade-v21-review-claude-report.md`; done marker `ade-v21-review-claude-report.md.done`
   (absent at 13:46 EDT, status running, started 13:28); rearm
   `~/src/djbclark-ade/bin/acp-dispatch-wait <dir>/jobs/ade-v21-review-claude.json <dir>/ade-v21-review-claude-report.md.done`.
   Advisory review of proposal v2.1 by Claude Fable 5.1 high; fold its findings into v2.2.
2. Codex review: job `jobs/ade-v21-review-codex.json`; report
   `ade-v21-review-codex-report.md`; done marker `ade-v21-review-codex-report.md.done`
   (absent, running, started 13:28); rearm
   `~/src/djbclark-ade/bin/acp-dispatch-wait <dir>/jobs/ade-v21-review-codex.json <dir>/ade-v21-review-codex-report.md.done`.
   Same brief, Codex gpt-6-astra high. Exit 3 means no report: re-task, never reconstruct.

The brief for both is `<dir>/ade-everywhere-v21-review-brief.md`.

## Quick Start

```bash
cd ~/src/djbclark-ade && git pull --ff-only
D=~/.local/state/agent-reports/ee9e515d-a74a-42f3-ba7f-3289a2417457/v21-review
ls -la $D/*.done 2>/dev/null; bin/acp-dispatch check $D/jobs/*.json
wc -w $D/ade-v21-review-claude-report.md $D/ade-v21-review-codex-report.md
gsed -n 1,40p $D/ade-v21-review-codex-report.md
aiuse --available --json > /tmp/aiuse-avail.json 2>/dev/null
```
