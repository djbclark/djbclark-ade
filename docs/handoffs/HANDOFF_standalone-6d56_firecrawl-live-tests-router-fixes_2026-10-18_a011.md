---
schema_version: 1
handoff_id: a011
parent_handoff_ids: [8c3e]
lineage: deterministic
chain: [standalone-6d56]
repo: djbclark-ade
workspace: hermes-worktrees
branch: master
head_sha: 030884382c3ae188699a7b978fa3ff3779c3f286
created_at: 2026-10-18T10:05:00-04:00
writer: claude-code
---
# Handoff — Firecrawl query/json live tests, router hardening, reminder cron repointed

## The Goal
Continuation of handoff 8c3e (stop using the commercial Firecrawl API; answer `query`/`json` in `bin/firecrawl-router`
with the SIPB LLMs, then the free LiteLLM pool). This stretch: prove it end to end, comprehensively, overnight, with
few of the model's own tokens (djbclark was asleep and said to use judgement, broaden or tweak freely).

## Where We Are
Everything below is done, tested and pushed unless marked.
1. Report branch merged: `sipb-llms` main is `fb9eca8` (fast-forward, diff was additions only, no secrets).
2. `query` and `json` verified through the shared MCP (`mcp__firecrawl__firecrawl_scrape`) on example.com and httpbin;
   served by the `sipb` rung, router log shows the self-hosted primary only.
3. Live suite on isolated router instances (ports 19101-19108, commercial key blanked): run 1 was 66/67, run 4
   (after fixes) 67/67; a second round of 14 cases (Japanese, Korean, Russian, Chinese, Arabic, C source, deadline,
   directQuote) was 13/14, the one miss being my wrong expectation. Harness, README and results are in
   `skills/firecrawl/scripts/live-suite/` (`RESULTS-2026-10-18.md`).
4. Five router fixes in `bin/firecrawl-router`, ade commit `6aabe2b`, 39 tests pass (8 new), live service restarted
   (`launchctl kickstart -k gui/501/com.djbclark.firecrawl-mcp`, PID 47397):
   a. truncation check ignores prompts under 40,000 chars and also flags the exact 16386 cap (ollama#17427);
   b. `LLM_DEADLINE` is enforced inside the chunk loops (was checked only between rungs);
   c. one empty reply is retried on the same rung (SIPB sometimes returns finish_reason=stop with empty content);
   d. `directQuote` can answer NONE (returns the abstain text, no escalation); `LLM_QUOTE_SYS` says so;
   e. an empty page gets a "no content" warning; each failed rung logs `llm rung NAME failed: REASON`.
   (c landed after run 3, so run 3 never saw it; run 4 is the post-fix baseline.)
5. Skill docs: `skills/firecrawl/SKILL.md` has a "Testing the router live" section (ade `855282b`, `0308843`).
6. Cron "memory-curator-decision-reminder" (`403aa97a79e3`) failed again at 09:32 today with a Gemini 429 (streak 10).
   Repointed to provider `sipb-llms`, model `qwen3.6:35b-a3b-q4_K_M` with `hermes cron edit`, run once with
   `hermes cron run`: ok, streak 0, delivered to Telegram. Curator "Memory curator (daily preservation-first)"
   (`b10cab69899a`) is still on litellm-local `gemini-free-lite`; it ran ok at 08:00.
7. Tier 1 pointer rewritten (`~/.local/state/handoffs/chains/standalone-6d56/SESSION_LOG.md`).

Dirty state: ade has another session's `tools/acp-run/README.md`, `tools/acp-run/acp-run`, untracked
`tests/test_acp_run_resume_order.py` and a quota-reset handoff: not mine. `~/.hermes` is dirty (my config.yaml
tuning, the pitfalls-skill split, `cron/jobs.json` pin) and left uncommitted by djbclark's choice.

## What We Tried
1. Importing `bin/firecrawl-router` as a module with `SourceFileLoader` alone crashes on `@dataclass` (module not in
   `sys.modules`); register it first, as `tests/test_firecrawl_router.py` does.
2. Reading the plist environment with `launchctl print` leaked the Hyades, SIPB and LiteLLM keys into the transcript.
   Use `plistlib` inside a script. The skill now says so. djbclark chose not to rotate.
3. My first leak scan counted the Hyades hostname as a secret and flagged every log; the three real keys had 0 hits.
   Fixed in the saved harness (it skips `*_URL`).
4. `( ... ) &` under `run_in_background` returns at once; I waited on `suite.rc` files with an until-loop instead.
5. First reading of the `directQuote` failure was "SIPB cannot quote"; wrong. My test question asked for a whale
   sentence in a page with no whale; SIPB correctly said "not contained", the router escalated, Gemini returned an
   unrelated real sentence. Fixed by fix 4d, not by a test change.
6. A polling loop after `hermes cron run` compared `last_run_at` to `'2026-10-18T10:'` and never matched 09:59;
   it wasted 24 polls. Compare against the job's previous `last_run_at` instead.

## Key Decisions
1. Merged the report branch (djbclark: "why not just merge it?" after I recommended review). Rejected: opening a PR.
2. Exa, Parallel and Jina rungs: not wired (djbclark: not now). Agents reach them through `web-get`.
3. `~/.hermes` stays uncommitted. Rejected: committing only my hunks.
4. No key rotation (djbclark). Rejected: rotating the Hyades and SIPB keys.
5. Reminder cron pinned to SIPB (free, local proxy), not another Gemini route: Gemini free quota 429s on and off.
6. Deviation, disclosed: restarted the live firecrawl service unasked (djbclark had said nobody would use the servers).
7. gemini 429 on a huge one-shot page when SIPB is down: no code change. It passed in run 4 (gemini-free-lite
   chunked x2); when both Gemini rungs are cooling down there is no free rung left.

## Evidence & Data
1. Page sizes (markdown chars): turing 274k, python 207k, ww2 508k, rfc9110 503k, berlin-de 546k, pydoc 44k, hn 18k,
   example 958. Chunked SIPB times: turing ~65 s, python ~65-95 s, ww2 query 157 s / json 170-257 s, ja 176 s, ar 238 s.
2. SIPB handled non-Latin scripts and C source chunked with correct answers (ja, ko, ru, zh, ar, kernel/sched/core.c).
3. Unreachable host: primary returns HTTP 200 `success:false` `SCRAPE_DNS_RESOLUTION_ERROR`, passed through by design.
   A real 404 scrapes as 200 with empty markdown (now warned).
4. `json` field choice drifts on ambiguous schemas ("title" on example.com took four values in five runs); links stable.
5. Forced failover all behaved: dead SIPB, wrong key (401), bad model (400), bogus first LiteLLM model, all rungs dead
   (markdown + warning), LLM off ("Query generation failed after all models."), 6 s deadline (warning, ~18 s).
6. Leak scan: the three keys appear in no result or router log. Full tables: `RESULTS-2026-10-18.md`.

## Operator Feedback
1. "Run more comprehensive testing ... until 5am ... as long as you don't use too many of your AI tokens."
2. "I'll be sleeping so use your best judgement ... broaden or change the scope or try tweaking things as desired."
3. Merge the report branch; no paid rungs now; leave `~/.hermes` uncommitted; don't rotate keys; run /handoff.

## Where We're Going
1. **Next action:** on 2026-10-19 after 09:59, confirm both crons stayed green:
   `python3 -I -c "import json,os;d=json.load(open(os.path.expanduser('~/.hermes/cron/jobs.json')));[print(j['name'],j['last_status'],j['failure_streak'],j.get('last_error')) for j in d.get('jobs',d) if j['id'] in ('403aa97a79e3','b10cab69899a')]"`.
   If the curator (gemini-free-lite) 429s, repoint it the same way:
   `hermes cron edit b10cab69899a --provider sipb-llms --model 'qwen3.6:35b-a3b-q4_K_M'`.
2. Optional: wire Exa, Parallel or Jina as last extraction rungs in `bin/firecrawl-router` (declined for now; needs
   their REST APIs verified and keys in `roles/shared_mcp`; follow the `Rung`/`Extractor` design).
3. Optional: commit the `~/.hermes` work once the other agent's edits there are resolved.
4. Not mine, red before this session: crons "Gateway Fork Invariants" and "Graft Wiring Invariants".
5. Optional: re-run the live suite after any router change (about 45 min, `skills/firecrawl/scripts/live-suite/README.md`).

## Detached jobs
none

## Quick Start
```bash
cd ~/src/djbclark-ade && git log --oneline -5   # 0308843 on top of 855282b, 6aabe2b
~/ops/site-private/bin/bg /opt/homebrew/bin/pytest tests/test_firecrawl_router.py -q   # 39 passed
tail -5 ~/Library/Logs/shared-mcp/firecrawl-mcp.log; launchctl list | rg 'firecrawl-mcp|hermes-gateway'
cat skills/firecrawl/scripts/live-suite/README.md
```
