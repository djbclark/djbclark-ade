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

## Integration status (2026-10-25; re-based 2026-11-07)

The guard, the hooks and the claim library exist; claims carry an owner and expire (`ade_claims.py new --ttl`, default
72 h; `ade-git-guard claim ls`, slim-down E8). Nothing creates claims in a live session yet. The wiring still to build:
W2, a Paseo `worktree.create.after` hook (a thin plugin) that runs `ade_claims.py new --ttl` and `ade-git-guard install`
for each agent worktree (E8 F4; `cow-pasture`, the first planned home, was removed 2026-11-06); W3, the W2 hook (or `paseo run`'s
environment) exporting `ADE_CLAIM_ID` (the dispatch shim never does, and leaves in Wave 6); W4, putting `libexec/agent-bin` first on each agent's PATH (acp-run's planned step goes with
acp-run in Wave 6). The operator runs `ade-git-guard install <repo>` once over `~/src/*` (the dangerous case is agent B
in primary P moving Z's branch: the hook must be in P; the shim also installs it the first time an agent runs a
non-read command there). The operator's shell and IDEs never go through the shim.

**Hard refusal stays off** until the S4 six-case pilot below passes (queue item 6; staged enforcement of standing
order 9, adopted 2026-10-25). Cases and pass/fail criteria are listed below; `bin/ade-claim-pilot` records the live
metrics without enabling PATH refusal, `~/.local/bin/git`, or any new refuse path.

## Commands

| Command | What |
|---|---|
| `git ARGS...` (the shim) | Run the real git, or refuse: exit 77, the reason on stderr, one line in `guard.log`. |
| `ade-git-guard git-ARGS...` | The same, called by name. |
| `ade-git-guard install [DIR]` | Write the chain-preserving hook stubs into `$(git rev-parse --git-common-dir)/hooks` of DIR's repository (one install covers every linked worktree). Idempotent. An existing hook of the same name is renamed `NAME.pre-ade` and runs after ours. Exit 0 ok, 2 not a repository, 78 `core.hooksPath` is set (git would never run the stubs; unset it or call the stubs from the directory it names), 73 `NAME.pre-ade` is already in the way. |
| `ade-git-guard --real-git` | Print the git the guard would run. |
| `ade-git-guard claim ls [--state active\|released\|merged\|expired] [--json]` | List what the claim registry holds: id, state, branch, owner, path, `expires_at` (2026-11-06; until then the listing was only `ade_claims.py list`, PLAN C5). Exit 2 for any other `claim` verb. |
| `ade_claims.py new --id ID --path DIR --branch B --base-sha S [--ttl HOURS] [...]` | Create a claim and its pointer; it expires after `--ttl` hours (default 72, 0 = never); exit 3 id exists, 4 path held by another owner's active claim. |
| `ade_claims.py list [--state S] [--json]` | What `claim ls` runs. |
| `ade_claims.py guard -- GIT_ARGS...` | What the shim runs. |
| `ade_claims.py hook-ref STATE`, `hook-push REMOTE URL` | What the two hooks run (stdin is git's). |
| `ade-claim-pilot cases\|record\|status\|show\|clear\|gate` | S4 six-case metrics recorder (2026-11-09). Writes `$ADE_STATE_DIR/s4-pilot.json`; **never** enables hard refusal. `gate` exits 0 only when all six cases are recorded `pass` (still leaves refusal off). Exit 0 ok / gate ready, 1 gate not ready, 2 usage, 3 IO. |

Exit codes: 77 = refused (`EX_NOPERM`); any other code of a shimmed call is the real git's (a call a hook refused ends
with git's own 128 and `fatal: ... aborted by the reference-transaction hook`). Every `ade_claims.py` subcommand exits 0
ok, 2 usage, 3 id exists, 4 path owned by another owner's active claim, 77 refused; `install` also 73 and 78
(78 also when git does not say whether `core.hooksPath` is set; an empty `core.hooksPath` is "set").

## Claims: owner and expiry (trimmed 2026-11-06, slim-down E8, D9)

A claim names its owner (`owner.record`, `owner.session`, `allow`) and, since 2026-11-06, when it stops guarding
(`expires_at`, set by `new --ttl`, default 72 h). An active claim past its `expires_at` is **expired**: the shim and the hooks
treat its workspace as unclaimed, `claim ls` shows it as `expired`, and another owner may claim the path. Expiry is read, not
written, so an agent that died never leaves a workspace guarded for good; a record with no `expires_at` (all records before
2026-11-06) never expires, and one that does not parse keeps the protection on. The CLI verbs `show`, `find` and
`set-state` had no caller and were removed the same day (the library functions stay for the guard, the hooks and the tests);
a claim is ended by its owner's tooling with `ade_claims.set_state(id, "released")`, or simply expires.

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

**Fail open (2026-10-25, round 10).** A hook that fails aborts git for everyone, the operator included, so the installed stub
runs the checkout's hook as a CHILD (never `exec`) and passes on only its documented refusal code, **77**; every other
outcome (the hook exits 1, 3 or 126, dies by a signal, is missing, python is missing or crashes, the 10 s alarm, git not
answering the origin question: see below) exits 0 and lets git proceed, for agents and humans alike. (Before round 10 the stub `exec`'d
the hook, so a Bash-level crash aborted git; tests now cover that layer.) **Fast path:** a caller with no agent
marker exits before anything else runs; an agent's call whose stdin names no `HEAD`, `refs/stash` or `refs/heads/` line
(a fetch of remote-tracking refs and tags) exits after one `grep`, without Python. Measured 2026-10-25, git 2.56: a fetch
of 500 updated branches opens ~500 reference transactions (one per ref); the test shows Python starts zero times for it.
A hook never runs a ref-writing git (the transaction's locks are held); the one thing it asks git is `git --git-dir <common>
config --local --includes --get remote.origin.url` (no ref lock), so the URL that matches a claim is git's answer: a trailing
`# comment`, quotes and `[include]`d config are handled by git. **Which scopes the question reads (round 11, 2026-10-25):** the
repository's own config file and the files it includes, and nothing else. The caller's command-line config (`-c`,
`GIT_CONFIG_COUNT/KEY_n/VALUE_n`, `GIT_CONFIG_PARAMETERS`), the global and system files, `HOME`, `XDG_CONFIG_HOME`,
`GIT_CONFIG_*`, `GIT_DIR` and `GIT_COMMON_DIR` are removed from the question's environment as well as ignored by `--local`, so a
caller cannot change the URL the claim is matched against (before round 11, `git -c remote.origin.url=/x branch -f cb main` did).
Asked of the common dir (a linked worktree's own git dir has no `remote.*`). **An unanswered question (timeout, cannot start, a
repository config or include that fails for this question only, e.g. `includeIf "gitdir:<common dir>"` is true for the hook's
`--git-dir` and false for the caller's own git dir in a linked worktree) does not switch the claim rule off for an agent:** the
origin then reads as "" and matches a claim of ANY origin for that branch name, so the rule can refuse a same-named branch of an
unrelated repository, never miss the claimed one. A human never reaches this (the fast path exits before Python). **Not
guarded (same uid):** a caller that sets `ADE_REAL_GIT` to a program of its own (the question is then answered by that program)
or `ADE_PYTHON` to one that exits 0 defeats the hook the same way it defeats the stub's own interpreter lookup.

**`pack-refs`/`gc`.** `git pack-refs --all` reports every ref it packs as `0 <sha> <ref>` and every loose ref it prunes as
`<sha> 0 <ref>` without changing a value, so beside any claim it would be refused. The stub exports its parent pid
(`ADE_HOOK_GIT_PID`); when that process is an executable named `git` (its real path: `/proc/PID/exe` on Linux, `sysctl
KERN_PROCARGS2` on macOS) whose exact argv, parsed word by word, names `pack-refs` (which `gc` and `maintenance` spawn), the
hook lets it through; its `argv[0]` must also be non-empty and named `git` (round 11: macOS pads the executable path with NULs
and the parse used to read an EMPTY `argv[0]` as padding, shifting argv by one word; it now counts the NULs beyond the padding
(`-(len(path)+1) mod 8`, measured arm64 2026-10-25) as empty leading arguments, and an empty `argv[0]` exempts nothing; tested with
`subprocess.run(["", "-C", "pack-refs", "branch", "-f", "cb", "main"], executable=REAL_GIT)`). A forged `argv[0]` such as `"git pack-refs"` does not count (the parse skips `argv[0]`; tested with
`subprocess.run(["git pack-refs", "branch", "-f", "cb", "main"], executable=REAL_GIT)`). **Residual (same uid):** a program
named `git` that sets a `pack-refs` argv and then runs the hook, or one that sets `ADE_HOOK_GIT_PID` to another process's
`pack-refs`, is believed. If neither /proc nor sysctl answers, nothing is exempted (a maintenance run beside a claim is then
refused; the operator reruns it). A real `branch -D` of the same packed ref is still refused (tested).

**Chain.** The installed stub runs the ade checkout's hook by absolute path (one copy of the logic; a checkout cloned with its `.git` from a claimed one, such as the retired cow pastures still on the Mac, whose `.git/hooks`
keeps working), then, if present, `NAME.pre-ade`. A refusal stops before the old hook runs. Install is atomic (temp file +
`os.replace`) and the stubs are bash 3.2 (tested with `/bin/bash -n`).

**Lazy install.** The shim's slow path installs the stubs the first time it meets a repository without them, after it has
allowed the call and before the real git runs, so the very first `git branch -f cb` an agent runs in an unprepared repository
is already guarded. Never in a directory that is not a repository, never while `git config --get-all core.hooksPath` says it is set (an empty
value counts: git then looks nowhere) or does not answer, never fails the user's command.

## The shim (what a hook cannot see)

Evaluated in order; the module docstring has every form.

1. **Fail closed.** A leading option git does not define, or one with no value (`unknown-option`); a subcommand that is not a
   git builtin, not an alias and not in `KNOWN_SUBS` (`unknown-subcommand`: external `git-foo` programs are refused; the
   operator can allow one call with the override). **`git commit-own MSG` goes through git's external-command lookup:**
   git would run the program `git-commit-own`, which the guard cannot read, so the shim refuses it as `unknown-subcommand`
   (confirmed 2026-10-25) while `git-commit-own MSG <paths>` called directly works (it is not a git call; the hooks still guard
   the refs it writes). Same for `git lfs` (run `git-lfs`) and any `git-foo`. The refusal text says so. Config on the command line or in the environment (`-c`,
   `--config-env`, `GIT_CONFIG_COUNT/KEY_n` read in full, `GIT_CONFIG_PARAMETERS`) whose key, after normalisation, is
   `core.hookspath` or starts with `hook.`, `include.` or `includeif.`; a `git config` write of such a key or `--edit`;
   and **`core.hooksPath` set, to any value, an empty one included, in the command, global or system scope as git itself says**
   (`git config --null --show-scope --get-all core.hooksPath`, run through the real git with the call's own options and the
   caller's environment, 5 s timeout: `HOME`, `XDG_CONFIG_HOME`, `GIT_CONFIG_GLOBAL/SYSTEM`, `[include]`d files; exit 0 = set,
   1 = unset) (`hook-config`). A repository's own (local or worktree) `hooksPath` is not refused: the repository chose it
   (husky, pre-commit), the hooks do not run there, and `install` reports it (78). If git answers neither 0 nor 1 (timeout, a
   config file it cannot parse) the call is refused with that reason (`hook-config-unknown`): **the shim fails closed, the
   hooks fail open**. **acp-run's own config pairs (2026-10-30):** acp-run puts two `GIT_CONFIG_PARAMETERS` entries in every agent's
   environment, `hook.acp-run-identity.event=reference-transaction` and `hook.acp-run-identity.command=~/.cache/acp-run/git-identity-guard.sh`
   (a config hook that checks the git identity; a config hook only adds a hook, it cannot switch the hooks directory's off). The
   per-key rule exempts exactly those two pairs from environment configuration (PARAMETERS or legacy COUNT pairs; command value
   shell-decoded as exactly one argument and matched exactly to the expected guard path (or its realpath),
   with canonical shell quoting and no lexical path normalization), spending each environment occurrence once. Another value, a command-line copy via `-c` or
   `--config-env`, and every other `hook.*`,
   `include*` and `core.hooksPath` key stay refused. **`clone` and `init` copy a template directory (its `config` and `hooks` included) into the new repository
   (round 11, 2026-10-25; djbclark's ruling): the shim refuses every non-default template source** as `hook-config`: `--template`
   (any abbreviation, `=` or next word), `GIT_TEMPLATE_DIR` in the environment, `init.templateDir` set on the command line, in the
   environment or in any config scope but the repository's own (asked of git like `core.hooksPath`; unanswered is
   `hook-config-unknown`), and, for `clone`, a `-c`/`--config` whose key is a hook key (`core.hooksPath`, `hook.*`, `include*`)
   or `init.templateDir` (tested for `-c KEY=V`, `-cKEY=V`, a cluster `-qc KEY=V`, `--config KEY=V`, `--config=KEY=V`, `--conf=`).
   `[hook]` sections and `[include]` of files that set no `hooksPath` are no longer refused: measured
   2026-10-25, git 2.56, `hook.<name>.enabled=false` does not stop a hook in the hooks directory. `push --no-verify` (any `--no-v`
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
   Same boundary as the shim. (A `HOME`/`XDG_CONFIG_HOME` redirected to a config that sets `hooksPath` IS refused by the shim
   since round 10; run through the real git by absolute path it is not.)
5. **`git branch -m|-c` destinations** only through the shim (above); **`--output` into a foreign tree** on the fast path.
6. **Writes that never open a ref transaction (listed 2026-10-25, round 10):** editing `.git/packed-refs` or a loose ref file
   directly (no hook runs; the shim cannot see a file edit), `git replace` and `git notes` (they write `refs/replace/*` and
   `refs/notes/*`, which no claim names; `replace` changes what a commit LOOKS like without moving the branch; **left out on
   purpose**, a claim protects a branch's tip, not the view of it), and a repository's own `core.hooksPath` (above).
7. Plumbing and maintenance stay the operator's call: `checkout-index`, `update-index`, `read-tree`, `fast-import`,
   `prune`/`repack`, `tag -f|-d` (claims name branches, not tags), `notes`, `replace`, `mv -f`, `add '*'`, and everything git
   itself spawns for the shim's rules (`bisect run`, `submodule foreach`, pagers, `!` aliases' children).
8. **Config-based hooks (git 2.54+, `hook.<event>.command`)** may let the W2 Paseo `worktree.create.after` hook inject the guard for
   repositories nobody installed; whether they run alongside the hooks directory is unverified (carried here). The shim refuses `hook.*` keys
   set on the command line or in the environment regardless; in a config FILE they are not judged (measured inert for the
   hooks directory, 2026-10-25).
9. **A same-uid program impersonating the `pack-refs` parent** (see above).
10. **A template directory or `core.hooksPath` that arrives by a route the shim does not see (round 11, 2026-10-25):** a human
    sets `init.templateDir` in the repository's own config (or points a template at a repository the agent did not create);
    an agent edits `.git/config` of its own repository by hand, or runs the real git by absolute path. The shim refuses the
    agent's own `clone`/`init` template sources and `clone -c core.hooksPath=...` (above), but a repository whose LOCAL
    `core.hooksPath` is set and not the ade stubs is still deliberately allowed, so `git push -f origin main:cb` there
    passes both hooks. Reproduced before round 11 (d9b0583, 3fb69ba): shim `clone -q --config core.hooksPath=/dev/null <up> c2`,
    then `push -f origin main:cb` in c2 moved the upstream branch. The durable rule, left to the operator: "an agent's call
    lands in a repository whose local hooksPath is set and not the ade stubs: refuse `push` and ref-writing subcommands".
11. **Template sources the shim only reads for `clone`, `init`:** `submodule add|update` and `fetch|pull --recurse-submodules` also
    clone (and copy `GIT_TEMPLATE_DIR` / `init.templateDir` into) new repositories; not refused (round 11, open question).
12. **The claim's repository identity is the repository's own `remote.origin.url`:** an agent that runs `git remote set-url origin
    /x` (allowed; reproduced 2026-10-25 through the shim) and then `git branch -f cb main` is no longer matched to the claim of
    `cb` in the hook, whatever the origin question reads. Matching the claim by something an agent cannot rewrite (its Paseo worktree's
    git dir or the common dir recorded in the claim) is a design call for the operator.
13. **Same-uid forgery of the hook's own inputs:** `ADE_REAL_GIT`, `ADE_PYTHON`, `ADE_HOOK_GIT_PID` (see the fail-open and
    `pack-refs` paragraphs).
14. **Output files written into an unclaimed checkout (replayed 2026-10-25 at ac2fc56 for Codex threads on f6fd689 and
    fdaad51):** the output-file rules went with O2 because no hook sees a worktree file write. So an agent's `git stash show
    -p --output=f` (also `--output=f` without `-p`, with `stash@{0}`), `git format-patch -1 -o .` (also `--output-directory=.`,
    `-o ./`, and a plain `format-patch -1`, which writes into the current directory) succeed through the shim and replace a
    file of that name in an unclaimed checkout that holds a peer's uncommitted work (observed: rc 0, the file now holds the
    stash diff or the patch). In a CLAIMED foreign workspace the same calls are refused (`[foreign-claim]`, rc 77). Accepted
    residual: the guard protects branches, history and tracked work, not arbitrary files an agent redirects git's output to.
    The durable rule, left to the operator (`docs/queue.md`): refuse `--output*`, `-o` and `--output-directory` on
    `stash show` and `format-patch` when the target lies inside a tree that is not the caller's claimed workspace.

## Refusal, log and override

A refusal prints the owner, the claim id and a safe alternative, appends one JSON line to `<state>/guard.log` (option names
from an allowlist only; values never), and exits 77 (a hook refusal makes git exit 128 after the same text). The operator
allows and logs one call with `ACP_OPERATOR_APPROVED=git-guard` (the convention `bin/acp-dispatch` already uses), in the shim
and the hooks alike. Other environment: `ADE_REAL_GIT` (skip the PATH search), `ADE_PYTHON` (default `python3`),
`ADE_STATE_DIR`.

The shim and the hooks are plain bash 3.2 (macOS `/bin/bash`): no `case` inside `$( )`, no associative arrays; a test runs
`/bin/bash -n` on them. Since 2026-10-29 macOS CI runs only on a manual `Tests` dispatch with `macos: true`, and Ubuntu's
`/bin/bash` is bash 5, so that test passes vacuously against bash 3.2 syntax there: a bash 3.2 regression is caught only by a
`macos: true` dispatch or a local run on the Mac.

On 2026-10-30 acp-run began shell-quoting the identity hook command and checking inherited hook pairs
before treating a nested launch as guarded. A marker whose PARAMETERS transport was stripped is repaired.

## S4 six-case enforcement pilot (scaffold 2026-11-09; recorder 2026-11-09; pilot before hard refuse)

Standing order 9's staged enforcement (adopted 2026-10-25; queue item 6) ends with **S4**: run six representative
workflows under claim-aware workspaces **before any hard refusal** (before agents are forced through the PATH shim /
`~/.local/bin/git`, and before `~/ops` leaves its transitional plain-master practice). S3 (changelog fragments) is done
(PR 190). S1/S2 and the W2–W4 claim wiring are separate open work; this section does not implement them and does **not**
flip refusal on.

**Recorder:** [`bin/ade-claim-pilot`](../bin/ade-claim-pilot) (2026-11-09) is the runnable metrics harness. It lists the
six cases, records per-case setup delay / disk delta / path-binding failures / false refusals into
`$ADE_STATE_DIR/s4-pilot.json`, and exposes `status` / `gate`. It never installs the PATH shim, never writes
`~/.local/bin/git`, and never flips a refuse path — even when `gate` exits 0. Tests: `tests/test_ade_claim_pilot.py`.

**Gate (explicit):** hard refusal stays off until every case below is run once, recorded with the metrics
(`ade-claim-pilot record …` / `ade-claim-pilot gate`), and the operator accepts the result. A failing case or an unrun
case blocks enabling hard refusal; it does not change today's rule-only posture. Optional narrowing of the guard
(E8 F3) remains an operator security decision outside this pilot.

### Cases and pass/fail

Measure each case for: setup delay, disk use, path-binding failures, and false refusals (a refuse that blocks a
legitimate owner or named exception). Pass = the workflow completes under a claimed task workspace (or a named
exception) with no false refusal and no path-binding failure; record the delay and disk figures even on pass
(`ade-claim-pilot record CASE --result pass --setup-delay-s … --disk-delta-bytes … --path-binding-failures 0
--false-refusals 0`). Fail = a false refusal, a path-binding failure that stops the workflow, or an unclaimed
shared-checkout write that the pilot was meant to keep out of (`--result fail` plus `--false-refusal-reason` as needed).

| # | Case | What to run | Pass | Fail |
|---|---|---|---|---|
| 1 | ADE code task | One code change in a linked worktree of `djbclark-ade` with an active claim; stage, commit, push the branch. | Owner git through the claim succeeds; foreign write to the same path would be refused if the shim were on PATH (observe only; do not enable). | Owner refused; or the work lands in the shared primary checkout. |
| 2 | One-line queue task | One-line edit to `docs/queue.md` (or a stand-in docs line) in its own claimed worktree, PR-only to master. | Edit and PR from the claimed workspace; no collision with another writer's uncommitted queue edit. | Edit made in a shared checkout; or a false refusal of the owner. |
| 3 | Ops promotion | Designated promoter: clean `git merge --ff-only` of a primary / `~/ops` master to a published revision (order 9 exception b); no commit made there. | Fast-forward succeeds under the named exception; no claim required on the integration checkout for that single step. | Promoter blocked as if it were an agent writer; or a non-promoter write is treated as allowed. |
| 4 | Submodule task | One task that updates or builds through a submodule / nested checkout from a claimed parent worktree. | Paths resolve inside the claim; submodule git does not write a foreign claimed branch. | Path-binding failure; or a submodule ref write escapes the claim unnoticed when hooks are installed. |
| 5 | Fixed-cwd agent | An agent whose tool cwd is fixed (cannot `cd` to a worktree) but whose git writes must still target a claimed workspace (`-C` / explicit worktree path). | Writes land only in the claimed path; reads of foreign trees stay on the read allowlist. | Agent writes the shared primary because cwd was fixed; or a legitimate `-C` owner write is refused. |
| 6 | Long-lived server | A long-running process (dev server, watcher) started from a claimed workspace and left up across other agents' turns. | Process keeps its claim's cwd/paths; no second writer mutates the same workspace until it exits (order 9 one-writer rule). | Second writer edits the same workspace while the server is still a writer; or stopping the server leaves a permanent claim (TTL/expiry should free it). |

### Test-plan scaffold (optional; not enabled)

Checklist for a later live run (copy into the pilot PR or a run log; do not flip refusal while working the list). Use
`ade-claim-pilot` to write the metrics; leave hard refusal off throughout:

1. [ ] Preconditions: hooks installed on the repos under test (`ade-git-guard install`); claims created with `ade_claims.py new --ttl` (manual or W2 plugin once available); **PATH shim not forced** for the fleet.
2. [ ] Run cases 1–6 once each; for each, `ade-claim-pilot record CASE --result pass|fail --setup-delay-s … --disk-delta-bytes … --path-binding-failures N --false-refusals N [--false-refusal-reason …]`.
3. [ ] Confirm exit 77 only where a foreign/destructive rule should fire in observe mode; owner and human shells stay exit 0.
4. [ ] Confirm expired claims free the path (`claim ls` shows `expired`; another owner may claim).
5. [ ] `ade-claim-pilot gate` exits 0 and the operator signs off that S4 passed → only then schedule hard-refusal enablement (separate change; not this recorder).
6. [ ] Until that sign-off: keep teaching agents the rule (order 9) without PATH hard refuse.
