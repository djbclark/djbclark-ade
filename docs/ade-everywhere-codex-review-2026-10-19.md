STATUS: complete

# ADE everywhere — advisory findings

## 1. Verdict

Approve the direction, but do not implement this proposal unchanged: its resume lock is unsafe, its exclusion list would discard canonical Hermes history, and its no-loss guarantee is unsupported. A public environment kit, an optional private companion, local searchable archives, and Paseo as the preferred front end are a coherent destination. Reach it through an early two-machine recovery experiment, reuse existing provisioning and search components, and retire the current fabric only after demonstrated workflow parity.

### Review basis

Reviewed on **2026-10-19**, against the proposal, measured inventory, prior-art report, AGENTS.md and README.md, in that order. References below use these exact files and their current line numbers; linked line numbers identify the start of the relevant passage, with ranges stated in text. Upstream documentation describes available capabilities, not proof that the installed binaries implement them correctly. In particular, the inventory's Paseo 0.11.4 and the upstream **0.12.0 changelog dated today** must not be conflated.

This is a source/documentation review, not a live migration qualification. No agent session was imported, no credentials were accessed, no services were changed, and no implementation tests were run. The working tree was not edited; pre-existing dirty skills and untracked artifacts were left alone. Paseo source was inspected at main revision `91154ba4e8ace3484595a05a4366279fb4818745`; other live-document observations are dated to this review, not an assertion of permanent API stability. Small raw upstream evidence copies are retained in this report directory's `evidence/` subdirectory.

**DECIDED:** The footer's exact report pathname controls over the earlier request for `findings.md`. This review recommends interfaces and experiments; it does not silently resolve operator choices about data loss, trust, retention or failover.

## 2. Findings

### F1 — blocker — A Syncthing lease file cannot prevent concurrent resume

**Proposal:** [§6.3, lines 300–323](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:300) makes files single-writer by placing them below a hostname, then uses `<id>.lease` containing host/time to prevent a second resume, with `--steal` to override.

**Reality:** Syncthing asynchronously reconciles files and preserves conflicting versions; it provides no atomic compare-and-set across disconnected devices. Both machines can observe no lease, create one, and resume. Waiting for “sync settled” before acquisition does not make acquisition atomic. A time-based expiry also needs clock, suspension and renewal rules, and stealing does not stop the previous process. These are deductions from the documented [synchronization/conflict model](https://docs.syncthing.net/users/syncing.html), not an undocumented Syncthing bug.

The host subtree isolates writes to archive *paths*, but after resuming on another host there are two histories for one logical session ID. The proposal never defines which history is current. A hostname also fails as a durable device identity after cloning or reinstalling a machine.

**Change:** Separate archive identity from runtime identity: provider, logical project/worktree, native session ID, stable device ID, generation and parent generation. Make offline continuation a **new branch/session identity**. Require acknowledged shutdown and transfer of the old runtime for exclusive continuation of the same identity; if automated exclusive failover is required, specify an authority/quorum and fencing that actually prevents the old writer from acting. A synced marker can be advisory, never the correctness boundary. Remove the claim that simultaneous resume is the only possible conflict.

### F2 — blocker — Hermes's database is canonical history, not disposable index

**Proposal:** [lines 78–81](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:78) generalize every SQLite file as derived; [§5, lines 257–258](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:257) exclude the 1.6 GB Hermes database as rebuildable, retaining only memory and config.

**Reality:** Hermes documents `state.db` as the canonical store of session messages and metadata, including gateway routing. Its old session JSONL files are no longer the live source. It has a first-party `hermes sessions export` JSONL backup format; dashboard import restores stored rows, while cross-agent import from Claude/Codex deliberately condenses history. These are distinct operations. [Hermes sessions](https://hermes-agent.nousresearch.com/docs/user-guide/sessions/).

**Change:** Classify **each store** as canonical, derived, cache or mixed. Preserve the Hermes database using a consistent backup plus versioned first-party exports until a restoration proves message, lineage and gateway-state coverage. A rendered Markdown export is not a database replacement. Use SQLite's [Online Backup API](https://www.sqlite.org/backup.html) or the application's supported transaction/export mechanism, not a live file copy. Apply the same classification to Cursor, OpenCode, Paseo metadata and any other database before excluding it. “Never synchronize a live SQLite file” is sensible; “discard every SQLite file” is not.

### F3 — major — T4 promises durability that the hot/cold topology does not supply

**Proposal:** [T4, lines 30–32](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:30), [lines 305–311 and 326–327](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:305) promise losing any device loses nothing, collect every few minutes, and allow old sessions to remain only on the encrypted peer.

**Reality:** A laptop can die before collection or replication. Offline work necessarily has a loss window. Moving old data to one peer makes that peer the only copy, contradicting the promise. Deleting hot files from an ordinary synchronized folder propagates deletion; it is not a tiering operation. Syncthing explicitly distinguishes synchronization from backup. [Syncthing FAQ](https://docs.syncthing.net/users/faq.html).

Receive-encrypted is still explicitly **beta/testing** in the current upstream documentation. Recovery needs the folder ID as well as the password; encrypted peers hide contents/names but expose some size and folder metadata. Renames can require retransmission. The mechanism is useful, but not a substitute for recovery design. [Untrusted-device encryption](https://docs.syncthing.net/users/untrusted.html).

**Change:** Define a measurable RPO and the event at which a capture is “durable,” expose unsynchronized bytes/age, and require two independent retained copies before deleting an origin copy. Keep a versioned encrypted backup outside ordinary delete propagation. Specify separate cold-store membership/retention, key recovery, device revocation and a restoration drill from ciphertext after losing the trusted devices. Treat encrypted Syncthing as a transport candidate subject to that drill, not the sole preservation mechanism.

### F4 — major — “Hardlink or copy grown files” is not a consistent archive protocol

**Proposal:** [lines 305–308](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:305) collect new/grown files and exporters periodically and on agent stop; existing ingesters become collectors.

**Reality:** A hardlink shares the native file's inode: later truncation or rewriting changes the purported archive. Growth-only detection misses rewrites, replaced files and sidecar changes. Copying an active transcript can capture a partial final record; separately copied transcript and subagent/tool sidecars need not describe the same point in time. Parsing a store for search is not evidence that an ingester preserves everything needed to resume it. SQLite documents why naive live copies can be inconsistent. [SQLite corruption guidance](https://www.sqlite.org/howtocorrupt.html).

Claude's `SessionEnd` is a useful collection trigger, but it has a bounded shutdown budget and cannot cover a killed process or machine loss. It is different from `Stop`, which occurs at turn completion. [Claude hook reference](https://code.claude.com/docs/en/hooks).

**Change:** Use `SessionEnd` to enqueue a small durable collection request; keep periodic and startup/wake reconciliation. Publish immutable capture generations with source versions, byte lengths, checksums, sidecar manifest and a completion marker written last. Preserve original bytes, record incomplete tails, and retry rather than pretending an in-progress capture is complete. Give every vendor adapter separate read/search/export/restore capabilities. No hardlinks as the durable archive, no “grown only” assumption, no network synchronization inside the shutdown hook.

### F5 — major — Use Claude's stable project key; do not promise arbitrary path surgery

**Proposal:** [lines 82–84](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:82) prefer the same login and `~/src`; [lines 316–320](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:316) rewrite embedded absolute paths on import. The prior-art report already records a better launch mechanism at [line 10](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-prior-art-2026-10-19.md:10), but the proposal omits it.

**Reality:** `/Users/alice/src` and `/home/alice/src` differ despite identical login and relative layout. Claude v2.1.234+ supports `CLAUDE_CODE_PROJECT_DIR_NAME` with `CLAUDE_CONFIG_DIR`, supplied in the launching shell, to give transcript and auto-memory directories a stable project key. It does not make tool paths, workspace contents or all session internals portable. Raw JSONL is an internal format. The documented duplicate-ID fallback rule is narrower than “a duplicate anywhere always breaks resume.” [Claude sessions](https://code.claude.com/docs/en/sessions).

**Change:** Make the supported environment variables the default for *new managed Claude launches*, with stable, collision-resistant keys per logical project/worktree and an explicit config-root policy. Test credential/plugin behavior before splitting config roots per project. Migrate existing sessions separately. Store logical project IDs and host-specific root mappings; prefer supported import/cwd controls over rewriting opaque content. Keep originals untouched, especially signed/reasoning payloads. Require a `/Users/...` → `/home/...` round trip in the first acceptance experiment, including subagents and file-history behavior.

### F6 — major — The secret plan overstates its authorization boundary and Linux readiness

**Proposal:** [§4.5, lines 221–234](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:221) says declarations specify which process may read each secret, uses sudo-secretspec at runtime, and assumes 1Password SSH Agent works as the general machine-identity solution.

**Reality:** The actual `frdminc/sudo-secretspec` fork's **`sudo-main`** guidance explicitly says authorized callers may export the declared environment, and client-family labels are correlation metadata, not authenticated principals. It does not provide per-secret confidentiality between agents running as the authorized operator. Its companion is documented for macOS; Linux parity was not established. Reading the upstream engine README on `main` would miss this distinction. [Fork security contract](https://github.com/frdminc/sudo-secretspec/blob/sudo-main/sudo-secretspec/AI-GUIDANCE.md), [companion README](https://github.com/frdminc/sudo-secretspec/blob/sudo-main/sudo-secretspec/README.md).

1Password's SSH Agent depends on the desktop application and authorization/unlock behavior. A headless service-account token is a different mechanism, with its own permissions and provisioning; it is not a desktop SSH agent. [SSH Agent requirements](https://developer.1password.com/docs/ssh/agent/), [service accounts](https://developer.1password.com/docs/service-accounts/).

**Change:** State the real same-user trust model. If per-agent isolation is required, use distinct OS/container identities and a policy-enforcing credential boundary. Define laptop, headless Linux and CI authentication separately, including unattended boot and key recovery. Keep sudo-secretspec referenced rather than vendored, but make its platform capability explicit. Define a backend interface so a new user can start with no private secrets, 1Password, or age/SOPS; do not make purchasing/configuring this operator's secret stack a hidden prerequisite.

### F7 — major — Service ownership is classified at the wrong granularity

**Proposal:** [§4.6, lines 240–246](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:240) makes fleet-watch, skillopt-night, s1-ingest, acp-dispatch-reap and Hermes fleet singletons controlled by an owner in Git.

**Reality:** The [existing README, line 67](/Users/djbclark/src/djbclark-ade/README.md:67) describes `acp-dispatch reap` as finalizing locally dead processes and resuming interrupted local slices. Every dispatch host needs that recovery function unless a remote supervisor is explicitly designed. Origin-side transcript collection likewise belongs on each origin; only downstream ingestion/integration may be singleton. A Git setting does not fence an old host that is offline with stale configuration.

Telegram ownership is per bot token/update stream, not simply “one Hermes in the fleet.” `getUpdates` offsets acknowledge updates, webhooks exclude polling, and pending updates have bounded retention. [Telegram Bot API](https://core.telegram.org/bots/api#getupdates).

**Change:** Give services scopes such as per-host, per-repository, per-account/bot, and fleet coordinator. Separate collection from integration. Specify disable-old/acknowledge/enable-new transfer, durable cursors, idempotency and what happens if the former owner cannot be contacted. Keep automatic failover disabled until fencing exists. Avoid enabling a copied Paseo schedule on every host merely because its definition synchronized. Per-host quota caches are reasonable, but they do not reserve shared subscription headroom: concurrent dispatchers can all act on the same stale balance. Carry account/pool identity and freshness into routing, coordinate polling/backoff, and state whether quota admission is best-effort or centrally reserved.

### F8 — major — Session continuity also needs workspace and control-plane state

**Proposal:** [T2–T3, lines 24–29](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:24), [§5, lines 259–267](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:259) clone projects, delete bigteam scratch, and exclude Orca state/workspaces because Orca is being replaced.

**Reality:** A transcript does not recreate an unpushed branch, dirty worktree, ignored input, report attachment or non-Git workspace. The inventory establishes size, not disposability. The current loop explicitly depends on file claims, pending questions, handoffs and completed reports ([README lines 32–59](/Users/djbclark/src/djbclark-ade/README.md:32)). Git has a separate [bundle mechanism](https://git-scm.com/docs/git-bundle) for transferring repository objects; even that does not include arbitrary untracked files.

**Change:** Define environment reproducibility, historical readability, conversation continuation and exact workspace recovery as separate acceptance levels. Before cleanup, identify unpushed/dirty work and unique reports, export lifecycle metadata, and preserve referenced artifacts according to policy. Do not synchronize live `.git`/worktree internals through the transcript folder. Add an explicit WIP-transfer workflow with consent about untracked/secret files. Excluding downloads and generated caches is sound; excluding unique work because its old front end is retiring is not. Keep the kb/SiYuan corpora outside the public kit, but include their client configuration, restore references and availability checks if those tools are part of the promised working environment. Likewise, reference external monitoring/phone infrastructure through a declared integration boundary rather than copying its implementation.

### F9 — major — Git does not make concurrent memory updates clean or semantically consistent

**Proposal:** [lines 247–249](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:247) say one fact per file means clean merges and pull/rebase before session start is enough; [lines 331–333](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:331) put several memory sources in the companion.

**Reality:** Two agents can edit the same fact, delete versus update it, or write contradictory facts in separate files with a technically clean merge. Startup synchronization does nothing about writes during a long session or while offline. Git explicitly stops rebases for conflicts rather than resolving meaning. [Git rebase](https://git-scm.com/docs/git-rebase). Basic Memory's files/index separation is appropriate, but it is not a distributed merge policy. [Basic Memory](https://github.com/basicmachines-co/basic-memory).

**Change:** Use local serialization around Git mutations and a dedicated integration worktree/outbox, not arbitrary rebase of a dirty operator checkout. Prefer immutable uniquely identified observations with provenance, then a reviewed consolidation step for canonical facts. Define commit/fetch/rebase/push retry, conflict surfacing, delete/tombstone semantics and offline backlog handling. Explicitly assign one authority to each Tier 1/Tier 2 handoff class; the proposal currently mixes companion Git and archive replication without a conflict rule.

### F10 — major — The provider survey is stale enough to change the implementation plan

**Proposal:** [§6.1, lines 280–286](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:280) treats OpenCode as the first-party export exception and says no vendor offers cross-machine sync.

**Reality:** There is no single vendor-neutral solution, but that blanket claim hides supported paths:

| Provider | Verified current capability | Consequence for ADE |
|---|---|---|
| Claude Code | Stable project-directory option; local resume; Agent SDK transcript mirrors with best-effort persistence. | Use launcher configuration and preserve CLI-native artifacts. An SDK mirror is not automatic replication for all independently launched CLIs. [SDK storage](https://code.claude.com/docs/en/agent-sdk/session-storage). |
| Codex | Official remote connections continue work on another host; newer Work Cloud continuation applies to eligible newly created tasks, not all historical CLI sessions. | Separate remote control/cloud continuity from offline local archive/import. No general first-party portable CLI backup/import guarantee was verified. [Official remote connections](https://developers.openai.com/codex/remote-connections/). |
| OpenCode | Export/import exists, but current v2 uses `opencode session export` / `session import`, including destination-directory control. | Version adapters. This repo's queue explicitly distinguishes current v2 from parked v1. [v2 CLI](https://dev.opencode.ai/v2/docs/cli/commands/), [queue lines 20–37](/Users/djbclark/src/djbclark-ade/docs/queue.md:20). |
| Gemini CLI | Session export/import shipped in **v0.43.0, 2026-05-22**; implementation adds `/export-session` and `--session-file`. | Prefer this supported portable-history route over project-hash rewriting; imported history is not live-process migration. [Changelog](https://geminicli.com/docs/changelogs/), [merged implementation](https://github.com/google-gemini/gemini-cli/pull/26514). |
| GitHub Copilot CLI | `--remote-export` sends history to GitHub.com/Mobile for viewing; remote-control/task-resume paths also exist. | Record account/feature availability and privacy settings. Readable exports and remote tasks are not an arbitrary native-store importer. [Command reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference). |
| Hermes | First-party structured export and imports exist; imported cross-agent conversation is deliberately transformed. | Use native backup/export where possible; qualify each restore mode. See F2. |
| Cursor | CLI local resume is documented. A supported portable native import/export or automatic full-history sync was **not verified**. | Keep a read-only exporter and preserve canonical source until a pinned-version recovery experiment succeeds. Do not present absence of documentation as proof no feature exists. [CLI parameters](https://cursor.com/docs/cli/reference/parameters). |

**Change:** Replace the yes/no survey with a versioned matrix of archive, readable export, lossless backup, native resume, fork/import, remote control and offline availability. Do not build an exporter where a maintained vendor command suffices. Keep the all-provider readable archive requirement even where native resume is unavailable.

### F11 — major — CASS already implements much of the proposed multi-host search subsystem

**Proposal:** [lines 312–315](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:312) extend `session-finder`'s index; the [prior-art report, line 71](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-prior-art-2026-10-19.md:71) says none of the listed search tools synchronize across machines.

**Reality:** CASS documents **Remote Sources / Multi-Machine Search**, SSH/rsync collection, `sources setup/sync/doctor`, source provenance and path mappings, plus archive/snapshot support. It covers multiple native agent formats. Its documented remote-ingestion exclusions also acknowledge that some stores contain credentials. [CASS repository and README](https://github.com/Dicklesworthstone/coding_agent_session_search).

**Change:** Evaluate CASS against this inventory before writing a new archive index and provider-adapter fleet. A sensible boundary is ADE device enrollment and preservation policy, CASS collection/search where adequate, and separate provider-native restoration. Check completeness, stable machine-readable APIs, performance on the actual corpus and Linux behavior. CASS is not proof of safe native resume or a distributed lock, and should not be sold as one. The existing live-session/claim logic may remain valuable even if historical search is delegated.

### F12 — major — Paseo's presence is not evidence of orchestration parity

**Proposal:** [§7.2, lines 359–373](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:359) substitutes worktrees/schedules for Orca's DAG, API prompts for slash commands, daemon idleness for sleepers, and a Paseo route for the ACP dispatch engine.

**Reality:** Worktree isolation does not supply dependency persistence, retries, file-claim arbitration, quota-reset continuation or crash recovery. A prompt containing a slash command is not guaranteed to invoke the CLI's native command semantics through every provider. Native Paseo orchestration MCP targets its daemon; cross-host targeting is available through the CLI. A CLI launch from outside Paseo is not automatically a child attached to an existing parent timeline. [Paseo orchestration](https://paseo.sh/docs/orchestration), [provider-plugin lifecycle contract](https://paseo.sh/docs/plugins/providers).

The current [dispatch contract in README line 67](/Users/djbclark/src/djbclark-ade/README.md:67) is materially richer than “start an agent.” The original terminal fabric also supports arbitrary shell processes and unrecognized TUIs. [Herdr automation](https://herdr.dev/docs/agent-automation/).

**Change:** Choose one owner of each launched process. Define a Paseo adapter for idempotent start, identity, input, question/permission response, cancel, terminal status, report completion and crash/quota resume. Test duplicate delivery and lost replies. Keep the existing engine behind that interface until a capability matrix passes for every required provider. Preserve a plain-terminal fallback. Remove unsupported sleeper/DAG retirement claims until their actual behaviors are replaced.

### F13 — major — Build the ADE-specific delta, not another quota and attention UI

**Proposal:** [lines 379–387](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:379) build Helm, quota, dispatch timeline and session-search panels largely from scratch.

**Reality:** Paseo already has account usage UI and a usage-source plugin API; today's 0.12.0 changelog adds `paseo usage`. [Paseo changelog](https://github.com/getpaseo/paseo/blob/main/CHANGELOG.md). Published plugins cover an all-host attention/workspace dashboard, waiting-event announcements, and archived conversation search. [Agents Dash List](https://paseo.sh/plugins/panrafal/agents-dash-list), [Herald](https://paseo.sh/plugins/gpambrozio/herald), [Agents History](https://paseo.sh/plugins/panrafal/agents-history).

These are not complete Helm replacements: Herald uses model-generated summaries and suppresses child announcements by default; Agents History searches supported file-backed providers on its daemon and is not a replicated offline cross-host archive. The SDK does expose client host enumeration and per-host clients. [Plugin reference](https://paseo.sh/docs/plugins/reference).

**Change:** Start with an `aiuse` usage-source adapter and a routing recommendation contribution, not duplicate quota cards. Reuse or extend an attention panel, preserving Helm's verbatim questions, ranking and one-question-at-a-time behavior. Build cross-host archived search against the chosen archive backend. Preserve host, permission-request and generation identities in every action so stale UI cannot answer a different request. The unique work is integration and correctness, not basic dashboard scaffolding.

### F14 — major — Plugin/profile/skill ownership needs a real compatibility and write policy

**Proposal:** [lines 369–373](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:369) duplicate routing policy in profiles while ADE owns skill links and Paseo keeps managed manifests; [risk table, lines 453–465](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:453) mainly proposes pinning the daemon.

**Reality:** Profiles are per-host and source inspection puts them in `daemon.agentProfiles` in the mutable Paseo config; the client saves profile updates as a settings patch. They can be represented in Git, but the whole live config is not a safe public declaration. [Profiles](https://paseo.sh/docs/agent-profiles), [config-store source](https://github.com/getpaseo/paseo/blob/main/packages/server/src/server/daemon-config-store.ts). Paseo refreshes its selected orchestration skills on startup. [Skill installation contract](https://paseo.sh/docs/skills).

Plugin entry contracts changed in 0.8 and installation shorthand changed in 0.11; version pinning must cover compatible clients and plugin artifacts too. [Plugin migration](https://paseo.sh/docs/plugins/migration). The 0.12 fixes for symlinked config writes and settings-schema rejection are direct evidence that this boundary moves. [Release history](https://github.com/getpaseo/paseo/blob/main/CHANGELOG.md).

**Change:** Generate profile declarations from the single routing policy required by [AGENTS.md lines 68–72](/Users/djbclark/src/djbclark-ade/AGENTS.md:68), with a declared policy for UI edits and drift. Merge only owned config fields; do not git-track or symlink the entire mutable home wholesale. Assign one updater per skill and preserve local customizations outside vendor-managed files. Record daemon/client/SDK/plugin/provider compatibility, pin revisions, stage upgrades, and retain rollback artifacts. Review provider plugins as trusted executable code, not configuration data.

### F15 — major — An ADE CLI is justified; a new general provisioner is not yet justified

**Proposal:** [§4.4, lines 183–217](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:183) implement bootstrap, packages, linking, merged settings, secrets, services and projects in a Python CLI, rejecting chezmoi as another configuration language.

**Reality:** The proposed system already introduces manifests, templates, profiles and merge rules. Chezmoi already handles machine prompts, file state/templates, externals and password-manager integration; Ansible already exists here for package/service work. [Chezmoi setup](https://www.chezmoi.io/user-guide/setup/), [external files](https://www.chezmoi.io/user-guide/include-files-from-elsewhere/), [Ansible template module](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/template_module.html). Language count is not an adequate reason to rebuild ownership, drift detection, permissions, removal and rollback.

**Change:** Keep Python/TOML for ADE-specific concepts—host identity, provider capability, route selection, project IDs and diagnostics—and expose one `ade` entry point. Prototype it as a thin orchestrator over existing Ansible plus chezmoi or narrowly scoped existing file machinery. Choose one file owner; do not stack two template managers over the same paths. Add schema versions, validation, inspectable plan/diff, non-destructive adoption, transactional backups, resumable failure and uninstall semantics before scaling. See the alternatives table for Nix, mise, devbox and Ansible-only tradeoffs.

### F16 — major — The public/private split needs an overlay and recovery contract, not just directories

**Proposal:** [lines 101–111 and 159–179](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:101) rename/restructure `site-private`, use an OPS_ROOT compatibility link, and offer a template plus GitHub private-repo creation.

**Reality:** Existing public/private dotfile projects explicitly define optional overlays and precedence; they work without the operator's private repository. [Optional private/corporate overlays](https://github.com/ithinkihaveacat/dotfiles/), [public fork/private companion pattern](https://github.com/romkatv/dotfiles-public). A directory proposal does not specify precedence, list merging, unknown keys, identities, credentials or a failed first-run recovery. A symlink cannot by itself prove that every ops-suite consumer tolerates a repository rename.

**Change:** Publish a versioned contract: public defaults, private overrides, role and machine overrides, with explicit precedence and keyed merges for hooks/plugins/profiles. Validate unknown fields and preserve unmanaged settings. Permit no companion and a generic existing Git remote as well as prompted private-repo creation; Forgejo must not be a second-class afterthought. A second user's defaults must contain no operator hostnames, account IDs, bot tokens, recipients or home paths. Defer cosmetic repo renaming until actual consumers are mapped. Keep the split into reusable skills/tools, manifests and private declarations; avoid duplicating service definitions in both `manifest/services.toml` and `services/units/` without one clearly authoritative schema.

### F17 — major — Linux parity and the bootstrap root of trust are scheduled too late

**Proposal:** [lines 183–208](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:183) promise git+shell bootstrap; [lines 250–253](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:250) treat Linux chiefly as package mappings and generated user units, with a container first.

**Reality:** The [inventory, line 229](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-inventory-2026-10-19.md:229) finds Node tooling supplied by `~/.hermes/node/bin`; that dependency must be removed from bootstrap assumptions. User services on Linux do not automatically survive logout or start at boot without the appropriate user-manager policy. [systemd lingering](https://www.freedesktop.org/software/systemd/man/latest/loginctl.html). A container does not exercise macOS login/keychain behavior, user-systemd lifecycle, desktop OAuth or suspend/resume. Paseo's Docker example persists `/home/paseo`, including provider homes, and uses a non-root container identity; it is not a full machine reconstruction image. [Official Docker documentation source](https://github.com/getpaseo/paseo/blob/main/public-docs/docker.md).

**Change:** Specify supported OS/architecture combinations and a pinned initial runtime acquisition path for uv/Python/Node, before invoking them. Separate desired versions from a resolved lock/provenance record for external tools, plugins and independent repositories. Generate service behavior, not merely unit syntax: PATH, working directory, login scope, credentials, retries, logs, missed schedules and timezone policy. Prove one real Linux user session and headless reboot/logout alongside the first Mac bootstrap. Keep container CI as a fast check, not the portability acceptance gate.

### F18 — major — Retention and privacy must include derived copies and device removal

**Proposal:** [lines 221–234](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:221) keep secrets out of Git and encrypt unowned peers; [lines 326–333](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:326) specify hot/cold retention and memory.

**Reality:** Every trusted workstation and its local search index may contain prompts, command outputs, credentials accidentally printed by tools and personal information. Hermes explicitly warns that backup exports include compacted/rewound history, and provides redaction for sharing; a display export and a full recovery backup have different purposes. See [Hermes export semantics](https://hermes-agent.nousresearch.com/docs/user-guide/sessions/). Additional search plugins create additional plaintext indexes. Removing a device from future synchronization does not erase its existing copies.

**Change:** Define full-fidelity private backup versus redacted shareable export, enrollment trust, local disk protection, index permissions, lost-device revocation, and deletion across replicas/backups/indexes. Keep sensitive memory and handoffs out of public Git, including historical commits and generated diagnostics. The age fallback needs recipient/key recovery and rotation rules; SOPS offers structured encrypted values and recipient management if that is the desired workflow. [age](https://github.com/FiloSottile/age), [SOPS](https://github.com/getsops/sops). Do not claim grep for this operator's username is sufficient to establish a generic, private-safe public kit.

### F19 — major — The phase plan performs cleanup before proving preservation and portability

**Proposal:** [§8, lines 401–420](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:401) starts with scratch cleanup, estimates a custom CLI at 1–2 weeks and session work at 1–2 weeks, and leaves second-machine/new-person acceptance near the end. Phase 1 already includes a second user account on this Mac, which is useful, but it does not exercise a different OS or an independently created private companion.

**Reality:** The highest-risk assumptions are the cross-host identity/ownership protocol, full-fidelity recovery, credential bootstrap and Linux service lifecycle. Finishing local plumbing first can entrench the wrong formats. Native session formats change, and the chosen front end has recent fixes where permission/question responses falsely reported success. [Paseo 0.12 release notes](https://github.com/getpaseo/paseo/blob/main/CHANGELOG.md). These are acceptance scenarios, not reasons to reject Paseo.

**Change:** Replace calendar-only phases with gates, in this order:

19.1 **Preserve and classify:** backup canonical stores, unique artifacts and current config; document source/version/ownership; do not delete scratch or old fabric yet.

19.2 **Thin vertical slice:** clone the public repo under another username on Mac and Linux; create an empty private companion; install one Claude and one Codex route; demonstrate authentication and dry-run/apply/reapply.

19.3 **Recovery protocol:** immutable capture, replication, index rebuild, source-host loss, different-home import, simultaneous/offline continuation policy, sidecars and cold recovery. Add Hermes before any database cleanup.

19.4 **Front-end pilot:** one real delegated workflow through Paseo, including waiting questions, permissions, crash/quota continuation, host disconnection, reports and rollback to current tools.

19.5 **Broaden:** remaining providers, services, memory writers, package/runtime locks and optional private integrations.

19.6 **Retire and generalize:** only after coverage is measured, remove redundant state/tools and have a second person follow the bootstrap without operator-private data.

Treat the proposed durations as provisional estimates. Adapter count and acceptance failures, rather than directory moves, determine effort. Require an explicit operator decision for any reduced continuity guarantee.

### F20 — minor — “No central node” and the cited evidence need narrower claims

**Proposal:** [lines 339–353](/Users/djbclark/src/djbclark-ade/docs/ade-everywhere-proposal.md:339) say every client attaches over SSH/relay/Tailscale and that tailnet plus relay-off satisfies no central node; the alternatives table calls LiteFS discontinued.

**Reality:** Paseo supports SSH for desktop/CLI; mobile needs a reachable direct/relay path. Self-hosted Hub is available, with embedded database or PostgreSQL, but supplies event-triggered coordination rather than archive replication. [Connectivity](https://paseo.sh/docs/connectivity), [Hub](https://paseo.sh/docs/hub). Tailscale's control plane, 1Password and vendor authentication are additional dependencies; perhaps acceptable, but not covered by “only GitHub, Forgejo and Hyades.” [Tailscale coordination](https://tailscale.com/kb/1155/terminology-and-concepts).

C10's cited Fly thread explicitly says LiteFS itself was **not** discontinued; reduced maintenance/Cloud-product changes are different facts. [Actual Fly discussion](https://community.fly.io/t/litefs-discontinued/23682). C4 cites a deleted-worktree resume bug as evidence for duplicate-ID lookup. These errors do not make LiteFS a good fit, but they undermine the stated decision trail.

**Change:** State whether the requirement excludes outside runtime/control-plane dependencies or merely a single indispensable user machine. Document direct mobile connectivity and permitted services, using Hyades-hosted alternatives where strict independence is intended. Correct the citations and qualify unsupported negatives; retain a decision log distinguishing measured installed behavior, published capability, inference and unverified recovery.

## 3. Missed alternatives and better comparisons

### 3.1 Archive, transport and database choices

The proposed **source artifacts plus disposable local indexes** remains the preferred general architecture, after correcting which sources are canonical. Syncthing is a reasonable transport for immutable captures; changing transport does not solve ownership or recovery semantics.

| ID | Alternative and primary source | Assessment for this operator |
|---|---|---|
| A1 | [CASS](https://github.com/Dicklesworthstone/coding_agent_session_search) | First evaluation target for historical collection/search; already supports remote sources. Keep live-process claims and native restoration separate. |
| A2 | [git-annex placement](https://git-annex.branchable.com/preferred_content/) and [copy policy](https://git-annex.branchable.com/git-annex-numcopies/) | Stronger than “cold storage only” as a policy layer: selective content placement and replica tracking can match full index/small laptop/large archive roles. Use immutable capture objects, not actively modified transcript files. |
| A3 | [Mutagen](https://mutagen.io/documentation/synchronization/) | Good controlled SSH development-pair synchronization with conflict policy; not inherently an N-way offline archive or distributed lock. Worth a two-host baseline, not a magical SQLite repair. |
| A4 | [rclone bisync](https://rclone.org/bisync/) | Genuine bidirectional synchronization, contradicting prior-art line 66's blanket “rclone one-way” dismissal. Pair state, resync/error handling and overlapping-run restrictions make an arbitrary multi-host mesh unattractive. One-way immutable-object upload with encrypted/versioned storage may be simpler. |
| A5 | [Perkeep](https://perkeep.org/doc/overview), [current project](https://perkeep.org/) | Content-addressed immutable objects and metadata fit archival history. A 2025-11 release exists, so “no relevant evidence” is not a current assessment. Consider archive design ideas or a small experiment; operational complexity makes it a weaker default than the existing toolchain. |
| A6 | [clync](https://github.com/Saturate/clync) | Not merely Git/LFS: also documents folder and S3 backends and encryption. A Claude-specific comparison implementation, not a universal protocol. Its merge policy must not silently choose between divergent agent executions. |
| A7 | [Dolt Git remotes](https://www.dolthub.com/blog/2026-02-13-announcing-git-remote-support-in-dolt/) | Verified feature since v1.81.10. Useful if ADE-owned coordination/memory data needs SQL branches and explicit merges; not a transparent replacement for vendor SQLite schemas or binary transcript preservation. |
| A8 | [Turso Sync](https://turso.tech/blog/sync-benchmark) | The current comparison should include newer logical-change push/pull sync, not only old embedded-replica WAL behavior. Still requires application integration and a chosen remote authority; little benefit for rebuilding a disposable search index. |
| A9 | [sqlite-sync](https://github.com/sqliteai/sqlite-sync) | A real offline CRDT extension with PostgreSQL/Supabase options, not demonstrated as a cr-sqlite project successor. Requires database/table integration; cannot be slipped into closed vendor stores safely. Review Elastic License 2.0/commercial terms and conflict semantics before adoption. Potential ADE-owned memory experiment only. |
| A10 | [Litestream](https://litestream.io/how-it-works/) / [LiteFS](https://fly.io/docs/litefs/) | Single-writer recovery/replication tools still have valid uses for a canonical host service. Neither solves concurrent offline writers in arbitrary native TUI stores. Reject on topology and ownership fit, not the erroneous discontinued claim. |
| A11 | [Claude SDK SessionStore](https://code.claude.com/docs/en/agent-sdk/session-storage) | Useful if ADE actually owns SDK launches and can supply the store; best-effort transcript mirror is not a universal collector for unrelated native sessions. Include subagent retrieval and mirror-failure handling. |
| A12 | [Taildrive](https://tailscale.com/docs/features/taildrive) | Alpha WebDAV access, useful for retrieving a remote file; not offline replication. Correct to avoid it as the archive foundation. |

### 3.2 Front-end choice

**Recommendation:** Paseo is the best **pilot** for the stated mobile/web, multi-provider and extensibility priorities. The evidence does not justify unconditional replacement of all Orca/herdr behaviors. None of these front ends, by itself, makes all old native sessions safely resumable on an offline replacement machine.

| ID | Candidate | What changes the comparison |
|---|---|---|
| A13 | [Paseo providers](https://paseo.sh/docs/providers), [provider plugins](https://paseo.sh/docs/plugins/providers) | Native adapters plus ACP catalog and extensible provider contract are a good match to the mixed fleet. Direct self-hosted access and optional Hub fit the desired topology. Provider coverage is not identical capability coverage; qualify every route. |
| A14 | [Orca](https://www.onorca.dev/docs/cli/reference), [remote/SSH workspaces](https://www.onorca.dev/docs/ssh) | Already has connected-host transcript search, remote ownership and service installation. It is the strongest baseline because the operator already uses it. Keep until Paseo preserves the actual task/claim/recovery loop. Connected-host search does not provide offline history replication. |
| A15 | [Herdr](https://herdr.dev/docs/agent-automation/) | Retain as the fallback for arbitrary TUIs and raw shell control; its agent lifecycle API is richer than “just panes.” A deliberately small residual terminal role is compatible with Paseo becoming the universal preferred UI. |
| A16 | [Superset remote access](https://docs.superset.sh/remote-access), [FAQ](https://docs.superset.sh/faq) | Now has remote hosts and iPhone/iPad access, so a desktop-only comparison is stale. Its documented relay/account/Pro model and experimental Linux desktop are less aligned with the strict independence requirement; CLI Linux support is distinct. |
| A17 | [OpenChamber](https://github.com/openchamber/openchamber) | Desktop/web/mobile and Linux are credible alternatives, but it is fundamentally OpenCode-based. Its [Claude provider bridge](https://github.com/openchamber/opencode-claude) changes harness/tool ownership rather than preserving every native TUI unchanged. Consider if standardizing on OpenCode is acceptable. |
| A18 | [Happy desktop](https://happy.engineering/desktop/), [original CLI status](https://happy.engineering/docs/) | Current Happy is broader than the old Happy Coder mobile wrapper. The original CLI is in maintenance mode; desktop/custom harness and self-hosted team features deserve comparison. Not automatically a better fit for preserving many existing native CLIs. |
| A19 | [Conductor Cloud Computer](https://www.conductor.build/docs/cloud/cloud-computer) | Has a managed reproducible cloud environment and multiplayer work; its current cloud setup supports GitHub repositories and vendor-hosted microVMs. Useful product reference, weaker match for Forgejo/Hyades and no extra central service. Linux cloud execution is not Linux desktop parity. |

### 3.3 Bootstrap and secrets choice

| ID | Candidate | Recommended role |
|---|---|---|
| A20 | [Chezmoi](https://www.chezmoi.io/user-guide/setup/) | Strong default to evaluate for files, prompts and private overlay materialization. Put ADE concepts in a thin Python front end; do not duplicate its file ownership machinery casually. |
| A21 | [Ansible](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/systemd_service_module.html) | Lowest incremental cost for packages/services given existing roles. Ansible-only is defensible if file merge/adoption requirements remain simple and explicitly implemented. |
| A22 | [Home Manager](https://nix-community.github.io/home-manager/), [nix-darwin](https://github.com/nix-darwin/nix-darwin) | Best candidate when pinned declarative user environments/rollback are worth the migration. Do not make a full Nix conversion a prerequisite for the session project. Mac applications need a package-by-package assessment; “all GUI apps require casks” is too broad. |
| A23 | [mise](https://mise.jdx.dev/dev-tools/) | Good owner for runtimes and tool versions; removes the accidental Hermes-owned Node dependency. Not a replacement for OS services, native app state or private-history management. |
| A24 | [devbox](https://www.jetify.com/docs/devbox) | Useful reproducible per-project shells; not a whole host/user-service bootstrap. Can coexist as a project-specific declaration. |
| A25 | [SOPS](https://github.com/getsops/sops), [sops-nix](https://github.com/Mic92/sops-nix), [agenix](https://github.com/ryantm/agenix) | Structured encrypted private declarations or Nix activation-time secrets are credible alternatives. Prior-art line 54 is misleading: encrypted store objects are not plaintext secrets; sops-nix decrypts at activation with configured ownership/permissions. It does not make plaintext safe at Nix evaluation time. |

## 4. Citation spot checks

These verdicts assess the **specific cited claim**, not endorsement of the whole design. “Partly” includes a true narrow statement used to justify a broader unsupported inference. Thirty citations checked; the remaining eight were not independently certified in this table.

| ID | Claim | Verdict | Note / checked source |
|---|---|---|---|
| C1 | Claude paths, config root, retention and resume lookup | holds | [Vendor sessions docs](https://code.claude.com/docs/en/sessions) support these, but also contain the stable project-name feature omitted from the proposal; lookup has current-project/worktree precedence. |
| C2 | SDK SessionStore is a best-effort transcript mirror | holds | [SDK docs](https://code.claude.com/docs/en/agent-sdk/session-storage); not a full environment backup or automatic native-CLI sync. |
| C4 | Issue 57920 proves duplicate-project-ID resume failure | wrong | [Issue 57920](https://github.com/anthropics/claude-code/issues/57920) concerns a deleted worktree/cwd resume failure. The conditional duplicate-ID rule belongs to C1's current documentation. |
| C5 | Plugin enablement/marketplaces are declarative; installed paths are local | holds | [Plugin loading](https://code.claude.com/docs/en/plugins/loading). Regenerate install state, and verify actual installation rather than only settings presence. |
| C6 | clync is Git/LFS session sync | partly | [Project](https://github.com/Saturate/clync) has that mode, plus folder/S3/encryption; comparison omits relevant capabilities. |
| C7 | OpenCode export/import is supported | partly | [CLI docs](https://opencode.ai/docs/cli/) support the old command family; [v2 reference](https://dev.opencode.ai/v2/docs/cli/commands/) changes the interface. Pin adapter version. |
| C9 | Litestream is single-writer backup/restore | holds | [How it works](https://litestream.io/how-it-works/); not multi-writer store reconciliation. |
| C10 | LiteFS discontinued | wrong | [Cited thread](https://community.fly.io/t/litefs-discontinued/23682) says the opposite about LiteFS itself. |
| C11 | cr-sqlite maintenance is thin | partly | [Issue 444](https://github.com/vlcn-io/cr-sqlite/issues/444) discusses maintainer focus elsewhere and a production fork; qualify upstream vs fork rather than declaring the technology dead. |
| C12 | Dolt Git remotes since February 2026 | holds | [Vendor release post](https://www.dolthub.com/blog/2026-02-13-announcing-git-remote-support-in-dolt/) names v1.81.10 and 2026-02-13. |
| C13 | Naively copying SQLite can corrupt it | holds | [SQLite documentation](https://www.sqlite.org/howtocorrupt.html); does not establish that the database is disposable. |
| C15 | Chezmoi setup/prompts/secrets | partly | [Setup guide](https://www.chezmoi.io/user-guide/setup/) supports first-run configuration; the broad secret-provider statement needs the relevant dedicated documentation, not one catch-all footnote. |
| C17 | Optional private overlays and precedence | holds | [Original repository](https://github.com/ithinkihaveacat/dotfiles/) explicitly describes optional private/corporate overlays. |
| C18 | Public fork plus separately created private repo | holds | [Original repository](https://github.com/romkatv/dotfiles-public) describes this manual pattern; it is not itself a generic prompted bootstrap. |
| C18b | sqlite-sync is a CRDT multi-writer successor | partly | [Project](https://github.com/sqliteai/sqlite-sync) supports the capability; successor lineage is not established. Terms/integration requirements are omitted. |
| C20 | Syncthing configuration/conflicts support the design | partly | [Configuration](https://docs.syncthing.net/users/config.html) supports folder configuration, not atomic distributed leases or the assertion that concurrent resume is the only conflict. |
| C20b | Receive-encrypted stores ciphertext on an untrusted peer | partly | [Docs](https://docs.syncthing.net/users/untrusted.html) support it, explicitly label beta/testing and specify recovery caveats omitted from the decision. |
| C21 | Mutagen two-way SSH synchronization | holds | [Project docs](https://mutagen.io/documentation/synchronization/); not evidence of safe N-way offline session ownership. |
| C22 | Taildrive alpha WebDAV, not sync | holds | [Vendor docs](https://tailscale.com/docs/features/taildrive) retain alpha status and remote-file-access semantics. |
| C23 | CASS local cross-agent search | partly | [README](https://github.com/Dicklesworthstone/coding_agent_session_search) supports local search and now remote collection; prior-art's “none sync” is wrong. |
| C24 | Orca search includes authorized connected hosts | holds | [CLI reference](https://www.onorca.dev/docs/cli/reference); not equivalent to a local replicated archive surviving all hosts offline. |
| C25 | Basic Memory Markdown plus SQLite index | holds | [Project](https://github.com/basicmachines-co/basic-memory); no automatic semantic conflict resolution follows. |
| C26 | Paseo SSH/relay/direct connections | partly | [Connectivity](https://paseo.sh/docs/connectivity); SSH client support differs from mobile/direct access. |
| C27 | Broad trusted plugin contributions | holds | [Plugin docs](https://paseo.sh/docs/plugins); supported extension surface is not a frozen ABI. |
| C28 | Orchestration across providers/hosts, schedules | partly | [Orchestration](https://paseo.sh/docs/orchestration); native MCP is host-local, cross-host CLI is separate. No demonstrated DAG-equivalence guarantee. |
| C29 | Hub self-hostable with embedded database | holds | [Hub](https://paseo.sh/docs/hub); event coordination, not transcript replication. |
| C30 | Official headless Docker image; state under .paseo | partly | [Docker source docs](https://github.com/getpaseo/paseo/blob/main/public-docs/docker.md); persistence example mounts `/home/paseo`, which also holds provider state/credentials. |
| C31 | Four orchestration skills installed per host | holds | [Skills docs](https://paseo.sh/docs/skills); selected skills also refresh at startup, important for ownership. |
| C35 | Copilot session files plus session-store DB | holds | [Config-dir reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference); omits consequential remote-export behavior in the broader survey. |
| C36 | Gemini project-hash session paths | holds | [Session management](https://geminicli.com/docs/cli/session-management/); true storage fact does not negate the released portable export/import route. |

Further prior-art corrections: line 54 conflates encrypted Nix-store material with decrypted secrets; line 66 overlooks rclone bisync; line 67 misses current Perkeep evidence; line 71 overlooks CASS remote sources. These should be repaired before this document is reused as an agent's implementation authority.

## 5. Questions only the operator can settle

5.1 **What does “every session reachable” require?** Readable history, native continuation, recovery of the exact working tree, or all three—and for which providers is anything less unacceptable?

5.2 **What loss window is acceptable?** Must a turn be remotely durable before it is acknowledged, or is losing the last few offline/minutes of work acceptable? Must every laptop hold all cold content or only an index with fetch-on-demand?

5.3 **What should happen during a partition?** Refuse continuation until ownership transfers, or allow a clearly labeled fork? Should a disconnected previous host ever be automatically fenced/terminated?

5.4 **Which external dependencies are permitted?** Does “only GitHub/Forgejo/Hyades” exclude Tailscale coordination, 1Password and vendor remote-session services, or only an indispensable personal machine? Are vendor cloud exports acceptable for private transcripts?

5.5 **Which devices/users may hold full plaintext history?** Is device removal prospective access revocation sufficient, or is there a deletion requirement spanning local indexes, backups and cold storage? What is the recovery-key custodian?

5.6 **What is the minimum newcomer experience?** Must it work without 1Password, GitHub, a Mac, Hyades access and any existing private repo, and which optional features should it then omit?

5.7 **Which current behaviors are non-negotiable retirement gates?** In particular: Orca DAG recovery, arbitrary terminal TUIs, file claims, verbatim Helm questions, quota-reset continuation, and existing keyboard/phone workflows.

5.8 **How should mutable memory be governed?** Preserve concurrent observations for later reconciliation, choose a designated curator, or accept an explicit automatic winner policy with possible semantic loss?

## 6. Checkpoint / completion record

Completed: prescribed document reads; primary-source review across session storage/sync, front ends, bootstrap/secrets, multi-machine services and alternatives; thirty citation spot checks; ordered recommendations and operator questions.

Complete: final editorial/source-consistency pass; all 36 local file references resolve and the table contains 30 citation checks. The working-tree status remains the pre-existing status observed at the start. No operational experiment is claimed. Unverified areas are stated in the findings: installed-provider restore fidelity, Cursor portable native import/export, Linux sudo-secretspec parity, full Paseo workflow parity, and a complete inventory of disposable scratch/workspace data.

Files touched: this report and its atomic temporary replacement; raw upstream documents under this report directory's `evidence/`. No working-tree file was changed. No commit, push, Git configuration change or shared-cache mutation was performed.

Retained evidence files (all under this report directory, source snapshots only):

6.1 `evidence/cass.txt` — retained.
6.2 `evidence/clync.txt` — retained.
6.3 `evidence/codex-remote.txt` — retained.
6.4 `evidence/gemini-changelog.txt` — retained.
6.5 `evidence/gemini-export-pr.txt` — retained.
6.6 `evidence/paseo-changelog.txt` — retained.
6.7 `evidence/paseo-config.txt` — retained.
6.8 `evidence/paseo-connectivity.txt` — retained.
6.9 `evidence/paseo-docker.txt` — retained.
6.10 `evidence/paseo-profile.txt` — retained.
6.11 `evidence/sudo-main-README.md` — retained.
6.12 `evidence/sudo-main-skills_sudo-secretspec_SKILL.md` — retained.
6.13 `evidence/sudo-readme.txt` — retained.
6.14 `evidence/sudo-secretspec.txt` — retained.
6.15 `evidence/sudo-secretspec_AI-GUIDANCE.md` — retained.
6.16 `evidence/sudo-secretspec_README.md` — retained.

The atomic temporary report was replaced and is not a remaining artifact. No inbox file was present at the final check. No parent-agent messaging endpoint named `main` is exposed in this Codex session; the complete deliverable is this file.

DONE
