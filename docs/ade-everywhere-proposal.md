# ADE everywhere: one repo that recreates the whole agent environment on any machine

Proposal, version 2.1, 2026-10-19. Status: **decided** (section 9 records djbclark's answer to every
question, same day); implementation starts with Phase 0.
Version 1 (commit 8d1cad5) was reviewed the same day by Codex `gpt-6-astra`
([ade-everywhere-codex-review-2026-10-19.md](ade-everywhere-codex-review-2026-10-19.md)); this
version answers all twenty findings (section 12), fixes two wrong citations, and adds a routing
table for the work itself (section 11). Evidence:
[ade-everywhere-inventory-2026-10-19.md](ade-everywhere-inventory-2026-10-19.md) (what exists
today, measured) and [ade-everywhere-prior-art-2026-10-19.md](ade-everywhere-prior-art-2026-10-19.md)
(web research; three of its lines are corrected in section 12). Citations are numbered
superscripts resolved under "Citation footnotes".

What changed from v1, in one paragraph: a synced lease file cannot stop two machines resuming
one session, so continuation on another machine forks by default and exclusive takeover needs a
live handshake; Hermes's database is canonical history, not a cache, so every store is now
classed as canonical, derived or cache before anything is deleted; the plan proves preservation
and a two-machine round trip before it retires or deletes anything; Paseo 0.12.0 already ships
usage, history, import and attention views, so the ADE plugin builds only the delta; Linux and
the bootstrap's root of trust move into the first slice; the "no central node" claim is
narrowed to "no indispensable personal machine".

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
   questions once (private repo URL, secret backend sign-in, vendor logins), and every tool,
   skill, hook, service, plugin and project checkout is present and `ade doctor` is green.
   Running it again changes nothing (idempotent), and chezmoi keeps the originals it replaced.
2. **T2 any project.** `ade clone <project>` (or `--all`) puts every listed project at
   `~/src/<name>` with the right remotes, and the project's own agent wiring (graft, hooks, Tier 1
   pointer) works unchanged.
3. **T3 any session, at three levels.** From machine B, for a session that ran on machine A:
   (a) *readable*: `session-finder` finds it, live or ended, and shows it in full; (b) *native
   continuation*: for Claude Code and Codex it can be continued on B, as a fork by default, or
   in place after A has acknowledged it stopped; (c) *workspace*: the dirty or unpushed work the
   session left behind can be carried over with one command. Level (a) is required for every
   provider, (b) for Claude Code and Codex, (c) for git projects.
4. **T4 no indispensable machine, with a stated loss window.** Each workstation holds a full
   copy of the shared state; the always-on peer holds ciphertext. Losing any one device loses at
   most what that device collected since its last sync (the recovery point is "last
   collection", a few minutes when online, longer when a laptop is asleep). Two retained copies
   exist before any original is deleted. GitHub, Forgejo, Hyades, the tailnet coordinator and the
   secret backend are outside dependencies the design accepts; no personal machine is one.
5. **T5 Paseo parity, proven by a pilot.** One real delegated workflow (a `bigteam` fan-out
   with questions, permission prompts, a quota stop and resume, and a rollback) runs end to end
   from the Paseo desktop, web or phone client before any herdr or Orca piece is retired.
6. **T6 someone else.** A second person forks the public repo, runs the same bootstrap, is
   prompted to create their own private companion, and gets a working environment with none of
   djbclark's hosts, accounts or memory; it works with no 1Password, no Hyades and a Forgejo
   remote.
7. **T7 reproducibility is tested, in CI.** GitHub Actions runs the bootstrap into a clean
   container on every push to the public repo as the fast check; the private companion's
   template test runs on the private repo's Actions, or on Forgejo CI (Hyades) when private
   work needs it; the gate is a real Linux user account that survives a reboot. None of this
   runs on the Mac.

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
jsonl, Codex 135 M of jsonl, OpenCode 1 G of SQLite, Cursor 1.1 G, Gemini 2.2 G. Hermes is 24 G,
of which `state.db` (1.6 G) is the canonical record of every Hermes conversation and the rest is
installs and a Gmail index. The only synced memory is `site-private/memory` and the Tier 2
handoffs, both git. The Tier 1 pointers in `~/.local/state/handoffs` (100 chains, 2.9 M), the most
valuable small item, are synced by nothing. `~/.local/state/bigteam` holds 106 G of scratch
whose reports have not been checked for uniqueness (inventory §6).

**Paseo is installed and in use.** Version 0.12.0 since today, daemon on `127.0.0.1:7263`,
hostname on the tailnet, relay off, providers configured for omp, Cline, Grok, Cursor, GLM,
Gemini, Hermes and Qwen as ACP agents. It stores only small per-agent JSON under
`~/.paseo/agents`; the transcripts stay in each provider's own store. Its usage dialog, history
search and session import already exist (section 7.1). The four Paseo orchestration skills are
installed into `ade/skills` and carry uncommitted edits from Paseo's own refresh.

## 3. Principles

1. **One public kit, one private companion, nothing else required.** `djbclark-ade` is the
   environment. The private companion holds what must be private. Machine provisioning that is
   not about agents (phone fleet, DNS, monitoring stacks) stays in `site-djbclark`/`stayturgid`
   and is optional.
2. **Classify before you copy, preserve before you delete.** Every store is canonical (the only
   record), derived (rebuildable from a canonical store), cache (re-downloadable) or mixed.
   Canonical stores get a verified backup before any phase touches them. File-syncing a live
   SQLite database is a documented way to corrupt it<sup>[1](#C13) [2](#C14)</sup>; canonical SQLite stores are
   backed up with the online backup API or the vendor's export, never by file copy<sup>[3](#C42)</sup>.
3. **Same paths everywhere.** `~/src/<name>` for every project, the same login name on every
   machine where possible. Claude Code keys transcripts by the working directory and embeds
   absolute paths inside them<sup>[4](#C1) [5](#C3)</sup>; identical layouts avoid rewriting, and a Mac-to-Linux
   round trip (`/Users` to `/home`) is an acceptance test, not an assumption.
4. **Declare, then apply, then diff.** chezmoi owns every dotfile and config template (Q4): its
   source state says what exists, `chezmoi diff` shows the plan, `chezmoi apply` makes it so,
   with templates, prompt-once data and a password-manager hook; `ade doctor` compares the
   rest (services, tools, sessions). Hand-made links are the bug class that produced today's
   five broken rules files.
5. **Secrets never touch git, and the trust model is stated.** `sudo-secretspec` grants secrets
   to the authorized operator identity, not per process<sup>[6](#C44)</sup>; 1Password is the default backend
   behind an interface that also admits `age` files or none (T6).
6. **Every workstation is a full peer; the always-on peer is blind.** Replication is
   peer-to-peer over the tailnet; the Hyades or vps-primary peer stores ciphertext it cannot
   read and is not an introducer.
7. **Paseo is the front end, not the engine.** Headless dispatch keeps its tested engine
   (`acp-run`/`acp-dispatch`); Paseo gets visibility and control of it through its CLI, SDK and a
   plugin. It replaces herdr and Orca only after the pilot in T5 passes, and herdr stays as the
   plain-terminal fallback for TUIs Paseo cannot host.
8. **Flag before building.** Where this proposal would discard paid-for work (herdr plugins, Orca
   docs, the hub-era scripts), it asks first (section 9) and schedules the discard last
   (section 8).
9. **CI does the heavy lifting; the Mac stays responsive.** Every build, test suite, container
   run and index rebuild goes to CI first (GitHub runners for GitHub-sourced repos, Forgejo CI
   on Hyades when private work needs it) or to the Linux peer; a local run is the exception,
   goes through `bg`, and never overlaps another heavy job (djbclark, 2026-10-19).
## 4. Target shape

### 4.1 Repos

| Repo | Visibility | Role after the project |
|---|---|---|
| `djbclark-ade` | public | The environment: manifest, bootstrap CLI, skills, orchestration tools, per-TUI config templates, service units, Paseo plugin, docs, tests. Nothing that names a host or account. |
| `site-private` (rename to `ade-private` later, Q1) | private | The operator's companion: memory, handoffs (Tier 1 chains and Tier 2 documents), private skills, machine facts and per-machine overrides, project list, secret declarations and backend references, Paseo profile notes. A template for it ships in the public repo. |
| `site-djbclark` + `stayturgid` | public | Infrastructure that is not the agent environment: phone fleet, DNS, monitoring stack, VPS NixOS, Hyades services. `ade` delegates package and service roles to it where they exist; it never depends on it being present. |
| `aiuse`, `sudo-secretspec`, `herdr`, `hermes-agent`, `orca`, `sipb-agent-skills`, `loopback-port-shim`, `sipb-llms` | public, own repos | Referenced from the manifest with install method and version; not vendored. |

The rename of `site-private` is deferred until every consumer of the name (stayturgid's memory
policy, the three `AGENTS.md` slices, `OPS_ROOT` paths, `.codex-runtime`) is mapped; the
newcomer sees `ade-private` from day one because the template creates it under that name
(Q1).

### 4.2 `djbclark-ade` directory structure (proposed)

Today's layout grew by accretion: `claude/`, `zcode/`, `opencode-plugins/`, `launchd/`,
`config/`, `plugins/`, `scripts/`, `bench/` are seven top-level answers to "where does per-TUI
and per-OS stuff go". Proposed:

```
djbclark-ade/
  AGENTS.md  CLAUDE.md -> AGENTS.md  README.md  LICENSE
  home/                # the chezmoi source state (Q4): every dotfile, per-TUI config template and rules link,
                       # with .chezmoi.toml.tmpl prompting once for the companion URL and operator data
  ade/                 # the ADE CLI (Python, uv): doctor, clone, sessions, services; it calls chezmoi, mise and Ansible
  manifest/
    tools.toml         # every external tool: source repo, install method per OS, version pin, PATH entry
    agents.toml        # every TUI: config dir, skills dir, commands dir, rules file, session store, store class, export and resume commands
    packages.toml      # brew/apt/nix/npm/uv/cargo/pipx package lists, by OS and by role; runtimes via mise
    services.toml      # every long-running job: command, schedule, scope (per-host | per-account | fleet-coordinator), OS
  schema/              # JSON schemas for every manifest and companion file (Q10: product framing)
  skills/              # unchanged; the canonical skills
  bin/                 # orchestration CLIs, unchanged
  tools/acp-run/       # unchanged
  agents/              # per-TUI material, one dir each
    claude/            # settings.json (template), hooks/, commands/, agents/, marketplace
    codex/             # config.toml template, hooks.json, rules/
    opencode/          # opencode.json template, plugins/, commands/
    gemini/  zcode/  cursor/  copilot/  hermes/  qwen/  grok/  cline/  omp/
    paseo/             # owned keys for config.json (a chezmoi `modify_` script merges them, never a symlink), provider catalog entries, profiles generated from routing.toml, plugin list
    rules/home-agents.md   # the one home rules file; every TUI's rules file links here
  services/
    units/             # one TOML per service; launchd plists and systemd user units are generated
  paseo-plugin/        # the ADE Paseo plugin (section 7.3)
  private-template/    # what `ade init-private` creates in a new companion repo: a chezmoi overlay plus the TOML files
  docs/                # design records and the product docs (Q10); handoffs move to the private companion
  tests/               # pytest, the container smoke test, and the Linux-user gate script
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
  operator.toml        # name, email, GitHub/Forgejo logins, tailnet name, default models, pronouns for docs; also the deny-list `ade doctor` greps the public tree for
  machines/<host>.toml # per-machine: OS, role, device id, services this host owns, overrides
  roles/<role>.toml    # workstation | server | phone-control overrides (between private and machine in precedence)
  projects.toml        # every project: remote URL, clone path (~/src/<name>), forge, CI note
  memory/              # unchanged: one fact per file; Basic Memory `main`
  handoffs/
    tier2/             # HANDOFF_*.md from ade/docs/handoffs and memory/handoffs
  skills/              # private skills (1password)
  secrets/
    secretspec.toml    # declarations only; values live in the backend
    backend.toml       # which backend (1password | age | none) and the item references
  agents/              # private per-TUI overrides merged over the public templates
  home/                # the companion's chezmoi overlay (Q4, Q11): personal shell, gradle, anything not agent-needed
```

Tier 1 chains are **not** in git: they are hot, written every session, and belong to the
session archive (section 6.3), where each host's copy is single-writer. Leaves:
`web/maynarddaycare` (a personal website, its own repo); `tailscale/` snapshots (into
`machines/`); `bin/`, `docs/`, `cursor`, `gradle`, `macos`, `prompts`, `shell`, `tests` symlink
shims (deleted once `ade link` owns every path); `.codex-runtime/` (Codex's own store; it stays
where Codex expects it, section 6.1).

### 4.4 Bootstrap: chezmoi plus a small `ade` CLI

djbclark chose chezmoi over a home-grown linker (Q4, 2026-10-19): chezmoi owns dotfiles and
templates from the start, and `ade` shrinks to what chezmoi does not do (doctor, clone,
sessions, services). The only prerequisites are git and a shell.

1. `chezmoi init --apply <public repo>` (or `ade bootstrap`, which runs it): the public source
   state under `home/` lands in `$HOME`. Its `.chezmoi.toml.tmpl` prompts once for the
   companion URL and operator data (`promptStringOnce`)<sup>[7](#C15)</sup>, then
   `.chezmoiexternal` pulls the companion's `home/` overlay so private files win where both
   define a path. Rules files, commands, hooks, agents, skills, Codex home, opencode plugins
   are chezmoi-managed symlinks or files; files other tools also write
   (`~/.claude/settings.json`, `~/.paseo/config.json`) get a `modify_` script that merges only
   the keys the kit owns. Paseo's settings writer replaces a symlinked `config.json` with a
   plain file (fixed in 0.12.0, but a warning about ownership)<sup>[8](#C52)</sup>, and its
   `agentProfiles` schema changed between releases; owned-key merging is the only safe
   contract. `chezmoi diff` is the plan, `chezmoi apply` is idempotent, chezmoi keeps the
   replaced originals.
2. `ade install`: runtimes (uv, Python, Node) through `mise`, pinned in
   `packages.toml`<sup>[9](#C56)</sup>, so Node no longer comes from Hermes's private copy
   (inventory §5); packages per OS from `packages.toml`; external tools from `tools.toml`
   (pinned); agent CLIs from their vendors. Where a `site-djbclark` Ansible role already
   installs something, `ade install` calls the role rather than re-implementing it.
3. `ade init-private <url>`: create the companion from `private-template/` on GitHub or
   Forgejo if it does not exist, then re-run the chezmoi external pull.
4. `ade secrets`: sign in to the chosen backend, declare every secret from `secretspec.toml`
   into `sudo-secretspec`, run each vendor's login that cannot be scripted and say so.
5. `ade services`: generate launchd plists or systemd user units from `services.toml` with this
   machine's paths, honouring each service's scope and `machines/<host>.toml` (section 4.6); on
   Linux, `loginctl enable-linger` so user units survive logout<sup>[10](#C58)</sup>.
6. `ade clone --all`: every project from `projects.toml` to `~/src/<name>`.
7. `ade sessions join`: attach this machine to the session archive (section 6).
8. `ade doctor`: `chezmoi verify` plus a diff of the manifest against reality (tools,
   services, session stores) and the deny-list grep for the operator's names in the public
   tree.

The prompt for an agent is then one paragraph: "clone djbclark-ade, read AGENTS.md, run `ade
bootstrap`, answer its questions, run `ade doctor` until green". `docs/apply-toolchain-prompt.md`
stays as the per-repo toolchain prompt; it is not a machine bootstrap (inventory §4).

**Root of trust.** The one thing the first command cannot verify is itself. The bootstrap
therefore (a) is a tagged release whose tag is signed with the operator's key, and the
one-paragraph prompt names the tag; (b) pins every external tool by version or commit in
`tools.toml`, with the checksum recorded for tarball installs; (c) never curl-pipes an
installer, chezmoi's own included (it is installed from the pinned package list). For a
newcomer (T6) the trust anchor is the public repo's signed tags; they re-sign with their own
key after forking.

**Why chezmoi, and not a home-grown linker, Nix or more Ansible.** v1 proposed its own
`ade link`; the review (F15) noted that "one fewer config language" was a weak argument and
that ownership, adoption, diff and rollback are the costly parts. chezmoi has all four
already, plus templates, the prompt-once pattern and the password-manager
hook<sup>[7](#C15)</sup>, and the product framing (Q10) makes a well-known tool a better
answer for a newcomer than a bespoke one. The cost is a second owner of some files next to
Ansible; the rule is that Ansible never touches `$HOME` once chezmoi does. Nix with
nix-darwin and home-manager gives the strongest pin at the highest cost, and still needs
Homebrew for casks<sup>[11](#C16)</sup>; vps-primary keeps its flake. The public/private split
follows the companion-overlay pattern with precedence and "works without the
overlay"<sup>[12](#C17) [13](#C18)</sup>, with secrets pulled from the backend at apply time
rather than age-encrypted in git<sup>[14](#C19)</sup>.

### 4.5 Secrets and private data

1. **Trust model, stated.** `sudo-secretspec` authorizes the operator identity; every process
   running as that user that passes the boundary can read every declared secret, and the
   client-family labels are correlation metadata, not principals<sup>[6](#C44)</sup>. The design does not claim
   per-process confidentiality. Linux support for `sudo-secretspec` is unverified and is a
   Phase 1 task.
2. **Backends.** `secrets/backend.toml` names one of: `1password` (default on a laptop with the
   desktop app, the SSH agent included), `1password-service-account` (headless Linux and CI),
   `age` (a file in the companion, key held by the operator, as several dotfiles repos
   do<sup>[14](#C19)</sup>), or `none` (T6 minimum). `ade secrets` seeds `sudo-secretspec` from whichever is
   configured.
3. **Declarations**: `secrets/secretspec.toml` says which secrets exist; `backend.toml` maps
   each to its item.
4. **Hosts and accounts**: `operator.toml` and `machines/*.toml`; the public kit refers to them
   only through template variables, and `ade doctor` fails on any deny-list hit in the public
   tree.
5. **Transcripts and their copies.** Transcripts contain whatever agents printed, including the
   odd secret, and so do every index, export and Paseo history built from them. The policy
   (section 6.5) distinguishes full-fidelity backups from redacted exports, sets index file
   permissions, and states that removing a device revokes future access only.
6. **Vendor OAuth tokens**: per machine by design; the bootstrap runs the logins and says which
   ones it could not.

### 4.6 Many machines at once

Things the single-Mac design assumes that a fleet breaks:

1. **Service scopes.** Three, not two. *Per-host*: load-watch, context-budget, the shared MCP
   servers, LiteLLM, the Paseo daemon, `acp-dispatch reap` (it recovers local slices, so it
   runs everywhere), the session collector. *Per-account-or-bot*: the Hermes Telegram gateway
   (two pollers on one bot token fight over `getUpdates`<sup>[15](#C45)</sup>), anything else holding a
   single-consumer credential. *Fleet-coordinator*: fleet-watch, skillopt-night, the downstream
   session ingest. `services.toml` carries the scope; `machines/<host>.toml` names the owner of
   each non-per-host service; other machines install them disabled. Handover is manual
   (disable here, enable there); there is no automatic failover, because a split brain costs
   more than a few hours without fleet-watch.
2. **Paseo schedules** are per daemon and never auto-enabled on every host by the overlay.
3. **Quota state.** `aiuse` and `cswap` read vendor APIs; their caches are per machine and
   advisory.
4. **Memory writes from two machines.** `site-private/memory` is one fact per file, so git
   merges cleanly, but a clean merge is not semantic agreement. Each writer takes a local lock
   around the git mutation, commits and pushes per write with fetch-rebase retry, deletes
   become tombstone facts, and a conflict that survives rebase is pinged to the operator rather
   than auto-resolved. Start-of-session pull stays as a convenience, not the mechanism.
5. **Linux.** `launchd/` becomes generated units (launchd or systemd user); Homebrew entries get
   apt/Nix equivalents or "Mac only" flags; `cow` (APFS) is Mac-only and Paseo worktrees are the
   portable isolation; `heavy-shim`, `macos/` are Mac-only. The first Linux target is a real
   user account on vps-primary or a VM, rebooted, in Phase 1; the container in CI is the fast
   smoke test (keychain, OAuth and sleep cannot be tested there).

## 5. What should not be in the project

1. **Hermes's installs and Gmail index** (about 22 G of the 24 G): rebuildable. Hermes's
   `state.db` is **not** in this list: it is the canonical store of every Hermes session and
   joins the archive as an export (section 6.1). Hermes is its own repo; `~/hermes-memory` and
   the config move to the companion.
2. **`~/.local/state/bigteam` (106 G)** is scratch, but it holds dispatch reports that may be
   the only copy of a slice's result. It is scanned for unique reports and unpushed work before
   deletion (Phase 0), never deleted blind.
3. **Paseo voice models (984 M)**, plugin caches, `~/.claude/plugins/cache`, graft caches,
   `.venv` dirs: re-downloadable, excluded.
4. **Orca state** (2.2 G plus 14 G of workspace checkouts): the checkouts are scanned for dirty
   or unpushed work (the same Phase 0 scan); Orca itself stays until the Paseo pilot passes
   (section 7).
5. **maynarddaycare**: a personal website in `site-private/web`; its own repo.
6. **The phone fleet, DNS, monitoring stacks** (stayturgid, watchdogd, caddy, grafana): machine
   ops, not the agent environment. Still reproducible, from their own repos.
7. **The `~/kb` book corpus**: personal documents; backed up, not part of the environment.
   `book-kb` (the tool) is.
8. **Claude plugin install records** (`installed_plugins.json`, `known_marketplaces.json`): they
   hold absolute install paths and are regenerated from `settings.json`'s `enabledPlugins` and
   `extraKnownMarketplaces`<sup>[16](#C5)</sup>; sync the settings keys, never the cache.
9. **Vendor OAuth tokens**: per machine by design.
## 6. Sessions everywhere

### 6.1 What the stores are, classified

The review's F10 showed v1's survey was stale; this table was re-verified on 2026-10-19 and
is the thing `agents.toml` encodes (adapters pinned to the version checked).

| Provider | Store | Class | Readable export | Lossless backup | Native resume | Import | Remote |
|---|---|---|---|---|---|---|---|
| Claude Code | jsonl per session under a path-derived dir<sup>[4](#C1)</sup> | canonical files | the jsonl itself | copy after completion marker | `--resume`, `--continue`; project dir can be named by `CLAUDE_CODE_PROJECT_DIR_NAME` with `CLAUDE_CONFIG_DIR`<sup>[4](#C1)</sup> | copy into the project dir (target cwd must exist<sup>[17](#C4)</sup>) | cloud sessions; SDK `SessionStore` mirror, best-effort<sup>[18](#C2)</sup> |
| Codex | rollouts under `~/.codex/sessions/YYYY/MM/DD` plus `session_index.jsonl` and `state_5.sqlite`<sup>[19](#C8)</sup> | canonical files plus derived index | the rollout | copy after completion | `codex resume`, `codex fork`, `exec resume`<sup>[20](#C50)</sup>; the index records `rollout_path` through symlinks<sup>[21](#C51)</sup> | `/import` from Claude Code and Cursor<sup>[20](#C50)</sup>; no first-party rollout import | remote connections continue a chat on its host, do not move it<sup>[20](#C50)</sup> |
| Gemini CLI | path-hash keyed store<sup>[22](#C36)</sup> | canonical files | `/export-session <path>` (v0.43.0)<sup>[23](#C47) [24](#C48)</sup> | export | `--session-file`<sup>[23](#C47)</sup> | `--session-file` | none |
| OpenCode | `opencode.db` (SQLite) | canonical SQLite | `opencode session export <id> [--sanitize]`<sup>[25](#C49)</sup> | online backup API<sup>[3](#C42)</sup> plus export | yes | `opencode session import <file> --directory`<sup>[25](#C49)</sup> | none |
| Copilot CLI | session files plus a session-store database<sup>[26](#C35)</sup> | mixed | `/share file|html|gist`, `--remote-export`<sup>[26](#C35)</sup> | copy plus backup API | `--resume`, `--remote --resume` | none | account-bound |
| Cursor | SQLite | canonical SQLite | none verified (third-party exporters only) | backup API | `--resume`, `ls`, `resume` | none | `worker` (private cloud) |
| Hermes | `~/.hermes/state.db`, the canonical store of all session messages and routing<sup>[27](#C41)</sup> | canonical SQLite | `hermes sessions export` (JSONL, full metadata and every stored message, `--redact` available)<sup>[27](#C41)</sup> | backup API plus nightly export | yes | import restores rows as archived history, not live context<sup>[27](#C41)</sup> | Telegram gateway |
| zcode, Crush, omp | SQLite | canonical SQLite | third-party or none | backup API | yes | none | none |
| Paseo | per-agent JSON under `~/.paseo/agents` | derived (points at provider stores) | history search, Import session (Claude, Codex, omp)<sup>[8](#C52)</sup> | copy | n/a | yes | per-host history only |

The lesson of the table: "readable everywhere" (T3a) is achievable for every provider by
collecting the native files or a vendor export; "native continuation" (T3b) is a Claude Code
and Codex feature, with Gemini and OpenCode close behind; nothing moves a running session
between machines.

### 6.2 Options considered for the shared store

| Option | Fits a laptop fleet with no primary? | Verdict |
|---|---|---|
| Replicate the SQLite stores (Litestream, LiteFS, cr-sqlite, sqlite-sync, Turso, rqlite) | No. Litestream streams one writer's WAL to object storage<sup>[28](#C9)</sup>; LiteFS is a single-primary design with limited maintenance<sup>[29](#C10)</sup>; cr-sqlite is thinly maintained<sup>[30](#C11)</sup>; sqlite-sync is new and Elastic-licensed<sup>[31](#C18b)</sup>; Turso and rqlite need a server or quorum. All of them must sit under the application, which we do not own for vendor stores. | Rejected on topology, not on project status. |
| Dolt with a git remote | Yes for tables, since Dolt now pushes to plain git remotes<sup>[32](#C12)</sup>, but it is a new engine for data that is files. | Not now; revisit if we want a git-hosted catalogue. |
| git for transcripts (clync-style UUID merge plus LFS)<sup>[33](#C6)</sup> | Append-only jsonl merges, but 10 GB and growing bloats history and LFS costs on GitHub; clync picks between divergent runs. | Rejected for transcripts; kept for memory and Tier 2 handoffs. |
| git-annex with Forgejo or Hyades as special remote | Not a folder mirror by its own account<sup>[34](#C34)</sup>, but its `numcopies` and preferred-content rules are exactly the "two copies before deletion" policy<sup>[35](#C57)</sup>. | Adopted for the cold tier (Phase 5). |
| CASS (coding_agent_session_search) pulling over SSH | Already collects from remote hosts over SSH or rsync with per-source provenance and path maps, indexes twenty-plus agents, and has a JSON API<sup>[36](#C23)</sup>. Pull-based, so an offline laptop is unsearchable until it is back. Licence has a rider excluding Anthropic, OpenAI and anyone acting for them; djbclark accepts it as inapplicable to this personal use (Q12). | **Adopted** as the index over the archive (Phase 2); the FTS5 index stays only as a fallback for a store CASS cannot read. |
| Syncthing over the tailnet | Peer-to-peer, no central node, fine for unique-named append-only files with one writer per file; concurrent writes to one file produce a `.sync-conflict` copy, never a refusal<sup>[37](#C40)</sup>; untrusted "receive-encrypted" peers exist but are marked beta, and recovery needs both the folder ID and the password<sup>[38](#C20b)</sup>. | **Chosen** for the live tier; it is sync, not backup. |
| Mutagen, rclone bisync, rsync over Tailscale SSH | Pairwise, no ownership semantics<sup>[39](#C21)</sup>. | Fallback for a machine that cannot run Syncthing. |
| Taildrive | Alpha WebDAV mount, not sync<sup>[40](#C22)</sup>. | Rejected. |

### 6.3 Design

**Identity.** Every archived item is keyed by (provider, project slug, session id, device id,
generation). The device id is Syncthing's device ID, not the hostname (hostnames repeat and
change). A generation is one captured snapshot of a session file: size, sha256, and a
completion marker written last; a later capture of a grown file is a new generation, and a
rewrite (Claude's compaction, Codex's fork) is detected by hash, not by size.

1. **The archive.** `~/ade-sessions/` is a Syncthing folder shared by every workstation. Layout:
   `<provider>/<device-id>/<project-slug>/<session-id>/<generation>.jsonl` plus sidecars
   (subagent dirs, file-history, Codex `session_index.jsonl` rows), and
   `<provider>/<device-id>/exports/` for the SQLite-backed TUIs (OpenCode and Gemini exports,
   Hermes `sessions export` JSONL nightly, Cursor and zcode third-party exports) alongside a
   `.backup`-API copy of each canonical SQLite file taken by the collector, never a live copy.
   The `<device-id>` level is what makes every file single-writer.
2. **The collector.** `ade sessions collect` (per-host, every few minutes, on wake, and
   enqueued by each TUI's end-of-session hook; Claude's `SessionEnd` is time-bounded and skipped
   on a kill, so the hook only enqueues<sup>[41](#C43)</sup>) copies (APFS clone on Mac, plain copy elsewhere;
   never a hardlink, which shares the inode) new generations into this device's subtree, trims a
   partial last jsonl line, and runs the exporters. It never writes into another device's
   subtree. The existing `s1_*` ingesters and `session-finder`'s adapters become this collector.
3. **The peers.** Every workstation plus one always-on peer (Hyades or vps-primary, Q2) in
   Syncthing's receive-encrypted mode, so the peer stores ciphertext only. It is **not** an
   introducer (an untrusted device must not be able to add devices to trusted ones). Folder ID
   and password are stored in the secret backend. Syncthing's file versioning is on, so a
   deletion on one workstation is recoverable from the others' version folders; a
   restore-from-ciphertext drill is part of Phase 3.
4. **The index.** CASS (Q12), pointed at the archive instead of at remote hosts, with a
   per-provider path map per device; where an adapter cannot read one of our stores (its
   OpenCode adapter looks for `.opencode/` directories, ours is
   `~/.local/share/opencode/opencode.db`) the collector's export feeds it, and only a store
   with no readable export falls back to `session-finder`'s FTS5 database
   (`history.v2.sqlite`) with a `device` column. `session-finder` keeps live sessions and file
   claims, which no archive can know, and fronts CASS's JSON API. Orca's cross-host
   `orca search`<sup>[42](#C24)</sup> is the retired equivalent.
5. **Continuation on another machine.** `ade sessions pull <id>` copies a Claude or Codex
   session's latest complete generation into this machine's native store at the path the local
   checkout implies, creates the checkout directory if absent<sup>[17](#C4)</sup>, rewrites only cwd fields
   when the home directory differs<sup>[5](#C3)</sup>, touches mtimes so the 30-day cleanup does not eat the
   copy<sup>[4](#C1)</sup>, and refuses if more than one other project dir already holds the id (Claude's
   lookup rule<sup>[4](#C1)</sup>). By default it **forks**: the continued session gets a new id whose first
   record names the parent id and device, so two machines can never write the same session.
6. **Exclusive takeover.** `ade sessions pull --take <id>` continues under the same id only
   after a live handshake: it asks the origin device over Tailscale SSH whether the session is
   open, and the origin's collector answers "stopped at generation N" or refuses. No file-based
   lease: a synced lease file cannot exclude anything, because Syncthing reconciles after the
   fact and both offline laptops would see their own lease as valid<sup>[37](#C40)</sup>. The old `.lease`
   idea survives only as an advisory marker shown by `session-finder`.
7. **Workspace carry-over (T3c).** `ade sessions pull --with-work` also fetches a `git bundle`
   of the origin checkout's unpushed commits and a patch of its dirty tree, produced by the
   origin's collector on request<sup>[43](#C46)</sup>; this is what makes "continue the work" rather than
   "re-read the chat" possible.
8. **Tier 1 pointers.** `~/.local/state/handoffs` joins the archive the same way (per device)
   and `session-handoff` reads all devices; chain keys are already unique. Tier 2 handoffs stay
   in git.

### 6.4 Memory

Basic Memory stays: markdown in git plus a per-machine index<sup>[44](#C25)</sup>. The seven empty
`~/agent-memory/*` projects are removed or pointed into the companion. `hermes-memory` moves into
the companion. The SiYuan and `~/kb` stores are out of scope (section 5). Concurrency is the
lock-and-push rule of section 4.6.

### 6.5 Retention, privacy and the loss window

1. **Hot tier**: every workstation, one year. **Cold tier**: git-annex with `numcopies 2`
   across the peer and at least one workstation<sup>[35](#C57)</sup>; `ade sessions archive` moves sessions
   older than a year and refuses to drop the hot copy until two annex copies verify.
2. **Copies are plaintext in more places than the archive**: the CASS or FTS5 index, Paseo's
   history, the Hermes export. Index files are mode 0600; exports used for sharing are made with
   `--redact` or `--sanitize`; full-fidelity copies never leave operator-owned devices or the
   ciphertext peer.
3. **Lost device**: remove it from Syncthing, rotate the receive-encrypted folder password, and
   accept that copies already on the device are not erased. Deletion scope is future access
   only unless djbclark asks for more (Q13).
4. **Loss window**: what a device collected since its last sync. When a laptop is asleep that
   can be days; the operator accepts it (T4) or runs the collector before closing the lid.

## 7. Paseo as the universal front end

### 7.1 What Paseo is, in our terms, at 0.12.0

An Apache-2.0 daemon per machine plus desktop, web, mobile and CLI clients; clients attach to any
daemon over SSH, the optional encrypted relay, or directly over Tailscale (the phone needs the
tailnet or the relay)<sup>[45](#C26) [46](#C33)</sup>. Agents run where the daemon runs, with that machine's tools
and credentials; the daemon persists workspaces, agent metadata and schedules, and leaves
transcripts in each provider's store. Agents inside Paseo get MCP tools to create workspaces,
launch and message other agents across providers and hosts, and set schedules and
heartbeats<sup>[47](#C28)</sup>. Plugins are trusted TypeScript installed per daemon and can add screens,
panels, Command Center items, slash commands, composer pills, timeline rows, themes,
attachment sources, daemon RPCs, usage sources and whole providers<sup>[48](#C27)</sup>. The CLI drives any
daemon with `--host`<sup>[49](#C32)</sup>; Hub is optional and self-hostable<sup>[50](#C29)</sup>; an official Docker image
runs the daemon headless<sup>[51](#C30)</sup>.

What it already has that v1 proposed to build: a **Usage** dialog with pinned summaries and a
plugin usage-source API (0.11.0), `paseo usage` on the CLI (0.12.0), history search and
**Import session** for Claude, Codex and omp, background workspaces, and a fix for parents
being told a child finished when its task was stopped<sup>[8](#C52)</sup>. Registry plugins add a cross-host
workspace list ordered by attention (Agents Dash List)<sup>[52](#C53)</sup>, an LLM-summarised feed of waiting
questions and permissions (Herald)<sup>[53](#C54)</sup>, and archived-conversation search for file-backed
providers on that daemon (Agents History)<sup>[54](#C55)</sup>. Custom providers accept per-provider `env` and
a custom binary<sup>[55](#C59)</sup>; agent profiles are saved per host with no export<sup>[56](#C60)</sup>.

So the "no indispensable machine" test holds: one daemon per machine, clients add each host
over the tailnet, relay off, Hub not needed. Paseo does **not** sync sessions between daemons;
section 6 covers that.

### 7.2 Capability map: today's loop against Paseo

Nothing in the "Decision" column happens before the T5 pilot; "replace" means "replace once the
pilot has exercised it".

| Today (herdr/Orca) | Paseo equivalent at 0.12.0 | Decision |
|---|---|---|
| herdr workspaces, tabs, panes as the place every session lives | Workspaces with agents, terminals, files, diffs, browser in split panes | Replace for Paseo-hosted agents; herdr stays as the plain-terminal fallback for any TUI Paseo cannot host. |
| Orca worktrees, task DAG with crash recovery, `orca search` | Worktree isolation and orchestration tools; no DAG persistence, no file claims, no quota-reset resume | Worktrees: replace. DAG, claims and resume stay in `acp-dispatch`; `orca search` is replaced by section 6.3.4. |
| `session-finder fleet.py` (which live session is where) | `paseo ls -a --host <h>` per host; Agents Dash List across hosts | Keep `fleet.py` as the aggregator over Paseo's CLI; drop its herdr and Orca adapters after the pilot. |
| `launch.py` starts a session over ACP in a visible pane | `create_agent` / `paseo run` with any provider, including the ACP catalog | Replace behind an adapter contract: idempotent start, question and permission response, cancel, report, resume. |
| `helm` answers every waiting session from one window | Herald (LLM-paraphrased items, child agents off by default); permission prompts per host; mobile approvals | Build the **Helm panel** as the delta: verbatim questions, request ids, ranking by work unlocked, one-tap relay, child agents included (section 7.3). |
| `herdr-tidy` closes idle panes with a close ledger | `archive_workspace`; agents keep their transcripts | Replace with a plugin RPC that writes the same ledger. |
| `herdr-sleeper`, `herdr-jump`, `herdr-ai` | Daemon manages idle agents; Command Center; chat | Retire after the pilot, not before (section 8, Phase 6). |
| `self-slash` types a slash command into a pane | Prompt the agent through the API | Replace. |
| `autorename`, `herdr_place.py` | `rename_workspace`, agent title | Replace; keep the title derivation. |
| `fleet-watch` pings Hermes on fleet changes | `notifyOnFinish`, push notifications to the phone app | Keep the Hermes ping for Telegram; feed it from Paseo events. |
| `acp-run` / `acp-dispatch` / `bigteam` / `route_agent.py` headless dispatch | `paseo run --provider X --no-wait`, SDK (`agents.create`, `waitForFinish`, `send`, `stop`, `--output-schema`), agent profiles | Keep the engine, which owns its processes and the policy layer (routing, quota-stop resume, reports, `BLOCKED:`, escalation, calibration); add `--via paseo` so slices appear as subagents; generate profiles from `routing.toml`; re-compare after the pilot (Q9). |
| `aiuse` quota probes and `route_agent.py` | Usage dialog, `paseo usage`, usage-source plugin API | Keep `aiuse` as the source of policy (disabled list, gates, pace); the plugin registers it as a usage source (section 11.4). |
| `cow-pasture` APFS workspaces | Worktree isolation | Keep cow for non-git and Mac-only speed; Paseo worktrees are the portable default. |
| launchd jobs that run agents (skillopt-night) | Schedules and heartbeats | Move agent-shaped jobs to Paseo schedules on their owning host only; system jobs stay units. |
| Hermes Telegram gateway | Paseo mobile app for approvals and chat | Keep both; Hermes is the always-on assistant, Paseo the workbench. |
| Skills linked into every TUI | Paseo installs its four skills on each host<sup>[57](#C31)</sup> | Unchanged; `ade link` owns the links, Paseo's managed-file manifest stays. |

### 7.3 The ADE Paseo plugin: the delta only

One plugin in `paseo-plugin/`, installed on every daemon by `ade link`, pinned to the daemon
version it was built against:

1. **Helm panel**: a screen listing waiting agents across all hosts the client knows, with the
   pending question verbatim (not paraphrased), the request id, child agents included, ranked
   by `helm.py`'s logic, one-tap relay.
2. **Quota source and routing pill**: `aiuse` registered as a Paseo usage source, so the Usage
   dialog shows the eleven providers with pool families; a composer pill with
   `route_agent.py`'s recommendation for the current slice kind.
3. **Dispatch timeline rows**: `acp-dispatch` slices appear in the parent agent's timeline with
   report and `BLOCKED:` state.
4. **Session search panel**: a workspace panel over the archive index (CASS or FTS5), with
   "pull here" offering fork, take, and with-work.
5. **Tidy and handoff commands**: Command Center items that run `/handoff` then archive, writing
   the close ledger.

### 7.4 What stays outside Paseo

Dispatch to agents that Paseo cannot host, the quota probes, the load watcher, the nightly
skill-edit cycle's non-agent parts, `sudo-secretspec`, and herdr as the plain-terminal
fallback. Paseo is a client of all of these.
## 8. Phases, as gates

Each phase ends green on `ade doctor` and is a separate PR set, each PR with an `adversary`
security verdict in its body. Durations are estimates. The order is the review's: preserve,
then prove a thin slice end to end, then widen, and only then retire or delete.

1. **Phase 0, preserve and classify (days).** Classify every store per section 6.1; take a
   `.backup`-API copy of Hermes `state.db`, OpenCode, Cursor and zcode databases plus a Hermes
   JSONL export; scan `~/.local/state/bigteam` and the Orca checkouts for unique reports,
   dirty trees and unpushed commits and bundle them; fix the five broken rules links; track the
   four untracked config files as templates. Nothing is deleted.
2. **Phase 1, thin vertical slice (1 to 2 weeks).** The chezmoi source state under `home/`
   for Claude Code and Codex only, with the companion overlay and the `modify_` merges;
   `manifest/*.toml` for the same two; `ade doctor`, `services`, `install` with mise; the
   signed-tag root of trust; `private-template/` and `ade init-private` with an empty companion.
   The first PR adds the GitHub Actions workflow (pytest plus the container smoke test) so
   every later PR is tested off the Mac; the companion test gets its own workflow on the
   private repo, moved to Forgejo CI if private work needs it. Gate: apply, reapply and doctor
   pass on this Mac **and** on a real Linux user account that survives a reboot, with a Forgejo
   remote and the `none` secret backend (so T6 is tested before djbclark's own companion is).
3. **Phase 2, sessions spike (1 week).** Stand up CASS over the real stores (adapter coverage,
   the OpenCode path map, the export feed for stores it cannot read); implement the capture
   protocol (generations, completion marker, APFS clone) for Claude Code and Codex; a
   cross-home resume test (Mac to Linux, `/Users` to `/home`) that forks by default; the
   takeover handshake. Gate: a session
   started on A is read, forked and continued on B, and B's work bundle comes back to A.
4. **Phase 3, sessions for everyone (1 to 2 weeks).** Syncthing folder with versioning, the
   receive-encrypted peer (Q2), the restore-from-ciphertext drill, every other provider's
   exporter, Tier 1 chains in the archive, `session-finder` over all devices, retention and the
   lost-device procedure. The initial Syncthing scan and the first full index build run on
   the Linux peer and off-hours on the Mac at low priority; the Mac never rebuilds the whole
   index while the operator is working.
5. **Phase 4, Paseo pilot (2 to 3 weeks).** Owned-key config merge, profiles generated from
   `routing.toml`, the plugin (Helm panel first, then the usage source), `launch.py` and
   `fleet.py` over the adapter contract, `acp-dispatch --via paseo`. Gate: the T5 pilot workflow
   (fan-out with questions, permissions, a quota stop and resume, a rollback) from desktop and
   phone, with Orca and herdr still installed as the fallback.
6. **Phase 5, widen (1 to 2 weeks).** The remaining providers, services and memory into the
   manifest; the agent-service Ansible roles (Q3); cold tier with git-annex; a second Mac from
   nothing with the one prompt; T1 to T5 pass on three machines.
7. **Phase 6, retire and delete (days).** Capability-map sign-off with both frontier reads
   (section 11); retire Orca and herdr's agent plugins (Q5); delete the scratch and duplicate
   stores whose preservation Phase 0 proved.
8. **Phase 7, product (2 to 3 weeks, can start after Phase 2).** djbclark chose full product
   framing (Q10): JSON schemas for every manifest and companion file, `ade doctor` validating
   against them, a documented config surface, templates and docs written for an arbitrary
   operator, the newcomer walkthrough from a fresh account with no 1Password, no Hyades, no
   Mac and a Forgejo remote (Q17), and a release process (signed tags, changelog). The
   optional features (sessions sync, cold tier, Hermes gateway) are documented as add-ons.

## 9. Decisions, with djbclark's answers (2026-10-19)

Numbering continues from v1 so earlier references stay valid; Q1 to Q11 are restated where the
review changed the recommendation, Q12 to Q17 are new. Every item was answered in a `/steps`
walk on 2026-10-19; the answer follows each question.

1. **Q1 Rename `site-private` to `ade-private`?** Now recommended: **later** (Phase 5), after
   every consumer of the name is mapped; the template creates a newcomer's companion as
   `ade-private` from day one.
   **Decided 2026-10-19: later, Phase 5.**
2. **Q2 Always-on Syncthing peer: Hyades or vps-primary?** Recommended: vps-primary if it stays
   (NixOS, already on the tailnet, a flake we control); Hyades if vps-primary is going away.
   Either runs receive-encrypted and is not an introducer.
   **Decided: vps-primary.**
3. **Q3 Move the agent-service Ansible roles (`shared_mcp`, `basic_memory_mcp`, `litellm`,
   `paseo_desktop`, the agent half of `site_agents`) from `site-djbclark` into
   `djbclark-ade/services`?** Recommended: yes, in Phase 5; until then `ade install` calls them
   where they are.
   **Decided: yes, Phase 5.**
4. **Q4 Provisioner.** Recommended as written in 4.4: a narrow `ade` CLI for ADE concepts,
   mise for runtimes, existing Ansible for system roles, chezmoi recorded as the switch-to, no
   Nix for Macs.
   **Decided: chezmoi now; `ade` keeps doctor, clone, sessions, services (section 4.4 rewritten).**
5. **Q5 Retire Orca and herdr's agent plugins once the Phase 4 pilot passes?** This discards
   `herdr-sleeper`, `herdr-jump`, `herdr-ai`, `reorg-orca`, `orca-reorg-watch` and the Orca docs.
   Recommended: yes for Orca after the pilot; herdr stays as the plain-terminal fallback.
   **Decided: yes, after the pilot.**
6. **Q6 Scope of native continuation (T3b): Claude Code and Codex now, Gemini and OpenCode
   when their export and import prove lossless, everything else read-only?** Recommended: yes.
   **Decided: as recommended.**
7. **Q7 Retention and at-rest policy**: hot tier a year on every workstation, cold tier
   git-annex with two copies; are encrypted transcripts allowed on a Hyades volume?
   **Decided: hot one year; cold on vps-primary plus one Mac; no Hyades volume.**
8. **Q8 Which machines are the fleet?** Macs, vps-primary, Hyades containers, Android phones?
   The bootstrap targets Mac and Linux; Termux is out unless you say otherwise.
   **Decided: Macs plus vps-primary; Hyades containers run services only; phones are clients.**
9. **Q9 Dispatch engine**: keep `acp-run` as the engine with a Paseo route (recommended), or
   move `acp-dispatch` onto the Paseo SDK and retire `acp-run`.
   **Decided: keep `acp-run`, add the Paseo route, re-compare after the pilot (capabilities, robustness and maintenance cost were compared in the decision walk).**
10. **Q10 Public-kit genericity**: how far to go for T6? Recommended: the operator's login,
    hosts and accounts out of the public tree via the deny-list, nothing more (no multi-tenant
    abstractions).
    **Decided: full product framing (Phase 7).**
11. **Q11 Shell and dotfiles**: `site-djbclark/shell` and `gradle/` are "my environment" but
    not the agent environment. Recommended: `ade` ships the shell fragments agents need (PATH,
    rtk, `bg`), the rest stays in site-djbclark.
    **Decided: agent-needed fragments public; personal shell and gradle in the companion's chezmoi overlay.**
12. **Q12 CASS licence.** Its MIT licence carries a rider granting no rights to Anthropic,
    OpenAI or anyone acting on their behalf, with "use" including indexing in automated
    pipelines<sup>[36](#C23)</sup>. Agents running on those vendors' models would be the ones invoking it.
    Whether that rider applies to this use is your call (this is not legal advice); if no, the
    FTS5 index path in 6.3.4 is the default and the spike is skipped.
    **Decided: adopt CASS; the rider is accepted as inapplicable to this personal use.**
13. **Q13 Deletion scope.** Is "future access only" (revoke the device, rotate the folder
    password) enough when a device is lost or a person leaves, or do you want a deletion
    requirement that spans local indexes, backups and the cold tier?
    **Decided: future access only.**
14. **Q14 Partition behaviour.** When the origin machine is unreachable, is a labelled fork
    the right default for continuation (recommended), or should `ade sessions pull` refuse
    until the origin answers?
    **Decided: fork by default, labelled.**
15. **Q15 Loss window.** Is "what a sleeping laptop collected since its last sync" acceptable
    (recommended), or must every turn be remotely durable before it is acknowledged (which
    would need a synchronous write to the peer and changes the design)?
    **Decided: the last-collection window is acceptable.**
16. **Q16 Memory governance.** Lock-and-push with tombstones and a ping on conflict
    (recommended), or a designated curator machine that is the only writer?
    **Decided: lock-and-push, tombstones, ping on conflict.**
17. **Q17 Newcomer minimum.** Confirm T6's floor: no 1Password, no Hyades, no Mac, a Forgejo
    remote; which optional features may be absent in that mode (recommended: sessions sync,
    cold tier, the Hermes gateway).
    **Decided: all four absent must work; sessions sync, cold tier and the Hermes gateway are optional add-ons.**

## 10. Risks

1. **Transcript path coupling.** Claude Code's slug and embedded paths make Linux continuation
   of a Mac session a rewrite with known traps<sup>[5](#C3)</sup>; identical layouts remove most of it, the
   cwd-only rewrite and the Phase 2 round-trip test catch the rest. The
   `CLAUDE_CODE_PROJECT_DIR_NAME` route needs a per-project `CLAUDE_CONFIG_DIR` and is a
   prototype, not the default, until its effect on credentials, plugins and settings is
   measured<sup>[4](#C1)</sup>.
2. **Paseo moves fast.** 0.12.0 today; the config schema and plugin contracts have changed
   between releases<sup>[8](#C52)</sup>. Mitigation: owned-key merges instead of symlinks, daemon, clients and
   plugin pinned together in `tools.toml`, the plugin kept small.
3. **Syncthing is sync, not backup.** Deletions propagate; the encrypted peer is beta<sup>[38](#C20b)</sup>.
   Mitigation: versioning on, the cold tier's two-copy rule, the restore drill.
4. **Two machines editing memory** produce occasional git conflicts and, more quietly,
   semantically inconsistent facts that merged cleanly. Mitigation: lock-and-push, tombstones,
   a ping on conflict, and a periodic consistency pass by an agent.
5. **The ops-suite policy** (stayturgid, three AGENTS.md slices) assumes `site-private`; the
   rename, when it comes, must keep that contract or update all three files in one commit.
6. **Discarding paid-for work** (herdr plugins, Orca integration) is a loss if Paseo turns out
   worse at something; the phase order retires nothing until the pilot has run the real
   workflow, and keeps herdr regardless.
7. **CASS's licence** may exclude the agents that would run it (Q12); the FTS5 path is kept
   ready.
8. **Quota.** The work itself competes with everything else for the Claude weekly window
   (section 11); the plan spends the near-full Gemini pool on research and bulk first.
9. **Mac load.** Container tests, index rebuilds and parallel agent fan-outs would make the
   workstation unusable. Mitigation: section 11.3; every PR is tested in CI before any local
   run, and the Linux peer hosts the heavy daemons.
## 11. Routing per phase: which AI does which step

Snapshot 2026-10-19 16:17 UTC from `aiuse --available --json` (remaining share of each window)
and `paseo usage --json`; re-probe before each batch, the numbers date fast. The $200 Claude plan
(Max 20x) is the deep pool: its weekly window is the one to pace, the 5-hour window turns over
by itself. Codex moved to the $100 plan on 2026-10-19 (aiuse plan label `prolite`), so the
Codex gate no longer waits on a 5-hour window. Rulings for this project (djbclark, 2026-10-19): antigravity (`agy`) is allowed on
both its pools, whichever is usable; Paseo's `glm-acp-agent` draws the `zai` pool; copilot,
gemini CLI and qwen-code are configured in Paseo but off; cline only for Hermes and
techno-euphora; hermes is never a target; omp needs an explicit yes per run.

### 11.1 Pools, as of the snapshot

| Pool (agent) | Remaining | Resets | Use it for |
|---|---|---|---|
| Claude Max 20x, default (`claude`) | 73% 5h, 51% weekly | 5h 19:10 UTC; weekly 2026-10-23 | judgment, integration, code |
| Claude Max 20x, Fable (`claude`) | 68% weekly | 2026-10-23 | one frontier gate per phase |
| Codex $100 plan (`codex`, aiuse plan "prolite") | 100% weekly (upgraded 2026-10-19) | weekly 2026-10-26 | the other frontier gate; no longer the scarce pool |
| antigravity Gemini (`agy`) | 96% weekly, 100% 5h; argon weekly 100% | 2026-10-25 | research, bulk, mechanical (aiuse's top "burn" suggestion) |
| antigravity Claude/GPT (`agy`) | 1% weekly, exhausted | 2026-10-24 18:18 UTC | nothing until the reset, then code |
| Cursor (`cursor`) | 70% auto, 8% third-party | 2026-11-10 | mechanical and bulk on `auto` only |
| z.ai GLM (`zcode`, Paseo `glm-acp-agent`) | 36% weekly | 2026-10-21 | isolated code modules, bulk |
| Grok (`grok`) | 59% | 2026-10-22 | realtime web research |
| OpenCode Go (`opencode`) | 2% monthly | 2026-11-10 | nothing this month |
| omp credits | 100% | 2026-11-05 | a Claude-pool code slice, only with an explicit yes |
| copilot, gemini CLI, qwen-code, cline, hermes | off by ruling | | never |

### 11.2 The table

"Context" is the window the slice is given; keep it at the default unless the row says
otherwise, because a 1M-token Claude window costs the weekly pool several times faster.

| Phase | Slice kind | Agent and model | Effort | Context | Pool | Why |
|---|---|---|---|---|---|---|
| every phase gate | frontier review, advise only | codex `gpt-6-astra` | high | default | Codex weekly 69% | the review that found F1 and F2; one per gate |
| every phase gate | second frontier read | claude `fable` 5.1 | high | 200k | Fable 68% | independent of Codex; `xhigh` only with a yes for that run |
| every phase | lead, design, integration, decisions | claude `opus` 5.5 | high | 200k | Claude weekly 51% | the session that owns the plan and the merges |
| every PR | security review | `adversary` agent (Claude) | high | 200k | Claude weekly | required before any PR (home rules item 28) |
| 0 hygiene | link fixes, config templating, duplicate resolution | cursor `auto` | low | default | Cursor auto 70% | mechanical, file-scoped, cheap |
| 0 hygiene | privacy sweep of `docs/handoffs`, `queue.md` | agy `gemini-3.8-flash` | medium | default | Gemini 96% | read-heavy, no judgment needed beyond a list |
| 1 manifest and `ade` CLI | manifest rows from the inventory | agy `gemini-3.8-flash` | low | default | Gemini 96% | bulk transcription with a schema |
| 1 manifest and `ade` CLI | chezmoi source state, `modify_` merges, companion overlay | claude `sonnet` 5.5 | high | 200k | Claude weekly 51% | templates and merge scripts against real config files; chezmoi docs re-read per slice |
| 1 manifest and `ade` CLI | `ade doctor`, `ade services`, `ade install` (Python, uv) | claude `sonnet` 5.5 | high | 200k | Claude weekly 51% | code that must be right first time; tests included |
| 1 manifest and `ade` CLI | root of trust: signed bootstrap, pinned tool versions | claude `opus` 5.5 then codex gate | high | 200k | Claude, Codex | security design, then an outside read |
| 1 manifest and `ade` CLI | Linux container CI (T7) | claude `sonnet` 5.5 | medium | 200k | Claude weekly | small, iterative on GitHub runners |
| 2 private companion | `private-template/`, `ade init-private`, newcomer trial | claude `sonnet` 5.5 | high | 200k | Claude weekly | code plus the empty-companion test |
| 2 private companion | provider and tool survey refresh (F10) | agy `gemini-4-argon` | high | default | argon weekly 100% | research with many sources; cheapest fresh pool |
| 3 sessions | identity model and store classification (§6) | claude `opus` 5.5, codex gate | high | 200k | Claude, Codex | the blocker findings live here |
| 3 sessions | collector over every adapter (`s1_*`, session-finder) | claude `sonnet` 5.5 | high | **1M** | Claude weekly | the one whole-archive refactor; budget it as several ordinary slices |
| 3 sessions | per-store exporters (OpenCode, Cursor, zcode, Hermes) | zai `GLM-5.3` | high | default | z.ai 36% | isolated modules with a fixed contract |
| 3 sessions | Syncthing units, receive-encrypted peer, two-machine trial | claude `sonnet` 5.5 | high | 200k | Claude weekly | ops plus a real trial on two hosts |
| 2 sessions spike | CASS deployment, path maps, export feed | claude `sonnet` 5.5 | high | 200k | Claude weekly | Rust tool, our adapters; the index runs on the Linux peer |
| 3 sessions | SQLite backup checks and exporter research | grok `grok-4.7` | high | 256k | Grok 59% | realtime web plus repo reading |
| 4 Paseo delta | ADE plugin (Helm panel, dispatch rows, session panel) | claude `sonnet` 5.5 | high | 200k | Claude weekly | TypeScript against a moving API; re-read `llms.txt` each slice |
| 4 Paseo delta | `launch.py`, `fleet.py`, `acp-dispatch --via paseo` | claude `sonnet` 5.5 | high | 200k | Claude weekly | touches the dispatch engine; tests first |
| 4 Paseo delta | profile and provider catalog entries | cursor `auto` | low | default | Cursor auto | mechanical JSON |
| 5 second machine | bootstrap a Linux box and a second Mac | claude `opus` 5.5 (driving `ade`) | high | 200k | Claude weekly | judgment under failure; fixes go back as Sonnet slices |
| 6 retire and clean | capability-map sign-off, retire Orca and herdr plugins | claude `opus` 5.5, then both gates | high | 200k | Claude, Codex, Fable | the irreversible step gets both frontier reads |
| 7 product | JSON schemas, `ade doctor` validation, release process | claude `sonnet` 5.5 | high | 200k | Claude weekly | schema work needs exactness |
| 7 product | docs and templates for an arbitrary operator | agy `gemini-3.8-flash` draft, claude `sonnet` 5.5 edit | medium | default | Gemini 96%, Claude | bulk prose first on the cheap pool, one careful pass after |
| 7 product | newcomer walkthrough from a fresh account | agy `gemini-4-argon` | high | default | argon 100% | an agent with none of this machine's context is the right tester |

### 11.3 Where the work runs: CI first, the Mac last

Ruling (djbclark, 2026-10-19): make full use of GitHub CI, and of Forgejo CI when private work
needs it, during this project and in general; avoid high Mac load.

| Work | Runs on | Notes |
|---|---|---|
| pytest, lint, the `ade` container smoke test, plugin build | GitHub Actions on `djbclark-ade` | free runners for a GitHub-sourced repo; the first PR of Phase 1 adds the workflow; `load-watch ci decide` is the check before any local run |
| private companion template test, `ade doctor` against a real companion | GitHub Actions on the private repo, or Forgejo CI on Hyades when the data or the minutes require it | secrets via the `none` backend in CI; never the operator's 1Password |
| the real-Linux-user gate (reboot, linger, services) | vps-primary or a VM, not CI | the one test a container cannot run |
| archive index builds (CASS or FTS5), Syncthing initial scan, Hermes export | the Linux peer; on the Mac only off-hours, low priority, through `bg` | 10 GB of small files; never while the operator is working |
| agent fan-outs during the project (`bigteam`, `acp-dispatch`) | Paseo daemon or `acp-run` on vps-primary where the agent's tools allow; the Mac runs the lead session | Paseo's one-daemon-per-machine model is what makes this a client choice, not a redesign |
| local runs that cannot be avoided | `~/ops/site-private/bin/bg`, one heavy job at a time | never `BG_LOAD_WAIT=0`, never two builds |

### 11.4 Reading the two quota sources

`paseo usage --json` (0.12.0) and `aiuse --available --json` agree to within one point on every
window they both report (Claude 5h, weekly and Fable; Codex 5h and weekly; Grok weekly) and
give the same reset times. Paseo covers five sources (Claude on two accounts, Codex, Cursor,
Grok, Muse) and reads per account, so it shows the plan name ("Max 20x", "plus") and caught an
expired Claude credential that Pi had refreshed; its Cursor row is empty and Muse reports no
quota. `aiuse` covers eleven providers with pool families (Gemini against Claude/GPT inside
antigravity, auto against third-party inside Cursor), pace projections, state (`ok`, `tight`,
`exhausted`), alerts, a single "burn this first" suggestion and the policy semantics (disabled
list, operator gates). The routing table therefore reads `aiuse`; Paseo's usage view is the
operator's glance and the ADE plugin's quota pill should read `aiuse` rather than duplicate it
(§7.3).

## 12. Response to the Codex review

The review (gpt-6-astra, 2026-10-19) made twenty findings; each was re-verified against its
primary source by an Opus sub-agent before this version was written. All twenty are accepted,
six with a change of remedy. The table says what moved.

| Finding | Decision | What changed in v2 |
|---|---|---|
| F1 a synced lease cannot prevent concurrent resume | accept | fork-by-default continuation, live takeover handshake, device ids, advisory marker only (6.3.5 and 6.3.6) |
| F2 Hermes `state.db` is canonical, not a cache | accept | store classification table (6.1); Hermes export plus backup-API copy in the archive; §5 corrected |
| F3 T4 over-promises durability | accept | T4 restated with a loss window; versioning; two copies before deletion; peer is not an introducer; restore drill |
| F4 hardlink-or-copy is not a capture protocol | accept | generations with size, hash and completion marker; APFS clone; hooks only enqueue (6.3.2) |
| F5 use Claude's stable project key | accept with change | `CLAUDE_CODE_PROJECT_DIR_NAME` needs a per-project `CLAUDE_CONFIG_DIR`, so it is a Phase 2 prototype; cwd-only rewrite; round-trip test |
| F6 secrets trust model overstated | accept | same-user model stated; backend interface (1Password, service account, age, none); Linux parity flagged (4.5) |
| F7 service scopes wrong granularity | accept | per-host, per-account-or-bot, fleet-coordinator; manual handover (4.6) |
| F8 continuity needs workspace state | accept with change | T3 split into three levels; work bundles; Phase 0 scans before deletion |
| F9 git does not make memory updates semantic | accept with change | lock-and-push, tombstones, ping on conflict; no observation pipeline (4.6.4, Q16) |
| F10 provider survey stale | accept | capability matrix re-verified 2026-10-19 (6.1); adapters pinned |
| F11 CASS already does multi-host search | accept with change | CASS spike first, licence question Q12, FTS5 kept as fallback (6.2, 6.3.4) |
| F12 Paseo presence is not orchestration parity | accept | adapter contract; DAG, claims and resume stay in `acp-dispatch`; herdr fallback; retirements moved to Phase 6 |
| F13 Paseo already has usage, attention, history | accept | 7.1 lists what 0.12.0 and registry plugins have; the plugin builds the delta (7.3) |
| F14 config ownership | accept | owned-key merge, never a symlinked `config.json`; profiles generated; versions pinned together |
| F15 CLI justified, general provisioner not | accept with change | v2 proposed a narrow `ade link`; djbclark then chose chezmoi outright (Q4), so `ade` keeps only doctor, clone, sessions, services; mise for runtimes |
| F16 overlay needs a contract | accept | `overlay.toml`: precedence, keyed merges, unknown keys fail; rename deferred (Q1) |
| F17 Linux and root of trust too late | accept | both in Phase 1; signed tags, pins, no curl-pipe; real Linux user as the gate |
| F18 retention must include derived copies | accept with change | 6.5: index permissions, redacted exports, lost-device procedure, deny-list from `operator.toml` |
| F19 cleanup before proving preservation | accept | phases reordered as gates; deletion is Phase 6 |
| F20 "no central node" too broad | accept | T4 names the accepted outside dependencies and claims only "no indispensable personal machine" |

Citation corrections: C10 (LiteFS) now says limited maintenance and single primary, which is
the thread's actual content<sup>[29](#C10)</sup>; C4 (claude-code issue 57920) is about a deleted worktree
path, so it now supports "create the target cwd before resuming" and the duplicate-id rule
cites the sessions page instead<sup>[4](#C1) [17](#C4)</sup>; C7 now cites OpenCode's v2 `session export` and
`session import` commands<sup>[25](#C49)</sup>; C20b carries the beta label; C23 says CASS does collect over
SSH. The prior-art document's lines on sops-nix, rclone bisync and "none sync" are superseded
by this section.

Missed alternatives the review raised, adopted: CASS (spike), Paseo's own usage and history
surfaces (build the delta), keeping Orca and herdr through the pilot, mise for runtimes,
git-annex `numcopies` for the cold tier, chezmoi as the named fallback. Dropped, with the
review's own reasoning: Mutagen and rclone bisync (pairwise), Perkeep (weight), clync
(Claude-only), Dolt, Turso Sync and sqlite-sync (must sit under the application), Litestream
and LiteFS (topology), the SDK `SessionStore` (only for launches ADE owns), Taildrive,
Superset, OpenChamber, Happy and Conductor (weaker independence or one-harness lock-in), Nix for
Macs, devbox, sops-nix and agenix (vps-primary only).

## Citation footnotes

1. <a id="C13"></a>C13 — copying or syncing a live SQLite file is a listed corruption path — How To Corrupt An SQLite Database File (reference; sqlite.org). <https://www.sqlite.org/howtocorrupt.html>
2. <a id="C14"></a>C14 — Syncthing users report constant conflicts on SQLite files — Syncthing forum thread (forum; syncthing.net). <https://forum.syncthing.net/t/sync-conflict-with-1-specific-sqlite-file-constantly/20836>
3. <a id="C42"></a>C42 — the online backup API copies a live database consistently — SQLite Online Backup API (reference; sqlite.org). <https://www.sqlite.org/backup.html>
4. <a id="C1"></a>C1 — transcript path derivation, `CLAUDE_CODE_PROJECT_DIR_NAME` with `CLAUDE_CONFIG_DIR` (v2.1.234+, launching shell only), `cleanupPeriodDays`, `--resume` lookup order and the "more than one other project" rule — Claude Code sessions (vendor docs; code.claude.com). <https://code.claude.com/docs/en/sessions>
5. <a id="C3"></a>C3 — moving a session to another computer needs the jsonl, side folder and path rewrites — Move a Claude Code session to another computer (guide; codonic.dev). <https://codonic.dev/guides/move-claude-code-session-to-another-computer>
6. <a id="C44"></a>C44 — sudo-secretspec authorizes the operator identity, not per-secret confidentiality among callers; client-family labels are correlation metadata — sudo-secretspec AI-GUIDANCE (repo docs; GitHub). <https://github.com/frdminc/sudo-secretspec/blob/sudo-main/sudo-secretspec/AI-GUIDANCE.md>
7. <a id="C15"></a>C15 — `chezmoi init --apply`, `promptStringOnce`, password-manager and age secrets — chezmoi setup user guide (project docs; chezmoi.io). <https://www.chezmoi.io/user-guide/setup/>
8. <a id="C52"></a>C52 — 0.11.0 Usage dialog, pinned summaries and plugin usage sources; 0.12.0 `paseo usage`, background workspaces, symlinked `config.json` fix, `agentProfiles` schema fix, parent-told-child-finished fix; Import session — Paseo CHANGELOG (repo; GitHub). <https://github.com/getpaseo/paseo/blob/main/CHANGELOG.md>
9. <a id="C56"></a>C56 — mise installs and pins runtimes (Python, Node, uv) per project and globally — mise dev tools (project docs; mise.jdx.dev). <https://mise.jdx.dev/dev-tools/>
10. <a id="C58"></a>C58 — `loginctl enable-linger` keeps user services running without a login session — loginctl (reference; freedesktop.org). <https://www.freedesktop.org/software/systemd/man/latest/loginctl.html>
11. <a id="C16"></a>C16 — nix-darwin plus home-manager pins the stack; casks still via Homebrew — Nixifying my dotfiles (blog, 2026-02; mattmichie.com). <https://mattmichie.com/2026/02/14/nixifying-my-dotfiles/>
12. <a id="C17"></a>C17 — public installer with optional private overlay clones and precedence — ithinkihaveacat/dotfiles (repo; GitHub). <https://github.com/ithinkihaveacat/dotfiles/>
13. <a id="C18"></a>C18 — fork the public repo, create an empty private one the scripts pull — romkatv/dotfiles-public (repo; GitHub). <https://github.com/romkatv/dotfiles-public>
14. <a id="C19"></a>C19 — Ansible bootstrap, age key from 1Password, encrypted private submodule — shanemcd/dotfiles (repo; GitHub). <https://github.com/shanemcd/dotfiles>
15. <a id="C45"></a>C45 — only one `getUpdates` consumer per bot token at a time — Telegram Bot API (vendor docs; telegram.org). <https://core.telegram.org/bots/api#getupdates>
16. <a id="C5"></a>C5 — `enabledPlugins` and `extraKnownMarketplaces` are the declarative state; install records hold absolute paths — Claude Code plugin loading (vendor docs; code.claude.com). <https://code.claude.com/docs/en/plugins/loading>
17. <a id="C4"></a>C4 — `claude --resume <id>` cannot find the transcript after the original worktree path is removed; recreating the directory fixes it — anthropics/claude-code issue 57920 (repo issue; GitHub). <https://github.com/anthropics/claude-code/issues/57920>
18. <a id="C2"></a>C2 — `SessionStore` mirror: transcripts only, best-effort, S3/Redis/Postgres adapters — Agent SDK session storage (vendor docs; code.claude.com). <https://code.claude.com/docs/en/agent-sdk/session-storage>
19. <a id="C8"></a>C8 — Codex rollouts under `~/.codex/sessions/YYYY/MM/DD` plus `session_index.jsonl` — Codex CLI sessions (guide; spawnd.dev). <https://spawnd.dev/codex-cli-sessions>
20. <a id="C50"></a>C50 — `codex resume`, `codex fork`, `exec resume`, `/import` from Claude Code and Cursor; remote connections continue a chat on its host — Codex changelog (vendor docs; developers.openai.com). <https://developers.openai.com/codex/changelog>
21. <a id="C51"></a>C51 — `state_5.sqlite` records `rollout_path` through symlinks, so copied rollouts rely on resume-by-id — openai/codex issue 51934 (repo issue; GitHub). <https://github.com/openai/codex/issues/51934>
22. <a id="C36"></a>C36 — Gemini CLI keys sessions by a project path hash — Gemini CLI session management (vendor docs; geminicli.com). <https://geminicli.com/docs/cli/session-management/>
23. <a id="C47"></a>C47 — `/export-session <path>` and `--session-file` shipped in v0.43.0 (2026-05-22) — Gemini CLI changelogs (vendor docs; geminicli.com). <https://geminicli.com/docs/changelogs/>
24. <a id="C48"></a>C48 — the session export and import implementation, merged 2026-05-08 — google-gemini/gemini-cli PR 26514 (repo PR; GitHub). <https://github.com/google-gemini/gemini-cli/pull/26514>
25. <a id="C49"></a>C49 — `opencode session export <id> [--sanitize]` and `session import <file|url> --directory` — OpenCode v2 CLI commands (vendor docs; opencode.ai). <https://dev.opencode.ai/v2/docs/cli/commands/>
26. <a id="C35"></a>C35 — Copilot CLI keeps session-state files and a session-store database; `/share`, `--remote-export`, `--remote --resume` — Copilot CLI config dir reference (vendor docs; docs.github.com). <https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference>
27. <a id="C41"></a>C41 — `~/.hermes/state.db` is the canonical store for all session messages; `hermes sessions export` writes full metadata and every message as JSONL, `--redact`; import restores archived history — Hermes sessions (vendor docs; nousresearch.com). <https://hermes-agent.nousresearch.com/docs/user-guide/sessions/>
28. <a id="C9"></a>C9 — Litestream streams one writer's WAL to object storage; replica is a restore target — How Litestream works (project docs; litestream.io). <https://litestream.io/how-it-works/>
29. <a id="C10"></a>C10 — "LiteFS hasn't been discontinued but we've refocused effort … limited updates" (Ben Johnson, 2025-01-28); single-primary design — Fly.io community thread (forum; fly.io). <https://community.fly.io/t/litefs-discontinued/23682>
30. <a id="C11"></a>C11 — cr-sqlite maintenance thin; a maintained fork is noted — vlcn-io/cr-sqlite issue 444 (repo issue; GitHub). <https://github.com/vlcn-io/cr-sqlite/issues/444>
31. <a id="C18b"></a>C18b — sqlite-sync, CRDT multi-writer extension, Elastic License — sqliteai/sqlite-sync (repo; GitHub). <https://github.com/sqliteai/sqlite-sync>
32. <a id="C12"></a>C12 — Dolt pushes to plain git remotes since 2026-02 — Announcing git remote support in Dolt (blog; dolthub.com). <https://www.dolthub.com/blog/2026-02-13-announcing-git-remote-support-in-dolt/>
33. <a id="C6"></a>C6 — git-based Claude session sync with UUID-tree merge and LFS; picks between divergent runs — Saturate/clync (repo; GitHub). <https://github.com/Saturate/clync>
34. <a id="C34"></a>C34 — git-annex is not a folder-mirroring system like Syncthing — git-annex "not" page (project docs; branchable.com). <https://git-annex.branchable.com/not/>
35. <a id="C57"></a>C57 — `numcopies` makes git-annex refuse to drop content until N copies verify — git-annex numcopies (project docs; branchable.com). <https://git-annex.branchable.com/git-annex-numcopies/>
36. <a id="C23"></a>C23 — remote sources over SSH/rsync with `cass sources setup|add|sync|doctor`, per-source provenance and path maps, 20+ agents, JSON API; MIT plus a rider granting no rights to Anthropic, OpenAI or anyone acting on their behalf — coding_agent_session_search (repo; GitHub). <https://github.com/Dicklesworthstone/coding_agent_session_search>
37. <a id="C40"></a>C40 — concurrent changes to one file are kept as a `.sync-conflict` copy, never refused; synchronisation is asynchronous — Understanding Synchronization (project docs; syncthing.net). <https://docs.syncthing.net/users/syncing.html>
38. <a id="C20b"></a>C20b — receive-encrypted folders on untrusted devices are beta / testing only; recovery needs the folder ID and the password — Syncthing untrusted device encryption (project docs; syncthing.net). <https://docs.syncthing.net/users/untrusted.html>
39. <a id="C21"></a>C21 — two-way low-latency sync over SSH with conflict policies — Mutagen synchronization (project docs; mutagen.io). <https://mutagen.io/documentation/synchronization>
40. <a id="C22"></a>C22 — Taildrive is an alpha WebDAV share, a mount not a sync — Taildrive (vendor docs; tailscale.com). <https://tailscale.com/docs/features/taildrive>
41. <a id="C43"></a>C43 — `SessionEnd` hooks receive `transcript_path`, run with a time limit, and do not run when the process is killed — Claude Code hooks (vendor docs; code.claude.com). <https://code.claude.com/docs/en/hooks>
42. <a id="C24"></a>C24 — `orca search` indexes transcripts across connected computers and paired servers — Orca CLI reference (vendor docs; onorca.dev). <https://www.onorca.dev/docs/cli/reference>
43. <a id="C46"></a>C46 — `git bundle` packages commits and refs into one file for transfer without a shared remote — git-bundle (reference; git-scm.com). <https://git-scm.com/docs/git-bundle>
44. <a id="C25"></a>C25 — markdown files plus SQLite index, MCP interface — basicmachines-co/basic-memory (repo; GitHub). <https://github.com/basicmachines-co/basic-memory>
45. <a id="C26"></a>C26 — clients connect over SSH, the encrypted relay, or Tailscale; mobile needs direct or relay — Paseo connectivity (vendor docs; paseo.sh). <https://paseo.sh/docs/connectivity>
46. <a id="C33"></a>C33 — what Paseo is: daemon, clients, providers, plugins, Apache-2.0 — Paseo llms.txt (vendor docs; paseo.sh). <https://paseo.sh/llms.txt>
47. <a id="C28"></a>C28 — agents launch, message and coordinate other agents across providers and machines; schedules and heartbeats — Paseo orchestration (vendor docs; paseo.sh). <https://paseo.sh/docs/orchestration>
48. <a id="C27"></a>C27 — plugin contributions: screens, panels, Command Center, slash commands, pills, timeline, themes, attachment sources, RPCs, usage sources, providers; trusted unsandboxed code — Paseo plugin quickstart (vendor docs; paseo.sh). <https://paseo.sh/docs/plugins>
49. <a id="C32"></a>C32 — `--host` targets any daemon (host:port, socket, ssh://, offer URL); plugin and project commands — Paseo CLI reference (vendor docs; paseo.sh). <https://paseo.sh/docs/cli>
50. <a id="C29"></a>C29 — Hub is the optional layer above daemons; self-hostable with an embedded database — Paseo Hub (vendor docs; paseo.sh). <https://paseo.sh/docs/hub>
51. <a id="C30"></a>C30 — official Docker image runs the daemon and web UI headless; state under `/home/paseo/.paseo` — Paseo Docker (vendor docs; paseo.sh). <https://paseo.sh/docs/docker>
52. <a id="C53"></a>C53 — workspaces from every connected host, ordered by attention; per-host state — Agents Dash List (plugin registry; paseo.sh). <https://paseo.sh/plugins/panrafal/agents-dash-list>
53. <a id="C54"></a>C54 — waiting questions, permissions and plan approvals, each summarised by an LLM (Haiku by default); child agents off by default — Herald (plugin registry; paseo.sh). <https://paseo.sh/plugins/gpambrozio/herald>
54. <a id="C55"></a>C55 — archived-conversation search for file-backed providers (Claude, Codex, omp, Pi) on that daemon — Agents History (plugin registry; paseo.sh). <https://paseo.sh/plugins/panrafal/agents-history>
55. <a id="C59"></a>C59 — provider entries accept per-provider `env` and a custom binary — Paseo custom providers (vendor docs; paseo.sh). <https://paseo.sh/docs/custom-providers.md>
56. <a id="C60"></a>C60 — agent profiles are saved per host; no export — Paseo agent profiles (vendor docs; paseo.sh). <https://paseo.sh/docs/agent-profiles.md>
57. <a id="C31"></a>C31 — the four orchestration skills install per host via Settings or `npx skills add getpaseo/paseo` — Paseo orchestration skills (vendor docs; paseo.sh). <https://paseo.sh/docs/skills>
