# D0.2 drain scripts (plan task T3, `docs/d1-implementation-plan.md`; run live 2026-11-02)

One script per tool about to be disabled in D4/D5. Each prints **one bounded JSON line** (`tool`, `held`, `evidence`,
optional `notes`; at most 25 evidence lines of 220 characters, `evidence_truncated` counts the rest) and exits:

| Exit | Meaning |
|---|---|
| 0 | nothing held: the tool is drained |
| 1 | it holds something (`held` > 0): the disable waits |
| 77 | the check could not run (`held` is `null`, `cannot_run` says why): counts as **not drained** |

All are read-only: they read launchd, relay, git and state files and never unload, disable, delete, kill or send.
bash with `set -u`; the JSON and every subprocess call (argv lists only, `subprocess.run`) live in `drain_common.py`.
macOS and Linux; no BSD-only tool. Run them one at a time at D0.2 and keep the output in the D4 drain record.

| Script | Drains | Reads | Held means |
|---|---|---|---|
| `herdr-sleeper-list.sh` | herdr-sleeper, agent-sleep | `~/.local/state/herdr-sleeper/sleeping.json` and `sessions/*/sleeping.json` (not `herdr-sleeper list`: it runs `heal_watcher()` first, which can start the watcher) | one line per sleeping/orphaned entry: each holds a Claude session UUID to wake or resume as a Paseo agent |
| `acp-dispatch-auto-resume.sh` | acp-dispatch auto-resume | records `jobs/*.json` and `*/jobs/*.json` under `~/.local/state/bigteam`, plus `launchctl print` of each pending label | an unclosed record with `auto_resume.state` scheduled / waiting-headroom / resuming |
| `relay-pending.sh` | session-finder relay (D6) | `relay.py --pending --json` of the main checkout (its bounded ack collection is the same one every listing runs; it sends, cancels and retires nothing) | a queued/sending message, or an `open` ack expectation (`OVERDUE`, `ASSUMED LOST` flagged); `failed`/`expired` are final and only counted in `notes`. Per-record detail: `relay.py --status ID` (changes nothing) |
| `worktrees-clean.sh [REPO...]` | herdr, Orca, cow-workspaces worktrees | `git worktree list`, `git status --porcelain`, `git rev-list --count HEAD --not --remotes` with `GIT_OPTIONAL_LOCKS=0` | `dirty PATH` or `unpushed PATH` (commits no remote has); a pushed branch is not held. Default repo: `~/src/djbclark-ade` |
| `bigteam-inboxes.sh` | bigteam inbox path | `*/jobs/NAME.inbox.md` against `NAME.replies.md` | a `## MSG N` with no `REPLY N:` |
| `check-disabled.sh TOOL ...` | V6 "still disabled" | skill dirs, `launchctl print gui/$UID/LABEL`, the bin entry | see below |

## `check-disabled.sh TOOL [--label L] [--bin PATH] [--skill-dir DIR]...`

The three checks: (1) skill `TOOL` is not linked (a dangling symlink counts) in any `skill-everywhere` target dir (default list:
`bin/skill-everywhere` lines 57-71; `--skill-dir` replaces it); (2) `launchctl print gui/$UID/LABEL` fails; (3) the bin entry exits non-zero
**and** says "retired". Exit 0 all three hold; 1 any shows it live (`live` lists which); 77 a check cannot run and nothing is live
(no `--label` or `--bin`, bin missing, no `launchctl`). The bin is executed with no arguments and stdin `/dev/null` under a 15 s limit,
and only when checks (1) and (2) found nothing live. `--self-test` runs seven cases against a temp stub and a label that does not exist.

Not wired into CI or `run-all.sh`: they read the operator's live state.
