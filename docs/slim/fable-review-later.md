# Work that could use a Fable review later

Started 2026-11-07, when the Fable credits ran out mid-Wave 5 (the lead fell back to Opus 5.5; workflow subagents failed with "out of usage credits"). Each item says what was done without Fable, by whom, and what a Fable review should check. The lead keeps this list updated until the final PR merges; strike an item (`~~…~~`) with the date and the reviewer when it is done.

## F1. Reviews and passes that ran without Fable

- **F1a. W3 docs critic, completeness pass** (run `wf_37bef6f2-767`, 2026-11-07): the final critic over README.md and AGENTS.md failed on credits and never ran. Re-run the critic stage alone (`docs/slim/briefs/wave5-E11-docs.md` section 6; the script is the W3 workflow's last agent): what replacement is not named where a new agent would look, which standing order contradicts a ruling.
- **F1b. W3 findings never verified** (57 of 161): the two skeptics per finding failed on credits for `docs/tui-lessons-learned.md` (25), `docs/paseo-only-rearchitecture.md` (16), `docs/threat-model.md` (13) and `docs/upstream-issues.md` (3). The list with each quote and proposed fix: `docs/slim/fable-review-later-w3-unverified.json`. Nothing was edited for these; a review decides which are real.
- **F1c. The 87 confirmed W3 fixes** were applied by the lead on Opus 5.5 (2026-11-07, commit named in F3), not reviewed after the edit (commit dd70d507, 21 files). A Fable read of the diff checks that no fix introduced a new false statement.

## F2. Security-critical work reviewed only by Opus (a cross-model second opinion is worth it)

- **F2a. `bin/review-launch`, `bin/review-pr`, `.github/workflows/adversary-marker.yml`, `bin/adversary_marker.py`** (E8): written and reviewed by Opus 5.5 (one repair round; the reviewer found the outside-author APPROVE hole). The external boundary (the operator's 2026-11-07 ruling: be pedantic about GitHub input) is the one place a same-family blind spot costs most. Check: the trusted-editor rule, the two-job workflow and its concurrency key, the tripwire's content-type allowlist, the self-check's cache key.
- **F2b. `bin/acp-dispatch` shim's frontier guards** (E6): the burst re-check under a lock, the estimate floor and per-wave cap port. Opus wrote and reviewed it.
- **F2c. `bin/route_agent.py` frontier gate on merged quota** (E7): the unknown-report rule ("an unknown Paseo report beside a fresh aiuse reading grants") is the lead's reading of the ruling; a Fable second opinion on whether it is right.

## F3. Lead work done on Opus after the fallback

- **F3a.** The W3 fixes (F1c, commit dd70d507).
- **F3b.** Wave 6: the final PR ([djbclark/djbclark-ade#297](https://github.com/djbclark/djbclark-ade/pull/297)) body and its merge-gate checklist, the fragment numbering, and `docs/slim/operator-batch.md` (compiled by Sonnet, not reviewed by Fable: its order inside each phase and its unverified commands are worth a second read).
- **F3c.** The `bin/review-pr` run on the final head that the PR's gate asks for will run on whatever model is available; a Fable run is the stronger cross-model review of an Opus-written branch.
