---
schema_version: 1
handoff_id: ce8b
parent_handoff_ids: [869e]
lineage: deterministic
chain: [standalone-869e]
repo: djbclark-ade
workspace: main
branch: master
head_sha: cec4de65ef1c3773de2e921018f177ef2e0559f6
created_at: 2026-10-23T13:05:00-0400
writer: claude-code
---
# Handoff — relay.py pane route: adversary rounds 7-9 repaired, hermes route queued

## The Goal
Parent handoff 869e: `relay.py` picks the best route for a peer session, falls back itself, and never delivers twice or
types into the operator's draft. This session finished the owed seventh adversary pass and repaired what rounds 7, 8 and
9 found. Standing rule: handoff and continue automatically (djbclark, 2026-10-23).

## Where We Are
All pushed to origin/master, tree clean (only `.agents/skills/fastino-glide/` untracked, not ours):
1. `9613508` round-7 repairs; `299a64c` round-8 repairs; `eda41d3` round-9 repairs; `711221b` and `cec4de6` queue entries
   in `docs/queue.md`. 172 relay tests pass:
   `python3 -m unittest tests.test_session_relay tests.test_relay_paseo tests.test_relay_fallback tests.test_prompt_line`.
2. Reports (all BLOCK, each repaired): `~/.local/state/bigteam/adhoc-2026-10-23/relay-ladder-adversary-report-7.md`,
   `-8.md`, `-9.md` (8 and 9 also under `~/.local/state/agent-reports/a432d308-faaa-458a-a5eb-6d0030442f01/`).
3. No round 10 was run: round 9's findings were regressions from one false assumption (below), now fixed with a test on
   the real record shape; the rest are lows, queued.

## What We Tried
1. Round 7 mediums: `box_text` read "empty" when the ❯ row scrolled out of the 14 rows read; `prompt_line` dropped any row
   starting with a hint word even when styled. Fixed with `box_parse` (None = unknown, never empty) and HINTS only on rows
   with no style codes.
2. Round 8 found the round-7 box_parse still took a rule row plus ❯ typed inside a draft as a smaller empty box, forgot an
   unsent entry on an unseen box (a retry then reached the socket: duplicate), and matched delivery by substring
   ("continue" in an assistant line). Fixed: box = the ONE rule row directly followed by a ❯ row, bottom rule last, nothing
   between; one read per `box_text`; forget only on proof; `sent_in` = a whole user or queue-enqueue message.
3. Round 9 found the round-8 `sent_in` never matched a text over 800 chars: Claude Code records a collapsed paste wrapped
   in `<pasted_content id="N">…</pasted_content id="N">` (user line and enqueue both; verified in 671 real transcripts).
   That reopened a double Enter on a recalled copy, and my 6 s PIN_WINDOW handed the operator's paste to the relay. Fixed:
   unwrap in `sent_in`, no window (the placeholder in the FIRST read after typing is ours, else none), a copy returning
   after ours left the box is a recall (`gone`), `isMeta`/`isCompactSummary` lines skipped.
4. My own failed assumption: I invented transcript shapes in the tests (bare `{"text": ...}`, then a bare string). Real
   shapes only surfaced when the round-9 adversary scanned real transcripts. Check real data first next time.

## Key Decisions
1. Unknown is not empty: `box_text` returns None when the box is not plainly in view; route_pane skips (or returns
   unverified for a retry of our own text), never types or presses Enter.
2. Forgetting an unsent entry needs proof (`seen`, or `box_text == ""`); otherwise arm with draft "" (a foreign draft
   never blocks a different text).
3. Rejected: a time window for the placeholder pin (round 9: hands the operator's paste to us); extra reads per poll.
4. Rejected: a round 10 now (diminishing; lows queued in `docs/queue.md`, "relay.py pane route: open lows after adversary
   round 9").

## Evidence & Data
1. Mutation checks on `git`-less copies (`/tmp/r7_mut.py`, `r8_mut.py`, `r9_mut.py`, may be gone): round 7 10/11 killed,
   round 8 10/11 (survivor equivalent), round 9 6/7 (survivor got a test). Tests: 133 → 172.
2. `bg` refuses non-test scripts, so the mutation scripts ran directly; test runs went through `~/ops/site-private/bin/bg`
   once, later runs were plain `python3 -m unittest` (targeted, ~30 s).

## Operator Feedback
None this session.

## Where We're Going
1. **The `hermes` route in relay.py** (asked via the load-watch session ac1d55cc as djbclark's ask; I replied "mine" and
   said I would do it next). Design and verified research: `~/.local/state/bigteam/loadgate-followup-2026-10-23/hermesbidi-report.md`
   (Q4); summary in `docs/queue.md` "`hermes` route in relay.py". `hermes --resume <sid> -z <text>`, no fallback; **verify
   the claim with a harmless test on a throwaway Hermes session first** (never djbclark's Telegram session without his yes);
   the Hermes-side skill is Hermes-owned: ask djbclark. Run it through `/bigteam` with an adversary pass before it ships.
2. Optional: the four lows queued after round 9 (enqueue labelled "delivered", short-text same-message window, one unsent
   entry per session, no real herdr/tmux capture fixture).
3. Optional: live-probe whether a socket frame wakes an idle Claude (code returns unverified if not).

## Detached jobs
none

## Quick Start
```bash
cd ~/src/djbclark-ade && git status -sb && git log --oneline -6
python3 -m unittest tests.test_session_relay tests.test_relay_paseo tests.test_relay_fallback tests.test_prompt_line
rg -n 'hermes' docs/queue.md | head
```
