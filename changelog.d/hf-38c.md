### Changed

- `bin/ade-worker-run` adopts the WORKER window registered to a predecessor whose fresh acknowledged self-handoff names the lead, when `paseo agent inspect` shows the predecessor archived, or idle/closed with no pending permissions; a running, unreadable, stale or other-successor record keeps the refusal and names the reason; `archive-window` follows the same adoption. (#755)
