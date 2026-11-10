# Wave 6 follow-up — shim and `acp-run` deletion readiness

Snapshot: 2026-11-10 (Mac proof harness + FIXTURE bundle + `--dry-run`
FAILCLOSED shape path; live Mac cycle still pending). Queue Carried
**item 33**. The slim-down's Wave 6 **shipped the shims** (`docs/slim/PLAN.md`
F). This doc is the **deletion readiness** checklist for the follow-up PR that
removes `skills/session-finder/relay.py`, `bin/acp-dispatch`, and
`tools/acp-run` after one Mac live cycle — **do not delete them in this
readiness PR**. Soft deadline **2026-11-20**
(`tests/test_relay_shim.py::test_the_shim_is_removed_by_2026_11_20`).
`bin/review-launch` and its boundary tests stay (E8 / review rule 11).

Gate tool: `bin/wave6-delete-check` (exit 0 only when every gate below is
green; prints named reasons otherwise). **CI / local shape regression (not
deletion-ready):** `bin/wave6-delete-check --dry-run` points at
`tests/fixtures/wave6-mac-proofs/evidence.FIXTURE.json`, checks FAILCLOSED
non-empty proof files + FIXTURE labels only, skips callers/soft_deadline, and
keeps `ready: false` even when exit 0. Mac capture harness:
`bin/wave6-mac-proof-capture --live --out DIR` (Darwin only; refuses to invent
Mac stdout elsewhere). Run `--evidence` on **live** captures before opening
the deletion PR. New code already calls Paseo directly (`paseo send`,
`paseo run`).

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
| `skills/loose/SKILL.md` | **port** the upstream-issue reader off `acp-run --perm deny` (item 33); Paseo read-only / deny path |
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
`callers_skills` and `callers_loose` green.

## B. Mac live-cycle proof commands (paste into the deletion PR)

Sooner than 2026-11-20 is allowed when **every** C3 row is migrated or waived
**and** these show no remaining caller. Run on the Mac after the slim final
merge's live cycle; paste stdout into the deletion PR **and** into the
non-empty `mac_proofs` files named by the evidence JSON for
`wave6-delete-check --evidence` (see shape below):

```bash
# B1. No live shim argv (agents / launchd / leftover waiters).
# Idle (no match) is the desired state — always record cmd + exit / verified line
# so the capture is non-empty (wave6-delete-check FAILCLOSEs on empty proof files).
# Prefer bin/wave6-mac-proof-capture --live: it also covers acp-dispatch process/
# launchd in the dispatch proof and exits 1 on probe FAILED (not verified idle).
echo "cmd: pgrep -lf 'relay\\.py|acp-dispatch|acp-run'"
pgrep -lf 'relay\.py|acp-dispatch|acp-run' || echo "verified: no match (exit $?)"
echo "cmd: launchctl list | grep -E 'acp-dispatch|acp-run'"
# Do not `2>/dev/null | grep` alone: a failed launchctl with empty stdout must
# be FAILED, never "verified: no match".
launchctl list >"$TMPDIR/wave6-lc.out" 2>"$TMPDIR/wave6-lc.err"
lc_rc=$?
if [ "$lc_rc" -ne 0 ]; then
  [ -s "$TMPDIR/wave6-lc.err" ] && echo "stderr: $(cat "$TMPDIR/wave6-lc.err")"
  echo "verified: FAILED launchctl (exit $lc_rc)"
else
  grep -E 'acp-dispatch|acp-run' "$TMPDIR/wave6-lc.out" \
    || echo "verified: no match (exit 0)"
fi
# B2. No outstanding dispatch records (C7). `acp-dispatch ls` does not exist —
# use `check` on the state root and Paseo's label listing. Failures are real;
# an empty/drained result is exit 0 / empty JSON — still echo a verified line.
# Also keep B1 process/launchd for acp-dispatch (harness puts them in this proof).
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
echo "verified: paseo send/run --help ok"
# optional: two-agent ack round with `paseo send --json --no-wait` and
# `Please reply: ack <your id>` — see AGENTS.md order 10
```

Evidence JSON shape (`wave6-delete-check --evidence PATH`). Status ticks
alone are not enough: every C3 key and Mac flag needs a **non-empty proof
file** named under `c3_proofs` / `mac_proofs` (paths relative to the evidence
JSON's directory). The gate FAILCLOSEs (`c3_<key>_proof_missing` /
`mac_<flag>_proof_missing`, exit 1) when a path is absent, empty or
unreadable — it never invents Mac stdout or outside-repo captures. A
successful Mac B1 idle probe (no matching process) must still leave a
non-empty file (`cmd:` + `verified: no match`); an empty redirect is treated
as a missing paste, not as idle proof:

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
  "c3_proofs": {
    "tendcf": "proofs/c3-tendcf.txt",
    "nix2cf": "proofs/c3-nix2cf.txt",
    "cfengine": "proofs/c3-cfengine.txt",
    "paseo_upstream": "proofs/c3-paseo-upstream.txt",
    "plektra": "proofs/c3-plektra.txt",
    "paseo4herdr": "proofs/c3-paseo4herdr.txt",
    "pi": "proofs/c3-pi.txt",
    "sudo_secretspec": "proofs/c3-sudo-secretspec.txt",
    "aiuse": "proofs/c3-aiuse.txt",
    "paseo_runner": "proofs/c3-paseo-runner.txt",
    "site_public_home_agents": "proofs/c3-site-public-home-agents.txt",
    "aiuse_config_opencode_go": "proofs/c3-aiuse-config-opencode-go.txt"
  },
  "mac": {
    "relay_idle": true,
    "acp_dispatch_idle": true,
    "acp_run_idle": true,
    "paseo_smoke_ok": true
  },
  "mac_proofs": {
    "relay_idle": "proofs/mac-b1-relay.txt",
    "acp_dispatch_idle": "proofs/mac-b2-acp-dispatch.txt",
    "acp_run_idle": "proofs/mac-b1-acp-run.txt",
    "paseo_smoke_ok": "proofs/mac-b3-paseo-smoke.txt"
  }
}
```

Each `c3` value is exactly `migrated` or `waived`. A waive needs the
operator's one-line note in `docs/slim/log.md`, and that note (or a paste of
it) must sit in the matching `c3_proofs` file. Mac proof files are
operator-captured on the Mac from section B (paste B1/B2/B3 stdout) or via
`bin/wave6-mac-proof-capture --live`. This readiness stack does **not** ship
invented live Mac proofs.

### B0. FIXTURE proofs (CI shape only) → replace after Mac live cycle

Without a Mac live cycle yet, CI uses a **labeled fixture** bundle at
[`tests/fixtures/wave6-mac-proofs/`](../../tests/fixtures/wave6-mac-proofs/)
(`evidence.FIXTURE.json` + `*.FIXTURE.txt` proofs). Every file starts with
`FIXTURE — NOT live Mac stdout` (or the C3 fixture equivalent). Tests under
`tests/test_wave6_mac_proof_fixtures.py` prove FAILCLOSED non-empty shape and
that the harness refuses to invent live stdout on non-Darwin.

**Regression CLI (FIXTURE only):**

```bash
bin/wave6-delete-check --dry-run --json
# exit 0 + fixture_shape_ok: true  → labeled FIXTURE proofs are non-empty
# ready is always false in --dry-run (never treat as deletion green)
# exit 2 if combined with --evidence / --allow-early
```

`--dry-run` FAILCLOSEs (`fixture_invalid:…`) when the bundle is missing, the
`recorded` field is not `FIXTURE-not-live-Mac`, the note omits FIXTURE/NOT, or
a `mac_proofs` file drops the FIXTURE first-line label — so inventing “live”
stdout under the fixture path cannot green the shape check.

**These fixtures are not deletion evidence.** After the Mac live cycle:

1. `bin/wave6-mac-proof-capture --live --out ./wave6-evidence --json`
   (Darwin + `--live` only; non-Darwin refuses — see harness docstring).
2. Merge the printed `mac_proofs` map into the real `evidence.json` (keep C3
   outside probes / waives from §C).
3. `bin/wave6-delete-check --evidence ./wave6-evidence/evidence.json` (exit 0).
   Do **not** use `--dry-run` here.
4. Paste live stdout into the deletion PR. Keep the FIXTURE bundle only as a
   shape regression, still labeled FIXTURE — never rename a fixture to look
   like a live capture.

Suggested capture (Mac; paths match the sample `mac_proofs` above). Prefer
`bin/wave6-mac-proof-capture --live --out "$EVID"` over hand redirects.
The harness exits **1** when any probe FAILED (diagnostics still written);
do not paste a failed capture as idle evidence — `wave6-delete-check` only
checks that proof files are non-empty.
**Do not** redirect bare `pgrep … || true` alone: when idle, that writes an
empty file and `wave6-delete-check` reports `mac_*_proof_missing` even though
idle is the desired state. Always record the command and an explicit
`verified: no match` (or match listing) plus exit status; mark probe failures
as `verified: FAILED` (preserve stderr), never as verified idle:

```bash
EVID=./wave6-evidence   # directory that will hold evidence.json + proofs/
mkdir -p "$EVID/proofs"
# B1 → relay_idle + acp_run_idle (split or share; both files must be non-empty)
{
  echo "cmd: pgrep -lf 'relay\\.py'"
  pgrep -lf 'relay\.py' || echo "verified: no match (exit $?)"
} > "$EVID/proofs/mac-b1-relay.txt"
{
  echo "cmd: pgrep -lf 'acp-run'"
  pgrep -lf 'acp-run' || echo "verified: no match pgrep (exit $?)"
  echo "cmd: launchctl list | grep -E 'acp-run'"
  launchctl list >"$EVID/proofs/.lc.out" 2>"$EVID/proofs/.lc.err"
  lc_rc=$?
  if [ "$lc_rc" -ne 0 ]; then
    [ -s "$EVID/proofs/.lc.err" ] && echo "stderr: $(cat "$EVID/proofs/.lc.err")"
    echo "verified: FAILED launchctl (exit $lc_rc)"
  else
    grep -E 'acp-run' "$EVID/proofs/.lc.out" \
      || echo "verified: no match launchctl (exit 0)"
  fi
  rm -f "$EVID/proofs/.lc.out" "$EVID/proofs/.lc.err"
} > "$EVID/proofs/mac-b1-acp-run.txt"
# B2 → acp_dispatch_idle (B1 process/launchd for acp-dispatch + B2 drain).
# Prefer the harness: it records launchctl/paseo failures as FAILED (with
# stderr), never as verified idle, and exits 1 when any probe fails.
{
  echo "cmd: pgrep -lf 'acp-dispatch'"
  pgrep -lf 'acp-dispatch' || echo "verified: no match pgrep (exit $?)"
  echo "cmd: launchctl list | grep -E 'acp-dispatch'"
  launchctl list >"$EVID/proofs/.lc.out" 2>"$EVID/proofs/.lc.err"
  lc_rc=$?
  if [ "$lc_rc" -ne 0 ]; then
    [ -s "$EVID/proofs/.lc.err" ] && echo "stderr: $(cat "$EVID/proofs/.lc.err")"
    echo "verified: FAILED launchctl (exit $lc_rc)"
  else
    grep -E 'acp-dispatch' "$EVID/proofs/.lc.out" \
      || echo "verified: no match launchctl (exit 0)"
  fi
  rm -f "$EVID/proofs/.lc.out" "$EVID/proofs/.lc.err"
  STATE="${ACP_DISPATCH_STATE:-$HOME/.local/state/bigteam}"
  if ! command -v acp-dispatch >/dev/null 2>&1; then
    echo "B2: acp-dispatch not on PATH"
  elif [ ! -d "$STATE" ]; then
    echo "B2: no state dir at $STATE (empty)"
  else
    acp-dispatch check "$STATE"
  fi
  echo "cmd: paseo ls -g --label ade.via=acp-dispatch --json"
  out=$(paseo ls -g --label ade.via=acp-dispatch --json 2>&1)
  ls_rc=$?
  if [ "$ls_rc" -ne 0 ]; then
    [ -n "$out" ] && printf '%s\n' "$out"
    echo "verified: FAILED paseo ls (exit $ls_rc)"
  elif [ -n "$out" ]; then
    printf '%s\n' "$out"
  else
    echo "verified: no match (empty paseo ls)"
  fi
} > "$EVID/proofs/mac-b2-acp-dispatch.txt"
# B3 → paseo_smoke_ok
{
  echo "cmd: paseo send --help; paseo run --help"
  if paseo send --help >/dev/null && paseo run --help >/dev/null; then
    echo "verified: paseo send/run --help ok (exit 0)"
  else
    echo "verified: FAILED (exit $?)"
  fi
} > "$EVID/proofs/mac-b3-paseo-smoke.txt"
```

## C. C3 gates (outside files; order 11)

PLAN.md C3. The slim lead may merge in the five named repos and asks when
unsure; everything else is a proposal. Tick each before the deletion PR
merges (`wave6-delete-check` reads the evidence JSON keys + proof files
above).

**Done when (per row):** either (a) `status=migrated` and the probe finds
**no** live shim / retired-tool names in the named outside path, with the
probe stdout (or a PR/merge citation) pasted into `c3_proofs.<key>`; or
(b) `status=waived` with the operator's one-line waive in
`docs/slim/log.md` pasted into that proof file. Missing/empty proof →
`c3_<key>_proof_missing` (exit 1). Order 11: probes on outside checkouts
are operator/lead work; this gate only checks the captured files.

| Key | Outside | Names to clear | Operator probe (paste into `c3_proofs.<key>`) |
|---|---|---|---|
| `tendcf` | tendcf `AGENTS.md` | `acp-dispatch --kind frontier`, `acp-run`, `relay.py`, … | In tendcf: `rg -n 'acp-dispatch\|acp-run\|relay\.py' AGENTS.md` (empty = migrated) |
| `nix2cf` | nix2cf `AGENTS.md` | same | In nix2cf: same `rg` on `AGENTS.md` |
| `cfengine` | CFEngine | `cfenginewatch`, `watch`, `fleet-watch` | In CFEngine checkout: `rg -n 'cfenginewatch\|\bfleet-watch\b\|bin/watch' .` |
| `paseo_upstream` | Paseo upstream | `paseowatch` | Against Paseo upstream / fleet-watch registration: `rg -n 'paseowatch' .` |
| `plektra` | Plektra | `acp-dispatch`, `relay.py`, `autorename`, `self-slash` | In Plektra: `rg -n 'acp-dispatch\|relay\.py\|autorename\|self-slash' .` |
| `paseo4herdr` | paseo4herdr | `acp-dispatch`, `relay.py`, `self-slash` | In paseo4herdr: `rg -n 'acp-dispatch\|relay\.py\|self-slash' .` |
| `pi` | Pi (`pi/extensions/…`, hand links, `agent_guard.py`) | I4f | In Pi tree: `rg -n 'acp-dispatch\|relay\.py\|agent_guard\|subagent' pi extensions hand 2>/dev/null` |
| `sudo_secretspec` | sudo-secretspec | `relay.py`, `acp-dispatch`/`acp-run` as clients | In sudo-secretspec: `rg -n 'relay\.py\|acp-dispatch\|acp-run' .` |
| `aiuse` | **aiuse** (incl. `src/aiuse/collectors/acp_usage.py`) | item 33 | In aiuse: `rg -n 'acp-run\|acp-dispatch\|relay\.py\|acp_usage' .` |
| `paseo_runner` | paseo-runner | same clients | In paseo-runner: `rg -n 'relay\.py\|acp-dispatch\|acp-run' .` |
| `site_public_home_agents` | `~/ops/site-public-djbclark/home-agents.md` item 40 | `coding-bot` | `rg -n 'coding-bot\|acp-run\|acp-dispatch' home-agents.md` |
| `aiuse_config_opencode_go` | `~/.config/aiuse/config.toml` | `opencode-go` exclusion (after PR 260) | `rg -n 'opencode-go' ~/.config/aiuse/config.toml` (gone or waived after PR 260) |

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
   citing queue item 33.
6. Remove or archive this readiness doc's "must rewrite" table rows that are
   done; keep a short "deleted on YYYY-MM-DD" note in `docs/slim/log.md`.

## F. Suggested PR shape

1. **Delete readiness** (this file + `bin/wave6-delete-check` + queue/PLAN
   pointers): lands first; **does not delete shims**.
2. **Caller rewrite PR(s)** path-disjoint: skills + AGENTS machine-context +
   load-watch negative matchers + `skills/loose` port.
3. **Deletion PR** last: remove section D; paste Mac evidence; run
   `bin/wave6-delete-check --evidence <json>` (must exit 0); adversary marker
   on the head.

Do not start (3) until (2) is green and C3 is ticked or waived.

## G. Links

- Plan: [PLAN.md](PLAN.md) F Wave 6, E3, E6, C3, I1, I2, I8
- Ledger: [ledger.md](ledger.md) A4 (`agent_guard.py`)
- Queue: [../queue.md](../queue.md) Carried item 33
- Gate: [`bin/wave6-delete-check`](../../bin/wave6-delete-check)
- Mac harness: [`bin/wave6-mac-proof-capture`](../../bin/wave6-mac-proof-capture)
- FIXTURE bundle (NOT live): [`tests/fixtures/wave6-mac-proofs/`](../../tests/fixtures/wave6-mac-proofs/)
- Standing orders: [../../AGENTS.md](../../AGENTS.md) 10 and "Two shims"
