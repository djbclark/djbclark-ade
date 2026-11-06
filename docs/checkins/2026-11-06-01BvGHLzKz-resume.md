# Restart state: ade1 lead orchestrator (01BvGHLzKz), cancelled 2026-11-06

Cancelled by djbclark, about 16:30 UTC on 2026-11-06. Everything stopped; nothing merged.
Combined check-in report: https://claude.ai/artifact/61ufc819fXztUoff2k1SmQ

## Sessions (all Anthropic cloud, claude-opus-5-5, env env_01B3WVq9VUmpufnhpHti9bnq)

| Role | Session | Work branch(es) | Resume note |
| --- | --- | --- | --- |
| Lead | session_01BvGHLzKzJxnbc5tsVVh82W | claude/ade1-9orwfa | this file |
| #278 | session_01BvGHM3L9L7cnyX55KTqtkJ | claude/issue-278-checkpointing | checkin/01BvGHM3: docs/checkins/2026-11-06-01BvGHM3-resume.md |
| #279 | session_01BvGHLyz5k4hAdc9VUjBg9b | claude/issue-279-linux-ports{,-1-sched,-2-monitors,-3-guards} | checkin/01BvGHLy: docs/checkins/2026-11-06-01BvGHLy-resume.md |
| #284 | session_01BvGHLzD4LkkXxMXY3g1n6T | claude/issue-284-ndc-oslo-ideas | checkin/01BvGHLz: docs/checkins/2026-11-06-01BvGHLzD4-resume.md |

## PRs at cancellation

| PR | State | Head | Remaining before merge |
| --- | --- | --- | --- |
| #289 (#284) | open, ready | beb417d (see child note for the exact sha) | pytest-linux and Codex on the head; marker on the head; /retro thread resolved per ruling |
| #291 (#279, 1/3) | open, ready | e95816e (see child note) | pytest-linux and the Codex security review on the head; marker on the head |
| #290 (#278) | DRAFT | 15186fb | adversary confirm, marker refresh, last Codex thread, CI and Codex re-review |
| #293 (#279, 2/3) | DRAFT, stacked on #291 | 58c5d9e | wait for the slim-down; merge #291 first; never delete the -1 branch before that |
| #292 (#279, 3/3) | CLOSED 2026-11-06 | e232f88 | surviving parts (skill-everywhere, codium-ai, app-tamer-ab, paseo-set-model) could be cherry-picked |

Also by the operator on 2026-11-06: #270 marked draft; #261 and #294 closed.

## Operator rulings in force

- /retro title trust (#289): option 1, collaborators are the trust boundary.
- This work is Claude-only (only this work).
- Paseo built-ins/plugins over relay.py and other home-grown plumbing.
- No installs or changes on djbclark's machines; no PR merges by children (lead merges with
  `gh pr merge N --squash --match-head-commit <sha>`; this cloud session has no merge tool).
- The operator relays messages by hand between this lead and the local Mac agents.

## How to restart

1. In a session with the claude-code-remote tools, `get_session` each child; if archived, `unarchive_session`.
2. `send_message` to each child: "[lead] RESUME: read your resume note on checkin/<id>, re-subscribe to your PR,
   bring it to READY on its current head, report READY head=<sha>. Do not merge." Ask for an ack first.
3. Expect the "claude-code-remote: Send Message" permission prompt in each child after a worker restart;
   the operator must approve it in claude.ai/code (choose always-allow).
4. When a child reports READY, check the marker names that head, CI is green and Codex has no open
   findings, then merge with --match-head-commit (#291 before #293).

## Lead branch

claude/ade1-9orwfa also carries 0cbeb70, the operator's settings script result for .claude/settings.json.
It drops graft's status line and Bash allows: do not land it as-is.
