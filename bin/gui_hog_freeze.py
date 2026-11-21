"""gui_hog_freeze: Freeze for the GUI-hog dialog (docs/gui-hog-dialog.md sections F and I3, PR 3c).

Stdlib only. It imports `gui_hog` (grouping, the protected list, process identity) and never `load-watch`, so a broken sampler
cannot block a thaw. Nothing here ever runs by itself except `thaw_due`, which only RESUMES, and `auto_freeze_step`, which the sampler calls for the apps
of `[freeze.auto] order` only (B6 as amended 2026-11-21: any other freeze is an operator click).

    freeze(...)         vet the app (F6, F3, C4b), write the entry as `freezing` BEFORE any SIGSTOP (F2), stop the root first,
                        then its helpers, rescan up to 3 times (F4), then write the entry as `frozen`
    resume_entry / thaw_due / thaw_all / thaw_stopped_apps    every thaw path (F5, F7); children first, the root last
    frozen_view         what `gui-hog frozen` prints

State: <state_dir>/gui-hog/frozen.json (+ .prev, frozen.lock, events.jsonl), all reached through a directory file descriptor
opened with O_NOFOLLOW: a symlinked state directory or state file is refused, never followed (J4). Every freeze, resume and thaw
holds an flock on frozen.lock for the whole operation (F1). `frozen.json` is DATA: every entry is validated, a pid must be an
int in 2..2**31-1 (never 0 or -1, which `kill` reads as a process group), and a signal is only ever sent to a process whose pid,
start time, uid and kernel executable path all match the record (F3), and, for SIGCONT, which is still stopped.

Exit codes of the CLI: 0 ok; 2 usage; 3 protected; 4 identity changed; 5 hosts a build or terminal; 6 freeze disabled;
7 lock timeout; 8 sampler not loaded; 9 refused (state unusable, already frozen or stopped, a signal failed).
"""
import errno
import fcntl
import json
import os
import re
import secrets
import signal
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gui_hog as gh  # noqa: E402

LABEL = "com.djbclark.load-watch"
FROZEN, LOCK, EVENTS = "frozen.json", "frozen.lock", "events.jsonl"
MAX_PID = 2 ** 31
MAX_TIMED_S = 24 * 3600
CLOCK_ZONE = "America/New_York"
CLOCK_SPAN_S = 7 * 24 * 3600   # the same limit as the Swift `thawText`
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def clock_text(ts, now, zone=CLOCK_ZONE):
    """A resume time for people, in `zone` (default New York, operator ruling 2026-11-14): `9:52 PM`, with a 3-letter day name (`Sun 9:52 PM`) when the
    day is not today. The same words as the Swift side's `thawText`. A time that cannot be shown is `?`; a zone that cannot be loaded falls back to UTC, marked."""
    try:
        from zoneinfo import ZoneInfo
        tz, mark = ZoneInfo(zone), ""
    except Exception:   # no tz database, or a bad name: say so rather than lie about the zone
        tz, mark = timezone.utc, " UTC"
    try:
        if abs(float(ts) - float(now)) > CLOCK_SPAN_S:   # a timed freeze is at most 24 h; anything far off is a hand-edited file: show no time
            return "?"
        t, n = datetime.fromtimestamp(float(ts), tz), datetime.fromtimestamp(float(now), tz)
    except (OverflowError, ValueError, OSError, TypeError):
        return "?"
    text = f"{t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}{mark}"
    return text if t.date() == n.date() else f"{_DAYS[t.weekday()]} {text}"
STATES = ("freezing", "frozen", "thawing")
BY = ("dialog", "cli", "sampler", "uninstall", "recovery", "menubar", "auto")
EVENTS_MAX_BYTES = 1024 * 1024
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")   # never starts with "-": an id is never read as an option
# load-watch's AGENT_CLIS (tests/test_gui_hog_freeze.py pins that they are the same): a process under one of these is a build.
DEFAULT_AGENT_CLIS = frozenset({"claude", "codex", "opencode", "omp", "pi", "gemini", "copilot", "cursor-agent", "agy",
                                "crush", "kimi", "qwen", "goose", "aider", "amp", "droid", "kiro-cli", "paseo"})
OK, USAGE, PROTECTED, IDENTITY, HOSTS_BUILD, DISABLED, LOCK_TIMEOUT, SAMPLER, REFUSED = 0, 2, 3, 4, 5, 6, 7, 8, 9


class Refusal(Exception):
    """A freeze or thaw that did not happen; `code` is the CLI exit code. No signal was sent for the refused step."""

    def __init__(self, code, msg):
        super().__init__(msg)
        self.code, self.msg = code, msg


def _pid_ok(x):
    return type(x) is int and 1 < x < MAX_PID


def _num(x):
    return gh._fin(x)


# ---- the OS seam: process table, identity, signals (tests substitute fakes) ----------------------------------------------
class Ops:
    """Everything that touches processes. `table` is load-watch's ps table, `info` the identity of live pids, `kill` a signal."""

    def __init__(self, my_uid=None):
        self.my_uid = os.getuid() if my_uid is None else my_uid

    def table(self, timeout=20):
        """(table, rss_kb, ttys, states): {pid: (ppid, uid, cores, command)}, {pid: KB}, {pid with a tty}, {pid: ps state}; as load-watch's
        ps_table. Raises OSError when ps fails or times out."""
        try:
            out = subprocess.run(["ps", "-axo", "pid=,ppid=,uid=,%cpu=,state=,pri=,rss=,tty=,command="], capture_output=True, text=True,
                                 timeout=timeout, env=dict(os.environ, LC_ALL="C")).stdout
        except subprocess.TimeoutExpired as e:
            raise OSError("ps timed out") from e
        table, rss, ttys, states = {}, {}, set(), {}
        for line in out.splitlines():
            parts = line.split(None, 8)
            if len(parts) < 8 or not parts[0].isdigit():
                continue
            try:
                table[parts[0]] = (int(parts[1]), int(parts[2]), float(parts[3]) / 100, parts[8] if len(parts) > 8 else "")
            except ValueError:
                continue
            states[parts[0]] = parts[4]
            rss[parts[0]] = int(parts[6]) if parts[6].isdigit() else 0
            if parts[7] not in ("??", "?", "-"):
                ttys.add(parts[0])
        return table, rss, ttys, states

    def exe(self, pid):
        return gh.kernel_exe(pid)

    def info(self, pids):
        """{pid: {start, uid, state, exe}} for the pids that exist (a gone pid is absent). start is gui_hog.proc_start's string. Raises OSError
        when ps times out: an unreadable identity is never a match."""
        pids = [int(p) for p in pids]
        out = {}
        if os.path.isdir("/proc/self"):
            for p in pids:
                try:
                    st = Path(f"/proc/{p}/stat").read_text().rsplit(")", 1)[1].split()
                    out[p] = {"start": "proc:" + st[19], "uid": os.stat(f"/proc/{p}").st_uid, "state": st[0], "exe": gh.kernel_exe(p)}
                except (OSError, IndexError, ValueError):
                    continue
            return out
        for i in range(0, len(pids), 200):
            chunk = pids[i:i + 200]
            try:
                r = subprocess.run(["ps", "-o", "pid=,uid=,state=,lstart=", "-p", ",".join(map(str, chunk))], capture_output=True, text=True,
                                   timeout=5, env=dict(os.environ, LC_ALL="C", TZ="UTC"))
            except subprocess.TimeoutExpired as e:
                raise OSError("ps timed out") from e
            if r.returncode < 0:   # ps itself was killed (memory pressure): an empty answer is not "everything is gone"
                raise OSError(f"ps was killed by signal {-r.returncode}")
            for line in r.stdout.splitlines():
                parts = line.split(None, 3)
                if len(parts) == 4 and parts[0].isdigit() and parts[1].isdigit():
                    out[int(parts[0])] = {"start": " ".join(parts[3].split()), "uid": int(parts[1]), "state": parts[2], "exe": None}
        for p, rec in out.items():
            rec["exe"] = gh.kernel_exe(p)
        return out

    def kill(self, pid, sig):
        """Send `sig`; False when the process is already gone. Anything else (EPERM) raises."""
        try:
            os.kill(pid, sig)
            return True
        except ProcessLookupError:
            return False


def mismatch(rec, inf, my_uid, need_exe=True):
    """Why `inf` (live identity of rec's pid) is not `rec`'s process, or None when all four match (F3): "gone", "start", "uid", "exe".
    `need_exe=False` (SIGCONT, the safe direction) compares pid, start time and uid only: a bundle replaced or moved while the app was frozen
    changes what the kernel reports as its path, and that must never leave it stopped."""
    if inf is None or str(inf.get("state", "")).startswith("Z"):
        return "gone"
    if inf.get("start") != rec["start"]:
        return "start"
    if inf.get("uid") != rec["uid"] or inf.get("uid") != my_uid:
        return "uid"
    if need_exe and (not inf.get("exe") or inf["exe"] != rec["exe"]):
        return "exe"
    return None


def is_stopped(inf):
    return str(inf.get("state", "")).startswith("T")


# ---- the state directory (J4): directory fds, O_NOFOLLOW, owner and mode checked ----------------------------------------------
def _check_dir(fd, what, private=True):
    """Owned by this user and not writable by anyone else (`private`), or at least not world-writable (the parent load-watch made with the
    user's umask, which another user's group may legitimately share)."""
    st = os.fstat(fd)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & (0o022 if private else 0o002):
        raise Refusal(REFUSED, f"{what} is not a private directory of this user")


def open_state(state_dir, create=True):
    """A directory fd for <state_dir>/gui-hog, or None when it does not exist and `create` is false. Refuses a symlinked `state_dir` or
    `gui-hog`, another owner and a group- or world-writable directory (Refusal 9)."""
    sd = str(state_dir)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        if create:
            os.makedirs(sd, mode=0o700, exist_ok=True)
        pfd = os.open(sd, flags)
    except FileNotFoundError:
        return None
    except OSError as e:
        raise Refusal(REFUSED, f"state directory {sd} unusable: {e.strerror or e}") from e
    try:
        _check_dir(pfd, sd, private=False)
        try:
            return _open_child(pfd, create)
        except OSError as e:
            raise Refusal(REFUSED, f"{sd}/gui-hog unusable: {e.strerror or e}") from e
    finally:
        os.close(pfd)


def _open_child(pfd, create):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        fd = os.open("gui-hog", flags, dir_fd=pfd)
    except FileNotFoundError:
        if not create:
            return None
        os.mkdir("gui-hog", 0o700, dir_fd=pfd)
        fd = os.open("gui-hog", flags, dir_fd=pfd)
    try:
        _check_dir(fd, "gui-hog")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _read_at(dfd, name, cap=1 << 20):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > cap or st.st_uid != os.getuid():
            raise OSError(errno.EINVAL, f"{name} is not a small regular file of this user")
        return os.read(fd, cap + 1).decode("utf-8", "replace")
    finally:
        os.close(fd)


def _write_at(dfd, name, data, keep_prev=False):
    """Atomic: a unique temp file in the same directory, fsync, os.replace. A symlink at `name` is replaced, never followed."""
    tmp = f".{name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
    try:
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        if keep_prev:
            try:
                json.loads(_read_at(dfd, name))   # keep only a GOOD previous file
                try:
                    os.unlink(name + ".prev", dir_fd=dfd)
                except FileNotFoundError:
                    pass
                os.link(name, name + ".prev", src_dir_fd=dfd, dst_dir_fd=dfd, follow_symlinks=False)
            except (OSError, ValueError):
                pass
        os.replace(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
    except BaseException:
        try:
            os.unlink(tmp, dir_fd=dfd)
        except OSError:
            pass
        raise
    os.fsync(dfd)


class Lock:
    """flock on frozen.lock for a whole operation (F1); Refusal 7 when it cannot be taken within `timeout` seconds."""

    def __init__(self, dfd, timeout=5.0):
        self.dfd, self.timeout, self.fd = dfd, timeout, None

    def __enter__(self):
        try:
            self.fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=self.dfd)
        except OSError as e:
            raise Refusal(REFUSED, f"cannot open {LOCK}: {e.strerror or e}") from e
        end = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() >= end:
                    os.close(self.fd)
                    self.fd = None
                    raise Refusal(LOCK_TIMEOUT, "frozen.lock is held by another gui-hog operation") from None
                time.sleep(0.05)

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)
        return False


# ---- the entries ---------------------------------------------------------------------------------------------------------------
def _rec(d, member=False):
    """A validated process record {pid, start, uid, exe}, or None."""
    if not isinstance(d, dict) or not _pid_ok(d.get("pid")):
        return None
    start, uid, exe = d.get("start"), d.get("uid"), d.get("exe")
    if not (isinstance(start, str) and 0 < len(start) <= 200 and type(uid) is int and 0 <= uid < MAX_PID
            and isinstance(exe, str) and 0 < len(exe) <= 4096):
        return None
    return {"pid": d["pid"], "start": start, "uid": uid, "exe": exe}


def norm_entry(e):
    """The validated, normalised entry, or None. `frozen.json` is hand-editable data: a wrong type, a pid that is not an int in 2..2**31-1
    (0 and -1 are process groups to kill), a missing field or a non-finite time drops the entry. A timed thaw_at is clamped to 24 h
    after frozen_at (a hand-edited far-future time must not hold an app frozen), and a missing or garbled one counts as due."""
    try:
        if not isinstance(e, dict) or e.get("state") not in STATES or e.get("mode") not in ("timed", "indefinite"):
            return None
        eid = e.get("id")
        root = _rec(e.get("root"))
        app = e.get("app") if isinstance(e.get("app"), dict) else {}
        if not (isinstance(eid, str) and ID_RE.match(eid)) or root is None or not _num(e.get("frozen_at")):
            return None
        members = [m for m in (_rec(x) for x in (e.get("members") if isinstance(e.get("members"), list) else [])[:5000]) if m]
        seen, uniq = {root["pid"]}, []
        for m in members:
            if m["pid"] not in seen:
                seen.add(m["pid"])
                uniq.append(m)
        frozen_at = float(e["frozen_at"])
        thaw_at = e.get("thaw_at")
        if e["mode"] == "timed":
            thaw_at = frozen_at if not _num(thaw_at) else min(float(thaw_at), frozen_at + MAX_TIMED_S)
        else:
            thaw_at = None
        by = e.get("by") if e.get("by") in BY else "cli"
        out = {"id": eid, "state": e["state"], "app": {"name": gh.clean(app.get("name", ""), 60), "bundle_id": gh.clean(app.get("bundle_id") or "", 80),
                                                       "bundle_path": gh.clean(app.get("bundle_path") or "", 200)},
               "root": root, "members": uniq, "mode": e["mode"], "frozen_at": frozen_at, "thaw_at": thaw_at, "by": by,
               "updated": float(e["updated"]) if _num(e.get("updated")) else frozen_at}
        if type(e.get("kept_running")) is int and 0 <= e["kept_running"] < 100000:
            out["kept_running"] = e["kept_running"]
        if isinstance(e.get("kept"), list):   # names of the processes the keep-running rule left running (informational: never signalled, never trusted)
            names = [gh.clean(x, 60) for x in e["kept"][:20] if isinstance(x, str)]
            if names:
                out["kept"] = names
        return out
    except Exception:  # noqa: BLE001 - the file is data; nothing in it may raise
        return None


def load_entries(dfd):
    """(entries, notes): the valid entries of frozen.json, or of frozen.json.prev when that one is missing or corrupt. `notes` says what was wrong
    (an unreadable or symlinked file, dropped invalid entries). Refusal 9 only when a file EXISTS and none can be read."""
    notes, unusable = [], False
    for name in (FROZEN, FROZEN + ".prev"):
        try:
            obj = json.loads(_read_at(dfd, name))
            if not isinstance(obj, dict) or obj.get("v") != 1 or not isinstance(obj.get("entries"), list):
                raise ValueError("shape")
        except FileNotFoundError:
            continue
        except (OSError, ValueError, RecursionError) as e:
            notes.append(f"{name}: unreadable ({e.strerror if isinstance(e, OSError) and e.strerror else type(e).__name__})")
            unusable = True
            continue
        good = [x for x in (norm_entry(e) for e in obj["entries"]) if x]
        if len(good) != len(obj["entries"]):
            notes.append(f"{name}: dropped {len(obj['entries']) - len(good)} invalid entries")
        if name != FROZEN:
            notes.append("using frozen.json.prev")
        return good, notes
    if unusable:
        raise Refusal(REFUSED, "frozen.json and its .prev are unusable (" + "; ".join(notes) + "); use `gui-hog thaw --all --stopped-apps`")
    return [], notes


def save_entries(dfd, entries):
    _write_at(dfd, FROZEN, json.dumps({"v": 1, "entries": entries}, separators=(",", ":")).encode(), keep_prev=True)


def event(dfd, ev, by, **kw):
    """Append one line to events.jsonl (every freeze and thaw, with `by`). Never raises: a log failure must not stop a thaw."""
    try:
        line = {"t": gh._iso(kw.pop("now", None) or time.time()), "event": ev, "by": by if by in BY else "cli"}
        line.update(kw)
        data = (json.dumps(line, separators=(",", ":"), default=str) + "\n").encode()
        try:
            if os.stat(EVENTS, dir_fd=dfd, follow_symlinks=False).st_size >= EVENTS_MAX_BYTES:
                os.replace(EVENTS, EVENTS + ".1", src_dir_fd=dfd, dst_dir_fd=dfd)
        except OSError:
            pass
        fd = os.open(EVENTS, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=dfd)
        try:
            if stat.S_ISREG(os.fstat(fd).st_mode):
                while data:
                    data = data[os.write(fd, data):]
        finally:
            os.close(fd)
    except Exception:  # noqa: BLE001
        pass


# ---- vet (F3, F4a, F6, C4b) ------------------------------------------------------------------------------------------------------
def _ancestors(table, pid):
    out, p, hops = set(), str(pid), 0
    while p in table and hops < 64:
        out.add(int(p))
        p, hops = str(table[p][0]), hops + 1
        if p in ("0", "1"):
            break
    return out


def vet_app(pid, ops, cfg, state_dir, *, start=None, bundle_id=None, bundle_path=None, now=None, agent_clis=DEFAULT_AGENT_CLIS,
            allow_stopped_root=False):
    """Everything that decides whether the app rooted at `pid` may be frozen, read from the LIVE processes (D4: the arguments are expected values
    only). Returns {"app": {...}, "root": rec, "members": [rec, ...]} (members exclude the root, parents before children), or raises
    Refusal: 4 the live identity differs from `start`/`bundle_id`/`bundle_path` or is not an app; 3 protected (F6, on the root AND on every
    member, and the process of this tool and its ancestors); 5 the app hosts a build or terminal subtree (C4b, E2)."""
    my_uid = ops.my_uid
    if not _pid_ok(pid):
        raise Refusal(IDENTITY, f"bad pid {pid!r}")
    table, rss_kb, ttys, states = ops.table()
    inf = ops.info([pid]).get(pid)
    if inf is None or str(pid) not in table:
        raise Refusal(IDENTITY, f"pid {pid} is gone")
    if start is not None and inf["start"] != start:
        raise Refusal(IDENTITY, f"pid {pid} has start time {inf['start']!r}, expected {start!r} (pid reused?)")
    if inf["uid"] != my_uid:
        raise Refusal(PROTECTED, f"pid {pid} runs as another user")
    exe = inf["exe"]
    if not exe:
        raise Refusal(IDENTITY, f"pid {pid} has no readable executable path")
    exe_real = gh._real(exe)
    bpath = gh._app_prefix(exe_real)
    if not bpath:
        raise Refusal(IDENTITY, f"pid {pid} ({exe}) is not an app bundle process")
    live_id = gh._plist_id(bpath)
    if bundle_id is not None and bundle_id != (live_id or ""):
        raise Refusal(IDENTITY, f"live bundle id {live_id!r} differs from the expected {bundle_id!r}")
    if bundle_path is not None and gh._real(bundle_path) != bpath:
        raise Refusal(IDENTITY, f"live bundle path {bpath!r} differs from the expected {bundle_path!r}")
    held = gh.read_holds(state_dir, now or time.time(), sweep=False)
    held_pids = [h["pid"] for h in held] + [h["caller_pid"] for h in held if h.get("caller_pid")]
    lsapps = [{"name": os.path.basename(bpath)[:-4], "bundle_id": live_id, "bundle_path": bpath, "exe": exe, "pid": pid, "type": "Foreground"}]
    apps = gh.group_apps(table, rss_kb, ttys, lsapps, exe_of=ops.exe, my_uid=my_uid, held_pids=held_pids, agent_clis=agent_clis, cfg=cfg)
    app = next((a for a in apps if a["id"] == str(pid)), None)
    if app is None:
        raise Refusal(IDENTITY, f"pid {pid} is not the root of an app")
    if app["protected"]:
        raise Refusal(PROTECTED, f"protected app ({app['protected']})")
    if app["excluded"]:
        raise Refusal(PROTECTED, f"the app is part of a build ({app['excluded']})")
    if app["hosts_build"]:
        raise Refusal(HOSTS_BUILD, "the app has a build or terminal subtree inside: no actions")
    pids = [int(p) for p in app["member_pids"]]
    infos = ops.info(pids)
    mine = _ancestors(table, os.getpid()) | {os.getpid()}
    bundle_real = gh._real(bpath)
    root = {"pid": pid, "start": inf["start"], "uid": my_uid, "exe": exe}
    def depth(p):   # parents before children, so a resume (reversed) runs deepest first; a helper launchd started counts as the root's child
        d, a = 0, str(p)
        while a != str(pid) and a in table and d < 64:
            a, d = str(table[a][0]), d + 1
        return d if a == str(pid) else 1
    members = []
    for p in sorted(pids, key=lambda p: (depth(p), p)):
        mi = infos.get(p) if p != pid else inf
        if mi is None:
            continue   # exited while we looked
        if p in mine:
            raise Refusal(PROTECTED, f"pid {p} is this tool or one of its ancestors")
        if mi["uid"] != my_uid:
            raise Refusal(PROTECTED, f"pid {p} in the tree runs as another user")
        mexe = mi["exe"]
        if not mexe:
            continue   # identity cannot be proved (F3): never stopped
        mreal = gh._real(mexe)
        why = gh.protect_reason(live_id, bundle_real, mreal, mi["uid"], my_uid, cfg)
        if why:
            raise Refusal(PROTECTED, f"pid {p} ({os.path.basename(mreal)}) is protected ({why})")
        if not gh._under(mreal, bundle_real):
            raise Refusal(HOSTS_BUILD, f"pid {p} ({os.path.basename(mreal)}) runs outside the app's bundle")
        if p != pid and mreal == gh._real(exe):   # the app's own main binary again: a second instance, which has its own row and its own terminals
            raise Refusal(HOSTS_BUILD, f"pid {p} is another instance of the same app: freeze neither")
        if p == pid:
            if is_stopped(mi) and not allow_stopped_root:
                raise Refusal(REFUSED, f"pid {pid} is already stopped (not by us)")
            continue
        members.append({"pid": p, "start": mi["start"], "uid": mi["uid"], "exe": mexe, "stopped": is_stopped(mi)})
    return {"app": {"name": gh.clean(app["name"]), "bundle_id": gh.clean(live_id or "", 80), "bundle_path": gh.clean(bpath, 200)},
            "root": root, "members": members, "kept": list(app.get("kept_names") or [])}


# ---- signals --------------------------------------------------------------------------------------------------------------------
def _signal_one(ops, rec, sig):
    """The one place a signal is sent: re-read the identity, require all four fields to match (F3) and, for SIGCONT, state T. Returns
    "sent", "gone", "start"/"uid"/"exe" (a mismatch: no signal), "not-stopped" (SIGCONT only) or "already-stopped" (SIGSTOP only).
    SIGCONT needs pid, start time, uid and state T but not the executable (a replaced or moved bundle still gets resumed: "sent-exe-changed").
    Raises OSError when the identity could not be read (ps timeout) or the signal failed with EPERM."""
    inf = ops.info([rec["pid"]]).get(rec["pid"])
    why = mismatch(rec, inf, ops.my_uid, need_exe=sig != signal.SIGCONT)
    if why:
        return why
    if sig == signal.SIGCONT and not is_stopped(inf):
        return "not-stopped"
    if sig == signal.SIGSTOP and is_stopped(inf):
        return "already-stopped"
    if not _pid_ok(rec["pid"]):
        return "gone"
    if not ops.kill(rec["pid"], sig):
        return "gone"
    return "sent-exe-changed" if sig == signal.SIGCONT and inf.get("exe") != rec["exe"] else "sent"


def _resume(dfd, entries, entry, ops, by, now, deadline=None):
    """SIGCONT every process of `entry`, children first and the root last (F4), then delete it. Returns (finished, notes). The entry is
    written as `thawing` first (F2); one that could not be completed (ps timeout, EPERM, the budget) stays with the unfinished processes
    listed, for the next attempt."""
    entry["state"], entry["updated"] = "thawing", now
    notes, pending = [], []
    try:
        save_entries(dfd, entries)
    except OSError as e:   # a full or read-only disk must never block a SIGCONT: the (identity-checked) signals go first, the record is retried after
        notes.append(f"state not written: {e.strerror or e}")
    order = list(reversed(entry["members"])) + [entry["root"]]
    for i, rec in enumerate(order):
        if deadline is not None and time.monotonic() > deadline:
            pending.extend(order[i:])
            notes.append("budget exhausted")
            break
        try:
            res = _signal_one(ops, rec, signal.SIGCONT)
        except OSError as e:
            pending.append(rec)
            res = f"error: {e.strerror or e}"
        notes.append(f"{rec['pid']}:{res}")
        if res == "sent-exe-changed":
            event(dfd, "exe-changed", by, now=now, entry=entry["id"], pid=rec["pid"], note="resumed; its executable path is not the recorded one")
        elif res == "not-stopped":
            event(dfd, "not-stopped", by, now=now, entry=entry["id"], pid=rec["pid"], note="something else resumed it")
        elif res in ("start", "uid", "exe", "gone"):
            event(dfd, "drop", by, now=now, entry=entry["id"], pid=rec["pid"], why=res)
    if pending:   # keep only what is unfinished; the last pending record takes the root's place (order: children first stays true)
        entry["root"], entry["members"] = pending[-1], pending[:-1]
        try:
            save_entries(dfd, entries)
        except OSError:
            pass
        return False, notes
    entries[:] = [e for e in entries if e is not entry]
    try:
        save_entries(dfd, entries)
    except OSError as e:   # everything is resumed; the stale record only gives `not-stopped` lines at the next tick
        notes.append(f"state not written: {e.strerror or e}")
    event(dfd, "thaw", by, now=now, entry=entry["id"], app=entry["app"], pids=[r["pid"] for r in order], notes=notes[:200])
    return True, notes


# ---- freeze (F2, F4) -------------------------------------------------------------------------------------------------------------
def sampler_loaded(my_uid):
    """F8-2: a timed freeze would never resume without the sampler. launchd's job must be loaded (the uid is read, never hard-coded)."""
    if sys.platform != "darwin":
        return True
    try:
        return subprocess.run(["launchctl", "print", f"gui/{my_uid}/{LABEL}"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _entry_id(now):
    return "f-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now)) + "-" + secrets.token_hex(2)


def freeze(state_dir, pid, *, start, bundle_id=None, bundle_path=None, minutes=None, by="cli", ops=None, cfg=None, now=None,
           agent_clis=DEFAULT_AGENT_CLIS, check_sampler=True, lock_timeout=None, passes=None):
    """Freeze the app rooted at `pid` (SIGSTOP its whole tree). `minutes` None is an indefinite freeze. Returns the `frozen` entry. Raises Refusal;
    when a signal fails midway everything already stopped is resumed first."""
    ops = ops or Ops()
    cfg = cfg or gh.load_config()
    fz = cfg.get("freeze", {})
    if not fz.get("enabled", True):
        raise Refusal(DISABLED, "freeze is disabled ([freeze] enabled = false in config/gui-hog.toml)")
    if by not in BY:
        raise Refusal(USAGE, f"bad --by {by!r}")
    if start is None or not str(start).strip():
        raise Refusal(USAGE, "--start is required")
    if minutes is not None and not (type(minutes) is int and 1 <= minutes <= int(fz.get("max_minutes", 1440))):
        raise Refusal(USAGE, f"--minutes must be 1..{fz.get('max_minutes', 1440)}")
    if check_sampler and not sampler_loaded(ops.my_uid):
        raise Refusal(SAMPLER, f"the load-watch sampler ({LABEL}) is not loaded: a timed freeze would never resume")
    now = time.time() if now is None else now
    dfd = open_state(state_dir, create=True)
    try:
        with Lock(dfd, float(lock_timeout if lock_timeout is not None else fz.get("lock_timeout_s", 5))):
            entries, notes = load_entries(dfd)
            for e in entries:
                if e["root"]["pid"] == pid:
                    raise Refusal(REFUSED, f"pid {pid} already has an entry ({e['id']}, {e['state']})")
            try:
                v = vet_app(pid, ops, cfg, state_dir, start=start, bundle_id=bundle_id, bundle_path=bundle_path, now=now, agent_clis=agent_clis)
            except (Refusal, OSError) as r:
                if isinstance(r, OSError):
                    r = Refusal(REFUSED, f"cannot read the process table or identity: {r.strerror or r}")
                event(dfd, "refuse", by, now=now, pid=pid, code=r.code, why=r.msg)
                raise r
            return _freeze_locked(dfd, entries, v, ops, cfg, state_dir, by, now, minutes, agent_clis,
                                  int(passes if passes is not None else fz.get("passes", 3)), bundle_id, bundle_path)
    finally:
        os.close(dfd)


def _freeze_locked(dfd, entries, v, ops, cfg, state_dir, by, now, minutes, agent_clis, passes, bundle_id, bundle_path):
    root = v["root"]
    todo = [m for m in v["members"] if not m.get("stopped")]
    entry = {"id": _entry_id(now), "state": "freezing", "app": v["app"], "root": root,
             "members": [{k: m[k] for k in ("pid", "start", "uid", "exe")} for m in todo],
             "mode": "timed" if minutes else "indefinite", "frozen_at": now, "thaw_at": now + minutes * 60 if minutes else None,
             "by": by, "updated": now}
    if v.get("kept"):
        entry["kept"] = list(v["kept"])   # the keep-running rule's processes (CodexBar's HTTP server): never stopped, shown in the dialog
    entries.append(entry)
    save_entries(dfd, entries)   # F2: the write-ahead record names everything we are about to stop, BEFORE the first SIGSTOP
    try:
        stopped_root = _stop(dfd, ops, entry, [root], by, now, is_root=True)
        if not stopped_root:
            raise Refusal(IDENTITY, f"the root pid {root['pid']} changed before it could be stopped")
        _stop(dfd, ops, entry, list(entry["members"]), by, now)
        known = {root["pid"]} | {m["pid"] for m in entry["members"]}
        for i in range(passes + 1):   # F4d: rescan; a helper forked between passes is caught by the next one
            again = vet_app(root["pid"], ops, cfg, state_dir, start=root["start"], bundle_id=bundle_id, bundle_path=bundle_path, now=now,
                            agent_clis=agent_clis, allow_stopped_root=True)["members"]   # the whole vet again: a protected newcomer or a build refuses
            new = [m for m in again if m["pid"] not in known and not m.get("stopped")]
            if not new:
                break
            if i == passes:
                entry["kept_running"] = len(new)
                event(dfd, "late-helpers", by, now=now, entry=entry["id"], pids=[m["pid"] for m in new][:50])
                break
            known |= {m["pid"] for m in new}
            entry["members"].extend({k: m[k] for k in ("pid", "start", "uid", "exe")} for m in new)
            save_entries(dfd, entries)   # recorded before they are stopped
            _stop(dfd, ops, entry, [{k: m[k] for k in ("pid", "start", "uid", "exe")} for m in new], by, now)
        entry["state"], entry["updated"] = "frozen", now
        save_entries(dfd, entries)
    except Exception as e:  # noqa: BLE001 - roll back: nothing we stopped stays stopped without a record, and nothing is left half-frozen
        try:
            _resume(dfd, entries, entry, ops, by, now)
        except Exception:  # noqa: BLE001 - the `thawing` record stays; the next thaw_due finishes it
            pass
        if isinstance(e, Refusal):
            event(dfd, "refuse", by, now=now, pid=root["pid"], code=e.code, why=e.msg)
            raise
        event(dfd, "refuse", by, now=now, pid=root["pid"], code=REFUSED, why=f"{type(e).__name__}: {e}")
        raise Refusal(REFUSED, f"freeze failed and was rolled back: {type(e).__name__}: {e}") from e
    event(dfd, "freeze", by, now=now, entry=entry["id"], app=entry["app"], mode=entry["mode"], thaw_at=entry["thaw_at"],
          root=root["pid"], members=len(entry["members"]), kept_running=entry.get("kept_running", 0), kept=entry.get("kept", []))
    return entry


def _stop(dfd, ops, entry, recs, by, now, is_root=False):
    """SIGSTOP each record after its identity check. A process that is gone or changed is dropped from the entry (never signalled); EPERM
    raises. Returns True when the (single) root record was stopped."""
    ok = False
    for rec in recs:
        res = _signal_one(ops, rec, signal.SIGSTOP)
        if res == "sent":
            ok = True
        elif not is_root:
            entry["members"] = [m for m in entry["members"] if m["pid"] != rec["pid"]]
            event(dfd, "drop", by, now=now, entry=entry["id"], pid=rec["pid"], why=res)
    return ok


# ---- the auto-freeze list (operator ruling 2026-11-21: B6 amended) ---------------------------------------------------------------
AUTO_RETRY_S = 120   # after a refused auto-freeze the same app is not retried for this long (a hosted build or a protected newcomer may clear)


def auto_candidates(apps, cfg, auto_state, now):
    """[(app_record, why_not)] for the bundle ids of `[freeze.auto] order`, preferred first. The app is the first running record of that bundle id;
    `why_not` is "" when it may be auto-frozen now, else the reason it is skipped: not-running, protected, excluded (part of a build), hosts-build,
    never-auto (on `[freeze.auto] skip`), cooling-down (frozen by us within refreeze_s: an operator's Resume sticks), retry-wait, or idle (its freeable cores, those of the processes a
    freeze would stop, are under `min_cores`: a freeze would free nothing). `[protected]` and the hard floor always win: a protected app is never a candidate."""
    au = cfg["freeze"]["auto"]
    out = []
    skip = {str(x).casefold() for x in au.get("skip", []) if isinstance(x, str)}
    for bid in au.get("order", []):
        if bid.casefold() in skip:   # operator ruling 2026-11-21: not worth suspending (P7); wins over `order`
            out.append(({"bundle_id": bid}, "never-auto"))
            continue
        a = next((x for x in apps if x.get("bundle_id") and str(x["bundle_id"]).casefold() == bid.casefold()), None)
        if a is None:
            out.append(({"bundle_id": bid}, "not-running"))
            continue
        st = auto_state.get(bid.casefold()) if isinstance(auto_state.get(bid.casefold()), dict) else None
        free = a["cores"] - a.get("kept_cores", 0.0)
        if a["protected"]:
            why = "protected"
        elif a["excluded"]:
            why = "excluded"
        elif a["hosts_build"]:
            why = "hosts-build"
        elif st and gh._fin(st.get("t")) and 0 <= now - st["t"] < (float(au.get("refreeze_s", 3600)) if st.get("ok") else AUTO_RETRY_S):
            why = "cooling-down" if st.get("ok") else "retry-wait"
        elif free < float(au.get("min_cores", 0.05)):
            why = "idle"
        else:
            why = ""
        out.append((a, why))
    return out


def auto_freeze_step(gh_state, state_dir, apps, held, now, cfg, *, my_uid, agent_clis=(), ops=None, dry=False, freeze_fn=None, starts=None, snoozed=False):
    """One sampler tick of the auto-freeze list: while a build is held by the GUI-hog trigger (`hold_active`: refused for hold_s on a gate desktop apps
    can relieve), freeze the FIRST app of `[freeze.auto] order` that is running, not protected, not part of a build, not frozen by us within refreeze_s
    and using at least min_cores. One app per tick, so the build's next admission poll can see the relief and the list stops there; it ends when the
    hold goes (no held build) or no listed app is left. Timed, like a click (`by` is "auto"; every thaw path is the same). Returns None when nothing
    was due, else {"app", "bundle_id", "entry" | "refused", "dry"}. Needs `[freeze] enabled`, `[freeze.auto] enabled` and a non-empty order.
    `snoozed` (the dialog's "Ignore 1 h" is active) pauses it too: an operator who ignored the warning wants their apps left alone (adversary L1).
    `starts` {pid: start string} is what the sampler read with the same table that chose the app (adversary L3): a relaunched app has another start,
    so `freeze()` refuses it; without an entry for a pid the start is read from `ops.info` just before the call. The sampler must be loaded: a
    timed auto-freeze made by a `load-watch sample` that launchd's job does not follow would never thaw (adversary M1: `check_sampler=True`)."""
    fz = cfg["freeze"]
    au = fz["auto"]
    if not fz.get("enabled", True) or not au.get("enabled", True) or not au.get("order"):
        return None
    if snoozed or not gh.hold_active(held, now, cfg)[1]:
        return None
    auto_state = gh_state.get("auto") if isinstance(gh_state.get("auto"), dict) else {}
    gh_state["auto"] = auto_state
    for a, why in auto_candidates(apps, cfg, auto_state, now):
        if why:
            continue
        res = {"app": a["name"], "bundle_id": a["bundle_id"], "dry": bool(dry)}
        if dry:
            return res
        ops = ops or Ops(my_uid)
        minutes = au.get("minutes") or fz.get("default_minutes", 10)
        key = a["bundle_id"].casefold()
        try:
            root = int(a["root_pid"])
            start = (starts or {}).get(root)
            if start is None:
                inf = ops.info([root]).get(root)
                if inf is None:
                    raise Refusal(IDENTITY, "gone")
                start = inf["start"]
            e = (freeze_fn or freeze)(state_dir, root, start=start, bundle_id=a["bundle_id"], bundle_path=a["bundle_path"],
                                      minutes=int(minutes), by="auto", ops=ops, cfg=cfg, now=now, agent_clis=agent_clis, check_sampler=True)
            auto_state[key] = {"t": now, "ok": True}
            res.update(entry=e["id"], thaw_at=e["thaw_at"], kept=e.get("kept", []))
        except Refusal as r:
            auto_state[key] = {"t": now, "ok": False}
            res["refused"] = f"{r.code}: {r.msg}"[:160]
        except OSError as r:   # a ps timeout or an unreadable state dir: recorded like a refusal, so it is retried after AUTO_RETRY_S, not every tick (adversary L5)
            auto_state[key] = {"t": now, "ok": False}
            res["refused"] = f"error: {type(r).__name__}: {r}"[:160]
        return res
    return None


# ---- thaw paths (F5, F7) ----------------------------------------------------------------------------------------------------------
def _locked(state_dir, fn, create=False, lock_timeout=5.0):
    dfd = open_state(state_dir, create=create)
    if dfd is None:
        return None
    try:
        with Lock(dfd, lock_timeout):
            entries, notes = load_entries(dfd)
            return fn(dfd, entries, notes)
    finally:
        os.close(dfd)


def thaw_due(state_dir, *, ops=None, now=None, by="sampler", dry=False, budget_s=30.0, lock_timeout=5.0, out=print):
    """F5a, b, d, e: resume every entry whose timed freeze is due and every `freezing`/`thawing` one (an orphan: its operation holds the lock, so a
    live one is never seen here), and prune entries whose processes are gone or no longer match (a reboot, logout or app exit). Bounded: every
    identity read has a timeout and the pass has `budget_s` in total; what is left waits for the next tick and is never signalled
    without a completed identity check. Returns {"resumed": [ids], "dropped": [ids], "deferred": n}; with `dry` it only reports."""
    ops = ops or Ops()
    now = time.time() if now is None else now
    deadline = time.monotonic() + budget_s
    res = {"resumed": [], "dropped": [], "deferred": 0}

    def work(dfd, entries, notes):
        changed = False
        for entry in list(entries):
            if time.monotonic() > deadline:
                res["deferred"] += 1
                continue
            # a `frozen_at` in the future is a wrong clock or a hand edit: the safe direction is to resume now
            due = (entry["state"] in ("freezing", "thawing") or entry["frozen_at"] > now + 300
                   or (entry["mode"] == "timed" and now >= (entry["thaw_at"] if entry["thaw_at"] is not None else 0)))
            if due:
                if dry:
                    out(f"gui-hog would resume {entry['id']} ({entry['app']['name']})")
                    res["resumed"].append(entry["id"])
                    continue
                done, _ = _resume(dfd, entries, entry, ops, by, now, deadline)
                if done:
                    res["resumed"].append(entry["id"])
                else:
                    res["deferred"] += 1
                continue
            try:
                infos = ops.info([entry["root"]["pid"]] + [m["pid"] for m in entry["members"]])
            except OSError:
                res["deferred"] += 1
                continue
            if mismatch(entry["root"], infos.get(entry["root"]["pid"]), ops.my_uid, need_exe=False):
                # the root exited (a Force Quit reaches a stopped process) or the machine rebooted: the helpers may still be stopped, so the
                # entry is RESUMED (every member that is still the recorded process gets SIGCONT), not just deleted
                if dry:
                    res["dropped"].append(entry["id"])
                    continue
                done, notes_ = _resume(dfd, entries, entry, ops, by, now, deadline)
                if not done:
                    res["deferred"] += 1
                elif any(n.endswith(":sent") or n.endswith(":sent-exe-changed") for n in notes_):
                    res["resumed"].append(entry["id"])
                else:
                    res["dropped"].append(entry["id"])
                continue
            keep = [m for m in entry["members"] if not mismatch(m, infos.get(m["pid"]), ops.my_uid, need_exe=False)]
            if len(keep) != len(entry["members"]) and not dry:
                entry["members"] = keep
                changed = True
        if changed:
            save_entries(dfd, entries)
        return res

    r = _locked(state_dir, work, create=False, lock_timeout=lock_timeout)
    return res if r is None else r


def thaw_all(state_dir, *, ops=None, now=None, by="cli", entry_id=None, budget_s=60.0, lock_timeout=5.0):
    """F7a, F5f: resume every recorded entry (or the one `entry_id`) after the identity checks. Returns (resumed ids, unfinished ids)."""
    ops = ops or Ops()
    now = time.time() if now is None else now
    deadline = time.monotonic() + budget_s

    def work(dfd, entries, notes):
        done, left = [], []
        for entry in list(entries):
            if entry_id is not None and entry["id"] != entry_id:
                continue
            ok, _ = _resume(dfd, entries, entry, ops, by, now, deadline)
            (done if ok else left).append(entry["id"])
        if entry_id is not None and not done and not left:
            raise Refusal(REFUSED, f"no entry {entry_id!r}")
        return done, left

    r = _locked(state_dir, work, create=False, lock_timeout=lock_timeout)
    return ([], []) if r is None else r


def stopped_apps(ops):
    """F7c: processes of this user in state T whose executable sits inside an .app bundle, or has no readable path at all (a bundle replaced or moved
    while the app was frozen): [{pid, start, uid, exe, state}]."""
    table, _rss, _tty, states = ops.table()
    mine = _ancestors(table, os.getpid()) | {os.getpid()}
    cand = [int(p) for p, st in states.items() if st.startswith("T") and table[p][1] == ops.my_uid and int(p) not in mine and _pid_ok(int(p))]
    out = []
    for p, inf in ops.info(cand).items():
        if inf["uid"] == ops.my_uid and is_stopped(inf) and (not inf["exe"] or gh._app_prefix(inf["exe"])):   # no readable path: its bundle was replaced or moved
            out.append({"pid": p, "start": inf["start"], "uid": inf["uid"], "exe": inf["exe"], "state": inf["state"]})
    return sorted(out, key=lambda r: r["pid"])


def thaw_stopped_apps(ops, recs):
    """SIGCONT the listed processes after the same identity check. Returns the pids resumed."""
    sent = []
    for rec in recs:
        try:
            if _signal_one(ops, rec, signal.SIGCONT) in ("sent", "sent-exe-changed"):
                sent.append(rec["pid"])
        except OSError:
            pass
    return sent


def frozen_view(state_dir, ops=None, now=None):
    """What `gui-hog frozen` prints and the menu-bar item reads: {"entries": [...], "notes": [...]}; each entry with its member count and whether
    its root is still the recorded process."""
    now = time.time() if now is None else now
    dfd = open_state(state_dir, create=False)
    if dfd is None:
        return {"v": 1, "entries": [], "notes": []}
    try:
        entries, notes = load_entries(dfd)
    finally:
        os.close(dfd)
    ops = ops or Ops()
    try:
        infos = ops.info([e["root"]["pid"] for e in entries])
    except OSError:
        infos = {}
    out = []
    for e in entries:
        out.append({"id": e["id"], "state": e["state"], "app": e["app"], "mode": e["mode"], "by": e["by"], "frozen_at": e["frozen_at"],
                    "thaw_at": e["thaw_at"], "root_pid": e["root"]["pid"], "members": len(e["members"]) + 1,
                    "alive": mismatch(e["root"], infos.get(e["root"]["pid"]), ops.my_uid, need_exe=False) is None, "kept_running": e.get("kept_running", 0),
                    "kept": e.get("kept", [])})
    return {"v": 1, "entries": out, "notes": notes}


def has_entries(state_dir):
    """True when frozen.json (or its .prev) holds at least one valid entry. Never raises: an unreadable state reads as False (thaw_due reports it)."""
    try:
        dfd = open_state(state_dir, create=False)
        if dfd is None:
            return False
        try:
            return bool(load_entries(dfd)[0])
        finally:
            os.close(dfd)
    except (Refusal, OSError):
        return False


def ensure_status_item(state_dir, *, popen=None, gui_ok=True, bundle=None):
    """The menu-bar item of E5: while something is frozen, keep `ADE GUI Hog.app --status-only` running (one instance, its own flock
    gui-hog/status.lock). Called by the sampler after `thaw_due`. Returns (started, why); never raises, never waits, never builds the bundle
    (C5, D2). The item shows what is frozen and offers Resume; it exits by itself when nothing is frozen."""
    try:
        if not gui_ok or not has_entries(state_dir):
            return False, "nothing-frozen" if gui_ok else "no-gui"
        kw = {"popen": popen} if popen is not None else {}
        return gh.launch_dialog(state_dir, bundle=bundle, extra=("--status-only",), lock="status.lock", **kw)
    except Exception as e:  # noqa: BLE001 - a failed launch is a log line, never a failed sample
        return False, f"error: {e!r}"[:120]


# ---- the CLI (called from bin/gui-hog) -----------------------------------------------------------------------------------------------
def add_subcommands(sub):
    p = sub.add_parser("freeze", help="SIGSTOP an app's whole process tree (an operator click, or the sampler for an app on the [freeze.auto] list)")
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--start", required=True, help="expected start time of the pid (the snapshot's value); a mismatch refuses")
    p.add_argument("--bundle-id", default=None, help="expected bundle id (the live one decides)")
    p.add_argument("--bundle-path", default=None, help="expected bundle path (the live one decides)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--minutes", type=int, default=None, help="timed freeze (default: [freeze] default_minutes)")
    g.add_argument("--indefinite", action="store_true")
    p.add_argument("--by", choices=BY, default="cli")
    p.set_defaults(func=_guard(cmd_freeze))
    p = sub.add_parser("resume", help="resume one frozen entry, or all")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--entry")
    g.add_argument("--all", action="store_true")
    p.add_argument("--by", choices=BY, default="cli")
    p.set_defaults(func=_guard(cmd_resume))
    p = sub.add_parser("thaw", help="--due (sampler tick), --all (escape hatch), --all --stopped-apps (lost state file)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--due", action="store_true")
    g.add_argument("--all", action="store_true")
    p.add_argument("--stale", action="store_true", help="accepted with --due: orphaned freezing/thawing entries are always resumed")
    p.add_argument("--stopped-apps", action="store_true", help="with --all: every stopped app process of this user, after a `yes`")
    p.add_argument("--yes", action="store_true", help="with --stopped-apps: do not ask")
    p.add_argument("--by", choices=BY, default="cli")
    p.set_defaults(func=_guard(cmd_thaw))
    p = sub.add_parser("frozen", help="list the frozen entries")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_guard(cmd_frozen))


class Terminated(Exception):
    """SIGTERM reached `gui-hog freeze` (the dialog gave up waiting): raised as an ordinary exception so the freeze rolls back what it stopped."""


def _on_term(signum, frame):
    raise Terminated("terminated")


def _guard(fn):
    """Any OSError (a full or read-only disk, a vanished directory) is a refusal with exit 9 and a one-line reason, never a traceback."""
    def run(a, state_dir):
        try:
            return fn(a, state_dir)
        except OSError as e:
            return _fail(Refusal(REFUSED, f"{e.strerror or type(e).__name__}"), as_json=getattr(a, "json", True))
    run.__name__ = fn.__name__
    return run


def _fail(r, as_json=True):
    print(json.dumps({"ok": False, "code": r.code, "reason": r.msg}) if as_json else f"gui-hog: {r.msg}", file=sys.stdout if as_json else sys.stderr)
    return r.code


def cmd_freeze(a, state_dir):
    cfg = gh.load_config()
    mins = None if a.indefinite else (a.minutes if a.minutes is not None else int(cfg["freeze"].get("default_minutes", 10)))
    signal.signal(signal.SIGTERM, _on_term)   # A6: a SIGTERM mid-freeze rolls back (the entry is resumed) instead of leaving the app stopped
    try:
        e = freeze(state_dir, a.pid, start=a.start, bundle_id=a.bundle_id, bundle_path=a.bundle_path, minutes=mins, by=a.by, cfg=cfg)
    except Refusal as r:
        return _fail(r)
    except Terminated:
        return _fail(Refusal(REFUSED, "interrupted; anything stopped was resumed"))
    # The freeze starts its own clock (H4 run 2026-11-14: a dialog opened by hand and a sampler without the thaw tick left a timed freeze stopped for
    # good): the menu-bar item runs `thaw --due` every 20 s whoever opened the dialog and whatever load-watch is loaded. Never raises, never fails the freeze.
    try:
        _started, why = ensure_status_item(state_dir, gui_ok=gh.gui_session(os.getuid()))
    except Exception as ex:  # noqa: BLE001 - the app is already stopped and recorded; the exit code must say so
        why = f"error: {ex!r}"[:120]
    print(json.dumps({"ok": True, "entry": e["id"], "state": e["state"], "mode": e["mode"], "thaw_at": e["thaw_at"], "members": len(e["members"]) + 1,
                      "kept_running": e.get("kept_running", 0), "kept": e.get("kept", []), "status_item": why}))
    return OK


def cmd_resume(a, state_dir):
    try:
        done, left = thaw_all(state_dir, by=a.by, entry_id=a.entry if not a.all else None)
    except Refusal as r:
        return _fail(r)
    print(json.dumps({"ok": not left, "resumed": done, "unfinished": left}))
    return OK if not left else REFUSED


def cmd_thaw(a, state_dir):
    try:
        if a.due:
            r = thaw_due(state_dir, by=a.by if a.by != "cli" else "sampler")
            print(json.dumps({"ok": True, **r}))
            return OK
        if a.stopped_apps:
            ops = Ops()
            recs = stopped_apps(ops)
            for r in recs:
                print(f"stopped: pid {r['pid']} {r['exe']}")
            if not recs:
                print(json.dumps({"ok": True, "resumed": []}))
                return OK
            if not a.yes and (not sys.stdin.isatty() or input("Resume all of these? Type yes: ").strip() != "yes"):
                print("gui-hog: not confirmed; nothing sent", file=sys.stderr)
                return REFUSED
            print(json.dumps({"ok": True, "resumed": thaw_stopped_apps(ops, recs)}))
            return OK
        done, left = thaw_all(state_dir, by=a.by)
    except Refusal as r:
        return _fail(r)
    print(json.dumps({"ok": not left, "resumed": done, "unfinished": left}))
    return OK if not left else REFUSED


def cmd_frozen(a, state_dir):
    try:
        v = frozen_view(state_dir)
    except Refusal as r:
        return _fail(r, as_json=a.json)
    if a.json:
        print(json.dumps(v))
        return OK
    if not v["entries"]:
        print("nothing is frozen")
    for e in v["entries"]:
        until = "resumes at " + clock_text(e["thaw_at"], time.time()) if e["thaw_at"] is not None else "until you Resume"
        print(f"{e['id']}  {e['app']['name'] or '?'}  [{e['state']}] {until}  {e['members']} processes, root pid {e['root_pid']}"
              + ("" if e["alive"] else "  (root is gone: its helpers are resumed at the next tick)") + f"  by {e['by']}")
    for n in v["notes"]:
        print(f"note: {n}", file=sys.stderr)
    return OK
