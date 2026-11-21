### Fixed

- `load-watch` tests: the race guard that stops a ticket from overwriting a `ci` row recorded during the ticket check is now pinned for a `ci` row at the main checkout and at a glob over its parent (follow-up of the review of #914), not only at the directory itself (#916)
