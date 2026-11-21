### Added

- `bin/codex-env-policy-apply --allow-set-keys KEY[,KEY...]` (operator, 2026-11-21): a deliberate template change to the explicit
  `[shell_environment_policy.set]` keys (such as swapping a Claude Code env flag) can now reach the live Codex config. The default is
  unchanged: any add, drop or change of a set key is refused; the flag permits exactly the keys it names and still refuses the rest, and
  the machine's browser digest key can never be allowed.
