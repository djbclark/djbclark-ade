### Added

- Add protected Linux retained-launch and owned IPC observation infrastructure
  for the actual fork controller/native promotion fixture. Bounded transport
  tests do not qualify runtime artifacts or permit live activation. (#0)

Private CLI bearer validation now uses fixed plain errors, including trailing-newline refusal. Transport failure interrupts the actual-close wait and preserves bounded cleanup failure with its process handoff; synthetic regression coverage does not imply daemon-operation settlement.
