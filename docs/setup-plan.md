# Setup, hardening and updates: plan (queue Carried 35)

Plan, 2026-11-07, not started. The operator asked for it the same day, in five parts: an easy install on a new Mac or Linux
machine with every dependency and TUI; automatic updates of djbclark-ade and its dependencies; easy setup of the GitHub
pieces a new djbclark-ade user needs (the `ade-merge-gate` App first); prompt-injection hardening of GitHub, both at setup and
on demand, with an ongoing check that the policy stays applied; and one config file for every djbclark-ade option. A sixth
part was added: prompts and code that hand any browser-only step to Grok Bot. The sections below go in build order:
S1 and S2 come first because every later section reads the config and adds a recipe.
The research behind S5 is dated 2026-11-07. Sources are listed at the end, and their facts must be re-probed when the work starts.

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
   - During the migration each tool reads its old file when present. It warns once and prefers `ade.toml`.
3. **Per-machine overrides** go in `~/.config/djbclark-ade/local.toml`, which is never tracked. Values merge table by
   table, and the local file wins. Secrets are never stored in either file: a field names a `sudo-secretspec` key.
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
2. **What it installs**, listed in `[install]` and probed, not assumed:
   - Paseo and the CLI of every provider enabled in `[routing]` (Claude Code, Codex, opencode, omp, Cursor, the
     antigravity provider's login).
   - The modern-CLI tools (site-djbclark's `skills/setup-modern-cli` holds the list; it moves into `[install]` or stays
     there by reference), `graft`, `aiuse`, `gh`, `uv`, `just`.
   - Each skill linked into every TUI (`bin/skill-everywhere --all`).
   - The launchd agents, systemd user timers or cron entries `bin/ade-sched` renders.
   - The secret-deny and hook templates (`bin/ade-template-check`).
3. **How it installs:** Homebrew on the Mac, plus Homebrew or the distribution's package manager on Linux (decided per
   tool, recorded in `[install]`). Each tool is installed by its normal path. Nothing is version-pinned (standing order 8).
4. **Logins** are a checklist, not automated: each provider's own `login` command, and `sudo-secretspec` for API keys.
   `just doctor` reports what is missing, never a secret's value.
5. Starting point: the decided but unbuilt proposal `docs/history/ade-everywhere-proposal.md` (2026-10-20). Keep its
   answered questions and re-base it on Paseo and the slim-down's tool list.

## S4. Updates

1. **`just update`** extends `bin/ade-update`, which today updates only the checkout:
   - djbclark-ade itself, as now (fast-forward, relink, changelog delta).
   - `brew upgrade` or the distribution's upgrade for the tools in `[install]`.
   - `paseo` and its plugins.
   - The provider CLIs.
   - `npx skills` updates for installed skill bundles.
2. **Automatic:** `bin/ade-sched` installs a daily `ade update --auto` job. It fast-forwards only (never merges or
   rebases), skips while a Paseo agent is mid-turn on the machine, and pings the operator on failure. A tool whose upgrade
   breaks `just doctor` gets one retry and is then reported, never rolled back silently.

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
the operator's Grok Bot "Chief of Staff", which acts in a browser.

1. **Probe first:** does Grok Bot have a browser session, and as whom? A GitHub session logged in as djbclark can change
   any setting, so its prompts are narrow. If it has no browser or no such login, the steps stay operator-only, printed as
   a checklist.
2. **`bin/ade-browser-task`** (recipe `browser-task`) renders a prompt from a checked-in template under
   `prompts/browser/` (one per task: `github-app-create.md`, `pr-access.md`, `issue-access.md`, …).
   - Each template names the exact URL, the exact control and the value to set.
   - Each template ends with a rule: change nothing else, report what the page showed before and after, and
     ask the operator on any surprise.
   - The tool sends the prompt through Hermes's `tell_chief_of_staff.py` (skills/tell-chief-of-staff).
3. **Delivery and verification:** that sender is fire-and-forget, and order 10 does not count a send as delivery.
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
