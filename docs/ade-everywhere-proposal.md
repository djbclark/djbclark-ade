# ADE everywhere: one repo that recreates the whole agent environment on any machine

Proposal, version 1, 2026-10-19. Status: **draft for djbclark's decisions** (section 9).
Evidence: [ade-everywhere-inventory-2026-10-19.md](ade-everywhere-inventory-2026-10-19.md) (what
exists today, measured) and [ade-everywhere-prior-art-2026-10-19.md](ade-everywhere-prior-art-2026-10-19.md)
(web research, every claim with a URL). Citations in this document are numbered superscripts
resolved under "Citation footnotes".

## 1. Goal, restated as acceptance tests

The request: move the entire AI development environment into `djbclark-ade` (or have it
referenced from there), so that on a new machine, after cloning that one repo and telling an
agent "recreate my environment", djbclark can work on any project exactly as on any other
machine. Every past session of every TUI must be reachable from every machine. No central node
other than GitHub, Forgejo and the services on Hyades. Paseo becomes the universal front end.
Someone else must be able to use the public kit with their own private companion.

Written as tests the finished project must pass:

1. **T1 fresh machine.** On a clean Mac or Linux box with git and a shell: clone
   `djbclark-ade`, run one command (or paste one prompt into any agent), answer the interactive
   questions once (private repo URL, 1Password sign-in, vendor logins), and every tool, skill,
   hook, service, plugin and project checkout is present and `ade doctor` is green.
2. **T2 any project.** `ade clone <project>` (or `--all`) puts every listed project at
   `~/src/<name>` with the right remotes, and the project's own agent wiring (graft, hooks, Tier 1
   pointer) works unchanged.
3. **T3 any session.** `session-finder` on machine B finds a session that ran on machine A
   (live or ended), can show it, and for Claude Code and Codex can resume it on B, with a guard
   against resuming the same session on two machines at once.
4. **T4 no central node.** Each machine holds a full copy of the shared state; losing any one
   machine, or the Hyades peer, loses nothing. GitHub/Forgejo carry the repos; the Hyades peer is
   an always-on replica and introducer, not a source of truth.
5. **T5 Paseo parity.** Everything the herdr/Orca-based loop does (find, start, answer from one
   window, carry work across sessions, fan out) has a Paseo-native equivalent, and the operator
   can drive all of it from the Paseo desktop, web or phone client.
6. **T6 someone else.** A second person forks the public repo, runs the same bootstrap, is
   prompted to create their own private companion, and gets a working environment with none of
   djbclark's hosts, accounts or memory.
7. **T7 reproducibility is tested.** CI runs the bootstrap into a clean container on every push
   and fails when the manifest and reality drift.

## 2. What exists today, in one paragraph each

**The kit is real but hand-wired.** `djbclark-ade` holds the skills, orchestration CLIs, hooks,
commands and docs, and `skill-everywhere` links skills into eleven TUIs. But nothing creates the
rest of the wiring: the per-file symlinks in `~/.claude`, `~/.codex`, `~/.config/opencode`,
`~/.zcode` and `~/AGENTS.md` were made by hand, five of them are broken today (Gemini, opencode,
Qwen, zcode and Codex load no global rules), and the four config files that matter most
(`~/.claude/settings.json`, `~/.codex/config.toml`, opencode's and Hermes's config) are tracked
nowhere (inventory §1).

**Three ops repos overlap.** `site-djbclark` (public) carries Ansible roles for services, the
Brewfile fragments, about 100 site scripts, the home rules file and shell config; `site-private`
is now mostly symlinks back into it plus `memory/`; `djbclark-ade` holds the agent kit. The
same thing lives in two places in at least eleven cases (inventory §3): `book-to-kb` differs
between two copies, three `hooks.json` files all differ, `acp-run` is reached through a three-hop
symlink chain, and launchd plists come from four sources with 109 copies installed.

**Session history is about 10 GB in about 15 stores, none synced.** Claude Code is 1.7 G of
jsonl, Codex 135 M of jsonl, OpenCode 1 G of SQLite, Cursor 1.1 G, Gemini 2.2 G, Hermes 24 G of
mostly rebuildable caches. The only synced memory is `site-private/memory` and the Tier 2
handoffs, both git. The Tier 1 pointers in `~/.local/state/handoffs` (100 chains, 2.9 M), the most
valuable small item, are synced by nothing. `~/.local/state/bigteam` holds 106 G of scratch
(inventory §6).

**Paseo is already installed and in use.** Version 0.11.4, daemon on `127.0.0.1:7263`, hostname
on the tailnet, relay off, providers configured for omp, Cline, Grok, Cursor, GLM, Gemini,
Hermes and Qwen as ACP agents. It stores only small per-agent JSON under `~/.paseo/agents`; the
transcripts stay in each provider's own store. The four Paseo orchestration skills are installed
into `ade/skills` and carry uncommitted edits from Paseo's own refresh.

## 3. Principles

1. **One public kit, one private companion, nothing else required.** `djbclark-ade` is the
   environment. The private companion holds what must be private. Machine provisioning that is
   not about agents (phone fleet, DNS, monitoring stacks) stays in `site-djbclark`/`stayturgid`
   and is optional.
2. **Sync source files, rebuild indexes.** Transcripts and memory are files; every SQLite file is
   a derived index rebuilt per machine. File-syncing a live SQLite database is a documented way to
   corrupt it<sup>[1](#C13) [2](#C14)</sup>, and no SQLite replicator fits a fleet of sleeping
   laptops with no primary (section 6.2).
3. **Same paths everywhere.** `~/src/<name>` for every project, the same login name on every
   machine where possible. Claude Code keys transcripts by the absolute working directory and
   embeds absolute paths inside them<sup>[3](#C1) [4](#C3)</sup>; identical layouts avoid rewriting.
4. **Declare, then link.** A manifest says what exists; a linker makes the symlinks; a doctor
   compares. Hand-made links are the bug class that produced today's five broken rules files.
5. **Secrets never touch git.** 1Password is the store, `sudo-secretspec` the runtime boundary;
   the private companion holds declarations and item references only.
6. **Every peer is equal.** Replication is peer-to-peer over the tailnet; the Hyades peer is one
   more device, running with an encrypted-at-rest copy it cannot read.
7. **Paseo is the front end, not the engine.** Headless dispatch keeps its tested engine
   (`acp-run`/`acp-dispatch`); Paseo gets visibility and control of it through its CLI, SDK and a
   plugin, and replaces the terminal fabric (herdr, Orca).
8. **Flag before building.** Where this proposal would discard paid-for work (herdr plugins, Orca
   docs, the hub-era scripts), it asks first (section 9).

## 4. Target shape

### 4.1 Repos

| Repo | Visibility | Role after the project |
|---|---|---|
| `djbclark-ade` | public | The environment: manifest, bootstrap CLI, skills, orchestration tools, per-TUI config templates, service units, Paseo plugin, docs, tests. Nothing that names a host or account. |
| `ade-private` (today `site-private`) | private | The operator's companion: memory, handoffs (Tier 1 chains and Tier 2 documents), private skills, machine facts and per-machine overrides, project list, secret declarations and 1Password references, Paseo profiles if they hold private notes. A template for it ships in the public repo. |
| `site-djbclark` + `stayturgid` | public | Infrastructure that is not the agent environment: phone fleet, DNS, monitoring stack, VPS NixOS, Hyades services. `ade` may call `just deploy-mac` if present, never depends on it. |
| `aiuse`, `sudo-secretspec`, `herdr`, `hermes-agent`, `orca`, `sipb-agent-skills`, `loopback-port-shim`, `sipb-llms` | public, own repos | Referenced from the manifest with install method and version; not vendored. |

Renaming `site-private` is cosmetic but matters for T6: a newcomer should see `ade-private` as
"the thing the bootstrap asked me to create", not an ops-suite artefact. The stayturgid policy
that `site-private` is the memory backing store keeps working if the rename is a GitHub rename
plus one `OPS_ROOT` symlink (question Q1).

### 4.2 `djbclark-ade` directory structure (proposed)

Today's layout grew by accretion: `claude/`, `zcode/`, `opencode-plugins/`, `launchd/`,
`config/`, `plugins/`, `scripts/`, `bench/` are seven top-level answers to "where does per-TUI
and per-OS stuff go". Proposed:

```
djbclark-ade/
  AGENTS.md  CLAUDE.md -> AGENTS.md  README.md  LICENSE
  ade/                 # the bootstrap CLI (Python, uv): install, link, doctor, clone, sessions, services
  manifest/
    tools.toml         # every external tool: source repo, install method per OS, version policy, PATH entry
    agents.toml        # every TUI: config dir, skills dir, commands dir, rules file, session store, resume command
    packages.toml      # brew/apt/nix/npm/uv/cargo/pipx package lists, by OS and by role
    services.toml      # every long-running job: command, schedule, singleton-or-per-machine, OS
    private.toml       # the overlay contract: which paths the private companion may provide
  skills/              # unchanged; the canonical skills
  bin/                 # orchestration CLIs, unchanged
  tools/acp-run/       # unchanged
  agents/              # per-TUI material, one dir each
    claude/            # settings.json (template), hooks/, commands/, agents/, marketplace
    codex/             # config.toml template, hooks.json, rules/
    opencode/          # opencode.json template, plugins/, commands/
    gemini/  zcode/  cursor/  copilot/  hermes/  qwen/  grok/  cline/  omp/
    paseo/             # config.json template, provider catalog entries, profiles, plugin list
    rules/home-agents.md   # the one home rules file; every TUI's rules file links here
  services/
    units/             # one TOML per service; launchd plists and systemd units are generated
  paseo-plugin/        # the ADE Paseo plugin (section 7.3)
  private-template/    # what `ade init-private` creates in a new companion repo
  docs/                # design records; handoffs move to the private companion
  tests/               # pytest plus the container bootstrap test
  vendor/              # pointers only
```

Moves: `claude/` to `agents/claude/`; `zcode/commands` to `agents/zcode/commands`;
`opencode-plugins/` to `agents/opencode/plugins/`; `launchd/` and `config/` into
`services/units/` and `manifest/`; `scripts/github-ci-run` into `bin/`; `bench/` into `tests/`;
`plugins/herdr-sleeper` out to its own repo (it already is `djbclark/herdr-sleeper`);
`docs/handoffs/` to the private companion (they name accounts and hosts; inventory §2.1).
`site-djbclark/home-agents.md` moves to `agents/rules/home-agents.md` with the operator-specific
lines templated from the private companion (section 4.4).

### 4.3 `ade-private` directory structure (proposed)

```
ade-private/
  AGENTS.md  README.md
  operator.toml        # name, email, GitHub/Forgejo logins, tailnet name, default models, pronouns for docs
  machines/<host>.toml # per-machine: OS, role (workstation|server|phone-control), singleton services it owns, overrides
  projects.toml        # every project: remote URL, clone path (~/src/<name>), forge, CI note
  memory/              # unchanged: one fact per file; Basic Memory `main`
  handoffs/
    chains/            # Tier 1 SESSION_LOG.md chains (synced copy of ~/.local/state/handoffs)
    tier2/             # HANDOFF_*.md from ade/docs/handoffs and memory/handoffs
  skills/              # private skills (1password)
  secrets/
    secretspec.toml    # declarations only; values live in 1Password
    op-items.toml      # 1Password vault/item references per secret
  agents/              # private per-TUI overrides merged over the public templates (codex config.toml, Paseo profiles with notes)
  sessions/            # NOT transcripts: the archive catalogue (section 6.4) if we choose git for it
```

Leaves: `web/maynarddaycare` (a personal website, its own repo); `tailscale/` snapshots (into
`machines/`); `bin/`, `docs/`, `cursor`, `gradle`, `macos`, `prompts`, `shell`, `tests` symlink
shims (deleted once `ade link` owns every path); `.codex-runtime/` (moves to the session archive,
section 6).

### 4.4 Bootstrap: `ade` CLI plus one prompt

The bootstrap is a small Python CLI in the public repo, run by `uv`, so the only prerequisites
are git and a shell. It does what Ansible, the justfiles and hand-made symlinks do today, from the
manifest:

1. `ade install`: packages per OS from `packages.toml` (Homebrew on Mac, apt or Nix on Linux,
   npm/uv/cargo/pipx everywhere), external tools from `tools.toml` (clone or tap, pinned where
   the manifest says), agent CLIs from their vendors.
2. `ade init-private <url>`: clone the companion; if absent, offer `gh repo create --private`
   from `private-template/` and ask the operator questions once (the chezmoi `promptStringOnce`
   pattern<sup>[5](#C15)</sup>, done in our own tool so there is no second config language).
3. `ade link`: every symlink in `agents.toml`: rules files, commands, hooks, agents, skills
   (absorbs `skill-everywhere`, adds "link all"), Codex home, opencode plugins and commands,
   Paseo config; writes `settings.json` from template plus private overrides.
4. `ade secrets`: sign in to 1Password, declare every secret from `secretspec.toml` into
   `sudo-secretspec`, run each vendor's login that cannot be scripted and say so.
5. `ade services`: generate launchd plists or systemd user units from `services.toml` with this
   machine's paths, honouring `machines/<host>.toml` for singleton jobs (section 4.6).
6. `ade clone --all`: every project from `projects.toml` to `~/src/<name>`.
7. `ade sessions join`: attach this machine to the session archive (section 6).
8. `ade doctor`: diff manifest against reality; the CI test (T7) runs it in a container.

The prompt for an agent is then one paragraph: "clone djbclark-ade, read AGENTS.md, run `ade
bootstrap`, answer its questions, run `ade doctor` until green". `docs/apply-toolchain-prompt.md`
stays as the per-repo toolchain prompt; it is not a machine bootstrap (inventory §4).

**Why our own CLI and not chezmoi, Nix or more Ansible.** chezmoi is the lowest-friction dotfiles
manager and has the prompt-once and secret-manager hooks we want<sup>[5](#C15)</sup>, but it would be
a second config language next to Ansible for a pattern (symlink into a repo) that already
works here. Nix with nix-darwin and home-manager gives the strongest pin at the highest cost, and
still needs Homebrew for casks<sup>[6](#C16)</sup>; vps-primary keeps its flake. Ansible stays for
services that are genuinely system-level (section 4.1) and the `ade` CLI can call it. The
public/private split follows the companion-overlay pattern with precedence and "works without
the overlay"<sup>[7](#C17) [8](#C18)</sup>, with secrets pulled from the password manager at apply time
rather than age-encrypted in git<sup>[9](#C19)</sup>, because 1Password and sudo-secretspec are
already the chosen boundary.

### 4.5 Secrets and private data

1. **Values**: 1Password only. On a new machine `ade secrets` signs in once (service account or
   personal account) and seeds `sudo-secretspec`; nothing is written to the repo.
2. **Declarations**: `ade-private/secrets/secretspec.toml` says which secrets exist and which
   process may read them; `op-items.toml` maps each to a vault item.
3. **SSH keys**: the 1Password SSH agent, so keys are never copied between machines; the
   companion records which key signs which forge.
4. **Hosts and accounts**: `operator.toml` and `machines/*.toml`. The public kit refers to them
   only through template variables; `ade doctor` greps the public tree for the operator's
   login, tailnet and hostnames and fails on a hit.
5. **Transcripts** contain whatever agents printed, including the odd secret. They stay out of
   git; the archive is encrypted at rest on any peer the operator does not own (section 6.3).
6. **Fallback without 1Password**: an `age`-encrypted `secrets.env` in the companion, key held
   by the operator, as in the pattern several dotfiles repos use<sup>[9](#C19)</sup>. Offered by
   `ade init-private`, not default.

### 4.6 Many machines at once

Things the single-Mac design assumes that a fleet breaks:

1. **Singleton services.** fleet-watch, skillopt-night, s1-ingest, acp-dispatch-reap and the
   Hermes Telegram gateway must run on exactly one machine (two Telegram pollers on one bot token
   fight). `services.toml` marks them `singleton`; `machines/<host>.toml` names the owner; other
   machines install them disabled.
2. **Per-machine services.** load-watch, context-budget, the shared MCP servers, LiteLLM, the
   Paseo daemon run everywhere.
3. **Quota state.** `aiuse` and `cswap` read vendor APIs; their caches are per machine, fine.
4. **Memory writes from two machines.** `site-private/memory` is one fact per file, so git
   merges cleanly; `ade sync` pulls with rebase before any agent session starts (today's
   `ops-memory-sync`).
5. **Linux.** `launchd/` becomes generated units (launchd or systemd user); Homebrew entries get
   apt/Nix equivalents or "Mac only" flags; `cow` (APFS) is Mac-only and Paseo worktrees are the
   portable isolation; `heavy-shim`, `macos/` are Mac-only. The first Linux target is a
   container in CI (T7), the second vps-primary.

## 5. What should not be in the project

1. **Hermes's 24 G.** `~/.hermes` is installs, caches, a 1.6 G state database and a 944 M Gmail
   index, all rebuildable. Sync only `~/hermes-memory` and the config. Hermes is its own repo.
2. **`~/.local/state/bigteam` (106 G)** is scratch; a cleanup, not a sync target.
3. **Paseo voice models (984 M)**, plugin caches, `~/.claude/plugins/cache`, graft caches,
   `.venv` dirs: re-downloadable, excluded.
4. **Orca state** (2.2 G plus 14 G of workspace checkouts): Orca is being replaced (section 7).
5. **maynarddaycare**: a personal website in `site-private/web`; its own repo.
6. **The phone fleet, DNS, monitoring stacks** (stayturgid, watchdogd, caddy, grafana): machine
   ops, not the agent environment. Still reproducible, from their own repos.
7. **The `~/kb` book corpus**: personal documents; backed up, not part of the environment.
   `book-kb` (the tool) is.
8. **Claude plugin install records** (`installed_plugins.json`, `known_marketplaces.json`): they
   hold absolute install paths and are regenerated from `settings.json`'s `enabledPlugins` and
   `extraKnownMarketplaces`<sup>[10](#C5)</sup>; sync the settings keys, never the cache.
9. **Vendor OAuth tokens**: per machine by design; the bootstrap runs the logins and says which
   ones it could not.

## 6. Sessions everywhere

### 6.1 What the stores are

Two shapes exist. Claude Code and Codex write one append-only jsonl per session under a
path-derived directory<sup>[3](#C1) [11](#C8)</sup>; Gemini keys by a path hash<sup>[12](#C36)</sup>; Copilot
keeps session files plus an index database<sup>[13](#C35)</sup>. OpenCode, zcode, Cursor, Hermes and
Crush keep sessions in SQLite; OpenCode has a supported `export`/`import`<sup>[14](#C7)</sup>, the
others only third-party exporters. No vendor offers cross-machine sync; Anthropic's supported
routes are cloud sessions and the Agent SDK's `SessionStore` mirror, which is transcripts only and
best-effort<sup>[15](#C2)</sup>.

### 6.2 Options considered for the shared store

| Option | Fits a laptop fleet with no primary? | Verdict |
|---|---|---|
| Replicate the SQLite indexes (Litestream, LiteFS, cr-sqlite, Turso, rqlite) | No. Litestream is one-writer backup<sup>[16](#C9)</sup>; LiteFS is discontinued<sup>[17](#C10)</sup>; cr-sqlite is thinly maintained<sup>[18](#C11)</sup> and its successor sqlite-sync<sup>[19](#C18b)</sup> is new; Turso and rqlite need a server or quorum. | Rejected; indexes are rebuilt locally. |
| Dolt with a git remote | Yes for tables, since Dolt now pushes to plain git remotes<sup>[20](#C12)</sup>, but it is a new engine for data that is files. | Not now; revisit if we want a git-hosted catalogue. |
| git for transcripts (clync-style UUID merge plus LFS)<sup>[21](#C6)</sup> | Append-only jsonl merges, but 10 GB and growing bloats history and LFS costs on GitHub. | Rejected for transcripts; kept for memory and handoffs. |
| git-annex with Forgejo or Hyades as special remote | Good for a cold archive, by its own account not a folder mirror<sup>[22](#C34)</sup>. | Optional later for the cold tier. |
| Syncthing over the tailnet | Peer-to-peer, no central node, fine for unique-named append-only files as long as one writer per file<sup>[23](#C20)</sup>; supports untrusted "receive-encrypted" peers<sup>[24](#C20b)</sup>. | **Chosen** for the live tier. |
| Mutagen or rsync over Tailscale SSH | One-way or pairwise; good for a dev box to laptop mirror<sup>[25](#C21)</sup>, no fleet semantics. | Fallback for a machine that cannot run Syncthing. |
| Taildrive | Alpha WebDAV mount, not sync<sup>[26](#C22)</sup>. | Rejected. |

### 6.3 Design

1. **The archive.** `~/ade-sessions/` is a Syncthing folder shared by every machine. Layout:
   `<agent>/<host>/<project-slug>/<session-id>.jsonl` plus sidecars (subagent dirs,
   file-history, Codex `session_index.jsonl` rows), and `<agent>/<host>/exports/` for the
   SQLite-backed TUIs (OpenCode `export`, Cursor and zcode exporters, Hermes session JSON). The
   `<host>` level is what makes every file single-writer, which is the Syncthing safety condition.
2. **The collector.** `ade sessions collect` (a per-machine service, every few minutes and on
   agent stop) hardlinks or copies new and grown native files into this host's subtree and runs
   the exporters. It never writes into another host's subtree. The existing `s1_*` ingesters and
   `session-finder`'s adapters already know every store's format; they become this collector.
3. **The peers.** Every workstation plus one always-on peer on Hyades (or vps-primary, Q2) in
   Syncthing's receive-encrypted mode, so the peer stores ciphertext only and acts as introducer.
   Losing any device, including that peer, loses nothing (T4).
4. **The index.** `session-finder`'s FTS5 database (`history.v2.sqlite`) is rebuilt on each
   machine from the archive; its `files` table gains `host`. `/session-finder-all` then answers
   for every machine. This is what Orca's cross-host `orca search` does<sup>[27](#C24)</sup> and what
   the independent cross-agent search tools do locally<sup>[28](#C23)</sup>.
5. **Resume on another machine.** `ade sessions pull <id>` copies a Claude or Codex session into
   this machine's native store at the path the local checkout implies, rewriting the project slug
   and embedded absolute paths when the home directory differs<sup>[4](#C3)</sup>, touching mtimes so
   the 30-day cleanup does not eat the copy<sup>[3](#C1)</sup>, and refusing if another project dir
   already holds that id (the `--resume` ambiguity rule<sup>[29](#C4)</sup>).
6. **The lease.** Pulling writes `<id>.lease` (host, time) next to the archive file; a second
   machine sees it and refuses unless `--steal`. Resuming one session on two machines is the one
   way to create a conflict<sup>[23](#C20)</sup>.
7. **Tier 1 pointers.** `~/.local/state/handoffs` joins the archive the same way (per host) and
   `session-handoff` reads all hosts; chain keys are already unique.
8. **Retention.** Hot tier on every machine for a year; `ade sessions archive` moves older
   sessions to a cold tier (git-annex on Hyades, or just the Syncthing peer) on request.

### 6.4 Memory

Basic Memory stays: markdown in git plus a per-machine index<sup>[30](#C25)</sup>. The seven empty
`~/agent-memory/*` projects are removed or pointed into the companion. `hermes-memory` moves into
the companion. The SiYuan and `~/kb` stores are out of scope (section 5).

## 7. Paseo as the universal front end

### 7.1 What Paseo is, in our terms

An Apache-2.0 daemon per machine plus desktop, web, mobile and CLI clients; clients attach to any
daemon over SSH, the optional encrypted relay, or directly over Tailscale<sup>[31](#C26) [32](#C33)</sup>.
Agents run where the daemon runs, with that machine's tools and credentials; the daemon
persists workspaces, agent metadata and schedules, and leaves transcripts in each provider's
store (inventory §6). Agents inside Paseo get MCP tools to create workspaces, launch and message
other agents across providers and hosts, and set schedules and heartbeats<sup>[33](#C28)</sup>.
Plugins are trusted TypeScript installed per daemon and can add screens, panels, Command
Center items, slash commands, composer pills, timeline rows, themes, attachment sources,
daemon RPCs and whole providers<sup>[34](#C27)</sup>. The CLI drives any daemon with
`--host`<sup>[35](#C32)</sup>; Hub is an optional, self-hostable layer for event-triggered
agents<sup>[36](#C29)</sup>; an official Docker image runs the daemon headless<sup>[37](#C30)</sup>.

So the "no central node" test holds: one daemon per machine, clients add each host over the
tailnet, relay off, Hub not needed. Paseo does **not** sync sessions between daemons (prior art
§8.3); section 6 covers that.

### 7.2 Capability map: today's loop against Paseo

| Today (herdr/Orca) | Paseo equivalent | Decision |
|---|---|---|
| herdr workspaces, tabs, panes as the place every session lives | Workspaces with agents, terminals, files, diffs, browser in split panes | Replace. herdr stays only as a plain terminal multiplexer if wanted. |
| Orca worktrees, task DAG, `orca search` | Paseo worktree isolation, orchestration tools, schedules; no cross-host search | Replace Orca; section 6 supplies the search. |
| `session-finder fleet.py` (which live session is where) | `paseo ls -a --host <h>` per host; agent titles and labels | Keep `fleet.py` as the cross-host aggregator over Paseo's CLI/SDK; drop its herdr and Orca adapters. |
| `launch.py` starts a session over ACP in a visible pane | `create_agent` / `paseo run` with any provider, including the ACP catalog | Replace; `launch.py` becomes a thin wrapper that calls Paseo so labels and claims carry over. |
| `helm` answers every waiting session from one window | Paseo surfaces permission requests and finished agents per host; mobile approvals | Build the **Helm panel** as the ADE Paseo plugin: a screen listing agents waiting across hosts, ranked by work unlocked, relaying one prompt at a time (section 7.3). |
| `herdr-tidy` closes idle panes with a close ledger | `archive_workspace`; agents keep their transcripts | Replace with a plugin RPC or CLI loop that writes the same ledger. |
| `herdr-sleeper`, `herdr-jump`, `herdr-ai` | Not needed (daemon manages idle agents), Command Center, chat | Retire. |
| `self-slash` types a slash command into a pane | Prompt the agent through the API | Replace. |
| `autorename`, `herdr_place.py` | `rename_workspace`, agent title | Replace; keep the title derivation. |
| `fleet-watch` pings Hermes on fleet changes | `notifyOnFinish`, push notifications to the phone app | Keep the Hermes ping for Telegram; feed it from Paseo events. |
| `acp-run` / `acp-dispatch` / `bigteam` / `route_agent.py` headless dispatch | `paseo run --provider X --no-wait`, SDK, agent profiles with "when to use" notes | Keep the engine; add a `--via paseo` route so dispatched slices appear as subagents in Paseo; encode the routing policy in Paseo profiles too. |
| `cow-pasture` APFS workspaces | Worktree isolation | Keep cow for non-git and Mac-only speed; Paseo worktrees are the portable default. |
| launchd jobs that run agents (skillopt-night) | Schedules and heartbeats | Move agent-shaped jobs to Paseo schedules; system jobs stay units. |
| Hermes Telegram gateway | Paseo mobile app for approvals and chat | Keep both; Hermes is the always-on assistant, Paseo the workbench. |
| Skills linked into every TUI | Paseo installs its four skills on each host<sup>[38](#C31)</sup> | Unchanged; `ade link` owns the links, Paseo's managed-file manifest stays. |

### 7.3 The ADE Paseo plugin

One plugin in `paseo-plugin/`, installed on every daemon by `ade link`:

1. **Helm panel**: a screen plus sidebar item listing waiting agents across all hosts the
   client knows, with the pending question verbatim and one-tap relay; the ranking logic from
   `helm.py`.
2. **Quota pill**: a composer pill showing `aiuse` headroom for the current provider and the
   routing recommendation from `route_agent.py`.
3. **Dispatch timeline rows**: `acp-dispatch` slices appear in the parent agent's timeline with
   report and `BLOCKED:` state.
4. **Session search panel**: a workspace panel over the rebuilt cross-host index (section 6.3.4),
   with "pull and resume here".
5. **Tidy and handoff commands**: Command Center items that run `/handoff` then archive, writing
   the close ledger.

### 7.4 What stays outside Paseo

Dispatch to agents that Paseo cannot host, the quota probes, the load watcher, the nightly
skill-edit cycle's non-agent parts, and `sudo-secretspec`. Paseo is a client of all of these.

## 8. Phases

Each phase ends green on `ade doctor` and is a separate PR set. Nothing already running is
stopped until its replacement passes the same test.

1. **Phase 0, hygiene (days).** Fix the five broken rules links; track the four untracked
   config files as templates; delete the 106 G scratch; resolve the eleven duplicates (inventory
   §3); sweep `docs/handoffs` and `queue.md` for private names before they move.
2. **Phase 1, manifest and `ade` CLI (1 to 2 weeks).** `manifest/*.toml` written from the
   inventory; `ade link`, `ade doctor`, `ade services` reproduce this Mac exactly; the CI container
   test (T7) runs `ade install` on Linux. Test on a second user account on this Mac before any
   other machine.
3. **Phase 2, private companion (days).** `private-template/`, `ade init-private`, rename
   `site-private`, move handoffs and `hermes-memory`, write `operator.toml`, `machines/`,
   `projects.toml`, `secrets/`; `ade doctor` fails on operator names in the public tree.
4. **Phase 3, sessions (1 to 2 weeks).** Archive layout, collector from the `s1_*` and
   session-finder adapters, Syncthing folder with the Hyades peer in receive-encrypted mode,
   `session-finder` over all hosts, `ade sessions pull` with lease, Tier 1 chains in the archive.
5. **Phase 4, Paseo parity (2 to 3 weeks).** Paseo config and profiles in `agents/paseo/`; the
   plugin (Helm panel first); `launch.py` and `fleet.py` over Paseo; `acp-dispatch --via paseo`;
   then retire Orca, then herdr's agent plugins, once the capability map is all green.
6. **Phase 5, second machine (1 week).** Bootstrap a Linux box (vps-primary or a fresh VM) and a
   second Mac from nothing with the one prompt; fix what breaks; T1 to T5 pass.
7. **Phase 6, someone else (days).** A fresh GitHub account forks the repo and runs the
   bootstrap (T6); README and the one-paragraph prompt written for them.

## 9. Decisions needed from djbclark

1. **Q1 Rename `site-private` to `ade-private`?** Recommended: yes, GitHub rename plus
   `~/ops/site-private` symlink kept for stayturgid's memory policy.
2. **Q2 Always-on Syncthing peer: Hyades or vps-primary?** Recommended: vps-primary if it stays
   (NixOS, already on the tailnet, a flake we control); Hyades if vps-primary is going away.
   Either runs receive-encrypted.
3. **Q3 Move the agent-service Ansible roles (`shared_mcp`, `basic_memory_mcp`, `litellm`,
   `paseo_desktop`, the agent half of `site_agents`) from `site-djbclark` into
   `djbclark-ade/services`?** Recommended: yes; they are the agent environment.
4. **Q4 Provisioner: our own `ade` CLI calling Ansible for system roles, no chezmoi, no Nix
   for Macs.** Recommended as written in 4.4; say if you want the Nix route instead.
5. **Q5 Retire Orca and herdr's agent plugins once parity is green?** This discards
   `herdr-sleeper`, `herdr-jump`, `herdr-ai`, `reorg-orca`, `orca-reorg-watch` and the Orca docs.
   Recommended: yes for Orca; herdr as a plain multiplexer may stay.
6. **Q6 Scope of cross-machine resume: Claude Code and Codex only, everything else
   search-only?** Recommended: yes.
7. **Q7 Retention and at-rest policy for the archive**: hot tier a year on every machine, cold on
   the peer; are transcripts allowed on a Hyades volume in encrypted form?
8. **Q8 Which machines are the fleet?** Macs, vps-primary, Hyades containers, Android phones? The
   bootstrap targets Mac and Linux; Termux is out unless you say otherwise.
9. **Q9 Dispatch engine**: keep `acp-run` as the engine with a Paseo route (recommended), or
   move `acp-dispatch` onto the Paseo SDK and retire `acp-run`.
10. **Q10 Public-kit genericity**: how far to go for T6? Recommended: the operator's login, hosts
    and accounts out of the public tree, nothing more (no multi-tenant abstractions).
11. **Q11 Shell and dotfiles**: `site-djbclark/shell` and `gradle/` are "my environment" but not
    the agent environment. Recommended: `ade` ships the shell fragments agents need (PATH, rtk,
    `bg`), the rest stays in site-djbclark.

## 10. Risks

1. **Transcript path coupling.** Claude Code's slug and embedded paths make Linux resume of a Mac
   session a rewrite with known traps<sup>[4](#C3)</sup>; identical layouts remove most of it,
   and the lease removes the rest. Mitigation: same login name and `~/src` on every machine.
2. **Paseo moves fast.** 0.11.x; plugin contracts can change (the skill tells agents to re-read
   `llms.txt`). Mitigation: pin the daemon version in `tools.toml`, keep the plugin small.
3. **Syncthing on a 10 GB folder of many small files** is fine, but an initial scan on a slow
   box takes a while; Hermes and Orca stay out (section 5).
4. **Two machines editing memory** produce occasional git conflicts; one fact per file keeps
   them rare and trivial.
5. **The ops-suite policy** (stayturgid, three AGENTS.md slices) assumes `site-private`; the
   rename must keep that contract or update all three files in one commit.
6. **Discarding paid-for work** (herdr plugins, Orca integration) is a loss if Paseo turns out
   worse at something; the phase order retires nothing until the capability map is green.

## Citation footnotes

1. <a id="C13"></a>C13 — copying or syncing a live SQLite file is a listed corruption path — How To Corrupt An SQLite Database File (reference; sqlite.org). <https://www.sqlite.org/howtocorrupt.html>
2. <a id="C14"></a>C14 — Syncthing users report constant conflicts on SQLite files — Syncthing forum thread (forum; syncthing.net). <https://forum.syncthing.net/t/sync-conflict-with-1-specific-sqlite-file-constantly/20836>
3. <a id="C1"></a>C1 — transcript path derivation, `CLAUDE_CONFIG_DIR`, `cleanupPeriodDays`, `--resume` lookup rules — Claude Code sessions (vendor docs; code.claude.com). <https://code.claude.com/docs/en/sessions>
4. <a id="C3"></a>C3 — moving a session to another computer needs the jsonl, side folder and path rewrites — Move a Claude Code session to another computer (guide; codonic.dev). <https://codonic.dev/guides/move-claude-code-session-to-another-computer>
5. <a id="C15"></a>C15 — `chezmoi init --apply`, `promptStringOnce`, password-manager and age secrets — chezmoi setup user guide (project docs; chezmoi.io). <https://www.chezmoi.io/user-guide/setup/>
6. <a id="C16"></a>C16 — nix-darwin plus home-manager pins the stack; casks still via Homebrew — Nixifying my dotfiles (blog, 2026-02; mattmichie.com). <https://mattmichie.com/2026/02/14/nixifying-my-dotfiles/>
7. <a id="C17"></a>C17 — public installer with optional private overlay clones and precedence — ithinkihaveacat/dotfiles (repo; GitHub). <https://github.com/ithinkihaveacat/dotfiles/>
8. <a id="C18"></a>C18 — fork the public repo, create an empty private one the scripts pull — romkatv/dotfiles-public (repo; GitHub). <https://github.com/romkatv/dotfiles-public>
9. <a id="C19"></a>C19 — Ansible bootstrap, age key from 1Password, encrypted private submodule — shanemcd/dotfiles (repo; GitHub). <https://github.com/shanemcd/dotfiles>
10. <a id="C5"></a>C5 — `enabledPlugins` and `extraKnownMarketplaces` are the declarative state; install records hold absolute paths — Claude Code plugin loading (vendor docs; code.claude.com). <https://code.claude.com/docs/en/plugins/loading>
11. <a id="C8"></a>C8 — Codex rollouts under `~/.codex/sessions/YYYY/MM/DD` plus `session_index.jsonl` — Codex CLI sessions (guide; spawnd.dev). <https://spawnd.dev/codex-cli-sessions>
12. <a id="C36"></a>C36 — Gemini CLI keys sessions by a project path hash — Gemini CLI session management (vendor docs; geminicli.com). <https://geminicli.com/docs/cli/session-management/>
13. <a id="C35"></a>C35 — Copilot CLI keeps session-state files and a session-store database — Copilot CLI config dir reference (vendor docs; docs.github.com). <https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference>
14. <a id="C7"></a>C7 — OpenCode `export` and `import` — OpenCode CLI reference (vendor docs; opencode.ai). <https://opencode.ai/docs/cli/>
15. <a id="C2"></a>C2 — `SessionStore` mirror: transcripts only, best-effort, S3/Redis/Postgres adapters — Agent SDK session storage (vendor docs; code.claude.com). <https://code.claude.com/docs/en/agent-sdk/session-storage>
16. <a id="C9"></a>C9 — Litestream streams one writer's WAL to object storage; replica is a restore target — How Litestream works (project docs; litestream.io). <https://litestream.io/how-it-works/>
17. <a id="C10"></a>C10 — LiteFS discontinued — Fly.io community announcement (forum; fly.io). <https://community.fly.io/t/litefs-discontinued/23682>
18. <a id="C11"></a>C11 — cr-sqlite maintenance thin — vlcn-io/cr-sqlite issue 444 (repo issue; GitHub). <https://github.com/vlcn-io/cr-sqlite/issues/444>
19. <a id="C18b"></a>C18b — sqlite-sync, CRDT multi-writer successor in the same style — sqliteai/sqlite-sync (repo; GitHub). <https://github.com/sqliteai/sqlite-sync>
20. <a id="C12"></a>C12 — Dolt pushes to plain git remotes since 2026-02 — Announcing git remote support in Dolt (blog; dolthub.com). <https://www.dolthub.com/blog/2026-02-13-announcing-git-remote-support-in-dolt/>
21. <a id="C6"></a>C6 — git-based Claude session sync with UUID-tree merge and LFS — Saturate/clync (repo; GitHub). <https://github.com/Saturate/clync>
22. <a id="C34"></a>C34 — git-annex is not a folder-mirroring system like Syncthing — git-annex "not" page (project docs; branchable.com). <https://git-annex.branchable.com/not/>
23. <a id="C20"></a>C20 — folder configuration and conflict behaviour — Syncthing configuration (project docs; syncthing.net). <https://docs.syncthing.net/users/config.html>
24. <a id="C20b"></a>C20b — untrusted devices store receive-encrypted folders — Syncthing untrusted device encryption (project docs; syncthing.net). <https://docs.syncthing.net/users/untrusted.html>
25. <a id="C21"></a>C21 — two-way low-latency sync over SSH with conflict policies — Mutagen synchronization (project docs; mutagen.io). <https://mutagen.io/documentation/synchronization>
26. <a id="C22"></a>C22 — Taildrive is an alpha WebDAV share, a mount not a sync — Taildrive (vendor docs; tailscale.com). <https://tailscale.com/docs/features/taildrive>
27. <a id="C24"></a>C24 — `orca search` indexes transcripts across connected computers and paired servers — Orca CLI reference (vendor docs; onorca.dev). <https://www.onorca.dev/docs/cli/reference>
28. <a id="C23"></a>C23 — cross-agent local session search over Claude, Codex, Gemini, OpenCode stores — coding_agent_session_search (repo; GitHub). <https://github.com/Dicklesworthstone/coding_agent_session_search>
29. <a id="C4"></a>C4 — `--resume <id>` fails when more than one project dir holds the id — anthropics/claude-code issue 57920 (repo issue; GitHub). <https://github.com/anthropics/claude-code/issues/57920>
30. <a id="C25"></a>C25 — markdown files plus SQLite index, MCP interface — basicmachines-co/basic-memory (repo; GitHub). <https://github.com/basicmachines-co/basic-memory>
31. <a id="C26"></a>C26 — clients connect over SSH, the encrypted relay, or Tailscale — Paseo connectivity (vendor docs; paseo.sh). <https://paseo.sh/docs/connectivity>
32. <a id="C33"></a>C33 — what Paseo is: daemon, clients, providers, plugins, Apache-2.0 — Paseo llms.txt (vendor docs; paseo.sh). <https://paseo.sh/llms.txt>
33. <a id="C28"></a>C28 — agents launch, message and coordinate other agents across providers and machines; schedules and heartbeats — Paseo orchestration (vendor docs; paseo.sh). <https://paseo.sh/docs/orchestration>
34. <a id="C27"></a>C27 — plugin contributions: screens, panels, Command Center, slash commands, pills, timeline, themes, attachment sources, RPCs, providers; trusted unsandboxed code — Paseo plugin quickstart (vendor docs; paseo.sh). <https://paseo.sh/docs/plugins>
35. <a id="C32"></a>C32 — `--host` targets any daemon (host:port, socket, ssh://, offer URL); plugin and project commands — Paseo CLI reference (vendor docs; paseo.sh). <https://paseo.sh/docs/cli>
36. <a id="C29"></a>C29 — Hub is the optional layer above daemons; self-hostable with an embedded database — Paseo Hub (vendor docs; paseo.sh). <https://paseo.sh/docs/hub>
37. <a id="C30"></a>C30 — official Docker image runs the daemon and web UI headless; state under `/home/paseo/.paseo` — Paseo Docker (vendor docs; paseo.sh). <https://paseo.sh/docs/docker>
38. <a id="C31"></a>C31 — the four orchestration skills install per host via Settings or `npx skills add getpaseo/paseo` — Paseo orchestration skills (vendor docs; paseo.sh). <https://paseo.sh/docs/skills>
