# Wave 6 follow-up — shim and `acp-run` deletion readiness

Snapshot: 2026-11-09. Queue Carried **item 1**. The slim-down's Wave 6
**shipped the shims** (`docs/slim/PLAN.md` F, gate marked done). This doc is the
**deletion readiness** checklist for the follow-up PR that removes
`skills/session-finder/relay.py`, `bin/acp-dispatch`, and `tools/acp-run`
after one Mac live cycle — **do not delete them in this readiness PR**. Soft
deadline **2026-11-20**
(`tests/test_relay_shim.py::test_the_shim_is_removed_by_2026_11_20`).
`bin/review-launch` and its boundary tests stay (E8 / review rule 11).

Gate tool: `bin/wave6-delete-check` (exit 0 only when every gate below is
green; prints named reasons otherwise). Run it before opening the deletion
PR. New code already calls Paseo directly (`paseo send`, `paseo run`).

## A. Remaining in-repo callers (must be gone or archived before delete)

Skills and tools that still teach or invoke the shims as **live** commands
(grep on 2026-11-09; `docs/history/`, `docs/slim/reports/`, `docs/slim/briefs/`,
`docs/handoffs/`, `docs/checkins/` are exempt from live refs).
`wave6-delete-check` scans the paths in column 1:

| Path | Replace with / action |
|---|---|
| `skills/fan-out/SKILL.md` | native `paseo run` / `paseo wait` / `paseo send` (footer from orchestration-practices, not `acp-dispatch footer`) |
| `skills/model-routing/SKILL.md` | drop legacy `acp-dispatch <agent> --model …` examples; `route_agent.py show` / `paseo run --provider …` only |
| `skills/session-handoff/SKILL.md` | Paseo's `paseo-handoff` / `paseo send`; no absolute `relay.py` |
| `skills/old-handoff-use-paseo-handoff/SKILL.md` | same; drop `acp-dispatch check` / slice wording |
| `skills/oc-go-key/SKILL.md` | `paseo send`; drop `relay.py` absolute-path examples |
| `skills/loose/SKILL.md` | **port** the upstream-issue reader off `acp-run --perm deny` (queue Carried 34 leftovers); Paseo read-only / deny path |
| `skills/baton/SKILL.md` | drop `acp-dispatch check` / `resume` / `reap` rearm instructions |
| `skills/research/SKILL.md` | dispatch via `paseo run`; drop `acp-dispatch` examples |
| `skills/dialogue/SKILL.md` | drop live `acp-run` kind alias as current; archive wording only |
| `AGENTS.md` standing order 10 + "Two shims" machine-context bullet | remove the "until 2026-11-20" shim sentence when the files are gone |
| `bin/load-watch`, `bin/deadline`, `bin/instruction-lint`, `bin/ade_claims.py` | argv / process matching must not treat `acp-run` or `acp-dispatch` as a live agent class; keep negative tests that prove retired names are **not** counted |

Fixture strings in `tests/test_load_watch_*.py` that **name** `acp-run` as a
negative example may stay when the assertion is "do not treat this as a live
agent".

Open Wave 6 caller-rewrite PRs (base `master` or stacked tips) cover parts of
this table; the deletion PR waits until `wave6-delete-check` reports
`callers_skills`, `callers_bins` and `callers_loose` green.

## B. Mac live-cycle proof commands (paste into the deletion PR)

Sooner than 2026-11-20 is allowed when **every** C3 row is migrated or waived
**and** these show no remaining caller. Run on the Mac after the slim final
merge's live cycle; paste stdout into the deletion PR (and into the evidence
JSON for `wave6-delete-check --evidence`):

```bash
# B1. No live shim argv (agents / launchd / leftover waiters)
pgrep -lf 'relay\.py|acp-dispatch|acp-run' || true
launchctl list 2>/dev/null | grep -E 'acp-dispatch|acp-run' || true
# B2. No outstanding dispatch records (C7). `acp-dispatch ls` does not exist —
# use `check` on the state root and Paseo's label listing. Failures are real;
# an empty/drained result is exit 0 / empty JSON.
STATE="${ACP_DISPATCH_STATE:-$HOME/.local/state/bigteam}"
if ! command -v acp-dispatch >/dev/null 2>&1; then
  echo "B2: acp-dispatch not on PATH (record as drained only after uninstall + empty paseo ls)"
elif [ ! -d "$STATE" ]; then
  echo "B2: no state dir at $STATE (empty)"
else
  acp-dispatch check "$STATE"
fi
paseo ls -g --label ade.via=acp-dispatch --json
# B3. Standing order 10 smoke without the shim (named ack path)
paseo send --help >/dev/null
paseo run --help >/dev/null
# optional: two-agent ack round with `paseo send --json --no-wait` and
# `Please reply: ack <your id>` — see AGENTS.md order 10
```

Evidence JSON shape (`wave6-delete-check --evidence PATH`):

```json
{
  "recorded": "2026-11-XX",
  "c3": {
    "tendcf": "migrated",
    "nix2cf": "migrated",
    "cfengine": "waived",
    "paseo_upstream": "waived",
    "plektra": "migrated",
    "paseo4herdr": "migrated",
    "pi": "migrated",
    "sudo_secretspec": "migrated",
    "aiuse": "migrated",
    "paseo_runner": "migrated",
    "site_public_home_agents": "waived",
    "aiuse_config_opencode_go": "waived"
  },
  "mac": {
    "relay_idle": true,
    "acp_dispatch_idle": true,
    "acp_run_idle": true,
    "paseo_smoke_ok": true
  }
}
```

Each `c3` value is exactly `migrated` or `waived`. A waive needs the
operator's one-line note in `docs/slim/log.md`.

Wave 6's final PR already re-ran C7/C1 as its merge gate; this follow-up only
needs proof the **cycle after that merge** left the shims idle.

## C. C3 gates (outside files; order 11)

PLAN.md C3. The slim lead may merge in the five named repos and asks when
unsure; everything else is a proposal. Tick each before the deletion PR
merges (`wave6-delete-check` reads the evidence JSON keys above):

| Key | Outside | Names |
|---|---|---|
| `tendcf` | tendcf `AGENTS.md` | `acp-dispatch --kind frontier`, `acp-run`, `relay.py`, … |
| `nix2cf` | nix2cf `AGENTS.md` | same |
| `cfengine` | CFEngine | `cfenginewatch`, `watch`, `fleet-watch` |
| `paseo_upstream` | Paseo upstream | `paseowatch` |
| `plektra` | Plektra | `acp-dispatch`, `relay.py`, `autorename`, `self-slash` |
| `paseo4herdr` | paseo4herdr | `acp-dispatch`, `relay.py`, `self-slash` |
| `pi` | Pi (`pi/extensions/…`, hand links, `agent_guard.py`) | I4f |
| `sudo_secretspec` | sudo-secretspec | `relay.py`, `acp-dispatch`/`acp-run` as clients |
| `aiuse` | **aiuse** (incl. `src/aiuse/collectors/acp_usage.py`) | queue Carried 34 |
| `paseo_runner` | paseo-runner | same clients |
| `site_public_home_agents` | `~/ops/site-public-djbclark/home-agents.md` item 40 | `coding-bot` |
| `aiuse_config_opencode_go` | `~/.config/aiuse/config.toml` | `opencode-go` exclusion (after PR 260) |

## D. Exact files to remove (deletion PR only)

| Path | Notes |
|---|---|
| `skills/session-finder/relay.py` | E3 shim; soft deadline 2026-11-20 |
| `tests/test_relay_shim.py` | includes the date assert |
| `bin/acp-dispatch` | E6 shim over `paseo run` |
| `bin/acp-dispatch-wait` | DELETE with the shim (ledger); C7 drain first |
| `config/acp-dispatch-report-schema.json` | only the shim validates against it |
| `tools/acp-run/` | whole tree |
| `tests/test_acp_dispatch.py` and shim-only siblings | go with the shim |
| `tests/test_acp_run_*` | ~4.5k named in PLAN E6 |
| `bin/go_model_policy.py`, `config/go-model-policy.json`, `tests/test_go_model_policy.py` | SHIM with `acp-run` once opencode retirement / PR 260 allows (ledger ruling 5) |
| `docs/dispatch-footer.md`, `docs/agent-guard-contract.md` | fold still-true facts into orchestration-practices / review-boundary, then remove or `docs/history/` |

**Keep (explicit):** `bin/review-launch`, `bin/adversary_marker.py`,
review-boundary docs and tests. `bin/agent_guard.py` until the deletion PR
decides whether `review-launch` or a surviving Pi path still needs it
(ledger A4).

After the bins go: `bin/ade-roster --write`.

## E. Test and doc updates required with the deletion PR

1. Drop or rewrite every test that imports only the shims (section D).
2. Port boundary coverage already owned by `bin/review-launch` (do **not**
   delete `tests` that review-launch still needs — ledger ruling 3:
   `test_acp_run_deny.py` / `test_acp_run_read_only.py` were the source; confirm
   review-launch's own tests cover the boundary before deleting).
3. AGENTS.md: standing order 10 and machine-context "Two shims" bullet.
4. README roster regeneration; `docs/skills.md` / orchestration docs that still
   present the shims as current.
5. Changelog fragment under `### Removed` (one line per user-visible deletion),
   citing queue Carried 1.
6. Remove or archive this readiness doc's "must rewrite" table rows that are
   done; keep a short "deleted on YYYY-MM-DD" note in `docs/slim/log.md`.

## F. Pi sole-TUI (related, not the same PR)

Policy: `docs/tui-security-and-pi-migration.md` A1–A6, `docs/setup-plan.md`
"Current operator policy — 2026-11-08", `docs/pi-services.md`.

Wave 6 deletion does **not** finish Pi migration. Keep these as separate
tracks (Linux-safe in-repo docs/routing first; Mac installs and pool
acceptance need the operator):

1. Routing and skills mention only Pi + retained vendor clients + Hermes.
2. Install catalog (`config/install.toml`) does not reinstall omp / OpenCode /
   Crush / Goose / Aider / Qwen Code as default components.
3. Per-pool acceptance before automatic routing (OpenAI API vs Codex sub;
   Anthropic API vs Claude sub; Google; etc.) — queue Carried 18 for Claude
   API-through-Pi after funding.
4. Archive / uninstall of retired TUIs on the Mac (operator step; order 11 for
   live settings).

## G. Suggested PR shape

1. **Delete readiness** (this file + `bin/wave6-delete-check` + queue/PLAN
   pointers): lands first; **does not delete shims**.
2. **Caller rewrite PR(s)** path-disjoint: skills + AGENTS machine-context +
   load-watch negative matchers + `skills/loose` port.
3. **Deletion PR** last: remove section D; paste Mac evidence; run
   `bin/wave6-delete-check --evidence <json>` (must exit 0); adversary marker
   on the head.

Do not start (3) until (2) is green and C3 is ticked or waived.

## H. Links

- Plan: [PLAN.md](PLAN.md) F Wave 6, E3, E6, C3, I1, I2, I8
- Ledger: [ledger.md](ledger.md) A4 (`agent_guard.py` keep-through-Wave-6)
- Queue: [../queue.md](../queue.md) Carried item 1
- Gate: [`bin/wave6-delete-check`](../../bin/wave6-delete-check)
- Standing orders: [../../AGENTS.md](../../AGENTS.md) 10 and "Two shims"
- Pi: [../tui-security-and-pi-migration.md](../tui-security-and-pi-migration.md), [../pi-services.md](../pi-services.md)
