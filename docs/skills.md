# Skills: what each one is and how to use it

Every hand-written skill that is safe to publish lives in [`skills/`](../skills/).
Each directory holds a `SKILL.md` (the instructions an agent loads) plus any
scripts or reference files beside it. Every TUI links the skill **directly**
at this repo — one symlink, no chain — so editing here reaches every agent
TUI:

```
~/.claude/skills/<name>  ->  ~/src/djbclark-ade/skills/<name>    (the real files)
```

Five skill dirs here are themselves symlinks into other repos: `forgejo-ci`
(`~/src/loopback-port-shim`), `sudo-secretspec` (`~/src/sudo-secretspec`),
`forgejo` and `hyades-docker` (`~/src/sipb-agent-skills`), and `sipb-llm-bench`
(`~/src/sipb-llms`).
**Commit an edit to a skill in the repo of its `realpath`**: `git add` here fails
with "pathspec is beyond a symbolic link" (2026-10-16), and the other repo may
hold another session's uncommitted edits, so stage only your hunk there.

(The hub chain through `~/ops/site-private/skills` → `~/ops/site-djbclark/skills`
was collapsed to these direct links on 2026-10-14; those paths no longer work.)

**How to use a skill.** In Claude Code type `/<name>` (with arguments after it),
or say one of the trigger phrases below and the agent loads it. Other TUIs find
the same skills through their own skills dir (`skill-everywhere`, README beside it).

**Not here, on purpose.** `1password` is private by decision and stays a real
directory in `~/ops/site-private/skills/` (this repo is public).
`tell-chief-of-staff` moved here on 2026-10-14 (operator ruling: public).
Tool-managed skills (bailian-*, composio-cli, herdr, orca-*,
sudo-secretspec, ralph-tui-create-*, ...) stay where their installer put them.

**Since when, and the rule.** This repo has been the canonical git copy of the
orchestration and session-hygiene skills since 2026-10-08 (`herdr-tidy` and
`autorename` joined that day) and of every hand-written skill since 2026-10-09.
**A new skill always goes here** (operator standing rule, 2026-10-09). **Edit a
skill here, never through a TUI path.** `/helm-all`, `/session-finder-all`,
`/resume`, `/herdr-tidy` and `/orca-tidy` are thin Claude command wrappers in
[`claude/commands/`](../claude/commands/).

## Sessions and handoffs

| Skill | What it does | How to use |
|---|---|---|
| `autorename` | Titles the current Claude Code, zcode, Grok, cursor-agent, OpenCode, Codex (in a herdr pane) or omp session like `/rename`, then offers to move its tab out of a generic herdr workspace. omp needs the `omp-bridge.ts` extension symlinked into `~/.omp/agent/extensions/` and an omp restart. A once-per-session nudge asks for that title (Claude Code and zcode on UserPromptSubmit, Grok on Stop in `~/.grok/hooks/autorename.json`, cursor-agent via the `~/.claude/settings.json` hook it also loads, as `beforeSubmitPrompt`; Grok discards UserPromptSubmit context, hence Stop). Also owns the full herdr layout pass (`workspace-layout.md`). | `/autorename`; `/autorename all` runs the full herdr reorg (workspaces, tabs, panes: create, rename, move); "name this session". Special workspaces and their top-of-herdr order come from `~/.config/autorename/workspaces.conf`. Runs by itself as the last step of `/handoff`. |
| `handoff` | Deep Tier 2 handoff document, chain-tagged and mined from the whole conversation; its last step (9) clears this session with `self-slash "/new"`, which queues one `/baton` into the fresh session, or, on Paseo when the session runs on Fable, the quota guard says tight/critical or the operator asks for another model, runs `self-slash --finish --successor claude/claude-opus-5-5 --thinking high` (Sonnet 5.5 when the guard says tight; plain `/new` when the session already runs on the target model), a new agent that starts with `/baton` (2026-10-23) (skipped for a doc-only handoff, and never run by a sub-agent or dispatched slice, 2026-10-20). On Paseo the pre-`/clear` transcript is not kept by `paseo logs` once `/baton` runs (2026-10-20; UI unverified), so what the operator must read goes into the handoff document, the Tier 1 pointer and the hermes-ping. | `/handoff`; "do a handoff"; before ending a long session. |
| `session-handoff` | Reads and writes the Tier 1 pointer (`SESSION_LOG.md`) for any git repo. | Runs at session start and end; "update session log". |
| `baton` | Resumes a workspace from its Tier 1 pointer. | `/baton` or `/resume` at the start of a session. |
| `loose` | Audits the session for loose ends, steps through them, then offers handoff and continue, finish and archive (`self-slash --finish`), or keep working. | `/loose`; "any loose ends?". |
| `loadwatch` | Registers this session as the one load watcher with the launchd `load-watch` job (replacing and telling any previous one), tests the channel, and investigates when the load is abnormal. | `/loadwatch`; "watch the load", "why is the machine hot". |
| `steps` | Walks open items one multiple-choice prompt at a time, recommendation first. | `/steps` (optionally item numbers or a topic); "walk me through it". |
| `teach` | Walks today's one or two install-or-use items (mods, skills, built-ins, installed plugins) from the rollout checklist, one prompt at a time, and ticks them off. | `/teach`, `/teach 5`, `/teach list`; the 04:14 Hermes ping. |
| `session-finder` | Finds which session is or ever was on a topic, where it lives, and how to continue it. | `/session-finder`, `/session-finder-all` (adds ended sessions); "tell the agent doing X ...". |
| `helm` | Answers every waiting session of every TUI from one window. | `/helm`, `/helm-all`, `/helm auto`; "what needs me". |
| `herdr-tidy` | Closes idle herdr panes safely and writes a ledger with the resume command. | `/herdr-tidy`, `/orca-tidy`; "which panes can I close". |

## Orchestration and routing

| Skill | What it does | How to use |
|---|---|---|
| `bigteam` | Fans a prompt out across the agent TUIs with free quota: probes pools, slices the work, dispatches, integrates. | `/bigteam <prompt>`; "parallelize this". |
| `model-routing` | Picks vendor x model x effort for a kind of work and reads `aiuse` pools. | Load before big multi-agent runs or when a quota window is tight. |
| `fallback-chains` | Dated inventory of every failure chain (Hermes, cron, LiteLLM, herdr-ai, acp-run) plus the not-started single-system backlog, and the web search/fetch failover ladder (`web-get`) with its pause rule. | Load when asked about fallback chains; re-read live config and update the snapshot if it drifted. |
| `effort-routing` | Matches this session's own reasoning effort to the stretch of work. | Load when starting rote edits or dispatching subagents. |
| `cow-workspaces` | Isolated workspaces as APFS copy-on-write pastures (`bin/cow-pasture`). | "give this agent its own workspace"; parallel work on a checkout under `~/src`. |
| `dialogue` | Runs a multi-model dialogue (for example Grok, Fable, Astra) that produces one artifact with a final-word model: fixed rounds through pinned routes, footers with point ids and dissent, a final-word state-file gate, noise strip and protocol lint. | "have the models chat about it and write X"; "three-model dialogue". Script: `skills/dialogue/scripts/dialogue.py`. |
| `ralph-tui-orchestration` | Operates the Ralph TUI + Beads multi-repo controller (dormant since 2026-08-23). | Only when seeding or checking a Ralph controller. |
| `terminus-kira` | Delegates a coding or shell task to a sandboxed agent in an Apple Container VM with one host directory mounted. | Risky or long tasks you want contained and reviewable. |
| `skillopt-sleep` | Reviews and steers the nightly SkillOpt-Sleep cycle (`bin/skillopt-night`, launchd 03:30) that mines every agent's sessions and stages gated skill edits: last night's report, free mock dry-run, per-skill adoption, the backend failover chain. | `/skillopt-sleep`; "what did the agents learn last night", "adopt the proposal". Guide: `docs/skillopt-sleep.md`. |
| `skillopt-sleep-learned` | The catch-all target SkillOpt-Sleep proposes edits to: lessons that belong to no single skill. Changes only by adoption. | Background rules for any task; edit only through `skillopt-sleep adopt` and a commit. |

## Knowledge and search

| Skill | What it does | How to use |
|---|---|---|
| `research` | Evidence-grounded research: every claim logged with a verbatim quote, a counter-evidence pass, then a script checks quotes and citations. | "deep research on X"; "what does the evidence say". Script: `skills/research/scripts/research_check.py`. |
| `skills-everywhere` | Links a canonical shared skill into every installed agent TUI and checks the resulting links. | `/skills-everywhere <name>` or `/skills-everywhere --check <name>`; script: `~/src/djbclark-ade/bin/skill-everywhere`. |
| `report` | Formats a long Markdown deliverable for Marked 2: numbered superscript citations, linked evidence table, descriptive file names, short paragraphs, render check by window capture. | `/report`; before the first `open -a "Marked 2"` of a research report, spec or review. Scripts: `skills/report/scripts/{reformat_citations,cite_sup}.py`. |
| `book-to-kb` | Adds a book (EPUB, PDF, DOCX, ...) to the local knowledge base at `~/kb` so any session can query it cheaply. | Give it a book path; query later with `book-kb query '<regex>' <slug>`. |
| `gmail-search` | Searches the local full-text index of the whole mailbox in about 100 ms; read-only. | "search my email", "find that message from X". |
| `tell-chief-of-staff` | Sends a message to the operator's cloud Grok Bot "Chief of Staff" via its inbound webhook, and explains how Chief of Staff can call back into Claude (ask_claude MCP tool). Webhook URL/key live in Keychain. | "tell grok", "tell Chief of Staff", "hand this to grokbot". |
| `graft` | Tells an agent to use the graft code graph before grepping or reading source. | Loads on its own in any graft-indexed repo. |
| `todo` | Tracks optional do-whenever tasks as Basic Memory notes. | "what could I work on"; "add to my todo". |

## Other tooling

| Skill | What it does | How to use |
|---|---|---|
| `sipb-llm-bench` | (Canonical files live in the public repo forgejo.mit.edu/djbclark/sipb-llms; this dir is a symlink.) Benchmarks a model on MIT SIPB LLMs (or any OpenAI-compatible Open WebUI/Ollama server) as an agentic-coding backend: speed probes, a tool-call conformance check, two tool-using tasks scored by running the tests. Serial and gentle on the shared server. Backs `report/REPORT.md` in sipb-llms. | "test model X on SIPB LLMs"; `bench.py run --models X`, `bench.py summary`. |
| `forgejo` | (Canonical files live in the public repo forgejo.mit.edu/djbclark/sipb-agent-skills; this dir is a symlink.) Uses a Forgejo instance (default `forgejo.mit.edu`) from an agent with the token in `sudo-secretspec`: `scripts/setup-token` stores `DJBCLARK_FORGEJO_MIT_EDU_TOKEN`, `forgejo-api` makes one `/api/v1` call, `tea-forgejo` runs `tea` with the secret on its env login. `fj`, `tea` installed globally (brew). | "use forgejo.mit.edu"; "set up a Forgejo token"; run `skills/forgejo/scripts/setup-token`. CI on forgejo.mit.edu is the `forgejo-ci` skill. |
| `forgejo-ci` | (Canonical files live in the public repo forgejo.mit.edu/djbclark/loopback-port-shim; this dir is a symlink.) Runs CI on SIPB Hyades (forgejo.mit.edu `ubuntu`, libkrun microVMs): runner facts, job-image selection (our own `ghcr.io/djbclark/ci-image-plektra` with JDK 17, Android SDK 36, node and the shim), the loopback `LD_PRELOAD` shim for libkrun TSI bugs (port 0, blocked recv, stale listeners), probe tooling, ticket etiquette and the SIPB/libkrun ticket map. | "my job on forgejo.mit.edu hangs or flakes"; "which image for Gradle/Android there"; "use the shim"; `skills/forgejo-ci/SKILL.md`. |
| `hyades-docker` | (Canonical files live in the public repo forgejo.mit.edu/djbclark/sipb-agent-skills; this dir is a symlink.) Hosts sites and services on SIPB Hyades (hyades.mit.edu; OCI images run as libkrun microVMs at `NAME.sipb.cloud`). `scripts/hyades` runs one SSH console command and restores the exit status the console drops; `hyades-registry` pushes with podman (docker only as fallback) through a throwaway login; `hyades-update-token` and `hyades-ci-secrets` keep the update token and the SIPB/hyades-action secrets in sudo-secretspec. `references/` holds the user guide, README, `console.py` and action snapshots (`hyades-refresh-docs`), the full console help, and `console.md` (each command's real behaviour, limits, the broken `exec` and `tmprun CMD`). | "deploy this to Hyades", "host it on sipb.cloud", "set up hyades-action", `/hyades-docker`. Registry tokens and Actions secrets come from the `forgejo` skill; runner problems are `forgejo-ci`. |
| `coderabbit-feeder` | Queues a CodeRabbit review request (attach mode for your repos, crossfork mode for others). | "queue a coderabbit review". |
| `sudo-secretspec` | (Part of the sudo-secretspec project — canonical files live in `~/src/sudo-secretspec` (github.com/frdminc/sudo-secretspec, also the brew tap); this dir is a symlink, like `forgejo-ci`. The brew-installed copy under `/opt/homebrew` is ignored by the TUIs.) Use the privilege-separated `sudo-secretspec` client for managed credentials — declare, set, rotate, read, delete, or inject a secret into a child process — instead of touching a secret store directly; also covers the deliberately-not-exposed boundary and what must be asked of the operator. | "need an API key/token/password via secretspec"; "rotate that credential"; `sudo-secretspec --help`. |
| `setup-modern-cli` | The replacement tables for the classic Unix tools — `cat`/`ls`/`find`/`grep`/`sed`/`awk`/`sort`/`join`/`cut`/`tr`/`wc`/`du`/`df`/`ps`/`diff`/`curl`/JSON/YAML/archives and the rest — split into **agent-safe** (non-interactive), **structured/stream data** (`mlr` for awk/sed/sort/join) and **human-interactive** (TUIs/fuzzy finders, never called from an agent), plus the BSD-vs-GNU portability answer (`gsort`/`gsed`/`uu-*`), the search ladder, token discipline, and the footguns. Entry file is short; the tables and the measured benchmark numbers are in `skills/setup-modern-cli/references/`. | Load before shell work in a repo, or when setting up a machine/repo toolchain; "modern CLI tools", "faster grep/find". |
| `reorg-orca` | Reorganizes a cluttered Orca setup from the CLI and says which moves Orca cannot do yet. | "tidy my Orca workspaces". For herdr use `autorename`. |
| `paseo`, `paseo-advisor`, `paseo-committee`, `paseo-handoff`, `paseo-help`, `paseo-plugin` | Paseo (github.com/getpaseo/paseo), vendored from upstream `skills/` (Apache-2.0; `skills/paseo/UPSTREAM.md`): operate the Paseo daemon (projects, workspaces, agents, schedules) through its CLI, a Paseo advisor or two-agent committee, a hand-off to a Paseo agent, product help, plugin authoring. Advisor/committee/handoff fire only on explicit Paseo requests (local patch). Daemons on port 7263 on the Mac, vps-primary and get (site-djbclark `docs/paseo.md`). | "/paseo-handoff", "run this in Paseo", "Paseo plugin", "why is Paseo not connecting". |
| `siyuan`, `siyuan-article-import`, `siyuan-excalidraw`, `siyuan-markdown` | SiYuan notes, vendored from `zhiluop/siyuan-skills` (MIT; see `skills/_shared/UPSTREAM.md`, written in Chinese): core concepts, API, templates and flashcards; web-article import; Excalidraw diagrams saved as SVG assets; SiYuan-flavored Markdown and image insertion. Pair with the SiYuan MCP ([mcp-servers.md](mcp-servers.md)); the scripts read `~/.claude/siyuan.json`. | "import this article into SiYuan", "draw a flowchart in SiYuan", SiYuan block, template or flashcard questions. |

## Disabled skills

Skills, plugins and MCP servers switched off in Claude Code on 2026-10-10 to
shrink every session's context, each with what it does and how to turn it back
on: [disabled-skills.md](disabled-skills.md).

## Adding or moving a skill

1. Put the directory in `skills/<name>/` here with a `SKILL.md` (front matter `name` and `description`).
2. Link it into every TUI:

   ```sh
   ~/src/djbclark-ade/bin/skill-everywhere <name>
   ~/src/djbclark-ade/bin/skill-everywhere --check <name>
   ```

3. Add a row above and in the README table. Nothing private goes in a skill here.
