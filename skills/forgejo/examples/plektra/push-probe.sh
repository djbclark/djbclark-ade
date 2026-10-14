#!/usr/bin/env bash
# push-probe.sh WORKFLOW.yml BRANCH [EXTRA_FILE...] — push a probe workflow as the only workflow on a throwaway branch
# (on top of bench/mit-ci's tip, working tree untouched); EXTRA_FILEs are added at the repo root. Force-pushes BRANCH. Prints the sha.
set -euo pipefail
YML=${1:?workflow file}; BR=${2:?branch}; shift 2; REPO=${PLEKTRA_REPO:-$HOME/src/plektra-djbclark}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd); GF="$HERE/../../scripts/git-forgejo"
PARENT=$(git -C "$REPO" ls-remote forgejo refs/heads/bench/mit-ci 2>/dev/null | cut -f1 || true)
[ -n "$PARENT" ] || PARENT=$("$GF" -C "$REPO" ls-remote forgejo refs/heads/bench/mit-ci | cut -f1)
git -C "$REPO" cat-file -e "$PARENT" 2>/dev/null || "$GF" -C "$REPO" fetch -q forgejo bench/mit-ci
export GIT_INDEX_FILE; GIT_INDEX_FILE=$(mktemp -u)
git -C "$REPO" read-tree "$PARENT"
git -C "$REPO" rm -q --cached -r --ignore-unmatch .forgejo/workflows >/dev/null
git -C "$REPO" update-index --add --cacheinfo "100644,$(git -C "$REPO" hash-object -w "$(realpath "$YML")"),.forgejo/workflows/probe.yml"
for f in "$@"; do git -C "$REPO" update-index --add --cacheinfo "100644,$(git -C "$REPO" hash-object -w "$(realpath "$f")"),$(basename "$f")"; done
SHA=$(git -C "$REPO" commit-tree "$(git -C "$REPO" write-tree)" -p "$PARENT" -m "probe: $(basename "$YML")")
rm -f "$GIT_INDEX_FILE"; unset GIT_INDEX_FILE
"$GF" -C "$REPO" push forgejo "+$SHA:refs/heads/$BR" 2>&1 | tail -1
echo "$SHA"
