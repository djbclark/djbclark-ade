# ADE everywhere: inventory of the current environment (2026-10-19)

Evidence for [ade-everywhere-proposal.md](ade-everywhere-proposal.md). Gathered by a
read-only inventory agent on 2026-10-19 from `graft/INDEX.md` of each repo, the READMEs and
`AGENTS.md` files, `readlink` of the live dot-directories, `du`, `just --list` and `gh` for repo
visibility. Sizes are that day's; paths are this Mac's.

## 1. Headline findings

1. **No bootstrap creates the agent wiring.** Ansible covers services (LaunchAgents, MCP servers,
   LiteLLM, DNS, PATH). The links into `~/.claude/{CLAUDE.md,commands,agents,hooks}`, `~/.codex/*`,
   `~/.config/opencode`, `~/.zcode/commands` and `~/AGENTS.md` were made by hand. The one exception
   is skills, which `bin/skill-everywhere` links, one named skill per call. The only automated link
   is stayturgid's `control_node/ops_memory_link.yml`, which links
   `~/.claude/projects/-Users-djbclark-ops/memory` to `site-private/memory`.
2. **Five home instruction links are broken.** Commit `ed96569` in site-private ("retire the skills
   hub layer") deleted `site-private/home-agents.md`. These still point at it: `~/.gemini/GEMINI.md`,
   `~/.config/opencode/AGENTS.md`, `~/.qwen/QWEN.md`, `~/.zcode/AGENTS.md` and `~/.codex/AGENTS.md`
   (through `.codex-runtime/AGENTS.md`). Gemini, opencode, Qwen, zcode and Codex load no global
   rules. `~/.claude/CLAUDE.md` and `~/AGENTS.md` point straight at `site-djbclark/home-agents.md`
   and work.
3. **`~/.claude/settings.json` (51K: hook registrations, plugins, marketplaces) has no tracked copy
   anywhere.** The same is true of `~/.codex/config.toml` (a regular file, despite the README
   saying it is a symlink), `~/.config/opencode/opencode.json` and `~/.hermes/config.yaml`.
4. **Session history is about 10 GB across about 15 stores** (section 5). Only git-backed memory is
   synced: `site-private/memory` (also the Basic Memory `main` project) and `ade/docs/handoffs`.
   Tier 1 pointers (`~/.local/state/handoffs`) are synced by nothing.
5. **Everything is Mac-only** except `nixos/` (vps-primary), the stayturgid Termux side and the
   plain-Python tools.

## 2. Repo by repo

### 2.1 `~/src/djbclark-ade` (GitHub, public)

Top-level directories:

1. `skills/`: about 50 shared skills, the canonical home for every TUI. Five are symlinks to other
   repos: `forgejo` and `hyades-docker` to `~/src/sipb-agent-skills`, `forgejo-ci` to
   `~/src/loopback-port-shim`, `sipb-llm-bench` to `~/src/sipb-llms`, `sudo-secretspec` to
   `~/src/sudo-secretspec`. Paseo writes `paseo*` into here (`.paseo-managed-files.json`).
2. `bin/`: the orchestration CLIs: `acp-dispatch`, `route_agent.py`, `failover.py`, `load-watch`,
   `cow-pasture`, `herdr-*`, `skill-everywhere`, `skillopt-night`, `web-get`/`web-digest`,
   `firecrawl-router`, `wait-file`, `heavy-shim`. `bin/graft/` is untracked graft cache.
3. `tools/acp-run/`: the ACP client (207K single script plus README).
4. `claude/`: `agents/` (4), `commands/` (8), `hooks/` (12 hooks plus
   `handoff-tools/session_log.py`). `handoff-tools/.venv` is 294 MB of local state.
5. `docs/`: design records (helm, failover, model-routing, apply-toolchain-prompt v5.11,
   skill-everywhere, mcp-servers, disabled-skills). `docs/handoffs/` holds Tier 2 `HANDOFF_*.md`
   (172K, tracked).
6. `launchd/`: 6 plists (acp-dispatch-reap, context-budget, load-watch, routing-recalibrate,
   skillopt-sleep, zcode-key-auth), all with hard-coded `/Users/djbclark/...` paths.
7. `config/`: `routing.toml`, `context-budget.toml`, `sudoers.d/acp-dispatch-pmset`.
8. `plugins/herdr-sleeper`: dev source of `djbclark/herdr-sleeper`.
9. `opencode-plugins/`: `rtk.ts` and `openusage-telemetry.ts`.
10. `zcode/commands/`: 15 slash wrappers.
11. `vendor/`: snapshots and pointers (gate-scripts, hermes skill, orca guide).
12. `scripts/github-ci-run`, `bench/firecrawl`, `tests/` (pytest for acp-run, acp-dispatch, hooks).
13. Per-agent repo wiring: `.claude/`, `.codex/`, `.cursor/`, `.gemini/`, `.kiro/`, `.windsurf/`,
    `.agents/`, `.adal/`, `.claude-plugin/marketplace.json`.
14. Local-only junk: `.crush/crush.db`, `.skillopt-sleep*/`, `.zcode/`.

Sensitivity: (i) public-safe and machine-independent: `skills/`, `tools/`, `bin/`, `claude/`,
`docs/`, `zcode/`, `opencode-plugins/`, `tests/`. (ii) Private in spirit but published:
`docs/handoffs` and `docs/queue.md` carry account and host names; a sweep is needed.
(iii) Machine-specific: `launchd/*.plist`, `config/sudoers.d`, `claude/hooks/handoff-tools/.venv`,
`.crush/`, `.skillopt-sleep*/`, `graft/` and `bin/graft`, `__pycache__`, `.pytest_cache`.

### 2.2 `~/ops/site-djbclark` (GitHub, public)

1. `roles/` and `playbooks/`: 9 Ansible roles, one playbook each (section 4).
2. `inventory/`: `hosts.yml`, the site facts: Tailscale IPs, USB serials, LAN IPs and a Telegram
   user ID, in a public repo (policy says IPs and hosts are acceptable).
3. `brew/fragments/*.yml`: stack-owned formula claims (agent-cli-tools, ai-quota-tools, paseo,
   site, stayturgid), projected to `generated/Merged-Brewfile`. Nothing runs `brew bundle`.
4. `bin/`: about 100 site scripts: `bg`/`bgb`, `fleet-watch` (a 49K real file here), `watchdogd`,
   `load-governor`, the `s1_*` session ingesters (one per TUI), `hermes-ping`, `sudo-ask`,
   `claude-statusline`, `check_hostnames`, `registry_lint`, `deploy_ops_release`.
5. `tools/`: `book-to-kb` (book-kb CLI and skill), `s-farm`, `herdr/pane-grep`. `acp-run` is a
   symlink to ade. `sipb-llms-proxy` is a "Moved" stub.
6. `claude/local-marketplace`: the `local-lsp` plugin, the only thing left in `claude/`.
7. `codex/`: `config.toml.example`, `hooks.json`, `rules/`, `herdr-agent-state.sh`.
8. `cursor/home-agents.mdc`, `config/autorename-workspaces.conf`, `gradle/`, `shell/` (bashrc,
   zshrc, bash_profile, selftest), `macos/` (corner-rescue, neofinder, otp-to-clipboard,
   no-apple-intelligence, hourly-updates, athena-kerberos, graft-hook-timeout-fix).
9. `nixos/`: flake for vps-primary. `olivetin/`, `services/twilio-webhook-relay` (Cloudflare worker).
10. `registry/`: `ports.yml`, `paths.yml`, identity patterns: the allocation authority.
11. `docs/`, `research/`, `human/`, `prompts/`, `skills/README.md` (hub tombstone), `tests/`.
12. `home-agents.md`: the live `~/AGENTS.md` and `~/.claude/CLAUDE.md`. `justfile`: 26.8K.

Sensitivity: (ii) `inventory/hosts.yml` and `group_vars`, `human/API-KEYS-E4.md` (names only),
`nixos/vps-primary`, `olivetin`. (iii) `generated/`, `.token-savior-cache.json` (856K), `.aider.*`,
`.ansible/`, `.env` (root-owned immutable tombstone), graft caches. Absolute `~/.local/bin` links
are made by `just herdr-agents-install`.

### 2.3 `~/ops/site-private` (GitHub, private)

1. `memory/`: 324 one-fact-per-file notes plus `handoffs/`, `codex/`, `todo/`, `reports/`,
   `agent-rules/`. Claude's home memory and the Basic Memory `main` project.
2. `1password/sync-to-grok.list`; `skills/1password` (the only private skill); `tailscale/`
   (tailnet export snapshots); `web/maynarddaycare` (12M personal site);
   `docs/operations/claudehelm` (private run docs; every other doc is a symlink to site-djbclark).
3. `bin/`: 23 entries, all symlinks into site-djbclark or ade: a compatibility shim only.
4. `codex/`: hooks, rules, README and example are symlinks to site-djbclark; `config.toml` and
   its `.bak` are real files.
5. `cursor`, `gradle`, `macos`, `prompts`, `shell`, `tests`: symlinks to site-djbclark.
6. `.githooks/`: pre-commit plus `private-paths`, enforcing the private-only rule.
7. `.codex-runtime/`: 913M, ignored: the real target of `~/.codex/{sessions,history.jsonl,
   state_5.sqlite,logs_2.sqlite,...}`.
8. `justfile`: `book-*` and `private-only-check`.

Sensitivity: (ii) `memory/`, `tailscale/`, `1password/`, `web/`, `docs/operations/claudehelm`,
`skills/1password`, `codex/config.toml`. (iii) `.codex-runtime/`, `.token-savior-cache.json`,
`.env`. Everything else is a pointer into public content.

### 2.4 `~/ops/stayturgid` (GitHub, public)

The product repo: keeps wireless ADB, Shizuku and SSH alive on unrooted Android phones over
Tailscale (Termux runtime, Ansible collections, a Mac control node, a Kotlin native agent, an SSH
CA). It matters here because site-djbclark's `just deploy-mac` and `just deploy` call stayturgid's
justfile. Its `control_node` role writes Mac LaunchAgents, the Hermes Telegram gateway, ssh
config and the ops memory symlink.

## 3. Overlap and duplication

1. `skills/`: canonical copy is `ade/skills`. `site-djbclark/skills` holds only a retired-hub
   README. `site-private/skills` has the 1password skill plus a README symlink.
2. `book-to-kb` is a real duplicate: `ade/skills/book-to-kb/SKILL.md` and
   `site-djbclark/tools/book-to-kb/skills/book-to-kb/SKILL.md` differ.
3. Skills outside the three repos: `~/.agents/skills` (orca-cli, herdr, orchestration,
   computer-use, caveman*, a `.trash/` copy), `~/.bailian/skills`, and `~/.claude/skills/ralph-tui-*`
   (real directories).
4. `claude/`: live material is in `ade/claude`. `~/.claude/hooks` also holds three unversioned real
   files: `herdr-agent-state.sh`, `upstream_review_gate.sh` and its `.test.sh`.
5. `codex/`: site-djbclark is canonical. Three `hooks.json` files all differ: `~/.codex/hooks.json`,
   `site-djbclark/codex/hooks.json` and `ade/.codex/hooks.json` (repo-level graft wiring).
6. `bin/`: site-private/bin is 100% symlinks. The `acp-run` chain is 3 hops: `~/.local/bin/acp-run`
   to `site-private/bin` to `site-djbclark/tools/acp-run` to ade. `fleet-watch` is a real file in
   site-djbclark/bin although the ade README and site-private AGENTS.md say it lives in ade.
7. `docs/`: about 15 site-private docs are symlinks to site-djbclark/docs. Handoff and session
   specs are split between `site-djbclark/docs/{handoff.md,session-handoff-compaction-spec.md,
   session-handoff-implementation-plan.md}` and `ade/skills/{handoff,session-handoff}` plus
   `ade/docs/handoffs`. Tier 2 handoffs live in both `ade/docs/handoffs` and
   `site-private/memory/handoffs`.
8. Home rules: `site-djbclark/home-agents.md`, `cursor/home-agents.mdc` (kept in step by hand) and
   `~/.copilot/copilot-instructions.md` (a regular file, likely drifting).
9. opencode plugins: `~/.config/opencode/plugins/{rtk.ts,openusage-telemetry.ts}` are copies of
   `ade/opencode-plugins` (identical today). `~/.config/opencode/commands/*.md` (9 files) are
   hand-made copies, not links.
10. `vendor/gate-scripts/opencode-ralph-tui*` are copies of `~/.local/bin` files (identical today).
11. launchd: plists come from four sources: `ade/launchd`, site-djbclark roles (site_agents,
    watchdogd, shared_mcp, basic_memory_mcp, litellm, paseo_desktop), stayturgid control_node and
    serverapp_*, and hand installs. `~/Library/LaunchAgents` has 109 plists, all copies.

## 4. How a machine is installed today

Ansible roles in site-djbclark (`playbooks/<role>.yml`; `just <role>-apply|-check|-status`):

1. `launchd_path`: launchd user PATH equals the login-shell PATH (root applier plus sudoers rule).
2. `mac_dns`: tailnet MagicDNS resolvers and search domains.
3. `site_agents`: maintenance LaunchAgents and `~/.local/bin` scripts: system-state-backup,
   hibernate-disk-check, cswap-auto, aiuse, s1-ingest, jobber, hermes-dashboard.
4. `watchdogd`: one launchd watcher with `~/.config/djbclark/watchdogd.d/*.toml`.
5. `shared_mcp`: loopback MCP servers crawl4ai :18798, arxiv :18800, paper-search :18802,
   firecrawl :18804.
6. `basic_memory_mcp`: shared basic-memory MCP at :18796.
7. `litellm`: proxy at 127.0.0.1:4000, launchd or systemd.
8. `open_webui`.
9. `paseo_desktop`: the Paseo daemon.

Secrets are injected through `*-apply-secrets`, which wraps sudo-secretspec. stayturgid roles
reached from `just deploy-mac`: `control_node` (ssh config, known_hosts, device reconnect
LaunchAgents, Hermes and its Telegram gateway, OpenCode web, the ops memory link) and
`serverapp_*` (caddy, grafana, vector, victoriametrics, openobserve, landing, olivetin,
blackbox_exporter).

Other bootstrap justfile targets: `brew-project`/`brew-diff` (projection only), `install-cswap`,
`install-aiuse-deps`, `install-caut`, `install-codexbar`, `install-openusage`, `install-tokscale`,
`install-ai-quota-tools`, `herdr-agents-install` (absolute symlinks into `~/.local/bin`),
`ops-memory-sync`, `site-sync`.

`ade/docs/apply-toolchain-prompt.md` (v5.11, 1639 lines) is a paste-in prompt for a Claude
orchestrator that applies the toolchain to some other repo. Its §1 is the best existing list of
tools and install commands. It is not a machine bootstrap.

Linking, per agent (by hand unless noted):

1. Skills: `ade/bin/skill-everywhere <name>` links `ade/skills/<name>` directly into
   `~/.claude/skills`, `~/.agents/skills` (codex, zcode), `~/.gemini/antigravity-cli/skills`,
   `~/.copilot/skills`, `~/.config/opencode/skills`, `~/.qwen/skills`, `~/.config/devin/skills`,
   `~/.cline/skills`, `~/.grok/skills`, `~/.omp/agent/skills` and
   `~/.local/share/skill-everywhere/skills` (Hermes external_dirs). No "link all" mode.
2. `~/.claude/{commands,agents,hooks}/*`: per-file symlinks to `ade/claude/`. No script creates them.
3. `~/.claude/CLAUDE.md` and `~/AGENTS.md` point to `site-djbclark/home-agents.md`.
4. `~/.codex/*`: per-entry symlinks into `site-private/.codex-runtime`, `codex/rules` and
   `memory/codex`. No script creates them.
5. `~/.zcode/commands`: 15 symlinks to `ade/zcode/commands`.
6. Claude plugins: marketplaces `djbclark-ade` (the ade repo) and `local`
   (`site-djbclark/claude/local-marketplace`) are registered in `settings.json`.

Mac-only: `brew/`, all launchd plists, `macos/`, roles launchd_path, mac_dns and site_agents, the
stayturgid control_node, cow (APFS), Orca.app, `heavy-shim`. Portable: skills, acp-run,
acp-dispatch, route_agent, session-finder, the Python hooks, `nixos/`, the litellm role's systemd
mode, `shell/`.

## 5. Tools that live elsewhere

| Tool | Source | Install | Public |
|---|---|---|---|
| aiuse | github.com/djbclark/aiuse (`~/src/aiuse`) | `brew tap djbclark/aiuse` 3.7.2 (vendor/README still says pipx) | yes |
| sudo-secretspec | github.com/frdminc/sudo-secretspec | brew formula, then `libexec/sudo-secretspec install --adopt-existing` puts a root-owned `/usr/local/bin/sudo-secretspec` | yes |
| acp-run | `ade/tools/acp-run` | 3-hop symlink chain | yes |
| acp-dispatch, web-get, web-digest, firecrawl-router, wait-file, skill-get, context-budget-check | `ade/bin` | direct `~/.local/bin` symlinks | yes |
| herdr | fork github.com/djbclark/herdr | `~/.local/bin/herdr` is a 20.7M real binary; `~/.herdr-wrapper/bin/herdr` (unversioned guard) is first on PATH; docs say Homebrew but it is not in the Cellar | yes |
| herdr plugins | djbclark/herdr-sleeper; collie (`~/.collie`, self-updating) | `~/.local/bin/herdr-sleeper` points at `~/orca/projects/djbclark-ade/bin` | yes |
| orca | app at `~/.local/churn-producing-apps/Orca.app`; fork djbclark/orca | CLI symlink into the bundle | yes |
| cswap | uv tool claude-swap (`just install-cswap`) | PyPI | yes |
| session-finder, helm, herdr-tidy | `ade/skills/*` Python; index at `~/.local/state/session-index` | run through the skills, not on PATH | yes |
| hermes | clone of github.com/djbclark/hermes-agent at `~/.hermes/hermes-agent` (5.7G) | unversioned `~/.local/bin/hermes` shim; config by stayturgid control_node | yes |
| graft | npm global `@nanonets/graft` | per-repo `graft/` caches | yes |
| cow | brew joeinnes/tap/cow 0.1.10 | `cow-pasture` (ade/bin) is not on PATH | yes |
| book-kb, clip | `site-djbclark/tools/book-to-kb/bin` via site-private/bin symlinks | not on PATH directly | yes |
| fleet-watch | `site-djbclark/bin/fleet-watch` | LaunchAgent runs `site-private/bin/fleet-watch` | yes |
| sipb-llms-proxy | forgejo.mit.edu/djbclark/sipb-llms | | yes |
| forgejo, hyades-docker, forgejo-ci skills | forgejo sipb-agent-skills, loopback-port-shim | symlinks | yes |
| uv tools | basic-memory, litellm (fork `~/src/litellm`), skillopt (pinned commit), crawl4ai, mcp-crawl4ai, arxiv-mcp-server, paper-search-mcp, mcp-proxy, open-webui, omnigent | uv | |
| pipx tools | ansible-lint, cfengine, yamllint, uiautomator2 | pipx | |
| caut | cargo | | |
| agent CLIs | claude (`~/.local/share/claude/versions`), codex (`~/.codex/packages`), cursor-agent | vendor installers | |
| npm globals | cline, opencode, zcode, claude-agent-acp, codex-acp, firecrawl-mcp, claude-powerline | npm; node/npm/npx on PATH are `~/.hermes/node/bin` (fragile) | |
| unversioned `~/.local/bin` files | muse, caam, tokscale, superbrain, terminus-kira, hreload, hsudo, opencode-all | hand-made | |

## 6. Session state (path; format; size; synced?)

| Store | Path | Format | Size | Synced |
|---|---|---|---|---|
| Claude Code transcripts | `~/.claude/projects/<slug>/*.jsonl` (553 project dirs) | jsonl per session, side dirs for subagents | 1.7G | no (memory subdirs for `~`, `~/ops`, aiuse link into git) |
| Claude history | `~/.claude/history.jsonl` | jsonl | 2.8M | no |
| Codex rollouts | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`, in `site-private/.codex-runtime` | jsonl plus sqlite (state_5, logs_2, memories_1) | 135M (913M total) | no; `~/.codex/memories` is git |
| OpenCode | `~/.local/share/opencode/opencode.db` | sqlite | 1.0G | no |
| Hermes | `~/.hermes/state.db` (plus 1.1G .bak), `gmail_index_v2.db` 944M; `~/hermes-memory` 92K | sqlite; markdown | 24G total | no |
| Cursor | `~/.cursor/chats` 905M, `~/.cursor/projects` 192M | sqlite plus transcripts | 1.1G | no |
| Gemini, Antigravity | `~/.gemini` (antigravity 180M) | per-project-hash dirs | 2.2G | no |
| Copilot | `~/.copilot/session-state` | files plus session-store.db | 46M | no |
| Cline | `~/.cline/data/sessions` | | 266M | no |
| Grok | `~/.grok` | | 256M | no |
| Qwen | `~/.qwen/projects` | | 39M | no |
| zcode | `~/.zcode/cli/db/db.sqlite` | sqlite | 268M | no |
| Muse | `~/.local/share/muse/sessions` | | 52M | no |
| Crush | `~/.config/crush/.crush/crush.db`, `ade/.crush` | sqlite | | no |
| Paseo | `~/.paseo` (agents, projects, runtime, daemon.log; `models/` is 984M of voice models) | small JSON per agent; transcripts stay in the provider stores | 994M | no |
| herdr | `~/.config/herdr` 9.8M; `~/.local/state/herdr` 704K | | | no |
| Orca | `~/Library/Application Support/Orca` 2.2G; `~/orca/workspaces` ~14G of checkouts | | | no |
| session-finder index | `~/.local/state/session-index/history.v2.sqlite` | sqlite FTS5 over files (`files`, `msgs`, `locations`) | 146M | no, rebuildable |
| session-finder, acp-run state | `~/.local/state/session-finder` 28M, `~/.local/state/acp-run` 50M | | | no |
| bigteam scratch | `~/.local/state/bigteam` (adhoc-2026-10-18 is 55G) | | 106G | no; cleanup target |
| Tier 1 pointers | `~/.local/state/handoffs/<repo>/<task>/SESSION_LOG.md` with redirects to `chains/<key>/SESSION_LOG.md`; written by `claude/hooks/handoff-tools/session_log.py` | markdown | 100 chains, 2.9M | no; the most valuable small item to sync |
| Tier 2 handoffs | `ade/docs/handoffs`, `site-private/memory/handoffs` | markdown | 172K+ | git |
| Basic Memory | `~/.basic-memory` (551M index); projects: `main` = site-private/memory (git); claude-, codex-, cursor-, opencode-, gemini-, zcode-, crush-, copilot-memory = `~/agent-memory/*`, all empty; hermes-memory; books = `~/kb/md` 4.3M | markdown plus sqlite index | | main via git; no bisync |
| S1 ingest | `site-djbclark/bin/s1_*.py`, launchd `com.djbclark.s1-ingest` | scans every TUI into a Hermes sink plus a search index | | no |
| System backup | Syncthing running with only an empty placeholder folder; Carbon Copy Cloner installed; `~/system-state` (Brewfile, launchctl and defaults dumps) not in git | | | no |

## 7. Dead, retired, obsolete

1. Broken links: the 5 home instruction links (section 1); `~/.local/bin/agent-coord` and
   `agent-coord-herdr` (point at the retired ops-djbclark worktrees); `~/.local/bin/arq_restore`;
   `~/.local/bin/cursor-cli` (old cursor-agent version).
2. Retired directories: `site-djbclark/skills`, `site-djbclark/claude` (all but local-marketplace),
   `site-djbclark/tools/sipb-llms-proxy`, `research/apply-dev-toolchain`, `docs/relay`.
3. Dormant: `ralph-tui-orchestration` skill, `~/.claude/skills/ralph-tui-*`,
   `vendor/gate-scripts/opencode-ralph-tui*`, `research/autonomy`.
4. Removed: agent-radar plugin (2026-10-18); `~/.claude/commands/z.md.bak-retired-2026-09-27`.
5. Retirement notes in site-private/memory: `project_crush_removed_2026-10-08` (yet `.crush`,
   crush-acp and crush tests remain), `project_goose_removed_2026-10-03`,
   `project_goose_desktop_retired`, `project_hindsight_retired_basic_memory_2026-09-30`,
   `project_orc_and_herdr_orchestration_retired`, `project_load_sampler_remove_after_next_spike`.
6. Stale docs: `ade/vendor/README` says helm is canonical in site-djbclark and the hooks are in
   site-private; the ade README and site-private AGENTS.md place fleet-watch in ade; the
   site-djbclark AGENTS.md chain "~ to site-private/home-agents.md" no longer exists; the herdr
   docs say Homebrew.
7. Backup clutter: `~/.hermes/config.yaml.bak-*` (30+), `~/.codex/config.toml.bak-*`,
   `~/.config/opencode/opencode.json.bak-*`.
8. Disabled but kept: `ade/docs/disabled-skills.md`, `~/.claude/skills-disabled`.
