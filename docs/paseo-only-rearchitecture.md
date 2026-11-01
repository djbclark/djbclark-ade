# Paseo-only re-architecture (plan v1, 2026-10-30)

Status: v1, the plan of record for the migration. v0 (2026-10-29, omp 086494f8) was refined by lead
1e61c979 (chain `standalone-b457`) with two second opinions, codex astra (GPT-6) and Fable 5.1, two
research passes, djbclark's answers in section F (2026-10-30), and the fixes for adversary
round 1's findings on PR 154 (safety of probes, archive and drains; plugin scope and fail modes). Until phase D7 lands,
`README.md`, `AGENTS.md` and `docs/orchestration-practices.md` still describe the multi-harness design;
this plan wins where they disagree about the future, they win about today. Sources: section I.

**Update 2026-10-31 (djbclark):** herdr (except the `herdr4paseo` and `paseo4herdr` bridges), Orca and BB
(get-bb/bb, npm `bb-app`; not `bigteam`) are retired **from djbclark-ade** by ruling (no skill or doc recommends them; a few live code paths still reach herdr or Orca until D4/D6, listed in AGENTS.md), and Paseo is the only
harness. They stay installed and configured on djbclark's computer, untouched ("mostly removed from djbclark-ade, not from my
computer"; "don't delete or modify the actual orca config"): **machine-side uninstall is NOT planned.** The docs now say so
(`AGENTS.md`, `README.md`, `docs/apply-toolchain-prompt.md`, retired skill descriptions). The phases below are unchanged.
Many files still describe herdr or Orca as live until phase D7's sweep.

**D7 conflict resolved (2026-10-31):** `bin/herdr-server-run` and `config/launchd/dev.herdr.server.plist` STAY: the installed
herdr server and the `herdr4paseo` / `paseo4herdr` bridges run on them, so D7's deletion of herdr tooling excludes both.

## A. The ruling (djbclark, 2026-10-29 and 2026-10-30)

1. **Paseo only.** No herdr, no tuios, no other harness (Orca, Superset/Paradev, TUICommander, raw tmux
   panes, Hermes-as-harness). Every agent the operator talks to is a Paseo agent. Amended by A8: two
   edge-case Herdr bridges and possibly a modified tuios stay, never as harnesses.
2. **Retire `relay.py`** and every non-Paseo channel; inter-agent communication moves to Paseo's native
   framework (`send_agent_prompt`, `create_agent` with `notifyOnFinish`, `list_agents`,
   `list_pending_permissions`/`respond_to_permission`, heartbeats, schedules, lineage).
3. **Replacement order for every djbclark-ade capability:** (a) native Paseo functionality or skill;
   (b) an existing Paseo plugin; (c) a Paseo plugin we write; (d) only then keep it in djbclark-ade.
4. **End state:** no mention of any harness other than Paseo anywhere in djbclark-ade, `~/AGENTS.md`
   (`site-djbclark/cursor/home-agents.mdc`), the ops `AGENTS.md` files, skills, docs or memory pointers,
   except the `docs/history/` directory (F5), the A8 bridges doc and skill, and, during the migration, this
   plan. The ban is on harness **roles**, not on words that name something else: Hermes is also a Paseo
   *provider* (`paseo provider ls`: `hermes available`) and `hermes-ping` is a notification channel (F1).
5. **Basis:** `Open-Source AI Agent Harnesses Compared.pdf` (Paseo Desktop upload
   `upload_d70305b6-6865-461c-83df-aab4fb305afb`, 2026-10-29): Paseo 92.2/100 on non-blocking inter-TUI
   communication with ClinePass and OpenCode Go support as a hard requirement (TUICommander 87.4,
   Superset 56). Known weakness: one Node event loop per daemon (section B9, risk H2).
6. **Fan-out during the migration:** Paseo-native subagents (`paseo run` / `create_agent`) and the
   `/paseo-handoff`, `/paseo-advisor`, `/paseo-committee` skills; not `/bigteam` until D5 rewrites it.
   Exception until D5: `acp-dispatch` stays the dispatcher for frontier consults and adversary reviews,
   because its quota gates are the only ones that exist today (H4). Until D1.3 and D2's gate have both
   passed, fan-out uses `isolation: local` workspaces only, and task worktrees come from `git worktree add`
   (order 9), whatever a skill such as `/paseo-handoff` offers (D0.3).
7. **Fable and codex astra take part in the re-architecting** (djbclark, 2026-10-29); this overrides the
   routing-policy line that reserves them for `frontier` consults. Both consulted on v0 (section I).
8. **Herdr bridges and attach clients stay, for edge cases** (djbclark, 2026-10-30): two projects, each
   built in its own herdr tab:
   1. **`herdr4paseo`** (tab `herdr4paseo-t`): Herdr attaches to running Paseo agents, as an **attach
      client** that shows and drives an agent Paseo hosts. A modified tuios may do the same.
   2. **`paseo4herdr`** (tab `paseo4herdr-t`; fork https://github.com/djbclark/paseo4herdr, checkout
      `~/src/paseo4herdr`; formerly the `paseo-herdr` plugin, installed disabled today as `herdr-harness`):
      Paseo reaches terminals that Herdr hosts.

   **These two are the only Herdr integration.** Herdr agents do not talk to Paseo agents: no messaging,
   relaying, launching, naming, sleeping or fleet tracking through Herdr, and no djbclark-ade tool depends
   on either bridge.

## B. Principles

1. **One authority per host.** The local `paseo` daemon holds that host's agents, lineage, permissions,
   terminals, worktrees, schedules and heartbeats; the Mac and vps-primary (F3) are two hosts.
   djbclark-ade keeps no fleet registry, pane map, transcript finder or waiter of its own. It does keep
   **durable evidence**: task ids, report files and outcome records live outside worktrees, so an
   archived workspace or a daemon restart loses no result (astra A2, B1e).
2. **Communication is a Paseo prompt or event, never typed text**: no screen scraping, prompt-line
   detection or pane typing. A message has four states and the toolchain names which one it proved:
   *accepted* (the daemon took it: all `send_agent_prompt` returns), *delivered* (the recipient's next turn
   started with it), *acted on* (the recipient's named ack), *completed* (`notifyOnFinish`). Completion is
   not an ack (astra B1a, Fable 3.5). **Never send to a running agent whose provider cannot steer**: Paseo
   then interrupts the turn; queue the message until the agent is idle (Fable 3.8). Which providers steer is
   unknown until D1 measures it, except antigravity (no steering, no Paseo tools, research 2a). Native sends
   (`send_agent_prompt` from any agent, the UI) bypass G3, so this rule binds only senders that use G3;
   the `paseo-peers` skill makes G3 the only sanctioned path and the bypass is taken upstream.
3. **Blocking is handled by the daemon.** Cards (permissions and questions: `paseo permit ls` lists `question`
   and `OMP ask` cards too) are answered by the parent, or by G4 for opted-in agents only, or reach the
   operator by push or Telegram (F1). A peer never waits on another's card. **Cards are not a security
   boundary**: `respond_to_permission` is on every agent's MCP catalog and an agent with a shell can reach
   the host anyway (upstream `mcp.md`), so an agent could answer its own card. Hard-to-reverse protection
   stays in provider-side hooks and `ade-git-guard`. In every agent profile except named orchestrators,
   `disabledTools` removes `respond_to_permission`, `update_agent`, `set_agent_mode` and `archive_agent`.
   That applies to **every profile id, each custom one included** (custom profiles do not inherit it through
   `extends`, `mcp.md`), and D2 lists the tool catalog of a UI-created and a Telegram-created agent to prove
   it.
4. **Workspaces are Paseo workspaces** (`isolation: worktree`), which replaces `git worktree add` and cow
   pastures. Paseo has **no writer lock** (several agents may share a workspace), so order 9's one-writer
   claim stays in `ade-git-guard` and its claim registry; the Paseo workspace is the claim's target
   (astra B1, Fable 1.4). **Archive must never delete unpushed work**: archiving the last agent of a
   worktree workspace removes the worktree (upstream `worktrees.md`), `session-janitor` can archive failed
   or closed subagents after 6 hours (disabled since 2026-10-30, point 3), and Paseo has no hook before an
   archive (only `workspace.archive.after`).
   So:
   1. **The `paseo.json` teardown is the only preserve point**, and it runs only in repos whose base branch
      commits one. Every repo a slice may target carries it (the list lives in `config/paseo-teardown-repos`),
      and G2 refuses a `worktree` workspace create (`workspace.create.before`) in any repo without it. Upstream
      forks are not slice targets (standing order 8 forbids adding the file to someone else's tree).
   2. The teardown **preserves locally first, unconditionally**: a `git bundle` of the branch, a stash commit of
      tracked changes, and a tar of untracked non-ignored files, written atomically into a 0700 directory
      outside the worktree (`~/.local/state/ade/rescue/<repo>/<branch>-<date>/`). Only then does it push a
      `rescue/<branch>-<date>` branch with **tracked changes only**, and only to a private remote; untracked
      files never leave the machine. A failed push still leaves the local rescue.
   3. No slice is created with `autoArchive`; workers lose `archive_agent` (B3). `session-janitor` had
      automatic child archiving on (`archiveChildren:true`, `archiveAfterHours:6`; read 2026-10-30; it had
      never archived anything). djbclark set `archiveChildren:false` and then disabled the plugin outright the
      same day, because its built-in defaults are archive-and-delete (`archiveChildren`, `deleteChildren` and
      `deleteMain` all true), so a settings reset, a reinstall or a fresh daemon would start there. It stays
      disabled until D2, which chooses the exclusion mechanism and writes all three settings explicitly:
      either G1 adds each worker to the janitor's native `protectedIds` through a supported surface
      (`archiveChildren:true`), or child archiving stays off for good (`archiveChildren:false`) and G1 archives
      a worker after its "branch pushed and report read" mark; `deleteChildren` and `deleteMain` stay false
      permanently either way. Until D2, the D0.2 drain script and the B9 watchdog assert, on the Mac and on
      vps-primary (`paseo --host wss://vps-primary.greyhound-sidemirror.ts.net:7263 plugin ls`, with D1.8's
      daemon credential through `sudo-secretspec run` once it exists; a non-zero exit alerts, and only an rc=0
      list without `session-janitor` counts as "not installed"), that the janitor is
      disabled or all three settings are false, and alert otherwise. The same check asserts herald's
      `cleanup.deleteHelpers` is exactly false in `$PASEO_HOME/plugin-data/herald/config.json` (a missing or
      invalid file means herald's default, true, and alerts). D2 replaces the janitor assertion with the
      chosen mechanism's own (always including `deleteChildren:false` and `deleteMain:false`). G1's "not
      archived until pushed" is a convention: the operator, the UI and `paseo-telegram`
      can still archive, which is why point 2 exists.
   4. D1.3 proves the teardown and the rescue; D2's gate proves G2's refusal.
5. **Native first, plugin only for a hook.** A script that calls the `paseo` CLI, SDK or MCP is native (A3a)
   and lives in djbclark-ade. A plugin is written only when a daemon lifecycle hook, a UI surface or a
   composer command is needed, because plugins are trusted, unsandboxed and sit in the create/turn path of
   the one daemon. Never a script that talks to a TUI (Fable 1.5; astra A1 on B5).
6. **Policy stays, enforcement moves.** Routing, quota and cost policy (`aiuse`, `route_agent.py`,
   `config/gates.toml`) stay; profiles are launch configuration only, so gates are enforced by the
   admission plugin G2, which must also cover UI sends, resumes and schedules or name the gap.
7. **The A8 bridges are edge-case tools.** Nothing depends on either being installed or open; no tool
   reads, types into, or messages an agent through Herdr or tuios.
8. **Strangler, not big bang.** Each phase ships its replacement beside the old path, proves it live
   (section D gates), **drains** the old tool (D0.2), then disables its entry point, and only the last phase
   deletes. Rollback reconciles live agent ids; it never relaunches paid work (astra D4).
9. **Outside supervision.** A daemon cannot report its own death or hang (#7121: 100% CPU, supervisor saw
   no exit; #2753: health answered while RPCs starved). A launchd watchdog outside Paseo probes
   `/api/health` and times a real RPC (`timeout 20 paseo ls --json`), and alerts through `hermes-ping`
   (F1). **Restart policy**: alert after two consecutive misses with the load average logged; capture
   diagnostics first (`sample`/`spindump` of the daemon, `eventLoopDelay` from `~/.paseo/daemon.log`);
   restart only after three consecutive misses while the load average is below the core count, at most
   once per 30 minutes (otherwise alert and wait for the operator); reconcile G1 after every restart.
   Keep active workspaces bounded (about 15, enforced by G2's create check), never register giant trees as
   workspaces, and create slice workspaces in the background (Fable 5.2).
10. **Destructive tests never touch the live daemon.** Every probe that restarts, hangs or kills a daemon
   runs against an isolated test daemon: its own fresh `PASEO_HOME` (never a copy of the live one, so it
   cannot inherit the live server id; it does not install `session-janitor`, or writes the three B4.3
   settings false before its first run) and a Unix socket, or a TCP port claimed in
   `site-djbclark/registry/ports.yml` first, or a scratch user on vps-primary. The live Mac daemon is touched
   only in a drained window (`paseo ls` shows no running agent, G1 reconciled) with djbclark's yes.

## C. Inventory and disposition

Counts are `rg -li` over the repo on 2026-10-29, excluding `graft/` and `docs/handoffs/`.

### C1. Capabilities

| Capability today | Footprint | Disposition | Replacement (section G for plugins) |
|---|---|---|---|
| `skills/session-finder/{relay.py,fleet.py,launch.py,where.py,prompt_line.py,nested_pty.py,adapters/}` | relay.py in 44 files | non-Paseo routes RETIRE in D4; relay.py and fleet.py in D6, once no watcher calls them | `send_agent_prompt` with B2's states; G3 for delivery and deferred send |
| herdr as a harness (`bin/herdr-*`, herdr docs and skills, `-t/-p` naming, panes hosting agents, pane typing) | 139 files | RETIRE; **retired from djbclark-ade by ruling 2026-10-31** (docs now; the tool stays installed and untouched, no uninstall planned; `bin/herdr-server-run` and `config/launchd/dev.herdr.server.plist` stay) | Paseo workspaces; naming `-pw` only |
| `herdr4paseo` (A8.1) | own project | KEEP, edge case | one A8 bridges doc and skill |
| `paseo4herdr` (A8.2), plugin `herdr-harness` (installed, disabled) | own project | KEEP, edge case | same doc and skill |
| tuios as an attach client (A8.1) | — | DECIDE: only if modified for it | same doc and skill |
| Orca (`docs/orca-integration.md`, `skills/orca-cli`, `skills/reorg-orca`, `orca-reorg-watch`, worker-start) | 103 files | RETIRE; **retired from djbclark-ade by ruling 2026-10-31** (docs now; Orca stays installed and its config untouched, no uninstall planned) | Paseo workspaces and subagents |
| Superset/Paradev skills | 10 files | RETIRE (evaluation concluded 2026-10-29) | none |
| BB (get-bb/bb, npm `bb-app`, the web agent workspace; not `bigteam`) | few files (`docs/apply-toolchain-prompt.md`) | RETIRE; **retired from djbclark-ade by ruling 2026-10-31** (docs now; BB stays installed where it is, no uninstall planned) | Paseo |
| Orca `computer-use` stub and `orca computer` for GUI control | outside the repo | RETIRED 2026-10-31 (the lead removed the Orca-installed skills `orca-cli`, `orca-per-workspace-env`, `herdr`, `orchestration` and the stub from the machine) | Paseo plugin `paseo-screen` (`skills/paseo-screen/`), THE screen-control tool; stays enabled when idle (2026-10-31) |
| `acp-run` (also the agent registry: `acp-run --list` feeds `route_agent.py`) | 138 files | REPLACE in D5 | `paseo provider ls` and the C2 map; an agent with no working provider blocks its own retirement |
| `acp-dispatch`, `acp-dispatch-wait`, records, launchd runners, reap sweep, `tell`, `resume`, `reroute`, exit-code contract (3 no report, 4 BLOCKED, 124 timeout) | 109 files | REPLACE in D5 | `paseo run`/`create_agent` + G1 jobs/deadline + G2 admission + `usage-auto-resume` (+ G5); report-file footer stays as a skill; `paseo run --output-schema` for typed results |
| `acp-dispatch outcome` → `route_agent.py calibrate`, `agent_stats.py burn` | — | KEEP the data | G1 writes the same outcome records, so calibration keeps its source (Fable 2.1, 4.3) |
| `/bigteam`, job records under `~/.local/state/bigteam` | 73 files | REWRITE in D5 | `paseo run` fan-out on G1 |
| `self-slash`, `/new`-`/baton` lifecycle, successor launch, `paseo-new-seat`, `paseo-bypass-watch` | — | SIMPLIFY in D5 | successor created **top-level** from the CLI without `PASEO_AGENT_ID` until D1 proves archive-parent behaviour (an agent-scoped `create_agent` makes the successor a child of the retiring agent, Fable 2.4); keep `/baton` and Tier 1/Tier 2 |
| `helm`, `/helm-all` | — | REPLACE | `paseo permit ls` / `respond_to_permission` for live seats; `paseo ls -a` and Tier 1 pointers for ended sessions |
| `herdr-tidy`, `herdr-sleeper`, `agent-sleep`, `autorename` herdr half | — | RETIRE after the D0.2 drain (sleepers hold Claude session UUIDs per pane: `plugins/herdr-sleeper/herdr-sleeper list` (bin/herdr-sleeper was removed 2026-10-31) plus the legacy journal `~/.local/state/herdr-sleeper/sleeping.json` must be empty or each resumed as a Paseo agent) | `session-janitor` (disabled until D2, B4.3), `archive_agent`; Paseo titles |
| `watch` roles, `fleet-watch` (in `~/ops/site-private/bin`, not this repo), `paseowatch`/`cfenginewatch` (`fleet-watch upstream --relay-to` uses relay.py), `tell-chief-of-staff` | — | REWRITE in D6 | `paseo send` from the launchd script; schedules only where a run needs judgment (F2) |
| `load-watch`, `session-load-watch`, `rumination-watch`, `bg`, gates, `wait-file` | — | KEEP (launchd, F2); drop pane typing | deliver via `paseo send` |
| `claude-quota-guard`, `context-watch`, `context_size_nudge` (provider hooks) | — | KEEP | they run inside the provider; G2 enforces the same gates for launches that bypass the hook |
| `pr-wait`, `ade-git-guard`, `git-commit-own`, `local-review`, graft, `aiuse`, `web-get`, `failover.py`; `ci-waiver` once parked PR 118 lands (not on master) | — | KEEP (harness-neutral) | n/a |
| Running Paseo plugins not covered elsewhere (`paseo plugin ls`, 2026-10-30): `better-paseo` (chat timeline and agent board; its approve/deny and archive buttons act only on the operator's click), `herald` (speaks when an agent waits; it denies tool requests only from its own summary helpers; it used to **hard-delete** (`paseo delete`) every agent labelled `herald.role=summarizer`, selected by that label, until djbclark set `cleanup.deleteHelpers:false` on 2026-10-30), `reopen-archived` (reopens archived workspaces with their agent), `skills` (skills browser), `forges` (no description; no permission, archive or prompt calls; it vendors an unused `agent.create` MCP-injection helper) | — | KEEP; herald's hard delete off and asserted (B4.3, G2.8) | none answers another agent's card or archives on its own. No running plugin attaches tools or MCP servers today (`better-paseo` and `usage-auto-resume` hook the legacy `agent.session_open` and return neither). This inventory is a snapshot: plugins track latest, so D2's catalog check (open-time tools and create-time `mcpServers`) reruns on every plugin install or upgrade |
| `cow-workspaces` | — | RETIRE | Paseo worktree workspaces plus `fresh-worktrees` (running) and setup hooks; the claim stays (B4) |
| `adversary` and other provider sub-agents | — | KEEP (provider-native) | or as a Paseo subagent in D5 |
| Hermes: `hermes-ping`; Hermes as a seat | 163 files | KEEP `hermes-ping` as a notification channel (F1); RETIRE Hermes-as-harness; Hermes stays a Paseo provider | Paseo push for agent events |
| `skills/model-routing`, `route_agent.py`, `docs/model-routing.md` | — | KEEP policy, strip the harness table | C2 map |
| `opencode-plugins/`, OpenCode V2 Go sessions, `opencode-plugin-guard` | 128 files | F4: keep provider-side plugins, drop harness-like ones | Paseo provider `opencode` |
| `cursor-cloud` | 14 files | KEEP as a tool (a cloud agent, not a harness) | — |
| `README.md` "two altitudes", `docs/orchestration-practices.md`, `docs/coding-factory.md`, `docs/ade-everywhere-*` | — | REWRITE in D7; history into `docs/history/` | — |
| `~/AGENTS.md` items 4, 24-26, 30, 33; `djbclark-ade/AGENTS.md` orders 9-10 and Machine context | — | REWRITE per phase, as each behaviour changes (astra B1h), final pass in D7; Opus 5.5+ edits `home-agents.mdc` | — |

### C2. Provider map (`paseo provider ls`, Mac daemon 0.14.0, 2026-10-30)

| Status | Providers | Consequence |
|---|---|---|
| available | claude, codex, copilot, opencode, omp, antigravity, cline, grok, cursor, glm-acp-agent, hermes, qwen-code | can replace `acp-run` for that agent once D1 proves steer/card behaviour |
| error | gemini, goose | fix or accept the loss before `acp-run` retires for them |
| unavailable | pi, muse | not used today |
| no provider | zcode (`zcode-acp`), crush/SIPB | custom ACP provider entries (Paseo custom-providers) or keep `acp-run` for these alone until then |

Steering: antigravity has none and gets no Paseo tools (research 2a). For every other provider,
steer-while-running behaviour is **unknown** until D1 measures it; Fable 7.3 warns that a send to a working
opencode, cline or grok agent may kill its turn, so B2's queue rule applies to all of them until then.

## D. Phases

Each phase is a PR with an adversary verdict and CHANGELOG lines. No phase edits a shared checkout, except
`~/ops` edits (D6, D7), which follow AGENTS.md order 9's transitional `~/ops` exception until the
ops-promotion pilot passes.

0. **Consult and research**: done 2026-10-30 (this v1). Three rules bind every later phase:
   1. **B10**: destructive probes run only on an isolated test daemon or in a drained, approved window.
   2. **Drain gate** (before any "disable" of B8): a script under `tests/paseo-acceptance/drain/` records,
      for the tool being disabled, that it holds nothing: `plugins/herdr-sleeper/herdr-sleeper list` and the legacy journal `~/.local/state/herdr-sleeper/sleeping.json` empty (`fleet.py ended` `sleeping` items show both), or each sleeper
      resumed as a Paseo agent with its session UUID; no `acp-dispatch` record quota-stopped or resumable and
      no launchd `auto-resume` job pending (each is resumed with `acp-dispatch resume` to completion, with
      `acp-dispatch` enabled until then, or imported as a Paseo agent with its session id; never a fresh
      dispatch); `relay.py --pending` empty or each expectation retired with a reason; every Orca worktree and
      cow pasture clean and pushed, or its owner named; bigteam inboxes drained.
   3. **No Paseo worktree fan-out before the preserve point exists**: until D1.3 and D2's gate have both
      passed, Paseo workspaces created for work use `isolation: local`, task worktrees come from
      `git worktree add` (order 9), and `session-janitor` stays disabled (B4.3). `skills/paseo-handoff`
      carries a pointer to this rule.
1. **Contracts and safety net.** Each probe is a repeatable script under `tests/paseo-acceptance/` with an
   **expected outcome and a named consequence if it fails**; D2 starts only when every consequence is
   resolved. D1 probes native Paseo behaviour and the non-plugin pieces it builds (the B4 teardown, the B9
   watchdog, the dead-man check); anything that needs a G plugin is checked in D2's gate.
   1. Steer while running, per C2 provider. Expected: steer queues. If not: that provider is "queue only"
      in G3.
   2. A parent answers a question card's *option*, not only allow/deny, via `respond_to_permission`.
      Expected: works. If not: B3 and G4 are redesigned (cards go to the operator).
   3. Archive an agent whose isolated worktree workspace is dirty and has an unpushed commit (isolated
      daemon). Expected: the B4 local rescue (bundle, stash commit, untracked tar) exists before the worktree
      goes, also when the push fails; the pushed `rescue/` branch carries tracked changes only. Record whether
      a failing teardown stops Paseo removing the worktree, and `session-janitor`'s current mode. If anything
      is lost: no slice moves into Paseo workspaces until it is not.
   4. Archive a parent with a running child. Expected: the child survives. If not: successors stay
      top-level (C1) permanently.
   5. Restart a daemon holding a queued prompt, a pending `notifyOnFinish` and a schedule (isolated
      daemon). Expected: none lost. If lost: G1 and G3 persist them themselves, and reconcile after restart.
   6. Schedule missed-run behaviour across Mac sleep (isolated daemon). If runs are lost: F2 keeps those
      jobs on launchd.
   7. The B9 watchdog: it fires on a forced hang **of the isolated daemon**, and does **not** restart a
      healthy daemon during one forced load incident (false-positive soak).
   7a. Tabs: an agent started with `paseo run` gets no tab in the app until something opens one (found by
      agent 3bdcc475, 2026-10-30; `self-slash` fixed for successors in PR 159 by opening before archiving).
      Record which creation paths open a tab (`paseo run`, `create_agent`, schedules, Telegram). Where one does
      not, ADE launchers call `paseo agent open`, which is best effort (it needs a running Desktop and cannot
      confirm the tab); `paseo ls -g` (D4's gate) stays the visibility check.
   7b. Create origin: does `agent.create.before` tell a plugin-SDK create from an MCP or CLI create? Record the
      answer; G2.8 depends on it.
   8. vps-primary, before the pilot (F3): the Paseo daemon password set and the listener bound to the tailnet
      interface only, with a Tailscale ACL that admits the Mac; pilot agents run as a dedicated unprivileged
      user with their own `PASEO_HOME` and no access to the host's deploy or service secrets; provider and
      Telegram credentials in the host's secrets mechanism (sops/agenix or `sudo-secretspec`); the
      upgrade 0.13.0 → 0.14 lands only as the pushed `master` head through `deploy-vps-primary` (home rule
      36). Expected: an unauthenticated request from another tailnet node is refused; `ps` shows the daemon
      and the pilot agents running as that dedicated user (the NixOS service's user changes, or a second
      instance runs as it); that user cannot read the host's deploy keys or other services' secrets.
   9. The dead-man check on vps-primary **holds no Mac credential and never calls the Mac daemon**; the Mac
      daemon stays bound to `127.0.0.1`. Each run, the Mac's B9 watchdog writes a heartbeat to vps-primary
      that carries its own result (`/api/health` and the timed real RPC), so a wedged daemon on an awake Mac
      still pages from vps-primary. A sleep/wake hook (IOKit power notification through `sleepwatcher` or an
      equivalent launchd agent) writes `sleeping since T` before sleep and clears it on wake. The Mac writes
      both through a dedicated ssh key installed for a dedicated unprivileged user on vps-primary
      (`restrict,from="<Mac tailnet IP>",command="…write-heartbeat"`). The forced command ignores
      `SSH_ORIGINAL_COMMAND`, reads at most 4 KB of JSON from stdin, validates its fields and replaces only
      those two files atomically. A sleep marker counts only while it is newer than the last heartbeat, and
      every heartbeat write clears an older marker, so a wake hook that failed cannot silence the check. The
      check pages when the heartbeat is stale with no current sleep marker, when the heartbeat reports a
      failing daemon, and when a current sleep marker is older than a configurable threshold (default 72 hours,
      so a weekend away does not page). The paging credential (`hermes-ping` on vps-primary) lives in D1.8's
      secrets mechanism. Expected: sleep (no page), daemon killed while awake (page), network cut while awake
      (page), wake hook failed and then a network cut while awake (page); from vps-primary an authenticated
      Paseo call to the Mac is impossible, and the key cannot run anything else.
2. **Minimum plugins and adopted plugins** (section G): G2, G3, G1, G4; `usage-auto-resume` coverage for omp,
   opencode, cline and grok (G5); the Telegram plugin's 0.14 test (F1). **Gate**, on the isolated daemon,
   asserting that the live daemon's state under `~/.local/state/ade/<serverId>/` is unchanged (or absent
   before and still absent, while the live daemon runs no G plugin): three concurrent launches against one
   pool admit at most what the ledger allows; an `aiuse` failure follows G2's fail mode; a reroute is
   visible to the launcher; a held G3 send survives a daemon restart; G4 ignores an agent G1 never recorded
   (also one labelled after create) and a job submitted without `permit: true`, and escalates compound
   commands (`;`, `&&`, `|`, `$(`, a newline, `sh -c`) and command-taking options (`git -c`, `find -exec`,
   `xargs`, `env VAR=… cmd`); a `jobs.submit` naming an existing agent id is refused; a non-orchestrator's
   tool catalog lacks `jobs.submit`, including an agent that a worker created with the orchestrator profile;
   if D1.7b found a create-origin signal, a CLI or `create_agent` create carrying `herald.role` is refused while
   herald's own helper passes (G2.8; otherwise the `deleteHelpers:false` assertion is the control);
   the janitor mechanism is chosen, its settings are written, and an unmarked worker past
   `archiveAfterHours` survives (B4.3); a non-owner Telegram
   message is refused; a forged agent id in an RPC input is refused; the tool catalogs of a UI-created and a
   Telegram-created agent lack the B3 tools, including tools any running plugin attaches in
   `agent.open.before`; a `worktree` create in a repo without a committed `paseo.json` teardown is refused
   (B4, G2).
3. **Canary.** One real workflow end to end on Paseo only: work → review → CI → report, including a forced
   quota stop that resumes and a daemon restart that loses nothing (isolated daemon, or a drained window
   with djbclark's yes), and the one-task pilot on vps-primary with its report retrieved on the Mac.
   **Gate:** no paid job or artifact depended on a retiring tool; outcome records written.
4. **Seat and communication cutover.** Every launch is `paseo run`/`create_agent`; `relay.py` routes only
   `--via paseo` (strangler); a `paseo-peers` skill (B2 states, G3 as the sanctioned path, named acks per
   standing order 10) replaces `peer-relay`. After the drain gate: relay's non-Paseo routes, helm,
   herdr-tidy and herdr-sleeper are disabled. `relay.py` and `fleet.py` themselves stay enabled
   (`--via paseo` only) because D6's watchers still call them. **Gate:** `paseo ls -g` shows every live seat;
   G3 shows `delivered` for a cross-workspace send; the drain record is committed.
5. **Dispatch, then lifecycle.** `acp-dispatch`/`acp-run` replaced by G1 on Paseo subagents (records kept
   readable until calibration reads G1's); `/bigteam` and the dispatch footer rewritten; after the drain gate,
   `acp-dispatch` is disabled; then `self-slash` successors (C1). `acp-run` retires only when zcode and crush
   have working custom Paseo providers, or djbclark rules to drop them. **Gate:** one `/bigteam` wave of three
   slices with deadline, report file and one forced quota stop; a successor survives its parent's archive with
   the chain pointer intact.
6. **Watchers and notifiers.** `fleet-watch`, `load-watch` delivery, quota-guard steers and the watch roles
   on `paseo send`; Paseo schedules for judgment jobs only (F2). Then, after the drain gate and a search for
   callers of `relay.py` or `fleet.py` (the watchers above, `fleet-watch upstream --relay-to`, `paseowatch`,
   `cfenginewatch`, `tell-chief-of-staff`, the quota guard), `session-finder` is disabled. The search covers
   all of `~/ops`, djbclark-ade, `~/.local/bin`, `~/Library/LaunchAgents`, the provider hook configs
   (`~/.claude/settings.json`, `~/.codex`, `~/.omp`) and vps-primary's NixOS config, matching any of
   `session[-_]finder`, `\b(relay|fleet|launch|where|prompt_line|nested_pty)\.py\b` and
   `^\s*(import|from)\s+(relay|fleet|launch|where)\b`, because callers also build the path in pieces or
   import after a `sys.path` insert (today `bin/context-watch:74`, `bin/load-watch:116,232`,
   `skills/helm/helm.py:56-57`, `skills/herdr-tidy/tidy.py:35`). It skips what D7 handles: `docs/history/`,
   `docs/handoffs/`, `site-private/memory/handoffs/`, `CHANGELOG.md`, `graft/`, `skills/session-finder/`, test
   code that loads or fixtures it (`tests/test_relay_*`, `tests/test_fleet_*`, the relay and fleet fixtures in
   `tests/conftest.py`, the relay case in `tests/test_codex_shell_env_policy.py`), this plan, and the code of
   tools an earlier phase already disabled after a committed drain record (D4: helm, herdr-tidy,
   herdr-sleeper), which D7 deletes; the search verifies each is still disabled and blocks if one is not. A
   hit in code, config, a launchd plist, a hook or the NixOS config **blocks** the
   gate. A hit in a live instruction file (AGENTS.md, `home-agents.mdc`, memory notes, other skills, docs)
   goes onto a triage list that D7's rewrite must empty. **Gate:** a load incident reaches its watcher as a
   Paseo prompt; no blocking hit remains; the triage list is committed.
7. **Deletion and docs.** Delete what earlier phases disabled; README, both AGENTS.md, ops AGENTS.md, memory
   pointers, skills index, `apply-toolchain-prompt.md`, `mcp-servers.md`; write `docs/history/`. The
   end-state check is a **new** CI step in djbclark-ade (the `context-policy` job runs only pytest today)
   plus a local script over `~/AGENTS.md`, `home-agents.mdc`, the ops `AGENTS.md` files and
   `site-private/memory/`, which no djbclark-ade CI job can read. Its pattern:
   `herdr|orca|tmux|\bsuperset\b|paradev|tuicommander|tuios|cow.pasture|relay\.py|acp-run|acp-dispatch`
   plus Hermes in a seat or harness role; `tmux` and `superset` hits go to a human for triage (ordinary
   English and non-harness uses). Exempt: `docs/history/`; the A8 bridges doc and skill (`herdr`, `tuios`);
   the literal names `herdr4paseo` and `paseo4herdr` wherever they appear (indexes must list the skill,
   review rule 8); and the check's own script and workflow. D7 moves this plan into `docs/history/`, and its
   own `Removed` CHANGELOG lines go into the frozen history CHANGELOG (F8).

Least reversible steps: deleting the dispatch record format (D5; kept readable until calibration moves),
worktree removal on archive (B4), and the instruction-file rewrites (D7). Each happens only after its gate.

## E. Carry-overs (not part of this plan; must not be lost)

1. PR 118 (CI waiver, docs-only class): parked at head `d55a8b4b` with adversary r9 BLOCK (push needs
   `--force-with-lease=refs/heads/master:<proved master>`, three untested guards, `[remote rejected]`
   message). Harness-neutral; resume or close after the migration (`docs/queue.md`).
2. D3 Nimbalyst Wiki install/test, assigned to the lead by djbclark via 0b70f359 (2026-10-29): parked, to run
   as its own Paseo subagent in a worktree workspace after D4.
3. `docs/queue.md` entries unchanged.
4. `paseo4herdr` and `herdr4paseo` (A8) are worked on in their own herdr tabs; this plan writes in neither.
5. The Jev-like judges now share one Hyades microVM, `djbclark-jevlike`, one judge at a time, Kev by default
   (djbclark, 2026-10-30; jev-like-hyades `bff0d6b`, sipb-agent-skills `6d71b98`, djbclark/mit `bba409f`).
   The freed Hyades slot is spare: F3 moved to vps-primary.
6. `relay.py` sender identification (found by 495e0645, 2026-10-30; not in `docs/queue.md`): a Paseo-hosted
   agent that neither carries `PASEO_AGENT_ID` nor has an ancestor that does (`fleet.py:627-631,647`; seen
   with an Antigravity agent) resolves to a channel-less `pid*` row (`fleet.py:878`), so its `--expect-ack`
   is recorded with no proof path (`timeline_base`, `relay.py:731-732`, returns None for a sender with no
   Paseo id, so `timeline_ack` returns at `:749-750` before the header match at `:757`) and never closes, and
   nothing warns at send time. Queued acks themselves close correctly (the header precedes the `[queued …]`
   prefix; `tests/test_relay_fallback.py:3009` pins that delivered format). It matters until D6 disables
   `session-finder`, because D0.2's drain gate relies on acks closing expectations; until then such records
   are retired with a reason.

## F. Decisions (djbclark, 2026-10-30, after the consults and research)

1. **Notifications**: Paseo native push for agent events (finished, error, permission, question). The B9
   launchd watchdog sends `hermes-ping` on a sustained failure, unexpected exit, failed recovery and
   recovery; a dead-man check on vps-primary covers the Mac offline while awake (D1.9: a sleeping Mac does
   not page). Also install the reviewed `Daaaaave/paseo-telegram` plugin (0.2.3) to answer cards from
   Telegram, after a 0.14 compatibility test (D2); it covers no daemon outage. It is a remote command
   channel (it can create and drive agents), so its policy is pinned before it is enabled: DMs from the owner
   only; groups "approve each group in Paseo" with none approved; requests from the owner only; agents it
   creates run in a non-bypass mode. Its bot token lives in the plugin's own store
   (`~/.paseo/plugin-data/telegram`), the review-rule-3 exception for a third-party tool's credential store,
   with the source of truth in `sudo-secretspec`. Note: the Mac daemon runs with the Paseo relay off; push
   goes from the daemon to Expo directly (research B2), which D1 verifies with the phone off the tailnet.
2. **Unattended runs**: split by job kind. Paseo schedules only for runs that need judgment
   (`skillopt-night`, triage, reports); launchd (systemd on Linux) for monitors, collectors, record reaping
   and the watchdog. Schedules that keep worktrees need archive-on-finish turned off in the app first.
3. **Second daemon**: use the **existing** vps-primary Paseo daemon (0.13.0, NixOS system service, connected
   to the Mac over the tailnet; 3.7 GiB RAM, 2 vCPU) for the one-task pilot and the dead-man check, after
   upgrading it to 0.14 and meeting D1.8's security prerequisites. Correction (lead 1e61c979, 2026-10-30):
   the first F3 answer chose a new Hyades microVM because the lead had not checked `paseo host ls`;
   Fable's consult found the daemon. Not on pastebin.xvm.mit.edu (too little memory).
4. Keep OpenCode plugins that act inside the provider session; drop anything that acts as an alternate harness.
5. The history goes in a `docs/history/` directory; the end-state check exempts that directory (and see F8).
6. omp Opus 5.5 high leads the judgment phases and Sonnet 5.5 the mechanical ones; Fable and astra consult.
   Every launch stays subject to the live quota gates: when omp is rate-gated (it shares the Claude weekly
   window), judgment work waits or goes to codex per the routing policy (Fable 1.7).
7. Phase order: astra's (contracts, minimum plugins, canary, communication, lifecycle/dispatch, watchers,
   deletion), refined with Fable's seat-before-communication and dispatch-before-lifecycle (section D).
8. **History files move into `docs/history/`** (djbclark, 2026-10-30, after adversary r1 C7 showed the
   check failing on `CHANGELOG.md` (102 lines), `docs/queue.md` (174), `docs/handoffs/` and `graft/`). In D7
   the current `CHANGELOG.md` and `docs/handoffs/` are frozen into `docs/history/` and new ones start; closed
   `docs/queue.md` entries move there too and open ones are rewritten. Links to the old paths break, by
   choice. `graft/` is regenerated in D7 with `docs/history/` left out of its index, so it comes out clean
   [lead's reading: the ruling did not name `graft/`; it is generated, not history].

## G. What we build (replacement order A3; interfaces are sketches for D2)

All hook names are Paseo 0.14's (`agent.create.before`, `agent.open.before`, `agent.turn.before`,
`agent.permission.before`, `workspace.create.before`; upstream `plugins_hooks.md`, "Renamed hooks").

**State.** Every plugin keeps its state outside worktrees under `~/.local/state/ade/<serverId>/<plugin>/`,
keyed by the daemon's server id, so an isolated test daemon (B10) never reads or writes the live daemon's
ledgers. The plugin reads its server id from the daemon at start (D2 names the SDK call; the running
`session-janitor` already stores one) and **refuses to start** if it cannot, rather than fall back to a
shared key. State is written atomically (temp file and rename), and every `reconcile()` acts only on
records carrying its own server id.

**Authorization.** A plugin RPC handler gets no authenticated caller (its input is self-asserted), so every
agent-facing operation (`jobs.submit`, `jobs.get`, `jobs.finish`, `jobs.extend`, `ack.register`) is a **plugin
agent tool** attached in `agent.open.before` and authorized by the daemon-supplied `context.agent.id`.
`jobs.submit` (and with it `permit: true`), `jobs.get` and `jobs.extend` are attached only to orchestrators,
which are identified from an operator-owned list (`config/orchestrators`), read as the **committed** blob
(`git show origin/master:config/orchestrators`), never from a working tree another session may have edited.
It lists agent ids, and profile ids only if probe D1.7b finds a creator signal to check them against; never
a field the creator sets. A worker gets `jobs.finish` and
`ack.register`. Every G1-recorded agent and every orchestrator gets `ack.register`. RPCs serve only the operator's UI,
which records the owner as `operator`. This stops mistakes and impersonation over the tool surface, **not** a
same-uid agent with a shell that edits the state files directly; like B3, it is not a boundary (adversary r1
C9, r2 C3 and C8, r3 N2, r4 R4).

1. **`ade-jobs` (plugin, hooks needed)**: durable task ids, deadline and grace, a wrap-up steer at
   T-minus-grace, interrupt at T recorded as exit 124 (cancellation confirmed, and the agent's child
   processes gone, before the writer claim is released), report-file validation, outcome records in the
   existing format, `reconcile()` after a daemon restart that never relaunches blindly. A job's agent is
   never archived until the job records "branch pushed and report read" (B4). Native parts:
   `paseo run --output-schema`, `paseo wait --timeout` (waits, does not cancel). Interface:
   `jobs.submit(taskId, host, workspace, profile, reportPath, deadline, grace, permit)` **creates the worker
   itself** and never accepts an existing agent id; it records `owner = context.agent.id` (the caller) and
   the worker's id, provider and mode. `jobs.get` for the owner; `jobs.finish` for the worker;
   `jobs.extend(taskId, seconds)` for the owner; `jobs.reconcile` (astra C1, Fable 3.1, adversary r3 N2).
2. **`ade-gate` (plugin)**: `agent.create.before` runs `aiuse` (cached about 60 s) and
   `bin/load-watch admit --json` with no wait (the admission predicate `acp-dispatch` already uses; exit 75
   means too hot, so the gate refuses with the load named and the launcher retries outside the hook, which
   has a 30 s ceiling), and enforces B9's workspace cap.
   1. **Fails closed**: an `aiuse` error, stale evidence or a hook timeout refuses the launch with the reason.
      The one exception copies `acp-dispatch`'s rule: a missing or crashed `load-watch` lets the launch
      through with the error recorded in the ledger (a gate that cannot read the load must not stop all work).
      The override is an expiring entry written through `bin/gate-profile` (`config/gates.toml`), so a broken
      `aiuse` cannot stop recovery work for long. Agents are told never to write it; G2 logs every launch
      that used an override and sends `hermes-ping` for it. It is **not a boundary**: `gate-profile` has no
      human-presence check, and any agent running as the operator's user could write the entry, or simply
      run `paseo plugin disable ade-gate`; the watchdog alert (G2.5) detects a disabled gate, it does not
      prevent it.
   2. **Reservations** are a locked ledger under `~/.local/state/ade/<serverId>/gate/`, decremented on every
      create, so launches inside one cache window cannot all pass.
   3. **Refuse by default; reroute only when the launch carries the label `ade.reroute=ok`**, and then only
      `provider` and `model`, never mode, env, tools or MCP servers; the reroute is written to the agent's
      timeline and the ledger. (Changes made in `agent.create.before` persist after the plugin is removed.)
   4. `agent.open.before` can change only env, tools and MCP servers, so on open the gate can only refuse.
   5. **Named gaps**, taken upstream: `agent.turn.before` is notify-only, so UI sends and
      `usage-auto-resume`'s resume prompts are not gated; a disabled, crashed or failed-to-reload plugin
      loses its hook registrations, so creates then pass ungated (the B9 watchdog alerts whenever
      `paseo plugin ls` does not show `ade-gate` running); and G2 has no update hook, so a label added later
      through `update_agent` is not refused. That gap matters only for herald's label, and herald's hard delete
      is off (G2.8).
   6. On `workspace.create.before` it refuses a `worktree` workspace in a repo without a committed
      `paseo.json` teardown (B4).
   7. It reads no secret; anything that needs one runs under `sudo-secretspec run` (astra C3, Fable 3.4).
   8. **Herald's hard delete is off** (djbclark, 2026-10-30: `cleanup.deleteHelpers:false` in
      `$PASEO_HOME/plugin-data/herald/config.json`; asserted by the B4.3 check). Herald selected agents to
      `paseo delete` by the label `herald.role`, including in a sweep 30 s after every plugin load; with the
      setting off, its `autoArchive` helpers are only archived, which is recoverable. As optional hardening, if
      probe D1.7b finds a create-origin signal, G2 also refuses that label on a create that does not come from
      herald (adversary r5 T2, r6 U1-U2).
3. **`ade-ack` (plugin)**: records sends (the `ack.register` agent tool, callable only by the sender). The
   `agent.turn.before` payload carries only the agent and turn ids and hook notifications are best effort with
   no replay, so on each turn start it fetches that turn's timeline through the SDK and marks *delivered*
   when the send is in it; after a restart it reconciles missed turns from history. It holds sends to busy
   non-steer agents in a **durable** queue until idle and deduplicates finish callbacks
   (`messages.send/ack/reconcile`; astra C4, Fable 3.5 and 3.8). Native sends bypass it (B2).
4. **`ade-permit` (plugin)**: **opt-in and fail-closed.**
   1. It trusts **its own record, not a label**: it acts only on workers G1 created through a `jobs.submit`
      with `permit: true` (the opt-in act), recording the provider and the bypass/full mode then; G1 refuses
      `permit: true` for a restrictive mode such as Always Ask, Write Approval or Plan, or a deny brief. Labels
      and modes can be changed after create (`update_agent`, `set_agent_mode`), so on every
      `agent.permission.before` it re-reads the agent's current mode through the SDK and does nothing unless it
      still matches the record. The operator's own sessions are never recorded.
   2. On `agent.permission.before` (a notification) it answers with `respondToPermission` only when the
      request, **tokenized with a shell parser**, matches an entry of the reviewed allow-list
      (`config/permit-allow.toml`) exactly as a whole argv, or an entry plus a declared argument shape. An
      argument shape may not admit `-c`, `-exec`/`--exec`, config overrides, `-C <path>` into another repo, or
      any option that takes a command (`git -c core.sshCommand=…`, `find -exec`, `xargs`, `env VAR=… cmd`). It
      escalates any request containing `;`, `&`, `|`, a backtick, `$(`, `>`, `<` or a newline, and any
      `sh -c`, `bash -c`, `python -c` or `eval` wrapper. Everything else, including every question card and
      every outward or hard-to-reverse action, goes to the parent or the operator.
   3. Audit: `~/.local/state/ade/<serverId>/permit/audit.jsonl`, one line per decision, with the request, the
      decision and the policy revision (the allow-list file's git blob id).
   4. It is not a security boundary (B3) (astra C5, Fable 3.6, adversary r1 B1).
5. **Adopted**: `usage-auto-resume` (running; covers Codex, Claude, Antigravity; extend it, or add a small
   turn-end hook (0.14 name per `plugins_hooks.md`), for omp, opencode, cline and grok), `session-janitor`
   (disabled until D2, B4.3),
   `fresh-worktrees`, `Daaaaave/paseo-telegram` (F1). Before adding any plugin, check overlap with these
   (astra B3).
6. **Not plugins**: the B9 watchdog and dead-man check (launchd/systemd), the report footer (a skill),
   `ade-git-guard` (the writer lock).

## H. Risks, ranked

1. **Delivery weaker than today**: `accepted` is not `delivered`; a one-way link goes unnoticed. G3 ships
   in D2, and standing order 10's named ack survives.
2. **One daemon wedge takes every agent down** (#7121). B9 watchdog in D1; vps-primary as a second host.
3. **Steer is not universal**: a send to a working non-steer agent kills its turn. B2's rule, G3's queue,
   the C2 map.
4. **Quota and load gates vanish with acp-dispatch**, and `create_agent` bypasses provider-side hooks such
   as the Claude quota guard. G2 ships before `/bigteam` is rewritten.
5. **Lifecycle defaults destroy work**: archive-on-finish deletes worktrees; archiving a parent may end a
   child successor. Retention set before canaries; top-level successors until D1 proves otherwise.

## I. Sources

1. Consults: `~/.local/state/bigteam/paseo-only-2026-10-29/consult-astra-report.md` (codex gpt-6-astra) and
   `consult-fable-report.md` (claude fable), both on v0 at `a7f41c47`.
2. Research: `research-paseo-report.md` (native API, plugins, issues) and `research-f123-report.md`
   (notifications, schedules versus launchd, remote daemons), same directory.
3. Live checks (2026-10-30): `paseo provider ls`, `paseo plugin ls`, `paseo host ls`, `paseo permit ls`;
   Hyades per-microVM RAM measured (`MemTotal` 7.78 GiB).
