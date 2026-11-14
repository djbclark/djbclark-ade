### Changed

- Peer-trust wording follow-up to #706: no launcher sets `ade.kind=external-review` today (`bin/review-launch` and `bin/review-pr` start no Paseo agent, no `gh-watch` launcher exists, PR Radar has no label field yet); `gh-watch` is dropped from the default sensitive title patterns (`claude/hooks/peer_trust_gate.py`, `config/peer-trust.toml`); docs/orchestration-practices.md says to append the label last because `paseo run` keeps the last `--label` for a duplicate key. (#715)
