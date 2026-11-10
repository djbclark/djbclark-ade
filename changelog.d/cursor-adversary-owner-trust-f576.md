### Changed

- Owner-authored PRs (repository owner login, including Cloud Agents under that login) now pass the
  `adversary-marker` gate without a manual APPROVE marker; a BLOCK or malformed marker still fails, and
  outside/MEMBER/COLLABORATOR PRs still need a live APPROVE in an owner issue comment (operator 2026-11-10:
  distrust only what does not come from the owner or AIs they run) (#TBD).
