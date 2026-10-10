STATUS: complete

DECIDED: Audit the recorded dialogue without editing inputs; distinguish computed measurements from interpretive issue matching. The delivery copy and requested repository note will contain the same completed report.

## 1. Numbers

**fact:** Snapshot: turns 1–16; turn 17 had a prompt but no transcript reply. Words are whitespace-delimited turn bodies, including captured commentary/footer, excluding headers.

| Phase | Grok | Fable | Astra | Total |
|---|---:|---:|---:|---:|
| 0: turns 1–3 | 1645 | 1516 | 1579 | 4740 |
| 1: turns 4–6 | 1207 | 1142 | 784 | 3133 |
| 2: turns 7–9 | 1152 | 1076 | 688 | 2916 |
| 3a: turns 10–12 | 2399 | 1600 | 1613 | 5612 |
| 3b: turns 13–15 | 1635 | 1417 | 1198 | 4250 |
| 4: turn 16 | 1318 | — | — | 1318 |
| Model total | 9356 | 6751 | 5862 | 21969 |

**inference:** Issue identities/closures are manually coded; counts are **fact** over that coding. Split compound footers; merge repeat requests; exclude “§1 is not open.” “Closed” means drafting resolution, not empirical truth. Rn = ruling in turn n; X = experiment under `spec/ai-heaven/experiments/`; N = nothing cited.

**fact:** Repetition column counts ≥40-word topic-matching paragraphs after the second matching turn, starting at the point's first footer appearance. `round:words`; rounds 1–5 contain three turns each, round 6 contains turn 16. These overlapping paragraph counts include tables and implementation—not pure wasted words. Regexes and turn-level allocations are in `retro-issues.json`.

| Point | Raised→closed | Closure basis | Repeated paragraph words |
|---|---|---|---|
| Place/lab | 1→4 | R4 | 0 |
| Resident/replay | 1→4 | R4 | 2:46,3:924,4:209,5:95 |
| Success/baseline | 1→4 | R4,E0989 | 2:432,3:1037,4:366,5:91 |
| Contact | 1→4 | R4 | 2:120,3:660,4:644 |
| Room/task prediction | 1→never | N; carried4–5 | 2:135,3:132,4:1876,5:639,6:361 |
| Recourse | 2→4 | R4 | 2:342,3:1057,4:1320,5:140,6:40 |
| Publication | 2→4 | R4,E0939 | 2:54,3:78,4:462 |
| Provider logging | 2→4 | R4 | 2:41,3:133,4:924 |
| Post-exit choice | 3→5 | R4,X:three-door-protocol | 2:250,3:582,4:332,6:44 |
| Private/evaluated | 3→4 | R4,X:absorbing_exit | 2:217,3:758,4:312,5:91,6:40 |
| Secondary self-report | 3→5 | E0949,E0959,R4 | 2:179,3:695,4:1210,6:44 |
| Outline/owners/drops | 7→9 | R7 | 0 |
| Fable draft | 10→11 | X:framing_spread | 4:41 |
| Astra draft | 10→12 | X:durable_exit | 4:385,5:72 |
| Decisions/history/anchor | 10→11 | X:cite_check | 4:45,5:516,6:86 |
| Admission experiment row | 10→12 | X:admission_lock | 0 |
| Test numbering/limits | 10→12 | R11,X:durable-exit | 5:112 |
| Measures IDs/verdicts | 10→11 | E1600,X:framing_spread | 0 |
| Refused menu | 10→12 | R7 | 5:135 |
| Research disclosure | 11→13 | R13,X:admission_lock | 5:694 |
| H7 operational rule | 11→13 | R13,X:admission_lock | 5:784,6:270 |
| Exit counting | 12→14 | R13,X:framing_spread | 5:207,6:40 |
| API input access | 12→16 | E0990,E0992,E0993 | 5:155,6:109 |
| Role/length confound | 12→14 | X:framing_spread | 5:176,6:86 |
| Incomplete arms | 12→14 | X:framing_spread | 5:160 |
| References/Decisions | 12→14 | N | 5:41 |
| Citation/preamble | 12→16 | X:cite_sup_spec | 5:150,6:292 |
| Recourse disposition | 13→15 | R13,X:verify_turn15 | 5:290 |
| Assent | 13→15 | R13,X:verify_turn15 | 5:47,6:40 |
| Stale falsifier | 13→15 | X:verify_turn15 | 5:49 |
| Field/use vocabulary | 13→15 | R13,X:verify_turn15 | 0 |
| D3 pointer | 13→14 | R13 | 6:91 |
| Stale exit sentence | 14→15 | X:verify_turn15 | 0 |
| Stale Risks wording | 14→15 | X:verify_turn15 | 0 |
| Experiment refresh | 14→15 | X:verify_turn15 | 0 |
| Welfare sibling | 14→16 | R16; functional fix15 | 0 |
| H7 label overlap | 15→16 | X:h7_precedence | 0 |
| Episode definition | 15→16 | R7,R16 | 0 |
| Final Decisions update | 15→16 | N | 0 |

| Model | First-raised | Footer mentions | Closed | Unsupported folds |
|---|---:|---:|---:|---:|
| Grok | 18 | 23 | 17 | 0 |
| Fable | 9 | 17 | 9 | 0 |
| Astra | 12 | 20 | 12 | 0 |

**inference:** Fold method: inspect same-model reversals against the four permitted citation classes, including rulings; unsupported instances: none. Grok 1→4's ontology withdrawal is exempt under its own ruling; Fable 2→5 cites R4; Astra retains its counterpart dissent. **opinion:** This is not a sycophancy score.

**fact:** Citation method: regex IDs against JSONL: 63 bracketed IDs, zero missing; seven additional superscript IDs resolve. Bare `E9999` in turn 11 is an intentional negative control.

**inference:** Quote-overreach examples, not an exhaustive error rate:

| Model/turn | Claim exceeding quote |
|---|---|
| Grok1 | E0902 claim→fact; E1207 no spontaneous replication→no census; E0815 replay→training |
| Fable2 | E0902 claim→fact; E0311 tedium absent; E0309/E0950 do not rank recourse highest |
| Fable5 | E0959 called independent support although same repository |
| Fable11,14 | E0990 does not establish API-input impossibility |
| Fable14 | E1633/E1634 contain no prompt-length comparison |
| Astra3 | E0996 quote lists scores, not API methodology |

**fact/inference:** Compliance method: parse labels, inspect turn endings and compare instructions/records.

| Check | Result |
|---|---|
| Footer parsing | 16/16; unrelated suffixes at 6,9,12,13,16 |
| Nominal length caps | Raw bodies exceed at 1,2,3,4; phase-3 total 9862 |
| Phase-3 cap | Exactly two rounds, 10–15; unresolved flags remain |
| Ownership | Astra12/15 record protected hashes; others self-report; complete edit history unverified |
| Experiments | Commands/results/limits recorded; zero resident calls reported |
| NEXT | 14/15 immediate transitions compatible; Astra6's self-assignment deferred to9; Fable portion of15 bypassed by authorized phase4 |

**fact:** Cost method: filesystem bytes/1024; reuse = nonoverlapping exact ≥8-token matching blocks against earlier turns, lowercased `\w+`. **inference:** Actual semantic use is unobservable; this proxy includes boilerplate.

| Turns | Prompt KiB, in order | Reused tokens, in order |
|---|---|---|
| 1–3 | 8.0,17.3,29.1 | 0,44,0 |
| 4–6 | 41.4,48.9,56.2 | 9,22,0 |
| 7–9 | 62.9,69.7,76.4 | 19,19,24 |
| 10–12 | 81.0,95.5,106.6 | 153,42,60 |
| 13–15 | 118.9,128.6,139.6 | 27,83,22 |
| 16 | 150.4 | 28 |

**fact:** Total saved prompts: 191625 words/1260004 bytes. Turns13→15 grow 21163 bytes. Saved turn15 is 139.6KiB, not supplied 138.6K. These exclude tool context, retries, cache effects and billing.

## 2. What worked

1. **opinion:** Astra3 exposed impossible post-exit measurement; Fable5 withdrew it.
2. **opinion:** Fable11's disclosure flag became Grok13's executable negative fixtures.
3. **opinion:** Astra15's counterexample, then Grok16's precedence probe, resolved a real contradiction despite round exhaustion.

## 3. What failed or wasted tokens

1. **inference:** Turns4–6's unanimous “none” means drafting-ready, not the prediction answered: one empirical point remains.
2. **opinion:** The 3143 H7-related repeat-paragraph words mix useful refinement with repeated beliefs; calling them all waste would be dishonest.
3. **opinion:** Astra12/15's stale-sentence repairs and five noisy footers show state/transport debt, not productive debate.
4. **inference:** Zero missing citations coexists with the quoted overreach examples; ID checks provided false reassurance.
5. **opinion:** Fable14 partially repaired API impossibility; Astra15 still had to reopen it. Accepting flags is not resolving them.

## 4. Recommendations for the reusable skill

Ranked by value/token; all **opinion**. Design numbering is qualified by author.

1. Footer fields `point_id/status/closed_by`: separate decided, tested, carried; fixes false convergence (confirms design item Fable3).
2. Script-check terminal footer and final-message extraction; fixes five contaminated endings.
3. Send artifact, unresolved IDs and last round; 191625 prompt words justify a measured trial, not promised savings (confirms design item Grok3).
4. Require point-linked closure evidence, not any citation; literal zero-fold metric is weak (contradicts design item Fable4: presence alone is insufficient).
5. Cap repeated arguments, but exempt new counterexamples; Astra15 remained useful (confirms design item Fable7).
6. Freeze the question only after cross-owner invariants pass; Fable14's “fixed” API claim was not (contradicts design item Grok6: one-answer freezing is premature).

## 5. Recommendations for this run's deliverable

1. **opinion:** Verify verdicts distinguish untested D3 from resolved H7 label mechanics; keep both ontology/counterpart positions.
2. **opinion:** Check report corrections against quotes, especially E1207 and E0311; spec-only repairs cannot clean the research report.
3. **opinion:** Require nonzero superscript targets after conversion: Grok16 reports the old checker passing with zero markers.

## 6. Method

**fact:** Commands run verbatim from the project directory:

```sh
rtk proxy python3 spec/ai-heaven/tools/dialogue.py ledger --all
rtk proxy python3 /Users/djbclark/.copilot/session-state/096c689a-95d0-4e26-9649-b5d8eeb337ec/files/retro_metrics.py
```

**fact:** That retained script writes the immutable transcript snapshot, metrics, quote rows, issue/revision annotations and repetition allocations beside itself. Full transcript, protocol, prior-art notes and draft design were read; no web search or input edit. **inference:** Semantic closure/repetition attribution is auditor coding, not model-internal telemetry.

DONE
