# ADE everywhere: one repo that recreates the whole agent environment on any machine

Proposal, version 2.3, 2026-10-19. Status: **decided**: all twenty-five questions answered
(section 9). v2.3 applies djbclark's round-3 answers (section 9.2), two of them against the
recommendation (Q20, Q22). Implementation starts with Phase 0.
v2.1 was reviewed the same day by Claude Fable 5.1
([ade-everywhere-v21-review-fable-2026-10-19.md](ade-everywhere-v21-review-fable-2026-10-19.md))
and Codex `gpt-6-astra`
([ade-everywhere-v21-review-codex-2026-10-19.md](ade-everywhere-v21-review-codex-2026-10-19.md));
this version applies their merged findings
([ade-everywhere-review-evaluation-v21-2026-10-19.md](ade-everywhere-review-evaluation-v21-2026-10-19.md),
section 12.2). Codex's review of version 1 (commit 8d1cad5,
[ade-everywhere-codex-review-2026-10-19.md](ade-everywhere-codex-review-2026-10-19.md)) and what
v2 changed in answer are in section 12.1. Evidence:
[ade-everywhere-inventory-2026-10-19.md](ade-everywhere-inventory-2026-10-19.md) (what exists
today, measured) and [ade-everywhere-prior-art-2026-10-19.md](ade-everywhere-prior-art-2026-10-19.md)
(web research; three of its lines are corrected in section 12). Citations are numbered
superscripts resolved under "Citation footnotes".

What v2.2 changed from v2.1: the companion is data, not a chezmoi "overlay" (chezmoi has one
source state), and an adoption snapshot stands in for the originals chezmoi never kept; storage
and plaintext work are split; CASS reads a native-shaped view at a pinned build; takeover becomes
a serialised transfer record and every generation carries a manifest; the Paseo route's real
contracts, the DAG's owner, a bootstrap stage zero and the Phase 1 product contracts are written
down. What v2.3 changed: vps-primary is a trusted peer that holds the key and runs the index
builds (Q18); `claude` and `codex` are shimmed so every launch honours a transfer (Q20); Homebrew
installs the standard way (Q22); the release matrix, key and name (Q24) and the generation budget
(Q25) are fixed.

## 1. Goal, restated as acceptance tests

The request: move the entire AI development environment into `djbclark-ade` (or have it
referenced from there), so that on a new machine, after cloning that one repo and telling an
agent "recreate my environment", djbclark can work on any project exactly as on any other
machine. Every past session of every TUI must be reachable from every machine. No central node
other than GitHub, Forgejo and the services on Hyades. Paseo becomes the universal front end.
Someone else must be able to use the public kit with their own private companion.

Written as tests the finished project must pass:

1. **T1 fresh machine.** On a clean Mac or Linux box with the stage-zero prerequisites (4.4): clone
   `djbclark-ade`, run one command (or paste one prompt into any agent), answer the interactive
   questions once (private repo URL, secret backend sign-in, vendor logins), and every tool,
   skill, hook, service, plugin and project checkout is present and `ade doctor` is green.
   Running it again changes nothing (idempotent). chezmoi keeps no originals<sup>[1](#C63)</sup>, so
   before the first apply `ade` snapshots every target it will manage (bytes, mode, symlink
   target, or a record that the path was absent), and `ade restore` puts them back.
2. **T2 any project.** `ade clone <project>` (or `--all`) puts every listed project at
   `~/src/<name>` with the right remotes, and the project's own agent wiring (graft, hooks, Tier 1
   pointer) works unchanged.
3. **T3 any session, at three levels.** From machine B, for a session that ran on machine A:
   (a) *readable*: `session-finder` finds it, live or ended, and shows it in full; (b) *native
   continuation*: for Claude Code and Codex it can be continued on B, as a fork by default, or
   in place after A has acknowledged a transfer (every launch, through the ADE shim, Q20); (c) *workspace*: the dirty or unpushed work the
   session left behind can be carried over with one command. Level (a) is required for every
   provider, (b) for Claude Code and Codex, (c) for git projects.
4. **T4 no indispensable machine, with a stated loss window.** Each workstation holds a full
   copy of the shared state, and so does the always-on peer, vps-primary. Losing any one device loses at
   most what no surviving device holds: the recovery point is the latest complete generation
   verified on a surviving device (minutes when online, longer when a laptop is asleep or
   offline), and `ade doctor` shows last-captured and last-replicated separately. Dirty or
   unpushed work is outside that window (Q21). Two retained copies
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
   work needs it; the gate is a real Linux user account that survives a reboot. None of it runs
   on the Mac except the Phase 1 gate's apply, reapply and restore on this Mac.

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
   SQLite database is a documented way to corrupt it<sup>[2](#C13) [3](#C14)</sup>; canonical SQLite stores are
   backed up with the online backup API or the vendor's export, never by file copy<sup>[4](#C42)</sup>.
3. **Same paths everywhere.** `~/src/<name>` for every project, the same login name on every
   machine where possible. Claude Code keys transcripts by the working directory and embeds
   absolute paths inside them<sup>[5](#C1) [6](#C3)</sup>; identical layouts avoid rewriting, and a Mac-to-Linux
   round trip (`/Users` to `/home`) is an acceptance test, not an assumption.
4. **Declare, then apply, then diff.** chezmoi owns every dotfile and config template (Q4): its
   source state says what exists, `chezmoi diff` shows the plan, `chezmoi apply` makes it so,
   with templates, prompt-once data and a password-manager hook; `ade doctor` compares the
   rest (services, tools, sessions). Hand-made symlinks are the bug class that produced today's
   five broken rules files.
5. **Secrets never touch git, and the trust model is stated.** `sudo-secretspec` grants secrets
   to the authorized operator identity, not per process<sup>[7](#C44)</sup>; 1Password is the default backend
   behind an interface that also admits `age` files or none (T6).
6. **Every workstation is a full peer, and so is the always-on peer.** Replication is
   peer-to-peer over the tailnet; vps-primary is a trusted peer that holds the key (Q18) and is
   not an introducer.
7. **Paseo is the front end, not the engine.** Headless dispatch keeps its tested engine
   (`acp-run`/`acp-dispatch`); Paseo gets visibility and control of it through its CLI, SDK and a
   plugin. It replaces herdr and Orca only after the pilot in T5 passes, and herdr stays as the
   plain-terminal fallback for TUIs Paseo cannot host.
8. **Flag before building.** Where this proposal would discard paid-for work (herdr plugins, Orca
   docs, the hub-era scripts), it asks first (section 9) and schedules the discard last
   (section 8).
9. **CI does the heavy lifting; the Mac stays responsive.** Every build, test suite and
   container run goes to CI first (GitHub runners for GitHub-sourced repos, Forgejo CI on Hyades
   when private work needs it). Index rebuilds need plaintext, so they run on vps-primary, a
   trusted host since Q18, off the Mac entirely (11.3). A local run goes through `bg` and never overlaps another
   heavy job (djbclark, 2026-10-19).

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
  AGENTS.md  CLAUDE.md -> AGENTS.md  README.md  LICENSE  .chezmoiroot (contains "home")
  home/                # the one chezmoi source state (Q4): every dotfile, per-TUI config template and rules link,
                       # with .chezmoi.toml.tmpl prompting once for the companion URL and operator data
  ade/                 # the ADE CLI (Python, uv): bootstrap, snapshot/restore, doctor, clone, sessions, services; it calls chezmoi, mise and Ansible
  manifest/
    tools.toml         # every external tool: source repo, install method per OS, version pin, PATH entry
    agents.toml        # every TUI: config dir, skills dir, commands dir, rules file, session store, store class, export and resume commands, and the ownership table (4.4)
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
  private-template/    # what `ade init-private` creates in a new companion repo: the TOML data files and an empty optional private source (4.4)
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
  agents/              # private per-TUI data the public templates read under the 4.4 contract
  home/                # optional second chezmoi source (Q11, Q19): personal shell, gradle; targets disjoint from the public set
```

Tier 1 chains are **not** in git: they are hot, written every session, and belong to the
session archive (section 6.3), where each host's copy is single-writer. Leaves:
`web/maynarddaycare` (a personal website, its own repo); `tailscale/` snapshots (into
`machines/`); `bin/`, `docs/`, `cursor`, `gradle`, `macos`, `prompts`, `shell`, `tests` symlink
shims (deleted once chezmoi owns every path); `.codex-runtime/` (Codex's own store; it stays
where Codex expects it, section 6.1).

### 4.4 Bootstrap: chezmoi plus a small `ade` CLI

djbclark chose chezmoi over a home-grown linker (Q4, 2026-10-19): chezmoi owns dotfiles and
templates from the start, and `ade` shrinks to what chezmoi does not do (bootstrap,
snapshot and restore, doctor, clone, sessions, services). Stage zero (below) comes first.

1. `ade bootstrap`: `ade snapshot` of every target the public state would manage, then
   `chezmoi init --apply <public repo>` with the `none` backend and no companion; its
   `.chezmoi.toml.tmpl` prompts once for the companion URL and operator data
   (`promptStringOnce`)<sup>[8](#C15)</sup>. Then `ade` clones the companion and applies
   again, snapshotting any newly managed target first. `chezmoi diff` is the plan and
   `chezmoi apply` is idempotent.
2. `ade install`: runtimes (uv, Python, Node) through `mise`, pinned in
   `packages.toml`<sup>[9](#C56)</sup>, so Node no longer comes from Hermes's private copy
   (inventory §5); packages per OS from `packages.toml`; external tools from `tools.toml`
   (pinned); agent CLIs from their vendors, with the `claude` and `codex` shims ahead of them
   on PATH (6.3.6). Where a `site-djbclark` Ansible role already
   installs something, `ade install` calls the role rather than re-implementing it.
3. `ade init-private <url>`: create the companion from `private-template/` on GitHub or
   Forgejo if it does not exist, clone it to the fixed path, and apply again.
4. `ade secrets`: sign in to the chosen backend, declare every secret from `secretspec.toml`
   into `sudo-secretspec`, run each vendor's login that cannot be scripted and say so.
5. `ade services`: generate launchd plists or systemd user units from `services.toml` with this
   machine's paths, honouring each service's scope and `machines/<host>.toml` (section 4.6); on
   Linux, `loginctl enable-linger` so user units survive logout<sup>[10](#C58)</sup>.
6. `ade clone --all`: every project from `projects.toml` to `~/src/<name>`.
7. `ade sessions join`: attach this machine to the session archive (section 6).
8. `ade doctor`: `chezmoi verify`, a diff of the manifest against reality (tools, services,
   session stores), the data-contract validation, the managed-set intersection check, and the
   deny-list grep for the operator's names in the public tree. Each check reports pass, fail,
   unsupported, disabled or untested.

The prompt for an agent is then one paragraph: "clone djbclark-ade, read AGENTS.md, run `ade
bootstrap`, answer its questions, run `ade doctor` until green". `docs/apply-toolchain-prompt.md`
stays as the per-repo toolchain prompt; it is not a machine bootstrap (inventory §4).

**Stage zero and the root of trust.** chezmoi must exist before `chezmoi init`, and a signed
tag from an unknown key proves nothing, so before step 1: (a) platform prerequisites (macOS
with the Command Line Tools, or a Linux account with git, a shell and sudo); (b) the release
key's fingerprint, given out of band, and a prompt naming the signed tag; (c) a chezmoi binary
whose cosign-signed checksums verify<sup>[11](#C72)</sup>; (d) Homebrew by its standard
installer, `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`,
trusting TLS to raw.githubusercontent.com<sup>[12](#C71)</sup> (Q22), distro packages on Linux; (e) companion and credentials only after the public-only apply passes.
`tools.toml` pins every external tool, with checksums for tarballs. A newcomer (T6) takes the
fingerprint from their fork's publisher and re-signs; djbclark's is a dedicated release key in
the secret backend (Q24).

**The companion is data, not an overlay.** chezmoi has one source state per config and errors
when two sources name one target (only directories coalesce)<sup>[13](#C61)</sup>; externals
install literal targets, not a second source state<sup>[14](#C62)</sup>. So (Q19):

1. The repo root's `.chezmoiroot` names `home/` as the single public source state.
2. `ade` clones the companion to a fixed path (today `~/ops/site-private`) before any apply
   that reads it.
3. Public templates read companion data through `stat`-guarded `include` and `fromToml`, so the
   public tree applies cleanly with no companion at all.
4. A private-only file is either a template output driven by that data, or lives in an
   optional second chezmoi instance (`--source` and `--config` on the companion's `home/`)
   restricted to targets the public state does not manage; `ade doctor` fails if the two
   `chezmoi managed` sets intersect.

The data contract, schema-versioned from Phase 1:

1. Precedence, lowest first: public defaults, `operator.toml`, `roles/<role>.toml`,
   `machines/<host>.toml`.
2. Tables merge by key; arrays of tables merge by a declared stable `id`, never by position.
3. A key is removed only by an explicit tombstone, never by omission.
4. An unknown key or a schema-version mismatch fails `ade doctor` and the apply.

**Adoption snapshot.** `chezmoi apply` overwrites existing dotfiles without warning and keeps
no journal<sup>[1](#C63)</sup>. Before each apply that adds targets, `ade snapshot` records
each new target `chezmoi managed` lists (bytes, mode, symlink target, or absence), privately
and outside git; `ade restore` puts them back, and the Phase 1 gate tests it.

**Ownership, per path and per key.** An ownership table in `agents.toml` says, per path,
whether chezmoi owns the file, a set of keys, or nothing. Files other tools also write
(`~/.claude/settings.json`, `~/.paseo/config.json`) get a `modify_` script, which is
read-modify-write<sup>[15](#C76)</sup> with no lock against the app's own writer: each merge is
idempotent and keeps unowned keys, and the apply quiesces the writer (stops the Paseo daemon)
or uses the app's interface. No shared config is a symlink; Paseo replaced a symlinked
`config.json` with a plain file until 0.12.0<sup>[16](#C52)</sup>. Ansible's package-only tasks
run from `ade install`; tasks that write HOME config move into chezmoi or stop touching its
paths.

**Why chezmoi, and not a home-grown linker, Nix or more Ansible.** v1 proposed its own
linker; the review (F15) noted that "one fewer config language" was a weak argument and
that ownership, adoption, diff and rollback are the costly parts. chezmoi has ownership and
diff, `ade snapshot` adds the adoption and rollback it lacks, and it brings templates, the prompt-once pattern and the password-manager
hook<sup>[8](#C15)</sup>, and the product framing (Q10) makes a well-known tool a better
answer for a newcomer than a bespoke one. The cost is a second owner of some files next to
Ansible, settled by the ownership table. Nix with
nix-darwin and home-manager gives the strongest pin at the highest cost, and still needs
Homebrew for casks<sup>[17](#C16)</sup>; vps-primary keeps its flake. The public/private split
follows the public-kit-plus-private-companion pattern, which works with no companion
present<sup>[18](#C17) [19](#C18)</sup>, with secrets pulled from the backend at apply time
rather than age-encrypted in git<sup>[20](#C19)</sup>.

### 4.5 Secrets and private data

1. **Trust model, stated.** `sudo-secretspec` authorizes the operator identity; every process
   running as that user that passes the boundary can read every declared secret, and the
   client-family labels are correlation metadata, not principals<sup>[7](#C44)</sup>. The design does not claim
   per-process confidentiality. Linux support for `sudo-secretspec` is unverified and is a
   Phase 1 task.
2. **Backends.** `secrets/backend.toml` names one of: `1password` (default on a laptop with the
   desktop app, the SSH agent included), `1password-service-account` (headless Linux and CI),
   `age` (a file in the companion, key held by the operator, as several dotfiles repos
   do<sup>[20](#C19)</sup>), or `none` (T6 minimum). `ade secrets` seeds `sudo-secretspec` from whichever is
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
   (two pollers on one bot token fight over `getUpdates`<sup>[21](#C45)</sup>), anything else holding a
   single-consumer credential. *Fleet-coordinator*, on vps-primary (a trusted host since Q18):
   fleet-watch, skillopt-night, the downstream session ingest and the index builds. `services.toml` carries the scope; `machines/<host>.toml` names the owner of
   each non-per-host service; other machines install them disabled. Handover is manual
   (disable here, enable there); there is no automatic failover, because a split brain costs
   more than a few hours without fleet-watch.
2. **Paseo schedules** are per daemon and never auto-enabled on every host by the companion data.
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
   `extraKnownMarketplaces`<sup>[22](#C5)</sup>; sync the settings keys, never the cache.
9. **Vendor OAuth tokens**: per machine by design.
## 6. Sessions everywhere

### 6.1 What the stores are, classified

The review's F10 showed v1's survey was stale; this table was re-verified on 2026-10-19 and
is the thing `agents.toml` encodes (adapters pinned to the version checked).

| Provider | Store | Class | Readable export | Lossless backup | Native resume | Import | Remote |
|---|---|---|---|---|---|---|---|
| Claude Code | jsonl per session under a path-derived dir<sup>[5](#C1)</sup> | canonical files | the jsonl itself | manifested generation (6.3) | `--resume`, `--continue`, `--fork-session`<sup>[23](#C68)</sup>; project dir can be named by `CLAUDE_CODE_PROJECT_DIR_NAME` with `CLAUDE_CONFIG_DIR`<sup>[5](#C1)</sup> | copy into the project dir (target cwd must exist<sup>[24](#C4)</sup>) | cloud sessions; SDK `SessionStore` mirror, best-effort<sup>[25](#C2)</sup> |
| Codex | rollouts under `~/.codex/sessions/YYYY/MM/DD` plus `session_index.jsonl` and `state_5.sqlite`<sup>[26](#C8)</sup>; here `~/.codex/sessions` is a symlink into `site-private`, which the collector follows | canonical files plus derived index | the rollout | copy after completion | `codex resume`, `codex fork`, `exec resume`<sup>[27](#C50)</sup>; the index records `rollout_path` through symlinks<sup>[28](#C51)</sup> | `/import` from Claude Code and Cursor<sup>[27](#C50)</sup>; no first-party rollout import | remote connections continue a chat on its host, do not move it<sup>[27](#C50)</sup> |
| Gemini CLI | path-hash keyed store<sup>[29](#C36)</sup> | canonical files | `/export-session <path>` (v0.43.0)<sup>[30](#C47) [31](#C48)</sup> | export | `--session-file`<sup>[30](#C47)</sup> | `--session-file` | none |
| OpenCode | `opencode.db` (SQLite) | canonical SQLite | `opencode session export <id> [--sanitize]`<sup>[32](#C49)</sup> | online backup API<sup>[4](#C42)</sup> plus export | yes | `opencode session import <file> --directory`<sup>[32](#C49)</sup> | none |
| Copilot CLI | session files plus a session-store database<sup>[33](#C35)</sup> | mixed | `/share file|html|gist`, `--remote-export`<sup>[33](#C35)</sup> | copy plus backup API | `--resume`, `--remote --resume` | none | account-bound |
| Cursor | SQLite | canonical SQLite | none verified (third-party exporters only) | backup API | `--resume`, `ls`, `resume` | none | `worker` (private cloud) |
| Hermes | `~/.hermes/state.db`, the canonical store of all session messages and routing<sup>[34](#C41)</sup> | canonical SQLite | `hermes sessions export` (JSONL, `--redact`), refused above `max_export_messages` stored rows (20,000)<sup>[34](#C41)</sup> | backup API (also the fallback for oversized sessions) plus nightly export | yes | import restores rows as archived history, not live context<sup>[34](#C41)</sup> | Telegram gateway |
| zcode, Crush | SQLite | canonical SQLite | third-party or none | backup API | yes | none | none |
| omp | JSONL under `~/.omp/agent/sessions` (checked locally) | canonical files | the JSONL | manifested generation | yes | none | none |
| Paseo | per-agent JSON under `~/.paseo/agents` | mixed: titles, parent links and labels exist only here | history search, Import session (Claude, Codex, omp)<sup>[16](#C52)</sup> | copy | n/a | yes | per-host history only |

The lesson of the table: "readable everywhere" (T3a) is achievable for every provider by
collecting the native files or a vendor export; "native continuation" (T3b) is a Claude Code
and Codex feature, with Gemini and OpenCode close behind; nothing moves a running session
between machines. Phase 0 inventories every installed store, including Cline, Qwen, Muse, Grok
and Antigravity, which this table does not yet cover.

### 6.2 Options considered for the shared store

| Option | Fits a laptop fleet with no primary? | Verdict |
|---|---|---|
| Replicate the SQLite stores (Litestream, LiteFS, cr-sqlite, sqlite-sync, Turso, rqlite) | No. Litestream streams one writer's WAL to object storage<sup>[35](#C9)</sup>; LiteFS is a single-primary design with limited maintenance<sup>[36](#C10)</sup>; cr-sqlite is thinly maintained<sup>[37](#C11)</sup>; sqlite-sync is new and Elastic-licensed<sup>[38](#C18b)</sup>; Turso and rqlite need a server or quorum. All of them must sit under the application, which we do not own for vendor stores. | Rejected on topology, not on project status. |
| Dolt with a git remote | Yes for tables, since Dolt now pushes to plain git remotes<sup>[39](#C12)</sup>, but it is a new engine for data that is files. | Not now; revisit if we want a git-hosted catalogue. |
| git for transcripts (clync-style UUID merge plus LFS)<sup>[40](#C6)</sup> | Append-only jsonl merges, but 10 GB and growing bloats history and LFS costs on GitHub; clync picks between divergent runs. | Rejected for transcripts; kept for memory and Tier 2 handoffs. |
| git-annex with Forgejo or Hyades as special remote | Not a folder mirror by its own account<sup>[41](#C34)</sup>, but its `numcopies` and preferred-content rules, with `mincopies` as the hard floor, are the "two copies before deletion" policy<sup>[42](#C57) [43](#C74)</sup>. | Adopted for the cold tier (Phase 5). |
| CASS (coding_agent_session_search) pulling over SSH | Already collects from remote hosts over SSH or rsync with per-source provenance and path maps, indexes twenty-plus agents, and has a JSON API<sup>[44](#C23)</sup>. Pull-based: an offline laptop's new sessions wait until it is back, but its mirrored history stays searchable. Licence has a rider excluding Anthropic, OpenAI and anyone acting for them; djbclark accepts it as inapplicable to this personal use (Q12). | **Adopted** as the index over a native-shaped view of the archive (6.3.4, Phase 2); the FTS5 index stays only as a fallback for a store CASS cannot read. |
| Syncthing over the tailnet | Peer-to-peer, no central node, fine for unique-named append-only files with one writer per file; concurrent writes to one file produce a `.sync-conflict` copy, never a refusal<sup>[45](#C40)</sup>; its untrusted-device encryption is beta<sup>[46](#C20b)</sup> and unused, since every peer here is trusted (Q18). | **Chosen** for the live tier; it is sync, not backup. |
| Mutagen, rclone bisync, rsync over Tailscale SSH | Pairwise, no ownership semantics<sup>[47](#C21)</sup>. | Fallback for a machine that cannot run Syncthing. |
| Taildrive | Alpha WebDAV mount, not sync<sup>[48](#C22)</sup>. | Rejected. |

### 6.3 Design

**Identity.** Every archived item is keyed by (provider, project slug, session id, device id,
generation). The device id is Syncthing's device ID, not the hostname (hostnames repeat and
change). A generation is one captured snapshot of a session plus a manifest listing every
object (transcript, sidecars) with hash, size, format version and parent generation. A marker
written last locally proves nothing elsewhere, because Syncthing pulls in `random` order by
default and other orders sort only within a batch<sup>[49](#C67)</sup>, so a receiver validates
the whole manifest before a generation becomes pullable or indexable. A later capture of a grown file is a new generation, and a rewrite (Claude's compaction, Codex's
fork) is detected by hash, not by size.

1. **The archive.** `~/ade-sessions/` is a Syncthing folder shared by every workstation. Layout:
   `<provider>/<device-id>/<project-slug>/<session-id>/<generation>.jsonl` plus sidecars
   (subagent dirs, file-history, Codex `session_index.jsonl` rows), and
   `<provider>/<device-id>/exports/` for the SQLite-backed TUIs (OpenCode and Gemini exports,
   Hermes `sessions export` JSONL nightly where the export limit allows, Cursor and zcode third-party exports) alongside a
   `.backup`-API copy of each canonical SQLite file taken by the collector, never a live copy.
   The `<device-id>` level is what makes every file single-writer. This tree is the record of
   history; no index reads it directly (6.3.4).
2. **The collector.** `ade sessions collect` (per-host, every few minutes, on wake, and
   enqueued by each TUI's end-of-session hook; Claude's `SessionEnd` hooks get 1.5 s by default,
   raisable to 60 s, so the hook only enqueues<sup>[50](#C43)</sup>) copies (APFS clone on Mac,
   plain copy elsewhere; never a hardlink, which shares the inode) new generations into this
   device's subtree, trims a partial last jsonl line, runs the exporters, and writes each
   generation's manifest. It never writes into another device's subtree. The existing `s1_*` ingesters and `session-finder`'s adapters become this collector.
3. **The peers.** Every workstation plus one always-on peer, vps-primary (Q2), a normal
   trusted Syncthing peer that receives plaintext over the encrypted transport and runs the
   index builds (Q18, 11.3). It is **not** an introducer (a compromised device must not be able
   to add devices to the others); device IDs are pinned per host. Each device's versioning type
   and retention are named in `machines/<host>.toml`. Syncthing versions only changes received from other devices, and is
   off by default<sup>[51](#C77)</sup>: a deletion on one workstation is recoverable from the
   others' version folders, but a local edit is never versioned on its own device. A
   restore-from-peer drill is part of Phase 3.
4. **The index.** CASS (Q12) cannot read the generation tree: `path_mappings` rewrite
   workspace paths only, the Claude connector takes a conversation's id from the relative path
   (every generation would be a new conversation), and structural connectors find nothing in
   wrapped layouts<sup>[52](#C64)</sup>. The indexing host, vps-primary (11.3), keeps a materialised view,
   `<device>/<native layout>`, one current file per session, plus the `.backup` SQLite copies
   via `OPENCODE_SQLITE_DB` and `HERMES_SQLITE_DB`<sup>[53](#C66)</sup>. CASS is pinned to a
   main commit with the #520 and #522 fixes, which v0.10.0 lacks<sup>[52](#C64) [54](#C65)</sup>
   (Q23); Phase 2 measures a full rebuild (wall time, RSS, bytes), and working-hours searches
   run with `--no-maintenance`. Only a store with no readable view falls back to
   `session-finder`'s FTS5 database (`history.v2.sqlite`) with a `device` column.
   `session-finder` keeps live sessions and file claims, which no archive can know, and fronts CASS's JSON API. Orca's cross-host
   `orca search`<sup>[55](#C24)</sup> is the retired equivalent.
5. **Continuation on another machine.** `ade sessions pull <id>` copies a Claude or Codex
   session's latest complete generation into this machine's native store at the path the local
   checkout implies, creates the checkout directory if absent<sup>[24](#C4)</sup>, rewrites only cwd fields
   when the home directory differs<sup>[6](#C3)</sup>, touches mtimes so the 30-day cleanup does not eat the
   copy<sup>[5](#C1)</sup>, and refuses if more than one other project dir already holds the id (Claude's
   lookup rule<sup>[5](#C1)</sup>). By default it **forks**: it stages the generation, then calls
   the provider's own fork (`claude --resume <id> --fork-session`<sup>[23](#C68)</sup>, `codex
   fork`<sup>[27](#C50)</sup>), so the continued session has a new id and two machines never
   write one session. Parentage (parent id, device, generation) goes in the archive sidecar,
   never into a native transcript.
6. **Exclusive takeover.** "Stopped at generation N" is an observation that two recipients
   can both hear, so `ade sessions pull --take <id>` asks the origin over Tailscale SSH for a
   serialised transfer: under a local lock its collector writes a transfer record (owner,
   epoch, recipient, transfer id, final generation), freezes its reaper and `acp-dispatch`'s
   auto-resume for that session, and acknowledges one recipient; later requests are refused,
   and the old origin never resumes a transferred id. The guarantee covers every launch (Q20):
   `ade install` puts thin `claude` and `codex` shims on PATH ahead of the vendor binaries. A
   shim parses nothing beyond `--resume`/`resume` and a session id, refuses a transferred id
   with the new owner's name, and otherwise `exec`s the vendor binary unchanged, so vendor
   updates pass through it. An unreachable origin means a fork (Q14). No file-based lease: a synced lease cannot exclude anything, because
   Syncthing reconciles after the fact<sup>[45](#C40)</sup>; `.lease` survives only as an
   advisory marker in `session-finder`.
7. **Workspace carry-over (T3c).** `ade sessions pull --with-work` fetches a work manifest the
   origin's collector builds on request: base commit and refs as a `git bundle`, which carries
   objects and refs only, not the worktree<sup>[56](#C46)</sup>; the staged and unstaged diffs
   kept apart, binary-safe; untracked files under a policy that excludes secrets and ignored
   paths; submodules and LFS objects listed, not carried. It restores into a fresh worktree and
   needs a live origin: a convenience, with a lost machine's dirty work outside the loss window
   (Q21, revisited after Phase 2).
8. **Tier 1 pointers.** `~/.local/state/handoffs` joins the archive the same way (per device)
   and `session-handoff` reads all devices; chain keys are already unique. Tier 2 handoffs stay
   in git.

### 6.4 Memory

Basic Memory stays: markdown in git plus a per-machine index<sup>[57](#C25)</sup>. The seven empty
`~/agent-memory/*` projects are removed or pointed into the companion. `hermes-memory` moves into
the companion. The SiYuan and `~/kb` stores are out of scope (section 5). Concurrency is the
lock-and-push rule of section 4.6.

### 6.5 Retention, privacy and the loss window

1. **Hot tier**: every peer keeps all generations for 30 days, then the latest per session
   plus every generation a fork or transfer record names, for a year (Q7, Q25; provisional
   until Phase 2 measures). **Cold tier**: git-annex with `numcopies 2` plus a `mincopies`
   floor, since `numcopies` alone can be breached by concurrent drops<sup>[42](#C57) [43](#C74)</sup>,
   across vps-primary and one Mac (Q7), in a `hybrid` or `pubkey` encrypted special remote whose
   key is in the secret backend, present on trusted hosts (Q18), never in git
   (`encryption=shared` keeps the cipher there<sup>[58](#C75)</sup>); `ade sessions archive`
   moves sessions older than a year and refuses to drop the hot copy until two annex copies
   verify.
2. **Copies are plaintext in more places than the archive**: the materialised view, the CASS or FTS5 index, Paseo's
   history, the Hermes export. Index files are mode 0600; exports used for sharing are made with
   `--redact` or `--sanitize`; full-fidelity copies never leave operator-owned devices (the
   Macs and vps-primary).
3. **Lost device**: remove its device ID from every peer, rotate any key it held, and
   accept that copies already on the device are not erased. Deletion scope is future access
   only unless djbclark asks for more (Q13).
4. **Loss window**: the recovery point is the latest complete generation verified on a
   surviving device; a lost device takes what it had not collected or not yet replicated (an
   offline laptop's day). `ade doctor` shows last-captured and last-replicated apart; Phase 3
   drills a lost origin; the operator accepts this (Q15) or lets sync finish before closing the lid.

## 7. Paseo as the universal front end

### 7.1 What Paseo is, in our terms, at 0.12.0

An Apache-2.0 daemon per machine plus desktop, web, mobile and CLI clients; clients attach to any
daemon over SSH, the optional encrypted relay, or directly over Tailscale (the phone needs the
tailnet or the relay)<sup>[59](#C26) [60](#C33)</sup>. Agents run where the daemon runs, with that machine's tools
and credentials; the daemon persists workspaces, agent metadata and schedules, and leaves
transcripts in each provider's store. Agents inside Paseo get MCP tools to create workspaces,
launch and message other agents across providers, and set schedules and heartbeats; those
tools act on their own host, and crossing hosts goes through the CLI<sup>[61](#C28) [62](#C70)</sup>. Plugins are trusted TypeScript installed per daemon and can add screens,
panels, Command Center items, slash commands, composer pills, timeline rows, themes,
attachment sources, daemon RPCs, usage sources and whole providers<sup>[63](#C27)</sup>. The CLI drives any
daemon with `--host`<sup>[64](#C32)</sup>; Hub is optional and self-hostable<sup>[65](#C29)</sup>; an official Docker image
runs the daemon headless, without the agent CLIs<sup>[66](#C30)</sup>.

What it already has that v1 proposed to build: a **Usage** dialog with pinned summaries and a
plugin usage-source API (0.11.0), `paseo usage` on the CLI (0.12.0), history search and
**Import session** for Claude, Codex and omp, background workspaces, and a fix for parents
being told a child finished when its task was stopped<sup>[16](#C52)</sup>. Registry plugins add a cross-host
workspace list ordered by attention (Agents Dash List)<sup>[67](#C53)</sup>, an LLM-summarised feed of waiting
questions and permissions (Herald)<sup>[68](#C54)</sup>, and archived-conversation search for file-backed
providers on that daemon (Agents History)<sup>[69](#C55)</sup>. Custom providers accept per-provider `env` and
a custom binary<sup>[70](#C59)</sup>; agent profiles are saved per host with no export command, though the SDK can read host
config<sup>[71](#C60)</sup>.

So the "no indispensable machine" test holds: one daemon per machine, clients add each host
over the tailnet, relay off, Hub not needed. Paseo does **not** sync sessions between daemons;
section 6 covers that.

### 7.2 Capability map: today's loop against Paseo

Nothing in the "Decision" column happens before the T5 pilot; "replace" means "replace once the
pilot has exercised it". "Owner" names who holds the capability after the pilot (Q5's
consequences).

| Today (herdr/Orca) | Paseo equivalent at 0.12.0 | Decision | Owner |
|---|---|---|---|
| herdr workspaces, tabs, panes as the place every session lives | Workspaces with agents, terminals, files, diffs, browser in split panes | Replace for Paseo-hosted agents; herdr stays as the plain-terminal fallback for any TUI Paseo cannot host. | Paseo; herdr for the rest |
| Orca worktrees, task DAG with crash recovery, `orca search` | Worktree isolation and orchestration tools; no DAG persistence, no file claims, no quota-reset resume | Worktrees: replace. The DAG is Orca's (README:206); `acp-dispatch` only launches, resumes after a quota stop and reaps. The DAG migrates with a replay proof in Phase 4, or Orca's orchestration stays. `orca search`: 6.3.4. | DAG: Orca until replayed; claims: `session-finder`; quota resume: `acp-dispatch` |
| `session-finder fleet.py` (which live session is where) | `paseo ls -a --host <h>` per host; Agents Dash List across hosts | Keep `fleet.py` as the aggregator over Paseo's CLI; keep its herdr adapter (herdr is the fallback); drop the Orca adapter with Orca. | `fleet.py` |
| `launch.py` starts a session over ACP in a visible pane | `create_agent` / `paseo run` with any provider, including the ACP catalog | Replace behind an adapter contract: idempotent start, question and permission response, cancel, report, resume. | `launch.py` over Paseo |
| `helm` answers every waiting session from one window | Herald (LLM-paraphrased items, child agents off by default); permission prompts per host; mobile approvals | Build the **Helm panel** as the delta: verbatim questions, request ids, ranking by work unlocked, one-tap relay, child agents included (section 7.3). | ADE plugin |
| `herdr-tidy` closes idle panes with a close ledger | `archive_workspace`; agents keep their transcripts | Replace with a plugin RPC that writes the same ledger. | ADE plugin |
| `herdr-sleeper`, `herdr-jump`, `herdr-ai` | Daemon manages idle agents; Command Center; chat | Retire after the pilot, not before (section 8, Phase 6). | Paseo daemon |
| `self-slash` types a slash command into a pane | `paseo wait`, then `paseo send` of a root-only built-in (`/clear`, `/compact`, `/context`, `/usage`) to the idle agent; sent with `PASEO_AGENT_ID` unset, because an agent-originated send is enveloped as text (0.12.0) | **Done 2026-10-19**: `self-slash` has a Paseo host (`/new` and `/reset` go as `/clear`); verified on a scratch agent. The context hook tells a Paseo-hosted session to compact and hand off itself. | ADE `bin/self-slash`; Paseo CLI |
| `autorename`, `herdr_place.py` | `rename_workspace`, agent title (`paseo agent update --name`) | Replace; keep the title derivation. Since 2026-10-19 `autorename` also sets the Paseo agent name. | Paseo; ADE title logic |
| `fleet-watch` pings Hermes on fleet changes | `notifyOnFinish`, push notifications to the phone app | Keep the Hermes ping for Telegram; feed it from Paseo events. | fleet-watch |
| `acp-run` / `acp-dispatch` / `bigteam` / `route_agent.py` headless dispatch | `paseo run --provider X --no-wait`, SDK (`agents.create`, `waitForFinish`, `send`), `paseo stop`, agent profiles | Keep the engine for job policy (routing, quota-stop resume, reports, `BLOCKED:`, escalation, calibration); Paseo runs the routed agent. `--via paseo` maps controls per the table below and refuses, before launch, any it cannot express; re-compare after the pilot (Q9). | `acp-run` (policy); Paseo (runtime) |
| `aiuse` quota probes and `route_agent.py` | Usage dialog, `paseo usage`, usage-source plugin API | Keep `aiuse` as the source of policy (disabled list, gates, pace); the plugin registers it as a usage source (section 11.4). | `aiuse` |
| `cow-pasture` APFS workspaces | Worktree isolation | Keep cow for non-git and Mac-only speed; Paseo worktrees are the portable default. | cow on Macs; Paseo |
| launchd jobs that run agents (skillopt-night) | Schedules and heartbeats | Move agent-shaped jobs to Paseo schedules on their owning host only; system jobs stay units. | Paseo; `ade services` |
| Hermes Telegram gateway | Paseo mobile app for approvals and chat | Keep both; Hermes is the always-on assistant, Paseo the workbench. | Hermes and Paseo |
| Skills linked into every TUI | Paseo installs its four skills on each host<sup>[72](#C31)</sup> | Unchanged; chezmoi owns the links, Paseo's managed-file manifest stays. | chezmoi; Paseo for its four |

The `--via paseo` route at 0.12.0, control by control<sup>[73](#C69)</sup>:

| acp-run control | Paseo flag / plugin / acp-run only |
|---|---|
| provider, model, effort | Paseo flag: `--provider`, `--model`, `--thinking`, `--mode` where the provider has one |
| named profile | resolved by ADE into explicit flags: `run` has no `--profile`, and the local `daemon` config has no `agentProfiles` key |
| report, `.done`, `BLOCKED:` | acp-run only; `--output-schema` is rejected together with `--no-wait` |
| context size, `--perm deny` and read-only, deadlines, inbox | acp-run only: the route refuses them before launch |
| parent edge | ADE keeps a host-qualified edge as a `--label`; `PASEO_AGENT_ID` resolves only on the target daemon |
| stop | `paseo stop`, result checked; closing the SDK client does not stop an agent |

A reconciliation state machine precedes Phase 4 code: host, agent id, native session id,
attempt and idempotency token persist before each retryable call, and an uncertain create or
send is reconciled, never retried blind.

### 7.3 The ADE Paseo plugin: the delta only

One plugin in `paseo-plugin/`, installed on every daemon by `ade install`, pinned to the daemon
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

1. **Phase 0, preserve and classify (days).** Inventory and classify every installed store
   per section 6.1; take a `.backup`-API copy of Hermes `state.db`, OpenCode, Cursor and zcode
   databases plus a Hermes JSONL export where `max_export_messages` allows; scan
   `~/.local/state/bigteam` and the Orca checkouts for unique reports, dirty trees, untracked
   files and unpushed commits and capture them; track the four untracked config files as
   templates. Fixing the five broken rules links waits for the adoption snapshot (4.4);
   classification and backups do not. Nothing is deleted.
2. **Phase 1, thin vertical slice (1 to 2 weeks).** The chezmoi source state under `home/`
   for Claude Code and Codex only: companion data through `stat`-guarded templates, the
   `modify_` merges under the ownership table, `ade snapshot` and `ade restore`;
   `manifest/*.toml` for the same two; `ade doctor`, `services`, `install` with mise and the
   package-only Ansible split; stage zero and the signed-tag root of trust; `private-template/`
   and `ade init-private` with an empty companion; the contracts this slice consumes (schema
   versions and namespaces, 4.4's precedence and deletion rules, signing with a dedicated
   release key in the secret backend, and the platform matrix, Q24): macOS arm64 and Linux
   x86_64. vps-primary is x86_64 (`uname -m`, Linux 6.18.56, checked locally 2026-10-19), so
   one Linux target covers it and GitHub's default runners; Linux arm64 is not in the first
   matrix.
   The first PR adds the GitHub Actions workflow (pytest plus the container smoke test) so
   every later PR is tested off the Mac; the companion test gets its own workflow on the
   private repo, moved to Forgejo CI if private work needs it. Gate: apply, reapply, restore and
   doctor pass on this Mac **and** on a real Linux user account that survives a reboot, with a
   Forgejo remote and the `none` secret backend (so T6 is tested before djbclark's own companion
   is); restore returns a pre-existing dotfile set exactly, modes, symlinks and absences included.
3. **Phase 2, sessions spike (1 week).** Stand up CASS at a pinned main commit over the
   materialised native view and the `.backup` copies (6.3.4), and measure a full rebuild (wall
   time, RSS, bytes); implement the capture protocol (manifested generations, APFS clone) for
   Claude Code and Codex; native fork; a cross-home resume test (Mac to Linux, `/Users` to
   `/home`); the transfer-record takeover and the `claude`/`codex` shims; the work manifest. Gate: a session started on A is
   read, forked and continued on B, and B's work comes back to A; the manifest survives
   marker-first arrival, a missing sidecar, truncation and compaction during capture; the work
   manifest carries an untracked file, a binary edit and a staged/unstaged split; a
   hand-typed resume of a transferred id is refused.
4. **Phase 3, sessions for everyone (1 to 2 weeks).** Syncthing folder with per-device
   versioning, vps-primary as a trusted peer (Q2, Q18), the restore-from-peer drill, every other
   provider's exporter, Tier 1 chains in the archive, `session-finder` over all devices,
   retention, the lost-device procedure and a lost-origin drill (6.5.4). Capture and export run
   on each origin; the index builds run on vps-primary, off the Mac entirely (Q18).
5. **Phase 4, Paseo pilot (2 to 3 weeks).** Owned-key config merge, profiles generated from
   `routing.toml`, the plugin (Helm panel first, then the usage source), `launch.py` and
   `fleet.py` over the adapter contract, `acp-dispatch --via paseo` after its state machine
   (7.2), and either the DAG's restart-and-replay proof or a decision to keep Orca's. Gate: the T5 pilot workflow
   (fan-out with questions, permissions, a quota stop and resume, a rollback) from desktop and
   phone, with Orca and herdr still installed as the fallback; the lead session, hosted by
   Paseo, compacts itself and hands off into a fresh session without the operator typing
   (the `self-slash` Paseo host, done 2026-10-19, 7.2).
6. **Phase 5, widen (1 to 2 weeks).** The remaining providers, services and memory into the
   manifest; the agent-service Ansible roles (Q3); cold tier with git-annex (encrypted special
   remote, `mincopies`); a second Mac from
   nothing with the one prompt; T1 to T5 pass on three machines.
7. **Phase 6, retire and delete (days).** Capability-map sign-off with both frontier reads
   (section 11); retire Orca and herdr's agent plugins (Q5); delete the scratch and duplicate
   stores whose preservation Phase 0 proved.
8. **Phase 7, product (2 to 3 weeks, can start after Phase 2).** djbclark chose full product
   framing (Q10); the contracts are Phase 1's, so this phase is the rest: schemas for the
   remaining manifests, a documented config surface, templates and docs written for an
   arbitrary operator, the newcomer walkthrough from a fresh account with no 1Password, no
   Hyades, no Mac and a Forgejo remote (Q17), changelog and release notes, and a
   dependency-notice and licence page. The repo is MIT, but CASS's rider does not pass to
   third parties, so the page names it. The distribution is `ade-kit` (Q24), since `ade` is
   taken on PyPI<sup>[74](#C73)</sup>; it ships for macOS arm64 and Linux x86_64. The optional features
   (sessions sync, cold tier, Hermes gateway) are documented as add-ons.

## 9. Decisions, with djbclark's answers (2026-10-19)

### 9.1 Rounds 1-2 (decided)

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
   **Decided: vps-primary.** **Superseded by Q18 (2026-10-19):** vps-primary is trusted.
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
   Note (v2.3): vps-primary now holds plaintext-capable keys (Q18), so the cold tier's "key off
   the peer" rule (G13) becomes "key in the secret backend, present on trusted hosts".
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
    pipelines<sup>[44](#C23)</sup>. Agents running on those vendors' models would be the ones invoking it.
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

### 9.2 Round 3 (decided)

Raised by the v2.1 reviews (12.2) and answered by djbclark on 2026-10-19; Q20 and Q22 go
against the recommendation. Already ruled, so not asked: `--via paseo` refuses what it cannot
express instead of falling back (7.2).

18. **Q18 Plaintext indexing host.** May one Linux host hold decrypted transcripts for
    indexing, or does it all stay on the Macs off-hours? Open: v2.1 gave plaintext work to a
    peer that held only ciphertext (G3). Options: (a) Macs only, via `bg`; (b) a new trusted Linux worker;
    (c) make vps-primary trusted, reversing Q2.
    **Recommended: (a)**: Q2 holds and no new host sees plaintext.
    **Decided: (c), reversing Q2.** vps-primary is trusted: it holds the key, receives plaintext
    over the encrypted transport and runs the index builds (risk 10.10).
19. **Q19 Companion delivery.** Template `include` plus an optional second chezmoi instance on
    disjoint paths, dropping "private overrides any public file"? Open: chezmoi cannot layer
    two source states (G1). Options: (a) data, templates and the second instance (4.4); (b) data
    and templates only; (c) a source tree composed by `ade` before each apply.
    **Recommended: (a)**: Q11's personal files keep chezmoi semantics, in that second instance.
    **Decided: (a)**: data, templates and an optional second instance on disjoint paths, which
    `ade doctor` checks.
20. **Q20 Takeover scope.** Same-id takeover for ADE-managed launches only, direct launches
    always forking? Open: no handshake sees a launch ADE never made (G5). Options: (a) yes;
    (b) also shim `claude` and `codex` to check the transfer record.
    **Recommended: (a)**: a shim around vendor CLIs breaks on their updates.
    **Decided: (b), against the recommendation**: `claude` and `codex` are shimmed, so every
    launch, hand-typed included, consults the transfer record (6.3.6, risk 10.11).
21. **Q21 Dirty work and the loss window.** Is a lost machine's dirty and unpushed work inside
    the window, or is `--with-work` a convenience needing a live origin? Open: an on-request
    bundle dies with its origin (G15). Options: (a) convenience only; (b) periodic work capture.
    **Recommended: (a)**, revisited after Phase 2: periodic capture of untracked files widens
    the secrets surface.
    **Decided: (a)**: a live-origin convenience; dirty work is outside the loss window;
    revisited after Phase 2.
22. **Q22 Fresh-Mac installer.** Homebrew's Apple-Silicon `.pkg` as the one sanctioned
    installer, or the curl-pipe as a documented exception? Open: Homebrew's default is a
    curl-pipe (G10). Options: (a) `.pkg` only, Intel Macs unsupported; (b) `.pkg` plus a
    checksum-pinned curl-pipe exception.
    **Recommended: (a)**: the fleet is Apple Silicon; the exception would be the one unverified step.
    **Decided, against the recommendation: the regular Homebrew curl-pipe install**, trusting the
    site's TLS certificate; no `.pkg` requirement, and the installer does not exclude Intel Macs (4.4).
23. **Q23 CASS build and view.** CASS from a pinned main commit, over a native-per-device view
    instead of the generation tree? Open: v0.10.0 lacks #520 and #522 (G4). Options: (a) yes;
    (b) wait for a release, FTS5 meanwhile.
    **Recommended: (a)**: the fixes exist and the generation tree stays the record.
    **Decided: (a)**: CASS from a pinned main commit over a native-per-device view; the
    generation tree is the record.
24. **Q24 Release boundary.** Which OS and architecture pairs does the first release promise,
    who holds the signing key, and what is the distribution name? Open: Phase 1 now consumes
    these (G11). Options: (a) macOS arm64 and Linux x86_64, a dedicated release key in the
    secret backend, `ade-kit`; (b) macOS arm64 only, the operator's own key, name later.
    **Recommended: (a)**: T1 and T7 test both, and a dedicated key rotates without touching
    the operator's identity.
    **Decided: (a)**: macOS arm64 and Linux x86_64, a dedicated release key in the secret
    backend, `ade-kit`. vps-primary is x86_64 (checked locally), so Linux arm64 is not in the
    first matrix (Phase 1).
25. **Q25 Generation budget.** What storage and transfer budget bounds a year of immutable
    generations? Open: full generations multiply storage (G4, Codex F8). Options: (a) all
    generations for 30 days, then the latest per session plus any a fork or transfer names;
    (b) all for the year; (c) a per-device byte cap, oldest pruned first.
    **Recommended: (a)**, provisional until Phase 2 measures: it keeps every point a fork names.
    **Decided: (a)**: all generations for 30 days, then the latest per session plus every
    generation a fork or transfer record names; provisional until Phase 2 measures (6.5.1).

## 10. Risks

1. **Transcript path coupling.** Claude Code's slug and embedded paths make Linux continuation
   of a Mac session a rewrite with known traps<sup>[6](#C3)</sup>; identical layouts remove most of it, the
   cwd-only rewrite and the Phase 2 round-trip test catch the rest. The
   `CLAUDE_CODE_PROJECT_DIR_NAME` route needs a per-project `CLAUDE_CONFIG_DIR` and is a
   prototype, not the default, until its effect on credentials, plugins and settings is
   measured<sup>[5](#C1)</sup>.
2. **Paseo moves fast.** 0.12.0 today; its published config schema wrongly rejected valid
   `agentProfiles` until 0.12.0<sup>[16](#C52)</sup>, and the plugin API is young. Mitigation: owned-key merges instead of symlinks, daemon, clients and
   plugin pinned together in `tools.toml`, the plugin kept small.
3. **Syncthing is sync, not backup.** Deletions propagate. Mitigation: per-device versioning, the cold tier's two-copy floor, the restore drill.
4. **Two machines editing memory** produce occasional git conflicts and, more quietly,
   semantically inconsistent facts that merged cleanly. Mitigation: lock-and-push, tombstones,
   a ping on conflict, and a periodic consistency pass by an agent.
5. **The ops-suite policy** (stayturgid, three AGENTS.md slices) assumes `site-private`; the
   rename, when it comes, must keep that contract or update all three files in one commit.
6. **Discarding paid-for work** (herdr plugins, Orca integration) is a loss if Paseo turns out
   worse at something; the phase order retires nothing until the pilot has run the real
   workflow, and keeps herdr regardless.
7. **CASS's licence** may exclude the agents that would run it (Q12), and the fixes it needs
   are on main only (Q23); the FTS5 path is kept ready.
8. **Quota.** The work itself competes with everything else for the Claude weekly window
   (section 11); the plan spends the near-full Gemini pool on research and bulk first.
9. **Mac load.** Container tests, index rebuilds and parallel agent fan-outs would make the
   workstation unusable. Mitigation: section 11.3; every PR is tested in CI before any local
   run, and index builds run on vps-primary (Q18).
10. **A vps-primary compromise exposes every session**, since Q18 gives it plaintext and the
    keys. Mitigation: full-disk encryption, keys in the secret backend, pinned Syncthing device
    IDs with no introducer, and an audit of who can ssh in.
11. **The `claude`/`codex` shim breaks on a vendor flag change** (Q20). Mitigation: it parses
    only `--resume`/`resume` and session ids and passes everything else through; `ade doctor`
    checks the shim still resolves first on PATH and reaches the vendor binary.

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
| every phase gate | frontier review, advise only | codex `gpt-6-astra` | high | default | Codex weekly 100% | the review that found F1 and F2; one per gate |
| every phase gate | second frontier read | claude `fable` 5.1 | high | 200k | Fable 68% | independent of Codex; `xhigh` only with a yes for that run |
| every phase | lead, design, integration, decisions | claude `opus` 5.5 | high | 200k | Claude weekly 51% | the session that owns the plan and the merges |
| every PR | security review | `adversary` agent (Claude) | high | 200k | Claude weekly | required before any PR (home rules item 28) |
| 0 hygiene | link fixes, config templating, duplicate resolution | cursor `auto` | low | default | Cursor auto 70% | mechanical, file-scoped, cheap |
| 0 hygiene | privacy sweep of `docs/handoffs`, `queue.md` | agy `gemini-3.8-flash` | medium | default | Gemini 96% | read-heavy, no judgment needed beyond a list |
| 0 inventory | provider and tool survey refresh, every installed store (F10, G16) | agy `gemini-4-argon` | high | default | argon weekly 100% | research with many sources; cheapest fresh pool |
| 1 manifest and `ade` CLI | manifest rows from the inventory | agy `gemini-3.8-flash` | low | default | Gemini 96% | bulk transcription with a schema |
| 1 manifest and `ade` CLI | chezmoi source state, `modify_` merges, companion data templates, snapshot and restore | claude `sonnet` 5.5 | high | 200k | Claude weekly 51% | templates and merge scripts against real config files; chezmoi docs re-read per slice |
| 1 manifest and `ade` CLI | `ade doctor`, `ade services`, `ade install` (Python, uv) | claude `sonnet` 5.5 | high | 200k | Claude weekly 51% | code that must be right first time; tests included |
| 1 manifest and `ade` CLI | stage zero and root of trust: signed bootstrap, cosign, pinned tool versions | claude `opus` 5.5 then codex gate | high | 200k | Claude, Codex | security design, then an outside read |
| 1 manifest and `ade` CLI | Linux container CI (T7) | claude `sonnet` 5.5 | medium | 200k | Claude weekly | small, iterative on GitHub runners |
| 1 private companion | `private-template/`, `ade init-private`, newcomer trial | claude `sonnet` 5.5 | high | 200k | Claude weekly | code plus the empty-companion test |
| 1 contracts | schemas, precedence and deletion rules, signing, platform matrix | claude `sonnet` 5.5 | high | 200k | Claude weekly | schema work needs exactness |
| 2 sessions spike | identity model, generation manifests, transfer record and shims (§6) | claude `opus` 5.5, codex gate | high | 200k | Claude, Codex | the blocker findings live here |
| 2 sessions spike | CASS at a pinned commit, materialised view, rebuild measurement | claude `sonnet` 5.5 | high | 200k | Claude weekly | Rust tool, our view; the index runs on vps-primary (11.3) |
| 3 sessions | collector over every adapter (`s1_*`, session-finder) | claude `sonnet` 5.5 | high | **1M** | Claude weekly | the one whole-archive refactor; budget it as several ordinary slices |
| 3 sessions | per-store exporters (OpenCode, Cursor, zcode, Hermes) | zai `GLM-5.3` | high | default | z.ai 36% | isolated modules with a fixed contract |
| 3 sessions | Syncthing units, vps-primary as a trusted peer, two-machine trial | claude `sonnet` 5.5 | high | 200k | Claude weekly | ops plus a real trial on two hosts |
| 3 sessions | SQLite backup checks and exporter research | grok `grok-4.7` | high | 256k | Grok 59% | realtime web plus repo reading |
| 4 Paseo delta | ADE plugin (Helm panel, dispatch rows, session panel) | claude `sonnet` 5.5 | high | 200k | Claude weekly | TypeScript against a moving API; re-read `llms.txt` each slice |
| 4 Paseo delta | `launch.py`, `fleet.py`, `acp-dispatch --via paseo` | claude `sonnet` 5.5 | high | 200k | Claude weekly | touches the dispatch engine; tests first |
| 4 Paseo delta | profile and provider catalog entries | cursor `auto` | low | default | Cursor auto | mechanical JSON |
| 5 second machine | bootstrap a Linux box and a second Mac | claude `opus` 5.5 (driving `ade`) | high | 200k | Claude weekly | judgment under failure; fixes go back as Sonnet slices |
| 6 retire and clean | capability-map sign-off, retire Orca and herdr plugins | claude `opus` 5.5, then both gates | high | 200k | Claude, Codex, Fable | the irreversible step gets both frontier reads |
| 7 product | remaining schemas, licence and notice page, release notes | claude `sonnet` 5.5 | medium | 200k | Claude weekly | the contracts already exist (Phase 1) |
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
| capture and export (collector, Hermes `.backup` and export, exporters) | the origin device, always | the native store exists only there; Hermes and its `state.db` live on the Mac |
| archive storage, its Syncthing scan and plaintext indexing (materialised view, CASS or FTS5 builds) | vps-primary, a trusted host since Q18, off the Mac entirely | 10 GB of small files; it holds plaintext (risk 10.10) |
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

## 12. Responses to the reviews

### 12.1 Codex review of v1 (twenty findings)

The review (gpt-6-astra, 2026-10-19) made twenty findings; each was re-verified against its
primary source by an Opus sub-agent before this version was written. All twenty are accepted,
six with a change of remedy. The table says what moved.

| Finding | Decision | What changed in v2 |
|---|---|---|
| F1 a synced lease cannot prevent concurrent resume | accept | fork-by-default continuation, live takeover handshake, device ids, advisory marker only (6.3.5 and 6.3.6) |
| F2 Hermes `state.db` is canonical, not a cache | accept | store classification table (6.1); Hermes export plus backup-API copy in the archive; §5 corrected |
| F3 T4 over-promises durability | accept | T4 restated with a loss window; versioning; two copies before deletion; peer is not an introducer; restore drill |
| F4 hardlink-or-copy is not a capture protocol | accept | generations with size, hash and completion marker (manifests in v2.2); APFS clone; hooks only enqueue (6.3.2) |
| F5 use Claude's stable project key | accept with change | `CLAUDE_CODE_PROJECT_DIR_NAME` needs a per-project `CLAUDE_CONFIG_DIR`, so it is a Phase 2 prototype; cwd-only rewrite; round-trip test |
| F6 secrets trust model overstated | accept | same-user model stated; backend interface (1Password, service account, age, none); Linux parity flagged (4.5) |
| F7 service scopes wrong granularity | accept | per-host, per-account-or-bot, fleet-coordinator; manual handover (4.6) |
| F8 continuity needs workspace state | accept with change | T3 split into three levels; work bundles; Phase 0 scans before deletion |
| F9 git does not make memory updates semantic | accept with change | lock-and-push, tombstones, ping on conflict; no observation pipeline (4.6.4, Q16) |
| F10 provider survey stale | accept | capability matrix re-verified 2026-10-19 (6.1); adapters pinned |
| F11 CASS already does multi-host search | accept with change | CASS spike first, licence question Q12, FTS5 kept as fallback (6.2, 6.3.4) |
| F12 Paseo presence is not orchestration parity | accept | adapter contract; herdr fallback; retirements moved to Phase 6; v2 put the DAG in `acp-dispatch`, v2.2 gives it to Orca until replayed (7.2) |
| F13 Paseo already has usage, attention, history | accept | 7.1 lists what 0.12.0 and registry plugins have; the plugin builds the delta (7.3) |
| F14 config ownership | accept | owned-key merge, never a symlinked `config.json`; profiles generated; versions pinned together |
| F15 CLI justified, general provisioner not | accept with change | v2 proposed a narrow home-grown linker; djbclark then chose chezmoi outright (Q4), so `ade` keeps only doctor, clone, sessions, services; mise for runtimes |
| F16 companion needs a contract | accept | v2 named a contract file it never defined; v2.2 writes the contract out (4.4): precedence, keyed merges, tombstones, unknown keys fail; rename deferred (Q1) |
| F17 Linux and root of trust too late | accept | both in Phase 1; signed tags, pins (stage zero in v2.2; Homebrew's curl-pipe allowed by Q22 in v2.3); real Linux user as the gate |
| F18 retention must include derived copies | accept with change | 6.5: index permissions, redacted exports, lost-device procedure, deny-list from `operator.toml` |
| F19 cleanup before proving preservation | accept | phases reordered as gates; deletion is Phase 6 |
| F20 "no central node" too broad | accept | T4 names the accepted outside dependencies and claims only "no indispensable personal machine" |

Citation corrections in v2: C10 (LiteFS) says limited maintenance and single
primary<sup>[36](#C10)</sup>; C4 supports "create the target cwd before resuming", and the
duplicate-id rule cites the sessions page<sup>[5](#C1) [24](#C4)</sup>; C7 became OpenCode's v2
`session export` and `import`<sup>[32](#C49)</sup>; C20b carries the beta label; C23 says CASS
collects over SSH. The prior-art document's lines on sops-nix, rclone bisync and "none sync"
are superseded.

Missed alternatives adopted: CASS, Paseo's usage and history surfaces, Orca and herdr through
the pilot, mise, git-annex `numcopies`, and chezmoi (a fallback in v2, adopted under Q4).
Dropped, with the review's reasoning: Mutagen and rclone bisync (pairwise), Perkeep (weight), clync
(Claude-only), Dolt, Turso Sync and sqlite-sync (must sit under the application), Litestream
and LiteFS (topology), the SDK `SessionStore` (only for launches ADE owns), Taildrive,
Superset, OpenChamber, Happy and Conductor (weaker independence or one-harness lock-in), Nix for
Macs, devbox, sops-nix and agenix (vps-primary only).

### 12.2 Fable 5.1 and Codex reviews of v2.1 (seventeen merged findings)

Neither reviewer overturns a decision; every claim was checked at its source (the v21
evaluation file).

| G | Severity | Reviewers (Fable / Codex) | Verdict | What v2.2 changed (section) |
|---|---|---|---|---|
| G1 no chezmoi overlay | blocker | F1 / F2 | accept with change | companion as data plus a disjoint second instance; data contract (4.2-4.4, Q19) |
| G2 no originals kept | blocker | F4 / F1 | accept | adoption snapshot, `ade restore`, restore test (T1, 4.4, Phases 0-1) |
| G3 plaintext on the blind peer | blocker | F2 / F9 | accept | three kinds of work split (principle 9, 6.3.3, 11.3, Phase 3, Q18); superseded by Q18 in v2.3 |
| G4 CASS input and build | major | F3 / F7, F8 | accept with change | materialised view, pinned commit, rebuild measured (6.3.4, Phase 2, Q23, Q25) |
| G5 takeover not exclusive | major | F10g in part / F5 | accept | serialised transfer record, ADE-managed only (T3, 6.3.6, Q20); v2.3 shims `claude` and `codex`, so it covers every launch |
| G6 completion marker | major | none / F6 | accept | per-generation manifest; arrival tests (6.3, Phase 2) |
| G7 fork natively | major | F7 / Q6 row | accept | `--fork-session`, `codex fork`, sidecar parentage (6.1, 6.3.5) |
| G8 Paseo route contracts | major | F5, F12 / F12 | accept with change | control table, refusal before launch, state machine (7.1, 7.2) |
| G9 the DAG is Orca's | major | none / F15 | accept | owner column; herdr adapter kept (7.2, Phase 4) |
| G10 bootstrap stage zero | major | F6 / F3 | accept with change | stage-zero contract (T1, 4.4, Q22); installer: curl-pipe by ruling |
| G11 contracts too late | major | F9 / F16 | accept with change | contracts in Phase 1; `doctor` states; licence page (4.4, 8, Q24) |
| G12 loss window | major | none / F10 | accept | recovery point restated; lost-origin drill (T4, 6.5.4, Phase 3) |
| G13 cold tier | major | F10a / F11 | accept | encrypted remote, `mincopies`, per-device versioning (6.2, 6.3.3, 6.5.1); superseded by Q18 in v2.3 |
| G14 `modify_` and HOME ownership | major | none / F4 | accept with change | ownership table; writer quiesced; Ansible split (4.4, Phase 1) |
| G15 work bundle | major | none / F13 | accept | work manifest and tests (6.3.7, Phase 2, Q21) |
| G16 store table gaps | major | F10e, F10f / F14 | accept | Hermes limit, omp, Paseo, Codex symlink, inventory (6.1, Phase 0) |
| G17 stale text | minor | F8, F12 / F17 | accept | linker command, 11.2 labels, T7, offline search, Paseo schema, cross-host MCP, C4 (passim) |

Refuted or mislabelled, for readers of the Fable review:

1. "`codex fork` not found" (F11): codex-cli 0.163.0 lists it<sup>[27](#C50)</sup>.
2. "CASS #466 is open" (F3): closed 2026-10-03, fixed in v0.9.0<sup>[75](#C78)</sup>.
3. "256 KiB chunks" (F3): main only; v0.10.0 captures a transcript under 8 MiB whole<sup>[54](#C65)</sup>.
4. "No effort equivalent" (F5): `run` has `--model`, `--thinking`, `--mode`<sup>[73](#C69)</sup>.
5. Its citation ids and Q-numbers follow another draft ("C49", "C58"; chezmoi is Q4, CASS Q12).

Citation corrections (id: old claim, corrected claim):

1. C4: a vendor rule; a missing cwd on 2.1.138, closed not planned, so a precondition.
2. C15: overlay precedence and kept originals; only init templates and `promptStringOnce`.
3. C52: "schema changed"; 0.12.0 fixed a published schema that rejected valid data.
4. C41: every message exported; refused above `max_export_messages` (20,000).
5. C57: a strict floor; that is `mincopies` (C74).
6. C23: offline laptop unsearchable, OpenCode via `.opencode/`; mirrored history searchable,
   `opencode.db` and `state.db` native.
7. C43: skipped on a kill (not on the page, dropped); 1.5 s budget, raisable to 60 s.
8. C46: bundle plus patch is the dirty tree; refs and objects only.
9. C28: agents coordinate across hosts; only the CLI crosses hosts.
10. C30: the image runs the daemon; without the agent CLIs.
11. C60: no export; no export command, but the SDK reads host config (unchecked).
12. Fable "C49", "T1", "C58": now chezmoi #3131, discussion 4657 and Homebrew's install page<sup>[13](#C61) [1](#C63) [12](#C71)</sup>.

## Citation footnotes

1. <a id="C63"></a>C63 — apply "should continue to overwrite dotfiles without any warning"; no originals kept — chezmoi discussion 4657 (GitHub). <https://github.com/twpayne/chezmoi/discussions/4657>
2. <a id="C13"></a>C13 — copying or syncing a live SQLite file is a listed corruption path — How To Corrupt An SQLite Database File (reference; sqlite.org). <https://www.sqlite.org/howtocorrupt.html>
3. <a id="C14"></a>C14 — Syncthing users report constant conflicts on SQLite files — Syncthing forum thread (forum; syncthing.net). <https://forum.syncthing.net/t/sync-conflict-with-1-specific-sqlite-file-constantly/20836>
4. <a id="C42"></a>C42 — the online backup API copies a live database consistently — SQLite Online Backup API (reference; sqlite.org). <https://www.sqlite.org/backup.html>
5. <a id="C1"></a>C1 — transcript path derivation, `CLAUDE_CODE_PROJECT_DIR_NAME` with `CLAUDE_CONFIG_DIR` (v2.1.234+, launching shell only), `cleanupPeriodDays`, `--resume` lookup order and the "more than one other project" rule — Claude Code sessions (vendor docs; code.claude.com). <https://code.claude.com/docs/en/sessions>
6. <a id="C3"></a>C3 — moving a session to another computer needs the jsonl, side folder and path rewrites — Move a Claude Code session to another computer (guide; codonic.dev). <https://codonic.dev/guides/move-claude-code-session-to-another-computer>
7. <a id="C44"></a>C44 — sudo-secretspec authorizes the operator identity, not per-secret confidentiality among callers; client-family labels are correlation metadata — sudo-secretspec AI-GUIDANCE (repo docs; GitHub). <https://github.com/frdminc/sudo-secretspec/blob/sudo-main/sudo-secretspec/AI-GUIDANCE.md>
8. <a id="C15"></a>C15 — `chezmoi init --apply`, `promptStringOnce`, password-manager and age secrets — chezmoi setup user guide (project docs; chezmoi.io). <https://www.chezmoi.io/user-guide/setup/>
9. <a id="C56"></a>C56 — mise installs and pins runtimes (Python, Node, uv) per project and globally — mise dev tools (project docs; mise.jdx.dev). <https://mise.jdx.dev/dev-tools/>
10. <a id="C58"></a>C58 — `loginctl enable-linger` keeps user services running without a login session — loginctl (reference; freedesktop.org). <https://www.freedesktop.org/software/systemd/man/latest/loginctl.html>
11. <a id="C72"></a>C72 — release checksums are cosign-signed — Install chezmoi (chezmoi.io). <https://www.chezmoi.io/install/>
12. <a id="C71"></a>C71 — the documented install is a curl-pipe of `install.sh` from raw.githubusercontent.com — Homebrew installation (brew.sh). <https://docs.brew.sh/Installation>
13. <a id="C61"></a>C61 — two sources for one target are an inconsistent-state error; only directories coalesce — chezmoi issue 3131 (GitHub). <https://github.com/twpayne/chezmoi/issues/3131>
14. <a id="C62"></a>C62 — externals name targets; archive members land as literal names; `git-repo` externals are plain clones — .chezmoiexternal format (chezmoi.io). <https://www.chezmoi.io/reference/special-files/chezmoiexternal-format/>
15. <a id="C76"></a>C76 — `modify_` scripts get the current contents and write new contents — Manage different types of file (chezmoi.io). <https://www.chezmoi.io/user-guide/manage-different-types-of-file/>
16. <a id="C52"></a>C52 — 0.11.0 Usage dialog and plugin usage sources; 0.12.0 `paseo usage`, background workspaces, symlinked `config.json` fix, fix to a published schema that wrongly rejected valid `agentProfiles`, parent-told-child-finished fix; Import session — Paseo CHANGELOG at v0.12.0 (GitHub). <https://github.com/getpaseo/paseo/blob/v0.12.0/CHANGELOG.md>
17. <a id="C16"></a>C16 — nix-darwin plus home-manager pins the stack; casks still via Homebrew — Nixifying my dotfiles (blog, 2026-02; mattmichie.com). <https://mattmichie.com/2026/02/14/nixifying-my-dotfiles/>
18. <a id="C17"></a>C17 — public installer with optional private overlay clones and precedence — ithinkihaveacat/dotfiles (repo; GitHub). <https://github.com/ithinkihaveacat/dotfiles/>
19. <a id="C18"></a>C18 — fork the public repo, create an empty private one the scripts pull — romkatv/dotfiles-public (repo; GitHub). <https://github.com/romkatv/dotfiles-public>
20. <a id="C19"></a>C19 — Ansible bootstrap, age key from 1Password, encrypted private submodule — shanemcd/dotfiles (repo; GitHub). <https://github.com/shanemcd/dotfiles>
21. <a id="C45"></a>C45 — only one `getUpdates` consumer per bot token at a time — Telegram Bot API (vendor docs; telegram.org). <https://core.telegram.org/bots/api#getupdates>
22. <a id="C5"></a>C5 — `enabledPlugins` and `extraKnownMarketplaces` are the declarative state; install records hold absolute paths — Claude Code plugin loading (vendor docs; code.claude.com). <https://code.claude.com/docs/en/plugins/loading>
23. <a id="C68"></a>C68 — `--resume <id> --fork-session` continues under a new id — Claude Code CLI reference (code.claude.com). <https://code.claude.com/docs/en/cli-reference>
24. <a id="C4"></a>C4 — `claude --resume <id>` fails when the session's cwd is missing (2.1.138); closed not planned 2026-06-09, so recreating the directory is a precondition — anthropics/claude-code issue 57920 (repo issue; GitHub). <https://github.com/anthropics/claude-code/issues/57920>
25. <a id="C2"></a>C2 — `SessionStore` mirror: transcripts only, best-effort, S3/Redis/Postgres adapters — Agent SDK session storage (vendor docs; code.claude.com). <https://code.claude.com/docs/en/agent-sdk/session-storage>
26. <a id="C8"></a>C8 — Codex rollouts under `~/.codex/sessions/YYYY/MM/DD` plus `session_index.jsonl` — Codex CLI sessions (guide; spawnd.dev). <https://spawnd.dev/codex-cli-sessions>
27. <a id="C50"></a>C50 — `codex resume`, `codex fork`, `exec resume`, `/import` from Claude Code and Cursor; remote connections continue a chat on its host — Codex changelog (vendor docs; developers.openai.com). <https://developers.openai.com/codex/changelog>
28. <a id="C51"></a>C51 — `state_5.sqlite` records `rollout_path` through symlinks, so copied rollouts rely on resume-by-id — openai/codex issue 51934 (repo issue; GitHub). <https://github.com/openai/codex/issues/51934>
29. <a id="C36"></a>C36 — Gemini CLI keys sessions by a project path hash — Gemini CLI session management (vendor docs; geminicli.com). <https://geminicli.com/docs/cli/session-management/>
30. <a id="C47"></a>C47 — `/export-session <path>` and `--session-file` shipped in v0.43.0 (2026-05-22) — Gemini CLI changelogs (vendor docs; geminicli.com). <https://geminicli.com/docs/changelogs/>
31. <a id="C48"></a>C48 — the session export and import implementation, merged 2026-05-08 — google-gemini/gemini-cli PR 26514 (repo PR; GitHub). <https://github.com/google-gemini/gemini-cli/pull/26514>
32. <a id="C49"></a>C49 — `opencode session export <id> [--sanitize]` and `session import <file|url> --directory` — OpenCode v2 CLI commands (vendor docs; opencode.ai). <https://dev.opencode.ai/v2/docs/cli/commands/>
33. <a id="C35"></a>C35 — Copilot CLI keeps session-state files and a session-store database; `/share`, `--remote-export`, `--remote --resume` — Copilot CLI config dir reference (vendor docs; docs.github.com). <https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference>
34. <a id="C41"></a>C41 — `~/.hermes/state.db` is canonical for all session messages; `hermes sessions export` writes JSONL (`--redact`) but refuses a session above `max_export_messages` stored rows (20,000 by default); import restores archived history — Hermes sessions (vendor docs; nousresearch.com). <https://hermes-agent.nousresearch.com/docs/user-guide/sessions/>
35. <a id="C9"></a>C9 — Litestream streams one writer's WAL to object storage; replica is a restore target — How Litestream works (project docs; litestream.io). <https://litestream.io/how-it-works/>
36. <a id="C10"></a>C10 — "LiteFS hasn't been discontinued but we've refocused effort … limited updates" (Ben Johnson, 2025-01-28); single-primary design — Fly.io community thread (forum; fly.io). <https://community.fly.io/t/litefs-discontinued/23682>
37. <a id="C11"></a>C11 — cr-sqlite maintenance thin; a maintained fork is noted — vlcn-io/cr-sqlite issue 444 (repo issue; GitHub). <https://github.com/vlcn-io/cr-sqlite/issues/444>
38. <a id="C18b"></a>C18b — sqlite-sync, CRDT multi-writer extension, Elastic License — sqliteai/sqlite-sync (repo; GitHub). <https://github.com/sqliteai/sqlite-sync>
39. <a id="C12"></a>C12 — Dolt pushes to plain git remotes since 2026-02 — Announcing git remote support in Dolt (blog; dolthub.com). <https://www.dolthub.com/blog/2026-02-13-announcing-git-remote-support-in-dolt/>
40. <a id="C6"></a>C6 — git-based Claude session sync with UUID-tree merge and LFS; picks between divergent runs — Saturate/clync (repo; GitHub). <https://github.com/Saturate/clync>
41. <a id="C34"></a>C34 — git-annex is not a folder-mirroring system like Syncthing — git-annex "not" page (project docs; branchable.com). <https://git-annex.branchable.com/not/>
42. <a id="C57"></a>C57 — `numcopies` makes git-annex refuse to drop content until N copies verify — git-annex numcopies (project docs; branchable.com). <https://git-annex.branchable.com/git-annex-numcopies/>
43. <a id="C74"></a>C74 — `mincopies` is the floor at all times; `numcopies` can be breached by concurrent drops — git-annex mincopies (branchable.com). <https://git-annex.branchable.com/git-annex-mincopies/>
44. <a id="C23"></a>C23 — remote sources over SSH/rsync with `cass sources setup|add|sync|doctor`, per-source provenance and path maps, 20+ agents, JSON API; mirrored history stays searchable offline; OpenCode `opencode.db` and Hermes `state.db` are native connectors; MIT plus a rider granting no rights to Anthropic, OpenAI or anyone acting on their behalf — coding_agent_session_search (repo; GitHub). <https://github.com/Dicklesworthstone/coding_agent_session_search>
45. <a id="C40"></a>C40 — concurrent changes to one file are kept as a `.sync-conflict` copy, never refused; synchronisation is asynchronous — Understanding Synchronization (project docs; syncthing.net). <https://docs.syncthing.net/users/syncing.html>
46. <a id="C20b"></a>C20b — encrypted folders on untrusted devices are beta / testing only; recovery needs the folder ID and the password — Syncthing untrusted device encryption (project docs; syncthing.net). <https://docs.syncthing.net/users/untrusted.html>
47. <a id="C21"></a>C21 — two-way low-latency sync over SSH with conflict policies — Mutagen synchronization (project docs; mutagen.io). <https://mutagen.io/documentation/synchronization>
48. <a id="C22"></a>C22 — Taildrive is an alpha WebDAV share, a mount not a sync — Taildrive (vendor docs; tailscale.com). <https://tailscale.com/docs/features/taildrive>
49. <a id="C67"></a>C67 — pull `order` defaults to `random`; other orders sort within a batch — Syncthing configuration (syncthing.net). <https://docs.syncthing.net/users/config.html>
50. <a id="C43"></a>C43 — `SessionEnd` hooks receive `transcript_path` and get 1.5 s by default, raisable to 60 s with `CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS` — Claude Code hooks (vendor docs; code.claude.com). <https://code.claude.com/docs/en/hooks>
51. <a id="C77"></a>C77 — versioning is per folder and device, off by default, and covers only changes received from other devices — Syncthing file versioning (syncthing.net). <https://docs.syncthing.net/users/versioning.html>
52. <a id="C64"></a>C64 — structural connectors index nothing from wrapped layouts; fixed on main, not v0.10.0 — CASS issue 520 (GitHub). <https://github.com/Dicklesworthstone/coding_agent_session_search/issues/520>
53. <a id="C66"></a>C66 — the OpenCode connector reads `~/.local/share/opencode/opencode.db` or `OPENCODE_SQLITE_DB` — franken-agent-detection 0.3.3 (docs.rs). <https://docs.rs/crate/franken-agent-detection/0.3.3/source/src/connectors/opencode.rs>
54. <a id="C65"></a>C65 — raw-mirror growth; 256 KiB chunking on main only, v0.10.0 keeps transcripts under 8 MiB whole — CASS issue 522 (GitHub). <https://github.com/Dicklesworthstone/coding_agent_session_search/issues/522>
55. <a id="C24"></a>C24 — `orca search` indexes transcripts across connected computers and paired servers — Orca CLI reference (vendor docs; onorca.dev). <https://www.onorca.dev/docs/cli/reference>
56. <a id="C46"></a>C46 — `git bundle` packages refs and objects into one file for transfer without a shared remote; it carries no worktree, index or untracked files — git-bundle (reference; git-scm.com). <https://git-scm.com/docs/git-bundle>
57. <a id="C25"></a>C25 — markdown files plus SQLite index, MCP interface — basicmachines-co/basic-memory (repo; GitHub). <https://github.com/basicmachines-co/basic-memory>
58. <a id="C75"></a>C75 — `encryption=shared` keeps the cipher unencrypted in git — git-annex encryption (branchable.com). <https://git-annex.branchable.com/encryption/>
59. <a id="C26"></a>C26 — clients connect over SSH, the encrypted relay, or Tailscale; mobile needs direct or relay — Paseo connectivity (vendor docs; paseo.sh). <https://paseo.sh/docs/connectivity>
60. <a id="C33"></a>C33 — what Paseo is: daemon, clients, providers, plugins, Apache-2.0 — Paseo llms.txt (vendor docs; paseo.sh). <https://paseo.sh/llms.txt>
61. <a id="C28"></a>C28 — agents launch, message and coordinate other agents across providers; schedules and heartbeats; cross-host work goes through the CLI — Paseo orchestration (vendor docs; paseo.sh). <https://paseo.sh/docs/orchestration>
62. <a id="C70"></a>C70 — orchestration MCP tools act on their own host; the CLI crosses hosts — Paseo orchestration at v0.12.0 (GitHub). <https://github.com/getpaseo/paseo/blob/v0.12.0/public-docs/orchestration.md>
63. <a id="C27"></a>C27 — plugin contributions: screens, panels, Command Center, slash commands, pills, timeline, themes, attachment sources, RPCs, usage sources, providers; trusted unsandboxed code — Paseo plugin quickstart (vendor docs; paseo.sh). <https://paseo.sh/docs/plugins>
64. <a id="C32"></a>C32 — `--host` targets any daemon (host:port, socket, ssh://, offer URL); plugin and project commands — Paseo CLI reference (vendor docs; paseo.sh). <https://paseo.sh/docs/cli>
65. <a id="C29"></a>C29 — Hub is the optional layer above daemons; self-hostable with an embedded database — Paseo Hub (vendor docs; paseo.sh). <https://paseo.sh/docs/hub>
66. <a id="C30"></a>C30 — official Docker image runs the daemon and web UI headless, without bundling agent CLIs; state under `/home/paseo/.paseo` — Paseo Docker (vendor docs; paseo.sh). <https://paseo.sh/docs/docker>
67. <a id="C53"></a>C53 — workspaces from every connected host, ordered by attention; per-host state — Agents Dash List (plugin registry; paseo.sh). <https://paseo.sh/plugins/panrafal/agents-dash-list>
68. <a id="C54"></a>C54 — waiting questions, permissions and plan approvals, each summarised by an LLM (Haiku by default); child agents off by default — Herald (plugin registry; paseo.sh). <https://paseo.sh/plugins/gpambrozio/herald>
69. <a id="C55"></a>C55 — archived-conversation search for file-backed providers (Claude, Codex, omp, Pi) on that daemon — Agents History (plugin registry; paseo.sh). <https://paseo.sh/plugins/panrafal/agents-history>
70. <a id="C59"></a>C59 — provider entries accept per-provider `env` and a custom binary — Paseo custom providers (vendor docs; paseo.sh). <https://paseo.sh/docs/custom-providers.md>
71. <a id="C60"></a>C60 — agent profiles are saved per host; no export command (the SDK can read host config; not independently checked) — Paseo agent profiles (vendor docs; paseo.sh). <https://paseo.sh/docs/agent-profiles.md>
72. <a id="C31"></a>C31 — the four orchestration skills install per host via Settings or `npx skills add getpaseo/paseo` — Paseo orchestration skills (vendor docs; paseo.sh). <https://paseo.sh/docs/skills>
73. <a id="C69"></a>C69 — `paseo run` has `--model`, `--thinking`, `--mode`, `--label`, no `--profile`; `--output-schema` is rejected with `--no-wait` — Paseo CLI at v0.12.0 (GitHub). <https://github.com/getpaseo/paseo/blob/v0.12.0/public-docs/cli.md>
74. <a id="C73"></a>C73 — the PyPI name `ade` is another project's — ade (pypi.org). <https://pypi.org/project/ade/>
75. <a id="C78"></a>C78 — issue 466 closed 2026-10-03, fixed in v0.9.0 — CASS issue 466 (GitHub). <https://github.com/Dicklesworthstone/coding_agent_session_search/issues/466>
