# Paseo-only re-architecture (plan v0, 2026-10-29)

Status: DRAFT written by the retiring lead (omp 086494f8, chain `standalone-b457`) in the hour after the
ruling, before any consult or web search. The successor lead refines it with Fable and codex astra
(GPT-6) second opinions, web research, and djbclark's answers to the open questions in section F, then
promotes it to the architecture of record. Until then the facts in `README.md`, `AGENTS.md` and
`docs/orchestration-practices.md` still describe the multi-harness design.

## A. The ruling (djbclark, 2026-10-29, verbatim intent)

1. **Paseo only.** No herdr, no tuios, no other harness (Orca, Superset/Paradev, TUICommander, raw tmux
   panes, Hermes-as-harness). Every agent the operator talks to is a Paseo agent. Amended by A8: two
   edge-case Herdr bridges and possibly a modified tuios stay, never as harnesses.
2. **Retire `relay.py`** and every non-Paseo channel; inter-agent communication moves to Paseo's native
   framework (`send_agent_prompt`, `create_agent` with `notifyOnFinish`, `list_agents`,
   `respond_to_permission`, heartbeats, schedules, `PASEO_PARENT_ID` lineage, the parent-wake plugin).
3. **Replacement order for every djbclark-ade capability:** (a) native Paseo functionality or skill;
   (b) an existing Paseo plugin; (c) a Paseo plugin we write; (d) only then keep it in djbclark-ade.
4. **End state:** no mention of any harness other than Paseo anywhere in djbclark-ade, `~/AGENTS.md`
   (`site-djbclark/cursor/home-agents.mdc`), the ops `AGENTS.md` files, skills, docs or memory pointers,
   except the history that is not normally read (the `docs/history/` directory, F5, to be written from the
   retired material), the Herdr bridges and attach-client material of A8, and, during the migration, this plan.
5. **Basis:** the research in `Open-Source AI Agent Harnesses Compared.pdf` (Paseo Desktop upload
   `upload_d70305b6-6865-461c-83df-aab4fb305afb`, 2026-10-29): Paseo scores 92.2/100 on non-blocking
   inter-TUI communication once ClinePass and OpenCode Go support without code is a hard requirement
   (TUICommander 87.4, Superset 56); Paseo wins on picklist/permission unblocking (`respond_to_permission`,
   steer past a card), lineage and heartbeats ("never losing each other"), and the native Android app.
   Known weakness to design around: a single Node event loop (upstream issues #2753, #7121) and a
   100-250 MB daemon.
6. **Fan-out during the migration:** not `/bigteam` (until it is rewritten on Paseo), but Paseo-native
   subagents (`create_agent` from the lead, `notifyOnFinish: true`) and the `/paseo-handoff`,
   `/paseo-advisor`, `/paseo-committee` skills, so the lead stays in touch and is never blocked on a
   picklist or card.
7. **Both Fable and codex astra (GPT-6) take part in the re-architecting** (djbclark, 2026-10-29); this
   overrides the routing-policy line that reserves them for `frontier` consults.
8. **Herdr bridges and attach clients stay, for edge cases** (djbclark, 2026-10-30): two separate projects,
   each built in its own herdr tab, and both allowed to exist:
   1. **`herdr4paseo`** (tab `herdr4paseo-t`): Herdr attaches to running Paseo agents. Herdr is an **attach
      client**: it shows and drives an agent that Paseo hosts. A modified tuios may do the same.
   2. **`paseo4herdr`** (tab `paseo4herdr-t`; formerly the `paseo-herdr` plugin): Paseo reaches terminals
      that Herdr hosts.

   **These two are the only Herdr integration.** Herdr agents do not talk to Paseo agents: no messaging,
   relaying, launching, naming, sleeping or fleet tracking through Herdr, and no djbclark-ade tool depends on
   either bridge. They are useful in a few edge cases, nothing more.

## B. Principles for the new architecture

1. One daemon of record: `paseo` holds the session graph, lineage, permissions, terminals, worktrees,
   schedules and heartbeats. djbclark-ade stops keeping its own fleet registry, pane maps, transcript
   finders and waiters.
2. Communication is a Paseo prompt or event, never typed text: no screen scraping, no prompt-line
   detection, no "is the composer empty" waits, no pane typing.
3. Blocking is handled by the daemon: a card is answered by `respond_to_permission` from the parent (under
   the operator's standing yolo rule) or surfaced to the operator on the phone; a peer is never asked to
   wait on another's card.
4. Workspaces are Paseo workspaces (`create_workspace` with `isolation: worktree`), which absorbs the
   claimed-worktree commandment (order 9) and `cow-workspaces`.
5. Anything we still need that Paseo lacks is a Paseo plugin (`paseo plugin add`, TypeScript SDK/MCP),
   living in its own repo or under `paseo-plugins/` here, never a sidecar script that talks to a TUI.
6. Routing, quota and cost policy stay (they are provider policy, not harness policy) but are expressed
   as Paseo agent profiles (`list_profiles`) plus `aiuse`.
7. The A8 bridges are edge-case tools. Nothing in the toolchain depends on either being installed or open, and
   no tool reads, types into, or messages an agent through Herdr or tuios.

## C. Inventory and disposition (first pass; counts are `rg -li` over the repo on 2026-10-29,
excluding `graft/` and `docs/handoffs/`)

| Capability today | Footprint | Disposition | Paseo replacement |
|---|---|---|---|
| `skills/session-finder/{relay.py,fleet.py,launch.py,where.py,prompt_line.py,nested_pty.py,adapters/}` | relay.py in 44 files | RETIRE | `send_agent_prompt` (steer/interrupt), `list_agents`, `PASEO_PARENT_ID`; acks become `notifyOnFinish` events |
| herdr as a harness (`bin/herdr-*`, `docs/herdr-*.md`, `skills/herdr*`, pane/tab naming `-t/-p`, panes hosting agents, pane typing) | 139 files | RETIRE | Paseo workspaces/tabs; naming `-pw` only |
| `herdr4paseo`: Herdr as an attach client to running Paseo agents (A8.1) | own project, tab `herdr4paseo-t` | KEEP, edge case | one doc and one skill: how to attach Herdr to a running Paseo agent |
| `paseo4herdr`: Paseo reaching Herdr-hosted terminals (A8.2), formerly `paseo-herdr` | own project, tab `paseo4herdr-t` | KEEP, edge case | the same doc and skill |
| tuios as an attach client (A8.1), possibly modified | — | DECIDE: only if tuios is modified to attach to Paseo agents | the same doc and skill |
| Orca (`docs/orca-integration.md`, `skills/orca-cli`, `skills/reorg-orca`, worker-start) | 103 files | RETIRE | Paseo workspaces + subagents |
| Superset/Paradev skills (`skills/superset-*`) | 10 files | RETIRE (evaluation concluded, 2026-10-29) | none |
| `acp-run`, `acp-dispatch`, `acp-dispatch-wait`, dispatch records, launchd runner scripts, reap sweep | 138 + 109 files | REPLACE | `create_agent` (worktree workspace, `notifyOnFinish`), schedules for unattended runs; keep only what Paseo cannot do (decide in consult: timeouts/wrap-up turn, report files, resume-after-quota) |
| `/bigteam`, job records under `~/.local/state/bigteam` | 73 files | REWRITE on Paseo subagents | `create_agent` fan-out, `list_agents` status, reports still as files |
| `self-slash`, `/new`-`/baton` lifecycle, successor launch, `paseo-new-seat`, `paseo-bypass-watch` | — | SIMPLIFY | Paseo-native: `send_agent_prompt`, `create_agent` successor, agent profiles for mode; keep `/baton` + Tier 1/Tier 2 (document layer, harness-neutral) |
| `helm`, `herdr-tidy`, `herdr-sleeper`, `agent-sleep`, `watch` roles, `fleet-watch` notices | — | REPLACE | `list_pending_permissions` + `respond_to_permission`; heartbeats; `archive_agent`; Paseo notifications to the phone |
| `load-watch`, `bg`, gates, `context_size_nudge`, `context-watch`, quota guard | — | KEEP (machine policy) but drop pane typing; deliver via Paseo prompts/heartbeats | heartbeats, `update_agent` settings |
| `pr-wait`, `ci-waiver`, `ade-git-guard`, `git-commit-own`, graft, `aiuse`, `web-get`, `failover.py` | — | KEEP (harness-neutral tooling) | n/a |
| Hermes (`hermes-ping`, Hermes as a seat) | 163 files | DECIDE in consult: keep `hermes-ping` as the Telegram notifier only if Paseo's own push notifications do not cover it; Hermes is no longer a harness | Paseo mobile notifications |
| `skills/model-routing`, `route_agent.py`, `docs/model-routing.md` | — | KEEP policy, strip harness table | Paseo profiles |
| `opencode-plugins/`, `docs/opencode-plugin-v2.md`, OpenCode V2 Go sessions | 128 files | DECIDE: OpenCode is a Paseo provider; the plugins stay only if they act inside the provider session, not as a harness | Paseo provider `opencode` |
| `cursor-cloud`, Cursor agents | 14 files | DECIDE (cloud agent, not a harness; likely keep as a tool) | — |
| `README.md` "two altitudes", `docs/orchestration-practices.md`, `docs/coding-factory.md`, `docs/ade-everywhere-*` | — | REWRITE / ARCHIVE into the history doc | — |
| `~/AGENTS.md` items 4, 24-26, 30, 33; `djbclark-ade/AGENTS.md` order 9-10 and the Machine context section | — | REWRITE (Opus 5.5+ edits `home-agents.mdc`, home rule) | — |

## D. Phases (each phase a PR with an adversary verdict; CHANGELOG lines; no phase edits a shared checkout)

0. **Consult and research** (successor lead): Fable and codex astra second opinions on this plan; web
   searches: Paseo native inter-agent API surface and limits (`send_agent_prompt` steer semantics per
   provider, `respond_to_permission`, parent-wake plugin, heartbeats, SDK/MCP server, plugin API, known
   event-loop issues #2753/#7121, multi-daemon/remote Linux workers), existing Paseo plugins that cover
   our needs (`docs/paseo-plugins-scan-2026-10-19.md` is the last scan), TUICommander/Orca only as
   contrast. Output: this doc v1 with decisions, the F questions answered by djbclark.
1. **Communication cutover**: every skill/doc that says "relay.py" says Paseo prompts; peer-relay,
   session-finder, helm, herdr-tidy, watch roles retired or rewritten; a `paseo-peers` skill (native
   comms recipes, ack discipline via `notifyOnFinish`) replaces `peer-relay`.
2. **Lifecycle cutover**: `self-slash`/handoff/baton on Paseo only; successor = `create_agent` in the
   same workspace with the chain pointer; `paseo-new-seat`/`paseo-bypass-watch` folded into profiles or
   a plugin; `agent-sleep`/`herdr-sleeper` retired.
3. **Dispatch cutover**: `acp-dispatch`/`acp-run` replaced by Paseo subagents in worktree workspaces
   (reports still as files; timeouts via heartbeats or a plugin); `/bigteam` rewritten; dispatch footer
   rewritten; `adversary` sub-agent as a Paseo subagent.
4. **Watchers and notices**: `fleet-watch`, `load-watch` pane typing, quota guard steers become Paseo
   prompts/heartbeats/schedules; Hermes decision applied.
5. **Docs and instruction files**: README, AGENTS.md (both), ops AGENTS.md, memory pointers, skills
   index, `apply-toolchain-prompt.md`, `mcp-servers.md`; write `docs/history/` from the
   retired material; `rg -i 'herdr|orca|tmux|superset|tuicommander|relay\.py|acp-run|acp-dispatch'`
   outside that directory returns nothing, except `herdr` and `tuios` in the one A8 bridges doc and skill
   (CI check, `context-policy` job).
6. **Plugins**: whatever D0 decided we must write (candidates: dispatch-with-timeout-and-report,
   quota-aware launch gate, Telegram notifier if Paseo's push is insufficient), each its own repo or
   `paseo-plugins/`, upstreamed where general (home rule 38).

## E. Carry-overs from the retiring lead (not part of this plan but must not be lost)

1. PR 118 (CI waiver, docs-only class): parked at head `d55a8b4b` with adversary r9 BLOCK (narrow: push
   needs `--force-with-lease=refs/heads/master:<proved master>`, three untested guards, `[remote
   rejected]` message). Harness-neutral; resume or close after the migration (`docs/queue.md`).
2. D3 Nimbalyst Wiki install/test, assigned to the lead by djbclark via 0b70f359 (2026-10-29): parked,
   to run as its own Paseo subagent in a worktree workspace after phase 1.
3. `docs/queue.md` entries unchanged.
4. The former `paseo-herdr` plugin is now `paseo4herdr` (A8.2), worked on in herdr tab `paseo4herdr-t`;
   `herdr4paseo` (A8.1) is worked on in tab `herdr4paseo-t`. djbclark wants both (2026-10-30). This plan
   writes in neither project; it only bounds them (A8, B7).

## F. Open questions for djbclark (successor asks with numbered options, one per card)

Answers so far (djbclark, 2026-10-30, after the codex astra consult; the Fable consult is pending):

1. **DECIDED** (2026-10-30, after research): Paseo native push for agent events (finished, error, permission,
   question). A launchd watchdog outside Paseo probes `/api/health` and times a real RPC, and sends `hermes-ping`
   on a sustained failure, unexpected exit, failed recovery and recovery. A dead-man check on the second
   daemon's host covers the Mac asleep or offline. Also install the reviewed `Daaaaave/paseo-telegram` plugin
   (0.2.3) to answer cards from Telegram, after a 0.14 compatibility test; it covers no daemon outage.
2. **DECIDED** (2026-10-30): split by job kind. Paseo schedules only for runs that need judgment
   (`skillopt-night`, triage, reports); launchd (systemd on Linux) for monitors, collectors, record reaping and
   the daemon watchdog, which must not depend on the daemon. Schedules that keep worktrees need archive-on-finish
   turned off in the app first.
3. **DECIDED** (2026-10-30): pilot a second Paseo daemon now on Hyades, in a new `djbclark-paseo` microVM, on
   one isolated task; it also hosts the F1 dead-man check. Not on pastebin.xvm.mit.edu (too little memory). The
   slot comes from folding `djbclark-kev` and `djbclark-laya` into one `djbclark-jevlike` microVM that loads one
   judge at a time (each needs nearly the 8 GiB per-microVM cap, MemTotal measured 7.78 GiB); both
   `*.sipb.cloud` names stay; the default judge is the one consumer d2a505dd is using. Reach the daemon over
   Tailscale inside the microVM, as `get` did, or Paseo's outbound relay; no `exposeports`.
4. **DECIDED**: keep OpenCode plugins that act inside the provider session; drop anything that acts as an
   alternate harness.
5. **DECIDED**: a `docs/history/` directory rather than one file; the end-state grep exempts only that directory.
6. **DECIDED**: omp Opus 5.5 high leads the judgment phases, Sonnet 5.5 the mechanical ones, Fable and codex
   astra consult; every launch stays subject to the live quota gates.
7. **DECIDED**: adopt the astra phase order: contracts, then the minimum jobs/admission/message-receipt
   support, then a canary workflow, then the communication cutover, then lifecycle and dispatch, then watchers
   and notifiers, then deletion. Old tools stay until their replacements pass live acceptance gates. Section D is
   rewritten to this order in plan v1.
