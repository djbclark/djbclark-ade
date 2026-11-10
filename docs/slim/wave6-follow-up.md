# Wave 6 follow-up — shim and `acp-run` deletion readiness

Snapshot: 2026-11-10 (status: in-repo §A LIVE_RE callers cleared on
`origin/master` after `#498` — `wave6-delete-check --inventory` →
`callers_remaining=0` / `gate_exits.callers=0`; C3 `--dry-run` FIXTURE
path tightened; **Mac live captured on bigmac** —
[`mac-live-2026-11-10.md`](mac-live-2026-11-10.md); delete gate still
exit 1 on C3+B2+date; soft delete ~2026-11-20).
Queue Carried **item 1**.
The slim-down's Wave 6 **shipped the shims** (`docs/slim/PLAN.md` F). This doc
is the **deletion readiness** checklist for the follow-up PR that removes
`skills/session-finder/relay.py`, `bin/acp-dispatch`, and `tools/acp-run`
after one Mac live cycle — **do not delete them in this readiness PR**. Soft
deadline **2026-11-20**
(`tests/test_relay_shim.py::test_the_shim_is_removed_by_2026_11_20`).
`bin/review-launch` and its boundary tests stay (E8 / review rule 11).

Gate tool: `bin/wave6-delete-check` (exit 0 only when every gate below is
green; prints named reasons otherwise). **CI / local shape regression (not
deletion-ready):** `bin/wave6-delete-check --dry-run` points at
`tests/fixtures/wave6-mac-proofs/evidence.FIXTURE.json`, checks FAILCLOSED
non-empty Mac **and** C3 FIXTURE labels + Linux-safe `cmd:`/`verified:`
(or `waive:`) shape, skips callers/soft_deadline, keeps
`mac_live_blocked: true` / `ready: false` even when exit 0, and
`--evidence` on a FIXTURE or `--linux-safe` bundle fails closed
(`mac_not_live`). **Caller inventory (Mac still blocked):**
`bin/wave6-delete-check --inventory` lists every remaining LIVE_RE hit under
the gated §A paths untruncated, fails on ungated `skills/*/SKILL.md` holes,
and reports `gate_exits` (`callers`, `evaluate_no_evidence`, optional
`dry_run_fixture`) proving those refs are gated — `ready` stays false and
`mac_live_blocked` stays true (combine with `--dry-run` for FIXTURE shape in
the same pass). Mac capture harness: `bin/wave6-mac-proof-capture --live
--out DIR` (Darwin only) or `--linux-safe --out DIR` (pgrep + optional
paseo; launchctl SKIPPED; labeled `LINUX-SAFE — NOT Mac live-cycle`). Run
`--evidence` on **Darwin `--live`** captures before opening the deletion PR.
New code already calls Paseo directly (`paseo send`, `paseo run`).

## Status (2026-11-10) — current open work

Queue Carried **[item 1](../queue.md)** residual. **Nothing here deletes the
shims.** Soft deadline for relay / dispatch / `acp-run` removal:
**~2026-11-20** (sooner only when every gate below is green, plus Mac live
+ C3 evidence; `--allow-early` only with operator yes).

| Gate | State | Where / why |
|---|---|---|
| C3 dry-run FIXTURE path | **ready (tightened)** | [#441](https://github.com/djbclark/djbclark-ade/pull/441) + [#453](https://github.com/djbclark/djbclark-ade/pull/453) + [#470](https://github.com/djbclark/djbclark-ade/pull/470): `--dry-run` FAILCLOSEs Mac **and** C3 FIXTURE labels + Linux-safe probe shape (`ready` stays `false`; `mac_live_blocked: true`) |
| Caller inventory (§A list) | **ready (inventory)** | `bin/wave6-delete-check --inventory` lists every gated §A hit + `gate_exits` proving coverage; ungated `skills/*/SKILL.md` FAILCLOSED; never Mac-live / never `ready` |
| Linux-safe Mac partial probes | **ready** | `bin/wave6-mac-proof-capture --linux-safe` (pgrep + optional paseo; launchctl SKIPPED). `wave6-delete-check` reports `mac_not_live` if used as `--evidence` |
| Mac live cycle | **captured (bigmac 2026-11-10)** | Real `--live` exit 0 ×2; archive SHA `18eab71c…ce236155`. B2 **not** drained (live lead `0cc34651…` labeled `ade.via=acp-dispatch`). Details: [`mac-live-2026-11-10.md`](mac-live-2026-11-10.md) |
| In-repo callers (§A) | **green on `master` (`#498`)** | Confirmed 2026-11-10: `wave6-delete-check --inventory` → `callers_remaining=0` / `gate_exits.callers=0` on `origin/master`. Full check still fails C3+B2+date, not `callers_*` |
| C3 outside migrations (§C) | **5 migrated / 7 open** | Migrated: `paseo_upstream`, `plektra`, `pi`, `paseo_runner`, `aiuse_config_opencode_go`. Open: `tendcf`, `nix2cf`, `cfengine`, `paseo4herdr`, `sudo_secretspec`, `aiuse`, `site_public_home_agents`. Extra: `fleet-watch` still calls `relay.py` |
| Soft delete deadline | **~2026-11-20** | `test_the_shim_is_removed_by_2026_11_20`; `--allow-early` **not** granted; deletion PR waits on green evidence |

### What the operator must supply

1. **Mac live-cycle proofs** — **received 2026-11-10** (bigmac). Still need B2 drain/recapture after lead `0cc34651…` label clears. Do not open the deletion PR on this capture alone.
2. **C3 row evidence** for the seven open keys in §C: either a migrated probe paste in `c3_proofs.<key>`, or a one-line waive in `docs/slim/log.md` copied into that proof file. **Do not invent waives.** Proposed historical lines for `paseo4herdr` / `sudo_secretspec` are in the Mac archive's `outside-migration-proposals.md` (NOT granted).
3. **Extra outside client:** authorize migration of `~/ops/site-private-djbclark/bin/fleet-watch` off `UPSTREAM_RELAY` / `relay.py` (order 11).
4. **Deletion PR last**: `bin/wave6-delete-check --evidence <json>` must exit 0 (**never** treat `--dry-run`, `--inventory`, FIXTURE, or `--linux-safe` as deletion-ready); keep `bin/review-launch`. No `--allow-early` without explicit yes after C3+Mac complete.

### Readiness stack (merged; do not treat as delete)

- [#398](https://github.com/djbclark/djbclark-ade/pull/398) — delete-readiness checklist + `bin/wave6-delete-check`
- [#417](https://github.com/djbclark/djbclark-ade/pull/417) — C3/Mac proof-file FAILCLOSED evidence
- [#441](https://github.com/djbclark/djbclark-ade/pull/441) — Mac harness + FIXTURE `--dry-run` path
- [#453](https://github.com/djbclark/djbclark-ade/pull/453) — C3 status (FIXTURE ready, Mac blocked)
- [#470](https://github.com/djbclark/djbclark-ade/pull/470) — C3 FIXTURE tighten + `--linux-safe` Mac probes (`mac_not_live`)
- [#472](https://github.com/djbclark/djbclark-ade/pull/472) — caller `--inventory`: untruncated §A reference list + `gate_exits` proof while Mac blocked
- [#498](https://github.com/djbclark/djbclark-ade/pull/498) — scrub remaining LIVE_RE callers to zero (keep shims); inventory `callers_remaining=0`
- LIVE_RE teaching refs outside the §A gate stay until the deletion PR; Mac still blocked

## A. In-repo callers (scrubbed on `#498`, 2026-11-10)

Gated §A LIVE_RE callers are **cleared**: `bin/wave6-delete-check --inventory`
→ `callers_remaining=0` / `gate_exits.callers=0` on master after `#498`. The
paths below are what the gate still scans; teaching refs outside this set
(README, orchestration docs, slim history) stay until the deletion PR.

| Path | Status after `#498` |
|---|---|
| `skills/fan-out/SKILL.md` | native `paseo` teaching; completion-notice kept |
| `skills/model-routing/SKILL.md` | `route_agent.py` / `paseo run` only |
| `skills/session-handoff/SKILL.md` | `paseo-handoff` / `paseo send` |
| `skills/old-handoff-use-paseo-handoff/SKILL.md` | no live `acp-dispatch` / `relay.py` |
| `skills/oc-go-key/SKILL.md` | `paseo send` |
| `skills/loose/SKILL.md` | Claude CLI `-p` reader (no `acp-run --perm deny`) |
| `skills/baton/SKILL.md` | no live `acp-dispatch check/resume/reap` |
| `skills/research/SKILL.md` | `paseo run` dispatch teaching |
| `skills/dialogue/SKILL.md` | archive wording only for `acp-run` |
| `bin/deadline`, `bin/load-watch`, `bin/instruction-lint`, `bin/ade_claims.py` | not counted as live agent class; negative tests keep retired names out |

Deletion still waits on Mac live + C3 evidence (§B/§C), not on this table.

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
(`evidence.FIXTURE.json` + `*.FIXTURE.txt` proofs). Mac proofs start with
`FIXTURE — NOT live Mac stdout`; C3 proofs start with
`FIXTURE — NOT live outside-repo probe` and carry the Linux-safe `cmd:`
(or `waive:`) + `verified:` shape from §C. Tests under
`tests/test_wave6_mac_proof_fixtures.py` prove FAILCLOSED non-empty shape,
C3 label/shape, that `--evidence` on the FIXTURE bundle reports
`mac_not_live`, and that the harness refuses to invent live stdout on
non-Darwin.

**Regression CLI (FIXTURE only):**

```bash
bin/wave6-delete-check --dry-run --json
# exit 0 + fixture_shape_ok: true + mac_live_blocked: true
#   → labeled Mac+C3 FIXTURE proofs have FAILCLOSED shape
# ready is always false in --dry-run (never treat as deletion green)
# exit 2 if combined with --evidence / --allow-early
```

**Caller inventory (Mac still blocked; not deletion-ready):**

```bash
bin/wave6-delete-check --inventory --json
# exit 0 + inventory_ok / coverage_ok + mac_live_blocked: true + ready: false
#   → references[] lists every gated §A LIVE_RE hit (untruncated)
#   → gate_exits.callers == 1 while hits remain; evaluate_no_evidence == 1
#   → ungated skills/*/SKILL.md LIVE_RE hits → exit 1 (ungated_skills)
bin/wave6-delete-check --inventory --dry-run --json
# also sets gate_exits.dry_run_fixture from the FIXTURE shape check
# exit 2 if combined with --evidence / --allow-early
```

`--dry-run` FAILCLOSEs (`fixture_invalid:…`) when the bundle is missing, the
`recorded` field is not `FIXTURE-not-live-Mac`, the note omits FIXTURE/NOT, a
`mac_proofs` / `c3_proofs` file drops its FIXTURE first-line label, or a
proof drops the Linux-safe `cmd:`/`verified:` (or `waive:`) shape — so
inventing “live” stdout under the fixture path cannot green the shape check.

**Linux-safe partial Mac probes (still not Mac live):**

```bash
bin/wave6-mac-proof-capture --linux-safe --out ./wave6-linux-safe --json
# writes *.LINUX-SAFE.txt (pgrep + optional paseo; launchctl SKIPPED)
# wave6-delete-check --evidence … → mac_not_live (Mac live still blocked)
```

**These fixtures / linux-safe captures are not deletion evidence.** After the
Mac live cycle:

1. `bin/wave6-mac-proof-capture --live --out ./wave6-evidence --json`
   (Darwin + `--live` only; non-Darwin refuses — see harness docstring).
2. Merge the printed `mac_proofs` map into the real `evidence.json` (keep C3
   outside probes / waives from §C).
3. `bin/wave6-delete-check --evidence ./wave6-evidence/evidence.json` (exit 0).
   Do **not** use `--dry-run`, the FIXTURE bundle, or `--linux-safe` output here.
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

**rg alternation (2026-11-10 Mac live):** use real ERE `|` inside the
pattern. Backslash-pipe `\|` under-matches and falsely reports clean.
Copy probes from the fenced block below (not from a table cell — markdown
`\|` escapes are not shell ERE). Empty match list = migrated; paste stdout
into `c3_proofs.<key>`.

| Key | Outside | Names to clear |
|---|---|---|
| `tendcf` | tendcf `AGENTS.md` | `acp-dispatch --kind frontier`, `acp-run`, `relay.py`, … |
| `nix2cf` | nix2cf `AGENTS.md` | same |
| `cfengine` | CFEngine (+ `cfengine-all` if present) | `cfenginewatch`, `watch`, `fleet-watch` |
| `paseo_upstream` | Paseo upstream | `paseowatch` |
| `plektra` | Plektra | `acp-dispatch`, `relay.py`, `autorename`, `self-slash` |
| `paseo4herdr` | paseo4herdr | `acp-dispatch`, `relay.py`, `self-slash` |
| `pi` | Pi (`pi/extensions/…`, hand links, `agent_guard.py`) | I4f |
| `sudo_secretspec` | sudo-secretspec | `relay.py`, `acp-dispatch`/`acp-run` as clients |
| `aiuse` | **aiuse** (incl. `src/aiuse/collectors/acp_usage.py`) | item 33 |
| `paseo_runner` | paseo-runner | same clients |
| `site_public_home_agents` | `~/ops/site-public-djbclark/home-agents.md` item 40 | `coding-bot` |
| `aiuse_config_opencode_go` | `~/.config/aiuse/config.toml` | `opencode-go` exclusion (after PR 260) |

```bash
# Intended ERE probes (paste into c3_proofs.<key>); empty = migrated
(cd ~/src/tendcf && rg -n -- 'acp-dispatch|acp-run|relay\.py' AGENTS.md)
(cd ~/src/nix2cf && rg -n -- 'acp-dispatch|acp-run|relay\.py' AGENTS.md)
(cd ~/src/cfengine-all && rg -n -- 'cfenginewatch|\bfleet-watch\b|bin/watch' .)   # also probe cfengine-core
(cd ~/src/paseo && rg -n -- 'paseowatch' .)
(cd ~/src/plektra-djbclark && rg -n -- 'acp-dispatch|relay\.py|autorename|self-slash' .)
(cd ~/src/paseo4herdr && rg -n -- 'acp-dispatch|relay\.py|self-slash' .)
(cd ~/.pi/agent && rg -n -- 'acp-dispatch|relay\.py|agent_guard|subagent' . 2>/dev/null)
(cd ~/src/sudo-secretspec && rg -n -- 'relay\.py|acp-dispatch|acp-run' .)
(cd ~/src/aiuse && rg -n -- 'acp-run|acp-dispatch|relay\.py|acp_usage' .)
(cd ~/src/paseo-runner && rg -n -- 'relay\.py|acp-dispatch|acp-run' .)
(cd ~/ops/site-public-djbclark && rg -n -- 'coding-bot|acp-run|acp-dispatch' home-agents.md)
rg -n -- 'opencode-go' ~/.config/aiuse/config.toml
```

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
| `bin/go_model_policy.py`, `config/go-model_policy.json`, `tests/test_go_model_policy.py` | **DECIDE** (ledger ruling 5): `route_agent.py` still loads the JSON. **Recommended default:** keep the trio in the shim-deletion PR; delete only acp-run's install path/tests. Rewrite `route_agent` off the policy, or waive opencode (PR 260 / J2) first, only with an explicit operator pick. |
| `docs/dispatch-footer.md`, `docs/agent-guard-contract.md` | fold still-true facts into orchestration-practices / review-boundary, then remove or `docs/history/` |

**Keep (explicit):** `bin/review-launch`, `bin/adversary_marker.py`,
review-boundary docs and `tests/test_review_launch.py`. `bin/agent_guard.py` (+
`tests/test_agent_guard.py` / `tests/test_omp_operator_gate.py`): prefer
**delete** in the shim PR unless a live Pi path still imports it (ledger A4;
`review-launch` does not). Confirm with `rg agent_guard` on the deletion tip.

After the bins go: `bin/ade-roster --write`.

## E. Test and doc updates required with the deletion PR

1. Drop or rewrite every test that imports only the shims (section D), including
   all `tests/test_acp_run_*.py` and `tests/test_acp_dispatch.py`.
2. Boundary coverage: `tests/test_review_launch.py` already owns deny/read-only
   allowlists, secret-deny, symlink refuse, and tripwire (2026-11-10 prep map).
   **Safe to drop** `tests/test_acp_run_deny.py` and
   `tests/test_acp_run_read_only.py` with `tools/acp-run/` — do **not** delete
   `tests/test_review_launch.py`. Drop `.github/workflows/test.yml` explicit
   acp / go_model path entries only when those files go.
3. AGENTS.md: standing order 10 (native `paseo send` + named ack only) and
   delete the machine-context "Two shims" bullet; review rule 4 loses the
   `tools/acp-run --verify` `shell=True` exception once acp-run is gone.
4. README roster regeneration (`bin/ade-roster --write`); `docs/skills.md` /
   `docs/orchestration-practices.md` / `docs/review-boundary.md` that still
   present the shims as current; fold or archive `docs/dispatch-footer.md` and
   `docs/agent-guard-contract.md`.
5. Changelog fragment under `### Removed` (one line per user-visible deletion),
   citing queue Carried **item 1** (Wave 6 shim deletion).
6. Remove or archive this readiness doc's "must rewrite" table rows that are
   done; keep a short "deleted on YYYY-MM-DD" note in `docs/slim/log.md`; close
   or reword queue Carried item 1 after the deletion merges.

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

- Status (open work): [§Status](#status-2026-11-10--current-open-work) above
- Plan: [PLAN.md](PLAN.md) F Wave 6, E3, E6, C3, I1, I2, I8
- Ledger: [ledger.md](ledger.md) A4 (`agent_guard.py`)
- Queue: [../queue.md](../queue.md) Carried item 33
- Gate: [`bin/wave6-delete-check`](../../bin/wave6-delete-check)
- Mac harness: [`bin/wave6-mac-proof-capture`](../../bin/wave6-mac-proof-capture)
- FIXTURE bundle (NOT live): [`tests/fixtures/wave6-mac-proofs/`](../../tests/fixtures/wave6-mac-proofs/)
- Standing orders: [../../AGENTS.md](../../AGENTS.md) 10 and "Two shims"
- Stack: [#398](https://github.com/djbclark/djbclark-ade/pull/398) → [#417](https://github.com/djbclark/djbclark-ade/pull/417) → [#441](https://github.com/djbclark/djbclark-ade/pull/441) → [#453](https://github.com/djbclark/djbclark-ade/pull/453) → [#470](https://github.com/djbclark/djbclark-ade/pull/470) → [#472](https://github.com/djbclark/djbclark-ade/pull/472) → LIVE_RE `<agent>` / `` `acp-dispatch` `` tighten (this tip; Mac still blocked)
- LIVE_RE notes: `wave6-delete-check` also matches backticked `` `acp-dispatch` `` and `acp-dispatch <agent>` placeholders (not only named-agent argv), so `--inventory` / `callers_skills` cannot go green while rewrite tips leave those live teachings
