#!/usr/bin/env bash
# check-disabled.sh TOOL | --self-test   (DRAFT, plan T3, adversary V6)
# CONTRACT: "still disabled" is a query with three checks, not an assertion in prose.
# EXPECT:   exit 0 when all three hold: (1) skill TOOL is not linked in any skill-everywhere target;
#           (2) launchctl print gui/$UID/LABEL fails; (3) the bin entry exits non-zero and mentions "retired".
#           exit 1 when any check shows it live; exit 77 when a check cannot run (counts as "not disabled").
# ON-FAIL:  the D4 drain record cannot claim TOOL disabled; D5/D6 must not proceed on it.
# SCOPE:    read-only. `--self-test` uses only a temp stub.
# HOW:      check-disabled.sh TOOL [--label L] [--bin PATH] [--skill-dir DIR]...
# STATUS:   DRAFT, never run against the live machine
set -u
if [ "${1:-}" = "--self-test" ]; then
  T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; me="$0"
  printf '#!/bin/sh\necho "tool retired" >&2\nexit 3\n' > "$T/retired"; chmod +x "$T/retired"
  printf '#!/bin/sh\necho live\n' > "$T/live"; chmod +x "$T/live"
  mkdir "$T/skills"
  "$me" stub --label com.djbclark.no-such-label --bin "$T/retired" --skill-dir "$T/skills" >/dev/null 2>&1; a=$?
  "$me" stub --label com.djbclark.no-such-label --bin "$T/live" --skill-dir "$T/skills" >/dev/null 2>&1; b=$?
  mkdir "$T/skills/stub"
  "$me" stub --label com.djbclark.no-such-label --bin "$T/retired" --skill-dir "$T/skills" >/dev/null 2>&1; c=$?
  rmdir "$T/skills/stub"
  "$me" stub --label com.djbclark.no-such-label --bin "$T/missing" --skill-dir "$T/skills" >/dev/null 2>&1; d=$?
  echo "{\"retired\":$a,\"liveBin\":$b,\"linkedSkill\":$c,\"missingBin\":$d}"
  [ "$a" = 0 ] && [ "$b" = 1 ] && [ "$c" = 1 ] && [ "$d" = 77 ]; exit $?
fi
tool="${1:?usage: check-disabled.sh TOOL [--label L] [--bin PATH] [--skill-dir DIR]...}"; shift
label=""; bin=""; dirs=()
while [ $# -gt 0 ]; do case "$1" in --label) label=$2; shift 2;; --bin) bin=$2; shift 2;; --skill-dir) dirs+=("$2"); shift 2;; *) echo "bad arg $1" >&2; exit 2;; esac; done
[ "${#dirs[@]}" = 0 ] && dirs=("$HOME/.claude/skills" "$HOME/.codex/skills" "$HOME/.agents/skills")  # UNVERIFIED: the skill-everywhere target list
live=(); cannot=()
for d in "${dirs[@]}"; do [ -e "$d/$tool" ] && live+=("skill linked in $d"); done
if [ -n "$label" ]; then
  if ! command -v launchctl >/dev/null; then cannot+=("no launchctl")
  elif launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1; then live+=("launchd job $label loaded"); fi
else cannot+=("no --label"); fi
if [ -n "$bin" ] && [ -x "$bin" ]; then
  out=$("$bin" 2>&1 </dev/null); rc=$?
  if [ "$rc" = 0 ] || ! printf '%s' "$out" | ggrep -qi retired; then live+=("bin $bin runs (rc=$rc) or does not say retired"); fi
else cannot+=("bin $bin not executable or missing"); fi
printf '{"tool":"%s","live":%s,"cannotCheck":%s}\n' "$tool" "$(printf '%s\n' "${live[@]:-}" | python3 -c 'import json,sys;print(json.dumps([l for l in sys.stdin.read().splitlines() if l]))')" "$(printf '%s\n' "${cannot[@]:-}" | python3 -c 'import json,sys;print(json.dumps([l for l in sys.stdin.read().splitlines() if l]))')"
[ "${#live[@]}" -gt 0 ] && exit 1
[ "${#cannot[@]}" -gt 0 ] && exit 77
exit 0
