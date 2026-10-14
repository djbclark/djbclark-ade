#!/usr/bin/env bash
# run-matrix.sh [OUTDIR] — unattended Plektra CI matrix on forgejo.mit.edu; no model needed.
# 1. Isolation run: CornerButtonThemeTest alone (as-is storage) with --info and heartbeats.
# 2. If that hangs the VM: repeat on tmpfs and stop. If not: run the full suite on as-is, tmpfs and loop
#    storage, one after another. Every run's log, step times, usage and last heartbeats go into
#    OUTDIR/summary.md. Hangs are detected (runner "context deadline exceeded", or timeout -> cancel).
# Needs git-forgejo / forgejo-api (sudo-secretspec) and a plektra checkout at ~/src/plektra-djbclark.
# Run it with run_in_background and read only OUTDIR/summary.md afterwards.
set -u
OUT=${1:-/tmp/matrix}; mkdir -p "$OUT"; SUM="$OUT/summary.md"
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd); S="$HERE/../../scripts"
RP=djbclark/plektra-djbclark; ISO_MIN=${ISO_MIN:-40}; FULL_MIN=${FULL_MIN:-75}
ISO_CMD="./gradlew :app:testStableDebugUnitTest --tests '*CornerButtonThemeTest' --info"
api() { "$S/forgejo-api" "$@"; }
latest_id() { api GET "/repos/$RP/actions/runs?limit=3" | jq -r '[.workflow_runs[].id]|max'; }
LAST_HUNG=0
run_one() {  # NAME STORAGE BRANCH MAXMIN [FULL_CMD]
  local name=$1 storage=$2 branch=$3 maxmin=$4 cmd=${5:-} before id st j t0
  before=$(latest_id)
  if [ -n "$cmd" ]; then export DERIVE_FULL_CMD="$cmd"; else unset DERIVE_FULL_CMD; fi
  "$HERE/push-bench.sh" "$storage" "$branch" > "$OUT/$name.push" 2>&1 || { echo "## $name: PUSH FAILED" >> "$SUM"; tail -3 "$OUT/$name.push" >> "$SUM"; LAST_HUNG=2; return; }
  for _ in $(seq 1 30); do id=$(latest_id); [ "$id" -gt "$before" ] && break; sleep 5; done
  t0=$(date +%s)
  while :; do
    st=$(api GET "/repos/$RP/actions/runs/$id" 2>/dev/null | jq -r .status)
    case "$st" in running|waiting|queued|"") ;; *) break;; esac
    if [ $(( $(date +%s) - t0 )) -gt $((maxmin*60)) ]; then api POST "/repos/$RP/actions/runs/$id/cancel" --yes > /dev/null 2>&1; st=timeout-cancelled; break; fi
    sleep 20
  done
  j=$(api GET "/repos/$RP/actions/runs/$id/jobs" | jq -r '.[0].id')
  api GET "/repos/$RP/actions/jobs/$j/logs" 2>&1 | sed 's/^[0-9T:.-]*Z //' > "$OUT/$name.log"
  "$S/ci-step-times" forgejo $RP "$id" > "$OUT/$name.tsv" 2>&1
  LAST_HUNG=0; if [ "$st" != success ] && grep -q 'context deadline exceeded' "$OUT/$name.log"; then LAST_HUNG=1; fi
  [ "$st" = timeout-cancelled ] && LAST_HUNG=1
  {
    echo; echo "## $name (run $id, storage=$storage) status=$st hung=$LAST_HUNG wall=$(( $(date +%s) - t0 ))s"
    echo '```'; cut -c1-150 "$OUT/$name.tsv"; echo '```'
    echo 'test results / usage / last heartbeats:'; echo '```'
    grep -E 'tests completed|BUILD (SUCCESSFUL|FAILED)|BENCHUSAGE|^(Filesystem|/dev/root|tmpfs|/dev/loop)|^Mem:|FAILED$' "$OUT/$name.log" | cut -c1-170 | tail -14
    grep -E 'HEARTBEAT' "$OUT/$name.log" | tail -3 | cut -c1-170
    grep -A3 -E 'HEARTBEAT' "$OUT/$name.log" | tail -4 | cut -c1-170
    echo '```'
  } >> "$SUM"
}
{ echo "# Matrix started $(date -u +%FT%TZ)"; } > "$SUM"
if [ "${MATRIX_MODE:-}" = diag ]; then   # one full-suite run with thread dumps of the hung test worker
  export DERIVE_STEP_MIN=${DIAG_STEP_MIN:-16}
  run_one diag-asis asis bench/mit-diag $((DERIVE_STEP_MIN*2+20)) "${DIAG_CMD:-./gradlew :app:testStableDebugUnitTest --info}"
  echo; echo "# Matrix finished $(date -u +%FT%TZ)" >> "$SUM"
  "$HOME/.local/bin/hermes-ping" "djbclark-ade: forgejo CI diag run finished, see $SUM"; exit 0
fi
run_one iso-asis asis bench/mit-iso "$ISO_MIN" "$ISO_CMD"
if [ "$LAST_HUNG" = 1 ]; then
  echo; echo "RESULT: CornerButtonThemeTest alone hangs the runner VM on as-is storage; trying tmpfs." >> "$SUM"
  run_one iso-tmpfs tmpfs bench/mit-iso-tmpfs "$ISO_MIN" "$ISO_CMD"
else
  for v in asis tmpfs loop; do run_one "full-$v" "$v" "bench/mit-full-$v" "$FULL_MIN"; done
fi
echo; echo "# Matrix finished $(date -u +%FT%TZ)" >> "$SUM"
"$HOME/.local/bin/hermes-ping" "djbclark-ade: forgejo CI matrix finished, see $SUM"
