---
schema_version: 1
handoff_id: 5a25
parent_handoff_ids: []
lineage: none
chain: [standalone-relay-refresh-01a1735a]
repo: djbclark-ade
workspace: /Users/djbclark/src/one-offs
branch: fix/self-slash-codex
head_sha: c93ac5d2b5f7ff7848a0266fe21b333c69953306
created_at: 2026-10-25T10:29:47-04:00
writer: codex
---

# Handoff — relay CI, Herdr refresh and hook diagnosis

## The Goal

Execute the operator's A–D plan: preserve the earlier relay repair, close its
main CI verification, refresh Herdr without interrupting other sessions, move
local guidance into canonical ADE, diagnose hook failures, and continue through
exactly one explicitly targeted baton in the same session when supported.

## Where We Are

The main relay commit is `e6a8614cb8e2e65d6b43abc7febb732d9e1f55f9`.
Its exact main [Tests run](https://github.com/djbclark/djbclark-ade/actions/runs/40198067287)
completed successfully on both Linux and macOS. The notifier was retargeted to
that run, completed, and sent its one completion notification. No workflows
were cancelled or rerun.
Linux: 3,700 passed, 13 skipped; macOS: 3,703 passed, 10 skipped. Both jobs
reported 1,320 passing subtests and zero failures.

The first same-TUI lifecycle queue exposed an ADE harness failure before it
sent anything: its waiter PID disappeared, and prompt detection explicitly
did not support Codex. This session remained on the same thread. The root
repair is committed and pushed on `fix/self-slash-codex` at `c93ac5d`:
`self-slash` now starts its waiter in a separate process session, recognizes
Codex's shaded composer (including multiline drafts), waits for authoritative
idle/done state, and uses atomic `agent prompt`. Ambiguous submission failures
stop without retry. No hook, permission or relay delivery guard was bypassed.

The repair is not promoted to master yet. Its single full Linux/macOS
[CI run](https://github.com/djbclark/djbclark-ade/actions/runs/40204830764)
is pending; it covers exact head `c93ac5d2b5f7ff7848a0266fe21b333c69953306`.
Follow-up documentation changes do not alter that tested code.

Herdr's installed binary was atomically upgraded from
`0.9.1-preview.2026-09-21-0ff0f27e2226` to the newest published preview,
`0.9.4-preview.2026-10-14-fbd2ae23927f`. GitHub's asset SHA-256 was verified:
`e6543d05b318b9ecad8173a87bc2b50e20585ad99327f2ab3482879cdd3d9090`.
Current upstream master resolved to `5608de0608918aba2f9d501e7793b984a0ca9cfa`;
the named skill's last modifying commit was
`1cbd794559fb139f95f1bdb4b2a8998082017d0e`. These are observations, not pins.

The skill now contains only `skills/herdr/SKILL.md` (15,171 bytes). Source
metadata names `herdrdev/herdr` and the named skill path. The installer was
blocked by Trail's command classifier; the operator explicitly chose the
documented manual fallback. The complete old installation and its local edit
were preserved before replacement. The ADE-specific precondition rule now
lives in `skills/session-finder/SKILL.md`, including the exception for detached
relay workers, which deliberately scrub caller context.

The installed Codex TUI is `0.164.0`, the current stable release. The operator
authorized an update if old, including a beta when justified, while preserving
all running TUI processes. `0.165.0-alpha.1` was inspected; its changes did not
establish a fix for the reported timeouts, so stable was retained. A running
older TUI still uses `0.163.0`; the separate ACP dependency reports `0.160.1`.
No Codex process was restarted, signalled, or upgraded in place.

Codex's `shell_environment_policy.inherit = "core"` strips Herdr context from
tool subprocesses. The initial shell check therefore returned 1 even though
this TUI is inside Herdr. This session's own Codex and owning shell process
environments agreed on `w2Q:p3`, tab `w2Q:t3`, workspace `w2Q`; process ancestry
proved both belonged to Herdr. Passing only that verified context explicitly
made `agent get` confirm this exact session ID, with cwd still `one-offs`.
Never recover identity from the focused pane or another process.

`herdr server live-handoff` succeeded. The running server now reports
`0.9.4-preview.2026-10-14-fbd2ae23927f`, endpoint compatibility, no restart needed
and no stale server binary. Every pre-existing Codex process retained its PID
and start time. No Codex TUI was restarted. Codex's installed managed hook
remains v8, whereas the preview bundles v10. Their shell assets differ only in
the version comment; the executable hook body is identical. The installer
migration defect below must be addressed at its owner rather than by editing
generated config.
Other installed integration version gaps are recorded privately.

## What We Tried

1. The prior branch [run](https://github.com/djbclark/djbclark-ade/actions/runs/40197527530)
   failed on exactly 15 baseline fixtures on each platform: three ACP reservation
   fixtures and twelve launcher fixtures. Linux: 3,685 passed, 13 skipped;
   macOS: 3,688 passed, 10 skipped; each had 1,320 passing subtests. Main includes
   PR 65's fixture repair and passed both platforms. These are not relay regressions.
2. The upstream named-skill installation command was rejected by Trail's
   PreToolUse classifier as though it were a Trail skill-save command. Even a
   read-only query containing that phrase was rejected. No local Trail executable
   or ADE implementation was located. Do not claim the external classifier was
   repaired. The operator approved upstream's manual fallback instead.
3. Historical transcript and SQLite log recovery did not identify the commands
   responsible for the reported 10-second and 8-second failures. Do not attribute
   them from deadline values or duplicate registrations alone.
4. Isolated installer and startup probes ran through the full `bg` wrapper after
   `load-watch ci decide ... local REASON` accepted the work. Two installer runs
   were byte-idempotent but retained two equivalent managed registrations: one
   unquoted and one single-quoted. The first exploratory fixture accidentally
   contained two unquoted copies and exposed the same preservation mechanism;
   the corrected fixture matched the live two-variant configuration.
5. All ten timing probes returned 0. Herdr v8 no-op probes took 0.028–0.140 s;
   v10 took 0.026–0.033 s. An isolated fresh-session socket received exactly one
   report from each hook: v8 in 0.096 s, v10 in 0.056 s. Moshi completed in
   0.134 s and the Graft/Trail startup hook in 0.132 s. Neither historical
   deadline failure reproduced. These are hook-level startup probes, not a new
   paid model turn or an end-to-end fresh-TUI acceptance claim.
6. The self-slash regression run initially exposed mistakes in the new test
   stub, not passing acceptance: it omitted the actual `pane get` identity,
   then invoked the internal child without the parent's follow-up environment.
   Both fixtures were corrected. The existing lifecycle suite passed; the
   affected parser/relay run reported 330 passed and 34 passing subtests, with
   only the new parent-launch test still failing at that intermediate point.
   The final Codex harness run passed all six tests and three subtests, including
   an actual detached fake-host parent -> `/new` -> one targeted `/baton` chain.
   Private logs: `self-slash-focused-tests.log`, `self-slash-codex-tests.log`.

## Key Decisions

1. Preserve all other session pointers. This new chain records ADE, one-offs and
   the Herdr worktrees as side workspaces; it owns no shared repository pointer.
2. Keep direct Herdr control conditional on real caller context. Do not impose
   that environment requirement on detached relay workers.
3. Preserve all fork work. Prepare integration separately and require the fork
   owner's coordination before promotion; never stash, reset or discard it.
4. Do not raise hook deadlines or hand-edit generated configuration. Test the
   actual bundled installer against isolated configuration and recommend repair
   at the owning installer or managed source.
5. Retain current stable Codex absent evidence that a prerelease fixes this case.

## Evidence & Data

Private evidence root:
`/Users/djbclark/.local/state/ade/relay-herdr-refresh-20261025/`.
It preserves the original Herdr binary, full old skill directory, skill metadata,
dirty-file backups, release/commit metadata, CI logs and the probe script/results.
Do not publish raw process/transcript/configuration logs.

Prior proof root `/tmp/relay-codex-submit-proof/` contains baseline and fixed
delivery receipts, the exact patch and the completed independent adversary
report: `APPROVE, no findings` on `f1a07ad780c24634302809f443ad5adae6be7233`
(code identical to `c90a9e9`). Prior targeted validation: 365 tests and 31
subtests passed; a real long-message Codex fixture returned `ACK_RELAY_FIXED`
without manual Enter. Main's complete CI independently passed with that code.

The fork `/Users/djbclark/src/herdr` remains on `herdr-sleeper` at `37dc774c`.
Its dirty files are `.gitignore` and untracked `.ignore`, both preserved.
Three existing unpushed commits remain unpushed: `7d6fb137`, `41f5bd17`,
`37dc774c`. Five earlier sleeper commits are also retained.

Isolated worktree `/Users/djbclark/src/herdr-upstream-refresh-wt`, branch
`integrate/upstream-refresh-20261025`, starts at upstream `5608de06` and has a
clean, uncommitted merge of `herdr-sleeper`. `git diff --cached --check` passed.
Merged index tree: `239b6db7f788b81e17373def23594ed3a85be99b`.
Staged paths: `.forgejo/workflows/ci.yml`, `scripts/forgejo-ci-run`, and
`scripts/herdr-sleeper/{README.md,herdr-sleeper,test_herdr_sleeper.py}`.
No promotion, push, compilation or server restart was performed.

Session edits: this handoff and `skills/session-finder/SKILL.md`.
The first unit was committed/pushed as `9e2d470` under the then-applicable
shared-master rule. After the operator replaced that rule, the remaining
uncommitted guidance was migrated, hunk-for-hunk, to the exclusively owned
`/Users/djbclark/src/djbclark-ade-relay-refresh-wt`, branch
`docs/relay-refresh-01a1735a`, recorded base `b26f543`. Subsequent edits and
commits happen only there. Shared checkout edits by other sessions are not ours.

## Operator Feedback

The operator chose the manual skill fallback after the external hook rejected
the named installer. They also requested current Codex and explicitly warned
that this session and other processes are active Codex TUIs. Preserve them.
The original plan explicitly forbids interruption of paid work, invented
delivery proof, version pins, and stealing another session's Tier 1 pointer.

## Where We're Going

1. After the queued clear/baton, verify the continuation in
   `/Users/djbclark/.local/state/self-slash.log` and confirm it still occupies
   `w2Q:p3`, cwd `/Users/djbclark/src/one-offs`, on the same model. The owning
   Codex PID before clearing was 1679; `/new` should create a new thread in
   that same TUI process. Check the actual fresh-session startup for hook
   failures as well as the targeted baton submission. The first queue sent
   nothing; the repaired queue is the only intended actual clear/baton chain.
   Do not clear again or repeat completed probes.
2. Read `self-slash-ci-result.json` in the private evidence root when
   `self-slash-ci.done` exists. Otherwise wait for that file; the detached CI
   watcher already owns the one run. Inspect any failures before declaring
   repair CI green. After success, integrate current master into the owned
   branch if needed, push/promote only verified code, and fast-forward the
   reference checkout only when clean and serialized. The source repair is
   currently executed from the owned task worktree, not an edited shared tree.
   Preserve that worktree until the waiter has finished its targeted baton.
3. Report concise results and remaining limitations after verification.
4. The narrow repair recommendation is in Herdr's installer: recognize the
   exact safe unquoted legacy hook command and remove all equivalent owned
   registrations while preserving unrelated hooks. `hook_command_variants`
   currently enumerates only canonical/legacy quoted variants. Both preview
   and current upstream retain that code. Duplicate search terms were
   `repo:herdrdev/herdr codex hook duplicate` and `integration unquoted`;
   the nearest existing report is [Kimi duplicate hook migration](https://github.com/herdrdev/herdr/issues/5157).
   Do not call this the timeout cause. Historical 10s/8s command attribution
   still requires an instrumented actual fresh-TUI reproduction with per-hook
   start/finish records; no timeout increase is justified by the current probes.
5. Coordinate with the owner before promoting the isolated Herdr merge. No live
   session was found with `/Users/djbclark/src/herdr` as its workspace.
6. Report the remaining managed-integration metadata gap (v8 installed, v10
   bundled; identical executable shell bodies). Migration repair belongs to
   the installer/source owner. Do not increase deadlines or treat the old
   version comment as a demonstrated runtime failure.
7. Use this chain's exact path for continuation:
   `/Users/djbclark/.local/state/handoffs/chains/standalone-relay-refresh-01a1735a/SESSION_LOG.md`.
   Queue only one baton through `self-slash` if it supports the actual host;
   never clear another session or silently substitute a new agent/process.

## Detached jobs

No open bigteam dispatch records belong to this session or the predecessor.
The CI notifier at `/tmp/relay-codex-submit-proof/notify-ci.py` completed;
`ci-main-notified` and `ci-main.json` in the evidence root prove the successful
notification and exact run. Its record is `ci-main-notifier.json`.

The isolated probe completed. Its script is `probe-hooks.py`, result
`hook-probes.json`. All local regression processes completed.

One detached CI watcher remains for the new source repair: record
`self-slash-ci-watch.json` in the evidence root, script
`watch-self-slash-ci.py`, exact run `40204830764`, result
`self-slash-ci-result.json`, completion marker `self-slash-ci.done`.
It runs in its own process session and sends one completion notification.
Do not start another watcher or rerun the workflow. If the result is absent,
wait for the marker using `bin/wait-file`.

The final same-session lifecycle waiter is owned by the repaired `self-slash`;
verify its log after continuation, never queue a second actual baton.

## Quick Start

```bash
python3 /Users/djbclark/src/djbclark-ade/claude/hooks/handoff-tools/session_log.py read --state-root /Users/djbclark/.local/state/handoffs --dir /Users/djbclark/.local/state/handoffs/chains/standalone-relay-refresh-01a1735a
git -C /Users/djbclark/src/herdr status --short
git -C /Users/djbclark/src/herdr-upstream-refresh-wt status --short
```
