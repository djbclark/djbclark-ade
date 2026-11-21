"""gui_hog: the data, the trigger and the actions' checks of the GUI-hog dialog (docs/gui-hog-dialog.md; PR 3a was dry-run only, PR 3b adds the
window: the sampler launches `ADE GUI Hog.app` live, writes its snapshot, and `vet` checks every Quit before the Swift view acts).

Stdlib only; it never imports `load-watch` (a broken sampler must not be able to break it, and PR 3c's thaw path will
live here). `load-watch` imports it lazily, inside a `try`, in two places: `admit --wait` writes the hold registry
(C2) and the 20 s sampler calls `tick` (C3, C4, C5). Nothing here signals, quits or freezes anything: the Swift dialog does Quit and
Force Quit itself (`NSRunningApplication`), after `vet` here said the app may be touched.

    hold_write / hold_remove / read_holds     ~/.local/state/load-watch/held/<pid>-<start>.json: who waits on `admit` now (C2)
    parse_lsappinfo / group_apps              GUI apps from `lsappinfo list`, with their process trees (C3, C4b)
    should_show(held, apps, now, snooze, last_shown, cfg)   the one pure decision function (C4)
    tick                                      the sampler's whole step: window, decision, snapshot, dry-run line, launch (K1, C5)
    build_snapshot / write_snapshot           gui-hog/snapshot.json, the dialog's only input (D3)
    vet                                       the live checks before a Quit or Force Quit (D4: exit 0 / 3 protected / 4 identity / 5 hosts a build / 6 gone)
    launch_dialog / bundle_state              start the bundle detached, never build at trigger time (C5, D2)
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
import fcntl
import hashlib
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
    # PR 3c (section F): Freeze. Only the shipped config can turn it off; `enabled = false` hides the buttons and refuses `gui-hog freeze`.
    "freeze": {"enabled": True, "default_minutes": 10, "max_minutes": 1440, "passes": 3, "lock_timeout_s": 5,
               # Operator ruling 2026-11-21 (design rule B6 amended): apps listed in `order` (bundle ids, preferred first) are frozen by the sampler
               # when a build is held by the GUI-hog trigger; unlisted apps still need a click. `[protected]` and the hard floor always win.
               # `always` (2026-11-21, Q3): apps frozen by the sampler WITHOUT asking: the dialog lists no row and counts no cores for them (the Frozen list and the menu
               # still offer Resume). `skip` wins over `always`; a protected app is never on it.
               "auto": {"enabled": True, "order": [], "always": [], "skip": [], "minutes": None, "min_cores": 0.05, "refreeze_s": 3600},
               # bundle id -> paths inside the bundle that a freeze never stops (matched on the kernel exe, never argv): CodexBar's HTTP server
               "keep_running": {},
               # bundle id -> what we depend on that a freeze of that app breaks (text for `gui-hog suggest`: the Beeper MCP port, the CodexBar quota feeder)
               "depends": {}},
    # `gui-hog suggest` thresholds (Q1): at least min_events freezes (or dialog sightings) over the last `days`
    "suggest": {"min_events": 3, "negligible_cores": 0.10, "large_cores": 0.50, "days": 30},
}

# The hard floor (F6): code, not configuration. Config can add protected entries, never remove these.
HARD_BUNDLE_IDS = frozenset({"com.apple.dock", "com.apple.loginwindow", "com.apple.finder", "com.apple.systemuiserver",
                             "com.apple.controlcenter", "com.apple.windowmanager", "com.apple.windowserver",
                             DIALOG_BUNDLE_ID.lower()})
HARD_PATH_PREFIXES = ("/System", "/usr")
HARD_EXE_NAMES = frozenset({"windowserver", "loginwindow", "dock", "finder", "ade-gui-hog"})   # real executables; `bg` is a script, matched by argv in group_apps (with the agent CLIs)
SHELLS = frozenset({"bash", "zsh", "sh", "dash", "fish", "ksh", "tcsh", "csh", "login"})
GUI_TYPES = ("Foreground", "UIElement")


# ---- untrusted text (J3) -----------------------------------------------------------------------------------------
_DROP_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})   # controls, ALL format characters (bidi, zero-width, TAG, soft hyphen), surrogates, private, unassigned, line/paragraph separators
_FILLERS = frozenset("\u034f\u115f\u1160\u3164\uffa0\u17b4\u17b5\u180b\u180c\u180d\u180f\u2800")   # invisible, but not in a dropped category


def _smuggler(ch):   # variation selectors: invisible after any base character, a known channel for hidden bytes
    return "\ufe00" <= ch <= "\ufe0f" or "\U000e0100" <= ch <= "\U000e01ef"


def _markish(ch):
    return unicodedata.category(ch).startswith("M") or "\ufe00" <= ch <= "\ufe0f" or "\U0001f3fb" <= ch <= "\U0001f3ff"


def clean(text, limit=60):
    """`text` as one line of plain, printable text: every control (Cc), format (Cf: bidi marks and overrides, zero-width, TAG, soft hyphen),
    surrogate, private-use and unassigned character, line and paragraph separator and invisible filler removed, then clipped to `limit` characters. The cut backs off any combining mark, so it
    never leaves half of a cluster (an approximation of a grapheme-cluster cut: ZWJ is removed, so a ZWJ emoji
    sequence degrades to its parts)."""
    s = "".join(ch for ch in str(text) if unicodedata.category(ch) not in _DROP_CATEGORIES and ch not in _FILLERS and not _smuggler(ch))
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


def _num(v, lo, hi):
    """A real, finite number (never a bool or a string) within [lo, hi]."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and _fin(v) and lo <= v <= hi


def rule_ok(r):
    """A keep-running rule is an exact executable: relative to the bundle (two or more components, `Contents/Helpers/CodexBarCLI`) or absolute (`~`
    expands) and then inside some `X.app` bundle, at least `X.app/<dir>/<file>`; never `/`, a broad directory such as /opt/homebrew, a path
    that is an existing directory, or a path with `..` (adversary L4: such a rule would turn off the out-of-bundle build stop for a whole toolchain).
    It is matched against a process's kernel executable path EXACTLY (`_same_path`), never as a prefix, so even a relative rule that names a directory
    keeps nothing (PR 859 adversary low 1)."""
    if not isinstance(r, str) or not r.strip():
        return False
    p = Path(os.path.expanduser(r) if r.startswith("~") else r)
    parts = p.parts
    if not parts or ".." in parts:
        return False
    if p.is_absolute():
        return any(x.casefold().endswith(".app") and len(parts) - i - 1 >= 2 for i, x in enumerate(parts)) and not p.is_dir()   # a directory is no executable (PR 859 low 1)
    return len(parts) >= 2


def _same_path(path, target):
    """True when `path` is exactly `target` (casefolded, by path components): a keep-running rule names ONE executable, never a directory's contents."""
    return Path(str(path).casefold()).parts == Path(str(target).casefold()).parts


def _merge_freeze(cfg, data, overlay=False):
    """Fold a `[freeze]` table (the shipped file or the user overlay) into cfg: plain keys replace, `auto` replaces key by key (typed: a wrong type or
    an out-of-range number keeps the previous value; the overlay can switch `enabled` OFF but never back on, so a shipped `enabled = false` rollback
    wins), `keep_running` is per bundle id (exact-executable rules, see `rule_ok`; the overlay adds to the shipped lists, it never removes one)."""
    for k, v in data.items():
        if k == "auto" and isinstance(v, dict):
            au = cfg["freeze"]["auto"]
            for ak, av in v.items():
                if ak == "order":
                    if isinstance(av, list):
                        au["order"] = [x for x in av if isinstance(x, str) and x.strip()]
                elif ak == "always":   # apps frozen without asking (Q3); the overlay adds, never removes; `skip` and [protected] win at use time (always_apps)
                    if isinstance(av, list):
                        clean_ = [x.strip() for x in av if isinstance(x, str) and x.strip()]
                        au["always"] = au["always"] + [x for x in clean_ if x.casefold() not in {y.casefold() for y in au["always"]}] if overlay else clean_
                elif ak == "skip":   # apps never auto-frozen, whatever `order` says (a manual freeze stays possible); the overlay adds, never removes
                    if isinstance(av, list):
                        names = [x.strip() for x in av if isinstance(x, str) and x.strip()]
                        au["skip"] = au["skip"] + [x for x in names if x.casefold() not in {y.casefold() for y in au["skip"]}] if overlay else names
                elif ak == "enabled":
                    if isinstance(av, bool):
                        au["enabled"] = (au["enabled"] and av) if overlay else av
                elif ak == "minutes":
                    if _num(av, 1, cfg["freeze"].get("max_minutes", 1440)):
                        au["minutes"] = av
                elif ak == "min_cores":
                    if _num(av, 0, 1000):
                        au["min_cores"] = av
                elif ak == "refreeze_s":
                    if _num(av, cfg["trigger"].get("hold_s", 180), 7 * 86400):   # shorter than hold_s would undo an operator's Resume on the next tick
                        au["refreeze_s"] = av
        elif k == "keep_running" and isinstance(v, dict):
            for bid, rels in v.items():
                if isinstance(bid, str) and isinstance(rels, list):
                    have = cfg["freeze"]["keep_running"].setdefault(bid, [])
                    have.extend(r for r in rels if rule_ok(r) and r not in have)
        elif k == "depends" and isinstance(v, dict):
            for bid, texts in v.items():
                if isinstance(bid, str) and isinstance(texts, list):
                    have = cfg["freeze"]["depends"].setdefault(bid, [])
                    have.extend(c for c in (clean(t, 120) for t in texts if isinstance(t, str) and t.strip()) if c and c not in have)
        elif k not in ("auto", "keep_running", "depends"):
            cfg["freeze"][k] = v


def load_config(path=None, local=None):
    """Defaults, then config/gui-hog.toml, then the user overlay (~/.config/load-watch/gui-hog.toml). The overlay can only ADD to the protected
    lists (never remove from them or from the hard floor in code); `[freeze.auto]` (the order, enabled, minutes, min_cores, refreeze_s) it may
    set or override, it only ADDS to `[freeze.auto] skip` and `always`, `[freeze.keep_running]` and `[freeze.depends]`, and it can switch `enabled`
    off, never on. Raises on a broken shipped file; a broken overlay is ignored."""
    cfg = json.loads(json.dumps(DEFAULTS))
    data = _read_toml(path or DEFAULT_CONFIG) if (path or DEFAULT_CONFIG).exists() else {}
    for sec, vals in data.items():
        if sec == "freeze" and isinstance(vals, dict):
            _merge_freeze(cfg, vals)
        elif sec in cfg and isinstance(vals, dict):
            cfg[sec].update(vals)
    loc = local if local is not None else LOCAL_CONFIG
    try:
        over = _read_toml(loc) if loc.exists() else {}
    except Exception:  # noqa: BLE001 - the overlay is optional
        over = {}
    extra = over.get("protected", {}) if isinstance(over, dict) else {}
    for key in cfg["protected"]:
        add = extra.get(key, []) if isinstance(extra, dict) else []
        if isinstance(add, list):
            cfg["protected"][key] = list(cfg["protected"][key]) + [x for x in add if isinstance(x, str)]
    fz = over.get("freeze") if isinstance(over, dict) else None
    if isinstance(fz, dict):   # only the auto-freeze list and the keep-running rules: the overlay cannot touch enabled, max_minutes, passes, the lock timeout
        _merge_freeze(cfg, {k: v for k, v in fz.items() if k in ("auto", "keep_running", "depends")}, overlay=True)
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


def always_problems(cfg):
    """[(bundle id, why)] for the entries of `[freeze.auto] always` that are ignored: on the never-auto list (`skip` wins) or protected (by bundle id or
    prefix: a protected app is never frozen without asking; a bundle PATH rule is applied to the live app at freeze time, `vet_app`). Also the dynamic
    refusals, an app hosting a build or terminal, which only the live process table can tell."""
    au = cfg["freeze"]["auto"]
    skip = {str(x).casefold() for x in au.get("skip", [])}
    out = []
    for bid in au.get("always", []):
        if bid.casefold() in skip:
            out.append((bid, "on the never-auto list (skip wins)"))
        elif protect_reason(bid, None, None, 0, 0, cfg):
            out.append((bid, "protected"))
    return out


def always_apps(cfg, effective=True):
    """The bundle ids (casefolded) that are frozen WITHOUT asking and so get no dialog row (Q3): `[freeze.auto] always` minus the ignored entries
    (`always_problems`). `effective` also requires that the sampler will really freeze them: `[freeze] enabled`, `[freeze.auto] enabled` and not
    `LW_GUI_HOG_AUTO=0`; otherwise the apps are ordinary rows again, so switching the auto-freeze off never hides an app from the operator."""
    fz, au = cfg["freeze"], cfg["freeze"]["auto"]
    if effective and (not fz.get("enabled", True) or not au.get("enabled", True) or os.environ.get("LW_GUI_HOG_AUTO", "").strip() == "0"):
        return frozenset()
    bad = {b.casefold() for b, _w in always_problems(cfg)}
    return frozenset(b.casefold() for b in au.get("always", []) if b.casefold() not in bad)


def quiet(a, always):
    """True for an app that is frozen without asking: its bundle id is in `always`, the set `quiet_ids` returns (or the bare `always_apps` list), and it is
    not protected and hosts no build or terminal (such an app is an ordinary row: the operator is asked, and the sampler cannot freeze it)."""
    return bool(always) and str(a.get("bundle_id") or "").casefold() in always and not a.get("protected") and not a.get("hosts_build")


def quiet_ids(cfg, means, now, gh_state=None, frozen=(), act=True):
    """The bundle ids (casefolded) that get no dialog row because they are ALREADY frozen by us or the sampler would freeze them now (Q3, adversary
    L2 of #872): on the effective always list and either in `frozen` (bundle ids with a live frozen entry), or running, not protected, hosting no
    build or terminal, not in the cooling-down / retry-wait window of `gh_state["auto"]` (the operator Resumed it, or a freeze was refused) and using
    at least `min_cores` now. Anything else is an ordinary row again: an app the sampler will not freeze must never disappear from the operator's
    sight. (Not here: `excluded` apps never reach the window, so they are no rows either; the sampler's own `kept_cores` is not known to the window,
    so the idle test is the app's current cores, a close approximation.) `act` says the sampler is allowed to freeze right now (a live hold and no
    Ignore snooze: `auto_freeze_step` does nothing otherwise, adversary L2r of #872); without it only the already frozen apps are quiet."""
    always = always_apps(cfg)
    if not always:
        return frozenset()
    au = cfg["freeze"]["auto"]
    auto = gh_state.get("auto") if isinstance(gh_state, dict) and isinstance(gh_state.get("auto"), dict) else {}
    frozen = {str(b).casefold() for b in frozen}
    try:
        from gui_hog_freeze import AUTO_RETRY_S as retry_s
    except Exception:  # noqa: BLE001
        retry_s = 120
    live = {}
    for a in means:
        bid = str(a.get("bundle_id") or "").casefold()
        if bid in always and bid not in live and a.get("present"):
            live[bid] = a
    out = set()
    for bid in always:
        a = live.get(bid)
        if bid in frozen:
            if a is None or not (a.get("protected") or a.get("hosts_build")):
                out.add(bid)
            continue
        if not act or a is None or a.get("protected") or a.get("hosts_build"):
            continue
        st = auto.get(bid)
        if isinstance(st, dict) and _fin(st.get("t")) and 0 <= now - st["t"] < (float(au.get("refreeze_s", 3600)) if st.get("ok") else retry_s):
            continue
        cpu = a.get("cpu_now", a.get("cores_5m", 0.0))
        if not _fin(cpu) or cpu < float(au.get("min_cores", 0.05)):
            continue
        out.add(bid)
    return frozenset(out)


def quiet_for(cfg, means, now, state_dir, gh_state, held=None):
    """`quiet_ids` with the frozen bundle ids read from `state_dir` and `act` taken from the same conditions `auto_freeze_step` uses (a live hold, no
    Ignore snooze); `held` is the holds the caller already read. Never raises: a failure reads as nothing frozen and no freeze due, so every app
    stays a row."""
    try:
        if not always_apps(cfg):
            return frozenset()
        frozen = ()
        try:
            import gui_hog_freeze
            frozen = gui_hog_freeze.frozen_bundle_ids(state_dir)
        except Exception:  # noqa: BLE001
            pass
        try:
            holds = read_holds(state_dir, now, sweep=False) if held is None else held
            snz = effective_snooze(gh_state if isinstance(gh_state, dict) else {}, read_snooze(state_dir), now, cfg["trigger"]["snooze_s"])
            act = bool(hold_active(holds, now, cfg)[1]) and not (snz is not None and now < snz)
        except Exception:  # noqa: BLE001
            act = False
        return quiet_ids(cfg, means, now, gh_state, frozen, act=act)
    except Exception:  # noqa: BLE001
        return frozenset()


# ---- process identity ----------------------------------------------------------------------------------------------
_libproc = None


def _libproc_lib():
    global _libproc
    if _libproc is None:
        _libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    return _libproc


def kernel_exe(pid):
    """The executable path the kernel reports for `pid` (never argv[0]): proc_pidpath on macOS, /proc/PID/exe on Linux. None
    when the process is gone or unreadable."""
    try:
        if sys.platform == "darwin":
            buf = ctypes.create_string_buffer(4096)
            n = _libproc_lib().proc_pidpath(int(pid), buf, 4096)
            return os.fsdecode(buf.value) if n > 0 else None
        return os.readlink(f"/proc/{int(pid)}/exe")
    except (OSError, ValueError, AttributeError):
        return None


def kernel_name(pid):
    """The kernel's short process name for `pid` (libproc `proc_name`, the p_comm the kernel took from the exec'd file's name: not argv and not the
    environment), or None. It answers for a process whose executable was replaced on disk by an upgrade (where `proc_pidpath` fails), and gives nothing
    for a zombie, a process that is gone, or (it is a same-user lookup in the kernel) another user's process. macOS only: Linux has no such name that the process cannot set itself (/proc/PID/comm can be changed by
    prctl), so there it is None."""
    try:
        if sys.platform != "darwin":
            return None
        buf = ctypes.create_string_buffer(256)
        n = _libproc_lib().proc_name(int(pid), buf, 256)
        return os.fsdecode(buf.value) if n > 0 and buf.value else None
    except (OSError, ValueError, AttributeError):
        return None


def _has_proc():
    return os.path.isdir("/proc/self")


def proc_start(pid):
    """A start-time string for `pid` that is stable for the life of the process (`ps -o lstart=` under LC_ALL=C TZ=UTC on macOS;
    /proc/PID/stat starttime on Linux), or None when it is gone or unreadable."""
    try:
        pid = int(pid)
        if _has_proc():
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


def proc_starts(pids):
    """{pid: start string} for the pids that exist, from ONE `ps -o pid=,lstart= -p a,b,c` call on macOS (LC_ALL=C TZ=UTC; a missing pid
    is simply absent and makes ps exit 1, which is not an error here) or one /proc read each on Linux. {} when ps fails or times out: the
    callers treat an unknown start as "cannot tell", never as a different process."""
    pids = [int(p) for p in pids]
    if not pids:
        return {}
    if _has_proc():
        return {p: s for p in pids if (s := proc_start(p))}
    try:
        env = dict(os.environ, LC_ALL="C", TZ="UTC")
        r = subprocess.run(["ps", "-o", "pid=,lstart=", "-p", ",".join(str(p) for p in pids)], capture_output=True, text=True, timeout=5, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    out = {}
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit():
            out[int(parts[0])] = " ".join(parts[1:])
    return out


def _sweep_tmp(d, now, max_age=120):
    """Remove `.hold-*.tmp` files (a writer killed between mkstemp and os.replace) older than `max_age` seconds. Regular files only, by lstat."""
    try:
        names = os.listdir(d)
    except OSError:
        return
    for name in names:
        if name.startswith(".hold-") and name.endswith(".tmp"):
            try:
                info = os.lstat(d / name)
                if stat.S_ISREG(info.st_mode) and now - info.st_mtime > max_age:
                    os.unlink(d / name)
            except OSError:
                pass


def read_holds(state_dir, now, sweep=True, start_of=None, cap=HOLD_AGE_CAP_S, check_start=True):
    """The live holds. A file is stale (and swept when `sweep`) when its `updated` is more than max(60 s, 2 polls + 15 s) old or in the future,
    or, when `check_start`, its pid is gone or now has another start time (pid reuse; a start time that cannot be read, such as a `ps` timeout
    under load, counts as stale only when the pid is dead). The start times of every candidate come from ONE `ps -p a,b,c` call
    (`proc_starts`), or from `start_of(pid)` one by one when a caller passes it. Only files named `<digits>-<slug>.json` are looked at, and never deleted otherwise;
    the directory must be a real directory of this user; each file is read as a small regular file (no symlink, no FIFO, 64 KB cap); a file that
    does not parse or has wrong types is skipped (and swept when older than 2 min by mtime); with `sweep`, a leftover `.hold-*.tmp` older than 2 min goes too.
    `refused_since` is clamped to [now - cap, now]: a future or non-integer value counts as `now`."""
    d = held_dir(state_dir)
    out = []
    if not safe_dir(d):
        return out
    if sweep:
        _sweep_tmp(d, now)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    cands = []   # (path, record, stale-by-age)
    for name in names:
        if not _HOLD_NAME.match(name):
            continue
        p = d / name
        try:
            rec = json.loads(read_small(p))
            pid, upd, poll = rec["pid"], rec["updated"], rec.get("poll_s", 15)
            ok = (rec.get("v") == 1 and type(pid) is int and 1 < pid < 2 ** 31 and _fin(upd) and _fin(poll)
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
        cands.append((p, rec, stale))
    starts = {}
    if check_start:
        want = [r["pid"] for _p, r, st in cands if not st and r.get("start", "")]
        if start_of is None:
            starts = proc_starts(want)
        else:
            starts = {pid: s for pid in want if (s := start_of(pid)) is not None}
    for p, rec, stale in cands:
        pid, upd = rec["pid"], rec["updated"]
        if not stale and check_start:
            rec_start = rec.get("start", "")
            cur = starts.get(pid) if rec_start else None
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


def argv_head_words(cmd):
    """The program word and the first non-option word after it, as base names: `node --max-old-space-size=4096 /opt/bin/pi` is {node, pi}
    (3a looked at the first two words only, so a leading node option hid the CLI). At most 8 words are scanned. Known limit: an option whose value is a
    separate word (`--max-old-space-size 4096 /opt/bin/pi`) still takes the value for the script word, as load-watch's own cli_heads does."""
    words = str(cmd).split()[:8]
    if not words:
        return set()
    heads = {os.path.basename(words[0]).lstrip("-")}
    for w in words[1:]:
        if not w.startswith("-"):
            heads.add(os.path.basename(w).lstrip("-"))
            break
    return heads


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


def keep_rules(cfg, bundle_id):
    """The paths that a freeze of `bundle_id` never stops (`[freeze.keep_running]`, matched on the bundle id, case-insensitively). A rule is a path
    inside the bundle (`Contents/Helpers/CodexBarCLI`) or an absolute path (`~` is the home directory) for a process the app spawns from OUTSIDE its
    bundle, such as Chrome's native-messaging hosts. A rule with a `..` component is ignored (it can never point somewhere it does not name)."""
    table = (cfg.get("freeze") or {}).get("keep_running") or {}
    out = []
    for bid, rels in table.items():
        if isinstance(bid, str) and bundle_id and bid.casefold() == str(bundle_id).casefold() and isinstance(rels, list):
            for r in rels:
                if rule_ok(r) and r not in out:
                    out.append(r)
    return out


def keep_targets(bundle_real, rules):
    """The rules as real paths: relative ones under the bundle, absolute (or `~/`) ones as they are."""
    out = []
    for r in rules:
        r = os.path.expanduser(r) if r.startswith("~") else r
        out.append(Path(_real(r)) if os.path.isabs(r) else Path(bundle_real, r))
    return out


def keep_running_pids(app, table, exe, cfg):
    """The members of `app` that a freeze must not stop: a process whose KERNEL executable path is a keep-running path of its bundle (never argv
    alone: a process sets its own argv), and every descendant of one inside the app. The root is never kept (an app whose main binary is
    kept would freeze nothing). `exe(pid)` is group_apps' cached realpath of the kernel executable."""
    rules = keep_rules(cfg, app.bundle_id)
    if not rules:
        return set()
    targets = keep_targets(app.real, rules)
    members = [m for m in app.members if m != app.id]
    kept = set()
    for m in members:
        ex = exe(m)
        if ex and any(_same_path(ex, t) for t in targets):   # the exact executable: a rule naming a directory keeps nothing (PR 859 low 1)
            kept.add(m)
    grew = True
    while grew:
        grew = False
        for m in members:
            if m not in kept and str(table[m][0]) in kept:
                kept.add(m)
                grew = True
    return kept


def group_apps(table, rss_kb, ttys, lsapps, *, exe_of, my_uid, held_pids=(), agent_clis=(), cfg=None):
    """One record per GUI app: {id (root pid), name, bundle_id, bundle_path, root_pid, members, cores, rss_mb, hosts_build,
    build_cores, build_pids, excluded, protected}. `table` is load-watch's ps table {pid: (ppid, uid, cores, command)}; `rss_kb` {pid: KB};
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

    def argv_heads(pid):   # the program and its script word (`node /x/claude`), as load-watch's cli_heads: a CLI's kernel exe is often `node` or a version number
        return argv_head_words(table[pid][3] if pid in table else "")

    def is_agent(pid):
        return bool(agent_clis & (argv_heads(pid) | {pname(pid)}))

    def is_shell(pid):
        words = table[pid][3].split() if pid in table else []
        return bool(SHELLS & {pname(pid).lstrip("-"), os.path.basename(words[0]).lstrip("-") if words else ""})

    keep_out = {}   # bundle realpath -> the absolute keep-running paths of its app (Chrome's native-messaging hosts): outside the bundle, but not a build

    def build_stop(pid, real):   # C4b: a shell, a pty-attached process, a held caller, `bg` or an agent CLI, or an executable outside the bundle
        ex = exe(pid)
        outside = ex is not None and not _under(ex, real) and not any(_same_path(ex, t) for t in keep_out.get(real, ()))
        return is_shell(pid) or pid in ttys or pid in held_pids or is_agent(pid) or outside

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
    for app in apps.values():
        keep_out[app.real] = [t for t in keep_targets(app.real, keep_rules(cfg, app.bundle_id)) if not _under(t, app.real)]
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
                    stack, visited = list(kids.get(pid, [])), {pid}   # what a helper launchd started runs is walked like the root's children (a shell in it is a build)
                    while stack:
                        c = stack.pop()
                        if c in visited or c not in table or c in owner:
                            continue
                        visited.add(c)
                        if build_stop(c, app.real):
                            sub = subtree(c, seen_build) or [c]   # `c` may already be in seen_build (ps order): it is still a build, whatever order the pids came in
                            app.build.update(sub)
                            app.build_cores += sum(table[q][2] for q in sub if q in table)
                            visited.update(sub)
                            continue
                        app.members.append(c)
                        owner[c] = rid
                        stack.extend(kids.get(c, []))
                break
    out = []
    for rid, app in apps.items():
        kept = keep_running_pids(app, table, exe, cfg)
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
                    "root_pid": app.root_pid, "members": len(app.members), "member_pids": [int(m) for m in app.members if m not in kept],
                    "kept_pids": sorted(int(m) for m in kept), "kept_rules": keep_rules(cfg, app.bundle_id),
                    "kept_cores": sum(table[p][2] for p in kept if p in table),
                    "kept_names": sorted({clean(os.path.basename(exe(m)), 60) for m in kept if exe(m)})[:20],
                    "cores": sum(table[p][2] for p in app.members if p in table),
                    "rss_mb": sum(rss_kb.get(p, 0) for p in app.members) / 1024.0,
                    "hosts_build": bool(app.build), "build_cores": app.build_cores, "build_pids": sorted(int(x) for x in app.build), "excluded": excluded,
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
    keep = [x for x in prev if isinstance(x, dict) and isinstance(x.get("a"), dict) and _fin(x.get("t")) and x["t"] >= t - tr["window_s"] and x["t"] <= t]
    keep.append({"t": t, "cpu": round(total_cores, 2), "a": row})
    st["apps"] = keep
    meta = st.get("app_meta") if isinstance(st.get("app_meta"), dict) else {}
    for a in apps:
        if a["id"] in row:
            meta[a["id"]] = {"n": clean(a["name"]), "b": clean(a["bundle_id"] or "", 80), "p": clean(a["bundle_path"] or "", 200)}
    live = {pid for x in keep for pid in x["a"]}
    st["app_meta"] = {k: v for k, v in meta.items() if k in live}


def _fin(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) != float("inf")


def window_means(st, t, cfg):
    """[{id, name, bundle_id, bundle_path, cores_5m, cpu_now, rss_mb, present, protected, hosts_build}] from st["apps"]: cores are the mean over the
    samples in the window (an app missing from a sample counts 0); RSS (an int, MB) is the latest reading, and 0 for an app absent from the latest
    sample (it has exited: its last reading must not keep the trigger alive until it ages out). `present` says whether the app is in the newest
    sample: 3b's dialog offers Quit and Force Quit only on a present row (an app that uses nothing also reads 0 MB, so rss_mb is no sign of it)."""
    apps = st.get("apps") if isinstance(st.get("apps"), list) else []
    win = [x for x in apps if isinstance(x, dict) and _fin(x.get("t")) and t - cfg["trigger"]["window_s"] <= x["t"] <= t
           and isinstance(x.get("a"), dict)]
    n = len(win)
    if not n:
        return []
    win.sort(key=lambda x: x["t"])
    latest = win[-1]["a"]
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
        here = pid in latest and isinstance(latest[pid], list) and len(latest[pid]) >= 2 and _fin(latest[pid][0]) and _fin(latest[pid][1])
        out.append({"id": pid, "name": clean(m.get("n", pid)), "bundle_id": clean(m.get("b", ""), 80), "bundle_path": clean(m.get("p", ""), 200),
                    "cores_5m": s / n, "rss_mb": int(it[1]) if here else 0, "cpu_now": float(latest[pid][0]) if here else 0.0, "present": bool(here),
                    "protected": bool(flag & 1), "hosts_build": bool(flag & 2), "excluded": None})
    out.sort(key=lambda a: -a["cores_5m"])
    return out


def hold_active(held, now, cfg):
    """(old, live): the holds refused for hold_s or longer, and those of them whose refusals include a gate that quitting a desktop app can relieve
    (C4a, C4b). `live` non-empty is the "a build is waiting because of desktop apps" condition that both the dialog and the auto-freeze list (B6,
    amended 2026-11-21) start from."""
    tr = cfg["trigger"]
    rel = set(tr["relievable"])
    old = [h for h in held if now - h["refused_since"] >= tr["hold_s"]]
    return old, [h for h in old if rel & set(h.get("refused", []))]


def should_show(held, apps, now, snooze, last_shown, cfg, quiet_set=None):
    """Would the dialog show now? {"show": bool, "reason": str, "sum_cores", "sum_rss_mb", "holds": [...]}. All of (C4):
    (a) some hold has been refused for hold_s or longer; (b) its refusals include a gate that desktop apps can relieve; (c) the SUM
    over non-build, non-protected apps of their 5-min mean cores is at least min_cores, or the sum of their RSS at least min_rss_mb
    (an app that hosts a build counts without the build); (d) rate_s since the dialog was last shown, and the Ignore snooze
    (`snooze`, an epoch or None) expired. `reason` names the first check that failed, in that order."""
    tr = cfg["trigger"]
    snooze = snooze if _fin(snooze) else None
    last_shown = last_shown if _fin(last_shown) and last_shown <= now else None   # a clock set back must not silence the trigger
    old, live = hold_active(held, now, cfg)
    always = quiet_ids(cfg, apps, now) if quiet_set is None else quiet_set
    pool = [a for a in apps if not a.get("protected") and not a.get("excluded") and not quiet(a, always)]   # an always-freeze app is frozen, not asked about (Q3)
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
    _jsonl_append(dry_run_path(state_dir), entry)


def events_path(state_dir):
    return gui_dir(state_dir) / "events.jsonl"


def events_append(state_dir, event, **fields):
    """One line in gui-hog/events.jsonl: what the operator clicked or what the sampler did (`by` says who). Strings are cleaned (J3). Raises on an OS error."""
    entry = {"t": _iso(time.time()), "event": clean(event, 40)}
    entry.update({k: (clean(v, 120) if isinstance(v, str) else v) for k, v in fields.items()})
    _jsonl_append(events_path(state_dir), entry)


def _jsonl_append(p, entry):
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


def would_show_line(decision, apps, t, load1, cfg, my_uid, quiet_set=None):
    """The dry-run record for a decision that says show. Names are cleaned text (J3); the rows are the busiest few."""
    tr = cfg["trigger"]
    always = quiet_ids(cfg, apps, t) if quiet_set is None else quiet_set
    rows = [a for a in apps if not a.get("protected") and not quiet(a, always)
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


# ---- the snapshot the dialog reads (D3) and the small state files it writes through us (D5) ---------------------------------
SNAPSHOT_MAX_ROWS = 12
DEFAULT_AGENT_CLIS = frozenset({"claude", "codex", "opencode", "omp", "pi", "gemini", "copilot", "cursor-agent", "agy",
                                "crush", "kimi", "qwen", "goose", "aider", "amp", "droid", "kiro-cli", "paseo"})   # = load-watch AGENT_CLIS (a test pins it)
VET_OK, VET_PROTECTED, VET_CHANGED, VET_BUILD, VET_GONE = 0, 3, 4, 5, 6


def _gui_dir_ready(state_dir):
    d = gui_dir(state_dir)
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not safe_dir(d):
        raise OSError(f"{d} is not a real directory of this user")
    return d


def atomic_json(path, obj):
    """Write `obj` as JSON to `path` (mode 0600) through a unique temp file in the same directory, then os.replace (D5: a fixed temp name would let
    two writers clobber each other). Raises on an OS error."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".gh-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_snooze(state_dir, now, minutes):
    """Ignore (D5): snooze_until = now + minutes, in gui-hog/snooze.json. The sampler only reads it and clamps it to snooze_s."""
    until = int(now + 60 * max(1, min(int(minutes), 24 * 60)))
    atomic_json(_gui_dir_ready(state_dir) / "snooze.json", {"snooze_until": until})
    return until


def record_exit(state_dir, code, now):
    """The dialog's own outcome (D5): gui-hog/last-exit.json. The sampler reads it on its next tick."""
    atomic_json(_gui_dir_ready(state_dir) / "last-exit.json", {"code": int(code), "at": int(now), "by": "dialog"})


def read_last_exit(state_dir):
    try:
        if not safe_dir(gui_dir(state_dir)):
            return None
        r = json.loads(read_small(gui_dir(state_dir) / "last-exit.json"))
        return r if isinstance(r, dict) and type(r.get("code")) is int and _fin(r.get("at")) else None
    except Exception:  # noqa: BLE001 - a corrupt file is no exit record
        return None


def parse_lstart(text):
    """Epoch seconds of a `ps -o lstart=` string (C locale, UTC), or None (also for the Linux `proc:` form)."""
    try:
        return calendar.timegm(time.strptime(" ".join(str(text).split()), "%a %b %d %H:%M:%S %Y"))
    except (ValueError, OverflowError):
        return None


def window_total(st, t, cfg):
    """The 5-minute mean of the machine's total cores (the header's sliding average, B2), or None without samples."""
    win = [x["cpu"] for x in (st.get("apps") if isinstance(st.get("apps"), list) else [])
           if isinstance(x, dict) and _fin(x.get("t")) and _fin(x.get("cpu")) and t - cfg["trigger"]["window_s"] <= x["t"] <= t]
    return sum(win) / len(win) if win else None


def build_snapshot(means, held, now, cfg, *, load=None, ncpu=None, cpu_5m=None, starts=None, manual=False, sources=None, sources_more=0, quiet_set=None):
    """The dialog's whole input (D3, E1, E2): header numbers, one line per held build, the rows (busiest first, up to 12, then `more`) and the
    protected-hidden count. No command lines, only cleaned text. A row carries `present` (the app is in the newest sample): the dialog offers
    Quit and Force Quit on a present row that does not host a build, and nowhere else. `starts` maps a root pid to its live start string."""
    tr = cfg["trigger"]
    starts = starts or {}
    always = quiet_ids(cfg, means, now) if quiet_set is None else quiet_set
    rows = [a for a in means if not a["protected"] and not quiet(a, always) and (a["cores_5m"] >= tr["min_row_cores"] or a["rss_mb"] >= tr["min_row_rss_mb"])]
    out = []
    for a in rows[:SNAPSHOT_MAX_ROWS]:
        pid = int(a["id"]) if str(a["id"]).isdigit() else 0
        st_s = starts.get(pid) if a.get("present") else None
        out.append({"app_id": str(a["id"]), "name": a["name"], "bundle_id": a["bundle_id"], "bundle_path": a["bundle_path"], "root_pid": pid,
                    "root_start": st_s or "", "root_start_epoch": parse_lstart(st_s) if st_s else None,
                    "cores_5m": round(a["cores_5m"], 2), "cpu_now": round(a.get("cpu_now", 0.0), 2), "rss_mb": int(a["rss_mb"]),
                    "present": bool(a.get("present")), "hosts_build": bool(a.get("hosts_build")), "frozen": False})
    return {"v": 1, "t": int(now), "manual": bool(manual),
            "header": {"load": [round(x, 2) for x in load] if load else None, "ncpu": ncpu, "cpu_5m": None if cpu_5m is None else round(cpu_5m, 2)},
            "holds": [{"caller": h["caller"], "held_s": int(max(0, now - h["refused_since"])), "refused": h["refused"]} for h in held],
            "rows": out, "more": max(0, len(rows) - SNAPSHOT_MAX_ROWS), "protected_hidden": sum(1 for a in means if a["protected"]),
            "rss_trigger": sum(a["rss_mb"] for a in means if not a["protected"]) >= tr["min_rss_mb"],
            # Q2: what actually uses the cores, whatever it is (builds, agents, apps, system processes); display only, a row never carries an action
            "sources": list(sources or []), "sources_more": int(sources_more),
            "freeze": {"enabled": bool(cfg.get("freeze", {}).get("enabled", True)), "default_minutes": int(cfg.get("freeze", {}).get("default_minutes", 10))}}


def write_snapshot(state_dir, snap):
    atomic_json(_gui_dir_ready(state_dir) / "snapshot.json", snap)


# ---- the bundle, the single-instance lock and the detached launch (C5, D2, D5) ----------------------------------------------------
def bundle_dir():
    return Path(os.environ.get("LW_GUI_HOG_BUNDLE") or HOME / ".local/libexec/djbclark-ade/ADE GUI Hog.app")


def bundle_exe(bundle=None):
    return Path(bundle or bundle_dir()) / "Contents" / "MacOS" / "ade-gui-hog"


def swift_dir():
    return ADE / "macos" / "gui-hog"


BUILD_RECIPE = "1"   # bump when bin/ade-gui-build's flags change, so every bundle counts as stale once


def source_hash(src=None):
    """SHA-256 over the Swift sources and Info.plist (names and bytes, sorted) and the build recipe: what `ade-gui-build` stamps into the bundle."""
    src = Path(src or swift_dir())
    h = hashlib.sha256(BUILD_RECIPE.encode())
    names = sorted([p.name for p in src.glob("*.swift")] + (["Info.plist"] if (src / "Info.plist").exists() else []))
    if not names:
        return None
    for n in names:
        h.update(n.encode() + b"\0" + (src / n).read_bytes() + b"\0")
    return h.hexdigest()


def bundle_state(bundle=None, src=None):
    """("ok"|"missing"|"stale", detail). Never builds. A bundle whose stamp does not match the sources, or sources that cannot be read, is stale: no dialog."""
    b = Path(bundle or bundle_dir())
    exe = bundle_exe(b)
    try:
        if not (exe.is_file() and os.access(exe, os.X_OK)):
            return "missing", f"no executable at {exe}"
        want = source_hash(src)
        have = (b / "Contents" / "Resources" / "source.sha256").read_text().strip()
    except OSError as e:
        return "stale", f"cannot read the stamp or the sources: {e}"
    if want is None:
        return "stale", "no Swift sources found"
    return ("ok", "") if want == have else ("stale", "sources changed since the bundle was built (run bin/ade-gui-build)")


def dialog_running(state_dir, lock="dialog.lock"):
    """True when a dialog holds gui-hog/dialog.lock (the dialog flocks it for its whole life: F8-13). A flock dies with its process, so a crash never
    leaves a stale lock. False when the directory does not exist yet. `lock="status.lock"` asks about the menu-bar item of PR 3c (E5) instead."""
    d = gui_dir(state_dir)
    if not safe_dir(d):
        return False
    try:
        fd = os.open(d / lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


def launch_dialog(state_dir, *, bundle=None, extra=(), popen=subprocess.Popen, python=None, lock="dialog.lock"):
    """Start the dialog detached and return (True, "") or (False, why). Argv list, no shell; `start_new_session`, `close_fds`, stdin and stdout
    on /dev/null, stderr on gui-hog/dialog.log (mode 0600, cut at 256 KB); never waited on, so the build never waits on the dialog (C5). The
    dialog gets the interpreter and `bin/gui-hog` to run its actions with (D4); it never builds anything here (D2)."""
    state, detail = bundle_state(bundle)
    if state != "ok":
        return False, f"bundle-{state}"
    if dialog_running(state_dir, lock):
        return False, "running"
    d = _gui_dir_ready(state_dir)
    logp = d / "dialog.log"
    try:
        if os.lstat(logp).st_size > 256 * 1024:
            os.unlink(logp)
    except OSError:
        pass
    try:   # O_NONBLOCK: a FIFO planted at dialog.log must fail the open, not block the sampler (adversary round 1, finding 4)
        errfd = os.open(logp, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    except OSError:
        return False, "log-unsafe"
    if not stat.S_ISREG(os.fstat(errfd).st_mode):
        os.close(errfd)
        return False, "log-unsafe"
    try:
        argv = [str(bundle_exe(bundle)), "--state-dir", str(state_dir), "--python", python or sys.executable,
                "--gui-hog", str(Path(__file__).resolve().parent / "gui-hog"), *extra]
        popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errfd, close_fds=True, start_new_session=True)
    finally:
        os.close(errfd)
    return True, ""


# ---- the live checks before a Quit or Force Quit (D4) --------------------------------------------------------------------------------
def collect_table(timeout=15):
    """(table, rss_kb, ttys) from one `ps` call, in the shape `group_apps` takes ({pid str: (ppid int, uid int, cores, command)}), or None when ps fails or times out."""
    try:
        r = subprocess.run(["ps", "-axo", "pid=,ppid=,uid=,%cpu=,rss=,tty=,command="], capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, LC_ALL="C"))
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    table, rss, ttys = {}, {}, set()
    for line in r.stdout.splitlines():
        parts = line.split(None, 6)
        if len(parts) < 6 or not parts[0].isdigit():
            continue
        try:
            table[parts[0]] = (int(parts[1]), int(parts[2]), float(parts[3]) / 100, parts[6] if len(parts) > 6 else "")
            rss[parts[0]] = int(parts[4]) if parts[4].isdigit() else 0
        except ValueError:
            continue
        if parts[5] not in ("??", "?", "-"):
            ttys.add(parts[0])
    return table, rss, ttys


def default_name_of(exe_of, name_of=None):
    """The short-name lookup the sampler pairs with `exe_of`: an explicit `name_of` as given; else the kernel's `kernel_name` when `exe_of` is the real
    `kernel_exe` (production), else None (a test's fake `exe_of` must never be paired with a lookup of REAL pids)."""
    return name_of if name_of is not None else (kernel_name if exe_of is kernel_exe else None)


def verify_identity(pid, expect_start, *, start_of=proc_start, exe_of=kernel_exe):
    """The pid-reuse check made right before an action (F3, carry-over e): the process exists, its executable path is readable and its start time
    equals `expect_start` (a non-empty string from the snapshot's `root_start`). Returns (ok, reason)."""
    if not expect_start:
        return False, "no start time to compare (the app was not in the newest sample)"
    live = start_of(pid)
    if live is None:
        return False, "the process is gone"
    if live != expect_start:
        return False, f"pid {pid} now has another start time (pid reuse)"
    if not exe_of(pid):
        return False, "no kernel executable path for the process"
    return True, ""


def vet(pid, expect_start, expect_bundle_id, expect_bundle_path="", *, state_dir, my_uid, cfg=None, agent_clis=DEFAULT_AGENT_CLIS,
        start_of=proc_start, exe_of=kernel_exe, table_fn=collect_table, lsapps_fn=collect_lsappinfo, plist_of=_plist_id):
    """May the dialog quit this app? (code, reason, info). Everything is read from the LIVE pid and the live process table, never from the snapshot
    (a snapshot can be 20 s old or tampered with): 4 when the pid is not the process the snapshot saw (start time, bundle id or bundle path differ),
    3 when the live bundle is protected or part of a build, 5 when the app hosts a build or terminal subtree (the walk of C4b, re-run now), 6 when the
    process is gone or ps failed. 0 only when all of that is clean. The arguments are expected values: a mismatch is a refusal, never a lookup key."""
    cfg = cfg or load_config()
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return VET_GONE, "bad pid", {}
    if not 1 < pid < 2 ** 31:
        return VET_GONE, "bad pid", {}
    ok, why = verify_identity(pid, expect_start, start_of=start_of, exe_of=exe_of)
    if not ok:
        return (VET_GONE if "gone" in why else VET_CHANGED), why, {}
    exe = exe_of(pid)
    live_path = _app_prefix(_real(exe)) if exe else None
    if not live_path:
        return VET_CHANGED, "the live executable is not inside an .app bundle", {}
    live_id = plist_of(live_path)
    if (expect_bundle_id or "").casefold() != (live_id or "").casefold():
        return VET_CHANGED, "the live bundle id differs from the one the dialog showed", {"bundle_id": clean(live_id or "", 80)}
    if expect_bundle_path and _real(expect_bundle_path) != _real(live_path):
        return VET_CHANGED, "the live bundle path differs from the one the dialog showed", {}
    got = table_fn()
    if got is None:
        return VET_GONE, "ps failed or timed out: no signal is sent without a live look", {}
    table, rss, ttys = got
    holds = read_holds(state_dir, time.time(), sweep=False, check_start=False)
    held_pids = [h["pid"] for h in holds] + [h["caller_pid"] for h in holds if h.get("caller_pid")]
    apps = group_apps(table, rss, ttys, lsapps_fn(), exe_of=exe_of, my_uid=my_uid, held_pids=held_pids, agent_clis=agent_clis, cfg=cfg)
    me = next((a for a in apps if a["root_pid"] == pid), None)
    if me is None:
        return VET_CHANGED, "the pid is not the root of a GUI app now", {}
    info = {"bundle_id": clean(me["bundle_id"] or "", 80), "name": clean(me["name"])}
    if me["protected"]:
        return VET_PROTECTED, f"protected ({me['protected']})", info
    if me["excluded"]:
        return VET_PROTECTED, f"part of a build ({me['excluded']})", info
    if me["hosts_build"]:
        return VET_BUILD, "the app has a terminal or build inside: no actions", info
    return VET_OK, "", info


# ---- the sampler's step -------------------------------------------------------------------------------------------------------------
def _has_frozen(state_dir):
    """True while something is frozen (the history ring is then kept on disk so the resume can be judged); False when that cannot be read."""
    try:
        import gui_hog_freeze
        return gui_hog_freeze.has_entries(state_dir)
    except Exception:  # noqa: BLE001
        return False


def _manual_snapshot_live(state_dir, t):
    """True while the operator's `gui-hog show` window is open on a snapshot it wrote (`manual`, under 30 min old): the sampler leaves that snapshot alone,
    so a manual test on a small app (`show --all`) is not overwritten by the next tick's thresholds."""
    try:
        snap = json.loads(read_small(gui_dir(state_dir) / "snapshot.json"))
        return bool(snap.get("manual")) and _fin(snap.get("t")) and 0 <= t - snap["t"] < 1800 and dialog_running(state_dir)
    except Exception:  # noqa: BLE001
        return False


def _note_exit(state_dir, gh, t):
    """D5: log the dialog's own exit record once (`dialog-exit`); a no-GUI exit (69) keeps the trigger quiet for the rate limit."""
    r = read_last_exit(state_dir)
    if r and r["at"] > gh.get("exit_seen", 0):
        gh["exit_seen"] = r["at"]
        events_append(state_dir, "dialog-exit", code=r["code"], by="sampler", note={69: "no-gui", 70: "internal-error", 75: "already-running"}.get(r["code"], ""))
        if r["code"] == 69:
            gh["last_shown"] = t


START_SLACK_S = 2   # `ps -o lstart=` has one-second resolution


def auto_starts(roots, held, t, start_of=None):
    """(starts, late) for the auto-freeze roots of one tick (PR 859 adversary low 2). `starts` is {pid: start string}, read in ONE batch call (or `start_of`
    one by one) and only while a build is held, since the step does nothing without a hold: the sampler no longer spawns a `ps` per listed app on every
    tick. `late` is the set of root pid strings whose process STARTED AFTER the table was read (`t`, more than START_SLACK_S later): that process is not
    the instance the table showed (a relaunch, or a reused pid), so its start is not handed on and the app is left out of this tick's step. A start the
    clock cannot parse (the Linux `proc:` form) is accepted, as `freeze()` re-checks the four identity fields against the live process anyway."""
    if not held or not roots:
        return {}, set()
    got = {p: s for p in roots if (s := start_of(p)) is not None} if start_of else proc_starts(roots)
    starts, late = {}, set()
    for p, s in got.items():
        epoch = parse_lstart(s)
        if epoch is not None and epoch > t + START_SLACK_S:
            late.add(str(p))
        else:
            starts[p] = s
    return starts, late


def tick(st, t, table, rss_kb, ttys, *, state_dir, my_uid, agent_clis=(), total_cores=None, load1=None, dry=False,
         cfg=None, lsapps=None, exe_of=kernel_exe, name_of=None, out=print, start_of=None, launch=False, popen=subprocess.Popen,
         load_avg=None, ncpu=None, gui_ok=None, auto_freeze=False, sysread=None):
    """The sampler's whole GUI-hog step (K1): refresh the app window in `st`, read the holds, decide, keep the dialog's snapshot fresh while a hold
    is active or the dialog runs (D3), and on a `show` write the dry-run line (kept in 3b: it is the count of how often the dialog fired) and,
    with `launch`, start the dialog (C5, D6). With `dry` it prints the line and changes nothing but the window. Returns the decision dict, or None
    when LW_GUI_HOG=0. The caller wraps it in a `try`: a failure here never stops load sampling."""
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
    srows, smore = [], 0
    try:   # Q1, Q2: the system readings a freeze is judged against, and what actually uses the cores; never stops the tick
        import gui_hog_savings
        import gui_hog_sources
        if not isinstance(gh.get("hist"), list):
            gh["hist"] = []
        sr = sysread if isinstance(sysread, dict) else {}
        gui_hog_savings.hist_add(gh["hist"], t, sr.get("load1", load1), sr)
        gh["hist"] = gui_hog_savings.clean_hist(gh["hist"])
        srcs = gui_hog_sources.group_sources(table, rss_kb, apps, held_pids=held_pids, agent_clis=agent_clis, exe_of=exe_of,
                                              name_of=default_name_of(exe_of, name_of))
        gui_hog_sources.window_update(gh, t, srcs, total_cores, cfg)
        smeans = gui_hog_sources.window_means(gh, t, cfg)
        top = [m["id"] for m in smeans if m["kind"] in ("build", "agent") and m["present"]][:6]
        srows, smore = gui_hog_sources.snapshot_rows(smeans, cfg, where=None if dry or not (held or dialog_running(state_dir)) else gui_hog_sources.proc_cwds(top))
        if not dry and (held or _has_frozen(state_dir)):
            gui_hog_savings.write_hist(state_dir, gh["hist"])
    except Exception as e:  # noqa: BLE001
        out(f"gui-hog: load sources: {e!r}")
    qset = quiet_for(cfg, means, t, state_dir, gh, held=held)
    d = should_show(held, means, t, effective_snooze(gh, read_snooze(state_dir), t, cfg["trigger"]["snooze_s"], record=True), gh.get("last_shown"), cfg, quiet_set=qset)
    if not dry:
        try:
            _note_exit(state_dir, gh, t)
        except Exception as e:  # noqa: BLE001 - the dialog's bookkeeping never stops the decision
            out(f"gui-hog: dialog exit record: {e!r}")
        if (held or dialog_running(state_dir)) and not _manual_snapshot_live(state_dir, t):
            try:
                rows = [a for a in means if a.get("present") and not a["protected"]][:SNAPSHOT_MAX_ROWS * 2]
                la = load_avg if load_avg is not None else (os.getloadavg() if hasattr(os, "getloadavg") else None)
                write_snapshot(state_dir, build_snapshot(means, held, t, cfg, load=la, ncpu=ncpu or os.cpu_count(), cpu_5m=window_total(st, t, cfg),
                                                         starts=proc_starts([int(a["id"]) for a in rows if str(a["id"]).isdigit()]),
                                                         sources=srows, sources_more=smore, quiet_set=qset))
            except Exception as e:  # noqa: BLE001
                out(f"gui-hog: snapshot: {e!r}")
    if (auto_freeze or dry) and os.environ.get("LW_GUI_HOG_AUTO", "").strip() != "0":   # LW_GUI_HOG_AUTO=0 turns only this off; the operator's auto-freeze list (B6 amended 2026-11-21): only the sampler passes auto_freeze=True; dry prints what it would do
        try:
            import gui_hog_freeze
            snz = effective_snooze(gh, read_snooze(state_dir), t, cfg["trigger"]["snooze_s"])
            order = {str(x).casefold() for x in list(cfg["freeze"]["auto"].get("order", [])) + list(cfg["freeze"]["auto"].get("always", [])) if isinstance(x, str)}
            roots = [int(a["root_pid"]) for a in apps if str(a.get("bundle_id") or "").casefold() in order and str(a.get("root_pid", "")).isdigit()]
            starts, late = auto_starts(roots, held, t, start_of)
            step_apps = [a for a in apps if str(a.get("root_pid", "")) not in late]   # a relaunch in the gap: this tick leaves that app alone (PR 859 low 2)
            r = gui_hog_freeze.auto_freeze_step(gh, state_dir, step_apps, held, t, cfg, my_uid=my_uid, agent_clis=agent_clis, dry=dry or not auto_freeze,
                                                starts=starts, snoozed=snz is not None and t < snz)
            if r:
                out(("gui-hog would auto-freeze " if r.get("dry") else "gui-hog auto-freeze ") + json.dumps(r, separators=(",", ":"), default=str))
        except Exception as e:  # noqa: BLE001 - the auto-freeze never stops a sample, the dialog or the decision
            out(f"gui-hog: auto-freeze: {e!r}")
    if d["show"]:
        line = would_show_line(d, means, t, load1, cfg, my_uid, quiet_set=qset)
        if dry:
            out("gui-hog would show dialog: " + json.dumps(line, separators=(",", ":")))
        else:
            ok = gui_session(my_uid) if gui_ok is None else gui_ok
            line["launch"] = "off" if not launch else ("no-gui" if not ok else "pending")
            gh["last_shown"] = t   # before the launch and the log line: a failure in either must not make the dialog return every 20 s
            if launch and ok:
                try:
                    started, why = launch_dialog(state_dir, popen=popen)
                except Exception as e:  # noqa: BLE001 - a failed launch is a log line, never a failed sample
                    started, why = False, f"error: {e!r}"[:120]
                line["launch"] = "started" if started else why
                if why.startswith("bundle-") and t - gh.get("bundle_noted", 0) >= 86400:   # D2: one line a day for a missing or stale bundle
                    gh["bundle_noted"] = t
                    events_append(state_dir, "bundle-" + why[7:], by="sampler")
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
    qset = quiet_for(cfg, means, now, state_dir, ghs, held=held)
    d = should_show(held, means, now, snooze, last, cfg, quiet_set=qset)
    bstate, bdetail = bundle_state()
    lines = [f"gui-hog (PR 3b: the window is live) {'ENABLED' if enabled() else 'OFF (LW_GUI_HOG=0)'}",
             f"dialog bundle: {bstate}" + (f" ({bdetail})" if bdetail else "") + f" at {bundle_dir()}; dialog running: {'yes' if dialog_running(state_dir) else 'no'}",
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
        lines.append(f"  {a['cores_5m']:5.2f} cores {int(a['rss_mb']):6d} MB  {a['name']}  [{a['bundle_id'] or 'no bundle id'}]"
                     + ("  has a build or terminal inside: no actions" if a["hosts_build"] else ""))
    if len(rows) > 12:
        lines.append(f"  +{len(rows) - 12} more")
    lines.append(f"{sum(1 for a in means if a['protected'])} protected apps hidden")
    always = always_apps(cfg)
    if cfg["freeze"]["auto"].get("always"):
        lines.append("always-freeze list (frozen without asking, no dialog row): " + (", ".join(sorted(always)) or "none in effect")
                     + "".join(f"; IGNORED {b}: {w}" for b, w in always_problems(cfg)))
    try:
        import gui_hog_sources
        sm = gui_hog_sources.window_means(ghs, now, cfg)
        srows, smore = gui_hog_sources.snapshot_rows(sm, cfg, limit=12)
        lines.append(f"load sources (what uses the cores, {tr['window_s']} s mean; shown, only apps marked can-freeze may be frozen):" + ("" if srows else " none yet"))
        for r in srows:
            lines.append(f"  {r['cores_5m']:5.2f} cores {r['share'] * 100:3.0f}%  {r['rss_mb']:6d} MB  {r['kind']:<6} {r['name']}"
                         + (f" (owner: {r['owner']})" if r["owner"] else "") + (f", heaviest {r['heaviest']}" if r["heaviest"] and r["kind"] != "app" else "")
                         + (" [waiting]" if r["waiting"] else "") + ("  can freeze" if r["can_freeze"] else f"  {r['why']}"))
        if smore:
            lines.append(f"  +{smore} more")
    except Exception as e:  # noqa: BLE001
        lines.append(f"load sources: unreadable ({e!r})")
    lines.append(f"dry-run log: {dry_run_path(state_dir)} ({count_dry_run(state_dir, 7, now)} would-show lines in the last 7 days); events: {events_path(state_dir)}")
    return lines
