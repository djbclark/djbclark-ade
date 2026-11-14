### Fixed

- `tests/test_deadline.py::test_install_agents_auto_looks_for_paseo_on_the_job_path` no longer depends on a real `paseo` in `/opt/homebrew/bin` or `/usr/local/bin`: the test pins its copied plist's `PATH` to the fake home and an empty directory (the code under test was right: it reads the plist's own `PATH`) (#712).
- `claude/hooks/agent_footer_gate.py`: the prompt's own `Report path:` line is also read behind the operator's `A1.` / `A1a.` / `B2)` labels; a `Report path:` line inside a fenced code block, a `>` quote or a 4-space-indented block (a pasted peer brief) no longer competes with the brief's own path; a brief that names a report only inside such text still gets it (#712).
- `tests/test_guard_keep_tags.py` runs the real git guard for both refusals and fails if `GUARD_KEEP_RULES` in `bin/review-pr` or `bin/ade-merge-ready` drifts from the rule tags `bin/ade_claims.py` prints (#712).
