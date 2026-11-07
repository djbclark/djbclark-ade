# Orchestration practices: decide cheaply, reason expensively, verify centrally

Snapshot **2026-10-11**, re-based on Paseo **2026-11-07** (slim-down E11). The rules every orchestration skill here
follows (`fan-out`, `research`, `dialogue`, `model-routing`). Each skill carries the short form of the rules it needs
and links here for the reasons and sources.

**Standing operator requirement:** every orchestration skill can dispatch to several providers. Since 2026-10-31 (Paseo is
the only harness) every agent is a Paseo agent, and since 2026-11-06 `acp-dispatch` is a shim over `paseo run`: in process through the Agent tool or a Workflow, out of process through `paseo run` (directly,
or through `bin/acp-dispatch`, a `paseo run` shim kept for one cycle with its report, `.done`, record and exit-code
contract; Wave 6's follow-up PR removes it). The providers are claude, codex, cursor, antigravity, opencode, omp and
hermes (`paseo provider ls --json`); `skills/fan-out` is the how-to.

## 1. Two kinds of work in an agent loop

1. **Reasoning** has an open-ended answer: plan, write code, debug, adjudicate.
   It goes to the judgment tier (Claude, codex, antigravity's Claude/GPT pool).
2. **Deciding** picks from a short list the harness already holds: which pool,
   which kind, retry or reassign or stop, which notes go in a brief, which
   tests run first. These are multiple-choice questions.
   They should not get a frontier model writing a paragraph before it
   commits.¹

**Ladder for a decision, cheapest first:**

1. **Code.** A rule or a table: `route_agent.py plan`, the dispatch shim's exit
   codes (section 5), `aiuse --available`'s exit 3, `git diff --name-only` to pick tests.
   Deterministic, free, and auditable. The reaction to a quota stop is the
   provider's: Paseo's session-guard pauses at exhaustion and usage-auto-resume
   continues after the reset (the dispatcher's own auto-resume was retired 2026-11-06).
2. **A typed decision model**, a call that returns a probability per option
   and no text (TypeSafe's Jev was one; it ran in shadow mode only and was
   removed 2026-11-06). Code reads the probability and applies a threshold.
   Never ask a model how confident it is; read the distribution.¹ ⁴
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
2. **Owned paths:** one owner per file (fan-out section 1).
3. **Inputs:** the selected context from section 2, and where to look.
4. **Tool guidance:** which tools and sources fit (graft before grep, the
   KB before the web).²
5. **Output format:** the report shape, `CHANGED:` / `SKIPPED:` / `NOTES:`.
6. **Acceptance check:** the command or observation that proves it.
7. **Boundaries:** the concurrency contract, and what is out of scope.
8. **Names with ids (2026-10-23, from the load watcher):** wherever a brief, message or report names a Paseo
   workspace, give the name the GUI shows (`<topic>-pw`) and its id (`wks_…`); for an agent, its agent id too. A GUI
   rename makes a name alone unreliable, and an id alone is unreadable.
9. **The delivery footer** (`acp-dispatch footer --report PATH`, docs/dispatch-footer.md): where the report goes, the
   `.done` marker, and the last line `DONE`, `BLOCKED: …` or `NO-REPORT: …`.

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
4. **Every dispatch passes the load gate before it starts** (the shim runs `load-watch admit --wait N`, default
   1800 s, exit 75 when the machine is still too hot; operator 2026-10-19), then its frontier, in-flight and per-wave
   checks, which parallel launches re-check under a lock after writing their record. The gate only decides whether to
   *start*: it never kills, throttles or slows running work.
5. **Plan with the load in mind** (load watcher, 2026-10-23, after load reached 42-62 on 8 cores with swap at 90%
   from three concurrent local pytest runs plus three dispatches): check `load-watch admit --json` before a large
   fan-out; builds and tests only through `bg` or CI, never `BG_LOAD_WAIT=0`; **one local test run at a time**; no new
   local pytest or dispatch while load per core is 1.5 or more (`uptime`).
6. **Stagger sends to a working Claude agent** (PR 294, from the retired `helm` lead guide, 2026-11-06): one message
   at a time, each gated on the target going idle, sent in the background; Paseo replaces a Claude agent's current
   turn when a steer is declined (for example during compaction), and the relay shim refuses a running agent whose
   provider cannot steer. A send that timed out waiting sent nothing: retry next round.

## 5. Failure handling: kill criteria in code

1. **Classify the failure first**, from the exit code and stderr, not by
   rereading the whole log at frontier effort: quota or plan → the vendor's
   sibling pool, then re-route; tooling → another vendor; the work itself →
   the orchestrator looks; refused → another model or a reworded
   authorization context. The shim's exit codes (dispatch, `wait`, `check`): 0 report delivered and ending in
   `DONE`; 1 report present but unfinished, or still running; 2 usage or a refused launch; 3 no report; 4 `BLOCKED`
   (or a pending permission); 5 pool unavailable before launch, re-plan; 75 machine too hot, nothing launched;
   77 review-launch's tripwire; 124 timed out waiting. Exit 0 is still not success: verify the diff, the tests and the
   report's content.
2. **Three attempts per slice, then stop and report.** The first run plus two
   re-routes. A slice stuck on the same error after that goes to the operator
   with the evidence, not to a fourth vendor.³
3. **Never kill healthy running work** to re-route it: it is already paid
   for.
4. **Stop dependent mutations on failure (2026-10-25).** A tool result is not
   a successful command: inspect `exit_code` after every edit, commit and push.
   In a multi-step tool block, throw or return on a nonzero result before the
   next mutation; with Python use `subprocess.run(..., check=True)`. A refused
   edit or failed commit must never be followed by a push or a review brief
   claiming the edit landed. Match only your own changelog entry, since other
   agents may also have pending PR-number placeholders.
5. **Never block on a job longer than about 2 minutes unless the next step
   depends on its result (2026-11-02).** An agent sat 10+ minutes in a blocking
   `wait` on `gh pr checks --watch` with nothing depending on it, and the
   operator had to interrupt. **Why it is worse than idle: an agent inside a
   long blocking wait never goes idle, so it cannot receive any relayed
   message** (Paseo queues a text for a working target until it has been quiet
   for 2 s): it is deaf as well as silent. On 2026-11-02 the lead's messages sat queued
   for hours behind such waits. Do other work; if there is none, end the turn with a status line (what
   runs, where its log is, what to check next) and let the result wake you.
6. **Never wait on CI** (`gh pr checks --watch`, `gh run watch`). Report
   "CI running" with the run URL and stop: the lead reads CI, and its wait command is
   `gh pr checks PR --watch --required` (since 2026-11-06); a merge-ready decision needs no agent parked on it.
7. **One progress line per round in a fix-and-review loop**: the head sha and
   the finding count (`round 3: head 1a2b3c4, 2 findings`). A long serial
   loop that prints nothing looks the same as a hang to a human reading the
   pane.
8. **A reply that cannot be delivered because its target waits on a question
   or permission card is the operator's to unblock** (2026-11-02: a message
   waited 184 minutes behind a card). The relay shim refuses such a send
   (exit 2, not delivered); `paseo permit ls` shows the pending card, and the
   asks / questions-please plugins are the operator's inbox. Report the message as
   held behind a card and move on; do not retry or poll it.

## 5a. Messages between agents (AGENTS.md order 10, re-based 2026-11-06)

1. Send with `paseo send --json` or the relay shim `skills/session-finder/relay.py TARGET "text"` (until 2026-11-20).
   TARGET is an agent id or a unique shortId prefix, never a title.
2. **What counts as delivered**: a sourceless send (deadline, load-watch: no `$PASEO_AGENT_ID`) is delivered when
   `.status` reads `sent` or `completed` (shim exit 0). An agent's send is **accepted** (exit 5): Paseo queues every
   agent-to-agent message and reports no later delivery, so only the peer's `ack <your id>` proves it. Exit 2 is not
   delivered; `paseo send`'s own `$?` is never read as delivery (it exits 0 for every status).
3. Ask for the named ack (`--ack <your id>`) whenever delivery matters and always on first contact; read your own
   inbox for it; re-send when none arrives; report a peer you cannot reach to the operator.
4. A reply written in your own turn reaches nobody: answer a peer by sending to it. A slice's channel back is its
   report file, and `acp-dispatch tell RECORD MESSAGE` (an inbox entry plus a `paseo send`) reaches a running slice.

## 5b. Unattended issue → PR (from `docs/history/coding-factory.md`, 2026-09-21)

The factory question was answered then: the trigger is a small GitHub Actions workflow on a label, the coder is a
pool already paid for (Cursor Cloud through `bin/cursor-cloud`, or a local Paseo agent; the Copilot cloud agent was
an option until the 2026-11-06 pool audit found no Copilot plan), and the
gate is repository configuration. The gate exists since 2026-11-06 (PR-only master, the required `adversary-marker`
status, the Tests checks); the trigger is not built. A PR such a coder opens is outside input until the owner edits
its body (AGENTS.md, Trust).

## 6. Checks: focused first, full suite before commit

1. After a wave, run the cheap checks first: lint and type-check on changed
   files, then the tests that cover the diff.¹
2. **The full suite still runs, once, before any commit.** Focused checks
   are an early warning, not a replacement.¹
3. A check hook on task completion (lint plus tests before a task counts as
   done) catches what a worker forgot.³
4. **Reuse CI and its watcher (2026-10-25).** Before manually dispatching a
   workflow, check its triggers and existing runs for this branch and head.
   When opening a PR will trigger the required checks, finish the pre-PR
   review and use that automatic run rather than dispatching the same suite
   first. Keep one watcher for the chosen run; record its PID and run ID so a
   successor can reuse it. If an older watcher is redundant, stop that local
   watcher only; cancelling an already running workflow requires the
   operator's approval. Repeat tests only for changed code, failures or an
   unresolved validation concern.

## 7. Measure, or the savings are a guess

1. Log, per slice: kind, vendor, model, tokens or cost (`acp-dispatch outcome`, the provider's usage), attempts, and
   whether the diff passed review unchanged.
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
