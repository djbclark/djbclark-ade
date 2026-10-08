---
schema_version: 1
handoff_id: 8bed
parent_handoff_ids: []
lineage: none
chain: [standalone-265e]
repo: djbclark-ade
workspace: djbclark-ade
branch: master
head_sha: e28aa35
created_at: 2026-10-08T10:45:45-0400
writer: claude-code
---
# Handoff — helm console built (2026-10-06), handed to coord (2026-10-08)

## The Goal
One window (a Claude session, or Hermes on Telegram) from which every waiting agent
session is answered: run `/steps` everywhere, `/loose` when a session is done, show each
pending decision with summary, recommendation and options, titled by project and location,
token-efficiently. Built 2026-10-06 as the `helm` skill; design record `docs/helm.md`.

## Where We Are
1. `helm` shipped 2026-10-06 (`~/ops/site-djbclark/skills/helm/`: `SKILL.md`, `helm.py`),
   linked into 11 TUIs by skill-everywhere, documented in `docs/helm.md`, pointer in
   `AGENTS.md` and `vendor/README.md`. fleet-watch (site-private `bin/fleet-watch`) sends a
   Hermes line when a session newly waits (`helm.py brief`; still works with coord's
   helm.py, checked 2026-10-08 10:40).
2. Since 2026-10-07 the herdr tab `coord` (Claude session `one-offs-42`) owns helm, helm-all,
   session-finder and session-finder-all and has rebuilt helm (fleet.py, launch.py over ACP,
   ranked walk, ended sessions). **Coord has precedence; it wins conflicts.** This session
   sent coord a handover note (2026-10-08 ~10:30) and edits none of those files any more.
3. Telegram: Hermes registered `/helm` on 2026-10-06; on 2026-10-08 djbclark reports `/helm`,
   `/steps` and `/skill` no longer work there. See `docs/helm.md` Open #4 for the state of
   that investigation (my first diagnosis was wrong and is retracted there).
4. This session's remaining untested paths (Orca/tmux key channels, unattended
   `wait --auto-audit`) were handed to coord and dropped here (djbclark, 2026-10-08).

## What We Tried
1. Diagnosing the Telegram regression as a `tools.override` capability gate after the Hermes
   upgrade (`ad9678e6`, 2026-10-08 09:25). Wrong: `hermes-worktrees-e5` verified that the
   `decision=deny` log lines are a discovery pass written for every user plugin and that
   `register_command` is not gated. Real lead: Hermes CLI session `20261008_100648` was editing
   `~/.hermes/plugins/skill-slash/__init__.py` at 10:06.
2. Answering a herdr prompt by key before it rendered: the key lands in the input box. Fixed
   in helm.py (screen check) and recorded in
   `~/ops/site-djbclark/skills/herdr-orchestration/references/herdr-cli-gotchas.md`.
3. A one-character session id prefix matched the wrong session: helm matches exact id/name only.

## Key Decisions
1. Sessions run their own `/steps` and `/loose`; helm relays and never answers for the
   operator (rejected: agent-deck's conductor, which auto-responds).
2. Location site-djbclark skills + doc here; Telegram via a Hermes skill plus Collie;
   ccgram deferred (djbclark, 2026-10-06).
3. Cold-cache guard: no automatic audit of a session idle > 55 min.
4. New operator rule 2026-10-08: run the `loose` sweep silently before every `/handoff`
   (handoff skill Step 0; `memory/feedback_loose_before_handoff.md`).

## Evidence & Data
1. Verified 2026-10-06 on scratch sessions: digit answers, free text, two-question prompts,
   refusals, audit loop; details in `docs/helm.md` "Verified".
2. herdr: a finished turn in an unviewed pane is `done`, not `idle` (by design; gotchas file).
3. Hermes gateway pid 99342 started 2026-10-06 15:27 (code unchanged since, per
   hermes-worktrees-e5); skill-slash plugin files parse fine.

## Operator Feedback
1. Numbered lists, hierarchical labels; coord has precedence on helm (2026-10-08).
2. Silent `/loose` before `/handoff` (2026-10-08) — now in the handoff skill.
3. The `sk-…` string in a 2026-07-22 opencode transcript: "already rotated, ignore".

## Where We're Going
1. **Telegram `/helm` regression** — djbclark restarted the gateway at 11:27 on 2026-10-08
   and `/helm`, `/steps`, `/skill` still fail. agent.log 11:27:58: "Telegram menu: 60
   commands registered, 100 hidden (over 60 limit)" — the 60-command cap or a collision
   with the core's per-skill auto-registration is the lead, not `tools.override`. A
   detached Hermes one-shot (`hermes --yolo -z`, pid 59939, log
   `~/.local/state/helm/telegram-commands-fix.log`, prompt beside it) owns the fix and
   reports to the Telegram Inbox. Check that log first; if it failed, rerun the prompt file
   with `hermes --yolo -z "$(cat ~/.local/state/helm/telegram-commands-prompt.txt)"`.
2. site-djbclark: nothing pending; the handoff-skill commit reached origin as `c692119`
   (a peer rebased the shared checkout).
3. Run the Telegram `clarify` walk of `/helm` once it works (`docs/helm.md` Open #3).
4. Coord owns: Orca/tmux key channels, `wait --auto-audit` live, helm-all. Nothing here.
5. Not mine, left alone: `~/ops/site-private/memory/memory/` (stray untracked dir),
   `bin/__pycache__/` there.

## Quick Start
```bash
cat ~/src/djbclark-ade/docs/helm.md            # design, verified, limits, open
python3 -I ~/ops/site-private/skills/helm/helm.py scan   # the live queue
git -C ~/ops/site-djbclark status -sb          # is the blocked push free yet?
```
