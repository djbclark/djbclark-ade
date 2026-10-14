#!/usr/bin/env bash
# wait-run.sh SHA OUT: wait for the Forgejo run of SHA to finish, save its job log to OUT
set -u; RP=${RP:-djbclark/plektra-djbclark}; API=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../scripts" && pwd)/forgejo-api; SHA=$1; OUT=$2; t0=$(date +%s)
while :; do
  id=$($API GET "/repos/$RP/actions/runs?limit=10" | jq -r --arg s "$SHA" '[.workflow_runs[]|select(.commit_sha==$s)][0].id // empty')
  if [ -n "$id" ]; then st=$($API GET "/repos/$RP/actions/runs/$id" | jq -r .status); case "$st" in success|failure|cancelled|skipped) break;; esac; fi
  [ $(( $(date +%s) - t0 )) -gt ${WAIT_MAX:-900} ] && { echo "timeout id=${id:-none}" > "$OUT.status"; exit 1; }
  sleep 10
done
j=$($API GET "/repos/$RP/actions/runs/$id/jobs" | jq -r '.[0].id')
$API GET "/repos/$RP/actions/jobs/$j/logs" > "$OUT" 2>&1; echo "run=$id status=$st" > "$OUT.status"
