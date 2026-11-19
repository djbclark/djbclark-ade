### Fixed

- `bin/load-watch` no longer stamps a Hermes cooldown after a failed ping, so a failed alert is retried on the next cycle instead of being suppressed for the cooldown period. (#803)
