### Fixed

- `bin/ade-worker-run` fills the delivery footer's `{lead}`, `{report}`, `{done}`, `{inbox}` and `{replies}` for a launch whose brief does not define its own report: a `Footer values:` line after the footer pointer names `~/.local/state/agent-reports/<lead id>/<slice>-report.md` and its `.done`, and the path goes to stderr and the JSON (`reportPath`, `donePath`), so a lead always has a `.done` to wait on. (#PR)
