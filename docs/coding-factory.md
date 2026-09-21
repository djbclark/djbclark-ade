# Unattended coding factory — evaluation and the improved prompt (2026-09-21)

The operator pasted a prompt titled *"Implement OpenHands coding factory
(solo OSS, no human coding/merging)"* and asked three things: improve it,
compare it with what this machine already runs, and look at other systems.
This doc is the answer. Everything in it was probed or fetched on
2026-09-21; product facts carry that date and will rot.

**Verdict in one paragraph.** The prompt describes four layers: chat front
door → GitHub Issue trigger → sandboxed coder → CI-gated auto-merge. This
machine already has the first (Hermes, live on Telegram/Signal) and the
third (nine coding CLIs on PATH, Orca to dispatch them) and has *none* of
the second or fourth: nothing listens to issue events, and no repo has
branch protection, rulesets or auto-merge enabled. OpenHands would add a
hosted trigger plus a sandboxed runner, at the cost of a new vendor, a
10-conversation/day free tier, and BYOK API spend that the routing policy
has retired. The trigger is a ten-line GitHub Actions workflow and the gate
is repo configuration, so the cheaper move is to build those two layers on
GitHub itself and point them at coders already paid for (Copilot cloud
agent, Jules free tier, or Hermes + Orca locally). The improved prompt
below is written that way: vendor-selected in Phase 0, not baked in.

## 1. What this machine already has

| Layer of the factory | Present here | State on 2026-09-21 |
|---|---|---|
| Chat front door | **Hermes Agent** gateway (launchd `com.stayturgid.hermes-gateway`), Telegram + Signal enabled, Discord configured; 29 cron jobs | Live. Already has the `github-issue-to-pr` skill (issue → tested PR, with a sabotage-run step that proves the regression test bites) and `gh` on PATH. Upstream also ships an optional `openhands` skill that wraps the **local** OpenHands CLI, not OpenHands Cloud. |
| System of record | GitHub Issues (`gh` authed as djbclark, scopes `repo, workflow`) | Live, but nothing *listens* to issue events. |
| Trigger (issue → agent) | none | **Gap.** Hermes cron polls things; no webhook/label trigger exists. Hermes cron does support webhook-fired jobs, so the gap is wiring, not capability. |
| Coders | claude, codex, copilot CLI 1.0.86, cursor-agent, devin, opencode, crush, grok, agy on PATH; ~25 agents in Orca's roster | Live. OpenHands, gemini, droid, amp, kilo, jules are **not** installed. |
| Orchestration | **Orca** macro-graph (task DAG, `worker_done`, heterogeneous fleet verified); Claude Code dynamic workflows | Live. Coordinator is an agent session, not an event: Orca has **no** GitHub-webhook or issue trigger (open upstream requests #11040, #12400, #20646). Cow-pasture dispatch still stalls on Claude's trust dialog. |
| Continuous controller | **Ralph TUI + beads** | **Dormant.** Binary absent from PATH and `~/.bun/bin`; its four controller workspaces lived under `~/src/ops-worktrees/`, deleted 2026-08-23. Config survives at `~/.config/ralph-tui/`. README's "third altitude" claim needs this caveat. |
| Workspaces | `bin/cow-pasture` (APFS CoW, secrets scrubbed) | Live. |
| CI | stayturgid: `collection-build`; Shizuku fork: Android CI + Build App; site-djbclark: monitor-only workflows, **no test CI**; djbclark-ade: none | Partial. |
| AI review | Copilot code review runs on stayturgid PRs (dynamic workflow, last runs 2026-07-30); `coderabbit-feeder` for CodeRabbit | Live but advisory: nothing is a *required* check. |
| Merge gate | branch protection / rulesets / `allow_auto_merge` | **Absent on every repo.** djbclark-ade is private on a free plan, so rulesets and branch protection are unavailable there without Pro or going public. |
| Kill switch | none | **Gap.** |
| Cost policy | model-routing: free and wasted pools first, claude/codex for judgment, **prepaid API spend retired** | Binding constraint on any BYOK option. |

## 2. The pasted prompt against that inventory

### 2.1 Facts in the prompt, checked

| Claim | Status | Detail |
|---|---|---|
| OpenHands Agent Canvas runs Claude Code / Codex / Gemini CLI as ACP workers | **True** | Blog 2026-06-18, docs `agent-canvas/acp-agents`. Subscription login is auto-detected only when the agent server runs on the machine where the CLI is signed in; Cloud sandboxes need API keys. ACP workers inside *automations* are not documented. |
| Hermes has an optional `openhands` skill | **True, but local-only** | `official/autonomous-ai-agents/openhands` drives the OpenHands CLI via `uv tool install openhands`. It does not talk to OpenHands Cloud. |
| OpenHands Cloud has a Slack app with `@openhands` | **True** | Cloud only; each member links their account; only the originator can follow up. |
| Automations can trigger on "Issue labeled `ready`" | **True in capability** | `issues.labeled` + JMESPath filter on the label. Reliability bug OpenHands/automation#107 (a `pull_request.labeled` automation on their own repo never fired) has been open since 2026-05-11. Org repos need a team org and a "claimed" GitHub org. |
| OpenHands can enable GitHub auto-merge on its PRs | **Not documented** | No setting or doc. Only possible as a prompt-level `gh pr merge --auto` inside the sandbox, which then hits the GitHub regression in 2.3. |
| "OpenHands Cloud Pro" | **Does not exist** | Plans are Open Source $0, Individual $0 (1 user, **10 daily conversations**, BYOK or at-cost models), Enterprise. The paid Growth plan was discontinued in 2026. |
| "Grok Ship" | **Does not exist** | Real products are Grok Build (CLI harness) and Grok Bot (always-on teammates, beta). |
| Sweep, Codegen as alternatives | **Defunct** for issue→PR | Sweep pivoted to a JetBrains assistant; Codegen was acquired by ClickUp and shut down 2026-01-16. |

### 2.2 What OpenHands would add, and duplicate

1. **Adds:** a hosted GitHub App trigger (`issues.labeled` etc.), a sandboxed
   runner per conversation, a Slack front door, a bot identity.
2. **Duplicates:** the chat front door (Hermes already spans Telegram,
   Signal, Discord and 20+ platforms), the coders (all installed), the
   orchestration (Orca), the issue-to-PR discipline (Hermes skill).
3. **Conflicts:** BYOK on Cloud means API-key spend, which standing order 7
   retired; the Individual tier caps at 10 conversations a day; local
   self-host would reuse subscriptions but then Hermes + Orca already do
   that job with tools that are wired in.
4. **Does not provide:** the merge gate. That is GitHub configuration plus a
   merge workflow whatever coder is used.

### 2.3 The gate the prompt assumes is broken

Since 2026-03-25 GitHub refuses to *enable* auto-merge until every
requirement is already satisfied (HTTP 422, `gh pr merge --auto` fails with
"Auto merge is not allowed"). Staff said a fix was queued on 2026-03-26; the
discussion shows it unfixed through September 2026. So "open PR → enable
auto-merge → wait for CI" fails at step two. Working alternatives:

1. A merge workflow on `workflow_run` completion that checks the PR's state
   and calls `PUT /repos/{o}/{r}/pulls/{n}/merge`. No new vendor.
2. **Kodiak** (still maintained, pushed 2026-09-11): merges on label or
   label-less when checks pass.
3. **Mergify**: free for OSS and ≤5 contributors, includes merge queue.

Also: a `do-not-merge` label blocks nothing by itself. It needs a required
check that fails while the label is present. The prompt says "document that
presence blocks merge", which would be a false belief.

### 2.4 Other weaknesses of the prompt as written

1. It chooses the vendor before Phase 0 discovers anything.
2. "CI green" is the only gate, but the coder writes the tests. Nothing stops
   a bot from weakening a test to pass. Needs a rule for PRs that touch both
   tests and source (sabotage proof in the PR body, or an AI review check).
3. No blast-radius limits: the bot could edit `.github/workflows/**`,
   dependency manifests, or secrets-adjacent files and have that auto-merge.
4. No loop prevention: bot-authored PRs and comments can re-trigger the bot.
5. No concurrency or budget cap: one label sweep could start N runs.
6. Private repos on a free plan cannot have rulesets at all. Phase 0 must
   detect this and stop, not proceed to Phase 1.
7. Retry, stale-PR and failure-notification policy are absent.
8. It uses plain bullets. Every list here is numbered (standing order 5).

## 3. Other systems considered (2026-09-21)

| System | Issue → PR intake | Merge | Cost model | Fit here |
|---|---|---|---|---|
| **GitHub Copilot cloud agent** | Assign issue to Copilot (any repo you can write to); Automations (schedule, issue opened, comments) need a **private/internal** repo | Requester's approval doesn't count; ruleset requires extra approval for unattributed Copilot PRs by default (can be turned off); **Copilot code review approvals count toward required approvals since 2026-09-01, opt-in** | Already paid; premium requests are a chronically-wasted pool | **Best first coder.** Native, no infra, no API key. Public repos: trigger by a tiny `issues.labeled` workflow that assigns Copilot. |
| **Google Jules** | Label `jules` via GitHub App, or `google-labs-code/jules-action` on `issues.labeled`, cron, CI failure | No | Free 15 tasks/day, 3 concurrent; AI Pro 100/day | **Free-pool coder** that matches routing rule 1. |
| **Kilo Code cloud agents** | Webhook on issue created/labeled `ai-implement`; `@kilocode-bot` | Not documented | Free for public repos; compute per second | Free-pool option for the public ops repos. |
| **Claude Code GitHub Action** | `@claude`, issue assignment, or automation mode on `issues: [opened]` | Not documented | API key / Bedrock / Vertex; README does not mention subscription OAuth | Conflicts with retired API spend unless subscription auth is confirmed. |
| **Codex cloud / GitHub app** | `@codex` on PRs, auto-review; issue intake not documented | No | ChatGPT plan | Second reviewer, not the issue coder. |
| **Cursor cloud agents + Automations** | Label changes, issue comments, CI completion, webhooks; **Bugbot** can be a required check | Bugbot cannot approve | Cursor Pro already paid; cloud-agent usage billed | Good **required-check reviewer**; coder for `.cursor`-configured repos. |
| **Devin** | `/devin` in PR comments, Linear/Slack/CI triggers; machine identity by default | Recommends branch protection first | Pro $20 / Max $200; paid and dormant here | Operator decided dormant 2026-08-23; not relitigated. |
| **OpenAI Symphony** | Polls one tracker (Linear in the demo); one workspace per issue; bounded concurrency; restarts stalled agents | Human accepts | Apache-2.0, Elixir reference, 27k stars, "engineering preview" | Closest open-source shape to the ask, but Linear-first and human-accept. |
| **OpenHands** | GitHub App label/mention, Cloud event automations, custom webhooks | Not documented | $0 with 10 convos/day or BYOK; self-host free | Adds trigger + sandbox; duplicates the rest. See 2.2. |
| **Factory droids** | `@droid`, issues opened/assigned (not labels) | Explicitly cannot merge | `FACTORY_API_KEY` | API spend. |
| **Firstmate** | None (local captain + crew over Claude Code, Codex, OpenCode, Cursor, Grok in worktrees) | `+yolo` merge modes | Local, BYO subscription | Overlaps Orca; no issue intake. |
| **Ralph TUI** | prd.json + Beads only | Not documented | Local | Dormant here; not a GitHub Issues system. |
| **Conductor, Amp, Augment, Zencoder** | No issue intake / paid consumption | | | Not a fit. |
| **Merge layer:** Kodiak, Mergify, Renovate `platformAutomerge` | | Kodiak and Mergify merge on checks; Renovate for deps with `minimumReleaseAge` | Kodiak OSS; Mergify free ≤5 contributors | Any of these dodges the 422 regression. |
| **Review-as-check:** CodeRabbit (`request_changes_workflow`), Greptile, Graphite Agent, Bugbot, Claude Code Review (always neutral; self-gate via check-run parsing) | | | | Pick one that can *fail* a check: Bugbot or CodeRabbit. |

## 4. Recommendation

1. **Build the two missing layers on GitHub, not on a new vendor.** A
   `factory.yml` workflow handles the trigger (`issues.labeled: ready` →
   assign Copilot, or apply the `jules` label), a `guard` job enforces
   blast-radius rules and the `do-not-merge` label, and a merge workflow on
   `workflow_run` completion does the merge. Rulesets on the public ops
   repos require the checks with zero approvals.
2. **Coders, in routing order:** Copilot cloud agent (paid, wasted pool),
   Jules (free 15/day) for small issues, Hermes `github-issue-to-pr` on a
   webhook-fired cron job for anything needing local context or a specific
   CLI. Add a second coder only after the first has merged ten PRs cleanly.
3. **Make one AI review a required, failing-capable check** (Bugbot, or
   CodeRabbit with `request_changes_workflow`). Turn on Copilot review
   approvals (2026-09-01 feature) so a Copilot-authored PR can satisfy the
   "additional approval" rule without a human, or disable that rule
   explicitly and rely on checks.
4. **Hermes stays the front door and the notifier.** It already files
   issues with `gh`, and a GitHub → Hermes webhook job posts merged/failed
   events to Telegram. No Slack, no OpenHands Slack app.
5. **Revisit OpenHands only if** the machine needs a hosted sandbox per run
   that Orca and cow pastures cannot give, or the operator wants ACP workers
   under one UI. Self-hosted Canvas would reuse subscriptions; Cloud would
   not.
6. **Start on stayturgid**, which already has real CI and Copilot review.
   site-djbclark first needs a test workflow; djbclark-ade needs Pro or
   public before any gate is possible.

## 5. The improved prompt

Paste into a fresh agent session on the target repo. It is coder-agnostic:
Phase 0 picks the coder from what is installed and paid for, and the merge
gate is built to survive GitHub's auto-merge regression.

````markdown
# Stand up an unattended coding factory (solo OSS, no human coding or merging)

## Goal
An issue labeled `ready` becomes a merged commit on the default branch with
no human writing code, reviewing diffs, or clicking Merge. I make product
decisions only: open issues, label them, use the kill switches.

## Hard constraints
1. GitHub Issues are the system of record. Every run links issue ↔ PR both ways.
2. Nothing merges without required checks that can actually fail. "Advisory"
   review bots do not count as a gate.
3. No new API-key spend. Prefer coders already covered by a subscription or
   a free tier. If a step needs an API key, stop and ask.
4. The bot may not modify `.github/workflows/**`, rulesets, repository
   settings, secrets, or CODEOWNERS. A PR touching those fails the guard.
5. One in-flight factory PR per issue; at most N (default 3) in flight per repo.
6. Every list in your replies is numbered so I can say "do 2".

## Non-goals
1. No human PR approval or merge click.
2. No auto-merge without real tests.
3. No hosted vendor added when a workflow file does the same job.

## Architecture
```
Chat front door (existing Hermes, or none)          → gh issue create + label `ready`
GitHub Actions `factory.yml` on issues.labeled       → dispatch to the chosen coder
Coder (Copilot cloud agent | Jules | Hermes/Orca worker | OpenHands, chosen in Phase 0)
                                                     → branch + PR referencing the issue
Required checks: ci + guard + one AI review that can fail
Merge workflow on workflow_run completion            → PUT /pulls/{n}/merge (squash)
                                                     → default branch; comment on issue
```

## Phase 0 — Discover (report, then proceed unless blocked)
1. Repo facts: greenfield or existing; language/runtime; default branch;
   existing CI workflows and whether any runs tests; visibility.
2. **Plan gate:** rulesets and branch protection are unavailable on private
   repos without GitHub Pro. If the repo is private and the plan is free,
   stop and ask: go public, upgrade, or pick another repo.
3. Coder availability, probed not assumed: Copilot plan and whether the
   coding agent is enabled (`gh api /user`, try assigning a scratch issue);
   Jules app or `JULES_API_KEY`; local Hermes/Orca reachable; OpenHands
   installed or Cloud account. Rank by: no API spend > native GitHub
   integration > already installed. Pick one primary coder. Say why.
4. Whether GitHub auto-merge currently enables on an unsatisfied PR
   (`gh pr merge --auto` on a scratch PR). Expect a 422 (regression since
   2026-03-25); if so, use the merge workflow in Phase 1, not `--auto`.
5. Bot identity: prefer the coder's own machine identity (Copilot, Jules,
   OpenHands bot). If a PAT is needed, create a fine-grained one scoped to
   this repo with contents, pull-requests, issues write only. Never my
   personal token in a workflow.

## Phase 1 — Gate first, before any coder runs
1. Add or fix CI: one workflow that installs deps and runs tests, lint and
   typecheck if cheap. If no tests exist, the first factory issue is
   "add smoke tests + CI"; do not lock the gate on an empty test job.
2. Add `guard` job (same or separate workflow) that fails when:
   a. label `do-not-merge` is present;
   b. the diff touches `.github/workflows/**`, `CODEOWNERS`, `.github/rulesets/**`,
      or dependency manifests/lockfiles unless the issue carries label `deps-ok`;
   c. the diff changes test files without the PR body containing a
      "Sabotage run:" section showing the new test failed on pre-fix code;
   d. changed lines exceed a cap (default 800) unless the issue has `large-ok`;
   e. repository variable `FACTORY_PAUSED` is `1`.
3. Add one AI review as a required check that can fail (Cursor Bugbot with
   fail-on-unresolved, or CodeRabbit with `request_changes_workflow: true`).
   If Copilot is the coder, either enable "Copilot code review can approve"
   (2026-09-01, opt-in) or explicitly disable the ruleset "Require an
   additional approval for unattributed Copilot PRs". Record which.
4. Ruleset on the default branch: require PR; require status checks
   `ci`, `guard`, `<review>`; `required_approving_review_count: 0`; block
   force-push; enable `allow_auto_merge` and `delete_branch_on_merge` on
   the repo.
5. Merge workflow: on `workflow_run` completed (and `check_suite` completed),
   find the PR, verify it is factory-authored, mergeable, all checks green,
   no `do-not-merge`, then squash-merge via the REST API and comment the
   commit SHA on the issue. Fall back to Kodiak or Mergify if you prefer a
   maintained tool; say which.
6. **Verify with scratch PRs before Phase 2**, and paste evidence:
   a. red CI → not merged;
   b. green CI → merged with no human click;
   c. green CI + `do-not-merge` → not merged; label removed → merged;
   d. green CI that edits `.github/workflows/x.yml` → guard fails;
   e. `FACTORY_PAUSED=1` → nothing dispatches on a new `ready` label.

## Phase 2 — Trigger and coder
1. `factory.yml` on `issues: [labeled]` with `if: label == 'ready'`:
   skip if actor is a bot, if `FACTORY_PAUSED=1`, if an open factory PR
   already references the issue, or if in-flight count ≥ N. Then dispatch:
   a. Copilot: assign the Copilot actor to the issue via GraphQL
      `replaceActorsForAssignable`;
   b. Jules: add the `jules` label (App) or call `jules-action`;
   c. Hermes/Orca: `repository_dispatch` or webhook to the local receiver,
      which runs the `github-issue-to-pr` skill in a fresh cow pasture;
   d. OpenHands: label `openhands`, or a Cloud event automation on
      `issues.labeled` filtered to `ready`.
   Comment on the issue: which coder, when, how to cancel.
2. Coder instructions (in `AGENTS.md`/`CLAUDE.md`/`.github/copilot-instructions.md`):
   branch `factory/<issue>-<slug>`; PR body with `Closes #<n>`, approach,
   tests, risk, and the "Sabotage run:" section when tests change; never
   touch guarded paths; stop and comment if the issue is ambiguous.
3. Failure policy: red CI → coder gets one fix cycle via a comment mention;
   still red after 2 → label `needs-human`, notify, stop. Stale PR > 72h →
   close with comment, remove `ready`.
4. Notification: on merge or `needs-human`, post to the operator's channel
   (Hermes/Telegram if available; else issue comment only).

## Phase 3 — Chat front door (optional; skip if Hermes already exists)
1. If Hermes is running: no install. Confirm it can `gh issue create --label ready`
   and that a webhook-fired cron job receives GitHub events for notification.
2. Else pick the coder's own chat surface (Copilot in GitHub, OpenHands
   Slack) and stop there. Do not add a second bot.

## Phase 4 — Operating contract
Write `docs/agent-factory.md`: how to request work; what merges and why;
kill switches (`do-not-merge` label, `FACTORY_PAUSED=1`, disable the
ruleset's required check, disable the merge workflow); what I still decide;
cost notes (which pools each coder draws from); a dated "verified on" line
per Phase 1.6 check.

## Success criteria (each with pasted evidence)
1. Ruleset live: PR required, checks required, zero approvals.
2. `ci`, `guard`, and the AI review are required and each has been seen to fail.
3. Phase 1.6 a–e all demonstrated.
4. `ready` label → coder run → PR → green → merged, on a real small issue.
5. Issue ↔ PR linked both ways; issue closed by the merge.
6. Kill switches tested, not described.
7. Runbook committed.

## When blocked
Ask only for: GitHub plan/visibility decision, coder login or App install,
a fresh token if a scratch test proves one is needed, stack confirmation.
Otherwise choose defaults, say which, and proceed.
````

## 6. Sources (fetched 2026-09-21)

1. OpenHands: `openhands.dev/blog/use-any-coding-agent-in-openhands-with-acp`,
   `docs.openhands.dev/openhands/usage/agent-canvas/acp-agents`,
   `…/automations/event-automations`, `…/cloud/github-installation`,
   `…/cloud/slack-installation`, `openhands.dev/pricing`,
   `github.com/OpenHands/automation/issues/107`.
2. Copilot: `docs.github.com` cloud-agent create-automations;
   `github.blog/changelog/2026-09-01-copilot-code-review-can-now-approve-pull-requests`;
   `…/2026-08-03-trigger-copilot-automations-with-comments`.
3. Auto-merge regression: GitHub community discussions #190610, #162623, #167357.
4. Jules: `google-labs-code/jules-action` README; Jules pricing/limits page.
5. Cursor: `cursor.com/docs/cloud-agent/automations`, `cursor.com/docs/bugbot`.
6. Claude Code: `anthropics/claude-code-action` README and `solutions.md`;
   `code.claude.com/docs/en/code-review`.
7. Symphony: `github.com/openai/symphony`. Kodiak: `github.com/chdsbd/kodiak`.
   Mergify pricing page. Hermes: `hermes-agent.nousresearch.com/docs` (skills,
   cron). Orca issues #11040, #12400, #20646.
8. Local probes: `gh api repos/djbclark/<repo>` (auto-merge, rulesets,
   protection, workflows), `~/.hermes/config.yaml` and `cron/jobs.json`,
   `which` over the coder CLIs, `~/.config/ralph-tui/`.
