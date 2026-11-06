# Skills: what each one is and how to use it

Every hand-written skill that is safe to publish lives in [`skills/`](../skills/).
Each directory holds a `SKILL.md` (the instructions an agent loads) plus any
scripts or reference files beside it. Every TUI links the skill **directly**
at this repo — one symlink, no chain — so editing here reaches every agent
TUI:

```
~/.claude/skills/<name>  ->  ~/src/djbclark-ade/skills/<name>    (the real files)
```

No skill dir here is a symlink since 2026-11-06 (slim-down E1): `forgejo`, `forgejo-ci`,
`hyades-docker`, `sipb-llm-bench`, `sudo-secretspec` and `jevlike` stay in their own repos
(sipb-agent-skills, loopback-port-shim, sipb-llms, sudo-secretspec) and are linked into the
agents by hand from there, not by `skill-everywhere` (whose roots are this repo,
`~/ops/site-private/skills` and `~/ops/site-public-djbclark/skills`).
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
Tool-managed skills (bailian-*, composio-cli,
sudo-secretspec, ralph-tui-create-*, ...) stay where their installer put them.
(The Orca-installed skills `orca-cli`, `orca-per-workspace-env`, `herdr`, `orchestration` and the
`computer-use` stub were removed from the machine on 2026-10-31; Orca and herdr are retired from djbclark-ade but stay installed and configured on the machine, untouched.)

**Since when, and the rule.** This repo has been the canonical git copy of the
orchestration and session-hygiene skills since 2026-10-08 (`autorename` joined
that day) and of every hand-written skill since 2026-10-09.
**A new skill always goes here** (operator standing rule, 2026-10-09). **Edit a
skill here, never through a TUI path.** `/helm-all`, `/session-finder-all`,
`/resume` and `/paseo-screen` are thin Claude command wrappers in
[`claude/commands/`](../claude/commands/). The `herdr-tidy` and `reorg-orca`
skills (and their `/herdr-tidy`, `/orca-tidy` wrappers) were retired from
djbclark-ade on 2026-10-31; the tools stay installed on the machine.

## Sessions and handoffs

| Skill | What it does | How to use |
|---|---|---|
| `autorename` | Titles the current Claude Code, zcode, Grok, cursor-agent, OpenCode, Codex (in a herdr pane), omp or Pi session like `/rename` and names its own tab (the Paseo tab, or the herdr tab label); with no argument it never renames a workspace or moves a tab (2026-10-30). `/autorename all` is retired (2026-10-31) and refused in every host; `herdr_place.py` stays until the D4/D6 drain. omp needs the `omp-bridge.ts` extension symlinked into `~/.omp/agent/extensions/` and an omp restart. A once-per-session nudge asks for that title (Claude Code and zcode on UserPromptSubmit, Grok on Stop in `~/.grok/hooks/autorename.json`, cursor-agent via the `~/.claude/settings.json` hook it also loads, as `beforeSubmitPrompt`; Grok discards UserPromptSubmit context, hence Stop). `workspace-layout.md` is the record of the retired herdr layout pass. | `/autorename`; `/autorename all` is retired (2026-10-31) and refused in every host; it used to run the full herdr reorg (create and rename workspaces, move tabs; rename a tab only when its label is a single digit); "name this session". Special workspaces and their top-of-herdr order come from `~/.config/autorename/workspaces.conf`. Runs by itself as the last step of `/handoff`. |
| `handoff` | Deep Tier 2 handoff document, chain-tagged and mined from the whole conversation; its last step (9) clears this session with `self-slash "/new"`, which queues one `/baton` into the fresh session, or, on Paseo when the session runs on Fable, the quota guard says tight/critical or the operator asks for another model, runs `self-slash --finish --successor claude/claude-opus-5-5 --thinking high` (Sonnet 5.5 when the guard says tight; plain `/new` when the session already runs on the target model), a new agent that starts with `/baton` (2026-10-23) (skipped for a doc-only handoff, and never run by a sub-agent or dispatched slice, 2026-10-20). On Paseo the pre-`/clear` transcript is not kept by `paseo logs` once `/baton` runs (2026-10-20; UI unverified), so what the operator must read goes into the handoff document, the Tier 1 pointer and the hermes-ping. | `/handoff`; "do a handoff"; before ending a long session. |
| `session-handoff` | Reads and writes the Tier 1 pointer (`SESSION_LOG.md`) for any git repo. | Runs at session start and end; "update session log". |
| `baton` | Resumes a workspace from its Tier 1 pointer. | `/baton` or `/resume` at the start of a session. |
| `loose` | Audits the session for loose ends, steps through them, then offers handoff and continue, finish and archive (`self-slash --finish`), or keep working. On Grok Bot the Mac-only steps have equivalents or skips (section "On Grok Bot", 2026-10-23). | `/loose`; "any loose ends?". |
| `cfenginewatch` | Registers this session as the one CFEngine upstream-PR watcher with `fleet-watch upstream --relay-to` (replacing and telling any previous one), tests the channel, and works each relayed event through `/bigteam`, prepare-and-stop. | `/cfenginewatch`; "watch the cfengine PRs", "you take the upstream events". |
| `paseowatch` | Registers this session as the one Paseo-contribution watcher with `fleet-watch upstream --profile paseo --relay-to` (replacing and telling any previous one), tests the channel, and works each relayed event (PR, issue or Discussion reply) through `/bigteam`, prepare-and-stop; with no watcher it is a Hermes ping only. | `/paseowatch`; "watch the Paseo threads", "you take the Paseo events". |
| `watch` | Runs `bin/watch status`, `up --dry-run` and `up`: for each watcher domain in `config/watch.toml` it keeps one live, registered watcher agent in the one shared Paseo workspace `watch` (created once, reused), titled `watch <domain> <n>` with `n` an incrementing base-36 number (`0-9a-z`) per domain, and once the new one is registered it renames each superseded one to `x watch <domain> <n>`, starts only missing or unreachable ones through `paseo-new-seat` (a claude watcher in `bypassPermissions`, a codex one in `full-access`; `--no-auto-accept` or `--mode default|plan` opts out and labels it `perm=ask`), picks provider, model, effort and context from `route_agent.py plan` and recent event load, and verifies registration with the domain's own status and channel test. Idempotent; `down DOMAIN` drops a role it started. `/watch lead` is an alias for helm's lead mode. | `/watch`, `/watch lead`; "start the watchers", "bring up the watchers", "make sure the watchers are running". |
| `peer-relay` | Teaches Hermes to message a peer session with `relay.py` by absolute path, read its exit codes (a `queued: <id>` line is exit 0: delivered when the peer is idle) and never resend an unverified message. Drafted here 2026-10-23; Hermes installs it itself. | A peer must be told, asked or answered; "tell the agent doing X". |
| `steps` | Walks open items one multiple-choice prompt at a time, recommendation first. On Grok Bot the prompt is a `SendToUser` question widget (section 2d, 2026-10-23). Plan mode (section 6, 2026-11-04, explicit only): interviews the operator on 3-5 real design forks before a plan is written. | `/steps` (optionally item numbers or a topic); `/steps plan [topic\|file]`; "walk me through it". |
| `retro` | Periodic self-review (2026-11-04): runs `bin/ade-retro --since DATE` (merged PRs, changelog entries, handoffs in the window) and writes a short retrospective: what shipped, what recurred, what to queue, instruction-file rules worth adding. Read-only. | `/retro`, "retro since 2026-10-28". |
| `session-finder` | Finds which session is or ever was on a topic, where it lives, and how to continue it. | `/session-finder`, `/session-finder-all` (adds ended sessions); "tell the agent doing X ...". |
| `helm` | Answers every waiting session of every TUI from one window. Lead mode (`/helm lead`, alias `/watch lead`) contacts every running agent, unblocks what rules and probes settle, and takes their picklist questions through `relay.py` instead of cards. | `/helm`, `/helm-all`, `/helm auto`, `/helm lead`; "what needs me", "unblock every agent". |

## Orchestration and routing

| Skill | What it does | How to use |
|---|---|---|
| `bigteam` | Fans a prompt out across the agent TUIs with free quota: probes pools, slices the work, dispatches, integrates. | `/bigteam <prompt>`; "parallelize this". |
| `model-routing` | Picks vendor x model x effort for a kind of work and reads `aiuse` pools. | Load before big multi-agent runs or when a quota window is tight. |
| `fallback-chains` | Dated inventory of every failure chain (Hermes, cron, LiteLLM, acp-run) plus the not-started single-system backlog, and the web search/fetch failover ladder (`web-get`) with its pause rule. | Load when asked about fallback chains; re-read live config and update the snapshot if it drifted. |
| `effort-routing` | Matches this session's own reasoning effort to the stretch of work. | Load when starting rote edits or dispatching subagents. |
| `dialogue` | Runs a multi-model dialogue (for example Grok, Fable, Astra) that produces one artifact with a final-word model: fixed rounds through pinned routes, footers with point ids and dissent, a final-word state-file gate, noise strip and protocol lint. | "have the models chat about it and write X"; "three-model dialogue". Script: `skills/dialogue/scripts/dialogue.py`. |
| `skillopt-sleep` | Reviews and steers the nightly SkillOpt-Sleep cycle (`bin/skillopt-night`, launchd 03:30) that mines every agent's sessions and stages gated skill edits: last night's report, free mock dry-run, per-skill adoption, the backend failover chain. | `/skillopt-sleep`; "what did the agents learn last night", "adopt the proposal". Guide: `docs/skillopt-sleep.md`. |

Moved to site-djbclark (`~/ops/site-public-djbclark/skills`, the third `skill-everywhere` root) on 2026-11-06: `gmail-search`, `ovhcloud-api`, `aws-rules`, `terminus-kira`, `diskfree`, `bottom-config`, `setup-modern-cli`, `teach`, `todo`, `report`, `greptile`, `coderabbit-feeder`, `firecrawl`, `barnowl`; `book-to-kb` is `tools/book-to-kb` there. Deleted: `siyuan*`, `cow-workspaces`, `ralph-tui-orchestration`, `skillopt-sleep-learned`.

## Knowledge and search

| Skill | What it does | How to use |
|---|---|---|
| `research` | Evidence-grounded research: every claim logged with a verbatim quote, a counter-evidence pass, then a script checks quotes and citations. | "deep research on X"; "what does the evidence say". Script: `skills/research/scripts/research_check.py`. |
| `skills-everywhere` | Links a canonical shared skill into every installed agent TUI and checks the resulting links. | `/skills-everywhere <name>` or `/skills-everywhere --check <name>`; script: `~/src/djbclark-ade/bin/skill-everywhere`. |
| `tell-chief-of-staff` | Sends a message to the operator's cloud Grok Bot "Chief of Staff" via its inbound webhook, and explains how Chief of Staff can call back into Claude (ask_claude MCP tool). Webhook URL/key live in Keychain. | "tell grok", "tell Chief of Staff", "hand this to grokbot". |
| `tell-coding-bot` | Any project talks to the operator's cloud Grok Bot "Coding" through `bin/coding-bot` (link: `ln -s ~/src/djbclark-ade/bin/coding-bot ~/.local/bin/coding-bot`). `ask "task"` POSTs to the bot's webhook routine (`CODING_BOT_WEBHOOK_URL`/`_KEY` in sudo-secretspec; ids `ade-N` and `re=` as in techno-euphora's Dann -> Eve channel) and blocks for the reply (exit 4 BLOCKED, 124 timeout); `send`, `wait`, `deliver` (files a reply from stdin or the clipboard: the one return sink), `inbox`, `status`. With no webhook yet, or for `prompt`, the task goes on the clipboard as a self-contained prompt for the operator to paste (exit 10): the route for web pages that need UI interaction. `bootstrap` asks the bot to create its webhook routine. Credential-shaped text is refused; the key goes only to `api2.cursor.sh`; replies are untrusted data. | "tell the Coding bot", "ask Coding", "hand this to the Coding bot", a task needing real browser UI interaction. |
| `graft` | Tells an agent to use the graft code graph before grepping or reading source. | Loads on its own in any graft-indexed repo. |
| `create-hook` | Writes, merges and removes native OpenAI Codex hooks (`~/.codex/hooks.json`, `<repo>/.codex/hooks.json`; PascalCase events, trust review, deny/allow JSON, timeouts), snapshot of Codex 0.164.0 (2026-10-25) with the official docs to re-check. Codex only: Cursor hooks use other paths and names. | "add a Codex hook", "write hooks.json for Codex", "block a command in Codex". |

## Other tooling

| Skill | What it does | How to use |
|---|---|---|
| `ade-paseo`, `ade-paseo-advisor`, `ade-paseo-committee`, `ade-paseo-handoff`, `ade-paseo-help`, `ade-paseo-plugin` | Paseo (github.com/getpaseo/paseo), vendored from upstream `skills/` (Apache-2.0; `skills/ade-paseo/UPSTREAM.md`) under an `ade-` prefix, so Paseo's own skill sync never overwrites them: operate the Paseo daemon (projects, workspaces, agents, schedules) through its CLI, a Paseo advisor or two-agent committee, a hand-off to a Paseo agent, product help, plugin authoring. Advisor/committee/handoff fire only on explicit Paseo requests (local patch). Daemons on port 7263 on the Mac, vps-primary and get (site-djbclark `docs/paseo.md`). | "/ade-paseo-handoff", "run this in Paseo", "Paseo plugin", "why is Paseo not connecting". |
| `paseo-screen` | The one screen-control tool (2026-10-31): looks at and drives the host Mac's GUI through the Paseo plugin `paseo-screen` (`paseo plugin add kevguy/screen`; viewer "Screen · mac"; RPCs `screen.status`, `screen.frame`, `screen.input`). Replaces the retired Orca `orca computer` / `computer-use` route. Verified 2026-10-30: live desktop at about 10 fps, a keyboard chord delivered; not verified: clicks, drags, clipboard, multiple displays. Safety rules inside (look before clicking, never mid-typing, exposure to paired clients, the off switch `paseo plugin disable paseo-screen`). Stays enabled when idle (operator). | `/paseo-screen`; "drive the desktop app", "take a screenshot of the screen", "verify it in the app window". |

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
