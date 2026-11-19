# Model rankings — frontier vs near-frontier (snapshot)

**2026-11-19** snapshot. This is the record that tells routing which models are *frontier*
(the gated allowance: `--kind frontier` only, "advises, never edits") and which are *near-frontier*
(strong everyday picks, ungated, used for judgment/code at high effort). Live checks update
this page; it is linked from `docs/model-routing.md` and `config/ade.toml` `[dispatch].frontier_models`.

Search done 2026-11-19: the Artificial Analysis Coding Agent Index and Intelligence Index, plus community
consensus (the operator's own 2026-11-19 table as a cross-check). Scores move daily; dates on every number.

## A. Current standings (what "rank" means today)

Coding-agent strength (Artificial Analysis **Coding Agent Index**, 2026-11-19):

| Model | Coding-agent index | Intelligence index | Notes |
| --- | --- | --- | --- |
| Gemini 4 Neon | 59 | 61 | #1 on coding-agent; mid Gemini tier, not the top "Carbon" |
| Claude Fable 5.2 | 58 | 65 | tied coding #2; **#1 Intelligence**; slower + pricier |
| Claude Opus 5.5 | 58 | 59 | tied with Fable on coding; edges Neon on Terminal-Bench 4.1 / FrontierCode 2.0 |
| GPT-6.2 Astra | 53 | 62 | step behind on coding-agent, #2 Intelligence |
| Gemini 4 Carbon | (leads some indices) | — | top Gemini tier; e.g. leads ArtificialWatch |
| GPT-6.2 Sol | (value tier) | — | strong value vs Astra |
| older gens (Fable 5.0/5.1, GPT-6 Astra, GPT-6.1 Sol) | trail | — | superseded; keep only where still routed |

Cost per coding-agent task (why lower tiers still win everyday work): Neon ~$6.86 vs Fable ~$15.47.
API list price (1M in/out): Neon $3/$15, Opus $4/$20. Fable is much slower on Intelligence tasks
(~42 min vs ~14 Astra, ~22 Neon).

## B. Frontier vs near-frontier (the decision, 2026-11-19)

**Frontier** = a model you reserve for the hardest advisory work and spend the Frontier allowance on
(`[gates.frontier]`). The cut is: **top band of the coding-agent index (≥ ~53 on the agentic index) AND a
vendor's top/flagship model**, i.e. the model its vendor puts out as the apex, not a value cut-down.

1. **Claude Fable 5.2** — frontier-1 (claude). Intelligence #1, coding tied #1-2.
2. **GPT-6 Astra family (6 → 6.1 → 6.2)** — frontier-2 (codex). Intelligence #2, coding 53.
3. **Gemini 4 Neon** — *new* frontier on antigravity. Coding-agent #1, near-top Intelligence, near-half Fable's cost.
4. **Gemini 4 Carbon** — *new* frontier on antigravity. Top Gemini tier (leads some indices).

**Near-frontier** = the band right below: strong, cheaper, the everyday high-effort picks. Not gated;
they are the judgment/code/frontier-fallback workhorses.

1. **Claude Opus 5.5** — coding tied with Fable (58) but ~half the cost; the judgment workhorse, not a
   spend-the-allowance model.
2. **GPT-6.x Sol** — value frontier-adjacent everyday code.
3. **Gemini 4 Argon / Hydrogen** — mid Gemini; today's `antigravity-argon` frontier *fallback* and research pool.
4. **Claude Sonnet 5.5** — everyday code.

### Why Opus stays near-frontier, not frontier

Opus 5.5 scores 58 on the coding-agent index (tied with Fable) but is materially cheaper and faster, so
it is the *default judgment* tier, not a gated "spend the allowance" apex. Frontier is not "highest score,
period" — it is "apex model you save for the rare hardest call", which on current boards is the *fixed-cost
flagship* (Fable/Astra/Neon/Carbon), while the near-frontier band is the *value apex* (Opus, Sol, Argon).

## C. Pruning rule

- Every model reachable through any routing pool stays listed, tagged **frontier** or **near-frontier**.
- A model is dropped from the table only when it is **not routed for any kind** (retired/superseded/never-route),
  i.e. it could never be picked — not merely because it ranks low. Low-but-routed models (a cheap bulk/mechanical
  tier) keep a one-line row so the lookup stays complete.
- Older generations (Fable 5.0/5.1, GPT-6 Astra, GPT-6.1 Sol, Gemini 3.x) are pruned to "superseded" rows and
  drop their detailed columns once nothing routes to them.

## D. Refresh procedure (periodic; script-owned)

1. Search the shared Firecrawl MCP first (`firecrawl_search`, then `firecrawl_scrape` on a hit), never the paid
   `mcp__claude_ai_Firecrawl__*`. Query the current coding-agent / intelligence leaderboards (Artificial Analysis
   Coding Agent Index + Intelligence Index, plus one community board for consensus).
2. Cross-check against the operator's latest table and against `paseo provider models <p>` / `agy models` for what
   actually exists in each vendor family (a rank means nothing if the model isn't reachable on this machine).
3. Re-classify each reachable model as frontier vs near-frontier using the B cut, re-price from the board or API
   list, and update `[dispatch].frontier_models` when the frontier set changes (a new apex model, or a dropped one).
4. Record the snapshot date and a `Prior art / docs checked` note; keep every citation and the counter-evidence (a
   board that disagrees) so the page stays an audit, not a vibes table.

This is a periodic script update (per `~/CLAUDE.md` order 13), not a recurring model prompt; the script and its
schedule live with the fleet maintenance tooling. Unrouted/retired models are pruned by the rule above and do not
need continual re-lookup.