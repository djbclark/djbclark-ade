### Fixed

- Detected routed Pi transcript failures before acknowledgement and preserved retry history and pool exclusions across creation refusals (#791)
- Checked Pi entry structure and timestamp order before classifying terminal failures, preserving recovered candidates and rejecting malformed or unsupported tails; retained saved-proof identity and digest checks on the success path (#821)
