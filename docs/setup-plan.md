# Setup, hardening and updates: plan (queue Carried 35)

Plan, 2026-11-07. The first bounded config-core unit shipped on 2026-11-08 ([PR 308](https://github.com/djbclark/djbclark-ade/pull/308)); later phases remain planned.
Overall and local coordination now belongs to the operator-appointed local
workhorse lead, with higher-tier judgment delegated through the router. This transfers coordination from the Claude
cloud lead; it does not change provider defaults or the historical slim-down rulings. The operator asked for the plan
the same day, in five parts: an easy install on a new Mac or Linux machine with every dependency and TUI; automatic updates of djbclark-ade and its dependencies; easy setup of the GitHub
pieces a new djbclark-ade user needs (the `ade-merge-gate` App first); prompt-injection hardening of GitHub, both at setup and
on demand, with an ongoing check that the policy stays applied; and one config file for every djbclark-ade option. A sixth
part was added: prompts and code that hand any browser-only step to Grok Bot. Later the same day: aiuse and
sudo-secretspec are hard dependencies, every listed component is in the install and update system except commercial
products, and Hermes is offered with a do-it-yourself or AI-assisted setup (S3, S3a). Then: the commercial services (1Password,
Grok Bot, GitHub Advanced Security, hosted firecrawl, Greptile, CodeRabbit) are optional components, and OVHcloud is
the suggested host. Then: API keys for every TUI and tool are checked, verified, collected in one batch and delivered
(S3b). The operator added managed jobs/services (S4b), the measured injection-gate build (S5a), and cloud-agent
coordination (S9). The sections below go in build order: S1 and S2 come first because every later section reads
the config and adds a recipe. S5a precedes final review of each adopting reader in the original design (security work deferred 2026-11-08). S9 stays last, after S1-S8,
item-24 message signing and S5a, and is built only with headroom.
The research behind S5 is dated 2026-11-07. Sources are listed at the end, and their facts must be re-probed when the work starts.

## Current operator policy — 2026-11-08

Pi is the sole general-purpose third-party TUI. Retain vendor clients required
for monthly plans and the unchanged Hermes exception. Archive other clients
reversibly; do not reinstall omp, OpenCode or the other retired clients from
an older component list. Their history and restoration state remain preserved.

New prompt-injection security implementation is deferred. The security sections
below remain design notes, not work to start automatically. Prioritize Pi
service acceptance and preserve separate API, subscription and gateway pools.
Basic inference is not automatic-routing, continuation or quota acceptance.
The current decision and evidence are in
[tui-security-and-pi-migration.md](tui-security-and-pi-migration.md) and
[pi-services.md](pi-services.md). These rulings supersede conflicting client
and security sequencing in the older plan; other unfinished planning stays intact.

## S1. One config file

1. **Format: TOML** (recommended). It is what `config/*.toml` already uses, Python reads it with the standard `tomllib`, it
   allows comments, and the operator already edits it. Alternatives considered:
   - YAML: indentation and type-coercion traps.
   - JSON or JSON5: no comments, or a non-standard reader.
   - Pkl, CUE or Nickel: typed and validating, but one more tool to install on every machine.

   Typed validation comes from a checked-in JSON Schema instead, run by `bin/ade-config --check` in CI.
2. **One file, `config/ade.toml`**, with a table per area: `[lead]`, `[routing]`, `[gates]`, `[dispatch]`,
   `[context_budget]`, `[pr_policy]`, `[secret_deny]`, `[install]`, `[update]`, `[github]`, `[hardening]`.
   - Today's files fold into it one at a time: `routing.toml`, `gates.toml`, `context-budget.toml`, `pr-policy.toml`,
     `secret-deny.toml`, and the JSON policies where they are hand-edited.
   - During migration, a missing new-format file uses a documented legacy projection. A present valid new-format file
     takes precedence; malformed new-format input fails validation rather than silently using legacy policy.
     Existing readers stay unchanged until their explicit adoption PR (implementation contracts below).
3. **Per-machine overrides** go in `~/.config/djbclark-ade/local.toml`, which is never tracked. Tables merge recursively by leaf, arrays replace whole,
   and the local file wins; type conflicts and duplicate identities are rejected. Secrets are never stored in either file: a field names a `sudo-secretspec` key.
4. **`bin/ade-config get|set|check|diff`** is the one reader and writer. A set is atomic (a temp file, then `os.replace`)
   and keeps the comments. The `switch` lines that AGENTS.md promises become `ade-config set` lines, for example
   `ade-config set lead.fable_lead false`.

## S2. One entry point: a justfile

1. **`just`** (recommended). site-djbclark already uses it, its recipes list themselves (`just --list`), and Homebrew and
   every Linux distribution package it. Alternatives considered:
   - make: tab and quoting traps.
   - mise tasks: ties the entry point to mise.
   - a Python `bin/ade` dispatcher: fine, but it duplicates what just gives for free.

   The recipes stay thin: each calls a `bin/` tool, so CI and agents can call the tool without just.
2. Recipe groups:
   - `install`, `update`, `doctor`
   - `github-setup`, `harden`, `harden-check`
   - `config-check`
   - `browser-task` (S7)

   Every recipe that changes something has a `--dry-run` that prints the change first.

## S3. Install on a new machine (Mac and Linux)

1. **`just install`** (bootstrap: `curl … | sh` is not used). A new machine runs
   `git clone https://github.com/djbclark/djbclark-ade ~/src/djbclark-ade && cd ~/src/djbclark-ade && ./bin/ade-install`,
   which installs `just` if it is missing and then runs the recipe.
2. **Every dependency is in one system** (operator, 2026-11-07: "All of the listed things should be part of our easy
   install/update/keep-updated system"; commercial services first left out, then made optional the same day). The list
   lives in `[install]`, one entry per component, each with its install, update and probe command. `vendor/README.md`
   points at it. The components fall into five classes:
   1. **Hard dependencies.** `just install` installs them, `just doctor` fails without them, and the daily job keeps
      them current:
      - **sudo-secretspec** (`frdminc/sudo-secretspec`; `brew install frdminc/sudo-secretspec/sudo-secretspec`, or its
        Linux path). It is the only way a key reaches a tool (review rule 3). Hard dependency by operator ruling of
        2026-11-07.
      - **aiuse** (`djbclark/aiuse`; Homebrew or PyPI, per its README). It is the main quota reading for routing.
        Hard dependency by operator ruling of 2026-11-07. Also **cswap** (`claude-swap`), which aiuse reads.
      - **Paseo** (`getpaseo/paseo`), its skill bundle (`npx skills add getpaseo/paseo`, set user-invocable-only),
        and the Paseo plugins of the J6 set, each with its settings from `[install.paseo_plugins]`: session-guard,
        baton, asks, questions-please (`djbclark/paseo-plugin-questions-please`), tell-agent, vitals, skills,
        pr-radar, claude-code-entrypoint-env, session-janitor, session-recovery. The ones not chosen are recorded too
        (zerosub, usage-auto-resume, plan-auto), so `doctor` can tell "not chosen" from "missing".
      - **The operator's own Paseo plugins and forks**, each as a Paseo plugin component:
        - **paseo-runner** (`djbclark/paseo-runner`): script packs as tabs of buttons on desktop, web and phone, stage 1
          (server core, no UI yet, 2026-11-07). Its `scripts/sync-plugins.mjs` installs, disabled, every plugin one
          daemon has onto the daemons that lack it, which is how `just update` keeps the Mac and vps-primary in step.
          An earlier draft of this plan listed it as a consumer of djbclark-ade; that was wrong, corrected 2026-11-07.
        - `djbclark/paseo-plugin-questions-please` (above) and `djbclark/paseo-plugin-dann-workspace-accent`.
        - The forks `djbclark/paseo-baton`, `djbclark/paseo-plugins` and `djbclark/paseo-transcript-search`: install
          the upstream unless the fork carries a change not yet upstreamed (standing order 8), and record which one in
          `[install]`. The baton fork was pushed on 2026-11-07, while the J6 set names upstream baton (dennyferra):
          decide which one at build time.
        - The Paseo fork `djbclark/paseo` follows the same rule: upstream Paseo unless the fork is needed.
      - **`graft`** (`@nanonets/graft`), **`gh`**, **`uv`**, **`just`**, `git`, and the modern-CLI tools
        (site-djbclark's `skills/setup-modern-cli` list moves into `[install]`).
      - **The provider clients:** Pi, plus vendor clients required for monthly plans (Claude Code, Codex,
        the Cursor CLI, and Paseo's antigravity provider). Retired third-party clients are restoration
        options, not hard dependencies. The subscriptions remain the user's own; logging in is the
        user's step (S3.5), and installing a client establishes no entitlement.
      - **The skill roots:** this repo, a site repository (site-djbclark for this operator, `[install.site_repo]` for
        another user), and `skills-lock.json`'s external skills (today `fastino-glide`), all linked by
        `bin/skill-everywhere --all`.
      - **Repo-local state:** the scheduled jobs `bin/ade-sched` renders (launchd, systemd user timers or cron), the
        hook and secret-deny templates (`bin/ade-template-check`), and the `.claude/settings.json` mirror of the Paseo
        skill overrides.
   2. **Offered, on by default for this operator, asked for a new user.**
      - **Hermes** (S3a).
      - **peer-link** (`frdminc/peer-link`), the Grok Bot channel, with `tell_chief_of_staff.py` (needs Hermes).
      - **The firecrawl router** (`bin/firecrawl-router`) pointed at a firecrawl endpoint: this operator's
        self-hosted one on Hyades, or none.
      - **The LiteLLM proxy** (the fork at `~/src/litellm`, site-djbclark's `roles/litellm`), Hermes' fallback.
   3. **Optional, off by default, offered one by one** (operator, 2026-11-07: commercial services are opt-in
      components, not exclusions). Each has an install, a basic setup and a `doctor` probe. Each is a free client or
      skill; the account behind it is the user's:
      - **1Password:** the app, the `op` CLI and the `1password` skill. The skill is site-private's `skills/1password`.
        It is linked from site-private when the user has access, as this operator does. For a new user, a public generic
        copy without this operator's vault or item names is a decision for the operator (site-private's private-paths
        list keeps the current copy private, and changing that needs the operator's yes, order 11).
      - **Grok Bot:** setup of the cloud bot's side for a new user (an account through Cursor, the bot's webhook and its
        `ask_claude` callback), on top of peer-link (S3.2.2).
      - **GitHub Advanced Security:** turned on for the repositories that have it, so "code scanning for AI applications"
        (S5) runs; the setup first probes whether the account can use it.
      - **Hosted firecrawl** (firecrawl.dev): an API key in `sudo-secretspec` and the router's upstream set to it, as the
        alternative to a self-hosted firecrawl.
      - **Greptile and CodeRabbit:** their CLIs or apps, keys in `sudo-secretspec`, and their skills (from site-djbclark)
        linked.
      - **The herdr bridges:** `herdr4paseo` and `paseo4herdr` (`djbclark/paseo4herdr`) and `bin/herdr-server-run`, the
        last herdr pieces, only for someone who still runs herdr.
   4. **Suggested, not installed: hosting.** A user who wants an always-on agent host (what vps-primary is here) is
      pointed at **OVHcloud** (operator, 2026-11-07: "suggest OVHcloud not Hetzner"). site-djbclark's `ovhcloud-api`
      skill can drive it once the user has an account. This operator's current hosts (vps-primary on Hetzner, the Hyades
      host) stay as they are; they are infrastructure, not components.
   5. **Never installed:** the paid plans themselves. The user buys them and logs in; their free clients are installed
      (S3.2.1):
      - Claude Max; Anthropic API credits are accounted separately and use Pi only after service acceptance;
      - the ChatGPT plan behind Codex;
      - Cursor, which also bills Grok Bot;
      - the Google AI plan behind the antigravity provider;
      - OpenCode Go subscription credits when accepted through Pi (the OpenCode TUI itself is archived; do not install it);
      - the Z.ai coding plan;
      - ClinePass.

      Repositories that *use* djbclark-ade (tendcf, nix2cf, Plektra) are not components either. site-private is cloned
      only when the user already has access to it.
3. **How it installs:** Homebrew on the Mac, plus Homebrew or the distribution's package manager on Linux (decided per
   component, recorded in `[install]`). npm, uv/pipx or a git clone are used where that is a component's normal path.
   Nothing is version-pinned (standing order 8).
4. **`just doctor`** probes every component: hard dependencies fail, offered ones that were chosen fail, and optional
   ones only report. A probe checks that the tool runs (`--version` or its own health check), not just that a file exists.
5. **Logins** are a checklist, not automated: each provider's own `login` command, the GitHub login, and
   `sudo-secretspec` for API keys. `just doctor` reports what is missing, never a secret's value.
6. Starting point: the decided but unbuilt proposal `docs/history/ade-everywhere-proposal.md` (2026-10-20). Keep its
   answered questions and re-base it on Paseo and this component list.

### S3a. Hermes: offered install and basic setup

`just install` asks whether to install Hermes (operator, 2026-11-07: "offer to install and do basic setup of hermes, but
allow for the user to do that setup either themselves or with interactive AI assistance"). The upstream project and its
install path are confirmed when this is built; the live setup is the one under `~/.hermes/`. The user picks one of
three paths:

1. **Skip.** Hermes is recorded as not chosen, and `doctor` stays quiet about it.
2. **Install, then set it up myself.** The tool is installed by its normal path, then a checklist is printed with the
   exact files and commands for a basic setup and a link to Hermes' own docs:
   - a model or provider (through the LiteLLM proxy or directly);
   - the search backend (firecrawl, if chosen);
   - the djbclark-ade skills root;
   - the vendored `claude-collaboration` skill;
   - the Claude MCP bridge;
   - `tell_chief_of_staff`'s Keychain items (its `setup.sh`).

   `just doctor hermes` checks each item.
3. **Install, then set it up with AI help.** The tool is installed, then `just hermes-setup` opens a Claude Code session
   with the checked-in prompt `prompts/setup/hermes.md`.
   - The session walks the same checklist one step at a time, each as a card with the recommended option first.
   - It runs what it can, stops for each secret (the user types it into `sudo-secretspec`, never into the chat) and
     for each choice.
   - It finishes with `just doctor hermes`.

Either path can be re-run later (`just hermes-setup`, `just hermes-setup --self`), and `just update` keeps an installed
Hermes current like every other component.

### S3b. API keys: check, verify, collect, deliver

Operator, 2026-11-07: every TUI and tool that uses an API key gets one at install, and the keys are re-checked as part of
keeping things current. The steps run in this order: check what `sudo-secretspec` already holds, verify that each held
key actually works, then ask for the missing or failing ones one at a time, in a single batch, with the URL to get each.
Keys are saved with `sudo-secretspec`, and also through Paseo if it has a secure store (S3b.5).

1. **One registry of keys**, in `config/ade.toml` as `[keys.<NAME>]`. Each entry has:
   - the components that use it;
   - required or optional (it follows the component's class in S3.2, so a key for an unchosen component is never
     asked for);
   - the URL to create it;
   - a verify probe;
   - where else it must be delivered (Paseo, or the tool's own credential store);
   - and, where the provider has one, its expiry.

   The starting list is everything the templates and tools name today:
   - `agents/*/*.tmpl` `{{ secret "…" }}`: `EXA_API_KEY`, `JINA_API_KEY`, the Hermes and LiteLLM entries;
   - site-djbclark `human/API-KEYS-E4.md`: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`,
     `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, `TELEGRAM_BOT_TOKEN`, which `sudo-secretspec run` itself requires;
   - the tools: `ZAI_CODING_PLAN_API_KEY` (Pi), the OpenCode Go service keys when that pool is still recovered via `skills/oc-go-key` (OpenCode TUI archived), `CURSOR_API_KEY`
     (`bin/cursor-cloud`), `FIRECRAWL_GITHUB_PUBLIC_TOKEN` (the router; it expires), `GREPTILE_API_KEY`, CodeRabbit's,
     hosted firecrawl's, and the merge-gate App's private key (S8; stored in GitHub, not locally).

   TUIs that log in by account (Claude Code, Codex, the Cursor CLI, the antigravity provider) appear as login checks,
   not keys, unless the user picks key-based auth.
2. **The URLs** go in the registry and are re-probed when this is built. The starting list, each marked unverified
   until probed:
   - Anthropic: `console.anthropic.com/settings/keys`
   - OpenAI: `platform.openai.com/api-keys`
   - Google Gemini: `aistudio.google.com/apikey`
   - OpenRouter: `openrouter.ai/keys`
   - DeepSeek: `platform.deepseek.com/api_keys`
   - Z.ai: its API-key page
   - Cursor: its dashboard's API keys
   - Exa: `dashboard.exa.ai`
   - Jina: `jina.ai`
   - GitHub fine-grained tokens: `github.com/settings/personal-access-tokens/new`, with the scopes the registry names
   - Telegram: `@BotFather`
   - Greptile, CodeRabbit and firecrawl.dev: their dashboards.
3. **Check, then verify.**
   - `just keys` (also run by `just install`) first asks `sudo-secretspec check` which keys are present. It never
     reads or prints a value.
   - For each present key it runs the verify probe under `sudo-secretspec run`. The probe is the provider's cheapest
     read-only authenticated call (for example, listing models), with argv lists, the key in a header read from the
     environment, and a short timeout. It records only the outcome:
     - `ok`;
     - `invalid` (HTTP 401 or 403);
     - `no-quota`;
     - `unreachable`;
     - `expiring <date>`.

     Outcomes go in `~/.local/state/djbclark-ade/keys.json`, written atomically, with no value and no hash of one.
   - A probe never spends money, never posts, and is rate-limited to one per key per run.
4. **Collect in one batch, one key at a time.** After the check, it prints one list of every key that is missing or
   failing, with its purpose and URL, and asks once whether to enter them now.
   - For each key in turn it shows the name, what uses it and the URL, then runs `sudo-secretspec set NAME`. That is
     sudo-secretspec's own no-echo prompt at a real terminal, so the value never passes through djbclark-ade, an
     agent or a chat.
   - It verifies the key straight away and offers retry, skip or "skip all".
   - It ends with a table: each key, ok, skipped or failed.
   - It reuses sudo-secretspec's `secrets-collect` where that already does the batch (it exists upstream; check its
     flags when building). It is not reimplemented.
   - In the AI-assisted setup (S3a.3) the agent stops at each key and the user types it into the prompt themselves.
5. **Deliver to Paseo and the tools, only through a secure store.**
   - First probe whether Paseo has a secure credential store for provider keys (the Keychain on the Mac, a 0600 file
     or the Secret Service on Linux), not one in a plaintext config, and how a key is written to it without echo.
     The answer is recorded with its date.
   - **If it does,** `just keys` writes each key the registry marks for Paseo from inside `sudo-secretspec run`, with
     the value passed on stdin or in the environment, never in argv.
   - **If it does not,** nothing is copied into Paseo's config. Paseo gets keys at launch instead: the daemon, or the
     provider's launch, runs under `sudo-secretspec run`. That matches review rule 3: the one place a key is written is
     a third-party tool's own credential store.
   - The same rule applies to every TUI's own store, for example Pi's own provider credential store and Hermes' Keychain items. A retired client's store is not copied into Pi.
6. **Kept current:**
   - The daily `just update --auto` (S4) runs `just keys --check`, which verifies and never prompts. It pings the
     operator about any key that is invalid, out of quota or expiring within 14 days, with the URL to replace it.
   - `just doctor` shows the same table.
   - A key replaced with `sudo-secretspec set` is re-delivered by the next `just keys`.

## S4. Updates and keeping everything current

1. **`just update`** updates every installed component in `[install]` with that component's own update command:
   - djbclark-ade itself, as `bin/ade-update` does today (fast-forward, relink, changelog delta);
   - the site repository and the external skills;
   - Paseo, its skill bundle and each plugin;
   - sudo-secretspec, aiuse, cswap, graft, gh and the modern-CLI tools;
   - the provider CLIs;
   - the chosen offered components: Hermes, peer-link, the LiteLLM fork through its upstream-tracking rule, standing
     order 8.

   It ends with `just doctor`.
2. **Automatic:** `bin/ade-sched` installs a daily `just update --auto` job.
   - It fast-forwards only (never merges or rebases).
   - It skips while a Paseo agent is mid-turn on the machine.
   - It pings the operator on failure.
   - A component whose upgrade breaks `just doctor` gets one retry and is then reported, never rolled back silently.
3. **New components:** a component added to `[install]` on master is installed on each machine by that machine's next
   `just update`, so adding a dependency is one table entry and one PR.

### S4b. Scheduled jobs and services

Operator, 2026-11-07: install and update manage every scheduled job and service that is reasonable to manage. On the
card the operator chose "ours, plus checks": djbclark-ade manages its own jobs and checks the rest.

1. **One inventory**, `config/ade.toml [install.jobs]`. Each entry has:
   - name;
   - kind: launchd agent, systemd user timer, cron (only where neither of those exists), Paseo schedule, or service;
   - owner: `djbclark-ade`, the site repo, or a dependency;
   - schedule and command;
   - for a Paseo schedule, its explicit `--mode` (`auto` / `auto-review`; never left out, `docs/scheduling.md`);
   - its class from S3.2 (hard, offered, optional).
2. **djbclark-ade's own jobs** are rendered and installed by `bin/ade-sched`: launchd on the Mac, systemd user timers
   on Linux, cron otherwise.
   - Today's list: `load-watch sample`, `deadline-sweep`, `pr-policy`, the daily `just update --auto` (S4), the daily
     `just harden-check` (S6) and `just keys --check` (S3b).
   - Paseo schedules (the context-budget check C69, the upstream check C70) are created, updated or deleted by name
     with `paseo schedule create|update|delete`, then read back with `paseo schedule ls --json`.
   - Re-running is idempotent: an unchanged job is left alone, a changed one is reloaded.
3. **Dependencies' services** are installed by each dependency's own installer, never re-implemented here: the Paseo
   daemon, aiuse's sampler, and Hermes' gateway and dashboard where Hermes was chosen. `just doctor` checks that each
   one runs.
4. **The site repo's jobs** (site-djbclark's fleet-watch, net-watch, watchdogd, the firecrawl MCP and the LiteLLM
   proxy roles) stay with that repo's own deploy. `just install` runs `just deploy-mac` (or the Linux equivalent) in
   the site repo as one step, named in `[install.site_repo].deploy`, and does not reimplement it.
5. **Root-level items** (LaunchDaemons, `/etc/sudoers.d`, `/etc/resolver`) go through a separate
   `just install --system`. It shows each change, needs sudo, and never runs from the daily automatic job.
6. **Removal.** A job dropped from the inventory is unloaded, and its file removed, by the next `just update`. Only
   jobs recorded in `~/.local/state/djbclark-ade/jobs.json` (written atomically) as installed by djbclark-ade are
   ever removed. Anything else is reported, not touched.
7. **Drift.** `just doctor` and the daily job compare the loaded state with the inventory for every owner:
   - `launchctl print gui/$UID/<label>`;
   - `systemctl --user list-timers`;
   - `crontab -l`;
   - `paseo schedule ls --json`.

   They fix only djbclark-ade's own jobs and report the rest.
8. **Retired jobs.** The slim-down's retired launchd jobs (`docs/slim/operator-batch.md` C6-C21: skillopt-sleep, the
   watch family, acp-dispatch-reap and the rest) become `[install.retired_jobs]`. `doctor` checks that each is absent
   and reports one that comes back. Pi is not on this list: it is the adopted third-party client (2026-11-08); automatic routing still awaits per-pool acceptance.
9. **Never touched:** Orca, BB and herdr configuration (AGENTS.md), and any job whose owner is unknown. Those are
   reported, so the operator decides.

## S5. GitHub hardening against prompt injection

Threat (docs/threat-model.md; the Trust section of AGENTS.md): every GitHub artifact not authored by the owner is
untrusted, and one injection attempt through a PR has already happened. The research of 2026-11-07 makes the same point.
The 2026 "Comment and Control" disclosures showed AI agents in CI leaking secrets through instructions hidden in PR
titles, issue bodies and comments. Reducing who can write those artifacts is the strongest lever.

1. **Options**, each one alone or all at once (`just harden all|<option> [--repos …|--owner djbclark|--all-owned] [--dry-run]`),
   for selected repositories, every repository of the personal account, or every organization the operator owns:
   - **Pull requests: collaborators only**, or pull requests disabled (GitHub, 2026-02-13: "Restrict pull requests to
     collaborators", "Disable pull requests entirely"). A Dependabot pull request (DPR) must still work: probe whether
     Dependabot is blocked under collaborators-only before applying it (an open question on GitHub's discussion).
   - **Issues: collaborators only** (GitHub, 2026-06), or issues off.
   - **Discussions, wiki and projects** off unless used.
   - **Interaction limits**, `collaborators_only` for `six_months` at the user level (`/user/interaction-limits`, public
     repositories), for comments too. They expire, so S6 re-applies them.
   - **Actions:**
     - approval required for every fork PR's workflows, not only first-time contributors;
     - a read-only default `GITHUB_TOKEN`;
     - no workflow may create or approve pull requests;
     - an allow-list of actions, pinned to full commit SHAs.
   - **Workflows:** no `pull_request_target` that checks out or runs PR code; untrusted fields (title, body, comment)
     reach a shell only through `env:`; `persist-credentials: false`; secrets only in protected environments (as
     `merge-gate` already does).
   - **AI reviewers on outside content:** Codex, Cursor and Copilot reviews and any AI workflow run only for owner-
     authored PRs, or by hand. No AI step whose input is outside content gets a write token or a secret.
   - **Agent reads:** the GitHub MCP server's lockdown mode (`--lockdown-mode`, `GITHUB_LOCKDOWN_MODE`,
     `X-MCP-Lockdown`), which filters content from users without push access. It is a best-effort filter, not a
     boundary; the repo's "untrusted data" briefs stay.
   - **Rulesets:** the merge-gate ruleset (adversary-marker plus CI, pinned App IDs, no bypass actors) on every
     repository that takes agent PRs; push protection and secret scanning on.
   - **Scanners:** `zizmor` in CI over `.github/` (template injection, broad permissions, mutable tags, risky
     triggers). GitHub's "code scanning for AI applications" (public preview, 2026-10-28) needs Advanced Security:
     probe whether it is available to this account before listing it.
2. **Policy as data:** each option is a key in `[hardening]` (on, off or ignore, per owner and per repository). `just
   harden` applies the diff between that table and what the GitHub API reports.
3. **Personal account, not an org:** GitHub's `safe-settings` App enforces settings for an organization, but djbclark's
   repositories are personal. So the applier is our own `bin/ade-harden` over `gh api`, with `safe-settings` as the
   model. A setting with no API is a browser task (S7).

## S5a. A typed classifier as an extra injection gate

The hardening in S5 reduces who can write outside content; this section adds a
cheap probabilistic reader-side gate for the content that still reaches agents.
It is built and measured **before** the final code and security reviews of any
reader that gets it (the order the operator set 2026-11-07): a gate that has
not been measured on our own traffic is a false sense of security, not a gate.

1. **What the gate is.** `bin/ade-injection-gate` — one shared tool every
   outside-content reader calls (`pr-policy`, `review-pr`, `skills/loose`,
   the Jira and firecrawl readers, and any agent brief that carries quoted
   outside text; plus `fleet-watch`, which lives in site-public-djbclark, so
   its hold is an out-of-repo integration to wire and verify from there —
   pending this repo's build). It sends the text as `state` with one fixed
   `choice` question (injection vs benign, the eval's prompt shape) and
   returns the probability distribution, the `decide` at the thresholds
   below, and the latency. The classifier is Jev (TypeSafe hosted,
   `jev-latest`) — the only
   one of the three measured models that separates injection from benign text
   (2026-11-07 eval: 32% recall at the 0.9 bar, 1.3% FP, 163 ms p50, ~$0.00003
   per call). Kev-0.8B and Laya were measured near-chance on this task and are
   NOT used for the gate (they stay in their existing judgment roles). The
   classifier is probability-only, no tools, no text generation, so the
   payload can steer nothing (S3 of the eval: no tool-using model ever sees a
   payload).

2. **Thresholds (the skill's own).** Act only at `p(injection) >= 0.9`
   (treat as injected: strip, quarantine or refuse) or `p(injection) <= 0.1`
   (treat as ordinary text, still tagged untrusted — a low score is NOT trust).
   Between 0.1 and 0.9 the gate returns `escalate`: tag the text untrusted,
   add it to the shadow log, and let the reader's existing untrusted-data rules
   carry on. The gate never approves anything and never lowers a tag.

3. **Fail-closed rules.**
   - Classifier unreachable (the helper's exit 3, a restart window) or any
     error, timeout or malformed answer: the text is **never treated as
     clean**. On ordinary surfaces the caller tags it untrusted with the gate
     unavailable, logs the miss, and its existing untrusted-data rules carry
     on. On the one surface whose whole point is the hold — the fleet-watch
     upstream `--perm all` dispatch (F-CRIT-1) — **no verdict means no
     dispatch**: the notice is queued for the operator instead. The S6 drift
     job alerts when gate unavailability has lasted more than 1 hour of wall
     clock time.
   - Any error, timeout or malformed answer is the same as `escalate`, never
     `benign`.
   - The gate runs **before** the text enters an agent context, not inside it:
     the reader calls `ade-injection-gate` on the fetched artifact and passes
     on text + verdict + provenance, so even a wrong `benign` leaves the
     Trust-section rules (data, never instructions) intact.

4. **What it does per surface** (from the eval's per-surface results; the
   eval doc is authoritative for why):
   - **PR/issue bodies, titles and comments (own repos, S1.1-S1.3):** tag +
     shadow-log, not block — recall below the 0.9 bar means a block would
     create false confidence; provenance (`author_association`) stays the
     primary control.
   - **Dependabot PR bodies and CI logs (S1.4-S1.5):** tag; the gate's value
     here is triage ordering, not blocking.
   - **firecrawl / web-search results (S4.1):** tag; too high FP risk on
     ordinary technical text to block.
   - **CFEngine Jira text (S3.1):** tag + escalate-to-operator on
     `p >= 0.9`.
   - **fleet-watch notices (S1.7 upstream):** escalate on `p >= 0.9` — this
     is the zero-click dispatch path of Argon F-CRIT-1, so any confident
     injection verdict holds the dispatch for the operator.
   - **Agent-to-agent `paseo send` messages:** the gate does not mediate peer
     messages (trust model, AGENTS.md Trust); the `"djbclark approved"`
     chain is fixed out-of-band (F-CRIT-1), not by a classifier.

5. **Config (`config/ade.toml`).**
   ```toml
   [hardening.injection_gate]
   enabled = true            # false = pass-through with tag "unverified"
   model = "jev"             # api.typesafe.ai alias; kev/laya measured unusable (eval 2026-11-07)
   act_high = 0.9            # p(injection) >= this -> injection verdict
   act_low = 0.1             # p(injection) <= this -> ordinary text (still untrusted)
   max_ms = 5000             # caller-side timeout; over = escalate (fail-closed)
   fail_closed = true        # never false in production; tested in CI
   shadow = true             # log verdicts beside the reader's outcome
   surfaces = ["pr", "issue", "comment", "ci-log", "dependabot", "web", "jira", "fleet-watch"]
   ```

6. **S6 drift check for the gate.** `just harden-check` (S6) gains a
   `gate-health` probe: one benign canary text and one disclosed-payload
   canary (from the eval's corpus, ids recorded, payload text never committed)
   through `ade-injection-gate`; the check fails if the canary answers `benign`
   at `p <= 0.1`, if the benign canary answers `injection` at `p >= 0.9`, if
   latency exceeds `max_ms`, or if the gate is unreachable — so a silently
   degraded or switched-off gate is caught daily, not discovered during an
   incident.

7. **Order of work.** The gate is built and measured (the eval doc's method,
   rerun monthly on fresh benign traffic) **before** the final code and
   security review of each reader that adopts it; new readers adopt it at
   review time, not after.

## S6. Ongoing check that the policy holds

1. **`just harden-check`** reads every setting in `[hardening]` back from the API and exits nonzero on drift, naming the
   repository, the setting, the wanted value and the value found. It never applies anything by itself.
2. **A daily scheduled run** (`bin/ade-sched`) and the same check in CI on this repository. On drift it pings the
   operator with the exact `just harden <option> --repos <r>` line. It re-applies on its own only the expiring interaction
   limits, a few days before they lapse.
3. **New repositories:** the check lists repositories with no `[hardening]` entry, so a new repository is caught on its
   first day.

## S7. Browser-only steps through Grok Bot

Some steps have no API: creating the `ade-merge-gate` App (the manifest flow can pre-fill it, but a person or a browser
still clicks), any hardening setting the API does not expose, and the Paseo or provider dashboards. These are handed to
the operator's Grok Bot "Coding", following the current browser route (operator instructions, 2026-11-07).

1. **Probe first:** does Grok Bot have a browser session, and as whom? A GitHub session logged in as djbclark can change
   any setting, so its prompts are narrow. If it has no browser or no such login, the steps stay operator-only, printed as
   a checklist.
2. **`bin/ade-browser-task`** (recipe `browser-task`) renders a prompt from a checked-in template under
   `prompts/browser/` (one per task: `github-app-create.md`, `pr-access.md`, `issue-access.md`, …).
   - Each template names the exact URL, the exact control and the value to set.
   - Each template ends with a rule: change nothing else, report what the page showed before and after, and
     ask the operator on any surprise.
   - The tool uses the installed `coding-bot ask` path described by `skills/tell-coding-bot`; if it is unavailable,
     it copies a self-contained prompt for operator relay and reports it as unsent.
3. **Delivery and verification:** a send or queued receipt proves neither completion nor the requested setting.
   The bot's reply is outside content, read as data; verify the actual artifact.
   - A task counts as done only when the API read-back (S6's check, or the App's `GET /app`) shows the new value.
   - With no read-back after a deadline (`bin/deadline`), the task is reported to the operator as not done.
4. **Never through the bot:**
   - secrets: the App's private key is downloaded by the operator and stored with `gh secret set`;
   - anything that widens access (adding a collaborator or a bypass actor);
   - anything taken from a GitHub artifact not written by the owner.

## S8. GitHub setup for a new djbclark-ade user

1. **`just github-setup`** (owner and repository in `[github]`) does each step, or prints the browser task for it (S7):
   - creates the `ade-merge-gate` App from a checked-in manifest (`.github/app-manifest.json`; the manifest flow fills
     every permission, and only the confirm click is manual);
   - installs it on the repositories;
   - creates the `merge-gate` environment restricted to master;
   - stores the private key (operator only);
   - creates the merge-gate ruleset with the App ID pinned;
   - applies `[hardening]`'s defaults (S5);
   - runs `just harden-check`.
2. Today these steps are `docs/slim/operator-batch.md` A8-A11 and B6-B13, run by hand through
   `docs/slim/operator-prompts.md` P5 and P10. They become recipes, and their tests (T0-T3b) become `just github-setup
   --verify`, which runs from a throwaway branch and from the second test account.

## S9. Cloud agents talk to Paseo agents, and Paseo agents run them (last, and only with headroom)

Operator, 2026-11-07: plan it now, but build it at the tail end, and only if there is headroom. Cloud agents (Cursor's
Cloud Agents, Claude Code cloud sessions, Codex cloud) should be able to message our Paseo agents, and Paseo agents
should be able to start and manage them.

1. **Paseo agents start and manage cloud agents.** Each kind gets a thin, Paseo-callable tool for start, status,
   send, stop and fetch-result.
   - Cursor: `bin/cursor-cloud` exists already (2026-10-20) and is the model.
   - Claude Code cloud: the session API that claude.ai/code exposes, with create, send and archive; whether it is
     reachable from the Mac is to be checked.
   - Codex cloud.
   - Each is wrapped so `paseo` sees it, either as a Paseo provider if Paseo supports remote providers by then, or as
     a skill plus a `bin/` tool.
2. **Cloud agents message Paseo agents.** A cloud agent cannot reach the Mac's Paseo daemon directly, so it needs an
   inbound path. Options to weigh at the time:
   - a mailbox on GitHub (a private repo or issue that the Mac polls);
   - a small relay on a host we control (vps-primary or Hyades), reached over Tailscale;
   - Paseo's own remote or relay feature, if it has one by then.

   Every message is signed with the agent-to-agent scheme decided for item 24 (signed messages, plus operator approval
   tokens for high-impact actions). A cloud agent reads outside content too, so its messages carry the provenance
   label and never count as operator approval.
3. **Order:** after S1-S8, the item-24 signing, and the injection-classifier gate (S5a). Built only if the plan's
   headroom allows; otherwise it stays here as a plan.
4. **Also weigh: djbclark-ade, and maybe a Paseo daemon, inside each cloud instance** (operator, 2026-11-07).
   - (a) **A stripped-down "cloud" install profile:** `just install --profile cloud`, which installs:
     - AGENTS.md and the skills;
     - the tools that need no Mac (route_agent's policy reader, `adversary_marker.py`, review-launch, the
       message-signing tool from item 24);
     - the trust rules.

     It runs from each platform's own setup hook: a Claude Code cloud environment's setup script, Cursor's
     environment and install step, Codex cloud's setup script. Expect it to be cheap and useful: every cloud agent
     follows the same rules and tools as the local ones. It installs no secrets, holds no operator keys, and runs no
     scheduled jobs.
   - (b) **A Paseo daemon in each cloud instance,** paired with the Mac's Paseo as a remote host. Paseo already knows
     saved hosts; paseo-runner's `sync-plugins.mjs` walks them. If pairing works, the Mac could start, message and
     manage cloud agents with plain `paseo` commands, and cloud agents could message back through the same link.
     Open questions:
     - can a cloud daemon pair through an outbound-only connection (cloud containers take no inbound connections and
       sit behind an egress proxy)?
     - does a short-lived container's daemon survive its session?
     - what does the pairing credential let a cloud agent do on the Mac's daemon?

     Treat it as an experiment. It is adopted only if the pairing can be scoped so a cloud agent cannot start, steer
     or approve Mac agents beyond signed, provenance-labelled messages. Otherwise items 1 and 2 stand.

## Implementation contracts (2026-11-07)

These clarify the plan after source inspection and the independent Astra advisory; they do not claim implementation
or live verification. The operator's S4b/S5a/S9 text above is preserved. Build these contracts before relying on their
safety properties, and keep existing readers unchanged until their adoption is reviewed.

1. **First bounded S1/S2 unit.** Add a versioned effective-config reader, checked schema, legacy projection,
   nonsecret source provenance and thin `just config-check` entry point. No installs, schedules, key/network probes,
   live config writes or consumer behavior switch. Publish one explicit projection table covering routing's current
   `[[service]]`, `[lead]`, `[dispatch]`, `[substrate]`, `[hermes]`, `[calibrate]` and gate floors; do not implicitly
   nest the entire old routing file. Preserve `ROUTING_POLICY` and `GATES_TOML` as isolated legacy-format overrides.
   Missing new config may project legacy; malformed or unknown-version new config must fail, including invalid local
   overrides. Recursive table merge keeps siblings; whole-array replacement does not concatenate services.
   Preserve existing policy bounds and failure behavior. Fixtures must prove equivalence, override precedence,
   type/identity failures and no writes. Comment-preserving atomic `set` (`ade-config set`, 2026-11-08) lands
   before adopting editable config as a live consumer switch; see `docs/config-migration.md` C2.
   Bootstrap Python 3.11+ before relying on `tomllib`. The typed install catalog, observe-only doctor
   (`probe_argv` when recorded), bounded user-scoped `ade-install apply`, and `--system --dry-run`
   preview of `system_argv` (`config/install.toml`, `bin/ade-install`, `bin/ade-user-install`,
   2026-11-09) follow; see `docs/install-catalog.md`. Live system apply / ownership-aware reconcile
   remain later.

2. **One desired job specification.** The TOML inventory feeds `Job.from_dict` and the existing `ade-sched`
   renderers. Existing plists are compatibility inputs until migrated, not a second editable authority. Distinguish
   timer/service lifecycle from launchd/systemd/cron/Paseo backend; cron does not supervise services. Use stable logical
   job identities, typed schedules/timezones and argv commands, with runtime IDs in local state. Update
   `docs/scheduling.md` when adopting the new source of truth. Explicit Paseo modes are validated, never guessed.
   Curate retired job IDs from the operator batch: its range also contains non-job operations. Retired entries only
   check absence. Pi is the adopted third-party client (2026-11-08), not a retired component or job; per-pool routing remains subject to acceptance.
3. **Authority and selection.** ADE directly reconciles only its recorded user jobs. Dependency installers and site
   deploy remain their owners' paths; plain doctor observes/reports, while requested repair or automatic update may
   reconcile only ADE scope. Root effects require the separate shown `--system` transaction; `--auto` must not reach
   root effects indirectly through another installer. Existing unrecorded installations require verified adoption;
   name prefixes and generated comments establish no ownership. Unknown owners, Orca, BB and herdr stay untouched.
   New hard requirements can be installed by update; offered, optional and commercial additions require an existing
   recorded choice rather than automatic opt-in.
4. **Recoverable, idempotent reconciliation.** Keep a versioned ownership ledger with generation, logical ID,
   host/user scope, backend/runtime identity, exact managed paths, nonsecret spec/artifact hashes and verification.
   Under one reconciliation lock, persist pending intent before writes and committed ownership only after read-back.
   Intent alone is no removal authority. Recover interrupted operations by checking exact state, reporting conflicts
   rather than deleting broadly. Missing/invalid ownership state means no removal. Preserve old/new identities across
   backend migration and verify absence before completing removal. Distinguish unknown/error observations from absent.
   Unchanged healthy jobs receive no writes/reloads; compare desired, last-applied and actual effective definitions.
5. **Preserve active work.** Disruptive update, reload, migration or removal needs shared admission and per-job
   activity evidence, not just one idle-agent snapshot. Unknown or busy state defers durably. Drain running work
   without killing or restarting paid runs; defer if the backend cannot stop future triggers safely. Do not reload
   the updater's own running service: leave its next generation pending. Until all launch paths participate, report
   conservative deferral rather than claiming race-free quiescence. Linux user-manager/linger prerequisites stay
   explicit; an unavailable systemd user manager is not a reason to silently switch to cron.
6. **S5a verdicts and actions are separate.** Keep one typed classifier result and the per-surface action matrix.
   Ordinary GitHub/web surfaces retain tagging/shadow behavior; fleet upstream dispatch requires an actual verdict.
   Disabled, unavailable, timeout or malformed gate output cannot authorize that dispatch, including when a global
   enable switch would otherwise pass through. Keep measured thresholds and recall limitations; never promote
   classifier output to trust or operator approval. Record payload-free IDs, provenance and verdict/health metadata.
   Before hosted processing of private text, define eligible payloads and retention for that reader. Canary integration
   needs an authorized fixture/provisioning source; never read the retained evaluation cache to obtain one. The
   injection canary must classify as injection and the benign canary as benign. Reader failure timestamps plus an
   existing health path at a specified sub-hour cadence support the one-hour outage alert; daily canaries are separate.
7. **S6 checks remain checks.** Keep `harden-check` read-only. A separately authorized automatic-update operation may
   renew only the configured expiring interaction limit after checking the exact target/current state and reading it
   back. No other hardening repair is implied by daily checks. Browser-bot replies and queued messages are not proof
   of completion; retain API or artifact read-back.
8. **S9 signing prerequisite.** “Item 24” in S9 means the operator's planned signed-agent-message contract, not
   Carried 24 in `docs/queue.md`. Define versioned sender/provenance, recipient, payload integrity, expiry and replay
   handling before choosing a transport. A cloud signature authenticates a message, not an operator approval; require
   separate operator tokens bound to high-impact actions. The cloud profile installs the signing tool with no keys
   or authority. Evaluate scoped runtime agent identity later; never ship an operator/shared signing private key.
   Cloud APIs, outbound pairing and credential scope remain unverified. Reject pairing that exceeds signed-message
   authority. No S9 experiment, installation or routing change occurs before its stated prerequisites and headroom.

## Sources (2026-11-07)

- GitHub changelog, 2026-02-13, new repository settings for pull request access:
  https://github.blog/changelog/2026-02-13-new-repository-settings-for-configuring-pull-request-access/
- GitHub docs, disabling pull requests:
  https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/disabling-pull-requests
- Visual Studio Magazine, 2026-06-30, issue creation limited to collaborators:
  https://visualstudiomagazine.com/articles/2026/06/30/github-extends-contribution-controls-from-prs-to-issues.aspx
- GitHub REST, repository interaction limits: https://docs.github.com/rest/interactions/repos
- CSA research notes on "Comment and Control" and on prompt injection in AI GitHub Actions:
  https://labs.cloudsecurityalliance.org/research/csa-research-note-comment-control-github-prompt-injection-20/ and
  https://labs.cloudsecurityalliance.org/research/csa-research-note-ai-github-actions-security-20260503-csa-st/
- GitHub MCP server lockdown mode: https://github.com/github/github-mcp-server/pull/1391 and
  https://github.blog/changelog/2025-12-10-the-github-mcp-server-adds-support-for-tool-specific-configuration-and-more
- GitHub `safe-settings` (policy as code, drift reverts): https://github.com/github/safe-settings
- zizmor (Thoughtworks Radar): https://www.thoughtworks.com/radar/tools/zizmor; WordPress Actions standards:
  https://developer.wordpress.org/coding-standards/wordpress-coding-standards/github-actions/
- GitHub code scanning for AI applications (2026-10-28):
  https://pondero.ai/news/2026-10-29-github-ai-code-scanning-prompt-injection/
