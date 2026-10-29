---
name: effort-routing
description: >-
  Match your own reasoning effort to the work within a session: drop to a
  cheaper tier for mechanical stretches, climb back for judgment, and say when
  you switch. When you dispatch, also pick a context window: a bigger one for
  a whole-corpus read or a long log, the default when the extra tokens would
  only cost more. Use for long stretches of file edits, doc writing or command
  running, when a high-effort session does rote work, when dispatching
  subagents, or on "should we drop the thinking level for this".
---

# Effort routing — your own tier, not other vendors'

Sibling to [model-routing](../model-routing/SKILL.md), which decides *which
vendor* runs work. This one decides *how much thinking* the current session
spends. They are different problems and get confused constantly.

Canonical source: `skills/effort-routing/SKILL.md` in djbclark-ade
(`~/src/djbclark-ade`; every TUI links to it directly via skill-everywhere). Snapshot
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
| The shape is not clear yet; architecture, adjudication, debugging something that already defeated one attempt | **high, Opus** (Fable `high` only when that really needs it; `xhigh` almost never, operator 2026-10-18) |

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
  session. Dispatch that single question to `acp-dispatch claude --model opus
  --kind judgment --effort high` and carry on. Only when it really needs a frontier model
  (it defeated real attempts, or is a security-relevant final review) use
  `fable-deep` (Fable at `high`) or `acp-dispatch codex --model gpt-6-astra
  --kind frontier --effort high` (a read-only advisor by default), one at a
  time: codex's 5-hour window holds about one hard slice, and a second one
  is refused while the first one's estimated quota is reserved (class
  `inflight`, 2026-10-18). Fable is **not** a separate budget: it is a sublimit (at
  most 50%) of the shared Claude weekly and bills the 5-hour window too. Fable
  at `xhigh` needs djbclark's yes for that run (model-routing, *Routing
  policy* item 1).
- **Minimum needed spec for every sub-agent, unasked** (operator 2026-10-15):
  the goal is cost against code quality, not token count. Agent-tool
  sub-agents only at Haiku `low`, for a lookup, a classification or a reformat
  (Claude's own models bill the shared Claude/Fable pool); implementation, clear
  shape or not, goes through `acp-dispatch` to the everyday pools (agy
  `claude-opus-5-5 --effort high`, zcode `GLM-5.3 --effort high`, cursor
  `default`); Fable/astra (`high`) only for the rare frontier calls above.
  Delegate proactively so the session's own context stays small, start on
  the cheap eligible tier and escalate through `acp-dispatch reroute` on a
  verified failure (operator, 2026-10-18).
- **Multiple-choice calls inside a loop** (which pool, retry or stop, which
  tests first) need no effort tier at all when code can answer them. Push
  them into a script or a table (`route_agent.py`, exit codes) and keep the
  thinking for the open-ended steps. See model-routing, *Multiple-choice
  decisions are not reasoning*.
- **Switching** — always name the switch and why. An unexplained tier change
  reads as inconsistency.

## What actually dominates cost: prompt caching

Effort tiering is a real lever, but a smaller one than the thing underneath
it. Verified against
[code.claude.com/docs/en/costs](https://code.claude.com/docs/en/costs):

- **The whole conversation is re-sent on every request**, including each
  batch of tool results. Prompt caching means that history is re-read at the
  cached rate rather than full price — so a one-line question in a session
  that has been open all day still draws usage for the entire conversation.
- **Cache lifetime is one hour on a subscription**, dropping to five minutes
  once you are drawing on usage credits (and five minutes on API keys). The
  first message after a longer break misses the cache and reprocesses
  everything. `ENABLE_PROMPT_CACHING_1H=1` keeps the one-hour lifetime while
  on usage credits.
- **`/clear` costs nothing; `/compact` is itself a large request**, because
  it reads the conversation it summarises. When you want a fresh start rather
  than continuity, clear — do not compact out of habit. Since 2026-10-15
  compaction is automatic: `autoCompactWindow` is 300000 in
  `~/.claude/settings.json` (every model, every host; the PreCompact hook
  writes the Tier 1 checkpoint first), and `context_size_nudge.py` tells a
  herdr or Orca session to compact itself earlier at a natural boundary via
  `self-slash "/compact <focus>"`, or to run the `handoff` skill then
  `self-slash "/new"` on a topic change (it sends `/baton` into the fresh
  session itself, 2026-10-19). Do not ask the operator for either.
- **Subagents isolate verbose work.** Test runs, log processing and doc
  fetches keep their output in the subagent's context and return only a
  summary. This is why dispatch beats doing rote work inline, independent of
  tier.

Practical consequence for the rules above: the cheapest thing you can do is
usually not a lower tier, it is a **shorter conversation**. Clear between
unrelated tasks; a stale 400k-token context taxes every subsequent message
regardless of model.

One caveat, deliberately flagged: a widely-shared video claims that switching
model, changing effort, toggling fast mode, connecting an MCP server,
installing plugins, denying a tool, or upgrading Claude Code each invalidate
the cache outright. **That list is not in the official docs**, which describe
cache misses only in terms of the time-based lifetime. Treat it as unverified
— if it is true, mid-session switching is more expensive than it looks, so
prefer dispatching a subagent over re-tiering a long session, which is the
better move anyway.

## Context window, when you dispatch

Effort is how hard the model thinks. The context window is how much text it
can hold. Pick both when you send work out. This session still cannot change
its own window mid-turn; the lever is the dispatched call.

1. Ask for a bigger window when the slice must read a whole corpus or a long
   log (`--context 500k` or `1m`). Keep the default for a small edit, a
   classification, or a short diff. A bigger window bills more per token on
   some services (xAI long-context rates from a 200k prompt; Cursor input
   above 256k at 2×, and Fast at 3×; Copilot's long tier costs more AI
   credits) and can be slower.
2. Request it on the same command as the model and the effort. The model is
   applied first. `acp-run <agent> -C <dir> -p '<prompt>' --model M --effort low --context 500k`.
   `acp-dispatch` takes `--effort` and `--context` as first-class flags
   (checked with the model before the slice is written, stored on the job,
   kept by `resume`): `acp-dispatch <agent> --model M --kind <kind> --effort low --context 500k`.
   `--acp-arg` still forwards other flags; a dash-leading value needs
   `--acp-arg=--meta`.
3. Read stderr `acp-run: applied: model=... effort=... ctx=...` before you
   trust the run. `(unverified)` means that value could not be read back. A
   mismatch is failure class `config`, exit 1. A level or size the agent
   cannot take exits 2 and names the valid values. Codex takes any size up to
   the model's `max_context_window` (the effective window is 95% of it). hermes, agy, cline, qwen, opencode and crush have
   no window knob: pick a model whose catalog window is already big enough,
   or leave `--context` off. The table is `tools/acp-run/README.md`, section
   "Per-agent choices: vendor, model, effort, context (2026-10-15)".

## Related

Vendor choice, quota headroom, and which pools are idle:
[model-routing](../model-routing/SKILL.md) and `bin/route_agent.py`
(`route --kind judgment|code|bulk|research|mechanical|github`). Effort routing
picks the tier; that picks the vendor. Run both.
