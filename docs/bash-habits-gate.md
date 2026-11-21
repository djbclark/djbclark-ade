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
`rtk` (also `rtk proxy`), `sudo -u X`, `env -i`/`env -u X`/`env -C DIR`, `nice -n N`/`nice --adjustment N`, quoted and unquoted assignments after `env`/`sudo` and their options, in any order (`env -i "PATH=$PATH" gh ...`, `env -i A=1 "B=$X" gh ...`; a quoted `"VAR=$?"` is not recognised), combined options ending in a value option (`env -iu X`, `sudo -Hu me`), `command -p`, `exec -a NAME`, a redirection glued to the command word (`gh>log run watch 9`), env prefixes (a wrapper option value that is itself named `gh` is handled: the first four `gh` words are each tried as the command; a real `gh` after four decoys named `gh` is not checked), `-R`, `&&`/`;`/subshells, `do`/`then`, backslash-newline, `$(...)` and backtick
substitutions (also inside double quotes) and the body of `bash -c '...'`; quoted text and heredoc bodies
are data). Why: every agent shares one GitHub token with a 5000/h API quota, and four `gh run watch` at gh's default
3 s interval emptied it from 10:22Z to 11:22Z. The reason names dispatch-footer item 20 and the alternatives: report "CI running"
with the run URL and end the turn, one-shot `gh run view RUN --json status,conclusion`, or a background loop sleeping 60 s
or more between one-shot checks. A watcher with `--interval`/`-i` of 60 or more passes (`GH_WATCH_MIN_INTERVAL`): it costs
a few calls a minute, and it is the lead's documented CI wait; the gate cannot count concurrent watchers across commands, so
rule 20 (never park an agent on one) stays a rule. `xargs -P N` / `parallel` around `gh` calls only **warns** (budget in
dispatch-footer item 26). Also unwrapped: `deadline run ... -- gh ...`, `bin/gh-pr-checks`, and a heredoc fed to a shell. Not detected: a `&>`/`>&` redirection among the words (`gh &>log run watch 9`; strip_literals blanks the operator), a watcher
started from a script or inline Python, `ssh host <<EOF`, `bash -c $'...'`, a shell with more than four words before it
(`deadline run --on-expire kill -- bash -c ...`), `$'..\\'..'`, a quoted command word (`gh run 'watch'`, `"gh" run watch`), `timeout -k 10 600 gh ...` (options with values),
a heredoc delimiter with non-word characters (`<<'X-Y'`), a `<<` that is a here-string, shift or quoted/commented text
(it hides the lines after it), substitutions in an unquoted heredoc body, a comment ending in a backslash, a nested `"$(... "x's" ...)"` followed by a single-quoted word (the apostrophe pairs with it), `$(case a in a) ...)`,
a comment holding `)` inside `$(...)`, `eval`, `\\gh`, an alias, flags before the subcommand, `rtk proxy -- gh ...`, `env -S 'gh run watch 9'` (the value is the command), an absolute-path wrapper (`/usr/bin/env -i gh ...`), a placeholder command word (`env -i $GH run watch 9`, ``env -i `which gh` ...``), other wrapper options with values
(`time -p gh`, `stdbuf -o L gh`), a watcher in a `case` branch (`a) gh run watch 9;;`), a function body (`f() { gh run watch "$1"; }`),
`parallel gh run watch ::: 1 2` (only the fan-out warning fires), and the same quota burn by another shape (`watch -n 3 gh run view`, a `gh run view`
loop that sleeps under 60 s). Known false positives (deny side): a compliant watcher after a branch named `env` or `nice` followed by a later word named `gh` (`gh pr checks env -i 60 --watch -R o/gh`), a `bash <<EOF` line, or `bash -c 'gh run watch N'` after a live `$(` in a double-quoted
message, and `| sh` inside a comment after a data heredoc. The 5000/h quota counts REST and GraphQL separately (`gh pr checks` reads GraphQL).

**Unquoted `=word` (2026-11-14, gs-02).** zsh, this Mac's Bash-tool shell, reads an unquoted word that starts with `=` as the
path of a command (`=ls` is `/bin/ls`) and, when there is none, prints `zsh: == not found` and **aborts the rest of a `;`
chain**: `echo ===; next` never ran `next` (the memory note `feedback_zsh_triple_equals_separator.md` did not stop it, so the
gate does). Probed on this Mac: `echo ===`, `echo ==`, `echo =b`, `echo ="x"`, `echo ==$e`, `ls =nonexist`, `[ a == a ]`, `test a == a`
and a `case` pattern `=*)` all fail (a `=word` that resolves, `echo =ls`, expands to its path and runs; it is denied too, as a habit that bites). Denied: any unquoted word of more than one character that starts with `=` and is not `=(`.
Passes: a lone `=`, `=(cmd)` (process substitution), quoted words (`'==='`), `\===`, `a=b`, `x==y` (not checked: zsh expands the
assignment value, rare), `--x=y`, `-d=`, heredoc bodies, comments, and the inside of `[[ ... ]]`, `(( ... ))` and `$(( ... ))`
(write `[ a = b ]` or `[[ a == b ]]`). Use `---` as a separator.

**`$NAME:x` history modifiers (2026-11-21; lows of the PR 909 review folded 2026-11-21).** zsh applies a modifier to a bare `$NAME` (also `$1`, `$@`, `$#`, `$?`) followed by `:` and a
modifier letter, unquoted or double-quoted: `C=<sha>; git push origin $C:refs/heads/ci/x` pushed `<sha>efs/heads/ci/x` (`$C:r`), and
`git show "$h:c..."` ate the `:c`; refspecs, `scp host:path` and rsync targets are all exposed. Modifier set probed with `/bin/zsh -f`:
`a A c e h l P q Q r s t u &` (`&` only inside double quotes; unquoted it is the background operator, already denied), after any run of the prefixes
`f`, `g`, `w`, `F`, and `F` or `W` with a delimited argument (`:gs/a/b/`, `:gr`, `:fr`, `:Fr`, `:F:2:r`, `:W:/:t`; `docker tag x $IMG:frontend` is `:fr`). zsh takes the character after `F` or `W` as the delimiter, whatever it is, and ends the argument at its next copy (`:F-2-r`, `:W.x.t`, `:Wrxrt`; `( [ { <` close with `) ] } >`); a bare `F` is a prefix only when no closing delimiter follows, so `$C:Fr` is `F` then `r` but `$C:Feature` and `$C:Ftest` are plain text. Known gaps, accepted because the forms are rare, not because they are harmless (zsh rewrites each one silently and the gate passes it): a delimiter that is whitespace, `\`, `'`, a backtick or `$` (`"$C:F 2 r"`, `"$C:F'2'r"`, `$C:F$2$r`), and whitespace inside the argument of a double-quoted `"$C:F.2 .r"`; an argument or subscript longer than 256 characters is not followed either (the patterns are bounded so a long run of `$C:F<` or `$C[` cannot stall the hook). Also reached: parameter flags between `$` and the name
(`$=C:t`, `$~C:t`, `$^C:t`, `$+C:t`, `$#C:t`) and one subscript after it (`$C[1]:r`, `$@[1]:t`). Denied: an unescaped, unquoted or double-quoted `$NAME:` + one
of those. The rule runs for every TUI the gate serves (Bash tool, Codex, Cursor): all use this Mac's zsh, and the hook cannot tell the shell.
The scan follows `$(...)` and backtick bodies as fresh command text, also inside double quotes (so `"$(echo '$C:r')"` passes and
`"$(echo "it's")" $C:r` is denied; 16 nesting levels, then the rest is read flat), and it reads the body of an **unquoted** heredoc (`<<EOF`, `<<-EOF`):
the shell expands `$C:r` there before `bash <<EOF` or `ssh host <<EOF` runs anything, so `git push origin $C:refs/heads/x` inside such a body is denied too (only a
backslash and `$` are special in a body; quotes and `#` are literal). Passes: `${NAME}:x` (write this), single quotes, `\$C:r` (also in a body), comments,
quoted-delimiter heredoc bodies (`<<'EOF'`, `<<"EOF"`), `$$C:r` (the pid, then plain text), `${C:-d}` / `${C:t}` parameter expansions, and
colon forms zsh leaves alone (`$C::`, `$C:-`, `$C:/`, `$C:p`, `$C:x`, `$C:S`, `$C:g:o:r`, digits, a prefix with nothing after it such as `$C:f`, `$C:Wr` or `$C:F:r`, `$1[1]:r`, `${C}[1]:r`), so `scp $HOST:path .` is not denied (`:p` is not applied).
Known gap: `<<\EOF` (backslash-quoted delimiter) is not recognised as a heredoc by the shared introducer scan, so its literal body is scanned as commands and a `$C:r` in it is denied.
The Codex argv form `bash -lc ...` is judged like the rest even though bash would leave `$C:r` alone (writing `${C}:` costs nothing).

**Backtick or `$(` in a double-quoted `paseo send` argument (2026-11-14, gs-02).** The shell runs that text before paseo starts:
a worker's `"... the `foo` call ..."` ran `foo` and the message arrived with a hole in it. Denied for `paseo [opts] send` and
`paseo agent send` (`paseo` must be the command word, after `VAR=x` assignments, a shell keyword (`if`, `then`, `do`) or a known wrapper such as `env -u X`, `timeout`, `gtimeout`, `bg`, `sudo`, `deadline run --`, `ssh host`, `flock F`, `watch -n N`, `direnv exec .`, `op run --` (the `SEND_WRAPPERS` set), a `case` command or a case-arm pattern word (`x) paseo send ...`; gs-03, 2026-11-15) or `{paseo` (no space after the brace); a `paseo` that is data for another command, `ls paseo send "$(date)"`, is not a send, and a `{}` placeholder is a word, not a group brace), when any double-quoted word after the
verb holds an unescaped backtick or `$(`; an unquoted `${ID}`, `$(cat id)` or backtick target before the message is read as part of
its word, so it does not hide the send; the body of every `$(...)`, `<(...)`, `>(...)` and backtick span (quoted or not) is checked as a command line of
its own, so `r=$(paseo send --json ab "...`x`...")` is denied too. Passes: single quotes, `"\`x\`"` and `"\$(x)"` (escaped, literal), arithmetic
`"$((n*2))"` (unless it holds a substitution), `--prompt-file FILE` (write it with `cat > FILE <<'EOF'`; `--prompt-file -` reads a
file named `-`, not stdin), python argv, a substitution in some other command (`echo "`date`"; paseo send ab ok`), and a command
that starts with `echo`, `printf`, `print`, `rg`, `grep`, `git`, `cat`, `gh` or `jq` (`echo paseo send "$(date)"` only prints text). Known false
positives: a wrapper or case arm lets the scan look past a data word (`case $a in x) ls paseo send "`y`"`; the `x) echo` case-arm instance from the rv-733 review (B2d) is the same class, `ssh host ls paseo send "`x`"`, `watch ... paseo send ...`, `op item get paseo send "$(x)"`, `f() echo paseo send ...`, a `$(cmd) ls paseo send ...`), a deliberate `"$(cat FILE)"` or `"$(paseo ls ...)"` target is denied too (assign it first: `ID=$(cat f); paseo send "$ID" ...`);
a redirect target `> "$(mktemp)"` after the send. Not detected: `bash -c 'paseo send ...'`, a wrapper missing from `SEND_WRAPPERS`, `P=paseo; $P send`, a send built by a script or
`eval`, unquoted backticks inside a message word, and a quote the scanner cannot pair (it fails open). Pre-existing, not changed here:
a here-string (`cat <<< x`) is read as an unterminated heredoc by the older heredoc checks. The old session-finder relay shim is gone, so
`relay.py` is no longer matched. `BASH_HABITS_GATE_OFF=1` is the operator's escape hatch and takes effect only in the TUI's own
environment, not as a command prefix.

**Job-control background `&` (2026-11-15, bh-bg).** Denied: a lone `&` that ends a simple command (`cmd &`, `cmd & next`, `cmd &` before a newline, `)` or `}`), including `nohup cmd &`, `setsid cmd &`, `( cmd & )` and `$(cmd &)`. Why: on 2026-11-15 a `python3 wait_check.py > out 2>&1 &` inside a foreground Bash call was orphaned (ppid 1) and untracked; `~/CLAUDE.md` item 33 requires the Bash tool's `run_in_background: true` parameter, which tracks the job and notifies on exit. The reason says so and that nothing ran. The `nohup`/`setsid`/subshell forms are denied on purpose: the tracked route is `run_in_background`. Never denied: `&&`, `2>&1`, `>&2`, `&>file`, `&>>file`, `|&`, `<&3`, `${x//&/y}`, `[[ a && b ]]`, `$((a & b))`, `\&`, anything in quotes (`'a&b'`, `$'..&..'`, a URL in quotes), heredoc bodies, comments, and text such as `kill %1` or `disown` in a string. An unquoted URL query (`curl http://h/x?a=1&b=2`) is denied: the shell backgrounds it, so quote it. The check runs after the per-stage checks, so a more specific reason (bare `open`) wins. No opt-out beyond the operator's `BASH_HABITS_GATE_OFF=1`. Exempt: a command whose every `&` is followed later in the same command by a `wait` builtin (`a & b & wait`, bounded fan-out); a trailing `&` after the last `wait` is still denied. The exemption is textual: `( cmd & ); wait`, `a & wait $!` and `x & (wait)` also pass (the `wait` may not reach the job), and `a & b && wait` is denied. Case-arm terminators `;&` and `;;&` are not backgrounds. The reason names the call's `timeout` (at most 7200000 ms, default 30 min stops the job) and, for longer jobs, CI, a `bin/ade-sched` one-shot or a Paseo terminal; TUIs without `run_in_background` (Codex, Pi) are not gated and keep `nohup sh -c '...' &`. Also not detected: `screen -dm`, `tmux new -d`, `launchctl submit`. Not detected: a `&` built by `eval` or a script, `bash -c '... &'`, `coproc`, a `&` in a `$(...)` inside double quotes (`echo "$(sleep 5 &)"`) or `${y:-$(...&)}`, and the older heredoc mis-scans. Known false positives (rare): `$(( (6 & 3) + 1 ))`, `$(( x & $(cmd) ))`, `$[6&3]`, a body with `&` under a `<<\EOF` heredoc. Dispatch-footer rule 10 now names `run_in_background` instead of `nohup ... &`.
