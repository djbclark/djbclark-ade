# Raw response: acp-run claude opus/high, resumed session, section 7 dashboard UX (2026-10-19 ~15:05 EDT)

acp-run applied: {"model": "opus", "effort": "high", "ctx": 1000000, "ctx_source": "usage_update"}; verified model claude-opus-5-5; cost reported $0.4400216; exit 0

---

MODEL: claude-opus-5-5

## Verdict

The journeys and the attention-queue idea are right. The main gap is that the phone, where Daniel spends most of his time, gets a read-only page he probably can't open. The spec also designs screens without defining the data behind them.

## P0

**1. Treat the phone as Telegram, not a web view.** Phone actions arrive in D4, the dashboard binds to localhost, and the digest "links to the phone view." From Telegram, that link only works if remote access is set up (Tailscale or similar), and the doc doesn't decide this. Make the Hermes message the primary phone UI and design it like a screen:
- one message per Needs-you item,
- the job title, not just `004`,
- the reason line,
- the diffstat,
- inline buttons: `Approve`, `Rework…`, `Snooze 4h`, `Open`.

Ship this in D1 or D2, not D4.

**2. Approving on a phone needs a decision card.** Nobody reads a diff on a phone. The card should show:
- why the job escalated,
- one line per reviewer,
- files changed (+/−),
- risk flags: touches auth, CI, dependencies or secrets,
- verify status.

Rule: a job with a security CHANGES verdict can't be merged from the phone, only snoozed or sent to rework.

**3. Write a data contract.** The dashboard is a static page served by `http.server`, so where do Diff and the diffstat come from? Specify what the orchestrator writes for the UI:
- `index.json` fields, with a `schema_version`,
- per-round `diff.patch` and `diffstat.json`,
- `summary` (≤80 characters) in each `verdict.json`.

The reason line depends on role prompts producing that short summary. LLM first lines are too long or empty too often to rely on.

**4. Needs you lacks ordering and an exit.**
- Order: burning (stuck, failed, over budget), then needs-human, then ready; oldest first within each group.
- Add `Snooze` and `Ack`. Without them, ready jobs nag forever and the warning banner trains him to ignore it.

**5. Show when the orchestrator itself is down.** If the orchestrator is dead, every "Running" row is false, yet the data still looks fresh. Show its heartbeat in the header, with a red "orchestrator down since 14:02" state.

## P1

**6. States you haven't defined:**
- first load,
- a `job.json` that fails to parse or has the wrong schema version,
- cancelled, merged, abandoned (terminal),
- a command waiting for the orchestrator ("rework queued"), confirmed, or failed,
- orchestrator down (P0 #5).

**7. Stuck detection will raise false alarms.** Log growth misses long thinking turns and slow test runs. Show "last activity: `Bash make test`, 4m ago" instead of ♥. Make `stuck_after` per role, with the builder getting longer.

**8. There's no return view.** You cite "close the lid, come back," but nothing implements it. Add a section "Since you last looked": merged, failed or escalated jobs since the last visit, with a last-seen marker.

**9. Spend numbers are misleading.** `$1.84 / $10` silently leaves out vendors that don't report cost. Show `$1.84 reported + 9 calls not reported`. Calls and wall-clock should lead, consistent with the guards in §8.

**10. The wireframes contradict your own rules:**
- `● ○ –` chips use color and shape alone, which breaks 7.9. Use `S✓ U… C✗`.
- `[a][w][o]` shows actions that don't exist in MVP. In D1, put a copy button for `factory approve 004` there. That makes the read-only MVP actually useful.
- The phone rows show ids with no titles.

**11. Polling breaks accessibility and keyboard use.** Re-rendering every 5 s moves the `j`/`k` selection, resets scroll and floods `aria-live` announcements. Update rows in place by key, keep focus, and announce only new Needs-you items.

**12. Shortcut conflicts:**
- `tab` to cycle tabs hijacks native focus order, which hurts keyboard and screen-reader users. Use `1`–`6` or `h`/`l`.
- Single-key shortcuts must be disableable and inactive inside inputs (WCAG 2.1.4).

## Missing

- A URL for every job and tab. Telegram links need them.
- The Needs-you count in the tab title and favicon, so the laptop view is glanceable without opening the page.
- Absolute timestamps on hover.
- Round-to-round deltas in Reviews: which findings were fixed, which are new.
- Aggregation across repos. One instance per repo means several digests otherwise.
- Notifications for stuck, over budget and quota, not just Needs you. Re-notify once if an item goes unanswered, with quiet hours respected.

## Over-built: cut or defer

- The board/table toggle. Ship the table only.
- The `⌘K` command palette and `/` search. Pointless for about 10 jobs.
- Role presets and estimated call count in New job. Defer; starting jobs is a CLI task for now.
- The 7-day per-vendor Spend page. Today's numbers in the header are enough.
- The separate Hygiene page. Use a banner plus an inline list.
- Spec and Build as separate tabs. Merge them into "Docs".
- §7.1 survey. Move it to an appendix; it isn't part of the spec.

## Revised delivery order

- **D1:** data contract, home (Needs you, Running, Since last), job Summary and Reviews, all states, copy-command buttons.
- **D2:** Telegram decision cards (read-only), deep links.
- **D3:** Telegram actions with confirm, and the command inbox.
- **D4:** SSE, Diff tab polish, keyboard actions.
