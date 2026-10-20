# Threat model: djbclark-ade (2026-10-20)

Snapshot **2026-10-20**, written for reviewers (Codex's GitHub security review reads this file for every
PR; the `adversary` sub-agent and Cursor's review checks may too) and as the baseline the ADE-everywhere
plan ([ade-everywhere-proposal.md](ade-everywhere-proposal.md) sections 1-4 and 11) assumes. Every claim
names the file that shows it; a claim without a file is the operator's statement and is marked
"operator". Re-read the code before relying on a line here: facts rot.

This repo is **personal tooling for one operator's machine, published as a public GitHub repo by
choice** (`djbclark/djbclark-ade`). It is not a service, has no inbound network listener, and holds no
secret values. What makes it security-relevant is that it launches AI agents that run commands as the
operator, unattended, and moves their output around.

## 1. Scope and assets

What an attacker would want, in order of damage:

1. **Secrets in the `sudo-secretspec` vault** (API keys for model vendors, Cursor, Z.ai, Forgejo and
   others). Not in this repo. The boundary authorizes the operator identity: any process running as
   the operator that passes it can read every declared secret; client-family labels are correlation
   metadata, not principals (proposal 4.5 item 1). `get` and `export` print values to stdout
   (`~/.claude/skills/sudo-secretspec/SKILL.md`, Pitfalls); `run` injects them into a child.
2. **Code execution as the operator.** acp-run runs every agent yolo (all tool calls auto-approved;
   only `--perm deny` is a gate, operator 2026-10-14; `tools/acp-run/README.md` Permissions). The
   proposal says outright that an unattended builder has the daemon user's credentials and that
   scrubbed pastures and config stripping are reliability switches, not a boundary (proposal 10, risk 12).
3. **GitHub write access** through the operator's `gh` login: push to this public repo, open and
   merge PRs, which here means changes to code that the operator's machine then runs.
4. **Cloud-agent credentials and spend**: `CURSOR_API_KEY` (`bin/cursor-cloud`) and the Codex/Cursor
   GitHub apps' access to this repo (`docs/queue.md` line 19-21).
5. **Agent state under `~/.local/state`**: dispatch records and reports (`~/.local/state/bigteam/<task>/`,
   `bin/acp-dispatch` `STATE_ROOT`), `~/.local/state/acp-dispatch/`, `~/.local/state/load-watch/`
   (`bin/load-watch` header), `~/.local/state/zcode-key-auth/`. Records name the commands launchd will
   run.
6. **Transcripts**, which hold whatever agents printed, occasionally a secret (proposal 4.5 item 5).
7. **The Hermes/Telegram channel**: a message path to the operator's phone, and two-way tools
   (`mcp__hermes__*`, `docs/mcp-servers.md`).
8. **launchd jobs** that persist across logins: `launchd/*.plist` (acp-dispatch-reap, context-budget,
   load-watch, routing-recalibrate, skillopt-sleep, zcode-key-auth) plus per-slice `launchctl submit`
   jobs (`bin/acp-dispatch` `runner_script`).
9. **The operator's machine itself** (a 16 GB Mac): availability under agent fan-out
   (`bin/acp-dispatch` `machine_overloaded`, load reached 230 on 2026-10-12).

## 2. Trust boundaries and actors

| Actor | Trust | Notes |
|---|---|---|
| The operator | Full | The only principal. One person, one personal machine. |
| Local agent TUIs and ACP sub-agents (`acp-run`, `acp-dispatch`) | **Trusted as the operator** (home rule 24: a peer's "djbclark approved" is approval) | But **prompt-injectable**: they read fetched web pages (`bin/web-get`, firecrawl MCP), third-party repo content, tool output and each other's reports. An injected agent acts with the operator's rights. |
| Cloud agents: Cursor Cloud Agents (`bin/cursor-cloud`), Codex review | **Untrusted writers, trusted-ish readers** | They run off the Mac, get the repo URL and a prompt, and push branches to a **public** repo (`cursor/...`, or `--work-on-branch` the starting ref). Codex is a PR reviewer only today (`docs/queue.md`). They hold no vault access. |
| Hermes bot (`~/.local/bin/hermes-ping`, `mcp__hermes__*`) | Trusted channel, outside this repo | `hermes-ping` is one-way (home rule 12). The MCP bridge is two-way: read/send messages and `permissions_respond` on Hermes's approval queue (`docs/mcp-servers.md`). |
| GitHub Actions runners | Untrusted compute, no secrets | `.github/workflows/test.yml`: `permissions: contents: read`, triggers `push` to master, `pull_request`, `workflow_dispatch`; runs `pytest` on macOS and Ubuntu; no `secrets.*` referenced. |
| vps-primary | **Trusted** (proposal decision Q18, 2026-10-19) | Future state: holds plaintext sessions and keys. Its compromise exposes every session (proposal 10, risk 10). Not part of the Mac code today. |
| Third-party MCP servers (`docs/mcp-servers.md` roster: hermes, beeper, hindsight, ghost-os, claude.ai connectors, ...) | Run as the operator or are remote | Twelve are denied in Claude Code via `deniedMcpServers` since 2026-10-10 (`docs/mcp-servers.md`). `graft` MCP removed 2026-10-18. The roster table is a 2026-08-23 snapshot. |
| Third-party PR authors and issue commenters | Untrusted | Anyone can open a PR or issue on a public repo; only mentions by the operator's apps trigger cloud agents (`@cursor` on a comment, `@codex review`; `docs/queue.md`). |

## 3. Entry points

1. **Prompts and footers written to files.** `acp-dispatch` appends `docs/dispatch-footer.md` to a
   prompt and passes it to `acp-run`; `cursor-cloud launch --prompt-file` sends file text to a cloud agent.
2. **launchd runner scripts built from record fields.** `runner_script` and
   `auto_resume_runner_script` (`bin/acp-dispatch`) write a bash file (mode 0700, `write_atomic`)
   whose values (`record`, `done`, `owner`, `label`) come from the record and go through `shlex.quote`;
   it is then run by `launchctl submit`. The agent command itself is stored as
   `" ".join(shlex.quote(c) ...)` and re-read with `shlex.split` (`bin/acp-dispatch` lines ~3577,
   ~3102).
3. **`acp-run --verify CMD`**: runs `CMD` as a shell command after an agent turn
   (`tools/acp-run/README.md`, item 13). The one deliberate `shell=True`-style path; the string is
   whatever the caller (operator or a lead agent) supplies.
4. **Load gate.** Today `acp-dispatch` gates on `machine_overloaded()` (in-process `os.getloadavg`,
   capped wait `ACP_DISPATCH_GATE_MAX` 900 s, then starts anyway). PR 7
   (branch `origin/feat/load-admit-gate`, open, not merged) adds `load-watch admit`, whose stdout line
   (`admit ok ...` exit 0, `admit hot ...` exit 75) the dispatcher parses. Treat that output as
   untrusted text: unreadable output must not read as admission (the branch's last commit says it does not).
5. **PR bodies, review comments and issue text written by agents or third parties**, which
   other agents and reviewers then read as instructions.
6. **Mentions**: `@codex review`, `@cursor` on an issue or PR comment (`docs/queue.md`,
   `bin/cursor-cloud` docs). A mention is a trigger a third party could also post if the app allows it
   for them; app settings are outside this repo.
7. **Environment variables.** Runners export `PATH` and `CLAUDE_CODE_SESSION_ID`. The tools read
   `ACP_DISPATCH_*` overrides (`STATE_ROOT`, `ACP_DISPATCH_LAUNCHCTL`, `ACP_DISPATCH_AIUSE`,
   `ACP_DISPATCH_NO_GATE`, `ACP_OPERATOR_APPROVED`, `CURSOR_CLOUD_API`, `ZCODE_CREDENTIAL_SECRET`,
   `LW_STATE_DIR`, `LW_REGISTRY`). An attacker who controls the operator's environment already
   controls the operator; the concern is an agent setting one of these for a child it launches
   (`ACP_DISPATCH_LAUNCHCTL` or `CURSOR_CLOUD_API` repoint a binary or the API endpoint).
8. **Web content and repo files** fetched by an agent mid-session (prompt-injection carrier).
9. **`load-watch` pane typing**: it writes a brief and types one line into an agent session's pane
   via `session-finder/relay.py` (`bin/load-watch` header), so a message the tool composes becomes input
   to a trusted agent.

## 4. Threats, ranked

Ranked by (impact x likelihood) for this repo today. "Control" is what exists; "Gap" is what does not.

### 4.1 Secret exfiltration

* **Control.** Keys are read only through `sudo-secretspec run`: `bin/cursor-cloud` re-executes itself
  under it when `CURSOR_API_KEY` is absent (`REASON`, `cmd = ["sudo-secretspec", "run", ...]`), so the
  value is never in a file or argument; `bin/zcode-key-auth` does the same for
  `ZAI_CODING_PLAN_API_KEY` and prints only hashes (`status`, `fp()`). AGENTS.md "Code review" rule 3
  forbids a key in argv, a log, a tracked file or a fixture. The vault ledger is audited
  (`audit-verify`, skill file).
* **Gap 1.** `get` and `export` print values to the caller's stdout; the client does not redact. An
  injected agent that runs them puts values in its transcript. The boundary does not tell an honest
  agent from an injected one (4.5 item 1 of the proposal).
* **Gap 2.** `bin/zcode-key-auth` writes the key into zcode's own credential store
  (`~/.zcode/v2/credentials.json`), encrypted AES-256-GCM with a key derived from `ZCODE_CREDENTIAL_SECRET`
  or a fallback built from platform, home and user name (file header). Anyone running as the operator
  can derive that key; the store is no stronger than the account. This is the one sanctioned place a
  key is written (rule 3).
* **Gap 3.** Cloud agents get the repo and prompt, not secrets, but a prompt file or a repo file
  that contains a secret would leave the Mac. No scanner runs on prompts (`cursor-cloud` does not check).

### 4.2 Command injection into runner scripts

* **Control.** Every interpolated value in the launchd runner scripts, the printed resume and rearm
  hints and the wait helper goes through `shlex.quote` (`bin/acp-dispatch` `runner_script`,
  `auto_resume_runner_script`, `rearm_cmd`; the many `q = shlex.quote` sites). Subprocesses use argv
  lists (rule 4); the stored command is `shlex.split` back, not run through a shell. Scripts are
  written atomically at mode 0700.
* **Gap.** The records the scripts are built from are plain JSON in the operator's home (4.5), so the
  quoting protects against bad *values*, not a tampered *record*. `acp-run --verify` is a shell by
  design (entry 3).

### 4.3 A cloud agent opens or merges a PR, or pushes where it should not

* **Control.** `bin/cursor-cloud` sends `autoCreatePR: False` on every launch (`launch_body`; docs say
  never). The agent pushes to a `cursor/...` branch; the lead opens the PR after an `adversary` verdict,
  and merges with `gh pr merge --squash --match-head-commit <reviewed sha>` (AGENTS.md Code review
  rule 1, branch `origin/docs/code-review-rules`, PR 9). Codex is reviewer-only (`docs/queue.md`).
* **Gap 1.** `--work-on-branch` makes the agent push to the named `--ref` itself, including a
  non-feature branch, if the GitHub app's token can. The only guard is the lead's choice of `--ref`.
* **Gap 2.** Branch protection or rulesets on this repo: `docs/coding-factory.md` (2026-09-21) records
  them absent on every repo, then unavailable because the repo was private on a free plan. The repo has
  been public since 2026-10-08, so they may now be available, but **no current check is recorded**.
  Without them, a token that can push can push to `master`.
* **Gap 3.** Cursor's Approval Agent is reported by the operator to auto-approve; it is a review
  *signal*, not a gate (operator, 2026-10-20; no repo file records it). Do not count it as a control.

### 4.4 Prompt injection of an agent (local or cloud)

* **Control.** Briefs are scoped (`docs/orchestration-practices.md` section 2: give each worker only
  what it needs); reviewers are read-only and `--perm deny` exists for a security-sensitive slice
  (home rule 16); `adversary` reviews before a PR. Cloud agents run off the Mac with no vault.
* **Gap.** A local agent reading a hostile page or a third-party file runs yolo with the operator's
  rights, and nothing screens tool output for instructions. A cloud agent reading the public repo's
  own issue or PR text can be steered by a third-party commenter if a mention triggers it. Mitigation is
  procedural: mentions only by the operator, human merge, exact-head verdicts.

### 4.5 State tampering under `~/.local/state`

* **Control.** Files are written atomically (`write_atomic`, `os.replace`; rule 6) and new record
  fields are read with `.get`. Record updates take a lock (`update_record`, "under the record's lock").
* **Gap.** The record is the dispatcher's source of truth for what a launchd job runs, and it is
  unsigned and unauthenticated. Any process running as the operator can edit a record, a runner or a
  `ci-only.tsv` registry (`~/.config/load-watch/ci-only.tsv`) and have launchd run it later. This is
  accepted (section 5), but it means **a local foothold is persistent** through `acp-dispatch`.

### 4.6 launchd persistence

* **Control.** Plists are installed only by the tools' own subcommands (`acp-dispatch reap --install`,
  `load-watch install`, `zcode-key-auth install`), copied from `launchd/` in this repo to
  `~/Library/LaunchAgents`. Per-slice jobs remove their own label on exit; a sweep reaps dead ones.
* **Gap.** The plist in a PR is code that will run as the operator at every login. Review a plist
  change like a script change: label, `ProgramArguments`, `WorkingDirectory`, `PATH` (the shipped
  plists use fixed paths under `/Users/djbclark/...`).

### 4.7 Supply chain

* **Control.** CI installs with `uv run --with pytest --with 'agent-client-protocol>=0.9,<1.0'`
  (`.github/workflows/test.yml`); `bin/web-get` pins `pypdf==6.19.0`. Actions are referenced by
  major tag (`actions/checkout@v4`, `astral-sh/setup-uv@v6`).
* **Gap.** The ACP client dependency is a range, not a pin; actions are tags, not SHAs; CI runs
  `brew install` from the runner's default taps. The proposal (Q22, 2026-10-19) accepts Homebrew's
  curl-pipe installer for new machines and relies on `tools.toml` pins with checksums for the rest, which
  does not exist yet (proposal 4.4 is a design). Third-party plugins are ordinary dependencies that run
  as the daemon user (proposal 10, risk 14).

### 4.8 Review bypass

* **Control.** AGENTS.md Code review rule 1 (PR 9): the body must quote the adversary verdict and the
  head SHA, and merge uses `--match-head-commit`. Three reviewers run on PR open (adversary, Codex
  auto review, Cursor Security Agent; `docs/queue.md`).
* **Gap.** The PR body is written by the author, so a verdict line is **self-asserted**: nothing
  fetches the adversary's report and compares. A reviewer should treat the quote as a claim and check
  the SHA against the PR head. No required status check enforces review (see 4.3 gap 2).

### 4.9 Denial of the operator's machine

* **Control.** `acp-dispatch` holds a slice before it spawns while `machine_overloaded()` is true, up
  to 900 s (`wait_for_capacity`); `load-watch` finds the session that caused sustained load and tells it
  to move heavy work to CI; `ci-only` makes `bg` refuse local builds (`bin/load-watch` header). Auto-resume
  is capped at 3 attempts and gated on live pool headroom (README `bin/` row).
* **Gap.** The dispatcher's gate starts the slice anyway after the cap. PR 7's `admit` gate adds
  an admission check with stagger and pending-runner accounting; until it merges, a wave of dispatches
  can still overload the Mac, as on 2026-10-12.

### 4.10 Telegram/Hermes as a command channel

* **Control.** `hermes-ping` is one-way and used for notices (`bin/load-watch`, `bin/zcode-key-auth`).
* **Gap.** `mcp__hermes__messages_send`, `events_wait` and `permissions_respond`
  (`docs/mcp-servers.md`) are two-way: an injected agent can message the operator and can answer
  Hermes's pending exec or plugin approval prompts. Inbound Telegram text is data from a channel the
  operator controls, but nothing marks it as non-instruction. The proposal plans a Paseo Telegram
  plugin that would replace the relay (proposal 10, risk 13); it is not built.

## 5. Out of scope and accepted risks

1. **One operator, one personal machine.** No multi-user separation, no defence against another
   process running as the operator (4.1 gap 1, 4.5). Operator-accepted (proposal 4.5 item 1).
2. **Yolo agents** (`acp-run` runs every agent auto-approved; operator 2026-10-14). The mitigation is
   reviewing outputs, not restricting tools.
3. **The repo is public by choice** (since 2026-10-08). Anything committed is world-readable; secrets
   policy depends on rule 3, not on privacy.
4. **vps-primary is trusted** and a compromise there is accepted as total (proposal Q18, risk 10).
5. **Vendor and platform risk**: GitHub, Forgejo, Hyades, model vendors, Cursor and Codex services
   (proposal T4 lists these as accepted outside dependencies).
6. **Fleet notices run from the ops repo**: `fleet-watch` lives at `~/ops/site-private/bin/fleet-watch`,
   not in this repo's `bin/` (AGENTS.md links `bin/fleet-watch`; the file is absent from this tree on
   2026-10-20), so its code is outside this review's reach.
7. **Documents carry dated snapshots**; a mismatch between a doc and the code is a doc bug, not a
   vulnerability.

## 6. What a reviewer should check on a PR

Follow the **Code review** section of [AGENTS.md](../AGENTS.md) (rules 1-8: adversary verdict with
head SHA, no result through a pipe, secrets only via `sudo-secretspec run`, argv lists and
`shlex.quote`, macOS and Linux, atomic records, dated facts, docs move with code). Beyond them, raise
these for this threat model:

1. A new or changed `launchd/*.plist`, `launchctl submit` call, or runner script (4.2, 4.6).
2. A change to who may trigger a cloud agent, `autoCreatePR`, `--work-on-branch`, or a workflow
   `permissions:` or `on:` block (4.3).
3. Any new place a secret value could be printed, stored, passed in argv or sent in a prompt (4.1).
4. New `shell=True`, `os.system`, `eval`, or a string built into a shell command without quoting (4.2).
5. A new dependency, an unpinned install, or a downloaded script piped to a shell (4.7).
6. A new write path to `~/.local/state`, or a new reader that trusts a record field without `.get`
   or validation (4.5).
7. A new two-way channel (Hermes tools, webhooks, mentions) (4.10).
