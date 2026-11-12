# Upstream review gate: `claude/hooks/upstream_review_gate.py` (2026-11-12)

A Claude Code `PreToolUse` hook that denies a write CFEngine upstream would see. Operator ruling, djbclark 2026-11-12:
"Re-enable, CFEngine-only". Background and the rules it serves: `cfengine-all/AGENTS.md`, "Upstream contributions -
standing rules" (upstream closed all 26 PRs and 26 Jira tickets of this effort in August 2026 and wants one bug, one
small PR, a human in the loop). It replaces `~/.claude/hooks/upstream_review_gate.sh`, an unversioned shell hook that
has been registered in no settings file since about 2026-08-24.

**A. What is gated** (everything else, other third-party repos included, passes: agents file upstream issues there
under a separate rule):

1. `gh` writes and `git push` whose target is a GitHub repository of the owners `cfengine` or `NorthernTechHQ` (any
   repo, any case).
2. A mutating request to `*.atlassian.net`: curl, wget, httpie or xh with `-X POST|PUT|PATCH|DELETE` or a data flag
   (`-d`, `--data*`, `--json`, `-F`, `-T`; `-G` with `--data-urlencode` is a GET and passes).
3. A Composio Jira write: a command with `composio` + `jira` + a write word, or a Composio MCP tool call carrying a
   `JIRA_<CREATE|UPDATE|ADD|EDIT|DELETE|ASSIGN|TRANSITION|COMMENT|REMOVE>` slug.

Reads are never gated: `gh pr view`, `gh api` GETs, `gh repo fork`, anonymous Jira GETs, `git fetch`.

**B. How the target is found** (gaps of the shell gate, both found 2026-11-12: `gh api -X PATCH repos/OWNER/NAME/...`
was judged by the cwd's remotes, never the path; `gh api -f/-F` with no `-X` is a POST in gh and was not seen):

1. Explicit target first: `-R/--repo` (also `HOST/OWNER/REPO`), `GH_REPO=`, a github.com URL (`gh pr comment <url>`),
   an `OWNER/NAME` positional naming a gated owner, `--owner`, and for `gh api` the endpoint (`repos/OWNER/NAME/...`,
   `/repos/...`, `orgs/OWNER/...`, a full `api.github.com` URL). Gated -> deny, ours -> allow.
2. No explicit target (`gh pr create`, `repos/{owner}/{repo}/...`, `repositories/ID`): the working directory's remotes,
   after any `cd` earlier in the command. A remote of a gated owner denies, because gh defaults a fork's `pr create`
   to the parent. `-R djbclark/<repo>` says the fork is meant.
3. `gh api graphql`: only a mutation is a write; denied when a gated owner appears in the command or in a file it reads
   (`-F query=@file`, `--input`), or when no repository is named and the cwd is a gated fork.
4. Write detection for `gh api`: a non-GET `-X/--method`; with no `-X`, any of `-f -F --field --raw-field --input`
   (an explicit `-X GET` makes them query parameters). For other groups (`pr issue release repo label workflow run
   secret variable project ruleset cache`): any verb that is not a read verb.
5. `git push`: the remote (named, URL, `--repo`, or the branch's `pushRemote` / `remote.pushDefault` /
   `branch.<b>.remote` / `origin`) resolved with `git remote get-url --push --all`. A libntech worktree whose origin is
   `NorthernTechHQ/libntech` cannot `git push` bare; `git push fork ...` and `git push -n` pass.

**C. Parsing.** `shlex` over the command. `;`, `&&`, `||`, `|`, `&`, newlines, parentheses and backticks separate
simple commands; any gated write in any of them denies. `$( )`, backticks, `bash -c STR`, `eval`, and heredocs fed to
a shell are analysed again; wrappers (`env`, `sudo`, `timeout`, `xargs`, `nohup`, `rtk`, `bg`, ...) are looked
through; heredoc bodies fed to `cat`, `git`, `gh` are data. Quoting shlex cannot parse (or a command over 100 KB, where shlex is quadratic) falls back to splitting on the
shell operators with redirections dropped, so a stray apostrophe does not let a gated write through. Comments are
removed; shell keywords (`do`, `then`, `if`, ...) are skipped; assignments (`R=cfengine/core`, `export GH_REPO=...`,
`GIT_DIR=`) are expanded into later `$R` words and carried into nested `bash -c`/heredoc commands; `( ... )` and
`$( ... )` restore the directory and environment on exit; `$(which gh) pr ...` is read as `gh pr ...`; a 10 s
alarm ends a pathological input with exit 0. The hook fails closed only for a gated
target: unrelated commands, malformed input and any internal error exit 0 with no output.

**D. Contract.** Deny is stdout JSON `permissionDecision: "deny"` plus a reason that names the target, not the payload
(it may carry tokens), and says that djbclark runs it or lifts the gate. The operator's off switch is
`UPSTREAM_REVIEW_GATE_OFF=1` in the Claude environment; an assignment inside the command is not read.

**E. Known limits.** A script or `just` recipe that runs `gh`/`git` itself is not seen. A fork with only an `origin`
remote (its parent known only to the GitHub API) is not detected for a bare `gh pr create`: the hook makes no network
call. `jj git push`, `ssh host gh ...` and Jira on `api.atlassian.com` are not parsed. Python or Node code that
posts to Jira is not seen. A `case` pattern's `)` inside `"$( )"` ends the substitution early; a dynamic
`--git-dir` and a `cd` into a directory created earlier in the same command are judged by the old directory; a
remote name only known at run time (`for r in $(git remote)`) is judged by the cwd's remotes, so name the remote
literally.

**F. Registration (not done by the PR).** Add a `PreToolUse` entry to `~/.claude/settings.json` (and the template
`agents/claude/settings.json.tmpl`) with matcher `Bash|mcp__.*[Cc]omposio.*` running
`python3 "$HOME/.claude/hooks/upstream_review_gate.py"`, and link the file the way the other hooks are linked. The
lead registers it after the merge.

**G. Tests.** `tests/test_upstream_review_gate.py` (temporary git repos for the remote cases).
