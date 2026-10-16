# Prompt: apply the djbclark / frdminc / Graft development toolchain to a repo

Version 5.11 (2026-10-16). Supersedes 5.10, 5.9, 5.8, 5.7, 5.6, 5.5, 5.4, 5.3, 5.2 and 5.1 (2026-10-09) and Version 5
(2026-10-01, which superseded
`CLAUDE_APPLY_DJBCLARK_TOOLING_Version4.md`). Lived at
`site-djbclark/research/apply-dev-toolchain/CLAUDE_APPLY_DJBCLARK_TOOLING.md`
until 2026-10-09; that path now points here.
Written for `Kuriboh493/perp-option-pricer`; the target-specific facts are
confined to §P0 and §12 so the rest can be reused for another repo.

## Preamble (for the human; not part of the prompt)

This one file is a human preamble (how to use it, how to cut it down to a
budget, what changed since the previous version) followed by the full prompt
for a Claude Code orchestrator session. The prompt installs the
stayturgid/aiuse/site-djbclark quality toolchain, Graft, project subagents, a
curated set of Claude Code skills and plugins, characterization tests,
pre-commit, CI, CodeRabbit and coderabbit-feeder into a target repo, with
backups and restore recipes for everything it touches outside git. Only §P0
and §12 are specific to the current target (`Kuriboh493/perp-option-pricer`);
everything else is reusable. The prompt names private repos only by URL and
contains no credentials.

Here is a prompt you could choose to drop into an **Opus 5.5 session at high
effort** in Claude Code. It orchestrates: the Opus session plans, integrates,
commits and talks to you, and it hands mechanical work to Haiku and Sonnet
subagents, so most of the tokens are spent on the cheaper models.

Alternatively, tell Claude to **read the prompt, consider it, and take no
action yet**, and then ask it to extract a subset that fits roughly the number
of tokens, the amount of money (only if you are on API pay-as-you-go, which I
strongly advise against for this; use a subscription plan and its session
windows instead), or the session time you are willing to spend. Good natural
cut points are the phase boundaries in §3: for example "§1 to §6 only, no
backport, no CI, no CodeRabbit" is a quarter of the work and leaves the repo
strictly better than before.

Practical notes before you paste it:

1. Start the session in a clean checkout of the target repo on its default
   branch, with `git status` clean, and run `/model` to confirm Opus is
   selected. Set effort to high (`/effort high` where the installed version
   offers it; otherwise it is the default for Opus).
2. The prompt assumes Claude Code 2.1.x (October 2026). It tells the
   orchestrator to verify every version-specific detail against the live docs
   at https://code.claude.com/docs/ before relying on it.
3. Everything that needs an account, a password or a decision from you is
   deferred to one interactive phase (§12), one step at a time, so you can walk
   away during the autonomous phases.
4. Nothing outside git is changed without a backup and a restore recipe (§15).
   Read §15.4 at the end to see how to undo any of it.
5. It is long on purpose. A long, specific prompt costs a few thousand input
   tokens once and saves many round trips of clarification; the token rules in
   §0.5 are where the real savings are.
6. **Skip every Crush item unless you drive weak, small-context LLMs with it.**
   djbclark's Crush setup (`crushrc`, `CRUSH.md`, the `crush()` shell function,
   `web-digest`, `web-digest-mcp`, `skill-get`, `crush-context-check`, the
   `sipb-llms-proxy`, the empty skills directory, the denied built-in tools, the
   auto-allow hook) exists only to make Crush + Qwen on SIPB LLMs (32k window) usable. It
   trades away skills, tools, project context and web access to save tokens, and
   it prompts or blocks things a capable model needs. With Claude, Codex, Grok or
   any large-context model, use that agent's own web search, skills and
   project-instruction loading, and use stock Crush with its defaults.

What changed from Version 4, so you can diff the intent rather than the text:
Graft's install and commit policy follow its current upstream README; the
subagent definitions use the current frontmatter fields (`effort`,
`permissionMode`, `maxTurns`, `memory`) and the `fable` alias is explicitly
excluded; a new §0.6 activates a curated set of Claude Code skills and plugins
and explains each one to you; `AGENTS.md` is now the canonical agent file with
a one-line `CLAUDE.md` importing it, because Claude Code only auto-loads
`CLAUDE.md`; the `tendcf` reference was corrected (it uses `core.hooksPath`,
not the pre-commit framework); doc links point at `code.claude.com`; the
missing §14 is gone and sections are renumbered.

What changed in 5.1 (2026-10-09): `sd` is no longer the find/replace tool.
`sd` 1.0 matches line by line unless given `-A` and exits 0 when nothing
matched (upstream chmln/sd PR #347, `--must-match`, is still open), so a
mistyped or multi-line FIND silently changes nothing; it lost an edit on
2026-10-09. `srgn` replaces it in §1.2, §1.3 and §8: it matches across lines
as typed and with `--fail-none` exits 1 when nothing matched. The file also
moved from `site-djbclark/research/apply-dev-toolchain/` to `djbclark-ade/docs/`.

What changed in 5.2 (2026-10-11): a new "Agent web access" table in §1.3
adds web search and fetch for agents with a failover ladder: the keyless Exa
and Parallel Search remote MCP servers, Jina (remote MCP and Reader; the key
lives in the user's secret store, never in a committed file), Crawl4AI for
pages that need JavaScript (added to §1.2, with the third-party
`mcp-crawl4ai` wrapper as its MCP server), and `web-get`, a shell entry
point that walks the providers in turn. With it comes a rule for agents: when
the whole ladder fails for a page or search the task needs, pause that work
and report, never continue without the source.

What changed in 5.3 (2026-10-11): a **search policy** paragraph in §1.3
(default `rg`, with the opt-in indexed `ig` as a first line for one known
literal, and when to fall back), and `setup-modern-cli` joins the
`djbclark-ade` skills table in §0.6. `HOMEBREW_NO_AUTO_UPDATE=1` is kept on the
install commands and is now labelled correctly: it is a performance knob (no
slow implicit `brew update` mid-setup), not an update switch — it does not stop
tools updating. The measured numbers and the caveats that justify the policy
live in `djbclark-ade/skills/setup-modern-cli/SKILL.md`.

What changed in 5.4 (2026-10-11): the rest of the modern toolchain is registered
here, not only in the skill — `miller` (awk/sed/sort/join over CSV/TSV/JSON),
`gnu-sed`/`gawk` plus `uutils-coreutils` for GNU-vs-BSD flag drift, `dust`/`gdu`/
`duf`/`procs`/`difftastic`/`hyperfine`/`tldr`, and `hexyl`/`ouch`/`glow`/`doggo`/
`ripgrep-all`/`rargs`/`entr`/`csvlens`/`qsv`/`dasel`/`b3sum`/`watchexec` are in
the §1.2 install line and the §1.3 utilities table; `runiq` is noted as
crates-only (`cargo install runiq`). Rationale and the per-tool verdicts live in
`djbclark-ade/skills/setup-modern-cli/` (`SKILL.md` + `references/`).

What changed in 5.5 (2026-10-11): four agent-data tools added — `duckdb` (SQL
over CSV/JSON/Parquet with no import), `jc` (command output → JSON), `gron`
(flatten JSON so `rg` can search it) and `moreutils` (`sponge`/`ifne`/`vidir`).
They are in the §1.2 install line, the §1.3 utilities table, and the skill's
`references/replacements.md`; the "Not installed, and why" table there records
what is still deliberately out (`jaq`, `mdcat`, `ov`, `tailspin`, `aria2c`,
`f2`, `angle-grinder`, `fclones`, `atuin`, `lazygit`, `lnav`, `nomino`).

What changed in 5.11 (2026-10-16): a new **MIT Athena** block after the SiYuan notes
(AuriStor AFS client, `athena-kinit` Kerberos renewal with AFS tokens, `athena-locker`
for `attach`/`add`/`detach`/`fsid` and `/mit`). Everything Athena-related, and the other
items that need an MIT login (`forgejo` for forgejo.mit.edu, `sipb-llm-bench`, the Crush
setup for SIPB LLMs), now says up front that it applies only if the user has an MIT
account (Athena/Kerberos); skip it otherwise.

What changed in 5.10 (2026-10-13): `forgejo-cli` (`fj`) and `tea` join the Homebrew
install (§1.2, §1.3) and §0.6 lists the `forgejo` skill (token in `sudo-secretspec`,
`setup-token`, `forgejo-api`, `tea-forgejo`). `pyforgejo` is deliberately not installed:
a library, used on demand with `uv run --with pyforgejo`.

What changed in 5.9 (2026-10-13): §0.6 lists the `autorename` skill, including the
user-level symlink that lets it rename omp sessions (its `omp-bridge.ts` extension).

What changed in 5.8 (2026-10-12): §0.6 lists the Fastino `fastino-glide` skill beside `typesafe-ai`
(a second hosted decision model, installed project-level with `npx skills add`; key
`FASTINO_API_KEY`).

What changed in 5.7 (2026-10-12): §0.6 lists the new `sipb-llm-bench` skill (benchmark a
model on SIPB LLMs or any OpenAI-compatible server as a coding-agent backend).

What changed in 5.6 (2026-10-12): Crawl4AI MCP is run as **one shared server
per machine over HTTP**, not registered as a stdio command. Every agent session
starts its own copy of each stdio MCP server, and a crawl4ai copy is a Python
process, a Playwright driver and three headless Chromium processes (~230 MB
phys footprint). On djbclark's 16 GB Mac, 15 concurrent sessions held 3.4 GB of
them and, with the other per-session servers, pushed the load average to 230
through swap thrash. The §1.3 row now starts it under a login agent and registers
the URL; the same applies to any heavy stdio server every agent registers.

---

## The prompt (paste from here down)

### Apply the djbclark / frdminc / Graft development toolchain to `Kuriboh493/perp-option-pricer`

You are Claude Code, running as the **orchestrator** in a local checkout of
https://github.com/Kuriboh493/perp-option-pricer (default branch `main`).

Do the work; do not just propose it. Follow the phase order in §3 and the
orchestration plan in §0. Anything you cannot do yourself goes into the
**interactive phase** (§12), where you guide the user **one step at a time**.

Priorities, in order: **(1) don't break anything, (2) get good results,
(3) use as few tokens as possible.**

## P0. Facts about the target (verify them; do not trust them blindly)

- Primary language: Python (NumPy, SciPy, Pandas, PyArrow). Scripts run from
  their own folders: `common/`, `perps/`, `prediction-markets/`.
- `perps/index.html` is a standalone, dependency-free HTML app with inline CSS
  and a large inline JavaScript pricing engine. It is real source code.
- About 90 GB of downloaded research data lives in git-ignored `data/` and
  `reports/` directories. Tools must never scan it, and CI must never download
  it.
- A root `README.md` exists. No license file has been found.
- The user's GitHub login is `Kuriboh493`. They already have read access to the
  private `djbclark/coderabbit-feeder` repo.

### Global safety rule: back up before touching anything outside git

Before you edit, overwrite, move or delete **any file that is not tracked by
git**, back it up first (§15). This covers files inside the target repo and
outside it: `~/.zshrc`, `~/.gitconfig`, `~/.claude/*`, `.git/hooks/*`,
LaunchAgent plists, anything under `~/.config/`, untracked or ignored files in
any checkout, and tool config directories. Files tracked in git are already
recoverable through git and need no copy, but never discard uncommitted changes
to them.

---

## 0. Orchestration: built-in Claude Code subagents

### 0.1 Confirm what the installed Claude Code supports

Run `claude --version`, open `/agents`, and read the current docs:
https://code.claude.com/docs/en/sub-agents and
https://code.claude.com/docs/en/skills. Confirm, and adapt §0.3 if anything
differs:

- project subagents live in `.claude/agents/<name>.md` (user-level ones in
  `~/.claude/agents/`), with YAML frontmatter `name`, `description` (both
  required), and optional `tools`, `disallowedTools`, `model`,
  `effort` (`low` | `medium` | `high` | `xhigh` | `max`), `permissionMode`,
  `maxTurns`, `skills`, `memory`, `background` and `hooks`;
- `model` accepts the family aliases `haiku`, `sonnet`, `opus` and `fable`, a
  full model ID, or `inherit`. **Never use `fable`** in these definitions: it
  is the most expensive tier and this work does not need it. If the user's plan
  includes it and they ask for it on a specific judgment call, that is their
  decision;
- independent subagents run in parallel (default cap 20, env
  `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`), each in its own context window, and
  only the final reply returns to you.

**Agent teams** (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`,
https://code.claude.com/docs/en/agent-teams) are still experimental and off by
default. Do **not** enable them; plain subagents are enough here. Use them only
if plain subagents prove insufficient, and then only with user approval and a
backup of any settings file you change (§15).

No external orchestrator (Herdr, Orca, Ralph TUI, Beads) is used.

### 0.2 Working rules for orchestration

Adapted from https://github.com/djbclark/claude-orchestration-skills (public;
read its `README.md` and `plugins/*/skills/*/SKILL.md` for detail; ignore its
Herdr/Ralph/Beads mechanics and its djbclark-specific paths).

1. **The orchestrator orchestrates.** Delegate mechanical and bounded work to
   subagents. Keep only planning, integration, judgment calls, commits and the
   interactive phase in the main session.
2. **Scope is the safety control.** Every delegation states: goal, exact files
   or paths allowed to change, files that must not change, commands allowed,
   what "done" means, and the reply format. Subagents doing research are
   read-only.
3. **Verify independently.** A subagent's "done" or "all green" is a claim, not
   a fact. Check it before accepting: rerun the command, inspect `git diff`,
   compare golden values. Status reports can be wrong in both directions.
4. **One writer per area.** Never let two writers touch the same file or
   worktree. Parallel writers need disjoint paths, or separate git worktrees
   (`git worktree add`) that the orchestrator integrates.
5. **Only the orchestrator commits, pushes and talks to the user.** Subagents
   never run `git commit`, `git push`, `gh pr`, account or settings changes,
   or interactive prompts.
6. **Handoff file.** Keep an untracked progress file at
   `~/.local/state/perp-tooling-work/HANDOFF.md`: current phase, done and
   pending steps, open decisions, commit SHAs, baseline status. Update it after
   every phase and before any context compaction (`/compact`), so a fresh
   session (`claude --continue` or `--resume`) can pick up with
   `Read HANDOFF.md and continue`. Claude Code's own auto-memory
   (`~/.claude/projects/<project>/memory/`) is a complement, not a substitute:
   it is not guaranteed to hold the exact resume state. If the
   `session-handoff` plugin from §0.6 is installed, use its Tier 1 pointer
   instead of a hand-rolled file and say so in the final report.

### 0.3 Subagents to create

Create these files under `.claude/agents/` in the target repo. They are useful
after this setup too; keep and commit them, and mention them in `AGENTS.md`.

| Agent | Model / effort | Tools | Job |
|---|---|---|---|
| `scout` | haiku / medium | Read, Grep, Glob, Bash (read-only commands), WebFetch | Inventory a repo or directory; extract specific config facts from a reference repo; return compact structured findings |
| `installer` | haiku / low | Bash | Check and install tools from §1; return a table of tool → version → status |
| `researcher` | sonnet / medium | Read, Grep, Glob, WebFetch, WebSearch | Find tools for uncovered formats (§2), exact current install commands, and docs questions |
| `config-writer` | sonnet / medium | Read, Edit, Write, Bash | Write the tool configuration files assigned to it, and nothing else |
| `test-author` | opus / high | Read, Edit, Write, Bash | Write characterization and golden tests (§5) |
| `backport-worker` | sonnet / medium | Read, Edit, Write, Bash | Apply one tool's fixes to the paths assigned to it (§7) |
| `numeric-reviewer` | opus / high | Read, Grep, Bash (read-only) | Review diffs to numerical code and the pricer for any change in meaning |
| `verifier` | sonnet / low | Read, Bash (read-only checks) | Run named `just` recipes and baseline comparisons; report pass/fail and exact failures |
| `docs-writer` | sonnet / medium | Read, Edit, Write | README, AGENTS.md, the skill, CHANGELOG, contributor docs |
| `fork-auditor` | opus / high | Read, Grep, Glob, Bash (read-only) | Find and classify environment-specific hardcoding (§14.1) |
| `fork-generalizer` | sonnet / medium | Read, Edit, Write, Bash | Generalize one forked repo in its own checkout (§14.3) |

Each file's body is its instructions. Include the §0.2 rules that apply, its
reply format (§0.5), and the reminder that it never commits, pushes or changes
accounts or settings. Give read-only agents `permissionMode: plan` or a
`disallowedTools` list covering Edit and Write, and set `maxTurns` on the
cheap ones so a confused Haiku run cannot loop. Example:

```markdown
---
name: verifier
description: Runs named quality gates and baseline comparisons and reports exact results. Use after any change.
tools: Read, Bash
disallowedTools: Edit, Write, NotebookEdit
model: sonnet
effort: low
maxTurns: 30
---
Run only the commands you are given. Do not edit files. Report each command,
its exit code, and the exact failing lines (at most 40 per command). Compare
baseline output against tests/baseline/BASELINE.md and list every difference.
Never say "passed" without showing the command's exit code.
```

### 0.4 Parallelism plan

Run independent work in parallel; keep anything with dependencies or shared
files sequential.

| Phase | In parallel | Must stay sequential |
|---|---|---|
| Inspect (§4) | one `scout` per reference repo, plus one `scout` for the target; `installer` starts at the same time | none |
| Install (§1–§2) | `installer` runs while scouts work; `researcher` handles uncovered formats | nothing installs into the target repo until inspection is done |
| Skills and plugins (§0.6) | none (settings files; orchestrator only) | after backups (§15) exist |
| Forks (§14) | one `fork-auditor`, then one `fork-generalizer` per repo, each in its own checkout | forking, pushing and approvals go through the orchestrator and the user |
| Baseline (§5) | Python tests and HTML/JS tests by separate `test-author`s, if their files are disjoint | the baseline run and recording, after both finish |
| Configure (§6) | several `config-writer`s, each owning distinct files | the orchestrator integrates `justfile` and `.pre-commit-config.yaml`, since they reference everything |
| Backport (§7) | read-only checks of one tool's output can run in parallel | **tool after tool, one at a time**, each followed by baseline verification and numeric review |
| Docs and CI (§8–§11) | `docs-writer` and the CI-workflow writer in parallel | license questions (interactive) |
| Interactive (§12) and feeder (§13) | none | everything, one step at a time |

### 0.5 Token budget rules

- Route by difficulty: Haiku for inventories, installs and version checks;
  Sonnet for configuration, docs and forks; Opus only for baseline tests,
  numerical review and the hardcoding audit. Set `effort` per agent as in
  §0.3; `max` and `xhigh` are never needed here.
- Subagents return **compact structured summaries** (tables or bullet lists,
  at most about 150 lines), with file paths and line numbers instead of pasted
  file contents.
- Read narrowly. Use the Graft MCP tools or `graft ask`/`graft skeleton` once
  the graph is built, `ast-grep`, `rg` and file line ranges instead of whole
  files. Never read the data directories.
- Write facts down once, in `HANDOFF.md` or `tests/baseline/BASELINE.md`, and
  point subagents at them instead of re-explaining.
- Don't re-run full suites when a targeted recipe answers the question, but
  always run the full baseline after each backport step.
- Keep failure output short: show the first failing lines, not entire logs.
- Don't delegate trivial one-command tasks; a subagent call has overhead.
- Run `/cost` (or read `/context`) at each phase boundary and note it in
  `HANDOFF.md`; the final report wants a per-phase estimate (§16).

### 0.6 Claude Code skills and plugins to activate, then explain

These are optional accelerators for the user's day-to-day work in this repo
after the setup. Install them **project-scoped where the mechanism allows**,
so the repo carries them and a fresh clone picks them up, and back up
`~/.claude/settings.json` and `.claude/settings.json` first (§15). Confirm
the current commands against https://code.claude.com/docs/en/plugins before
running them. Nothing here sends code anywhere; plugins are prompt and hook
bundles that run inside the user's own session.

**Built in to Claude Code (nothing to install; confirm each exists with
`/help`):**

| Command | What it does | When the user should reach for it |
|---|---|---|
| `/init` | Drafts a `CLAUDE.md` from the codebase | Not needed here (§8 writes `AGENTS.md`); use only to compare its draft against ours |
| `/code-review [low\|medium\|high]` | Reviews the current diff or a PR for correctness bugs; `ultra` runs a billed multi-agent cloud review | Before pushing any non-trivial change; `ultra` only for big risky branches |
| `/simplify` | Cleans up the changed code for reuse and simplicity without hunting bugs | After a feature works and before review |
| `/security-review` | Security pass over the current changes | Anything that touches input parsing, file handling or subprocesses |
| `/fewer-permission-prompts` | Scans transcripts and adds a read-only allowlist to `.claude/settings.json` | After a few sessions, when prompts get annoying |
| `/compact`, `--continue`, `--resume` | Context compaction and session resume | Long sessions; pair with `HANDOFF.md` |
| `/cost`, `/context` | Token and cost view | At phase boundaries |
| `/loop`, `/schedule` | Recurring local prompt; scheduled cloud routines | Only if the user wants unattended runs; not part of this setup |

**From the official marketplace** (`/plugin marketplace add
anthropics/claude-plugins-official` if it is not already known; then
`/plugin install <name>@claude-plugins-official`). Install the first group;
offer the second:

| Plugin | Install? | What it gives this repo |
|---|---|---|
| `commit-commands` | yes | `/commit`, `/commit-push-pr`: consistent commit messages and PR creation |
| `pr-review-toolkit` | yes | Specialised PR review agents (tests, error handling, type design, simplification); complements CodeRabbit with an in-session pass |
| `security-guidance` | yes | Pattern warnings on edits plus an LLM diff review on stop, catching injection, hardcoded secrets and similar in Claude-written code |
| `claude-md-management` | yes | Audits and maintains `AGENTS.md`/`CLAUDE.md` so §8 stays accurate as the repo evolves |
| `pyright-lsp` | yes | Python language server for Claude's own edits (type-aware navigation); `brew install pyright` (§1.2; not `uv tool`, which would shadow it) or `bun add --dev pyright` as it requires |
| `typescript-lsp` | yes | Same for the inline JavaScript and any `.ts` tests |
| `skill-creator` | yes | Creates and evaluates skills; use it to write and validate `.claude/skills/dev-tooling` in §8 |
| `session-report` | yes | Local HTML report of token use per session; feeds the §16 cost note |
| `claude-code-setup` | offer | Analyses the repo and recommends hooks, skills and subagents; a good second-opinion pass after this prompt finishes |
| `hookify` | offer | Turn "never do X again" into a hook from a markdown rule; useful once the user has seen a repeated mistake |
| `code-simplifier` | offer | Agent form of `/simplify` for larger refactors |
| `feature-dev` | offer | Explore, design, implement, review workflow for new features |
| `ralph-loop` | no (mention only) | Self-repeating loops; not appropriate until the baseline and gates exist and the user has used the plain workflow for a while |

**From djbclark's orchestration marketplace** (public, MIT):

```text
/plugin marketplace add djbclark/claude-orchestration-skills
/plugin install session-handoff@claude-orchestration-skills
```

`session-handoff` provides the Tier 1 pointer file and a `PreCompact` hook
that checkpoints before compaction. Its hook needs copying into the hooks
directory and registering in `settings.json` (read its README); do that only
with the user's approval and a backup. Do not install `herdr-orchestration`
or `ralph-tui-orchestration`; they need tools this setup does not use.

**From djbclark's `djbclark-ade` repo** (public, MIT;
https://github.com/djbclark/djbclark-ade, skills under `skills/`, each
described in `docs/skills.md`). Install project-scoped by copying or
symlinking the skill directory into `.claude/skills/<name>/`:

| Skill | Install? | What it gives this repo |
|---|---|---|
| `report` | yes | `/report`: formats a long Markdown deliverable (research report, spec, review) so it reads well in a Markdown previewer such as Marked 2: numbered superscript citations linked to an anchored list, an evidence table whose ids link to the source (no URL column), descriptive file names with a symlink at any generic name a tool expects, paragraphs under ~180 words, and a render check that captures only the previewer's window. Its two stdlib scripts (`scripts/reformat_citations.py`, `scripts/cite_sup.py`) are idempotent. Apply it before the first `open` of any long document the user will read, not after a formatting complaint. |
| `dialogue` | yes | Runs a multi-model dialogue that produces one artifact (a spec, a report, a design) with a final-word model: fixed speaking rounds through pinned headless routes (for example Grok, Claude and GPT via `acp-run`), a machine-read footer per turn with point ids, status and dissent, a transcript that is the record, and `scripts/dialogue.py` checks for the failures the first run measured (noise strip, protocol lint, final-word gate). Use when several vendors should argue the points of contention before one writes the deliverable; not for a quick second opinion or for fan-out work with no argument between models. |
| `sipb-llm-bench` | offer | Benchmarks a model on MIT SIPB LLMs (or any OpenAI-compatible Open WebUI/Ollama server) as an agentic-coding backend: speed probes, a tool-call conformance check, two tool-using tasks scored by running the tests, and a procedure for updating the published report. Serial and gentle on the shared server; only useful for a repo that targets such a server. SIPB's own servers need an MIT account, so skip it for a user without one. |
| `setup-modern-cli` | yes | The standing instruction to prefer modern tools over the classic ones: the replacement table (`rg`←`grep`, `fd`←`find`, `bat`←`cat`, `srgn`←`sed`, `eza`←`ls`, `hck`←`cut`/`awk`, `jq`/`yq`, `xh`, `ast-grep`, `dust`/`gdu`, `rtk`) with the exact command patterns, the footguns (`rg -rln` is `--replace`; a pathless `rg` over-searches; `sd` is retired), and the measured search policy from §1.3 (`rg` by default, opt-in indexed `ig` as a first line for one known literal, never `ayg`). Load it before shell searches; it is the long form of the §1.3 table. |
| `autorename` | offer | `/autorename`: names the current agent session (Claude Code, zcode, Grok, cursor-agent, OpenCode, Codex in a herdr pane, omp) from what it is working on, writing where each TUI's own `/rename` writes; `--auto` keeps a title the user set by hand. **omp needs one user-level step:** `ln -s <djbclark-ade>/skills/autorename/omp-bridge.ts ~/.omp/agent/extensions/autorename-bridge.ts`, then restart omp (it loads extensions at startup only). The extension lets the running omp rename itself, because omp moves a session to a new file when anything else writes it. Ask before creating the symlink: it is outside the repo and loads into every omp session. |
| `forgejo` | offer | Uses a Forgejo instance (default `forgejo.mit.edu`) with the token held in `sudo-secretspec` as `DJBCLARK_<HOST>_TOKEN`: `scripts/setup-token` declares the secret (optional), opens the token page and verifies it; `forgejo-api` makes one `/api/v1` call (mutations need `--yes`); `tea-forgejo` runs `tea` with the secret on its env login. Needs `fj` and `tea` from §1.2, and a token only the user can create in the browser, so offer it only where the user works with a Forgejo server. The default host `forgejo.mit.edu` (and the SIPB runner below) need an MIT account (Athena/Touchstone login), so skip those for a user without one. For the SIPB `ubuntu` CI runner it also records the `LD_PRELOAD` loopback shim (port 0 and `shutdown()`) Gradle needs there (libkrun#818) and the per-job resource limits (16 vCPU, 62.8 GiB, virtiofs disk with a 32 GiB tmpfs). |

**From Matt Pocock's skills marketplace** (public):

```text
/plugin marketplace add mattpocock/skills
/plugin install mattpocock-skills@mattpocock
```

Worth having for this repo: `tdd` (red-green-refactor, matches the §8 testing
rules), `diagnosing-bugs` (a disciplined loop for "it's wrong and I don't know
why", good for numerical regressions), `writing-for-agents` (when editing
`AGENTS.md` or the skill), `research` (captures findings as a markdown file in
the repo) and `code-review` (standards-vs-spec review). The rest are harmless
but unused.

**From the TypeSafe marketplace** (public, MIT; added 2026-10-11):

```text
/plugin marketplace add typesafe-ai/skills
/plugin install typesafe@typesafe-ai
```

`typesafe` provides the `typesafe-ai` skill: guidance for building features on
TypeSafe's System One models (Jev), which return typed judgments and
probabilities that code composes (choice, yes/no probability, score). Its
instructions say to read the live docs at https://docs.typesafe.ai/llms.txt
before writing an integration. Install it only for repos that call, or plan to
call, the TypeSafe API; use it when a feature needs semantic judgment (routing,
ranking, extraction, verification), not for rules or exact lookups that plain
code handles. Other agents: `npx skills add typesafe-ai/skills --skill
typesafe-ai` (use one install method, not both).

**`fastino-glide`** (Fastino's GLiDE, a second hosted decision model on the same
`/v1/systemone` request shape: yes/no, pick-one and score questions with a
probability per option). Install it only for repos that call, or plan to call,
the Fastino API, and for the same kinds of judgment as `typesafe-ai`. One command,
project-level, no prompts: `npx skills add https://docs.fastino.ai --skill
fastino-glide -a claude-code -y` (`-a codex` or `-a cursor` for those agents; it
lands in `.claude/skills/fastino-glide/` plus a `skills-lock.json` that pins its
hash; read the SKILL.md before trusting it). The key is `FASTINO_API_KEY`: on
djbclark's machine it lives in sudo-secretspec (`sudo-secretspec run --reason ... --
cmd`), never in source. Verified live 2026-10-11/12: the response `model` is
`glide_v2`, where Fastino's docs say `glide` (docs/upstream-issues.md). Remove with
`npx skills remove fastino-glide` or by deleting the directory and its lockfile
entry.

**Graft's own wiring** (hooks, statusline and MCP server) is installed by
`graft init` in §6, not here. The web-access MCP servers (Exa, Parallel
Search, Jina, Crawl4AI) are installed with the §1.3 "Agent web access" table.

**Explain each one to the user.** In the interactive phase (§12, step 2)
walk through the installed set one item at a time: what it is, the command
or trigger, when to use it, when not to, and how to remove it (`/plugin
uninstall <name>@<marketplace>`; the backup manifest for settings files). Ask
after each whether to keep it. Record the final set in `AGENTS.md` (§8 item
3) so other agents and future sessions know what is available.

---

## 1. Tool inventory

Install **everything in this section, even for languages and formats the repo
does not use yet**, so the tools are ready when they are needed. Check first
(`<tool> --version`) and skip anything already installed at a suitable version.
Never use `sudo pip install`.

### 1.1 Homebrew first

- **Homebrew**: https://brew.sh/ , the macOS package manager used for nearly
  everything below.

```bash
brew --version || /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
# If `brew` is not found afterwards:
eval "$(/opt/homebrew/bin/brew shellenv)"   # Apple Silicon
eval "$(/usr/local/bin/brew shellenv)"      # Intel
```

The Homebrew installer may ask for the macOS password. If it does, hand that
step to the user in the interactive phase. If the installer offers to add
`brew shellenv` to a shell profile, back that file up first (§15).

### 1.2 Install everything with Homebrew (one command)

```bash
HOMEBREW_NO_AUTO_UPDATE=1 brew install \
  git gh forgejo-cli tea uv just oven-sh/bun/bun node \
  ruff pre-commit gitleaks typos-cli semgrep \
  shellcheck shfmt biome lychee dotenv-linter actionlint \
  openjdk coreutils caddy \
  ripgrep fd bat srgn eza hck git-delta jq yq xh ast-grep \
  miller gnu-sed gawk findutils grep make gnu-tar uutils-coreutils dasel qsv b3sum \
  dust gdu duf procs difftastic hyperfine tldr \
  hexyl ouch glow doggo ripgrep-all rargs entr csvlens watchexec \
  duckdb jc gron moreutils \
  black mypy pyright flake8 pylint isort bandit pycodestyle yapf autopep8 \
  vulture pyupgrade python-lsp-server pytest tox nox \
  poetry pdm hatch virtualenv twine python-build python-setuptools \
  python-packaging pip-tools pip-audit pipdeptree python-launcher python-argcomplete \
  ipython jupyterlab jupytext sphinx mkdocs-material python-markdown \
  numpy scipy pillow cython pybind11 python-matplotlib python-tabulate \
  python-tk@3.14 python-gdbm@3.14 swig \
  httpie cookiecutter commitizen litecli pgcli mycli pyinstaller \
  age
# `age` (2026-10-15): encrypts the `get` volume exports streamed to defeat
# (`~/src/get/scripts/export-volumes`, `AGE_RECIPIENT`); not a VM, a 12 MB CLI.
# Python dev tools come from Homebrew first (2026-10-12). `mkdocs-material`
# bundles `mkdocs`: never add the plain `mkdocs` formula. Skip `python-yq`: it
# conflicts with the Go `yq` above. Keep the unversioned `python3` on the
# interpreter the brew Python packages are linked against (3.14 as of
# 2026-10-12; brew's own default moved to 3.15 on 2026-10-11), with a sidecar
# README saying why; revisit when numpy/python-* formulae move up:
ln -sfn /opt/homebrew/bin/python3.14 ~/.local/bin/python3
printf '%s\n' 'python3 here pins brew python3.14: the brew Python packages are linked against it. See apply-toolchain-prompt.md 1.2.' > ~/.local/bin/python3.PIN-README.md

# `runiq` (uniq on unsorted input) is not in Homebrew:
cargo install runiq

# Lighthouse and Puppeteer need a Chrome-family browser:
ls "/Applications/Google Chrome.app" >/dev/null 2>&1 || brew install --cask google-chrome

# Python CLIs installed as isolated global tools: ONLY for what Homebrew lacks.
# `~/.local/bin` sits ahead of `/opt/homebrew/bin` on PATH, so a stray
# `uv tool install mypy` (or pipx) silently shadows the brew copy.
uv tool install ansible-lint
uv tool install pyinilint
# Crawl4AI (JavaScript-rendering page fetch for agents, §1.3 "Agent web access");
# pinned Python because 0.9.4 supports up to 3.13; crawl4ai-setup downloads
# Playwright browsers (~0.6 GB in ~/Library/Caches/ms-playwright):
uv tool install --python 3.13 'crawl4ai==0.9.4'
crawl4ai-setup

# SkillOpt-Sleep (nightly skill learning from every agent's transcripts, §1.3
# "SkillOpt-Sleep"); machine-wide, pinned to the upstream main commit verified
# 2026-10-12 (PyPI 0.2.0 lacks the handoff backend and multi-skill fan-out):
uv tool install "skillopt @ git+https://github.com/microsoft/SkillOpt@343db229dbd5ddaf9df6b1d5540d8bcdb2604d5c"

# Graft (agent context graph); confirm the package name against the upstream README first (§1.3):
npm install -g @nanonets/graft
```

**About `HOMEBREW_NO_AUTO_UPDATE=1`: a performance knob, not an update switch.**
It suppresses the `brew update` brew otherwise runs in front of
`install`/`upgrade` (minutes, and it can fail on a flaky network), so a
multi-package install stays fast and deterministic. It does **not** stop
anything updating: `brew update`/`brew upgrade` still work, and on djbclark's
machine `site-djbclark/shell/bashrc` exports it machine-wide while the scheduled
`brew-fast-upgrade` Jobber job (daily 03:10) updates brew and npm globals. Keep
it on automated install lines.

### 1.3 What each tool is, where it lives, and how it is installed

**Core workflow**

| Tool | Website | Install | What it does |
|---|---|---|---|
| Git | https://git-scm.com/ | `brew install git` | Version control |
| GitHub CLI `gh` | https://cli.github.com/ | `brew install gh` | GitHub from the terminal: repos, PRs, Actions, forks, collaborators |
| Forgejo CLI `fj` | https://codeberg.org/forgejo-contrib/forgejo-cli | `brew install forgejo-cli` | Forgejo from the terminal (Forgejo-native). Use unauthenticated only: `fj auth` keeps tokens in its own plaintext file, outside `sudo-secretspec` |
| `tea` | https://gitea.com/gitea/tea | `brew install tea` | Gitea/Forgejo CLI for authenticated agent work: the `forgejo` skill's `tea-forgejo` feeds it `GITEA_INSTANCE_URL` and `GITEA_TOKEN` from `sudo-secretspec`, so never `tea login add` |
| uv | https://docs.astral.sh/uv/ | `brew install uv` | Python interpreters, virtual environments, locked dependencies (`uv.lock`) |
| just | https://just.systems/ | `brew install just` | Command runner (`just test`, `just check`, …). `just --fmt --check` is the justfile linter/formatter |
| Bun | https://bun.sh/ | `brew install oven-sh/bun/bun` | Installs and runs repo-local JS tooling (`bunx`), with `bun.lock` |
| Node.js | https://nodejs.org/ | `brew install node` | Needed by Puppeteer, Lighthouse, Graft and npm-based tools |
| pre-commit | https://pre-commit.com/ | `brew install pre-commit` (also a locked project dev dependency) | Manages pinned git hooks |

**Python quality** (locked project dev dependencies, installed with `uv sync`)

| Tool | Website | What it does |
|---|---|---|
| pytest | https://docs.pytest.org/ | Test runner |
| Ruff | https://docs.astral.sh/ruff/ (also `brew install ruff`) | Lint, import sorting, formatting |
| mypy | https://mypy.readthedocs.io/ | Static type checking |
| Bandit | https://bandit.readthedocs.io/ | Python security lint |
| yamllint | https://yamllint.readthedocs.io/ | YAML lint |

**Docs, text and configuration**

| Tool | Website | Install | What it does |
|---|---|---|---|
| Prettier + prettier-plugin-toml + prettier-plugin-ini | https://prettier.io/ , https://github.com/un-ts/prettier | `bun add --dev` | Formatting for Markdown, TOML, INI, HTML, CSS and YAML |
| markdownlint-cli | https://github.com/DavidAnson/markdownlint-cli | `bun add --dev` | Markdown lint |
| typos | https://github.com/crate-ci/typos | `brew install typos-cli` | Spell check for source and docs |
| dotenv-linter | https://dotenv-linter.github.io/ | `brew install dotenv-linter` | Lints `.env` / `.env.example` |
| pyinilint | https://pypi.org/project/pyinilint/ | `uv tool install pyinilint` | Lints `.ini` files |
| lychee | https://lychee.cli.rs/ | `brew install lychee` | Link checker (run offline for docs) |

**HTML, CSS, JavaScript and web: include all of these** (modeled on `djbclark/stayturgid`)

| Tool | Website | Install | What it does |
|---|---|---|---|
| html-validate | https://html-validate.org/ | `bun add --dev html-validate` | Offline HTML structure and accessibility-markup lint |
| Nu HTML Checker (vnu-jar) | https://validator.github.io/validator/ | `bun add --dev vnu-jar` (needs Java: `brew install openjdk`; list it in `trustedDependencies`) | W3C-grade HTML validation |
| Stylelint + stylelint-config-standard | https://stylelint.io/ | `bun add --dev` | CSS lint, including inline `<style>` blocks |
| Biome | https://biomejs.dev/ | `brew install biome` | JS/TS/CSS lint and format |
| TypeScript `tsc` | https://www.typescriptlang.org/ | `bun add --dev typescript` | Type-checks JS through `checkJs` |
| pa11y | https://pa11y.org/ | `bun add --dev pa11y` | Accessibility audit of the rendered page |
| Puppeteer | https://pptr.dev/ | `bun add --dev puppeteer` | Headless browser smoke tests (page loads, no JS errors, finite outputs) |
| Lighthouse | https://developer.chrome.com/docs/lighthouse | `bunx lighthouse` (needs Chrome) | Full-page performance, accessibility and best-practices audit |

**Shell, CI, infrastructure and security**

| Tool | Website | Install | What it does |
|---|---|---|---|
| ShellCheck | https://www.shellcheck.net/ | `brew install shellcheck` | Shell static analysis (`-S warning`) |
| shfmt | https://github.com/mvdan/sh | `brew install shfmt` | Shell formatting (`-i 2 -ci`) |
| actionlint | https://github.com/rhysd/actionlint | `brew install actionlint` | Lints GitHub Actions workflows. Not used in the reference repos; added under the "same spirit" rule (§2) because this repo will have workflows |
| ansible-lint | https://ansible.readthedocs.io/projects/lint/ | `uv tool install ansible-lint` | Ansible lint (for when Ansible appears) |
| Caddy | https://caddyserver.com/ | `brew install caddy` | Only `caddy fmt` is used, for Caddyfiles |
| Gitleaks | https://github.com/gitleaks/gitleaks | `brew install gitleaks` | Secret scanning (`--redact`) |
| Semgrep | https://semgrep.dev/ | `brew install semgrep` | Structural search and curated security rules (see the gate policy in §6) |
| GNU coreutils | https://www.gnu.org/software/coreutils/ | `brew install coreutils` | `gtimeout` and other GNU tools for hooks |

**Agent and contributor CLI utilities** (from `site-djbclark`'s
`brew/fragments/agent-cli-tools.yml`, rationale in its `docs/tooling-policy.md`)

| Tool | Website | Install | Use instead of |
|---|---|---|---|
| ripgrep `rg` | https://github.com/BurntSushi/ripgrep | `brew install ripgrep` | `grep` |
| fd | https://github.com/sharkdp/fd | `brew install fd` | `find` |
| bat | https://github.com/sharkdp/bat | `brew install bat` | `cat` |
| srgn | https://github.com/alexpovel/srgn | `brew install srgn` | `sed`/`sd` for literal find/replace: `srgn -L --fail-none --stdin-detection force-unreadable --glob FILE 'FIND' -- 'REPL'` matches across lines as typed and exits 1 when nothing matched (`sd` exits 0 and matches line by line without `-A`) |
| eza | https://eza.rocks/ | `brew install eza` | `ls` |
| hck | https://github.com/sstadick/hck | `brew install hck` | `cut` / `awk` |
| delta | https://dandavison.github.io/delta/ | `brew install git-delta` | Raw `git diff` |
| jq | https://jqlang.org/ | `brew install jq` | Hand-parsing JSON |
| yq | https://mikefarah.gitbook.io/yq/ | `brew install yq` | Hand-parsing YAML |
| xh | https://github.com/ducaale/xh | `brew install xh` | `curl` for JSON APIs |
| ast-grep | https://ast-grep.github.io/ | `brew install ast-grep` | `rg` for code-shape queries |
| `mlr` (Miller) | https://miller.readthedocs.io/ | `brew install miller` | `awk`/`sed`/`cut`/`join`/`sort` over CSV/TSV/JSON with named fields: `mlr --csv sort -f col f.csv` |
| GNU `gsort`/`gsed`/`gawk`/`gdate`/`gfind`/`gxargs`/`ggrep`/`gmake`/`gtar` | https://www.gnu.org/software/coreutils/ | `brew install coreutils gnu-sed gawk findutils grep make gnu-tar` | BSD-vs-GNU flag drift (`sort -h`, `sed -i`, `date -d`, `find -printf`): call the `g`-prefixed binary in scripts; standing rule since 2026-10-14: prefer brew GNU tools over macOS BSD ones, install what is missing; since 2026-10-15 always `gsed`, never bare `sed`, unless BSD sed is required |
| `uu-*` (uutils) | https://uutils.github.io/coreutils/ | `brew install uutils-coreutils` | portable GNU-compatible coreutils (`uu-sort`, `uu-cut`, …); its `sed`/`awk` are still in progress |
| `gnu-tools-check` | https://github.com/djbclark/djbclark-ade (`bin/gnu-tools-check`) | `ln -s ~/src/djbclark-ade/bin/gnu-tools-check ~/.local/bin/gnu-tools-check`; needs the GNU tools in the row above | Enforces the row above: `gnu-tools-check [paths]` lists shell code (scripts, `just` recipes, fenced shell blocks and pipelines in Markdown) that calls a bare BSD tool where BSD and GNU differ (`sed`, `awk`, `grep`, `find`, `date`, `head`, `tail`, `tr`, `xargs`, … 24 in all) or passes a GNU-only long option to a BSD basic (`ls`, `cp`, `rm`, …). Quote- and heredoc-aware, scans tracked and untracked files (not gitignored ones). Opt-outs: a `.gnu-tools-check-ignore` file of globs, a `gnu-tools-check: portable` marker for a file meant to run on BSD, a `gnu-tools-check: ignore` line marker. Exit 1 on findings. Added 2026-10-14 |
| `dust`, `gdu` | https://github.com/bootandy/dust | `brew install dust gdu` | `du` — and never `du`/`find` over `~/.cache` (they time out) |
| `duf` | https://github.com/muesli/duf | `brew install duf` | `df` |
| `procs` | https://github.com/dalance/procs | `brew install procs` | `ps` (`procs --json` for scripts) |
| `difft` (difftastic) | https://difftastic.wilfred.me.uk/ | `brew install difftastic` | `diff` for syntax-aware comparisons |
| `hyperfine` | https://github.com/sharkdp/hyperfine | `brew install hyperfine` | `time` for real numbers |
| `tldr` | https://tldr.sh/ | `brew install tldr` | `man`, when you only need the flags |
| `b3sum` | https://github.com/BLAKE3-team/BLAKE3 | `brew install b3sum` | checksums (macOS ships `sha256sum` now) |
| `hexyl` | https://github.com/sharkdp/hexyl | `brew install hexyl` | `xxd` / `hexdump` |
| `rga` (ripgrep-all) | https://github.com/phiresky/ripgrep-all | `brew install ripgrep-all` | searching inside PDFs, Office files and archives |
| `ouch` | https://github.com/ouch-org/ouch | `brew install ouch` | one command for `tar`/`zip`/`7z`/`gz` |
| `glow` | https://github.com/charmbracelet/glow | `brew install glow` | rendering markdown to read |
| `doggo` | https://github.com/mr-karan/doggo | `brew install doggo` | `dig` |
| `dasel` | https://github.com/tomwright/dasel | `brew install dasel` | JSON/YAML/TOML/XML in one tool (`dasel query -i json X < f` in v3) |
| `qsv`, `csvlens` | https://github.com/dathere/qsv | `brew install qsv csvlens` | CSV stats/query and browsing instead of eyeballing |
| `watchexec`, `entr` | https://github.com/watchexec/watchexec | `brew install watchexec entr` | `watch` (non-interactive, safe for agents) |
| `runiq` | https://github.com/whitfin/runiq | `cargo install runiq` (not in Homebrew) | `uniq` on unsorted input |
| `rargs` | https://github.com/lotabout/rargs | `brew install rargs` | `xargs -I` plus `awk`-style conditions |
| `duckdb` | https://duckdb.org/ | `brew install duckdb` | ad-hoc SQL over CSV/JSON/Parquet/globs with no import step — replaces long `awk`/`mlr`/`jq` chains |
| `jc` | https://github.com/kellyjonbrazil/jc | `brew install jc` | JSON-ify the output of commands that have no `--json` (`ip`, `df`, `ls`, `dig`, `systemctl`, …) |
| `gron` | https://github.com/tomnomnom/gron | `brew install gron` | flatten JSON to `path = value` lines so `rg` can search an unknown shape |
| `moreutils` (`sponge`, `ifne`, `vidir`) | https://joeyh.name/code/moreutils/ | `brew install moreutils` | `sponge` writes a file from mid-pipeline, `ifne` runs only on non-empty input |

These govern shell use. Claude Code's own `Read`/`Grep`/`Glob`/`Edit` tools
stay preferred over shelling out when an equivalent exists (site-djbclark
`docs/tooling-policy.md`).

**Search policy (added 2026-10-11).** Default to **`rg`**: it is exhaustive,
always correct, and already replaces a `find … | grep …` pipeline in one
command (`rg -n -g '*.py' PAT PATH`; `-l` for files, `-c` for counts). The
indexed **`ig`** (instant-grep) is an opt-in **first line for one thing you
already know** — an exact literal (symbol, string, filename fragment) you
expect in few files, in a repo whose index is current; it answered about 13x
faster than `rg` on a 3.3k-file tree. Fall back to `rg` as soon as any of these
holds: the search must be exhaustive; the pattern is a regex, multiline or
PCRE2; you need filters beyond `ig -g`/`ig -t`; `ig` returns nothing (it missed
6 of `rg`'s files in the same test, `vendor/` among them); or the tree changed
since the last index — `ig` silently returns nothing until `ig index` is re-run,
which is the normal case mid-edit. Do not adopt **`ayg`** (aygrep): it indexes
only git-tracked files, so untracked work is invisible even after a rebuild,
and it writes its index inside the repo. Tables, measured numbers and the
`rg` flag results (no flag helps; `--sort path` costs 5x) are in
`djbclark-ade/skills/setup-modern-cli/SKILL.md`. Record any deviation in
`AGENTS.md`.

Do not change global git config (e.g. making delta the pager) without asking.
If the user agrees, back up `~/.gitconfig` first (§15).

**Crush over ACP (temporary; added 2026-10-11, djbclark).** **Everything about Crush in this
prompt, here and in the tool table, is for one purpose: driving weak, small-context LLMs
(Qwen on SIPB LLMs, 32k window). Do not apply it for any other use of Crush; see Practical
note 6.** Crush is installed
only to use SIPB LLMs (`brew install crush`; provider in `~/.config/crush/crushrc`),
which need an MIT account: skip all of it for a user without one.
No release has an ACP mode, so `acp-run crush` runs a local build: clone the
fork (`gh repo clone djbclark/crush ~/src/crush`), then
`git -C ~/src/crush fetch upstream pull/2450/head:pr-2450` and
`git -C ~/src/crush worktree add -b acp-pr2450 ~/src/crush-acp upstream/main`,
merge `pr-2450` there (resolve `go.sum` by taking upstream's, then `go mod
tidy`), cherry-pick the three yolo commits of `yolo-true-unblock`
(upstream PR #3909, withdrawn 2026-10-14: the TUI now runs stock Homebrew Crush; the built `crush-acp` keeps these commits, so rebuild from this branch, never from plain upstream), `go build -o ~/.local/bin/crush-acp ./` (copy
to a temp name, then `mv -f`). Registered in `tools/acp-run/acp-run` as
`crush`; run it without `--model`. Drop all of this once PR #2450 merges and a
release has `crush acp`.

**SkillOpt-Sleep: nightly skill learning (machine-wide; added 2026-10-12, djbclark).**
Once per machine, not per repo. It mines every agent's past sessions into
tasks, replays them against the current skills and stages gated SKILL.md /
AGENTS.md edits for review; nothing changes until someone runs `skillopt-sleep
adopt`. Guide: `djbclark-ade/docs/skillopt-sleep.md`.

| Step | Command | What it does |
|---|---|---|
| CLI | `uv tool install "skillopt @ git+https://github.com/microsoft/SkillOpt@343db229dbd5ddaf9df6b1d5540d8bcdb2604d5c"` (§1.2) | `skillopt-sleep` (`run`, `dry-run`, `harvest`, `status`, `adopt`). Never use its `schedule` (crontab) or `--auto-adopt`, and never `uv tool upgrade` it: `skillopt-night` refuses any commit but its `REVIEWED_REV`; to move, review the upstream diff, then bump the pin in all three places |
| Source adapters | `~/src/djbclark-ade/bin/skillopt_sources.py` (runs under the skillopt tool's Python) | SessionDigest JSON for zcode, agy and crush stores, and the same filters for the native sources: path exclusions, the cycle's own sessions dropped, extra redaction |
| Skills | `~/src/djbclark-ade/bin/skill-everywhere skillopt-sleep skillopt-sleep-learned` (links each TUI directly at `~/src/djbclark-ade/skills/<name>`) | `/skillopt-sleep` (review last night, free mock `--dry-run`, per-skill adoption, the backend chain) in every TUI; `skillopt-sleep-learned` is the catch-all skill the cycle proposes edits to |
| Nightly job | `~/src/djbclark-ade/bin/skillopt-night install` (copies `launchd/com.djbclark.skillopt-sleep.plist` to `~/Library/LaunchAgents/` and bootstraps it; `uninstall` reverses) | 03:30 nightly run over every transcript source; inert until `~/.skillopt-sleep/night.json` has `"enabled": true`. Check the chain first with `skillopt-night chain-check` |
| Failover library | `~/src/djbclark-ade/bin/failover.py` (`registry`, `check`, `ask`, `run`; `docs/failover.md`) | The ordered chain of agent routes the night answers its prompts through (deny list, allowlist, aiuse preflight, attempt log). Reuse it for any tool that must fail over between pools instead of hand-rolling one |

**Agent context graph**

| Tool | Website | Install | What it does |
|---|---|---|---|
| Graft | https://github.com/trailhq/Graft (npm package `@nanonets/graft`) | `npm install -g @nanonets/graft`, or `npx @nanonets/graft init` without a global install. **Re-read the upstream README's Quick start and use its exact command; do not invent a package name.** | Builds a local, regenerable code-context graph under `graft/` (tree-sitter only; no model or key needed) and exposes it as an MCP server plus CLI (`graft init/build/map/ask/skeleton/callers/grep`), so agents read far less source. `graft init` wires hooks and a statusline into `.claude/`; see §6 for the policy |

Graft facts to respect (from the upstream README, re-read 2026-10-11): `graft
build` adds `graft/` to `.gitignore` itself; the graph is a local cache like
`node_modules`, and what gets committed is the wiring `graft init` drops in:
`.claude/` (hooks, statusline, `.claude/skills/graft/SKILL.md`), the project
`.mcp.json` entry for the Graft MCP server (`graft mcp`; skip with
`--no-mcp`), and `AGENTS.md` only if the `agents` host is selected.
`graft init` merges into `.claude/settings.json` without clobbering, is
idempotent, and has `--dry-run`, `--agents claude`, `--no-hooks` and
`--no-statusline`. `graft build --deep` (LLM summaries) needs an API key and
is not used. The hosted side (`graft trail ...`, `graft init --trail`, and the
Graft GitHub App) sends code to a third party and is **opt-in only** (§12).
`graft uninstall` (dry-run without `-y`) is the inverse of `init`. Graft
sends anonymous usage events (buckets and fixed labels only, never code,
paths, queries or repo names; `TELEMETRY.md` upstream, and `graft telemetry
debug` prints the payload) and runs a daily npm version check. Events are
appended to `~/.graft/telemetry-queue.ndjson` and a detached child posts
one batch at most once a day, so no command waits on the network.
**Telemetry is off** (djbclark, 2026-10-11, revised the same day): the events
only feed upstream's product analytics (Nanonets PostHog); they give us nothing
locally, and builds from source, like djbclark's `~/src/Graft` checkout, have no
ingestion key and cannot send anyway. Measured cost when on is small (about
1.7 ms of local writes per command, one detached send a day, no tokens), so
cost is not the reason. Run `graft telemetry disable` after install and untick
the "anonymous usage stats" checkbox in `graft init`. The `[graft] tokens saved ≈
N` line in tool output is graft's savings report, not telemetry, and
`DO_NOT_TRACK` does not remove it or stop the version check (upstream
#580). Selecting the `agents` host also writes user-level `~/.codex/`
config and hooks; `--agents claude` does not, and `--no-global` skips them.

**Agent web access** (search and page fetch for every agent; added 2026-10-11)

| Tool | Website | Install | What it does |
|---|---|---|---|
| Exa MCP (remote) | https://exa.ai/ | `claude mcp add --transport http --scope user exa https://mcp.exa.ai/mcp`; the same URL in other clients' MCP configs. No key | Web search (`web_search_exa`) and page fetch (`web_fetch_exa`) |
| Parallel Search MCP (remote) | https://parallel.ai/ | `claude mcp add --transport http --scope user parallel-search https://search.parallel.ai/mcp`. No key | Web search by objective plus queries (`web_search`) and page fetch (`web_fetch`) |
| Jina MCP (remote) and Reader | https://jina.ai/ | MCP at `https://mcp.jina.ai/v1` with header `Authorization: Bearer $JINA_API_KEY`. Keep the key in the user's secret store (on djbclark's machine `sudo-secretspec`, entry `JINA_API_KEY`) and pass it through the client's headers helper where it has one (Claude Code `headersHelper`, Codex `http_headers_helper`); a client without one needs the literal header in a mode-0600 config outside git. Reader `https://r.jina.ai/<url>` also works keyless at a lower rate limit; Search `https://s.jina.ai/?q=` needs the key | `read_url`, `search_web`, `search_arxiv`, `extract_pdf` and more; Reader turns any URL into markdown |
| Crawl4AI | https://github.com/unclecode/crawl4ai | `uv tool install --python 3.13 'crawl4ai==0.9.4'`, then `crawl4ai-setup` (§1.2); `crawl4ai-doctor` checks it | Local headless-browser crawl: `crwl <url> -o markdown` renders JavaScript-heavy pages that plain fetches return empty. The package ships no MCP server; use the wrapper in the next row. A cold start under load takes 30-120 s |
| Crawl4AI MCP (`mcp-crawl4ai`, third-party wrapper) | https://pypi.org/project/mcp-crawl4ai/ | `uv tool install --python 3.13 'mcp-crawl4ai==0.3.1' --with crawl4ai==0.9.4 --with fastmcp==4.0.10 --with mcp==2.2.0 --with playwright==1.63.0`, then run ONE shared copy per machine, `crawl4ai-mcp --transport http --host 127.0.0.1 --port 18798`, under a login agent (launchd `KeepAlive`; djbclark's: site-djbclark `roles/shared_mcp`, `just shared-mcp-apply`), and register its URL `http://127.0.0.1:18798/mcp` as server `crawl4ai` in every agent (`claude mcp add --scope user --transport http crawl4ai http://127.0.0.1:18798/mcp`; Codex `url = …` with `tool_timeout_sec = 180`). Do not register the stdio command `~/.local/bin/crawl4ai-mcp`: each agent session would start its own Python + Playwright + 3 Chromium (~230 MB) (5.6). One server shares one browser across clients; concurrent calls work | MCP tools `scrape {targets}` (a URL or a list; not `url`), `crawl`; reuses the Playwright Chromium; first start about 26 s |
| Firecrawl MCP (shared, with `firecrawl-router`) | https://github.com/firecrawl/firecrawl-mcp-server; router: https://github.com/djbclark/djbclark-ade (`bin/firecrawl-router`) | `npm i -g firecrawl-mcp@3.23.7` and `ln -s ~/src/djbclark-ade/bin/firecrawl-router ~/.local/bin/firecrawl-router`, then run ONE shared copy per machine under a login agent: `firecrawl-router -- firecrawl-mcp` with `HTTP_STREAMABLE_SERVER=true HOST=127.0.0.1 PORT=18804`, `FIRECRAWL_SELFHOST_URL` + `FIRECRAWL_SELFHOST_API_KEY` (a self-hosted Firecrawl; djbclark's runs on SIPB Hyades, `skills/hyades-docker/examples/firecrawl/`) and optionally `FIRECRAWL_API_KEY` (commercial fallback); djbclark's: site-djbclark `roles/shared_mcp`, `just shared-mcp-apply-secrets`. Keys come from the secret store and live only in the 0600 LaunchAgent. Register `http://127.0.0.1:18804/mcp` as server `firecrawl` in every agent (Codex `tool_timeout_sec = 180`; agy through `mcp-proxy --transport streamablehttp`). No self-hosted instance: set only `FIRECRAWL_API_KEY` and `FIRECRAWL_SELFHOST_URL=https://api.firecrawl.dev` | `firecrawl_scrape` (JavaScript rendering, PDFs), `firecrawl_search`, `firecrawl_map`, `firecrawl_crawl`. The router sends each request to the self-hosted instance (no rate limit, no credits) and retries on the commercial API on a 5xx, an unreachable backend, a bot-walled page (status 202/403/405/429/503, or a short page whose text is a Cloudflare, Akamai, DataDome, HUMAN, Imperva, Vercel, AWS WAF or F5 challenge), or an empty map or search; crawl jobs stay on the backend that started them. Comparison and recommendation: `docs/firecrawl-commercial-vs-selfhosted-2026-10-14.md`. Give the self-hosted instance a SearXNG backend (`SEARXNG_ENDPOINT`; djbclark's is a SearXNG microVM on the same Hyades network, `build-searxng-image`) and make `firecrawl_search` the first search rung in every client's instructions: free, no rate limit. For Hermes, add `--listen 127.0.0.1:18805 --open` to the router and set `web.search_backend: firecrawl` with `FIRECRAWL_API_URL=http://127.0.0.1:18805` (Hermes never reroutes a failed search, so the router is its fallback). Added 2026-10-14 |
| `web-get` | https://github.com/djbclark/djbclark-ade (`bin/web-get`) | Symlink it into `~/.local/bin` (`ln -s ~/src/djbclark-ade/bin/web-get ~/.local/bin/web-get`, as for `acp-dispatch`) so the bare name resolves | Shell failover ladder: `web-get search '<query>'` (firecrawl, exa-api, exa-mcp, parallel, jina-mcp, jina-search, composio; firecrawl is a self-hosted Firecrawl's `/v2/search` with `FIRECRAWL_SELFHOST_API_KEY`, failing over at once without it), `web-get fetch '<url>'` (exa-api, exa-mcp, parallel, jina-reader, pdf, crawl4ai, firecrawl-mcp, wayback; firecrawl-mcp is the shared Firecrawl MCP below, so bot-walled pages reach the commercial API), `web-get check` (which providers work now). exa-api is the Exa REST API with the user's `EXA_API_KEY` from the secret store (header only, never argv); without it the keyless Exa MCP answers. PDF URLs get a local rung (curl into a fresh temp dir, then `pdftotext`; crawl4ai skips them). Wall-clock timeouts per attempt (45 s; crawl4ai 150 s; wayback and pdf 120 s). A soft-404 or redirect page fails its rung on every rung that reports a URL or title (`--no-page-check` for a page checked by hand). A body cut at a provider's cap is not success: the ladder walks on for a fuller copy (for at most `--walk-budget`, 300 s) and flags `truncated`, exit 6, only if none is found; a `--max-bytes` cut is the caller's choice and never hides a provider cap. The vault read runs before the ladder with its own timeout; child processes never get the keys. Exit 5 means every provider failed |
| `web-digest` (small-context models only) | https://github.com/djbclark/djbclark-ade (`bin/web-digest`) | `ln -s ~/src/djbclark-ade/bin/web-digest ~/.local/bin/web-digest`. Needs `web-get` on PATH (next to it in `bin/`). Add rule 6 of `research/sipb-llms/bench/rules.md` to the model's `CRUSH.md` | **Only for a model with a small context window** (Crush + Qwen3.6 35B A3B on SIPB LLMs, 32k tokens, no prompt cache). Claude, Codex, Grok and the other large-context agents keep their own web tools and `web-get`; do not point them at it. One call: `web-digest "<question>" [--url U] [--max-tokens 700] [--thorough]` searches and fetches through the `web-get` ladder, ranks passages against the question with BM25 (no model call), and prints a cited digest capped at 700 tokens (hard max 2000). Whole pages never reach the model. For Crush it is also exposed as a native MCP tool: `ln -s ~/src/djbclark-ade/bin/web-digest-mcp ~/.local/bin/web-digest-mcp` and `mcp add web --type stdio --command ~/.local/bin/web-digest-mcp` in `crushrc` (the model then calls `mcp_web_web_search`; it typed the shell command as text when it had only the CLI). Exit 5 plus `WEB-DIGEST FAILED` is the pause signal: the model must stop and tell the user, not answer from memory. Added 2026-10-14 |
| `skill-get` (small-context models only) | https://github.com/djbclark/djbclark-ade (`bin/skill-get`) | `ln -s ~/src/djbclark-ade/bin/skill-get ~/.local/bin/skill-get`. Keep the skills disabled in `crushrc` (`option disable-skill`); add rule 7 of `bench/rules.md` to `CRUSH.md` and the `skill` and `skills` commands in `~/.config/crush/commands/` | **Only for a model with a small context window** (same as `web-digest`); every other agent loads skills natively. Loads one skill on demand instead of preloading 124 descriptions each request: `skill-get --list` (names, ~700 tokens), `skill-get --list <keyword>` (one line each), `skill-get <name>` (SKILL.md body without frontmatter, 7000-character pages with the next-page command; `--ref references/x.md` for a file under the skill). In the Crush TUI (verified in tmux 2026-10-14): press `/` (it opens the command palette), type `skill`, Enter, fill SKILL and TASK; `skills` lists by keyword. The commands are `~/.config/crush/commands/skill.md` and `skills.md`. Added 2026-10-14 |
| `crush-context-check` (Crush on small-context models only) | https://github.com/djbclark/djbclark-ade (`bin/crush-context-check`) | `ln -s ~/src/djbclark-ade/bin/crush-context-check ~/.local/bin/crush-context-check`. Called by the `crush()` shell function in `~/.bashrc` (`[[ $# -eq 0 || $1 == -* ]] && crush-context-check \|\| return`) before the TUI starts: lists the context files Crush will auto-load (AGENTS.md, CLAUDE.md, ...), with a token estimate against the 32k window, and asks y / always / N. `CRUSH_CONTEXT_OK=1 crush` skips it. Stopgap for upstream charmbracelet/crush#4070. |
| `heavy-shim` | https://github.com/djbclark/djbclark-ade (`bin/heavy-shim`) | `ln -s ~/src/djbclark-ade/bin/heavy-shim ~/.local/bin/swift` and the same for `~/.local/bin/xcodebuild` (`~/.local/bin` sits ahead of `/usr/bin` on PATH). Needs site-djbclark's `bin/bg` at `~/ops/site-private/bin/bg` | PATH shim for agents with no hooks (agy, codex, cursor, …): `swift build\|test\|run` and any `xcodebuild` re-exec through `bg` (machine-wide test slot, load gate, `-j`/`-jobs` `BG_CPUS`, default 3); `swift package`, `--version`, `--help` and `xcodebuild -version` pass straight to `/usr/bin`. `BG_SHIM=1` is the loop guard. Added 2026-10-13 after a bare `swift test` ran one `swift-frontend` per core and took the load to 180 |

Register the MCP servers in user scope (back up `~/.claude.json` and the other
clients' configs first, §15), never in a committed `.mcp.json` when a key is
involved. The failover order per client, and the pause rule, are in
`djbclark-ade/skills/fallback-chains/references/web-access.md`. Put the rule
into the target's `AGENTS.md` (§8): an agent tries every rung; when the whole
ladder fails for a page or search the task needs, it pauses that work,
reports the failed URLs or queries with each error, and waits. It never
continues without the source or fills it in from memory.

**SiYuan notes (machine-specific; added 2026-10-12, djbclark).** Only where the
SiYuan desktop app (https://b3log.org/siyuan/) is installed and the repo's work
touches the operator's notes; skip it otherwise. SiYuan 3.8+ serves MCP from its
own kernel, so there is nothing to install or proxy: register
`claude mcp add --scope user --transport http siyuan http://127.0.0.1:6806/mcp`
(Hermes: `mcp_servers.siyuan` with the same URL, `tools.exclude` of `file`,
`http_request`, `web_fetch`, `web_search`, `unzip`). It works only while the app
runs and the kernel has no access auth code, so keep `networkServe` off. Skills:
`siyuan`, `siyuan-article-import`, `siyuan-excalidraw`, `siyuan-markdown`
(vendored from `zhiluop/siyuan-skills`, MIT, in `djbclark-ade/skills/`; link them
with `bin/skill-everywhere`). Their scripts read `~/.claude/siyuan.json`
(`api_url`, `local_path` and `"api_token": ""`: the key must exist but may be empty
unless the kernel sets an access auth code; `import_article.py` needs a patch for
SiYuan 3.8's `lsNotebooks` shape, see `skills/_shared/UPSTREAM.md`).

**MIT Athena (machine-specific; added 2026-10-16, djbclark).** **Only if the user has
an MIT Athena account (a Kerberos principal `<user>@ATHENA.MIT.EDU`); skip every item
in this block otherwise.** Ask first; never create or guess an account. Everything
below is the macOS setup in site-djbclark `macos/athena-kerberos/`
(https://github.com/djbclark/site-djbclark/tree/master/macos/athena-kerberos):

| Item | Website | Install | What it does |
|---|---|---|---|
| Kerberos renewal (`athena-kinit`) | https://github.com/djbclark/site-djbclark (`macos/athena-kerberos/`) | `macos/athena-kerberos/install.sh` (user level; first run `athena-kinit init` stores the password in the login Keychain). Apple's Heimdal `kinit`, `~/Library/Preferences/edu.mit.Kerberos` (realm `ATHENA.MIT.EDU`, forwardable, renewable 7 d), hourly LaunchAgent `com.djbclark.athena-kinit` | Keeps a renewable TGT; each renewal also runs `aklog` for the local AFS token and pushes the TGT to the Athena dialup and, if configured, a VPS. The dialups still require Duo after Kerberos (one shared ssh master; the `athena-master` and `athena-duo-askpass` scripts in the same directory) |
| AuriStor AFS client | https://www.auristor.com/filesystem/client-installer/ | Download the dmg for the installed macOS (macOS 27: `https://www.auristor.com/downloads/auristor/osx/macos-27.0/AuriStor-client-2021.05-72-GoldenGate.dmg`; the path is `osx/macos-<version>/`, find the current file name on the installer page), check `pkgutil --check-signature` on the `.pkg`, then `sudo installer -pkg Auristor-Lite.pkg -target /`. Edit `/etc/yfs/yfs-client.conf.d/thiscell.conf` to `thiscell = athena.mit.edu` (the pkg's cell dialog only runs in the GUI installer). On Apple Silicon the Mac needs Permissive Security with "allow user management of kernel extensions" (Startup Security Utility in Recovery; `sudo bputil -d` shows it), then Privacy & Security → Allow "AuriStor, Inc." and a reboot, which also creates `/afs` (`afs` line in `/etc/synthetic.conf`) | `/afs` with the Athena cell; the OpenAFS client has no maintained Apple Silicon build. The AuriStor EULA applies. Tokens: `aklog` (done by `athena-kinit`), check with `tokens` |
| `athena-locker` (`attach`, `detach`, `add`, `fsid`) and `/mit` | https://github.com/djbclark/site-djbclark (`macos/athena-kerberos/athena-locker`) | `macos/athena-kerberos/install.sh` links the commands into `~/.local/bin` and adds the `add` shell function to `~/.bashrc.local`; once as root `sudo /bin/sh macos/athena-kerberos/install-root.sh` makes `/mit` a synthetic symlink to `/Users/Shared/mit` (reboot). Lockers to pre-attach go in `~/.config/athena/lockers` (LaunchAgent `com.djbclark.athena-lockers`, hourly). Needs the AuriStor client above | Athena's `attach`/`add` on a Mac: Hesiod lookup (TXT `<name>.filsys.ns.athena.mit.edu`), `aklog -path`, symlink into `/mit`. Not on demand: a locker must be attached before `cd /mit/<locker>` (Athena's FUSE `pyhesiodfs` is not reproduced). Most locker binaries are Linux builds, so only scripts and data lockers are useful |

**GitHub-side services** (accounts and app installs happen in the interactive phase)

| Service | Website | What it does |
|---|---|---|
| GitHub Actions | https://docs.github.com/actions | CI running the same `just` gates |
| CodeRabbit | https://www.coderabbit.ai/ | AI pull-request review, label-gated by `review-ready` |
| coderabbit-feeder (private; used via a generalized fork, §14) | https://github.com/djbclark/coderabbit-feeder | Queues and paces CodeRabbit reviews of an entire codebase. Kuriboh493 already has access |
| Semgrep AppSec Platform (optional) | https://semgrep.dev/ | Hosted Semgrep scanning. Only if the user opts in |

**Kotlin (deliberate exception).** Do not install Kotlin tooling until Kotlin
code appears. Then copy `stayturgid`'s Gradle-plugin setup (Spotless + ktfmt,
detekt with a baseline, Konsist, JUnit 5/Kotest, Kover). Those tools are pinned
inside Gradle and are not meaningful as global installs.

---

## 2. Coverage rule for unlisted languages and formats

Inventory every tracked file type (`git ls-files | gsed 's/.*\.//' | gsort | guniq -c`,
plus extensionless scripts identified by shebang). For **any language or format
not covered in §1**, have a `researcher` find tools in the same spirit and treat
them as if they had been on the original list. The spirit is:

- a deterministic formatter, a linter, a type/static checker where one exists,
  and a security check where relevant;
- free and open source; installable through Homebrew, `uv tool`, or a locked
  `bun`/`uv` dev dependency; offline-capable; pinnable;
- runnable from `just`, pre-commit and CI.

For each one, report the website, install command, purpose and why it was
chosen. Then install it and wire it in exactly like the other tools.

---

## 3. Phase order (strict)

1. **Inspect** the target and the reference repos (§4).
2. **Install** all tools (§1–§2).
   - 2a. **Backup system:** create the backup store and its restore `justfile`
     (§15) before the first change to any untracked file.
   - 2b. **Subagents:** create `.claude/agents/*.md` (§0.3).
   - 2c. **Skills and plugins:** install the "yes" set from §0.6.
   - 2d. **Fork and generalize:** fork any reference project you will *run*
     that contains djbclark-specific hardcoding (§14). Do this before using any
     of those projects.
3. **Baseline:** write characterization tests against the *unchanged* code, run
   them, and record the outputs (§5). Do not change product code before this.
4. **Configure** the tooling (§6).
5. **Backport:** apply the tools across the existing codebase, re-running the
   baseline after each step (§7).
6. **Documentation and agent integration:** `AGENTS.md` plus `CLAUDE.md`
   import, the skill, README, and license (§8–§10).
7. **CI** (§11).
8. **Interactive phase** (§12): accounts, GitHub-side installs, the plugin
   walkthrough, approvals for forks and pushes, and a CodeRabbit test.
9. **Last:** feed the entire codebase to CodeRabbit through coderabbit-feeder
   (§13), only after everything above is verified working.

Update `HANDOFF.md` at the end of every phase.

---

## 4. Inspect first

Fan this out to `scout` subagents in parallel (§0.4). Each returns a compact
summary of the specific facts requested, with file paths.

**Target repo:** record the branch, `git status`, the Python version implied by
syntax and dependencies, how each script is invoked, existing tests, the full
`.gitignore`, existing hooks (including `core.hooksPath`), any existing
`AGENTS.md`/`CLAUDE.md`/`.claude/`, `LICENSE` and CI. Preserve unrelated local
changes. Do not assume a `src/` layout or an existing `tests/` directory.

**Reference repos.** All are public except `coderabbit-feeder`. Read their
current default branches. Do not copy them blindly.

- `djbclark/stayturgid`: `docs/toolchain.md` (the canonical toolchain and the
  "N+1 pattern": every tool appears in `justfile`, `.pre-commit-config.yaml`,
  its config file and CI), `.pre-commit-config.yaml`, `pyproject.toml`,
  `justfile`, `just/tests.just`, `package.json`, `.shellcheckrc`,
  `.coderabbit.yaml`, `AGENTS.md`, `docs/hacking.md`
- `djbclark/aiuse`: `pyproject.toml`, `.pre-commit-config.yaml`, `justfile`,
  `.yamllint`, `.markdownlint.json`, `package.json`, `.github/workflows/test.yml`,
  `AGENTS.md`
- `djbclark/site-djbclark`: `docs/tooling-policy.md`,
  `brew/fragments/agent-cli-tools.yml`, `.coderabbit.yaml`, `AGENTS.md`
- `djbclark/ops-djbclark`: `AGENTS.md` (non-interactive command rules),
  `docs/ops-worktrees-layout.md` (cross-agent rules),
  `docs/headless-claude-worker.md` (permission policy for unattended runs)
- `djbclark/claude-orchestration-skills`: `README.md`, `plugins/`
  (orchestration discipline, session handoff)
- `djbclark/RevengeQuickSwitcher`: its `justfile`, which mirrors the stayturgid
  tooling in a TypeScript project
- `djbclark/coderabbit-feeder` (private): `README.md`, `pyproject.toml`, `src/`
- `frdminc/tendcf` (a focused schema linter, `bin/schema_lint.py`, run from
  CI and from a plain `.githooks/pre-commit` via `core.hooksPath`; not the
  pre-commit framework), `frdminc/Shizuku` (`review-ready` convention in
  `.coderabbit.yaml`), `frdminc/sudo-secretspec` (`CLAUDE.md`, CHANGELOG
  discipline)
- `trailhq/Graft`: `README.md` (Quick start, Claude Code integration, CLI,
  uninstall), `package.json`, `docs/`
- other relevant public repos under https://github.com/djbclark and https://github.com/frdminc

Distinguish active, historical, project-specific and **deliberately retired**
policy. Cite the repo and file for each notable choice. Do not claim the review
was exhaustive if it wasn't.

---

## 5. Baseline characterization tests (before any tooling change)

Delegate to `test-author` (Opus); Python and HTML/JS tests can be written in
parallel by two subagents with disjoint files.

1. Create `tests/` (pytest) and, for the HTML app, a Puppeteer smoke test.
2. Write tests that pin **current behavior**, not desired behavior:
   - Python: pure functions in `common/` and the analysis scripts. Use small
     synthetic inputs, never the 90 GB data. Use mathematical invariants where
     they apply (no-arbitrage bounds, non-negative prices, put–call parity,
     monotonicity, zero-volatility and zero-jump limits) plus golden values
     captured from the current code. Use explicit tolerances.
   - HTML pricer: load `perps/index.html` from `file://`; click each preset
     (BTC/ETH/US stock/Gold), each model (Merton/Bates) and European/everlasting;
     assert no console errors or uncaught exceptions; assert price/Greeks fields
     are finite; capture golden displayed values for the default preset. Also
     extract the pure `<script id="math">` functions (`Ncdf`, `black`,
     `fairPerp`, `euro`, `impliedVol`, …) in a Node test and assert invariants
     and golden values.
   - Scripts that need missing data: assert they import or parse arguments
     cleanly, or mark them `@pytest.mark.data` and skip by default.
3. The orchestrator runs everything (or has a `verifier` run it) and **records
   the outputs** in `tests/baseline/BASELINE.md`: the date, commit SHA,
   interpreter and tool versions, commands, full pass/fail output, and the
   golden values. Commit the golden data with the tests.
4. Rule: if a baseline test fails on the untouched code, it is a finding. Record
   it and do not "fix" the product code to make it pass.

---

## 6. Tooling configuration

Split distinct config files across parallel `config-writer`s. The orchestrator
writes the `justfile` and `.pre-commit-config.yaml` itself, because they tie
everything together.

Follow stayturgid's **N+1 pattern**: every tool appears consistently in the
`justfile`, `.pre-commit-config.yaml`, its config file, and CI.

- **`pyproject.toml` + `uv.lock`:** runtime deps (numpy, scipy, pandas, pyarrow)
  and a `dev` group (pytest, ruff, mypy, bandit, yamllint, pre-commit).
  Don't invent a license string before §10. Don't create a package/`src/`
  migration.
  - Ruff: `line-length = 120`, target matching Python, `select = ["E","F","I","W"]`,
    `ignore = ["E501","E402"]`, `line-ending = "lf"`. Evaluate `UP`, `B` and `SIM`
    (used in coderabbit-feeder).
  - mypy: `explicit_package_bases`, `ignore_missing_imports`,
    `warn_redundant_casts`, `warn_unused_ignores`, `warn_unreachable`,
    excluding `.venv/` and data.
  - pytest: `testpaths = ["tests"]` and a `data` marker excluded by default.
- **`package.json` + `bun.lock`:** all JS and web dev deps from §1, with
  `"trustedDependencies": ["vnu-jar"]` and `"private": true`.
- **Config files:** `.yamllint` (aiuse's: `extends: default`, line length 160,
  truthy values `["true", "false"]`, forbid implicit and explicit octal),
  `.markdownlint.json` (aiuse/stayturgid rule set: `default: true` with
  MD013, MD024, MD028, MD029, MD031, MD033, MD034, MD036, MD038, MD040, MD041,
  MD046 and MD056 off), `.html-validate.json`, `.stylelintrc.json`,
  `biome.json`, `.shellcheckrc`, `.typos.toml` (only for real domain words such
  as Kalshi, Polymarket, Deribit, Bates), and `.coderabbit.yaml` exactly as
  stayturgid and Shizuku have it:

  ```yaml
  reviews:
    auto_review:
      enabled: false
      labels:
        - "review-ready"
  ```

- **`justfile`** (`set shell := ["bash", "-uc"]`) with recipes for:
  `setup test baseline ruff mypy bandit yamllint markdownlint prettier typos
  html-validate vnu stylelint biome tsc pa11y puppeteer lighthouse lychee-docs
  shellcheck shfmt actionlint dotenv-linter pyinilint gitleaks semgrep-audit
  graft-build just-check check lint lint-offline format pre-commit ci`.
  - Every recipe works on `git ls-files` output or explicit paths, never the
    data directories.
  - A recipe for a format that is absent passes with "no files", so tools stay
    wired in for later.
  - Browser-dependent checks (Lighthouse) are skipped cleanly when Chrome is
    unavailable. `lint-offline` skips anything network-dependent.
  - `check` is the fast deterministic gate, `lint` is `check` plus security, and
    `ci` is exactly what GitHub Actions runs.
- **`.pre-commit-config.yaml`**, with
  `default_install_hook_types: [pre-commit, pre-push]`:
  - **pre-commit:** fast file-level checks: Ruff fix+format, typos,
    markdownlint, Prettier check, yamllint, html-validate, Stylelint, Biome,
    ShellCheck, shfmt, actionlint, dotenv-linter, pyinilint, `just --fmt --check`,
    Bandit, Gitleaks.
  - **pre-push:** pytest, mypy, the Node/Puppeteer tests and `vnu`.
  - Never recurse. Never silently `git add` generated output: copy stayturgid's
    pattern in `.pre-commit-config.yaml` that fails and names the unstaged
    files so the developer reviews and stages them.
- **Semgrep policy:** install it and add `just semgrep-audit` using a
  **curated** ruleset (for example `p/python`, `p/security-audit`) with
  `--metrics off`. Do **not** add `--config auto` as a blocking gate. stayturgid
  removed its semgrep pre-commit hook on 2026-08-23 (commits `0319f25` and
  `3cf92e3`) after an audit found it only produced unjustified suppressions and
  false positives. Promote a curated ruleset to a gate only if its findings on
  this repo are actionable, and every suppression must carry a written
  justification.
- **Graft:** back up `.claude/settings.json` and `~/.claude/settings.json`
  (§15), then run `graft init --dry-run` and show the file list in
  `HANDOFF.md`. If it is acceptable, run `graft init --agents claude` and
  `graft build`. Follow upstream: `graft/` stays git-ignored (it is a local
  cache), the `.claude/` and `.mcp.json` wiring is committed, and
  `just graft-build` wraps `graft build`. Keep the hooks only if a trial session shows they are not
  noisy; otherwise re-run `graft init --no-hooks`. If `init` fails, needs
  credentials, or the graph adds noise, document that it was declined and
  run `graft uninstall` (dry-run first).
- **`.gitignore`:** add caches (`.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`,
  `node_modules/`, `.coverage`, `htmlcov/`, browser and lighthouse output,
  `graft/` if `graft build` did not add it) and keep the data/report
  exclusions.
- Install hooks (back up any existing untracked `.git/hooks/*` first, §15):
  `uv run pre-commit install --hook-type pre-commit --hook-type pre-push --install-hooks`.

---

## 7. Backport the tools into the existing codebase

**Sequential, one tool at a time.** Order: formatters (Ruff format, Prettier,
Biome, shfmt), then safe autofixes (Ruff `--fix`), then linters, types,
HTML/CSS, accessibility and security.

For each tool:

1. A `backport-worker` applies that one tool's changes to the paths it is
   assigned.
2. A `verifier` runs `just baseline` and compares against
   `tests/baseline/BASELINE.md`. Golden values must match within tolerance, and
   no test may regress.
3. If the diff touches numerical code or `perps/index.html`, a
   `numeric-reviewer` checks that nothing changed meaning: no reordering of
   floating-point operations, no altered constants, no changed defaults.
4. The orchestrator checks the diff itself, then makes one focused local commit
   per tool, e.g. `style: apply ruff format`.

Independent read-only checks of the result (e.g. running several linters) can
run in parallel. Edits cannot.

Rules:

- Fix real findings. Use **narrow, justified** suppressions only; a bare
  `# noqa`/`# nosemgrep` without a reason is not allowed.
- If fixing a finding would change results, stop and report it instead.
- For the HTML pricer, keep it single-file and dependency-free. If a reformat
  would produce a huge diff that is hard to review, prefer lint-only plus
  targeted fixes and record that decision.
- Finish with `just ci`, `just lint` and `just baseline` all green, and record a
  final run below the baseline in `BASELINE.md`.

---

## 8. Agent instructions file and skill

`docs-writer` drafts; the orchestrator reviews.

**Which file:** `AGENTS.md` is canonical (the cross-vendor convention). Claude
Code auto-loads only `CLAUDE.md`, so also create a `CLAUDE.md` whose entire
content is the import line `@AGENTS.md` (or a symlink, if the user prefers;
imports are the portable choice). If a `CLAUDE.md` with real content already
exists, move that content into `AGENTS.md` and leave the import behind. Never
maintain two divergent copies. Add these sections:

1. **Required skill.** "Before any code change, load and follow the
   `dev-tooling` skill at `.claude/skills/dev-tooling/SKILL.md`."
2. **Commands:** `just setup`, `just test`, `just check`, `just lint`,
   `just format`, `just ci`, `just baseline`.
3. **Subagents, skills and plugins:** list `.claude/agents/`, the installed
   plugins and skills from §0.6 with one line each, the model routing rule
   (Haiku mechanical, Sonnet standard, Opus for numerical correctness and
   risky judgment, never Fable unless the user asks), the §0.2 rules, and the
   parallelism rule (parallel reads, disjoint writes, one tool at a time for
   codebase-wide changes).
4. **Testing rules** (from stayturgid, aiuse and coderabbit-feeder):
   - Run the full test suite before **and** after every change.
   - Every bug fix gets a regression test. Every new feature gets tests.
   - Pin behavior with characterization or golden tests before refactoring.
   - For numerical code, test invariants with explicit tolerances.
   - Tests are offline and deterministic. Tests that need data are marked
     `data` and excluded from CI.
   - Never weaken or delete a test to make it pass.
5. **Coding and workflow guidelines** (from the reference repos; adjust as needed):
   - Make one coherent change at a time. Commit early and often.
   - Don't trust a clean exit code; verify real outputs and state (ops-djbclark).
   - Use non-interactive command forms (`cp -f`, `mv -f`, `rm -f`, `ssh -o
     BatchMode=yes`) (ops-djbclark).
   - `HOMEBREW_NO_AUTO_UPDATE=1` is a performance knob, not an update switch: it
     suppresses brew's implicit `brew update` in front of install/upgrade (slow,
     and it can fail on a flaky network) and does **not** stop anything updating
     (the scheduled `brew-fast-upgrade` job owns that; `site-djbclark/shell/bashrc`
     exports it machine-wide). Keep it on long automated install lines.
   - Prefer `rg`, `fd`, `bat` and `srgn` in shell (`srgn --fail-none`, never
     `sd`, for edits: it must fail when nothing matched); use `ast-grep`/`semgrep` for
     code-shape queries; use the Graft tools before broad source reading
     (site-djbclark, Graft).
   - Run `typos` before finalizing docs.
   - Keep the N+1 pattern in sync and bump tool versions in lockstep across
     `pyproject.toml`, `package.json`, `.pre-commit-config.yaml` and CI
     (stayturgid).
   - Suppressions need a written justification (stayturgid's Semgrep audit).
   - Never commit secrets. Gitleaks runs on every commit.
   - Hooks must not silently stage generated files.
   - Before merging, check provenance:
     `git log origin/main..HEAD` and `git diff origin/main...HEAD`. Green CI does
     not replace knowing what you are merging (ops-djbclark).
   - Never commit into a branch or worktree another agent created.
   - Back up untracked files before changing them.
   - No environment-specific hardcoding: use config, environment variables or
     derived values, with committed `*.example` files.
   - Keep a `CHANGELOG.md` "Unreleased" section for user-facing changes
     (sudo-secretspec).
   - Research results must not change silently. Any change to a model or number
     needs a test and a note.
6. **Review:** add the `review-ready` label to request a CodeRabbit review. Bulk
   or full-codebase reviews go through coderabbit-feeder; never create
   throwaway PRs by hand. Use `/code-review` and the `pr-review-toolkit`
   agents for the in-session pass first.

**Skill:** create `.claude/skills/dev-tooling/SKILL.md` using the
`skill-creator` plugin from §0.6, following the current skills docs
(https://code.claude.com/docs/en/skills; the vendor-neutral spec is
https://agentskills.io/specification if reachable), with YAML frontmatter:

```yaml
---
name: dev-tooling
description: Use this repository's quality toolchain (just, uv, pytest, ruff, mypy, pre-commit, HTML/CSS/JS checkers, security scanners, graft, CodeRabbit) and its subagents when writing, changing, testing, or reviewing code here.
---
```

The skill body should cover:

- a decision table: change type → which `just` recipes to run, and which
  subagent to use;
- the before/after-test rule and `just baseline`;
- how to add a test of each kind (pytest, Node math, Puppeteer);
- how to add a new language or format (§2 rule plus N+1 wiring);
- search-tool selection (Graft MCP / `graft ask` / `ast-grep` / `rg`);
- the token budget rules from §0.5, in short form;
- the suppression policy;
- how to request review (`review-ready` label; coderabbit-feeder for bulk).

Validate it with `skill-creator`'s evaluation, or with `skills-ref validate
.claude/skills/dev-tooling` if that validator is installed. Mirror the skill
at `.agents/skills/dev-tooling/SKILL.md` (or symlink it) so non-Claude agents
find it.

---

## 9. README

Keep the existing README content. Add a **Development** section covering macOS
bootstrap (the Homebrew one-liner from §1.2), `just setup`, the hook install,
daily commands, the testing rules, a pointer to `AGENTS.md` and the skill, the
plugin list, and the CI badge. Replace the manual `python -m venv` setup with
`uv`, but keep the "run scripts from their own folder" note.

---

## 10. License (interactive; only if no license exists)

If there is no `LICENSE`, ask the user **one question at a time**, waiting for
each answer:

1. Do you want others to be allowed to use, copy and modify this code at all?
   (If no: say no license file is needed, all rights stay reserved, and stop.)
2. Do you require anyone who distributes modified versions to publish their
   source under the same terms (copyleft)?
3. If yes: should that also apply when it is only offered over a network (AGPL),
   or only on distribution (GPL-3.0)? Is linking from proprietary code acceptable
   (LGPL/MPL-2.0)?
4. If no (permissive): do you want an explicit patent grant and
   patent-retaliation clause (Apache-2.0), or the simplest short license (MIT)?
5. Should the written research and documentation use a separate content
   license, e.g. CC BY 4.0?
6. Whose name and what year go in the copyright line?

Recommend one license with a one-sentence rationale. Point to
https://choosealicense.com/ for comparison. Once the user confirms, add the
canonical `LICENSE` text, set `license` in `pyproject.toml` and `package.json`
(`private: true` stays), and mention the license in the README.

---

## 11. CI

Add `.github/workflows/ci.yml`:

- runs on `pull_request` and `push` to `main`, with least-privilege
  `permissions: contents: read`;
- installs Python through `uv`, plus `just`, Bun, Java (for vnu) and Chrome
  (for Puppeteer);
- installs dependencies from the lockfiles (`uv sync --frozen`,
  `bun install --frozen-lockfile`);
- runs `just ci`, plus `actionlint` on the workflow itself;
- no secrets, no dataset downloads, no live market APIs;
- actions pinned to current stable majors. aiuse's workflow uses
  `actions/checkout`, `actions/setup-python`, `astral-sh/setup-uv`,
  `extractions/setup-just` and `oven-sh/setup-bun`; have a `researcher` check
  the current major of each rather than copying aiuse's pins.

Run `actionlint` locally before finishing.

---

## 12. Interactive phase: one step at a time

Only start after §5–§11 pass locally. For **each** step: say what it does, give
the exact command or URL, say what the user should see, then **wait for
confirmation** before giving the next step. Troubleshoot anything that doesn't
match. Skip steps that are already done (check first). No subagents here.

1. **Homebrew password:** only if §1.1 needed interactive authorization.
2. **Skills and plugins walkthrough** (§0.6): one item per turn, with what it
   is, how to invoke it, when to use it and how to remove it. Keep or drop
   each on the user's answer, then update `AGENTS.md`.
3. **GitHub CLI login:** `gh auth login` → GitHub.com → HTTPS → log in with a
   web browser. Then verify with `gh auth status` and
   `gh api /user --jq .login` (expected: `Kuriboh493`).
4. **Verify feeder access:** `gh repo view djbclark/coderabbit-feeder`. If it
   fails, the user checks https://github.com/notifications for a pending
   invitation and accepts it.
5. **Approve forks** (§14.2): for each repo that needs generalizing, confirm
   creating the fork and its visibility (private stays private).
6. **Notification preference** for forked tools such as coderabbit-feeder:
   none, log only, or the user's own command.
7. **Approve pushing each generalized fork branch** (§14.3).
8. **License questions** (§10), if no license exists yet.
9. **Review local commits:** show `git log --oneline origin/main..HEAD` and
   `git diff --stat origin/main...HEAD`, and get explicit approval.
10. **Authorize the push:** with the user's yes, run `git push origin main` (or
    push a branch and open a PR if the user prefers).
11. **GitHub Actions:** check
    https://github.com/Kuriboh493/perp-option-pricer/settings/actions allows
    Actions, then confirm the first run is green with `gh run list --limit 1`.
12. **CodeRabbit account:** go to https://www.coderabbit.ai/ → sign up with GitHub.
13. **CodeRabbit GitHub App:** install it on **only selected repositories** →
    `Kuriboh493/perp-option-pricer`. Review the permissions it requests.
14. **CodeRabbit plan:** note the plan and its review rate limit. The feeder's
    pacing assumes CodeRabbit's "Next review available in: N minutes" messages.
15. **Verify CodeRabbit:** open a tiny test PR, add the `review-ready` label,
    and confirm that a real CodeRabbit review appears. Close the PR afterwards
    without merging unless the user says otherwise.
16. **Optional branch ruleset:** require PRs and the CI check (use the real
    check name from step 11).
17. **Optional Semgrep platform:** explain that it sends code to a third party;
    proceed only if the user opts in (https://semgrep.dev/ → sign in with
    GitHub → select the repo).
18. **Optional Graft hosted (Trail) integration and GitHub App:** same opt-in
    rule. Local mode needs no account and is what §6 set up.
19. **Optional upstream suggestions** (§14.4): show each draft; open it only on
    approval.

---

## 13. Last step: feed the entire codebase to CodeRabbit with coderabbit-feeder

Do this only after the interactive phase is complete, CI is green, CodeRabbit
has produced a verified review, and the tooling commits are pushed. The
orchestrator does this directly, without subagents.

1. **Clone the generalized fork** (§14), not `djbclark/coderabbit-feeder`, into
   its own source checkout:

   ```bash
   gh repo clone Kuriboh493/coderabbit-feeder ~/src/coderabbit-feeder
   cd ~/src/coderabbit-feeder && git remote -v && uv sync --group dev && uv run pytest
   ```

   `git remote -v` must show `origin` pointing at the fork and `upstream` at
   `djbclark/coderabbit-feeder`.
2. **Read** its current `README.md`, `src/coderabbit_feeder/{cli,feeder}.py`,
   and `coderabbit-feeder --help` (subcommands as of 2026-08: `tick`, `build`,
   `list`, `add`, `add-crossfork`). Confirm the details below against the code
   before relying on them.
3. **Confirm the generalization from §14 is in place.** The known hardcoding
   that must already be fixed in the fork: `NOTIFY_TARGET` in `feeder.py`
   (djbclark's Telegram target), the unconditional `hermes send` call in
   `notify()` (it raises `FileNotFoundError` when `hermes` isn't installed,
   because `check=False` does not catch a missing executable), and every
   `/Users/djbclark`, `~/ops`, `com.djbclark.*` or `djbclark/...` default in
   code, docs, plists and examples. The user's chosen notification setting
   lives in local untracked config.
4. **Use an independent runtime directory.** Never use djbclark's queue or
   state. Back up any existing directory first (§15).

   ```bash
   mkdir -p ~/.config/coderabbit-feeder && cd ~/.config/coderabbit-feeder
   ```

   Always invoke it as:

   ```bash
   uv run --project ~/src/coderabbit-feeder coderabbit-feeder <cmd>
   ```

   Use **`--project`, never `--directory`.** `--directory` changes the working
   directory and writes the queue into the source checkout, where the
   scheduler never reads it (this is documented in the feeder's README).
5. **Configure `repos.toml`** in the runtime directory, following the format in
   the feeder's source. Point it at a dedicated, clean worktree of the target
   (for example `~/src/feeder-workspace/perp-option-pricer`), never the
   development checkout, with `gh_repo = "Kuriboh493/perp-option-pricer"`.
6. **Build the queue:** `coderabbit-feeder build`. It chunks the repo's tracked
   files into batches of at most 300 (CodeRabbit's review-slot limit). Then
   check `coderabbit-feeder list` and confirm the batches cover every tracked
   file and nothing from the data directories. Tell the user how many
   throwaway "audit" PRs this will open, and get confirmation.
7. **Smoke-test:** run `coderabbit-feeder tick` once by hand. Verify a real
   audit PR opened, it got the `review-ready` label and `@coderabbitai review`
   trigger, and `list` shows the queue advancing.
8. **Schedule it:** ask the user to choose between running `tick` manually or
   periodically, or installing a per-user LaunchAgent (`StartInterval` 300,
   `WorkingDirectory` = `~/.config/coderabbit-feeder`, `ProgramArguments` =
   `uv run --project ~/src/coderabbit-feeder coderabbit-feeder tick`, logs in
   that directory, a label in the user's own namespace, not `com.djbclark.*`).
   Install the LaunchAgent only if the user says yes, and record it in the
   backup manifest as "absent" so it can be removed (§15). Verify it with
   `launchctl list | ggrep coderabbit-feeder` and a log line showing a tick.
9. **Explain how to watch and act on results:** findings land in
   `~/.config/coderabbit-feeder/findings/`. Fix actionable findings with
   normal PRs under the AGENTS.md rules. The feeder never auto-commits fixes.

---

## 14. Fork and generalize anything with environment-specific hardcoding

Any reference project that you will **run, install from source or copy code
out of** (not merely read) must be checked for values specific to djbclark's
environment. If it has any, **fork it, generalize the fork, and use the fork**.
Never point the user's tools at djbclark's live infrastructure, accounts or
messaging.

### 14.1 Detect (`fork-auditor`, Opus)

In every candidate repo, search code, docs, configs, plists, workflows,
templates and tests:

```bash
rg -n -i --hidden -g '!.git' \
  -e 'djbclark' -e 'frdminc' -e '/Users/[A-Za-z0-9_-]+' -e '~/ops\b' -e 'site-(djbclark|private)' \
  -e 'telegram:' -e '\bhermes\b' -e 'com\.djbclark\.' -e '@(gmail|mit)\.(com|edu)' \
  -e 'greyhound|\.ts\.net' -e '100\.[0-9]+\.[0-9]+\.[0-9]+' -e 'ops-worktrees'
```

Then read each hit in context and classify it as one of:

- **environment-specific:** must be generalized (usernames, home paths,
  hostnames, Tailscale names or IPs, notification targets, email addresses,
  LaunchAgent labels, repo owners used as defaults, account names);
- **attribution or history:** leave it (copyright lines, changelog entries,
  upstream issue links, `authors` metadata);
- **intentional upstream reference:** leave it, but make it configurable if it
  is used as a default (e.g. `gh_repo` defaults).

Known case: `djbclark/coderabbit-feeder` (`NOTIFY_TARGET`, `hermes send`,
`/Users/djbclark/...` and `com.djbclark.coderabbit-feeder` in its README's
launchd instructions). Also check anything copied out of `stayturgid`,
`site-djbclark`, `aiuse` or `claude-orchestration-skills`, such as justfile
snippets that reference `~/ops/stayturgid`, `STAYTURGID_*` variables, `site-*`
discovery, or `~/src/ops-worktrees` paths (the `session-handoff` plugin's
default paths are its author's layout; adapt them). Templates and snippets
copied into the target repo get the same treatment, without forking.

Audits of different repos can run in parallel.

### 14.2 Fork (orchestrator, after user approval)

For each repo that needs changes:

```bash
gh repo fork <owner>/<repo> --clone=false --fork-name <repo>
#   creates Kuriboh493/<repo>. Keep a private source private; check with:
gh repo view Kuriboh493/<repo> --json visibility,parent
gh repo clone Kuriboh493/<repo> ~/src/<repo>
cd ~/src/<repo> && git remote add upstream https://github.com/<owner>/<repo>.git 2>/dev/null || true
git switch -c generalize-environment
```

If forking is blocked (for example, forking is disabled on the private repo),
stop and hand it to the interactive phase: the user asks djbclark to enable
forking or to push a generalized branch.

### 14.3 Generalize (`fork-generalizer`, one per repo, in parallel)

- Replace each hardcoded value with, in order of preference: a config file
  entry (with documented defaults), an environment variable, a CLI flag, or a
  value derived at runtime (`$HOME`, `gh api /user --jq .login`,
  `git remote get-url origin`).
- Defaults must be **safe and generic**. For notifications, the default is
  "log only". Optional notify commands run only when configured, and a missing
  executable is reported, never raised as an uncaught error.
- Where the user's own environment needs a specific value (their username,
  paths or notification choice), put it in a **local, untracked config file**
  plus a committed `*.example`. Do not hardcode the user's values in place of
  djbclark's.
- Update docs, README examples and plist templates to match.
- Add tests for each new configuration path, including "no notifier
  installed" for the feeder.
- Run the fork's own test suite before and after.
- Record each change in the fork's `CHANGELOG.md` "Unreleased" section.
- The orchestrator verifies the result, commits, and pushes to the **fork**
  only after user approval (§12). Never push to the upstream repo.

### 14.4 Use the fork, and offer it upstream

- All later steps (§13 especially) use the fork's clone.
- Draft an upstream issue or PR description explaining that the changes make
  the project portable (configurable values, safe defaults, no behavior change
  for djbclark when he sets his own config). Show it to the user; open it only
  if they approve.
- List every fork, its upstream, its branch and its changes in the final report.

---

## 15. Backups of untracked files, with a restore justfile

### 15.1 Store

Create one backup store for the whole session:

```bash
BACKUP_ROOT="$HOME/.local/state/perp-tooling-backups"
SESSION="$(date +%Y%m%dT%H%M%S)"
mkdir -p "$BACKUP_ROOT/$SESSION" && chmod 700 "$BACKUP_ROOT"
```

It lives outside every repo, so git operations can't delete it and it is never
committed.

### 15.2 Rule for each file

Before the first edit, overwrite, move or delete of any **untracked** path,
check `git ls-files --error-unmatch <path>` in its repo (or note that it is
outside any repo). If it is not tracked:

1. Copy it, keeping its metadata: `cp -p` for files, `cp -pR` for
   directories. For a symlink, record the link itself (`cp -P`) and its target.
2. If the path **does not exist yet** (you are about to create it), record an
   "absent" marker so restoring means removing what you created.
3. Back up each path only once per session. The first copy is the true
   original.
4. Append a line to `$BACKUP_ROOT/$SESSION/MANIFEST.tsv`:
   `id  original_path  kind(file|dir|symlink|absent)  sha256  reason`.
5. Never print the contents of files containing credentials. Note in the
   manifest that a backed-up file contains secrets.

Typical candidates: `~/.zshrc`, `~/.bash_profile`, `~/.gitconfig`,
`~/.claude/settings.json`, `~/.claude/plugins/*` (plugin installs edit it),
`.claude/settings.json` in the target (Graft and `/fewer-permission-prompts`
edit it), `.git/hooks/*`, `~/Library/LaunchAgents/*.plist`, `~/.config/*`, any
existing `~/.config/coderabbit-feeder/`, untracked or ignored files in the
target repo (e.g. a local `.venv`, local configs), and Homebrew-created shell
setup lines.

Subagents never write backups or the restore justfile. They tell the
orchestrator which untracked paths they need to change, and the orchestrator
backs them up first.

### 15.3 Restore justfile

Maintain `$BACKUP_ROOT/justfile` and update it as each backup is taken:

```just
set shell := ["bash", "-euo", "pipefail", "-c"]

backups := justfile_directory()

# List everything that can be restored (default).
default:
    @just --justfile "{{ backups }}/justfile" --list --unsorted
    @echo
    @echo "Manifest:"
    @column -t -s $'\t' "{{ backups }}"/*/MANIFEST.tsv

# Restore ~/.zshrc from session 20261001T120000 (backed up before adding PATH lines).
restore-zshrc-20261001T120000:
    #!/usr/bin/env bash
    set -euo pipefail
    src="{{ backups }}/20261001T120000/files/zshrc"
    dst="$HOME/.zshrc"
    if [[ -e "$dst" ]]; then cp -p "$dst" "$dst.pre-restore.$(date +%Y%m%dT%H%M%S)"; fi
    cp -p "$src" "$dst"
    echo "restored $dst"

# Remove ~/Library/LaunchAgents/<label>.plist (it did not exist before this session).
restore-launchagent-feeder-20261001T120000:
    #!/usr/bin/env bash
    set -euo pipefail
    dst="$HOME/Library/LaunchAgents/<label>.plist"
    launchctl bootout "gui/$(id -u)" "$dst" 2>/dev/null || true
    if [[ -e "$dst" ]]; then mv -f "$dst" "$dst.pre-restore.$(date +%Y%m%dT%H%M%S)"; fi
    echo "removed $dst (restored to absent)"

# Restore every backup from a session, in reverse order of capture.
restore-all-20261001T120000:
    @just --justfile "{{ backups }}/justfile" restore-launchagent-feeder-20261001T120000
    @just --justfile "{{ backups }}/justfile" restore-zshrc-20261001T120000
```

The recipes above are examples of the shape; generate the real ones. Rules for
the generated file:

- **One recipe per backed-up path**, named `restore-<short-name>-<session>`,
  with a comment line describing the path and why it was backed up. The
  comment is what `just --list` shows.
- `default` must be the **first** recipe, so plain `just` lists everything
  that can be restored.
- Every restore first saves the *current* file as `*.pre-restore.<timestamp>`,
  so a restore can itself be undone. "absent" entries remove the created path
  (unloading LaunchAgents first). Directory restores replace the directory
  wholesale, after moving the current one aside.
- Include `restore-all-<session>`, which restores in reverse order of capture.
- For things with their own uninstaller (Graft: `graft uninstall`; plugins:
  `/plugin uninstall`), the recipe comment names it, but the recipe still
  restores the backed-up file, because the uninstaller may not exist later.
- Verify with `just --justfile "$BACKUP_ROOT/justfile" --fmt --check` and
  `just --justfile "$BACKUP_ROOT/justfile" --list`. Then dry-run at least one
  restore against a temporary copy to prove it works, and record that in the
  final report.

### 15.4 Tell the user

At the end of the autonomous phase and in the final report, print:

```bash
just --justfile ~/.local/state/perp-tooling-backups/justfile          # list restorable items
just --justfile ~/.local/state/perp-tooling-backups/justfile restore-<name>-<session>
```

Do not delete the backups. Explain that the user can remove them once they
are satisfied.

---

## 16. Final report

Include:

- the orchestration used: Claude Code version, subagents created, which phases
  ran in parallel, and any deviation from §0 (e.g. different frontmatter
  fields);
- a rough token-use note per phase (`/cost`, `session-report`), and where
  cheaper routing was used;
- every tool installed, with its version, website and install method;
- "same spirit" tools added under §2, with rationale;
- tools declined and why;
- the skills and plugins installed, kept, dropped and offered (§0.6), and
  where they are recorded;
- the baseline commands and results, before and after the backport;
- files created or changed;
- `AGENTS.md`, the `CLAUDE.md` import, the skill path and the subagent files;
- the README changes and the chosen license;
- CI status and link;
- CodeRabbit verification;
- forks created (`Kuriboh493/<repo>` ← upstream), branches, generalized values,
  tests, and any upstream suggestion drafted or opened;
- feeder status: queue size, first PR link, schedule and notification choice;
- backup store path, manifest summary, the restore `justfile` recipe list, and
  the result of the restore dry-run;
- outstanding findings;
- the location of `HANDOFF.md`;
- `git status --short`.

Never report an external service as working until it has been verified with a
real authenticated interaction.
