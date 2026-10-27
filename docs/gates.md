# Claude quota gates: `config/gates.toml` and temporary profiles (2026-10-26)

Two scripts turn the Claude quota into a level that sessions act on. Before 2026-10-26 their numbers were code
constants (plus a launchd env var with no expiry). They now live in a versioned file, and a **profile** can loosen
them for a bounded time (a planned absence) without anyone editing code, an env var or a plist.

| piece | what |
| --- | --- |
| [`config/gates.toml`](../config/gates.toml) | the baseline (the current values), the floors a profile may not cross, and the profiles (`away`, a draft) |
| [`bin/ade_gates.py`](../bin/ade_gates.py) | the loader the scripts call: `load_gates(gate, now, defaults) -> (thresholds, info)` (gates `governor`, `quota_guard`, `frontier`) |
| [`bin/gate-profile`](../bin/gate-profile) | the CLI: `status [--json]`, `show`, `diff`, `validate`, `set`, `clear` |
| `~/.local/state/ade/gate-profile.json` | the active profile (env `GATE_PROFILE_STATE`); audit log `gate-profile.log` beside it (`GATE_PROFILE_LOG`) |

The gates: [`bin/claude-fleet-governor`](../bin/claude-fleet-governor) (`[governor]`, launchd every 300 s, downshifts
Opus/Fable agents to Sonnet at tight/critical) and [`bin/claude-quota-guard`](../bin/claude-quota-guard)
(`[quota_guard]`, launchd every 15 min, feeds `claude/hooks/quota_nudge.py`; the governor also reads its level). A profile
never changes a code path, only these numbers.

## Precedence

Lowest to highest: the script's `THRESHOLDS` (code default, the fail-safe) < `[governor]` / `[quota_guard]` in `gates.toml`
< the active profile < env JSON (`CLAUDE_GOVERNOR_THRESHOLDS`, `CLAUDE_QUOTA_GUARD_THRESHOLDS`; tests and emergencies, no
floors, bad input is an error: governor exit 12, guard exit 64). The baseline must equal the code defaults: `tests/test_gates.py`
and `bin/gate-profile validate` fail on drift, so change a number in both places in one commit. At run time the baseline is
guarded too (below), but only for keys with a `[floors]` entry: the file may tighten such a code default, never loosen it. A key
with no floor entry (a timing, age, lock or exhaustion-window key) is not guarded at run time and takes the file's value.

## `gates.toml`

`[meta]` (`schema = 1`, `max_profile_hours = 240`), the two baseline tables with every key commented (meaning, unit),
`[floors.<gate>]`, `[profiles.<name>.<gate>]`. A floor is `key = { loosen = "lower" | "higher", bound = N }`:

| key kind | looser is | profile value must lie in |
| --- | --- | --- |
| `*_left*`, `*_weekly`, `critical_five_hour`, `watch_fable` (percent left) | lower | `[bound, baseline]` |
| `tight_projected` (projection at reset) | higher | `[baseline, bound]` |
| `conserve_alert_level` (a level: 0 ok, 1 watch, 2 tight, 3 critical) | lower | `[1, 2]` (bound 1 = watch) |
| `frontier1_judged`, `frontier2_judged`, `frontier*_per_wave`, `frontier1_agent_calls_per_day` (a count or 0/1 switch) | higher | `[baseline, bound]` |
| `frontier*_min_left` (percent left) | lower | `[bound, baseline]` |
| every timing, age, lock and exhaustion-window key | not overridable | (unlisted: a profile that sets one is rejected) |

Bounds (2026-10-26): no trigger below 3% left (the aiuse collector is hourly, the guard runs every 15 min, a 5-hour window
can burn ~25 points between readings), `tight` triggers keep a margin above the `critical` ones, `tight_projected` up to 1000.

## Profile lifecycle

`bin/gate-profile set away --for 72h --reason TEXT` (or `--until 2026-10-29T21:00:00Z`) validates, refuses a window over
`max_profile_hours` or in the past, writes `{"schema":1,"profile":"away","since":...,"until":...,"reason":...,"set_by":...}`
atomically, appends a JSON line to the audit log, sends one `hermes-ping`, then runs `claude-fleet-governor run` and
`claude-quota-guard check` so the effect is immediate (all soft-fail). `clear` does the same and removes the file. Ends
by itself at `until`; the next governor or guard run sends ONE ping ("away profile expired, baseline restored"), records
`expired_notified` in the file and leaves it in place as the audit trail, ignored. Both scripts' state files and `status --json`
carry `profile` (`{"name","until"}` or null); the governor's change ping adds `[gate profile away until ...]`.
`claude-quota-guard`'s human line shows the profile too. `route_agent.py governor_hold()` and the hooks read the
governor's or guard's `level`, which is computed from the active profile, so they follow with no change.

**Daily nudge (2026-10-26, by script, never a recurring model prompt).** While a profile is active, the first governor
`run` (launchd, every 300 s) of each America/New_York calendar day sends ONE `hermes-ping`: "away profile active until Thu Oct 29
12:00 PM EDT, 2 days left; restore normal routing now: gate-profile clear (stay longer: gate-profile extend --for 24h)". The
day is the New York date (a DST day is 23 or 25 h), recorded as `last_daily_nudge` in the profile file under the state flock, so
a restart, a second run or the guard never repeats it; `set` records its own day (its ping is that day's nudge); the day the
profile expires gets the expiry ping instead; no profile, no ping; `check` and `--dry-run` send nothing. A failed ping is not
recorded and is retried by the next run. `status` shows the next nudge, and the guard's state carries `profile`, so
`claude/hooks/quota_nudge.py` prints one line "[gates] away profile active until <time>; gate-profile clear restores normal
routing" per session per New York day (any level) while the profile is unexpired.

`gate-profile extend --for 24h` moves `until` later (audit line, ping, recompute). It obeys the same cap as `set`: `until` minus
the original `since` stays within `max_profile_hours`, and it refuses an expired or ignored profile (`clear` and `set` a new
one instead).

After every `set`, `extend` and `clear` the order is: ping, then the guard's recompute, then the governor's run, so the governor (the actor) reads the
guard's fresh level and never downshifts or hands off on the thresholds the change just replaced (Codex P2 on PR 84).

## Fail-safe: when a profile is ignored (baseline applies, `status` says why)

File missing, unreadable, a symlink, FIFO, directory or over 64 KiB, not a JSON object, `schema` not the integer 1 (not `true`,
not `1.0`); `until` or `since` missing, naive, or not offset zero; `profile` not `[a-z0-9_-]` (ASCII, 32 characters at most);
`until` at or before now (the profile ends exactly at `until`); `since` in the future; `until <= since`; window over
`max_profile_hours`; unknown profile name; any key not under `[floors]`, any value tighter than the baseline, below a
`lower` bound or above a `higher` bound, on EITHER gate (the whole profile is rejected, never clamped, so the governor and the guard
always agree); a profile whose applied values break an ordering: guard `watch_weekly >= tight_weekly >= critical_weekly`,
governor `tight_left_weekly >= critical_left` and `tight_left_five_hour >= critical_left` (`validate` also checks the baseline);
`gates.toml` missing or unparsable (code defaults apply, logged once to stderr). A number too large for a float (an integer of 400
digits) is not a number anywhere: baseline, profile, `max_profile_hours` (then the 240 h default), profile file or env JSON
(a `GateEnvError`, the existing bad-env path); none of them can crash a gate.

## Locking, file reads and run-time guards (2026-10-26, after adversary round 1)

**Lock.** `~/.local/state/ade/gate-profile.json.lock` is an flock that serialises every WRITER of the profile file: the governor's
and guard's expiry and daily notices (held across their `hermes-ping`, up to 60 s) and `gate-profile set`, `extend` and `clear`
(held only around their read and write or unlink, never around their ping and recompute: those run the governor, which takes the
same lock). Readers (the gates' `load_gates`, `status`, `show`, `diff`) never take it, so a ping in flight never delays a
threshold; writes are atomic replaces. Bounds: a CLI command waits at most 120 s (two 60 s pings back to back; env
`GATE_PROFILE_LOCK_WAIT` shortens it for tests), then exits 1 with "the profile lock is still held ... nothing changed, try
again in a minute". The governor and guard wait at most 10 s, then skip that notice; nothing was marked, so the next run
(5 min, 15 min) retries it. So a ping holding the lock cannot starve a gate run: the worst it costs the governor is 10 s before
it writes its level, and launchd never starts a second instance of a running job. (`claude-fleet-governor` has no run lock of
its own, so a manual `run` during a launchd run can overlap: unchanged, not made worse.) A notice's failed-ping restore is a
compare-and-restore: the mark is taken back only while the file still holds exactly the marked text, so a profile cleared or set
again by a writer that did not wait (an older `gate-profile`, a hand edit) is never brought back or overwritten. A lock file that
is a symlink, FIFO or other non-regular file counts as no lock and nothing blocks on it: the notices skip and name the lock path
once on stderr (so they stay off until it is removed), `set` and `extend` refuse naming it, and `clear` goes on without the lock
(no writer can hold that lock either) after naming it, so a profile can always be cleared.

**Baseline guard.** `load_gates` replaces a `gates.toml` baseline value with the code default when the key has a `[floors]` entry
and the file's value is looser in that direction (lower for a "percent left" key, higher for `tight_projected`), logs it once to
stderr and lists it in `info["baseline_guarded"]` (`status` prints it). So git can tighten a number without touching code but a
loosening needs a profile (expiring, floored, pinged). Keys with no floor entry (timings, ages, locks) take the file's value at
run time; `validate` and `tests/test_gates.py` still fail on ANY drift, tighter or looser. Profile validity is judged against the
file's baseline, the same verdict in both gates.

**Profile file reads.** `O_RDONLY|O_NONBLOCK|O_NOFOLLOW|O_CLOEXEC`, `fstat` must say regular file, at most 64 KiB (a real one is
about 400 bytes). Anything else is the baseline with the reason in `status`. DECIDED: a symlink is refused, even to a valid file:
`gate-profile set` writes by atomic rename (it replaces a link with a regular file), nothing in this toolchain creates a link
there, and a link is how a FIFO or `/dev/zero` would be slipped in. A symlinked parent directory is still followed.

**Accepted, as designed.** Env JSON has no floors and beats a profile (setting it needs the launchd plist or the Ansible role, which
is control of the code already). `set` is mark-before-ping, so a SIGKILL between the mark and the ping loses that day's nudge (the
next day still nudges) or the expiry ping; a failed ping that returns normally is restored and retried on the next run. A
governor profile whose `tight_left_weekly` sits at its floor of 8 while a drifted baseline keeps `critical_left` looser is judged
against the file's baseline (see above); the effective order can then fire critical first, which is stricter, never looser.
`--reason` is limited to 500 characters and `--by` to 64 (the file is read back with a 64 KiB cap); the `set` ping carries one
printable line, the reason clipped to 120 characters and `--by` to 40. After `clear`, if the guard recompute fails, the file is
gone and the gates are at baseline; the quota hook may keep printing its `[gates]` line until the next guard run, and `clear` says so.

## Worked example: three days away

```
bin/gate-profile validate                      # gates.toml ok: baseline equals the code defaults; profiles: away; max 240 h
bin/gate-profile diff away                     # baseline -> away, changed keys only; edit gates.toml first if the draft changes
bin/gate-profile set away --for 72h --reason "away Thu-Sun, spend the weekly quota"
bin/gate-profile status                        # profile away: active until Thu Oct 29 12:00 PM EDT (3d 0h 0m left) ...
# 72 h later: the next governor/guard run pings "away profile expired, baseline restored"; or end early:
bin/gate-profile clear
```

Away draft (values are confirmed by the operator at activation, edit `[profiles.away.*]` in the same PR or commit as
the activation so the window is in git): governor `tight_projected` 90 -> 500, `tight_left_five_hour` 25 -> 15,
`tight_left_weekly` 30 -> 15 (`critical_left` stays 10); guard `watch_weekly` 40 -> 20, `tight_weekly` 30 -> 15,
`critical_weekly` 15 -> 10, `conserve_alert_level` 2 -> 1 (`critical_five_hour`, `watch_fable` unchanged). A weekly window at 65%
used with 4d5h left (projected 242%, left 35) is `tight` at baseline and `ok` under `away`; with aiuse's `conserve` projection alert
also live it is `tight` at baseline and `watch` under `away`.

## The `conserve` alert rule

The guard also raises its level on aiuse `conserve` alerts: any Claude alert gives `watch`, and a weekly "projected to run out ...
before reset" alert gives `tight` (ignored while that window is `pace_early`). That rule is capped by `conserve_alert_level`
(baseline 2): an alert gives min(that number, the level it would otherwise give), so a baseline run is unchanged. `away` sets 1,
so the projection alert alone gives `watch` (advice text only) and the governor, which reads the guard's level, does not
downshift on it. A profile cannot set 0 (an alert always gives at least `watch`); env JSON can, for tests and emergencies.

## Frontier allowance: the `[frontier]` gate (2026-10-27)

A third gate, read by `bin/route_agent.py`, `bin/acp-dispatch`, `claude/hooks/frontier_agent_gate.py`, `bin/claude-quota-guard`
(advice, state) and `claude/hooks/quota_nudge.py` (daily line). Code default: `ade_gates.FRONTIER_DEFAULTS`; load it with
`ade_gates.load_frontier()`. **No threshold env override** (an agent can set an environment variable; the allowance must not widen that
way). The path variables `GATES_TOML` and `GATE_PROFILE_STATE` (and, for `acp-dispatch`, `CLAUDE_QUOTA_GUARD_STATE` and `HOME`)
still redirect the inputs, so a CLI consumer started by an agent can be pointed at a self-written profile: a `frontier_judged`
record in a dispatch record is an audit trail, not proof that a grant existed. The Claude Code hook takes its environment from
the Claude process, which a session cannot change. Baseline (every number is today's rule): no judged use, one frontier slice per pool per wave, no Agent-tool frontier call
without asking.

| key | baseline | `away` | floor (`loosen`, bound) | meaning |
| --- | --- | --- | --- | --- |
| `frontier1_judged` | 0 | 1 | higher, 1 | 1: an agent MAY pick the claude frontier model (Fable) on its own judgment, with a reason |
| `frontier2_judged` | 0 | 1 | higher, 1 | same for the codex frontier model (gpt-6-astra) |
| `frontier1_per_wave` | 1 | 2 | higher, 2 | frontier slices per wave on the claude pool (moved from `routing.toml` `frontier_per_wave`) |
| `frontier2_per_wave` | 1 | 1 | higher, 1 | the same on the codex pool |
| `frontier1_agent_calls_per_day` | 0 | 4 | higher, 6 | Agent-tool frontier-1 calls allowed without asking per America/New_York day (0: always ask) |
| `frontier1_min_left` | 10 | 10 | lower, 10 | percent of the Fable cap that must be left (moved from `routing.toml` `fable_min_left`); a profile may not lower it |
| `frontier2_min_left` | 60 | 60 | lower, 40 | percent left on the codex binding window |

`route_agent.py` reads `frontier1_per_wave` (pool `claude`) and `frontier2_per_wave` (every other pool) in `plan`, and
`frontier1_min_left` in `suggest_model`; the keys are gone from `config/routing.toml`.

**What a granted allowance is.** While `away` (or any profile setting the keys) is active, an agent MAY use a frontier model
where it judges it significantly better than judgment, if it states why in one line. The checks, in order:

| step | `claude/hooks/frontier_agent_gate.py` (Agent tool, Fable) | `bin/acp-dispatch --kind frontier --frontier-reason TEXT` |
| --- | --- | --- |
| gate | `frontier1_judged` and `frontier1_agent_calls_per_day` at least 1, else ask | the family's `*_judged` at least 1 (claude pool: 1, codex pool: 2) |
| guard | `quota-guard.json` at most 30 min old, level `ok`, or `watch` whose `reasons` are only `["weekly"]`, `stale` false, `fable_left` at least `frontier1_min_left`; else ask | claude: the same check; codex: the pool reading at least `frontier2_min_left` (no reading: not granted) |
| reason | a `frontier-reason: TEXT` line in the prompt, 10-200 characters, one line, no control or format character (so no tab, zero-width joiner or soft hyphen); else ask (the ask text names the format) | `--frontier-reason`, same bounds; empty or missing: baseline treatment; non-empty but out of bounds or multi-line: exit 2 |
| cap | allowed-judged calls today (NY) below `frontier1_agent_calls_per_day`, counted from the log AND `agent-calls-day.json` (the larger) | fewer than `*_per_wave` frontier slices in flight on the pool |
| record | log row `decision: allowed-judged`, reason, profile name and `until` | `frontier_reason`, `frontier_judged` (family, profile, until, cap, in flight), `frontier_judged_note` (why not) in the dispatch record, one stderr line |

Unchanged under any profile: advise-only (no `frontier-exec`), the `fable-xhigh` approval, no lead session on a frontier model
(the governor's move), and the `tight`/`critical` stop signal (judged use needs level `ok`, or `watch` for the weekly window
alone: a stale collector, an alert, a snapshot-only row or the Fable cap at `watch` keep the baseline). A profile that expires
mid-wave ends the allowance on the next call (each call re-reads the profile); a slice already running is not stopped.

Decisions and limits (2026-10-27): (1) `acp-dispatch` never refuses a dispatch the baseline allows: omitting the reason is
exactly today's behaviour, so the allowance there is recorded and capped, not a lock; only the Agent-tool hook asks.
(2) The per-wave cap in `acp-dispatch` counts `frontier`-kind slices in flight on the pool (a wave has no id there).
(3) The guard writes `reasons` (which triggers fired: `weekly`, `five_hour`, `fable`, `alert`, `snapshot-only`, `exhausted`,
`stale`) and `frontier_allowance` (`judged`, `agent_calls_per_day`) into `quota-guard.json`; the daily nudge line says "allowed"
only when `frontier_allowance.judged` is true. (4) Same-user files (`agent-calls.jsonl`, the day counter, the profile, the guard
state, `GATES_TOML`) can be edited by any agent: the double counter, the regular-file and future-dated-row checks, the
fail-closed parse errors and the lock raise the cost of spoofing the cap, they do not make it impossible. The hook also trusts
its process environment: a session can start a child `claude` or `acp-run` with `ACP_OPERATOR_APPROVED=frontier-agent` set,
and that child's frontier sub-agents then pass unasked and uncapped (pre-existing, not closed by the gate). For the `frontier`
gate both a `gates.toml` baseline and a profile value are judged by the code's direction (`*_min_left` lower is looser, every
other key higher), never by a floor entry's `loosen`, so a flipped floor entry cannot loosen the baseline or let a profile pass
the entry's `bound` in the wrong direction; the `bound` itself is still a `gates.toml` edit (same-user, above). (5) A reason is
self-asserted: it bounds nothing but the audit trail; the cap, the floors and the guard level bound the spend. (6) Residual:
`gate-profile set` and `extend` have no operator check (no tty, approval token or Touch ID; `--by` is free text), so any agent
can grant the allowance by setting `away`. Mitigations: `set` sends a `hermes-ping` and every change is appended to
`gate-profile.log`. (7) In the Agent-tool hook, once a call is identified as a frontier call, any error in its own state (state
directory, lock, log append, counter) asks instead of allowing; the lock is polled for 5 s, then asks. The log, lock and counter
are opened `O_NOFOLLOW|O_NONBLOCK` and checked with `fstat` on the opened fd, reads included (no stat-then-open, so a file
swapped in during the read cannot block it; the guard state and `gates.toml` are read `O_NONBLOCK`, regular files only), so a
symlink or a FIFO planted in its place asks at once instead of hanging (the
hook entry in `settings.json` carries `"timeout": 15` and `"onFailure": "block"` since 2026-10-27 (djbclark's choice; Claude Code 2.1.295 or later): a stalled, timed-out or unstartable hook then blocks the Agent/Task call instead of letting it through, and a missing or broken hook script, or a hook that fails to start, blocks every Agent/Task call; the hook itself starts on a macOS `/usr/bin/python3` 3.9 (it has no `datetime.UTC` import), but under a `python3` older than 3.11 its allowance cannot load (`ade_gates` needs `tomllib`), so every frontier call asks and the reason is only in the log row's `ask_reason`; the live hook path  is a symlink into the shared `~/src/djbclark-ade` checkout, so a checkout without `claude/hooks/frontier_agent_gate.py` blocks them machine-wide). The counter is written before
the log row, so a failed write never leaves an `allowed-judged` row for a call that asked; a counted call with no row only
over-counts, which is safe.

## Not covered (2026-10-26)

`route_agent.py` constants (`plenty_min`, `SUBSTRATE_MIN_HEADROOM` in `config/routing.toml` and the script) and the routing
policy text in `skills/model-routing/SKILL.md` are not profile-controlled. (`frontier_per_wave` and `fable_min_left` moved
to the `[frontier]` gate on 2026-10-27, above.)
