# Paseo-only re-architecture (plan v0, 2026-10-29)

Status: DRAFT written by the retiring lead (omp 086494f8, chain `standalone-b457`) in the hour after the
ruling, before any consult or web search. The successor lead refines it with Fable and codex astra
(GPT-6) second opinions, web research, and djbclark's answers to the open questions in section F, then
promotes it to the architecture of record. Until then the facts in `README.md`, `AGENTS.md` and
`docs/orchestration-practices.md` still describe the multi-harness design.

## A. The ruling (djbclark, 2026-10-29, verbatim intent)

1. **Paseo only.** No herdr, no tuios, no other harness (Orca, Superset/Paradev, TUICommander, raw tmux
   panes, Hermes-as-harness). Every agent the operator talks to is a Paseo agent.
2. **Retire `relay.py`** and every non-Paseo channel; inter-agent communication moves to Paseo's native
   framework (`send_agent_prompt`, `create_agent` with `notifyOnFinish`, `list_agents`,
   `respond_to_permission`, heartbeats, schedules, `PASEO_PARENT_ID` lineage, the parent-wake plugin).
3. **Replacement order for every djbclark-ade capability:** (a) native Paseo functionality or skill;
   (b) an existing Paseo plugin; (c) a Paseo plugin we write; (d) only then keep it in djbclark-ade.
4. **End state:** no mention of any harness other than Paseo anywhere in djbclark-ade, `~/AGENTS.md`
   (`site-djbclark/cursor/home-agents.mdc`), the ops `AGENTS.md` files, skills, docs or memory pointers,
   except ONE history document that is not normally read (`docs/history-multi-harness.md`, to be written
   from the retired material) and, during the migration, this plan.
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

## C. Inventory and disposition (first pass; counts are `rg -li` over the repo on 2026-10-29,
excluding `graft/` and `docs/handoffs/`)

| Capability today | Footprint | Disposition | Paseo replacement |
|---|---|---|---|
| `skills/session-finder/{relay.py,fleet.py,launch.py,where.py,prompt_line.py,nested_pty.py,adapters/}` | relay.py in 44 files | RETIRE | `send_agent_prompt` (steer/interrupt), `list_agents`, `PASEO_PARENT_ID`; acks become `notifyOnFinish` events |
| herdr (`bin/herdr-*`, `docs/herdr-*.md`, `skills/herdr*`, pane/tab naming `-t/-p`) | 139 files | RETIRE | Paseo workspaces/tabs; naming `-pw` only |
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
   index, `apply-toolchain-prompt.md`, `mcp-servers.md`; write `docs/history-multi-harness.md` from the
   retired material; `rg -i 'herdr|orca|tmux|superset|tuicommander|relay\.py|acp-run|acp-dispatch'`
   outside that one doc returns nothing (CI check, `context-policy` job).
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

## F. Open questions for djbclark (successor asks with numbered options, one per card)

1. Hermes: keep `hermes-ping` as a notifier, or rely on Paseo mobile notifications only?
2. Unattended runs (nightly `skillopt-night`, `reap`, `load-watch`): Paseo schedules, or keep launchd for
   non-agent jobs?
3. Remote Linux workers (vps-primary, Hyades): a second `paseo` daemon there now, or later?
4. OpenCode plugins and the OpenCode V2 Go sessions: keep as provider-side plugins, or drop?
5. The history document's name and location.
6. Lead model for the migration (this draft proposes omp Opus 5.5 high for judgment phases, Sonnet 5.5
   for pipeline phases; Fable and astra as consults per A7).
