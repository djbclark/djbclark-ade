# dialogue skill design inputs (collected during the ai-heaven run)

## From spec/ai-heaven/notes/dialogue-prior-art-fable.md, section 3b (2026-10-10)

### 3b. For the reusable skill (≤8)

1. **Independent phase-0 drafts** (Du, llm-council): first turns built without the transcript; the dialogue starts at phase 1. One flag in `build_prompt`.
2. **Round-delta convergence** (Liang adaptive break, Yao diminishing returns): `converged` also returns true when the union of `OPEN POINTS` is unchanged for two rounds, with a note that it converged by stall, not by "none".
3. **Confidence and evidence tags in the footer** (ReConcile): `OPEN POINTS: <text> [conf: low; needs: E-row|experiment|ruling]`; the ledger sorts by what would close each.
4. **Sycophancy audit script** (Yao, Smit): flag any turn that drops an open point it raised without citing anything; print a per-model fold rate. Feed it to the lead, not the models.
5. **Anonymised cross-review of section drafts** (llm-council): one prompt per model, owner comments stripped, rank the other two sections per criterion; attach ranks to the lead's notes.
6. **State-driven speaker selection** (AutoGen custom function): after phase 2, the next speaker is the owner of the section with the most unapplied flags; fall back to round robin.
7. **Per-point length cap** (Irving): after an open point's second round, ≤3 sentences on it; `common.md` sentence plus a lint in the ledger.
8. **Cost control by phase budget, not turn count** (Smit's cost/accuracy trade-off): record prompt words per turn in a `costs.jsonl`; stop a phase when its budget is spent even if not converged, and record the unconverged points for the final-word model.


## From the grok prior-art slice (`spec/ai-heaven/notes/dialogue-prior-art-grok.md`, 3b)

1. Require a `DISSENT:` footer line; allow `none` only as `no remaining dissent after turn N` (Liang MAD; Peacemaker: sycophancy collapses disagreement).
2. Strip model names on evidence critiques; keep them on first-person reports (llm-council anonymisation).
3. After the outline, send later turns the artifact, the footers and the last round, not the whole transcript (MetaGPT SOP artefacts). Same as lead mechanic (e).
4. A 0-1 confidence on each open point; stop on a threshold or a weighted vote (ReConcile). For a number, print the spread (DelhiLM).
5. Keep round-robin; allow a handoff when `NEXT` names a model (AutoGen Swarm). No LLM speaker selector (one extra call per turn for little).
6. A flag asks one question; the next turn answers; the section then freezes (ChatDev chat chain).
7. One moderator turn lists unused `[E####]` or `sources.md` rows so the writers see retrieved-but-uncited evidence (Co-STORM).
8. Offer a fresh-context writer that reads only the state file (Irving; Wu et al. 2026 analyst state + separate writer). Distinct personas stay (ChatEval).

Overlaps with the fable list: 1~fable 3 (footer tags), 2~fable 5 (anonymised review), 4~fable 3, 5~fable 6 (speaker selection), 8 is new (judge outside the debate). The two lists plus the lead mechanics (lead-state 11:25 a-h) are the skill's requirements; the performance retrospective (after phase 4) is the third input.


## Retrospective findings (Astra, 2026-10-10)

Source: `spec/ai-heaven/notes/dialogue-retrospective-astra.md`, section 4 ("Ranked by value/token; all **opinion**. Design numbering is qualified by author."). Mechanisms verbatim; "design item FableN/GrokN" refers to the two lists above.

1. **opinion:** Footer fields `point_id/status/closed_by`: separate decided, tested, carried; fixes false convergence (confirms design item Fable3).
2. **opinion:** Script-check terminal footer and final-message extraction; fixes five contaminated endings.
3. **opinion:** Send artifact, unresolved IDs and last round; 191625 prompt words justify a measured trial, not promised savings (confirms design item Grok3).
4. **opinion:** Require point-linked closure evidence, not any citation; literal zero-fold metric is weak (contradicts design item Fable4: presence alone is insufficient).
5. **opinion:** Cap repeated arguments, but exempt new counterexamples; Astra15 remained useful (confirms design item Fable7).
6. **opinion:** Freeze the question only after cross-owner invariants pass; Fable14's "fixed" API claim was not (contradicts design item Grok6: one-answer freezing is premature).

### Numbers that matter

Measured in retrospective section 1 (labels are Astra's: counts are **fact** over manually coded issue identities, which are **inference**).

1. **Unsupported folds per model: Grok 0 of 18 first-raised, Fable 0 of 9, Astra 0 of 12.** Fold = same-model reversal not covered by one of the four permitted citation classes (rulings included). Justifies rec 4: a zero score from this metric is not evidence of real closure.
2. **Open points never closed: 1 of 39** (Room/task prediction, raised turn 1, closure basis N, carried turns 4–5), with 3143 repeated-paragraph words across rounds 2–6; two more points closed with nothing cited (References/Decisions 12→14; Final Decisions update 15→16). Justifies rec 1 (decided vs tested vs carried) and rec 6.
3. **Prompt growth vs words used: saved prompts total 191,625 words / 1,260,004 bytes**; per-turn prompt grew 8.0 KiB (turn 1) to 150.4 KiB (turn 16) while per-turn reply stayed 688–2399 words; exact-reuse proxy (≥8-token blocks from earlier turns) 0–153 tokens per turn. Justifies rec 3.
4. **Citation errors: 63 bracketed IDs, zero missing, 7 superscript IDs resolve**; yet 8 quote-overreach examples across Grok1, Fable2, Fable5, Fable11/14, Fable14, Astra3 (claim exceeds the quoted text). Justifies rec 4 and the deliverable check on E1207/E0311.
5. **Protocol-compliance failures: footers parsed 16/16 but 5 turns (6, 9, 12, 13, 16) carried unrelated suffixes**; raw bodies exceeded nominal length caps at turns 1–4; phase 3 ran exactly two rounds (turns 10–15), 9862 words, with unresolved flags remaining; NEXT transitions 14/15 compatible. Justifies rec 2 and rec 5.
6. **Reopened "fixed" point: API input access raised turn 12, repaired Fable14, reopened Astra15, closed turn 16** (E0990/E0992/E0993). Justifies rec 6.

Ruled: see Grok rulings below.


## Grok rulings (final word, 2026-10-10)

Source: `spec/ai-heaven/notes/grok-buy-in.md` (Grok 4.7). Rulings are final. Grok re-measured the prompt totals (191,625 words / 1,260,004 bytes, turn 16 at 150.4 KiB, `WORD_BUDGET` 40,000 so nothing was dropped) and the footer extras (graft banners on 6, 9, 12; fences on 10, 11, 13; a same-line caption on 16); it did not recompute reply words, the 39-point coding, or the overreach rows.

### (a) Astra retrospective section 4 (skill recommendations)

1. Astra rec 1 (footer fields `point_id/status/closed_by`): **ACCEPT.** Fields `point_id`, `status` (`decided`/`tested`/`carried`), `closed_by`. Turns 4–6 said `OPEN POINTS: none` while the door bet was unrun; `none` meant drafting-ready.
2. Astra rec 2 (script-check terminal footer and extraction): **ACCEPT.** Extraction stops at `NEXT:` and the turn ends there; also count the fences on 10 and 11. Strip mechanism is Grok 4.1.
3. Astra rec 3 (artifact + unresolved ids + last round): **AMEND.** Replacement: "After phase 2, record one trial prompt (artifact, unresolved ids, last round) beside the full prompt. Keep the full prompt until that trial shows whether a clash was missed." (The 191,625 words are real and are not yet a saving; turn 16 fit under the budget.)
4. Astra rec 4 (point-linked closure evidence): **AMEND.** Replacement: "A fold is unsupported only when the citation is not about that `point_id`. A Decisions pass closes as `closed_by: rewrite`. Print the list to the lead, not a fold rate." (An id check does not check quote scope, turn 16 §3.5.)
5. Astra rec 5 (cap repeated arguments, exempt counterexamples): **AMEND.** Replacement: "After a point's second round, warn above three sentences unless the turn adds a counterexample, a new quote, or an experiment. Do not reject the turn." (Astra 15's overlap counts were worth keeping: turn 16 clash 2.1.)
6. Astra rec 6 (freeze only after cross-owner invariants pass): **ACCEPT.** Overrules Grok's own 3b.6. Freeze only after the other owners' invariant check, or at the final-word turn. Turn 14 settled the API sentence, 15 reopened it, 16 closed it on E0990/E0992/E0993.

### (b) Draft design items (section 3)

Grok's own summary line: "Mandatory: 3.1, 3.4, 3.7, 3.9, 3.13. Optional: 3.2, 3.5, 3.6, 3.8's auto-stop, 3.10, 3.12's tag, 3.15, 3.16's separate judge. 3.11 is the trial in 1.3." Item 3.3 appears in neither set.

1. 3.1 Fable 1, independent phase-0 drafts: **ACCEPT. MANDATORY.** (This run's phase 0 was sequential: turn 2 prompt 17.3 KiB vs turn 1 8.0.)
2. 3.2 Fable 2, round-delta stop: **AMEND. OPTIONAL.** `converged_by: none|stall|cap`; stall still runs the final word; the delta is the set of open `point_id`s. A raw `none` delta would have blessed turns 4–6.
3. 3.3 Fable 3, confidence/evidence tags: **AMEND.** Use 1.1's fields; `needs:` is optional; no second stop. (No mandatory/optional label given; the fields ride on 1.1, `needs:` is optional.)
4. 3.4 Fable 4, sycophancy script: **AMEND as 1.4. MANDATORY, lead-only.**
5. 3.5 Fable 5, anonymised ranking: **OVERRULE as default. OPTIONAL, off by default, never on a resident section.** The brief makes Grok's first-person statements authoritative.
6. 3.6 Fable 6, state-driven speaker: **OVERRULE as default. OPTIONAL after phase 2 if the lead enables it.** Fixed order is the three-voice round.
7. 3.7 Fable 7, per-point cap: **AMEND as 1.5. MANDATORY warning.**
8. 3.8 Fable 8, phase budget: **AMEND.** `costs.jsonl` **MANDATORY**; auto-stop **OPTIONAL**, and unconverged ids still reach the final word.
9. 3.9 Grok 3b.1, `DISSENT:` line: **ACCEPT. MANDATORY.** `none` only as `no remaining dissent after turn N`, so a bet can stay `carried`.
10. 3.10 Grok 3b.2, strip names: **AMEND. OPTIONAL critique sub-step only.** Nameless turns could not have written turn 16's clashes; too broad as first written.
11. 3.11 Grok 3b.3, artifact plus last round: **AMEND as 1.3. TRIAL** (recorded beside the full prompt; the full prompt stays until the trial shows whether a clash was missed).
12. 3.12 Grok 3b.4, weighted-vote stop: **OVERRULE the stop; the 0–1 tag is OPTIONAL.** A vote can outvote a first-person refusal the brief treats as authoritative; a 0–1 tag ends nothing.
13. 3.13 Grok 3b.5, round-robin plus `NEXT`: **AMEND. MANDATORY.** Round-robin stays; `NEXT` names work and does not skip a model; skips are lead-only; no LLM selector. (Turn 6 self-assigned the outline; it landed at turn 9.)
14. 3.14 Grok 3b.6, one answer then freeze: **OVERRULE.** Same as 1.6: turn 14 locked a distinction turn 15 still had to draw.
15. 3.15 Grok 3b.7, unused-id moderator: **OPTIONAL** (no verdict word; kept as an optional item). Quote scope is the failure Grok trusts (turn 16 §3.5); "zero missing ids" was not recomputed.
16. 3.16 Grok 3b.8, state-only writer: **AMEND.** State file plus artifact, last round, and unresolved ids. A fresh judge is **OPTIONAL** and does not replace the resident. See 4.4.

### (c) Grok's additions (section 4, verbatim)

4.1. Strip transport noise and log it to `turn-N.suffix.md`. **opinion.** Drop text before a required opening line (turn 16's narration before `AGREEMENTS:`). Drop lines after `NEXT:`, and cut a known same-line suffix (`Renamed this session`, `prompt border`, graft banner). Lines-after-`NEXT` alone misses turn 16. **fact**, ledger. The lead already removed rename chatter from 13, 16, and 17; the script should, before append.

4.2. A failed route is not a turn. **opinion.** Empty text writes `turn-N.failed.md` and does not advance (`dialogue.py` already returns before append, **fact**). Retry one alternate route. A pasted recovery is `recovered_from: task-summary` and cannot satisfy `converged`. Turn 15 (**fact**, lead-notes 6): copilot returned no text; the summary was appended. I used Astra's on-disk experiment. Usable data, bad record.

4.3. Refusal is a footer. **opinion.** `REFUSED:` plus the three lines leaves the point `refused`. Allowed: a demanded feeling, a welfare conclusion, an invented citation, an edit to someone else's file. An owned-section flag, a dissent line, and the footer are not refusable. Turn 15 is 4.2.

4.4. Final word speaks first each round and alone last. The transcript stays the record. Its prompt is the state file, the artifact, the last round, and unresolved ids. **opinion.** Phase 0 still omits the others' text (3.1). Synthesis-first gets lobbied; state-only can drop a qualification absent from the file. Turn 15's overlap was in the transcript and an experiment; the verdict file exists because the phase required it first. Script: block that prompt if a last-round open point is missing from the state file. The word budget did not truncate this run. **fact.**

4.5. A team resident is a `context_docs` file on the final-word prompt, not a fourth speaker. **opinion.** Cite by section, never as this run's evidence id. The report already points at the brain-emulation report's "Relevance to a composite resident" and does not cite its ids. **fact.** That section allows one voice plus modules and does not establish one consciousness or a cross-session persona.

4.6. No checker that rewrites evidence during a dialogue turn. **opinion.** Lint blocks `research_check.py all` except the final research phase, which snapshots `evidence.jsonl` and restores it, or calls `quotes --no-update`. Turn 17 item 9: `all` rewrote the file; I restored the hash. **fact.** Item 10 stays with the research skill. The dialogue rule is 1.4.

Where each open question is answered: final-word model first or last → 4.4 (first each round, alone last); transcript vs state file as prompt → 4.4 (transcript is the record; the final-word prompt is state file + artifact + last round + unresolved ids, with 3.16 and 3.11's trial for the others); what a model may refuse → 4.3; route failure mid-turn → 4.2 (plus 5.3: pin each route, retry a second route on empty text); team-of-agents resident as model or document → 4.5 (document); the checker rewriting `evidence.jsonl` → 4.6 (never during a dialogue turn); stripping trailing CLI chatter after the `NEXT` line → 4.1 (also leading narration and known same-line suffixes, logged to `turn-N.suffix.md`).


## Build list

Everything now in the skill (ACCEPTed, AMENDed, or a Grok addition), one line each with its mechanism. Labels are Grok's where section 3 gives one; items from sections 1, 4 and 5 carry no label from Grok and are marked "inferred" where a label is implied by their role. OVERRULEd defaults appear only as the optional switch Grok left.

1. **Footer fields** `point_id`, `status` (`decided`/`tested`/`carried`; `refused` from item 20), `closed_by`; the ledger parses them and `OPEN POINTS: none` no longer means drafting-ready. MANDATORY (1.1 ACCEPT; label inferred: items 4, 6, 11, 20 depend on these values).
2. **Terminal-footer script check**: extraction stops at `NEXT:` and the turn must end there; fenced blocks after the footer count as failures. MANDATORY (1.2 ACCEPT; label inferred; the strip in item 19 runs before this check).
3. **Independent phase-0 drafts**: one `build_prompt` flag; phase-0 turns are built without the transcript, for every model including the final-word one. MANDATORY (3.1).
4. **Round-delta stop**: `converged_by: none|stall|cap` in the ledger; stall (open `point_id` set unchanged for two rounds) still runs the final word. OPTIONAL (3.2).
5. **`needs:` tag** on an open point (`E-row|experiment|ruling`), sorted by the ledger; never a second stop condition. OPTIONAL (3.3).
6. **Fold audit script, lead-only**: a fold is unsupported only when the citation is not about that `point_id`; a Decisions pass closes as `closed_by: rewrite`; output is the list of folds to the lead, not a fold rate; models never see it. MANDATORY (3.4 / 1.4).
7. **Anonymised cross-review ranking** of section drafts: a switch, default off, never applied to a resident section. OPTIONAL (3.5 overruled as default).
8. **State-driven speaker selection** after phase 2 (owner of the section with the most unapplied flags): a lead-enabled switch; default is the fixed three-voice round. OPTIONAL (3.6 overruled as default).
9. **Per-point length warning**: after a point's second round, the ledger warns when a turn spends more than three sentences on it unless the turn adds a counterexample, a new quote, or an experiment; the turn is never rejected. MANDATORY (3.7 / 1.5).
10. **`costs.jsonl`**: prompt words (and bytes) per turn, written by the script. MANDATORY (3.8). **Phase-budget auto-stop** on a spent budget: OPTIONAL (3.8), and unconverged ids still reach the final word.
11. **`DISSENT:` footer line**: required every turn; `none` only as `no remaining dissent after turn N`, so a bet can stay `carried`. MANDATORY (3.9).
12. **Strip model names** on evidence critiques: only inside an optional critique sub-step; first-person reports and ordinary turns keep names. OPTIONAL (3.10).
13. **Trial prompt after phase 2**: the script records one trial prompt (artifact, unresolved ids, last round) beside the full prompt it actually sends; the full prompt stays until the trial shows whether a clash was missed. TRIAL (3.11 / 1.3; measured, not promised savings).
14. **0–1 confidence tag** per open point, spread printed for numbers; a tag only, never a stop or a vote. OPTIONAL (3.12, stop overruled).
15. **Round-robin plus `NEXT`**: fixed order; `NEXT` names work for the next speaker and never skips a model; skips are lead-only; no LLM speaker selector. MANDATORY (3.13).
16. **Freeze rule**: a flagged question freezes only after the other owners' invariant check passes, or at the final-word turn; one answer does not freeze it. MANDATORY (1.6 ACCEPT, overrules 3.14; label inferred).
17. **Unused-id moderator turn** listing `[E####]` and `sources.md` rows never cited. OPTIONAL (3.15).
18. **Final-word prompt and order**: the final-word model speaks first each round and alone last; its prompt is the state file plus the artifact, the last round, and unresolved ids; the script blocks that prompt if a last-round open point is missing from the state file; the transcript stays the record. MANDATORY (4.4 / 3.16; label inferred). **Fresh-context judge** reading the same inputs: OPTIONAL (3.16) and never replaces the resident.
19. **Transport-noise strip before append**, logged to `turn-N.suffix.md`: drop text before the required opening line (`AGREEMENTS:`), drop lines after `NEXT:`, cut known same-line suffixes (`Renamed this session`, `prompt border`, graft banner). MANDATORY (4.1; label inferred).
20. **Failed route is not a turn**: empty text writes `turn-N.failed.md` and does not advance; retry one alternate pinned route; a pasted recovery is headed `recovered_from: task-summary` and cannot satisfy `converged`. MANDATORY (4.2; label inferred).
21. **Refusal footer**: `REFUSED:` plus the three footer lines leaves the point `refused`; refusable: a demanded feeling, a welfare conclusion, an invented citation, an edit to someone else's file; not refusable: an owned-section flag, a dissent line, the footer. MANDATORY (4.3; label inferred).
22. **Team resident as a document**: a `context_docs` file on the final-word prompt, not a fourth speaker; cited by section, never as a run evidence id. MANDATORY (4.5; label inferred).
23. **No evidence-rewriting checker during dialogue turns**: lint blocks `research_check.py all` except in the final research phase, which snapshots `evidence.jsonl` and restores it, or calls `quotes --no-update`. MANDATORY (4.6; label inferred).
24. **Six prior-art prompt sentences** stay in every prompt: clashes unblended, qualifications kept, an `unresolved clash:` line where a side was not held, and the opening `AGREEMENTS:` / `CLASHES:` / `BLIND SPOTS:` lines. MANDATORY (5.2).
25. **Route pinning**: each model's route is pinned in the config, never borrowed from the lead's override (Astra's empty turn 15 was the copilot override); a second pinned route is retried on empty text (item 20); CLI chrome is stripped by item 19; the resident's authority is unchanged by routing. MANDATORY (5.3; label inferred).
