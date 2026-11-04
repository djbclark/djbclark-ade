# Agent TUI consolidation plan (2026-11-04; proposal, djbclark rules on it)

**Summary.** This Mac has 21 agent CLIs/TUIs installed (plus the general `venice` CLI). Eleven of them
ran an `acp-dispatch` slice in the last 30 days, and four of those eleven did 89% of the work. The
plan keeps **10**: the five vendor clients the monthly plans need (claude, agy, cursor-agent and
grok are the only allowed way to spend theirs; codex stays for `bin/local-review`, B2), the two Claude/OpenAI API-credit harnesses (omp, pi), one open
multi-provider harness that absorbs every pool that is not vendor-locked (opencode), the messaging
gateway (hermes), and cline as the ClinePass client behind Dann's substrate (operator, 2026-10-23).
It retires or folds the other 11, including both new installs (`venicecode` and `dsh`). Every live
quota pool keeps a client. Nothing has been removed; section G says which steps are inside
djbclark-ade and which need djbclark's yes (standing order 11).

Snapshot sources, all taken 2026-11-04 10:10-10:40 EST: `aiuse --json`, `acp-run --list`, each
binary's `--version`, the 1,736 job records under `~/.local/state/bigteam/*/jobs/` (all from the
last 30 days), `paseo ls -a -g` (671 agents, archived included) and Paseo's provider list. Numbers
are dated; re-probe before acting on them.

## A. What is installed

"Dispatches" are acp-dispatch slices in the last 30 days (ok = exit 0 or a done status). "Code
files" counts files under `bin/`, `tools/`, `skills/`, `claude/`, `config/` and `tests/` (not
Markdown) that name the agent: the upkeep each one costs this repo.

| # | Agent (version) | Quota pool it spends | ACP / Paseo provider | Dispatches (ok) | Paseo agents | Code files | Verdict |
|---|---|---|---|---|---|---|---|
| A1 | `claude` 2.1.318 | Claude Max (subscription) | yes / yes | 205 (197) | 473 | 177 | keep (C1) |
| A2 | `codex` 0.166.0 | ChatGPT `prolite` ($100) | yes / yes | 160 (125) | 78 | 132 | keep (C2) |
| A3 | `agy` 1.5.0 | Google AI Pro (3 families) | Google's `agy_acp_server.par` / yes | 100 (77) | 4 | 44 | keep (C3) |
| A4 | `cursor-agent` 2026.10.22 | Cursor Ultra | yes / yes | 37 (34) | 2 | 36 | keep (C4) |
| A5 | `grok` 1.0.70 (Grok Build) | SuperGrok | yes / yes | 15 (13) | 0 | 47 | keep (C5) |
| A6 | `omp` 18.16.0 | Claude API credits ($250/month grant) | yes / yes | 1,077 (1,061) | 81 | 61 | keep (C6) |
| A7 | `pi` 1.5.0 | OpenAI API credits | `pi-acp` / yes | 1 (0) | 7 | 31 | keep (C7) |
| A8 | `opencode` 2.2.5 | OpenCode Go (3 accounts), SIPB, Zen free | yes / yes | 54 (40) | 9 | 64 | keep, grows (C8) |
| A9 | `hermes` 0.22.2 | gateway, never a delegation target | yes / yes | 0 | 0 | 89 | keep as infrastructure (C9) |
| A10 | `zcode` 3.17.2 | Z.ai GLM Coding Plan `lite` | `zcode-acp-server` / no (Paseo has `glm-acp-agent`) | 54 (43) | 0 | 45 | fold into opencode (D1) |
| A11 | `copilot` 1.0.105 | Copilot Pro (GitHub use only since 2026-10-30) | yes / yes | 31 (25) | 0 | 26 | fold into opencode (D2) |
| A12 | `crush` 0.99.0 + `crush-acp` fork build | SIPB (free) | fork build / no | 2 (2) | 0 | 34 | retire (D3) |
| A13 | `venicecode` 0.0.0-dev (built 2026-11-04) | Venice API (disabled in aiuse) | no / no | 0 | 0 | 0 | retire (D4) |
| A14 | `dsh` 0.2.1-rc.5 (installed 2026-11-04) | DeepSeek API (disabled in aiuse) | plugin bridge / no | 0 | 0 | 0 | do not adopt now (D5) |
| A15 | `cline` 3.0.74 | ClinePass (lifeline of Hermes and Dann) | yes / yes | 0 | 15 | 36 | keep, never a slice target (C10, D6) |
| A16 | `qwen` 0.26.6 (qwen-code) | Alibaba coding plan (disabled in aiuse) | yes / yes | 0 | 0 | 18 | retire (D7) |
| A17 | `goose` 1.57.0 via `goose-scout` | Bedrock PAYG (Llama 4 Scout) | yes / disabled | 0 | 0 | 8 | retire again (D8) |
| A18 | `muse` (Meta Muse Code) | none measured (disabled in aiuse) | no / plugin | 0 | 0 | 17 | ask (D9) |
| A19 | `aider` 0.86.2 | any API key | no / no | 0 | 0 | 1 | retire (D10) |
| A20 | `kiro-cli` (Kiro CLI.app) | AWS Kiro | `--` in acp-run / no | 0 | 0 | 8 | retire (D11) |
| A21 | `devin` (shell wrapper only; binary gone) | Devin ACUs (disabled in aiuse) | `--` in acp-run / no | 0 | 0 | 10 | retire (D12) |

Not counted: `venice` 2.1.0 (`veniceai-cli`: chat, images, TTS; not a coding agent; it goes with the
Venice account, E3), `herdr-omp` (a herdr bridge provider in Paseo, handled by the plan's D4/D6
drain) and Grok Bot (a cloud agent with its own pool, no local TUI).

Concentration: omp, claude, codex and agy ran 1,542 of the 1,736 slices (89%). Ten agents ran none.

## B. Which plans can be spent only in the vendor's own client

This decides what cannot be folded. Checked on the web 2026-11-04 (sources in section I).

| # | Plan | Allowed clients | Consequence here |
|---|---|---|---|
| B1 | Claude Pro/Max | Claude's own tools only: third-party harnesses lost subscription access on 2026-04-04 [1][2] | `claude` is the only client for the Max pool; omp spends the separate API credits |
| B2 | ChatGPT (Codex) | `codex`, and OpenCode's ChatGPT login since 2026-01-10 [3] | foldable in principle, but `codex review` backs `bin/local-review`, so codex stays |
| B3 | Google AI Pro | Antigravity only: Gemini CLI stopped serving AI Pro on 2026-06-18 [4]; third-party use of Antigravity OAuth is a breach of clause 6 and can suspend the Antigravity and Gemini CLI accounts [5] | `agy` is the only client; never an OAuth plugin in opencode or Pi |
| B4 | Cursor | Cursor's own clients (IDE, `cursor-agent`, Cloud Agents) | `cursor-agent` stays |
| B5 | SuperGrok / X Subscription | Grok Build, Grok apps, Warp (same weekly pool), and Cursor under the X Subscription [6][7] | `grok` stays; see E1 for the bundle |
| B6 | Z.ai GLM Coding Plan | officially Claude Code, Cline, OpenCode, Kilo, OpenClaw and others [8] | `zcode` is not required (D1) |
| B7 | Copilot Pro | `copilot`, and officially OpenCode since 2026-01-16 [9] | `copilot` is not required (D2) |
| B8 | OpenCode Go | an `OPENCODE_API_KEY` plan, used by OpenClaw and Codex Router too [10] | stays in opencode |
| B9 | Venice | the API is metered: Pro includes about $1/month of API use and "a paid subscription does not include free or unlimited API usage" [11] | Venice is a pay-as-you-go route, not a plan |
| B10 | DeepSeek | API key, pay as you go | any harness; prepaid tier retired here since 2026-08-23 |

## C. Target roster (10)

1. **C1 `claude`**: the only client for the Max pool (B1); judgment and code tier; 177 code files
   already built around it.
2. **C2 `codex`**: the ChatGPT pool, the `frontier` gpt-6-astra slices, and `bin/local-review`.
3. **C3 `agy`**: the only client for all three Antigravity families (B3). Its ACP server is Google's
   own `agy_acp_server.par` (ACP registry entry `antigravity-acp`, memory
   `acp-adapter-vetting-agy-zcode-2026-10-03`), not the third-party Bun adapter.
4. **C4 `cursor-agent`**: the Cursor Ultra pool (99% left today). Of its 37 slices, 27 ran on
   `default`, 8 on Composer, one on Grok 4.7 and one on Claude Sonnet 5.5, which matters for E1.
5. **C5 `grok`**: the SuperGrok pool and the `realtime-web` kind (X search).
6. **C6 `omp`**: the workhorse, 62% of all slices, spending the monthly Claude API grant before it
   expires. On 2026-11-04 at 10:24 EST the Anthropic API refused an omp preflight with "Your credit
   balance is too low to access the Anthropic API" while aiuse read $249.27 of $250 left and
   `route_agent.py plan` still routed judgment to omp at "100% left" (H7).
7. **C7 `pi`**: the OpenAI API pool (added 2026-11-03, a deliberate operator decision). Both pi and
   omp are Pi-family harnesses, so one could serve both pools; H4 asks whether to fold them later.
8. **C8 `opencode`**: the one open harness. It already holds the OpenCode Go, SIPB, Zen-free and
   Alibaba providers (19 SIPB models, 30 Go, 87 Alibaba in `opencode models` today) and takes the
   GLM plan (D1), Copilot on explicit request (D2), SIPB work from crush (D3), and Venice or DeepSeek
   API keys if those accounts are ever re-enabled (D4, D5).
9. **C9 `hermes`**: the messaging gateway (`hermes-ping`, relay route). Not a coding target; listed
   so nobody removes it with the coding TUIs.
10. **C10 `cline`**: not a slice target (operator-gated, `discovery.never_route` lists clinepass),
    but `[substrate].lifeline = ["clinepass"]` makes ClinePass the lifeline of both Hermes and Dann
    (operator, 2026-10-23). Hermes reaches it through LiteLLM; Dann does not: `bin/paseo-new-seat`
    defaults to `--provider cline --model cline-pass/deepseek-v4.1-flash`, and `DANN_SUBSTRATE` in
    `bin/route_agent.py` fails over between the Paseo `cline` and `opencode` providers. The Cline
    client stays while that ruling stands (D6).

The roster drops `skill-everywhere` from 17 targets to 12 (goose, qwen, devin, muse and zcode go;
11 if copilot goes too, D2) and the `acp-run --list` registry from 17 rows to 11 (10 without
copilot).

## D. Retire or fold

1. **D1 zcode into opencode.** Z.ai lists OpenCode as a supported client for the GLM Coding Plan
   (B6), and OpenCode's catalog (models.dev) has a `zai-coding-plan` provider (7 models on
   2026-11-04; it reads `ZHIPU_API_KEY`). zcode costs 45 code files (an acp-run denylist shim,
   `bin/zcode-key-auth`, session-finder, helm, autorename and self-slash adapters, `bin/failover.py`
   and `bin/skillopt-night`) and has no Paseo provider of its own. The key reaches opencode through
   `sudo-secretspec run`, never pasted into `opencode auth login` or `opencode.json`; if a
   credential-store write proves unavoidable, it is a named exception like `bin/zcode-key-auth`
   (review rule 3). Gate: run the same GLM-5.3 slices through
   `acp-run opencode --model zai-coding-plan/glm-5.3` and confirm aiuse's `zai` 5-hour window moves
   (proof the plan, not an API balance, paid). Then switch the `zai` service's `agent` in
   `config/routing.toml` and retire `zcode`, `zcode-acp-server` and Paseo's `glm-acp-agent`. Keep
   the zcode session-store reader until its history is no longer harvested.
2. **D2 copilot into opencode.** Since 2026-10-30 the Copilot pool is "used only via GitHub or on
   explicit request; never route or burn", and GitHub-side Copilot review does not use the local
   CLI. An explicit request can go through opencode's `github-copilot` provider (B7), its
   `GITHUB_TOKEN` through `sudo-secretspec run` like D1's key (unverified: the provider may need
   GitHub's device login instead, which writes opencode's own auth store and would be D1's named
   exception; check it in the trial). Lowest priority:
   Paseo has a Copilot provider and the CLI is GitHub's own, so this is tidying, not a fix.
3. **D3 crush: retire.** It came back on 2026-10-11 only "to use mit-sipb-llms" (memory
   `project_crush_removed_2026-10-08`), through an ACP build of the unmerged upstream PR 2450 in
   `~/src/crush-acp`: a local patch that standing order 8 says must be upstreamed or dropped. It ran
   2 slices, is excluded from deny-mode reviews (queue, 2026-10-14), and opencode's `sipb` provider
   already reaches the same models, including the one that runs agent tasks reliably
   (`qwen3.6:35b-a3b-q4_K_M`). Retiring it removes 34 code files and two crush databases.
4. **D4 venicecode: retire.** Its upstream, georgeglarson/venicecode, was archived on 2026-08-31
   [12]. Its stated reason to exist was an array-content fix for GLM 4.6 and Qwen3 Coder in the
   OpenCode of that time; it is now a stale OpenCode fork that `brew-fast-upgrade` rebuilds from an
   archived branch every night (`site-private-djbclark/bin/venicecode-upgrade`), with its own
   isolated config. Venice is disabled in aiuse (operator, 2026-10-08) and its plan barely funds the
   API (B9). OpenCode's own catalog already has a `venice` provider (127 models on 2026-11-04), so
   no fork is needed: if Venice is wanted again, connect it in opencode with `VENICE_API_KEY` through
   `sudo-secretspec`, and add an aiuse collector so it is measured. Do not
   use the community proxies that drive the venice.ai web session (for example
   `opencode-venice-web`): it is the same subscription-arbitrage pattern Anthropic and Google ban.
5. **D5 dsh (DeepSeek Harness): do not adopt now.** It is DeepSeek's official harness, MIT, very
   popular, and still a developer preview whose README warns "THERE WILL BE COMPATIBILITY-BREAKING
   CHANGES" [13]. It is web-UI first (`dsh web`); the official ACP bridge streams plain text only, and
   richer bridges are community plugins [14]. It spends a DeepSeek API key, which aiuse lists as
   disabled, and DeepSeek V4 models are already on the OpenCode Go plan (`deepseek-v4-pro` ran 16
   slices this month). Uninstall, or keep it as an unrouted trial and revisit when it leaves
   preview; either way leave it out of `acp-run`, routing and `skill-everywhere` (H2).
6. **D6 cline: keep (C10).** An earlier draft retired it on the belief that ClinePass is reached
   only through LiteLLM; that holds for Hermes and Hindsight, not for Dann, whose seats and substrate
   failover run on the Paseo `cline` provider. Folding it would mean moving `paseo-new-seat`'s default
   and `DANN_SUBSTRATE`'s clinepass leg off the Cline client, which reverses the 2026-10-23 ruling,
   so it is H3's question, not a step. Separately, `config/routing.toml` line 92 says "the TUI is
   uninstalled", which is stale: cline 3.0.74 is installed and `acp-run --list` shows it.
7. **D7 qwen: retire.** The Alibaba plan is disabled in aiuse; no slices. If it comes back, opencode
   already has the `alibaba` and `alibaba-cn` providers configured.
8. **D8 goose: retire again.** djbclark, 2026-10-03: "Remove goose from everywhere, we decided not to
   use it." It returned as `goose-scout` (Bedrock Llama 4 Scout); its Paseo provider is disabled and
   it ran nothing. Bedrock, if needed, is an opencode provider.
9. **D9 muse: ask.** Meta's launcher says downloads are "available to Meta employees"; aiuse has
   `muse` and `museai` disabled since 2026-10-08; it is the one non-ACP headless TUI; no slices.
   Keep only if djbclark has a reason (H5).
10. **D10 aider: retire.** No ACP, no Paseo provider, no slices; opencode does what it does.
11. **D11 kiro-cli: retire.** djbclark, 2026-10-25: he does not want to use kiro-cli; it is
    `never_route` and its acp-run row is already `--`.
12. **D12 devin: retire.** The binary is gone; only the shell wrapper and the acp-run row (`--`)
    remain; Devin is disabled in aiuse.

## E. Plan decisions for djbclark (subscriptions, not TUIs)

1. **E1 The X Subscription (SpaceXSI, launched 2026-10-12).** One plan for Grok, Grok Bot, Cursor
   and X, with one weekly pool shared by Grok and Cursor [6][7]. Today Grok is 100% used while Cursor
   Ultra is 1% used, so a shared pool would put Cursor's idle allowance behind Grok work. Against it:
   **the switch is permanent**, and after it Claude and GPT in Cursor are billed at API list price
   instead of being included [7]. This month that would have touched one slice (the Claude Sonnet one,
   C4), but `config/routing.toml` still lists `claude-sonnet-5-5` as cursor's code model. Recommendation: do not switch until a month of cursor dispatch shows the
   third-party pool unused, then compare tiers (Super $100, Ultra $200) against the current SuperGrok
   plus Cursor Ultra bill.
2. **E2 OpenCode Go has three accounts** (monthly windows at 99%, 50% and 13% used today, swapped by
   `oc-go-key`). Keep them only if the routed volume needs them; opencode ran 54 slices this month.
3. **E3 Venice and DeepSeek accounts.** Both are disabled in aiuse. Cancel any recurring Venice Pro
   charge unless Venice is a non-coding need (the `venice` CLI does images and TTS); do not top up
   DeepSeek for dsh while V4 runs on the Go plan.
4. **E4 Dormant plans.** Check that nothing is still billed for Devin, the Alibaba coding plan or
   Muse; each is disabled in aiuse.
5. **E5 Copilot Pro** stays for GitHub-side review (the reserve with a 60% floor); only its local CLI
   is in question (D2).

## F. Considered and not recommended (not on disk)

1. **F1 Gemini CLI**: no longer serves AI Pro (B3); `agy` replaced it.
2. **F2 Warp**: can spend SuperGrok [6], but it is a terminal, not a harness Paseo or acp-run drive.
3. **F3 Kimi CLI, Factory Droid, Amp, Kilo CLI**: each brings its own billing and none is the only
   client for a plan held here, so each would add a TUI without retiring one. A Kimi or MiniMax
   coding plan, if ever bought, goes into opencode.
4. **F4 Subscription-bridge plugins** (`opencode-antigravity-auth`, `pi-grok-cli`, Claude OAuth
   proxies, `opencode-venice-web`): they spend a vendor plan through a client the vendor did not
   ship. Google and Anthropic suspend for this [2][5]; never install them.

The roster needs nothing new: opencode is already the open harness, and the gaps are policy, not
tools.

## G. Migration, in order, each step its own PR or operator action

1. **G1 Docs and registry (inside djbclark-ade, the lead's call).** Mark only the items with no open
   question and no live dependency retired: D4, D7, D8, D10, D11 and D12, in `config/routing.toml`
   and `docs/model-routing.md` (whose service matrix still says Cursor Pro and lists devin as
   dormant). Drop the devin and kiro rows from `tools/acp-run` (both already `--`), remove goose,
   qwen and devin from `bin/skill-everywhere` (muse after H5), add `venicecode` and `dsh` to
   `discovery.never_route` until they are gone, and correct the stale "TUI is uninstalled" comment
   (D6). Never touch the `clinepass` service or `[substrate].lifeline`: `hermes_chain` in
   `bin/route_agent.py` drops a retired api service, so marking it would also cut ClinePass out of
   Hermes's generated chain.
2. **G2 Trials (inside djbclark-ade).** D1's GLM-through-opencode slices with the aiuse window
   check, and two SIPB slices through `acp-run opencode --model sipb/qwen3.6:35b-a3b-q4_K_M` to
   replace crush. Read the result from the job records and the pool readings, not from exit codes.
3. **G3 Re-point routing (inside djbclark-ade, after G2 passes).** Point the `zai` service at
   `agent = "opencode"`; re-point the `crush` service (the only SIPB row) to `agent = "opencode"`
   with model `sipb/qwen3.6:35b-a3b-q4_K_M`, renamed `sipb` with an alias `crush` to `sipb` so old
   records still resolve. In the same PR: replace crush and zcode in `bin/skillopt-night`
   (`DEFAULT_ALLOW`, keeping the `ADAPTER_SOURCES` readers for history) and `bin/failover.py`
   (their `Tui` rows), drop the qwen, goose, zcode and crush rows from `tools/acp-run` and the zcode
   target from `bin/skill-everywhere`, then mark D3 retired. D5 and D9 are marked only after H2 and
   H5. A follow-up PR removes the remaining crush and zcode references (`dispatch.extra.crush` in
   `config/routing.toml`, `bin/acp-dispatch`, `bin/agent_guard.py`, `bin/crush-context-check`,
   `bin/ade-backup-stores`, `bin/web-digest-mcp`, `bin/skillopt_sources.py`) once G4 has removed the
   binaries. D2 gets its own trial and PR only if djbclark wants it (lowest priority).
4. **G4 Machine-side removal (outside djbclark-ade: needs djbclark's yes, order 11).** Uninstall
   venicecode (binary, `~/src/venicecode`, `~/.config/venice-opencode-isolated`, and its
   `brew-fast-upgrade` pass), dsh (if H2 says uninstall; also its `brew-fast-upgrade` pass and the
   `dsh_repair_native_binding.py` hook), qwen-code, block-goose-cli and `goose-scout`, aider, the
   Kiro CLI app, crush with `crush-acp` and `~/src/crush-acp`, and zcode after G3; drop their bashrc
   wrappers; disable the matching Paseo providers (`qwen-code`, `glm-acp-agent`, and `muse` per H5;
   never `cline` while C10 stands). Back up each tool's local state first, as the 2026-10-08 crush
   removal did.
5. **G5 Plans (djbclark).** E1-E4.

## H. Open questions

1. **H1** Approve the 10-agent roster in C?
2. **H2** dsh: uninstall now, or keep as an unrouted trial until it leaves developer preview?
3. **H3** cline: keep it as Dann's substrate client (the 2026-10-23 ruling, C10)? The recommendation
   is yes: `DANN_SUBSTRATE`'s other leg is already opencode-go, so moving the clinepass leg there
   too would leave Dann without a second provider to fail over to. Retiring the Cline client needs
   a different second provider first. Hermes and Hindsight already reach ClinePass through LiteLLM.
4. **H4** Fold pi into omp later (one Pi-family harness for both API pools), or keep one harness per
   pool as decided on 2026-11-03?
5. **H5** muse: is there a use for it?
6. **H6** E1: wait a month of cursor data before considering the X Subscription switch?
7. **H7** omp's credit refusal (C6): the grant may have lapsed or not reach this key, and aiuse and
   the router both still count it as available. Fix the reading now, or queue it?

## I. Sources (fetched 2026-11-04)

1. [1] [kersai.com: Anthropic banned third-party Claude auth (2026-04-07)](https://kersai.com/anthropic-killed-third-party-claude-access-heres-every-workaround-that-still-works/)
2. [2] [groundy.com: the three-stage repricing (2026-02-20)](https://groundy.com/articles/anthropic-bans-third-party-use-subscription-auth-three-stage-repricing/)
3. [3] [Dev Genius: Codex OAuth now works in OpenCode (2026-01-10)](https://blog.devgenius.io/jump-ship-in-minutes-codex-oauth-now-works-in-opencode-d2708c32f571)
4. [4] [Google: transitioning Gemini CLI to Antigravity CLI (2026-05-19)](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/)
5. [5] [Zentor: Antigravity clause 6, as of 2026-09-04](https://zentor.ai/blog/antigravity-account-suspended-third-party)
6. [6] [x.ai pricing](https://x.ai/pricing) and [Warp: SuperGrok subscription (2026-10-28)](https://docs.warp.dev/agents/inference/grok-subscription/)
7. [7] [docs.x.ai: What is The X Subscription? (updated 2026-10-12)](https://docs.x.ai/x-subscription/overview)
8. [8] [Z.ai: GLM Coding Plan](https://z.ai/subscribe)
9. [9] [GitHub changelog: Copilot now supports OpenCode (2026-01-16)](https://github.blog/changelog/2026-01-16-github-copilot-now-supports-opencode/)
10. [10] [OpenClaw docs: OpenCode Go provider](https://docs.openclaw.ai/providers/opencode-go)
11. [11] [opencode-venice-web README, quoting Venice's API docs](https://github.com/CanArslanDev/opencode-venice-web) and [Venice: how do I access the API?](https://veniceai.featurebase.app/help/articles/7782904-how-do-i-access-the-api)
12. [12] [georgeglarson/venicecode (archived 2026-08-31)](https://github.com/georgeglarson/VeniceCode)
13. [13] [deepseek-ai/deepseek-harness README](https://github.com/deepseek-ai/deepseek-harness)
14. [14] [grunmin/dsh-acp-enhanced (2026-08-16)](https://github.com/grunmin/dsh-acp-enhanced)
