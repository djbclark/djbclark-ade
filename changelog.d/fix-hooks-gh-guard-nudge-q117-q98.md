### Fixed

- Stopped `claude/hooks/adversary_marker_gate.py` and `bin/ade-gh-guard` from expanding backticks or `$(...)` inside single-quoted / ANSI-C `$'...'` shell text or already-expanded `gh` shim argv words, so PR bodies mentioning doc paths such as `` `docs/code-review.md` `` pass while active unquoted/double-quoted substitutions, operand files, stdin, and literal live APPROVE markers stay denied (#PR).
- Required `ASK_MIN_GROWTH` (16k tokens, ~2 tool rounds) before floor-clamped (`ASK_FLOOR` 80k) handoff tiers fire in `claude/hooks/context_size_nudge.py` and `bin/context-watch`, preventing fresh >80k successors on 114k–163k compaction windows from immediately re-handing off while leaving the 300k window unchanged (#PR).

### Changed

- Updated `docs/approval-window.md` section II to reflect that `roles/sudo_ask_grant` is merged on `site-public-djbclark` `master` (PRs #304/#305/#306/#309/#310/#311), adversary-reviewed, and installed live on `bigmac` (#PR).
