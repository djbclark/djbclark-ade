# Paseo-only re-architecture (plan v1, 2026-10-30)

Status: v1, the plan of record for the migration. v0 (2026-10-29, omp 086494f8) was refined by lead
1e61c979 (chain `standalone-b457`) with two second opinions, codex astra (GPT-6) and Fable 5.1, two
research passes, djbclark's answers in section F (2026-10-30), and the fixes for adversary
round 1's findings on PR 154 (safety of probes, archive and drains; plugin scope and fail modes). Until phase D7 lands,
`README.md`, `AGENTS.md` and `docs/orchestration-practices.md` still describe the multi-harness design;
this plan wins where they disagree about the future, they win about today. Sources: section I.

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
   because its quota gates are the only ones that exist today (H4).
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
   worktree workspace removes the worktree (upstream `worktrees.md`), `session-janitor` archives failed or
   closed subagents after 6 hours, and Paseo has no hook before an archive (only `workspace.archive.after`).
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
   3. No slice is created with `autoArchive`; the janitor stays in preview mode (its current mode is
      recorded in D1) or excludes every agent G1 has not marked "branch pushed and report read"; workers lose
      `archive_agent` (B3). G1's "not archived until pushed" is a convention: the operator, the UI and
      `paseo-telegram` can still archive, which is why point 2 exists.
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
   runs against an isolated test daemon: its own `PASEO_HOME` and a Unix socket, or a TCP port claimed in
   `site-djbclark/registry/ports.yml` first, or a scratch user on vps-primary. The live Mac daemon is touched
   only in a drained window (`paseo ls` shows no running agent, G1 reconciled) with djbclark's yes.

## C. Inventory and disposition

Counts are `rg -li` over the repo on 2026-10-29, excluding `graft/` and `docs/handoffs/`.

### C1. Capabilities

| Capability today | Footprint | Disposition | Replacement (section G for plugins) |
|---|---|---|---|
| `skills/session-finder/{relay.py,fleet.py,launch.py,where.py,prompt_line.py,nested_pty.py,adapters/}` | relay.py in 44 files | non-Paseo routes RETIRE in D4; relay.py and fleet.py in D6, once no watcher calls them | `send_agent_prompt` with B2's states; G3 for delivery and deferred send |
| herdr as a harness (`bin/herdr-*`, herdr docs and skills, `-t/-p` naming, panes hosting agents, pane typing) | 139 files | RETIRE | Paseo workspaces; naming `-pw` only |
| `herdr4paseo` (A8.1) | own project | KEEP, edge case | one A8 bridges doc and skill |
| `paseo4herdr` (A8.2), plugin `herdr-harness` (installed, disabled) | own project | KEEP, edge case | same doc and skill |
| tuios as an attach client (A8.1) | — | DECIDE: only if modified for it | same doc and skill |
| Orca (`docs/orca-integration.md`, `skills/orca-cli`, `skills/reorg-orca`, `orca-reorg-watch`, worker-start) | 103 files | RETIRE | Paseo workspaces and subagents |
| Superset/Paradev skills | 10 files | RETIRE (evaluation concluded 2026-10-29) | none |
| `acp-run` (also the agent registry: `acp-run --list` feeds `route_agent.py`) | 138 files | REPLACE in D5 | `paseo provider ls` and the C2 map; an agent with no working provider blocks its own retirement |
| `acp-dispatch`, `acp-dispatch-wait`, records, launchd runners, reap sweep, `tell`, `resume`, `reroute`, exit-code contract (3 no report, 4 BLOCKED, 124 timeout) | 109 files | REPLACE in D5 | `paseo run`/`create_agent` + G1 jobs/deadline + G2 admission + `usage-auto-resume` (+ G5); report-file footer stays as a skill; `paseo run --output-schema` for typed results |
| `acp-dispatch outcome` → `route_agent.py calibrate`, `agent_stats.py burn` | — | KEEP the data | G1 writes the same outcome records, so calibration keeps its source (Fable 2.1, 4.3) |
| `/bigteam`, job records under `~/.local/state/bigteam` | 73 files | REWRITE in D5 | `paseo run` fan-out on G1 |
| `self-slash`, `/new`-`/baton` lifecycle, successor launch, `paseo-new-seat`, `paseo-bypass-watch` | — | SIMPLIFY in D5 | successor created **top-level** from the CLI without `PASEO_AGENT_ID` until D1 proves archive-parent behaviour (an agent-scoped `create_agent` makes the successor a child of the retiring agent, Fable 2.4); keep `/baton` and Tier 1/Tier 2 |
| `helm`, `/helm-all` | — | REPLACE | `paseo permit ls` / `respond_to_permission` for live seats; `paseo ls -a` and Tier 1 pointers for ended sessions |
| `herdr-tidy`, `herdr-sleeper`, `agent-sleep`, `autorename` herdr half | — | RETIRE after the D0.2 drain (sleepers hold Claude session UUIDs per pane: `bin/herdr-sleeper list` must be empty or each resumed as a Paseo agent) | `session-janitor` (running; preview mode or G1-excluded, B4), `archive_agent`; Paseo titles |
| `watch` roles, `fleet-watch` (in `~/ops/site-private/bin`, not this repo), `paseowatch`/`cfenginewatch` (`fleet-watch upstream --relay-to` uses relay.py), `tell-chief-of-staff` | — | REWRITE in D6 | `paseo send` from the launchd script; schedules only where a run needs judgment (F2) |
| `load-watch`, `session-load-watch`, `rumination-watch`, `bg`, gates, `wait-file` | — | KEEP (launchd, F2); drop pane typing | deliver via `paseo send` |
| `claude-quota-guard`, `context-watch`, `context_size_nudge` (provider hooks) | — | KEEP | they run inside the provider; G2 enforces the same gates for launches that bypass the hook |
| `pr-wait`, `ade-git-guard`, `git-commit-own`, `local-review`, graft, `aiuse`, `web-get`, `failover.py`; `ci-waiver` once parked PR 118 lands (not on master) | — | KEEP (harness-neutral) | n/a |
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

0. **Consult and research**: done 2026-10-30 (this v1). Two rules bind every later phase:
   1. **B10**: destructive probes run only on an isolated test daemon or in a drained, approved window.
   2. **Drain gate** (before any "disable" of B8): a script under `tests/paseo-acceptance/drain/` records,
      for the tool being disabled, that it holds nothing: `bin/herdr-sleeper list` empty or each sleeper
      resumed as a Paseo agent with its session UUID; no `acp-dispatch` record quota-stopped or resumable and
      no launchd `auto-resume` job pending (each is resumed with `acp-dispatch resume` to completion, with
      `acp-dispatch` enabled until then, or imported as a Paseo agent with its session id; never a fresh
      dispatch); `relay.py --pending` empty or each expectation retired with a reason; every Orca worktree and
      cow pasture clean and pushed, or its owner named; bigteam inboxes drained.
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
   8. vps-primary, before the pilot (F3): the Paseo daemon password set and the listener bound to the tailnet
      interface only, with a Tailscale ACL that admits the Mac; pilot agents run as a dedicated unprivileged
      user with their own `PASEO_HOME` and no access to the host's deploy or service secrets; provider and
      Telegram credentials in the host's secrets mechanism (sops/agenix or `sudo-secretspec`); the
      upgrade 0.13.0 → 0.14 lands only as the pushed `master` head through `deploy-vps-primary` (home rule
      36). Expected: an unauthenticated request from another tailnet node is refused.
   9. The dead-man check on vps-primary **holds no Mac credential and never calls the Mac daemon**; the Mac
      daemon stays bound to `127.0.0.1`. Each run, the Mac's B9 watchdog writes a heartbeat to vps-primary
      that carries its own result (`/api/health` and the timed real RPC), so a wedged daemon on an awake Mac
      still pages from vps-primary. A sleep/wake hook (IOKit power notification through `sleepwatcher` or an
      equivalent launchd agent) writes `sleeping since T` before sleep and clears it on wake. The Mac writes
      both through a dedicated ssh key restricted on vps-primary (`restrict,command="…write-heartbeat"`) that
      can only replace those two files. The check pages when the heartbeat is stale with no sleep marker,
      when the heartbeat reports a failing daemon, and when a sleep marker is older than a configurable
      threshold (default 72 hours, so a weekend away does not page). A marker followed by silence counts as
      asleep until that threshold. Expected: sleep (no page), daemon killed while awake (page), network cut
      while awake (page); from vps-primary an authenticated Paseo call to the Mac is impossible, and the key
      cannot run anything else.
2. **Minimum plugins and adopted plugins** (section G): G2, G3, G1, G4; `usage-auto-resume` coverage for omp,
   opencode, cline and grok (G5); the Telegram plugin's 0.14 test (F1). **Gate**, on the isolated daemon,
   asserting that the live daemon's state files under `~/.local/state/ade/<serverId>/` are byte-identical
   before and after: three concurrent launches against one pool admit at most what the ledger allows; an
   `aiuse` failure follows G2's fail mode; a reroute is visible to the launcher; a held G3 send survives a
   daemon restart; G4 ignores an agent G1 never recorded (also one labelled after create) and escalates
   compound commands (`;`, `&&`, `|`, `$(`, a newline, `sh -c`); a non-owner Telegram message is refused; a
   forged agent id in an RPC input is refused; the tool catalogs of a UI-created and a Telegram-created
   agent lack the B3 tools; a `worktree` create in a repo without a committed `paseo.json` teardown is
   refused (B4, G2).
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
   on `paseo send`; Paseo schedules for judgment jobs only (F2). Then, after the drain gate and a search
   showing no caller of `relay.py` or `fleet.py` left outside `docs/history/` (the watchers above,
   `fleet-watch upstream --relay-to`, `paseowatch`, `cfenginewatch`, `tell-chief-of-staff`, the quota guard),
   `session-finder` is disabled. **Gate:** a load incident reaches its watcher as a Paseo prompt; that search
   is empty.
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
   is recorded with no proof path (`relay.py:752` returns before any header is read) and never closes, and
   nothing warns at send time. Queued acks themselves close correctly (the header precedes the `[queued …]`
   prefix, pinned by `tests/test_relay_fallback.py:3009`). It matters until D4 retires `relay.py`, because
   D0.2's drain gate relies on acks closing expectations; until then such records are retired with a reason.

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
ledgers. State is written atomically (temp file and rename), and every `reconcile()` acts only on records
carrying its own server id.

**Authorization.** A plugin RPC handler gets no authenticated caller (its input is self-asserted), so
agent-facing operations (`jobs.finish`, `jobs.extend`, `ack.register`) are **plugin agent tools** attached in
`agent.open.before`, authorized by the daemon-supplied `context.agent.id` against the record's owner. RPCs
serve only the operator's UI. This stops mistakes and impersonation over the tool surface, **not** a same-uid
agent with a shell that edits the state files directly; like B3, it is not a boundary (adversary r1 C9, r2 C3
and C8).

1. **`ade-jobs` (plugin, hooks needed)**: durable task ids, deadline and grace, a wrap-up steer at
   T-minus-grace, interrupt at T recorded as exit 124 (cancellation confirmed, and the agent's child
   processes gone, before the writer claim is released), report-file validation, outcome records in the
   existing format, `reconcile()` after a daemon restart that never relaunches blindly. A job's agent is
   never archived until the job records "branch pushed and report read" (B4). Native parts:
   `paseo run --output-schema`, `paseo wait --timeout` (waits, does not cancel). Interface:
   `jobs.submit(taskId, host, workspace, profile, reportPath, deadline, grace)`, `jobs.get`, and, for the
   job's owner only (as agent tools), `jobs.finish`, `jobs.extend(taskId, seconds)`; `jobs.reconcile` (astra C1, Fable 3.1).
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
      human-presence check, and any agent running as the operator's user could write the entry.
   2. **Reservations** are a locked ledger under `~/.local/state/ade/<serverId>/gate/`, decremented on every
      create, so launches inside one cache window cannot all pass.
   3. **Refuse by default; reroute only when the launch carries the label `ade.reroute=ok`**, and then only
      `provider` and `model`, never mode, env, tools or MCP servers; the reroute is written to the agent's
      timeline and the ledger. (Changes made in `agent.create.before` persist after the plugin is removed.)
   4. `agent.open.before` can change only env, tools and MCP servers, so on open the gate can only refuse.
   5. **Named gaps**, taken upstream: `agent.turn.before` is notify-only, so UI sends and
      `usage-auto-resume`'s resume prompts are not gated; and a disabled, crashed or failed-to-reload plugin
      loses its hook registrations, so creates then pass ungated. The B9 watchdog alerts whenever
      `paseo plugin ls` does not show `ade-gate` running.
   6. On `workspace.create.before` it refuses a `worktree` workspace in a repo without a committed
      `paseo.json` teardown (B4).
   7. It reads no secret; anything that needs one runs under `sudo-secretspec run` (astra C3, Fable 3.4).
3. **`ade-ack` (plugin)**: records sends (the `ack.register` agent tool, callable only by the sender). The
   `agent.turn.before` payload carries only the agent and turn ids and hook notifications are best effort with
   no replay, so on each turn start it fetches that turn's timeline through the SDK and marks *delivered*
   when the send is in it; after a restart it reconciles missed turns from history. It holds sends to busy
   non-steer agents in a **durable** queue until idle and deduplicates finish callbacks
   (`messages.send/ack/reconcile`; astra C4, Fable 3.5 and 3.8). Native sends bypass it (B2).
4. **`ade-permit` (plugin)**: **opt-in and fail-closed.**
   1. It trusts **its own record, not a label**: it acts only on agent ids G1 recorded at `jobs.submit`,
      with the provider and the bypass/full mode recorded then (G1 refuses to record an agent launched in a
      restrictive mode such as Always Ask, Write Approval or Plan, or with a deny brief). Labels and modes
      can be changed after create (`update_agent`, `set_agent_mode`), so on every `agent.permission.before`
      it re-reads the agent's current mode through the SDK and does nothing unless it still matches the
      record. The operator's own sessions are never recorded.
   2. On `agent.permission.before` (a notification) it answers with `respondToPermission` only when the
      request, **tokenized with a shell parser**, matches an entry of the reviewed allow-list
      (`config/permit-allow.toml`) exactly as a whole argv, or an entry plus a declared argument shape. It
      escalates any request containing `;`, `&`, `|`, a backtick, `$(`, `>`, `<` or a newline, and any
      `sh -c`, `bash -c`, `python -c` or `eval` wrapper. Everything else, including every question card and
      every outward or hard-to-reverse action, goes to the parent or the operator.
   3. Audit: `~/.local/state/ade/<serverId>/permit/audit.jsonl`, one line per decision, with the request, the
      decision and the policy revision (the allow-list file's git blob id).
   4. It is not a security boundary (B3) (astra C5, Fable 3.6, adversary r1 B1).
5. **Adopted**: `usage-auto-resume` (running; covers Codex, Claude, Antigravity; extend it, or add a small
   turn-end hook (0.14 name per `plugins_hooks.md`), for omp, opencode, cline and grok), `session-janitor` (bounded by B4),
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
