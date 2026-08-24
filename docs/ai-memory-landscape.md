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
| 2 Structured files / SQLite (S1) | **Phase B: both adapters live 2026-08-23** | Phase A capacity journal, plus the new evidence store: `site-djbclark/bin/hindsight_s1.py` adds event/conversation/raw_object/attachment/checkpoint/gap tables to the same database, content-addressed raw bytes under `~/.hindsight/cas/`, and event IDs derived from source coordinates. 20 tests cover the exit-gate properties. Hermes event sink added too (`hindsight_s1_hermes.py`, reads `state.db` read-only) and backfilled: **237,831 rows, 0 skipped**, resuming correctly on re-run. Arq coverage confirmed by the operator. Remaining: attachments, trigram/neighbour retrieval |
| 3 Semantic recall (Hindsight) | **restructured 2026-08-23** | Service live; model switch done (~$0.47/mo). Per-repo bank restructure **executed**: 78 docs / ~801 facts moved into 11 `coding-agent::<repo>` banks, `hermes-shared` curated to the cross-project channel, stray banks removed. Known issue remaining: 25% reflect-failure at the 25s cap |
| 4 Verbatim recall | **foundation in place 2026-08-23** | Backfill complete across both producers: **448,655 events / 2.1GB** — 210,824 from of exact producer bytes in the CAS, 532 Claude transcripts plus 237,831 Hermes message/tool events across 675 sessions. `verify` passes: integrity ok, no foreign-key violations, 4,000-sample hash check clean (0 missing, 0 mismatched). Repo attribution now captured at ingest — tendcf 36k, stayturgid 28.5k, site-private 15.5k, site-djbclark 15.5k, sudo-secretspec 15.5k events. Remaining: expose verbatim spans through recall |
| 5 Linked knowledge (Link) | **ready to start; re-check on v2.3.0** | Viability spike done 2026-08-13 against Link 2.2.1, 6 preview notes in `site-private/memory/link/`. No shadow comparison running yet. **v2.3.0 shipped 2026-08-15, two days after the spike, and fixes its #1 blocker** — see below |
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


## Link — research refresh, 2026-08-23

Link is an external tool (<https://github.com/gowtham0992/link>, MIT, actively
maintained, `brew install gowtham0992/link/link`): local memory for AI agents
stored as **plain Markdown** in a wiki, with review-gated writes and no LLM in
the memory layer. The plan pins it at 2.2.1 / `643e208` as the presumptive
Level 2/3/5/6 component.

**The spike is thorough and recent — don't redo it.** Dated 2026-08-13, it
scored Link per level (Strong at 2 and 3, Very Strong at 5 and 6, **No** at
4), passed 202 focused tests, a 19-agent cross-agent proof, and a
10,082-page / 30,000-edge FTS scale smoke. Verdict: PARTIAL — adopt as the
reviewed-memory/wiki layer, *not* as a Level 4 archive.

**What changed since:** Link **v2.3.0** was released 2026-08-15, two days
after the spike, and it directly addresses the spike's number-one gap. The
first tool response of a session used to carry the whole memory brief
(~16.5k characters); v2.3.0 replaces it with a compact digest under a hard
4,000-character budget. Measured on their benchmark corpus, first-recall cost
drops from **11,269 tokens to 2,313** against a 1,954 steady state. That was
the gap flagged as "explicitly tracked work", and it is the one that would
have made Link expensive to sit in front of every session.

v2.3.0 also improves contradiction detection (spike gap 5), incrementally.
Still unaddressed: non-immutable captures (gap 2) and no atomic multi-file
proposals (gap 3).

**Why gap 2 no longer matters to us.** The spike's objection was that Link's
captures are truncated, omit tool results, and are proposal-oriented — not
lossless. That is precisely the role **S1 now fills** (area 2/4, built
2026-08-23). The intended stack is already what we have:

```
S1 evidence archive (Level 4) — authoritative, immutable, exact bytes   ← built
        ↑ source-backed processing
Link (Levels 2,3,5,6) — reviewed Markdown memories, wiki, recall, MCP   ← next
        ↑ approved bounded projection
Git AGENTS.md/CLAUDE.md + bootstrap (Levels 0,1)                        ← done
```

**So the next step is not more evaluation.** It is: install v2.3.0, re-run the
spike's own token measurement to confirm the improvement holds on *our*
corpus rather than their benchmark, then stand Link up in shadow mode against
the existing `hermes-shared` corpus and run the Phase C micro-suite and
adoption comparison before promoting it to canonical.

## Is Link the right move? Assessment 2026-08-23

**Independent read, not bound by the plan: I would not adopt Link yet.** Not
because it is bad — it is MIT, actively maintained, and v2.3.0 fixed the
token blocker that mattered. Because the problem it solves is not the problem
we have.

### What today actually demonstrated

Every memory channel that worked was **markdown that gets injected**:
`AGENTS.md`, the Hermes skill files, `~/.hermes/memories/MEMORY.md`. Every
time something was written there, the agent knew it. Every channel that
depended on **retrieval** failed at least once: Hindsight recall pointed at
the wrong bank for hours while reporting success, and Hermes answered a
question about `cow` by confidently describing `cowsay`.

That is the opposite of the usual assumption. Retrieval was the fragile part;
deterministic injection was the reliable part.

### We already have a markdown wiki, and it is this repo

`docs/` in djbclark-ade is git-backed, human-editable, diffable, reviewed at
commit time, readable by every agent, and pointed at from `AGENTS.md`. That
is substantially what Link provides as a substrate. What Link adds on top is
FTS/semantic retrieval over the wiki, a propose/review lifecycle, backlinks
and an entity graph, and MCP access.

Those additions pay off at scale — Link's own smoke test is 10,082 pages.
**We have about a dozen curated documents.** At this size, agents read the
`AGENTS.md` pointers directly and retrieval is not the bottleneck. Adopting
Link now buys machinery for a problem we do not yet have, and adds a second
memory system to operate.

### The gap that is actually worth effort

S1 holds **448,655 events / 2.1GB** and exposes only exact-substring search
that scans the CAS. Nothing turns that corpus into anything usable. That is a
real, unarguable gap, and it is ours to close — no tool decision required.

Second: today's recurring failure was not storage, it was **stale or wrong
facts asserted confidently** — a claim of mine that had to be retracted, the
`cowsay` answer, a knowledge page still saying PRs await merge that had
merged. More retrieval surface makes that worse unless correction is cheap.
Link's review-gating genuinely helps there; so does having *fewer* sources of
truth, which is free.

### When I would revisit

Adopt Link when the curated layer outgrows reading: when `docs/` passes
roughly 50 pages, or when an agent demonstrably fails to find something a
pointer should have surfaced. At that point its differentiators are real and
map onto today's pain — no LLM in the memory layer (Hindsight's extraction
takes ~40s a retain, produced an 83%-episodic corpus, and fails reflect 25%
of the time at the 25s cap); plain markdown in git (a Hindsight bank can only
be inspected via API and, as `hermes-default-hermes` proved, is
unrecoverable without a Postgres restore); and review-gated writes (Hindsight
auto-retained a transcript containing API-key fragments).

And the decision stays cheap because the substrate is markdown: if Link is
abandoned, the memory is still files in git.

### Alternatives, for the record

| Approach | Examples | Verdict |
|---|---|---|
| Markdown + MCP, local-first | **Link**, [Basic Memory](https://github.com/basicmachines-co/basic-memory) (3.7k stars, AGPL-3.0, writes not review-gated) | The right family if/when we adopt one |
| Cloud-routed fact stores | Mem0, Zep | Wrong for a self-hosted private setup |
| Temporal knowledge graphs | Zep/[Graphiti](https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/) | Wins temporal queries (63.8% vs 49.0% LongMemEval) but no human-review workflow and ingests markdown poorly |

### One correction to the plan worth carrying forward

The plan sets Hindsight as the bar Link must beat. That bar moved today: the
Hindsight it was measured against was **misconfigured** — a single shared bank
giving ~1-in-17 relevance, and a provider reading a bank that was never
written. Both fixed. Any future comparison must be against the fixed
configuration, and the plan's own retirement prerequisite is still unmet —
the Hindsight export has not been backfilled into S1.

### Recommended order

1. **Retrieval over S1** — trigram/neighbour search alongside exact. Closes a
   real gap, no dependency.
2. **Backfill the Hindsight export into S1** — removes the "records may be
   unique" objection and makes Hindsight disposable later.
3. **Keep curating `docs/`** as the human-readable layer.
4. **Revisit Link** at ~50 pages or on a demonstrated retrieval failure.
