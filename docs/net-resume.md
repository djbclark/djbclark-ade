# Network recovery for a lead's agents

`bin/ade-net-resume` (2026-11-12) scans `paseo ls -g --background --json` for error-status
descendants of an explicit full `--lead` UUID. Background workspaces are included. Unresolvable unrelated agents are skipped. Ancestry uses inspect's
`ParentAgentId`; missing records, cycles, archived agents and unknown providers
cannot authorize a resume. PR 585's auto-permit helper was not on master when
this tool was built, so this command has its own small ancestry walk.

```
bin/ade-net-resume --lead LEAD_UUID
bin/ade-net-resume --lead LEAD_UUID --apply
bin/ade-net-resume --lead LEAD_UUID --apply --watch 600 --interval 30
```

`--max-error-age-minutes MINUTES` defaults to **30 minutes**. The inspect
`UpdatedAt` value must be a valid timezone-aware ISO timestamp between now and
the configured age limit (inclusive). Missing, malformed, timezone-less or
future timestamps are skipped as `stale`. A stale error is rejected before
logs, endpoint probes or a budget reservation; age is rechecked before sending.
This uses Paseo's updated time, which can reflect metadata changes as well as
an error; it is not a guaranteed error-occurrence timestamp (2026-11-12).

Structured `paseo logs ID --json` also checks for an unquoted, unfenced
`done:` delivery line in the latest assistant output before the terminal network
error. That agent is skipped as `delivered`, even when its error is recent.
User messages and tool output cannot supply a delivery line; a newer user
message resets the search, and prior assistant outputs are not searched beyond
the latest non-error output. Unreadable structured logs fail closed. The delivery
heuristic is deliberately narrow: other completion formats still rely on the
age guard. Neither skip consumes budget. Both checks also apply to dry runs.

Default is a single dry-run scan with a 120-second overall deadline. `--watch`
accepts 1..3600 seconds, `--interval` 5..300 seconds (default 30). CLI calls and
HTTPS probes have timeouts clipped to the remaining deadline. Offline scans
report `offline`; watch checks again at the interval. A single scan never sends
while disconnected. The scan may run out of budget before reaching every agent.

Only the **last nonempty log line** can match the provider's explicit transient
error table in the script. Antigravity recognizes the incident's exact system
network error; Codex recognizes system stream-disconnect/request-send errors;
Claude recognizes system connection/timeouts. Pi has testable classification
patterns but is held because its provider host depends on routing. Unknown
errors and quota (1302/1308/429), auth, billing and refusal messages are skipped.
Earlier quoted errors cannot authorize a send. Logs are treated as data; no
prompt or host is ever taken from them.

Both `https://api.github.com/` and a fixed provider endpoint must answer HTTPS
HEAD: Antigravity daily-cloudcode-pa.googleapis.com, Codex chatgpt.com, Claude
api.anthropic.com. TLS verification stays enabled. Probes run through `curl -q` with both a process timeout (including DNS) and a curl timeout. No redirects are followed;
HTTP responses below 500 (except 429) prove transport availability, including
401/403/404 at endpoints requiring credentials. No credential is used. A healthy
root endpoint cannot guarantee an authenticated inference request will succeed.

Immediately before apply, status, ancestry, provider and logs are re-read.
The fixed prompt is:

> network outage over; continue from where you stopped, re-fetch first, same report path

`--state-dir` defaults to `~/.local/state/ade/net-resume`. Every invocation must
share this directory: it contains a nonblocking exclusive lock and fsynced
`events.jsonl`. Dry runs write observations but consume no resume budget. Apply
requires at least 16 seconds remaining (the full 15-second CLI timeout plus a
one-second reservation margin) before reserving and sending, with at most **two attempts per agent per rolling
hour**, across leads and invocations. The same error-event fingerprint (`UpdatedAt` plus the final error line) is never sent
twice, including after an uncertain send. Failed/timed-out sends consume budget;
operators inspect these manually rather than resetting the ledger. State is
append-only and malformed state fails closed. The ledger records IDs, times,
decisions and log hashes, never raw transcript content. Clock rollback can
delay eligibility. Keep the ledger; deleting or switching it resets protection.

`paseo send --json --no-wait` exit 0 or 5 is recorded as `submitted`, never as
proof that the agent continued. No running agent is steered. Error state can
race after the final check; the CLI has no conditional-send transaction.

Exit codes: 0 completed scan/watch, 2 invalid usage or unreadable CLI/state,
3 lock held for a one-shot (watch retries at the next interval). The unloaded template
`config/launchd/com.djbclark.ade-net-resume.plist` runs a one-shot **dry-run with `--quota`**
every minute (operator ruling, 2026-11-13). Render it with `ade-sched render ... --set __LEAD__=UUID
--set __STATE__=/absolute/log/dir`; installing requires a deliberate operator
action, and enabling sends also requires adding `--apply` to the template.
The scheduler render fixtures supply `__LEAD__` using the same substitution
contract as the merged auto-permit template (2026-11-12); unfilled placeholders
are still refused. This PR installs or loads nothing.

## Quota resume (`--quota`, 2026-11-12)

Session-guard resumes a quota-failed agent only when Paseo's `provider.usage.list` has a usage entry for the
agent's provider; Pi pools (z.ai, OpenCode Go, ClinePass) have none, and a daemon idle collection turns the errored
agent into `closed` with its `lastError` gone (design `design-quota-resume.md`, W10 evidence, 2026-11-12). `--quota`
(off by default) adds a second pass after the network pass. The network path, its `DENIED` regex and its 30-minute
rule are unchanged, and it still rejects every quota message. The launchd template includes `--quota`
but stays **dry-run**, with no `--apply` (operator ruling, 2026-11-13). Enabling sends remains a separate
operator decision (order 11); reinstalling the template after merge enables quota observations only.

```
bin/ade-net-resume --lead LEAD_UUID --quota --only-agent CANARY_UUID --watch 3600 --interval 60
```

Flags: `--quota-per-pool N` (default 1 resume per pool per scan; N above 1 changes only a dry run's counting, because
the 600 s pool gap limits `--apply`), `--quota-grace-seconds S` (default 60),
`--only-agent UUID` (repeatable; restricts **both** passes, so a canary is isolated from the fleet).

Scope, all of it kept from the network path (descendants of `--lead` only, `Archived` false, the reserve-before-send
ledger, two attempts per agent per hour, an error event sent once, an uncertain send never retried, re-inspection
before the send, the lock, dry-run unless `--apply`, the scan deadline) plus:

1. **Pi pools only.** `pool_of` maps provider `pi` with model prefix `zai/` to the aiuse provider `zai`. Claude and Codex
   stay with session-guard; any agent with a pending guard pause (`~/.paseo/plugin-data/session-guard/state.json`,
   `pauses[].agentId`, phase not `resumed`/`cancelled`; session-guard's `dismissed` is a flag, not a phase) is `guard-owned` and skipped. Add a pool only
   with a line copied from a real stop.
2. **Narrow classification.** The last log line must fully match the pool's rendered quota line (the z.ai 5-hour
   code-1308 line, copied from a real stop 2026-11-12) and must not match `QUOTA_DENIED` (auth, credential, API key,
   billing, credit, balance, 1113, 401, 403). Weekly stops do not match the pattern; a weekly window exhausted in
   aiuse is `quota-excluded` (windows over 360 minutes never qualify).
3. **aiuse is the reset anchor, fail closed.** On first sight of an eligible error the scan records `quota-wait`
   (`signature`, `pool`, `window_id`, `window_minutes`, `resets_at`, `updated_at`) from the exhausted aiuse window
   (`state` exhausted or used 95% or more). The reset must fall after the error and within `window_minutes` of it, else
   `stale`; no exhausted window is `quota-unconfirmed`, never a resume. **aiuse dependency (2026-11-12):** the wait is armed
   only when aiuse itself shows the window `exhausted` or at 95% or more. If aiuse's collector lags, or its own quota-note
   matching (family `5h` against a window whose `pool_family` is null) never flips the `primary` window, the pass stays
   `quota-unconfirmed` and never fires; check with a dry-run canary first. aiuse is not changed by this pass.
   An unconfirmed agent is re-evaluated against aiuse on every scan but its logs are not re-read (see 5). aiuse nulls `resets_at` after a reset (it can also carry an earlier reset forward as an estimate),
   so the ledger copy is the only anchor and the resume gate still needs a fresh post-reset sample.
4. **Resume gate.** A resume needs a fresh aiuse sample (`fresh` true, not stale, `usable_now` true) whose
   `collected_at` is at or after `resets_at` plus grace and not in the future, showing the recorded window below the
   limit and no window longer than 360 minutes (or of unknown length) exhausted, whatever `usable_now` says. A missing aiuse, bad JSON, a missing or ambiguous account, or a stale sample waits (`quota-waiting`, or
   `aiuse-unavailable` at first sight, at most one row per clock-aligned ten-minute bucket each). The reset may be at most `--max-error-age-minutes` (default 30) in the past, else `stale`.
5. **Agent state.** `error` is eligible after `paseo logs --json` shows the quota line still last: a newer user
   message or other output is `changed`, a `done:` line before the error is `delivered`. That check runs **before**
   `quota-wait` is armed, while the agent is still loaded, and again before a resume. `closed` is eligible only
   when the ledger holds a `quota-wait` for the agent whose `UpdatedAt` is unchanged (operator ruling, lead 2026-11-12);
   a closed agent's timeline is never read. Which Paseo call reloads an agent (adversary reading of Paseo
   0.16.0-beta.2, 2026-11-12): `paseo agent inspect` is `fetchAgent` and returns the live agent or the stored record
   without reloading; `paseo logs` also fetches the **timeline**, which reloads an agent from persistence if it is not
   live, and the reloaded timeline holds only the original user message. Inspect reports the stored status of a non-live
   agent, and that stays `error` across a daemon restart or worker crash (2026-11-12 crash, item 20 of
   `docs/upstream-issues.md`), so `error` does **not** prove the agent is loaded. The pass therefore never calls
   `paseo logs` for a `closed` agent, never for an `error` agent whose `UpdatedAt` is older than 360 minutes plus
   `--max-error-age-minutes` (the quota analogue of the network path's age rule; note that widening that flag
   widens this bound too) or in the future, and not again once the ledger holds a row for that `UpdatedAt`: a
   `quota-wait` (the scan matches its `updated_at` and pool and reuses the stored signature) until the reset check, or
   a first-sight row (`quota-unconfirmed`, `quota-excluded`, `aiuse-unavailable`, `stale`, which are only re-checked
   against aiuse, and `delivered`/`changed`, which end the matter for that error event). What remains is a reload of an unloaded `error` agent younger than the
   bound: Paseo's reload turns its stored `error` into `idle` and drops `lastError`, so the scan reads it about once, and
   that agent is skipped (fails closed) with **no ledger row** and no longer shows as errored; a later idle collection
   closes it. A reload at the reset check (an armed agent unloaded by a daemon restart before its reset) writes
   `changed`, but the agent can still be resumed later through the closed path, because the first-sight timeline check
   passed and its `UpdatedAt` is unchanged. Inspect carries no
   `lastUserMessageAt` (design B4d), so the closed-agent identity check is the unchanged `UpdatedAt`, which a new
   user message changes because the agent runs.
6. **Prompt and dry run.** `provider quota window reset; continue from where you stopped, check any interrupted operation before
   retrying, same report path`. One resume per pool per scan, and at least 600 seconds between two quota
   resumes of one pool (so `--quota-per-pool` above 1 changes only a dry run's counting: under `--apply` one reservation
   blocks the pool for 600 s, and with the default 30-minute staleness window at most about three agents per pool are
   resumed per reset, at reset+grace, +10 and +20 minutes; widen `--max-error-age-minutes` for more) (`QUOTA_POOL_GAP_SECONDS`, read from the ledger's quota `reserved` rows across scans and runs; a
   blocked agent logs `pool-gap`), so a just-reset pool is not drained at once. A dry run counts a `would-resume-quota`
   toward the per-scan cap, so with several agents in one pool it shows only the first one (every scan) until that error
   goes stale (reset plus `--max-error-age-minutes`).
7. **Ledger rows.** Written once per error event (keyed), not once per scan: the first-sight outcomes
   `quota-unconfirmed`, `quota-excluded`, `delivered`, `changed` and `stale`; `capped`; `guard-owned`; both `changed`
   rows (the closed-path one keyed by `UpdatedAt`, the pre-send and reset-check ones by signature); `delivered` at the
   reset check; `would-resume-quota`. At most one row per clock-aligned ten-minute bucket (two rows can fall seconds
   apart across a bucket boundary): `unavailable` (per failure type), `quota-waiting`, `pool-gap` and the first-sight
   `aiuse-unavailable`. A persistent failure is therefore about one row per ten minutes while the agent stays listed.
   A `quota-wait` row with a missing or mistyped field, or a `resets_at`/`updated_at` that is not a timezone-aware
   timestamp, is **skipped** with one `quota-ledger-invalid` row (keyed by the row's time and signature); the run goes
   on, the agent is simply treated as having no wait. An `events.jsonl` that is not valid JSON, or has a non-numeric
   `time`, still fails the whole run (exit 2).

`--quota` shares the network pass's ledger. A lead that replaces a quota-stopped agent with a new one should archive the old agent, or the old one may be resumed
beside it.

The quota implementation slice (2026-11-12) did not change the launchd plist or run a canary or live `--apply`.
The template update (2026-11-13) adds only dry-run quota scanning; it installs or loads nothing.

Offline tests use a fake Paseo executable, a fake `aiuse` and mocked endpoint health. CI runs
them on Linux; no real agent is resumed by the tests.
