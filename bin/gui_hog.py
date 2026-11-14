"""gui_hog: the data and the trigger of the GUI-hog dialog (docs/gui-hog-dialog.md, PR 3a: dry-run only, no window).

Stdlib only; it never imports `load-watch` (a broken sampler must not be able to break it, and PR 3c's thaw path will
live here). `load-watch` imports it lazily, inside a `try`, in two places: `admit --wait` writes the hold registry
(C2) and the 20 s sampler calls `tick` (C3, C4, C5). Nothing here signals, quits or freezes anything.

    hold_write / hold_remove / read_holds     ~/.local/state/load-watch/held/<pid>-<start>.json: who waits on `admit` now (C2)
    parse_lsappinfo / group_apps              GUI apps from `lsappinfo list`, with their process trees (C3, C4b)
    should_show(held, apps, now, snooze, last_shown, cfg)   the one pure decision function (C4)
    tick                                      the sampler's whole step: window, decision, dry-run line (K1)
    status_lines                              `bin/gui-hog status`

Untrusted text (J3): an app sets its own name and bundle id, `admit_caller` is a program name: `clean` strips control,
bidi, zero-width and line-separator characters and clips before anything is logged. Identity and protection never use
a display name: bundle id, bundle path and executable realpath only.
"""
import ctypes
import json
import os
import plistlib
import re
import stat
import subprocess
import sys
import tempfile
import calendar
import time
import unicodedata
from pathlib import Path

ADE = Path(__file__).resolve().parent.parent
HOME = Path.home()
DEFAULT_CONFIG = ADE / "config" / "gui-hog.toml"
LOCAL_CONFIG = Path(os.environ.get("LW_GUI_HOG_LOCAL", HOME / ".config/load-watch/gui-hog.toml"))
DIALOG_BUNDLE_ID = "com.djbclark.ade.gui-hog"
HOLD_AGE_CAP_S = 3600.0   # = load-watch's STARVE_REFUSED_SINCE_MAX_S default: a hold is never credited with more than this
HOLD_STALE_S = 60.0       # a hold file not refreshed for this long is stale (widened by the waiter's own poll interval)
DRY_RUN_MAX_BYTES = 1024 * 1024

DEFAULTS = {
    "trigger": {"hold_s": 180, "min_cores": 0.75, "min_rss_mb": 2048, "rate_s": 1800, "snooze_s": 3600, "window_s": 300,
                "min_row_cores": 0.05, "min_row_rss_mb": 200,
                "relievable": ["load", "compressor", "free_mem", "pageins", "swapins"]},
    "protected": {"bundle_ids": [], "bundle_id_prefixes": [], "bundle_paths": [], "exe_paths": []},
}

# The hard floor (F6): code, not configuration. Config can add protected entries, never remove these.
HARD_BUNDLE_IDS = frozenset({"com.apple.dock", "com.apple.loginwindow", "com.apple.finder", "com.apple.systemuiserver",
                             "com.apple.controlcenter", "com.apple.windowmanager", "com.apple.windowserver",
                             DIALOG_BUNDLE_ID.lower()})
HARD_PATH_PREFIXES = ("/System", "/usr")
HARD_EXE_NAMES = frozenset({"windowserver", "loginwindow", "dock", "finder", "ade-gui-hog"})   # real executables; load-watch and bg are scripts, matched by argv in group_apps
SHELLS = frozenset({"bash", "zsh", "sh", "dash", "fish", "ksh", "tcsh", "csh", "login"})
GUI_TYPES = ("Foreground", "UIElement")


# ---- untrusted text (J3) -----------------------------------------------------------------------------------------
_DROP_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})   # controls, ALL format characters (bidi, zero-width, TAG, soft hyphen), surrogates, private, unassigned, line/paragraph separators
_FILLERS = frozenset("\u034f\u115f\u1160\u3164\uffa0")   # invisible, but not in a dropped category


def _markish(ch):
    return unicodedata.category(ch).startswith("M") or "︀" <= ch <= "️" or "\U0001f3fb" <= ch <= "\U0001f3ff"


def clean(text, limit=60):
    """`text` as one line of plain, printable text: every control (Cc), format (Cf: bidi marks and overrides, zero-width, TAG, soft hyphen),
    surrogate, private-use and unassigned character, line and paragraph separator and invisible filler removed, then clipped to `limit` characters. The cut backs off any combining mark, so it
    never leaves half of a cluster (an approximation of a grapheme-cluster cut: ZWJ is removed, so a ZWJ emoji
    sequence degrades to its parts)."""
    s = "".join(ch for ch in str(text) if unicodedata.category(ch) not in _DROP_CATEGORIES and ch not in _FILLERS)
    if len(s) <= limit:
        return s
    cut = limit
    while cut > 0 and _markish(s[cut]):
        cut -= 1
    return s[:cut] + "…"


# ---- config ------------------------------------------------------------------------------------------------------
def _read_toml(path):
    import tomllib
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_config(path=None, local=None):
    """Defaults, then config/gui-hog.toml, then the local file's protected lists (it can only ADD to them). Raises on a broken
    shipped file; a broken local file is ignored (it can only add)."""
    cfg = json.loads(json.dumps(DEFAULTS))
    data = _read_toml(path or DEFAULT_CONFIG) if (path or DEFAULT_CONFIG).exists() else {}
    for sec, vals in data.items():
        if sec in cfg and isinstance(vals, dict):
            cfg[sec].update(vals)
    loc = local if local is not None else LOCAL_CONFIG
    try:
        extra = _read_toml(loc).get("protected", {}) if loc.exists() else {}
    except Exception:  # noqa: BLE001 - local additions are optional
        extra = {}
    for key in cfg["protected"]:
        add = extra.get(key, []) if isinstance(extra, dict) else []
        if isinstance(add, list):
            cfg["protected"][key] = list(cfg["protected"][key]) + [x for x in add if isinstance(x, str)]
    return cfg


def _under(path, prefix):
    """True when `path` is `prefix` or inside it, by path components (so /A/Ghostty.app does not match /A/Ghostty.app.x/)."""
    a, b = Path(str(path).casefold()).parts, Path(str(prefix).casefold()).parts
    return bool(b) and a[:len(b)] == b


def _real(path):
    try:
        return os.path.realpath(path)
    except (OSError, ValueError):
        return str(path)


def protect_reason(bundle_id, bundle_real, exe_real, uid, my_uid, cfg):
    """Why an app may never be a dialog row, or None. Uses live values only (never a display name): the hard floor first
    (F6a-c), then the configured bundle ids, id prefixes, bundle paths and executable paths. An app that CLAIMS a protected bundle id is
    protected: the safe direction (J3)."""
    bid = (bundle_id or "").casefold()
    if uid != my_uid:
        return "hard:uid"
    if bid in HARD_BUNDLE_IDS:
        return "hard:bundle-id"
    for p in HARD_PATH_PREFIXES:
        if (bundle_real and _under(bundle_real, p)) or (exe_real and _under(exe_real, p)):
            return "hard:system-path"
    if exe_real and os.path.basename(exe_real).casefold() in HARD_EXE_NAMES:
        return "hard:exe"
    pr = cfg.get("protected", {})
    if bid and any(bid == str(x).casefold() for x in pr.get("bundle_ids", [])):
        return "cfg:bundle-id"
    if bid and any(bid.startswith(str(x).casefold()) for x in pr.get("bundle_id_prefixes", []) if x):
        return "cfg:bundle-id-prefix"
    if bundle_real and any(_under(bundle_real, _real(x)) for x in pr.get("bundle_paths", [])):
        return "cfg:bundle-path"
    if exe_real and any(_under(exe_real, _real(x)) for x in pr.get("bundle_paths", [])):
        return "cfg:bundle-path"
    if exe_real and any(_under(exe_real, _real(x)) for x in pr.get("exe_paths", [])):
        return "cfg:exe"
    return None


# ---- process identity ----------------------------------------------------------------------------------------------
_libproc = None


def kernel_exe(pid):
    """The executable path the kernel reports for `pid` (never argv[0]): proc_pidpath on macOS, /proc/PID/exe on Linux. None
    when the process is gone or unreadable."""
    try:
        if sys.platform == "darwin":
            global _libproc
            if _libproc is None:
                _libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
            buf = ctypes.create_string_buffer(4096)
            n = _libproc.proc_pidpath(int(pid), buf, 4096)
            return os.fsdecode(buf.value) if n > 0 else None
        return os.readlink(f"/proc/{int(pid)}/exe")
    except (OSError, ValueError, AttributeError):
        return None


def proc_start(pid):
    """A start-time string for `pid` that is stable for the life of the process (`ps -o lstart=` under LC_ALL=C TZ=UTC on macOS;
    /proc/PID/stat starttime on Linux), or None when it is gone or unreadable."""
    try:
        pid = int(pid)
        if os.path.isdir("/proc/self"):
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            return "proc:" + fields[19]
        env = dict(os.environ, LC_ALL="C", TZ="UTC")
        r = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=2, env=env)
        out = " ".join(r.stdout.split())
        return out if r.returncode == 0 and out else None
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except (OSError, ValueError, OverflowError):
        return False


def read_small(path, cap=65536):
    """Text of a small regular file, never following a symlink and never blocking on a FIFO (the state directory is data, not trusted). Raises
    OSError for anything else: a FIFO, a device, a symlink, a directory, a file over `cap` bytes."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > cap:
            raise OSError("not a small regular file")
        data = os.read(fd, cap + 1)
    finally:
        os.close(fd)
    if len(data) > cap:
        raise OSError("file grew past the cap")
    return data.decode("utf-8", "replace")


def safe_dir(path):
    """True when `path` is a real directory (not a symlink) owned by this user: a state directory somebody else could redirect is not used."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()


# ---- the hold registry (C2) ----------------------------------------------------------------------------------------
def held_dir(state_dir):
    return Path(state_dir) / "held"


def _slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "-", str(text)).strip("-")[:48]


_HOLD_NAME = re.compile(r"[0-9]+-[A-Za-z0-9-]*\.json\Z")


def hold_write(state_dir, pid, start, caller, refused_since, refused, now, poll_s=15.0, caller_pid=None):
    """Write (atomically) this waiting `admit`'s hold file and return its path. `refused_since` is the epoch the unbroken run of
    refusals began; the caller has already passed it through parse_refused_since. Raises on an OS error: the caller
    wraps it, because the registry must never change admit's verdict or exit code."""
    d = held_dir(state_dir)
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not safe_dir(d):
        raise OSError(f"{d} is not a real directory of this user")
    rec = {"v": 1, "pid": int(pid), "start": start or "", "caller": clean(caller or "", 80), "refused_since": int(refused_since),
           "refused": [clean(x, 40) for x in refused][:12], "updated": int(now), "poll_s": min(600, max(1, int(poll_s)))}
    if caller_pid:
        rec["caller_pid"] = int(caller_pid)
    path = d / f"{int(pid)}-{_slug(start or 'unknown')}.json"
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".hold-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(rec, f, separators=(",", ":"))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def hold_remove(path):
    try:
        if path:
            os.unlink(path)
    except OSError:
        pass


def read_holds(state_dir, now, sweep=True, start_of=proc_start, cap=HOLD_AGE_CAP_S, check_start=True):
    """The live holds. A file is stale (and swept when `sweep`) when its `updated` is more than max(60 s, 2 polls + 15 s) old or in the future,
    or, when `check_start`, its pid is gone or now has another start time (pid reuse; a start time that cannot be read, such as a `ps` timeout
    under load, counts as stale only when the pid is dead). Only files named `<digits>-<slug>.json` are looked at, and never deleted otherwise;
    the directory must be a real directory of this user; each file is read as a small regular file (no symlink, no FIFO, 64 KB cap); a file that
    does not parse or has wrong types is skipped (and swept when older than 2 min by mtime). `refused_since` is clamped to [now - cap, now]:
    a future or non-integer value counts as `now`."""
    d = held_dir(state_dir)
    out = []
    if not safe_dir(d):
        return out
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for name in names:
        if not _HOLD_NAME.match(name):
            continue
        p = d / name
        try:
            rec = json.loads(read_small(p))
            pid, upd, poll = rec["pid"], rec["updated"], rec.get("poll_s", 15)
            ok = (rec.get("v") == 1 and type(pid) is int and 0 < pid < 2 ** 31 and _fin(upd) and _fin(poll)
                  and isinstance(rec.get("start", ""), str) and isinstance(rec.get("refused", []), list))
            if not ok:
                raise ValueError("shape")
        except Exception:  # noqa: BLE001 - the directory is data: any failure to read or parse one file is that file's problem
            try:
                if sweep and now - os.lstat(p).st_mtime > 120:
                    p.unlink()
            except OSError:
                pass
            continue
        stale = now - upd > max(HOLD_STALE_S, 2 * min(600, max(1, poll)) + 15) or upd > now + HOLD_STALE_S
        if not stale and check_start:
            rec_start = rec.get("start", "")
            cur = start_of(pid) if rec_start else None
            stale = (cur != rec_start) if cur is not None else not _alive(pid)
        if stale:
            if sweep:
                hold_remove(p)
            continue
        rs = rec.get("refused_since")
        since = min(max(rs, now - cap), now) if _fin(rs) else now
        cp = rec.get("caller_pid")
        out.append({"pid": pid, "start": rec.get("start", ""), "caller": clean(rec.get("caller", ""), 80), "refused_since": since,
                    "caller_pid": cp if type(cp) is int and 1 < cp < 2 ** 31 else None,
                    "refused": [clean(x, 40) for x in rec.get("refused", []) if isinstance(x, str)][:12], "updated": upd})
    return out


# ---- lsappinfo (C3) ------------------------------------------------------------------------------------------------
# `lsappinfo list` is a diagnostic tool, not an API (the design's closing note): the text format is parsed per entry
# against fixtures (tests/fixtures/gui_hog/), an unparseable entry is skipped, and an empty result sends `group_apps` to the
# kernel executable path's bundle instead. Entry shape (macOS 27, checked 2026-11-14):
#   3) "Ghostty" ASN:0x0-0x1f21f2:
#       bundleID="com.mitchellh.ghostty"            (or bundleID=[ NULL ] )
#       bundle path="/Applications/Ghostty.app"
#       executable path="/Applications/Ghostty.app/Contents/MacOS/ghostty"
#       pid = 52564 token=[sess=... uid:502,502,502 ...] type="Foreground" flavor=3 ...
_HEAD = re.compile(r'^\s*\d+\)\s+"(.*)"\s+ASN:\S*:?\s*$')


def parse_lsappinfo(text):
    """[{name, bundle_id, bundle_path, exe, pid, type}] from `lsappinfo list` text. Entries without a pid or a type are skipped."""
    out, cur = [], None

    def done():
        if cur and cur.get("pid") and cur.get("type"):
            out.append(cur)
    for line in str(text).splitlines():
        m = _HEAD.match(line)
        if m:
            done()
            cur = {"name": m.group(1), "bundle_id": None, "bundle_path": None, "exe": None, "pid": None, "type": None}
            continue
        if cur is None:
            continue
        s = line.strip()
        if s.startswith("bundleID="):
            m2 = re.match(r'bundleID="([^"]*)"', s)
            cur["bundle_id"] = m2.group(1) if m2 else None
        elif s.startswith("bundle path="):
            m2 = re.match(r'bundle path="([^"]*)"', s)
            cur["bundle_path"] = m2.group(1) if m2 else None
        elif s.startswith("executable path="):
            m2 = re.match(r'executable path="([^"]*)"', s)
            cur["exe"] = m2.group(1) if m2 else None
        elif s.startswith("pid ="):
            m2, m3 = re.match(r"pid\s*=\s*(\d+)", s), re.search(r'\btype="([^"]*)"', s)
            cur["pid"] = int(m2.group(1)) if m2 else None
            cur["type"] = m3.group(1) if m3 else None
    done()
    return out


def collect_lsappinfo(timeout=5):
    """`lsappinfo list` parsed, or [] when it is missing, fails, times out or prints nothing parseable."""
    try:
        r = subprocess.run(["lsappinfo", "list"], capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, LC_ALL="C"))
        return parse_lsappinfo(r.stdout) if r.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired):
        return []


class _App:
    """One app while its tree is walked."""

    def __init__(self, pid, root):
        self.id, self.root_pid = pid, int(pid)
        self.name, self.bundle_id, self.bundle_path, self.real = root["name"], root["bundle_id"], root["bundle_path"], root["real"]
        self.members = [pid]
        self.build = set()
        self.build_cores = 0.0


# ---- grouping (C3, C4b) --------------------------------------------------------------------------------------------
def _app_prefix(path):
    """The outermost `X.app` prefix of `path`, or None."""
    parts = Path(path).parts
    for i, comp in enumerate(parts):
        if comp.lower().endswith(".app") and len(comp) > 4:
            return str(Path(*parts[:i + 1]))
    return None


def _plist_id(bundle_path):
    try:
        with open(Path(bundle_path) / "Contents" / "Info.plist", "rb") as f:
            v = plistlib.load(f).get("CFBundleIdentifier")
        return v if isinstance(v, str) else None
    except Exception:  # noqa: BLE001 - optional metadata
        return None


def group_apps(table, rss_kb, ttys, lsapps, *, exe_of, my_uid, held_pids=(), agent_clis=(), cfg=None):
    """One record per GUI app: {id (root pid), name, bundle_id, bundle_path, root_pid, members, cores, rss_mb, hosts_build,
    build_cores, excluded, protected}. `table` is load-watch's ps table {pid: (ppid, uid, cores, command)}; `rss_kb` {pid: KB};
    `ttys` the pids with a controlling terminal; `exe_of(pid)` the kernel executable path (cached by the caller).

    An app is the process tree under a `Foreground` or `UIElement` lsappinfo entry that owns an `.app` bundle, plus any process whose
    executable lies inside that bundle (helpers launchd started). The walk down the tree STOPS at a shell, a pty-attached process, a
    held caller, `bg` or an agent CLI, or a descendant whose executable lies outside the app's bundle: that subtree is a build
    (`hosts_build`), its cores never count towards the app. `excluded` is set when the app's own ancestry reaches a held caller
    or an agent CLI (Playwright's Chrome for Testing). Apps with no lsappinfo entry at all (lsappinfo failed) come from the
    kernel exe path's bundle."""
    cfg = cfg or DEFAULTS
    held_pids = {str(p) for p in held_pids}
    agent_clis = set(agent_clis) | {"bg"}
    kids = {}
    for pid, (ppid, *_r) in table.items():
        kids.setdefault(str(ppid), []).append(pid)
    exe_cache = {}

    def exe(pid):
        if pid not in exe_cache:
            e = exe_of(pid)
            exe_cache[pid] = _real(e) if e else None
        return exe_cache[pid]

    def pname(pid):
        e = exe(pid)
        if e:
            return os.path.basename(e)
        cmd = table[pid][3] if pid in table else ""
        return os.path.basename(cmd.split()[0]) if cmd.split() else ""

    def argv_heads(pid):   # the program and its first argument (`node /x/claude`), as load-watch's cli_heads: a CLI's kernel exe is often `node` or a version number
        return {os.path.basename(w).lstrip("-") for w in (table[pid][3].split()[:2] if pid in table else [])}

    def is_agent(pid):
        return bool(agent_clis & (argv_heads(pid) | {pname(pid)}))

    def is_shell(pid):
        words = table[pid][3].split() if pid in table else []
        return bool(SHELLS & {pname(pid).lstrip("-"), os.path.basename(words[0]).lstrip("-") if words else ""})

    def build_stop(pid, real):   # C4b: a shell, a pty-attached process, a held caller, `bg` or an agent CLI, or an executable outside the bundle
        ex = exe(pid)
        return is_shell(pid) or pid in ttys or pid in held_pids or is_agent(pid) or (ex is not None and not _under(ex, real))

    roots = {}
    for e in lsapps:
        bp = e.get("bundle_path") or ""
        pid = str(e["pid"])
        if e.get("type") not in GUI_TYPES or _app_prefix(bp) != bp.rstrip("/") or pid not in table or table[pid][1] != my_uid:
            continue
        roots[pid] = {"name": e.get("name") or os.path.basename(bp), "bundle_id": e.get("bundle_id"), "bundle_path": bp}
    if not lsapps:   # lsappinfo gave nothing: the kernel's executable path decides
        cand = {}
        for pid, (ppid, uid, _c, cmd) in table.items():
            if uid != my_uid or ".app/" not in cmd:
                continue
            ex = exe(pid)
            bp = _app_prefix(ex) if ex else None
            if bp:
                cand[pid] = bp
        for pid, bp in cand.items():
            anc, hops = str(table[pid][0]), 0
            while anc in table and hops < 64 and cand.get(anc) != bp:
                anc, hops = str(table[anc][0]), hops + 1
            if cand.get(anc) == bp and anc != pid:
                continue   # a helper inside an app we already have a root for
            roots[pid] = {"name": os.path.basename(bp)[:-4], "bundle_id": _plist_id(bp), "bundle_path": bp}
    for pid, r in roots.items():
        r["real"] = _real(r["bundle_path"])
    # a helper app nested in another root's bundle (Chrome's, Electron's) belongs to the outer app
    for pid in sorted(roots, key=lambda p: len(roots[p]["real"])):
        if pid in roots and any(o != pid and _under(roots[pid]["real"], roots[o]["real"]) and roots[pid]["real"].casefold() != roots[o]["real"].casefold()
                                for o in roots):
            del roots[pid]
    for pid in list(roots):   # a helper entry whose parent process is a root of the same bundle is that app, not a second one
        anc, hops = str(table[pid][0]), 0
        while anc in table and hops < 64:
            if anc in roots and roots[anc]["real"] == roots[pid]["real"]:
                del roots[pid]
                break
            anc, hops = str(table[anc][0]), hops + 1
    apps = {pid: _App(pid, r) for pid, r in roots.items()}
    owner = {pid: pid for pid in apps}

    def subtree(pid, seen):
        stack, out = [pid], []
        while stack:
            p = stack.pop()
            if p in seen:
                continue
            seen.add(p)
            out.append(p)
            stack.extend(kids.get(p, []))
        return out

    seen_build = set()
    for rid, app in apps.items():
        stack = list(kids.get(rid, []))
        visited = {rid}
        while stack:
            c = stack.pop()
            if c in visited or c not in table:
                continue
            visited.add(c)
            if build_stop(c, app.real):
                sub = subtree(c, seen_build)
                app.build.update(sub)
                app.build_cores += sum(table[p][2] for p in sub if p in table)
                visited.update(sub)
                continue
            app.members.append(c)
            owner[c] = rid
            stack.extend(kids.get(c, []))
    def build_ancestry(pid, real):   # does the chain up from `pid` reach the app (clean) or pass a build stop first?
        a, hops = str(table[pid][0]), 0
        while a in table and a not in ("0", "1") and hops < 64:
            if a in owner or a in apps:
                return False
            if build_stop(a, real):
                return True
            a, hops = str(table[a][0]), hops + 1
        return False

    for pid, (ppid, uid, _c, cmd) in table.items():   # helpers launchd started: their executable sits inside a bundle
        if pid in owner or pid in seen_build or uid != my_uid or ".app/" not in cmd:
            continue
        ex = exe(pid)
        if not ex:
            continue
        for rid, app in apps.items():
            if _under(ex, app.real):
                if build_stop(pid, app.real) or build_ancestry(pid, app.real):
                    seen_build.add(pid)   # a build running the app's own binary (a headless browser under a test run): not the app's helper
                else:
                    app.members.append(pid)
                    owner[pid] = rid
                break
    out = []
    for rid, app in apps.items():
        anc, hops, excluded = str(table[rid][0]), 0, None
        if rid in held_pids:
            excluded = "held-caller"
        while excluded is None and anc in table and hops < 64:
            if anc in held_pids:
                excluded = "held-ancestor"
            elif is_agent(anc):
                excluded = "agent-ancestor"
            anc, hops = str(table[anc][0]), hops + 1
        rex = exe(rid)
        out.append({"id": rid, "name": app.name, "bundle_id": app.bundle_id, "bundle_path": app.bundle_path,
                    "root_pid": app.root_pid, "members": len(app.members),
                    "cores": sum(table[p][2] for p in app.members if p in table),
                    "rss_mb": sum(rss_kb.get(p, 0) for p in app.members) / 1024.0,
                    "hosts_build": bool(app.build), "build_cores": app.build_cores, "excluded": excluded,
                    "protected": protect_reason(app.bundle_id, app.real, rex, table[rid][1], my_uid, cfg)})
    return out


# ---- the 5-minute window and the decision (C3, C4) -------------------------------------------------------------------
def window_update(st, t, apps, total_cores, cfg):
    """Add this sample to st["apps"] (trimmed to window_s) and refresh st["app_meta"]. An app is stored when it is not an excluded build
    tree and either uses 0.02 cores or holds 50 MB; a protected app is stored with flag 1 (it is counted, not listed)."""
    tr = cfg["trigger"]
    row = {}
    for a in apps:
        if a["excluded"] or (a["cores"] < 0.02 and a["rss_mb"] < 50):
            continue
        item = [round(a["cores"], 2), int(a["rss_mb"])]
        flag = (1 if a["protected"] else 0) | (2 if a["hosts_build"] else 0)
        if flag:
            item.append(flag)
        row[a["id"]] = item
    prev = st.get("apps") if isinstance(st.get("apps"), list) else []
    keep = [x for x in prev if isinstance(x, dict) and _fin(x.get("t")) and x["t"] >= t - tr["window_s"] and x["t"] <= t]
    keep.append({"t": t, "cpu": round(total_cores, 2), "a": row})
    st["apps"] = keep
    meta = st.get("app_meta") if isinstance(st.get("app_meta"), dict) else {}
    for a in apps:
        if a["id"] in row:
            meta[a["id"]] = {"n": clean(a["name"]), "b": clean(a["bundle_id"] or "", 80), "p": clean(a["bundle_path"] or "", 120)}
    live = {pid for x in keep for pid in x["a"]}
    st["app_meta"] = {k: v for k, v in meta.items() if k in live}


def _fin(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) != float("inf")


def window_means(st, t, cfg):
    """[{id, name, bundle_id, bundle_path, cores_5m, rss_mb, protected, hosts_build}] from st["apps"]: cores are the mean over the
    samples in the window (an app missing from a sample counts 0), RSS is the latest reading."""
    apps = st.get("apps") if isinstance(st.get("apps"), list) else []
    win = [x for x in apps if isinstance(x, dict) and _fin(x.get("t")) and t - cfg["trigger"]["window_s"] <= x["t"] <= t
           and isinstance(x.get("a"), dict)]
    n = len(win)
    if not n:
        return []
    meta = st.get("app_meta") if isinstance(st.get("app_meta"), dict) else {}
    sums, last = {}, {}
    for x in win:
        for pid, item in x["a"].items():
            if isinstance(item, list) and len(item) >= 2 and _fin(item[0]) and _fin(item[1]):
                sums[pid] = sums.get(pid, 0.0) + item[0]
                last[pid] = item
    out = []
    for pid, s in sums.items():
        it, m = last[pid], meta.get(pid, {}) if isinstance(meta.get(pid, {}), dict) else {}
        flag = it[2] if len(it) > 2 and isinstance(it[2], int) else 0
        out.append({"id": pid, "name": clean(m.get("n", pid)), "bundle_id": clean(m.get("b", ""), 80), "bundle_path": clean(m.get("p", ""), 120),
                    "cores_5m": s / n, "rss_mb": it[1], "protected": bool(flag & 1), "hosts_build": bool(flag & 2), "excluded": None})
    out.sort(key=lambda a: -a["cores_5m"])
    return out


def should_show(held, apps, now, snooze, last_shown, cfg):
    """Would the dialog show now? {"show": bool, "reason": str, "sum_cores", "sum_rss_mb", "holds": [...]}. All of (C4):
    (a) some hold has been refused for hold_s or longer; (b) its refusals include a gate that desktop apps can relieve; (c) the SUM
    over non-build, non-protected apps of their 5-min mean cores is at least min_cores, or the sum of their RSS at least min_rss_mb
    (an app that hosts a build counts without the build); (d) rate_s since the dialog was last shown, and the Ignore snooze
    (`snooze`, an epoch or None) expired. `reason` names the first check that failed, in that order."""
    tr = cfg["trigger"]
    snooze = snooze if _fin(snooze) else None
    last_shown = last_shown if _fin(last_shown) and last_shown <= now else None   # a clock set back must not silence the trigger
    rel = set(tr["relievable"])
    old = [h for h in held if now - h["refused_since"] >= tr["hold_s"]]
    live = [h for h in old if rel & set(h.get("refused", []))]
    pool = [a for a in apps if not a.get("protected") and not a.get("excluded")]
    cores, rss = sum(a["cores_5m"] for a in pool), sum(a["rss_mb"] for a in pool)
    res = {"show": False, "reason": "", "sum_cores": round(cores, 2), "sum_rss_mb": int(rss), "holds": live}
    if not held:
        res["reason"] = "no-hold"
    elif not old:
        res["reason"] = "hold-too-short"
    elif not live:
        res["reason"] = "not-relievable"
    elif cores < tr["min_cores"] and rss < tr["min_rss_mb"]:
        res["reason"] = "below-threshold"
    elif _fin(snooze) and now < snooze:
        res["reason"] = "snoozed"
    elif _fin(last_shown) and now - last_shown < tr["rate_s"]:
        res["reason"] = "rate-limited"
    else:
        res["show"], res["reason"] = True, "show"
    return res


# ---- state files the dialog will own (D5) and the dry-run log (I1) -----------------------------------------------------
def gui_dir(state_dir):
    return Path(state_dir) / "gui-hog"


def read_snooze(state_dir):
    """snooze_until (epoch) from gui-hog/snooze.json, or None. The sampler only reads it (D5)."""
    try:
        if not safe_dir(gui_dir(state_dir)):
            return None
        v = json.loads(read_small(gui_dir(state_dir) / "snooze.json")).get("snooze_until")
        return v if _fin(v) else None
    except Exception:  # noqa: BLE001 - a corrupt or hostile file is no snooze
        return None


def effective_snooze(gh_state, raw, t, snooze_s, record=False):
    """The snooze epoch to honour: `raw` (the file's snooze_until) clamped to snooze_s after the moment it was FIRST seen, so a hostile or
    garbled value never silences the trigger for longer than an Ignore lasts. The first sighting is kept in the sampler's state
    (`snooze_seen`); a reader that cannot write (`gui-hog status`) clamps against `t`."""
    if not _fin(raw):
        return None
    seen = gh_state.get("snooze_seen") if isinstance(gh_state, dict) else None
    if isinstance(seen, dict) and seen.get("raw") == raw and _fin(seen.get("until")):
        return seen["until"]
    until = min(raw, t + snooze_s)
    if record and isinstance(gh_state, dict):
        gh_state["snooze_seen"] = {"raw": raw, "until": until}
    return until


def dry_run_path(state_dir):
    return gui_dir(state_dir) / "dry-run.jsonl"


def dry_run_append(state_dir, entry):
    """Append one JSON line to dry-run.jsonl (mode 0600; rotated at 1 MB to one `.1` file). Raises on an OS error: the caller wraps it."""
    p = dry_run_path(state_dir)
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not safe_dir(p.parent):
        raise OSError(f"{p.parent} is not a real directory of this user")
    try:
        if os.lstat(p).st_size >= DRY_RUN_MAX_BYTES:
            os.replace(p, p.with_name(p.name + ".1"))
    except OSError:
        pass
    data = (json.dumps(entry, separators=(",", ":"), default=str) + "\n").encode()
    fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NONBLOCK | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("dry-run log is not a regular file")
        while data:
            data = data[os.write(fd, data):]
    finally:
        os.close(fd)


def count_dry_run(state_dir, days, now):
    """How many `would-show` lines the dry-run log holds from the last `days` days (it and its `.1` file)."""
    n = 0
    cutoff = now - days * 86400
    p = dry_run_path(state_dir)
    for f in (p.with_name(p.name + ".1"), p):
        try:
            text = read_small(f, 4 * DRY_RUN_MAX_BYTES)
        except OSError:
            continue
        for ln in text.splitlines():
            try:
                r = json.loads(ln)
                t = calendar.timegm(time.strptime(r["t"], "%Y-%m-%dT%H:%M:%SZ"))
            except (ValueError, KeyError, TypeError, AttributeError, RecursionError, OverflowError):
                continue
            if isinstance(r, dict) and r.get("event") == "would-show" and t >= cutoff:
                n += 1
    return n


def _iso(t):
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
    except (OverflowError, ValueError, OSError, TypeError):
        return "?"


def gui_session(my_uid):
    """True when the operator owns the console (a window could appear). os.stat, no subprocess; False on Linux or an unreadable console."""
    try:
        return sys.platform == "darwin" and os.stat("/dev/console").st_uid == my_uid
    except OSError:
        return False


def would_show_line(decision, apps, t, load1, cfg, my_uid):
    """The dry-run record for a decision that says show. Names are cleaned text (J3); the rows are the busiest few."""
    tr = cfg["trigger"]
    rows = [a for a in apps if not a.get("protected")
            and (a["cores_5m"] >= tr["min_row_cores"] or a["rss_mb"] >= tr["min_row_rss_mb"])]
    return {"t": _iso(t), "event": "would-show", "reason": decision["reason"],
            "held": [{"caller": h["caller"], "held_s": int(t - h["refused_since"]), "refused": h["refused"]} for h in decision["holds"]],
            "sum_cores": decision["sum_cores"], "sum_rss_mb": decision["sum_rss_mb"],
            "cores_hit": decision["sum_cores"] >= tr["min_cores"], "rss_hit": decision["sum_rss_mb"] >= tr["min_rss_mb"],
            "apps": [{"name": a["name"], "bundle_id": a["bundle_id"], "cores_5m": round(a["cores_5m"], 2), "rss_mb": int(a["rss_mb"]),
                      "hosts_build": a["hosts_build"]} for a in rows[:8]],
            "protected_hidden": sum(1 for a in apps if a.get("protected")),
            "gui_session": gui_session(my_uid), "load1": None if load1 is None else round(load1, 2)}


def enabled():
    return os.environ.get("LW_GUI_HOG", "").strip() != "0"


def tick(st, t, table, rss_kb, ttys, *, state_dir, my_uid, agent_clis=(), total_cores=None, load1=None, dry=False,
         cfg=None, lsapps=None, exe_of=kernel_exe, out=print, start_of=proc_start):
    """The sampler's whole GUI-hog step (K1): refresh the app window in `st`, read the holds, decide, and on a `show` write the dry-run
    line (or, with `dry`, print it and change nothing but the window). Returns the decision dict, or None when LW_GUI_HOG=0.
    The caller wraps it in a `try`: a failure here never stops load sampling."""
    if not enabled():
        for k in ("apps", "app_meta"):
            st.pop(k, None)
        return None
    cfg = cfg or load_config()
    for key, kind in (("apps", list), ("app_meta", dict), ("gui_hog", dict)):   # corrupt state heals itself instead of killing every tick
        if not isinstance(st.get(key), kind):
            st[key] = kind()
    held = read_holds(state_dir, t, sweep=not dry, start_of=start_of)
    held_pids = [h["pid"] for h in held] + [h["caller_pid"] for h in held if h.get("caller_pid")]
    lsapps = collect_lsappinfo() if lsapps is None else lsapps
    apps = group_apps(table, rss_kb, ttys, lsapps, exe_of=exe_of, my_uid=my_uid, held_pids=held_pids, agent_clis=agent_clis, cfg=cfg)
    if total_cores is None:
        total_cores = sum(row[2] for row in table.values())
    window_update(st, t, apps, total_cores, cfg)
    gh = st["gui_hog"]
    means = window_means(st, t, cfg)
    d = should_show(held, means, t, effective_snooze(gh, read_snooze(state_dir), t, cfg["trigger"]["snooze_s"], record=True), gh.get("last_shown"), cfg)
    if d["show"]:
        line = would_show_line(d, means, t, load1, cfg, my_uid)
        if dry:
            out("gui-hog would show dialog: " + json.dumps(line, separators=(",", ":")))
        else:
            dry_run_append(state_dir, line)
            gh["last_shown"] = t
    return d


# ---- `gui-hog status` ----------------------------------------------------------------------------------------------
def status_lines(st, state_dir, now, cfg):
    tr = cfg["trigger"]
    held = read_holds(state_dir, now, sweep=False)
    means = window_means(st, now, cfg)
    ghs = st.get("gui_hog") if isinstance(st.get("gui_hog"), dict) else {}
    snooze, last = effective_snooze(ghs, read_snooze(state_dir), now, cfg["trigger"]["snooze_s"]), ghs.get("last_shown")
    d = should_show(held, means, now, snooze, last, cfg)
    lines = [f"gui-hog (PR 3a, dry-run only: no window exists yet) {'ENABLED' if enabled() else 'OFF (LW_GUI_HOG=0)'}",
             f"decision now: {'WOULD SHOW' if d['show'] else 'no'} ({d['reason']})",
             f"thresholds: hold {tr['hold_s']} s, sum of non-build apps >= {tr['min_cores']:g} cores (5-min mean) or >= {tr['min_rss_mb']} MB RSS; "
             f"rate {tr['rate_s']} s, Ignore snooze {tr['snooze_s']} s",
             f"sum now: {d['sum_cores']:.2f} cores, {d['sum_rss_mb']} MB over {sum(1 for a in means if not a['protected'])} listed apps"]
    lines.append(f"holds: {len(held)}" + ("" if held else " (no `admit --wait` is held now)"))
    for h in held:
        lines.append(f"  {h['caller'] or '?'} pid {h['pid']} held {int(now - h['refused_since'])} s for {', '.join(h['refused']) or '?'}")
    lines.append(f"snooze until: {_iso(snooze) if snooze else 'none'}; last would-show: {_iso(last) if _fin(last) else 'never'}")
    rows = [a for a in means if not a["protected"] and (a["cores_5m"] >= tr["min_row_cores"] or a["rss_mb"] >= tr["min_row_rss_mb"])]
    lines.append(f"apps (busiest first; cores = {tr['window_s']} s mean):")
    for a in rows[:12]:
        lines.append(f"  {a['cores_5m']:5.2f} cores {a['rss_mb']:6d} MB  {a['name']}  [{a['bundle_id'] or 'no bundle id'}]"
                     + ("  has a build or terminal inside: no actions" if a["hosts_build"] else ""))
    if len(rows) > 12:
        lines.append(f"  +{len(rows) - 12} more")
    lines.append(f"{sum(1 for a in means if a['protected'])} protected apps hidden")
    lines.append(f"dry-run log: {dry_run_path(state_dir)} ({count_dry_run(state_dir, 7, now)} would-show lines in the last 7 days)")
    return lines
