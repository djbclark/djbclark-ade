### Fixed

- The Bash habits gate (`claude/hooks/bash_habits_gate.py`) no longer reads the text after the `)` of a `$(... | tool ...)` group as arguments of the last tool inside it, which denied valid commands such as `gh api x $(echo $r|cut -d/ -f1):master --jq .y` as `cut --jq`; a GNU option inside the group is still denied (#254)
