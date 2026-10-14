#!/usr/bin/env bash
# push-bench.sh VARIANT BRANCH — derive the forgejo.mit.edu workflow for a storage variant
# (asis|tmpfs|loop) from the repo's GitHub ci.yml at BASE_REF and push it as a commit on top of
# bench/mit-ci's tip to BRANCH, without touching the working tree (temp index + commit-tree).
# Prints the new commit sha. Needs git-forgejo (sudo-secretspec) for the push.
set -euo pipefail
V=${1:?asis|tmpfs|loop}; BR=${2:?branch}; REPO=${PLEKTRA_REPO:-$HOME/src/plektra-djbclark}; BASE_REF=${BASE_REF:-afa1734}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd); GF="$HERE/../../scripts/git-forgejo"
PARENT=$(git -C "$REPO" ls-remote forgejo refs/heads/bench/mit-ci 2>/dev/null | cut -f1 || true)
[ -n "$PARENT" ] || PARENT=$("$GF" -C "$REPO" ls-remote forgejo refs/heads/bench/mit-ci | cut -f1)
git -C "$REPO" cat-file -e "$PARENT" 2>/dev/null || "$GF" -C "$REPO" fetch -q forgejo bench/mit-ci
Y=$(mktemp); DERIVE_STORAGE=$V python3 -I "$HERE/derive-forgejo-ci.py" "$REPO" "$BASE_REF" > "$Y"
export GIT_INDEX_FILE; GIT_INDEX_FILE=$(mktemp -u)
git -C "$REPO" read-tree "$PARENT"
git -C "$REPO" update-index --add --cacheinfo "100644,$(git -C "$REPO" hash-object -w "$Y"),.forgejo/workflows/ci.yml"
SHA=$(git -C "$REPO" commit-tree "$(git -C "$REPO" write-tree)" -p "$PARENT" -m "bench: storage variant $V")
rm -f "$GIT_INDEX_FILE" "$Y"; unset GIT_INDEX_FILE
"$GF" -C "$REPO" push forgejo "+$SHA:refs/heads/$BR" 2>&1 | tail -1
echo "$SHA"
