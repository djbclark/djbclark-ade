### Changed

- `skills/model-routing` C7: Antigravity's `claude-*`/`gpt-*` models draw a separate small Claude/GPT weekly pool
  (exhausted 2026-11-12 while `aiuse` showed 36% left); spend expiring agy headroom on its Gemini models only. (#571)
- `AGENTS.md`: check `gh pr list --base <branch>` before `gh pr merge --delete-branch` (a deleted base closed stacked PR #567). (#571)
- `skills/model-routing` E1a: check each pool's `collected_at` against the previous wave's start before dispatching; re-read with `--live` otherwise. (#571)
- `skills/model-routing` E1b: z.ai 429/1302 is a request-rate limit, not quota; keep at most 5 z.ai agents running and move a throttled one to another Pi pool. (#571)
