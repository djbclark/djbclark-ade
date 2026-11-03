### Fixed
- `relay.py ID -` no longer sends the one-character text `-` and reports it delivered (a peer saw an empty message, 2026-11-02): a bare positional `-` is a usage error (exit 2, nothing sent) that names `--message-file -`, the only form that reads stdin (#267)
