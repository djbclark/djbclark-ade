---
schema_version: 1
handoff_id: 5a25
parent_handoff_ids: []
lineage: none
chain: [standalone-relay-refresh-01a1735a]
repo: djbclark-ade
workspace: /Users/djbclark/src/one-offs
branch: master
head_sha: 1d7bded
created_at: 2026-10-25T10:25:00-04:00
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

This execution context exposes no Herdr, Orca or Paseo caller identity.
`test "${HERDR_ENV:-}" = 1` returned 1 in a separately checked tool call.
Do not fabricate that identity or directly control a focused pane from here.
The live Herdr server has not been transitioned. Its current version still
needs a permitted host-side status receipt; process liveness alone is not a
version check. Codex's installed managed hook is v8, whereas the preview bundles
v10. Other installed integration version gaps are recorded privately.

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
4. Short isolated installer and startup probes were submitted through the full
   `bg` wrapper after `load-watch ci decide ... local REASON` accepted the work.
   The wrapper initially held for load/memory churn. Read the probe result before
   claiming installer idempotence or a hook root cause.

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

Session edits: this handoff and
`/Users/djbclark/src/djbclark-ade/skills/session-finder/SKILL.md`.
Other dirty ADE paths (`CHANGELOG.md`, `README.md`, `docs/skills.md`,
`skills/paseowatch/`) predate this session and are not ours.

## Operator Feedback

The operator chose the manual skill fallback after the external hook rejected
the named installer. They also requested current Codex and explicitly warned
that this session and other processes are active Codex TUIs. Preserve them.
The original plan explicitly forbids interruption of paid work, invented
delivery proof, version pins, and stealing another session's Tier 1 pointer.

## Where We're Going

1. Read `hook-probes.json` in the private evidence root and the saved probe log;
   if the job is still waiting, retain that job rather than launching a duplicate.
2. Attribute any reproduced failures to actual commands and measured timings.
   If historical failures remain unidentifiable, say so separately from current
   probe results and recommend the smallest instrumented fresh-TUI reproduction.
3. Coordinate with the owner before promoting the isolated Herdr merge. No live
   session was found with `/Users/djbclark/src/herdr` as its workspace.
4. From a genuine Herdr caller, obtain the running server version, compare it
   with the installed preview, and transition only with verified compatible
   handoff or a proven safe idle boundary. Check integration version separately.
5. Use this chain's exact path for continuation:
   `/Users/djbclark/.local/state/handoffs/chains/standalone-relay-refresh-01a1735a/SESSION_LOG.md`.
   Queue only one baton through `self-slash` if it supports the actual host;
   never clear another session or silently substitute a new agent/process.

## Detached jobs

No open bigteam dispatch records belong to this session or the predecessor.
The CI notifier at `/tmp/relay-codex-submit-proof/notify-ci.py` completed;
`ci-main-notified` and `ci-main.json` in the evidence root prove the successful
notification and exact run. Its record is `ci-main-notifier.json`.

The isolated probe is running through `bg` in an exec session; it is not a
durable detached job. Its script is `probe-hooks.py`, result `hook-probes.json`.
Do not assume that an exec waiter survives a context clear.

## Quick Start

```bash
python3 /Users/djbclark/src/djbclark-ade/claude/hooks/handoff-tools/session_log.py read --state-root /Users/djbclark/.local/state/handoffs --dir /Users/djbclark/.local/state/handoffs/chains/standalone-relay-refresh-01a1735a
git -C /Users/djbclark/src/herdr status --short
git -C /Users/djbclark/src/herdr-upstream-refresh-wt status --short
```
