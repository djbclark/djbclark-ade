# Goal Mode (`37chengshan/goal-mode`): paper eval for issue 284 #4

Snapshot **2026-11-09**. Source read at registry head
[`afd07503494c13746a5ca676f6990a9d3db71520`](https://github.com/37chengshan/paseo-goal-mode/commit/afd07503494c13746a5ca676f6990a9d3db71520)
(`paseo-goal-mode` 0.1.0; listing [paseo.sh/plugins/37chengshan/goal-mode](https://paseo.sh/plugins/37chengshan/goal-mode)).
**No live Mac install in this eval** (Cloud Agent has no `paseo`; Mac probe is operator-needed).

Issue 284 item 4 asked for a **goal / verify-until-pass** loop after `acp-run --verify` retired: opt-in acceptance
command, Stop hook / skill for interactive sessions, **max 3 attempts**, under `deadline` + `bg`. Queue Carried #1
said evaluate this Paseo plugin first. This page is that eval.

## A. What it is

Goal Mode is a Paseo daemon plugin (id `goal-mode`). On `agent.turn_ended` it auto-sends a short continue
(steer) until the agent self-reports done or blocked, or hits the nudge cap.

1. **Start:** `/goal <objective>` (or `/goal --max=N <objective>`, N 1–100; default **10**).
2. **Control:** `/goal status|pause|resume|clear` (`stop`/`off`/`cancel`/`none` clear aliases).
3. **Done marker** (last ~3 lines of turn text): `<goal-complete />`.
4. **Blocked marker:** `<goal-blocked>reason</goal-blocked>`.
5. **State:** `~/.paseo/plugin-state/goal-mode.json` on the daemon host (atomic rewrite). Timeline cards
   (`kind: goal`) show set / nudge / complete / blocked / paused.
6. **Limits:** canceled turn → pause; **3** consecutive failed turns → pause; failed send → pause; nudge
   limit → status `blocked` for a human. Requires Paseo **≥ 0.11.4**. No external network; prompts still go
   through the agent's provider.

It is a **keep-working / Ralph-style auto-continue** helper (also noted in
`docs/history/paseo-plugins-scan-2026-10-19.md`). It is **not** a harness that runs an acceptance command.

## B. Install probe commands (operator, Mac daemon)

Do not invent results. Run on the Mac that hosts the Paseo daemon; install only with the operator's yes
(AGENTS.md order 11 for live plugin settings).

```sh
paseo --version                                          # need >= 0.11.4
paseo plugin --help                                      # confirm add/ls/disable verbs on this CLI
paseo plugin ls --json                                   # before: is goal-mode already present?
# only after explicit operator yes:
paseo plugin add 37chengshan/goal-mode
paseo plugin ls --json                                   # expect id goal-mode, running/enabled
# smoke on a disposable agent (not a live fan-out slice):
#   /goal --max=2 echo the word ping then stop
#   confirm one auto-continue, then agent ends with <goal-complete />
#   /goal status  → completed; /goal clear
paseo plugin disable goal-mode                           # off switch; only on operator word
```

Record: Paseo version, plugin id/status from `ls --json`, whether markers ended the loop, and any send/steer
collisions with an in-flight turn. Paste those facts back into Carried #1 / this page's "Mac probe" line.

## C. Accept / reject vs the current ADE loop

### C1. What ADE already does (paseo + fan-out)

1. Macro graph: `skills/fan-out` + `paseo run` / `acp-dispatch` shim; briefs with acceptance check and
   delivery footer (`docs/dispatch-footer.md`: report ends `DONE` / `BLOCKED:`, then `.done`).
2. Failure: classify by exit code; **three attempts per slice, then stop** (`docs/orchestration-practices.md`
   §5); load gate before start; `deadline` + `bg` for long work.
3. Verify the **artifact** (diff, tests, report content), not prose (`AGENTS.md` standing order 4; orch §6).
4. Issue 284 #4 residual: replace retired `acp-run --verify` with opt-in **verifyCmd** (and a Stop nudge /
   `skills/goal` for interactive), still capped and gated.

### C2. Gaps if used as verify-until-pass

| Need (284 #4 / ADE) | goal-mode |
|---|---|
| Run an acceptance **command**; pass = exit 0 | None; completion is agent-emitted markers |
| Cap **3** attempts | Default **10** nudges (`--max` can lower; not ADE-wired) |
| `deadline` + `bg` + load-watch | No integration |
| Delivery footer / `.done` / shim exit codes | Separate timeline goal card; no report contract |
| Fan-out: one message at a time, idle-gated | Auto-steer on every finished turn can collide with orchestrator sends |
| Verify centrally after DONE | Self-report can claim complete with failing tests |

### C3. Verdict (paper, 2026-11-09)

1. **Reject as the verify-until-pass replacement.** It does not run verifyCmd and treats model prose as
   success. Building ADE's loop on top of it would still need an external checker; the plugin would only
   supply auto-continue noise.
2. **Do not install on the trusted daemon for that purpose** until a Mac probe (section B) and an operator
   yes. Auto-continue that steers agents is the same trust class as other unattended prompt senders
   (`docs/slim/research/plugins-trust-2026-11-06.md`).
3. **Optional later (separate decision):** interactive "keep working on this tab" after the Mac smoke, with
   `--max` ≤ 3 and never on fan-out worker slices. That is not issue 284 #4.
4. **Next for 284 #4:** design the small ADE-native path (Stop hook / skill + opt-in verifyCmd under
   `deadline`/`bg`, max 3) without depending on this plugin; keep this page as the reject record.

## D. Mac probe status

**Operator-needed** (2026-11-09). Not run from Cloud Agent (`paseo` absent). No install/disable claimed.
