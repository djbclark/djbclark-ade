---
schema_version: 1
handoff_id: c615
parent_handoff_ids: []
lineage: none
chain: [standalone-ba7b]
repo: djbclark-ade
workspace: djbclark-ade-bridge-guard-wt
branch: fix/opencode-bridge-econnrefused-guard
head_sha: c8403793f18a63662f07784e5e2dff8b4f7644dc
created_at: 2026-11-04T07:00:00-05:00
writer: omp
---
# Handoff — Paseo OpenCode bridge stale-binding fix, PR 281 awaiting gates

## The Goal
djbclark reported the OpenCode model drop-down in Paseo blank ("our opencode proxy that lets us switch accounts
without restarting paseo tabs is down"). Restore it, make the fix recoverable, upstream it. Current goal: land
[PR 281](https://github.com/djbclark/djbclark-ade/pull/281) (adversary verdict, local Codex review, squash-merge,
remove the worktree).

## Where We Are
- The dropdown is restored: `paseo provider models opencode` lists 177 models and no `paseo.bridge/bind` 500 has been
  logged since 2026-11-04T11:36:27Z. Not looked at in the Paseo UI itself.
- The "proxy" is `oc-go-key` (writes the shared OpenCode DB, reloads servers). It and the OpenCode service
  (`opencode serve --service`, pid 21228 at the time, port in `~/.local/state/opencode/service.json`) were never down.
- Root cause: Paseo's `paseo-managed-bridge` plugin keeps session bindings in a module-level Map (`state.mjs`) that
  survives plugin reloads; its bind handler ignores a refused connection to the previous bridge only for
  `error.cause.code === "ECONNREFUSED"` or `error.code === "ConnectionRefused"`. OpenCode 2.2.5 embeds Bun 1.4.4
  (`strings` on the binary), whose fetch error has `error.code === "ECONNREFUSED"` and no cause, so a stale binding is
  never dropped and every bind returns HTTP 500; the daemon then logs `OpenCodeLocationReadyTimeoutError` and the model
  list stays empty.
- Fix applied by hand (djbclark approved it through a question card): one clause added at line ~6738 of
  `~/.config/opencode/plugins/paseo-managed-bridge/server.js`. OpenCode's file watcher reloaded it at 11:36:31Z with no
  service restart. Paseo rewrote the file from its runtime copy about a minute later (mtime 06:37 local), so the patch is
  transient; that was enough, because Paseo retries the bind every ~4 s and the patched handler cleared the stale binding.
- Upstream: [getpaseo/paseo#8780](https://github.com/getpaseo/paseo/issues/8780) filed, with a follow-up comment about the
  overwrite. Dupe search in getpaseo/paseo: "ECONNREFUSED bridge opencode", "opencode bind 500 stale": nothing.
- Durable: memory note `reference_paseo_opencode_bridge_stale_binding_econnrefused.md` plus its index line in
  `MEMORY-reference.md`, committed and pushed to site-private master (03b691b and a follow-up).
- PR 281 (branch `fix/opencode-bridge-econnrefused-guard`, worktree `~/src/djbclark-ade-bridge-guard-wt`, head c840379):
  `bin/opencode-plugin-guard` gains `handle_paseo_bridge`; run without `--check` it applies the one-line exact-string patch
  atomically on the realpath, keeping the mode; `--check` only reports and exits 0; an unknown shape or an absent file is
  left alone. Docs section in `docs/opencode-plugin-v2.md`, fragment `changelog.d/fix-opencode-bridge-econnrefused-guard.md`
  (ends `(#281)`, `bin/changelog-fold --check` rc 0), 4 new tests in `tests/test_rtk_opencode_plugin.py`
  (`bin/pytest -q tests/test_rtk_opencode_plugin.py`: 17 passed; run directly, not through `bg`).
- This handoff lives on the local branch `handoff/bridge-guard-ba7b` of the same worktree, NOT on the PR branch; never push it
  into PR 281.

## What We Tried
- First report said the patch was in place; it was not. `guard --check` showed it missing because Paseo had reverted it. The
  recovery still held, so the claim was retracted in chat, in the memory note and on the upstream issue.
- An earlier `--check` design returned rc 1 whenever the patch was absent; changed to rc 0 with an informational line,
  because Paseo always reverts the patch and a healthy system would report a failure.
- Tests first ran through the bare shell instead of `bg` (rule 34 says builds and tests go through `bg`); the run takes 4 s.

## Key Decisions
Chose an on-demand guard step over a standing guard because Paseo reverts the file within a minute and the patch only has
to run until one bind clears the stale binding. Rejected restarting the OpenCode service: it kills every running OpenCode
session and `oc-go-key reload` does not clear bindings. Rejected waiting for Paseo to fix it.

## Decisions
- [decision] on-demand `opencode-plugin-guard` bridge patch, `--check` informational; rejected: standing guard that exits 1 when unpatched; because Paseo rewrites the file within a minute, so a standing check is always red; in [PR 281](https://github.com/djbclark/djbclark-ade/pull/281).
- [ruling] "Patch the bridge plugin (hot reload)" (djbclark, 2026-11-04)
- [ruling] "Extend opencode-plugin-guard" (djbclark, 2026-11-04)
- [ruling] "Handoff and continue" (djbclark, 2026-11-04)

## Relations
- decided_in [[HANDOFF_standalone-ba7b_paseo-opencode-bridge-guard_2026-11-04_c615]]

## Evidence & Data
- OpenCode log `~/.local/share/opencode/log/opencode.log`: `rpc handler failed rpc=paseo.bridge method=bind defect="TypeError: ECONNREFUSED"` every ~4 s until 11:36:27Z; first seen 2026-11-03T12:01Z.
- Paseo daemon log `~/.paseo/20261104-0543-01-daemon.log`: 48 `Cannot connect the Paseo tool bridge to OpenCode ... bind failed (HTTP 500)` lines.
- Bun reproduction: fetch to a closed port gives `TypeError`, `code === "ECONNREFUSED"`, `cause === undefined`.
- Plugin source: runtime copy `~/.paseo/runtime/opencode/paseo-v2-db40ef2c.../server.js`, identical to the live copy; bind handler at lines 6723-6752.

## Operator Feedback
djbclark answered all three question cards without comment. The standing rule he set earlier applies: upstream every local change (order 8).

## Where We're Going
1. Run the adversary review of PR 281's head and put the marker in the PR body:
   `<!-- adversary-verdict:v1 {"verdict":"APPROVE"|"BLOCK","head":"<40-hex>"} -->` (head = `git -C ~/src/djbclark-ade-bridge-guard-wt rev-parse fix/opencode-bridge-econnrefused-guard`; the current head is c8403793f18a63662f07784e5e2dff8b4f7644dc).
2. Run `~/src/djbclark-ade/bin/local-review 281` (exit 0 clean) and `~/src/djbclark-ade/bin/pr-wait 281 --local-codex`; fix any finding in the worktree, then rerun.
3. Merge: `gh pr merge 281 --repo djbclark/djbclark-ade --squash --match-head-commit <head>`, check `gh pr view 281 --json state` reads MERGED, then `git worktree remove ~/src/djbclark-ade-bridge-guard-wt` and delete the branch `fix/opencode-bridge-econnrefused-guard` (and the local `handoff/bridge-guard-ba7b`, after copying this file if wanted).
4. Ask djbclark to look at the Paseo OpenCode dropdown (not checked in the UI).
5. Watch #8780; when Paseo ships the fix, remove `handle_paseo_bridge`, its tests, doc section and this note's guard pointer.
6. Not mine: `~/src/djbclark-ade` has an uncommitted ` M .gitignore`; leave it to its owner.

## Detached jobs
none

## Quick Start
```bash
cd ~/src/djbclark-ade-bridge-guard-wt && git status -sb && git log -3 --oneline
gh pr view 281 --repo djbclark/djbclark-ade --json state,headRefOid,statusCheckRollup
paseo provider models opencode | wc -l      # 177 when healthy
bash bin/opencode-plugin-guard --check      # read-only
```
If the dropdown is blank again: `bash ~/src/djbclark-ade-bridge-guard-wt/bin/opencode-plugin-guard` (or the merged copy), wait ~15 s, recheck.
