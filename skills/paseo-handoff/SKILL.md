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
2. **Isolation** — "in a worktree" / "worktree" → create a workspace with `isolation: "worktree"`, using a short branch name derived from the task.
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

After startup, tell every still-relevant peer the new agent ID/title, workspace ID/name, task worktree and chain pointer through **peer-relay**. Check `delivered`; carry queued/unverified records without resending. A permission/question-card refusal remains blocked: report it and leave the notice for after that card is resolved, never bypass it. Preserve the old transcript until the receiver is verified; do not archive a workspace containing other agents or terminals.

Do not wait or poll for the agent to finish.
