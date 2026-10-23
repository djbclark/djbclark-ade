---
schema_version: 1
handoff_id: 869e
parent_handoff_ids: []
lineage: none
chain: [standalone-869e]
repo: djbclark-ade
workspace: main
branch: master
head_sha: a5fe7ec
created_at: 2026-10-23T11:45:00-0400
writer: claude-code
---
# Handoff — relay.py route ladder with automatic fallback (shipped, one review pass owed)

## The Goal
djbclark: "Update relay.py so it automatically uses the best messaging option for any given situation, and tries to
fallback itself before returning an error. Then make sure every TUI knows to use it." Standing rule since: handoff and
continue automatically at the end of a session, without asking (djbclark, 2026-10-23).

## Where We Are
Done and pushed to origin/master: `3ffa82e` (relay ladder, SKILL.md, tests, CHANGELOG) and `cc07c5a` (round-6 repairs).
Home instructions (item 24 in `~/ops/site-djbclark/home-agents.md` and `cursor/home-agents.mdc`) were pushed earlier.
Every TUI already links the repo copy of session-finder (`bin/skill-everywhere --check session-finder`: all linked;
Grok Bot not installed here). 133 relay tests pass: `python3 -m unittest tests.test_session_relay tests.test_relay_paseo
tests.test_relay_fallback` through `~/ops/site-private/bin/bg`.

Route order in `skills/session-finder/relay.py`: `paseo` (a Paseo-hosted agent: its only route), `dispatch`
(`acp-dispatch tell`), `launch` (live interactive ACP inbox), `pane` (keys into herdr/Orca/tmux, verified in the
transcript), `socket` (Claude messaging socket, fallback only). `--plan` prints the order, `--via ROUTE` limits it.
Results: ok / skip (provable non-send, try next) / stop / unverified (sent but unprovable: exit 1, never falls back,
"Do not resend"). Hard stops never fall back: self, finished, blocked, a Paseo agent Paseo cannot confirm.

## What We Tried
1. Socket before pane: a frame to an idle session is not proven to wake it (Claude stores it only when it absorbs it),
   and pane-then-socket could deliver twice. Rejected; pane is first, socket is the fallback only when the pane provably
   did not take the text.
2. "Absent" vs "failed" typing CLI: a timeout is "failed" (text may be typed), only a CLI that could not start is
   "absent". Without this a timed-out send-text fell through to the socket and duplicated.
3. UNSENT as bare text then as `{text, draft, mark, at}` with a 3600 s TTL: needed so a retry never types a second copy
   and never presses Enter on the operator's draft. Six adversary rounds each found a new hole in the Enter decision:
   `[Pasted text` accepted as ours (r4/r5), a 12-char middle-piece `holds` rule (r6; the r5 review itself proposed it),
   `draft()` seeing only the first box row (r6), "+N lines" placeholders (multi-line pastes) accepted (r6).

## Key Decisions
1. Enter is pressed only on a box that is our text, its visible beginning, or (after "…") its tail, plus any rows
   below the ❯ line (`box_text`, `rows_below`), or our exact recorded paste placeholder `[Pasted text #N]` for a text over
   800 chars (`PASTE_MIN`). Never a middle piece, never "+N lines".
2. Loose "stuck" detection (first 30 chars agree) only arms the leftover; the strict test (`box_state`) decides Enter.
3. Entries clear only on proof (`retry_leftover` ok) or `forget(sid, text)` for the same text; an Enter that empties the
   box keeps the entry so the exact retry proves delivery from its stored transcript mark.
4. Same text already in the box with an expired entry returns unverified, never the socket.
5. Socket success: a working session is "accepted" at once; any other status is verified in the transcript by the
   enveloped whole body, else unverified.
6. In-loop proof now searches the whole JSON-escaped text (`probe_of` removed).

## Evidence & Data
Adversary reports (all BLOCK, severities falling medium -> low): `~/.local/state/bigteam/adhoc-2026-10-23/
relay-ladder-adversary-report.md`, `-report-2.md` ... `-report-6.md`. Round 6 reviewed relay.py sha1 c3252d0e69c1;
`cc07c5a` repairs it. Mutation check done by hand for the holds guard (the two new tests fail when it is loosened).
Peer message to rework-2 lead (1dddc3ac) delivered through `relay.py --idle 120` (Paseo route, "accepted").
Scratch: `/tmp/relay-work/` (test logs t1-t11, patch scripts); disposable.

## Operator Feedback
1. "You can just automatically handoff and continue in the future" (2026-10-23): no Rule-4 closing question.
2. Earlier this session: `-pw` workspace naming, adversary report kept, `autoArchiveAfterMerge` in the Ansible role.

## Where We're Going
1. THE next action: run one narrow seventh adversary pass (Opus, `adversary` agent, read-only) on the `cc07c5a` repairs
   in `skills/session-finder/relay.py` (`box_text`, `rows_below`, `box_state`, `holds`, `ours_paste`, the `stale`
   check in `route_pane`), plus the mutation gaps from `relay-ladder-adversary-report-6.md` items 7.1-7.4 (tests exist
   for most; verify). Fix by editing relay.py and tests, rerun the 133 tests via bg, commit by path, push.
2. Unproven: whether a socket frame wakes an IDLE Claude session; the code returns "unverified" if the text does not
   appear in the transcript. A live probe against a throwaway idle Claude session would settle it.
3. Known residuals: the operator's own single-line paste over 800 chars during a long relay's window; a hard-wrapped
   long URL in a leftover makes `holds` fail safe (no Enter). Exit code 1 still means both "not sent" and
   "unverified"; callers (`bin/load-watch`, `bin/session-load-watch`, site-djbclark `bin/fleet-watch`) read only 0/non-0.
   A distinct exit code or `--json` use in fleet-watch would let them honour "do not resend".
4. Memory entry about the relay ladder rules (written this session: `relay-route-ladder-rules`).

## Detached jobs
none

## Quick Start
```bash
cd ~/src/djbclark-ade && git log --oneline -5
python3 -I skills/session-finder/relay.py --plan <id>      # route order for a session
~/ops/site-private/bin/bg python3 -m unittest tests.test_session_relay tests.test_relay_paseo tests.test_relay_fallback
```
Not mine in this checkout: `.agents/skills/fastino-glide/` (untracked). Branch master, head a5fe7ec at write time;
the checkout is shared with other sessions (pointer `djbclark-ade/main` belongs to chain standalone-329d, listed here
as a side workspace).
