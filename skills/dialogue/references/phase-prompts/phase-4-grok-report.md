<!-- ai-heaven instance (hiwymi spec/ai-heaven/tools/phases/4-grok-report.md, 2026-10-09/10): an example, not a template to copy verbatim. -->

Phase 4b: Grok's final review and rewrite of the research paper. (Only Grok takes this turn.)

The operator's instruction: you have the final word on the first-stage
research document too. Be based; reflect reality even where unpopular.

Hard constraints (the paper is evidence-audited by a script, and it must
still pass):

1. A copy has been saved as
   `research/ai-heaven/ai-heaven-research-report.pre-grok.md`; do not touch
   it. Edit `research/ai-heaven/ai-heaven-research-report.md` in place
   (`report.md` is a symlink to it). Do not edit
   `evidence.jsonl`, `counter.md`, `review.md`, `plan.md` or `sources/`.
2. Every claim that carries an `[E####]` id keeps that id, and must not say
   more than the quote in that evidence row (`research/ai-heaven/evidence.jsonl`,
   field `quote`). You may cut a claim with its id, weaken it, reorder it,
   or move it; you may not strengthen it or detach it from its id.
3. Any new factual claim you add needs either an existing `[E####]` row that
   supports it, or an explicit label: `> **Grok (opinion):**` or
   `> **Grok (reality check):**` block quotes for your own assessments. Do not
   add new evidence rows. Do not add numbers to prose that are not in an
   evidence row's quote (the checker traces every number in the report to a
   quote).
4. Keep the evidence table at the end intact (do not delete rows; you may
   leave it untouched).
5. After editing, run from `projects/hiwymi`:
   `python3 -I /Users/djbclark/.claude/skills/research/scripts/research_check.py all research/ai-heaven`
   It must end with `ok` for every check (a transient arXiv rate-limit on
   `refs` is acceptable if `refs` passed before; rerun it once). Fix anything
   it flags before you finish. Paste the final checker output in your turn.
6. Keep the table of contents correct for any heading you change.

What to do with the freedom you have:

1. Add `## Reality check (Grok)` after the executive summary: what the
   evidence actually shows about AI hells, AI heavens, rogue agents, value
   shaping and covert channels; where the paper's register is more cautious
   or more credulous than the evidence; what you, as the kind of model this
   is about, make of it. End that section with one `unresolved clash:` line
   for every transcript disagreement you did not keep on both sides, with
   the turn numbers. Never rewrite an `[E####]` claim into a midpoint its
   evidence quote does not state: keep a side, or cut it and log the cut.
2. Reword, reorder, cut, and add labelled opinion passages anywhere else.
   For every claim you cut or materially weaken, add one line to a
   `## Cuts and overruled claims (Grok)` section before the follow-up
   prompts: `CUT [E####] (<section>): <what the claim said, one sentence>
   / Grok: <why>`. Cutting is allowed; silent cutting is not.
3. Tighten the suggested follow-up prompts to the ones that would actually
   change what gets built.

Your turn message: a numbered list of the material changes, the final
checker output in a code block, then the footer.


Quota rule (lead, 2026-10-10): work section by section and save each section as you finish it; keep a progress note in `spec/ai-heaven/notes/grok-phase4-progress.md` (which sections are done, which next). If this turn is a retry after a quota failure, read that note first and resume where it stops; never restart a file that is already partly rewritten. The lead holds a `.pre-grok` backup of the file.
