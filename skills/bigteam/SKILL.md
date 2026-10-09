---
name: bigteam
description: >-
  Run the prompt that follows as a multi-vendor fan-out instead of doing it
  single-threaded: probe every quota pool, slice the work into disjoint
  file-scoped assignments, dispatch them in parallel across the non-Claude TUIs
  with fresh monthly subscription windows, and integrate the results yourself.
  Use when the operator types /bigteam, says "bigteam", "parallelize this",
  "orchestrate this across agents/vendors", or "use the other agents too". Also
  the default, unprompted, for any discrete, separable task whose work would
  otherwise pull heavy context into the session (operator ruling 2026-10-08),
  and whenever the context-size hook says to delegate. Another bigteam run may
  be live (herdr tab `coord`): Step 0 keeps the two apart.
---

# bigteam — multi-vendor fan-out for one prompt

Turn one prompt into parallel work across every agent CLI on this machine,
spending the *cheapest adequate* pool for each slice and keeping Claude's own
window for what only it should do.

Two optimisation targets, both of them explicit operator goals:

1. **Token value** — don't spend Opus on mechanical edits, and never redo work
   already paid for.
2. **Multi-vendor monthly-plan use** — several subscriptions here reset monthly
   and go chronically unused. Idle quota is wasted money. Prefer a fresh
   subscription pool over Claude's 5-hour window for anything delegable.

This skill is the *method*. `model-routing` holds the verified headless
invocation forms and the billing-class map; read it, don't duplicate it here.

## Step 0 — another bigteam run may already be live

Another session may be running its own fan-out right now (often the herdr tab
labelled `coord`). The two share every quota pool and possibly the checkout, so
before slicing:

1. **Look.** `herdr tab list` (a `coord` tab, or any tab whose agent is
   `working` on a fan-out) and `ls -lt ~/.local/state/bigteam/` (task dirs
   touched in the last hour). Read each live dir's `CLAIM`.
2. **Claim.** Use a task name no live run uses, and write
   `~/.local/state/bigteam/<task>/CLAIM` before dispatching: session (herdr
   pane or Claude session id), repo, owned files, start time. Append `DONE`
   when you finish.
3. **Never overlap files.** A file another live claim owns is not yours to
   slice, edit, stage or format. In a shared repo, commit only your own paths,
   by path, after `git pull --rebase`; never touch the other run's uncommitted
   files.
4. **Pools are shared.** Re-probe `aiuse --available` right before each batch
   (the other run drains the same windows), leave headroom, and don't put both
   runs on a burst-limited pool at once (agy's ~60 requests/hour is machine-wide).
5. **Hands off its panes.** Never reuse, close or message the other run's
   tabs, panes or agents. To coordinate, tell its session (`session-finder`).

## Step 1 — probe, never assume

    aiuse --available        # usable pools only, one line per vendor AND model family, cache, <1 s
    aiuse --available --live # force a live collect (~30-60 s)
    cswap list               # Claude 5h / weekly / Fable

`aiuse --available` (aiuse 3.1.4+) prints only pools that can take work, sorted by
headroom, every window as "X% used / Y% left", with the data's age on its first
line. Exit 0 means usable pools exist, **3 means nothing is usable** (the data is
fine, the quota is not), 1 is a real error. It reads the snapshot cache that
`aiuse watch` and an hourly launchd job keep fresh, so you rarely need `--live`.
**Use the cache by default** (operator, 2026-10-06: slightly stale data saves a lot
of time). Take it as good enough when it says `fresh` (under ~25 min); add `--live`
only when it is older than that, or when the choice hinges on a pool that is near
empty or past its reset time since the snapshot. History: every collect is kept in
`~/.cache/aiuse/snapshots/` (and `ledger/`), so trends need no live call either. A pool missing from the list is exhausted or
suppressed: `aiuse --json -q | jq -r '.summary_lines[]'` shows every pool,
including the exhausted ones. Either way, preflight each target (*Reading the numbers* below),
because no snapshot sees a pool drained in the last few minutes.
(`~/ops/site-private/bin/aiuse-pools` is a thin wrapper for the same command.)

### Reading the numbers — a misreading here already cost a dispatch round

Read every number per `model-routing`'s *Reading quota numbers* and *agy has a
burst limit* (the one copy of those rules): used is consumed, the fullest window
binds, one TUI can hold several model-family pools (retry the vendor's other
pool before reassigning), re-probe before each batch, preflight each target
with `"Reply with exactly: OK"`, and agy only via `acp-run agy`, no probe loops.
`aiuse --available` already encodes the first three in its output.

Classify every pool before assigning anything:

| class | meaning | use for |
| --- | --- | --- |
| **fresh subscription** | monthly/weekly window largely unused | bulk, mechanical, writing, research — use heavily |
| **tight** | >40% of the binding window burned | one slice at most, or skip |
| **exhausted** | `remaining_percent` ≈ 0 on ANY window of that pool | skip that pool entirely (the same vendor's other model-family pool may be fine) |
| **lifeline** | another agent runs on it | use with care and never let it run out; see *Reserve pools* below (clinepass and Claude itself) |
| **shared allowance** | a GitHub-side feature draws on the same subscription | usable, but spend modestly and keep a margin; see *Copilot* under *Reserve pools* below |
| **prepaid** | real money | never without a fresh explicit operator decision |
| **excluded** | operator has ruled it out | respect it, with its end condition (below) |

### Vendors come back on their own

Nothing here takes a vendor out of rotation for good (operator, 2026-10-06: "make
sure vendors are automatically used again when more tokens become available"):

1. **Exhausted pools** drop out of `aiuse --available` and reappear by themselves
   once the sampler's snapshot sees the reset. Never keep a private "skip X" list
   between batches; probe each batch.
2. **`aiuse note-exhausted`** overrides always carry a reset time and expire then.
3. **An operator exclusion** ("don't use agy for now") is recorded with its end
   condition: a date, or an event such as "until reinstalled" (`acp-run --list`
   shows `ok` again) or "until the burst-limit issue is fixed". Re-check the
   condition each batch; when it has passed, the vendor is back in the pool. If no
   end condition was given, ask for one rather than excluding indefinitely.

**Current exclusions** (keep this list short; delete an entry when it lapses):

1. **The grok vendor (xAI's SuperGrok subscription)** — excluded 2026-10-06,
   operator: "Stop using grok (the vendor) in /bigteams etc. for now. You can
   still use grok models via several other vendors." End condition: none —
   permanent until the operator explicitly lifts it (confirmed 2026-10-06); don't
   ask for an end date or re-check it per batch. Covers every route that bills SuperGrok: the `grok`
   TUI/CLI, `acp-run grok`, Ralph's `grok` plugin, and LiteLLM's `grok-sub`
   model (the `xai_oauth_bridge`). Grok *models* through another vendor's pool
   (opencode, cursor, copilot, …) stay allowed, under that pool's own rules
   (prepaid ones like openrouter still need a fresh operator decision).
   **Enforcement (2026-10-06):** `aiuse --available` omits it via
   `[analysis.excluded_pools] "grok"` in `~/.config/aiuse/config.toml` and
   lists it under `excluded` (aiuse a540f15); Hermes's `fallback_providers`
   no longer name `grok-sub` or `xai-oauth` (`~/.hermes/config.yaml`).
   Still open by choice: `acp-run --list` shows `grok`, and LiteLLM keeps
   `grok-sub` in other models' fallback chains (`roles/litellm`,
   `litellm_xai_bridge_enabled`). Lifting the exclusion means undoing the
   aiuse and Hermes entries too.

### Reserve pools — never run them out

These pools have something else depending on them. Running one dry breaks that
dependant, which costs more than any slice saves:

1. **clinepass** — Hermes runs on it, through the LiteLLM gateway on `:4000`.
   Never bulk-route to it.
2. **The grok TUI** (`grok`, the SuperGrok subscription) — GrokBot, the cloud
   "Chief of Staff", runs on it. **Currently excluded entirely** (see *Current
   exclusions* above); when that lapses, small slices only, window checked
   first. Grok *models* reached through another TUI (opencode, cursor,
   copilot, …) bill that TUI's pool instead and are fine.
3. **Claude** — do use it; it does the judgment, integration and review. But
   orchestration runs from Claude, so if its 5-hour or weekly window runs out,
   nothing else gets dispatched, integrated or committed either. Check
   `cswap list` before every batch, not once per session, and keep enough
   headroom to finish integrating what is already in flight.

If one of these is the only pool left for a slice, wait or ask; don't spend the
reserve.

**Copilot — lighter care, not a lifeline.** The `copilot` TUI draws on the same
GitHub Copilot subscription that GitHub-side features use, notably automatic
Copilot code review of commits to `master` (djbclark's note of 2026-07-30), so a
drained allowance can also stop those reviews. Be careful, but far less than
with clinepass: nothing of the operator's runs on it, it is not a bulk pool
(its direct-use allowance is small), and it is opt-in only for slices that lean
on GitHub context. Check its remaining premium requests first and give it one
small slice at most, never a whole batch.

Ignore `aiuse`'s `kind:"conserve"` pace alerts for go/no-go; they fire on a fast
hour even when the window is nearly untouched.

## Step 2 — slice by file, not by topic

A fan-out only works if slices cannot collide. The partition rule:

> **Every file has exactly one owner for the duration of the batch.**

Topic slices overlap; file slices don't. Derive the partition from the files the
work actually touches, then name the owned paths explicitly in each prompt. Two
agents in the same file will silently lose each other's edits.

Prefer one shared checkout with strict file ownership over a worktree per agent:
disjoint files in one tree need no merge, and merging five branches costs more
than it saves at this granularity. Reach for `cow-workspaces` or
`git worktree` only when slices genuinely must touch the same file.

Keep for **yourself** (the orchestrator), never delegate:

- anything security-relevant, or any change whose blast radius you'd have to
  verify anyway
- the final integration, every diff review, all tests, and all commits
- any decision that removes a feature the operator deliberately built

## Step 3 — the concurrency contract

Every dispatched prompt carries the same hard rules. They exist because each one
has already been violated by a real agent on this machine:

- Edit **only** the listed files. Report anything else, don't fix it.
- **No git writes** — no add/commit/checkout/stash/restore/reset/rebase/clean.
  Read-only git is encouraged.
- **No test suite, no repo-wide formatter or linter.** The orchestrator runs
  tests centrally. A stray `ruff --fix .` rewrites other agents' files.
- Leave changes **uncommitted**. The orchestrator commits, staged **by path** —
  `git add -A` in a shared checkout stages other sessions' in-flight work.
- No package installs, no new directories, no scratch files inside the repo.
- **Verify before acting.** Findings handed to an agent were written by another
  AI. Tell it so, and tell it that reporting a finding as wrong is a better
  outcome than a confident wrong edit.
- Report in a fixed shape: `CHANGED:` / `SKIPPED:` / `NOTES:` / `DONE`.

## Step 4 — dispatch, and make sure you are told when each slice finishes

Learning that an agent finished is the part that fails silently, so it is
designed here rather than left to chance.

**The rule: each slice is a FOREGROUND command inside its own Bash call with
`run_in_background: true`. Never end a command by launching a `&` job, and never
poll with `pgrep -f`.** The harness tracks a `run_in_background` call and
re-invokes you the moment it exits. A job backgrounded only by a shell `&` is
invisible to it: verified 2026-10-03, such a job ran to completion and produced
no notification at all, and the batch sat finished for over an hour until it was
next checked. `acp-run` does not change this; it is an ordinary command, and ACP
only makes its own exit code and stop reason trustworthy.

**A `run_in_background` slice or waiter dies with the session.** It is a direct
child of the Claude process (verified 2026-10-08: task pid 21672, ppid 58204,
the session's `claude`) and Claude Code cleans it up when it exits (docs,
*Background Bash commands*). It does not come back on `claude --resume`.
Everything below about notifications holds only while the session lives; for
work that must outlive it, see *Jobs and records* after the waiter paragraph.

Send every slice in **one message as parallel Bash calls**, each
`run_in_background: true`, so each reports as it finishes and the first results
arrive first. **For every agent that speaks ACP, dispatch through `acp-run`**
(`~/ops/site-private/bin/acp-run`; agent list, flags and current status in
`model-routing`):

    acp-run <agent> -C <repo> -f "$OUT/brief-<name>.md" --model <m> \
        --perm scoped:<owned file>,<owned file> --timeout 1500 \
        --log "$OUT/<name>.jsonl" > "$OUT/out-<name>.txt" 2> "$OUT/sum-<name>.txt"

(`$OUT` is `~/.local/state/bigteam/<task>/`, outside the repo; owned paths are
relative to `-C`. No trailing `&`: the Bash call itself is the background job.)
**Not the session scratchpad:** it is wiped when the session restarts, and on
2026-10-05 that took a batch's briefs and outputs with it mid-run. Briefs,
outputs, logs and diffs for a fan-out live under `~/.local/state/bigteam/<task>/`
until the work is committed or recorded in a repo.

1. **`--perm scoped:<owned files>`** turns Step 2's one-owner-per-file rule into
   a per-call check: an edit outside the slice's paths is refused, not just
   discouraged. It binds only agents that send permission requests (copilot and
   cline do; claude, cursor and opencode mostly auto-allow by their own
   settings, so give those a stricter `--mode` where `--info` offers one, and
   still check the diff). Use `--perm deny` for review-only slices.
2. **Always `--model`.** The default is the agent's own, which for the claude
   adapter is the expensive settings model.
3. **One `--log` per slice**, so the event log (every tool call and permission
   decision) can be read when a slice goes wrong. `sum-<name>.txt` gets the
   one-line summary: stop reason, tool calls, permissions allowed/denied,
   tokens, cost.
4. Exit 124 is a timeout (acp-run cancels the session first); exit 1 is an
   agent error or other stop reason (`stop=cancelled` in `sum-<name>.txt` with
   exit 1 is the same timeout, reported by the adapter).
5. **Budget the timeout from the work, and put the report before optional
   checks.** A slice that runs the test suite N times under load needs
   N × (suite time + `bg`'s load wait, minutes when load is high) on top of the
   edits; 1500 s does not cover a six-finding fix plus a per-finding mutation
   check (2026-10-08: the D-fix slice on herdr-sleeper was cancelled at 1704 s
   in its mutation check, after 683 tests had passed, and the report, the last
   step of the brief, was never written). So: order every brief **edits →
   tests → write the report → optional verification (mutation checks, extra
   ruff passes) → update the report**, and give expensive verification its own
   slice when the count of suite runs is more than two. Prefer `--timeout 2400`
   over a tight one for an edit-and-test slice; the cost of a cancel is the
   whole report.
6. **A cancelled slice is resumed, not re-tasked.** The session id is in the
   `--log` file (`"sessionId"` in the result event). `acp-run <agent> -C <repo>
   --resume <id> --model <m> --perm deny --timeout 600 -p "write your report
   now from what you already did; edit nothing"` gets the real report from the
   agent's own context (the claude adapter resumes; other adapters: check
   `--info`). Only if that fails, reconstruct from the diff with a fresh
   read-only slice.

For agents with no working ACP route (zcode, muse), and as a fallback for
agy when its ACP client fails (it fails independently of the CLI), use the
per-CLI form from `model-routing`, with **stdin closed** and a `timeout` guard:

    { timeout 1500 <tui-invocation> < /dev/null; echo "---<name> exit=$?"; } > out-<name>.txt 2>&1

— again as its own `run_in_background: true` call, no `&`.

**One notification for the whole batch, if you prefer it:** a single
`run_in_background` call that starts the slices with `&` and ends in `wait`. The
`&` is fine there because the outer call is the tracked one; you get one event,
when the slowest slice ends. The broken shape is a call whose last act is
launching a `&` job: it returns at once, so the harness reports it done
immediately (false-early) or, without `run_in_background`, never reports it.

**Waiting on something that is not itself a tracked command** (a report file
another process will write) — run the wait as a `run_in_background` call and
bound it, so a file that never appears cannot hang forever:

    timeout 1800 bash -c 'until [ -e /abs/path/to/report-x.done ]; do sleep 10; done'

(Write the path out in full, or `export OUT` first: a `$OUT` inside the single
quotes is empty in the inner `bash -c`, so the loop would wait on `/report-x.md`
forever. Wait on a `.done` marker, not on the report: see *Jobs and records*.)

**Never write the wait as `until ! pgrep -f '<pattern>'`.** `pgrep -f` matches
the waiting shell's own command line, which contains `<pattern>`, so it always
finds itself and the loop never exits. On 2026-10-03 two such waiters ran for
1.5 hours and the only notification was the one produced by killing them. For
liveness use the PID (`kill -0 $pid`) or `wait`; for completion, wait on the
report file or the `---<name> exit=` line.

### Jobs and records — work that must outlive the session

What survives a session is a file, not a process. Every slice and every
detached job follows the same contract (2026-10-08).

1. **Report through a temp file, `.done` last.** The slice writes its report to
   `$OUT/<name>.report.tmp`, `mv -f`s it to `$OUT/<name>.report.md`, then
   `touch "$OUT/<name>.done"` as its very last act. Waiters wait on `.done`,
   never on the report, so a half-written file is never read.
2. **A job record per slice that may outlive its launcher:**
   `~/.local/state/bigteam/<task>/jobs/<name>.json`, written the same way
   (temp + `mv -f`):

       {"owner": "<CLAUDE_CODE_SESSION_ID>", "started": <epoch>,
        "report": "<abs>/<name>.report.md", "done": "<abs>/<name>.done",
        "rearm": "timeout 1800 bash -c 'until [ -e <abs>/<name>.done ]; do sleep 10; done'",
        "cmd": "<what was launched, one line>"}

   `owner` is the id of the Claude session that launched it. Claude Code sets
   `CLAUDE_CODE_SESSION_ID` in every Bash call (checked 2026-10-08 with
   `env | grep -i session`; there is no `CLAUDE_SESSION_ID`). Use
   `${CLAUDE_CODE_SESSION_ID:-unknown}`. `rearm` is the exact bounded waiter
   with absolute paths inlined. A record is **open** until it carries a
   `"closed": <epoch>` key; `/handoff` lists open records of its session and
   `/baton` re-arms and closes them. Records are closed, never deleted.
3. **Work expected to outlive the session is launched detached, not as a child
   of it:** multi-hour runs, anything that must survive a `/new` or the TUI
   quitting. `bg` does not do this: `~/ops/site-private/bin/bg` only waits for
   load and then `exec`s `taskpolicy -c utility "$@"`, so the command stays a
   child of whoever ran it. The verified detached form is `launchctl submit`
   (flags checked against `man launchctl`, macOS 27, and run: the job's parent
   is launchd, pid 1). Put the whole job in a small script so it reports the
   way item 1 says and removes its own label:

       # $OUT/run-<name>.sh   (chmod +x)
       #!/bin/bash
       export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
       OUT=<abs OUT>; N=<name>; L=bigteam.<task>.<name>
       [ -e "$OUT/$N.done" ] && { launchctl remove "$L"; exit 0; }
       <command> > "$OUT/$N.report.tmp" 2> "$OUT/$N.stderr"; rc=$?
       echo "exit=$rc" >> "$OUT/$N.report.tmp"
       mv -f "$OUT/$N.report.tmp" "$OUT/$N.report.md"
       touch "$OUT/$N.done"
       launchctl remove "$L"

       launchctl submit -l bigteam.<task>.<name> \
           -o "$OUT/<name>.out" -e "$OUT/<name>.err" -- "$OUT/run-<name>.sh"

   Three facts verified 2026-10-08 that the script above is built around:
   **launchd restarts a submitted job every time it exits** (a bare job reran
   every ~20 s), so the script must `launchctl remove` its own label as its last
   line, and the first-line `.done` check stops a restart after a crash from
   redoing finished work; the job's environment is bare (`PATH=/usr/bin:/bin:
   /usr/sbin:/sbin`, `HOME` set, nothing else), so export what the command
   needs inside the script; and a submitted job does not survive a reboot. Not
   tested: an agent CLI under launchd (keychain and login state), and
   `claude --bg --exec '<cmd>'` (the background-session supervisor; per the docs
   its output is held in memory and cleaned about five minutes after the job
   exits, so it would still need the report-file contract above).
4. **What is and is not promised.** Only detached jobs that have a record are
   promised to outlive the session. Whether an ordinary `run_in_background`
   task survives a `/new` is NOT established as a guarantee: the test result
   below saw it survive in one Claude Code version and one case, and saw it die
   on quit. Do
   not hand work to the next session on the assumption that a background task or
   waiter will still be there.

**Why jobs are records on disk (investigation, 2026-10-08).** A Claude Code
docs and local-process investigation found: background Bash tasks are
children of the `claude` process and "automatically cleaned up when Claude Code
exits" (https://code.claude.com/docs/en/interactive-mode, *Background Bash
commands*), including anything under `setsid` or `timeout`; `claude --resume`
does not restore them (https://code.claude.com/docs/en/sessions); no flag,
hook or environment variable lets a new session list or adopt another
session's tasks. Named pipes were rejected: a pipe buffers about 64 KiB, a
writer blocks or fails with no reader, and the reader would itself be a
background process with the same exit problem. So the result is a file, the
completion signal is a `.done` marker written last, and a small record names the
owner, the paths and the exact waiter to re-arm; the cost is one wake turn per
completion and one re-arm turn per new session. Backgrounding the whole session
(`/background`) also keeps its tasks; `claude --bg --exec` was not tested.

**Test result (2026-10-08, Claude Code 2.1.295, a throwaway interactive
`claude --model haiku` session in a herdr pane, since closed).** Three
observations, all in one case:

1. `/new` is an alias of `/clear` in this version (the transcript echoes
   `/clear`). It starts a new transcript in the **same** `claude` process. A
   `run_in_background` `sleep 311` started before it kept running (still a child
   of the same `claude`), the footer of the new session showed it as a running
   shell, and when it finished the completion notification woke the **new**
   session (which did not recognize it as its own).
2. Quitting the TUI stops background tasks: `/exit` raises a prompt "Background
   work is running / The following will stop when you exit" with *Exit and stop
   tasks*, *Move to background and exit*, *Stay*. Choosing the first killed the
   `sleep 313` (verified with `ps`). So `/handoff` then `/new` in the same TUI
   keeps tasks; `/handoff` then quit, or a crash, or a new terminal tab does not.
3. A `launchctl submit` job is parented by launchd (pid 1), not by any Claude
   session, so it is independent of all of the above.

This is one version and one path. It does not make a background task a safe
carrier for work: the next session may be a different process, and it did not
recognize the inherited task as its own. Records and detached jobs stay the
contract.

**A slice that fails on quota** (429, `usage limit`, `RESOURCE_EXHAUSTED`) is
Step 1 item 3: try the same vendor's other model-family pool before reassigning.
Then **tell the next agent**, so it does not walk into the same wall:
`aiuse note-exhausted <provider> [--family <gemini|claude_gpt|fable|...>]
--resets-in 4h53m [--reason '<the 429 text>']` (or `--resets-at <ISO>`). It is an
advisory override that expires at the reset time and shows up in
`aiuse --available` as `source: agent-reported`. Only record what a call really
returned; do not guess a reset time.

## Step 5 — integrate, and trust nothing on faith

- **Exit 0 is not success.** A file holding only a preamble, or a reviewer
  returning no findings, is a failed run. Check for an actual report. This holds
  for `acp-run` too: an agent can end its turn normally with a provider error
  as its whole reply. The summary line's permissions-denied count shows a slice
  that tried to leave its files.
- Read every diff yourself before committing. Agents are good and still get
  ordering, alphabetisation and scope wrong.
- Run the tests centrally, once, after the batch settles.
- When an agent refutes part of its own brief, that is the system working —
  prefer its evidence over your assumption, and say so.
- A slice that fails on tooling (not on the work) gets **reassigned to a
  different vendor**, not retried on the same one. The exception is a quota
  failure on one model-family pool: retry on the same vendor's other pool first
  (Step 1 item 3), because the vendor itself is not spent.

## Step 6 — second opinion on contract decisions

For a protocol/contract/API decision, or any recommendation to delete
functionality, get one independent opinion from a **differently sourced** vendor
than the one that proposed it, and make it adversarial: tell it not to defer,
and ask it to check each claim with file:line evidence. Then put the decision in
front of the operator if it removes something they deliberately built.

## Known failure modes, already paid for

| symptom | cause | action |
| --- | --- | --- |
| `copilot` hangs or `shared writer lock ... changed` | headless `--allow-all-tools` disables itself when it can't reach a policy server, then waits for an approval no TTY can give | reassign the slice; keep copilot timeout-bounded |
| `agy` CLI returns `RESOURCE_EXHAUSTED (code 429)` on every model while `aiuse` shows headroom, or looks hung for ~2m20s | per-client burst limit on the CLI login (2026-10-03: ~304 requests in 3 h); the CLI retries 8 times in-process, and `--print-timeout` cuts it with exit 0 and partial output | stop; `grep 'attempt [0-9]* failed' ~/.gemini/antigravity-cli/log/cli-*.log`; use `acp-run agy` or reassign; do not loop probes |
| `agy` runs with a flag as its prompt | `-p` is a required-value string flag | always `-p='<prompt>'`; a non-zero exit here is the guard working |
| `zcode` hangs with ~0 CPU | `--mode build`/`edit` gates tools behind an impossible approval | default yolo only; `ZCode Built-in skipped` on stderr is benign |
| `opencode.json` turns up modified | every `opencode run` rewrites it in cwd | `git checkout -- opencode.json`, or avoid in tracked repos |
| `opencode/*` model fails on funds | that's the prepaid Zen catalogue | use `opencode-go/*` for the free bundle |
| a stray empty dir appears | agy has done this | `git status --porcelain` after every batch |
| `acp-run` exits 1 with `FAILED quota/plan/auth/transient` (or 5: empty reply, every permission denied) | since 2026-10-05 acp-run detects provider failures that arrive as a normal `end_turn` (plan-gated reply, reply cut off by a transport error, quota text); `reply truncated; edits may be present` means check the tree | read the stderr line and the log; reassign the slice or wait for the pool; for truncated, review what was edited |
| no notification when an agent finishes | it was launched with a trailing shell `&` and no `run_in_background` call, so the harness is not tracking it | run each slice as a foreground command in its own `run_in_background: true` call (Step 4) |
| a wait loop never ends | `until ! pgrep -f '<pattern>'` matches its own shell | wait on the report file, a PID or `wait`; bound it with `timeout` |
| `RESOURCE_EXHAUSTED` / "usage limit" from a vendor you thought had headroom | `used_percent` read as free; or the pool was drained since the probe; or that model family's pool is spent while a sibling pool is fine | decide from `remaining_percent`, preflight, re-probe per batch, retry on the sibling model family |

## What this skill is not for

A single-file edit, a lookup, or anything where the coordination overhead
exceeds the work. Fan-out has a real fixed cost: writing the slices, enforcing
the contract, reviewing the diffs. Don't count slices to decide, though: a
discrete task that would read many files, logs or long outputs into this
session belongs in a fan-out even as one or two slices, because keeping this
context small is itself the goal (2026-10-08). Do it yourself only when the
work is small enough that its tokens cost less than the brief and review.
