# ADE-native verifyCmd (verify-until-pass): design

Snapshot **2026-11-10**. Design only — nothing built in this PR. Issue
[284](https://github.com/djbclark/djbclark-ade/issues/284) item 4 asked for a
goal / verify-until-pass loop after `acp-run --verify` retired: an opt-in
acceptance command, a Stop hook / skill for interactive sessions, **max 3
attempts**, under `deadline` + `bg`. Queue Carried #1 said evaluate
`37chengshan/goal-mode` first; [#425](https://github.com/djbclark/djbclark-ade/pull/425)
did that paper eval and **rejected** the plugin as the verifyCmd replacement
(self-report markers, no acceptance command; see
[`docs/goal-mode-eval.md`](goal-mode-eval.md) on that PR). This page is the
next step: the ADE-native path that eval called for.

Status: **design**. Build waits on operator yes for any live hook install
(order 11) and on a thin runner landing through a normal PR. The retired
`claude-quota-guard` named in issue 284 #4 is gone (slim-down E7); MVP does
not revive it.

## A. Problem

1. **`acp-run --verify` is gone** with Wave 6 / the acp-run retirement
   (AGENTS.md review rule 4). Nothing in the harness currently re-runs an
   operator- or brief-supplied command until it exits 0.
2. **Prose is not acceptance.** Standing order 4 and orch §6: verify the
   artifact (diff, tests, report content). A model saying DONE, or emitting
   `<goal-complete />`, can still leave failing tests.
3. **goal-mode does not close the gap** ([#425](https://github.com/djbclark/djbclark-ade/pull/425)
   / `docs/goal-mode-eval.md` C2–C3): it auto-continues on self-report markers,
   defaults to 10 nudges, and has no verifyCmd, no `deadline`/`bg` wiring, and
   no delivery-footer / shim exit contract. Auto-steer also collides with
   fan-out orchestrator sends. Reject as the 284 #4 implementer; keep that
   page as the reject record.
4. **Caps must live in code** (orch §1 rule 4): "retry at most 3 times" in a
   prompt becomes 30; a counter does not.

## B. Shape (what registers, who runs it)

### B1. Registration (opt-in)

A Paseo agent (or its dispatcher) registers one acceptance command per
workspace / agent id. No registration → no verify loop (interactive sessions
and slices that already verify in the brief stay unchanged).

Proposed record (atomic rewrite beside, then `os.replace`; fields read with
`.get` so older records still load):

```json
{
  "version": 1,
  "agent_id": "<PASEO_AGENT_ID>",
  "workspace": "/abs/path/to/claimed/worktree",
  "argv": ["bin/pytest", "-q", "tests/test_foo.py"],
  "cwd": "/abs/path/to/claimed/worktree",
  "max_attempts": 3,
  "attempt": 0,
  "budget": "20m",
  "owner": "<PASEO_AGENT_ID or lead id>",
  "created_at": "2026-11-10T00:00:00Z",
  "last_rc": null,
  "last_log": null,
  "state": "armed"
}
```

1. **`argv` is an argv list, never a shell string** (review rule 4). No
   `shell=True`. The operator or the brief's acceptance line is parsed once at
   register time into argv; refused (exit 2) if empty, relative without a
   resolvable cwd, or if cwd is outside the claimed workspace.
2. **Home of the record (MVP proposal):**
   `~/.local/state/ade/verifycmd/<agent_id>.json` (ADE-owned, not a Paseo
   plugin-state file). Interactive Claude Stop hook may *also* mirror a
   pointer at `.git/ade-goal.json` inside the worktree (issue 284's sketch)
   so a hook confined to the tree can find it; the authoritative counter and
   argv stay under `~/.local/state/ade/verifycmd/`.
3. **Who may register:** the agent itself (interactive `/verify` or
   `skills/goal`), or the dispatcher writing the record before `paseo run`
   when the brief carries an acceptance command. Fan-out workers never raise
   `max_attempts` above 3; the harness clamps.

### B2. Runner (harness-owned)

A small ADE binary (name TBD: `bin/ade-verify` or `bin/verifycmd`) owns the
loop. The model never decides "pass":

```text
armed → run(argv) under deadline+bg → rc==0? → passed
                                      rc!=0? → attempt++ → attempt>=max? → failed
                                                      else → nudge agent once → armed
```

1. **Pass:** exit 0 from argv. That is the only success signal.
2. **Fail attempt:** nonzero rc (including signal death as 128+N). Log path +
   rc recorded; one bounded nudge to the agent ("verifyCmd failed, rc=N,
   log=…; fix and end the turn"). No auto-steer storm: one message per
   attempt, idle-gated like orch §5a.
3. **Exhausted:** `state=failed`, no further nudge; report / Stop path surfaces
   `BLOCKED: verifyCmd exhausted after 3` (or the dispatch shim's exit 4
   shape once wired).
4. **Missing command / refuse:** exit 2 from the runner (bad argv, workspace
   claim mismatch, already `passed`/`failed` and not re-armed).
5. **Deadline stop of the verify process:** exit 124 (same as `deadline run`);
   counts as a failed attempt, not a pass.

### B3. Two entry points (same runner)

| Surface | Trigger | MVP? |
|---|---|---|
| **Interactive** | Stop hook (`claude/hooks/goal_stop_nudge.py` sketch) and/or `skills/goal` that arms argv and, on Stop, calls the runner; if fail and attempts left, nudge instead of ending | Yes (Claude Stop first; other TUIs later) |
| **Dispatched / jobs** | Opt-in on finish: after the report ends `DONE` (and before `.done` is authoritative for waiters), the harness runs verifyCmd; only then treat delivery as verified | Yes for the acp-dispatch / fan-out finish path once the shim or its Paseo replacement owns finish; "ade-jobs G1" from 284 stays a later consumer of the same runner |

Both share max 3, `deadline`+`bg`, and the state file. Interactive never arms
on a fan-out worker slice that the orchestrator already verifies centrally
(orch §6): one verifier per slice.

## C. Exit semantics

| Code | Meaning |
|---|---|
| **0** | Acceptance command exited 0; record `state=passed`. |
| **1** | Acceptance command exited nonzero and attempts remain (or the runner is reporting "not yet passed" to a waiter). |
| **2** | Refused: no record, bad argv, cwd outside claim, or terminal state without re-arm. |
| **4** | Exhausted (`max_attempts` reached, still nonzero). Aligns with dispatch `BLOCKED`. |
| **75** | Machine too hot (`load-watch` / `bg` refusal); nothing run; attempt **not** consumed. |
| **124** | Deadline killed the verify process; attempt consumed as failure. |

Rules:

1. **Exit 0 of the agent process is still not success** without verifyCmd when
   one is armed (orch §5). Waiters that today treat `.done` + report `DONE` as
   finished must, when a verifyCmd record is present, also require
   `state=passed` (or the runner's exit 0) before treating the slice as
   verified.
2. **Attempt counter is harness state**, incremented only after a started
   verify process finishes (0 / nonzero / 124). Refuse and 75 do not
   increment.
3. **No pipe-rc** (review rule 2): runner writes `rc` into the record and a
   sidecar log, then exits with the table above.

## D. Interaction with `deadline` and handoff

### D1. deadline + bg

1. Every verify invocation runs as
   `deadline run --budget <record.budget> --owner <owner> -- bg <argv…>`
   (or `deadline run` wrapping the same argv `bg` would admit). Budget
   default 20m; register may lower it; harness clamps to a config ceiling.
2. Nested: if the agent is already under `DEADLINE_NAME`, the runner does
   **not** register a second deadline for a short verify; it beats the outer
   record and still runs argv under `bg` when `bg` is required for tests
   (dispatch footer rule 16). Long verify (≥ ~2 min) always has its own
   named record (`verifycmd-<agent_id>-<attempt>`).
3. Expiry: `--on-expire kill` of the verify process group only — never the
   agent TUI (deadline safety rule 3). Owner gets the usual notify/relay.
4. Load: `bg` / `load-watch` may return 75; that is "try later", not a
   consumed attempt.

### D2. handoff

1. On handoff (legacy `skills/handoff` / `old-handoff-use-paseo-handoff`, or
   Paseo's `paseo-handoff`): the predecessor's verifyCmd record is either
   **re-keyed to the successor agent id** (same argv, `attempt` preserved) or
   **cleared** if the handoff brief drops acceptance. Silent orphan records
   under the old id are swept after 7 days (same retention idea as deadline
   terminal records).
2. A successor that starts top-level (`env -u PASEO_AGENT_ID … paseo run`,
   AGENTS.md handoff note) must re-register or inherit explicitly; a Stop
   hook must not read another agent's record by workspace alone without the
   agent id match.
3. Checkpoint / interruption (`docs/checkpoint.md`): verifyCmd state is
   ADE state beside the agent, not inside the model context — a resumed
   session re-reads the record; it does not trust transcript claims of pass.

## E. Risks

1. **Self-report regression.** Any path that treats model text or a plugin
   marker as pass re-introduces the #425 failure mode. Mitigation: only argv
   exit 0; markers are out of scope for this design.
2. **Shell / injection.** Operator- or brief-supplied strings become argv at
   register time; never `shell=True`. Refuse metacharacter-only "commands"
   that cannot parse to argv.
3. **Fan-out collision.** Auto-nudge during an orchestrator send races like
   goal-mode's steer. Mitigation: one nudge per failed attempt, only when
   `paseo` reports idle; never arm verifyCmd auto-nudge on a worker the
   orchestrator already owns.
4. **CI-first / Mac load.** Heavy verify on the Mac fights `~/CLAUDE.md`
   CI-first and `bg`'s load gate. Mitigation: argv should be focused checks
   `load-watch ci check` allows; full suite stays CI / pre-commit policy
   (orch §6). MVP docs say so; the runner does not ban heavy argv but `bg`
   may refuse (75).
5. **Hook trust / order 11.** A Stop hook in live `~/.claude/settings.json`
   is a live config change. Design ships in-repo; install waits for operator
   yes. Unsandboxed daemon plugins stay off the path (PLAN I3 / #425 D).
6. **False "verified" for waiters.** If `.done` is touched before verify
   passes, leads re-task too early. Mitigation: when a record is armed,
   finish path runs verify **before** authoritative `.done` (or waiters
   require `state=passed`).
7. **Attempt burn on flakes / infra.** 124 and flaky tests consume attempts.
   Mitigation: 75 does not burn; operator may re-arm; max stays 3 (issue
   284), not goal-mode's 10.
8. **Workspace claim.** Running argv outside the claimed worktree breaks
   order 9. Mitigation: refuse cwd outside claim; no follow of symlinks out
   of the tree (same spirit as `review-launch`).

## F. MVP scope

**In (first build PR after this design):**

1. State file schema + `bin` runner: register / status / clear / run-once /
   run-until-pass (max 3), argv-only, exit table in §C.
2. `deadline` + `bg` wrapping as in §D1; tests under a temp state dir
   (no real daemon).
3. Docs: this page kept current; Carried #1 points here; orch §6 gains a
   one-line pointer once code lands (or in the build PR).
4. Optional thin `skills/goal` that only arms/clears/status via the runner
   CLI (no plugin).

**Out of MVP:**

1. Installing or depending on `37chengshan/goal-mode` (rejected, #425).
2. Live Claude Stop hook install on the operator Mac (order 11).
3. ade-jobs G1 / full job state machine; other TUI Stop hooks; Paseo daemon
   plugin.
4. Reviving `claude-quota-guard`.
5. Raising max attempts above 3; shell-string verify; auto-continue without
   a failed verifyCmd.
6. Mac probe of goal-mode (still operator-needed on the #425 page; unrelated
   to this runner).

## G. Acceptance of *this* design (doc)

1. Cites [#425](https://github.com/djbclark/djbclark-ade/pull/425) reject and
   issue 284 #4 residual.
2. Defines register → run → exit semantics, deadline/handoff rules, risks,
   MVP in/out.
3. Queue Carried #1 points at this page for the ADE-native residual.
4. No code, no APPROVE, no merge in the design PR.
