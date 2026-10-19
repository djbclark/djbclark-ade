# Paseo plugins and Paseo-specific tooling: a scan for the ADE (2026-10-19)

Summary: Paseo 0.12.0 is installed here with plugins disabled and none installed. The official
registry (paseo.sh/plugins, added in 0.11.0 on 2026-10-07) lists 312 plugins, 205 of them not
themes; the independent paseo.cafe catalogue lists 246 with a machine-readable security scan. About
twenty matter to the ADE. Nine are worth a trial now, behind a plugin trust rule, because each
covers a loop the ADE runs by hand or by script today (quota resume, attention triage, usage
ledgers, Forgejo issues, approval gates). The rest wait for the Phase 4 ADE plugin or are
replaced by it. Questions for djbclark are SF-Q14 to SF-Q16 in
[software-factory-research-digest-2026-10-19.md](software-factory-research-digest-2026-10-19.md).

## 1. Facts, checked 2026-10-19

1. Local: `/opt/homebrew/bin/paseo` is 0.12.0; `~/.paseo/config.json` has `pluginsEnabled` unset
   (null) and no plugin entries. Nothing in this scan is installed.
2. Registry: 312 plugins by category (a plugin can carry several): Utils 108, Themes 107,
   Sidebar 74, Workspaces 73, Orchestration 29, Git 23, Providers 22, Daemon management 19,
   Extras 15. Every entry has an install count; the full dataset, parsed from the registry page,
   is kept as `paseo-registry.json` in the session scratchpad (not committed).
3. paseo.cafe: 246 plugins, `GET /api/plugins` and `/llms.txt`; each record carries a security
   scan (`passed` / `failed`), licence, Paseo version requirement, npm downloads and a health
   block (manifest valid, README, licence, tests, typecheck, updated recently). Eight shortlist
   plugins fail its scan today: Agents Dash List, Agents History, Chat Resume, Session Usage,
   Schedule Runs (all panrafal, `git:` installs with no npm package), Parent Wake, Obol and ZCode
   Provider.
4. Plugin API at 0.11+: screens, sidebar items, workspace and agent panels, Command Center
   items, slash commands, composer pills, timeline items, themes, RPC handlers, usage sources,
   providers (direct or `runAcpProvider()`), lifecycle hooks (agent creation, turns, permissions,
   archive) and transforms. Plugins are **trusted, unsandboxed code with the daemon user's
   access** to files, processes, credentials and network (every README repeats the sentence).
5. Install sources: `paseo plugin add <owner>/<slug>` (registry-reviewed, pinned revision),
   `paseo plugin install git:<owner>/<repo>[:path]`, `npm:<package>`, or a local checkout.
   Management: `paseo plugin ls|update|reload|logs|disable|enable|remove`; `update` shows the
   new revision and asks. SDK: `@getpaseo/client` (TypeScript). Skills:
   `npx skills add getpaseo/paseo` installs paseo-handoff, paseo-advisor and paseo-committee,
   already under `skills/`.

## 2. Shortlist, grouped by the ADE loop each touches

Installs are registry counts on 2026-10-19; "source" is the registry id unless marked `git:`.

### 2.1 Quota, resume and provider switching (today: `aiuse`, `acp-dispatch` in-place resume)

| Plugin | Installs | What it does | Against the ADE |
|---|---|---|---|
| babo-jeonguk/usage-auto-resume | 72 | continues Codex, Claude and Antigravity agents after their usage window resets | the Paseo-side twin of `acp-dispatch resume`; covers interactive chats the dispatcher never sees |
| keefeere/continuity | 28 | continues work on a fallback provider after a quota or rate-limit failure | routing policy says reroute within the eligible tier; needs its fallback list set to the policy's order |
| panrafal/chat-resume (`git:`) | 14 | composer pills: continue now, resume after renewal, prepare a handover | the `handoff` skill for Paseo chats; scan `failed` on cafe |
| tomgrin10/defer | 14 | defer a message until a time or usage-window reset | one-shot scheduling without a cron prompt (item 13) |
| aborakati/usage-monitor | 114 | provider quotas, balances, token history in screens and pills | overlaps `aiuse`; a display, not a decision source |
| stv1024/token-ledger | 203 | per-turn tokens, cache counts and cost, persistent ledger | the per-turn view `agent_stats.py` lacks |
| panrafal/session-usage (`git:`) | 35 | token, tool-call, timing and cost from local Claude, Codex, OpenCode, Kilo, Devin, Cursor records | overlaps `aiuse`'s snapshot; scan `failed` |
| nerveband/provider-usage (`git:`) | 13 | quota windows, credits, cost per provider in a sidebar page | overlaps `aiuse` |
| kapybara-org/zerosub, dutchakdev/account-switcher, raffidahmad/accounts | 169, 20, 18 | several Claude/Codex subscriptions side by side, per agent | one account per provider here; skip |
| anh-chu/switch-provider | 9 | continue a session on another provider and model, compacting history | the `self-slash`/handoff path for a cross-vendor move |

### 2.2 Attention and triage (today: `/helm`, `hermes-ping`, `herdr-sleeper`)

| Plugin | Installs | What it does | Against the ADE |
|---|---|---|---|
| omercnet/agent-monitor | 72 | host-wide agent triage roster | the Paseo view `helm` wants (proposal 7.2) |
| panrafal/agents-dash-list (`git:`) | 7 | workspaces across all hosts ordered by what needs you | cited in the proposal as C53; scan `failed` |
| gpambrozio/herald | 23 | speaks one sentence when an agent needs you; a waiting list panel | cited as C54 |
| panrafal/agents-history (`git:`) | 42 | every workspace ever, archived included, searchable | cited as C55; a slice of §6 sessions-everywhere |
| sm1ee/session-triage | 0 | which sessions need input, are working, or are done | published 2026-10-19; watch |
| summerisgood1/paseo-next-check | 273 npm downloads | opens the oldest unread reply across workspaces | the `helm` "next" action |
| kingsleydon/recap | 31 | a goal / progress / next-step recap after every turn | a per-turn Tier 1 pointer; compare `session-handoff` |
| nkwib/turn-report | (registry) | claims versus command evidence per turn | standing order 4 as a panel |
| zhjiang22/agent-observatory (`git:`) | 121 | unread queue, timelines, usage, schedules for every agent and subagent | a bigger agent-monitor; no licence |
| daaaaave/telegram | 16 | Telegram DMs, groups and topics bound to Paseo chats and workspaces | overlaps Hermes's relay; see SF-Q16 |

### 2.3 Orchestration (today: `bigteam`, `acp-dispatch`, Orca, `tell-chief-of-staff`)

| Plugin | Installs | What it does | Against the ADE |
|---|---|---|---|
| gpambrozio/firstmate | 105 | one first-mate agent runs a crew in their own worktrees, with a live board | bigteam with a UI; Paseo-native worktrees |
| omercnet/agent-crew, omercnet/tell-agent | 34, 23 | crew panel; message agents in other workspaces on the same host | `session-finder/relay.py` for Paseo agents |
| jtsang4/mesh, maxwell-01/cross-daemon | 16, 8 | list, read, create and message agents on other daemons | the cross-host hop §6 needs for vps-primary and Hyades |
| epistex0/parent-wake (`git:`) | 9 | wakes a parent on every child question or finished turn | what bigteam's waiter does for ACP slices; scan `failed` |
| duongvm57/slp (`git:`) | 6 | Supervisor, Lead, Peer teams with a repository desk for assignments, review and evidence | a factory-shaped team inside Paseo; compare Phase F |
| oliexe/bots | 332 | personal bots: instructions, model, memory, routines, teams, skills, MCP, connected apps | a Hermes-like assistant inside Paseo; overlaps Hermes |
| 37chengshan/goal-mode | (registry) | keeps an agent on one objective across turns with automatic follow-ups | a Ralph-style loop (queue item "Ralph postponed") |
| omercnet/gas-city, omercnet/beads, jmkelly/beads-board, cuongntr/beads-viewer | 6-14 | Gas City supervisors; Beads work queues and boards | only if Gas Town or Beads is adopted (see the digest §3.3) |
| cybershape/schedule-submit, panrafal/schedule-runs | 7, 7 | schedule a message; a feed of schedule runs | one-shot scheduling (item 13) |

### 2.4 Git and forges (today: `gh`, `git-forgejo`, `forgejo-ci`, `cow-workspaces`)

| Plugin | Installs | What it does | Against the ADE |
|---|---|---|---|
| xpufx/forges | 1,210 npm downloads | Forge/Gitea-family issues from inside Paseo | the only Forgejo-aware plugin; MIT/SIPB repos |
| omercnet/fresh-worktrees | 31 | fast-forwards a clean base branch before Paseo creates a worktree | item 36's "deploy the pushed head" hygiene for worktrees |
| cprecioso/worktreeinclude | 11 | copies gitignored files listed in `.worktreeinclude` into new worktrees | cow's dependency-carrying for plain worktrees (SF-Q5 adapter) |
| omercnet/pr-radar | 25 | viewer-aware delivery queue for PRs linked to workspaces | the factory's "ready" list (Phase F) |
| gpambrozio/github-board, alysnnix/github-integration, pmusaraj/pr-views, ajma/issues-workspaces | 20, 14, 12, 16 | GitHub issues, PRs, discussions; issue to worktree with an agent | GitHub-only; issue intake (SF-Q9) |
| mentalfl0w/review-deck, laokashouji/turn-changes | 13, 23 | human-in-the-loop review with inline comments; per-turn diff cards with undo | the human review surface the factory lacks |
| cprecioso/gh-stack | 920 npm downloads | GitHub stacked PRs panel | only if stacks are used |
| MaplumeX/archive-branch-cleanup | (cafe) | deletes the local branch when a Paseo worktree is archived | hygiene |
| tomgrin10/send-to-paseo | (cafe) | local HTTP bridge dispatching PR work to the right workspace and agent | a browser-to-Paseo intake |

### 2.5 Daemon, host and safety (today: launchd plists, `fleet-watch`, `sudo-ask`, `sudo-secretspec`)

| Plugin | Installs | What it does | Against the ADE |
|---|---|---|---|
| xpufx/twofado | 1,200 npm downloads | approval-gate UI and notifications for the 2fado privileged-command daemon | the `sudo-ask` pattern with a Paseo surface; evaluate 2fado itself first |
| yuruiz/secrets | 4 | private text and image input, one-use execution grants | compare `sudo-secretspec`; never a second secret store |
| gpambrozio/launchd-jobs | 1,267 npm downloads | schedule shell commands through launchd from a panel | `fleet-watch`-style jobs without hand-written plists |
| hichamboushaba/keep-awake | 59 | keeps the host awake while agents work | Macs that sleep mid-slice |
| babo-jeonguk/free-your-agents | 8 | stops idle agent processes without losing the conversation | `agent-sleep` / `herdr-sleeper` for Paseo agents |
| a31521424/host-monitor, zedobaia/resources, tomgrin10/vitals, xpufx/top | 150, 24, 10, 10 | CPU, memory, disk, Docker per host | overlaps `load-watch` |
| itsjustanks/mcp, koinzhang/customize | 18, 15 | MCP connectors in step across Claude and Codex; inspect rules, skills, MCP, subagents per provider | `docs/mcp-servers.md` as a live view |
| alessandrocornacchia/port-forward, zedobaia/ports | 16, 15 | forward agent ports from remote hosts; share over Tailscale | useful once daemons run on vps-primary |
| vercel-labs/vercel-sandbox | 13 | persistent sandbox hosts for Codex, Claude Code, OpenCode, Pi | a hosted isolation option for the factory (SF-Q2 of the Codex read) |

### 2.6 Providers

| Plugin | Installs | Against the ADE |
|---|---|---|
| omercnet/omp | 118 | omp is gated behind an explicit yes per run (`~/CLAUDE.md` item 26); install only if that changes |
| lefos13/antigravity-cli, 3ae3ae/agy-provider | 34, 7 | agy as a Paseo provider; agy pools are at 1% this week, and `acp-run agy` is the only sanctioned route |
| geoqiao/deepseek-harness | 114 | not in the routing policy |
| supermomonga/zcode-provider (`git:`) | 16 | zcode is in the policy (GLM-5.3); scan `failed`; Paseo may already run zcode through ACP |

## 3. Recommendation tiers

1. **Trial now** (SF-Q14 option a), each pinned from the registry, plugins enabled in
   `~/.paseo/config.json`: Usage Auto Resume, Continuity (fallback order from the routing policy),
   Agent Monitor, Herald, Agents Dash List, TokenLedger, forges, Fresh Worktrees, twofado (after
   reading 2fado). Together they cover quota resume, attention, cost and Forgejo for interactive
   Paseo chats, which the ADE's scripts cover only for dispatched slices.
2. **After Phase 4's ADE plugin exists:** Agents History, Recap, Turn report, Session triage,
   paseo-next-check, Mesh / Cross Daemon, worktreeinclude, PR Radar, Review Deck, Turn Changes.
   The ADE plugin should subsume or depend on them, not re-implement them; proposal §7.3 lists
   the delta only.
3. **Skip:** account multiplexers (ZeroSub, Account Switcher, Accounts), the Telegram plugin
   unless SF-Q16 says otherwise, Bots, provider plugins the routing policy does not admit, host
   monitors that duplicate `load-watch`, Gas City and Beads unless the digest's §3.3 projects are
   adopted.

## 4. Trust rule (proposed, SF-Q15)

1. A plugin runs as the daemon user with no sandbox, so installing one equals running its author's
   code with every credential the daemon can reach. On a trusted daemon (the Mac, vps-primary)
   install only registry-reviewed entries by `paseo plugin add <owner>/<slug>`, which pins a
   reviewed revision; run `paseo plugin update` by hand and read its revision line.
2. No `git:` or `npm:` sources on a trusted daemon. The five panrafal plugins and Parent Wake are
   `git:` only today; they wait until they are registry entries, or get an `adversary` read of the
   pinned checkout first (option b).
3. Record every installed plugin and its pinned revision in `ade-private` (proposal §4.3) so
   `ade install` reproduces the set; `paseo plugin ls` is the artifact to verify against.
4. paseo.cafe's security scan is advisory: a `failed` means the catalogue could not verify the
   package, not that the code is hostile; a `passed` is not a review.

## 5. Related Paseo tooling, not plugins

1. `@getpaseo/client`: the TypeScript SDK the Phase 4 ADE plugin and any `ade` CLI hook use.
2. paseo-vscode and Paseo Icon (macOS menu bar): editor and menu-bar clients; neither changes
   the plan.
3. Cross-Daemon Comms MCP server: the MCP form of Mesh; relevant if an ACP agent, not a Paseo
   chat, needs to reach another daemon.
4. Devbox Fleet, Docker self-host, Vercel Sandbox: ways to run daemons elsewhere; the plan's
   answer is vps-primary and Hyades (Q18), so these are references only.
5. `npx skills add getpaseo/paseo`: already applied; the three skills under `skills/paseo-*`
   carry `.paseo-managed-files.json` markers (untracked at the time of this scan).

## 6. Install log, 2026-10-19 (SF-Q14 and SF-Q15 decided: trial tier, any source)

`pluginsEnabled` set to true in `~/.paseo/config.json` (backup `config.json.bak-2026-10-19`),
then `paseo daemon reload`. Status from `paseo plugin ls --json` afterwards:

| Plugin | Source used | Result |
|---|---|---|
| usage-auto-resume | registry `babo-jeonguk/usage-auto-resume` | running |
| herald | registry `gpambrozio/herald` 0.6.0 | running |
| token-ledger | registry `stv1024/token-ledger` 0.7.0 | running |
| agent-monitor | `npm:@omercnet/paseo-agent-monitor` 3.0.0 (registry copy pinned `^0.11.0`, refused on 0.12.0) | running |
| forges | `npm:@xpufx/paseo-forges` 0.1.4 (not in the registry under `xpufx/forges`) | running |
| twofado | `npm:@xpufx/paseo-twofado` 0.1.5 (same) | running |
| continuity | registry and `npm:paseo-continuity` 0.2.1 | build failed: esbuild `paseo-plugin-server-runtime-boundary` cannot resolve type dependency `@getpaseo/client` from `server/failover.ts` |
| agents-dash-list | registry and `git:panrafal/paseo-plugins:agents-dash-list` | build failed: same error from `client/dash-surface.tsx` |
| fresh-worktrees | registry and `npm:@omercnet/paseo-fresh-worktrees` 3.0.0 | refused: requires Paseo `^0.11.0`, daemon is 0.12.0 |
| telegram | registry `daaaaave/telegram` | refused: requires Paseo `>=0.11.2 <0.12.0` |

The two build failures look like one Paseo 0.12.0 issue (plugins that import `@getpaseo/client`
types without declaring it); the two refusals are plugin version pins. Both are upstream
items, see `docs/upstream-issues.md` candidates and the queue.
