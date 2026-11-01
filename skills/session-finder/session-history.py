#!/usr/bin/env python3
"""Full-text search over every agent session on this machine, live or ended.

    session-history.py ccc slowness         # best-matching sessions across all agents
    session-history.py --agent hermes ccc   # one agent only (repeatable)
    session-history.py --limit 20 ccc       # more sessions
    session-history.py --json ccc           # machine-readable
    session-history.py --update-only        # just bring the index up to date
    session-history.py --status             # read-only: index age, sessions not yet indexed per agent
    session-history.py --install|--uninstall  # the 10-minute launchd refresh (primary checkout only)
    SESSION_INDEX_DIR=DIR ...               # use another index directory (tests)
    session-history.py --rebuild            # drop and rebuild (slow)
    session-history.py --agents             # which adapters loaded, session counts
    session-history.py --check              # prove the FTS5 index works (integrity + a MATCH)

One adapter per agent in adapters/*.py (contract in adapters/README.md). SQLite FTS5
index at ~/.local/state/session-index/history.v2.sqlite: a session is re-read only
when its fingerprint changed. User and assistant text only (no tool output).
Document adapters (todo notes, `--agent todo`) index each note as one entry.
The index holds prompt text: private, never copy it into a repo. No model tokens.
Exit 0 = hits, 1 = none, 2 = cannot run.
"""
import argparse
import os
import shlex
import subprocess
import importlib.util
import json
import sqlite3
import sys
import time
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
INDEX_DIR = Path(os.environ.get("SESSION_INDEX_DIR") or Path.home() / ".local/state/session-index").expanduser().resolve()
DB = INDEX_DIR / "history.v2.sqlite"
CAP = {"user": 4000, "assistant": 2000, "note": 4000}
SCHEMA = """
CREATE TABLE IF NOT EXISTS files(key TEXT PRIMARY KEY, agent TEXT, sid TEXT, fp TEXT, cwd TEXT, title TEXT, mtime REAL);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v REAL);
CREATE VIRTUAL TABLE IF NOT EXISTS msgs USING fts5(key UNINDEXED, role UNINDEXED, text, tokenize='porter unicode61');
"""


def load_adapters(only):
    mods = []
    for p in sorted((HERE / "adapters").glob("*.py")):
        spec = importlib.util.spec_from_file_location(f"sf_adapter_{p.stem}", p)
        try:
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
        except Exception as e:  # a broken adapter must not take the others down
            print(f"adapter {p.name} failed to load: {e}", file=sys.stderr)
            continue
        if not only or m.AGENT in only:
            mods.append(m)
    return mods


def update(db, mods, only=()):
    stats = {}
    for m in mods:
        added = seen = 0
        try:
            sess = list(m.sessions())
        except Exception as e:
            print(f"adapter {m.AGENT}: sessions() failed: {e}", file=sys.stderr)
            continue
        for s in sess:
            seen += 1
            row = db.execute("SELECT fp FROM files WHERE key=?", (s["key"],)).fetchone()
            if row and row[0] == s["fp"]:
                continue
            try:
                cwd, title, msgs = s["load"]()
            except Exception as e:
                print(f"adapter {m.AGENT}: skip {s['sid']}: {e}", file=sys.stderr)
                continue
            db.execute("DELETE FROM msgs WHERE key=?", (s["key"],))
            db.executemany(
                "INSERT INTO msgs(key, role, text) VALUES (?,?,?)",
                [(s["key"], r, t[: CAP.get(r, 2000)]) for r, t in msgs if t and len(t) > 3],
            )
            db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?)",
                       (s["key"], m.AGENT, s["sid"], s["fp"], cwd or "", title or "", s["mtime"]))
            db.commit()
            added += 1
        stats[m.AGENT] = (seen, added)
    if not only:  # a full pass: drop entries of agents whose adapter is gone (e.g. a removed TUI)
        known = [m.AGENT for m in mods]
        gone = [r[0] for r in db.execute("SELECT DISTINCT agent FROM files") if r[0] not in known]
        for agent in gone:
            db.execute("DELETE FROM msgs WHERE key IN (SELECT key FROM files WHERE agent=?)", (agent,))
            n = db.execute("DELETE FROM files WHERE agent=?", (agent,)).rowcount
            db.commit()
            stats[agent] = (0, -n)
    if not only:
        db.execute("INSERT OR REPLACE INTO meta VALUES('updated', ?)", (time.time(),))
        db.commit()
    return stats


def status() -> int:
    """Read-only: how far behind the index is. Nothing is written or reindexed."""
    if not DB.exists():
        print("no index yet: run session-history.py --update-only", file=sys.stderr)
        return 2
    db = sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True, timeout=30)
    now = time.time()
    try:
        last = db.execute("SELECT v FROM meta WHERE k='updated'").fetchone()
    except sqlite3.Error:
        last = None
    print("last full update: " + (f"{(now - last[0]) / 60:.0f} min ago" if last else "never recorded (run --update-only)"))
    indexed = {k: (fp, mt) for k, fp, mt in db.execute("SELECT key, fp, mtime FROM files")}
    per = {a: n for a, n in db.execute("SELECT agent, count(*) FROM files GROUP BY agent")}
    print(f"{'agent':10}{'indexed':>8}{'on disk':>8}{'unindexed':>10}{'changed':>8}{'orphan':>7}  newest session")
    worst = 0
    for m in load_adapters(set()):
        seen, new, changed, newest = set(), 0, 0, 0.0
        try:
            for sess in m.sessions():
                seen.add(sess["key"])
                newest = max(newest, sess["mtime"] or 0)
                row = indexed.get(sess["key"])
                new += row is None
                changed += row is not None and row[0] != sess["fp"]
        except Exception as e:
            print(f"{m.AGENT:10} sessions() failed: {e}")
            continue
        orphan = sum(1 for k in indexed if k.startswith(m.AGENT + ":") and k not in seen)
        worst = max(worst, new + changed)
        age = f"{(now - newest) / 3600:.1f} h ago" if newest else "-"
        print(f"{m.AGENT:10}{per.get(m.AGENT, 0):8}{len(seen):8}{new:10}{changed:8}{orphan:7}  {age}")
    print("orphan = session gone from its agent's store, kept here as history (never pruned)")
    return 1 if worst else 0


PLIST = "com.djbclark.session-history-update.plist"


def render_plist(template: str, repo: Path) -> str:
    """Fill in the job: the checkout it runs and the index directory it refreshes and logs to (SESSION_INDEX_DIR
    of the installing shell, else the default), so the installed job and this command see the same database."""
    return template.replace("__REPO__", escape(str(repo))).replace("__INDEX_DIR__", escape(str(INDEX_DIR)))


def install(remove: bool) -> int:
    """Copy launchd/<PLIST> to ~/Library/LaunchAgents and (un)load it."""
    dest = Path.home() / "Library/LaunchAgents" / PLIST
    domain = f"gui/{os.getuid()}"
    if remove:
        subprocess.run(["launchctl", "bootout", domain, str(dest)], check=False, capture_output=True)
        dest.unlink(missing_ok=True)
        print(f"removed {dest}")
        return 0
    # The job must run the primary checkout, never a linked worktree (unreviewed branch state that
    # `git worktree remove` later deletes): resolve it from the repository's common git dir.
    clean = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")}
    g = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                       check=False, capture_output=True, text=True, env=clean)
    if g.returncode == 0 and g.stdout.strip():
        repo = Path(g.stdout.strip()).parent
    elif (HERE.parent.parent / ".git").is_dir():  # git failed: only a primary checkout (.git is a directory) is safe
        repo = HERE.parent.parent
    else:
        print("cannot resolve the primary checkout (git failed and this is a linked worktree)", file=sys.stderr)
        return 2
    if not ((repo / "launchd" / PLIST).is_file() and (repo / "skills/session-finder/session-history.py").is_file()):
        print(f"{repo} (the primary checkout) lacks this job or script: merge this change and fast-forward it first", file=sys.stderr)
        return 2
    INDEX_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)  # launchd's stdout/stderr files live here
    subprocess.run(["launchctl", "bootout", domain, str(dest)], check=False, capture_output=True)  # reinstall = replace
    dest.parent.mkdir(parents=True, exist_ok=True)  # a fresh account has no ~/Library/LaunchAgents yet
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(render_plist((repo / "launchd" / PLIST).read_text(), repo))
    os.replace(tmp, dest)
    r = subprocess.run(["launchctl", "bootstrap", domain, str(dest)], check=False, capture_output=True, text=True)
    print(f"installed {dest}; bootstrap rc={r.returncode} {r.stderr.strip()}")
    return r.returncode


def check(db) -> bool:
    """Prove FTS5 is usable: compiled in, the virtual table is intact, a MATCH returns rows."""
    try:
        fts = any("FTS5" in r[0] for r in db.execute("PRAGMA compile_options"))
        db.execute("INSERT INTO msgs(msgs) VALUES('integrity-check')")  # raises SQLITE_CORRUPT_VTAB if broken
        n_files, n_msgs = db.execute("SELECT (SELECT count(*) FROM files), (SELECT count(*) FROM msgs)").fetchone()
        sample = db.execute("SELECT text FROM msgs LIMIT 1").fetchone()
        word = next((w for w in (sample[0].split() if sample else []) if w.isalpha() and len(w) > 3), "")
        hits = db.execute("SELECT count(*) FROM msgs WHERE msgs MATCH ?", ('"' + word + '"',)).fetchone()[0] if word else 0
        agents = ", ".join(f"{a}={n}" for a, n in db.execute("SELECT agent, count(*) FROM files GROUP BY agent"))
        ok = fts and n_msgs > 0 and hits > 0
        print(f"fts5 {'ok' if ok else 'BROKEN'}: compiled={fts} integrity=ok entries={n_files} rows={n_msgs} "
              f"probe MATCH {word!r} -> {hits} rows\n  {agents}", file=sys.stderr)
        return ok
    except sqlite3.Error as e:
        print(f"fts5 BROKEN: {e} (try --rebuild)", file=sys.stderr)
        return False


FLEET_RUNNING = frozenset({"working", "idle", "silent", "blocked", "busy-background"})


def fleet_is_running(status) -> bool:
    """A whitelist: a finished or failed ACP launch, an archived or closed pane must not read as running."""
    status = str(status or "")
    return status in FLEET_RUNNING or status.startswith("card:")


def native_id(sid) -> str:
    sys.path.insert(0, str(HERE))  # python -I drops the script dir
    from nativeid import native_id as _native_id
    return _native_id(sid)


def fleet_running(agents):
    """For agents whose adapter cannot say what is running (no live()): the native ids and the (agent, cwd)
    pairs of their running fleet rows. Most fleet rows carry no native id (a Paseo-hosted codex has none), so
    the cwd pairs back a weaker "LIVE?" label. Empty when fleet.py cannot run."""
    exact, cwds = set(), set()
    try:
        sys.path.insert(0, str(HERE))  # python -I drops the script dir
        import fleet
        for r in fleet.sessions():
            if r.get("agent") not in agents or not fleet_is_running(r.get("status")):
                continue
            # an exited ACP launch stays in launches.jsonl with status idle: fleet marks it finished
            if r.get("finished") or r.get("ended") or (r.get("launch") or {}).get("result") is not None:
                continue
            if r.get("sid"):
                exact.add((r["agent"], native_id(r["sid"])))
            cwds.add((r["agent"], r.get("cwd") or ""))
    except Exception:
        pass
    return exact, cwds


def clean(text) -> str:
    """Printable text: C0, C1 and DEL control characters (escape sequences, newlines in an id) become '?'."""
    return "".join("?" if ord(c) < 32 or 127 <= ord(c) < 160 else c for c in str(text or ""))


def resume_hint(template, sid: str, cwd: str) -> str:
    """The printed `resume:` line. Quoted, and empty when an id or directory holds a control character
    (a newline ends a shell comment or a quoted string a template might sit in)."""
    if not template or any(ord(c) < 32 or c == "\x7f" for c in sid + (cwd or "")):
        return ""
    if callable(template):  # an adapter whose command depends on the session (crush: its project's data dir)
        return template(sid, cwd or "")
    return template.format(sid=shlex.quote(sid), cwd=shlex.quote(cwd or ""))


def _main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)
    ap.add_argument("keywords", nargs="*")
    ap.add_argument("--agent", action="append", default=[])
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--update-only", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--agents", action="store_true")
    ap.add_argument("--check", action="store_true", help="FTS5 integrity check and a probe MATCH; exit 2 on failure")
    ap.add_argument("--status", action="store_true", help="read-only: index age and, per agent, sessions not yet indexed; exit 1 if any")
    ap.add_argument("--install", action="store_true", help="install the launchd job that runs --update-only every 10 minutes")
    ap.add_argument("--uninstall", action="store_true", help="remove that launchd job")
    a = ap.parse_args()
    if a.install or a.uninstall:
        return install(a.uninstall)
    if a.status:
        return status()
    if not (a.keywords or a.update_only or a.rebuild or a.agents or a.check):
        ap.print_usage(sys.stderr)
        return 2

    INDEX_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    if a.rebuild and DB.exists():
        DB.unlink()
    db = sqlite3.connect(DB, timeout=120)
    os.chmod(DB, 0o600)  # prompt text: private even if SESSION_INDEX_DIR points into a shared directory
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    mods = load_adapters(set(a.agent))
    t0 = time.time()
    stats = update(db, mods, set(a.agent))
    if a.check:
        ok = check(db)
        if not a.keywords:
            return 0 if ok else 2
    if a.agents or a.update_only or a.rebuild:
        for name, (seen, added) in stats.items():
            print(f"{name:10} sessions={seen:5} {'dropped=' + str(-added) + ' (no adapter)' if added < 0 else 'reindexed=' + str(added)}", file=sys.stderr)
        print(f"{time.time() - t0:.1f}s", file=sys.stderr)
        if not a.keywords:
            return 0

    match = " ".join('"' + k.replace('"', "") + '"*' for k in a.keywords)
    agent_sql = ""
    params = [match]
    if a.agent:
        agent_sql = f"AND f.agent IN ({','.join('?' * len(a.agent))})"
        params += a.agent
    rows = db.execute(
        f"SELECT m.key, m.role, bm25(msgs), snippet(msgs, 2, '[', ']', '...', 24) "
        f"FROM msgs m JOIN files f ON f.key = m.key WHERE msgs MATCH ? {agent_sql} ORDER BY 3 LIMIT 600",
        params,
    ).fetchall()
    best = {}
    for key, role, rank, snip in rows:
        prev = best.get(key)
        count = prev[3] + 1 if prev else 1
        if not prev or rank < prev[0]:
            best[key] = (rank, role, snip, count)
        else:
            best[key] = (prev[0], prev[1], prev[2], count)
    # titles are not in the FTS table (a Hermes or omp title may never appear in the message text): a session
    # whose title holds every keyword is a hit too, ranked after the text matches
    esc = lambda k: k.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace('"', "")  # noqa: E731
    tkw = [esc(k.lower()) for k in a.keywords if esc(k).strip()]  # an empty keyword would match every title
    if tkw:
        title_sql = " AND ".join("lower(title) LIKE ? ESCAPE '\\'" for _ in tkw)
        for key, title in db.execute(f"SELECT key, title FROM files WHERE {title_sql} {agent_sql.replace('f.agent', 'agent')} LIMIT 100",
                                     [f"%{k}%" for k in tkw] + a.agent):
            best.setdefault(key, (1e9, "title", title or "", 0))
    live = {m.AGENT: (m.live() if hasattr(m, "live") else set()) for m in mods}
    labels = {m.AGENT: (getattr(m, "LIVE_LABEL", "LIVE"), getattr(m, "ENDED_LABEL", "ended")) for m in mods}
    info = {m.AGENT: (m.live_info() if hasattr(m, "live_info") else {}) for m in mods}
    resume = {m.AGENT: getattr(m, "RESUME", "") for m in mods}
    blind = {m.AGENT for m in mods if not hasattr(m, "live")}
    picked = [(hit, db.execute("SELECT agent, sid, cwd, title, mtime FROM files WHERE key=?", (hit[0],)).fetchone())
              for hit in sorted(((k, *v) for k, v in best.items()), key=lambda h: h[1])[: a.limit]]
    # the fleet scan (herdr, orca, paseo, ps: seconds when a service stalls) only when a printed hit needs it
    need = blind & {row[0] for _, row in picked}
    fl_exact, fl_cwds = fleet_running(need) if need else (set(), set())
    out = []
    for (key, rank, role, snip, count), (agent, sid, cwd, title, mtime) in picked:
        is_live = sid in live.get(agent, set()) or (agent, sid) in fl_exact
        likely = (not is_live and agent in blind and (agent, cwd) in fl_cwds and time.time() - mtime < 600)
        out.append({"agent": agent, "sessionId": sid, "live": is_live,
                    "state": "LIVE?" if likely else labels.get(agent, ("LIVE", "ended"))[0 if is_live else 1], "cwd": cwd,
                    "title": title, "lastActive": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)),
                    "hits": count, "role": role, "snippet": " ".join(snip.split()),
                    "resume": resume_hint(resume.get(agent, ""), sid, cwd)})
    if info:
        sys.path.insert(0, str(HERE))  # python -I drops the script dir
        import where as _where
        for r in out:
            i = info.get(r["agent"], {}).get(r["sessionId"])
            if i:
                r["name"] = i["name"]
                r["where"] = _where.lookup(i["pid"], i["procStart"])
    if a.json:
        print(json.dumps(out, indent=1))
    else:
        for r in out:
            print(f"{r['agent']}  {clean(r['sessionId'])}  {r['state']}  {r['lastActive']}  hits={r['hits']}  cwd={clean(r['cwd'])}")
            print(f"    title: {clean(r['title']) or '(untitled)'}")
            if r.get("name"):
                print(f"    send to: {r['name']}")
            if r.get("where"):
                print(f"    where: {r['where']['where']} · {r['where']['cwd']}")
                if r["where"]["focus"]:
                    print(f"    focus: {r['where']['focus']}")
            print(f"    {r['role']}: {clean(r['snippet'])}")
            if r["resume"] and (not r["live"] or r["agent"] in blind):  # fleet-derived LIVE is not authoritative
                print(f"    resume: {r['resume']}")
    return 0 if out else 1


def main() -> int:
    """_main, but any crash exits 2 with one line: exit 1 means "no hits" to callers (session-find --all)."""
    try:
        return _main()
    except (sqlite3.Error, OSError) as e:
        print(f"session-history: {type(e).__name__}: {e} (try --check, or --rebuild)", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
