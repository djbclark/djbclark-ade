---
name: effort-routing
description: >-
  Match your own reasoning effort to the work in front of you, within a
  single session — drop to a cheaper tier for mechanical stretches, climb
  back for judgment, and say when you switch. Use when starting a long
  stretch of file edits, doc writing, or command running; when a session
  set to high effort is doing rote work; when dispatching subagents; or
  when asked "should we drop the thinking level for this".
---

# Effort routing — your own tier, not other vendors'

Sibling to [model-routing](../model-routing/SKILL.md), which decides *which
vendor* runs work. This one decides *how much thinking* the current session
spends. They are different problems and get confused constantly.

Canonical source: `skills/effort-routing/SKILL.md` in djbclark-ade. Snapshot
**2026-08-23**.

## The honest constraint

`claude --model` and `--effort` set the tier **for a session**, and
`~/.claude/settings.json` holds the default (`effortLevel`). A running session
cannot re-tier itself mid-turn. So "dynamic effort" has exactly two real
mechanisms:

1. **Dispatch.** Subagents take their own `model` and `effort`. Sending a
   mechanical stretch to a cheap subagent is the one fully automatic lever.
2. **Tell the operator.** For the session's own tier, say plainly that the
   next stretch is mechanical and they can `/model` down — then keep working.
   Do not stop and wait.

Anything claiming more than that is describing a feature that does not exist.

## Classifying the stretch

Ask what the *next several actions* look like, not the last one:

| Signal | Tier |
|---|---|
| Applying a decision already made; edits, commits, doc writing, running known commands | **low / haiku** |
| Normal implementation with a clear shape; tests, adapters, refactors | **medium / sonnet** |
| The shape is not clear yet; architecture, adjudication, debugging something that already defeated one attempt, whole-corpus reading | **high / xhigh, Fable** |

Two traps worth naming. A session set high stays high through hours of rote
work because nobody notices — that is the common failure, and it is invisible
because nothing breaks. The rarer, worse one is dropping tier for something
that *looked* mechanical and quietly producing a bad decision; when in doubt
about which side you are on, stay high and say so.

## What to actually do

- **Long mechanical stretch ahead** — say so in one line and keep going;
  offer that `/model sonnet` or `--effort low` would cost less. Do not ask
  permission.
- **Fan-out of rote nodes** — dispatch them at `model: "haiku"`,
  `effort: "low"` rather than doing them inline at session tier.
- **One hard call inside otherwise ordinary work** — do not raise the whole
  session. Dispatch that single question to `fable-deep` and carry on; this is
  what its separate weekly budget is for (see model-routing).
- **Switching** — always name the switch and why. An unexplained tier change
  reads as inconsistency.

## Related

Vendor choice, quota headroom, and which pools are idle:
[model-routing](../model-routing/SKILL.md) and `bin/route_agent.py`
(`route --kind judgment|code|bulk|research|mechanical|github`). Effort routing
picks the tier; that picks the vendor. Run both.
