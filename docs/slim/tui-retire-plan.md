# tui-retire plan (2026-11-04)

Source of truth for which TUIs: PR 283 docs/tui-consolidation.md (branch docs/tui-consolidation,
worktree ~/src/djbclark-ade-tui-consolidation-wt), section D: fold zcode, copilot (CLI) into opencode;
retire crush, venicecode, qwen, goose, aider, kiro-cli, devin; dsh not adopted; muse (H5 open, flagged).
Keep: claude, codex, agy, cursor-agent, grok, omp, pi, opencode, hermes, cline.

Wave 1 (read-only research): R1 pi/omp herdr tab + pi Paseo agent; R2 omp billing fix (aiuse
fix/omp-promo-credits-only); R3 inventory of every retiring-TUI mention (djbclark-ade, aiuse, referenced
repos); R4 lessons from the retiring TUIs (docs, memory, failure tables) + the venice/dsh cursor herdr tabs.
Wave 2: lessons-learned doc (docs/tui-lessons-learned.md) PR; billing fix PR (aiuse); pi->omp ports.
Wave 3: G1 registry/docs; G2 trials (GLM + SIPB via opencode); G3 re-point; removal slices by file.
Wave 4: final sweep: rg for every retiring name; only the lessons doc, CHANGELOG/handoffs (logs) remain.
Machine-side uninstall (G4) = operator action list, not done without djbclark's yes.

## Billing (H7), from aiuse agent 23adbb25 (2026-11-04 13:06)
Root cause: aiuse/CodexBar fed omp the wrong meters (claude.ai cloud-session credits $250 row; org-wide Admin cost_report;
CodexBar Claude Platform picked the first readable Console org, not the linked one, Freedom Included). The real omp grant:
claude.ai Settings -> Billing -> API credits, $200/month, linked 2026-10-13, next credit 2026-11-06; currently spent.
23adbb25 owns: aiuse branch fix/omp-promo-credits-only (worktree ~/src/aiuse-wt-omp-promo-credits) -> commit, PR, gates (asked 13:07, ack tr2-23adbb25).
Lead owns (djbclark-ade): acp-dispatch preflight / route_agent treat a 400 "credit balance is too low" as not routable with
the reset at the next credit (note-exhausted omp until 2026-11-06T00:00-05:00 recorded by hand meanwhile).
Operator steps for djbclark: ~/.config/aiuse [credits.omp] organization="Freedom Included", next_credit_at=2026-11-06,
set-credits --remaining 0; CodexBar Console cookies for the claudeplatform live read; upstream CodexBar org picker (#4654).
Lessons (for the doc): three Anthropic money surfaces (API-credit grant for a linked org / Usage-credits wallet / Console
spend cap; only the first is omp); "credit balance too low" is the API balance, not Claude Code's OAuth quota; always pin
the Console organization, never the first CodexBar org; route off the aiuse omp row plus a live probe.

## dsh, from w20:p0 (Cursor herdr tab, 2026-11-04 13:07)
Live machine state it made: ~/.local/bin/dsh (secretspec + YOLO wrapper), ~/.local/lib/dsh/bin/dsh-bin -> pnpm shim,
~/.dsh/profiles/web/cordis.patch.yml (danger-full-access), ~/.zshrc dsh() function, site-djbclark commit 3913c57 (pnpm dsh
upgrade + bin/dsh_repair_native_binding.py). Uncommitted: roles/site_agents/templates/brew-fast-upgrade.sh.j2 ensure_dsh_wrapper
(asked w20:p0 to revert its own hunk, ack tr2-w20p0). All of it is G4 removal material (machine-side: djbclark's yes).
Lessons: pnpm global @deepseek-ai/dsh can leave the darwin-arm64 native addon unlinkable (12 KB attempts[] dump on boot;
repair = symlink the platform package into the loader's node_modules); dsh requires pnpm (npm -g: EBADDEVENGINES); a key via
sudo-secretspec env (apiKeyEnv) works if no stored API key outranks it; YOLO is DSH_PERMISSION_MODE=danger-full-access, not
a flag; pnpm's bin dir prepended after ~/.local/bin shadows wrappers: use an absolute-path shell function or an ensure_wrapper
step; two parallel clipboard secrets-collect runs race (re-collect both).

## Batch log
- wave 1 (13:20-13:08 +1h): r1-pi, r2-billing (cursor default), r3-inventory, r4-lessons (zcode GLM-5.3 high): all DONE, reports beside this file.
  r3: 527 files / 3942 hit lines (ade 170, aiuse 108, site-public 83, site-private 158 incl. 147 memory notes, stayturgid 8).
  r1: pi->omp ports mostly landed (PRs 274/275); open: omp fail-open vs pi fail-closed (B2, operator call), ACP_RUN_OMP_ANY_MODEL
  agent-settable + only --agent-arg scanned (B9), agent_guard.py:39 comment (B11), session-find LIVE? shown as ended (B5).
- wave 2 (dispatched ~13:15): w2a-lessons-doc (cursor default, worktree ~/src/djbclark-ade-tui-lessons-wt, docs/tui-lessons-learned.md),
  w2b-credit-refusal (cursor default, worktree ~/src/djbclark-ade-omp-credit-wt, bin/acp-dispatch + test + fragment).
## Pending operator questions (asked 13:15)
Q1 machine-side uninstall (G4) yes? Q2 muse retire (H5)? Q3 memory notes: fold into the lessons doc and move the 147 notes
to an archive dir? Q4 keep the credential exclusions in bin/ade-backup-stores as a named exception?

## Roster update (13:11, rulings relayed by 501a7e0d; file inputs/rulings-2026-11-04.md)
Retire list adds pi (folds into omp) and cline (ClinePass allowed outside Cline; Dann substrate leg -> omp + cline-pass;
paseo-new-seat default --provider cline must move). Keep: claude, codex, agy, cursor-agent, grok, omp, opencode, hermes.
D2 copilot CLI: fold "keep a fallback". D3 yes: acp-run guard vs subscription credentials in omp/opencode. Ports: pi fail-closed
capacity gate -> omp; pi subagent extension -> omp. PR 283 (head 2c22ba5b, adversary r4 APPROVE) handed to the lead; its text
is stale vs these rulings: fold it into docs/tui-lessons-learned.md and close 283 as superseded (planned).

## venicecode, from w20:p11 (Cursor herdr tab, 2026-11-04 13:12)
Live machine state: ~/.local/bin/venicecode (secretspec + isolated XDG), ~/.local/lib/venicecode/bin/venicecode-bin,
~/.config/opencode/venicecode.json + ~/.config/venice-opencode-isolated/, ~/.zshrc venicecode(), ~/ops/site-private-djbclark/bin/venicecode-upgrade,
brew-fast-upgrade run_venicecode_pass; VENICE_API_KEY declared in sudo-secretspec (runtime). All G4 material.
Kept (opencode-general): plugins->plugin, commands->command layout, command/hand.md frontmatter (asked who owns the shared-checkout edits).
Lessons: the venicecode dev build has no --auto (YOLO = opencode.json permission allow); sudo-secretspec run exports every
secret, so unset AWS_* or the bedrock autoload breaks a compiled bun binary; isolate a fork with XDG_CONFIG_HOME +
OPENCODE_DISABLE_DEFAULT_PLUGINS; OpenCode v2 dirs are singular (plugin/, command/); verify an API key with a live GET
/api/v1/models, not a guessed length (a wrong length makes secrets-collect clear the clipboard without storing).
- w20:pS (codex, 13:14): no overlap; PR 282 merged; lesson: cached aiuse usable_now=true/99.7% while the API refused (12:17Z), so a cached reading is not proof of admission.
- wave 2 DONE ~13:30: w2a doc (427 lines; lead fixed scratch pointers, muse-as-pending, copilot fallback open) -> PR 288 head 8dea54ce;
  w2b credit-refusal (+137 acp-dispatch, 10 new tests + 89 touched) -> PR 287 head 341c2a50. Both in review-pr.sh (adversary codex sol high -> marker -> local-review).
- PR 286 (w20:p11, opencode hand.md frontmatter): clean local review + adversary APPROVE 3dbc039; waiting CI (its own pr-wait pid 93593).
- aiuse PR 47 (23adbb25): 3 P2 from local review sent back to author 13:32 (ack tr3-23adbb25).
- 13:50 PR 287 adversary BLOCK (2 P2: loose match, no retry horizon) -> w2b2-credit-fix (cursor pool 0% -> codex gpt-6.1-sol medium). PR 288 adversary BLOCK (P1 account billing/login history disclosure, P2 muse) -> lead fixed, head 8d319c88, review round 2.
- 14:45 aiuse PR 47: author fixed 3 P2s, head 25cd2f79 (1744 tests); lead's local-review running. Release after merge: `just release` in aiuse (author's note).
- 14:50 PR 287 r2 BLOCK (credit check after acp-run's fail=provider label: unreachable) -> lead fixed, head 1ccc4653, 89 focused tests pass (pypi.org DNS failing: UV_OFFLINE=1). PR 288 r3 BLOCK (funding state, C1 incident) -> lead fixed, head 67aee69b. Both in review (288 r4, 287 r3).
- 2026-11-06 05:10: PR 286 MERGED (w20:p11 hand.md). PR 287 MERGED 498d6bb1 (credit refusal -> class credit, capped 6 h). PR 288 r4 adversary APPROVE,
  local-review P2 (B11 wording) -> fixed head 38bcf78d, r5 running. aiuse PR 47 head 25cd2f79: 2 new P2s sent to 23adbb25 (tr4). Cloud credit expired 2026-11-05 02:59 EST unused.
- 05:20 aiuse PR 47 MERGED 0fcb9392 with 3 unresolved GitHub Codex threads (lead's mistake: a hand count printed 3 and the
  merge ran anyway). Sent to 23adbb25 (tr5): verify P1 omp skip-filter bypass + 2 P2 against main, fix/resolve, hold release.
  Fix: every merge in this task goes through ~/.local/state/bigteam/tui-retire/merge-pr.sh (pr-wait merge_ready or refuse).
  Queue: add "merge only after pr-wait --repo OWNER/NAME reports merge_ready, in every repo" to skills/bigteam/SKILL.md in the next djbclark-ade PR.
- 05:30 aiuse PR 48 MERGED 893219d9 (P1 omp skip filter; local-review clean f15a9db7); PR 47 threads 0 open; aiuse v4.0.1 released (tag, Homebrew), installed 4.0.1.
- 2026-11-06 09:50: PR 288 MERGED da6b2e7d (lessons doc; first deliverable done). PR 283 CLOSED as superseded. Decisions Q1-Q5 sent to helm lead
  7c58015b as a picklist (queued 20261106-095227-c20e49, ack tr-7c58015b).
- wave 3 (decided six: venicecode, qwen-code CLI, goose, aider, kiro, devin; 57 files / ~270 lines via git grep -P):
  w3-code (codex gpt-6.1-sol medium, 17 files, wt retire-w3-code), w3-skills (claude sonnet high, 18 files, wt retire-w3-skills),
  w3-docs (opencode-go minimax-m3, 11 living docs, wt retire-w3-docs). Kept: lessons doc, CHANGELOG, changelog.d, handoffs, history,
  9 dated docs, graft/, bin/ade-backup-stores (Q4), pi/ (pi track). NOTE: git grep -E has no \b; use -P.

## WIND-DOWN 2026-11-06 ~10:35 (helm lead 7c58015b, on djbclark's word)
- wave 3 NEVER RAN: all three slices exit 75 at the load gate ("machine too hot", load1 up to 310). Empty worktrees and branches removed.
- Nothing uncommitted of mine anywhere. Merged so far: djbclark-ade #285 (pr-policy + launchd job), #286, #287 (credit refusal), #288 (lessons doc);
  #283 closed (superseded). aiuse #47, #48 merged; aiuse v4.0.1 released and installed.
## NEXT (for whoever resumes; /baton from this file)
1. Re-dispatch wave 3 as written: briefs brief-w3-{code,skills,docs}.md, owned lists wave3-owned.json (regenerate with
   `python3 wave3-files.py` against fresh origin/master; worktrees retire-w3-{code,skills,docs} from origin/master), when load allows.
2. Then per PR: review-pr.sh (adversary codex sol high -> marker -> local-review) and merge only via merge-pr.sh.
3. Await djbclark's answers Q1-Q5 (sent to helm lead 7c58015b, record 20261106-095227-c20e49).
4. Later waves: zcode/crush trials through opencode (plan G2), pi -> omp ports (fail-closed capacity gate, subagent extension) then pi
   removal, cline (Dann substrate leg -> omp + cline-pass; paseo-new-seat default), copilot CLI per Q5, muse per Q2, ops repos and
   machine uninstall per Q1, memory notes per Q3; skills/bigteam/SKILL.md line "merge only after pr-wait merge_ready, every repo".
5. Open operator steps: aiuse [credits.omp] organization + next credit date; CodexBar Console cookies (omp row has no reading).
6. Final sweep: rg every retiring name; only docs/tui-lessons-learned.md, CHANGELOG/changelog.d, handoffs, history, dated docs remain.

## djbclark's answers (relayed by helm lead 7c58015b, 2026-11-06 11:26; ack tr-7c58015b)
- Q1 = 1: YES, machine-side uninstall of all decided TUIs, each tool's local state backed up first. NOT run by 0dc43dbd:
  the lead says who runs it and when.
- Q2 = 1: retire muse.
- Q3 = 1: move the 147 site-private memory notes that mention the retired TUIs to an archive folder agents do not read;
  the lessons stay in docs/tui-lessons-learned.md.
- Q4 = 1: keep the bin/ade-backup-stores credential exclusions as the one named exception.
- Q5 = 1: the copilot fallback is Paseo's Copilot provider; remove the copilot CLI support.
- The unfinished retirement (wave 3 onward) is FOLDED INTO the djbclark-ade split/slim-down session's scope, via this file.
- 0dc43dbd stays paused under the slim-down: no repo edits, no new work until a continue message.
