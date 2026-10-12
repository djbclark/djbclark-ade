# SkillOpt-Sleep — the nightly learning cycle for every agent on this Mac

Set up 2026-10-12. [SkillOpt](https://microsoft.github.io/SkillOpt/)
(microsoft/SkillOpt) treats a skill file as trainable state: SkillOpt-Sleep
mines past agent sessions into tasks, replays them against the current skills,
proposes bounded edits, and keeps an edit only if a held-out validation gate
does not regress. Proposals are **staged**; nothing changes a live skill until
someone runs `skillopt-sleep adopt`. Day-to-day use is the
[`skillopt-sleep`](../skills/skillopt-sleep/SKILL.md) skill (`/skillopt-sleep`).

## 1. What runs when

| When | What |
|---|---|
| 03:30 nightly | launchd `com.djbclark.skillopt-sleep` runs `bin/skillopt-night`. |
| Each night | For each source with data (claude, codex, cursor, opencode, copilot_cli, pi): one `skillopt-sleep run --project ~/src/djbclark-ade --scope all --source <s> --skill-root ~/src/djbclark-ade/skills --preferences <docs/skillopt-preferences.md> --progress --json`, sequentially, under `nice -n 10`, 90 min timeout each. |
| Until a backend is chosen | The runner sees `backend: "mock"`, prints "waiting for backend decision", records `waiting-backend`, exits 0. Nothing is mined or spent. |

Guards in `bin/skillopt-night`: the overload gate from `bin/acp-dispatch`
(load above 4x CPUs or critical memory pressure; waits up to 30 min then skips
the night), a lock so two nights never overlap, and the mock refusal above.
`--dry-run` always runs `skillopt-sleep dry-run --backend mock` and never moves
a checkpoint; it takes about 30 s for all six sources.

## 2. Paths

| Path | What |
|---|---|
| `~/.local/bin/skillopt-sleep` | The CLI. `uv tool install "skillopt @ git+https://github.com/microsoft/SkillOpt"`, upstream main at **343db229dbd5ddaf9df6b1d5540d8bcdb2604d5c** (2026-10-12; PyPI 0.2.0 lacks multi-skill fan-out, OpenAI-compatible endpoints, the OpenCode/Cursor/Copilot/Pi sources and the handoff backend). Upgrade: `uv tool upgrade skillopt`, then rerun section 4's dry-run. |
| `~/.skillopt-sleep/config.json` | The config (copy: [`skillopt-sleep-config.example.json`](skillopt-sleep-config.example.json); keep them in step). |
| `~/.skillopt-sleep/state.json` | Upstream state: night counter, harvest checkpoint, slow memory, history. |
| `~/.skillopt-sleep/evidence/` | Dry-run evidence logs. **Sensitive** (truncated prompts and replies). |
| `~/src/djbclark-ade/.skillopt-sleep/staging/<night>/` | A real night's `report.md`, `report.json`, `diagnostics.json`, `manifest.json`, `evidence.jsonl` (sensitive), per-skill proposals, and `backup/` after an adoption. Git-ignored. |
| `~/src/djbclark-ade/.skillopt-sleep-handoff/` | Handoff rounds (`PROMPTS.md`, `pending.json`, `answers/`). Git-ignored. |
| `~/.local/state/skillopt-sleep/` | Runner state: `<date>-<source>.log` (`-dry` for dry-runs), `nights.jsonl` (one line per source run: rc, sessions, tasks, gate, proposals, staging dir), `cursors.json`, `codex-home/` shim, `launchd.out/.err`. |
| `launchd/com.djbclark.skillopt-sleep.plist` | The job; `skillopt-night install` copies it to `~/Library/LaunchAgents/` and bootstraps it, `skillopt-night uninstall` removes it. |
| `skills/skillopt-sleep-learned/SKILL.md` | The managed catch-all target (`target_skill_path`): lessons that belong to no single skill. |
| [`skillopt-preferences.md`](skillopt-preferences.md) | House rules passed as `--preferences` to every reflect step. |

## 3. The config

Keys set beyond upstream defaults: `projects: "all"`, `multi_skill_fanout:
true` (one gated proposal per skill a session invoked, resolved from
`.claude/skills`, `.agents/skills`, the Claude home roots and `--skill-root`),
`gate_no_regression: true` (reject any candidate that lowers any validation
score), `edit_budget: 4`, `max_tasks_per_night: 40`, `evolve_memory: true`
(proposes edits to the project's `CLAUDE.md`, which here is a symlink to
`AGENTS.md`), `evolve_skill: true`, `target_skill_path` and `skill_roots` as
above, `redact_secrets: true`, `evidence_log: true`, `auto_adopt: false`, and
absolute `opencode_db`, `opencode_path`, `cursor_path`, `codex_path`
(`~/.opencodex/bin/codex`). `lookback_hours` stays 72: a source's first night
reads only the last 72 hours. For a deliberate backfill run once by hand with
`--lookback-hours N` (0 = all history; expensive with a real backend).

**`max_tokens_per_night` is not enforced** at 343db229: the key exists in
`config.py` but nothing reads it (draft upstream issue in
[upstream-issues.md](upstream-issues.md) section 14). Spend per source run is
bounded only by `max_tasks_per_night`, `edit_budget`, the number of fan-out
skill groups, and the runner's 90 min timeout. Lower `max_tasks_per_night` to
cut spend.

## 4. Choosing and switching the backend

Upstream backends that fit this Mac (the lead asks the operator to choose):

1. **`opencode`**: the `opencode` CLI with project config, MCP and tools
   disabled, billed to the OpenCode Go pool. Works today, no secret needed.
   Transcript excerpts go to whichever provider OpenCode routes the model to.
2. **`azure_openai`** in OpenAI-compatible mode against the local LiteLLM proxy
   (`http://127.0.0.1:4000/v1`, override with `azure_endpoint`). `model` is a
   LiteLLM model name from `~/ops/site-djbclark/roles/litellm/` (2026-10-12):
   `go-kimi`, `go-deepseek-pro`, `go-deepseek-flash`, `go-glm-flash` (OpenCode
   Go pool, direct API, spend logged per key), `gemini-free`,
   `gemini-free-lite` (Gemini free tier; the role notes its RPM/RPD caps cannot
   carry bulk), `grok-sub` (SuperGrok subscription via the OAuth bridge), and
   `clinepass-*` (reserve pool: never). **Not available yet:** the runner reads
   the key with `sudo-secretspec` (`SKILLOPT_LITELLM_API_KEY`, else
   `LITELLM_MASTER_KEY`) and neither is declared in its schema. To enable,
   preferably with a dedicated virtual key (add an `{alias: skillopt-sleep,
   key: ...}` row to `litellm_client_keys` in the role and apply it), then:

   ```sh
   sudo-secretspec add SKILLOPT_LITELLM_API_KEY --description "LiteLLM virtual key for the nightly SkillOpt-Sleep run" --optional --reason "skillopt-night azure_openai backend"
   sudo-secretspec set SKILLOPT_LITELLM_API_KEY --reason "skillopt-night azure_openai backend"
   ```

   and mirror the declaration into the tracked declarations template (a
   runtime `add` shows as `template-check` drift until then). The key is held
   in memory and exported only into the child's environment.
3. **`handoff`**: the engine makes no model calls. It writes prompts; an agent
   session answers each in a fresh-context sub-agent (Opus on the Claude
   subscription) and reruns, 3 to 6 rounds a night. Manual: the runner does
   one source per night and pings when prompts are waiting
   (`skills/skillopt-sleep` section 5).

Roles can split: `target_backend`/`target_model` run the task attempts,
`optimizer_backend`/`optimizer_model` mine, judge and write edits (for example
target `opencode`, optimizer `handoff`). Backends to avoid: `claude` (draws the
shared Claude weekly pool that orchestration depends on), `codex` (its own
replay sessions get re-harvested, upstream issue 286), `cursor`.

**Switch** by editing `backend` (and `model`) in `~/.skillopt-sleep/config.json`
and the example copy, for instance:

```sh
python3 - <<'EOF'
import json, pathlib
p = pathlib.Path.home() / ".skillopt-sleep/config.json"
c = json.loads(p.read_text()); c["backend"] = "opencode"; c["model"] = ""
p.write_text(json.dumps(c, indent=2) + "\n")
EOF
```

Then check with `~/src/djbclark-ade/bin/skillopt-night --dry-run` (free), and
optionally one real source by hand: `~/src/djbclark-ade/bin/skillopt-night
--source pi` (smallest store). Setting `backend` back to `mock` pauses the
nightly job.

## 5. Reading a night

1. `tail ~/.local/state/skillopt-sleep/nights.jsonl`: per source, `rc`
   (0 ok, 3 handoff pending, 124 timeout), `sessions`, `tasks`, `gate`
   (`accept`/`reject`), `proposals`, `staging_dir`.
2. `skillopt-sleep status --project ~/src/djbclark-ade`: `latest_staging`,
   `staged_skills` (pending), `adopted_skills`, history tail.
3. `<latest_staging>/report.md`: what was mined, baseline vs candidate scores,
   each proposed edit and why it passed or failed the gate.
4. A night that stages anything sends one Hermes line: "djbclark-ade:
   skillopt-sleep staged N proposal(s) from <sources>; review: ...". Failures,
   pending handoff prompts and an unavailable backend each send one line too.

## 6. Adopting and rolling back

`skillopt-sleep adopt --project ~/src/djbclark-ade --skill <name>` (repeatable)
writes one staged proposal over the canonical skill (realpath, so the TUI
symlinks keep working); `--legacy` adopts the catch-all skill and `CLAUDE.md`
proposal, `--all-skills` every per-skill proposal. Each adoption first backs up
the live file under `<staging>/backup/` and refuses if the live file changed
since the night read it. An adoption is an ordinary commit in this repo: review
the diff, `git add` the skill path, commit naming the night, push. Roll back
with `git revert <sha>`, or copy `<staging>/backup/skills/<name>/SKILL.md` back
(upstream has no `revert` command yet: issue 247, PR 280). The `CLAUDE.md`
memory path resolves to `AGENTS.md` through the symlink; check the diff names
`AGENTS.md` before adopting it (not yet exercised here).

## 7. Sources

Supported upstream and present here (free harvest, 2026-10-12, full history
capped at 120 sessions per source):

| Source | Store | Sessions | Mined tasks |
|---|---|---|---|
| claude | `~/.claude/projects` | 120 (cap) | 40 |
| codex | `~/.codex/sessions` via the shim | 120 (cap) | 40 |
| cursor | `~/.cursor/projects` | 96 | 40 |
| opencode | `~/.local/share/opencode/opencode.db` | 54 | 32 |
| copilot_cli | `~/.copilot/session-store.db` | 31 | 28 |
| pi | `~/.pi/agent/sessions` | 3 | 1 |

Two runner workarounds for upstream behaviour:

1. **Per-source cursors.** Upstream keys the harvest checkpoint by project
   only, so the second source in a night would see only sessions newer than
   the first run. The runner keeps one cursor per source in `cursors.json` and
   swaps it into `state.json` before each run (draft upstream issue,
   [upstream-issues.md](upstream-issues.md) section 15). After a night,
   `state.json` holds the last source's cursor; a manual `skillopt-sleep run`
   uses that.
2. **Codex shim.** Upstream's codex harvester reads only a flat
   `~/.codex/archived_sessions` (Codex Desktop). Codex CLI writes
   `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`; the runner rebuilds
   `~/.local/state/skillopt-sleep/codex-home/archived_sessions/` as symlinks
   and passes `--codex-home`. Drop it when upstream PR 282 ("harvest Codex CLI
   rollout sessions") merges.

**Not supported upstream:** Hermes (`~/.hermes/sessions`), zcode (`~/.zcode`),
grok (`~/.grok/projects`), agy, muse, cline, and acp-dispatch job reports
(`~/.local/state/bigteam/*/jobs`). Their sessions are not learned from yet.

## 8. Phase 2: pluggable sources (queued, docs/queue.md)

`skillopt_sleep/harvest_sources.py` is a fixed if-chain over source names, each
returning `SessionDigest` records (session_id, project, git_branch, started_at,
ended_at, user_prompts, assistant_finals, tools_used, skills_used,
files_touched, feedback_signals, turn counts). Plan:

1. Upstream PR making sources pluggable: a `skillopt_sleep.sources` entry-point
   group (name to `harvest(cfg, since_iso, limit) -> list[SessionDigest]`) and
   a `--source-module pkg.mod:func` flag, plus the per-source checkpoint fix.
2. Adapters here for Hermes, zcode, grok, agy, muse, cline and acp-dispatch
   job reports, each with the replay-session filter.
3. `skillopt-night` gains those sources in its loop.

Searched upstream 2026-10-12 (issues and PRs: "source", "harvest", "plugin
entry point", "pluggable", "custom transcript", "per-source", "checkpoint",
"budget"): no pluggable-source proposal exists. Related, each adding one more
branch to the if-chain: issue 225 / PR 266 (DeepSeek Harness source), issue 97
(VS Code Copilot), PR 282 (Codex CLI rollouts), issue 286 / PR 287 (exclude
Codex replay sessions). Issue 247 / PR 280 (`revert`).

## 9. Privacy

A real backend receives transcript excerpts from **every** project on this
Mac: user prompts, final replies, tools and skills used, with obvious secrets
redacted (`redact_secrets`). The handoff backend keeps them in Claude
sub-agents. `evidence.jsonl` and `~/.skillopt-sleep/evidence/` hold truncated
prompts and replies: never commit, paste or upload them.
