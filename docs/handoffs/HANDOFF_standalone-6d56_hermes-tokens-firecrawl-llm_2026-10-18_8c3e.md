---
schema_version: 1
handoff_id: 8c3e
parent_handoff_ids: []
lineage: none
chain: [standalone-6d56]
repo: djbclark-ade
workspace: hermes-worktrees
branch: master
head_sha: f254481a0c448460c523f50d11b5475599b91667
created_at: 2026-10-18T01:50:00-04:00
writer: claude-code
---
# Handoff — Hermes token leak, Firecrawl without the commercial API, router-side LLM extraction

## The Goal
Started as "analyze our Hermes install for token leaks". It grew into: stop using the commercial Firecrawl API
(djbclark: treat it as non-existent except for comparison tests), and make Firecrawl's `query`/`json` formats work
without it, using the SIPB LLMs (free) and then the free LiteLLM pool. Exa, Parallel and Jina are allowed as a last
resort (djbclark, 2026-10-18).

## Where We Are
Everything below is done, tested and pushed unless marked.
1. Token-leak analysis delivered (no runaway loop; drivers are long sessions with weak pruning, a ~15k-token prompt
   floor, `background_review` about 7% of volume, an oversized skill, and the cron 402s).
2. Commercial Firecrawl fallback removed from the deployment: site-djbclark `roles/shared_mcp` renders no commercial
   key unless `shared_mcp_firecrawl_commercial_enabled=true` (commit 7dc05a2). An earlier router change that spent
   commercial credits was reverted (6872432).
3. Router-side extraction built: `bin/firecrawl-router` strips `query`/`json` from the upstream request, takes the
   markdown from the primary and answers locally: SIPB qwen3.6:35b-a3b-q4_K_M (local proxy 127.0.0.1:8890) when the
   page is up to ~24k estimated tokens, else chunked map-reduce on the same model, then LiteLLM `gemini-free`,
   `gemini-free-lite`. A reply whose `usage.prompt_tokens` is far below the size sent counts as truncated. All rungs
   failing returns the markdown plus `data.warning`. Header `X-Firecrawl-LLM` names the rung. Commits: ade 2e386de
   (code), f254481 (key-hiding test), fee6e8f (docs); site-djbclark d4d4cb0 (passes MIT_SIPB_API_KEY and
   LITELLM_MASTER_KEY to the router only). Live check: small page 26 s via sipb; a 280k-char Wikipedia page ran as 6 chunks
   in 87 s with a correct answer. 31 router tests pass.
4. `~/.hermes/config.yaml` edited (backup beside it, mode 600: `config.yaml.bak-2026-10-18-tokens`): threshold_tokens
   65000, protect_last_n 20, min_tail_user_messages 3, proactive_prune_min_result_chars 2500, memory.nudge_interval 10,
   auxiliary.background_review.max_input_tokens 250000. Gateway restarted (PID 20916), healthy.
5. Cron jobs "Memory curator (daily preservation-first)" (b10cab69899a) and "memory-curator-decision-reminder"
   (403aa97a79e3) repointed from the exhausted Cline pool (HTTP 402) to litellm-local `gemini-free-lite`. The curator was
   re-run once and succeeded (failure_streak 0).
6. `~/.hermes/skills/hermes/hermes-config-pitfalls`: SKILL.md 58.8 KB to 8.5 KB; 19 sections moved verbatim to
   `references/sec-*.md` (line-by-line multiset check: nothing missing).
7. SIPB measurements recorded on a report branch: https://forgejo.mit.edu/djbclark/sipb-llms/compare/main...sipb-bench/firecrawl-extraction-2026-10-18
   (commit fb9eca8, pushed with the forgejo skill's `git-forgejo`, NOT merged).

Dirty state: ade has two modified `tests/test_acp_run_strip*.py` that are another session's. `~/.hermes` has 157 dirty
paths; mine are config.yaml (mixed with a 288-line pre-existing diff) and the skill split (mixed with another agent's
uncommitted paragraphs). Left uncommitted by djbclark's choice.

## What We Tried
1. First fix for the `query` format failure: make the router fall back to commercial Firecrawl when the primary says
   "Query generation failed". It worked and spent commercial credits; djbclark objected; reverted.
2. Assumed the SIPB server needs no key. It returns 401 without one; the local proxy passes the client key through.
3. Background `( ... ) &` jobs reported exit 0 early; waiting on `.rc` files fixed it.
4. A plain `git push` to forgejo.mit.edu fails (no HTTPS credentials); use
   `~/src/djbclark-ade/skills/forgejo/scripts/git-forgejo -C DIR push origin BRANCH`.
5. My first skill-split threshold (12 lines) left 24 KB; a 1 KB-per-section threshold gave 8.5 KB.

## Key Decisions
1. Extraction runs in the router on the Mac, not on Hyades, so Hyades needs no LLM key or route to SIPB.
   Rejected: LLM env on the Hyades Firecrawl (unverified env names, reachability, no truncation detection).
2. Order SIPB, chunked SIPB, free LiteLLM pool (as djbclark approved), even though a Gemini one-shot would be faster
   for very large pages.
3. Paid rungs (Exa, Parallel, Jina) allowed but NOT wired into the router: their APIs are unverified and they would
   need three more keys in the plist. Agents reach them through `web-get`.
4. Did not add a new failure alert for crons: Hermes already appends a "failed N runs in a row" nudge at 3 (config
   `cron.failure_nudge_threshold`).
5. Left ~/.hermes uncommitted: it is shared and the pitfalls skill itself says not to commit a dirty config.yaml.
6. Deviation: edited config.yaml by script, not `hermes config set` (YAML parsed, diff reviewed, gateway came back).

## Evidence & Data
1. SIPB limits (qwen3.6:35b and qwen3.5:4b alike): needle found at both ends up to 28,054 reported prompt tokens;
   at ~32.3k sent the server answers 200 with `prompt_tokens` = 16386 and the start is lost. 16386 = 32768/2 + 2, the
   rule in https://github.com/ollama/ollama/issues/17427. Between 28k and 32k not located.
2. Task screen (11 cases, one run each): qwen3.5:4b 11, qwen3.6:35b 10, qwen3.5:9b 10, gemma4:e4b 6, gemma3:4b 6.
3. About 5 to 7 of 27 sampled pages exceed ~24k tokens (sample leans to docs, Wikipedia, arXiv).
4. Raw data and method: sipb-llms branch above, `report/extra/firecrawl-extraction-2026-10-18/`. The temporary
   scratchpad is gone after the session.
5. `gemini-free` returned a quota 429 (then a LiteLLM 300 s cooldown) and later a 503 during the session; it is also the
   Hermes gateway default model.

## Operator Feedback
1. "We want to avoid using the commercial API." (Firecrawl.)
2. "only the firecrawl commercial fallback is gone - we have I think 2-3 other commercial fallbacks like jina."
3. Chose: all paid rungs allowed, build now, apply all Hermes config, fix skill and cron, report branch, leave ~/.hermes.

## Where We're Going
1. **Next action:** after 09:31 on 2026-10-18, check that "memory-curator-decision-reminder" ran on the new route:
   `python3 -I -c "import json,os;d=json.load(open(os.path.expanduser('~/.hermes/cron/jobs.json')));[print(j['name'],j['last_status'],j['failure_streak'],j.get('last_error')) for j in (d.get('jobs',d)) if j['id']=='403aa97a79e3']"`.
   If gemini-free-lite 429s, try another litellm route or SIPB (`sipb-llms` provider).
2. Review and merge (or revise) the sipb-llms report branch.
3. Optional: wire Exa, Parallel or Jina as final extraction rungs in `bin/firecrawl-router` (needs their REST APIs
   verified and keys added to `roles/shared_mcp`; follow the `Rung`/`Extractor` design).
4. Optional: commit the ~/.hermes work once the other agent's edits there are committed or discarded.
5. Not mine, still red before this session: cron "Gateway Fork Invariants" (`launchd_install()` foreign-job guard
   missing) and "Graft Wiring Invariants" (3 checks).
6. Unverified: first real use of `query`/`json` by an agent through the MCP (verified only via the 18805 listener).

## Detached jobs
none

## Quick Start
```bash
cd ~/src/djbclark-ade && git log --oneline -4 && /opt/homebrew/bin/pytest tests/test_firecrawl_router.py -q   # via ~/ops/site-private/bin/bg
tail -5 ~/Library/Logs/shared-mcp/firecrawl-mcp.log
curl -s -D- http://127.0.0.1:18805/v2/scrape -H 'Content-Type: application/json' -d '{"url":"https://example.com","maxAge":0,"formats":[{"type":"query","prompt":"what is this page?"}]}' | rg -i 'x-firecrawl|answer'
launchctl list | rg 'firecrawl-mcp|hermes-gateway'
```
