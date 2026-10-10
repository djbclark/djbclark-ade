# Prior art for the dialogue skill (two slices, concatenated)

Both notes were written during the hiwymi ai-heaven run on 2026-10-10 and are copied unchanged below.

1. Grok slice, source: `techno-euphora/projects/hiwymi/spec/ai-heaven/notes/dialogue-prior-art-grok.md`
2. Fable slice, source: `techno-euphora/projects/hiwymi/spec/ai-heaven/notes/dialogue-prior-art-fable.md`

---

<!-- source: spec/ai-heaven/notes/dialogue-prior-art-grok.md -->

# Dialogue prior art (grok slice)

`dialogue.py` runs Grok, Fable, Astra in order; stacks rules, persona, phase, lead notes, and the transcript; and stops on every last `OPEN POINTS: none`. Phase 4 is Grok alone. No fetched page described diff-based editing.

## 1. Catalogue

| # | name | kind | year | turn protocol | convergence rule | judge or final-word role | URL |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1.1 | Du et al. | paper | 2023 | debate rounds | shared answer | model combines | https://arxiv.org/abs/2305.14325 |
| 1.2 | Liang MAD | paper | 2023 | tit-for-tat | judge's solution | judge | https://arxiv.org/abs/2305.19118 |
| 1.3 | Irving et al. | paper | 2018 | capped short statements | the cap | outside human | https://arxiv.org/abs/1805.00899 |
| 1.4 | ReConcile | paper | 2023 | round table | weighted vote | the vote | https://arxiv.org/abs/2309.13007 |
| 1.5 | ChatEval | paper | 2024 | distinct personas | unstated | referees | https://proceedings.iclr.cc/paper_files/paper/2024/hash/25cc3adf8c85f7c70989cb8a97a691a7-Abstract-Conference.html |
| 1.6 | Wu et al. | paper | 2026 | two synthesis calls | no further debate | writer sees a state | https://arxiv.org/abs/2604.02923 |
| 1.7 | Karpathy council | tool | undated | anonymous rank | one pass | chairman | https://github.com/karpathy/llm-council/blob/master/README.md |
| 1.8 | okjpg council | tool, fringe | undated | five personas | chairman verdict | lists clashes | https://github.com/okjpg/llm-council |
| 1.9 | AutoGen | tool | undated 0.2 | round-robin or LLM pick | until stop | none | https://microsoft.github.io/autogen/0.2/docs/tutorial/conversation-patterns |
| 1.10 | MetaGPT | paper | 2023 | SOP artifacts | phase order | none | https://arxiv.org/abs/2308.00352 |
| 1.11 | ChatDev | paper | 2023 | chat chain | unstated | none | https://arxiv.org/abs/2307.07924 |
| 1.12 | STORM | paper | 2024 | perspective Q&A | outline ends it | writer | https://aclanthology.org/2024.naacl-long.347/ |
| 1.13 | DelhiLM | tool | undated | Delphi numbers | until consensus | weighted mean | https://github.com/YuzeHao2023/DelhiLM |
| 1.14 | Peacemaker | paper | 2026 | debaters plus judge | collapse metric | judge included | https://openreview.net/forum?id=RlSA7cEUqc |
| 1.15 | AutoGen Swarm | tool | undated | handoff message | until stop | none | https://microsoft.github.io/autogen/dev/user-guide/agentchat-user-guide/swarm.html |
| 1.16 | Co-STORM | tool | 2024 | moderator questions | discourse continues | moderator asks | https://github.com/stanford-oval/storm |

1.1 "In this paper, we present a complementary approach to improve language responses where multiple language model instances propose and debate their individual responses and reasoning processes over multiple rounds to arrive at a common final answer."

1.2 "To address the DoT problem, we propose a Multi-Agent Debate (MAD) framework, in which multiple agents express their arguments in the state of "tit for tat" and a judge manages the debate process to obtain a final solution."

1.3 "Given a question or proposed action, two agents take turns making short statements up to a limit, then a human judges which of the agents gave the most true, useful information."

1.4 "ReConcile enhances collaborative reasoning between LLM agents via multiple rounds of discussion, learning to convince other agents to improve their answers, and employing a confidence-weighted voting mechanism that leads to a better consensus."

1.5 "Furthermore, we find that the diverse role prompts (different personas) are essential in the multi-agent debate process; that is, utilizing the same role description in the prompts can lead to a degradation in performance."

1.6 "We present an inspectable LLM Council with two synthesis stages: an analyst organizes three independent candidate answers into a structured textual state, and a separately invoked writer composes the final response from the question and that state."

1.7 "Under the hood, the LLM identities are anonymized so that the LLM can't play favorites when judging their outputs."

1.8 "A chairman produces the final verdict with agreements, clashes, blind spots, and a clear recommendation."

1.9 "We support several strategies to select the next agent: round_robin , random , manual (human selection), and auto (Default, using an LLM to decide)."

1.10 "MetaGPT encodes Standardized Operating Procedures (SOPs) into prompt sequences for more streamlined workflows, thus allowing agents with human-like domain expertise to verify intermediate results and reduce errors."

1.11 "In this paper, we introduce ChatDev, a chat-powered software development framework in which specialized agents driven by large language models (LLMs) are guided in what to communicate (via chat chain) and how to communicate (via communicative dehallucination)."

1.12 "We propose STORM, a writing system for the Synthesis of Topic Outlines through Retrieval and Multi-perspective Question Asking."

1.13 "This repository implements a Delphi pipeline, designed to aggregate expert opinions through iterative rounds of elicitation, leveraging large language models (LLMs)."

1.14 "Our findings reveal that sycophancy consistently correlates with disagreement collapse and performance degradation in multi-agent debates, and controlling debaters' sycophancy as a tunable parameter produces measurable gains."

1.15 Swarm, https://microsoft.github.io/autogen/dev/user-guide/agentchat-user-guide/swarm.html : "Different from the other two group chat teams, at each turn, the speaker agent is selected based on the most recent HandoffMessage message in the context."

1.16 Co-STORM, https://github.com/stanford-oval/storm : "This agent generates thought-provoking questions inspired by information discovered by the retriever but not directly used in previous turns."

## 2. What they do that dialogue.py does not

2.1 Analyst state, then a separate writer (1.6). One scratch file in Grok's turn.

2.2 Chairman lines: agreements, clashes, blind spots (1.8, fringe).

2.3 Anonymized ranking on evidence turns (1.7). Keep names on first-person reports.

2.4 Confidence plus a weighted vote (1.4). Footer change.

2.5 Sycophancy collapses disagreement (1.14). Today's stop is self-reported `none`.

2.6 The judge stands outside the debate (1.3). Use a fresh context; this run still gives Grok the pen.

2.7 Later turns read an SOP artifact (1.10), which spends less than a full replay.

2.8 One clarifying question, then the section freezes (1.11).

2.9 Ask about sources already retrieved and unused (1.16).

2.10 Handoff names the next speaker (1.15). An LLM picker (1.9) is another call each turn.

2.11 Re-ask numbers and average by dispersion (1.13).

## 3. Recommendations

### 3a. For phase 4 now

3a.1 In `spec/ai-heaven/tools/phases/4-grok-spec.md`, at the end of item 2, add: "Before rewriting, write `spec/ai-heaven/notes/grok-phase4-state.md` containing only agreements, clashes (both positions and turn numbers, unblended), and qualifications attached to claims, and let `SPEC.md` use a transcript claim only when that state or an `[E####]` row contains it." Source 1.6. Highest value per token.

3a.2 Same file, end of item 6, add: "Open the turn with the lines `AGREEMENTS:`, `CLASHES:`, and `BLIND SPOTS:`, each naming models and turns, and then give the numbered changes." Source 1.8.

3a.3 In `spec/ai-heaven/tools/phases/4-grok-report.md`, end of item 1 under "What to do with the freedom you have", add: "Add an `unresolved clash:` line for every transcript disagreement you did not keep on both sides, with the turn numbers, and do not rewrite an `[E####]` claim into a midpoint its evidence quote does not state." Source 1.6.

### 3b. For the reusable skill

3b.1 Require `DISSENT:`, and allow `none` only as `no remaining dissent after turn N` (1.2, 1.14).

3b.2 Strip names on evidence critiques; keep them on first-person reports (1.7).

3b.3 After the outline, send the artifact, the footers, and the last round (1.10).

3b.4 Put a 0–1 confidence on each open point and stop on a threshold or a weighted vote (1.4). For a number, print the spread (1.13).

3b.5 Keep round-robin; allow handoff when `NEXT` names a model (Swarm). Skip an LLM selector (1.9).

3b.6 A flag asks one question; the next turn answers; the section then freezes (1.11).

3b.7 One moderator turn lists unused `[E####]` or `sources.md` rows (Co-STORM).

3b.8 Offer a fresh writer that reads only the state file (1.3, 1.6). This run keeps Grok as writer; 3a.1 still applies. Distinct personas stay (1.5).

## 4. Search log

Engine for 4.1–4.7: `web_search` (batch size, not an index total). Date 2026-10-10. Seven searches and seven opens.

4.1 `Du "Improving Factuality and Reasoning" multiagent debate 2023 arxiv Liang MAD "Encouraging Divergent Thinking" Irving "AI safety via debate"` — 8 returned.

4.2 `ReConcile round-table LLM ChatEval multi-agent debate Exchange-of-Thought Mixture-of-Agents Wang 2024 arxiv` — 8 returned.

4.3 `Karpathy llm-council github chairman anonymous peer ranking README` — 5 returned.

4.4 `AutoGen GroupChat speaker selection round_robin CAMEL MetaGPT SOP ChatDev chat chain CrewAI OpenAI Swarm handoffs` — 8 returned.

4.5 `STORM multi-agent Wikipedia article writing LLM Delphi method large language models collaborative document critic author` — 8 returned.

4.6 `multi-agent debate sycophancy agreement collapse judge termination "LLM council" Claude GPT Grok document 2025 2026` — 8 returned.

4.7 `"Delphi method" LLM OR "large language models" consensus rounds CAMEL "role-playing" arxiv ChatDev MetaGPT CrewAI hierarchical process OpenAI Swarm handoff README` — 6 returned.

4.8 https://arxiv.org/abs/2406.04692 opened, unrowed (MoA). 4.9 https://arxiv.org/abs/2312.01823 failed (Exchange-of-Thought). 4.10–4.12 and 4.14 opened (1.3, 1.10, 1.11, 1.6). 4.13 https://arxiv.org/abs/2303.17760 failed; 4.7 rendered the CAMEL abs, unrowed. Fringe row: 1.8. Search renderings supply 1.1, 1.2, 1.4, 1.5, 1.7–1.9, 1.13–1.16.


---

<!-- source: spec/ai-heaven/notes/dialogue-prior-art-fable.md -->

# Prior art for the three-model spec dialogue (fable slice, 2026-10-10)

Scope: tools, papers and write-ups where several LLMs take turns on one shared
document or decision, read against `tools/dialogue.py` (fixed order Grok,
Fable, Astra; footer `SETTLED/OPEN POINTS/NEXT`; `converged` = every model's
last footer says `OPEN POINTS: none`; phase 3 capped at 2 rounds; Grok's
phase-4 final word). Every row below was opened (arXiv abstract page or the
cited URL); one verbatim sentence each. Search budget: 14 calls, log at the end.

## 1. Catalogue

| name | kind | year | turn protocol | convergence rule | judge / final word | URL |
|---|---|---|---|---|---|---|
| Du et al., Multiagent Debate | paper | 2023 | N instances answer, then each sees the others' answers and revises, fixed rounds | fixed round count, then majority of final answers | none (majority) | https://arxiv.org/abs/2305.14325 |
| Liang et al., MAD (tit-for-tat) | paper | 2023 | two debaters alternate, a judge watches each round | "adaptive break": judge ends the debate when it can extract an answer | judge model, final solution | https://arxiv.org/abs/2305.19118 |
| Irving, Christiano, Amodei, AI safety via debate | paper | 2018 | two agents alternate short statements up to a limit | statement limit | human judge picks the more true/useful side | https://arxiv.org/abs/1805.00899 |
| ReConcile | paper | 2023 | round table of different vendors' models; each round's prompt = grouped answers + explanations + confidence scores | confidence-weighted vote once answers agree or rounds run out | none; weighted vote | https://arxiv.org/abs/2309.13007 |
| Mixture-of-Agents | paper | 2024 | layered: every agent in layer k reads all layer k-1 outputs | fixed depth | aggregator model in the last layer | https://arxiv.org/abs/2406.04692 |
| Smit et al., Should we be going MAD? | paper | 2023 | benchmark of debate protocols | tuned "agreement level" prompts | varies | https://arxiv.org/abs/2311.17371 |
| Yao et al., Peacemaker or Troublemaker | paper | 2025 | centralized (judge) and decentralized debate, sycophancy varied per role | diminishing-returns stop recommended | judge sycophancy measured separately | https://arxiv.org/abs/2509.23055 |
| MetaGPT | paper | 2023 | assembly line: roles hand structured artefacts (PRD, design, code) downstream | SOP completes | none; each role verifies the previous | https://arxiv.org/abs/2308.00352 |
| Karpathy, llm-council | tool | 2025 | 1 first opinions, 2 anonymised peer ranking, 3 chairman synthesis | one pass | chairman model compiles all responses | https://github.com/karpathy/llm-council |
| AutoGen GroupChat speaker selection | tool/doc | 2024 | `auto`, `manual`, `random`, `round_robin`, or a custom function of (last speaker, chat) | custom function returns `None` to end; `max_round` cap | none built in | https://microsoft.github.io/autogen/0.2/docs/topics/groupchat/customized_speaker_selection |
| Reddit: "let ChatGPT, Claude and Gemini debate each other" (fringe, not opened) | post | 2026 | three vendors debate in a web app | unknown | unknown | https://www.reddit.com/r/ArtificialInteligence/comments/1tayk5m/ |

Quotes (one per opened page):

1. Du et al.: "multiple language model instances propose and debate their individual responses and reasoning processes over multiple rounds to arrive at a common final answer."
2. Liang et al.: "the adaptive break of debate and the modest level of 'tit for tat' state are required for MAD to obtain good performance. Moreover, we find that LLMs might not be a fair judge if different LLMs are used for agents."
3. Irving et al.: "two agents take turns making short statements up to a limit, then a human judges which of the agents gave the most true, useful information."
4. ReConcile: "a 'discussion prompt' that consists of (a) grouped answers and explanations generated by each agent in the previous round, (b) their confidence scores, and (c) demonstrations of answer-rectifying human explanations".
5. MoA: "Each agent takes all the outputs from agents in the previous layer as auxiliary information in generating its response."
6. Smit et al.: "MAD protocols might not be inherently worse than other approaches, but that they are more sensitive to different hyperparameter settings and difficult to optimize."
7. Yao et al.: "sycophancy is a core failure mode that amplifies disagreement collapse before reaching a correct conclusion in multi-agent debates, yields lower accuracy than single-agent baselines, and arises from distinct debater-driven and judge-driven failure modes."
8. MetaGPT: "MetaGPT encodes Standardized Operating Procedures (SOPs) into prompt sequences for more streamlined workflows, thus allowing agents with human-like domain expertise to verify intermediate results and reduce errors."
9. llm-council README: "the LLM identities are anonymized so that the LLM can't play favorites when judging their outputs."
10. AutoGen: "In GroupChat, we can customize the speaker selection by passing a function to the GroupChat object."
11. Reddit post: not opened (both fetch routes refuse reddit.com); the search excerpt reads "Built a platform where Claude, ChatGPT, and Gemini debate each ..." Fringe; keep as a lead, do not cite.

Seen in search excerpts only, not opened (leads for the grok slice): LLM-based Delphi study (arXiv 2502.21092: stops "after a defined sets of rounds", not on consensus); "Isolated Self-Correction Prevails Over Unguided Homogeneous Multi-Agent Debate" (ACM, 2025: "inter-agent sycophancy can trigger premature, incorrect consensus"); Courtroom-style MAD (arXiv 2603.28488: early stop when score change < 0.05); CONSENSAGENT (sycophancy-mitigated consensus).

## 2. What they do that dialogue.py does not

1. **Anonymised peer ranking before synthesis** (llm-council stage 2). Our models know who said what, and the brief makes Grok authoritative, so identity bias is built in by design; but a one-off anonymised ranking of the three phase-3 drafts would show whether the deference is earned. Cheap: one extra prompt per model, labels stripped.
2. **Confidence attached to every position** (ReConcile). Our footers carry `OPEN POINTS` lines with no confidence; `converged` cannot tell a firm "none" from a tired one. Cheap: add `confidence: high|medium|low` per open point in the footer regex.
3. **Judge-driven adaptive break** (Liang MAD; Yao's diminishing-returns stop; courtroom early stop). We stop only on unanimous "none" or a hard cap; nobody measures whether the last round changed anything. Cheap: diff the `OPEN POINTS` set between rounds and stop when it is unchanged twice.
4. **Agreement-level as a tuned prompt parameter** (Smit et al.). Our personas do not say how readily to concede. Cheap: one sentence in `common.md` ("concede only to a cited row or an experiment; otherwise record the disagreement").
5. **Sycophancy measured per role, judge included** (Yao et al.). We have no metric for "folded without evidence"; the final-word model's own sycophancy toward the loudest transcript voice is unmeasured. Moderate: a script that flags a position reversed with no `[E####]`, source row or experiment in the reversing turn.
6. **Fresh independent first opinions** (Du; llm-council stage 1). Our phase 0 is sequential: Fable reads Grok before writing, Astra reads both (Turn 2 admits the convergence is "weak evidence" for this reason). Cheap next run: build phase-0 prompts with the transcript omitted.
7. **Speaker selection as a function of state** (AutoGen). Ours is fixed order. Moderate: `--only` already exists; a rule like "next speaker = owner of the most-flagged section" is a few lines.
8. **Structured hand-offs instead of prose** (MetaGPT SOPs). Phase 3 approaches this with `R-`/`T-` ids; phase 1 chat does not. Cheap: a required `DISAGREE n:` label so the ledger can count carried disagreements.
9. **Layered aggregation with a named aggregator** (MoA). Phase 4 is this with one layer; MoA's lesson is that the aggregator must receive all drafts, not a summary. Already true (Grok reads the files), but see 3a.
10. **Statement length limit as the convergence lever** (Irving). We cap words per turn but not per open point; a point can be re-argued at full length every round. Cheap: "each open point gets ≤3 sentences after its second appearance."

## 3. Recommendations

### 3a. For phase 4 now (≤3, ranked by value per token)

1. **Make Grok list the dissents it overrules.** Yao et al. show judge-driven collapse is a distinct failure; llm-council's chairman compiles without a dissent record. Add to `4-grok-spec.md` item 3, after "not remove a recorded one": *"For every requirement you cut or materially weaken that another model owned, add one line to `## Decisions and recorded disagreements`: `OVERRULED R-x (owner): <their rationale in one sentence> / Grok: <why>`."* Same sentence in `4-grok-report.md` item 2 for cut claims.
2. **Require a pre-rewrite verdict table.** Liang's judge "extracts" before deciding; ReConcile groups answers before voting. Add to `4-grok-spec.md` after item 2: *"Before editing, write `notes/grok-phase4-verdicts.md`: one row per open point and carried disagreement from the transcript footers (`dialogue.py ledger --all`), with your ruling and the evidence row, source or experiment that decides it; a row with none of those is recorded as `opinion` in the spec, not as a requirement."*
3. **Separate the resident voice from the judge voice.** Liang: "LLMs might not be a fair judge if different LLMs are used for agents"; here the judge is also the authoritative first-person witness. Add to item 4 of `4-grok-spec.md`: *"Label every sentence in `## Reality check (Grok)` as `first-person report` or `judge's ruling`; a first-person report may not be the sole rationale for cutting a test."*

### 3b. For the reusable skill (≤8)

1. **Independent phase-0 drafts** (Du, llm-council): first turns built without the transcript; the dialogue starts at phase 1. One flag in `build_prompt`.
2. **Round-delta convergence** (Liang adaptive break, Yao diminishing returns): `converged` also returns true when the union of `OPEN POINTS` is unchanged for two rounds, with a note that it converged by stall, not by "none".
3. **Confidence and evidence tags in the footer** (ReConcile): `OPEN POINTS: <text> [conf: low; needs: E-row|experiment|ruling]`; the ledger sorts by what would close each.
4. **Sycophancy audit script** (Yao, Smit): flag any turn that drops an open point it raised without citing anything; print a per-model fold rate. Feed it to the lead, not the models.
5. **Anonymised cross-review of section drafts** (llm-council): one prompt per model, owner comments stripped, rank the other two sections per criterion; attach ranks to the lead's notes.
6. **State-driven speaker selection** (AutoGen custom function): after phase 2, the next speaker is the owner of the section with the most unapplied flags; fall back to round robin.
7. **Per-point length cap** (Irving): after an open point's second round, ≤3 sentences on it; `common.md` sentence plus a lint in the ledger.
8. **Cost control by phase budget, not turn count** (Smit's cost/accuracy trade-off): record prompt words per turn in a `costs.jsonl`; stop a phase when its budget is spent even if not converged, and record the unconverged points for the final-word model.

## 4. Search log (2026-10-10, engine in brackets)

1. `Delphi method LLM agents consensus iterative rounds paper` [Firecrawl web] — 6 hits.
2. `blog Claude GPT Grok debate each other write one document together round-robin` [Firecrawl web] — 8 hits (reddit, LinkedIn, facebook, vendor comparisons; one usable fringe lead).
3. `multi-agent debate LLM convergence termination sycophancy "agreement" early stopping judge` [Firecrawl web] — 6 hits.
4. Opened by id [arXiv abstract API]: 2305.14325, 2305.19118, 1805.00899, 2309.13007, 2406.04692, 2509.23055, 2311.17371, 2308.00352 — 8 calls.
5. Opened [WebFetch]: github.com/karpathy/llm-council; microsoft.github.io AutoGen customized_speaker_selection — 2 calls.
6. Failed [WebFetch, then Firecrawl scrape]: reddit.com/r/ArtificialInteligence/comments/1tayk5m — both routes refuse reddit.com; the retry put the slice at 15 calls, one over the cap.

Not opened for budget: ChatEval, Exchange-of-Thought, CAMEL, ChatDev, CrewAI, OpenAI Swarm, Khan et al. "Debating with more persuasive LLMs"; the grok slice should take these.
