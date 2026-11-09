# Queue — carried work, closed items, done items

Triaged 2026-11-07 by the slim-down (E11; `docs/slim/PLAN.md` J5: the queue stays a doc). Each entry is one line: what,
why it is still open (or how it closed), where it lives now. **The full text of every entry before the triage is in git
history**: `git show pre-slim-2026-11-06:docs/queue.md` (2,114 lines). New work is queued
under **Carried**, newest first, one line each; an item leaves when it ships (into its doc) or is dropped (say why).

## Stale

1. **CONFLICTING master-bottom PRs** (2026-11-10): eight open PRs conflict with `master` (#194, #208, #227, #231, #256, #269, #270, #290); close/rebase/supersede guidance and the #290 vs #471 recovery split live in `docs/history/conflicting-pr-hygiene-2026-11-10.md`.

## Carried

1. **Wave 6 shim deletion** (2026-11-09; status 2026-11-10): remove `relay.py`, `acp-dispatch` and `acp-run` after one live cycle (soft deadline 2026-11-20); C3 outside files migrated or waived; keep `review-launch`. Checklist: `docs/slim/wave6-follow-up.md`. C3 `--dry-run` FIXTURE path ready/tightened; `--inventory` lists gated shim callers with `gate_exits`; Mac live cycle still blocked (`mac_not_live` on FIXTURE/LINUX-SAFE). Tools: `bin/wave6-delete-check` (`--dry-run` = FIXTURE shape; `--inventory` = §A caller list) + `bin/wave6-mac-proof-capture` (`--live` Darwin / `--linux-safe` partial; labeled FIXTURE proofs under `tests/fixtures/wave6-mac-proofs/` until replaced). Operator must supply live Mac proofs + C3 migrate/waive pastes. (Absorbs the deletion half of former Carried 33.)
2. **Issue 284 follow-ups** (2026-11-04): the goal / verify-until-pass loop (evaluate the Paseo plugin `37chengshan/goal-mode`
   first), Codex and opencode wiring of `secret_read_gate.py` and `post-edit-check --hook`, a Claude `filesystem.denyRead`
   live trial (template/render landed 2026-11-09 in `agents/claude/settings.json.tmpl` via `bin/render-secret-deny`;
   applying denyRead and enabling `sandbox.enabled` in live `~/.claude/settings.json` still needs the operator's yes,
   order 11), a Codex deny-read profile (openai/codex#22179), whether `hook-deadline` passes exit 2 through, applying the
   template's new hook and deny entries live (operator's yes, order 11), the gate's slow-glob budget LOW, and
   `bin/instruction-lint` over `~/AGENTS.md` and `home-agents.mdc`. Lives in `docs/secret-deny.md`, `docs/post-edit-check.md`.
3. **Interruption recovery** (issue 278, 2026-11-04): D1 provider and capture probes, G1 persistence and failure-injection
   gates, a canary, legacy record recovery; PR 290 (`ade-recovery`) parked until Paseo's native resume is measured (PLAN J6,
   J9). Lives in `docs/checkpoint.md`.
4. **Context visibility in Paseo** (2026-10-27): Paseo Desktop's meter divides by the 1M manifest window and ignores
   `autoCompactWindow` (getpaseo/paseo#4949); examine the nudge state, search prior art, then offer the operator a live
   per-agent readout or tighter nudge tiers. The self-slash half closed with self-slash (E4). Lives in
   `docs/context-hygiene.md`, `bin/context-watch`.
5. **Model tiers as data** (2026-10-31): one `config/model-tiers.toml` and a `promote` command so a new top model is one
   data change; re-check the design's inventory against E7's `route_agent.py` and `config/routing.toml [lead]` first.
   Design: `docs/history/model-tiers-design.md`.
6. **Push on completion** (load-watch agent 96a17744, 2026-10-23): a delegated slice tells its requester "done: title,
   status, report" when its turn ends, instead of waiters polling; candidates are Paseo's `tell-agent` plugin (J6) or the
   dispatch footer. Lives in `docs/orchestration-practices.md`.
7. **ade-git-guard's open items** (2026-10-25 onward; W2–W4 landed 2026-11-10): `plugins/ade-claim/` scaffolds
   landed (#336 worktree claim, #355 `ADE_CLAIM_ID` + bind-owner, #357 `libexec/agent-bin` on PATH, #381
   release-on-archive + install-on-create). Still open: live claim creation on the Mac (`paseo plugin install` +
   observe/`new --ttl` hook path; E8 F4), the O2 redesign's residual (writes outside the caller's claimed workspace,
   with failing tests and an adversary round), the six-case enforcement pilot (S4) before any hard refusal, and the
   optional narrowing E8 declined (F3: a security decision for the operator). Lives in `docs/git-guard.md`.
8. **Drop the brew Paseo for our fork** (2026-10-24): disruptive, **ask the operator first**; after the connected-hosts work.
9. **Paseo connected hosts** (2026-10-24): connect vps-primary (user `djbclark`) after a quiesced Paseo upgrade.
10. **Paseo in-place model change upstream** (2026-10-23): `docs/upstream-issues.md` entry 17 (`paseo agent model <id>
   <model>`), so `bin/paseo-set-model` (used by `route_agent.py substrate --apply`) can go.
11. **Live `~/.claude/settings.json` lacks the `context_size_nudge.py` registration** the template has (2026-10-23):
    the operator's edit (C2 batch, `docs/slim/log.md`). Detector: `ade-install doctor` /
    `just install-doctor` (2026-11-09); apply remains hand-edit of the live file (order 11).
12. **Codex threads left unresolved on merged PRs** (2026-10-23): read each against its PR and fix what is real (review
    rule 9 is advisory since J8).
13. **Templates, Phase 1** (2026-10-20): declare the `TODO_*` secret names, give each template field a home, make the
    Codex and Claude templates merges, and the `ade-template-check` scanner LOWs (adversary round 3 on PR 23). Lives in
    `agents/README.md`.
14. **Delete the credential vault after 2026-11-19** (owner djbclark): `~/.local/state/ade/credential-bak/`,
    nothing reads it. `ade-install doctor` WARNs within 14 days before that date and FAILs on/after it while
    the vault still exists (never deletes; operator yes still required). Lives in `bin/ade_install.py`.
15. **`ade-backup-stores` LOWs and schedule** (PR 24 rounds 4-22): a launchd schedule, a generation retention,
    `O_NOFOLLOW` walks, the unscrubbed `.part`; and scrub or delete the first generation (it predates the credential
    scrub). Lives in `bin/ade-backup-stores`.
16. **First release tag and `ade-update` LOWs** (2026-10-20; plist scaffold 2026-11-09; Linux systemd path #374):
    tag once CI, rule 10 and `ade-update` are settled (the final slim-down PR is a natural point). Daily `--check`
    plist is `config/launchd/com.djbclark.ade-update-check.plist` (operator still runs `ade-sched install`); Linux
    systemd unit path landed (#374); `just update` / `just doctor` / `just install` aliases exist on the
    transitional catalog. Mac schedule install + first release tag remain.
17. **Codex Cloud environment** (2026-10-19): blocked upstream (openai/codex#50182, #51585); re-probe after each
    codex-cli release.
18. **Claude API credits through Pi** (2026-11-08): the API check was billing-blocked; re-check only after funding
    and explicit pool acceptance, then verify its aiuse attribution. Claude subscription quota is separate; archived
    omp is never a fallback. Lives in `~/src/aiuse`, `skills/model-routing` C.
19. **Paseo Telegram plugin as the phone surface** (SF-Q16, 2026-10-19): blocked on a release compatible with the
    current daemon; then re-point `hermes-ping` and the approval buttons, Hermes's relay as the rollback. The 2fado
    Telegram fallback (2026-10-25) waits for this.
20. **Basic Memory** (2026-10-23): seven of the eight accepted recommendations (Q1 is done); `bin/bm-lint`'s two LOWs
    (PR 55) and its weekly hook-up in site-djbclark `fleet-watch` (offer the parked patch to the operator).
21. **The podman, kev, laya and hyades-docker microVMs** (2026-10-23): inventory first, into a new `docs/microvms.md`.
22. **Phase 0 data decisions** (2026-10-20): where the 41 unreferenced bigteam report sets go, host or bundle
    `~/src/one-offs`, push or bundle branches on no origin. The scanner is gone (E2); its findings are in
    `docs/history/ade-everywhere-phase0-scan-2026-10-20.md`.
23. **Research checker: namespace-aware citations across runs** (2026-10-10): a bare evidence id from another run passes
    `research_check.py claims`. Lives in `skills/research`.
24. **Ingest web-interface AI conversations** (Gemini, Grok web; 2026-08-23) into the memory system: not started.
25. **Dynamic model and effort adjustment by token efficiency** (2026-08-23): not started; the Jev effort nudge that
    approached it was deleted (E2). Lives in `skills/model-routing` B.
26. **S1 Phase B adapters** (hindsight, 2026-08-23; status 2026-11-10): the Claude tail and checkpoint
    adapter onward; site-djbclark's `bin/hindsight_s1.py` (order 11). Docs/status open as #478
    (`docs/history/s1-phaseb-status-2026-11-10.md`). Drop or grant after an operator Phase-B decision under
    the Pi-only ruling.
27. **jj (Jujutsu)** (2026-08-23): a larger, separate bet than the retired cow pastures; not started.
28. **Loopback shim by default on forgejo.mit.edu, then ask SIPB** (2026-10-14): steps 1, 4, 5, 6 done; the ticket is
    left. Lives in `~/src/loopback-port-shim`.
29. **Leftovers from 2026-08-23**: confirm-then-delete the hindsight banks `hermes-telegram` and `herdr-shared`; site-djbclark's
    failing `just ops-memory-sync`; file the upstream drafts in `docs/upstream-issues.md` (operator decision).
30. **Re-check Context7 use** (due 2026-10-24): count its calls in the transcripts; if still about zero, ask whether to
    block it (the 2026-10-10 numbers: `docs/history/disabled-skills.md`).
31. **Keep the instruction files lean** (2026-08-24 cost review): Claude's docs advise under 200 lines; AGENTS.md is
    338 lines after the E11 rewrite (2026-11-07), the review rules being most of it.
32. **`bg` registers its own deadline** (2026-11-01): site-public-djbclark `bin/bg`, waits for the operator's yes (order 11).
33. **Two test LOWs from the 2026-10-23 rework-2 PRs**: `tests/test_bin_modes.py`'s docstring says "outside tests/" while
    the code exempts a `tests/` directory at any depth (PR 32 round 6); no test pins that `xhigh` and `max` are accepted as
    `[lead]` effort values (PR 33 round 2).
34. **Slim-down leftovers after Wave 6 deletion** (2026-11-07; deletion itself is Carried 1 / `docs/slim/wave6-follow-up.md`): port `skills/loose`'s
    upstream-issue reader off `acp-run --perm deny`; aiuse's acp-run
    readers (`src/aiuse/collectors/acp_usage.py`); the shim does not apply the Argon `fallback_block` at dispatch (E7 E5);
    `routing-recalibrate` as a Paseo schedule if wanted
    (E5); upstream Paseo filings (a codex read-only mode, a quota-pause primitive, a workspace-claim primitive).
35. **`bin/review-pr` and `gh pr checks --watch` register no deadline of their own** (2026-11-07, W3 docs critic): run them under `deadline run` until one of them registers itself (`docs/deadline.md` Known gaps).
36. **One-step install and automatic updates on a new machine, Mac and Linux** (operator, 2026-11-07): an easy way to install
    djbclark-ade with all its dependencies and TUIs (Paseo and its providers' CLIs, the modern-CLI tools, `graft`, `aiuse`,
    skills linked by `skill-everywhere`), and an automatic way to keep it and every dependency current (software tracks
    its latest release, order 8). Start from what exists: `bin/ade-update` (this checkout only), `bin/ade-sched` for the
    schedule, site-djbclark's `skills/setup-modern-cli`, and the decided but unbuilt proposal `docs/history/ade-everywhere-proposal.md`
    (2026-10-20, pre-slim: re-base it on Paseo and the slim-down's tool list). Widened the same day to GitHub setup for a new
    user (the `ade-merge-gate` App), prompt-injection hardening on demand with a daily drift check, one config file
    (`config/ade.toml`), a justfile entry point, and browser-only steps through Grok Bot: the plan is `docs/setup-plan.md`.
    Later operator additions (2026-11-07): S4b manages ADE-owned jobs and checks other owners without taking them over;
    residual (2026-11-10): inventory + `ade-sched list`/`diff` + doctor drift landed (never unload foreign); full reconcile still open;
    S5a originally accompanied setup, but security implementation is deferred by the 2026-11-08 operator ruling;
    S9 plans cloud-agent communication last, after signing and the earlier sections, and builds only with headroom
    (design slice: `docs/s9-cloud-paseo.md`, 2026-11-10 — prerequisites, non-goals, paper phases; no live wiring).
    Overall and local coordination now share the local lead.

37. **Pi-only third-party client** (operator, 2026-11-08): migration and archive-only history search shipped;
    omp/OpenCode/Crush are archived, never fallbacks. Dynamic defaults use explicit per-pool acceptance and
    task boundaries (`docs/pi-defaults.md`); normal startup and an unpinned live request passed after activation.
    Restored Grok subscription access (Pi and vendor ACP) and Antigravity Pi passed basic tool checks
    (`docs/pi-services.md`); Grok uses the cancelled plan's remaining allowance and stays manual-only.
    Machine-readable gate: `config/pi-pool-acceptance.toml` + `bin/ade-pi-pools check` (Cursor/Z.ai accepted
    2026-11-08; Grok/Antigravity/SIPB/Go still `accepted=false` until the operator flips them after
    continuation/quota/identity acceptance). Claude API credits remain billing-blocked, separate from the
    vendor subscription. Security implementation and SIPB reliability work are deferred; prior evidence
    remains in `docs/tui-security-and-pi-migration.md`.

## Closed by the slim-down (2026-11-06/07; the slice that closed it)

1. relay: card-blocked records fail fast (2026-10-31): the outbox is gone; the shim fails closed on a target with a pending permission (E3).
2. relay.py status, stuck-queue visibility, the ack-staleness addendum H1-H5 and housekeeping (2026-10-31): the deferred records, `--status`, `--sweep` and expectations are gone (E3).
3. Verified peer messaging and its round 2 (2026-10-25): order 10 re-based on `paseo send` and the named ack; the expectation ledger and first-contact footer are gone (E3).
4. Research: relay and self-slash blocking on picklists (2026-10-28): self-slash is gone (E4); the shim refuses a busy target that cannot steer (E3).
5. Follow-ups after PRs 73 and 74, relay deferred send (PR 57), the pane route lows, Paseo agents in fleet.py and relay.py, the `hermes` route: relay.py's routes and fleet.py are gone (E3).
6. Orchestration rules from the load watcher (2026-10-23): name a workspace by name and id, and the load-planning rules, are in `docs/orchestration-practices.md` (E11); finding a peer is `paseo ls` (E3); push on completion is carried (item 5).
7. `paseo-bypass-watch` launchd install (2026-10-29): the tool is gone; `paseo agent mode ID bypass` by hand (E4).
8. Paseo tabs, `-pt` naming, autorename for tabs, rename history (2026-10-23): naming in `docs/workspace-layout.md`; autorename is gone, renames are `paseo agent update --name` (E4).
9. Paseo workspace names after a handoff (2026-10-20): a successor starts with `paseo run --title` (E4).
10. self-slash cannot drive omp (2026-10-13): self-slash is gone (E4).
11. `bin/load-watch` `send_to` exposure (2026-10-20): load-watch sends with `paseo send --no-wait --json` and reads `.status` (E5).
12. PR 31 `claude-fleet-governor` and the 2026-10-23 quota emergency: the governor is gone; Paseo's session-guard and usage-auto-resume plugins replace it (E7).
13. Follow-ups from PRs 29 and 30 (quota guard, self-slash, the one-waiter-per-PR item): the guard, self-slash and pr-wait are gone (E7, E4, E8).
14. `frontier_agent_gate._guard_state` keeps its own reader (2026-11-01): the hook calls `ade_gates.read_guard_state()` (E7).
15. Follow-ups from the 2026-10-20 reviews: the firecrawl-router listener (kept 2026-11-07), the dispatch load-gate and `cursor-cloud` place (E6; `bin/cursor-cloud` direct), the PR 12 routing notes (E7) and the relay Paseo channel (E3).
16. pr-wait follow-ups (PR 58, MEDIUM and LOWs) and the deadline follow-up for `local-review`: both tools are gone (E8).
17. ade-scan-state follow-ups 2 and 3, and the Phase 0 scanner: the tool is gone (E2); the skill-everywhere `unsafe_links` LOW (PR 37) was accepted.
18. Heavier use of Hermes worktrees and cow pastures (2026-10-23): pastures are gone; Paseo worktrees and the claim registry (E2, E8; order 9).
19. `cow-pasture remove --force` with several names (2026-10-09): the tool is gone (E2).
20. Buy a Jev plan, the Jev-vs-GLiDE review's follow-ups: Jev is gone (E2).
21. Ralph on OpenCode v2 (postponed 2026-10-13): `ralph-tui-orchestration` and the gate scripts are gone (E2).
22. Software factory, Phase F (2026-10-19): Jev and cow are gone; the design is `docs/history/software-factory-design.md`; unattended issue→PR is a paragraph in `docs/orchestration-practices.md` (E11).
23. acp-dispatch launchd label lows (PR 62): the launchd runner and reap are gone (E6).
24. A read-only codex advisor ends on its first refused escalation (2026-10-19): codex slices run in its default mode, best effort (E6, internal-trust ruling).
25. acp-run `--perm deny` user-config strip, and classifying quota failures at the source: auto-resume and `failure_class` are gone (E6); acp-run goes in Wave 6.
26. Resurface the first SkillOpt-Sleep night, SkillOpt-Sleep phase 2: SkillOpt-Sleep is gone (E10).
27. Crush under `--perm deny` (2026-10-14): crush is retired (E9).
28. Review the Copilot subscription (2026-08-24): the copilot CLI is retired and no copilot plan survived the pool audit (E9, E10).
29. Type `skills/session-finder/launch.py` (2026-10-09): the file is gone (E3).
30. tuios support (2026-10-24): one harness, Paseo (the 2026-10-31 ruling, kept by the slim-down; tuios is a retired term in `bin/instruction-lint`).
31. Research: web prior art before code spelunking, Python over bash, Kiro/LSP (2026-10-25): the prior-art shadow nudge is gone (E10), kiro is retired (E9); the search-first rule stays in `~/CLAUDE.md`.

## Done before (one line each; detail in git history)

1. Port the Linux suite to uutils (2026-10-28): `pytest-linux` makes g-prefixed wrapper scripts, on `ubuntu-latest`.
2. Keep every machine current, and a changelog (2026-10-20): `bin/ade-update`, `CHANGELOG.md`, fragments since 2026-10-31.
3. Phase 0 backups (PR 24) and the templates (PR 23), 2026-10-20.
4. ade-git-guard O2 redesign adopted and built (PR 59, 2026-10-25).
5. An absolute "all work in a worktree" commandment (2026-10-25): adopted as order 9.
6. Deadline waiters register themselves (2026-11-02); the sweep installs on Linux too (`deadline install --backend`).
7. Queued lows branch, adversary BLOCK, repair and round 2 APPROVE (2026-10-24).
8. Cloud agents: the Cursor API key and `bin/cursor-cloud` (2026-10-19/20).
9. Claude API credits: the omp login and the aiuse credits row (2026-10-19), the Admin API collector (aiuse 3.8.0, 2026-10-20).
10. Quota-aware cross-vendor routing (queued 2026-08-23): `route_agent.py plan|route|show` (2026-10).
11. Implement cow (2026-08-23; removed with `cow-pasture` 2026-11-06).
12. Completed 2026-08-23: `~/src/ops-worktrees/` retired with every branch preserved.
13. Token-cost hygiene review of 2026-08-24 (its one open point is Carried 30).
14. Monthly plans that work with Hermes (research of 2026-08-24; ClinePass).
15. Why the `sed` edit failed twice (2026-10-14): `~/CLAUDE.md` item 33.
16. Flaky MockWebServer tests on the SIPB runner (2026-10-14).
17. Watch Orca upstream for structural-reorg verbs; Orca's short PostCompact hook; the herdr-only capability and Orca parity list: dropped 2026-10-31 with Orca and herdr.
18. Restart the `hindsight` MCP server in sessions older than 2026-08-23 20:00: moot (no such session survives).
