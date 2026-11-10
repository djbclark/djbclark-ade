### Removed

- Deleted `claude/hooks/quota_nudge.py` and `claude/hooks/cswap_quota_context.sh` with their template hook lines (R2-18): E7's session-guard and usage-auto-resume replaced the Claude quota gate; the nudge was inert without the deleted guard state file, and the SessionStart cswap table was that path's display companion. Live `~/.claude` hook lines remain an operator edit (`docs/slim/operator-batch.md` C5) (#457).
