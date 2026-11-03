#!/usr/bin/env bash
# check-disabled.sh TOOL [--label L] [--bin PATH] [--skill-dir DIR]...   |   --self-test      (plan T3; adversary V6)
# CONTRACT: "still disabled" is a query with three checks, not an assertion in prose:
#           (1) the skill TOOL is not linked in any skill-everywhere target dir;
#           (2) `launchctl print gui/$UID/LABEL` fails (the launchd job is not loaded);
#           (3) the bin entry exits non-zero AND its output says "retired".
# EXPECT:   exit 0 when all three hold; exit 1 when any shows the tool live; exit 77 when a check cannot run
#           (no --label, no --bin, bin missing or not executable, no launchctl) and nothing shows it live: counts as "not disabled".
# ON-FAIL:  the D4 drain record cannot claim TOOL disabled; D5/D6 must not proceed on it.
# SCOPE:    read-only. The bin entry IS executed (no arguments, stdin /dev/null, 15 s limit, the bin is the tool being
#           retired and must answer "retired"); it is skipped when check (1) or (2) already shows the tool live.
#           `--self-test` uses only a temp stub and a label that does not exist.
# HOW:      check-disabled.sh herdr-tidy --label dev.herdr.server --bin ~/src/djbclark-ade/bin/herdr-tidy
#           --skill-dir DIR replaces the default skill-everywhere target list (bin/skill-everywhere lines 57-71): repeatable.
# OUTPUT:   {"tool","live":[...],"cannotCheck":[...],"checked":[...]}; exit 0 / 1 / 77
# STATUS:   self-test and a live run on 2026-11-02 (see the T3 report)
set -u
here=$(cd "$(dirname "$0")" && pwd)
export PYTHONDONTWRITEBYTECODE=1
if [ "${1:-}" = "--self-test" ]; then
  T=$(mktemp -d) || exit 2; trap 'rm -rf "$T"' EXIT
  printf '#!/bin/sh\necho "tool retired" >&2\nexit 3\n' > "$T/retired"
  printf '#!/bin/sh\necho live\n' > "$T/live"
  printf '#!/bin/sh\nexit 3\n' > "$T/silent"
  chmod +x "$T/retired" "$T/live" "$T/silent"
  mkdir "$T/skills"
  L=com.djbclark.no-such-label.$$
  me="$here/$(basename "$0")"
  run() { bash "$me" stub --label "$L" --skill-dir "$T/skills" "$@" >/dev/null 2>&1; echo $?; }
  a=$(run --bin "$T/retired")                       # all three hold: 0
  b=$(run --bin "$T/live")                          # bin still runs: 1
  s=$(run --bin "$T/silent")                        # non-zero but no "retired": 1
  d=$(run --bin "$T/missing")                       # bin check cannot run: 77
  mkdir "$T/skills/stub"; c=$(run --bin "$T/retired"); rmdir "$T/skills/stub"   # skill still linked: 1
  ln -s /nonexistent "$T/skills/stub"; e=$(run --bin "$T/retired"); rm "$T/skills/stub"   # dangling link counts as linked: 1
  n=$(bash "$me" stub --skill-dir "$T/skills" >/dev/null 2>&1; echo $?)   # no label, no bin: 77
  echo "{\"retired\":$a,\"liveBin\":$b,\"silentBin\":$s,\"missingBin\":$d,\"linkedSkill\":$c,\"danglingSkill\":$e,\"noLabelNoBin\":$n}"
  [ "$a" = 0 ] && [ "$b" = 1 ] && [ "$s" = 1 ] && [ "$d" = 77 ] && [ "$c" = 1 ] && [ "$e" = 1 ] && [ "$n" = 77 ]; exit $?
fi
[ "$#" -ge 1 ] && [ "${1#-}" = "$1" ] || { echo "usage: check-disabled.sh TOOL [--label L] [--bin PATH] [--skill-dir DIR]... | --self-test" >&2; exit 2; }
python3 - "$here" "$@" <<'PY'
import json, os, shutil, sys
sys.path.insert(0, sys.argv[1])
import drain_common as dc
tool, args = sys.argv[2], sys.argv[3:]
label, binp, dirs = "", "", []
i = 0
while i < len(args):
    if args[i] in ("--label", "--bin", "--skill-dir") and i + 1 < len(args):
        v = args[i + 1]
        if args[i] == "--label": label = v
        elif args[i] == "--bin": binp = os.path.expanduser(v)
        else: dirs.append(os.path.expanduser(v))
        i += 2
    else:
        print(f"check-disabled.sh: bad argument {args[i]!r}", file=sys.stderr)
        sys.exit(2)
if "/" in tool or tool in ("", ".", ".."):
    print("check-disabled.sh: TOOL is a skill name, not a path", file=sys.stderr)
    sys.exit(2)
if not dirs:   # bin/skill-everywhere lines 57-71, the targets that have a directory of their own
    dirs = [os.path.expanduser(d) for d in (
        "~/.claude/skills", "~/.agents/skills", "~/.gemini/antigravity-cli/skills", "~/.copilot/skills",
        "~/.config/opencode/skills", "~/.qwen/skills", "~/.config/devin/skills", "~/.cline/skills",
        "~/.local/share/skill-everywhere/skills", "~/.grok/skills", "~/.omp/agent/skills")]
live, cannot, checked = [], [], []
# (1) skill linked anywhere? A dangling symlink still counts (lexists).
for d in dirs:
    if os.path.lexists(os.path.join(d, tool)):
        live.append(f"skill linked in {d}")
checked.append(f"skill-dirs:{len(dirs)}")
# (2) launchd job loaded?
if not label:
    cannot.append("no --label: the launchd check cannot run")
elif shutil.which("launchctl") is None:
    cannot.append("no launchctl on this host")
else:
    rc, _o, err = dc.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"], 15)
    checked.append(f"launchd:{label}")
    if rc is None:
        cannot.append(f"launchctl print failed to run: {err[:80]}")
    elif rc == 0:
        live.append(f"launchd job {label} loaded")
# (3) bin exits non-zero and says retired; run it only when nothing already shows the tool live
if not binp:
    cannot.append("no --bin: the bin check cannot run")
elif not (os.path.isfile(binp) and os.access(binp, os.X_OK)):
    cannot.append(f"bin {binp} missing or not executable")
elif live:
    checked.append("bin:skipped (already live)")
else:
    rc, out, err = dc.run([binp], 15)
    checked.append(f"bin:{binp}")
    if rc is None:
        cannot.append(f"bin {binp} did not finish: {err[:80]}")
    elif rc == 0 or "retired" not in (out + err).lower():
        live.append(f"bin {binp} runs (rc={rc}) or does not say retired")
print(json.dumps({"tool": tool, "live": live, "cannotCheck": cannot, "checked": checked}, ensure_ascii=False))
sys.exit(1 if live else 77 if cannot else 0)
PY
exit $?
