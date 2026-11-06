# HANDOFF: HELM LEAD 7c58015b, before the Mac reboot, 2026-11-06 ~11:40 EST

Successor start: `/baton` on this file, or read it whole. Lead = omp anthropic/claude-opus-5-5, Paseo agent
7c58015b-9996-4673-86e2-58842182418c, cwd ~/src/djbclark-ade. State dir: ~/.local/state/bigteam/lead-2026-11-02/.

## A. Where things stand
A1 Slim-down check-in round DONE. Consolidated doc: lead-2026-11-02/slim-down-checkins-2026-11-06.md, pushed to
   https://github.com/djbclark/djbclark-ade/blob/checkin/7c58015b/docs/checkins/slim-down-checkins-2026-11-06.md (989bb57b).
   37 reports; per-agent copies in lead-2026-11-02/checkins/; shas in checkin-done.txt.
A2 Missing reports: herdr panes w20:pM (agy, ~/src/bottom) and w36:pB (agy, ~/src/barnowl); delivery unverified, never resent.
A3 All held decisions answered by djbclark (doc section E9; per-agent answer files in answers/; originals split in
   pending-decisions/<agent>.md). Unverified deliveries: ebd6ed1a, 3ac46de6 (accepted), w20:pQ (herdr queued). Check
   `relay.py --pending` after reboot; never resend an accepted/queued one, confirm via the target's transcript.
A4 EVERY agent is PAUSED (slim-down). The next step belongs to djbclark: the Claude cloud split session runs, then
   agents get continue/stop/handoff. Do not resume agents' work on reboot; just bring them back up idle.
A5 Open for djbclark: 9946ed38 on the shared checkout master (ed6863c7 committed it there; also branch gitignore-aider):
   land by PR or drop, then reset master to origin/master. Doc E8f-E8k depend on what the split keeps.

## B. Stopped for the reboot
B1 3ac46de6 (tendcf lead) told at ~11:38 to stop its three detached slices (s5-design, fork-cmdb, q10-policy), commit WIP
   on their own branches, record resume state in its Tier 1 log (chain tendcf-linux-targets-20261029); ack id
   `reboot-3ac46de6` (delivered; ack not yet seen). Job records: ~/.local/state/bigteam/{tendcf-s5-20261103,
   fork-cmdb-closed-20261103,tendcf-q10-policy-20261106}/jobs/*.json. After reboot: `acp-dispatch` status on each; a
   killed slice with no report = exit 3, re-task (never reconstruct), do not resume blind.
B2 Nothing else of mine runs. launchd jobs come back by themselves: com.djbclark.load-watch, pr-policy, deadline-sweep,
   watchdogd. com.djbclark.ade-lander / ade-feeder stay booted out (djbclark: until the split ends).
B3 My open PRs (unchanged, held by the pause): 261 (fe676324), 270 (ca969c51), 294 (a688c9e4); questions-please PR 1.

## C. Bring-up after reboot (all in Paseo; herdr is retired from djbclark-ade)
C1 Paseo agents persist across a daemon restart (D1 T8). After login: open Paseo, `paseo ls --json`, diff against
   paseo-agents.json / paseo-agents.md in this dir (29 rows: 26 idle/running + 3 closed Dann tabs). Any missing or
   error row: reopen it from Paseo (same workspace), do NOT create duplicates. Dann tabs (428f5f02, 193014a8, d2a505dd)
   stay as they are (closed, never archived; djbclark's).
C2 Wake gently: at most 4 agents at a time, `bin/load-watch admit` between batches (PR 294 rule). Message is a plain
   "Mac rebooted; you are still PAUSED for the slim-down; confirm idle, `ack reboot-<id>`" via relay.py, no --steer.
C3 Herdr panes to bring into Paseo as new Paseo agents resuming the same native session (cwd, then resume command):
   | pane | agent | cwd | resume |
   |---|---|---|---|
   | w20:pN | omp | ~/src/aiuse | omp --resume 01a1a638-77f6-7250-ac46-3f0e6477c547 |
   | w20:pE | claude (32779db2, ops-e7) | ~/ops | claude --resume 32779db2-0fec-4f15-b8f2-a86b0a61636d |
   | w20:pQ | omp | ~/src/djbclark-ade-bridge-guard-wt | omp --resume 01a1a78e-8744-728e-9c36-c5944715ebf4 |
   | w20:pS | codex | ~/src/djbclark-ade-278-recovery-wt | codex resume 01a1a676-c0f2-7891-bf17-d0a5f5cdc619 |
   | w20:p0 | cursor | ~/src/aiuse | cursor-agent --resume a23df5c4-74a7-49c6-8111-ebb516687363 |
   | w20:p11 | cursor | ~/src/djbclark-ade | session id not recorded: newest cursor chat in that cwd titled "Venice model prompt injection hardening" |
   | w20:p12 | cursor | ~/src/djbclark-ade | cursor-agent --resume 656b0fec-e0aa-4802-bae5-199d0b1b5603 |
   | w36:pD | cursor | ~/src/barnowl | id not recorded: "Flash drive in-use processes (mac256usb)" |
   | w38:p8 | omp | ~/src/djbclark-ade | omp --resume 01a1a203-f827-71fa-b94f-2c064cf5b098 |
   | w20:pM | agy | ~/src/bottom | id not recorded; agy only via acp-run; no check-in |
   | w36:pB | agy | ~/src/barnowl | id not recorded; no check-in |
   Source: fleet.json (this dir, captured ~11:37) and each pane's check-in report (session ids). Exact resume flag
   syntax per TUI: check `acp-run --list` / the TUI's own docs before running; Paseo create_agent with matching
   provider where Paseo has one (omp, codex, claude, cursor), else a Paseo terminal running the resume command.
   Most of these panes finished their work (check-in recommendations ii/iv); djbclark may prefer not to revive them:
   ask with a picklist before reviving w20:p0, w20:p11, w20:p12, w20:pN, w38:p8, w20:pS (all report "done").
C4 Cloud sessions 01BvGHLy / 01BvGHLzD4 / 01BvGHM3 run in Anthropic's cloud; unaffected by the reboot.

## D. Rules carried (from djbclark, binding)
D1 Separate files per agent/owner; consolidate by reading them. D2 Dann tabs never archived. D3 Wake ≤4 at a time.
D4 Never stop paid work unasked (this reboot stop was asked). D5 Never commit in ~/src/djbclark-ade or ~/ops; worktrees.
D6 Replies: labelled lists, markdown links. D7 Burnable pools: agy, omp API, codex, zcode, cursor, grok; never Claude
   subscription, opencode-go, cline (cline 40% floor; Go/cline only for techno-euphora + Hermes).

## E. Update ~11:42: B1 done
E1 3ac46de6 acked `reboot-3ac46de6`: all three slices stopped; every worktree committed (WIP where partial) and pushed:
   s5-design c80ae8c (~/src/tendcf-s5-design-wt); merge-tmp-integration d32cade13 (djbclark/core, ~/src/cfengine-core-cmdb-wt);
   fork-pin-cmdb-fail-closed 072ceef (tendcf PR 41, still DO NOT MERGE); policy-cmdb-crosscheck 71245b8 (tendcf PR 42).
   Resume state per slice: ~/.local/state/handoffs/chains/tendcf-linux-targets-20261029/SESSION_LOG.md.
