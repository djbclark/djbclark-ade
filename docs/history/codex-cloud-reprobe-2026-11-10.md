# Codex Cloud environment — re-probe 2026-11-10

Queue Carried #16. Original evidence: `docs/history/ade-everywhere-proposal.md`
(2026-10-19 row: CLI 0.163.0 fails to discover owned Cloud environments;
openai/codex#50182, #51585).

## Probe (Linux-safe, no live Cloud exec)

| Check | Result (2026-11-10) |
|---|---|
| openai/codex#50182 | **OPEN** — "codex cloud does not discover current Cloud environments"; last activity 2026-11-07 |
| openai/codex#51585 | **OPEN** — "Codex Cloud environment catalogs differ between CLI, desktop, and web (CLI 0.160.1)"; last activity 2026-10-29 |
| Latest `openai/codex` release | `rust-v0.167.0` / name `0.167.0`, published 2026-11-06 |
| Local `codex` CLI | not installed in this environment — no `codex cloud exec` / `codex cloud list` re-run here |

## Still blocked

Until #50182 / #51585 close (or a release notes a catalog/discovery fix), Codex Cloud
remains a PR reviewer path (`@codex review`) and not a builder via `codex cloud exec`.
Next re-probe: after the next codex-cli release, or when either upstream issue closes.
