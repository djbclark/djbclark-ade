### Changed

- Peer-trust follow-up to #715: a test that an internal `worker gh-watch-gate ...` title is believed (so the `gh-watch` pattern cannot return unnoticed), and the watcher wording in AGENTS.md, docs/peer-trust.md and config/peer-trust.toml names fleet-watch's upstream PR watcher (off, dispatcher deleted in #699, relay mode) and says a native port or relay target must carry `--label ade.kind=external-review`, appended last. (#723)
