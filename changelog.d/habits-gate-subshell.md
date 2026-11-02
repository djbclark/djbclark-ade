### Fixed

- The Bash habits gate (`claude/hooks/bash_habits_gate.py`) no longer reads the text after the `)` of a `$(... | tool ...)` group as arguments of the last tool inside it, which denied valid commands such as `gh api x $(echo $r|cut -d/ -f1):master --jq .y` as `cut --jq`; it now checks the outer command (substitutions replaced by a placeholder) and each substitution body as separate commands, so a GNU option in either is still denied, including in a lone `$(date -d yesterday)` that it used to miss (#254)
