# ade-git-guard — destructive git refused in a workspace another agent owns

**Built 2026-10-24 (isolation slice W1).** A seatbelt, not a sandbox: it stops an agent's accidental or careless git, not
one that works at it. Code: [`bin/ade-git-guard`](../bin/ade-git-guard) (bash front door, installed as the PATH shim
`libexec/agent-bin/git`) and [`bin/ade_claims.py`](../bin/ade_claims.py) (claim library and rules). The module docstring
of `ade_claims.py` is the rule-by-rule reference; this page is the operator's summary. Tests:
`tests/test_ade_git_guard.py`.

## Integration status (2026-10-24)

Only the guard and the claim library exist. Nothing calls them in a live session yet: W3 (`acp-dispatch` exports
`ADE_CLAIM_ID`), W4 (`acp-run` puts `libexec/agent-bin` first on the PATH of every agent it launches) and W5 (the
Claude hook running `--check`) are not installed. The operator's shell, Orca and IDEs never go through the shim.

## Commands

| Command | What |
|---|---|
| `git ARGS...` (the shim) | Run the real git, or refuse: exit 77, the reason on stderr, one line in `guard.log`. |
| `ade-git-guard git-ARGS...` | The same, called by name. |
| `ade-git-guard --check CMD [--cwd DIR]` | Judge every `git` call inside a shell command string (the Claude hook). Exit 0 allow, 77 refuse (also a call it cannot classify), 2 usage. |
| `ade-git-guard --real-git` | Print the git the guard would run. |
| `ade_claims.py new --id ID --path DIR --branch B --base-sha S [...]` | Create a claim and its pointer; exit 3 id exists, 4 path held by another owner's active claim. |
| `ade_claims.py show ID [--field F]`, `find [DIR]`, `list [--state S] [--json]`, `set-state ID active\|released\|merged` | Read and change claims; exit 1 when not found. |
| `ade_claims.py guard -- GIT_ARGS...`, `check CMD [--cwd DIR]` | What the shim and `--check` run. |

Exit codes: 77 = refused (`EX_NOPERM`); any other code of a shimmed call is the real git's; every `ade_claims.py`
subcommand exits 0 ok, 1 not found, 2 usage, 3 id exists, 4 path owned by another owner's active claim, 77 refused.

## Who is guarded

Only agents: `ACP_RUN_AGENT=1` or `ADE_CLAIM_ID` set. A human shell, git's own hooks (`GIT_INDEX_FILE`) and pre-commit
(`PRE_COMMIT`) are never refused. A guard crash, a missing `python3` or an unexpected exit **fails open** (a warning on
stderr, the real git runs): a guard bug must not stop all git.

## Claim lifecycle

One claim per workspace (a cow pasture or a linked worktree): who owns it, its branch and base.

1. **Created** by `ade_claims.py new`: `~/.local/state/ade/claims/<id>.json` (`ADE_STATE_DIR` moves `~/.local/state/ade`),
   written atomically, plus the pointer `<git-dir>/ade-claim` holding the id (never tracked; per worktree).
2. **Active** while `state` is `active`; a workspace with an active claim that is not the caller's is read-only to the
   caller. The caller is "mine" when its `ADE_CLAIM_ID` (or harness session id) is the claim id, `owner.record`,
   `owner.session` or is in `allow`; `lead` is not implied.
3. **Released / merged** via `set-state`: no longer guards. A re-claim of a path by the same owner releases the old
   record; a path held by another owner's active claim is refused (exit 4).

A pointer is trusted only when the claim's `path` is this workspace, so a pasture copied from a claimed checkout does not
inherit the claim.

## What is refused (summary; the docstring has every form)

1. In a workspace another agent's active claim covers: everything that is not read-only. A command that looks read-only
   but writes is not: `--output[=]` of `diff`/`log`/`show`/`stash show|list`/`whatchanged`/`range-diff`/`shortlog`,
   `format-patch -o`, `archive -o`, `grep -O`, `fetch` that can update a local branch, `symbolic-ref -d`.
2. In a checkout with no claim: `stash`, `reset --hard|--merge|--keep`, `checkout -f|-p|<path>`, `restore` of the
   working tree, `switch -f`, `clean`, `rm -f`, `commit -a`, `add -A|-u|.`, autostash, `rebase -x`, `!` aliases.
3. In a linked worktree, even its owner's: `stash`, `rebase -x`, `!` aliases (refs/stash is shared).
4. Anywhere: `push` to another claim's branch (destinations from git's own `push --dry-run --porcelain`).
5. Anywhere, by target: `worktree remove|move|prune` of a claimed worktree; `branch -d|-D|-m|-M|-f|-c|-C` (a copy is
   judged by its destination), `checkout -B`, `switch -C|--force-create`, `worktree add -B`, `update-ref` of another
   claim's branch; `fetch`, `pull` and `remote update` whose refspecs write a local branch (command line,
   `remote.<name>.fetch` as git reads it under the call's own `-C`/`-c`/environment, or `--stdin`, which cannot be
   inspected: refused while another agent holds a claim in the repository); a file written (`--output`, `bundle create
   FILE`, `fast-export --export-marks`, `config --file`) into another claim's tree or over a dirty file of a shared
   checkout.

Not covered (plumbing and object-store maintenance stay the operator's call): `checkout-index`, `update-index`,
`read-tree`, `fast-import`, `gc`/`prune`/`repack`, `tag -f|-d` (claims name branches, not tags), `notes`, `replace`,
`mv -f`, `add '*'`, and everything git itself spawns (hooks, `bisect run`, `submodule foreach`, pagers, `!` aliases'
children, `fetch --upload-pack`).

## Refusal, log and override

A refusal prints the owner, the claim id and a safe alternative, appends one JSON line to `<state>/guard.log` (option
names from an allowlist only; values never), and exits 77. The operator allows and logs one call with
`ACP_OPERATOR_APPROVED=git-guard` (the convention `bin/acp-dispatch` already uses). Other environment: `ADE_REAL_GIT`
(skip the PATH search), `ADE_PYTHON` (default `python3`).

The shim is plain bash 3.2 (macOS `/bin/bash`): no `case` inside `$( )`, no associative arrays; a test runs
`/bin/bash -n` on it.
