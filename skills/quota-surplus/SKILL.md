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
   spending; `NO VERDICT` means the reading is stale or missing: re-check with `--live` before acting on it, never guess.
2. Note the pool, the hours left and the dispatch line on the `ACT` line (Argon: `acp-run agy --model gemini-4-argon
   --effort high`, because acp-dispatch cannot read a fresh Argon window yet).

## 2. Pick the work

1. `quota-surplus list-work --fit frontier` for a frontier pool (gpt-6-astra, Fable, Gemini 4 Argon), `--fit bulk` for any
   other; most valuable first, read-only first. `--repo PATH` narrows it to one repository.
2. A repo-scoped pool (opencode-go, cline: techno-euphora and Hermes only) is spent only on that repo's items; the notice
   already goes only to those seats.
3. Order: **read-only reviews and second opinions first** (nothing to land or clean up, and a reset mid-way loses
   nothing but the half-done read), then research and design, then writing work.
4. **Never start an item that cannot finish before the reset**: size S is under 30 min, M under 2 h, L longer. With
   under 30 min left take S only; with under 2 h take S or M.

## 3. Dispatch

1. Dispatch through the normal route (`acp-dispatch` with `--kind`, or the notice's `acp-run` line for Argon), read-only
   (`--perm deny`) for review items, one slice per item, within the pool's per-wave cap (`route_agent.py policy --md`).
2. Results land as review comments, queue entries or reports, like any other slice. Mark the item done by deleting it from
   that repo's `docs/surplus-work.md` in a claimed workspace (AGENTS.md order 9).
3. The script never dispatches and never spends quota itself; deciding what is worth it is the lead's call.

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
