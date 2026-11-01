#!/usr/bin/env bash
# run-all.sh [--list] [--readonly] (DRAFT)
# --list prints every probe with its SCOPE line. --readonly runs only readonly/ro-*.sh (against the live daemon, read-only).
# It NEVER runs a probe whose SCOPE starts with DESTRUCTIVE or "second daemon only"; run those by hand with a fresh PASEO_HOME.
here=$(cd "$(dirname "$0")" && pwd)
for f in "$here"/readonly/ro-*.sh "$here"/d1-*.sh "$here"/watchdog-selftest.sh "$here"/drain/*.sh; do
  [ -f "$f" ] || continue
  scope=$(ggrep -m1 '^# SCOPE:' "$f" | cut -c12-)
  case "${1:-}" in
    --list) printf '%-34s %s\n' "${f#$here/}" "$scope";;
    --readonly) case "$f" in "$here"/readonly/*) bash "$f"; echo "rc=$? $(basename "$f")";; esac;;
    *) echo "usage: run-all.sh --list | --readonly" >&2; exit 2;;
  esac
done
