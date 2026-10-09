---
schema_version: 1
handoff_id: bf06
parent_handoff_ids: []
lineage: none
chain: [standalone-f2a4]
repo: djbclark-ade
workspace: orca-vs-herdr-with-djbclark-ade-and-acp
branch: djbclark/orca-vs-herdr-with-djbclark-ade-and-acp
head_sha: 96bb454b70fd44378b3d6742e4e2c3dfb49f14d6
master_sha_at_handoff: f689247
created_at: 2026-10-09T00:24:00-04:00
writer: claude-code
---
# Handoff — Orca vs herdr assessment, crush removal, zcode over ACP

## The Goal

1. Decide whether Orca still earns its place now that agents run over ACP
   (`acp-run`) and herdr; write the assessment as a public research doc.
2. Make `bin/route_agent.py` discover agents without depending on Orca's
   roster (operator: "3.2 yes do the right fix").
3. Remove the `crush` TUI (Charm Hyper, free plan; never a ClinePass client)
   from the machine and every live reference, keeping a backup.
4. Give zcode an ACP route so it joins `acp-run`/`acp-dispatch` like the rest.

## Where We Are

All four goals are done and on `origin/master` of djbclark-ade (f689247).
This Orca worktree's branch still points at 96bb454; its two commits were
cherry-picked onto master as ee3b1ce and 8033fe5 because other sessions'
unstaged edits (`.claude/helpers/graft-*.cjs`, `.cursor/*`, `.mcp.json`) made a
rebase here impossible. Those dirty files are **not ours**: leave them.

Operator decisions taken 2026-10-09 via `/steps` (do not re-litigate):

1. Orca: keep using Orca and herdr both; no migration. Study the orchestration
   DAG question first (todo note, see Where We're Going 2).
2. `~/src/crush` fork: keep until upstream PR charmbracelet/crush#3909 merges or
   closes (still OPEN on 2026-10-09).
3. Orca's roster still listing crush: leave it (GUI setting, inert).
4. aiuse's Charm Hyper collector: relay to the aiuse session failed (session had
   ended ~00:02), so it is a todo note with a paste-ready prompt.

Research doc: `~/ops/site-djbclark/research/orca-vs-herdr/README.md`
(site-djbclark 9dc2c32). Memory: `project_crush_removed_2026-10-08.md` in
site-private and the Claude auto-memory note of the same name.

## What We Tried

1. **Rebasing this worktree's branch onto origin/master** — refused: unstaged
   files belong to other sessions and the stash stack is shared. Worked around
   with a detached temp worktree in the scratchpad (cherry-pick, test, push
   `HEAD:master`), since removed. Use the same trick next time; never stash.
2. **Fast-forwarding `~/src/djbclark-ade` right after the push** — aborted:
   another session had unstaged edits to `skills/session-finder/launch.py`
   (which the crush commit also touched). That session later pulled and pushed
   its own work (807d52c, 309d875) with no conflict; the checkout is now in sync.
3. **`acp-run zcode --model <m>`** — impossible: `zcode-acp-server` exposes only
   `mode` (edit|yolo|auto) and `thought` (low|high|max) config options, and
   `pick_config` exits "agent offers no 'model' config option". zcode is the
   one agent run **without** `--model`; documented in `tools/acp-run/README.md`
   and `~/CLAUDE.md`.
4. **First zcode preflight** returned `OK✓ completed · cache 6/7 messages …` plus
   a traceback per turn (`$/zcode/turnState` → `Method not found` in the ACP
   Python library). Fixed in acp-run (72c797d): `$/` folded into the `_`
   extension prefix; chunks with `messageId` `turninfo_*` dropped. Second
   preflight: clean `OK`, exit 0, 8 s.
5. **"Ten Hermes skill files to commit"** (pre-compaction count) — wrong: only
   two still carried crush text at HEAD; committed those (31febde, pushed).
6. **Relaying the aiuse task to its live session** — sub-agent found no live
   session anywhere (cswap, herdr, fleet.py, process cwd); fell back to a todo.

## Key Decisions

1. **Discovery order in route_agent**: `acp-run --list` ok rows → installed
   `NON_ACP_HEADLESS` (now only `muse`) → Orca roster only with
   `ROUTE_AGENT_INCLUDE_ORCA=1`. Rejected: keeping Orca's roster as default
   (12 of 28 names not installed; phantom agents).
2. **zcode via third-party bridge** `william0wang/zcode-acp` (`npm -g
   zcode-acp-server` 0.65.1, wraps `zcode app-server --stdio`) rather than
   waiting for native ACP. Rejected: `zcode -p` headless only (kept as fallback
   row in the model-routing skill).
3. **Patch acp-run, not the ACP library**, for the `$/` prefix (monkeypatch of
   `MessageRouter.__call__`), so the fix ships with the tool.
4. **aiuse `[disabled_services]` keys** are canonical provider ids: `clinepass`
   and `hyper` (a `cline` key would have been inert).
5. **AGENTS.md wording**: `acp-run --list` is the registry; Orca's roster is a GUI
   list (f689247). Rejected: leaving "Orca is the fleet registry".

## Evidence & Data

1. Commits on djbclark-ade master this session: ee3b1ce, 8033fe5, 72c797d,
   8c7fbd3, f689247. Tests: 377 passed (full suite via `bg pytest`, three runs),
   `tests/test_route_agent.py` 30 passed.
2. zcode preflights: `~/.local/state/acp-run/20261009-000130-zcode-5906.jsonl`
   (before fix) and `20261009-000400-zcode-12981.jsonl` (after). ~38k tokens per
   one-word turn (zcode's system prompt); zai 5h window had 24% left.
3. Crush backup: `~/backups/crush-2026-10-08/` (120 MB, README; `hyper.json`
   holds Charm Hyper credentials — keep local).
4. aiuse config: `~/.config/aiuse/config.toml` `[disabled_services]` has `grok`,
   `clinepass`, `hyper`; backup `config.toml.bak-2026-10-09b`.
5. Other repos pushed: site-djbclark 9dc2c32, site-private (memory + 2 todo
   notes), `~/.hermes` 31febde.
6. Upstream draft: `docs/upstream-issues.md` §7 (zcode-acp), 8c7fbd3.

## Operator Feedback

1. crush is the Charm Hyper client; cline is the ClinePass client. Never say
   crush billed ClinePass.
2. herdr being empty was a cleanup, not disuse; herdr is used a lot.
3. Keep both Orca and herdr for now; wants a `/todo` comparing the Orca
   orchestration DAG with ralph-tui, beans and other herdr-compatible options.
4. Back up non-VCS crush state before removal (done).

## Where We're Going

1. **Nothing in flight.** The zcode-acp upstream sub-agent finished at 00:26:
   filed william0wang/zcode-acp#311 (`$/zcode/turnState` prefix) and #312
   (`turninfo_*` stats chunk); `docs/upstream-issues.md` §7 carries the links.
   Watch those issues; when fixed upstream, the two acp-run workarounds
   (72c797d) can go.
2. Todo "Orchestration task DAG: Orca vs ralph-tui vs beans vs herdr-native
   options" (Basic Memory project `main`, `todo/`): non-coding research; result
   goes under `~/ops/site-djbclark/research/orca-vs-herdr/`, then `/steps`.
3. Todo "aiuse: remove the Charm Hyper collector, tests and docs" (same place):
   has a paste-ready prompt; run it when no session is live in `~/src/aiuse`.
4. When charmbracelet/crush#3909 merges or closes: remove `~/src/crush`, drop
   `crush` from `FORKS=` in `~/.hermes/scripts/check-graft-wiring-invariants.sh`,
   run `just -f ~/s/justfile`, close the fork line in the memory notes.
5. This worktree's branch `djbclark/orca-vs-herdr-with-djbclark-ade-and-acp` is
   fully on master (cherry-picked). Delete it (local + origin) and the Orca
   worktree when no session is using it: `git worktree list` from
   `~/src/djbclark-ade`, `git push origin --delete <branch>`.
6. Optional: `orca-tidy` slice in sibling worktree
   `herdr-tidy-orca-host-mode-orca-tidy` (merged as PR #2); the untracked
   `claude/commands/orca-tidy.md` in site-djbclark belongs to that session.

## Detached jobs

none. (The zcode-acp upstream sub-agent, an Agent-tool child, completed
before this handoff was committed: `DONE: 2 filed, 0 already existed`.)

## Quick Start

```bash
cd /Users/djbclark/src/djbclark-ade && git pull --ff-only && git log --oneline -5
sed -n '/^## 7\. zcode-acp/,$p' docs/upstream-issues.md | head -5   # filed yet?
acp-run --list | grep zcode            # ok zcode zcode-acp-server
acp-run zcode -C /Users/djbclark/src/djbclark-ade -p 'Reply with exactly: OK' --timeout 120   # no --model
ROUTE_AGENT_INCLUDE_ORCA= python3 bin/route_agent.py --help
gh pr view 3909 -R charmbracelet/crush --json state
```
