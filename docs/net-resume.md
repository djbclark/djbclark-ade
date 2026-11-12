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
`config/launchd/com.djbclark.ade-net-resume.plist` runs a one-shot **dry-run**
every minute. Render it with `ade-sched render ... --set __LEAD__=UUID
--set __STATE__=/absolute/log/dir`; installing requires a deliberate operator
action, and enabling sends also requires adding `--apply` to the template.
The scheduler render fixtures supply `__LEAD__` using the same substitution
contract as the merged auto-permit template (2026-11-12); unfilled placeholders
are still refused. This PR installs or loads nothing.

Offline tests use a fake Paseo executable and mocked endpoint health. CI runs
them on Linux; no real agent is resumed by the tests.
