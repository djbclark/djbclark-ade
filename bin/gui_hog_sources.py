"""gui_hog_sources: what actually causes the load (docs/gui-hog-dialog.md section Q2, operator ruling 2026-11-21).

The dialog used to show desktop apps only, so "A build is waiting" never named the builds, test jobs and agents that really use the cores. This module
READS the process table the sampler already has and groups every process into one SOURCE:

    app      a GUI app (gui_hog.group_apps), with its protected / part-of-a-build / hosts-a-build flags
    build    the process tree under a build or test tool (bgrun, cargo, gradle, pytest, ...), a held `admit` caller, or a terminal/build subtree
             that sits inside an app (a shell in Ghostty); a build under a build joins the outer one (cargo -> rustc)
    agent    an agent CLI (claude, codex, paseo, ...) and everything under it that is not a build of its own
    system   every other process, grouped by program name (kernel_task, mds, ...)

Each source carries cores, RSS, process count, its heaviest process and, for a build, the owning agent (the nearest agent-CLI ancestor). Only an
unprotected app that hosts nothing can be frozen, and the dialog offers Freeze for those rows only; every other source is SHOWN, never acted on:
nothing here signals, stops or quits anything, and no command line leaves this module (only program names, cleaned: J3).

Stdlib only; imported by gui_hog.tick lazily inside a try, so a fault here never stops a sample or the dialog.
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gui_hog as gh  # noqa: E402

# Programs whose process tree is "a build or test job". Matched on the program word and the first non-option word after it (`python3 -m pytest`,
# `node /x/vitest`), as base names, never on a command line as a whole. Generic runtimes (node, python, java) are deliberately NOT here.
BUILD_HEADS = frozenset({
    "bg", "bgrun", "cargo", "rustc", "rustup", "gradle", "gradlew", "pytest", "py.test", "vitest", "jest", "mocha", "playwright",
    "make", "gmake", "ninja", "cmake", "xcodebuild", "swift-build", "swift-frontend", "swiftc", "swift-test", "clang", "clang++", "ld", "tsc",
    "webpack", "vite", "esbuild", "next", "mvn", "bazel", "go", "npm", "pnpm", "yarn", "bun", "uv", "nix", "nix-build", "docker", "xctest"})
GRADLE_MARKS = ("org.gradle", "GradleDaemon", "GradleWorkerMain", "gradle-launcher")   # the Gradle daemon is a bare `java` process
MAX_SOURCES = 40   # per sample, after sorting by cores


def _label(cmd):
    """A cleaned program name for an unclaimed process: the executable's base name (a bundle's executable may contain spaces), never its arguments."""
    cmd = str(cmd)
    mark = "/Contents/MacOS/"
    if mark in cmd:
        # A bundle's executable may contain spaces ("Google Chrome Helper (Renderer)"), and the arguments follow it: take the executable name
        # only when it matches the bundle's own name (its length bounds the cut, so no argument can ride along), else the first word after it.
        head, rest = cmd.split(mark, 1)
        bundle = os.path.basename(head.rstrip("/"))
        bundle = bundle[:-4] if bundle.endswith(".app") else bundle
        if bundle and rest[:len(bundle)].casefold() == bundle.casefold() and (len(rest) == len(bundle) or rest[len(bundle)] in " \t"):
            name = rest[:len(bundle)]
        else:
            name = (rest.split() or [""])[0]
        return gh.clean(name or "?", 40)
    first = (cmd.split() or [""])[0]
    return gh.clean(os.path.basename(first.rstrip("/")) or "?", 40)


def _build_head(cmd):
    heads = gh.argv_head_words(cmd)
    for h in sorted(heads & BUILD_HEADS):
        return h
    for m in GRADLE_MARKS:
        if m in cmd:
            return "gradle"
    return None


def group_sources(table, rss_kb, apps, *, held_pids=(), agent_clis=()):
    """[{key, kind, id, name, cores, rss_mb, procs, heaviest, heaviest_cores, owner, waiting, bundle_id, protected, excluded, hosts_build}] for every
    source with cores or memory worth keeping, busiest first (at most MAX_SOURCES). `table` is {pid str: (ppid, uid, cores, command)}, `rss_kb`
    {pid: KB}, `apps` the records of `gui_hog.group_apps` (their `member_pids`, `kept_pids` and `build_pids` say which process is whose),
    `held_pids` the pids of waiting `admit` callers. Reads only: the result is data about processes, never a handle to signal one."""
    held = {str(p) for p in held_pids}
    agents = set(agent_clis) - {"bg"}   # `bg` is a build here, an exclusion marker in group_apps
    app_of, inbuild, app_by_id = {}, set(), {}
    for a in apps:
        app_by_id[str(a["id"])] = a
        for p in list(a.get("member_pids", ())) + list(a.get("kept_pids", ())):
            app_of[str(p)] = str(a["id"])
        inbuild.update(str(p) for p in a.get("build_pids", ()))

    def role(pid):
        if pid in app_of:
            return "app"
        cmd = table[pid][3]
        if gh.argv_head_words(cmd) & agents:
            return "agent"
        if pid in held or _build_head(cmd):
            return "build"
        if pid in inbuild and str(table[pid][0]) not in inbuild:
            return "build"   # the top of a terminal or build subtree inside an app
        return None

    memo = {}

    def resolve(pid):
        chain = []
        cur = pid
        while cur not in memo and len(chain) < 64:
            chain.append(cur)
            par = str(table[cur][0])
            if par in table and par not in ("0", "1") and par != cur:
                cur = par
            else:
                cur = None
                break
        base = memo.get(cur) if cur is not None else None
        for p in reversed(chain):   # top of the chain first: a child inherits what its parent resolved to
            r = role(p)
            if r == "app":
                key = ("app", app_of[p])
            elif r == "agent":
                key = ("agent", p)
            elif r == "build":
                key = base if base and base[0] == "build" else ("build", p)
            else:
                key = base if base else ("system", _label(table[p][3]))
            memo[p] = key
            base = key
        return memo[pid]

    groups = {}
    for pid, (ppid, uid, cores, cmd) in table.items():
        key = resolve(pid)
        g = groups.setdefault(key, {"cores": 0.0, "rss_kb": 0, "procs": 0, "heavy": ("", 0.0), "root": key[1]})
        g["cores"] += cores
        g["rss_kb"] += rss_kb.get(pid, 0)
        g["procs"] += 1
        if cores >= g["heavy"][1]:
            g["heavy"] = (_label(cmd), cores)

    def owner_of(pid):
        cur, hops = str(table[pid][0]), 0
        while cur in table and hops < 64:
            if gh.argv_head_words(table[cur][3]) & agents:
                return gh.clean(sorted(gh.argv_head_words(table[cur][3]) & agents)[0], 40), int(cur)
            cur, hops = str(table[cur][0]), hops + 1
        return None, None

    out = []
    for key, g in groups.items():
        kind, ident = key
        waiting = kind == "build" and ident in held
        rec = {"key": f"{kind}:{ident}", "kind": kind, "id": ident, "cores": g["cores"], "rss_mb": g["rss_kb"] / 1024.0, "procs": g["procs"],
               "heaviest": g["heavy"][0], "heaviest_cores": g["heavy"][1], "owner": None, "owner_pid": None, "waiting": waiting,
               "bundle_id": None, "protected": None, "excluded": None, "hosts_build": False}
        if kind == "app":
            a = app_by_id[ident]
            rec.update(name=gh.clean(a["name"]), bundle_id=gh.clean(a["bundle_id"] or "", 80), protected=a["protected"], excluded=a["excluded"],
                       hosts_build=bool(a["hosts_build"]), id=str(a["id"]))
        elif kind == "build":
            head = _build_head(table[ident][3]) or ("admit" if waiting else None)
            rec["name"] = gh.clean(head or _label(table[ident][3]), 40)
            if ident in inbuild and not head:
                rec["name"] = "terminal session (" + rec["name"] + ")"
            rec["owner"], rec["owner_pid"] = owner_of(ident)
        elif kind == "agent":
            rec["name"] = gh.clean(sorted(gh.argv_head_words(table[ident][3]) & agents)[0], 40)
        else:
            rec["name"] = gh.clean(ident, 40)
        out.append(rec)
    out.sort(key=lambda r: -r["cores"])
    return out[:MAX_SOURCES]


# ---- the freeze verdict for a source ---------------------------------------------------------------------------------------------------------
def can_freeze(rec, cfg):
    """(True, "") only for an unprotected app that is neither part of a build nor hosts one, while freeze is on. Else (False, why): the reason is a short fixed
    text the dialog shows after "shown only:", so an operator sees why a heavy source has no Freeze button."""
    if rec["kind"] != "app":
        return False, {"build": "a build or test job", "agent": "an agent session"}.get(rec["kind"], "a system process")
    if rec.get("protected"):
        return False, "protected app: never frozen"
    if rec.get("excluded"):
        return False, "part of a build: never frozen"
    if rec.get("hosts_build"):
        return False, "has a terminal or build inside: never frozen"
    if not cfg.get("freeze", {}).get("enabled", True):
        return False, "freeze is turned off"
    return True, ""


# ---- the 5-minute window (the same shape as gui_hog.window_update / window_means) -------------------------------------------------------------
def window_update(gh_state, t, sources, total_cores, cfg):
    """Add this sample to gh_state["srcwin"] (trimmed to window_s) and refresh gh_state["srcmeta"]. A source is stored when it uses `min_row_cores`
    or holds `min_row_rss_mb`, or is a waiting build; the busiest MAX_SOURCES only."""
    tr = cfg["trigger"]
    row, meta = {}, gh_state["srcmeta"] if isinstance(gh_state.get("srcmeta"), dict) else {}
    for s in sources:
        if s["cores"] < tr["min_row_cores"] and s["rss_mb"] < tr["min_row_rss_mb"] and not s["waiting"]:
            continue
        row[s["key"]] = [round(s["cores"], 2), int(s["rss_mb"])]
        meta[s["key"]] = {"k": s["kind"], "id": s["id"], "n": s["name"], "b": s["bundle_id"] or "", "o": s["owner"] or "", "op": s["owner_pid"] or 0,
                          "w": bool(s["waiting"]), "pr": gh.clean(s["protected"] or "", 40), "ex": gh.clean(s["excluded"] or "", 40),
                          "hb": bool(s["hosts_build"]), "np": s["procs"], "hv": s["heaviest"], "hc": round(s["heaviest_cores"], 2)}
    prev = gh_state.get("srcwin") if isinstance(gh_state.get("srcwin"), list) else []
    keep = [x for x in prev if isinstance(x, dict) and isinstance(x.get("s"), dict) and gh._fin(x.get("t")) and t - tr["window_s"] <= x["t"] <= t]
    keep.append({"t": t, "cpu": round(total_cores, 2), "s": row})
    gh_state["srcwin"] = keep
    live = {k for x in keep for k in x["s"]}
    gh_state["srcmeta"] = {k: v for k, v in meta.items() if k in live}


def window_means(gh_state, t, cfg):
    """[{key, kind, id, name, owner, ..., cores_5m, cpu_now, rss_mb, share, present, waiting}] busiest first. `cores_5m` is the mean over the samples in the
    window (a source missing from a sample counts 0), `share` that mean over the mean of the machine's total cores in the same samples (0..1), RSS the latest
    reading (0 for a source that has gone)."""
    win = [x for x in (gh_state.get("srcwin") if isinstance(gh_state.get("srcwin"), list) else [])
           if isinstance(x, dict) and gh._fin(x.get("t")) and t - cfg["trigger"]["window_s"] <= x["t"] <= t and isinstance(x.get("s"), dict)]
    n = len(win)
    if not n:
        return []
    win.sort(key=lambda x: x["t"])
    latest = win[-1]["s"]
    total = sum(x["cpu"] for x in win if gh._fin(x.get("cpu"))) / n
    meta = gh_state.get("srcmeta") if isinstance(gh_state.get("srcmeta"), dict) else {}
    sums, last = {}, {}
    for x in win:
        for k, it in x["s"].items():
            if isinstance(it, list) and len(it) >= 2 and gh._fin(it[0]) and gh._fin(it[1]):
                sums[k] = sums.get(k, 0.0) + it[0]
                last[k] = it
    out = []
    for k, s in sums.items():
        m = meta[k] if isinstance(meta.get(k), dict) else {}
        here = k in latest and isinstance(latest[k], list) and len(latest[k]) >= 2
        mean = s / n
        out.append({"key": gh.clean(k, 60), "kind": gh.clean(m.get("k", "system"), 12), "id": gh.clean(str(m.get("id", "")), 60), "name": gh.clean(m.get("n", k), 60),
                    "bundle_id": gh.clean(m.get("b", ""), 80), "owner": gh.clean(m.get("o", ""), 40) or None, "owner_pid": m.get("op") or None,
                    "waiting": bool(m.get("w")), "protected": gh.clean(m.get("pr", ""), 40) or None, "excluded": gh.clean(m.get("ex", ""), 40) or None,
                    "hosts_build": bool(m.get("hb")), "procs": int(m.get("np", 0)) if isinstance(m.get("np", 0), int) else 0,
                    "heaviest": gh.clean(m.get("hv", ""), 40), "heaviest_cores": float(m.get("hc", 0)) if gh._fin(m.get("hc", 0)) else 0.0,
                    "cores_5m": mean, "cpu_now": float(latest[k][0]) if here and gh._fin(latest[k][0]) else 0.0,
                    "rss_mb": int(last[k][1]) if here else 0, "share": (mean / total) if total > 0 else 0.0, "present": bool(here)})
    out.sort(key=lambda r: -r["cores_5m"])
    return out


def snapshot_rows(means, cfg, limit=10, where=None):
    """The rows the dialog and `gui-hog status` show: gone sources dropped, the busiest first (waiting builds kept even at 0 cores), each with the
    can-freeze verdict. `where` is {pid: short folder name} for a build or agent root (read by the caller from the live process, optional). Returns
    (rows, more)."""
    where = where or {}
    rows = [m for m in means if m["present"] and (m["cores_5m"] >= cfg["trigger"]["min_row_cores"] or m["rss_mb"] >= cfg["trigger"]["min_row_rss_mb"] or m["waiting"])]
    out = []
    for m in rows[:limit]:
        ok, why = can_freeze(m, cfg)
        r = {"key": m["key"], "kind": m["kind"], "name": m["name"], "owner": m["owner"], "cores_5m": round(m["cores_5m"], 2), "cpu_now": round(m["cpu_now"], 2),
             "rss_mb": int(m["rss_mb"]), "share": round(m["share"], 3), "procs": m["procs"], "heaviest": m["heaviest"], "waiting": m["waiting"],
             "can_freeze": ok, "why": why, "app_id": m["id"] if m["kind"] == "app" else ""}
        pid = m["id"] if m["kind"] in ("build", "agent") else None
        if pid is not None and where.get(str(pid)):
            r["where"] = gh.clean(where[str(pid)], 60)
        out.append(r)
    return out, max(0, len(rows) - limit)


def proc_cwds(pids, timeout=3):
    """{pid str: last two components of its working directory} for a few pids, from ONE `lsof -a -d cwd -Fpn` call (read-only, no arguments of any
    process, no environment). {} when lsof is missing, fails or times out: the folder is a nicety, never a requirement."""
    pids = [str(int(p)) for p in pids if str(p).isdigit()][:8]
    if not pids:
        return {}
    try:
        r = subprocess.run(["lsof", "-a", "-d", "cwd", "-Fpn", "-p", ",".join(pids)], capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, LC_ALL="C"))
    except (OSError, subprocess.TimeoutExpired):
        return {}
    out, cur = {}, None
    for ln in r.stdout.splitlines():
        if ln.startswith("p") and ln[1:].isdigit():
            cur = ln[1:]
        elif ln.startswith("n") and cur is not None:
            out[cur] = "/".join(os.path.normpath(ln[1:]).split("/")[-2:])
    return out
