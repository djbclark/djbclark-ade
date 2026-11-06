#!/usr/bin/env bash
# d1-03-archive-rescue
# CONTRACT: D1.3/B4.1-4.2: archiving the last agent of a dirty, unpushed worktree workspace leaves a local rescue (bundle, stash commit, untracked tar) BEFORE the worktree is removed; the pushed rescue branch holds tracked changes only
# EXPECT:   rescue dir 0700 with branch.bundle (standalone `git bundle verify` ok, carries the branch and refs/rescue/<branch>), untracked.tar (untracked yes, ignored no); verified by the teardown while the worktree still existed; private remote has rescue/<branch>-<date> with no untracked file; Paseo then removes the worktree. Archiving the last agent is tried first (20 s); if it leaves the workspace active (0.15.0-beta.1 does) `paseo workspace archive` follows, and the record says which removed it
# ON-FAIL:  no slice moves into Paseo workspaces (plan D1.3)
# SCOPE:    DESTRUCTIVE: second daemon only
#           NEVER run this against the live daemon (plan B10). It refuses unless PASEO_HOME is a fresh test home.
# HOW:      bash tests/paseo-acceptance/d1-03-archive-rescue.sh   (refusing remote + failing teardown: d1-03b-teardown-failure.sh, which runs this with D1_03_REFUSE=1)
# NEEDS:    isolated daemon; one short paid turn (PROBE_PROVIDER, default codex, PROBE_MODEL default gpt-5.6-luna); git; a throwaway repo, origin and private bare remotes it creates under ACC_BASE
# STATUS:   run 2026-11-02 (see docs/d1-implementation-plan.md T6); the fixture is created here, never a real repo
set -u
here=$(cd "$(dirname "$0")" && pwd)
REFUSE=${D1_03_REFUSE:-0}
ACC_PROBE=${ACC_PROBE:-d1-03-archive-rescue}
. "$here/lib/common.sh"
ON_FAIL=${ON_FAIL:-no\ slice\ moves\ into\ Paseo\ workspaces\ \(plan\ D1.3\)}
RESCUE=${ADE_RESCUE_BIN:-$(cd "$here/../.." && pwd)/bin/ade-rescue-worktree}
PROVIDER=${PROBE_PROVIDER:-codex}; MODEL=${PROBE_MODEL:-gpt-5.6-luna}; THINKING=${PROBE_THINKING:-low}
[ -x "$RESCUE" ] || skip "bin/ade-rescue-worktree not found at $RESCUE"
case "$PROVIDER" in claude*|opencode*|cline*) skip "provider $PROVIDER: pool protected (djbclark 2026-11-02)";; esac
now() { python3 -c 'import time; print("%.3f" % time.time())'; }
G=(git -c user.name=acc -c user.email=acc@invalid -c commit.gpgsign=false -c core.hooksPath=/dev/null)

isolated_up "rescue$REFUSE"; trap isolated_down EXIT
fx="$ACC_BASE/fx"; repo="$fx/repo"; origin="$fx/origin.git"; private="$fx/private.git"
mkdir -m 700 "$fx"
git init -q --bare "$origin" && git init -q --bare "$private" && git init -q -b main "$repo" || die "fixture init failed"
if [ "$REFUSE" = 1 ]; then
  printf '#!/bin/sh\necho "d1-03b: this remote refuses every push" >&2\nexit 1\n' > "$private/hooks/pre-receive"
  chmod 755 "$private/hooks/pre-receive"
fi
# The teardown body: run the rescue, then (still inside teardown, so before Paseo deletes anything) verify the bundle
# while the worktree exists. Mode "fail" exits 3 afterwards, to record whether a failing teardown stops the removal.
cat > "$fx/teardown.sh" <<'TEARDOWN'
#!/usr/bin/env bash
set -u
fx="$1"; mode="$2"; rescue="$3"
python3 -c 'import time; print("%.3f" % time.time())' > "$fx/teardown.start"
printf '%s\n%s\n' "${PASEO_BRANCH_NAME:-}" "${PASEO_WORKTREE_PATH:-}" > "$fx/teardown.env"
ADE_RESCUE_ROOT="$fx/rescue" "$rescue" --repo fx --branch "${PASEO_BRANCH_NAME:-}" --worktree "${PASEO_WORKTREE_PATH:-}" \
  --remote private --json > "$fx/rescue.json" 2> "$fx/rescue.err"
rc=$?
echo "$rc" > "$fx/rescue.rc"
dir=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("rescueDir") or "")' "$fx/rescue.json" 2>/dev/null)
if [ -n "$dir" ] && [ -d "${PASEO_WORKTREE_PATH:-/nonexistent}" ] \
   && git -C "$PASEO_WORKTREE_PATH" bundle verify "$dir/branch.bundle" > "$fx/teardown-verify.out" 2>&1; then
  echo yes > "$fx/verified-before-removal"
else
  echo no > "$fx/verified-before-removal"
fi
python3 -c 'import time; print("%.3f" % time.time())' > "$fx/teardown.end"
[ "$mode" = fail ] && exit 3
exit "$rc"
TEARDOWN
chmod 700 "$fx/teardown.sh"
mode=ok; [ "$REFUSE" = 1 ] && mode=fail
python3 - "$repo/paseo.json" "$fx" "$mode" "$RESCUE" <<'PY' || die "cannot write paseo.json"
import json, shlex, sys
path, fx, mode, rescue = sys.argv[1:]
cmd = shlex.join(["bash", fx + "/teardown.sh", fx, mode, rescue])
json.dump({"worktree": {"teardown": [cmd]}}, open(path, "w"), indent=2)
PY
printf 'a0\n' > "$repo/a.txt"; printf '*.log\n' > "$repo/.gitignore"
"${G[@]}" -C "$repo" add -A && "${G[@]}" -C "$repo" commit -qm base && "${G[@]}" -C "$repo" remote add origin "$origin" \
  && "${G[@]}" -C "$repo" remote add private "$private" && "${G[@]}" -C "$repo" push -q origin main || die "fixture commit/push failed"

id=$(pj run -q --no-wait --provider "$PROVIDER" --model "$MODEL" --thinking "$THINKING" --title "d1-03 rescue probe" --cwd "$repo" \
  --new-workspace worktree --worktree-slug "rescue-probe$REFUSE" "Reply with exactly the word ok. Do not run any tool." 2> "$fx/run.err")
[ -n "$id" ] || fail "paseo run failed: $(head -c 300 "$fx/run.err")" '{"stage":"run"}'
echo "$id" > "$fx/agent.id"
pj wait --timeout 300 "$id" > "$fx/wait.out" 2>&1
pj inspect --json "$id" > "$fx/inspect.json" 2> "$fx/inspect.err"
wt=$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print(d.get("Cwd") or d.get("cwd") or "")' "$fx/inspect.json" 2>/dev/null)
[ -n "$wt" ] && [ -d "$wt" ] && [ "$wt" != "$repo" ] || fail "agent has no worktree cwd" "{\"stage\":\"inspect\",\"cwd\":\"$wt\"}"
echo "$wt" > "$fx/worktree.path"
branch=$(git -C "$wt" symbolic-ref --short HEAD 2>/dev/null) || fail "worktree is not on a branch" '{"stage":"branch"}'

# The unpushed work: one commit, one staged and one unstaged tracked change, one untracked file, one ignored file.
printf 'committed\n' > "$wt/b.txt"; "${G[@]}" -C "$wt" add b.txt && "${G[@]}" -C "$wt" commit -qm unpushed || die "commit in worktree failed"
printf 'staged\n' > "$wt/s.txt"; "${G[@]}" -C "$wt" add s.txt
printf 'unstaged\n' > "$wt/a.txt"
printf 'untracked\n' > "$wt/u.txt"; printf 'ignored\n' > "$wt/x.log"

# poll_gone LIMIT_S: wait for the worktree to disappear; prints the epoch it was seen gone, or nothing.
poll_gone() {
  local _
  for _ in $(seq 1 $(($1 * 5))); do
    [ -d "$wt" ] || { now; return 0; }
    sleep 0.2
  done
}
# Stage 1, the plan's step: archive the workspace's last (only) agent.
t_archive=$(now)
pj archive "$id" > "$fx/archive.out" 2>&1; archive_rc=$?
t_removed=$(poll_gone 20)
agent_archive_removed=false; [ -n "$t_removed" ] && agent_archive_removed=true
teardown_on_agent_archive=false; [ -e "$fx/teardown.start" ] && teardown_on_agent_archive=true
# Stage 2 (checked 2026-11-02, 0.15.0-beta.1): archiving the last agent leaves the workspace active, so no teardown
# and no removal. The removal path is a workspace-scope archive (`paseo workspace archive`, archive-on-merge, MCP).
ws_rc=""
if [ -z "$t_removed" ]; then
  wks=$(pj workspace ls --json 2> "$fx/workspace-ls.err" | python3 -c '
import json, os, sys
wt = os.path.realpath(sys.argv[1])
for w in json.load(sys.stdin):
    c = w.get("cwd") or w.get("Cwd") or w.get("path") or ""
    if c and os.path.realpath(c) == wt:
        print(w.get("workspaceId") or w.get("id") or w.get("Id") or ""); break' "$wt" 2>/dev/null)
  [ -n "$wks" ] || wks=$(grep -o 'wks_[A-Za-z0-9]*' "$fx/run.err" | head -1)
  echo "$wks" > "$fx/workspace.id"
  t_archive=$(now)
  pj workspace archive "$wks" > "$fx/workspace-archive.out" 2>&1; ws_rc=$?
  limit=90; [ "$REFUSE" = 1 ] && limit=45
  t_removed=$(poll_gone "$limit")
fi
sleep 1
pj ls --json > "$fx/ls-after.json" 2>/dev/null
git -C "$repo" worktree list --porcelain > "$fx/worktree-list-after.txt" 2>&1

python3 - "$fx" "$wt" "$branch" "$REFUSE" "$t_archive" "${t_removed:-}" "$archive_rc" "$ACC_BASE" \
  "$agent_archive_removed" "$teardown_on_agent_archive" "$ws_rc" > "$fx/evidence.json" <<'PY'
import json, os, stat, subprocess, sys, tarfile, tempfile
fx, wt, branch, refuse, t_archive, t_removed, archive_rc, base, agent_removed, agent_teardown, ws_rc = sys.argv[1:]
refuse = refuse == "1"
def rd(name, default=""):
    try:
        return open(os.path.join(fx, name)).read().strip()
    except OSError:
        return default
def git(*a, cwd=None):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)
ev = {"mode": "refuse-push+failing-teardown" if refuse else "normal", "worktree": wt, "branch": branch,
      "archiveRc": int(archive_rc), "worktreeRemoved": t_removed != "", "tArchive": float(t_archive),
      "tRemoved": float(t_removed) if t_removed else None, "teardownRan": os.path.exists(os.path.join(fx, "teardown.start")),
      "teardownEnv": rd("teardown.env").splitlines(), "rescueRc": rd("rescue.rc") or None,
      "verifiedBeforeRemoval": rd("verified-before-removal") == "yes", "evidenceDir": fx,
      "agentArchiveRemovedWorktree": agent_removed == "true", "teardownOnAgentArchive": agent_teardown == "true",
      "workspaceArchiveRc": int(ws_rc) if ws_rc else None, "workspaceId": rd("workspace.id") or None}
ev["removedBy"] = ("agent archive" if ev["agentArchiveRemovedWorktree"] else
                  "workspace archive" if ev["worktreeRemoved"] else None)
try:
    res = json.load(open(os.path.join(fx, "rescue.json")))
except (OSError, ValueError):
    res = {}
ev["pushed"] = res.get("pushed"); ev["pushError"] = (res.get("pushError") or "")[-200:] or None
d = res.get("rescueDir") or ""
ev["rescueDir"] = d
if ev["teardownRan"]:
    ev["teardownStart"] = float(rd("teardown.start")); ev["teardownEnd"] = float(rd("teardown.end") or 0) or None
    if ev["tRemoved"] and ev.get("teardownEnd"):
        ev["rescueBeforeRemoval"] = ev["teardownEnd"] <= ev["tRemoved"]
if d and os.path.isdir(d):
    ev["dirMode"] = oct(stat.S_IMODE(os.stat(d).st_mode))[2:]
    empty = tempfile.mkdtemp(dir=fx, prefix="verify-")
    git("init", "-q", empty)
    b = os.path.join(d, "branch.bundle")
    ev["bundleVerifyStandalone"] = git("bundle", "verify", b, cwd=empty).returncode == 0
    heads = git("bundle", "list-heads", b, cwd=empty).stdout.split()
    ev["bundleRefs"] = [h for h in heads if h.startswith("refs/")]
    git("fetch", "-q", b, "refs/*:refs/*", cwd=empty)
    ev["restoredCommittedFile"] = git("show", f"refs/heads/{branch}:b.txt", cwd=empty).stdout == "committed\n"
    ev["restoredUnstaged"] = git("show", f"refs/rescue/{branch}:a.txt", cwd=empty).stdout == "unstaged\n"
    ev["restoredStaged"] = git("show", f"refs/rescue/{branch}^2:s.txt", cwd=empty).stdout == "staged\n"
    try:
        names = tarfile.open(os.path.join(d, "untracked.tar")).getnames()
    except (OSError, tarfile.TarError):
        names = None
    ev["untrackedTar"] = names
    ev["artifactMtimes"] = {n: os.stat(os.path.join(d, n)).st_mtime for n in ("branch.bundle", "untracked.tar")}
remote = os.path.join(fx, "private.git")
refs = git("--git-dir", remote, "for-each-ref", "--format=%(refname)", "refs/heads/rescue/").stdout.split()
ev["remoteRescueRefs"] = refs
if refs:
    files = git("--git-dir", remote, "ls-tree", "-r", "--name-only", refs[0]).stdout.split()
    ev["remoteHasUntracked"] = "u.txt" in files or "x.log" in files
    ev["remoteHasTracked"] = "b.txt" in files and "s.txt" in files
ev["branchStillInRepo"] = git("-C", os.path.join(fx, "repo"), "rev-parse", "--verify", "-q", f"refs/heads/{branch}").returncode == 0
ev["rescueRefStillInRepo"] = git("-C", os.path.join(fx, "repo"), "rev-parse", "--verify", "-q", f"refs/rescue/{branch}").returncode == 0
# session-janitor's mode: the isolated daemon runs no plugins (B10); the live mode is read from files only (no paseo call).
live = os.path.expanduser("~/.paseo")
try:
    cfg = json.load(open(os.path.join(live, "config.json")))
    live_enabled = (cfg.get("plugins") or {}).get("session-janitor")
    if isinstance(live_enabled, dict):
        live_enabled = live_enabled.get("enabled")
except (OSError, ValueError):
    live_enabled = None
try:
    prefs = json.load(open(os.path.join(live, "plugin-settings", "session-janitor", "preferences.json"))).get("values", {})
except (OSError, ValueError):
    prefs = {}
ev["sessionJanitor"] = {"isolated": "not running (pluginsEnabled false)", "livePluginEnabled": live_enabled,
                        "livePrefs": {k: prefs.get(k) for k in ("enabled", "archiveChildren", "deleteChildren", "deleteMain",
                                                                 "archiveAfterHours", "waitForParentArchive")}}
log = os.path.join(base, "daemon.out")
try:
    lines = [l for l in open(log, errors="replace") if "eardown" in l]
    ev["daemonTeardownLogLines"] = [l.strip()[:300] for l in lines[-5:]]
except OSError:
    ev["daemonTeardownLogLines"] = None
print(json.dumps(ev, sort_keys=True))
PY
ev=$(cat "$fx/evidence.json")
[ -n "$ev" ] || fail "evidence collection failed" '{"stage":"evidence"}'
python3 - "$fx/evidence.json" "$REFUSE" <<'PY'
import json, sys
e = json.load(open(sys.argv[1])); refuse = sys.argv[2] == "1"
local = (e.get("rescueRc") == "0" and e.get("dirMode") == "700" and e.get("bundleVerifyStandalone")
         and e.get("restoredCommittedFile") and e.get("restoredUnstaged") and e.get("restoredStaged")
         and e.get("untrackedTar") == ["u.txt"] and e.get("verifiedBeforeRemoval"))
if refuse:
    ok = local and e.get("pushed") is False and not e.get("remoteRescueRefs")
else:
    ok = (local and e.get("pushed") is True and e.get("remoteHasTracked") and e.get("remoteHasUntracked") is False
          and e.get("worktreeRemoved") and e.get("rescueBeforeRemoval"))
sys.exit(0 if ok else 1)
PY
case $? in
  0) pass "$ev" ;;
  *) fail "rescue contract not met (see evidence)" "$ev" ;;
esac
