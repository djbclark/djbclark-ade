# The `gh` shim: the adversary-marker gate in the `gh` process (mg-52, 2026-11-16)

**Operator ruling (2026-11-16, B2 + B5):** build the `gh` PATH shim, keep the Claude hook as a backstop, and narrow the promise. The
hook (`claude/hooks/adversary_marker_gate.py`, rule 14 of [code-review.md](code-review.md)) read the text of a Bash command, and PR 749
showed that this has no end: twelve review rounds, and since round 9 every block was one more token variant of redirect or assignment
lexing. The shim reads the real thing instead.

## A. What it is

A. `libexec/agent-bin/gh` (POSIX `sh`, marker `# ade-gh-shim:`) and its helper `bin/ade-gh-guard` (python3), modelled on the `paseo` shim
([archived-send-guard.md](archived-send-guard.md) section 2). The shim finds the real `gh` (`ADE_REAL_GH`, else the first executable `gh` on
`PATH` that is no copy of the shim), runs it untouched when no argument is `pr`, `issue` or `api`, and otherwise hands the call to the helper.

B. The helper sees the real argv, the real cwd, the real operand files and the real stdin. It finds the write with the hook's own
`gh_invocation`/`is_write` (`pr`/`issue` `create`, `new`, `edit`, `comment`, `review`, `close`, `reopen`; `api` with a body flag) and judges it with
the hook's own `judge(..., argv=words, stdin_path=...)`: directly on the already-expanded process words (2026-11-24, queue #117), so no shell
re-quoting or command-substitution expansion runs on prose containing backticks or `$(...)`.
One module, no copy: a change to the marker rules in the hook is a change to the shim. A stdin the argv reads (`--body-file -`, `-F-`, `--input -`,
`-F body=@-`) is spooled whole (no size cap: the real `gh` submits exactly the bytes the caller sent) into a private temp file, judged via `stdin_path`
(the gate reads no file over `MAX_FILE`, 256 KiB: a stdin larger than that is judged on its first 256 KiB, and still reaches `gh` whole), and handed to the real `gh` as its fd 0.

C. A refusal is exit 4 and one line on stderr; nothing runs. Everything else is `os.execv(real_gh, [real_gh, *argv])`: same argv, stdin,
exit status and environment (the helper pops `ADE_REAL_GH`; only when the real `gh` is itself a script does the shim set `ADE_GH_SHIM_DEPTH`,
a re-entry counter capped at 8, exit 127).

D. Failure modes: it **fails open** on its own failure (no `python3`, no helper, an error before the judgement: the real `gh` runs, one line on
stderr); it **fails closed only** for a write that takes a body that the gate could not read (an exception inside `judge`).

## B. Install

A. Nothing links the shim into `~/.local/bin`. It guards a `gh` only where `gh` resolves to `libexec/agent-bin`: put that directory first on `PATH`
(`PATH="<checkout>/libexec/agent-bin:$PATH"`), or run `<checkout>/libexec/agent-bin/gh` by its path. The ade-claim plugin's W4
`agent.open.before` hook already prepends this directory to an agent's PATH in `enforce` mode ([git-guard.md](git-guard.md)); with it, the shim
is installed for every agent the plugin opens. The Claude hook stays registered as before (`agents/claude/settings.json.tmpl`).

B. Update path: the shim and helper are files of this checkout (`ade update`, [skill-everywhere.md](skill-everywhere.md)); there is no copy to refresh.

## C. What it never catches

A. The promise is narrow on purpose (rule 14): the gate stops an agent's careless marker text, not deliberate obfuscation. It does not see:
an absolute path to the real `gh`; `curl`, `python` or `node` with a token; the GitHub MCP or the web UI; the owner's own shell and
`bin/ade-merge-ready approve-post` (the operator's route); a `gh alias` that expands to a write (the shim sees the alias name, not its
expansion); a bash process whose startup file rewrites `PATH` (the `paseo` shim has the same limit: `env -u BASH_ENV`, or a PATH kept by the caller);
a marker that sits past the first 256 KiB of a stdin stream (GitHub rejects a body over 65,536 characters, so only a payload padded with other fields can hide one); a marker that a program the shim does not run assembles after `gh` has read its input (a `gh` extension, a pager).

B. The hook still covers a command typed in a Bash tool call that names a `gh` write, through an absolute path or a PATH without the shim, with the
limits listed in rule 14 (PR 749's record holds the lexing rounds; no new lexer work).

## D. Tests

`tests/test_ade_gh_guard.py`: a fake real `gh` that records argv, stdin and environment; pass-through of reads and clean writes (same argv, stdin,
exit status), the marker in each body route (inline, `--body-file`, `-F`, `@file`, `--input`, stdin, JSON payload, GraphQL), recursion and shim-copy
skipping, an environment with no shim variable for a binary `gh`, no `python3`, and a write the gate cannot read.
