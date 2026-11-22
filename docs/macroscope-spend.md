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

## Entries

No entries yet. Running total: US$0.00 of US$100.
