# djbclark-ade — an agentic development environment

One operator, one Mac, many coding agents run as one environment: the skills every agent loads, the few tools
that start, steer and review them, and the docs that record what was verified. **Paseo is the only harness**
(2026-10-31). Providers kept (pool audit 2026-11-06, rulings 2026-11-07; Pi sole-TUI 2026-11-08/09): **claude, codex,
cursor, antigravity, pi, hermes**, each on its own paid pool, and **grok-bot** (Cursor-billed, through peer-link).
omp/OpenCode are retired as live TUIs (routing `retired = true`; packaging may remain until Wave 6 cleanup). Agents
read [AGENTS.md](AGENTS.md) (`CLAUDE.md` links to it) first; this page is the map.

## The loop

1. **Find**: `paseo ls -a -g --json` lists every live agent and where it works; `paseo agent inspect ID --json` says
   what one is doing. Continue a topic by messaging its agent, by `/baton` from its handoff, or start fresh.
2. **Start**: `paseo run --provider P/M --title T [--thinking E] [--mode M] "<prompt>"`, in its own worktree with
   `--new-workspace worktree`. Which provider, model and effort: `bin/route_agent.py plan`, [`model-routing`](skills/model-routing/SKILL.md).
3. **Answer**: `paseo permit ls` lists pending permission cards; the asks / questions-please plugins (installed at the final merge) are the
   operator's inbox. Agents message each other with `paseo send --json` (positional id + message / `--prompt`; ask for
   `ack <your id>` and prove the return path). The one-cycle shim `skills/session-finder/relay.py` remains until Wave 6
   deletion (soft deadline 2026-11-20; [docs/slim/wave6-follow-up.md](docs/slim/wave6-follow-up.md)) — do not start new
   call sites on it.
4. **Carry**: [`handoff`](skills/handoff/SKILL.md) (Tier 2 document), [`session-handoff`](skills/session-handoff/SKILL.md)
   (Tier 1 pointer), [`baton`](skills/baton/SKILL.md) (`/resume`); [`loose`](skills/loose/SKILL.md) and [`steps`](skills/steps/SKILL.md) walk what is open.
5. **Fan out**: [`fan-out`](skills/fan-out/SKILL.md): the Agent tool or a Workflow in process; `paseo run --no-wait` for a
   slice in its own worktree; `paseo wait` to collect. Rules: [docs/orchestration-practices.md](docs/orchestration-practices.md).
   `bin/acp-dispatch` is a transitional `paseo run` shim scheduled for the same Wave 6 deletion — not the default launch path.

## Layout

| Path | What |
|---|---|
| `skills/` | the canonical copy of every hand-written skill (edit here, never through a TUI's path); [published roster](https://github.com/djbclark/djbclark-ade/blob/generated-roster/ROSTER.md) |
| `bin/` | the tools; [published roster](https://github.com/djbclark/djbclark-ade/blob/generated-roster/ROSTER.md). `libexec/git-hooks/` and `libexec/agent-bin/git` are the git guard's hooks and shim |
| `claude/` | Claude Code `agents/` (`adversary`, `backend`, `fable-deep`, `ux`), `hooks/`, `commands/` (only `resume.md`), linked from `~/.claude/` |
| `agents/<tui>/*.tmpl` | live Claude, Codex and Hermes config templates (opencode tmpl is residual packaging); secrets as `{{ secret "NAME" }}`; `bin/ade-template-check` is their gate ([agents/README.md](agents/README.md)) |
| `config/` | `routing.toml` (pools, `[lead].fable_lead`), `gates.toml` (frontier allowance), `secret-deny.toml`, `pr-policy.toml`, schemas |
| `tools/acp-run/`, `opencode-plugins/`, `omp/` | transitional ACP client (removed with `acp-dispatch` in Wave 6 deletion); OpenCode plugins; omp's commands — Pi is the sole 3rd-party TUI policy ([docs/tui-security-and-pi-migration.md](docs/tui-security-and-pi-migration.md)) |
| `docs/` | AGENTS.md lists the live docs; `docs/history/` holds retired designs and records, `docs/slim/` the slim-down's plan and log |
| `changelog.d/`, `graft/` | one changelog fragment per PR (review rule 10); the generated context graph (`graft build`) |

## Install and update (this machine)

```sh
~/src/djbclark-ade/bin/skill-everywhere <name>          # link one skill into every TUI's skills dir
~/src/djbclark-ade/bin/skill-everywhere --all           # every public, private and site skill
~/src/djbclark-ade/bin/ade-update --check               # report only; exit 10 when behind
~/src/djbclark-ade/bin/ade-update                       # fast-forward, relink skills, check links, print the changelog delta
```

Targets: `~/.claude/skills` (cursor-agent reads it too), `~/.agents/skills` (Codex + Pi),
Hermes' external dir, a copy for Grok Bot; roots: this repo, `~/ops/site-private/skills`,
`~/ops/site-public-djbclark/skills`. Then `/reload-skills` in running Claude sessions. Paseo's `paseo*` skills come
from Paseo (`npx skills add getpaseo/paseo`). Details: [docs/skill-everywhere.md](docs/skill-everywhere.md).

## The review gate

Master takes changes **by PR only** (branch protection, admins included). The PR body carries the adversary's
verdict marker ([docs/code-review.md](docs/code-review.md) rule 1; AGENTS.md keeps a short pointer); the
`adversary-marker` Action (logic in `bin/adversary_marker.py`) reads it and posts the required
`adversary-marker` status beside the Tests checks. `bin/review-pr PR` is the local review (rule 11: Claude
inside `bin/review-launch`'s boundary, or its trusted YOLO mode for an owner-authored PR, [docs/review-boundary.md](docs/review-boundary.md)) and prints the
marker. After a body edit `gh workflow run adversary-marker.yml -f pr=N`; wait with `gh pr checks N --watch
--required`; merge with `gh pr merge --squash --match-head-commit <reviewed sha>`.

## Where things went

herdr (bar the `herdr4paseo`/`paseo4herdr` bridges and its server runner), Orca and BB left this repo on 2026-10-31
(still installed on the Mac, untouched). The slim-down of 2026-11-06/07 ([`docs/slim/log.md`](docs/slim/log.md)
records every merge and every behaviour lost on purpose) removed what Paseo or Claude Code now does natively, or what
served a retired provider: session-finder's search and launch, helm, self-slash, autorename, bigteam (now `fan-out`),
the watch family, the quota guard and fleet governor (Paseo's session-guard and usage-auto-resume plugins, installed at the final merge), pr-wait
and the Codex local review (now the `adversary-marker` Action and `bin/review-pr`, review rule 11), SkillOpt-Sleep, the web ladder, and the agy, crush, pi,
zcode, kiro, goose, qwen, devin, copilot CLI, cline, muse and grok CLI integrations; fifteen site skills and five
tools moved to site-djbclark. Retired designs are in [`docs/history/`](docs/history/), the old README at tag
`pre-slim-2026-11-06`, each retired TUI's lessons in [docs/tui-lessons-learned.md](docs/tui-lessons-learned.md).
Every live doc is in AGENTS.md's "Read before acting" table; [docs/queue.md](docs/queue.md) holds what is carried.

## Roster

[Current skill and tool roster](https://github.com/djbclark/djbclark-ade/blob/generated-roster/ROSTER.md)
— generated automatically after every merge to master by the
[Roster workflow](https://github.com/djbclark/djbclark-ade/actions/workflows/roster.yml).
The generated page records its source commit and links to that snapshot. It lives on a separate
branch so inventory changes cannot conflict with open PRs. To inspect a local checkout, run
`bin/ade-roster`; `--write` and `--check` remain available for documents with roster markers.


## Workflow migration

[Old way versus new way](docs/old-way-new-way.md) compares legacy skills with native Paseo,
records plugin advice, and defines the Linux/macOS cross-host handoff acceptance checks.
