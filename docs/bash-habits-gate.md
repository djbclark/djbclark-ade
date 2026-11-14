# Bash habits gate

As of 2026-11-12, `claude/hooks/bash_habits_gate.py` checks a submitted shell
command before execution. A denial blocks the entire submission: **nothing in
the command ran, including any earlier part**. Fix the offending part and
re-run the whole command. This applies to compound commands separated by `;`
or `&&` as well as single commands.

The denial includes this explanation in Claude's permission decision, Codex's
stderr and Cursor's user/agent messages. Warnings continue to allow execution.
Checks include bare BSD `sed`, recursive `grep`, GNU-only flags on BSD tools
and pipelines that mistake a filter's status for the producing command's.

**GitHub watchers (2026-11-14).** `gh run watch` and `gh pr checks --watch` are denied (found through `timeout`, `bg`,
`rtk`, `sudo -u X`, env prefixes, `-R`, `&&`/`;`/subshells, `do`/`then`, backslash-newline, `$(...)` and backtick
substitutions (also inside double quotes) and the body of `bash -c '...'`; quoted text and heredoc bodies
are data). Why: every agent shares one GitHub token with a 5000/h API quota, and four `gh run watch` at gh's default
3 s interval emptied it from 10:22Z to 11:22Z. The reason names dispatch-footer item 20 and the alternatives: report "CI running"
with the run URL and end the turn, one-shot `gh run view RUN --json status,conclusion`, or a background loop sleeping 60 s
or more between one-shot checks. A watcher with `--interval`/`-i` of 60 or more passes (`GH_WATCH_MIN_INTERVAL`): it costs
a few calls a minute, and it is the lead's documented CI wait; the gate cannot count concurrent watchers across commands, so
rule 20 (never park an agent on one) stays a rule. `xargs -P N` / `parallel` around `gh` calls only **warns** (budget in
dispatch-footer item 26). Also unwrapped: `deadline run ... -- gh ...`, `bin/gh-pr-checks`, and a heredoc fed to a shell. Not detected: a watcher
started from a script or inline Python, `ssh host <<EOF`, `bash -c $'...'`, a shell with more than four words before it
(`deadline run --on-expire kill -- bash -c ...`), `$'..\\'..'`, a quoted command word (`gh run 'watch'`, `"gh" run watch`), `timeout -k 10 600 gh ...` (options with values),
a heredoc delimiter with non-word characters (`<<'X-Y'`), a `<<` that is a here-string, shift or quoted/commented text
(it hides the lines after it), substitutions in an unquoted heredoc body, a comment ending in a backslash, a nested `"$(... "x's" ...)"` followed by a single-quoted word (the apostrophe pairs with it), `$(case a in a) ...)`,
a comment holding `)` inside `$(...)`, `eval`, `\\gh`, an alias, flags before the subcommand, other wrapper options with values
(`time -p gh`, `stdbuf -o L gh`), a watcher in a `case` branch (`a) gh run watch 9;;`), a function body (`f() { gh run watch "$1"; }`),
`parallel gh run watch ::: 1 2` (only the fan-out warning fires), and the same quota burn by another shape (`watch -n 3 gh run view`, a `gh run view`
loop that sleeps under 60 s). Known false positives (deny side): a `bash <<EOF` line, or `bash -c 'gh run watch N'` after a live `$(` in a double-quoted
message, and `| sh` inside a comment after a data heredoc. The 5000/h quota counts REST and GraphQL separately (`gh pr checks` reads GraphQL).
