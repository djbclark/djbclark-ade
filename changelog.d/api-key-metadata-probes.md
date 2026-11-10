### Added

- Added fixed OpenAI/OpenRouter metadata verification commands to the existing
  key engine, with environment-only credentials, bounded read-only GETs and
  exit-code-only results; metadata authentication did not establish inference
  quota, entitlement or provider acceptance. (#552)
