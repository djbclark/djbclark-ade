# Slim-down check-in: prompt for every agent working on djbclark-ade

Snapshot 2026-11-06. Paste the block below, verbatim, into every agent that is
working on djbclark-ade (or on anything that writes into it: its skills,
`~/.local/bin` links, launchd jobs). The operator pastes it; the agent answers in
its own session AND pushes a report file, so the slim-down lead (a Claude cloud
session, which cannot see your machine) reads it from git.

To find the agents: `paseo ls -a -g --json | jq -r '.[] | [.id,.title,.workspace.directory] | @tsv'`
(and any Claude Code / Codex sessions outside Paseo: `fleet.py`, while it still exists).

After every agent has answered, the lead runs
`git fetch --all --prune && git log --all --format='%h %D' -- docs/checkins/` to read the reports.

---

```
CHECK-IN REQUEST (slim-down of djbclark-ade, 2026-11-06). Read all of it before acting.

A Claude cloud session is about to split djbclark-ade (move the non-ADE parts
out, delete what Paseo now does natively, shrink the rest). Before it starts,
every agent touching this repo must report its state and then pause. Do the
steps in order. Do not start any new work after step 1.

1. FINISH OR ABORT the current unit cleanly. If you are mid-merge or
   mid-rebase, resolve it or `git merge --abort` / `git rebase --abort`; if a
   test run or build is in flight, let it finish or stop it. Say which you did.

2. REPORT. Write the answers to these questions into a file
   `docs/checkins/2026-11-06-<your-short-id>.md` (short id = first 8 chars of
   your PASEO_AGENT_ID, or your session id, or your branch name if neither):
   a. Who: provider, model, PASEO_AGENT_ID or session id, workspace directory,
      branch (`git branch --show-current`), who/what started you, when.
   b. Task: one paragraph on what you were asked to do and what is done so far.
      Link the queue entry, PR, or message that assigned it.
   c. State: paste `git status --porcelain=v1`, `git log --oneline origin/master..HEAD`,
      `git worktree list`, `git stash list`, and any PR numbers you opened.
   d. Footprint: every file you changed or plan to change (repo-relative).
      Also anything OUTSIDE the repo you changed: `~/.local/bin` links,
      `~/.claude`/`~/.codex` config, launchd jobs, Paseo settings or plugins,
      files in `~/src/djbclark-ade` (the shared checkout) or `~/ops`.
   e. Overlap: mark each of your files against these areas, which are
      candidates for deletion or move: tools/acp-run, bin/acp-dispatch*,
      skills/session-finder (relay.py, fleet.py, launch.py), skills/helm,
      bin/self-slash, skills/autorename, skills/bigteam, skills/cow-workspaces,
      bin/ade-scan-state*, bin/route_agent.py, bin/failover.py, the quota
      gates, the watchers (load-watch, rumination-watch, watch, paseowatch,
      cfenginewatch), non-Claude TUI support (pi/, opencode/, omp/, zcode/,
      agents/, bin/*codex*, bin/*opencode*, bin/coding-bot, cursor-cloud), the
      non-ADE skills (siyuan*, gmail-search, barnowl, book-to-kb, ovhcloud-api,
      aws-rules, hyades-docker, forgejo*, terminus-kira, diskfree,
      bottom-config, setup-modern-cli, teach, todo, report), and docs/ in
      general. If your work builds ON one of these, say so plainly.
   f. Your own recommendation, one line each: (i) STOP and discard,
      (ii) STOP after landing what is already committed, (iii) FINISH first
      because <reason>, (iv) CONTINUE unaffected because <reason>. State what
      would be lost under (i) and how long (ii)/(iii) would take.
   g. Anything the lead must know to not break you: processes you left
      running, claims you hold (`ade-git-guard claim ls` if it exists),
      deadlines registered (`deadline ls`), scheduled Paseo heartbeats or
      schedules you created.

3. COMMIT AND PUSH everything, including the report, as WORK IN PROGRESS:
   - If you are in a worktree or pasture on your own branch: `git add -A`
     (check `git status` first so no secret or ignored state is added), commit
     with message `wip(checkin): <task> -- slim-down check-in 2026-11-06`, then
     `git push -u origin <branch>`. Retry the push up to 4 times with backoff
     on network errors.
   - If your edits sit in the SHARED checkout `~/src/djbclark-ade` or in
     `~/ops`: do NOT commit there. Create a worktree
     (`git worktree add -b checkin/<your-short-id> ~/src/djbclark-ade-checkin-<id>-wt origin/master`),
     move the diff (`git diff > /tmp/ci.patch` in the shared checkout, then
     `git apply /tmp/ci.patch` in the worktree), commit and push THERE, and
     say in the report that the shared checkout still carries the uncommitted
     copy (the lead will tell you when to drop it; do not reset it yourself).
   - Never push to master (branch protection refuses it anyway). Never force-push.
   - Do not open a PR for this commit.

4. REPLY in this session with the full text of the report file plus the exact
   branch name and commit sha you pushed, then say `CHECKIN DONE <short-id>`.

5. PAUSE. Do not pick up new queue items, do not start subagents, do not
   archive or remove worktrees, do not delete branches. Stay idle until a
   message tells you to continue, stop, or hand off. If you are a watcher
   (load-watch, paseowatch, cfenginewatch, rumination-watch), keep watching
   but make no repo edits.

If any step is impossible, say exactly which and why in the reply instead of
working around it.
```
