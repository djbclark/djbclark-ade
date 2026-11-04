### Fixed

- `bin/acp-dispatch` recognized positively identified Anthropic credit-balance refusals on failed runs, excluded exit-0 tool output, and capped row-derived or refusal-text retry timestamps at six hours so healthy pools are not poisoned and exhausted pools are rechecked (#287).
