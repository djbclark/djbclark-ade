### Fixed

- Bash habits gate: the `$NAME:x` zsh-modifier rule now also denies a `$C:r` in an unquoted heredoc body (`bash <<EOF`), the `f`/`F`/`F:expr:`/`W:sep:` prefixes (`$IMG:frontend`), parameter flags and subscripts (`$=C:t`, `$C[1]:r`), and follows `$(...)` and backtick bodies inside double quotes (`"$(echo "it's")" $C:r` denied, `"$(echo '$C:r')"` passes); `$$C:r` is no longer denied; the tests are one case per rule branch, mutation-checked (#PR)
