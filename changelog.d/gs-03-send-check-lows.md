### Fixed

- `claude/hooks/bash_habits_gate.py`: the `paseo send` backtick check also reads a send after a `case` arm (`x) paseo send ...`), `ssh host`, `gtimeout`, `noglob`, `nocorrect`, `builtin`, `coproc`, `flock`, `watch`, `script`, `direnv`, `secretspec run` and `op run`, and `{paseo send ...;}` without a space after the brace (the #707 adversary's Lows); `bin/completion-notice`: two over-long lines wrapped and the `build_message` docstring now says a short SHA can be refused (the #721 lead review's Lows) (#733).
