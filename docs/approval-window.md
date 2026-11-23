# The approval window also answers agent permission prompts (2026-11-22; installed live on bigmac 2026-11-23)

Operator ruling, 2026-11-22: "we want our limited-duration token to also avoid prompts such as this". The "token" is the
sudo-ask approval window (site-public-djbclark, `sudo-ask grant [DURATION]`: one Touch ID opens a timed window, 1 minute to 24
hours). While it is open, `sudo-ask` commands run without a dialog. This change makes the same window clear **agent
tool-permission prompts** too: Paseo's Accept/Deny card and Claude Code's own prompt. Nothing here opens, extends or ends a
window; it only reads one.

The prompt that started it: under Paseo, a Claude agent in bypass mode ran `rm -f $S/all.done $S/*.log` and the card read
"Dangerous rm operation on possibly-empty variable path: $S/*.log ... (rewrite it as "${S:?}"/*.log or use a literal path)".
That is Claude Code's built-in `rm` safety check. No allow rule and no PreToolUse hook approves it; in bypass mode it falls
through to the host's `canUseTool` callback, which for Paseo is the card (docs: permission-modes.md, agent-sdk/permissions.md,
hooks.md on code.claude.com).

**What this is, plainly (lead and operator, 2026-11-22: "denylist plus hardening; say plainly it is not a boundary").** Our agents
are trusted. The critical-path removal rule and the denylist below guard against **careless commands from a trusted agent** (an
empty variable, a stray glob, a runaway `rm`), not against a hostile one, and they are **not a security boundary**. A determined
agent can write a command this parser misreads; the shell is too large to out-parse. So the policy does two things: it fails closed
wherever it cannot be sure (it holds, the operator is asked as before), and it adds a textual tripwire for a remover word it did
not itself judge (III 1d4). Section III 2a lists what passes on purpose.

## I. What the window covers

***1.*** **`sudo-ask` commands** (the site repo's `roles/sudo_ask_grant`): unchanged by this change; the root helper judges them.

***2.*** **Paseo permission requests of every provider** (Claude, Codex, OpenCode, Pi, OMP and the ACP-backed ones): the
responder `bin/ade-approval-window` (logic in `bin/ade_approval_window.py`) lists pending requests and allows the ones the
policy below allows, for any agent.

***3.*** **A Claude Code session Paseo does not run**: the `PermissionRequest` hook `claude/hooks/approval_window_permit.py`
returns the documented allow decision under the same policy and window check. It prints nothing otherwise, so the normal prompt
is shown.

## II. The window file

`/var/db/sudo-ask/grant` (directory `root:wheel 0755`, file `root:wheel 0644`), JSON `{expires_utc, granted_utc,
granted_by_uid, duration_s, nonce}`, written by the root helper `sudo-ask-granted grant` (site-public-djbclark branch
`feat/sudo-ask-grant-window`, `roles/sudo_ask_grant/files/sudo-ask-granted`, `read_grant`). `read_window` in
`bin/ade_approval_window.py` mirrors that reader and fails closed. The window is open only when:

- the directory and the file are owned by root and neither is group- or world-writable (`mode & 0o022 == 0`);
- the directory and the file are not symlinks (`lstat`; the open uses `O_NOFOLLOW` and re-checks the inode and mode on the
  descriptor);
- the file is at most 4096 bytes and the JSON has all five fields, with the helper's types (the nonce is 32 lower-case hex digits);
- `duration_s` is 60 s to 24 h and `expires_utc - granted_utc == duration_s`; `granted_utc` is not more than 120 s ahead of the clock;
- `expires_utc` is in the future and **not more than 24 h away** (a far-future file is tampering, so it is closed).

Any error is "closed". The path is hard-coded; only function parameters (tests) move it. The installed
`/usr/local/libexec/sudo-ask-granted` was an unreviewed draft when this was written: nothing here runs it, calls `sudo-ask
grant|revoke|status` or uses sudo.

## III. Policy while the window is open

First match wins. The audit line records the rule.

***1.*** **Stays pending** (the operator is asked as before):

***a.*** *Not a plain tool request*: Paseo's `kind` is `plan`, `question`, `mode` or `other` (or missing), or the tool name is a question
or plan name (`AskUserQuestion`, `ExitPlanMode`, `EnterPlanMode`, `CodexPlanApproval`, `request_user_input`, ...; the stem
list is copied from `bin/ade-auto-permit`). Allowing a question answers nothing and allowing a plan skips the review. Rules
`kind:*`, `question:*`.

***a2.*** *Our own gates' asks* (rules `gate:subagent`, `gate:ade`; adversary round 1, 2026-11-22): a Claude sub-agent launch (`Agent`,
`Task`) is never answered, because `claude/hooks/frontier_agent_gate.py` returns `permissionDecision: "ask"` for a frontier
sub-agent on purpose (scarce Fable, operator 2026-10-18) and Paseo does not forward the reason, so the policy cannot tell the
gate's ask from an ordinary launch. Any request whose title, description, detail or metadata carries the gate's text
(`Frontier sub-agent:`, pinned by a test against the hook's source) also stays pending. The other gates under `claude/hooks/`
deny, they do not ask.

***b.*** *Unreadable* (rule `unreadable:*`): a command tool (Bash, CodexBash, `execute`, any request with a `command` field) with no
command text, a file tool (Write, Edit, Read, `CodexFileChange`, ...) with no path, a request with no input, detail or title at
all, or a string over 200,000 characters. `CodexFileChange` carries only a free-text reason, so Codex file-change prompts always
stay pending.

***b2.*** *A command line it cannot read with confidence* (rule `unreadable:unparsable:*`). The text is read with real shell quoting
**first** (single and double quotes, backslashes, comments, here-documents), and only then split on `;` `&&` `||` `|` `&`,
newlines and parentheses, so `zsh -lc 'cd /tmp && rm -rf ~/'` is one `zsh` command whose `-c` body is read again (`sh`, `bash`,
`zsh`, `dash`, `ksh` and `env -S`, recursively, to depth 4; `$1` and `$@` after the body are filled in). Held: an unbalanced quote
or parenthesis, nesting deeper than 4, `eval`, `source` or `.` of stdin or a substitution, a shell with no `-c` and no script (it reads
stdin: `curl ... | sh`), a here-document or here-string fed to a shell, a command substitution or backtick **in the command word or in
the arguments of a removal** (`rm`, `find -delete`, `chmod -R`, `rsync --delete`, ...), and a removal through `xargs` whose input
is not an `echo`, `printf` or `find` it can read (a substitution inside that input counts as unreadable too). Also held (round 3):
a shell script named `-`, `/dev/stdin`, `/dev/fd/N` or by a substitution (`bash <(curl ...)`), and `alias` or a function
definition in a command line that also holds a remover word anywhere. **Decision (the lead may overrule):** a substitution elsewhere
(`git commit -m "$(cat <<'EOF' ... EOF)"`, `echo $(date)`, `x=$(git rev-parse HEAD)`) is not held, because it is
everyday agent text and holding it would defeat the window: its body is parsed and judged like any command line (so
`echo $(rm -rf /)` is held), and an unquoted here-document body is scanned for substitutions too.

***c.*** *The sudo-ask denylist* (rule `denylist:*`), mirrored from the site helper's `PROTECTED`, `TRIPWIRE`, `ALWAYS_DENY` and
verb lists: any string of the request (command, path, title, reason, raw ACP input; never file content or diff text) containing
`sudoers`, `pam.d`, `sudo.conf`, `sudo-ask-grant`, `sudo-ask-granted`, `/db/sudo-ask`, `secretspec` (the
`sudo-secretspec` broker, its policy, its test boundary), `/usr/local/libexec`, `/usr/local/sbin`, `com.apple.TCC`, `tcc.db`,
`Library/Keychains`, `.keychain` or `dslocal`; and a command that runs `visudo`, `csrutil`, `nvram`, `tccutil`, `fdesetup`,
`pwpolicy`, `systemsetup`, `dseditgroup`, `sysadminctl`, `passwd`, `profiles`, `fdisk`, `gpt`, `asr`, `newfs_*`, `mkfs*`,
`sudo-ask grant|revoke`, `diskutil` with any verb outside the read-only list (so `erase*`, `secureErase`, `apfs delete*`),
`dscl` unless it only reads, or `security` unless its verb is read-only (so keychain edits stay pending). Since the site head `f6dd14ba` (round 2 of its PR) the list also holds the persistence paths a root process could use to outlive
the window, judged as paths (`~`, `..`, links, case and `--opt=PATH` forms resolved) for every command that is not read-only
and for every redirection and file-tool path: `/Library/LaunchDaemons`, `/Library/LaunchAgents` (the root one; `~/Library/LaunchAgents`
is user level and stays allowed), `/Library/StartupItems`, `/private/var/at`, `/usr/lib/cron`, `/private/etc/periodic`,
`/private/etc/zshenv`, `zprofile`, `zshrc`, `profile`, `bashrc`, `/private/etc/paths` and `paths.d`, `/private/var/root`,
`/private/etc/ssh`, `/Library/Security/SecurityAgentPlugins`, `/private/etc/ld.so.conf`, `/dev/disk*`, `login.keychain*`; and the
programs `sntp`, `ntpdate`, `su`, `login`, `at`, `batch`, `chroot`, `crontab` (except `-l`),
`launchctl submit|asuser|bootstrap|load|enable|kickstart` and `date` with a time to set. **Not mirrored on purpose** (they are the
site's rules for what root may run, not for what a user-level agent may do): `ssh`, `tmux`, `screen`, `script`, `expect`, `parallel`,
`watch`, `entr`, `osascript`, a bare `sudo-ask <command>`, the interpreter and agent-writable-path rules (`INVOKER_UID`, scripts and
programs under writable directories) and the hard-link check. `tests/test_ade_approval_window.py` pins the lists to that head
(`git show` of the site worktree; skipped where it is absent). A word such as
`passwd` or `security` counts only where a command stands (first word, after `sudo`/`env`/`time`/...), so `echo passwd` and
`cat /etc/passwd` do not trip it.

***d.*** *A critical-path removal* (rule `critical-rm:*`, `critical-reason` when the card's own title or description says "critical
path", or `unreadable:unparsable:*` where the parser cannot be sure): the removal family `rm`, `rmdir`, `unlink`, `srm`, `shred` (also
GNU `grm`, `gfind` and the like, and any directory or `..` form of the program path), `find` with `-delete` or `-exec`, `-execdir`,
`-ok`, `-okdir` running `rm` or a shell (roots, `-f ROOT` and the default `.` judged), `xargs rm` (the piped `echo`, `printf` or `find`
input judged), `chmod|chown|chgrp|chflags -R`, `rsync --delete*` (the destination) and `git clean -f` (the directory, or `-C DIR`
or `--work-tree DIR`), aimed at `/`, `~`, `$HOME`, `/Users`, a home directory (`/Users/<name>`), `~/Library` and
`~/Library/Application Support` themselves (ancestors of the protected TCC and Keychains paths), `/System` (and its tree), `/usr`, `/etc`,
`/var`, `/private`, `/Volumes/<volume>`, `/bin`, `/sbin`, `/opt`, `/opt/homebrew`, `/usr/local`, `/Library`, `/Applications`, `/tmp`, the
system `bin`/`lib` trees, or `D/<glob>` for any of them (d2). Symlinks are resolved (`/etc` is `/private/etc`). The details, each a rule
with a test:

***d1.*** *Variables* (round 3, revised in rounds 4 and 5). A variable the command line **never sets** is modelled as **empty**, the
failure Claude Code's own check warns about: `rm -rf $S/` is `rm -rf /` and stays pending, `rm -rf $S/<glob>` is `rm -rf /<glob>`,
while the screenshot's `rm -f $S/all.done $S/*.log` models as `/all.done` and `/*.log` and is allowed. A variable the line **sets**
(`NAME=`, `export/declare/local/readonly NAME=`, `for NAME in`, `select`, `read NAME`, `mapfile`, `printf -v`, `${NAME:=x}`, in any
nested `-c` body, before or after the use) is **tracked** when it is set exactly once, by a plain assignment at the top of a command
list (not after `&&`, `||` or `then`, also when a line break only continues the `&&`, `||` or `|`; not inside an `if`, `while`, `until`,
`for`, `select` or `case` body or in a `{ ... }` group (`[ -n "$CI" ] && {` newline `D=...` newline `}`), also when `then`, `do`
and `{` stand on lines of their own; not in a pipeline or before `&`; not when
the request defines a function or alias; and not used after the `( ... )` group it was set in), to one of
three things: a **literal** (no whitespace, no `$(`, not starting with `-`; `~`, `$HOME` and other tracked variables allowed), a
**`$(mktemp ...)`** (alone in the substitution: a fresh temp path, safe to remove, modelled as `/private/tmp/ade-fresh-mktemp`), or the
loop variable of `for NAME in WORDS` with a literal word list (no glob, brace or `$`; at most 32 values, each one judged). A removal
is judged on the real value(s): `S=$(mktemp -d); ...; rm -rf "$S"`, `S=/private/tmp/claude-502/x; rm -f $S/*.log` and
`for f in a.log b.log; do rm -f "$f"; done` pass, while `S=/; rm -rf $S`, `S=~; rm -rf $S` and `for d in /tmp/a /; ...` are
`critical-rm`. Every other set variable is **unknown** and a removal that uses it is held (`unreadable:unparsable:variable $S in a
removal`): a use before the assignment, a name set twice (also `+=`, `unset`, `read`), a value from any other substitution, a prefix
assignment (`S=/ rm -rf $S`), an assignment after `&&` or inside `if` (one line or many), an array (`arr=(~ /tmp/x)`, `declare -a
arr=(~)`: `$arr` is its first element in bash, every element in zsh). So are positionals (`$1`, `$@`, `$*`, `$0`, also inside a
function body), `$PWD`/`$OLDPWD`, and every `${NAME<operator>...}` form, `${S:?}` and `${S?}` included (the check Claude Code suggests
makes the variable error out, but this module cannot tell that it did). When the line **sources** anything (`source F`, `. F`,
`set -a`, `export $(...)`, `eval`; also after `then`, `do`, `else`, `elif`, `if`, `while`, `until`, `time` or `!`), every variable
except `$HOME` is unknown and nothing is tracked, because the file may set any name. The body of a `bash -c` or `sh -c` (also through
`nohup`, `timeout`, `env`, `sudo`) and the line of an `env -S` run in a **new process**: they see none of the values tracked in the
outer line (a child shell gets only exported names, and `sudo` drops those), so an outer name that is set is unknown there, while a
name the body sets itself is tracked inside the body. `$(mktemp ...)` is modelled as a fresh path **only as a removal operand**: it
is never a `cd` target (`S=$(mktemp -d); cd "$S" && rm -rf *` is held, because a failed mktemp makes `cd ""`, a no-op that leaves the
old directory).

***d2.*** *Globs and braces* (round 3, revised in round 4). A glob or brace character (`*`, `?`, `[`, `]`, `{`, `}`) in the first
path component under a critical directory is held: `~/*`, `~/.*`, `~/{*,.*}`, `~/?*`, `~/[a-z]*`, `~/*.*`, `/Users/*`,
`/Users/tester/{.,}*`, `/usr/lo*`, `/Us*rs`. Two exceptions, both narrow. Directly below `/` and below `/tmp` and `/private/tmp`, a name
pattern that ends in an extension (`*.log`, `?*-old.txt`: stars or `?`, optional name characters, a dot and 2 or more letters or digits)
does not reach everything: `/*.log` (what `$S/*.log` becomes with S empty) and `/tmp/*.log` are allowed. Below `/tmp` and
`/private/tmp` only, a pattern with a literal stem of 2 or more characters and no leading dot (`/tmp/claude-*`, `/private/tmp/prefix-*`,
`/tmp/pytest-*.log`) is allowed too. Under home, `/Applications`, `/Library`, `/Users` and the rest there is no exception:
`~/*.log`, `~/*.app`, `/Applications/*.app`, `/Users/tester/*-old.txt` are held. Below a critical `tree` (`/etc`, `/usr/bin`,
`/System`...) every path is already critical, glob or not. A glob deeper than the first component under a non-critical directory
(`~/src/*`, `/var/folders/*/x`) is not held.

***d3.*** *The working directory* (round 3, revised in rounds 4 and 5). The request's own `cwd` is the start, and `cd` (also `pushd`,
`popd`) is followed within one command line, but a `cd` changes the judged directory only while `&&` (or `|`) keeps joining the
statements after it, or when `||` is followed by `exit` (round 5: `return` leaves only inside a function, which the module holds
anyway, and `break` and `continue` only inside a loop; at the top level bash prints an error and goes on). A line break after `&&`,
`||` or `|` does not end the join (`cd /tmp/x &&` newline `rm -rf *` is judged in `/tmp/x`). At the first `;`, newline, `||` or `&`
after the chain (`cd /tmp/x && ls; rm -rf *`) the cd may have failed, so the directory is **unknown**; when the request's own
directory is known, the removal is judged against **every** directory the line may be in: the one the chain started from and each
one a later `cd` in the chain left (`cd ~ && cd build; rm -rf *` is held in `~/src/x` because the second cd may fail; `cd /tmp/x && ls;
rm -rf *` is allowed in `~/src/x` and held in `~`). `git clean` uses the same list. A `cd X || break` or `|| continue` makes `X`
certain only inside its loop: at the `done` the directory is unknown. A `$( )` or backtick body is scanned before the statements
run, so once the line holds any `cd`, `pushd` or `popd` it is judged twice, in the request's directory and in an unknown one. A
`git clean` after a broken chain that began in an unknown directory is also judged in the directory the cd would have reached. After `|` the cd ran in a pipeline stage and the outer directory is unchanged. A `( ... )`
group (and a `sh -c` or `$(...)` body) gives the outer directory and the outer variables back when it ends. So `cd ~ && rm -rf *` and
`cd / && rm -rf ./*` are judged against `~` and `/`, `cd build && rm -rf *` against `build`, and `cd build; rm -rf *`,
`cd build || true; rm -rf *`, `cd /tmp/x; rm -rf *` and `(cd /tmp/x); rm -rf *` (with no outer directory) are held. A Paseo Claude
request carries **no** `cwd`, so the start is unknown too: a relative removal that reaches all of its directory (`.`, `..`, `../x`, a
bare glob such as `*`, `.*`, `./*`, `*.*`, `?*`, `[a-z]*`, `{a,b}*`) is held, and `rm -rf ./build`, `rm -f *.log`, `rm -rf build/*` are
not. From an unknown directory a `find` that starts at `.`, `..` or a glob and deletes (`-delete`, `-exec rm`, `-execdir rm`, also
`find ... | xargs rm`) is held **unless a narrowing name test is present**: `-name`, `-iname`, `-path` or the like with a pattern that
has no glob character at all (`-name node_modules`) or at least two literal characters, one a letter or digit (`-name '*.pyc'`,
`-name 'core.*'`), or `-empty`. Round 5: only the tests **before the first action** (`-delete`, `-exec`, `-execdir`, `-ok`,
`-okdir`) count, because find evaluates left to right and a test after the action filters nothing (`find . -delete -name '*.pyc'` is
held). `-type`, `-mtime`, `-size`, `-user`, `-newer`, `-perm`, `-name '*'` and `-name '*.*'` do not narrow it, and neither does an
expression with `!`, `-not`, `-o` or `,`. When the find feeds `xargs rm`, a `-print`, `-print0`, `-printf`, `-ls` or the like counts as an
action too, since it hands every path found so far to xargs (`find . -print0 -name x | xargs -0 rm` is held). A `cd` to a substitution or a variable (`cd "$(echo ~)"`, `cd $X`, `cd -`,
`popd`) followed by a removal with a relative operand, or by `git clean -f`, is held; a `cd` to a tracked variable (d1) is followed.
`git -C DIR` and `git --work-tree DIR` follow the same rule; a `git -C "$(...)"` or `-C $VAR` is unreadable (held), and an `xargs` fed
by a substitution counts as unknown input.

***d4.*** *The textual tripwire and command words* (round 3, revised in round 5). Anywhere in a command line, after quotes, backslashes
and `$'...'` (decoded) are removed, a **remover word** (`rm`, `rmdir`, `unlink`, `srm`, `shred`, `trash`, `rip`, `rimraf`, `del-cli`
(the two JavaScript tools are never judged, so every form of them, `npx rimraf dist` included, keeps the card), the GNU `g` forms, `-delete`,
`--delete*`, `git clean`) that the parser did **not** itself judge as a removal holds the request. That covers `parallel`, `ssh`,
`fd -X`, `flock`, `script`, `tmux send-keys`, `xargs -J`, `alias`, `docker rm` and the like without parsing each. The words of a
removal the parser did judge (the program word, the `-exec` word of a `find` it judged, a `-c` body it recursed into), and the
arguments of programs that only carry text (`echo`, `printf`, `grep`, `rg`, `cat`, `git`, `gh`, `man`, `paseo`, ...), are not counted.
A command word that is not a plain word (written with quotes or a backslash, or holding `$`, `{`, `?`, `*`, `[`, or starting with `=`;
`[` and `[[` excepted) is held. `noglob`, `nocorrect`, `builtin`, `coproc`, `command` and `exec -a NAME` are followed like `sudo` and `env`
(whose long `--user`, `--group`, `--unset` options take a value, as do `xargs -d -J -R -S -a`). The positional parameters of a `sh|bash|zsh -c` body named on the line (`sh -c 'rm -rf "$1"' _ /`) are filled in; when `xargs`
feeds the shell (`... | xargs -0 sh -c 'rm -rf "$@"' _`) the parameters beyond those given are the feed, which is judged like the input of
a bare `xargs rm` (a narrowed `find`, an `echo` of safe paths; anything else is unknown and held; round 7). Round 8: the feed is judged whenever xargs
feeds a shell body that removes, moves (`mv`), changes recursively or runs `git ... clean`, whatever the way the feed arrives (`$@`, `$N`,
the `-I{}` or `-I %` replacement string); a bare xargs-fed `mv` judges its feed the same way.
A python, perl, ruby, node, php or osascript
one-liner (`-c`, `-e`, `--eval`, a here-document or here-string) whose text names `rmtree`, `unlink`, `remove`, `rmdir`, `rm -`, `rmSync`,
`do shell script`, `delete` or `trash` is held; a script file is not read. Round 4 extends the one-liner check to the runners that
start an interpreter (`uv run python -c`, `uvx`, `pipx run`, `poetry run`, `npx node -e`, `bunx`, `pnpm`, `npm`, `pdm`, `rye`,
`hatch`), judges `mv` like a removal of its sources (`mv ~ /tmp/gone`, `mv ~/Library ~/L.old`, `mv -t DIR ~` are held), and reads the
command lines that `git` runs (`git submodule foreach CMD`, `rebase --exec CMD`, `-x`, `bisect run CMD`, `-c alias.x='!CMD'`) for
remover words, though `git` otherwise stays a program whose arguments are only text. A path that has a glob component and then a `..`
(`/tmp/cl*/../../../Users/tester`) is judged by its whole normalised path (round 5). Not judged, noted only: the zsh `$~S` and `$=S`
expansion forms (`S=/; rm -rf $=S`), which are written only to evade.

***2.*** **Allowed** (rule `allow:window`): everything else, any agent, any provider. In particular **the "possibly-empty variable"
class from the screenshot is allowed**: `rm -f $S/all.done $S/*.log` models as `/all.done` and `/*.log`, which name no critical
path. Allowed are also MCP tools, WebFetch, ordinary Bash and file edits, and the hold list of `bin/ade-auto-permit`
(`respond_to_permission`, `set_agent_mode`, ...) is **not** applied: the operator's ruling is no prompts while the window is open.
Also allowed by that ruling, and worth knowing: a Bash call with `dangerouslyDisableSandbox: true` (a sandbox escape), WebFetch of any
URL, `mcp__paseo__create_agent` with `mode: bypassPermissions`, tools whose only argument sits under a content key
(`{"text": "rm -rf /"}` on an unknown tool; content keys are not scanned), and, in non-interactive sessions, a call that would have been
auto-denied for want of a hook decision.

***2a.*** **What passes on purpose** (the guard is for careless commands, so these are known and accepted): a script file the agent
wrote and runs later (`bash script.sh`, `python3 script.py`: its text is not read) and `source FILE`; a substitution anywhere except in
a removal's operands or the command word (its body is parsed and judged); a removal with a literal operand below a critical directory
(`rm -rf /Users/tester/src/old`); `rm` of a narrow glob (`/tmp/*.log`, `/tmp/claude-*`); a `find . -name '*.pyc' -delete` (a narrowing
name test, d3) from an unknown directory; a removal of a variable set once to a literal or `$(mktemp ...)` (d1; a failed `mktemp` makes `rm -rf "$S"` an `rm -rf ""`, accepted); `git clean -f` with no path in the unknown directory; a link made after the check; a program that deletes through
its own code (`make clean`, `git filter-branch`, `docker`/`aws`/`gh` actions on remote things; their arguments are not read for
remover words when the program only carries text); and anything the shell assembles from a variable the line never sets. Hostile
commands can reach the shell in ways this parser misreads; see V 4.

***3.*** **Window closed** (missing, expired, revoked, or any check above fails): nothing at all. The responder does not contact
the daemon, writes no log line, and the hook prints nothing.

## IV. How it answers (Paseo's interface, read from source on 2026-11-22)

Paseo's loopback Agent MCP route, `POST http://127.0.0.1:7263/mcp/agents` (`daemon.listen` in `~/.paseo/config.json`; stateless
streamable HTTP, no session; `packages/server/src/server/bootstrap.ts:1537`, open when no daemon password is set, as here):

- `list_pending_permissions` (`packages/server/src/server/agent/tools/paseo-tools.ts:3211`) returns every pending request of every
  agent with the whole request: `name`, `kind`, `title`, `description`, `input`, `detail`, `metadata`.
- `respond_to_permission` (`paseo-tools.ts:3245`) takes the exact `agentId`, `requestId` and `{behavior: "allow"}`.

Why not the CLI: `paseo permit ls --json` rows carry only `id`, `agentId`, `name` and `description`
(`packages/cli/src/commands/permit/ls.ts:8-14, 28-38`). A Claude Bash request has no description, and its command lives in `input`
and `detail` (`providers/claude/agent.ts:5030-5067`; Paseo does not forward the SDK's decision reason), so the CLI cannot tell
`rm -rf /` from `ls`. `paseo permit allow AGENT REQUEST` (`permit/allow.ts`) matches request ids by prefix; the MCP tool is exact.
The responder refuses any daemon URL that is not `http://<loopback>/mcp/agents`, bypasses proxies, and treats any unreadable
answer as an error with nothing approved.

```sh
bin/ade-approval-window status [--json]            # exit 0 open, 1 closed; never contacts the daemon
bin/ade-approval-window respond --once             # one sweep
bin/ade-approval-window watch [--interval S] [--duration S]
```

`watch` polls every 2 s at most (a smaller `--interval` is raised to 2) and contacts the daemon only while a grant file exists. The
window is re-read before **every** allow. One responder per audit path (a lock file), so overlapping runs never double-answer.

Audit: `~/.local/state/djbclark-ade/approval-window/permits.jsonl` (mode 0600), one line per decision: `time` (UTC), `agent`,
`provider`, `tool`, `request`, `command` (at most 200 characters, credential-looking text replaced by `<redacted>`), `decision`
(`allow`, `hold`, `error`) and `rule`. The `allow` line is written **before** the answer is sent; a log that cannot be written
means nothing is allowed. The hook's lines carry no tool id (Claude gives the PermissionRequest hook none), so its `request` is `<session>:sha256-<12 hex of the tool input>`. Held requests are logged once per `watch` run (a one-shot `respond` or a new run logs them again).

## V. Threat notes

***1.*** **An agent cannot open or extend a window.** The grant file and its directory are root-owned and not writable by the
operator's user; only the root helper writes them, and `grant` needs Touch ID (the site's sudoers drop-in).

***2.*** **No new power.** An agent can already call `paseo permit allow` or the MCP `respond_to_permission` itself today (Paseo
has no per-caller authorization on its loopback routes). This tool adds no capability beyond automating the operator's own Accept,
inside a window the operator opened.

***3.*** **It approves for ALL agents on the machine, a compromised one included, until the window expires or is revoked.** A prompt
injected into one agent can have its next Bash card answered. The window is the bound: pick the shortest duration that covers the
work, and `sudo-ask --revoke` ends it.

***4.*** **The denylist and the critical-path rule are guard rails against careless commands, not a sandbox and not a security
boundary** (adversary rounds 1 and 2 broke the earlier, tighter claims with forms such as `$'\x72m'`, `xargs -d`, `exec -a`, `sudo --user`,
`fd -X`, a loop variable and `~/{*,.*}`; the answer was to fail closed and add the textual tripwire, not to out-parse the shell).
It reads the text of the request, with shell quoting and `//`, `.` and `..` in paths removed. **A variable, a glob (`v?sudo`,
`/etc/sudo*`), a link to a denied program, a script the agent wrote first and ran later, or `python3 -c` that opens `/etc/sudoers`
are not seen** (the denylist half; round 2 LOW 4, kept as documented). The same limits the site helper
documents for root commands apply. (The prompts replaced here belong to agents that run as the operator, not as root, so the
worst case is the operator's own files, which a bypass-mode agent could already change.)

***5.*** **Fail closed everywhere**: a window that cannot be proven open, a daemon answer that is not Paseo's shape, an unwritable
audit log, an unreadable request: nothing is allowed.

***6.*** No `ade.kind=external-review` hold (`bin/ade-auto-permit` has one): the operator's rule here is "any agent". No launcher sets
that label today.

## VI. Enabling it (installed live on bigmac 2026-11-23)

Live status (2026-11-23): with operator approval, `djbclark-ade` PR #939 was installed live on `bigmac` —
`~/.claude/hooks/approval_window_permit.py` symlink, the `PermissionRequest` hook entry in `~/.claude/settings.json`, and
launchd `com.djbclark.ade-approval-window` (60 s interval). The `sudo-ask-grant` root window itself is installed via
`site-djbclark`. The hook's effect on an already-showing prompt still needs a live check (section VII 1).

***1.*** Open a window: `sudo-ask grant 2h` (the site tool, installed via `site-djbclark`; Touch ID). Check: `bin/ade-approval-window status`.

***2.*** Paseo agents: either run `bin/ade-approval-window watch` in a Paseo terminal, or render the launchd template
`config/launchd/com.djbclark.ade-approval-window.plist` (`bin/ade-sched render`, then install after the operator's yes; its
log directory must exist; installed live on `bigmac` on 2026-11-23). It runs `watch --duration 50` every 60 s (an
`ade-job-run` admission lock covers the whole run, so a reconcile defers while one runs).

***3.*** Non-Paseo Claude Code: the hook is registered in `agents/claude/settings.json.tmpl` under `PermissionRequest` (matcher `*`, behind
`hook-deadline 8`, outer timeout 15, after Orca's own entry); on a new host it takes effect when the operator
applies the template (`bin/ade-settings-apply`) and `ade update` links the hook (installed live on `bigmac` on 2026-11-23).

## VII. Open items (live checks the lead makes)

***1.*** Whether a `PermissionRequest` hook's allow clears a prompt that is already showing (the interactive countdown) is
**not documented**; hooks.md says only that the hook runs when Claude Code "is about to ask you for permission", and that for a
call that reaches an Agent SDK `canUseTool` callback the hooks "run alongside your host, and whichever decides first applies".
So, for Paseo's own Claude agents, the hook (if their settings load it) may also win the race; the responder is the primary route
there and is the same policy either way.

***2.*** Codex file changes (`CodexFileChange`) and other requests that expose no path stay pending by rule (III 1b).

***3.*** The grant schema and the denylist are mirrored from the site branch `feat/sudo-ask-grant-window` (pinned head `f6dd14ba778bb76bbbb0df226659de9754e4993e`); when the site tool changes either,
update `read_window` and the lists here in the same change (`tests/test_ade_approval_window.py` pins both).

***4.*** `ade-auto-permit` (a separate, name-only, always-on sweep, template only) is unchanged.

Tests: `tests/test_ade_approval_window.py` (the checker, the policy, the responder against a fake daemon and against a fake HTTP
opener that speaks Paseo's MCP framing, the CLI, the hook). Nothing in them opens a socket or reads the real grant, daemon or log.
