---
name: cow-workspaces
description: >-
  Give an agent its own workspace with `cow` (APFS copy-on-write pastures) via
  the `cow-pasture` wrapper, instead of a plain clone or `git worktree`. Use
  when starting parallel or isolated work on a checkout under ~/src or ~/.hermes,
  dispatching a Hermes or Paseo worker into its own directory, or asked about
  cow, pastures, `cow migrate`. Orca (and `~/orca/projects`) is retired
  (2026-10-31); no Orca recipe is kept in this skill.
---

# cow workspaces

`cow` (github.com/joeinnes/cow, `/opt/homebrew/bin/cow`) clones a whole repo
directory with APFS `clonefile(2)`. A pasture is an **independent repo with
its own `.git`** that carries the source's untracked content (`node_modules`,
build output), so agents start without reinstalling. That content must be a
real clone, not a link back into the source: bare `cow create` links it (see
item 1 below), `cow-pasture create` does not. Measured: 36.5 GB
logical in 4.4 GB on disk across 10 pastures. The win is space and dependency
reuse, not speed.

## The rule

For a new isolated workspace on a **primary checkout**, run:

```bash
~/src/djbclark-ade/bin/cow-pasture create <name> --source <repo> [--branch <b>]
```

It prints the pasture path. A pasture and a linked `git worktree add`
checkout are both valid task workspaces (AGENTS.md standing order 9,
2026-10-25): prefer a pasture when the task needs the source's untracked
dependencies (`node_modules`, build caches) and a linked worktree when
reusing them adds nothing; a plain clone is for submodule-heavy repos or when
cow refuses (see limits). Default pasture root is
`~/.cow/pastures/<source-name>/<name>`.

Never create pastures from `~/ops/*` — those are deployment checkouts that
running services read directly; the wrapper refuses (exit 3). For now work
there in place with plain git (operator decision 2026-08-23); AGENTS.md
standing order 9 (2026-10-25) makes that transitional: once the queue's
ops-promotion pilot passes, ops development moves to a linked worktree
outside `~/ops` and `~/ops` master only fast-forwards.

## Why the wrapper, not bare `cow create`

Verified 2026-09-20 (item 1: 2026-11-01, cow 0.1.10):

1. **cow links dependency dirs into the source.** By default `cow create`
   replaces large directories (each package under `node_modules`, whole scope
   dirs such as `node_modules/@types`, `.venv/bin`) with **absolute symlinks
   into the source checkout**, and `--print-path` hides its "writes affect
   source" warning. Builds in such a pasture read the source's packages, and
   a package install there writes into the source: on 2026-11-01 an
   `npm install` in a paseo pasture emptied ~392 package directories of
   `~/src/paseo/node_modules`. `cow-pasture create` now passes `--no-symlink`,
   runs `cow materialise <source>/<name>`, and exits 1 without printing a
   path if any symlink in the pasture still resolves into the source or any
   other checkout `cow list --json` records.
   Check an older pasture with `cow-pasture check <pasture-path>` (exit 1
   lists the links; on 2026-11-01 `hermes-agent/forgejo-ci-2026-10` had 795)
   and fix it with `cow materialise <source>/<name>`, the `name` that
   `cow list --json` shows for its path. A pasture made from such a pasture
   inherits links into the grandparent source that cow's state does not
   record, so `materialise` leaves them (`forgejo-ci-2026-10/gh-ci-2026-10`):
   remove it and create again from the primary checkout. The check sees
   symlinks only: a copied Python venv still names the source's venv by
   absolute path in `bin/activate` and every script's `#!` line, so a
   `pip`/`uv pip install` through it lands in the source; recreate `.venv`
   in the pasture (`uv sync`, with `VIRTUAL_ENV` unset) before installing.
2. **cow copies gitignored secrets.** `.env`, `*.pem`, keys — everything
   untracked comes along, `uchg` flag included. `cow-pasture` deletes
   gitignored secret-like files after the clone (patterns in the script),
   warns about *tracked* ones, keeps dependency dirs. `--keep-secrets` opts
   out. Credentials a task really needs go through `sudo-secretspec`.
3. **`uchg` strands pastures.** Copied `.env` files are often user-immutable,
   so `cow remove` fails. `cow-pasture remove <name>` (short name or
   `<source>/<name>`) runs `chflags -R nouchg` first.
4. **Orca registration is retired.** `--orca` (`orca repo add`) and the Orca
   unregistration on `remove` were deleted from `cow-pasture` on 2026-10-31
   (Orca is retired from djbclark-ade); `create ... --orca` is now a usage
   error. An older pasture may still sit in Orca's own list; that is left
   untouched.
5. **`cow-pasture` is not on `PATH`**: call `~/src/djbclark-ade/bin/cow-pasture`.
   Plain `cow remove <short-name>` prints "not found — skipping" and **exits 0**
   having removed nothing; it needs `<source>/<name>` (2026-10-18). Check `ls`
   afterwards.

## Folder trust

**Claude workers and folder trust.** Claude Code shows a folder-trust "Quick
safety check" in any directory it has never seen, so a headless Claude start
in a fresh pasture stalls there (reproduced 2026-09-20 through Orca's
`worker-start`, since retired from djbclark-ade). There is no flag
or env var for it (the binary's only trust env vars are for Anthropic's cloud
runner); the mechanism is `~/.claude.json` → `projects[<path>].
hasTrustDialogAccepted = true`. `cow-pasture create` now pre-seeds that
(atomic write, backup at `~/.claude.json.bak.cow-pasture`; `--no-trust` to
skip), and a Claude agent then starts normally. Tradeoff:
the pasture's own `.claude/` settings, hooks and MCP config run without the
prompt — acceptable for a clone of your own repo with secrets scrubbed, not
for untrusted code.

**graft.** Agent sessions write `graft/.cache/session/*.json` into the
workspace. `create` adds `graft/.cache/` to the pasture's `.git/info/exclude`
so the pasture is not "dirty", and `remove` deletes that untracked cache first
so no `--force` is needed. Tracked `graft/` content is never touched.

## Limits

- cow refuses linked worktrees ("is a git worktree, not a primary
  repository") and bare stores ("No VCS found"). `~/src/core-*`,
  `libntech-*`, `ss-*`, `ralph-tui-*-plugin` are linked worktrees; use their
  primaries. `~/src/ops-worktrees/` sits on bare stores — leave it alone.
- `cow migrate` fails when the source has an uncommitted `.gitignore` edit;
  keep tracked `.gitignore` clean, put local ignores in `.git/info/exclude`.
- `cow migrate` skips dirty worktrees; `--force` needs the operator.

## Reclaiming space

`cow gc --merged --dry-run` (then without `--dry-run`, with the operator's
go) removes pastures whose branch merged. `cow stats` before and after.

## Turning it off

Delete this skill directory; nothing else runs automatically. The MCP server
(`mcp__cow__*`, user-scope stdio) and `cowcd` shell function are independent.
