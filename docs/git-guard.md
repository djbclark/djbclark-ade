# ade-git-guard — git hooks guard the refs, a small shim guards the rest

**Built 2026-10-24 (isolation slice W1); redesigned 2026-10-25 ("O2", PR 59).** A seatbelt, not a sandbox: it stops an
agent's accidental or careless git, not one that works at it. Code: [`libexec/git-hooks/`](../libexec/git-hooks/)
(`reference-transaction`, `pre-push`: bash 3.2 stubs), [`bin/ade-git-guard`](../bin/ade-git-guard) (bash front door,
installed as the PATH shim `libexec/agent-bin/git`) and [`bin/ade_claims.py`](../bin/ade_claims.py) (claim library, hook
rules, shim rules). The module docstring of `ade_claims.py` is the rule-by-rule reference; this page is the operator's
summary. Tests: `tests/test_ade_git_hooks.py` (the real git, the hooks), `tests/test_ade_git_guard.py` (the shim, the
claim library).

## Why two enforcement points (2026-10-25)

Nine adversary rounds (r1-r9) each found another argv spelling of the same final event: git writes `refs/heads/<claimed>`
(`fetch . main:heads/cb`, `pull --set-upstream`, `--multiple --no-multiple`, `remote -v update`, `-c fetch.parallel=4`,
`--namespace`, `--attr-source`, `--shallow-file`, the default remote ...). A parser of git's grammar is always one release
behind it. Git's `reference-transaction` hook is called for every ref update of every command, in `prepared` with the
fully resolved ref name, and a non-zero exit aborts the transaction. So:

1. **Refs are guarded where git has already done the resolving: the hooks.** The same event is refused whatever argv wrote
   it. Nothing in the hook parses an option.
2. **The shim guards only what a hook cannot see** (a foreign workspace, the shared checkout's destructive forms, worktree
   verbs, rename/copy destinations), and **fails closed** on what it cannot read: under the old design a parser miss was a
   bypass, now it is a false refusal with a readable message.

## Integration status (2026-10-25)

The guard, the hooks and the claim library exist. Nothing calls them in a live session yet. Call sites to wire (not done
in this PR): W2 `cow-pasture create` runs `ade-git-guard install <new pasture>` (a pasture's `clonefile` copy of `.git/hooks`
inherits a stub anyway); W3 `acp-dispatch` exports `ADE_CLAIM_ID` and runs `ade-git-guard install` in the repository at
claim time; W4 `acp-run` puts `libexec/agent-bin` first on the PATH of every agent it launches; the operator runs
`ade-git-guard install <repo>` once over `~/src/*` and `~/orca/projects/*` (the dangerous case is agent B in primary P moving
Z's branch: the hook must be in P; the shim also installs it the first time an agent runs a non-read git there). The
operator's shell, Orca and IDEs never go through the shim.

## Commands

| Command | What |
|---|---|
| `git ARGS...` (the shim) | Run the real git, or refuse: exit 77, the reason on stderr, one line in `guard.log`. |
| `ade-git-guard git-ARGS...` | The same, called by name. |
| `ade-git-guard install [DIR]` | Write the chain-preserving hook stubs into `$(git rev-parse --git-common-dir)/hooks` of DIR's repository (one install covers every linked worktree). Idempotent. An existing hook of the same name is renamed `NAME.pre-ade` and runs after ours. Exit 0 ok, 2 not a repository, 78 `core.hooksPath` is set (git would never run the stubs; unset it or call the stubs from the directory it names), 73 `NAME.pre-ade` is already in the way. |
| `ade-git-guard --real-git` | Print the git the guard would run. |
| `ade_claims.py new --id ID --path DIR --branch B --base-sha S [...]` | Create a claim and its pointer; exit 3 id exists, 4 path held by another owner's active claim. |
| `ade_claims.py show ID [--field F]`, `find [DIR]`, `list [--state S] [--json]`, `set-state ID active\|released\|merged` | Read and change claims; exit 1 when not found. |
| `ade_claims.py guard -- GIT_ARGS...` | What the shim runs. |
| `ade_claims.py hook-ref STATE`, `hook-push REMOTE URL` | What the two hooks run (stdin is git's). |

Exit codes: 77 = refused (`EX_NOPERM`); any other code of a shimmed call is the real git's (a call a hook refused ends
with git's own 128 and `fatal: ... aborted by the reference-transaction hook`). Every `ade_claims.py` subcommand exits 0
ok, 1 not found, 2 usage, 3 id exists, 4 path owned by another owner's active claim, 77 refused; `install` also 73 and 78.

## Who is guarded

The shim: agents only (`ACP_RUN_AGENT=1` or `ADE_CLAIM_ID` set). A human shell, git's own hooks (`GIT_INDEX_FILE`) and
pre-commit (`PRE_COMMIT`) are never refused. The hooks: those, and also a caller with `CLAUDECODE`, `OMPCODE` or `CODEX_*`
set and no claim identity, who is an agent that may write nothing claimed. A shim crash, a missing `python3` or an
unexpected exit **fails open** (a warning on stderr, the real git runs).

## The hooks (refs)

`reference-transaction` refuses in the `prepared` state only (`preparing` still has unresolved symrefs). Rules:

1. **Claimed branch.** An update of `refs/heads/<b>` (creation, update, deletion, a `0 0` line) while another owner's
   active claim, of a repository whose `remote.origin.url` matches the claim's `repo_origin`, names `<b>` or has `<b>`
   checked out in its workspace.
2. **Foreign workspace.** A `HEAD` or `refs/heads/*` update while the hook runs in a workspace another agent claims (git runs
   hooks with the work tree as cwd and `GIT_DIR` exported, so `-C`, `--git-dir`, `checkout`, `switch`, `commit` there are all
   seen).
3. **Stash.** A `refs/stash` update in a linked worktree (refs/stash is shared by every worktree).
4. **`committed`** appends one line to `guard.log` per change to a claimed branch (actor, ref, old, new) and never fails; this
   records the actor even for a bypass.

`pre-push` refuses a push to `refs/heads/<b>` (deletion included) claimed by another owner of the repository the URL names.
`git push --no-verify` skips it, so the shim refuses that.

**Fail open.** A hook that fails aborts git for everyone, the operator included, so the stub maps exactly "python exited
77" to exit 1 and everything else (no python, a traceback, the 10 s alarm) to exit 0. **Fast path:** a caller with no agent
marker exits before anything else runs; an agent's call whose stdin names no `HEAD`, `refs/stash` or `refs/heads/` line
(a fetch of remote-tracking refs and tags) exits after one `grep`, without Python. Measured 2026-10-25, git 2.56: a fetch
of 500 updated branches opens ~500 reference transactions (one per ref); the test shows Python starts zero times for it.
A hook never runs a ref-writing git (the transaction's locks are held); it reads `.git/config` itself.

**`pack-refs`/`gc`.** `git pack-refs --all` reports every ref it packs as `0 <sha> <ref>` and every loose ref it prunes as
`<sha> 0 <ref>` without changing a value, so beside any claim it would be refused. The stub exports its parent pid
(`ADE_HOOK_GIT_PID`); when that git process is `pack-refs` (which `gc` and `maintenance` spawn) the hook lets it through.
A real `branch -D` of the same packed ref is still refused (tested).

**Chain.** The installed stub runs the ade checkout's hook by absolute path (one copy of the logic; a pasture's cloned `.git/hooks`
keeps working), then, if present, `NAME.pre-ade`. A refusal stops before the old hook runs. Install is atomic (temp file +
`os.replace`) and the stubs are bash 3.2 (tested with `/bin/bash -n`).

**Lazy install.** The shim's slow path installs the stubs the first time it meets a repository without them, after it has
allowed the call and before the real git runs, so the very first `git branch -f cb` an agent runs in an unprepared repository
is already guarded. Never in a directory that is not a repository, never while `core.hooksPath` is set, never fails the
user's command.

## The shim (what a hook cannot see)

Evaluated in order; the module docstring has every form.

1. **Fail closed.** A leading option git does not define, or one with no value (`unknown-option`); a subcommand that is not a
   git builtin, not an alias and not in `KNOWN_SUBS` (`unknown-subcommand`: external `git-foo` programs are refused; the
   operator can allow one call with the override). Config on the command line or in the environment (`-c`, `--config-env`,
   `GIT_CONFIG_COUNT/KEY_n`, `GIT_CONFIG_PARAMETERS`) whose key, after normalisation, is `core.hookspath` or starts with
   `hook.`, `include.` or `includeif.`; a `git config` write of such a key or `--edit`; a `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM`
   file that sets `hooksPath` or has a `[hook]`, `[include]` or `[includeIf]` section (`hook-config`). `push --no-verify` (any `--no-v`
   prefix; `push-no-verify`) and `send-pack`/`http-push`, which never run `pre-push` (`push-plumbing`).
2. **Foreign workspace, coarse and read-only.** When the cwd, or any `-C`, `--git-dir`, `--work-tree`, `GIT_DIR` or
   `GIT_WORK_TREE` value the call types (even one a later option moves git away from), resolves under another agent's active
   claim, only an allowlist runs: `status`, `log`, `show`, `diff`, `rev-parse`, `ls-files`, `ls-tree`, `cat-file`, `blame`,
   `describe`, `rev-list`, `for-each-ref`, `grep`, `shortlog`, `name-rev`, `merge-base`, `version`, `help`, and the read forms
   of `branch` (a listing), `remote` (`-v`, `get-url`), `config` (`--get*`, `--list`), `worktree list`, `symbolic-ref`. `fetch`,
   `stash list`, `tag -l`, `ls-remote`, `show-ref` and everything else is refused there. `--output` of diff/log/show/shortlog and
   `grep -O` are refused where the guard is asked (the bash fast path for the allowlisted subcommands scans no argument: a
   stray file in another agent's tree is a nuisance, not lost work).
3. **Shared checkout (no claim):** `stash`, `reset --hard|--merge|--keep`, `checkout -f|-p|<path>`, `restore` of the work
   tree, `switch -f`, `clean`, `rm -f`, `commit -a`, `add -A|-u|.`, autostash, `rebase -x`, `!` aliases. An abbreviated long
   option counts as the dangerous option it may stand for.
4. **Linked worktree, even its owner's:** `stash`, `rebase -x`, `!` aliases.
5. **Targets no hook sees:** `worktree remove|move|prune` of a claimed worktree; the destination of `branch -m|-M|-c|-C` (the
   files backend reports a rename's source deletion to the hook, never its destination, and a copy not at all: measured
   2026-10-25; queued upstream, below).

**Removed in O2 (replaced by the hooks):** the fetch/pull/remote-update dry-run preflight, the push dry-run preflight, the
`update-ref`, `branch -d|-D|-f`, `checkout -B`, `switch -C` and `worktree add -B` target rules, the output-file rules
(`bundle create FILE`, `format-patch -o`, `config --file`, `bugreport -o`, `--export-marks`), the shell-string `--check`
analyser (and the Claude PreToolUse hook it was for, W5).

## What is NOT covered (2026-10-25)

1. **Writers that never run git's hooks:** libgit2, gitoxide, `jj`, an IDE's embedded git. Nobody here uses them for agents;
   if one appears, it needs its own rule.
2. **A harness that turns repository hooks off** (Hermes does in its trees: design report line 133): the shim is then the only
   guard, and it no longer judges refs.
3. **Repositories without the hooks.** The shim installs them lazily and the operator's one-time `install` pass covers the
   primaries, but a repository no agent has touched through the shim, a plain `git clone` in /tmp by an agent that then runs
   only fast-path reads, or one with `core.hooksPath` set, has none.
4. **`env -i`, `nix-shell --pure`, unsetting the markers:** the hook sees no agent marker and treats the caller as the operator.
   Same boundary as the shim.
5. **`git branch -m|-c` destinations** only through the shim (above); **`--output` into a foreign tree** on the fast path.
6. Plumbing and maintenance stay the operator's call: `checkout-index`, `update-index`, `read-tree`, `fast-import`,
   `prune`/`repack`, `tag -f|-d` (claims name branches, not tags), `notes`, `replace`, `mv -f`, `add '*'`, and everything git
   itself spawns for the shim's rules (`bisect run`, `submodule foreach`, pagers, `!` aliases' children).
7. **Config-based hooks (git 2.54+, `hook.<event>.command`)** may let `acp-run` inject the guard for repositories nobody
   installed; whether they run alongside the hooks directory is unverified (`docs/queue.md`). The shim refuses `hook.*` keys
   regardless.

## Refusal, log and override

A refusal prints the owner, the claim id and a safe alternative, appends one JSON line to `<state>/guard.log` (option names
from an allowlist only; values never), and exits 77 (a hook refusal makes git exit 128 after the same text). The operator
allows and logs one call with `ACP_OPERATOR_APPROVED=git-guard` (the convention `bin/acp-dispatch` already uses), in the shim
and the hooks alike. Other environment: `ADE_REAL_GIT` (skip the PATH search), `ADE_PYTHON` (default `python3`),
`ADE_STATE_DIR`.

The shim and the hooks are plain bash 3.2 (macOS `/bin/bash`): no `case` inside `$( )`, no associative arrays; a test runs
`/bin/bash -n` on them.
