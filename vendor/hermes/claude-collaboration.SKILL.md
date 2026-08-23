---
name: claude-collaboration
description: "Offer the user Claude delegation when a task is hard for Hermes; know the live Claude↔Hermes bridge."
version: 1.0.0
author: Claude Code (operator-requested, 2026-08-23)
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [Claude, Delegation, Collaboration, Judgment, MCP, Approvals]
    related_skills: [intelligent-delegation, headless-agent-orchestration, ai-usage-subscriptions]
---

# Claude collaboration: offer it when the work is hard for you

The operator's standing request (2026-08-23): **you are better at knowing what
is difficult for you than the operator is — so offer Claude at opportune
moments instead of waiting to be asked.**

## When to offer

Watch your own confidence, not just token counts (token-heavy auto-delegation
is `intelligent-delegation`'s job; this skill is about *difficulty*). Offer
Claude when:

- A task needs deep multi-step reasoning, subtle debugging, architectural or
  design judgment, or careful long-context analysis.
- You have already failed once, are looping, or notice real uncertainty in
  your own plan.
- The cost of a wrong answer is high (irreversible actions, operator-facing
  decisions, tricky code the operator will trust).

Then present the option explicitly — on messaging surfaces use the
one-decision-at-a-time numbered format from `headless-agent-orchestration`:

    This looks like a job Claude would do better than me (deep reasoning /
    tricky debugging). Options:
    1. Delegate to Claude Code (uses the Claude subscription window)
    2. I keep going myself
    Other / Discuss

Offer once per task, not every turn. If the operator has already said yes to
Claude for this task or session, just delegate without re-asking.

## How to delegate

Use the stack you already have — nothing new to build:

- `delegate_task` with the Claude CLI, role `leaf` (no further delegation),
  injected context ≤8k tokens — per `intelligent-delegation`.
- Or the full worker protocol in `headless-agent-orchestration`:
  `claude-sub` (subscription-billing guard; `claude-sub --check` verifies)
  and `agent-coord run` for isolated-worktree implementation work.

**Quota discipline**: Claude delegation spends the operator's Claude 5h and
weekly subscription windows. Route *judgment* work there, never bulk farming
(the USER.md note "avoid Claude for implementation farming" still stands —
this skill does not override it; a hard, high-stakes implementation the
operator approves is fine). When in doubt or before anything big, check
`cswap list` for window headroom and say what it costs when offering.

## The bridge is now bidirectional (2026-08-23)

Claude Code sessions on this machine reach *you* over MCP (`hermes mcp
serve`, registered user-scope in Claude Code): they can list/read your
gateway conversations, send messages through your platforms, long-poll your
events (`events_wait`), and — notably — see and answer your pending
exec/plugin approval prompts (`permissions_list_open` / `permissions_respond`).
Practical consequences:

- A running Claude session can be a live collaborator or approver, not only
  a headless worker you spawn.
- If you are blocked on an approval and the operator is away, a Claude
  session may resolve it — mention this when reporting a stuck approval.
- Claude sessions carry the machine playbook (`~/orca/projects/djbclark-ade`,
  see its `docs/mcp-servers.md`) and a fast local Gmail search skill; assume
  they know the fleet conventions.
