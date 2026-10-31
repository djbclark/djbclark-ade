
# Software factory → ADE-everywhere: research report (Claude reader, 2026-10-19)

## 1. Verdict

The factory is worth adding, but as a thin state machine over tools the plan already owns, not as the program the design describes. `acp-dispatch` already does job records, reports, `BLOCKED:`, quota-stop resume, SIGKILL reaping, detached launchd runs, `--perm read-only`, advisor tree-hash checks, routing eligibility and reroute/escalate (`bin/acp-dispatch:2-45,103-136`); the design's orchestrator, cost guards, fallbacks and resume rules re-specify most of that. What is new: a per-job `events.jsonl` state machine with rounds, `verdict.json`, a workspace adapter (cow pasture on Macs), a CI-run `verify`, and a PR opener. The dashboard should not be a static page: Paseo is the decided front end (§7, Q9) and Hermes Telegram already renders inline approval buttons. Four design claims are wrong for this machine (bwrap, local `verify`, hard-coded role→agent, job state inside the repo). Nine questions remain for djbclark; the rest are already ruled in §9 or follow from the routing policy.

## 2. Fit

### 2.1 Phase

1. Not in the plan today: the proposal's §8 phases (`docs/ade-everywhere-proposal.md:648-716`) never mention a factory; `docs/coding-factory.md` (2026-09-21) is listed in `AGENTS.md:30` but superseded by nothing and cited by the design nowhere.
2. Dependencies, in order: (a) Phase 1's first PR adds the GitHub Actions workflow on `djbclark-ade` (proposal:672-674), which the factory's `verify` needs under the CI-first rule (proposal:954-967; `~/CLAUDE.md:92-93`, item 37); (b) Phase 4's ADE Paseo plugin already lists "Dispatch timeline rows: `acp-dispatch` slices appear in the parent agent's timeline with report and `BLOCKED:` state" (proposal:636-637), which is the factory's board; (c) Phase 0 only matters in that nothing is deleted while the factory writes state.
3. Recommended placement: a parallel track, "Phase F", F1-F3 starting once the Phase 1 CI workflow is merged; the dashboard becomes one more panel of the Phase 4 plugin; GitHub Issues intake and any merge automation wait for Phase 5 or later, because no repo has branch protection or required checks (coding-factory.md:36, 2026-09-21, not re-verified today).

### 2.2 Repo and path

`djbclark-ade`. The design's `tools/factory` (design:668-669) is acceptable, but `tools/` holds the vendored single-file `acp-run` with its own README (acp-run README:638-647), while the Python CLIs that import each other live in `bin/` (`acp-dispatch`, `route_agent.py`, `load-watch`, `failover.py`). Recommend `bin/factory`, `config/factory.toml` beside `config/routing.toml`, role prompts in `config/factory/roles/*.md`, `docs/factory.md`. Job state goes under `~/.local/state/factory/<repo>/<job>/`, never in the target repo (correction 3.4).

### 2.3 Reuse table

| # | Factory component (design) | Existing ADE piece | Verdict | Proof |
|---|---|---|---|---|
| 1 | Orchestrator shells out to `acp-run --json` per role (design:104-106) | `acp-dispatch <agent> --model --kind --name --task -C -f` with report, `.done`, record, footer | **reuse**; the factory calls acp-dispatch, never acp-run | `bin/acp-dispatch:4-13,54-61` |
| 2 | `job.json` sole writer, `events.jsonl` source of truth (design:796-801) | `jobs/<name>.json` per slice (temp+`mv -f`), `rearm`, `closed` | **adapt**: factory adds `~/.local/state/factory/<repo>/<job>/events.jsonl` + `job.json` snapshot keyed to acp-dispatch record paths | `skills/bigteam/SKILL.md:748-767`; `bin/acp-dispatch:56-61` |
| 3 | Crash-resume, orphan reaping (design:797-798) | `reap`, `pid_start`, launchd `--detach`, `restart-resumed`, `wait` | **reuse** | `skills/bigteam/SKILL.md:608-640`; `bin/acp-dispatch:37-45` |
| 4 | Quota pause / fallback agent (design:567-571) | auto-resume in place at reset; `reroute --agent/--escalate` with `rerouted_from` recorded; no silent swap | **reuse**; delete `fallback[]` from roles | `bin/acp-dispatch:103-124`; README:499-504 |
| 5 | `prompt_retries`, `--max-load`, `--load-wait` (design:559-561) | acp-run items 9-10 | **reuse** | `tools/acp-run/README.md:261-268` |
| 6 | Reviewers read-only (design:144-147) | `--perm read-only` on claude, codex, opencode, zcode; tripwire exit 77; `--role advise` tree hash | **reuse** | `tools/acp-run/acp-run:543-575`; `bin/acp-dispatch:176-179` |
| 7 | Verdict parsing first line (design:141-142) | report contract `STATUS:`/`BLOCKED:`/`DONE`, `check` classifier, `FAILED fake-tool-calls` | **adapt**: add `verdict.json` beside the report | `bin/acp-dispatch:54-58,86-93` |
| 8 | Builder resume (design:148-151) | `acp-dispatch resume RECORD -p TEXT`; agy Claude pool cannot reopen, checkpoint reroute instead | **reuse** | README:489-497; bigteam:600-603 |
| 9 | Builder `--verify "<repo test cmd>"` (design:153-154) | CI-first: `load-watch ci decide`, `bg` exit 3 refusal, `ci/base` + `ci/run/**` recipe | **replace**: push `ci/run/<job>-<sha8>` and wait; `acp-run --verify` only for a focused check `load-watch ci check` allows | `bin/load-watch:43-49`; `skills/forgejo-ci/SKILL.md:179-194`; `~/CLAUDE.md:142-145` |
| 10 | Role → agent/model table (design:223-261) | `route_agent.py plan --kinds`, `config/routing.toml`, `--kind` mandatory, cheap-first escalation | **replace**: roles map to kinds and constraints; `plan` picks the pool at dispatch | `config/routing.toml:17,122-128,141-154`; `skills/model-routing/SKILL.md:466-543` |
| 11 | Git worktree per job (design:588-589) | `bin/cow-pasture create <name> --source <repo> --branch <b>` (secrets scrubbed, deps carried); refuses `~/ops/*` | **adapt**: one `workspace` adapter; pasture on Macs, `git worktree` + setup cmd on Linux | `skills/cow-workspaces/SKILL.md:23-35,40-47,89-93`; proposal:605 |
| 12 | Guard against primary checkout (design:594-598) | bigteam Step 0 `CLAIM` files; nothing in acp-run | **build new**, in the factory launcher only (D1) | bigteam:61-85; proposal Q9 (:757-759) |
| 13 | Security reviewer (design:243-246) | `adversary` agent: Opus high, read-only, `APPROVE`/`BLOCK`, required before any PR | **reuse** the prompt as the role | `~/.claude/agents/adversary.md:1-24`; `~/CLAUDE.md:114-116` |
| 14 | Approver LLM (design:258-260) | human merge after adversary verdict in PR body | **cut** | proposal:650-651; `~/CLAUDE.md:115-116` |
| 15 | Dashboard HTML + `factory serve` (design:114-116, 276-556) | Paseo front end; ADE plugin "Dispatch timeline rows", Helm panel; `fleet.py` | **replace** with a plugin panel in Phase 4; `factory status` text meanwhile | proposal:136-139,625-642 |
| 16 | Telegram digest / actions (design:506-510, 782-785) | `hermes-ping`; Hermes `clarify` inline keyboard buttons and exec approval cards | **reuse** | `~/.local/bin/hermes-ping:1-23`; `~/.hermes/hermes-agent/website/docs/user-guide/messaging/telegram.md:1390-1411` |
| 17 | Cost in USD per run (design:214-216) | acp-run reports usage only for some agents (agy, crush: none) | **adapt**: calls + wall-clock caps; USD "reported + N not reported" | `docs/failover.md:71-85` |
| 18 | Minimal env, no push token (design:775-777) | `failover.py` gives children `BASE_ENV_KEYS` only; acp-run strips only HERDR vars | **adapt** failover's pattern into the factory launcher | `docs/failover.md:65-68`; README:297 |
| 19 | Outcome → model comparison (design:662) | `acp-dispatch outcome --ci --review --merged`; `route_agent.py calibrate` | **reuse** | `bin/acp-dispatch:25-27`; README:529-535 |
| 20 | Backlog via GitHub Issues (design:112) | Hermes `github-issue-to-pr` skill; nothing listens to issue events | **later** (Phase 5+) | `docs/coding-factory.md:27-29` |

Answers to the four pointed questions: the orchestrator is acp-dispatch plus a state machine over its records (rows 1-4); the job workspace is a cow pasture on Macs with `git worktree` as the portable fallback (row 11); the dashboard is Paseo plus Hermes, not a new page (rows 15-16); "human merge authority" is exactly the existing PR-with-adversary-verdict rule (rows 13-14).

## 3. Corrections

1. **`bwrap` on macOS.** Claim: "bwrap/container before any unattended run" (design:775-777, 690-691; agy review `docs/software-factory-reviews/agy-full-and-worktree.md:22`). Artifact: `/opt/homebrew/bin/bwrap` does not exist (Glob, 2026-10-19); `/usr/bin/sandbox-exec` exists (deprecated, no replacement: lib.rs/ai-jail write-up); Claude Code's sandbox "on macOS uses the built-in Seatbelt framework", "on Linux relies on bubblewrap", and "is off by default" (code.claude.com/docs/en/sandboxing, fetched 2026-10-19). Codex has a `read-only` Seatbelt session mode (`acp-run:547`). Apple's `container` CLI is used as a Linux control in `skills/forgejo-ci/SKILL.md:133` but is not at `/usr/local/bin/container` (unverified where). Consequence: v1 isolation = `--perm read-only` for reviewers, a scrubbed pasture plus minimal env for the builder, and the test run in CI; a container is not a v1 gate, and the operator's standing rule already says sub-agents run yolo unless security-sensitive (`skills/model-routing/SKILL.md:388`).
2. **Which agents take `--perm read-only`, `--resume`, `deny`.** Claim: roles.toml puts reviewer-ux on `agy` with `fallback = ["cline"]` and reviewer-code on `cline` (design:248-256). Artifact: `READONLY_AGENTS = ("claude", "codex", "opencode", "zcode")` (`acp-run:568`); agy reads unasked under `deny` and needs `--tripwire-exempt-kinds` (bigteam:544-547); cursor "cannot deny at all" (model-routing:339-343); cline is uninstalled and gated behind `ACP_OPERATOR_APPROVED=cline` (`config/routing.toml:74-76,92`; model-routing:280-284); `--resume` exits 2 where neither `loadSession` nor `session/resume` is advertised (README:581-584). Consequence: reviewer roles must be constrained to the four read-only agents; cline is out; the design's `--info` validation (design:271-273) should check `perm_modes` (`acp-run:579-586`).
3. **`verify` runs on the Mac.** Claim: "Builder acceptance check uses `acp-run --verify`" and "Orchestrator runs `verify` itself" (design:153-154, 803-804). Artifact: acp-run's verify "Runs `CMD` as a shell command with `-C DIR` as cwd" (README:273-282); the CI-first rule: "Heavy jobs run in CI, not on the Mac" (`~/CLAUDE.md:92-93`), `bg` refuses a repo with no `ci` decision (exit 3; `bin/load-watch:43-49`), proposal §11.3 (:954-967). Consequence: `verify` = push `ci/run/<job>-<sha8>` (forgejo-ci:179-194) and wait for the run; the Mac runs at most a focused check `load-watch ci check` allows.
4. **Job state inside the target repo.** Claim: `factory/jobs/<job-id>/` and `factory/roles.toml` in the repo (design:107-110, 221), while the orchestrator "rejects diffs touching `factory/`" (design:803-804). Artifact: acp-dispatch keeps records under `~/.local/state/bigteam/<task>/`, "never the session scratchpad" (acp-dispatch:59-61); a cow pasture copies untracked content (cow-workspaces:14-16); principle 3 wants identical paths across machines (proposal:121-124). Consequence: state under `~/.local/state/factory/`; roles in `djbclark-ade/config/`.
5. **Hard-coded agent per role and Opus on spec.** Claim: `agent = "claude" model = "opus"` per role (design:229-260). Artifact: "`acp-dispatch` needs `--kind`; cheapest eligible tier first" (`~/CLAUDE.md:133-136`); `plan` picks pools within the quality band (routing.toml:36-42); Claude review found the sample "contradicts the cheap-first rule" (claude-opus-round1.md:68). Consequence: roles declare kind, perm, constraints (vendor must differ from builder, read-only required), not agents.
6. **Fallback agents.** Claim: `fallback[]` used on quota failure (design:250, 567-571). Artifact: a quota stop is auto-resumed in place and a reroute is recorded (`acp-dispatch:103-124`; `~/CLAUDE.md:101-103`). Consequence: drop the field; D5 is already satisfied by the engine.
7. **Dashboard served by `python3 -m http.server`** (design:44-45, 114-116). Artifact: "Paseo is the front end, not the engine" (proposal:136-139), Q9 decided (:757-759), plugin item 3 (:636-637). Consequence: no third UI; see SF-Q6.
8. **Telegram actions are new work.** Claim: D6 schedules Telegram buttons for D2 (design:782-785). Artifact: Hermes already renders `clarify` as "inline keyboard buttons" with a numbered-list fallback and an exec-approval card (telegram.md:1390-1411); the sender is `hermes-ping` (hermes-ping:1-23, target `telegram:838808636:22158`). Consequence: the phone surface is a Hermes skill or cron job, not a bot; and the "approve" action in v1 is GitHub's own merge button (GitHub mobile), because `ready` = PR opened.
9. **Reconciling with `docs/coding-factory.md`.** That doc found "branch protection / rulesets / allow_auto_merge: absent on every repo" and GitHub's auto-merge 422 regression (coding-factory.md:36, 69-75, 2026-09-21; not re-verified today). The new design is the local-orchestrator variant of its Phase 2c (coding-factory.md:250-251: Hermes/Orca worker "in a fresh cow pasture"). Its Phase 1 gate (rulesets, `guard` job, a failing-capable review check) is the precondition for any `ready → merged` automation and is still unbuilt; v1 therefore ends at "PR opened", which needs none of it.
10. **zazencodes licence.** Claim: "skeleton we borrow", "role prompts ... ported from the zazencodes `.claude/agents/*.md`" (design:26-27, 267-269). Artifact: the GitHub page shows the files (`SKILL.md`, seven agents, `backlog.md`, `dashboard.html`, two example jobs) but "No license is shown" (fetch 2026-10-19). Consequence: verify the repo licence before copying prompt text; otherwise write the seven prompts fresh from the role list.
11. **Cost per run is often unreported.** Design:214-216 copies `cost` from `--json`; `docs/failover.md:76-80`: "agy and crush report none"; the design's own §12.1 shows agy and cursor reported no cost (design:716, 721). Consequence: caps are calls and wall-clock; USD advisory (already the §12.4.3 revision, confirmed).
12. **Parallel jobs.** `max_parallel_jobs` default 2 (design:573-574) versus per-pool caps (agy 2-3, cursor 2, codex 1; routing.toml:164,199,214,323) and Claude's "1 until crash-resume has been tested" (claude-opus-round1.md:90). Consequence: 1 in v1; concurrency comes from `plan`'s wave spreading, not the factory.

## 4. Prior art, dated (all checked 2026-10-19)

1. zazencodes `software-factory-claude-code`: one skill + seven subagents + markdown; `/factory <feature>`; spec-writer (opus) → builder (opus) on `factory/<id>` → four parallel reviewers (security opus; ux, ui, code sonnet) with `VERDICT` lines → ≤2 builder resumes → approver `APPROVE|ESCALATE`; `backlog.md`, `dashboard.html` polling every 2 s; README says it now uses per-job `job.json` and worktrees (matches design:35-39). Licence and last commit not visible. <https://github.com/zazencodes/zazencodes-season-3/tree/main/src/software-factory-claude-code>
2. github/spec-kit: releases v1.2.2 (19 Oct), v1.2.1 (16 Oct), v1.2.0 (13 Oct); year not printed on the page, inferred 2026 from a 2026-09-24 report of 1.0.11. <https://github.com/github/spec-kit/releases>, <https://tproger.ru/news/github-vypustil-spec-kit-1-0-11-s-idempotentnym-dobavleniem-kata>
3. Fission-AI/OpenSpec: v1.14.3 (17 Oct), v1.14.2 (15 Oct), v1.14.1 (6 Oct); year not printed; releasebot lists v1.12.0 on 2026-09-03. <https://github.com/Fission-AI/OpenSpec/releases>, <https://releasebot.io/updates/fission-ai/openspec>
4. automazeio/ccpm: PRD → epic → GitHub Issues → parallel agents in worktrees; last push 2026-03-18 (gittrend), ~8.2k stars. <https://gittrend.io/repo/automazeio/ccpm>
5. Aperant (ex Auto-Claude): AGPL-3.0, pivoting to a commercial platform (rebrand March 2026); one source reports no repo pushes since 2026-03-23, another cites 2.8.0-beta.4 in July 2026; activity unclear. <https://rywalker.com/research/auto-claude>, <https://blog.brightcoding.dev/2026/07/04/aperant-the-revolutionary-multi-agent-coding-framework-every-developer-needs>
6. smtg-ai/claude-squad: AGPL-3.0, 8.6k stars, 222 commits; agents Claude Code, Codex, Gemini, Aider, OpenCode, Amp; shortcuts `n N Enter/o s c r D q` (design:308-311 matches). <https://github.com/smtg-ai/claude-squad>
7. Superset: macOS desktop app, git worktree per task with its own terminal sessions and port allocations; runs Claude Code, Codex, OpenCode, Cursor, Copilot, Gemini; Windows/Linux "coming soon"; the exact "waiting on you" wording not confirmed. <https://docs.superset.sh/overview>, <https://superset.sh/blog/working-with-worktrees-in-superset>
8. OpenHands: Agent Canvas automations run on schedule or webhooks (GitHub, Slack, Linear); any ACP agent as the worker; PyPI `openhands-ai` 1.11.0 says "the code in this repo is moving" to Agent Canvas. No label-trigger reliability update found since coding-factory.md:49 (issue automation#107). <https://openhands.dev/blog/use-any-coding-agent-in-openhands-with-acp>, <https://pypi.org/project/openhands-ai/1.11.0/>
9. GitHub Copilot, October 2026 changelog: "Dynamic workflows in Copilot CLI and the Copilot app" (Oct 1); "Copilot code review: API support and new default effort level" (Oct 2); "Local sandboxing for GitHub Copilot now generally available" (Oct 7); "Copilot code review: new organization billing options and controls" (Oct 8); model deprecations effective Oct 2. Nothing new on issue assignment or approvals. <https://github.blog/changelog/label/copilot/>, <https://github.blog/changelog/month/09-2026/>
10. Google Jules: free 15 tasks/day, 3 concurrent; bundled in AI Pro ($19.99) and Ultra ($124.99) at 5×/20×; GA at I/O 2026-05-19; "Jules V2" waitlist reported by one site, unverified. <https://finance.yahoo.com/news/google-ai-coding-agent-jules-160000019.html>, <https://theaiagentindex.com/agents/jules>
11. OpenAI Symphony: Apache-2.0, 27.7k stars, Linear board as control plane, Codex workers, "engineering preview", OpenAI "does not plan to maintain it as a standalone product"; released 2026-04-28. <https://github.com/openai/symphony>, <https://www.helpnetsecurity.com/2026/04/28/openai-symphony-codex-orchestration-linear/>
12. Nothing newer found that does spec → build → independent multi-vendor ACP reviews → human gate as a small local tool. OpenHands Agent Canvas (ACP workers, automations) is the closest hosted shape; Symphony the closest open-source shape, Linear-first and Codex-only. The gap the factory fills is real but narrow: it is `bigteam` plus a persisted state machine and a PR opener.
13. Sandboxing on macOS (for §3.1): `sandbox-exec` deprecated with no replacement; the bubblewrap-on-Linux / sandbox-exec-on-macOS wrapper pattern (ai-jail). <https://akitaonrails.com/en/2026/03/01/ai-jail-sandbox-for-ai-agents-from-shell-script-to-real-tool/>, <https://code.claude.com/docs/en/sandboxing>

No AGPL code or AGPL-marked design detail was copied; items 5-6 were read for state only.

## 5. Answers to design §11 Q1-Q11 and §12.3 D1-D8

Already ruled in proposal §9 and not re-asked: Paseo as front end (Q9, :757-759); cow for Mac speed, Paseo worktrees portable (:605); CI-first (:954-967); Codex $100 plan and frontier-only (:908, routing.toml:156-178); copilot/gemini CLI/qwen off, cline only Hermes and techno-euphora, omp explicit yes, hermes never (:897-900); vps-primary trusted (Q18).

1. **Q1 location**: `djbclark-ade`, `bin/factory` + `config/factory.toml` + `config/factory/roles/` + `docs/factory.md`; state in `~/.local/state/factory/`. Why: §2.2. Confidence high. Depends on nothing.
2. **Q2 merge policy**: never auto-merge in v1; `ready` = PR opened with CI green, adversary `APPROVE` and code-review `PASS` quoted in the body; a human merges. Why: `~/CLAUDE.md:115-116`, proposal:650-651, coding-factory.md:36,69-75. Confidence high. Not a question.
3. **Q3 approver**: cut. Why: all three reviews; the PR body plus the human is the approver. Confidence high.
4. **Q4 roles → kinds and caps** (proposal, see SF-Q3/Q4): spec-writer `judgment` (Opus high; model-routing 4c.1 "Planning: the brief or plan a Sonnet slice will execute", :563-566); builder `code` via `plan` (agy Claude pool ≥40%, else cursor `default`, zcode `GLM-5.3 --effort high`, claude `sonnet --effort high`; routing.toml:141-257); reviewer-security = `adversary` prompt, `claude --model opus --kind judgment --perm read-only`; reviewer-code `code` kind, `--perm read-only`, vendor ≠ builder's (bigteam Step 6, :900-906): today zcode GLM-5.3 or claude sonnet (codex is frontier-only, opencode-go at 2%). Caps: ≤12 model calls, ≤4 h wall per job, ≤3 jobs/day, 1 parallel job; USD advisory. Confidence medium on the numbers.
5. **Q5 reviewers default-on**: security + code only. Confidence high.
6. **Q6 backlog**: `factory run <brief.md>` only; GitHub Issues later, through Hermes's existing `github-issue-to-pr` skill or a label workflow (coding-factory.md:27, 244-254). Confidence high.
7. **Q7 guard**: in the factory launcher, `refuse` for factory children with no setting; acp-run unchanged (Q9 keeps it as the engine). No `warn` mode and no manual-session registry in v1. Confidence high.
8. **Q8 workspace root**: cow's default `~/.cow/pastures/<repo>/<job>` on Macs; `~/.local/state/factory/worktrees/<repo>/<job>` for the `git worktree` fallback. Why: cow-workspaces:30-31; principle 3 identical paths (proposal:121-124); never inside the checkout. Confidence medium (SF-Q5 decides the primitive).
9. **Q9 sandbox**: no bwrap on macOS (§3.1). v1: reviewers `--perm read-only`; builder yolo in a scrubbed pasture with a minimal env (failover `BASE_ENV_KEYS` pattern, failover.md:65-68) and no push token (the orchestrator pushes); `verify` in CI. A container is not a v1 gate; revisit if a builder is ever pointed at untrusted code. Confidence medium-high; depends on Phase 1's CI workflow.
10. **Q10 phone**: Hermes Telegram is the phone UI (all three reviews, coding-factory.md:139-141); the approve action is GitHub's merge button, since `ready` is a PR; a job with a security `BLOCK` never becomes a PR, so it cannot be merged from a phone; remote dashboard = Paseo's mobile client over the tailnet (proposal:559-561), no Tailscale work. Confidence high.
11. **Q11 digest**: one digest, the existing `hermes-ping` topic; the state root is per repo, `factory status` aggregates. Confidence medium.
12. **D1 guard location**: agree, launcher only.
13. **D2 worktree root**: differ: cow default / XDG, not `../<repo>.wt` (Q8).
14. **D3 `fs` shell function**: cut entirely from v1; `cow-pasture create` and `cowcd` already exist (cow-workspaces:23-31, 107).
15. **D4 containers**: as Q9; "scrubbed env + no push token" stays, "bwrap/container before unattended" goes.
16. **D5 approver**: agree, cut.
17. **D6 phone actions**: v1 D1 = `hermes-ping` alert with why-line and diffstat plus a PR URL; D2 = Hermes `clarify` buttons for `Rework`/`Abandon` (already supported, telegram.md:1400-1411); approve is never a Telegram button.
18. **D7 `verdict.json`**: agree: `{verdict, summary<=80, findings[]}` written beside the acp-dispatch report; missing or unparseable = infra failure, one retry, then `needs-human`, never `CHANGES`.
19. **D8 hygiene**: agree red-only; v1 only refuses a primary checkout at launch; no banner or stale-worktree list until the Paseo panel.

## 6. Questions for djbclark

1. **SF-Q1 Where in the phase plan?** (a) **recommended**: a parallel "Phase F" (F1 orchestrator, F2 reviews + pasture + PR, F3 Paseo panel) starting once Phase 1's first PR (GitHub Actions on `djbclark-ade`) is merged; (b) fold the whole factory into Phase 4; (c) start now, before Phase 0 ends. Changes: (a) adds three rows to §8 and §11; (b) delays it 3-5 weeks; (c) means `verify` has no CI to run on. Reason: the factory needs CI and nothing else from Phases 0-3.
2. **SF-Q2 First pilot repo?** (a) **recommended**: `djbclark-ade` itself (pytest, the Phase 1 workflow); (b) a repo already on `ci/base` (herdr, secretspec-sqlite, sudo-secretspec); (c) hyades-bench. Changes: the `ci/run` command and the `verify` wait time. Reason: the first job should exercise the plan's own CI.
3. **SF-Q3 Spec-writer tier?** (a) **recommended**: Opus `judgment` (planning is Opus's listed use); (b) cheap-first (agy Claude/Sonnet) with `--escalate` on a failed spec check. Changes: Claude weekly draw per job (≈1 Opus call). Reason: the design's own "spec quality drives everything" against the cheap-first rule; only you weigh it.
4. **SF-Q4 Hard caps for v1?** (a) **recommended**: 12 calls, 4 h, 3 jobs/day, 1 parallel; (b) your numbers. Changes: `config/factory.toml` defaults and when `paused-quota` fires. Reason: checked before every dispatch, so wrong values stall or overspend.
5. **SF-Q5 Workspace primitive?** (a) **recommended**: cow pasture on Macs, `git worktree` + per-repo `setup` command elsewhere, one adapter; (b) `git worktree` only (portable, matches Paseo's default); (c) pasture only (Mac-only factory). Changes: whether a Linux (vps-primary) factory is possible in v1; whether `node_modules`/`.env` handling is needed. Reason: the design's §9 complaints are solved by cow but cow is APFS-only.
6. **SF-Q6 Dashboard before Phase 4?** (a) **recommended**: none; `factory status` (table, needs-you first) plus Telegram alerts; the board is a panel in the Phase 4 ADE plugin; (b) the design's D1 static read-only page anyway. Changes: (b) adds a third front end the plan later retires. Reason: §7 decided Paseo; only you can accept the interim gap.
7. **SF-Q7 What `ready` means?** (a) **recommended**: a PR opened by the orchestrator (not the agent) with CI green, adversary `APPROVE` and code `PASS` quoted; you merge on GitHub (phone ok); (b) branch pushed, PR only after you say so in Telegram. Changes: whether Telegram needs an action in v1. Reason: it fixes the merge-authority boundary.
8. **SF-Q8 Reviewer-code vendor rule?** (a) **recommended**: must be a different vendor from the builder's (bigteam Step 6); (b) any read-only-capable agent `plan` picks. Changes: with (a) and agy's Claude pool exhausted, code review lands on zcode or claude; with (b) builder and reviewer may share a vendor. Reason: independence versus headroom is your trade.
9. **SF-Q9 Intake in v1?** (a) **recommended**: `factory run <brief.md>` only; (b) also `gh issue` label from day one. Changes: (b) pulls `gh` state into the resume path (Grok's "second store"). Reason: you asked for GitHub Issues originally (coding-factory.md:1-3).

Not asked (facts or defaults): zazencodes licence (verify before porting prompts, §3.10); Telegram topic (existing `hermes-ping` target); CLI name `factory`.

## 7. Draft plan text (for the proposal; ≤900 words)

### 8b. Phase F: the software factory (a parallel track)

A feature brief goes in; a spec, a branch, two independent reviews, a CI run and an opened pull request come out. The factory is a state machine over `acp-dispatch` records, not a new runner: every role is one `acp-dispatch` slice with the report contract, routed by `route_agent.py plan` under §11, resumed and reaped by the engine. It starts after Phase 1's first PR (the GitHub Actions workflow) and runs beside Phases 2-3. Source: `docs/software-factory-design.md` v2 §12.4-12.5, corrected by the two frontier reads of 2026-10-19.

**Scope, v1.**

1. `bin/factory run <brief.md> [--repo ~/src/<name>]`, `status`, `rework <job> -m`, `abandon <job>`, `retry <job>`, `gc`. Config `config/factory.toml` (kinds, perms, caps); role prompts `config/factory/roles/`. State `~/.local/state/factory/<repo>/<job>/`: `events.jsonl` (source of truth), `job.json` (snapshot), `commands.jsonl` (CLI inbox), the acp-dispatch records and reports, per-round `diff.patch`, `diffstat.json`, `verdict.json`; a per-job lock. Nothing is written into the target repo.
2. Roles: spec-writer (`judgment`), builder (`code`), reviewer-security (the `adversary` prompt, `claude --model opus --kind judgment --perm read-only`), reviewer-code (`code`, `--perm read-only`, vendor differs from the builder's). Reviewers write `verdict.json` `{verdict, summary<=80, findings[]}` beside their report; the orchestrator reads only that. Failure of a reviewer is an infra failure: one retry, then `needs-human`, never `CHANGES`.
3. Workspace: `cow-pasture create factory-<job> --source <repo> --branch factory/<job>` on Macs (secrets scrubbed, dependencies carried); `git worktree` plus a per-repo `setup` command elsewhere; root outside the checkout; `base_sha` pinned; the launcher refuses a primary checkout. Builder runs yolo in the pasture with a minimal env and no push token; the orchestrator pushes.
4. `verify` is a CI run: push `ci/run/factory-<job>-<sha8>` (the `ci/base` recipe) and wait; a focused local check only where `load-watch ci check` allows it.
5. States: `queued → spec → build → verify → review(N) → ready | needs-human → merged | abandoned`, side states `failed`, `paused-quota`, `cancelled`. Retry and unpause re-enter the state that stopped. `max_rounds` 3. All PASS plus CI green = `ready`: the orchestrator opens the PR with both verdicts quoted; djbclark merges. A security `BLOCK` at round 3 is `needs-human` with no PR.
6. Guards checked before every dispatch: ≤12 model calls and ≤4 h per job, ≤3 jobs per day, one job at a time; per-slice `--timeout` from the remaining budget; USD shown as reported plus N unreported. Quota stops use the engine's in-place resume; a reroute is recorded, never silent.
7. Notifications: one `hermes-ping` per transition into needs-you (job title, why-line, diffstat, PR URL); Hermes `clarify` buttons for `Rework`/`Abandon` in F2. No static dashboard; the board is a panel of the Phase 4 ADE plugin (dispatch timeline rows).

**Cut from v1:** approver LLM, UX/UI reviewers, spec-kit/OpenSpec bake-off (plain markdown spec), GitHub Issues intake, fallback agents, parallel jobs, kanban, SSE, model-comparison view, `fs`/session registry, pre-commit hook, `jj`, containers, any auto-merge.

**Milestones as gates.**

1. **F1 orchestrator (1 week).** Single job, sequential, acp-dispatch-driven; `events.jsonl`; guards; the kill test. Gate: `kill -9` the orchestrator in every state and mid-slice, restart, and the job completes with no duplicate side effect (one PR, one ping), no orphan process (`acp-dispatch reap` clean), the pasture at the recorded `head_sha`.
2. **F2 reviews and PR (1 week).** Two parallel reviewers, rework loop, pasture lifecycle with `gc --dry-run` default, CI `verify`, PR opener, Telegram alert and buttons. Gate: one real brief on `djbclark-ade` runs to `ready` from the CLI, with the adversary verdict in the PR body, and djbclark merges it from GitHub mobile.
3. **F3 Paseo panel (in Phase 4).** Factory jobs as rows in the ADE plugin: needs-you first, running with last activity text, since-you-last-looked; `rework` as a Command Center item writing `commands.jsonl`. Gate: the T5 pilot includes one factory job.
4. **Later (Phase 5+):** GitHub Issues intake via Hermes's `github-issue-to-pr` skill or a label workflow; merge gates (rulesets, required checks) before any `ready → merged` automation; a Linux factory on vps-primary.

**Routing per role (§11 rows to add).** spec-writer: `claude opus`, `judgment`, high, 200k, Claude weekly. builder: `plan --kinds code` (agy Claude pool ≥40%, else cursor `default`, zcode `GLM-5.3`, claude `sonnet`), high. reviewer-security: `claude opus --perm read-only`, `judgment`, high. reviewer-code: `zcode GLM-5.3 --perm read-only` or `claude sonnet --perm read-only`, whichever differs from the builder. No `frontier` slice inside a job; one optional `codex gpt-6-astra --role advise` read of the whole factory before F2 merges, per the phase-gate row.

**Dependencies.** Phase 1 PR 1 (CI workflow) for `verify`; `acp-dispatch` unchanged; `cow-pasture` on Macs; Phase 4's plugin for the board. No dependency on Phases 2-3.

**Test plan.** The F1 kill test above; a quota-stop drill (force `NO-REPORT: quota` on the builder and watch the in-place resume); a reviewer-timeout drill (no rework round consumed); a dirty-primary-checkout launch (refused); a PR opened twice after a crash (refused by the outbox event id).

(Word count ≈ 760.)

## 8. Cost per job (estimates unless marked read)

1. **Model calls.** Spec 1; build 1 + ≤2 rework resumes; reviews 2 per round × ≤3 rounds = 6; total ≤10, cap 12 with retries. Verify ≤3 CI runs on free GitHub runners (not quota).
2. **Pools drawn** (read from `~/.cache/aiuse/snapshots/latest.json`, collected 2026-10-19 20:11 UTC, since Bash is unavailable in this run): Claude Max weekly 47% left, 5h 93% left (lines 164-167, 89-93) takes spec, adversary review ×≤3 and any Sonnet build; `[dispatch.estimate_floor] claude = 8.0` percent of the binding window per slice (routing.toml:117-120) gives roughly 4-5 Claude slices ≈ 35-40% of one 5-hour window per job, weekly draw unknown. antigravity Claude/GPT weekly 1% left, exhausted until 2026-10-24 18:18 UTC (lines 72-75): no builder there this week. Cursor Pro+ 68.5% total (395); z.ai lite weekly 36% (691); codex `prolite` weekly 96% (215) but frontier-only; opencode-go 2% (627) unusable; copilot 0% (260), a reserve anyway; omp 99.7% credits (548), gated.
3. **Wall-clock.** acp-dispatch default `--timeout` 2400 s per slice (bigteam:580). Sequential estimate: spec 5-10 min, build 10-40 min, reviews in parallel 5-15 min, CI 5-10 min per round (Plektra's Gradle run was 7 m 20 s, forgejo-ci:55; a pytest repo should be shorter): one job ≈ 1-3 h, bounded by the 4 h cap. These are estimates, not measurements; F1's gate should record the real figures via `acp-dispatch outcome`.

## 9. Evidence log

Files (repo-relative to `~/src/djbclark-ade` unless absolute):

1. `docs/software-factory-design.md:3-5, 26-57, 101-116, 141-154, 161-162, 198-216, 223-273, 276-556, 559-577, 588-639, 643-663, 668-699, 704-826`.
2. `docs/software-factory-reviews/claude-opus-round1.md:15-93, 95-113`; `claude-opus-worktree.md:13-45`; `claude-opus-dashboard.md:15-97`; `agy-full-and-worktree.md:11-75`; `agy-dashboard.md:9-55`; `agy-partial-interrupted.md:8-16`; `cursor-grok-full-and-worktree.md:9-39`; `cursor-grok-dashboard.md:11-25`.
3. `docs/ade-everywhere-proposal.md:1-5, 30-77, 78-148, 237-333, 408-432, 555-647, 648-716, 717-856, 857-889, 891-981, 983-1077`.
4. `docs/coding-factory.md:1-39, 44-53, 69-75, 102-148, 191-264`.
5. `bin/acp-dispatch:2-45, 47-61, 63-74, 76-136, 143, 175-179, 265-266, 806-810`.
6. `tools/acp-run/README.md:28-74, 177-185, 186-202, 203-283, 455-497, 499-535, 543-632, 634-652`; `tools/acp-run/acp-run:543-586`.
7. `skills/bigteam/SKILL.md:18-59, 61-85, 87-136, 138-194, 385-423, 425-454, 470-527, 529-683, 736-784, 900-906`.
8. `skills/model-routing/SKILL.md:28-69, 71-116, 209-236, 240-356, 385-388, 466-668, 670-689`.
9. `config/routing.toml:14-49, 66-128, 141-257, 292-304, 315-334, 339-359`.
10. `skills/cow-workspaces/SKILL.md:14-35, 37-58, 60-87, 89-108`; `docs/orca-integration.md:122-169, 193-222`.
11. `docs/failover.md:9-69, 71-102, 142-196`; `docs/jev.md:92-101, 133-170`; `docs/queue.md:6-18, 62-92`.
12. `bin/load-watch:2-49`; `~/ops/site-private/bin/bg:19-33, 42-50`.
13. `skills/forgejo-ci/SKILL.md:15-18, 30-77, 79-91, 133, 161-194`.
14. `skills/tell-chief-of-staff/SKILL.md:9-29`; `~/.local/bin/hermes-ping:1-33, 102-110`; `~/.hermes/hermes-agent/website/docs/user-guide/messaging/telegram.md:1390-1411, 1419`.
15. `~/.claude/agents/adversary.md:1-26`; `~/CLAUDE.md:77-81, 89-93, 101-116, 133-145` (items 21, 25, 26, 28, 32-34, 36, 37); `AGENTS.md:44-72, 76-83`.
16. `~/.cache/aiuse/snapshots/latest.json:1-10, 14-78, 82-167, 175-216, 223-261, 269-396, 403-451, 458-496, 504-549, 556-628, 636-692`.
17. Glob checks 2026-10-19: `/opt/homebrew/bin/bwrap` absent; `/usr/bin/sandbox-exec` present; `/usr/local/bin/container` absent; `/opt/homebrew/bin/cow` absent by that Glob (cow-workspaces:13 says `/opt/homebrew/bin/cow`; the wrapper's presence was not re-verified here, uncertain); `tools/factory*` absent.

URLs (all fetched or searched 2026-10-19):

18. <https://github.com/zazencodes/zazencodes-season-3/tree/main/src/software-factory-claude-code>
19. <https://github.com/github/spec-kit/releases>; <https://tproger.ru/news/github-vypustil-spec-kit-1-0-11-s-idempotentnym-dobavleniem-kata>
20. <https://github.com/Fission-AI/OpenSpec/releases>; <https://releasebot.io/updates/fission-ai/openspec>
21. <https://gittrend.io/repo/automazeio/ccpm>; <https://github.com/Ninegd/ccpm>
22. <https://rywalker.com/research/auto-claude>; <https://blog.brightcoding.dev/2026/07/04/aperant-the-revolutionary-multi-agent-coding-framework-every-developer-needs>
23. <https://github.com/smtg-ai/claude-squad>
24. <https://docs.superset.sh/overview>; <https://superset.sh/blog/working-with-worktrees-in-superset>; <https://github.com/hegarty-tech/superset>
25. <https://openhands.dev/blog/use-any-coding-agent-in-openhands-with-acp>; <https://docs.openhands.dev/openhands/usage/run-openhands/acp>; <https://pypi.org/project/openhands-ai/1.11.0/>
26. <https://github.blog/changelog/label/copilot/>; <https://github.blog/changelog/month/09-2026/>
27. <https://finance.yahoo.com/news/google-ai-coding-agent-jules-160000019.html>; <https://theaiagentindex.com/agents/jules>; <https://aiweekly.co/alerts/google-jules-v2-targets-claude-code-with-goal-driven-coding-agent>
28. <https://github.com/openai/symphony>; <https://www.helpnetsecurity.com/2026/04/28/openai-symphony-codex-orchestration-linear/>; <https://devops.com/openai-debuts-symphony-to-orchestrate-coding-agents-at-scale/>
29. <https://code.claude.com/docs/en/sandboxing>; <https://akitaonrails.com/en/2026/03/01/ai-jail-sandbox-for-ai-agents-from-shell-script-to-real-tool/>; <https://lib.rs/crates/ai-jail>
30. <https://github.blog/changelog/label/copilot-coding-agent/> (404 on fetch)

DECIDED: this run had no Bash tool, so quota figures were read from the aiuse snapshot cache (collected 2026-10-19 20:11 UTC) instead of `aiuse --available --json`, and the Apple `container` binary location, the `cow` binary path and GitHub branch-protection state (coding-factory.md, 2026-09-21) were not re-verified; each is marked uncertain where used.

DONE
