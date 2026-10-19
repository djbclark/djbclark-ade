# Software factory research digest (2026-10-19)

Summary: what two frontier reads, an OpenRig study and a landscape sweep say about adding the
software factory (`docs/software-factory-design.md`, DRAFT v2) to the ADE-everywhere plan
(`docs/ade-everywhere-proposal.md`). Verdict: add it as a thin state machine over `acp-dispatch`,
a parallel "Phase F" starting after Phase 1's CI workflow lands; borrow five ideas from OpenRig
and agent-stack now; do not adopt OpenRig as a third fabric. Thirteen questions for djbclark are
listed in §5, numbered on from the Fable report's SF-Q1 to SF-Q9. Everything dated here was
checked on 2026-10-19 unless marked otherwise.

## 1. Sources

1. Fable 5.1 high, read-only advise (`acp-dispatch --kind frontier --role advise`), report copied to
   [software-factory-reviews/fable-research-2026-10-19.md](software-factory-reviews/fable-research-2026-10-19.md).
2. Codex `gpt-6-astra` high, same brief, third attempt (the first two ended on a refused
   escalation and a sandboxed-execute tripwire; both fixed in b33d028 and e72a777). Still running
   when this digest was written; §6 is its placeholder.
3. OpenRig: the README, blog index, `compare/paperclip`, `compare/claude-agent-teams`, and
   korallis/agent-stack's README, all fetched 2026-10-19 (jina, exa, parallel; the shared
   firecrawl search returned no web results for any query that day).
4. Landscape numbers: `gh api repos/<owner>/<repo>` on 2026-10-19 for stars, licence and last push.
5. Ry Walker's thirteen-tool comparison of agent orchestrators (2026-09-15), used for its
   evaluation criteria, not its scores.

## 2. The Fable read in six lines

1. The factory is worth adding but as a state machine over tools the plan already owns:
   `acp-dispatch` already has job records, reports, `BLOCKED:`, quota resume, reaping, detached
   launchd runs, `--perm read-only` and routing. New work is a per-job `events.jsonl`, a
   `verdict.json` contract, a workspace adapter, CI-run `verify` and a PR opener.
2. Four design claims are wrong for this machine: bwrap on macOS (absent; Seatbelt only),
   `verify` on the Mac (CI-first rule), hard-coded agent per role (cheapest eligible tier rule),
   and job state inside the target repo (state lives under `~/.local/state/factory/`).
3. No third UI: Paseo is the front end (proposal Q9); Hermes Telegram already renders approval
   buttons; `ready` means "PR opened", and the merge button is GitHub's own.
4. Reviewer roles are limited to the four read-only-capable agents (claude, codex, opencode,
   zcode); cline is out; the reviewer-code vendor should differ from the builder's.
5. Placement: Phase F (F1 orchestrator, F2 reviews + pasture + PR, F3 Paseo panel) beside
   Phases 2-3, after Phase 1's first PR; GitHub Issues intake and any auto-merge wait for Phase 5+.
6. Nine questions (SF-Q1 to SF-Q9) remain for djbclark; they are restated in §5 with the OpenRig
   and Paseo questions added after them.

## 3. OpenRig and the comparable projects

### 3.1 What OpenRig is

OpenRig (openrig.dev, the YouTube talk djbclark linked) is a Node 22 CLI that runs a team of
terminal coding agents as a **rig**: pods of seats, each seat an agent TUI in a tmux pane, with a
durable work queue, shared context packs and an orchestrator seat. It installs and uses Herdr by
default as its terminal fabric, which is why its author's earlier video ran his "AI civilization"
in Herdr. Concepts, with the ADE equivalent where one exists:

| OpenRig concept | What it does | ADE today |
|---|---|---|
| rig / pod / seat addresses (`dev-build@starter`) | stable names for agents, used by every command | herdr pane ids; `acp-run --list` names |
| RigSpec / AgentSpec YAML | declarative team shape, agent per seat, model, prompt | `config/routing.toml` plus `route_agent.py plan` (per slice, not a standing team) |
| `CULTURE.md` | one file of team norms every seat reads | `AGENTS.md`, `~/CLAUDE.md`, `skills/` |
| `rig send/capture/broadcast/chatroom` | tmux-keystroke transport between seats | ACP (`acp-run`, `acp-dispatch`), `session-finder/relay.py` |
| `rig queue` (durable, owned items; a message never creates a queue item) | the work ledger, separate from chat | `acp-dispatch` job records, `docs/queue.md`, bigteam records |
| context packs with addressable headings, profiles fresh / post-compaction / reviewer | `rig context get 'pack/file.md#heading'` hands a seat only the slice it needs | graft nodes, `session-handoff`, the `handoff` skill, `/baton` |
| rig bundles: pinned commit + package digest + "what it writes to your machine" + tested-configuration ladder + registry | reproducible, auditable install of a whole rig | ade-kit (proposal §4.4) has no manifest of this shape yet |
| seat continuity and inheritance skills | a replacement seat inherits its predecessor's state | `baton`, `session-handoff` Tier 1, `self-slash --then` |
| lore folder | durable lessons by topic | `~/ops/site-private/memory/feedback_*.md`, Basic Memory |
| epistemic maturity ladder | how far a claim has been verified, stated with the claim | standing order 4 ("verify against the artifact") in prose only |
| HA orchestrator pair, witness and dogfood seats | a second orchestrator watches the first; a witness seat checks the deployed result | none; `fleet-watch` watches services, not work |
| `rig ask` over saved transcripts | question answering over the rig's own history | `s1_search.py`, `agents-history`-style Paseo plugins |
| workflows + watchdog | YAML workflows with a stuck detector | Orca task DAG, `acp-dispatch reap`, `agent-sleep` |
| `rig scope slice create` (spec, progress, proof folders) | one folder per slice holding the spec, the progress log and the proof | bigteam scratchpad per slice, report file contract |
| non-interruptive mode | yolo for every seat | item 16 of `~/CLAUDE.md` |

Risks seen in the sources: the transport is tmux keystrokes and screen capture, not a protocol
(ACP is the ADE's choice, proposal §3); `rig install` writes hooks, trust settings and agent
settings files into the home directory; the 0.6.x line moved weekly during September and
October 2026; Node 22 is required on every host.

### 3.2 agent-stack: an existing OpenRig glue project

korallis/agent-stack (Apache-2.0, 35 stars, created 2026-09-28, last push 2026-10-05, Linux only)
is OpenRig plus Claude Code, Codex, CLIProxyAPI, TypeSafe Jev and Playwright, with a merge gate
that is the most complete one found in any open project:

1. CI required checks green on the exact candidate head.
2. An `independent-review` commit status from a reviewer seat of a different vendor.
3. A QA seat's `proof/brb-<head>.md` with `PASS` for that exact head, produced by a Playwright
   run against the deployed candidate.
4. A live Jev `review.merge_gate` decision in the act band.
5. Only then `gh pr merge --squash --match-head-commit <sha>`, so a push after review cannot
   merge under the old verdicts.

It also carries three more Jev decision sites the ADE's `bin/jev` (shadow mode since 2026-10-11)
has no equivalent for: `agent-dispatch pick-seat` (which seat takes a slice), `agent-stuck-check`
(is a seat stuck, and what to do) and `agent-reroute` (move a slice to another seat). A witness
agent checks the deployed app after merge.

### 3.3 Comparable projects, dated 2026-10-19

| Project | Stars | Licence | Last push | Shape | Takeaway for the ADE |
|---|---|---|---|---|---|
| paperclipai/paperclip | 104,664 | MIT | active | "company" of agents: tickets, heartbeats, per-agent budgets, Postgres, dashboard | budget per agent and a ticket as the unit of work; too heavy (Postgres, its own UI) |
| openai/symphony | 27,744 | Apache-2.0 | 2026-09-15 | Linear board drives Codex workers; engineering preview, not maintained as a product | board-as-control-plane; Codex-only |
| gastownhall/gastown | 18,431 | MIT | active | Mayor + polecats, hooks = worktrees, convoys, Beads tickets, Witness / Deacon / Dogs watchers, Refinery bisecting merge queue; Gas City toolkit | the bisecting merge queue and the watcher roles; Paseo has a Gas City control-plane plugin |
| OrchestratorInc/agent-orchestrator | 13,378 | Apache-2.0 | active | desktop app + daemon, persistent project orchestrator, worktree workers, live Kanban | closest desktop shape to "Paseo + factory" |
| snarktank/antfarm | 2,496 | | active | OpenClaw-based agent farm | not ACP; skip |
| 777genius/agent-teams-ai | 2,281 | AGPL | active | agent teams | AGPL; read for ideas only, never code |
| jayminwest/overstory | 1,315 | | archived | superseded by Warren | skip |
| open-mercato/cezar | 733 | MIT | active | "orchestrator and ADE": worktree per task, YAML workflows, runs 24/7 on a VPS, no database, nothing auto-merges | the no-database, nothing-auto-merges stance matches the Fable verdict |
| korallis/agent-stack | 35 | Apache-2.0 | 2026-10-05 | OpenRig + Jev + Playwright merge gate (§3.2) | mine the gate and the Jev sites |
| Alireza29675/teamctl, creynir/phalanx, VeNom, agent-teams, Aqua, teamfuse | 3-20 | mixed | | small team runners | nothing the above do not |

The Fable report's own list (zazencodes, spec-kit, OpenSpec, ccpm, Aperant, claude-squad,
Superset, Cloudroom, OpenHands Agent Canvas, Copilot, Jules) stands; it missed every row above
except Symphony.

Ry Walker's comparison gives five criteria every row above can be scored on, and the factory
should state them in its own README: reproducible environment, task ownership, recovery from an
interrupted run, independent verification, explicit merge policy.

### 3.4 What to borrow now (no new runtime)

1. **Exact-head verification and `--match-head-commit`.** Every verdict (CI, adversary, code
   review, QA proof) names the sha it judged; the PR opener records it; any later merge
   automation passes `--match-head-commit`. Cost: a few lines in the factory's PR step and in
   `docs/orchestration-practices.md`.
2. **Jev decision sites.** Add `pick-seat` (which agent takes a slice: a typed wrapper over
   `route_agent.py plan`), `stuck-check` (over `acp-dispatch check` and `agent-sleep` data) and
   `merge-gate` to `bin/jev`, shadow first like the existing sites.
3. **Witness step.** For repos with a deployed app, an optional post-merge slice that checks the
   deployment and files an issue on failure. Phase 5 or later.
4. **Bundle-style manifest for ade-kit.** Pinned commit, package digest, a "what it writes to
   your machine" list and a tested-configuration ladder (macOS / NixOS / Ubuntu, each with the
   date and commit last verified). Goes into proposal §4.4.
5. **Spec, progress, proof per slice.** The factory's per-job directory keeps the three as named
   files, so a reviewer, a witness and a human read the same artefacts.

Already covered, no action: project-world map (graft map plus the `AGENTS.md` trailhead), seat
inheritance (baton and session-handoff), lore (memory feedback files), non-interruptive mode
(item 16).

### 3.5 What not to do

1. Do not adopt OpenRig as a third fabric beside herdr and Orca now: its transport is tmux
   keystrokes, it writes hooks and trust settings into `~`, and ACP is the decided control plane.
2. Do not run agent-stack as-is: Linux only, CLIProxyAPI in the path, and its gate assumes
   Playwright-testable web apps.
3. An optional spike: after F1, one time-boxed OpenRig run on a Linux host (vps-primary or a
   Hyades CI runner), to see whether its queue and context packs beat `acp-dispatch` records and
   graft for a standing team. Not before.

## 4. Paseo plugins

The separate scan is [paseo-plugins-scan-2026-10-19.md](paseo-plugins-scan-2026-10-19.md): the
registry at 0.12.0 has 312 plugins, none installed here, and about twenty are relevant to the ADE
(quota resume, cross-daemon orchestration, usage ledgers, Forgejo issues, approval gates, GitHub
boards). Its questions are SF-Q14 to SF-Q16 below.

## 5. Questions for djbclark (for the `/steps` walk)

SF-Q1 to SF-Q9 are the Fable report's, restated in one line each; the recommended option is first.

1. **SF-Q1 Where in the phase plan?** (a) parallel Phase F after Phase 1's first PR; (b) fold
   into Phase 4; (c) start before Phase 0 ends.
2. **SF-Q2 First pilot repo?** (a) `djbclark-ade` itself; (b) a repo already on `ci/base`;
   (c) hyades-bench.
3. **SF-Q3 Spec-writer tier?** (a) Opus `judgment`; (b) cheap-first with `--escalate`.
4. **SF-Q4 Hard caps for v1?** (a) 12 calls, 4 h, 3 jobs/day, 1 parallel; (b) other numbers.
5. **SF-Q5 Workspace primitive?** (a) cow pasture on Macs, `git worktree` elsewhere, one adapter;
   (b) `git worktree` only; (c) pasture only.
6. **SF-Q6 Dashboard before Phase 4?** (a) none, `factory status` plus Telegram; (b) the static
   page anyway.
7. **SF-Q7 What `ready` means?** (a) a PR opened by the orchestrator with verdicts quoted, djbclark
   merges; (b) branch pushed, PR only after a Telegram yes.
8. **SF-Q8 Reviewer-code vendor rule?** (a) must differ from the builder's vendor; (b) any
   read-only-capable agent `plan` picks.
9. **SF-Q9 Intake in v1?** (a) `factory run <brief.md>` only; (b) also a `gh issue` label.
10. **SF-Q10 OpenRig?** (a) borrow the five ideas in §3.4 now and allow a time-boxed Linux spike
    after F1; (b) adopt OpenRig as the factory runtime; (c) ignore it.
11. **SF-Q11 agent-stack?** (a) mine the merge gate and the three Jev decision sites into
    `bin/jev` and the factory; (b) run agent-stack as-is on a Linux host; (c) ignore it.
12. **SF-Q12 Witness step?** (a) optional post-merge check for repos with a deployed app, Phase 5+;
    (b) in F2 for the pilot repo; (c) none.
13. **SF-Q13 ade-kit bundle manifest?** (a) adopt the pinned-commit + digest + "what it writes" +
    tested-ladder manifest in Phase 1; (b) later; (c) no.
14. **SF-Q14 Which Paseo plugins to trial now?** (a) the "trial now" tier of the scan (Usage Auto
    Resume, Continuity, Agent Monitor, Herald, Agents Dash List, TokenLedger, forges, Fresh
    Worktrees, twofado) behind `pluginsEnabled`; (b) none until the Phase 4 ADE plugin exists;
    (c) a different set.
15. **SF-Q15 Plugin trust rule?** Paseo plugins are unsandboxed code with the daemon user's
    access. (a) registry-reviewed plugins only, pinned by `paseo plugin add <owner>/<slug>`,
    `paseo plugin update` reviewed by hand, no `git:` or `npm:` sources on a trusted daemon;
    (b) also allow `git:` sources after an `adversary` read of the checkout; (c) anything.
16. **SF-Q16 Telegram surface?** (a) Hermes stays the only Telegram bot; the Paseo Telegram
    plugin is not installed; (b) trial the Paseo Telegram plugin on a separate bot token for
    Paseo-only chats; (c) replace Hermes's relay with it.

## 6. Codex read

Codex `gpt-6-astra` high, `--perm all`, third attempt, 9,300 words, copied to
[software-factory-reviews/codex-research-2026-10-19.md](software-factory-reviews/codex-research-2026-10-19.md).
The record was flagged "advisor edited the tree" because this digest and the Fable copy were
added to the checkout while it ran; `git status` shows no other change, and `acp-dispatch check`
now names the changed paths so the next such flag is readable at a glance.

### 6.1 Where it agrees with Fable

Optional workflow, not a platform; dispatch only through `acp-dispatch`; Paseo plus Hermes as
the surfaces, no static dashboard; human merge in v1; no bwrap on the Mac; reviewers limited to
the four read-only agents; hard-coded roles violate the routing policy; reviewer infra failures
never count as `CHANGES`; cow on Macs, Paseo worktrees as the portable default. Its placement is
`tools/factory` where Fable said `bin/factory`; a naming choice, take Fable's (`bin/` holds the
Python CLIs that import each other).

### 6.2 What it adds

1. **Reconciliation, not replay, is the hard part.** Crash recovery must inspect dispatch state
   and PIDs, honour §6.3's ownership transfer and attempt identity, and never retry an uncertain
   create or send blind. Job identity includes repository, host owner and attempt, never only an
   absolute path.
2. **Every resume counts against admission.** `acp-dispatch` auto-resumes quota stops and never
   refuses a resume by reservation, so the factory's caps must count resumes, canaries and
   wrap-ups, not only transitions.
3. **Model preflight is not fail-closed** (`acp-dispatch` dispatches with a warning when the
   probe fails); factory admission must refuse an unverified required model, permission or
   capability.
4. **Mac detachment is launchd-specific**; the Linux CI workflow stubs launchd. Portable
   unattended execution is unproven and must be gated, not assumed.
5. **The adversary-before-PR rule is not merge authority.** The two factory documents conflict
   (coding-factory.md wanted zero clicks; the design wants human merge); decide it once.
6. **Licences re-checked:** Superset is Elastic License 2.0, not permissive; Cloudroom's core is
   now Apache-2.0 and self-hostable (the "cloud only" objection is stale); Aperant and
   claude-squad stay AGPL, excluded from code and design-idea reuse.
7. **Closer comparators Fable missed:** watt-mind/factory (Apache-2.0, multiple ACP agents, path
   ownership per ticket, cold PR review, CI gates, GitHub only), Fabro (MIT, graph workflows,
   durable events and checkpoints, ACP backend with local, Docker or Daytona execution, human
   gates), addyosmani/factory (MIT, fresh independent verifier, human-owned charter, draft PRs,
   review-queue limit, human merges), StrongDM Attractor (Apache-2.0, a workflow specification
   with human-gate handlers, not an engine). Its evidence file `prior-art-repos.json` sits in the
   scratchpad.
8. **CI probe on `djbclark-ade` at 20:29 UTC:** public, two active workflow entries, no rulesets,
   master unprotected, `allow_auto_merge` false. An active workflow is not a default-branch gate.

### 6.3 Its questions, merged into §5

Codex's SF-Q1 (authority boundary) is Fable's SF-Q7; its SF-Q5 (pilot repo and change class) is
SF-Q2 with an added allowlist; its SF-Q3 (budget) is SF-Q4 in different units (prompt
submissions and agent-process minutes per job and per rolling day, plus a ceiling on ready PRs
awaiting review). Two are new:

17. **SF-Q17 Supervised or unattended v1?** (a) supervised pilot after Phase 2 on the Mac with
    scrubbed environments, unattended operation deferred to Phase 5 behind an isolation gate
    (Linux VM or container that passes credential, filesystem and network tests); (b) unattended
    from v1, only after that isolation gate passes first.
18. **SF-Q18 Does a generated spec need a human click before building?** (a) no, when it stays
    inside the submitted brief: the admitted spec is hashed, scope expansion refuses, and any
    unresolved product decision stops for you; (b) yes, every spec, through an
    `awaiting_spec_approval` state with stale-spec invalidation; silence never approves.
