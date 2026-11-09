# The frontier allowance: `config/gates.toml [frontier]` (2026-10-27; trimmed 2026-11-07)

`config/gates.toml` holds one gate since 2026-11-07 (slim-down E7): the frontier-model allowance. Since
2026-11-09, `ade_gates.load_frontier` reads it through `ade_config.load_effective` (legacy projection when
`config/ade.toml` is absent; `GATES_TOML` still isolates the gates domain for tests). Consumed by
`bin/route_agent.py` (the planner's per-wave cap and the Fable floor; Wave 6 `Choice.dispatch` emit is native
`paseo run`), `bin/ade_gates.py` / the transitional `bin/acp-dispatch` shim (the `--frontier-reason` grant until
the shim delete), and `claude/hooks/frontier_agent_gate.py` (Agent-tool Fable calls). The Claude quota gates that shared the file
(the fleet governor's `[governor]` and the quota guard's `[quota_guard]` thresholds, the temporary gate profiles with
their floors, the `away` profile and the `conserve` alert rule) were deleted with their scripts; pausing at a quota limit
and resuming after the reset is the session-guard and usage-auto-resume Paseo plugins' job (PLAN D4). The 2026-10-26
text of this page is in git history.

## A. Loading the gate (`bin/ade_gates.py`)

A1. `ade_gates.load_frontier()` returns `(thresholds, info)`. The code default, `ade_gates.FRONTIER_DEFAULTS`, is the
fail-safe and is **all closed**: no judged use, one frontier slice per pool per wave, no Agent-tool frontier call without
asking. It applies when `gates.toml` is missing, unreadable, not a regular file, or its `[frontier]` table is missing or
holds a non-number (`info["toml_error"]` says why), so the hook asks.
A2. The standing allowance is the file's `[frontier]` baseline. A "higher is looser" key (every key but `*_min_left`) may
rise to its `[floors.frontier]` numeric `bound` and takes the code default above it; a `*_min_left` key is never looser
(lower) than its code default, whatever the floors say. A replaced value is listed in `info["baseline_guarded"]`. The
direction comes from the code, never from a floor entry's `loosen`.
A3. **No env override of the numbers** (an agent can set an environment variable; the allowance must not widen that way).
`GATES_TOML` still redirects the file, so a CLI consumer started by an agent can be pointed at a self-written file: a
`frontier_judged` record in a dispatch record is an audit trail, not proof of a grant. The Claude Code hook takes its
environment from the Claude process. Same-user edits of the file (or of the shared checkout the hook's symlink resolves
through) widen it unlogged: the internal-trust ruling of 2026-11-07 accepts that.

| key | code default (fail-safe) | baseline (standing) | floor bound | meaning |
| --- | --- | --- | --- | --- |
| `frontier1_judged` | 0 | 1 | 1 | 1: an agent MAY pick the claude frontier model (Fable) on its own judgment, with a reason |
| `frontier2_judged` | 0 | 1 | 1 | the same for the codex frontier model (gpt-6-astra) |
| `frontier1_per_wave` | 1 | 2 | 2 | frontier slices per wave on the claude pool |
| `frontier2_per_wave` | 1 | 1 | 1 | the same on every other pool (codex, the Argon fallback) |
| `frontier1_agent_calls_per_day` | 0 | 4 | 4 | Agent-tool Fable calls allowed without asking per America/New_York day |
| `frontier1_min_left` | 15 | 15 | (code default) | percent of the Fable cap that must be left (15 since 2026-11-07: the old guard's `watch_fable` stop); below it a claude frontier slice is Opus |
| `frontier1_window_min_left` | 30 | 30 | (code default) | percent left on the tightest Claude window (the old quota guard's tight level: the stop signal) |
| `frontier2_min_left` | 60 | 60 | (code default) | percent left on the codex binding window |

## B. The Claude reading (2026-11-07)

B1. `ade_gates.read_guard_state()` (its name kept for its importers) returns `route_agent.claude_quota_state()`: the
merged quota snapshot's `claude` entry (`aiuse --available --json` first, `paseo usage ls --json` second;
`docs/model-routing.md` D) as `checked_at` (now minus that reading's own age), `remaining` (the tightest window),
`fable_left` (the Fable sublimit), `windows`, `source`, and `unknown` (why there is no reading: nothing reports claude, or
only a Paseo report whose status is not `available`). It replaced the quota guard's state file.
B2. `ade_gates.judged_guard_block(state, t, now)` blocks, in order: a missing state; an `unknown` one; no usable
`checked_at`; a reading older than 30 minutes (`GUARD_STATE_MAX_AGE_S`) or more than a minute in the future; no window
percentage; a tightest window under `frontier1_window_min_left`; no Fable reading; a Fable cap under `frontier1_min_left`.
Both sources already drop a non-exhausted window older than 25 minutes, so a reading between 25 and 30 minutes old
blocks as "no window percentage". An unknown Paseo report beside a fresh aiuse reading does not block: aiuse is the primary
reading, and the fail-closed rule applies when no source reports Claude.
B2a. **What changed from the quota guard (2026-11-07):** its `conserve` alerts (aiuse's pace projections, which could raise
the level to tight) are gone, so a projected exhaustion no longer stops judged use on its own; the window floor is one
number for the tightest window, so the 5-hour floor rose from the guard's 10 (critical) to 30, and the weekly floor stays
at 30 (the guard's tight); the Fable floor stays at the guard's 15. `judged_pool_block(family, …)` is the one copy for both families: claude through
`judged_guard_block`, every other pool by its reading at least `frontier2_min_left` (no reading: blocked).
B3. The hook bounds its two quota reads to 5 s each (`ROUTE_AGENT_AIUSE_TIMEOUT`, `ROUTE_AGENT_PASEO_TIMEOUT` defaults it
sets) so it stays inside its 15 s settings timeout.

## C. What a granted allowance is

While the effective gate allows it (the standing baseline), an agent MAY use a frontier model where it judges it
significantly better than Opus 5.5, if it states why in one line. The checks, in order:

| step | `claude/hooks/frontier_agent_gate.py` (Agent tool, Fable) | Out-of-process frontier slice (`route_agent.py plan --kinds frontier` → `Choice.dispatch` / transitional `acp-dispatch --kind frontier --frontier-reason TEXT`) |
| --- | --- | --- |
| gate | `frontier1_judged` and `frontier1_agent_calls_per_day` at least 1, else ask | the family's `*_judged` at least 1 (claude pool: 1, codex pool: 2) |
| reading | `judged_guard_block` (B2) passes, else ask | claude: the same; codex: the pool reading at least `frontier2_min_left` |
| reason | a `frontier-reason: TEXT` line in the prompt, 10-200 characters, one line, no control or format character; else ask | `--frontier-reason` on the shim (same bounds); empty or missing: no allowance claimed; out of bounds or multi-line: exit 2. Native `paseo run` from `Choice.dispatch` records the planner's kind label; do not invent a second reason flag |
| cap | allowed-judged calls today (NY) below `frontier1_agent_calls_per_day`, counted from the log AND `agent-calls-day.json` (the larger) | fewer than `*_per_wave` frontier slices in flight on the pool |
| record | log row `decision: allowed-judged` and the reason | shim: `frontier_reason`, `frontier_judged` (family, cap, in flight), `frontier_judged_note` (why not) in the dispatch record; native path: planner + Paseo labels |

C1. `route_agent.py plan` puts at most `frontier1_per_wave` frontier slices on claude and `frontier2_per_wave` on any other
pool in a wave, and the cap above the closed 1 holds only while `judged_pool_block` passes (B2); otherwise the closed 1.
C2. Unchanged by the allowance: advise-only (`--role exec` needs `ACP_OPERATOR_APPROVED=frontier-exec`), the `fable-xhigh`
approval for Fable at `xhigh`/`max`, and the stop signal (a short, stale or unknown Claude reading keeps the closed rules).
The transitional shim never refuses a dispatch the closed gate allows: omitting the reason is the pre-allowance behaviour; only the
Agent-tool hook asks. New launches prefer `route_agent.py` → `Choice.dispatch` (native `paseo run`).
C3. **Gemini 4 Argon** (`antigravity-argon`, the frontier fallback behind codex and claude, restored 2026-11-07) has no
allowance of its own: it is a `frontier` model (planner `--kinds frontier` / shim `--kind frontier` only), counts as family 2 in the planner's per-wave cap,
and the `--frontier-reason` grant covers the claude and codex pools only (for Argon the reason is recorded, nothing is
refused). The fallback-only rule is the planner's (`fallback_after`); the transitional shim does not re-check it.
C4. The hook, once a call is identified as a frontier call, asks on any error in its own state (state directory, lock,
log append, counter); the lock is polled for 5 s. The log, lock and counter are opened `O_NOFOLLOW|O_NONBLOCK` and checked
with `fstat` on the opened fd; the counter is written before the log row. Its settings entry carries `"timeout": 15` and
`"onFailure": "block"` (2026-10-27): a hook that cannot start blocks every Agent/Task call, and the live hook path is a
symlink into the shared `~/src/djbclark-ade` checkout.
C5. **To close the allowance:** a PR setting `[frontier]` back to the code defaults (`frontier1_judged`,
`frontier2_judged`, `frontier1_agent_calls_per_day` 0; per-wave keys 1).
