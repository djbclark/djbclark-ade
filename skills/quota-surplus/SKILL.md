---
name: quota-surplus
description: >-
  Spend a "use it or lose it" quota surplus before its window resets: a quota-surplus
  notice, /quota-surplus, "quota will be lost", "spend the Argon/astra/Fable quota
  before the reset". Picks read-only items from every repo's docs/surplus-work.md
  via `quota-surplus list-work`; never starts work that cannot finish before the reset.
---

# quota-surplus — spend expiring quota, never waste it

`bin/quota-surplus` (no model) finds quota a reset will throw away at the current pace and tells the leads (djbclark,
2026-11-02, after a 25% Gemini 4 Argon weekly surplus nearly expired unnoticed). This skill is what a lead does with the
notice. The algorithm, thresholds and exit codes are in the script's usage text (`bin/quota-surplus check -h` prints it).

## 1. Read the surplus

1. `~/src/djbclark-ade/bin/quota-surplus check` (add `--live` to re-collect a stale reading). `ACT` lines are worth
   spending; `NO VERDICT` means the reading is stale, missing or `exhausted`, or a reset has passed and no reading taken
   since shows the new `resets_at`: re-check with `--live` before acting on it, never guess. (2026-11-02: Argon still
   refused 5 min after aiuse dropped the window.)
2. Note the pool, the hours left and the dispatch line on the `ACT` line (Argon: `acp-run agy --model gemini-4-argon
   --effort high`, because acp-dispatch cannot read a fresh Argon window yet).
3. Only pools where running out is fine are ever offered (djbclark, 2026-11-03): agy, omp API credits, codex, zcode,
   cursor, grok. Never spend the Claude subscription, opencode-go or cline down for a surplus.
4. Who gets the notice: live seats whose name or title starts with the word `LEAD` in capitals (`LEAD paseo-only
   rearch`), plus any agent id in `QUOTA_SURPLUS_LEADS`; name a lead seat that way to receive them. A pool pages at most
   once a day; a 5-hour window never pages (`info` only).

## 2. Pick the work

1. `quota-surplus list-work --pool POOL` (the pool the notice names, e.g. `antigravity-argon`) keeps only the items that
   pool may serve: frontier items for a frontier pool, bulk ones otherwise, and for a repo-scoped pool (opencode-go:
   techno-euphora and Hermes only) only its repos' items. Most valuable first, read-only first. `--repo PATH` narrows it
   to one repository.
2. Order: **read-only reviews and second opinions first** (nothing to land or clean up, and a reset mid-way loses
   nothing but the half-done read), then research and design, then writing work.
3. **Never start an item that cannot finish before the reset**: size S is under 30 min, M under 2 h, L longer. With
   under 30 min left take S only; with under 2 h take S or M.

## 3. Dispatch

1. Dispatch through the normal route (`acp-dispatch` with `--kind`, or the notice's `acp-run` line for Argon), read-only
   (`--perm deny`) for review items, one slice per item.
2. **Bounded bursts: run at most the number of concurrent slices the notice names**, and re-check
   `quota-surplus check --live` between them. It comes from the pool's measured per-slice cost (route_agent's estimate
   floor) where one exists, else 1-2 at a time, never above the pool's `max_parallel`. Why (lead 7c58015b, 2026-11-03):
   aiuse read Argon at 25% left, four parallel read-only agy runs (5-8 min, 27-86 tool calls each) exhausted it within
   about 10 minutes, and aiuse still read 25%. aiuse lags a burst, and a percentage does not say how many slices it buys.
3. **A provider's own "Usage Limit Reached" is authoritative over aiuse**: stop dispatching to that pool at once,
   whatever `check` says.
4. Results land as review comments, queue entries or reports, like any other slice. Mark the item done by deleting it from
   that repo's `docs/surplus-work.md` in a claimed workspace (AGENTS.md order 9).
5. The script never dispatches and never spends quota itself; deciding what is worth it is the lead's call.

## 4. Keep the lists useful

Every repo may keep `docs/surplus-work.md` (format: djbclark-ade's copy): numbered one-line items with kind, size, fit,
read-only and value. Add an item when you find work that is worth a frontier look but not urgent; remove it when done.

## Install the timer (djbclark or the lead, after review; nothing installs it automatically)

    gsed -e "s|__ADE__|$HOME/src/djbclark-ade|g" -e "s|__HOME__|$HOME|g" \
      ~/src/djbclark-ade/config/launchd/com.djbclark.quota-surplus.plist > ~/Library/LaunchAgents/com.djbclark.quota-surplus.plist
    mkdir -p ~/.local/state/quota-surplus
    launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.djbclark.quota-surplus.plist

Uninstall:

    launchctl bootout gui/$(id -u)/com.djbclark.quota-surplus
    rm ~/Library/LaunchAgents/com.djbclark.quota-surplus.plist

It runs `quota-surplus notify` every 15 min: one `hermes-ping` and one `relay.py --fyi` line per live lead seat per new
`act` episode (`--idle 1800` for a Claude Paseo target), state in `~/.local/state/quota-surplus/state.json`, relay output
in `relay.log` there. `notify --dry-run` shows what it would send.
