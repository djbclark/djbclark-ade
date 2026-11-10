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
| `bin/ade_browser_task_state.py` | Opt-in pr-access lifecycle, deadline registration and API readback |
| `just browser-task` / `browser-task-list` / `browser-task-render` | Thin recipes over the bin tool |

Owner/repo defaults come from transitional `config/github.toml` when present
(same source as S8). Override with `--owner` / `--repo`.

## Commands

```
ade-browser-task list [--root DIR] [--json]
ade-browser-task render TASK [--root DIR] [--owner O] [--repo R] [--json]
ade-browser-task relay TASK [--root DIR] [--owner O] [--repo R]
                            [--dry-run|--send] [--json]
ade-browser-task track pr-access --name NAME --deadline-seconds N
                        --notify-owner ID [--owner O --repo R] [--dry-run|--yes]
                        [--root DIR] [--state-dir DIR] [--json]
ade-browser-task status NAME [--state-dir DIR] [--json]
ade-browser-task verify NAME [--dry-run] [--state-dir DIR] [--json]
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

## Opt-in pr-access lifecycle (2026-11-10)

Only `pr-access` currently has completion readback in this tool. `track` defaults
to a plan: no state writes, subprocesses, sends or API requests. `--dry-run` makes
that choice explicit; `--yes` creates a pending record and registers an
announce-only `bin/deadline start … --on-expire notify --checkpoint RECORD`
wait for the supplied recipient. A task name uses lowercase letters, digits and
hyphens, starts with a letter and has at most 48 characters. Deadline seconds
must be 1–86400; the notification recipient is a nonempty ID, not a prompt.

For example, after inspecting the default plan, explicitly register a wait:

```sh
bin/ade-browser-task track pr-access --name repo-pr-access --deadline-seconds 600 \
  --notify-owner AGENT_ID --owner OWNER --repo REPO --yes
bin/ade-browser-task relay pr-access --owner OWNER --repo REPO --dry-run
# Operator relays separately when ready; tracking never sends the prompt.
bin/ade-browser-task verify repo-pr-access --dry-run
bin/ade-browser-task verify repo-pr-access --json
bin/ade-browser-task status repo-pr-access --json
```

Records default to `~/.local/state/ade/browser-tasks/` (`--state-dir` overrides).
The target, rendered-template/URL SHA256 and deadline are fixed at creation;
existing names cannot be replaced. Records contain no rendered prompt, bot
reply, credentials, raw API body or subprocess output. Atomic replacement and a
per-record lock serialize creation/verification. `status` reads local state
without writes or network access and projects overdue pending records as
`expired`; it is not a fresh GitHub check.

Successful registration is reported only after matching the deadline tool's
structured receipt, including its registration ID. Names include a random suffix
to avoid collisions across task directories. Missing/nonzero registration is
reported as failed/unknown monitoring with exit 1; a crash, timeout or malformed
reply may leave a real deadline registered, so the intent record remains and
registration is never retried automatically. Inspect the record and `deadline ls`
to reconcile uncertainty. This command does not install the deadline sweep job
or prove that it is running; external expiry notification depends on that
existing job and its delivery path. No receipt establishes task completion.

`verify` performs only `gh api --hostname github.com --method GET repos/OWNER/REPO`,
using S6's API version header. The hostname is fixed to the template's
`github.com` even when `GH_HOST` selects an enterprise host. It requires the
exact repository identity (case-insensitive),
`has_pull_requests: true` and
`pull_request_creation_policy: "collaborators_only"`. Missing fields, mismatched
identity, unreadable JSON, failed authentication/network calls or a changed
template binding leave the task not done. It checks time again after the bounded
request; proof arriving at/after the fixed deadline cannot complete the task.
Expired records cannot be revived. `verify --dry-run` prints the GET argv and
changes nothing; ordinary verification persists only a narrow observation.
Completed-record proof must also name `github.com`; a completed record without
that host binding is refused rather than treated as valid historical evidence.

On matching readback before the deadline, the record becomes `completed` and
the tool closes its confirmed deadline registration with `deadline done`.
Cleanup failure remains explicit and cannot invalidate the API proof. An
unconfirmed registration is never deregistered automatically. A completed record
is historical evidence at `completed_at`, not a promise against later drift;
subsequent `verify` calls return it without replaying requests or sends. Create
a new named task for a fresh observation. Verification exit 0 means completed
(or dry-run described); exit 1 means not done/error. `status` exits 0 for any
readable record, including pending/expired. Parser errors exit 2.

`issue-access` remains unverified: its template documents no REST policy field,
and the separate-account POST denial probe is outside this unit.
`github-app-create` also remains unverified: App existence or a send receipt
cannot establish the requested identity, permissions and repository-only
installation. No API writes, browser session, private key or live acceptance
was performed for this unit. Automatic polling and remaining template-specific
verification are still pending; the lifecycle commands introduce no scheduler.

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
