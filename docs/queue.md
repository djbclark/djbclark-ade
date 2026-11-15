# Queue — carried work, closed items, done items

Triaged 2026-11-07 by the slim-down (E11; `docs/slim/PLAN.md` J5: the queue stays a doc). Each entry is one line: what,
why it is still open (or how it closed), where it lives now. **The full text of every entry before the triage is in git
history**: `git show pre-slim-2026-11-06:docs/queue.md` (2,114 lines). New work is queued
under **Carried**, newest first, one line each; an item leaves when it ships (into its doc) or is dropped (say why).

## Stale

1. **CONFLICTING master-bottom PRs** (2026-11-10): open leftovers vs `master` (#290 parked — recovery vs #471; #293 closed 2026-11-10 — tip would have resurrected slim-retired monitors; load-watch `ade_sched` install shipped as #525; #256 closed via #522; #208/#194 closed 2026-11-10; #269 via #523; #227/#231/#270 closed earlier). Guidance: `docs/history/conflicting-pr-hygiene-2026-11-10.md`.

## Carried

1. **Wave 6 shim deletion: done 2026-11-14** (PR `wave6-delete-shims`; operator ruling "Let's get rid of that shim"): `relay.py`, `acp-dispatch`, `acp-dispatch-wait` and `tools/acp-run` are gone, with their tests, `agent_guard.py` and `docs/agent-guard-contract.md`; the evidence bundle is the 2026-11-12 bigmac capture (`docs/slim/log.md`). Retired 2026-11-14 (load-watch callers PR): `bin/wave6-delete-check`, `bin/wave6-mac-proof-capture`, their tests and `tests/fixtures/wave6-mac-proofs/`. Left over: (b) outside `site-public-djbclark/bin/fleet-watch` still names `acp-dispatch` as `UPSTREAM_DISPATCH` (upstream-PR dispatch; the installed launchd job sets `FLEET_WATCH_UPSTREAM=off`), a proposal for that repo (order 11); (c) the `hook.acp-run-identity` allow-list in `bin/ade_claims.py` / `docs/git-guard.md` is dead and can go, and so can `ACP_RUN_AGENT` in `libexec/git-hooks/{reference-transaction,pre-push}`; the guard it served is lost too (acp-run's committer-identity `reference-transaction` hook, 2026-10-18 incident): port it to the ade ref hooks (`libexec/git-hooks/reference-transaction` already runs for agents) if the operator wants it back; (d) Pi Grok/Antigravity/SIPB/Go stay `accepted=false`; (e) the `fable-xhigh` / `frontier-exec` approval gates were enforced only by the deleted shim: port the Fable-xhigh check to `bin/ade-worker-run` or a `paseo run` hook if the operator wants it enforced again (docs/gates.md C2); (f) remove `~/.local/bin/acp-dispatch` / `acp-run` links and `~/.cache/acp-run/` on the Mac (installed state, order 11).
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
5. **ade-git-guard's open items** (2026-10-25 onward; W2–W4 + doctor probe + W2 `--ttl`/dry-run 2026-11-10):
   `plugins/ade-claim/` W2–W4 + W2 follow-up land on master; W2 always passes `ade_claims.py new --ttl` and
   supports `ADE_CLAIM_DRY_RUN` observe-only; `ade-install` catalog/doctor observe `paseo_plugin=ade-claim` as
   missing/disabled/ok and **never** install or enable. Still open: live Mac `paseo plugin install` of `ade-claim`
   and `ade-yolo` (or dry-run first) + observe/`new --ttl` hook path (E8 F4), the O2 redesign's residual (writes
   outside the caller's claimed workspace, with failing tests and an adversary round), the six-case enforcement
   pilot (S4) before any hard refusal (`bin/ade-claim-pilot --fixture` covers cases 1–2 in CI; 3–6 need live),
   and the optional narrowing E8 declined (F3: a security decision for the operator). Lives in
   `docs/git-guard.md`; YOLO plugin: `plugins/ade-yolo/` (#526). Rollout (observe-only install → go-live) is tracked in
   https://github.com/djbclark/djbclark-ade/issues/638 (2026-11-13: `ADE_CLAIM_DRY_RUN` gates only W2, so an observe mode
   for every hook comes before the install).
6. **Drop the brew Paseo for our fork** (2026-10-24): disruptive, **ask the operator first**; after the connected-hosts work.
7. **Paseo connected hosts** (2026-10-24): connect vps-primary (user `djbclark`) after a quiesced Paseo upgrade.
8. **Paseo in-place model change upstream** (2026-10-23): `docs/upstream-issues.md` entry 17 (`paseo agent model <id>
   <model>`), so `bin/paseo-set-model` (used by `route_agent.py substrate --apply`) can go.
9. **Live `~/.claude/settings.json` lacks the `context_size_nudge.py` registration** the template has (2026-10-23):
    the operator's edit (C2 batch, `docs/slim/log.md`). Detector: `ade-install doctor` /
    `just install-doctor` (2026-11-09); apply remains hand-edit of the live file (order 11).
10. **Codex threads left unresolved on merged PRs** (2026-10-23): read each against its PR and fix what is real (review
    rule 9 became the must-triage gate for listed reviewer bots on 2026-11-14, `bin/review-bot-findings`).
11. **Templates, Phase 1** (2026-10-20): declare the `TODO_*` secret names, give each template field a home, make the
    Codex and Claude templates merges, and the `ade-template-check` scanner LOWs (adversary round 3 on PR 23). Lives in
    `agents/README.md`.
12. **Delete the credential vault after 2026-11-19** (owner djbclark): `~/.local/state/ade/credential-bak/`,
    nothing reads it. `ade-install doctor` WARNs within 14 days before that date and FAILs on/after it while
    the vault still exists (never deletes; operator yes still required). Lives in `bin/ade_install.py`.
13. **`ade-backup-stores` LOWs and schedule** (PR 24 rounds 4-22): a launchd schedule, a generation retention,
    `O_NOFOLLOW` walks, the unscrubbed `.part`; and scrub or delete the first generation (it predates the credential
    scrub). Lives in `bin/ade-backup-stores`.
14. **First release tag and `ade-update` LOWs** (2026-10-20; plist scaffold 2026-11-09; Linux systemd path #374):
    tag once CI, rule 10 and `ade-update` are settled (the final slim-down PR is a natural point). Daily `--check`
    plist is `config/launchd/com.djbclark.ade-update-check.plist` (folded into full `ade-install apply` / `just sched-reconcile-checks` on Linux write backends; launchd reconcile write path is #520 landing on master); Linux
    systemd unit path landed (#374); `just update` / `just doctor` / `just install` aliases exist on the
    transitional catalog. First release tag remains.
15. **Codex Cloud environment** (2026-10-19): blocked upstream (openai/codex#50182, #51585); re-probe after each
    codex-cli release.
16. **Claude API credits through Pi** (2026-11-08): the API check was billing-blocked; re-check only after funding
    and explicit pool acceptance, then verify its aiuse attribution. Claude subscription quota is separate; archived
    omp is never a fallback. Lives in `~/src/aiuse`, `skills/model-routing` C.
17. **Paseo Telegram plugin as the phone surface** (SF-Q16, 2026-10-19): blocked on a release compatible with the
    current daemon; then re-point `hermes-ping` and the approval buttons, Hermes's relay as the rollback. The 2fado
    Telegram fallback (2026-10-25) waits for this.
18. **Basic Memory** (2026-10-23): seven of the eight accepted recommendations (Q1 is done); `bin/bm-lint`'s two LOWs
    (PR 55) and its weekly hook-up in site-djbclark `fleet-watch` (offer the parked patch to the operator).
19. **The podman, kev, laya and hyades-docker microVMs** (2026-10-23): inventory first, into a new `docs/microvms.md`.
20. **Phase 0 data decisions** (2026-10-20): where the 41 unreferenced bigteam report sets go, host or bundle
    `~/src/one-offs`, push or bundle branches on no origin. The scanner is gone (E2); its findings are in
    `docs/history/ade-everywhere-phase0-scan-2026-10-20.md`.
21. **Research checker: namespace-aware citations across runs** (2026-10-10): a bare evidence id from another run passes
    `research_check.py claims`. Lives in `skills/research`.
22. **Ingest web-interface AI conversations** (Gemini, Grok web; 2026-08-23) into the memory system: not started.
23. **Dynamic model and effort adjustment by token efficiency** (2026-08-23): not started; the Jev effort nudge that
    approached it was deleted (E2). Lives in `skills/model-routing` B. Price input: item 36.
24. **S1 Phase B adapters** (hindsight, 2026-08-23; status 2026-11-10): the Claude tail and checkpoint
    adapter onward; site-djbclark's `bin/hindsight_s1.py` (order 11). Docs/status open as #478
    (`docs/history/s1-phaseb-status-2026-11-10.md`). Drop or grant after an operator Phase-B decision under
    the Pi-only ruling.
25. **jj (Jujutsu)** (2026-08-23): a larger, separate bet than the retired cow pastures; not started.
26. **Loopback shim by default on forgejo.mit.edu, then ask SIPB** (2026-10-14): steps 1, 4, 5, 6 done; the ticket is
    left. Lives in `~/src/loopback-port-shim`.
27. **Leftovers from 2026-08-23**: confirm-then-delete the hindsight banks `hermes-telegram` and `herdr-shared`; site-djbclark's
    failing `just ops-memory-sync`; file the upstream drafts in `docs/upstream-issues.md` (operator decision).
28. **Re-check Context7 use** (due 2026-10-24): count its calls in the transcripts; if still about zero, ask whether to
    block it (the 2026-10-10 numbers: `docs/history/disabled-skills.md`).
29. **Keep the instruction files lean** (2026-08-24 cost review): Claude's docs advise under 200 lines; AGENTS.md is
    338 lines after the E11 rewrite (2026-11-07), the review rules being most of it.
30. **`bg` registers its own deadline** (2026-11-01): site-public-djbclark `bin/bg`, waits for the operator's yes (order 11).
31. **Slim-down leftovers after Wave 6 deletion** (2026-11-07; deletion itself is Carried 1 / `docs/slim/wave6-follow-up.md`): `skills/loose` upstream-issue reader already uses Claude CLI `-p` (no `acp-run --perm deny`; scrubbed on tip `#498`); remaining: aiuse's acp-run
    readers (`src/aiuse/collectors/acp_usage.py`, order 11);
    `routing-recalibrate` as a Paseo schedule if wanted
    (E5); upstream Paseo filings (a codex read-only mode, a quota-pause primitive, a workspace-claim primitive).
32. **One-step install and automatic updates on a new machine, Mac and Linux** (operator, 2026-11-07): an easy way to install
    djbclark-ade with all its dependencies and TUIs (Paseo and its providers' CLIs, the modern-CLI tools, `graft`, `aiuse`,
    skills linked by `skill-everywhere`), and an automatic way to keep it and every dependency current (software tracks
    its latest release, order 8). Start from what exists: `bin/ade-update` (this checkout only), `bin/ade-sched` for the
    schedule, site-djbclark's `skills/setup-modern-cli`, and the decided but unbuilt proposal `docs/history/ade-everywhere-proposal.md`
    (2026-10-20, pre-slim: re-base it on Paseo and the slim-down's tool list). Widened the same day to GitHub setup for a new
    user (the `ade-merge-gate` App), prompt-injection hardening on demand with a daily drift check, one config file
    (`config/ade.toml`), a justfile entry point, and browser-only steps through Grok Bot: the plan is `docs/setup-plan.md`.
    Later operator additions (2026-11-07): S4b manages ADE-owned jobs and checks other owners without taking them over;
    residual (2026-11-10): inventory + `ade-sched list`/`diff` + doctor drift landed (never unload foreign);
    launchd + systemd + cron + paseo schedule reconcile + `jobs.json` ownership ledger write path landed (S4b host backends complete);
    S5a originally accompanied setup, but security implementation is deferred by the 2026-11-08 operator ruling;
    S9 plans cloud-agent communication last, after signing and the earlier sections, and builds only with headroom
    (design slice: `docs/s9-cloud-paseo.md`, 2026-11-10 — prerequisites, non-goals, paper phases; no live wiring).
    Overall and local coordination now share the local lead.

33. **Pi-only third-party client** (operator, 2026-11-08): migration and archive-only history search shipped;
    omp/OpenCode/Crush are archived, never fallbacks. Dynamic defaults use explicit per-pool acceptance and
    task boundaries (`docs/pi-defaults.md`); normal startup and an unpinned live request passed after activation.
    Restored Grok subscription access (Pi and vendor ACP) and Antigravity Pi passed basic tool checks
    (`docs/pi-services.md`); Grok uses the cancelled plan's remaining allowance and stays manual-only.
    Machine-readable gate: `config/pi-pool-acceptance.toml` + `bin/ade-pi-pools check` (Cursor/Z.ai accepted
    2026-11-08; Grok/Antigravity/SIPB/Go still `accepted=false` until the operator flips them after
    continuation/quota/identity acceptance). Claude API credits remain billing-blocked, separate from the
    vendor subscription. Security implementation and SIPB reliability work are deferred; prior evidence
    remains in `docs/tui-security-and-pi-migration.md`.
35. **`ade-sched reconcile` never creates a `kind = "paseo"` row** (2026-11-13): the admission factory has a launchd
    adapter only, so a Paseo schedule step gets the default `JobAdmission` and defers (exit 6, "shared admission
    incomplete"). `context-budget` was created by hand that day (`paseo schedule create`, id c98b8f3c, operator yes), so
    the ledger does not own it. Next: a Paseo-schedule admission adapter (or record manual create as the path and let
    reconcile adopt a matching live row). Lives in `bin/ade_sched.py` (`JobAdmission`, admit factory), `docs/scheduling.md`.
36. **Model prices from models.dev** (operator, 2026-11-14): install the `~/src/paseo-plugins/model-pricing` Paseo
    plugin (sidebar price table; reads [models.dev](https://models.dev) and OpenRouter, no keys) and feed the same
    catalog into routing. Today `bin/route_agent.py` routes on quota headroom and quality rank only; no per-token
    price enters it. Use list price where it is the real cost: API-billed pools (Bedrock, OpenRouter, Cursor
    Cloud API price, Claude API credits via Pi, OpenCode Go), the dollar side of item 23's token-efficiency
    measure, and `aiuse` cost estimates. Subscription pools (Claude, Codex, Antigravity) keep quota headroom as the
    constraint, list price only a tie-break. models.dev is community data: cache it with its fetch date, bound
    sanity (drop a price that moves >5x between fetches), never fail a route on a missing row. Next: install the
    plugin (operator asked), then a design note in `docs/model-routing.md` and a `route_agent.py` price reader.
38. **Handoff friction, part c** (2026-11-14, PR 714 repair; parts a and b shipped by [PR 736](https://github.com/djbclark/djbclark-ade/pull/736), rq-38): while a handoff is acknowledged but not finished, `bin/ade-worker-run` refuses the WORKER window registered to the predecessor (wks_c6e5c2283a9e63d7, registered to 6621fe2b, not 54b15a51): adoption only happens for a replaced lead, so the successor must open a second window. Next: have `bin/ade-worker-run` count a fresh acknowledged link as a succession via `ade_lead_succession.successor_of(..., statuses=ACKNOWLEDGED)` (PR 736; it applies `_ack_is_fresh` itself). That is a wider grant than the send redirect, today its only user: a record can stay acknowledged for up to an hour after `finish` stops for a hand step (Carried 43a), so window adoption must also check that the predecessor is no longer acting.
40. **Refresh `agents/claude/settings.json.tmpl` from the live `~/.claude/settings.json`** (operator, 2026-11-14, ec-01): item 9 is one known difference between them and `ade-install doctor` / `just install-doctor` is the detector. Next: diff the two, move each live registration worth keeping into the template (no secret-bearing keys), leave the live file alone (order 11), re-run the doctor.
42. **route_agent rq-37 review Lows** (2026-11-15, lead review of [PR 735](https://github.com/djbclark/djbclark-ade/pull/735), merged; report `~/.local/state/agent-reports/b4eaf47c-9f91-45c4-8f37-bef9d37c2eba/lead-adversary-review-pr-735-report.md`): (a) the aiuse `account` label is trusted as the quota id, so one email in two orgs folds as one account (over-stated headroom); (b) `docs/model-routing.md` D3a claims more than the code checks: nothing matches an aiuse account to a Paseo account; (c) a mutant that compares only the last-seen account (`seen[-1] == who` instead of the `all(...)` in `_folds_as_accounts`) survives (no `[a, b, b]` test); (d) the family half of the (account, family) identity is unreachable today; (e) Info B5: `aiuse --available` lists only usable rows, so an exhausted second account is invisible to the router, and rows that map to no pool (zai 5h/weekly, antigravity gemini, cursor grok_bot) drop out of the fold. Lives in `bin/route_agent.py`, `tests/test_route_agent_rq37.py`.
43. **Self-session send-redirect Lows** (2026-11-15, rq-38 reviews of [PR 736](https://github.com/djbclark/djbclark-ade/pull/736), merged; reports `~/.local/state/agent-reports/a4e18327-55e8-434c-ad2c-5ef6b65edf41/rq-38r-report.md` and `~/.local/state/agent-reports/9aed22b1-98b6-4779-8ba9-09da19b49ae5/lead-adversary-review-pr-736-r2-report.md`): (a) after an `AGENT_RUNNING` refusal naming a different agent, `finish` stops but the send guard keeps redirecting to the successor for up to an hour (rv-736r B1; its suggested fix: give that refusal a non-waiting code such as `ARCHIVE_RESOLVED_OTHER_AGENT`); (b) a stale `AGENT_RUNNING` survives a crash in a second archive call (R1, hour-bounded); (c) after a failed first check, a later successful re-run keeps the redirect off until archived (R2); (d) the hour can expire during retries (N2); (e) up to four `paseo agent inspect` calls per guarded send (B5, Info). None misroutes to a third agent. Lives in `bin/ade_send_guard.py`, `bin/ade_self_session.py`.
44. **gs-04 docs Low** (2026-11-15, lead review of [PR 737](https://github.com/djbclark/djbclark-ade/pull/737), merged; report `~/.local/state/agent-reports/9aed22b1-98b6-4779-8ba9-09da19b49ae5/lead-adversary-review-pr-737-report.md`): the bash-habits docs name the case-arm false-positive class but not the `x) echo` instance from the rv-733 review (B2d). Lives in `docs/bash-habits-gate.md`.
45. **Adversary-marker gate review Lows** (2026-11-15, lead review of [PR 734](https://github.com/djbclark/djbclark-ade/pull/734), merged; report `~/.local/state/agent-reports/af841d47-3dcd-4fb5-959d-de9839639e78/lead-adversary-review-pr-734-report.md`; the false allows are pre-existing, while 734 added the over-claiming rule 14 text (a); former (c), the vacuous RecursionError test, and the review's D1 leaf-path fix shipped in [PR 741](https://github.com/djbclark/djbclark-ade/pull/741), cq-45c): (a) `docs/code-review.md` rule 14 says a later `D=decoy` reassignment is handled, but `cd $D` after one still reads the wrong dir and allows (B1); (b) `cd -P`, `cd --`, `{ cd`, `if cd` and `builtin cd` are not followed, so a body file only under that dir is not read and a live marker is allowed, and rule 14 does not list it (B2); (d) padding a `--input` payload past 256 KB in a key GitHub ignores still allows (B4, Info, documented); the GraphQL-escape clause of this item is now Carried 52. Lives in `claude/hooks/adversary_marker_gate.py`, `tests/test_adversary_marker_gate.py`.
47. **graft 0.29.0 rewires agent files in every fresh worktree** (2026-11-15, tendcf lead handback; upstream trailhq/Trail-Code#830): `graft init` writes `.adal/`, `.gemini/`, `.grok/`, `.kiro/`, `.windsurf/` and `.github/copilot-instructions.md` untracked into a fresh worktree, and rewrites tracked `AGENTS.md`, `.claude/` and `.cursor/` hook files. **Landed (operator ruling 2026-11-15): [PR 743](https://github.com/djbclark/djbclark-ade/pull/743)** ignores the six untracked paths in `.gitignore` and `.ignore` (`/opencode.json` is tracked here, so no line; `.agents/` is not ignored). Remaining: (a) the global `~/.config/git/ignore` `/opencode.json` line, for repos that do not track it, is managed from its source repo (order 11) and needs the operator; (b) graft's rewrites of tracked files (`AGENTS.md`, `GEMINI.md`, `opencode.json`, `.mcp.json`, `.claude/`, `.cursor/` hooks) are not ignorable (Low; upstream); (c) the untracked `.agents/skills/fastino-glide/` in the shared checkout is not graft's: it is the `skills` CLI project install from `https://docs.fastino.ai` that `skills-lock.json` (tracked, 3425aa2f, 2026-10-12) records, recreated at 09:11 on 2026-11-10 by an unknown run, content identical to the 2026-10-19 copy; it is byte-identical to the tracked `.claude/skills/fastino-glide/SKILL.md` (same commit, sha256 equals the lock file's `wellKnownDigest`), so committing it adds a duplicate and deleting it loses nothing; prose only (no scripts), it never calls out by itself, but it tells an agent to call api.fastino.ai with `FASTINO_API_KEY`, sending project data to a third party, when a task is classifying, routing or scoring decisions; decide delete, ignore or keep (operator). Lives in `.gitignore`, `.ignore`, `~/.config/git/ignore`.
49. **Self-session `creation-refused` status** (2026-11-15, tendcf lead handback; PR 668 follow-up): a handoff whose native `paseo run` failed with a recorded `native_error` still ends `creation-unknown` (`bin/ade_self_session.py`: set near line 479, kept by the `agent run` error branch near line 521, reconciled near line 630), so it waits on a reconcile it cannot need. Next: decide whether a definite native refusal (error code present, no agent id) becomes `creation-refused`, then add the status, its `docs/self-session.md` C-table row and tests. Lives in `bin/ade_self_session.py`.
50. **rv-742: `bin/ade-worker-run` cwd-compare review Lows** (2026-11-15, review of [PR 742](https://github.com/djbclark/djbclark-ade/pull/742), merged; former Carried 41 fix; report `~/.local/state/agent-reports/df8239f6-f47d-45e3-81a2-70e1f2111f9a/lead-adversary-review-pr-742-report.md`): (a) the redirect-site change has no test; (b) the new-window case refuses falsely on a case-variant spelling; (c) a `ValueError` or `UnicodeEncodeError` can surface after launch; (d) `same_dir` duplicates `ade_claims._same_path`. Lives in `bin/ade-worker-run`.
51. **rv-741: adversary-marker gate review Lows** (2026-11-15, review of [PR 741](https://github.com/djbclark/djbclark-ade/pull/741), merged; report `~/.local/state/agent-reports/df8239f6-f47d-45e3-81a2-70e1f2111f9a/lead-adversary-review-pr-741-report.md`; all pre-existing except (a)): (a) the allow-tests ignore stderr, so a diagnostic or traceback there goes unnoticed; (b) a UTF-8 BOM before `{` in a `--input` payload is not handled (D4; whether GitHub accepts it is unverified); (c) a program's output or a decoder (`base64 -d`, `gzip -dc`) piped into `gh api --input -` is outside the gate's model (D5); (d) the operand-cap `truncated` path and the past-`MAX_STARTS` leaf path still use the single-decode `mentions_approve`; switch both to `mentions_approve_decoded` (D6, one line). Lives in `claude/hooks/adversary_marker_gate.py`, `tests/test_adversary_marker_gate.py`.
52. **rv-741: GraphQL literal-escape limit, pre-existing** (2026-11-15, review of [PR 741](https://github.com/djbclark/djbclark-ade/pull/741), merged; its B2, Info; moved here from Carried 45 (d)): a GraphQL string literal with `\u003c`/`\u003e` escapes and `\"` is allowed, both inline (`-f query=`) and through `-F query=@file`; GitHub's parser decodes the escapes, so the stored comment would carry a live marker. `docs/code-review.md` rule 14 names only the inline `gh api graphql -f query=` form, not `-F query=@file`; the PR 741 lead review report is `~/.local/state/agent-reports/df8239f6-f47d-45e3-81a2-70e1f2111f9a/lead-adversary-review-pr-741-report.md`. Next: decode GraphQL string escapes in a `query` text before `live_approve`, and name the `-F query=@file` form in rule 14. Lives in `claude/hooks/adversary_marker_gate.py`.
53. **rv-740 Info: `session_cookie:x` kept** (2026-11-15, review of [PR 740](https://github.com/djbclark/djbclark-ade/pull/740), merged; former Carried 46; report `~/.local/state/agent-reports/df8239f6-f47d-45e3-81a2-70e1f2111f9a/lead-adversary-review-pr-740-r2-report.md`): the widened pattern keeps a code such as `session_cookie:x` as is. Info only, no fix needed; drop this item at the next prune. Lives in `bin/ade_self_session.py`.
54. **rv-744: load-watch local-gate Lows left after repair** (2026-11-15, review of [PR 744](https://github.com/djbclark/djbclark-ade/pull/744), merged as 21019601; report `~/.local/state/agent-reports/df8239f6-f47d-45e3-81a2-70e1f2111f9a/lead-adversary-review-pr-744-r2-report.md`): (a) `registry_lock` has no lock-wait timeout; (b) the TMPDIR comment overstates, since bash falls back to `/tmp`; (c) the dialog may appear before a damaged-row refusal. Lives in `bin/load-watch`, `tests/test_load_watch.py`.
55. **graft-ignore D1: `graft init` rewrites tracked agent files** (2026-11-15, worker report of [PR 743](https://github.com/djbclark/djbclark-ade/pull/743), merged; upstream trailhq/Trail-Code#830): the same limit as Carried 47 (b), which holds the file list and stays the one record; this item is a cross-reference only and closes with it.

## Closed by the slim-down (2026-11-06/07; the slice that closed it)

1. relay: card-blocked records fail fast (2026-10-31): the outbox is gone; the shim fails closed on a target with a pending permission (E3).
2. relay.py status, stuck-queue visibility, the ack-staleness addendum H1-H5 and housekeeping (2026-10-31): the deferred records, `--status`, `--sweep` and expectations are gone (E3).
3. Verified peer messaging and its round 2 (2026-10-25): order 10 re-based on `paseo send` and the named ack; the expectation ledger and first-contact footer are gone (E3).
4. Research: relay and self-slash blocking on picklists (2026-10-28): self-slash is gone (E4); the shim refuses a busy target that cannot steer (E3).
5. Follow-ups after PRs 73 and 74, relay deferred send (PR 57), the pane route lows, Paseo agents in fleet.py and relay.py, the `hermes` route: relay.py's routes and fleet.py are gone (E3).
6. Orchestration rules from the load watcher (2026-10-23): name a workspace by name and id, and the load-planning rules, are in `docs/orchestration-practices.md` (E11); finding a peer is `paseo ls` (E3); push on completion shipped 2026-11-09 (Done before: footer rule 22, `bin/completion-notice`, fan-out Collect).
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

1. **`bin/review-pr` and `bin/gh-pr-checks --watch` self-register deadlines** (#361 / #393 / #448, 2026-11-09/10): former Carried residual; see `docs/deadline.md`.
2. **load-watch via ade_sched** (2026-11-10, #525): `load-watch install|uninstall` uses `ade_sched` with
   `__ADE__`/`__HOME__` templates (Linux systemd + Mac launchd); closes the #293 leftover without restoring
   slim-retired monitors.
3. **Two test LOWs from rework-2 PRs 32/33** (docstring nested `tests/` + `[lead]` `xhigh`/`max`): fixed in #391 (2026-11-10); queue row closed 2026-11-10.
4. **Push on completion** (load-watch 96a17744, 2026-10-23; shipped 2026-11-09): a delegated slice tells its requester
   `done: <title>, <PR URL>` (or status/report) via `paseo send --json --no-wait` with named ack, never relay; dispatch
   footer rule 22, `bin/completion-notice`, `skills/fan-out` Collect, `docs/orchestration-practices.md` §5a.
5. **Model tiers as data** (2026-10-31 → 2026-11-09, PR #401): `config/model-tiers.toml`, `bin/ade-model-tiers promote|set`,
   `route_agent` / `load_effective` readers; design remains `docs/history/model-tiers-design.md`.
6. Port the Linux suite to uutils (2026-10-28): `pytest-linux` makes g-prefixed wrapper scripts, on `ubuntu-latest`.
7. Keep every machine current, and a changelog (2026-10-20): `bin/ade-update`, `CHANGELOG.md`, fragments since 2026-10-31.
8. Phase 0 backups (PR 24) and the templates (PR 23), 2026-10-20.
9. ade-git-guard O2 redesign adopted and built (PR 59, 2026-10-25).
10. An absolute "all work in a worktree" commandment (2026-10-25): adopted as order 9.
11. Deadline waiters register themselves (2026-11-02); the sweep installs on Linux too (`deadline install --backend`).
12. Queued lows branch, adversary BLOCK, repair and round 2 APPROVE (2026-10-24).
13. Cloud agents: the Cursor API key and `bin/cursor-cloud` (2026-10-19/20).
14. Claude API credits: the omp login and the aiuse credits row (2026-10-19), the Admin API collector (aiuse 3.8.0, 2026-10-20).
15. Quota-aware cross-vendor routing (queued 2026-08-23): `route_agent.py plan|route|show` (2026-10).
16. Implement cow (2026-08-23; removed with `cow-pasture` 2026-11-06).
17. Completed 2026-08-23: `~/src/ops-worktrees/` retired with every branch preserved.
18. Token-cost hygiene review of 2026-08-24 (its one open point is Carried 29).
19. Monthly plans that work with Hermes (research of 2026-08-24; ClinePass).
20. Why the `sed` edit failed twice (2026-10-14): `~/CLAUDE.md` item 33.
21. Flaky MockWebServer tests on the SIPB runner (2026-10-14).
22. Watch Orca upstream for structural-reorg verbs; Orca's short PostCompact hook; the herdr-only capability and Orca parity list: dropped 2026-10-31 with Orca and herdr.
23. Restart the `hindsight` MCP server in sessions older than 2026-08-23 20:00: moot (no such session survives).
24. **Web search first and last** (operator, 2026-11-13; former Carried 34, shipped by the `websearch-policy` PR): the required `Prior art / docs checked:` brief line and the `Closing search:` report field live in `docs/dispatch-footer.md` rule 24 and the `skills/fan-out` brief section; the reviewer rule (missing on a non-exempt PR is a LOW) is `docs/code-review.md` rule 12.
25. route_agent rt-01 (2026-11-14, PR 708): `--available` rows of one pool key fold as accounts (a window or row one account cannot measure closes the pool for every kind on pooled services (claude, cursor, antigravity-argon, ...); on codex only its plenty kinds, so codex `frontier` stays eligible), a snapshot `error` account is an unmeasured account (the `--available` guard is defensive: aiuse emits no error row there), and `[dispatch.repo_overrides.REPO] frontier_order` orders the eligible `frontier` pools for `--repo REPO` (tendcf: codex, claude, antigravity-argon; validated by the router and by `ade-config check`, the error naming the overlay). No live routing changes today: the only multi-account provider is retired opencode-go.
26. route_agent rq-37 (2026-11-15, PR 735; former Carried 37): a quota row is identified by its aiuse (`account`, family), not the pool key, and `usage_from_paseo` by the Paseo row `id`; an unreadable report of another account adds an `(unmeasured)` window (`docs/model-routing.md` A2c/D3a). The old item's `frontier_order` clause closed too: A2c makes no repo order the intended default. Its review Lows are Carried 42.
27. Self-session handoff friction, parts a and b (2026-11-15, PR 736; former Carried 38 a, b): `bin/ade_send_guard.py` redirects a send to an acknowledged predecessor to its successor, and the successor brief says to read lead-log lines newer than the checkpoint. Part c stays Carried 38; the review Lows are Carried 43.
28. Self-handoff successor keeps the chain's identity (st-01; 2026-11-14, PR 726; former Carried 39): title and `ade.predecessor` / `ade.chain` / `ade.role` labels, re-checked at `accept` and `finish` (`docs/self-session.md` C-id).
29. `bin/ade-worker-run` compares `--cwd` spellings of one directory as equal (cq-41; 2026-11-15, [PR 742](https://github.com/djbclark/djbclark-ade/pull/742); former Carried 41): review Lows are Carried 50.
30. ade-self-session keeps lowercase, dotted and colon native error codes (cq-46; 2026-11-15, [PR 740](https://github.com/djbclark/djbclark-ade/pull/740); former Carried 46): review Info is Carried 53.
31. [PR 665](https://github.com/djbclark/djbclark-ade/pull/665) (Beeper re-registration and interactive-only OAuth docs) merged as 8bbc9249 (2026-11-15; former Carried 48).
