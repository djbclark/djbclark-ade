### Fixed

- `bin/ade-worker-run` fills the delivery footer's `{lead}`, `{report}`, `{done}`, `{inbox}` and `{replies}` always: a `Footer values:` line after the footer pointer takes `{report}` from a labelled line of the brief (`Report:`, `Report path:`, `Report file:`, "write your report to", `{report} =`) and otherwise generates a unique `~/.local/state/agent-reports/<lead id>/<slice>-report.md`, never reusing a report or `.done` that exists; the chosen `reportPath` and `donePath` go to stderr and the JSON, so a lead always has a `.done` to wait on. (#935)
