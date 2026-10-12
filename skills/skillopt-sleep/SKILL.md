---
name: skillopt-sleep
description: >-
  Review and steer the nightly SkillOpt-Sleep cycle that learns from every
  agent's past sessions on this Mac and stages gated skill edits: read last
  night's report, run a free mock dry-run, adopt a staged proposal per skill,
  answer handoff prompts, choose or switch the optimizer backend. Use for
  /skillopt-sleep, "sleep cycle", "what did the agents learn last night",
  "review staged skill proposals", "adopt the proposal".
---

# skillopt-sleep — review what the agents learned overnight

`bin/skillopt-night` (in `~/src/djbclark-ade`) runs nightly at 03:30 from
launchd (`com.djbclark.skillopt-sleep`). Per transcript source with data
(claude, codex, cursor, opencode, copilot_cli, pi) it runs one
`skillopt-sleep run --scope all`, mining every project's sessions into tasks,
replaying them against the current skills, and **staging** gated edits. Nothing
changes a live skill until someone adopts it. Full guide:
`~/src/djbclark-ade/docs/skillopt-sleep.md`.

## 1. What happened last night

```sh
skillopt-sleep status --project ~/src/djbclark-ade        # night, staged skills, latest staging dir
tail -n 8 ~/.local/state/skillopt-sleep/nights.jsonl      # one line per source run: rc, tasks, gate, proposals
```

`status` prints `latest_staging`; read `<that dir>/report.md` first (the
human summary), then `report.json` / `diagnostics.json` for gate scores. A
`waiting-backend` row means the job is installed but inert (backend still
`mock`). Per-source logs: `~/.local/state/skillopt-sleep/<date>-<source>.log`.

## 2. Free preview

```sh
~/src/djbclark-ade/bin/skillopt-night --dry-run            # mock backend, every source, never advances checkpoints
~/src/djbclark-ade/bin/skillopt-night sources              # which transcript stores have data
skillopt-sleep harvest --project ~/src/djbclark-ade --scope all --source claude   # mined tasks, no model calls
```

Never run `skillopt-sleep dry-run` with a real backend to "preview": it spends.

## 3. Adopt a proposal

Review the staged diff in the staging dir, then adopt per skill:

```sh
skillopt-sleep adopt --project ~/src/djbclark-ade --skill <name>      # one staged skill (repeatable)
skillopt-sleep adopt --project ~/src/djbclark-ade --legacy            # the catch-all skill + CLAUDE.md proposal
```

Prefer `--skill` over `--all-skills`. Adoption writes the canonical file under
`~/src/djbclark-ade/skills/<name>/SKILL.md` (TUI paths are symlinks; the
memory proposal targets `CLAUDE.md`, which is a symlink to `AGENTS.md`), and
backs up the prior file under `<staging dir>/backup/`. Then commit it like
any other change in this repo: `git add skills/<name>/SKILL.md`, a message
naming the night, push. Roll back with `git revert` (or copy the backup back).
Never pass `--auto-adopt`.

## 4. The backend decision

`backend` in `~/.skillopt-sleep/config.json` decides which model pool the
nightly optimizer burns. Options (docs/skillopt-sleep.md has the detail):

1. `opencode`: OpenCode Go pool via the `opencode` CLI.
2. `azure_openai`: OpenAI-compatible mode against the local LiteLLM proxy
   (`http://127.0.0.1:4000/v1`), `model` = a LiteLLM model name; the key comes
   from `sudo-secretspec` at run time and goes only into the child env.
3. `handoff`: no model calls from the engine; it writes prompts that an agent
   session answers (section 5).

`optimizer_backend`/`target_backend` split the roles (for example target =
`opencode`, optimizer = `handoff`). Switch by editing the JSON (keep
`docs/skillopt-sleep-config.example.json` in step), then preview with section 2.

## 5. Handoff nights (subscription-only)

With `backend: "handoff"` the night runs one source and exits 3, leaving
`~/src/djbclark-ade/.skillopt-sleep-handoff/PROMPTS.md` and `pending.json`,
and pings Hermes. To answer:

1. Read `PROMPTS.md`; for each pending id spawn a **fresh-context** sub-agent
   (Agent tool, `model: "opus"`) with only that prompt's text, and write its
   raw reply to `answers/<id>.md`. Never answer from this session's own
   context: it would contaminate the held-out gate.
2. Rerun the same command: `~/src/djbclark-ade/bin/skillopt-night --source <s>`.
3. Repeat until it exits 0 (typically 3 to 6 rounds), then section 3.

## 6. Privacy boundary

A real backend receives transcript excerpts (user prompts, final replies,
redacted for obvious secrets) from every project. `evidence.jsonl` in each
staging dir and `~/.skillopt-sleep/evidence/` hold truncated prompts and
replies: treat them as sensitive, never commit or paste them. The repo
ignores `.skillopt-sleep/` and `.skillopt-sleep-handoff/`.
