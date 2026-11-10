# Wave 6 follow-up — shim and `acp-run` deletion

Snapshot: 2026-11-09. The slim-down's Wave 6 **shipped the shims**
(`docs/slim/PLAN.md` F, gate marked done). This doc is the **deletion**
checklist for the follow-up PR: remove `skills/session-finder/relay.py`,
`bin/acp-dispatch`, and `tools/acp-run` after one live cycle, **at the latest
2026-11-20** (`tests/test_relay_shim.py::test_the_shim_is_removed_by_2026_11_20`).
`bin/review-launch` and its boundary tests stay (E8 / review rule 11).

New code already calls Paseo directly (`paseo send`, `paseo run`). This PR
only deletes the temporary wrappers and rewrites their remaining callers.

## A. Delete in-repo (the follow-up PR)

| Path | Why |
|---|---|
| `skills/session-finder/relay.py` | E3 shim over `paseo send --json` |
| `tests/test_relay_shim.py` | goes with the shim (including the 2026-11-20 date assert) |
| `bin/acp-dispatch` | E6 shim over `paseo run` |
| `tests/test_acp_dispatch.py` (and siblings that import only the shim) | go with the shim |
| `config/acp-dispatch-report-schema.json` | only the shim validates against it |
| `tools/acp-run/` (the script and its tree) | goes with the shims (E6) |
| `tests/test_acp_run_*` | ~4.5k tests named in PLAN E6; delete with `acp-run` |
| `docs/dispatch-footer.md`, `docs/agent-guard-contract.md` | "both go with the shim in Wave 6" (AGENTS.md table) — fold any still-true facts into `docs/orchestration-practices.md` / `docs/review-boundary.md`, then remove or archive under `docs/history/` |

**Keep (explicit):** `bin/review-launch`, `bin/adversary_marker.py`, review-boundary docs and tests, `bin/agent_guard.py` until the follow-up decides whether `review-launch` or a surviving Pi path still needs it (ledger A4).

## B. Rewrite in-repo callers before the delete lands

Skills and tools that still teach or invoke the shims (grep on 2026-11-09;
historical `docs/history/`, `docs/slim/reports/`, `docs/checkins/` are exempt
from live refs):

| Path | Replace with |
|---|---|
| `skills/fan-out/SKILL.md` | native `paseo run` / `paseo wait` / `paseo send` (footer text from orchestration-practices, not `acp-dispatch footer`) |
| `skills/model-routing/SKILL.md` | drop legacy `acp-dispatch <agent> --model …` examples; `route_agent.py show` / `paseo run --provider …` only |
| `skills/session-handoff/SKILL.md`, `skills/old-handoff-use-paseo-handoff/SKILL.md` | Paseo's `paseo-handoff` / `paseo send`; no absolute `relay.py` |
| `skills/oc-go-key/SKILL.md` | drop or rewrite any `acp-run` / retired-TUI path (Pi sole-TUI policy) |
| `AGENTS.md` standing order 10 | already points at `paseo send`; remove the "until 2026-11-20" shim sentence and the "Two shims" machine-context bullet when the files are gone |
| `bin/load-watch`, `bin/deadline`, `bin/instruction-lint`, `bin/ade_claims.py` | any argv / process matching that treats `acp-run` or `acp-dispatch` as a live agent class must treat `paseo` (or nothing) instead; keep tests that prove retired names are **not** counted as agents |
| `README.md` roster | regenerate with `bin/ade-roster --write` after the bins go |
| `changelog.d/<branch>.md` | one `### Removed` line per user-visible deletion |

Fixture strings in `tests/test_load_watch_*.py` that **name** `acp-run` as a negative example may stay if the assertion is "do not treat this as a live agent"; rewrite only when the matcher still special-cases the shim as positive.

## C. Outside files (C3) — order 11; migrate or waive per file

PLAN.md C3. The slim lead may merge in these five repos and asks when unsure;
everything else is a proposal. Tick each before the deletion PR merges:

| Outside | Names | Status (fill on Mac / by lead) |
|---|---|---|
| tendcf / nix2cf `AGENTS.md` | `acp-dispatch --kind frontier`, `acp-run`, `relay.py`, … | |
| CFEngine | `cfenginewatch`, `watch`, `fleet-watch` | |
| Paseo upstream | `paseowatch` | |
| Plektra | `acp-dispatch`, `relay.py`, `autorename`, `self-slash` | |
| paseo4herdr | `acp-dispatch`, `relay.py`, `self-slash` | |
| Pi (`pi/extensions/…`, hand links, `agent_guard.py`) | I4f | |
| sudo-secretspec, **aiuse**, paseo-runner | `relay.py`, `acp-dispatch`/`acp-run` as clients (I4g) | |
| `~/ops/site-public-djbclark/home-agents.md` item 40 | `coding-bot` | |
| `~/.config/aiuse/config.toml` | `opencode-go` exclusion (drop after PR 260 decision) | |

A waived row needs the operator's one-line waive in `docs/slim/log.md`.

## D. Live-cycle evidence (Mac; paste into the deletion PR)

Sooner than 2026-11-20 is allowed when **every** C3 row is migrated or waived
**and** these show no remaining caller:

1. `relay.py` / `acp-dispatch` / `acp-run` process and log scan (no live argv
   from agents or launchd after the cycle window).
2. Re-run of C7 drain items that still apply post-slim (no resumable
   `acp-dispatch` records, no scheduled `auto-resume` for the shim).
3. `paseo send --json` / `paseo run` smoke from a lead agent (standing order 10
   ack path) without going through the shim.

Wave 6's final PR already re-ran C7/C1 as its merge gate; this follow-up only
needs proof the **cycle after that merge** left the shims idle.

## E. Pi sole-TUI (related, not the same PR)

Policy: `docs/tui-security-and-pi-migration.md` A1–A6, `docs/setup-plan.md`
"Current operator policy — 2026-11-08", `docs/pi-services.md`.

Wave 6 deletion does **not** finish Pi migration. Keep these as separate
tracks (Linux-safe in-repo docs/routing first; Mac installs and pool
acceptance need the operator):

1. Routing and skills mention only Pi + retained vendor clients + Hermes.
2. Install catalog (`config/install.toml`) does not reinstall omp / OpenCode /
   Crush / Goose / Aider / Qwen Code as default components.
3. Per-pool acceptance before automatic routing (OpenAI API vs Codex sub;
   Anthropic API vs Claude sub; Google; etc.) — queue Carried 17 for Claude
   API-through-Pi after funding.
4. Archive / uninstall of retired TUIs on the Mac (operator step; order 11 for
   live settings).

## F. Suggested PR shape

1. **Docs-only precursor** (this file + PLAN/queue pointers): lands with the
   docs/changelog CI short-circuit.
2. **Caller rewrite PR(s)** path-disjoint from install work: skills + AGENTS
   machine-context + load-watch negative matchers.
3. **Deletion PR** last: remove the three trees and their tests; fold dispatch
   footer / agent-guard-contract; `ade-roster --write`; changelog fragment;
   paste Mac live-cycle evidence; adversary marker on the head.

Do not start (3) until (2) is green and C3 is ticked or waived.

## G. Links

- Plan: [PLAN.md](PLAN.md) F Wave 6, E3, E6, C3, I1, I2, I8
- Ledger: [ledger.md](ledger.md) A4 (`agent_guard.py` keep-through-Wave-6)
- Queue: [../queue.md](../queue.md) (add a Carried line pointing here when this doc lands)
- Standing orders: [../../AGENTS.md](../../AGENTS.md) 10 and "Two shims"
- Pi: [../tui-security-and-pi-migration.md](../tui-security-and-pi-migration.md), [../pi-services.md](../pi-services.md)
