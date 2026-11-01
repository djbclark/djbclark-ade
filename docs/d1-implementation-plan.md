# D1 implementation plan: contracts and safety net (prepared 2026-11-01)

Status: DRAFT for the lead; nothing here is installed or enabled. It turns phase D1 of
[paseo-only-rearchitecture.md](paseo-only-rearchitecture.md) (plan v1) into ordered tasks. Section and item
numbers (B4, D1.3, G2.8, ...) are that plan's. Drafts live in `tests/paseo-acceptance/` and
`bin/paseo-watchdog`; both are unreviewed and the destructive ones have never been run.

## 1. Dependencies on open PRs (checked 2026-11-01, all OPEN)

| PR | What D1 needs from it | Without it |
|---|---|---|
| 190 `changelog-fragments` | D1's CHANGELOG entries are a fragment `changelog.d/<branch>.md`, folded by `bin/changelog-fold`; review rule 10 asks for a fragment | D1 would edit the shared `## Unreleased` block and conflict with every other open PR |
| 177 `relay-status` | `relay.py --status` and the visible stuck queue and collected acks feed the D0.2 drain script (`drain/relay-pending.sh`): "no queued or stuck message" becomes a query, not a transcript read | the drain script can only list `--pending`, so the `relay.py` half of the drain gate is weaker (and D1.1's evidence cannot cross-check an ack) |
| 180 `retire-docs` | herdr (but its two bridges), Orca and BB retired from the docs and toolchain prompt; `paseo-screen` skill | D1 files may name the retired tools in prose that 180 then rewrites; rebase and recheck `rg -i 'orca\|herdr\|tuios'` over D1's new files after 180 lands |

Rebase `d1-prep` onto master after all three land, then re-read `docs/queue.md` and AGENTS.md orders 9 to 11
(they change in 180 and 190). Nothing in D1 touches `~/ops`, `~/.local/bin` or the live daemon's config
without djbclark's yes (order 11).

## 2. Facts measured on 2026-11-01 (read-only; refresh with the probes in `tests/paseo-acceptance/readonly/`)

1. The Mac **CLI is 0.15.0-beta.1; the running daemon is 0.14.0** (`paseo -v`, `paseo status`). Every probe
   records both, because a CLI/daemon skew can change behaviour. The plan says "Mac daemon 0.14.0".
2. `paseo status` printed `Status details unavailable (DAEMON_REQUEST_TIMEOUT): ... (1500ms)` while
   `/api/health` answered 200 in 8 ms and `paseo ls --json` in 1 s: the plan's #2753 shape (health answers,
   RPC starves) is visible on the live daemon right now. B9's two probes are right; keep both.
3. `GET http://127.0.0.1:7263/api/health` returns `{"status":"ok","timestamp":"..."}`. `paseo plugin ls --json`
   is an array with `id`, `enabled`, `status` (`running`, `disabled`), `source`, `commit`, `installation`.
4. **`herdr-harness` is `enabled: true`, `status: running`** on the Mac. Plan A8.2 and C1 say "installed,
   disabled". Question 8.
5. `session-janitor` is `disabled`; its state lives in `~/.paseo/plugin-data/paseo-session-janitor/state.json`
   (directory name differs from the plugin id) and holds `protectedIds`, `pinnedWorkspaces`, `observations`.
   The three B4.3 settings (`archiveChildren`, `deleteChildren`, `deleteMain`) are in neither that file nor
   `~/.paseo/config.json`: **where the janitor keeps them is unknown**; T9 finds out.
6. `~/.paseo/plugin-data/herald/config.json` has `cleanup.deleteHelpers: false` (B4.3 holds today).
7. CLI surface relevant to D1: `paseo send --behavior steer|interrupt` (default: the agent's own default),
   `paseo permit ls|allow|deny` (`allow --input <json>` carries "modified input"; there is **no CLI
   `respond`**), `paseo agent detach`, `paseo agent archive --force`, `paseo daemon run|start|stop|restart|status|
   config|set-password`, `--home` and `--host` on every command (the isolated-daemon hook), `paseo schedule
   create|run-once|logs`, `paseo workspace create|archive`, `paseo run --new-workspace worktree --worktree-slug`.
   Each CLI call costs about 1 s of start-up.
8. `paseo permit ls --json` returned `[]` and `paseo ls --json` returned 14 agents (running and idle) at the
   time of writing, so the live daemon is **not drained**: no D1 probe may touch it except the read-only ones.

## 3. Conventions every probe follows

1. **Header block** (first 15 lines): `CONTRACT` (plan item proved), `EXPECT`, `ON-FAIL` (the named consequence
   from the plan), `SCOPE`, `HOW`, `NEEDS`. `SCOPE` is exactly one of `READ-ONLY live`, `second daemon only`, or
   `DESTRUCTIVE: second daemon only` (B10; anything that restarts, hangs, kills a daemon or an agent's turn, or
   deletes a worktree).
2. Every non-read-only probe sources `lib/common.sh` and calls `require_isolated`, which **refuses (exit 2)**
   unless `PASEO_HOME` is set, differs from `~/.paseo`, is a fresh directory the library created (marker file
   `.ade-acceptance-home`), and `--host` points at that daemon's Unix socket or a port found in
   `site-djbclark/registry/ports.yml`. A copy of the live home is refused (the live `daemon-keypair.json`
   and server id would be inherited, B10).
3. Exit codes: 0 contract held, 1 contract broken (the consequence is printed), 77 precondition missing (skip,
   not a pass), 2 usage or isolation refusal.
4. Result record: `~/.local/state/ade/acceptance/<UTC date>/<probe>.json` (atomic; `.get` on read), with
   `cliVersion`, `daemonVersion`, `provider` where relevant, `verdict`, `evidence` (paths, never secrets).
   Nothing is written under the repo; the lead copies the verdicts into the D1 PR body.
5. No pytest. Probes are shell and Python run by hand or by `tests/paseo-acceptance/run-all.sh --list`;
   CI runs `shellcheck` only if a CI step for it exists (question 10).
6. Test daemons never install `session-janitor`, or write its three settings false before first run (B10);
   `lib/common.sh` `isolated_up` creates the home, writes `daemon config` with a Unix-socket listener (question 1),
   sets a password, starts `paseo daemon run` under a saved PID, and `isolated_down` kills exactly that PID.

## 4. Ordered task list

Order is by dependency; tasks 1 to 3 are infrastructure, 4 to 12 are the D1.x probes, 13 to 16 are the
non-plugin builds. "Accept" is the check that closes the task.

### T1. Scaffolding and the read-only probes (no dependency)

Files: `tests/paseo-acceptance/README.md`, `lib/common.sh`, `readonly/ro-{health,ls,permit-ls,inspect,plugins,
provider-ls}.sh`, `run-all.sh`, `changelog.d/d1-contracts.md` (after PR 190).
Interface: `lib/common.sh` exports `die`, `verdict`, `require_isolated`, `isolated_up NAME`, `isolated_down NAME`,
`pj` (`paseo --home "$PASEO_HOME"`), `record_result`.
Accept: each `ro-*` script exits 0 on the live daemon and prints one bounded JSON line; `require_isolated`
exits 2 when run with the live home, with `PASEO_HOME=~/.paseo`, and with a copied home (three negative cases).

### T2. Isolated test daemon (D1.7, B10; blocks T4 to T10)

Files: `lib/common.sh` (`isolated_up/down`), `isolated-smoke.sh` (SCOPE `second daemon only`).
Do: fresh `PASEO_HOME` under `$TMPDIR/ade-acc-<id>`, Unix-socket listener, password, no `session-janitor`, no
herald, no telegram. Needs one provider credential path: either the cheapest provider already logged in under
the real home (read-only reference, never copied wholesale) or a probe-only account (question 2).
Accept: `paseo --home <fresh> status` reports its own `serverId`, different from `srv_3QHQeiJniWBD`; the live
daemon's pid, `startedAt` and `paseo ls` count are unchanged before and after (the script asserts this).

### T3. D0.2 drain scripts (`tests/paseo-acceptance/drain/`) (depends on PR 177 for item b; blocks every "disable")

Files: `drain/README.md`, `drain/herdr-sleeper-list.sh`, `drain/acp-dispatch-auto-resume.sh`,
`drain/relay-pending.sh`, `drain/worktrees-clean.sh`, `drain/bigteam-inboxes.sh`, `drain/check-disabled.sh`
(V6).
Do: one script per tool being disabled; each prints a record (`tool`, `held`, `evidence`) and exits 1 when it
holds anything. `check-disabled.sh TOOL` implements the three checks of V6: skill not linked in any
`skill-everywhere` target, `launchctl print gui/$UID/<label>` failing, bin entry exiting non-zero with a
"retired" message; a check that cannot run exits 77 and counts as "not disabled".
Accept: each script run against today's state either reports its held items or an empty record, never a crash.
Not executed by this prep slice (they read launchd and relay state; draft only).

### T4. D1.1 Steer-while-running matrix

Files: `d1-01-steer.sh` (SCOPE `DESTRUCTIVE: second daemon only`: a non-steer provider's turn dies).
Do: per provider in C2's "available" list (claude, codex, copilot, opencode, omp, cline, grok, cursor,
glm-acp-agent, hermes, qwen-code; antigravity recorded "no steering" without a probe), start an agent on a task
that runs 60 s (a `sleep`-bearing shell tool call), send `paseo send --behavior steer` carrying a marker, then
inspect the timeline (`paseo logs`) for: turn survived, marker delivered as the next input, no interrupt entry.
Output: `steer-matrix.json` with `provider -> {steers, queues, interrupts, evidence}`.
Accept: every provider has a verdict; a provider that interrupts is "queue only" and goes into G3's table
(`config/ade-providers.toml`, name proposed, question 11).
Cost: one short paid turn per provider; run the cheapest model per provider (question 2).

### T5. D1.2 Card option answers

Files: `d1-02-card-option.sh` (SCOPE `second daemon only`).
Do: a claude agent in a mode that asks, prompted to use `AskUserQuestion` with two options; a second agent (the
parent, a plain `paseo` caller) answers option 2 through the surface a parent uses. The CLI has only
`permit allow|deny [--input json]`, so the probe tries (a) `permit allow --input '{"answers":...}'` and (b) the
MCP tool `respond_to_permission` through `mcp` from an agent (`MCP_STEP` branch, needs the tool catalog).
Accept: the agent's next turn shows the chosen option's text. If neither works, B3 and G4 are redesigned
(cards go to the operator): the probe prints that consequence.

### T6. D1.3 Archive rescue and the `paseo.json` teardown (blocks D2's gate; the largest task)

Files: `bin/ade-rescue-worktree` (the teardown body; Python, stdlib, argv lists only), `config/paseo-teardown-repos`,
a template `paseo.json` teardown snippet (`docs/d1-teardown.md` section or `config/paseo.json.example`),
`d1-03-archive-rescue.sh` (SCOPE `DESTRUCTIVE: second daemon only`), `d1-03b-teardown-failure.sh` (same).
Interface: `ade-rescue-worktree --repo NAME --branch B --worktree PATH [--remote NAME] [--dry-run] [--json]`.
1. Bundle: `git bundle create <dir>/branch.bundle <branch>` (plus `--all` of the worktree's unmerged commits).
2. Stash commit of tracked changes: `git stash create` into a ref `refs/rescue/<branch>` bundled too (a stash
   commit with no ref is unreachable; the ref is what the bundle carries).
3. Tar of untracked, non-ignored files: `git ls-files -z -o --exclude-standard | tar --null -T - -cf`.
4. All three written to a temp directory beside the final one then renamed (`os.replace`), directory mode 0700,
   under `~/.local/state/ade/rescue/<repo>/<branch>-<date>/`.
5. Only after the local rescue succeeded: push `rescue/<branch>-<date>` carrying the stash commit's tracked
   changes (never the untracked tar) to the private remote; a push failure exits 0 with `pushed:false` (the
   local rescue stands) and is logged.
Accept (the D1.3 expectations): on the isolated daemon, archive the last agent of a dirty worktree workspace with
one unpushed commit; the three artifacts exist and `git bundle verify` passes **before** the worktree is gone
(the probe polls for the worktree's removal and compares timestamps); repeat with the remote refusing the push:
the local rescue still exists; record (`d1-03.json`) whether a failing teardown stops Paseo removing the
worktree, and `session-janitor`'s current mode. If anything is lost: no slice moves to Paseo workspaces.
Also: `config/paseo-teardown-repos` lists the repos slices may target (question 11), and the G2 refusal check is
D2's, not D1's.

### T7. D1.4 Archive a parent with a running child

Files: `d1-04-archive-parent-child.sh` (`DESTRUCTIVE: second daemon only`).
Do: parent creates a child through MCP `create_agent` (agent-scoped, so lineage is set), child runs a 60 s task,
`paseo archive <parent>`; poll the child. Repeat after `paseo agent detach <child>`.
Accept: child survives archive of the parent (status still `running`, finishes). If not, successors stay
top-level permanently (C1); record whether `detach` changes the outcome.

### T8. D1.5 Daemon restart keeps queued prompts, pending `notifyOnFinish` and schedules

Files: `d1-05-restart-persistence.sh` (`DESTRUCTIVE: second daemon only`).
Do: set up one of each (queued send to a busy agent, `create_agent` with `notifyOnFinish`, `paseo schedule create`),
`paseo --home X restart`, then diff: queue survives, the finish notification arrives once, the schedule exists
and fires. Accept: none lost; else G1 and G3 persist and reconcile themselves (their designs already say so).

### T9. D1.6 Schedule behaviour across sleep, and the janitor settings location

Files: `d1-06-schedule-missed-run.sh` (`DESTRUCTIVE: second daemon only`; needs `pmset sleepnow` or an
`caffeinate`-free manual step: SEMI-MANUAL), `d1-06b-janitor-settings.sh` (read-only in an isolated home with the
janitor installed and `session-janitor` writing its settings: finds the file and key names).
Accept: a schedule due during sleep is run once on wake, never, or many times (record which); if lost, F2 keeps
those jobs on launchd. The settings probe feeds the B4.3 assertion in `bin/paseo-watchdog`.

### T10. D1.7a Tab creation paths

File: `d1-07a-tabs.md` (a checklist, not a script: needs Desktop). Per creation path (`paseo run`,
MCP `create_agent`, a schedule run, Telegram) record whether a tab appears and whether `paseo agent open`
creates one. Because only the live Desktop shows tabs, this runs on the **live daemon with one throwaway agent in
a drained window and djbclark's yes** (question 12), or Desktop connected to the second daemon as a host
(`paseo host add`), which needs no yes. Accept: a table of path -> tab yes/no.

### T11. D1.7b Create origin, and the reopen hook (V3)

Files: `fixtures/origin-probe-plugin/` (a ~40-line plugin that logs the `agent.create.before` and
`agent.open.before` payloads to a file; SDK names unverified, marked `TODO: confirm against plugins_hooks.md`),
`d1-07b-create-origin.sh`, `d1-10-reopen-hook.sh` (both `second daemon only`).
Do: create agents by UI-equivalent (plugin SDK / RPC is not scriptable: record N/A), CLI `paseo run`, MCP
`create_agent`; diff payloads for any origin field. For V3: create, archive, reopen (`reopen-archived`'s path or
the `paseo` reopen call) and resume the same agent; record whether `agent.open.before` fires each time.
Accept: a written answer for G2.8 ("signal exists: <field>" or "none") and for G1's orchestrator list
("catalog recomputed on reopen: yes/no"). If no, the registration flow (V3) cannot be create, merge id, reopen;
G1 then needs the list read at `jobs.submit` time instead.

### T12. D1.8 vps-primary security prerequisites (needs djbclark's yes; touches `~/ops`, order 11)

Files: `d1-08-vps-security.sh` (`READ-ONLY` against vps-primary: ssh `ps`, `ss`, `id`, `ls -l`, and one
unauthenticated HTTP request from the Mac; refuses unless `--i-know-it-is-the-pilot-host`), `docs/d1-vps-primary.md`
(the NixOS change as a **proposal**, not applied).
Do (proposal): daemon password, listener on the tailnet interface only, Tailscale ACL admitting the Mac, pilot
agents under a dedicated unprivileged user with its own `PASEO_HOME` and no deploy keys, credentials in
sops/agenix or `sudo-secretspec`, upgrade 0.13.0 to the pushed `master` head through `deploy-vps-primary`.
Accept: from a second tailnet node an unauthenticated request is refused; `ps` shows the daemon and pilot
agents under that user; that user cannot read deploy keys or other services' secrets.

### T13. D1.9 Dead-man check (depends on T12; design in section 7)

Files: `deadman/write-heartbeat` (forced command), `deadman/deadman-check`, `deadman/mac-heartbeat-sender` (called
by the watchdog), `deadman/sleep-hook.md` (sleepwatcher option), `d1-09-deadman.sh` (four scenarios, run on the
vps-primary pilot user or a local Linux container, never against production heartbeat files).
Accept: the four expected outcomes in D1.9 (sleep: no page; daemon killed while awake: page; network cut while
awake: page; wake hook failed and then network cut: page), and from vps-primary an authenticated Paseo call to the
Mac is impossible.

### T14. D1.7 B9 watchdog (design in section 6; draft already in `bin/paseo-watchdog`)

Files: `bin/paseo-watchdog`, `launchd/com.djbclark.paseo-watchdog.plist` (not installed), `d1-07-watchdog-fire.sh`
and `d1-07c-watchdog-soak.sh` (both `DESTRUCTIVE: second daemon only`), `tests/paseo-acceptance/watchdog-selftest.sh`
(fake `paseo` on PATH; no daemon; safe, but still not run by this slice because the lead runs tests through `bg`).
Accept: fires on a forced hang of the isolated daemon (a SIGSTOP of its worker) and does not restart a healthy
daemon during a forced load incident (a CPU burner raising load above the core count for 10 minutes): zero
restarts, alerts only after two misses.

### T15. Notifications check (F1)

File: `d1-11-push-off-tailnet.md` (manual): the Mac daemon runs with the Paseo relay off, push goes to Expo
directly; verify with the phone off the tailnet that a finished-agent push arrives. Accept: yes or no recorded.

### T16. Plan amendments D1 must carry (docs only; one commit in the D1 PR)

Edits to `docs/paseo-only-rearchitecture.md` for V2, V3, V4, V5, V6 as in section 5, plus the "CLI 0.15 / daemon
0.14" and "`herdr-harness` enabled" corrections, plus this file linked from section D1. Adversary reviews the PR;
the plan's own "docs move with the code" rule (review rule 8) is why they ride along.

## 5. Adversary r7 findings V1 to V6 mapped to tasks

| Finding | Carried by | What D1 does | Check |
|---|---|---|---|
| V1 `deleteHelpers` can be flipped from herald's settings screen; the assertion races a restart | T14 (watchdog), T16 | Watchdog runs the B4.3 assertion (`--assert-b43`) **before** any restart or reload and refuses to restart when it fails (alert only); G2.8 text names the settings-screen toggle | `watchdog-selftest.sh` case `b43-fail-blocks-restart`: assertion fails, 3 misses, load low: still no restart |
| V2 herald check host scope; remote `$PASEO_HOME` unreadable | T14, T12, T16 | Assert `deleteHelpers:false` only on hosts whose parsed `plugin ls` lists herald (enabled or not); a host without herald passes; for vps-primary the pilot user's `PASEO_HOME` and the read route (`ssh <pilot-user>@host cat $PASEO_HOME/plugin-data/herald/config.json`) are named in `docs/d1-vps-primary.md` | selftest cases `herald-absent-passes`, `herald-flag-true-alerts`, `herald-file-missing-alerts` |
| V3 new orchestrator cannot get `jobs.submit`; refire unknown | T11, T16 | Probe `d1-10-reopen-hook.sh` answers whether `agent.open.before` refires on reopen or resume; plan amendment names the repo (djbclark-ade), a promoted copy or `git fetch` + `git show` in a named reference checkout, and the flow create, merge id, reopen; the matching D2 case ("newly registered orchestrator gains `jobs.submit` after reopen, unregistered does not") is added to D2's gate list | probe verdict in `d1-10.json`; D2 gate text diff |
| V4 empty `plugin ls` output counts as "absent" | T14, T12 | Empty output accepted only while the host runs 0.13 (`paseo -v` or `daemonVersion` below 0.14, janitor cannot be installed); otherwise a header row (table) or valid JSON array (`--json`) is required; the watchdog parses `plugin ls --json` and treats unparseable or empty-on-0.14 as a failed check (alert) | selftest cases `plugin-ls-empty-014-alerts`, `plugin-ls-empty-013-passes` |
| V5 D6 skip lists name only three tools; tests and fixtures hit | T16 | Amend D6 so both skips are **definitions** with non-exhaustive examples ("tools a committed drain record shows disabled in D4 or D5", "test code and fixtures that load, fixture or assert on session-finder's modules"); each exempted file goes on the committed triage list; `tools/acp-run/acp-run:499` comment edited | `drain/check-disabled.sh` lists the exempt set; D6's search script (D6, not D1) consumes the triage list |
| V6 "still disabled" has no check | T3, T16 | `drain/check-disabled.sh TOOL` runs the three checks (skills unlink, `launchctl print` fails, bin exits non-zero with "retired"); the D4 drain record names the act and the check per tool; an unrunnable check counts as "not disabled" | `drain/check-disabled.sh --self-test` against a stub |

## 6. B9 watchdog: design (`bin/paseo-watchdog`)

Purpose: detect a hung or dead local Paseo daemon from outside it, alert, and restart only under B9's conditions.
Runs as a launchd agent every 60 s with `--once`; all state is a small JSON file so each pass is stateless.

1. **Probes per pass** (both always run, both bounded): (a) `GET <base>/api/health` with a 5 s timeout expecting
   `{"status":"ok"}`; (b) `timeout 20 paseo ls --json` expecting rc 0 and a JSON array. A pass is **healthy only if
   both pass**; a health-ok / RPC-timeout pass is a miss tagged `rpc-starved` (#2753), the reverse `health-down`.
   `--home` and `--host` select the daemon, so the soak and fire probes point at the isolated daemon.
2. **State** (`--state-dir`, default `~/.local/state/ade/watchdog/`): `{consecutiveMisses, lastOkAt,
   lastRestartAt, alerted, downSince, lastReason}`, written atomically; an unreadable file is treated as zero
   misses and logged (never as a licence to restart).
3. **Policy**, in order, each pass: record the load average and core count with every miss; on **2** consecutive
   misses alert once (`hermes-ping "paseo-watchdog: ..."`, argv list, never a shell string) and capture
   diagnostics (`sample <pid> 5` of the daemon pid from `paseo.pid`, the last 200 lines of `daemon.log` matching
   `eventLoopDelay`, `uptime`, `ps` rows for the daemon) into `diag/<UTC>/`, mode 0700; **diagnostics come first**.
   On **3** consecutive misses, restart only if all of: `--allow-restart` was passed (default off, see DECIDED
   below); load average (1 min) below the core count; the last restart older than 30 minutes; the **B4.3
   assertion passes** (V1); the live-workspace count and G1 reconcile hook (`--reconcile-cmd`, absent until D2)
   present or explicitly waived by `--no-reconcile`. Otherwise alert "not restarting: <reason>" and wait for the
   operator. After a restart, run the reconcile command, ping "recovered", clear state.
4. **B4.3 assertion** (`--assert-b43`, also callable alone as a read-only check, rc 0 pass, 1 alert, 77 cannot
   run): parse `plugin ls --json`; if `session-janitor` is listed and enabled, require `archiveChildren`,
   `deleteChildren`, `deleteMain` all explicitly false (found by searching the janitor's plugin-data files and
   the `plugins` subtree of `config.json` for the key names; **absent keys count as the dangerous default true**);
   if herald is listed (enabled or not), require `$PASEO_HOME/plugin-data/herald/config.json`
   `cleanup.deleteHelpers is False` (missing, invalid or non-boolean alerts; a host whose list lacks herald
   passes, V2); empty or unparseable `plugin ls` output alerts on a 0.14+ daemon and passes on 0.13 (V4); when
   `--expect-plugin ade-gate` is given, also require it `running` (G2.5). It runs on every pass, not only before
   a restart, and alerts (rate-limited to once per 6 hours per distinct failure) on its own.
5. **Heartbeat to vps-primary** (`--heartbeat-cmd ARGV...`, off by default): after each pass, pipes
   `{"ts":..., "health":bool, "rpc":bool, "misses":n, "host":"mac"}` to the forced command (section 7). A failed
   heartbeat write is logged and never changes the probe verdict.
6. **Safety**: no secrets read; no shell; every subprocess has a timeout and is killed with its process group;
   the script refuses `--allow-restart` when `--home` is the live home unless `ADE_WATCHDOG_LIVE=1` is also set
   (so a mistyped soak cannot restart the live daemon). `--dry-run` never pings, restarts or writes outside
   `--state-dir`.
7. **Restart command** is `--restart-cmd` (default `paseo restart`). The live daemon is `desktopManaged: true`,
   so whether `paseo restart` is the right path (versus relaunching the Desktop app's managed worker) is measured
   in T14's fire probe on the isolated daemon first, and is open question 4.
8. **launchd**: `launchd/com.djbclark.paseo-watchdog.plist`, `StartInterval 60`, `RunAtLoad`, log files under
   `~/.local/state/ade/watchdog/`, `Nice 10`; **not installed** (installing is a lead action after the soak).
9. **Cost**: two CLI starts per pass is about 2 s of CPU a minute; the Electron-helper start-up the
   `paseo-bypass-watch` header measures (about 3 s) makes 60 s the floor, 30 s is not used.

DECIDED (this prep): restart is **alert-only by default** (`--allow-restart` is opt-in, enabled by the lead only
after T14's soak passes); a conservative choice, easily flipped.

## 7. D1.9 dead-man check on vps-primary (design)

1. **Mac side** (inside the watchdog, `--heartbeat-cmd`): `ssh -i <dedicated key> -o BatchMode=yes -o
   ConnectTimeout=10 <pilot-user>@vps-primary` with the forced command; the key is a dedicated one, never an agent
   or login key. The sleep/wake hook (`sleepwatcher` `~/.sleep` and `~/.wakeup`, or an equivalent launchd agent
   on IOKit power events) calls the same ssh with `sleep` and `wake` verbs on stdin JSON.
2. **vps-primary side**: `authorized_keys` line `restrict,from="<Mac tailnet IP>",command="/path/write-heartbeat"`
   (no `SSH_ORIGINAL_COMMAND`); `write-heartbeat` reads at most 4 KB from stdin, parses JSON, validates fields
   (`kind` in `heartbeat|sleep|wake`, `ts` integer, `health`/`rpc` booleans), then replaces exactly
   `heartbeat.json` and `sleep.json` atomically. A `heartbeat` write deletes a `sleep` marker older than itself;
   a `wake` deletes the marker. A `sleep` marker is honoured only while newer than the last heartbeat.
3. **`deadman-check`** (systemd timer, every 5 minutes, no Mac credential, never calls the Mac): pages through
   `hermes-ping` (credential in D1.8's secrets mechanism) when: the heartbeat is stale (default 15 minutes) with
   no current sleep marker; the latest heartbeat reports `health:false` or `rpc:false`; or a current sleep marker
   is older than `--max-sleep-hours` (default 72). Pages are rate-limited and a recovery page follows.
4. Mac daemon stays bound to `127.0.0.1`; nothing on vps-primary can authenticate to it.

## 8. Gate for D1 and what D2 inherits

D1 ends when every probe has a verdict record, every failed contract's consequence is resolved (printed by the
probe, written into the plan), and: the drain scripts exist; the B4 teardown and rescue pass T6; the watchdog
passes T14 and, with the dead-man check, T13; the vps-primary prerequisites pass T12. D2 then starts. Carried to
D2: V3's extra gate case, the `config/orchestrators` read rule, the janitor mechanism choice (needs T9's finding),
G3's provider table (T4), G2.8's create-origin answer (T11).

## 9. Open questions for djbclark (one sentence each)

1. May the isolated test daemon on the Mac listen on a Unix socket under `$TMPDIR` (preferred), or must it claim a port in `site-djbclark/registry/ports.yml`?
2. Which providers and models may the steer matrix (T4) spend real tokens on, and with what budget (about one short turn each, 11 providers)?
3. Should the watchdog stay alert-only until its soak has passed once (the draft's default), or restart from day one?
4. The live daemon is Desktop-managed: is `paseo restart` the sanctioned restart path, or must the watchdog relaunch the Desktop app's worker?
5. Which Paseo version does vps-primary upgrade to (today's Mac CLI is 0.15.0-beta.1, daemon 0.14.0, plan says 0.14)?
6. What is the pilot user's name on vps-primary, and may a session propose the NixOS change in `~/ops` (order 11)?
7. Where does `session-janitor` keep `archiveChildren`, `deleteChildren` and `deleteMain` (none found in `config.json` or its `state.json`), and who sets them before D2?
8. `herdr-harness` is enabled and running on the Mac although the plan says disabled: disable it, or amend the plan?
9. May `sleepwatcher` (brew) or a launchd power-event agent be installed on the Mac for the sleep/wake hook?
10. Should CI run `shellcheck` over `tests/paseo-acceptance/` and `bin/paseo-watchdog`, and is a Python selftest under `bg bin/pytest` wanted for the watchdog logic?
11. Which repos go in `config/paseo-teardown-repos`, and is `config/ade-providers.toml` the right home for G3's steer/queue table?
12. May tab probe T10 run on the live daemon in a drained window with one throwaway agent, or only against Desktop attached to the second daemon?

### Decisions (2026-11-01)

Answered by djbclark in a `/steps` walk (E2, E3, E4, E6, E8, E9, E12); the rest decided by the lead (1e61c979) under standing rules.

1. Unix socket under `$TMPDIR`: no port claim is needed for a socket (lead; the ports registry covers TCP binds).
2. All providers with quota that day, cheapest model each, about one short turn each (djbclark). Copilot is skipped while its monthly quota is exhausted.
3. Alert-only until the watchdog's soak has passed once on the isolated daemon; a hang pages djbclark until then (djbclark).
4. Restart path: `paseo restart` first; if the daemon is not healthy after it, relaunch the Desktop app (quit Paseo.app, open it). D1 verifies `paseo restart` on the Desktop-managed daemon once, in a drained window with djbclark's yes (djbclark).
5. vps-primary upgrades to the latest released Paseo at the time, as everything tracks latest (lead; `~/AGENTS.md` item 5).
6. Delegated to the lead (djbclark: "do whatever you want here; I don't need to review; test several things; consult a frontier model"): the lead picks the pilot user's name and drafts and deploys the NixOS change in `~/ops` after trying options and a `frontier` consult. This is djbclark's yes under order 11 for that change; deploys still run only from the pushed branch head (`~/AGENTS.md` item 36).
7. A fact to find, not a decision: D1 locates where `session-janitor` reads `archiveChildren`, `deleteChildren` and `deleteMain` (its source), and the lead sets them before D2 (lead).
8. `herdr-harness` stays enabled; the plan text is amended to match (djbclark; plan table and section A8.2 changed in this branch).
9. Install `sleepwatcher` (brew), tracking latest, with the hook scripts in D1, and add it to `docs/apply-toolchain-prompt.md` (djbclark).
10. Yes to `shellcheck` in CI over `tests/paseo-acceptance/` and `bin/paseo-watchdog`, and a hermetic Python selftest for the watchdog logic run through `bg bin/pytest` (lead).
11. The lead drafts the teardown repo list in `config/paseo-teardown-repos` and keeps G3's table in `config/ade-providers.toml`; both are reviewed in the D1 PR (lead).
12. Tab probe T10 runs only against Desktop attached to the isolated second daemon, never the live daemon (djbclark).
