# Skills: what each one is and how to use it

Every hand-written skill that is safe to publish lives in [`skills/`](../skills/).
Each directory holds a `SKILL.md` (the instructions an agent loads) plus any
scripts or reference files beside it. Skills are reached through one chain, so
editing here reaches every agent TUI:

```
~/.claude/skills/<name>  ->  ~/ops/site-private/skills/<name>
                         ->  ~/ops/site-djbclark/skills/<name>   (symlink)
                         ->  ~/src/djbclark-ade/skills/<name>    (the real files)
```

The old `~/ops/site-djbclark/skills/<name>` paths still work; they are symlinks
into this repo. Do not edit through them in a way that replaces the symlink.

**How to use a skill.** In Claude Code type `/<name>` (with arguments after it),
or say one of the trigger phrases below and the agent loads it. Other TUIs find
the same skills through their own skills dir (`skill-everywhere`, README beside it).

**Not here, on purpose.** `1password` and `tell-chief-of-staff` are private by
decision and stay real directories in `~/ops/site-private/skills/` (this repo is
public). Tool-managed skills (bailian-*, composio-cli, herdr, orca-*,
sudo-secretspec, ralph-tui-create-*, ...) stay where their installer put them.

## Sessions and handoffs

| Skill | What it does | How to use |
|---|---|---|
| `autorename` | Titles the current Claude Code, zcode, or Grok session like `/rename`, then offers to move its tab out of a generic herdr workspace. A once-per-session nudge asks for that title (Claude Code and zcode on UserPromptSubmit, Grok on Stop in `~/.grok/hooks/autorename.json`). Also owns the full herdr layout pass (`workspace-layout.md`). | `/autorename`; `/autorename all` runs the full herdr reorg (workspaces, tabs, panes: create, rename, move); "name this session". Special workspaces and their top-of-herdr order come from `~/.config/autorename/workspaces.conf`. Runs by itself as the last step of `/handoff`. |
| `handoff` | Deep Tier 2 handoff document, chain-tagged and mined from the whole conversation. | `/handoff`; "do a handoff"; before ending a long session. |
| `session-handoff` | Reads and writes the Tier 1 pointer (`SESSION_LOG.md`) for any git repo. | Runs at session start and end; "update session log". |
| `baton` | Resumes a workspace from its Tier 1 pointer. | `/baton` or `/resume` at the start of a session. |
| `loose` | Audits the session for loose ends, steps through them, then offers `/handoff` or quit. | `/loose`; "any loose ends?". |
| `steps` | Walks open items one multiple-choice prompt at a time, recommendation first. | `/steps` (optionally item numbers or a topic); "walk me through it". |
| `session-finder` | Finds which session is or ever was on a topic, where it lives, and how to continue it. | `/session-finder`, `/session-finder-all` (adds ended sessions); "tell the agent doing X ...". |
| `helm` | Answers every waiting session of every TUI from one window. | `/helm`, `/helm-all`, `/helm auto`; "what needs me". |
| `herdr-tidy` | Closes idle herdr panes safely and writes a ledger with the resume command. | `/herdr-tidy`, `/orca-tidy`; "which panes can I close". |

## Orchestration and routing

| Skill | What it does | How to use |
|---|---|---|
| `bigteam` | Fans a prompt out across the agent TUIs with free quota: probes pools, slices the work, dispatches, integrates. | `/bigteam <prompt>`; "parallelize this". |
| `model-routing` | Picks vendor x model x effort for a kind of work and reads `aiuse` pools. | Load before big multi-agent runs or when a quota window is tight. |
| `effort-routing` | Matches this session's own reasoning effort to the stretch of work. | Load when starting rote edits or dispatching subagents. |
| `cow-workspaces` | Isolated workspaces as APFS copy-on-write pastures (`bin/cow-pasture`). | "give this agent its own workspace"; parallel work on a checkout under `~/src`. |
| `ralph-tui-orchestration` | Operates the Ralph TUI + Beads multi-repo controller (dormant since 2026-08-23). | Only when seeding or checking a Ralph controller. |
| `terminus-kira` | Delegates a coding or shell task to a sandboxed agent in an Apple Container VM with one host directory mounted. | Risky or long tasks you want contained and reviewable. |

## Knowledge and search

| Skill | What it does | How to use |
|---|---|---|
| `research` | Evidence-grounded research: every claim logged with a verbatim quote, a counter-evidence pass, then a script checks quotes and citations. | "deep research on X"; "what does the evidence say". Script: `skills/research/scripts/research_check.py`. |
| `report` | Formats a long Markdown deliverable for Marked 2: numbered superscript citations, linked evidence table, descriptive file names, short paragraphs, render check by window capture. | `/report`; before the first `open -a "Marked 2"` of a research report, spec or review. Scripts: `skills/report/scripts/{reformat_citations,cite_sup}.py`. |
| `book-to-kb` | Adds a book (EPUB, PDF, DOCX, ...) to the local knowledge base at `~/kb` so any session can query it cheaply. | Give it a book path; query later with `book-kb query '<regex>' <slug>`. |
| `gmail-search` | Searches the local full-text index of the whole mailbox in about 100 ms; read-only. | "search my email", "find that message from X". |
| `graft` | Tells an agent to use the graft code graph before grepping or reading source. | Loads on its own in any graft-indexed repo. |
| `todo` | Tracks optional do-whenever tasks as Basic Memory notes. | "what could I work on"; "add to my todo". |

## Other tooling

| Skill | What it does | How to use |
|---|---|---|
| `coderabbit-feeder` | Queues a CodeRabbit review request (attach mode for your repos, crossfork mode for others). | "queue a coderabbit review". |
| `reorg-orca` | Reorganizes a cluttered Orca setup from the CLI and says which moves Orca cannot do yet. | "tidy my Orca workspaces". For herdr use `autorename`. |

## Adding or moving a skill

1. Put the directory in `skills/<name>/` here with a `SKILL.md` (front matter `name` and `description`).
2. Link it into the hub and every TUI:

   ```sh
   ln -s /Users/djbclark/src/djbclark-ade/skills/<name> ~/ops/site-djbclark/skills/<name>
   ln -s ../../site-djbclark/skills/<name> ~/ops/site-private/skills/<name>
   ~/ops/site-private/bin/skill-everywhere <name>
   ~/ops/site-private/bin/skill-everywhere --check <name>
   ```

3. Add a row above and in the README table. Nothing private goes in a skill here.
