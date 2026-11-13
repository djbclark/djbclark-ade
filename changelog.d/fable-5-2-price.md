### Fixed

- `bin/claude-cost-mix` and `bin/claude-cost-whatif` priced Fable 5.2 as Fable 5.1 ($10/MTok base, unverified since #627);
  the published price is $8/MTok base (cache read 0.025x unchanged: $0.20/MTok), checked against
  platform.claude.com/docs/en/about-claude/pricing on 2026-11-13. (#0)
