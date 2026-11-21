"""gui_hog_savings: what a freeze actually saved, and which apps belong on which list (docs/gui-hog-dialog.md section Q1, operator ruling 2026-11-21).

    hist_add / clean_hist / window_metrics   a ring of system readings (load, compressor, pageins, swap-ins) the sampler keeps while a build is held or an app is frozen
    before_measure / result                  the numbers recorded when an app is frozen, and the `freeze-result` event written when it is resumed
    read_events / read_would_show            the history on disk (events.jsonl, dry-run.jsonl, and their `.1` files)
    suggest / suggest_lines                  `gui-hog suggest`: proposals for `[freeze.auto] skip` and `[freeze.auto] always`, with the evidence; edits nothing

WHAT IS MEASURED, plainly: a SIGSTOP frees no memory. The resident set of a frozen app stays resident until the system compresses or swaps it under
pressure, so `rss_freed_mb` is always 0 here and RSS is recorded only to show what the app holds. What a freeze buys is CPU (the app's cores before the
freeze stop being used) and, indirectly, less pressure on the compressor and the page-in rate. The system numbers are the mean load and the compressor,
page-in and swap-in rates over the freeze window against the same-length window just before it; they are EVIDENCE, not proof: the build that the freeze let
in starts in the second window and adds load of its own, so the load delta can be positive for a freeze that did exactly what it should.

Stdlib only; reads and writes only the small files named here under <state_dir>/gui-hog. Nothing here signals a process.
"""
import calendar
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gui_hog as gh  # noqa: E402

HIST_FILE = "sys-hist.json"
HIST_MAX = 180            # readings kept: one hour at the sampler's 20 s
GAP_S = 120               # two readings further apart than this straddle a sleep or a stall: that pair counts toward no rate
MIN_WINDOW_S, MAX_WINDOW_S, DEFAULT_WINDOW_S = 120, 1800, 600
RATE_KEYS = ("compress_s", "pageins_s", "swapins_s")


# ---- the ring of system readings --------------------------------------------------------------------------------------------------------------
def _f(x):
    """x as a float, or None unless it is a finite number."""
    return float(x) if gh._fin(x) else None


def hist_add(ring, t, load1, mem):
    """Append one reading [t, load1, compress, pageins, swapins] (a counter is cumulative; None when it could not be read) and keep the last HIST_MAX.
    A time that does not move forward is ignored (a clock set back must not reorder the ring)."""
    if not gh._fin(t) or (ring and ring[-1][0] >= t):
        return
    mem = mem if isinstance(mem, dict) else {}
    ring.append([round(float(t), 1), _f(load1), _f(mem.get("compress")), _f(mem.get("pageins")), _f(mem.get("swapins"))])
    del ring[:-HIST_MAX]


def clean_hist(raw):
    """The valid rows of a ring read from disk (data: any wrong shape is dropped, the time must increase)."""
    out = []
    for r in raw if isinstance(raw, list) else []:
        if isinstance(r, list) and len(r) == 5 and gh._fin(r[0]) and all(x is None or gh._fin(x) for x in r[1:]) and (not out or r[0] > out[-1][0]):
            out.append([float(r[0])] + [None if x is None else float(x) for x in r[1:]])
    return out[-HIST_MAX:]


def write_hist(state_dir, ring):
    gh.atomic_json(gh._gui_dir_ready(state_dir) / HIST_FILE, {"v": 1, "rows": ring})


def read_hist(state_dir):
    try:
        if not gh.safe_dir(gh.gui_dir(state_dir)):
            return []
        obj = json.loads(gh.read_small(gh.gui_dir(state_dir) / HIST_FILE))
        return clean_hist(obj.get("rows")) if isinstance(obj, dict) and obj.get("v") == 1 else []
    except Exception:  # noqa: BLE001 - a missing or hostile file is no history
        return []


def window_metrics(ring, a, b):
    """{n, span_s, load, compress_s, pageins_s, swapins_s} over the readings with a <= t <= b, or None without any. `load` is the mean 1-minute load;
    a rate is the counter's rise over the time of the consecutive pairs that are at most GAP_S apart (None for a counter that was unreadable, went
    backwards, or has no such pair). The numbers are read as they are: nothing is smoothed or filled in."""
    rows = [r for r in ring if a <= r[0] <= b]
    if not rows:
        return None
    loads = [r[1] for r in rows if r[1] is not None]
    out = {"n": len(rows), "span_s": int(rows[-1][0] - rows[0][0]), "load": round(sum(loads) / len(loads), 2) if loads else None}
    for i, key in enumerate(RATE_KEYS, start=2):
        num = den = 0.0
        for p, q in zip(rows, rows[1:]):
            dt = q[0] - p[0]
            if 0 < dt <= GAP_S and p[i] is not None and q[i] is not None and q[i] >= p[i]:
                num, den = num + (q[i] - p[i]), den + dt
        out[key] = round(num / den, 1) if den > 0 else None
    return out


# ---- the numbers recorded at a freeze and at its resume ---------------------------------------------------------------------------------------
def window_for(planned_s):
    """The length of the window before a freeze: the freeze's own planned length (10 minutes when it is indefinite), 2 to 30 minutes."""
    return int(min(MAX_WINDOW_S, max(MIN_WINDOW_S, planned_s if gh._fin(planned_s) and planned_s > 0 else DEFAULT_WINDOW_S)))


def before_measure(ring, now, planned_s, cores, rss_mb):
    """What `freeze` stores in the entry: the app's freeable cores and RSS just before the signal, and the system window just before it."""
    w = window_for(planned_s)
    return {"w": w, "cores": round(max(0.0, float(cores)), 2), "rss_mb": int(max(0, rss_mb)), "sys": window_metrics(ring, now - w, now)}


def norm_measure(m):
    """The validated `measure` of a stored entry, or None (frozen.json is data)."""
    try:
        if not isinstance(m, dict) or not gh._fin(m.get("w")) or not gh._fin(m.get("cores")) or not gh._fin(m.get("rss_mb")):
            return None
        s = m.get("sys")
        if isinstance(s, dict):
            s = {k: (s[k] if gh._fin(s.get(k)) else None) for k in ("n", "span_s", "load") + RATE_KEYS}
        else:
            s = None
        return {"w": int(min(MAX_WINDOW_S, max(0, m["w"]))), "cores": round(float(m["cores"]), 2), "rss_mb": int(m["rss_mb"]), "sys": s}
    except Exception:  # noqa: BLE001
        return None


def result(entry, ring, now):
    """The `freeze-result` event body for a resumed entry that carries a `measure`. `delta` is during minus before for every figure present in both."""
    m = entry["measure"]
    during = window_metrics(ring, entry["frozen_at"], now)
    before = m.get("sys")
    delta = {}
    if before and during:
        for k in ("load",) + RATE_KEYS:
            if before.get(k) is not None and during.get(k) is not None:
                delta[k] = round(during[k] - before[k], 2)
    return {"entry": entry["id"], "app": entry["app"], "bundle_id": entry["app"].get("bundle_id", ""), "mode": entry["mode"], "froze_by": entry["by"],
            "held_s": int(max(0, now - entry["frozen_at"])), "window_s": m["w"], "cores_before": m["cores"], "rss_mb": m["rss_mb"],
            "cores_freed_est": m["cores"], "rss_freed_mb": 0, "before": before, "during": during, "delta": delta}


# ---- the history on disk ----------------------------------------------------------------------------------------------------------------------
def _lines(path, cap=4 * gh.DRY_RUN_MAX_BYTES):
    for f in (path.with_name(path.name + ".1"), path):
        try:
            text = gh.read_small(f, cap)
        except OSError:
            continue
        for ln in text.splitlines():
            try:
                r = json.loads(ln)
            except (ValueError, RecursionError):
                continue
            if isinstance(r, dict) and isinstance(r.get("t"), str):
                try:
                    r["_t"] = calendar.timegm(time.strptime(r["t"], "%Y-%m-%dT%H:%M:%SZ"))
                except (ValueError, OverflowError):
                    continue
                yield r


def read_events(state_dir, days, now, event="freeze-result"):
    """The `event` lines of events.jsonl (and its `.1`) from the last `days` days, oldest first."""
    cutoff = now - days * 86400
    return [r for r in _lines(gh.events_path(state_dir)) if r.get("event") == event and r["_t"] >= cutoff]


def read_would_show(state_dir, days, now):
    """The `would-show` lines of dry-run.jsonl (and its `.1`) from the last `days` days: what the dialog was about to list, with each app's cores and RSS."""
    cutoff = now - days * 86400
    return [r for r in _lines(gh.dry_run_path(state_dir)) if r.get("event") == "would-show" and r["_t"] >= cutoff]


# ---- suggestions --------------------------------------------------------------------------------------------------------------------------------
def _stats(vals):
    return {"n": len(vals), "median": round(statistics.median(vals), 2), "max": round(max(vals), 2)} if vals else None


def collect(results, shows):
    """{bundle id (casefolded): {name, freezes: [cores_before], rss: [..], held: [..], load_delta: [..], shows: [cores_5m], show_rss: [..], hosts_build: n}}."""
    per = {}

    def slot(bid, name):
        return per.setdefault(bid.casefold(), {"bundle_id": bid, "name": name or bid, "freezes": [], "rss": [], "held": [], "load_delta": [], "shows": [],
                                                  "show_rss": [], "hosts_build": 0})
    for r in results:
        bid = r.get("bundle_id")
        if not isinstance(bid, str) or not bid or not gh._fin(r.get("cores_before")) or not gh._fin(r.get("held_s")) or r["held_s"] < 60:
            continue   # a freeze held under a minute (an immediate Resume, a rollback) says nothing about what it saves
        s = slot(bid, (r.get("app") or {}).get("name") if isinstance(r.get("app"), dict) else "")
        s["freezes"].append(float(r["cores_before"]))
        s["rss"].append(float(r["rss_mb"]) if gh._fin(r.get("rss_mb")) else 0.0)
        s["held"].append(float(r["held_s"]))
        d = r.get("delta") if isinstance(r.get("delta"), dict) else {}
        if gh._fin(d.get("load")):
            s["load_delta"].append(float(d["load"]))
    for line in shows:
        for a in line.get("apps", []) if isinstance(line.get("apps"), list) else []:
            if isinstance(a, dict) and isinstance(a.get("bundle_id"), str) and a["bundle_id"] and gh._fin(a.get("cores_5m")):
                s = slot(a["bundle_id"], a.get("name"))
                s["shows"].append(float(a["cores_5m"]))
                s["show_rss"].append(float(a["rss_mb"]) if gh._fin(a.get("rss_mb")) else 0.0)
                s["hosts_build"] += 1 if a.get("hosts_build") else 0
    return per


def suggest(cfg, results, shows, my_uid=None):
    """The proposals, from the history and the config. Nothing is edited. Returns {"never_auto": [...], "always": [...], "notes": [...], "apps": {...}}:
    each proposal is {bundle_id, name, why, evidence: [text, ...]}.

    never-auto (`[freeze.auto] skip`) when the app is not on it already and EITHER freezing it breaks something we depend on (the config's
    `[freeze.depends]`: the Beeper MCP port, the CodexBar quota feeder), OR at least `min_events` measured freezes (or dialog sightings, when it was
    never frozen) show a median under `negligible_cores`.
    always (`[freeze.auto] always`) when it is on neither list, nothing we know depends on it, it never hosted a build and is not protected, and
    at least `min_events` freezes (or sightings) show a median of `large_cores` or more."""
    sg = cfg.get("suggest", {})
    min_n, neg, large = int(sg.get("min_events", 3)), float(sg.get("negligible_cores", 0.10)), float(sg.get("large_cores", 0.50))
    au = cfg["freeze"]["auto"]
    skip = {x.casefold() for x in au.get("skip", [])}
    always = {x.casefold() for x in au.get("always", [])}
    deps = {k.casefold(): v for k, v in (cfg["freeze"].get("depends") or {}).items() if isinstance(v, list)}
    per = collect(results, shows)
    uid = os.getuid() if my_uid is None else my_uid
    never, alw, notes, apps = [], [], [], {}
    for key in sorted(set(per) | set(deps) | skip | always):
        s = per.get(key, {"bundle_id": key, "name": key, "freezes": [], "rss": [], "held": [], "load_delta": [], "shows": [], "show_rss": [], "hosts_build": 0})
        bid, name = s["bundle_id"], gh.clean(s["name"], 60)
        measured, seen = _stats(s["freezes"]), _stats(s["shows"])
        basis, label = (measured, "measured freezes") if measured and measured["n"] >= min_n else ((seen, "dialog sightings") if seen and seen["n"] >= min_n else (None, ""))
        ev = []
        if measured:
            ev.append(f"{measured['n']} freezes: cores before the freeze median {measured['median']:.2f}, max {measured['max']:.2f}; RSS median "
                      f"{statistics.median(s['rss']):.0f} MB (a freeze frees none of it)"
                      + (f"; load during minus before: median {statistics.median(s['load_delta']):+.2f}" if s["load_delta"] else ""))
        if seen:
            ev.append(f"{seen['n']} dialog sightings: cores (5-min mean) median {seen['median']:.2f}, max {seen['max']:.2f}")
        apps[bid] = {"name": name, "freezes": measured, "sightings": seen, "hosts_build": s["hosts_build"], "depends": deps.get(key, [])}
        if gh.protect_reason(bid, None, None, uid, uid, cfg):
            if key in always:
                notes.append(f"{bid} is protected: it is ignored on the always-freeze list")
            continue
        dep = deps.get(key) or []
        if key in always and key in skip:
            notes.append(f"{bid} is on the always-freeze list but also on the never-auto list (that wins)")
        elif key in always and dep:
            notes.append(f"{bid} is on the always-freeze list but something depends on it ({'; '.join(dep)})")
        if key not in skip:
            if dep:
                never.append({"bundle_id": bid, "name": name, "why": "freezing it breaks something we depend on", "evidence": [*dep, *ev]})
            elif basis and basis["median"] < neg:
                never.append({"bundle_id": bid, "name": name, "why": f"negligible savings (median under {neg:g} cores over {basis['n']} {label})",
                                          "evidence": ev})
        if key not in always and key not in skip and not dep and not s["hosts_build"] and basis and basis["median"] >= large:
            alw.append({"bundle_id": bid, "name": name, "why": f"large savings (median {basis['median']:.2f} cores over {basis['n']} {label}) "
                                  "and nothing known depends on it", "evidence": ev})
    return {"never_auto": never, "always": alw, "notes": notes, "apps": apps}


def suggest_lines(sug, days):
    """The text `gui-hog suggest` prints. It states every figure's source and ends by saying nothing was edited."""
    lines = [f"gui-hog suggest: history of the last {days} days (events.jsonl freeze-result lines, dry-run.jsonl would-show lines)"]
    for title, key, target in (("Propose for the never-auto list ([freeze.auto] skip)", "never_auto", "skip"),
                               ("Propose for the always-freeze list ([freeze.auto] always)", "always", "always")):
        rows = sug[key]
        lines.append(f"{title}: " + ("none" if not rows else ""))
        for r in rows:
            lines.append(f"  {r['bundle_id']}  ({r['name']}): {r['why']}")
            lines.extend(f"      {e}" for e in r["evidence"])
            lines.append(f"      to adopt, add \"{r['bundle_id']}\" to {target} in config/gui-hog.toml")
    for n in sug["notes"]:
        lines.append(f"note: {n}")
    if not sug["apps"]:
        lines.append("no history yet: freezes write `freeze-result` events, the dialog's would-show lines carry app cores; both fill as it runs")
    lines.append("Nothing was edited. A SIGSTOP frees CPU, not memory; RSS above is what the app holds, not what a freeze returns.")
    return lines
