### Fixed

- `claude/hooks/bash_habits_gate.py`: denies an unquoted word that starts with `=` (zsh expands `=cmd`, so `echo ===; next` failed with `zsh: == not found` and never ran `next`; `[[ ]]`, `(( ))`, `=(cmd)` and quoted words pass), and a `paseo send` or `paseo agent send` command whose double-quoted argument holds a backtick or `$(` (the shell ran it before paseo saw the message); both reasons say what to write instead, and `docs/bash-habits-gate.md` lists the probed cases (#707).
