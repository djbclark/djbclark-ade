---
name: skillopt-sleep
description: >-
  Review and steer the nightly SkillOpt-Sleep cycle that learns from every
  agent's past sessions on this Mac and stages gated skill edits: read last
  night's report, run a free mock dry-run, adopt a staged proposal per skill,
  check or change the backend failover chain. Use for
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

## 4. The backend chain

The engine runs SkillOpt's `handoff` backend; `bin/skillopt-night` answers each
round's prompts through the first working entry of the chain in
`~/.skillopt-sleep/night.json` (library: `bin/failover.py`, docs/failover.md).
Each prompt is a fresh `acp-run` session in an empty dir with `--perm deny`, or
one request to the MIT SIPB endpoint. One entry answers a whole source night; if
it fails, state is restored and the night reruns on the next entry.

```sh
~/src/djbclark-ade/bin/skillopt-night chain-check     # preflight table: pool, floor, ready, why
tail -n 20 ~/.local/state/skillopt-sleep/attempts.jsonl   # what each entry did and why it was skipped
```

Policy (operator, 2026-10-12): allowed TUIs `zcode`, `agy`, `opencode`,
`claude` (Haiku or Sonnet only), and `sipb` last. Never cursor, cline/ClinePass,
Hermes, Opus or Fable; such a chain is refused whole. The chain ships with
`"enabled": false` until the operator approves the per-entry list; enabling it
is `"enabled": true` after a clean `chain-check`. Keep
`docs/skillopt-sleep-night.example.json` in step. Sizing knobs: `max_sessions`
(round 1 sends one prompt per harvested session), `jobs`, `max_rounds`,
`source_timeout_s`.

## 5. A night by hand

`~/src/djbclark-ade/bin/skillopt-night --source pi` runs one small source
through the chain (it spends). Never answer `PROMPTS.md` from this session's
own context: the runner's fresh-context answers keep the held-out gate clean.
If a night was interrupted, its handoff dir
(`~/src/djbclark-ade/.skillopt-sleep-handoff/<source>/`) is wiped at the next
attempt.

## 6. Privacy boundary

A real backend receives transcript excerpts (user prompts, final replies,
redacted for obvious secrets) from every project. `evidence.jsonl` in each
staging dir and `~/.skillopt-sleep/evidence/` hold truncated prompts and
replies: treat them as sensitive, never commit or paste them. The repo
ignores `.skillopt-sleep/` and `.skillopt-sleep-handoff/`.
