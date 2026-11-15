### Fixed

- `claude/hooks/adversary_marker_gate.py` now denies a `gh` write whose JSON payload is nested past the parser's recursion limit when it mentions APPROVE (an escaped live marker could slip past the leaf walk); the old recursion test could not fail and is replaced by tests that do (#741)
