---
name: paseo-handoff
description: Hand off the current task to another agent running in Paseo, with full context. Use only when the user asks to hand off through Paseo ("/paseo-handoff", "hand this to a Paseo agent"); a plain "handoff" is the handoff skill (Tier 2 document), and an Orca hand-off is orca-cli.
user-invocable: true
---

# Handoff Skill

Transfer the current task — context, decisions, failed attempts, constraints — to a fresh agent. The receiving agent starts with **zero context**, so the handoff prompt must be a self-contained briefing.

**User's arguments:** $ARGUMENTS

## Prerequisites

Read the **paseo** skill. Use `list_profiles` and read configured profiles' `notes` when that MCP tool is exposed. In a terminal-only session without Paseo MCP, use the CLI fallback in **paseo** instead; do not invent a `paseo profile` command or treat an unavailable tool as an absent profile catalog.

**Check execution mode first (2026-10-27).** Plan Mode permits inspection only: no handoff writes, claims, launches or peer notices. Say that mode is the blocker and retain the selected destination. When Default mode resumes and the operator says “go”, continue without asking again.

## Parsing arguments

1. **Agent profile** — explicit profile name first; otherwise choose the profile whose `notes` best match the work. Materialize it into `create_agent` as described by the **paseo** skill. If no profile fits, use Paseo's provider discovery fallback.
2. **Isolation** — "in a worktree" / "worktree" → create a workspace with `isolation: "worktree"`, using a short branch name derived from the task. **Interim rule (2026-10-30, `docs/paseo-only-rearchitecture.md` D0.3; local patch 2 in `skills/paseo/UPSTREAM.md`):** until that plan's D1.3 and D2 gate have passed, archiving a Paseo worktree workspace can delete unpushed work. So run `git worktree add` first (AGENTS.md order 9), then create the `isolation: "local"` workspace at that worktree's path, so the agent never starts in the shared checkout; tell the user why.
3. **Task description** — anything else the user said.

## The handoff prompt

The receiving agent has zero context. Include:

```
## Task
[Imperative description.]

## Context
[Why this task exists, required context.]

## Relevant files
- `path/to/file.ts` — [what it is and why it matters]

## Current state
[What's done, what works, what doesn't.]

## What was tried
- [Approach] — [why it failed or was abandoned]

## Decisions
- [Decision — rationale]

## Acceptance criteria
- [ ] [Criterion]

## Constraints
- [Must-not / must-preserve]
```

**Preserve task semantics.** Investigate-only → "DO NOT edit files." Fix → "implement the fix." Refactor → "refactor, not rewrite." Carry the user's exact intent.

## Launch

Prepare the handoff in a dedicated workspace:

1. Select the current workspace or call `create_workspace` with the requested isolation.
2. Call `create_agent` with a `[Handoff] <task>` title, the briefing as initial prompt, and the selected `workspaceId` when explicit placement is needed.
3. Return the agent and workspace to the user, explaining that it remains in your subagent track until they detach it manually.

Do not encode independence as a create mode and do not invoke CLI or wire-level detach operations. Detach is a user gesture in the subagents track.

Verify startup once with `paseo inspect <agent-id> --json` and verify the returned workspace against `paseo workspace ls --json`; check provider/model, mode and cwd. This is a startup check, not a wait for completion. If placement resolves to a shared reference checkout, the initial brief must require every edit/test/commit in a separately claimed task worktree.

For a durable continuation, first use **handoff** to write and commit the Tier 2 brief in the claimed task worktree and **session-handoff** to update the owned Tier 1 chain. Put the explicit chain pointer in the initial prompt; a bare `/baton` from a shared checkout can resume another chain. Do not run handoff's same-session `/new` when transferring to Paseo.

After startup and any expectation transfer below, tell every still-relevant peer the new agent ID/title, workspace ID/name, task worktree and chain pointer through **peer-relay**. Check `delivered`; carry queued/unverified records without resending. A permission/question-card refusal remains blocked: report it and leave the notice for after that card is resolved, never bypass it. Preserve the old transcript until the receiver is verified; do not archive a workspace containing other agents or terminals.

## Retire the predecessor, and register the successor with peers (djbclark, 2026-10-30)

Two standing rules, made in the Dann Chat thinking room; they bind **every** Paseo seat here, not only
Dann's. The Dann-specific reading, with commands and a dated seat map, is
`~/src/techno-euphora/docs/handoffs/TAB-LIFECYCLE.md`.

1. **Archive the old tab once the successor is verifiably up.** *"Whenever you verifiably open a
   successor tab, you can close the old tab."* Verification is, in this order: `paseo inspect <id>
   --json` reports `ParentAgentId: null` (a parented agent runs, answers and is invisible in the tab
   list — see the **paseo** skill); the `Cwd`, provider and model are the ones intended; and the
   successor has answered at least one turn. Then `paseo archive <old-id>` — a **soft-delete** that
   interrupts only if the old agent is still running and returns `archivedAt`. Re-list and prove the
   old id left the active list; the transcript stays retrievable with `--include-archived`. Archive
   the **agent** first, never a workspace that still holds anything (a workspace archive takes every
   agent and terminal in it, and until `docs/paseo-only-rearchitecture.md` D1.3/D2 gate can delete
   unpushed work). **Then, whenever you archive or close an agent for any reason, check its
   workspace:** if it now has no live agent (`paseo ls -g --json`, matched to the workspace through
   `~/.paseo/agents/*/<id>.json`; `paseo ls --workspace` does not filter, 2026-11-01), no terminal
   (`paseo terminal ls`) and `isolation: local` (`paseo workspace ls --json`; never a worktree
   workspace), archive it too with `paseo workspace archive <wks_id>`, so the sidebar does not fill
   with empty workspaces (djbclark, 2026-11-01: six were left behind). Any doubt keeps it. A seat
   that has not written down what it learned has not handed off.
2. **Every sibling and child learns the successor's id, and the successor learns theirs** — both
   directions, on every handoff. A peer that does not know the id of the seat above or beside it
   cannot hand off to it, cannot relay to it, and cannot notice it was archived; that is a one-way
   link and it is how an entity splits. A notice names the agent id and tab title, the **role** it
   answers to and the role it is being told about, and that this id supersedes any earlier id for that
   role. Send it through **peer-relay** and read the status word: unsent until `delivered` or an
   `ack <id>`. An idle peer gets a plain prompt, never `--steer`. **The role is the durable address
   and the id is the instance** — ids go in the notice and in the routing table, never in a brief as
   if they were permanent.

## Peer notices belong to the successor (operator, 2026-10-27)


`relay.py --expect-ack` and the first-contact footer tell the peer to reply to the **sender's own** id (`relay.py` footer, `me[id]`),
and the expectation watches the **sender's** transcript. A notice sent by the retiring session therefore sends every late ack to a
window that is about to close (2026-10-27: a peer's ack reached the old session after the transfer and would have been lost).

1. The retiring session sends no location notice. It puts the durable peer list in the Tier 2 document: per peer the id, title,
   workspace, any relay record ID already sent with its status (`delivered`, `queued`, `unverified`, `failed` or blocked by a
   question card) and the ack token it was asked for.
2. Before the old session finishes, it verifies that the successor accepted this duty (the successor's named ack).
   This acceptance ack is separate from the late peer acks being adopted. The old session then finishes; no step depends
   on its model or window forwarding a late reply.
3. The **successor FIRST transfers** expectations already sent by the old session:
   `relay.py --transfer-expectations OLD_SENDER` (or repeat `--id TOKEN` to select), then `relay.py --pending` / `--sweep`.
   OLD_SENDER is its exact fleet id, full session id or Paseo id and must name one row carrying `finished`: Claude transcript
   `/handoff` or `/quit`, or ACP `done` (heuristics, not proof of process exit; ACP can take another turn). A non-Claude Paseo
   agent cannot be transferred yet: it has no `finished` evidence and is refused, exit 2. Live, missing, ambiguous and self rows
   are also refused, exit 2. A same-pane successor sharing the old fleet id cannot transfer, even with distinct session ids.
   Unswept acks in the OLD transcript are settled as `acked` rather than transferred. Tokens skipped for ownership/target safety
   are listed as `skipped`. JSON/text report `transferred`, `acked`, `skipped` and `missing`; any explicit `--id` not transferred
   exits 1 with `missing: [...]` (including absent, closed, another sender's, skipped, or just settled as `acked`). Partial transfers
   still take effect. With no explicit ids, zero transfers exits 0. Never resend notices already sent or hand-edit their records.
4. **THEN the successor tells peers** to address late `ack TOKEN` replies to its surviving id, from its real identity
   (`relay.py PEER "<text>" --expect-ack NEW_TOKEN`; first contact asks for a named ack). Use a fresh token for a deliberate
   new return-path check. An ack sent to the SUCCESSOR before the transfer offset is not counted. Transfer forwards no messages.
   Queued, unverified and card-blocked statuses survive unchanged and are never called delivered; notify a blocked peer after
   its card resolves, not around it.
5. Acceptance scenario: the old session finishes before a peer's delayed ack and before a queued notice delivers. While its
   finished fleet row still exists, the successor transfers the open expectation, THEN tells the peer its surviving address.
   `relay.py --pending` lists the new owner; the later ack to the successor resolves it by `relay.py --sweep`. An ack already
   in the old transcript is instead settled during transfer. The queued notice remains queued until relay reports `delivered`.

CLI gotcha (2026-10-27): `paseo logs --json` prints rendered text, not parseable JSON, on this install; `inspect` and `logs` do not
share an encoding. Match a token in logs as text.

Do not wait or poll for the agent to finish.
