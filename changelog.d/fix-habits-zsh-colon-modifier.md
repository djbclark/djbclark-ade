### Fixed

- Bash habits gate: deny a bare `$NAME:x` (unquoted or double-quoted, also `$1`/`$@`) where `x` is a zsh history modifier (`a A c e h l P q Q r s t u &`, optionally after `g`/`w`), such as `git push origin $C:refs/heads/x` that pushed `<sha>efs/heads/x`; `${NAME}:x`, single quotes and `:p`-style non-modifiers pass (#909)
