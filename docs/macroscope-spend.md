# Macroscope spend ledger

The one append-only record of Macroscope review spend (operator, 2026-11-22: US$100 in total, non-renewable, billed per
KB of reviewed diff). The requester reads the last running total here before asking for a review and appends one line
after (`skills/macroscope-review`, `docs/review-boundary.md`). Never edit or delete an earlier line; a correction is a new
line that says what it corrects.

This file is public. It records spend only, never a screenshot or copy of the Macroscope billing screen: the true balance
is read by the operator in the Macroscope app (Settings, Billing).

Format, one line per request, newest last:

`date UTC | PR URL | head sha (40 hex) | diff KB | mode | est. cost | running total`

Example shape (not an entry): `2026-11-23T14:05Z | https://github.com/OWNER/REPO/pull/1 | <40 hex> | 30 | balanced | US$1.50 | US$1.50 of US$100`

Master is PR-only, so each ledger append is its own docs PR and the ledger on master can lag. Before a request, the
requester counts the running total as master's last line plus every entry in an open ledger PR: list them with
`gh pr list --state open --search "docs/macroscope-spend.md in:path"` (or open PRs on a `macroscope-ledger-*` branch)
and read each one's added line. Merge the ledger PR promptly, before the next request. The first entry replaces the
"No entries yet" line below; later ones append after the last entry, so two in-flight appends conflict on the tail line
and the later one is rebased (a conflict is a signal that someone else already spent: re-add their entry to your total).

## Entries

No entries yet. Running total: US$0.00 of US$100.
