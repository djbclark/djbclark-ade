# Orchestration practices: decide cheaply, reason expensively, verify centrally

Snapshot **2026-10-11**. The rules every orchestration skill here follows
(`bigteam`, `research`, `dialogue`, `model-routing`, `effort-routing`,
`ralph-tui-orchestration`). Each skill carries the short form of the rules it
needs and links here for the reasons and sources.

**Standing operator requirement:** every orchestration skill must be able to
dispatch to several TUIs, through ACP (`acp-dispatch` / `acp-run`) wherever the
agent has an ACP mode, and the per-CLI headless forms only where it has none
(muse) or as a fallback (`model-routing`, *Headless invocation*).

## 1. Two kinds of work in an agent loop

1. **Reasoning** has an open-ended answer: plan, write code, debug, adjudicate.
   It goes to the judgment tier (Claude, codex, agy's Claude/GPT pool).
2. **Deciding** picks from a short list the harness already holds: which pool,
   which kind, retry or reassign or stop, which notes go in a brief, which
   tests run first. These are multiple-choice questions.
   They should not get a frontier model writing a paragraph before it
   commits.¹

**Ladder for a decision, cheapest first:**

1. **Code.** A rule or a table: `route_agent.py plan`, `acp-dispatch`'s exit
   codes, `aiuse --available`'s exit 3, `git diff --name-only` to pick tests.
   Deterministic, free, and auditable. The reaction to a quota stop is code
   too (2026-10-18): `acp-dispatch` schedules the in-place resume of the same
   session itself (exit 1 `resume-scheduled`, the waiter waits through it);
   only a non-quota exit 3 is a re-task decision for the judgment tier.
2. **A typed decision model**, a call that returns a probability per option
   and no text. TypeSafe's Jev is one (the `typesafe-ai` skill; needs a
   TypeSafe API key, stored in `sudo-secretspec` as `TYPESAFE_API_KEY` since 2026-10-11, **in shadow mode only since 2026-10-11** (`bin/jev`, `docs/jev.md`)). Code reads
   the probability and applies a threshold. Never ask a model how confident
   it is; read the distribution.¹ ⁴
3. **A cheap text model** at low effort (haiku, a free pool), with a closed
   option list and a parser that rejects anything off the list.
4. **The judgment tier**, when the question is not really multiple choice,
   or the cheaper rung was unsure.

**Rules for every rung:**

1. **The harness writes the options.** Each option is something code knows
   how to act on. A model that writes its own option list puts you back to
   parsing free text.¹
2. **Thresholds by risk.**¹
   a. Cheap to undo (note selection, test order): act at about 0.55-0.65.
   b. A wrong answer costs a failed step the harness catches (routing,
      recovery): about 0.8.
   c. Hard to undo (delete, force-push, production config, migrations,
      removing a feature the operator built): no model decides alone; the
      operator, or the judgment tier plus a confirmation step.
3. **Below the threshold, route up**, never guess. Routing errors are
   asymmetric: a hard slice sent to a cheap worker costs a failed step and a
   retry; an easy slice sent up costs a little extra.¹
4. **Caps live in code, not in prompts.** "Retry at most 3 times" in a prompt
   is sometimes 30; a counter is not.¹ ³
5. **Shadow before switching.** Before a new decider acts, log its answer
   beside the current one, read only the disagreements, and set the
   threshold from them. Put every decider behind a flag that turns it off.¹
6. **Known weak spots of typed deciders:** arithmetic and counting, date
   comparison, literal reading of negations; do those in code.⁴

## 2. Context: give each worker only what it needs

1. **Always-load set:** the concurrency contract, security rules, the
   repo's non-negotiables. Never scored out.
2. **Select the rest per slice.** A brief carries the notes, files and
   findings that slice needs, not the whole `AGENTS.md` tree. Keep a floor
   (if nothing scores, include the top two) and **log what was left out**:
   when a slice goes wrong, first check whether the note that would have
   prevented it was dropped.¹
3. Context selection is the riskiest decision to automate, because a wrong
   drop fails silently.¹ (A reader's reply to the source thread.) Until a
   shadow log shows otherwise, the orchestrator picks a brief's notes itself.

## 3. Briefs: the spec is the multiplier

A vague brief makes parallel agents duplicate work, leave gaps, or misread
the task, and the ambiguity is copied into every slice.² ³ Every brief has:

1. **Objective:** one paragraph, what done looks like.
2. **Owned paths:** one owner per file (bigteam Step 2).
3. **Inputs:** the selected context from section 2, and where to look.
4. **Tool guidance:** which tools and sources fit (graft before grep, the
   KB before the web).²
5. **Output format:** the report shape, `CHANGED:` / `SKIPPED:` / `NOTES:`.
6. **Acceptance check:** the command or observation that proves it.
7. **Boundaries:** the concurrency contract, and what is out of scope.

## 4. Size the run to the work

1. **Scale slice count with complexity.** Anthropic's research system uses one
   agent with 3-10 tool calls for a simple lookup, 2-4 for a comparison, and
   more than 10 only for complex work with clearly divided responsibilities.
   Its common early failure was overinvesting in simple queries.²
2. **Cap the fan-out at what you can verify.** Verification, not generation,
   is the bottleneck; more agents mean more diffs to review.³ ⁵ A wave is the
   number of diffs the orchestrator can read properly before the next wave
   lands.
3. **One level of delegation.** Workers launch no agents; only the
   orchestrator dispatches.⁵
4. **Every dispatch passes the load gate before it starts** (`acp-dispatch` runs
   `load-watch admit --wait N`, default 1800 s, exit 75 when the machine is still too hot; operator 2026-10-19).
   The gate only decides whether to *start*: it never kills, throttles or slows running work.

## 5. Failure handling: kill criteria in code

1. **Classify the failure first**, from the exit code and stderr, not by
   rereading the whole log at frontier effort: quota or plan → the vendor's
   sibling pool, then re-route; tooling → another vendor; the work itself →
   the orchestrator looks; refused → another model or a reworded
   authorization context (`acp-dispatch`/`acp-run` already classify these).
2. **Three attempts per slice, then stop and report.** The first run plus two
   re-routes. A slice stuck on the same error after that goes to the operator
   with the evidence, not to a fourth vendor.³
3. **Never kill healthy running work** to re-route it: it is already paid
   for.

## 6. Checks: focused first, full suite before commit

1. After a wave, run the cheap checks first: lint and type-check on changed
   files, then the tests that cover the diff.¹
2. **The full suite still runs, once, before any commit.** Focused checks
   are an early warning, not a replacement.¹
3. A check hook on task completion (lint plus tests before a task counts as
   done) catches what a worker forgot.³

## 7. Measure, or the savings are a guess

1. Log, per slice: kind, vendor, model, tokens or cost (acp-run's summary
   line), attempts, and whether the diff passed review unchanged.
2. Re-read that log before changing a capability profile in
   `route_agent.py`; a profile change without evidence is a guess.
3. The cost math in source 1 is modelled, not measured; use your own before
   and after numbers.¹

## Sources

1. CyrilXBT, "Your coding agent is paying frontier prices for multiple choice
   questions", 2026-10-09,
   <https://x.com/cyrilXBT/status/2108693524900110515>, and the reply by
   @AILoreWeaver on note selection.
2. Anthropic, "How we built our multi-agent research system",
   <https://www.anthropic.com/engineering/multi-agent-research-system>.
3. Addy Osmani, "The Code Agent Orchestra", 2026-03-26,
   <https://addyosmani.com/blog/code-agent-orchestra/>.
4. Width.ai, "What Is Jev AI?",
   <https://www.width.ai/post/what-is-jev-ai-typesafe>, summarising
   TypeSafe's jev-1.13 jaggedness page,
   <https://docs.typesafe.ai/model-jaggedness/jev-1.13>.
5. Firecrawl, "Multi-Agent Orchestration With Codex",
   <https://www.firecrawl.dev/blog/codex-multi-agent-orchestration>.
6. Survey: "Dynamic Model Routing and Cascading for Efficient LLM
   Inference", <https://arxiv.org/html/2603.04445v2> (uncertainty-based
   routing and cascades, background for section 1).
