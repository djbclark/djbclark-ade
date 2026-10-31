---
schema_version: 1
handoff_id: cf8f
parent_handoff_ids: [4330]
lineage: deterministic
chain: [standalone-329d]
repo: kool-ade
workspace: kool-ade
branch: master
head_sha: 2d528aa
created_at: 2026-10-19T15:16:22-04:00
writer: claude-code
---
# Handoff — ADE everywhere v2.3 decided (all 25 questions); next is Phase 0 as a PR set

## The Goal
Move the whole AI development environment into `kool-ade` so one clone plus one prompt recreates
it on any machine, every past session of every TUI reachable everywhere, no central node beyond
GitHub/Forgejo/Hyades, Paseo as the universal front end, private data handled well, a second person
can set it up. The proposal `docs/ade-everywhere-proposal.md` is the plan; implementation starts with
Phase 0 (§8 item 1) **from a fresh session, as a PR set** (djbclark, 2026-10-19, round 2).

## Where We Are
1. Proposal **v2.3, status decided**, commit 0bcae91: Q1-Q25 all answered in §9 (9.1 rounds 1-2,
   9.2 round 3). Opened in Marked 2. Hermes pinged.
2. Both v2.1 frontier reviews landed and are in the repo:
   `docs/ade-everywhere-v21-review-fable-2026-10-19.md`, `docs/ade-everywhere-v21-review-codex-2026-10-19.md`
   (11827ba); merged, verified digest `docs/ade-everywhere-review-evaluation-v21-2026-10-19.md`
   (e9ccc78, G1-G17, three blockers, four Fable claims refuted). v2.2 (f4e032b) applied G1-G17 and
   §12.2; v2.3 (0bcae91) applied the round-3 answers.
3. acp-run fix landed and was reviewed: 3cd8892 adds `--perm read-only` (claude, codex, opencode,
   zcode), acp-dispatch refuses `--role advise --perm deny`, and a reply of tool calls printed as
   text fails the delivery check (`FAILED fake-tool-calls`, exit 1, never recovered as done). Live
   smoke on all four agents in its report; 481 tests green. `graft build` run after it.
4. No detached jobs open. Nothing of Phase 0 implemented.
5. **self-slash works in Paseo** (2d528aa, same day, on djbclark's "super important" ask): a
   Paseo-hosted session compacts itself and hands off then `/new` (sent as `/clear`) through
   `paseo wait` + `paseo send` with `PASEO_AGENT_ID` unset; the context hook and autorename know
   the host; proposal 7.2 rows and the Phase 4 gate record it. Verified on a scratch agent; this
   session's own `/new` after this handoff is the first live use on a real session (check
   `~/.local/state/self-slash.log` for "paseo … sent /clear").

## What We Tried
1. Both v2.1 reviews first dispatched with `--perm deny`: Fable printed tool calls as text in 26 s and
   was recorded done; Codex deny run killed. Cause: deny strips every tool. Fixed in code (3cd8892),
   not just the README (4d7a9f3). Use `--perm read-only` for any reading advisory review.
2. `--perm deny` artefacts kept under `~/.local/state/agent-reports/ee9e515d-.../v21-review/deny-attempt/`.

## Key Decisions
Round 3 (djbclark, 2026-10-19, via `/steps`), recorded in §9.2:
1. Q18 **vps-primary is trusted, reversing Q2**: holds the key, indexes plaintext, runs the builds.
2. Q19 companion = data + templates + optional second chezmoi instance on disjoint paths (chezmoi
   cannot layer two source states; "private wins" is gone).
3. Q20 **shim `claude` and `codex`** so hand launches consult the transfer record (against the
   recommendation; pass-through `exec`, parses only resume flags and session ids).
4. Q21 `--with-work` is a live-origin convenience; dirty work is outside the loss window; revisit after Phase 2.
5. Q22 **standard Homebrew curl-pipe install, trust TLS** (against the recommendation; no `.pkg` rule).
6. Q23 CASS from a pinned main commit over a native-per-device view; the generation tree is the record.
7. Q24 first release: macOS arm64 + Linux x86_64 (vps-primary verified x86_64, Linux 6.18.56),
   dedicated release key in the secret backend, name `ade-kit` (PyPI `ade` is taken).
8. Q25 all generations 30 days, then latest per session plus every generation a fork or transfer names.
Earlier rulings still in force: CI-first, low Mac load (§11.3); routing per §11 (Codex $100 plan,
antigravity allowed, copilot/gemini/qwen off, cline only Hermes/techno-euphora, omp explicit yes);
Phase 0 from a fresh session as a PR set with an `adversary` verdict per PR.

## Evidence & Data
1. v2.3: 15,516 words; 75 citations, 103 superscripts, pandoc render with no dangling anchors.
2. Sub-agent reports (read these, never final messages), all under
   `~/.local/state/agent-reports/ee9e515d-a74a-42f3-ba7f-3289a2417457/`: `v21-digest-report.md`,
   `v22-fold-report.md`, `v23-fold-report.md`, `acp-run-readonly/acp-run-readonly-perm-report.md`,
   `v21-review/jobs/*.json`. Fold briefs: `v22-fold/brief.md`, `v23-fold/brief.md`.
3. Memory: `~/.claude/projects/-Users-djbclark-src-kool-ade/memory/project_ade_everywhere_proposal.md`.

## Operator Feedback
1. "We should fix acp-run" (done, 3cd8892). Open the latest plan in Marked 2 when a version is done (done each time).
2. Q22: "You can just use the regular unverified piping to shell install that everyone uses. We'll trust the web site's SSL cert."
3. Q24: asked to check vps-primary's architecture before committing to x86_64 (checked: x86_64).

## Where We're Going
1. **NEXT: Phase 0 (proposal §8 item 1) as a PR set from a fresh session.** Read §8 Phase 0 and §4.4
   adoption snapshot, §6.1 inventory (G16: per-store inventory incl. Cline, Qwen, Muse, Grok,
   Antigravity, omp, Paseo, Hermes export limit), T1. Each PR: branch, CI runs the tests (GitHub
   Actions; `load-watch ci decide` before any local run; local via `~/ops/site-private/bin/bg`),
   `adversary` verdict quoted in the PR body, `acp-dispatch --kind` slices on Sonnet 5.5 / Codex
   per §11.2. Nothing is deleted in Phase 0; it preserves and classifies.
2. After the first Codex slices under the $100 plan: `route_agent.py calibrate`.
3. Carried loose ends (not blocking): five broken links in `~/ops/site-djbclark/home-agents.md`
   (`rg -o '\[\[[^]]+\]\]'` and check each target); untracked configs in this repo that are not mine
   (`skills/paseo*/`, `skills/graft/SKILL.md`, `bin/graft/`, `HANDOFF_standalone-32c0_…quota.md`:
   another agent's, leave alone); stale `vendor/README.md`; prior-art doc lines 54/66/71 superseded by
   §12 (the proposal says so; the doc itself is unchanged).

## Detached jobs
none

## Quick Start
```bash
cd ~/src/djbclark-ade && git pull -q && git log --oneline -3
gsed -n '/^## 8\. Phases/,/^## 9\./p' docs/ade-everywhere-proposal.md | head -80   # Phase 0 gate
aiuse --available --json 2>/dev/null | head -40
~/src/djbclark-ade/bin/load-watch ci decide
```
