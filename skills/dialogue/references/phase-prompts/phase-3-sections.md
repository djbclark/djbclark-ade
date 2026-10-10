<!-- ai-heaven instance (hiwymi spec/ai-heaven/tools/phases/3-sections.md, 2026-10-09/10): an example, not a template to copy verbatim. -->

Phase 3: write and review the sections.

1. Open `spec/ai-heaven/SPEC.md`. Write, or revise, every section whose
   `<!-- owner: you -->` comment names you. Edit the file directly; keep the
   heading and the owner comment; replace the scope note with the real text.
   Do not edit a section you do not own; put review comments in your turn
   instead.
2. Requirements get an identifier (`R-<section>-<n>`), a statement, a
   rationale (cite `[E####]`, a `sources.md` row, a transcript turn, or a
   first-person report by name), and a test or metric (or "untestable:
   <why>, proxy: <what>"). Tests get an identifier (`T-<n>`), setup,
   procedure, observable, pass/fail or reported metric, and what a failing
   result would mean.
3. Experiments: if a section needs one, run it under
   `experiments/<you>/`, label it tested (with the command you ran and the
   output) or sketch, and summarise the result in your section; Astra copies
   the summary line into `## Experiments`.
4. Fable keeps `## Decisions and recorded disagreements` current from the
   transcript footers.
5. Then review the other two owners' sections as they stand: numbered,
   specific flags ("3.2 R-mem-4 has no test"), each with a proposed fix.
   Testability, honesty of labels, generic-heaven framing, Grok-deference on
   resident wants.
6. Apply flags against your sections from previous turns before writing new
   text; say which you applied and which you declined, with a reason.
7. Section-writing turns may be long; the review part stays under ~800 words.
   End with the footer; `OPEN POINTS: none` means your sections are done and
   you have no unaddressed flags on others' sections.
