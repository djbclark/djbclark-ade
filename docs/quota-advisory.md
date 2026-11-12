# Advisory quota reminders (2026-11-12)

At every batch boundary the lead runs `python3 bin/quota_nudge.py`.
`python3 bin/route_agent.py show` also prints the reminder. Both reuse the
router's merged `aiuse --available --json` and `paseo usage ls --json` reading;
the existing router environment variables support offline fixtures.

`config/quota-advisory.toml` owns default thresholds and optional `[pools.ID]`
overrides. Values are percent **remaining**, inclusive at each boundary:
10 or less is critical; 30 or less is conserve; above that is ok. Missing,
invalid, future-dated or stale per-pool readings are unknown, never ok. The
maximum age is configured independently of routing. Unknown config prints an
unavailable reminder and does not fail the batch. No daemon, prompt hook,
blocking quota guard or live auto-routing change is installed. The old
`claude/hooks/quota_nudge.py` inspired the level/profile reminder; it remains
unchanged and the deleted guard is not revived.

The operator can explicitly record a spending intention:

```sh
python3 bin/quota_nudge.py --set-profile antigravity \
  --name "use expiring agy headroom" --until 2026-11-13T00:00:00-05:00
python3 bin/quota_nudge.py --set-profile openai \
  --name "OpenAI metered: allowed" --until 2026-11-13T00:00:00-05:00
python3 bin/quota_nudge.py --clear-profile openai
```

Use the exact pool id from `show`. A profile is visible even if its pool has
no current measurement; that pool stays unknown. Profiles are operator intent,
not grants: they never alter ranks, billing, disabled pools, frontier gates,
Fable settings, Pi acceptance, model/effort, or plan/route eligibility. Even a
profile named "allowed" cannot authorize a dispatch that existing gates reject.

Profiles live outside git at `~/.local/state/ade/spending-profiles.json`
(`ADE_SPENDING_PROFILES` overrides it for fixtures). Timestamps require an
explicit timezone and a future expiry. Every read drops expired or malformed
entries; expiry needs no timer or cleanup write. Set/clear prune old entries
and atomically replace the file. Concurrent operator set/clear commands should
be serialized (last writer wins). Merely reading a reminder writes nothing.
