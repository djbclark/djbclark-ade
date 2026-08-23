# AGENTS.md — djbclark-ade

You are an AI agent working on djbclark's machine. This repo is the
operating guide for running AI agents as **graphs** here — read this file,
then follow the pointers. Everything in it applies to any agent (Claude
Code, Codex, OpenCode, Crush, Cline, Copilot, Grok, Cursor, …), not just
the one that wrote it.

## What this repo is

A reference architecture plus live operating knowledge for two altitudes
of agent-graph work, verified by real runs on 2026-08-23:

- **Micro graph** — Claude Code dynamic workflows: in-process subagent
  fan-out coordinated by plain JavaScript, zero-token orchestration.
- **Macro graph** — Orca orchestration: a task DAG across separate agent
  CLI processes in their own git worktrees, CLI-agnostic lifecycle
  (`worker_done`, ask/reply, escalation).

Start with [README.md](README.md) for the architecture and how the
altitudes compose (a macro node can run a micro graph as its body).

## Read before acting

- [docs/model-routing.md](docs/model-routing.md) — **which AI/service to
  use for what work**: every service on this machine mapped to its
  TUI/CLI, monthly-subscription vs prepaid vs free, chronic-waste pools
  worth burning, per-service effort levers. Numbers are dated snapshots —
  always re-probe (`aiuse --json`, ~1 min, JSON starts after two preamble
  lines; `cswap list` for Claude windows).
- [docs/orca-integration.md](docs/orca-integration.md) — runnable macro-
  graph command sequences plus hard-won live-run lessons (stall false
  deaths, rejected-late `worker_done` semantics, the retry recipe, the
  ack loop). The authoritative command reference is served by the binary:
  `orca skills get orchestration` — never trust a cached copy.
- [.claude/workflows/graph-audit.js](.claude/workflows/graph-audit.js) —
  runnable micro-graph example (schema-validated fan-out → adversarial
  verify → synthesize). Claude Code sessions in this repo can invoke it
  as `/graph-audit`. It has audited this repo itself, twice; its
  confirmed findings are fixed.
- [skills/model-routing/SKILL.md](skills/model-routing/SKILL.md) —
  canonical source of the machine-wide model-routing skill (Claude Code's
  live copy is deployed at `~/.claude/skills/model-routing/`).
- [vendor/README.md](vendor/README.md) — sidecar index of everything this
  repo references that lives elsewhere on the system: vendored copies
  (prepaid gate scripts, a dated Orca orchestration guide snapshot) and
  pointers to things with their own homes (aiuse, cswap, the Orca fork,
  hooks, the LiteLLM proxy).

## Standing orders (operator-issued; they bind every agent here)

1. **Continuous operation — never stop work because context is large.**
   Externalize heavy work (subagents, background workflows, Orca
   workers), keep state on disk continuously, and let the harness's
   compaction bridge context windows. A handoff document is an artifact
   you write *without stopping*, reserved for work where the conversation
   itself is the state.
2. **Commit AND push at opportune moments.** After each coherent unit of
   work. On a sweep, also catch artifacts living outside any repo that
   should be tracked. Never push secrets or ignored local state.
3. **Flag best-practice deviations.** If a request or existing config
   conflicts with current best practices, say so and propose the
   improvement — but don't relitigate decisions the operator made
   knowingly.
4. **Routing discipline**: free and chronically-unused pools first for
   bulk work; claude/codex for judgment (tier inside them); **never**
   bulk-route to clinepass (infrastructure lifeline); the prepaid tier is
   retired until an explicit operator top-up.

## Machine context you should know

- **Orca is the fleet registry**: ~25 TUI agents preconfigured (see
  docs/model-routing.md, "Orca is the fleet registry"); macro-graph
  dispatch reaches any enabled one via
  `orca orchestration worker-start --agent <name>`.
- The broader ops-suite conventions (worktree/PR/release flow, memory
  rules) live in `~/CLAUDE.md` and the site-private repo — they govern
  `~/ops` and are not duplicated here. This repo itself is an ordinary
  repo: commit to master, push to `djbclark/djbclark-ade`.
- Facts in this repo carry snapshot dates. Probes beat memory; when you
  verify something has changed, update the doc in the same breath
  (standing order 2).
