# Operator prompts for the Mac steps (2026-11-07)

One prompt per step of the final-merge walk-through, to paste into a Claude Code TUI started on the Mac **outside
Paseo** (`cd ~ && claude`). Each prompt reads `docs/slim/operator-batch.md` from the slim branch, so it works before PR 297
merges. They change the Mac (installs, config, launchd): each says to show the plan and wait for your yes before the first
change, and to report what it ran. Item ids (A1, C7, …) are the operator batch's.

Common preamble every prompt assumes (it repeats the essentials):

- The slim-down branch is `claude/determined-maxwell-uvddaz` of `djbclark/djbclark-ade`; read files from it with
  `git -C ~/src/djbclark-ade fetch origin claude/determined-maxwell-uvddaz` then
  `git -C ~/src/djbclark-ade show origin/claude/determined-maxwell-uvddaz:<path>`. Do not check it out in `~/src/djbclark-ade`
  (a shared checkout, AGENTS.md order 9) and do not edit any repository in these steps unless the prompt says so.

## P2. Paseo plugins (A2-A4)

```
You are helping me (djbclark) install Paseo plugins on this Mac. Paseo is already 0.15.x. Do not use Paseo to run yourself.

1. Run: git -C ~/src/djbclark-ade fetch origin claude/determined-maxwell-uvddaz
   Then read: git -C ~/src/djbclark-ade show origin/claude/determined-maxwell-uvddaz:docs/slim/research/plugins-trust-2026-11-06.md
   (the source summaries and the "Settings to apply on install" section) and items A2-A4 of
   git -C ~/src/djbclark-ade show origin/claude/determined-maxwell-uvddaz:docs/slim/operator-batch.md
2. Run `paseo plugin --help` and `paseo plugin ls` (or the listing subcommand --help names) to learn the exact install,
   list and settings commands on this version; the registry form is `paseo plugin add <owner>/<slug>`. Never guess a flag.
3. The set to install (my default; show it to me and wait for my yes or edits before installing anything):
   - tell-agent (omercnet), questions-please (djbclark/paseo-plugin-questions-please), asks (fullstackhouse/paseo-asks),
     vitals (tomgrin10), skills (gpambrozio), pr-radar (omercnet), claude-code-entrypoint-env (getpaseo);
   - baton (dennyferra) with handoffProfileId set to a cheap model;
   - session-guard (tomgrin10) with includeNativeSubagents=false and protectByDefault=false for the first week;
   - session-janitor (sm1ee) left in preview (automation off);
   - session-recovery (sm1ee) with enabled=false and an explicit daemonHome (my Paseo home).
   NOT installed: zerosub (I run one Claude subscription), usage-auto-resume (it reads my Claude/Codex tokens; session-guard
   does the same job), plan-auto (unless I ask).
4. Install them one at a time, apply each plugin's settings right after it installs, and confirm each shows as installed.
5. Make sure Paseo's native "Resume agents after restart" setting is OFF (find where it lives: Paseo settings or
   ~/.paseo/config.json; change nothing else there).
6. Report: a table of plugin, version installed, settings applied, and anything that failed or did not match the summary
   (a different version than the summary read, a new permission prompt, a setting that does not exist).
```

## P3. Verify session-guard (A5)

```
On this Mac, verify the Paseo plugin session-guard works before the slim-down removes the old Claude quota guard.
Read item A5 and the session-guard entry of docs/slim/research/plugins-trust-2026-11-06.md from the slim branch
(git -C ~/src/djbclark-ade fetch origin claude/determined-maxwell-uvddaz; git -C ~/src/djbclark-ade show
origin/claude/determined-maxwell-uvddaz:<path>). Then:
1. Show session-guard's status (its RPC or UI; find the command with `paseo plugin --help` or the plugin's README) and the
   usage windows it sees for Claude (it polls provider usage every 15 s).
2. Do NOT burn quota to test it. Report what it would do at 100% (its threshold, protected agents, autoResume), and
   whether it lists my running Claude agents as protected once I turn protectByDefault on.
3. Tell me how to watch for the first real pause and resume (the log or UI to check after the next limit hit), and write
   that check as one line I can keep. Change no setting without asking.
```

## P4. Native-resume trial (A6)

```
On this Mac, run ONE bounded trial of Paseo's native "Resume agents after restart", to decide parked PR 290 (ade-recovery).
Read items A4 and A6 of docs/slim/operator-batch.md and the session-recovery entry of docs/slim/research/plugins-trust-2026-11-06.md
from the slim branch (git -C ~/src/djbclark-ade fetch origin claude/determined-maxwell-uvddaz; then git show of each path).
Rules: the fleet must be idle (no agent mid-turn: `paseo ls -g --json`, check statuses), and new launches held
(`~/src/djbclark-ade/bin/load-watch admit` refusing, or simply start nothing during the trial). Show me the plan and wait for
my yes. Then:
1. Note the agents and their statuses (`paseo ls -g --json`).
2. Turn native resume ON, restart the Paseo daemon once (find the supported restart command; ask if unsure).
3. After it is back, list the agents again: which resumed, which stayed idle, any that started a turn on their own (a
   "mass wake"), any errors in the daemon log.
4. If anything mass-woke or misbehaved, turn native resume OFF again; if it behaved, leave it ON.
5. Write a five-line result I can paste into PR 290: what was tested, what happened, the setting left, and the limit
   (an idle-fleet trial cannot show what a busy fleet does).
```

## P5. GitHub App and environment for the merge gate (A8-A11)

```
Set up the GitHub side of djbclark-ade's new merge gate, on this Mac with my gh login. Read items A8-A11 of
docs/slim/operator-batch.md and section E of docs/slim/reports/wave4-E8.md from the slim branch
(git -C ~/src/djbclark-ade fetch origin claude/determined-maxwell-uvddaz; then git show origin/claude/determined-maxwell-uvddaz:<path>).
1. A8 is in the GitHub web UI: walk me through creating the App `ade-merge-gate` (webhook inactive; Commit statuses read
   and write, Checks read and write, Pull requests read-only; "Only on this account"; install on djbclark-ade only;
   generate a private key). Ask me for the App ID and Client ID when I have them. Never ask me to paste the private key.
2. A9: create the `merge-gate` environment limited to `master` with the two gh api calls in A9; show each before running.
3. A10: store the key with `gh secret set MERGE_GATE_PRIVATE_KEY --env merge-gate --repo djbclark/djbclark-ade < <the .pem path>`
   (I give the path) and the client id with `gh variable set MERGE_GATE_CLIENT_ID ...`; then delete the downloaded .pem.
4. A11: run the check-run query and confirm `pytest-linux` and `context-policy` with app id 15368.
5. Report the App ID, the environment's branch policy as gh shows it, and A11's output. Do not create the ruleset yet
   (that is after PR 297 merges).
```

## P6. Firecrawl (A12): nothing to run

The operator kept `bin/firecrawl-router` in djbclark-ade (2026-11-07), so the shared MCP and Hermes' backend keep working through
it. After the merge, P12 checks that `http://127.0.0.1:18804/mcp` still answers.

## P8. C7 drain and C1 live-process checks (A18-A25)

```
On this Mac, run the slim-down's final merge-gate checks and give me one block to paste into djbclark-ade PR 297.
Read items A18-A25 of docs/slim/operator-batch.md from the slim branch
(git -C ~/src/djbclark-ade fetch origin claude/determined-maxwell-uvddaz; then git show ...). Run every command in A18-A24
exactly as written there, read-only (A21's relay.py is the OLD one on master: run it from ~/src/djbclark-ade as it is now).
Capture each command's output with its exit status (`cmd > f 2>&1; echo rc=$?`), never through a pipe's status.
Then summarise: for each of A18-A24, PASS (matches the "expect") or what differs. Produce the paste block: a fenced block
headed "C7/C1 re-run <date> on <host>" with the per-item result lines and, below, the raw outputs trimmed to what matters.
Change nothing; if something needs a waiver or a drain, list it and ask me.
```

## P10. Merge-gate tests and the ruleset (B6-B13), after PR 297 is on master

```
djbclark-ade PR 297 has merged, so the `adversary-marker` Action now runs from master. On this Mac, prove the merge gate and
switch it on. Read items B6-B13 of docs/slim/operator-batch.md and section E3/E4 of docs/slim/reports/wave4-E8.md on master
(git -C ~/src/djbclark-ade fetch origin master; git -C ~/src/djbclark-ade show origin/master:<path>). Work in throwaway
worktrees (`git -C ~/src/djbclark-ade worktree add -b throwaway/<name> ~/src/djbclark-ade-<name>-wt origin/master`), never in
~/src/djbclark-ade itself. Show me each test's plan once, then run without stopping unless something differs from the
expected result.
1. B6 T0: a draft PR whose body carries an APPROVE marker for its own head; wait for the Tests run, then read the
   `adversary-marker` status (`gh api repos/djbclark/djbclark-ade/commits/<head>/statuses`): expect success from the App.
2. B7: write the ruleset JSON exactly as B7 gives it (adversary-marker pinned to the App ID from step 5, pytest-linux and
   context-policy pinned to 15368, no bypass actors), show it, and create it with `gh api -X POST .../rulesets`.
3. B8: re-check T0 under the ruleset (`gh pr view <N> --json mergeStateStatus,statusCheckRollup`); if the status does not
   satisfy the pin, apply the check-run fallback B8 describes (a one-line workflow change, landed as its own PR).
4. B9 T1: a PR that edits adversary-marker.yml into an always-green job: expect BLOCKED and the merge refused.
5. B10 T2: a PR adding .github/workflows/spoof.yml with `permissions: {statuses: write}`: expect BLOCKED.
6. B11 T3: from the second GitHub test account (find its login with `gh auth status`; switch with `gh auth switch`, and
   switch back to djbclark afterwards), fork djbclark-ade, push a branch at T0's head with an APPROVE marker in a PR body
   written by that account: expect `failure` "marker not written by a trusted user", never success.
7. B12: close every throwaway PR with `gh pr close <N> --delete-branch`, remove the worktrees, delete the fork's branch.
8. B13: only if branch protection also lists required checks, remove them now that the ruleset holds (show first).
Report a table: test, PR number, expected, observed, PASS/FAIL; the ruleset id; and anything that needed the fallback.
```

## P11. Mac cleanup after the merge (C1-C64)

```
PR 297 (the djbclark-ade slim-down) has merged. On this Mac, do the post-merge cleanup in phase C of
docs/slim/operator-batch.md (now on master: `git -C ~/src/djbclark-ade fetch origin master` then
`git -C ~/src/djbclark-ade show origin/master:docs/slim/operator-batch.md`). Work in this order, group by group, WITHOUT
stopping for my yes (operator choice, 2026-11-07): print each group's commands before running them, keep going unless a
command fails or something differs from the batch, and stop only then:
1. C1-C5 hook lines in ~/.claude/settings.json (back it up first to ~/.claude/settings.json.pre-slim).
2. C6-C21 stop the retired launchd jobs and remove their plists (launchctl list first; skip any not loaded; C16, C17 and
   C19 name unverified labels: check them).
3. C22 `ade update`, then C23-C34 relinks and dangling-link removal (`skill-everywhere report`, `--all`, `--check`).
4. C35-C39 Paseo skills and config (C35: `npx skills add getpaseo/paseo`, then set them user-invocable-only in my live
   ~/.claude/settings.json as the template does).
5. C40-C47 hosts and services that name old paths (C40 and C41 change authorized_keys: show the exact line diff).
6. C48 backup tarball FIRST (verify it opens), then C49-C64 uninstalls and archives. Never touch ~/.gemini/antigravity-acp
   or ~/.gemini/antigravity.
Never skip the backups (settings.json before group 1, the tarball before group 6, and check that the tarball opens).
After each group report what ran and its exit status; at the end, a checklist of C1-C64 with done / skipped (why) / failed.
```

## P12. Live checks after the merge (C65-C73)

```
On this Mac, run the slim-down's live checks, items C65-C73 of docs/slim/operator-batch.md on djbclark-ade master
(`git -C ~/src/djbclark-ade show origin/master:docs/slim/operator-batch.md`), in order, each command exactly as written:
review-launch --check (both modes), the first bin/review-pr on a real PR, route_agent.py services --check-models and show,
one live acp-dispatch read-only run, the context-budget Paseo schedule (C69), the optional upstream schedule (C70, create it:
no need to ask, operator choice 2026-11-07), closing PR 270 (C71, close it: no need to ask), a check that
`http://127.0.0.1:18804/mcp` still answers (the kept firecrawl router), and `graft build` (C73). Capture each exit status without a pipe. Report a table:
item, command, rc, PASS or what differed; for C65 paste the self-check table into a short note I can put in
docs/slim/log.md through a PR.
```
