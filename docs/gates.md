# Claude quota gates: `config/gates.toml` and temporary profiles (2026-10-26)

Two scripts turn the Claude quota into a level that sessions act on. Before 2026-10-26 their numbers were code
constants (plus a launchd env var with no expiry). They now live in a versioned file, and a **profile** can loosen
them for a bounded time (a planned absence) without anyone editing code, an env var or a plist.

| piece | what |
| --- | --- |
| [`config/gates.toml`](../config/gates.toml) | the baseline (the current values), the floors a profile may not cross, and the profiles (`away`, a draft) |
| [`bin/ade_gates.py`](../bin/ade_gates.py) | the loader both scripts call: `load_gates(gate, now, defaults) -> (thresholds, info)` |
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
and `bin/gate-profile validate` fail on drift, so change a number in both places in one commit.

## `gates.toml`

`[meta]` (`schema = 1`, `max_profile_hours = 240`), the two baseline tables with every key commented (meaning, unit),
`[floors.<gate>]`, `[profiles.<name>.<gate>]`. A floor is `key = { loosen = "lower" | "higher", bound = N }`:

| key kind | looser is | profile value must lie in |
| --- | --- | --- |
| `*_left*`, `*_weekly`, `critical_five_hour`, `watch_fable` (percent left) | lower | `[bound, baseline]` |
| `tight_projected` (projection at reset) | higher | `[baseline, bound]` |
| `conserve_alert_level` (a level: 0 ok, 1 watch, 2 tight, 3 critical) | lower | `[1, 2]` (bound 1 = watch) |
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

## Fail-safe: when a profile is ignored (baseline applies, `status` says why)

File missing, unreadable, not a JSON object, `schema` not 1; `until` or `since` missing, naive, or not offset zero;
`until` at or before now (the profile ends exactly at `until`); `since` in the future; `until <= since`; window over
`max_profile_hours`; unknown profile name; any key not under `[floors]`, any value tighter than the baseline, below a
`lower` bound or above a `higher` bound, on EITHER gate (the whole profile is rejected, never clamped, so the governor and the guard
always agree); a profile whose applied guard values break `watch_weekly >= tight_weekly >= critical_weekly` (`validate` also
checks the baseline); `gates.toml` missing or unparsable (code defaults apply, logged once to stderr).

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

## Not covered (2026-10-26)

`route_agent.py` constants (`plenty_min`, `fable_min_left`,
`SUBSTRATE_MIN_HEADROOM` in `config/routing.toml` and the script) and the routing policy text in
`skills/model-routing/SKILL.md` are not profile-controlled.
