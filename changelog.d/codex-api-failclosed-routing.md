### Changed

- Split the Codex routing pool by billing identity: `codex` now routes gpt-6.1-sol (judgment/code/research) and
  gpt-6-astra (frontier) on the OpenAI API prepaid credits (pool family `openai_api`, fail-closed when unknown or
  exhausted), while a new `codex-subscription` service routes gpt-6-luna (bulk/mechanical) on the ChatGPT subscription
  windows (pool family `default`). `canary_pool()` now also matches a service's `pool` family and `pool_family`, so the
  `openai_api` canary gates. (#776)
