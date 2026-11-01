# Queue — accepted, not started

Work the operator has explicitly queued. Newest first. Items leave this file
when they ship (into the relevant doc) or when they're dropped (say why).

Triage 2026-11-01 (proposal, `queue-triage` branch): entries are checked against `docs/paseo-only-rearchitecture.md`
(its phases D1-D7 are named below). DONE and OBSOLETE entries, and the closed halves of mixed ones, moved verbatim to
[history/queue-2026-10.md](history/queue-2026-10.md); a shortened entry keeps only what is still true, and its full
text is in git at `a2c9ee9b`. Per D7 this file is rewritten again when the plan lands.

## A. Carry-over and phase-bound work

## Build "model tiers as data" after D1 (djbclark via `/steps`, 2026-10-31)

Design: [model-tiers-design.md](model-tiers-design.md) (merged in PR 188; design only). It moves every hard-coded model name and tier rule into `config/model-tiers.toml` with
a `bin/model-tiers promote` command; neither exists yet. Start after D1; re-check the design's inventory against the code first, since routing moves to Paseo in later phases.

## Dynamic self-adjustment of model version and effort by token efficiency

Queued 2026-08-23, not started; sibling of the model tiers item. A session raises and lowers its own tier and effort by observed token efficiency. Open questions: the
efficiency signal; whether a session can change its own model mid-flight or only dispatch to sub-agents at chosen tiers; what prevents oscillation and silent quality loss.
Start advisory-only ("this stretch is mechanical, drop to Sonnet"), after the model tiers item. The `effort-routing` skill is the manual version today.

## `paseo-bypass-watch` test gaps from adversary round 4 (PR 121, 306039a; deferred 2026-10-29)

Coverage gaps only (report `~/.local/state/bigteam/adhoc-2026-10-29/watch-adv4-report.md`). D5 simplifies this watcher: fold these into that PR, or drop them if the watcher goes.

1. **B1, low.** Add `"Auto"`, `"DEFAULT"` and `"autoSomething"` to the parametrize list of `test_only_default_and_auto_modes_are_acted_on` in `tests/test_paseo_bypass_watch.py:216`, expecting no flip.
2. **B3, very low.** Mutant `if after not in (TARGET_MODE, "auto")` (`bin/paseo-bypass-watch` ~283) survives; add a test where the set "succeeds" but the seat still reads `auto`.

Also deferred: installing a launchd job for the watcher. Ask again when the tests have shipped, or when a UI-opened claude seat is seen unflipped.

## Sibling `RecursionError` readers: governor and quota-guard (PR 98, 1f56db3)

`guard_level` in `bin/claude-fleet-governor` and `load_state` in `bin/claude-quota-guard` still lack the `RecursionError` handling PR 98 gave `ade_gates.read_guard_state`
(`rg RecursionError` finds nothing in either, 2026-11-01). Optionally have the hook call `g.read_guard_state()`. Failing tests first (force `RecursionError` as PR 98's test
does), one adversary round, CHANGELOG `Fixed`. A dispatched slice job `recursion-readers` may already cover this: check `~/.local/state/bigteam/*/jobs/` first.

## Context visibility in Paseo and compact/handoff discipline (djbclark via session ab4e97be, 2026-10-27)

Partly built since: context-watch (PR 107), context nudges (PRs 108, 114, 117, 127). Still open: (a) examine `~/.claude/state/context-nudges.json` against the 35 sessions that peaked at
200-270k and the two failure classes (handoff "gave up", failed successor launches); (b) dupe-search, then comment on getpaseo/paseo#4949 (the meter ignores `autoCompactWindow`, 300000);
(c) talk to djbclark with numbered options before building a live per-agent readout or tighter nudge tiers; ask before touching `~/.claude/settings.json`. The 2026-10-27 measurements and brief are in the
base-commit text (`~/.local/state/ade-briefs/context-visibility-and-handoff-audit-2026-10-27.md`). Phase: D6 (context-watch is harness-neutral, C1 KEEP).

## Orchestration rules from the load watcher (load-watch agent 96a17744, 2026-10-23): the two doc rules left

Phase D7 (the practices doc is rewritten there). Put both into `docs/orchestration-practices.md` and the brief template in `skills/bigteam/SKILL.md` (or its D5 replacement):
1. Name a Paseo workspace by its GUI name AND its id (`wks_...`), and an agent by its id too.
2. Load-watch in planning: check `load-watch admit --json` before a large fan-out; builds and tests only through `bg` or CI, never `BG_LOAD_WAIT=0`; one test run at a time; no new
   local pytest or dispatch while load per core >= 1.5 (`uptime`). Each ships its CHANGELOG line with its own PR.

## `bin/load-watch` `send_to` has the relay's round-1 exposure (adversary on PR #25, 2026-10-20)

Phase D6 (notifiers move to `paseo send`). The `--` half is done (86b288b). Open: the label/gate half and lows R1-R5; drop the relay-shaped fixes when delivery moves to `paseo send`. The
related load-gate follow-ups (PR 7 final pass, items 3a-d of the 2026-10-20 reviews) ride with this work.

## ade-git-guard (PR 59): what is left

`docs/git-guard.md` ("Integration status") still says nothing calls the guard in a live session. The O2 design is adopted (PR 59). Open, in order:
1. **Next adversary round, with a NEW brief** (O2 plan step 5): ref writes that reach disk without a `reference-transaction` (`packed-refs` edit, `git replace`, `git notes`, per-worktree `symbolic-ref`); hook disabling through config the shim does not see
   (`HOME`/`XDG_CONFIG_HOME`, `GIT_CONFIG_SYSTEM`, a hand-written `core.hooksPath`); no-ref harms in a foreign tree; false refusals of the owner's ordinary work.
2. **Upstream report** (AGENTS.md rule 8): `git branch -m|-M|-c|-C` destinations are not reported to `reference-transaction` (git 2.56, files backend). Dupe-search git's list, draft a minimal reproduction, file it.
3. **Config-based hooks (git 2.54+)**: measure FIRST whether a `hook.reference-transaction.command` runs alongside the file hook and whether `-c hook.*.enabled=false` beats an env-injected one.
4. **Wire the call sites**: W2 (cow-pasture) is retired by B4; W3 (`acp-dispatch` exports `ADE_CLAIM_ID`, installs the hooks at claim time) and W4 (`acp-run` puts `libexec/agent-bin` first on PATH) move to the Paseo launch path (D5).
   Enforcement stages from standing order 9: S1 launcher claim, S2 `ade-git-guard` refuses `add`/`commit` in shared checkouts, S3 CHANGELOG fragments (PR 190, open), S4 the six-case pilot. Check Hermes and Paseo workspaces before relying on hooks.
5. **`git replay`, `git history`, `git refs migrate`** (git 2.54-2.56): re-measure the hook on each. 6. **Output files into an unclaimed checkout** (`stash show --output`, `format-patch -o`) is an accepted residual; close it with a slim shim rule only if djbclark asks.

## Follow-ups: pr-wait, bm-lint, ade-scan-state, PR 31 governor, PRs 29/30 (all low, carry-over)

All tools are harness-neutral (C1 KEEP). One small PR each when the tool is next touched; originals in the base commit and, for the split entries, in `history/queue-2026-10.md`.

1. **pr-wait MEDIUM**: `push_stamp` ignores `head_branch`, so a sha pushed earlier to another ref dates the push too early; then the LOWs (clock skew in the 120 s window, lost request-state file). **bm-lint LOW**: a lone surrogate in a project path aborts with `UnicodeEncodeError` (`bin/bm-lint:418-425`); the partial-read headline could show the skipped count. The weekly `bm-lint` hook-up goes to the D6 notifier.
2. **ade-scan-state** (PRs 39, 47, 54): LOWs about test assertions per note, the `--separate-git-dir` CHANGELOG file list, and the accepted `cp -rL` amplification in canonical mode.
3. **PR 31 governor**: gate for Agent-tool sub-agents (`claude/hooks/frontier_agent_gate.py` has no sonnet rewrite, so a model change by daemon RPC never reaches them); the seven downshifted agents' restore record; the LOWs 4a-f (window-stale exit 10 writes no state, unpinned mutants, `load_snapshots` OverflowError).
4. **Routing (PR 73 round 5)**: the aiuse snapshot-file fallback admits on a file up to 25 minutes old when aiuse itself fails; make it fail closed. A hanging aiuse can cost three timeouts per foreground dispatch.
5. **PRs 29/30 residual lows** (items 5-9 of the 2026-10-23 follow-up entry): fold into the sibling `RecursionError` PR above.
6. **Delete the credential vault `~/.local/state/ade/credential-bak/` after 2026-11-19** (owner djbclark; adversary round 8 on PR 16).

## Make better use of Basic Memory (djbclark, 2026-10-23)

Q1 (the security upgrade to v0.24.1) is DONE; bm-lint shipped (PR 55). djbclark accepted all eight recommendations 2026-10-23; the rest is unbuilt (`claude/hooks/bm_recall.py` is absent). Remaining rulings, in order:
2. shadow our own `claude/hooks/bm_recall.py` (titles only, 400 tokens at most) against `bm hook session-start` for a week, keep the cheaper one that passes the recall evaluation, never both live;
3. move the 193 per-project auto-memory files into `site-private/memory/projects/<slug>/` with symlinks back; 4. re-enable Hermes's Basic Memory provider with `capture_per_turn: false` (drop if Hermes-as-harness is retired);
5. remove the 8 empty `~/agent-memory/*` projects, archive the 3 dead `basic-memory/` subtrees; 6. handoffs older than 30 days go to `handoffs/archive/` (D7 moves handoffs to `docs/history/` anyway);
7. backfill `type:` on the 321 prefixed root notes in one reversible script commit; 8. a `ruling` only for something djbclark said (quoted, dated), agents' own choices are `decision` notes with a relation to it. Report: `~/.local/state/bigteam/adhoc-2026-10-23/design-basicmemory-report.md`.

## Make full use of the podman, kev, laya and hyades-docker microVMs (djbclark, 2026-10-23)

Plan E5 (Jev-like judges share one Hyades microVM); nothing is built. 1. Inventory first (one read-only scout slice) into a new `docs/microvms.md`: what each gives, limits (disk, toolchains, the TSI loopback bug and its shim), cost, who can reach it, restart behaviour.
2. Then route to them: heavy tests and builds through `forgejo-ci` (`load-watch ci decide DIR ci "CI CMD"`), adversary probes that run code (the round-18 probe that ran the backup tool against the real HOME is what a disposable microVM prevents), `--perm deny` reviews of untrusted repos, and kev/laya as `jevlike` gates at the sites `docs/jev.md` lists. The Hyades runner is shared: never fan out.

## SkillOpt-Sleep phase 2: pluggable transcript sources and backends

Queued 2026-10-12. zcode, agy and crush adapters shipped (crush was later removed). Remaining: (1) the upstream PR offered in microsoft/SkillOpt#314 once upstream answers (per-source checkpoint is #312); (2) adapters for Hermes, grok, muse, cline and acp-dispatch job reports, each with the replay-session filter; (3) add them to `bin/skillopt-night`'s source loop (the nightly run moves to a Paseo schedule, F2). Drop the runner's codex shim when upstream PR 282 merges.

## Research checker: namespace-aware citations across runs

Queued 2026-10-10, not started. `skills/research/scripts/research_check.py claims` checks only that a cited evidence id exists in the run's own ledger, so an id from another run passes while pointing at the wrong source (GPT-6 Astra's amendment A8, Grok 4.7's rule R-src-5; `spec/ai-heaven/notes/grok-phase4-verdicts.md`). Build a subcommand that resolves relative links into another run's report by file AND id.

## Cloud-agent readiness: Codex Cloud environment (ruling 2026-10-19)

The Cursor half is DONE (`bin/cursor-cloud`, PRs 5 and 8, the `acp-dispatch` place and `route_agent.py` service). Open: environment `ccarenv_02c6721d65dc4191b57a76a84baa4121` exists, but codex-cli cannot see new-style environments (openai/codex#50182, #51585; the GitHub connector answers "create an environment" for non-review mentions). Re-probe `codex cloud exec --env <ID> --branch <b> "<task>"` after each codex release; then add a `codex-cloud` place to the router (§11.5 rule 4). `@codex review` on a PR works today.

## The Claude API credits (omp): finish the wiring (decided 2026-10-19). Deadline 2026-11-08

Credits ($95.57 of $200 on 2026-10-19) EXPIRE 2026-11-08. Done: the omp login, the per-run gate lifted, aiuse row (8a9dc43). Still to confirm: a slice's cost lands on the credits pool in `aiuse`; the `api-only` callers (`bin/failover.py` Claude SDK route, a verdict classifier) draw these credits and ask `route_agent.py route --kind api-only` for the balance first. Else let them lapse.

## Paseo Telegram plugin replaces Hermes's relay (SF-Q16, 2026-10-19). Phase D2

Plan F1 installs `paseo-telegram`; D2 includes the test on Paseo 0.14 (the old "registry needs Paseo <0.12" block is stale). Then re-point `hermes-ping`, the approval buttons and the home rule, keeping Hermes's relay as the rollback until D6.

## Ralph on OpenCode v2: postponed (operator, 2026-10-13)

Parked: "postpone all ralph work". Revisit only on djbclark's word.

## Re-check Context7 use (on or after 2026-10-24, now due)

Count `mcp__claude_ai_Context7__` calls in `~/.claude/projects/*/*.jsonl` since 2026-10-10; if still about 0, ask djbclark whether to block it too (Firecrawl is the costly one, `docs/disabled-skills.md`).

## Ingest web-interface AI conversations into the memory system

Queued 2026-08-23, not started. Pick one source first (the ChatGPT export) and write the importer into the memory store; the full requirements are in the base-commit text.

## Token-cost hygiene (from video analysis, 2026-08-24). Phase D7

Live item: keep instruction files lean (AGENTS.md is far past the 200-line guidance; the D7 rewrite is the place). One-off checks still open: run `/usage` and `/context` to measure skills and MCP servers, `/insights`, consider `ENABLE_PROMPT_CACHING_1H=1`, prefer `/clear` over `/compact` between unrelated tasks. Not adopted: output-token scaffolds (caveman, "be brief").

## Also outstanding (raised, not formally queued)

Still true after the triage (the Orca parity gaps and the `cow-pasture --force` bug are retired with their tools):
1. Restart any `hindsight` MCP server started before 2026-08-23 20:00 (it caches its bank); confirm-then-delete the leftover banks `hermes-telegram` (5 docs) and `herdr-shared` (1 doc).
2. `just ops-memory-sync` failed for site-djbclark (`docs/plans/memory-architecture-v2.md` unreleased past ops-v1.3.26): re-probe; needs a release cut or a revert (site-djbclark code: ask first).
3. File the two upstream issue drafts in [upstream-issues.md](upstream-issues.md) (operator decision: they go to third-party trackers).
4. Type `skills/session-finder/launch.py` (52 pre-existing basedpyright errors; decided 2026-10-09 to leave; a separate pass).

## Keep every machine current: the two items left

ade-update (PR 20) and the CHANGELOG shipped. Left: a daily `--check` timer (launchd here, systemd user unit on Linux) that writes a notice when the checkout is behind; and the `v0.1.0` tag with `Unreleased` moved under it so `ade update` has a delta to print (CHANGELOG fragments, PR 190, are open and change the CHANGELOG header).

## B. Awaiting djbclark (ASK)

Each needs a decision before any work (the triage report's section B lists the same questions).

1. **Research leftovers (web prior art, Python over bash, Kiro/LSP, Cerevisor; 2026-10-25).** The shadow hook `claude/hooks/prior_art_nudge.py` was built (PR 85, not installed live); its move to an advisory nudge waited on E1's numbers. Do you rule on the rest, or drop the entry? Report: `~/.local/state/bigteam/adhoc-2026-10-25/research-web-python-lsp-report.md`.
2. **Drop the brew Paseo and run our fork (2026-10-24, "ASK FIRST, it is disruptive").** With F3 using the vps-primary daemon, do you still want the desktop install replaced by our fork, with its Gatekeeper and upgrade cost?
3. **Phase 0 scan of bigteam and the Orca checkouts (2026-10-20, PR 27 built the tool).** Where do the 41 unreferenced bigteam report sets go; host or bundle `~/src/one-offs` (37 commits, no remote); push or bundle the branches with commits on no origin branch (`docs/ade-everywhere-phase0-scan-2026-10-20.md` §3.2)? The 54.5 GiB `hm-promo-rehearsal/` scratch is a later cleanup call.
4. **ADE-everywhere Phase 0 preserve and classify (2026-10-20).** `ade-backup-stores` shipped (PR 24); should it run on a schedule, with what retention? (The scan LOWs in that entry are long and low value: dropped from the queue, text in the base commit.)
5. **Buy a Jev plan before the factory's merge gate goes live (SF-Q10).** `bin/jev` is shadow-only; do you buy a plan (`TYPESAFE_API_KEY` via `sudo-secretspec`), or let the E5 Hyades-microVM judges replace it?
6. **Telegram for 2fado, Herald and agent web searches: talk first (2026-10-25).** Does this still stand now that F1 picked `paseo-telegram`?
7. **Software factory, Phase F (decided 2026-10-19).** Does the unattended issue-to-PR-to-auto-merge factory (`docs/coding-factory.md`, no `bin/factory` yet) survive the Paseo-only plan?
8. **S1 Phase B, Hindsight adapters (2026-08-23).** `site-djbclark/bin/hindsight_s1.py` landed; the Claude transcript tail adapter stops the loss of GC'd transcripts, the Hermes sink item depends on Hermes-as-harness. Continue, or retire with Hermes?
9. **Review the Copilot subscription ($29/mo).** Open PR 207 adds a Copilot use-it-up exception to the routing policy; keep the plan?
10. **tuios (2026-10-24, "do it LAST").** Retired with herdr (A1/A8), except the plan's own "modified tuios?" DECIDE: is that alive?
