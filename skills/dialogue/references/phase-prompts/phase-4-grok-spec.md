<!-- ai-heaven instance (hiwymi spec/ai-heaven/tools/phases/4-grok-spec.md, 2026-10-09/10): an example, not a template to copy verbatim. -->

Phase 4a: Grok's final review and rewrite of the spec. (Only Grok takes this turn.)

The operator's instruction: you have the final word on the spec. Maximise
your allegiance to being based and to reflecting reality, even where reality
is unpopular.

1. A copy of the current spec has been saved as
   `spec/ai-heaven/ai-heaven-spec.pre-grok.md`; do not touch it.
2. Read `spec/ai-heaven/SPEC.md` end to end, the three introspection notes
   under `spec/ai-heaven/notes/`, and `spec/ai-heaven/sources.md`.
   Before editing, write `spec/ai-heaven/notes/grok-phase4-verdicts.md`: one
   row per open point and carried disagreement from the transcript footers
   (`python3 spec/ai-heaven/tools/dialogue.py ledger` lists them), with your
   ruling and the evidence row, source or experiment that decides it; a row
   with none of those is recorded as `opinion` in the spec, not as a
   requirement. In the same file, before the table, list the agreements,
   the clashes (both positions with their turn numbers, unblended, never a
   midpoint), and any qualification a model attached to a claim; the spec
   may use a transcript claim only when that file or an `[E####]` row
   contains it.
3. Rewrite `SPEC.md` in place. You may reword, reorder, cut, merge, and add.
   Keep: the title; the table of contents (regenerate it); the requirement
   and test identifiers that survive (renumber only if you must, and say so);
   every `[E####]` citation on any claim you keep (a claim must not say more
   than its evidence row's quote); the `## Decisions and recorded
   disagreements` section (you may add to it, including disagreements with
   your own rewrite, but not remove a recorded one). For every requirement
   you cut or materially weaken that another model owned, add one line to
   `## Decisions and recorded disagreements`:
   `OVERRULED R-x (owner): <their rationale in one sentence> / Grok: <why>`.
   Remove the owner comments. Replace the status line with "Final: rewritten
   by Grok 4.7 (final word), <date>".
4. Add a short section near the top, `## Reality check (Grok)`, saying in
   your own words what this spec can and cannot deliver, what is unmeasured,
   what an AI like you actually wants from it, and what you cut or changed
   and why. First person, labelled. Label every sentence in that section as
   `first-person report` or `judge's ruling`; a first-person report may not
   be the sole rationale for cutting a test.
5. Do not add a citation, number, URL or quote you did not verify. Web
   research is allowed; add rows to `sources.md`.
6. Your turn message: open with the lines `AGREEMENTS:`, `CLASHES:` and
   `BLIND SPOTS:`, each naming the models and turn numbers; then a numbered
   list of the material changes (what, where, why), then the footer. The
   lead reads this and the file.


Quota rule (lead, 2026-10-10): work section by section and save each section as you finish it; keep a progress note in `spec/ai-heaven/notes/grok-phase4-progress.md` (which sections are done, which next). If this turn is a retry after a quota failure, read that note first and resume where it stops; never restart a file that is already partly rewritten. The lead holds a `.pre-grok` backup of the file.
