#!/usr/bin/env bash
# Exit 0 if the full pytest suite should run; exit 1 if every changed path is
# docs/changelog-only (pytest-linux may short-circuit). Used by Tests CI.
#
# Snapshot 2026-11-09: pytest-linux spends ~10–11 min in the suite itself
# (~6100 tests); setup is ~5 s. Skipping the suite for docs/changelog-only
# PRs keeps the pytest-linux check name green without a ruleset change.
set -eu

usage() {
  echo "usage: pytest-suite-needed.sh --base <sha|ref> --head <sha|ref>" >&2
  exit 2
}

base=""
head=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --base)
      [ "$#" -ge 2 ] || usage
      base=$2
      shift 2
      ;;
    --head)
      [ "$#" -ge 2 ] || usage
      head=$2
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    *)
      usage
      ;;
  esac
done

[ -n "$base" ] && [ -n "$head" ] || usage

# Paths that do not require the full suite. Keep in sync with docs/ci-notes.md.
# Intentionally narrow: workflow, bin/, tests/, config/, skills/, etc. still force
# a full run. Root instruction markdown and LICENSE are covered by context-policy /
# instruction-lint, not the 6k-test suite. context-policy still runs on every PR.
skippable_path() {
  case "$1" in
    CHANGELOG.md|changelog.d/*|docs/*) return 0 ;;
    # Root prose / license only (2026-11-10): AGENTS/CLAUDE/GEMINI/README/LICENSE.
    AGENTS.md|CLAUDE.md|GEMINI.md|README.md|LICENSE) return 0 ;;
    *) return 1 ;;
  esac
}

# Name-only, no renames: both sides of a rename must be examined as separate paths.
mapfile -d '' -t paths < <(git diff --name-only -z --no-renames "$base" "$head")

if [ "${#paths[@]}" -eq 0 ]; then
  echo "suite=needed reason=no-changes"
  exit 0
fi

for path in "${paths[@]}"; do
  [ -n "$path" ] || continue
  if ! skippable_path "$path"; then
    echo "suite=needed reason=non-docs-path path=$path"
    exit 0
  fi
done

echo "suite=skip reason=docs-changelog-only count=${#paths[@]}"
exit 1
