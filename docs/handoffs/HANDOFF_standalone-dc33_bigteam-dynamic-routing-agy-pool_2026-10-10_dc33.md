---
schema_version: 1
handoff_id: dc33
parent_handoff_ids: []
lineage: none
chain: [standalone-dc33]
repo: djbclark-ade
workspace: djbclark-ade
branch: master
head_sha: 4c3a0c31095d4f0447d4ce606fa64fd13770a809
created_at: 2026-10-10T13:55:00+00:00
writer: claude-code
---
# Handoff — Bigteam dynamic routing and agy Claude/GPT pool

## The Goal
1. Use agy's Claude/GPT pool (Google AI Pro plan, "a lot of headroom") as much as possible, through `acp-run agy` only, and make `/bigteam` and friends know about it.
2. Make the per-pool split a general mechanism (copilot and others may gain multiple pools).
3. Make `/bigteam` periodically dynamic: route from current quota, not a one-time up-front vendor binding.

## Where We Are
All three goals are done, committed and pushed to `origin/master`; tree clean at `4c3a0c3`.

1. `fe47299` — `bin/route_agent.py`: `Service.burn_first`, `Service.pool=(provider, pool_family)`, `max_parallel`; `pool_service()` maps aiuse windows to services; new service `antigravity-claude` (burn-first while at or above 40% headroom on every window). Claude `fable` pool_family is a model sublimit and is deliberately NOT split. Docs fixed: model-routing skill, bigteam skill, research skill, `docs/model-routing.md`, README.
2. `4c3a0c3` — `route_agent.py plan --kinds code,code,research,bulk [--exclude a,b] [--min-headroom N] [--json]` spreads a wave over pools using `max_parallel`; `STALE_SOFT` 25 min warning; bigteam SKILL.md has "Dynamic routing — plan a wave, re-plan at every boundary" (re-plan on slice finish, quota failure via `aiuse note-exhausted` then `--exclude`, a one-shot `sleep 1500` timer, a pool coming back).
3. Tests: 42 router tests pass; full suite 408 passed at the second commit (run through `bg pytest`).
4. Live check at 13:45 UTC: `plan --kinds code,code,research,bulk` -> both code slices to `antigravity-claude` (49% left), research and bulk to `antigravity` (94% left).

## What We Tried
1. Smoke-testing with the latest aiuse snapshots printed nothing: snapshots from ~13:30 to ~13:37 UTC had 0 accounts. It was transient: by 13:44 `latest.json` had 6 accounts and `aiuse --available --json` returned rc=0. Cause never found. Router falls back to capability-only routing with a stderr warning when the snapshot is empty.
2. `test_no_room_comes_back_as_none_not_an_error` failed: unmeasured services stay reachable as a last resort by design and my fixture omitted `antigravity-claude`. Fixed the fixture, not the router.
3. `self-slash` rejected a 351-character argument (limit ~300); shortened and it queued.
4. MCP failure (see Key Decisions 4): `/mcp` reconnect would NOT have helped; the cause was the session's proxy env.

## Key Decisions
1. Pool split is declarative (`Service.pool`), not an agy special case. Rejected: hard-coding agy.
2. Burn-first thresholds: at or above 40% remaining on every window use it first; 15–40% one slice at a time; under 15% or a 429 it is spent. Rejected: keeping "use agy Opus sparingly".
3. Slices are queued by kind and bound to a vendor only at dispatch; healthy running slices are never moved. Rejected: static up-front binding.
4. Loopback MCP failure: this session had `HTTPS_PROXY=http://opencodex:…@127.0.0.1:10200` (from `~/.claude/settings.json` `env`) and no `NO_PROXY`, so Claude Code's MCP POSTs to `127.0.0.1:18796` (basic-memory) and `:18790` (hermes) went through opencodex and got 405. Direct POST returns 200; POST via the proxy returns 405 (verified). Added `"NO_PROXY": "127.0.0.1,localhost,::1"` to that env block (atomic write, formatting preserved, other keys unchanged). A backup of the old file is in the previous session's scratchpad (`.../892c2ff6-.../scratchpad/settings.json.bak`; may be cleaned).

## Evidence & Data
1. Files: `bin/route_agent.py`, `tests/test_route_agent.py`, `skills/bigteam/SKILL.md`, `skills/model-routing/SKILL.md`, `skills/research/SKILL.md`, `docs/model-routing.md`, `README.md`.
2. Only aiuse snapshot good-run reference used earlier: `2026-10-10T132712.842947Z.json` (`AIUSE_SNAPSHOT=` env).
3. The proxy credential was printed once into the session transcript by an `env | grep proxy` probe; it only works on the local loopback proxy.

## Operator Feedback
1. "Do make it general … copilot" and "make /bigteam at least periodically dynamic" were the only course corrections; both implemented.

## Where We're Going
1. **Next action:** in a FRESH session (the NO_PROXY change applies only to new sessions), run `claude mcp list` and confirm `basic-memory` and `hermes` connect. If they still fail, check whether `ocx`/opencodex rewrites the `env` block of `~/.claude/settings.json` (it owns `HTTPS_PROXY` and `NODE_EXTRA_CA_CERTS` there) and move `NO_PROXY` to wherever it is generated. Note: `settings.json` is not tracked in git.
2. When copilot or cursor is re-enabled in aiuse and reports more than one `pool_family`, add a `Service(pool=(provider, pool_family))` row in `bin/route_agent.py` (copy the `antigravity-claude` row) and, in bigteam's pool-class table, classify the pool as burn-first only if its idle window resets unused.
3. Optional: find why aiuse snapshots were empty 13:30–13:37 UTC (`aiuse --available --live`, collector logs). Low priority; recovered by itself.
4. Not asked this session: whether to add anything to `docs/apply-toolchain-prompt.md` (existing skills changed, no new tool).

## Detached jobs
none

## Quick Start
```bash
cd ~/src/djbclark-ade && git status -sb          # expect clean, at 4c3a0c3 or later
claude mcp list 2>&1 | grep -E 'basic-memory|hermes'
python3 bin/route_agent.py plan --kinds code,code,research,bulk
~/ops/site-private/bin/bg pytest tests/test_route_agent.py -q
```
