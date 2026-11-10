# Browser tasks (setup-plan S7)

First unit for Carried #35 / setup-plan **S7**: checked-in prompt templates under
`prompts/browser/` and `bin/ade-browser-task` with **list / render / relay**.
Relay defaults to **dry-run** (print the prompt). `--send` calls `coding-bot ask`
when that binary is on PATH; otherwise the tool prints a self-contained prompt
and reports **unsent** (skills/tell-coding-bot). No live browser session is
required for this unit. A send proves neither completion nor the setting
(S7 §3). Secrets and access-widening tasks are refused (S7 §4).

Snapshot: 2026-11-10.

## Entry points

| Piece | Role |
|---|---|
| `prompts/browser/<task>.md` | One template per browser-only step |
| `bin/ade_browser_task.py` / `bin/ade-browser-task` | List, render, dry-run/send relay |
| `just browser-task` / `browser-task-list` / `browser-task-render` | Thin recipes over the bin tool |

Owner/repo defaults come from transitional `config/github.toml` when present
(same source as S8). Override with `--owner` / `--repo`.

## Commands

```
ade-browser-task list [--root DIR] [--json]
ade-browser-task render TASK [--root DIR] [--owner O] [--repo R] [--json]
ade-browser-task relay TASK [--root DIR] [--owner O] [--repo R]
                            [--dry-run|--send] [--json]
```

- **list** — every `prompts/browser/*.md` task id (skips `README.md`).
- **render** — substitute `{{owner}}`, `{{repo}}`, `{{owner_repo}}`,
  `{{app_name}}`, `{{manifest}}`; print the prompt. Template `url:` must stay
  on `https://github.com/…` after substitution.
- **relay** — default dry-run (print prompt, status `dry-run`). `--send` runs
  `coding-bot ask -` with the prompt on stdin when `coding-bot` is on PATH;
  missing or failed ask → status `unsent` plus the prompt for operator paste.
  Status `sent` means only that ask exited 0.

Just recipes: `just browser-task-list`, `browser-task-render task=<id>`,
`browser-task task=<id>` (dry-run relay), `browser-task-send task=<id>`
(`--send`).

## Templates shipped in this unit

| Task | URL (pattern) | Control |
|---|---|---|
| `github-app-create` | `https://github.com/settings/apps/new` | Manifest create confirm; install on configured repo only; private key stays with the operator |
| `pr-access` | `https://github.com/<owner>/<repo>/settings/access` | Pull request creation → Collaborators only (API preferred when available) |
| `issue-access` | `https://github.com/<owner>/<repo>/settings/general` | Issues → Creation allowed by → Collaborators only |

Every template ends with: change nothing else, report before/after, ask the
operator on surprise. Templates set `widens_access: false`. Task ids in the
widen deny list (`add-collaborator`, …) and any template with
`widens_access: true` are refused.

## Never through the bot

- Secrets (App private key): operator downloads and `gh secret set … < file`.
- Anything that widens access (collaborator, bypass actor).
- Anything taken from a GitHub artifact not written by the owner.

`ade-browser-task` refuses PEM / secret flags on argv (same rule as
`ade-github-setup`).

## Related

- Plan: [setup-plan.md](setup-plan.md) S7 (and S8 for merge-gate App create).
- Coding bot pointer: [skills/tell-coding-bot/SKILL.md](../skills/tell-coding-bot/SKILL.md).
- Hardening context: [security/argon-injection-review-2026-11-07.md](security/argon-injection-review-2026-11-07.md) D3 / H2.
