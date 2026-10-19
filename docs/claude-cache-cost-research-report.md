# Cutting Claude Code's cache cost: what the data says (2026-10-18)

Scope: item 3a of the graphify answer ("cache reads are most of the cost; shorter sessions and earlier delegation"). Research only: nothing on the machine was changed except the new measuring tool, `bin/claude-cost-mix` (djbclark-ade `b117768`, `24bfc5d`).

Data: the last 7 days of Claude Code transcripts on this Mac: 667 transcripts, 25,408 API requests, 77 compactions. Costs are API list-price dollars, priced by each request's own model. On the subscription this is a quota equivalent, not a bill.

## 1. Correction first

My earlier reply said cache reads were 71% of cost and navigation output at most 16%. Both figures priced every cache read at 0.1× base input. Opus 5.5 and Sonnet 5.5 reads cost 0.05× and Fable 5.1 reads 0.025×<sup>[1](#C1)</sup>, and 93% of our read tokens were on those models.

Repriced, the week cost about **$1,677 at list price**:

| Component | Share |
|---|---|
| Cache reads | 46.6% |
| Cache writes (1-hour TTL, 2× base) | 37.4% |
| Output | 15.9% |
| Uncached input | 0.0% |

Navigation output is at most 13.1% (it was 16%). The graphify verdict stands. The project memory note from that answer now carries the corrected numbers.

## 2. Where the money goes

1. **By context size at the request:** <100k 16.0%, 100–200k 36.4%, 200–300k 31.4%, 300–400k 11.9%, 400k+ 4.3%. The average request carries about 180k of context.
2. **Main sessions vs sub-agents:** 77.6% vs 22.4%. A sub-agent starts at a median of 52k tokens, the same preamble the main session carries (median 53k).
3. **Fixed preamble:** the first request's context, re-read on every later request, is **17.2% of all cost**. That counts reads only; its writes at session start come on top.
4. **Cache writes, $628/week, by cause:**

| Cause | Share of writes | Requests |
|---|---|---|
| Normal per-turn growth (<20k new) | 52.0% | 24,515 |
| Rebuild after more than 1 hour idle | 16.7% | 67 |
| Main-session start (preamble + first prompt) | 11.9% | 518 |
| First request after a compaction | 7.2% | 77 |
| Sub-agent start | 5.4% | 144 |
| Large single additions (≥20k) | 3.4% | 79 |
| Model switch, other cache busts | 3.4% | 18 |

## 3. The preamble has nearly doubled since the 2026-10-10 trim

`claude -p "/context"` in this repo measured **46.3k** tokens for a fresh session today. On 2026-10-10 it was 26.7k (docs/disabled-skills.md). This headless figure also leaves out the claude.ai connectors, which `-p` blocks: Gmail, Calendar, Drive and the cloud Firecrawl.

| Part | 2026-10-10 | Today |
|---|---|---|
| Memory files | 5.5k | 14.5k (global `CLAUDE.md` 8.3k, `djbclark-ade/AGENTS.md` 5.8k) |
| MCP tools loaded up front | 4.8k | 11.0k |
| MCP server instructions | 3.1k | 4.8k |
| Skills listing | 10k | 10k (bailian ×10 ≈ 1.6k, paseo ×6 ≈ 0.6k, ralph ×5 ≈ 0.5k) |

## 4. Levers, ranked by measured or estimated saving

| # | Lever | Weekly effect | Basis |
|---|---|---|---|
| 4.1 | Trim the preamble back to ~27k (−19k) | **≈ −8%** (~$140) | Measured preamble share, scaled by 19/53, plus session-start and post-compaction rewrites |
| 4.2 | Idle compaction from 100k: `CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS=100000` | ≈ −2% | 60 of 88 idle rebuilds were under the 200k default<sup>[3](#C3)</sup>; estimate |
| 4.3 | Compaction threshold 400k → 300k (or 250k) | −1.6% (−1.8%) | Simulated on the real request history |
| 4.4 | Hand off and start fresh at task boundaries instead of compacting | not simulated; likely the larger behavioural win | A fresh session is ~46–53k with no summary call; a compacted one floors at ~104k |
| 4.5 | Shrink the ~104k post-compaction floor | makes 4.3 pay more | Compaction re-attaches up to 5 files and up to 25k of skill bodies<sup>[5](#C5)</sup> |
| 4.6 | Keep the 1-hour TTL everywhere | 5-minute everywhere: **+30.6%**; sub-agents on 5-minute: **+2.9%** | Simulated; 3.2% of requests follow a 5–60 min gap |
| 4.7 | A threshold of 200k or lower | 200k: +1.0%; 150k: **+17.2%** | Simulated: too many compactions |

On 4.6, the web research suggested moving sub-agents to the 5-minute TTL (`CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL=5m`)<sup>[2](#C2)</sup>. Our data says no. Our sub-agents often sit 5–60 minutes on long foreground waits, and every such gap would force a full rewrite.

On 4.3, the published break-even math (pay back in 4–12 turns<sup>[2](#C2)</sup>) assumes a ~50k post-compaction context. Ours is ~104k, and at 0.05× reads that roughly halves the benefit. This matches the 2026-10-10 measurement in `feedback_self_compact`.

Output is 15.9% and belongs to effort routing, so it is outside this report. Uncached input is negligible.

## 5. Proposed changes to the self-compact setup

The "auto-compact skill" here is `claude/hooks/context_size_nudge.py` plus `bin/self-slash`, governed by `feedback_self_compact`. None of the following is applied yet.

1. **At task completion, prefer handoff then `/new` over `/compact`.** Do this once context is past about 150k and the next task is not a direct continuation. Today the nudge says this only on a topic change. Anthropic's own advice points the same way<sup>[4](#C4)</sup>.
2. **Lower the hard ceiling from 400k to 300k:** `autoCompactWindow` and the hook's `ASK_TOTAL`, about −1.6%. Keep the +200k-from-floor growth tier. Do not go to 200k total.
3. **Set `CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS=100000`** in `~/.claude/settings.json` `env`. Idle compaction needs the 1-hour TTL we already run and fires about 54 minutes after the last request<sup>[3](#C3)</sup>. It catches the 100–200k sessions that are left idle and later resumed.
4. **Keep summaries short.** The `/compact <focus>` text should ask for a brief summary. A `Compact Instructions` section in `AGENTS.md` steers automatic compactions too<sup>[5](#C5)</sup>. Compaction inherits extended thinking, and its output is billed at 5×<sup>[5](#C5)</sup>.
5. **Add a preamble budget guard.** The 10-10 trim grew back within 8 days. A nightly `claude -p "/context"` check (skillopt-night or fleet-watch) should send a Hermes ping when a fresh session goes over about 30k, naming the part that grew.
6. **Do the 4.1 trim itself:**
   1. Condense the global `CLAUDE.md` and `djbclark-ade/AGENTS.md` (14.5k → ~8k).
   2. Move rarely used skill families (bailian, paseo, ralph, siyuan) out of the global listing into the projects that use them.
   3. Check which MCP servers load tools up front (11k).
   4. Review the claude.ai connectors in interactive sessions: Gmail, Calendar, Drive, and the cloud Firecrawl that rule 7 already forbids.
7. **Leave the TTL alone**, and record why: we measured that both 5-minute variants cost more.

## 6. Caveats and next measurement

1. List prices stand in for subscription quota. Anthropic does not publish whether plan limits weight cache reads and writes exactly like the API.
2. The compaction simulation keeps the real per-turn growth and assumes nothing dropped needs re-reading. Real compaction loses some state, so treat −1.6% as an upper bound.
3. 4.1, 4.2 and 4.4 are estimates. Decision-grade evidence would be paired tasks run twice (current setup vs trimmed preamble and a 300k ceiling), judged on cost per successful task, as arXiv 2607.12161 argues<sup>[6](#C6)</sup>.
4. Server-side context editing (`clear_tool_uses`) invalidates the cache from the cleared point<sup>[7](#C7)</sup>, and Claude Code's own tool-result clearing has no setting. Neither is a lever we can pull.

Scripts: `bin/claude-cost-mix` (the cost split) and `bin/claude-cost-whatif [DAYS]` (the TTL and compaction-threshold simulations in 4.3, 4.6 and 4.7; default 7 days).

## Citation footnotes

1. <a id="C1"></a>C1 — Opus 5.5 and Sonnet 5.5 cache hits are 0.05× base input, Fable 5.1 0.025×; 1-hour writes 2×; no long-context premium — Anthropic pricing (docs; Anthropic), fetched 2026-10-18. <https://platform.claude.com/docs/en/about-claude/pricing>
2. <a id="C2"></a>C2 — `ENABLE_PROMPT_CACHING_1H` covers both buckets; per-bucket TTL env vars; a compaction while warm reads the cached prefix — Claude Code prompt caching (docs; Anthropic), fetched 2026-10-18. <https://code.claude.com/docs/en/prompt-caching>
3. <a id="C3"></a>C3 — `idleCompaction` needs the 1-hour TTL, a 200,000-token default threshold and ~54 minutes idle; `CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS` (floor 100000) — Claude Code settings (docs; Anthropic), fetched 2026-10-18. <https://code.claude.com/docs/en/settings>
4. <a id="C4"></a>C4 — "start a fresh session to execute it"; "`/clear` costs nothing" — Claude Code best practices (docs; Anthropic), fetched 2026-10-18. <https://code.claude.com/docs/en/best-practices>
5. <a id="C5"></a>C5 — after compaction Claude Code re-reads up to five files and skill bodies up to 25,000 tokens; the summary inherits thinking; Compact Instructions — Claude Code context window (docs; Anthropic), fetched 2026-10-18. <https://code.claude.com/docs/en/context-window>
6. <a id="C6"></a>C6 — cutting tool output 38.4% raised billed cost 6.8%; evaluate cost per successful task — "Token Reduction Is Not Cost Reduction" (paper; arXiv), v5 2026-08-12. <https://arxiv.org/abs/2607.12161>
7. <a id="C7"></a>C7 — tool-result clearing invalidates cached prefixes from the cleared point — Anthropic context editing (docs; Anthropic), fetched 2026-10-18. <https://platform.claude.com/docs/en/build-with-claude/context-editing>
