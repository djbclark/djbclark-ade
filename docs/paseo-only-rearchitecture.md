# Paseo-only re-architecture (plan v1, 2026-10-30)

Status: v1, the plan of record for the migration. v0 (2026-10-29, omp 086494f8) was refined by lead
1e61c979 (chain `standalone-b457`) with two second opinions, codex astra (GPT-6) and Fable 5.1, two
research passes, and djbclark's answers to every question in section F (2026-10-30). Until phase D7 lands,
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
   Exception until D5: `acp-dispatch` stays the dispatcher for frontier consults, because its quota gates
   are the only ones that exist today (H4).
7. **Fable and codex astra take part in the re-architecting** (djbclark, 2026-10-29); this overrides the
   routing-policy line that reserves them for `frontier` consults. Both consulted on v0 (section I).
8. **Herdr bridges and attach clients stay, for edge cases** (djbclark, 2026-10-30): two projects, each
   built in its own herdr tab:
   1. **`herdr4paseo`** (tab `herdr4paseo-t`): Herdr attaches to running Paseo agents, as an **attach
      client** that shows and drives an agent Paseo hosts. A modified tuios may do the same.
   2. **`paseo4herdr`** (tab `paseo4herdr-t`; formerly the `paseo-herdr` plugin, installed disabled today as
      `herdr-harness`): Paseo reaches terminals that Herdr hosts.

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
   then interrupts the turn; queue the message until the agent is idle (Fable 3.8; antigravity has no
   steering and no Paseo tools, research 2a).
3. **Blocking is handled by the daemon.** Cards (permissions and questions: `paseo permit ls` lists `question`
   and `OMP ask` cards too) are answered by the parent through `respond_to_permission` under a written
   policy (G4), or reach the operator by push or Telegram (F1). A peer never waits on another's card.
4. **Workspaces are Paseo workspaces** (`isolation: worktree`), which replaces `git worktree add` and cow
   pastures. Paseo has **no writer lock** (several agents may share a workspace), so order 9's one-writer
   claim stays in `ade-git-guard` and its claim registry; the Paseo workspace is the claim's target
   (astra B1, Fable 1.4).
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
   (section D gates), then disables the old entry point, and only the last phase deletes. Rollback
   reconciles live agent ids; it never relaunches paid work (astra D4).
9. **Outside supervision.** A daemon cannot report its own death or hang (#7121: 100% CPU, supervisor saw
   no exit; #2753: health answered while RPCs starved). A launchd watchdog outside Paseo probes
   `/api/health` and times a real RPC (`timeout 20 paseo ls --json`), and alerts through `hermes-ping`
   (F1). Keep active workspaces bounded (about 15), never register giant trees as workspaces, and create
   slice workspaces in the background (Fable 5.2).

## C. Inventory and disposition

Counts are `rg -li` over the repo on 2026-10-29, excluding `graft/` and `docs/handoffs/`.

### C1. Capabilities

| Capability today | Footprint | Disposition | Replacement (section G for plugins) |
|---|---|---|---|
| `skills/session-finder/{relay.py,fleet.py,launch.py,where.py,prompt_line.py,nested_pty.py,adapters/}` | relay.py in 44 files | RETIRE in D4 | `send_agent_prompt` with B2's states; G3 for delivery and deferred send |
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
| `herdr-tidy`, `herdr-sleeper`, `agent-sleep`, `autorename` herdr half | — | RETIRE | `session-janitor` (running), `archive_agent`; Paseo titles |
| `watch` roles, `fleet-watch`, `paseowatch`/`cfenginewatch` (`fleet-watch upstream --relay-to` uses relay.py), `tell-chief-of-staff` | — | REWRITE in D6 | `paseo send` from the launchd script; schedules only where a run needs judgment (F2) |
| `load-watch`, `session-load-watch`, `rumination-watch`, `bg`, gates, `wait-file` | — | KEEP (launchd, F2); drop pane typing | deliver via `paseo send` |
| `claude-quota-guard`, `context-watch`, `context_size_nudge` (provider hooks) | — | KEEP | they run inside the provider; G2 enforces the same gates for launches that bypass the hook |
| `pr-wait`, `ci-waiver`, `ade-git-guard`, `git-commit-own`, `local-review`, graft, `aiuse`, `web-get`, `failover.py` | — | KEEP (harness-neutral) | n/a |
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

Steering: antigravity has none and gets no Paseo tools; claude, codex, opencode and omp follow the generic
steer-or-interrupt contract, which D1 measures per provider (research 2a).

## D. Phases (each a PR with an adversary verdict and CHANGELOG lines; no phase edits a shared checkout)

0. **Consult and research**: done 2026-10-30 (this v1).
1. **Contracts and safety net.** Launchd watchdog (B9) with `hermes-ping`; vps-primary daemon upgraded from
   0.13.0 to 0.14 through its NixOS config and the dead-man check there (F1, F3); the C2 map; live
   capability probes written as repeatable scripts under `tests/paseo-acceptance/`: steer while running per
   provider; a parent answering a question card's *option* (not only allow/deny) via
   `respond_to_permission`; archive-parent with a running child; daemon restart with a queued prompt, a
   pending `notifyOnFinish` and a schedule; schedule missed-run behaviour across Mac sleep.
   **Gate:** every probe has a recorded result; the watchdog has fired once on a forced hang.
2. **Minimum plugins and adopted plugins** (section G): G2 admission, G3 delivery, G1 jobs/deadline,
   G4 permission policy; `usage-auto-resume` coverage for omp/opencode/cline/grok (G5); the Telegram plugin's
   0.14 compatibility test (F1). **Gate:** each plugin's own acceptance test, plus concurrent admission of
   three launches against one pool.
3. **Canary.** One real workflow end to end on Paseo only: work → review → CI → report, including a forced
   quota stop that resumes, a forced daemon restart that loses nothing, and the one-task pilot on
   vps-primary with its report retrieved on the Mac. **Gate:** no paid job or artifact depended on a
   retiring tool; outcome records written.
4. **Seat and communication cutover.** Every launch is `paseo run`/`create_agent`; `relay.py` routes only
   `--via paseo` (strangler), then its other routes are disabled; a `paseo-peers` skill (B2 states, G3,
   named acks per standing order 10) replaces `peer-relay`; helm, herdr-tidy and session-finder retire.
   **Gate:** `relay.py --plan` prints `paseo` only for every live agent; G3 shows `delivered` for a
   cross-workspace send.
5. **Dispatch, then lifecycle.** `acp-dispatch`/`acp-run` replaced by G1 on Paseo subagents (records kept
   readable until calibration reads G1's); `/bigteam` and the dispatch footer rewritten; then `self-slash`
   successors top-level (C1). **Gate:** one `/bigteam` wave of three slices with deadline, report file and
   one forced quota stop; a successor survives its parent's archive with the chain pointer intact.
6. **Watchers and notifiers.** `fleet-watch`, `load-watch` delivery, quota-guard steers and the watch roles
   on `paseo send`; Paseo schedules for judgment jobs only (F2). **Gate:** a load incident reaches its
   watcher as a Paseo prompt.
7. **Deletion and docs.** Disable then delete retired entry points; README, both AGENTS.md, ops AGENTS.md,
   memory pointers, skills index, `apply-toolchain-prompt.md`, `mcp-servers.md`; write `docs/history/`.
   `rg -i 'herdr|orca|tmux|superset|tuicommander|relay\.py|acp-run|acp-dispatch'` outside `docs/history/`
   returns nothing except `herdr` and `tuios` in the A8 bridges doc and skill (CI, `context-policy` job).

Least reversible steps: deleting the dispatch record format (D5, keep readable until calibration moves),
archive-on-finish deleting worktrees (turn it off before any schedule keeps work, F2), and the instruction-file
rewrites (D7). Each happens only after its gate.

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

## F. Decisions (djbclark, 2026-10-30, after the consults and research)

1. **Notifications**: Paseo native push for agent events (finished, error, permission, question). The B9
   launchd watchdog sends `hermes-ping` on a sustained failure, unexpected exit, failed recovery and
   recovery; a dead-man check on vps-primary covers the Mac asleep or offline. Also install the reviewed
   `Daaaaave/paseo-telegram` plugin (0.2.3) to answer cards from Telegram, after a 0.14 compatibility test
   (D2); it covers no daemon outage. Note: the Mac daemon runs with the Paseo relay off; push goes from the
   daemon to Expo directly (research B2), which D1 verifies with the phone off the tailnet.
2. **Unattended runs**: split by job kind. Paseo schedules only for runs that need judgment
   (`skillopt-night`, triage, reports); launchd (systemd on Linux) for monitors, collectors, record reaping
   and the watchdog. Schedules that keep worktrees need archive-on-finish turned off in the app first.
3. **Second daemon**: use the **existing** vps-primary Paseo daemon (0.13.0, NixOS system service, connected
   to the Mac over the tailnet; 3.7 GiB RAM, 2 vCPU) for the one-task pilot and the dead-man check, after
   upgrading it to 0.14. Correction (lead 1e61c979, 2026-10-30): the first F3 answer chose a new Hyades
   microVM because the lead had not checked `paseo host ls`; Fable's consult found the daemon. Not on
   pastebin.xvm.mit.edu (too little memory).
4. Keep OpenCode plugins that act inside the provider session; drop anything that acts as an alternate harness.
5. The history goes in a `docs/history/` directory; the end-state grep exempts only that directory.
6. omp Opus 5.5 high leads the judgment phases and Sonnet 5.5 the mechanical ones; Fable and astra consult.
   Every launch stays subject to the live quota gates: when omp is rate-gated (it shares the Claude weekly
   window), judgment work waits or goes to codex per the routing policy (Fable 1.7).
7. Phase order: astra's (contracts, minimum plugins, canary, communication, lifecycle/dispatch, watchers,
   deletion), refined with Fable's seat-before-communication and dispatch-before-lifecycle (section D).

## G. What we build (replacement order A3; interfaces are sketches for D2)

1. **`ade-jobs` (plugin, hooks needed)**: durable task ids, deadline and grace, a wrap-up steer at
   T-minus-grace, interrupt at T recorded as exit 124, report-file validation, outcome records in the
   existing format, `reconcile()` after a daemon restart that never relaunches blindly. Native parts:
   `paseo run --output-schema`, `paseo wait --timeout` (waits, does not cancel). Interface:
   `jobs.submit(taskId, host, workspace, profile, reportPath, deadline, grace)`, `jobs.get`, `jobs.finish`,
   `jobs.reconcile`, `jobs.extend(taskId, seconds)` (astra C1, Fable 3.1).
2. **`ade-gate` (plugin)**: `before("agent.create")` and `before("agent.open")` run the `aiuse` and
   `load-watch ci decide` checks (cached about 60 s, under the hooks' 30 s ceiling), refuse with a reason
   or reroute to an eligible profile, and record the reservation. `agent.turn.before` is notify-only, so
   per-turn gating of UI sends is a named gap to take upstream (astra C3, Fable 3.4).
3. **`ade-ack` (plugin)**: records sends (`ack.register(agentId, token)`), marks *delivered* on the
   recipient's next `turn_started` carrying it, holds sends to busy non-steer agents until idle, and
   deduplicates finish callbacks (`messages.send/ack/reconcile`, astra C4, Fable 3.5 and 3.8).
4. **`ade-permit` (plugin)**: on `agent.permission_requested`, allow what the standing yolo rule allows,
   deny the hard-to-reverse set, leave questions and outward actions to the parent or operator, audit
   every decision; provider modes carry routine authorization (astra C5, Fable 3.6).
5. **Adopted**: `usage-auto-resume` (running; covers Codex, Claude, Antigravity; extend or add a small
   `turn_ended` hook for omp, opencode, cline and grok), `session-janitor`, `fresh-worktrees`,
   `Daaaaave/paseo-telegram` (F1). Before adding any plugin, check overlap with these (astra B3).
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
