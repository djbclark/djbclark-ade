# SkillOpt-Sleep — the nightly learning cycle for every agent on this Mac

Set up 2026-10-12. [SkillOpt](https://microsoft.github.io/SkillOpt/)
(microsoft/SkillOpt) treats a skill file as trainable state: SkillOpt-Sleep
mines past agent sessions into tasks, replays them against the current skills,
proposes bounded edits, and keeps an edit only if a held-out validation gate
does not regress. Proposals are **staged**; nothing changes a live skill until
someone runs `skillopt-sleep adopt`. Day-to-day use is the
[`skillopt-sleep`](../skills/skillopt-sleep/SKILL.md) skill (`/skillopt-sleep`).
The model calls go through a failover chain built on
[`bin/failover.py`](failover.md).

## 1. What runs when

| When | What |
|---|---|
| 03:30 nightly | launchd `com.djbclark.skillopt-sleep` runs `bin/skillopt-night`. |
| Each night | For each source with data (claude, codex, cursor, opencode, copilot_cli, pi), one stateful `skillopt-sleep run --project ~/src/djbclark-ade --scope all --source <s> --backend handoff --skill-root ~/src/djbclark-ade/skills --preferences <docs/skillopt-preferences.md> --max-sessions N --progress --json`, sequentially, under `nice -n 10`. Each handoff round's prompts are answered through the chain (section 4). |
| Until the chain is enabled | No `"enabled": true` chain in `~/.skillopt-sleep/night.json`: the runner prints "waiting for backend decision", records `waiting-backend`, exits 0. Nothing is mined or spent. |

Guards in `bin/skillopt-night`: the chain policy check (a chain naming a denied
or non-allowlisted route is refused whole, with one Hermes line), the overload
gate from `bin/acp-dispatch` (load above 4x CPUs or critical memory pressure;
waits up to 30 min then skips the night), and a lock so two nights never
overlap. `--dry-run` always runs `skillopt-sleep dry-run --backend mock`, never
touches the chain and never moves a checkpoint; it takes about 30 s for all six
sources. `skillopt-night chain-check` runs only the chain preflights and prints
the table.

## 2. Paths

| Path | What |
|---|---|
| `~/.local/bin/skillopt-sleep` | The CLI. `uv tool install "skillopt @ git+https://github.com/microsoft/SkillOpt"`, upstream main at **343db229dbd5ddaf9df6b1d5540d8bcdb2604d5c** (2026-10-12; PyPI 0.2.0 lacks multi-skill fan-out, OpenAI-compatible endpoints, the OpenCode/Cursor/Copilot/Pi sources and the handoff backend). Upgrade: `uv tool upgrade skillopt`, then rerun the dry-run. |
| `~/.skillopt-sleep/config.json` | SkillOpt's config (copy: [`skillopt-sleep-config.example.json`](skillopt-sleep-config.example.json)). Its `backend: "mock"` only affects hand-run commands; the runner passes `--backend handoff`. |
| `~/.skillopt-sleep/night.json` | The runner's own config: the chain, allowlist, sizing (copy: [`skillopt-sleep-night.example.json`](skillopt-sleep-night.example.json)). A separate file because SkillOpt's config is upstream's namespace. |
| `~/.skillopt-sleep/state.json` | Upstream state: night counter, harvest checkpoint, slow memory, history. |
| `~/.skillopt-sleep/evidence/` | Dry-run evidence logs. **Sensitive** (truncated prompts and replies). |
| `~/src/djbclark-ade/.skillopt-sleep/staging/<night>/` | A real night's `report.md`, `report.json`, `diagnostics.json`, `manifest.json`, `evidence.jsonl` (sensitive), per-skill proposals, and `backup/` after an adoption. Git-ignored. |
| `~/src/djbclark-ade/.skillopt-sleep-handoff/<source>/` | The running night's handoff rounds (`PROMPTS.md`, `pending.json`, `digests.json`, `tasks.json`, `answers/`). Git-ignored; moved to `handoff-archive/` when the night finishes. |
| `~/.local/state/skillopt-sleep/` | Runner state: `<date>-<source>.log` (`-dry` for dry-runs), `nights.jsonl` (one line per source night), `attempts.jsonl` (every preflight and attempt, from bin/failover.py), `cursors.json`, `codex-home/` shim, `handoff-archive/` (last ten), `launchd.out/.err`. |
| `launchd/com.djbclark.skillopt-sleep.plist` | The job; `skillopt-night install` copies it to `~/Library/LaunchAgents/` and bootstraps it, `skillopt-night uninstall` removes it. |
| `skills/skillopt-sleep-learned/SKILL.md` | The managed catch-all target (`target_skill_path`): lessons that belong to no single skill. |
| [`skillopt-preferences.md`](skillopt-preferences.md) | House rules passed as `--preferences` to every reflect step. |

## 3. SkillOpt's config

Keys set beyond upstream defaults: `projects: "all"`, `multi_skill_fanout:
true` (one gated proposal per skill a session invoked, resolved from
`.claude/skills`, `.agents/skills`, the Claude home roots and `--skill-root`),
`gate_no_regression: true` (reject any candidate that lowers any validation
score), `edit_budget: 4`, `max_tasks_per_night: 40`, `evolve_memory: true`
(proposes edits to the project's `CLAUDE.md`, which here is a symlink to
`AGENTS.md`), `evolve_skill: true`, `target_skill_path` and `skill_roots` as
above, `redact_secrets: true`, `evidence_log: true`, `auto_adopt: false`, and
absolute `opencode_db`, `opencode_path`, `cursor_path`, `codex_path`.
`lookback_hours` stays 72: a source's first night reads only the last 72 hours.
For a deliberate backfill run once by hand with `--lookback-hours N` (0 = all
history; expensive).

**`max_tokens_per_night` is not enforced** at 343db229: the key exists in
`config.py` but nothing reads it (draft upstream issue in
[upstream-issues.md](upstream-issues.md) section 14). Spend is bounded by
`max_sessions` and `max_tasks_per_night`, `edit_budget`, the fan-out groups,
`max_rounds` and the per-source timeout.

## 4. The backend: a failover chain through acp-run

**Why the handoff backend.** SkillOpt's `get_backend` is a fixed if-chain over
backend names, and an unknown name silently becomes the mock backend, so no
external backend can be registered without patching the installed package. The
`handoff` backend makes no model calls itself: each round it writes the prompts
it needs to `pending.json` and exits 3. The runner answers every prompt through
the chain and reruns, until the engine finishes (typically 3 to 6 rounds;
`max_rounds` caps it). Each prompt is answered by a fresh `acp-run` session in
an empty temporary directory with `--perm deny` (no tools, no project context),
or by one OpenAI-compatible request for the SIPB entry. That is what upstream
asks for: every answer in a fresh context, so the held-out gate is not
contaminated.

**One entry per source night.** All prompts of a source night are answered by
the same entry, so baseline and candidate scores come from one model. An entry
fails when its preflight fails, any answer fails (acp-run nonzero, a delivery
check such as quota or refusal, or an empty answer), the run ends nonzero, the
staging dir's `diagnostics.json` holds a `call_error` or "empty response on
all", or tasks were mined but none replayed. Then the runner restores
`state.json` from its pre-attempt copy, wipes the source's handoff dir and
reruns that source night on the next entry. When the chain is exhausted it
records `chain_exhausted` and sends one Hermes line.

**Policy** (operator, 2026-10-12). Allowed TUIs: `zcode`, `agy`, `opencode`
(OpenCode Go), `claude` (Haiku or Sonnet only), and the MIT SIPB
OpenAI-compatible endpoint as the last entry. Denied everywhere by
`bin/failover.py`: cursor, cline/ClinePass, Hermes, any Opus or Fable model.
`crush` is under discussion and not in the allowlist. A violating chain is
refused at load time, whole.

**Provisional chain** (installed with `"enabled": false`; the per-entry list,
TUI, vendor, model, version and effort, awaits operator approval). Readiness is
from `skillopt-night chain-check` on 2026-10-12:

| # | Entry | Vendor | Pool | Floor | Ready 2026-10-12 |
|---|---|---|---|---|---|
| 1 | opencode `opencode-go/deepseek-v4-flash` | OpenCode Go | opencode-go | 10% | yes (25.7%) |
| 2 | agy `gemini-3.8-flash`, effort medium (`gemini-3.8-flash-medium`) | Google | antigravity/gemini | 10% | yes (16.0%) |
| 3 | zcode, effort low (`--set thought=low`; zcode refuses `--model`) | Z.ai | zai | 10% | no: weekly window exhausted |
| 4 | claude `haiku` | Anthropic | claude/default | 15% | yes (20.0%) |
| 5 | claude `sonnet` | Anthropic | claude/default | 15% | yes (20.0%) |
| 6 | sipb `qwen3-coder:30b` via `http://127.0.0.1:8890/api` (sipb-llms-proxy), key `MIT_SIPB_API_KEY` | MIT SIPB | none tracked (aiuse has no windows) | none | yes (proxy reachable, key declared) |

Effort levers that exist: zcode `--set thought=low|high|max`; agy's effort is
the model id suffix (`-low`, `-medium`, `-high`); the claude and opencode ACP
agents expose no effort option to acp-run, so their entries take none.

**Sizing.** Round 1 sends one LLM-mining prompt per harvested session: a free
handoff dry-run on 2026-10-12 produced **118** prompts for the claude source at
upstream's default cap of 120 sessions. Every prompt is a whole agent spawn, so
each one also pays that agent's system prompt. `max_sessions` (40 in the
provisional file), `jobs` (parallel answers, 2), `max_rounds` (8) and
`source_timeout_s` (7200) in night.json size it. Put free or under-used pools
first and Claude late.

**Enable or change.** Edit `~/.skillopt-sleep/night.json` (and the example copy),
run `~/src/djbclark-ade/bin/skillopt-night chain-check`, then set
`"enabled": true`. Optionally run one small source by hand first:
`~/src/djbclark-ade/bin/skillopt-night --source pi`. Set `enabled` back to
`false` to pause the nightly job.

## 5. Reading a night

1. `tail ~/.local/state/skillopt-sleep/nights.jsonl`: per source, `status`
   (`ok`, `chain_exhausted`; `waiting-backend`, `chain-invalid`, `skipped:`
   for the whole night), `entry` (which chain entry answered), `rounds`,
   `answered`, `sessions`, `tasks`, `gate` (`accept`/`reject`), `proposals`,
   `staging_dir`, and `failed` (every entry that was skipped or failed, why).
2. `tail ~/.local/state/skillopt-sleep/attempts.jsonl`: each preflight and
   attempt with its reason and seconds.
3. `skillopt-sleep status --project ~/src/djbclark-ade`: `latest_staging`,
   `staged_skills` (pending), `adopted_skills`, history tail.
4. `<latest_staging>/report.md`: what was mined, baseline vs candidate scores,
   each proposed edit and why it passed or failed the gate.
5. A night that stages anything sends one Hermes line: "djbclark-ade:
   skillopt-sleep staged N proposal(s) from <sources>; review: ...". An
   exhausted chain and a refused chain each send one line too.

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

Runner workarounds for upstream behaviour:

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
3. **Per-source handoff dirs.** Upstream's handoff dir is one per project, and
   it pins `digests.json`/`tasks.json` for resumption; it is archived only when
   a night stages something. The runner sets `SKILLOPT_SLEEP_HANDOFF_DIR` per
   source and archives the dir after every finished night, so a rejected night
   never replays stale pinned tasks the next night.

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
   The same treatment would suit backends (`get_backend` silently maps unknown
   names to mock), which would let the chain plug in directly instead of
   through handoff rounds.
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

The chain entry that answers a night receives transcript excerpts from
**every** project on this Mac: user prompts, final replies, tools and skills
used, with obvious secrets redacted (`redact_secrets`; `pending.json` prompts
are redacted too). Which vendor sees them depends on which entry answered:
`nights.jsonl` names it. `evidence.jsonl`, `~/.skillopt-sleep/evidence/` and
the handoff dirs and archive hold prompts and replies: never commit, paste or
upload them.
