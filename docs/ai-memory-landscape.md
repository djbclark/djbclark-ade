# AI memory: the six levels, where we are, and the wider field

Snapshot **2026-08-23**. The machine-local plan is not in this repo — it lives
at `~/ops/site-djbclark/docs/plans/memory-architecture-v2.md` (accepted
2026-08-18, issue #139), with the Hindsight-specific slice at
`~/ops/site-private/memory/project_hindsight_memory_restructure.md`. This file
is the orientation layer: what the levels are, where they came from, and how
they line up with the published literature.

## Where the six levels came from

A YouTube video the operator summarized on 2026-08-11:
**https://youtu.be/UHVFcUzAGlM** — channel `youtube.com/@simonscrapes`.

Note the title drift: the actual video title is **"Every Claude Code Memory
System Compared (So You Don't Have To)"** (verified by fetching the page
2026-08-23). Hermes's memory recorded it as "6 Levels of Claude Code Memory",
which is the *summary's* descriptive title, not the video's. The plan itself
never cites the video — it cites only Karpathy's LLM Wiki — so this
provenance existed solely in session memory until now.

The levels as named in that source:

| Level | Source's name | What it is |
|---|---|---|
| 1 | CLAUDE.md + auto-memory | native, in-project instructions |
| 2 | Structured `.claude/memory/` + session-start hook | Pavel Huryn / John Connolly pattern |
| 3 | MemSearch (Zilliz plugin) | durable memory.md + daily notes, semantic top-3 auto-injection |
| 4 | MemPalace | local RAG, verbatim recall, SQL + ChromaDB, symbolic index |
| 5 | Karpathy's LLM Wiki (+ Recall, LightRAG) | `raw/` + `wiki/`, "second brain" |
| 6 | Open Brain (Nate Jones) / Mem0 | shared cross-tool memory: one table + embeddings + MCP |

The plan renumbers to 0–6: it adds **Area 0** (bounded bootstrap capacity /
overflow safety — a Hermes-specific concern absent from the video), collapses
MemPalace into "verbatim transcript/event recall", and generalizes the LLM
Wiki into "interlinked knowledge base".

## Status per area (from Hermes, 2026-08-23)

| Area | Status | Today |
|---|---|---|
| 1 Native instructions | **done** | AGENTS.md/CLAUDE.md across `~` and the three ops repos |
| 2 Structured files / SQLite (S1) | **Phase B: both adapters live 2026-08-23** | Phase A capacity journal, plus the new evidence store: `site-djbclark/bin/hindsight_s1.py` adds event/conversation/raw_object/attachment/checkpoint/gap tables to the same database, content-addressed raw bytes under `~/.hindsight/cas/`, and event IDs derived from source coordinates. 20 tests cover the exit-gate properties. Hermes event sink added too (`hindsight_s1_hermes.py`, reads `state.db` read-only). Remaining: attachments, trigram/neighbour retrieval, Arq backup coverage |
| 3 Semantic recall (Hindsight) | **restructured 2026-08-23** | Service live; model switch done (~$0.47/mo). Per-repo bank restructure **executed**: 78 docs / ~801 facts moved into 11 `coding-agent::<repo>` banks, `hermes-shared` curated to the cross-project channel, stray banks removed. Known issue remaining: 25% reflect-failure at the 25s cap |
| 4 Verbatim recall | **foundation in place 2026-08-23** | Backfill complete: **210,824 events / 916MB** of exact producer bytes in the CAS, from all 532 Claude transcripts (208,534 records, 0 skipped). `verify` passes: integrity ok, 3,000-sample hash check clean. Repo attribution now captured at ingest — tendcf 36k, stayturgid 28.5k, site-private 15.5k, site-djbclark 15.5k, sudo-secretspec 15.5k events. Remaining: expose verbatim spans through recall |
| 5 Linked knowledge (Link) | **early** | Viability spike done, 6 preview notes in `site-private/memory/link/`. No canonical repo, no shadow comparison |
| 6 Cross-tool sharing | **working, after a real fix** | Hermes↔Claude bridged over MCP 2026-08-23. The memory half was silently broken: Hermes's provider config (`~/.hermes/hindsight/config.json`) templated its bank as `hermes-{profile}-{workspace}`, so it never read `hermes-shared` — retained facts were committed and API-recallable yet invisible to it, and it answered confidently wrong. Both keys now pinned to `hermes-shared`; verified Hermes recall returns the shared facts |
| 0 Capacity guard | **done** | 75/85/70 thresholds + supervised writer in the Hermes bootstrap store |

**Where the effort now goes**: areas 2 and 4 have their foundation and need
retrieval surfaced; area 5 (Link) is the largest untouched piece — still just
a viability spike and six preview notes, with no canonical repo and no shadow
comparison running. That is the next real build.

## How the plan handles cross-vendor memory

Verbatim from the plan: scope is *"Hermes and Claude first; portable to other
local agents"*; non-negotiables say *"Other MCP/CLI-capable agents should be
supportable without copying canonical state into each runtime"*; §9.3 requires
other clients to *"prefer the same Link MCP contract and S1 event envelope.
Never copy canonical memory into client-private stores as the synchronization
mechanism."* §9.4 explicitly reserves Codex's own consolidation artifacts
(`memory/codex/memory_summary.md`, `raw_memories.md`) as read-only and
non-competing.

So cross-vendor is a first-class *requirement* but only Hermes and Claude are
first-class *clients*.

## How this compares to the published field

Useful because the plan's six levels are an **implementation-layer** taxonomy
(where memory physically lives), while the academic taxonomy is
**cognitive** (what the memory is *for*). They are orthogonal — worth keeping
straight when reading outside material.

- The dominant academic split is **four** types, from Princeton's **CoALA**
  framework ([arXiv:2309.02427](https://arxiv.org/abs/2309.02427)): working
  (in-context), episodic, semantic, procedural.
  ([overview](https://atlan.com/know/types-of-ai-agent-memory/))
- Extended taxonomies add more — a **7-type** version adds retrieval,
  parametric, and prospective memory
  ([MarkTechPost](https://www.marktechpost.com/2026/06/21/the-7-types-of-agent-memory-a-technical-guide-for-ai-engineers/)).
- Mapping ours onto theirs: our Area 3 (Hindsight) is doing *semantic +
  episodic* at once — and the measured 83%-episodic skew in the shared bank is
  precisely the failure of not separating them. Area 4 is episodic-verbatim,
  Area 1 is procedural, Area 0 is working-memory capacity management.

On cross-vendor portability specifically (the video's Level 6), the field
moved during 2026:

- **PAM (Portable AI Memory)** — an open spec for a vendor-neutral memory
  interchange format, positioned as "vCard for AI memory"
  ([portable-ai-memory.org](https://portable-ai-memory.org/blog/ai-memory-portability-problem/)).
- **Vendor import tools** — Anthropic shipped conversation-history import in
  early March 2026, Google ~3 weeks later (ZIP upload up to 5GB). One-way
  migration, not live sharing.
- **Memory-passport products** — e.g. MemoryLake, a platform-neutral layer
  detaching memory from any one provider
  ([landscape survey](https://mnemoverse.com/docs/research/ai-memory-landscape-2026)).

Implication for us: the plan's "never copy canonical memory into
client-private stores" rule is the right instinct and matches where the
standards are heading. If PAM stabilizes, it is the natural wire format for
the S1 event envelope rather than something to invent.
