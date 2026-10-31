# ade_gates.rpy -- console port of bin/ade_gates.py: gate definitions, profile overlay, and the operator review flow.
#
# The Claude quota gates' numbers, told as dialogue. Every gate is a character, every rule is a
# line, every human choice is a menu. The Python logic lives in the `init python:` block below and
# follows the original's functions one for one; the labels only narrate their results.
#
# Entry point: from your script, `call ade_gates_start`. The hub returns to the caller when the
# player walks out. Nothing here touches the real config/gates.toml or ~/.local/state: the file
# system is replaced by in-game dictionaries (GATES_TOML_CANON, profile_file, guard_state modes).
#
# Known gaps, stated plainly: no file locks (a boolean stands in for the flock), no atomic writes
# (a dict clear-and-update stands in for os.replace), and America/New_York is modelled as a fixed
# UTC-4 offset, so daylight saving never happens in this port.

# -- characters ----------------------------------------------------------------------------------------------------

define governor = Character("Governor", color="#7fb2ff")
define guard = Character("Quota Guard", color="#ffb37f")
define frontier = Character("Frontier Clerk", color="#b98cff")
define profclerk = Character("Profile Clerk (gate-profile)", color="#8fd694")
define envvar = Character("CLAUDE_*_THRESHOLDS", color="#e8e07a")
define hermes = Character("Hermes (ping)", color="#ff8fb1")
define lockwarden = Character("State Lock Warden", color="#9ad6d6")
define tomlkeeper = Character("gates.toml Keeper", color="#d6b98f")
define reviewer = Character("Adversary", color="#ff6b6b")
define narrator_note = Character("Ops Ledger", color="#cccccc")

# -- store state (saved with the game) -----------------------------------------------------------------------------

default gate_visits = 0
default toml_mode = "ok"          # ok | missing | invalid | no_governor | loose
default profile_mode = "none"     # none | active | wide | greedy | expired | future | too_long | corrupt
default guard_mode = "ok"         # ok | watch_weekly | watch_alert | tight | stale | old | missing | no_fable
default env_text = ""             # the CLAUDE_*_THRESHOLDS environment value, as the player typed it
default frontier_text = "a reason on one line"
default lock_busy = False         # a ping is in flight and holds the state lock
default profile_file = {}         # the gate-profile state file, as a dict
default ping_failures = False     # the next ping returns False (the retry path)

# -- the python half: a port of bin/ade_gates.py ------------------------------------------------------------------

init python:
    import copy
    import json
    import re
    from datetime import datetime, timedelta, timezone

    UTC = timezone.utc
    # A fixed offset stands in for America/New_York. Daylight saving is not modelled.
    NY = timezone(timedelta(hours=-4), "EDT")

    GATES = ("governor", "quota_guard", "frontier")
    ENV_VARS = {"governor": "CLAUDE_GOVERNOR_THRESHOLDS", "quota_guard": "CLAUDE_QUOTA_GUARD_THRESHOLDS"}
    SCHEMA = 1
    DEFAULT_MAX_HOURS = 240
    NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
    ORDERINGS = {
        "quota_guard": (("watch_weekly", "tight_weekly"), ("tight_weekly", "critical_weekly")),
        "governor": (("tight_left_weekly", "critical_left"), ("tight_left_five_hour", "critical_left")),
    }

    FRONTIER_DEFAULTS = {
        "frontier1_judged": 0.0,
        "frontier2_judged": 0.0,
        "frontier1_per_wave": 1.0,
        "frontier2_per_wave": 1.0,
        "frontier1_agent_calls_per_day": 0.0,
        "frontier1_min_left": 10.0,
        "frontier2_min_left": 60.0,
    }
    CODE_DEFAULTS = {
        "governor": {"tight_left_weekly": 30.0, "critical_left": 10.0, "tight_left_five_hour": 35.0},
        "quota_guard": {"watch_weekly": 30.0, "tight_weekly": 20.0, "critical_weekly": 10.0},
        "frontier": FRONTIER_DEFAULTS,
    }
    FRONTIER_REASON_MIN, FRONTIER_REASON_MAX = 10, 200
    GUARD_STATE_MAX_AGE_S = 30 * 60
    JUDGED_OK_LEVELS = ("ok", "watch")
    JUDGED_OK_REASONS = ("weekly",)
    MAX_PROFILE_BYTES = 64 * 1024

    # The stand-in for config/gates.toml, already parsed. Loaded fresh each time (copy.deepcopy).
    GATES_TOML_CANON = {
        "meta": {"max_profile_hours": 240},
        "governor": {"tight_left_weekly": 35.0, "critical_left": 10.0, "tight_left_five_hour": 40.0},
        # watch_weekly 25 is looser than the code default 30 (lower is looser): the guard will refuse it.
        "quota_guard": {"watch_weekly": 25.0, "tight_weekly": 20.0, "critical_weekly": 10.0},
        "frontier": {
            "frontier1_judged": 1.0,
            "frontier2_judged": 0.0,
            "frontier1_per_wave": 1.0,
            "frontier2_per_wave": 1.0,
            "frontier1_agent_calls_per_day": 5.0,
            "frontier1_min_left": 10.0,
            "frontier2_min_left": 60.0,
        },
        "floors": {
            "governor": {
                "tight_left_weekly": {"loosen": "lower", "bound": 15.0},
                "critical_left": {"loosen": "lower", "bound": 5.0},
                "tight_left_five_hour": {"loosen": "lower", "bound": 15.0},
            },
            "quota_guard": {
                "watch_weekly": {"loosen": "lower", "bound": 20.0},
                "tight_weekly": {"loosen": "lower", "bound": 10.0},
                "critical_weekly": {"loosen": "lower", "bound": 5.0},
            },
            "frontier": {
                "frontier1_judged": {"loosen": "higher", "bound": 1.0},
                "frontier2_judged": {"loosen": "higher", "bound": 1.0},
                "frontier1_per_wave": {"loosen": "higher", "bound": 3.0},
                "frontier2_per_wave": {"loosen": "higher", "bound": 3.0},
                "frontier1_agent_calls_per_day": {"loosen": "higher", "bound": 10.0},
                "frontier1_min_left": {"loosen": "lower", "bound": 5.0},
                "frontier2_min_left": {"loosen": "lower", "bound": 30.0},
            },
        },
        "profiles": {
            "away": {
                "description": "the weekend is off-grid; quota is for Monday",
                "governor": {"tight_left_weekly": 20.0},
                "quota_guard": {"watch_weekly": 22.0},
                "frontier": {"frontier1_agent_calls_per_day": 10.0},
            },
            "wide": {"governor": {"critical_left": 6.0}},
            "greedy": {"governor": {"not_a_key": 1.0}},
        },
    }

    # Logging and pings are in-game too.
    LOGGED = set()
    STDERR = []
    PING_BOX = {"text": "", "ok": True}

    class GateEnvError(ValueError):
        """The env JSON override is not usable."""

    class LockBusy(Exception):
        """The state lock stayed held past the wait bound (a ping is in flight)."""

    # -- escaping for Ren'Py text ----------------------------------------------------------------------------------

    def rpy_escape(text):
        """Ren'Py reads { and [ in dialogue as tags and interpolation: double them so they print literally."""
        return str(text).replace("{", "{{").replace("[", "[[")

    # -- small helpers ---------------------------------------------------------------------------------------------

    def is_num(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) < 1e300

    def show(v):
        text = repr(v)
        return text if len(text) <= 80 else text[:77] + "..."

    def log_once(msg):
        if msg not in LOGGED:
            LOGGED.add(msg)
            STDERR.append("ade_gates: " + msg)

    def iso(dt):
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def parse_utc(value):
        if not isinstance(value, str):
            return None
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
            return None
        return dt.astimezone(UTC)

    def ny_text(dt):
        d = dt.astimezone(NY)
        return f"{d:%a %b} {d.day} {d.hour % 12 or 12}:{d:%M} {'AM' if d.hour < 12 else 'PM'} {d:%Z}"

    def ny_date(dt):
        return dt.astimezone(NY).date().isoformat()

    # -- gates.toml (the stand-in) ---------------------------------------------------------------------------------

    def read_toml():
        if toml_mode == "missing":
            return None, "config/gates.toml: No such file or directory"
        if toml_mode == "invalid":
            return None, "config/gates.toml: not valid TOML (Expected '=' after a key)"
        cfg = copy.deepcopy(GATES_TOML_CANON)
        if toml_mode == "no_governor":
            del cfg["governor"]
        if toml_mode == "loose":
            cfg["quota_guard"]["watch_weekly"] = 12.0
        return cfg, None

    def max_hours(cfg):
        meta = cfg.get("meta")
        v = meta.get("max_profile_hours") if isinstance(meta, dict) else None
        return float(v) if is_num(v) and v > 0 else float(DEFAULT_MAX_HOURS)

    def toml_baseline(cfg, gate):
        tbl = cfg.get(gate)
        if not isinstance(tbl, dict) or not tbl or not all(is_num(v) for v in tbl.values()):
            return None
        return {k: float(v) for k, v in tbl.items()}

    def toml_baselines(cfg):
        return {g: toml_baseline(cfg, g) or {} for g in GATES}

    def floor_spec(cfg, gate, key):
        floors = cfg.get("floors")
        tbl = floors.get(gate) if isinstance(floors, dict) else None
        spec = tbl.get(key) if isinstance(tbl, dict) else None
        return spec if isinstance(spec, dict) else None

    def spec_problem(spec):
        if spec.get("loosen") not in ("lower", "higher"):
            return 'loosen must be "lower" or "higher"'
        if not is_num(spec.get("bound")):
            return "bound must be a number"
        return None

    def value_problem(spec, baseline, value):
        if not is_num(value):
            return show(value) + " is not a number"
        bad = spec_problem(spec)
        if bad:
            return "floor spec is malformed: " + bad
        bound = float(spec["bound"])
        if spec["loosen"] == "lower":
            if value > baseline:
                return f"{value:g} is tighter than the baseline {baseline:g} (lower is looser)"
            if value < bound:
                return f"{value:g} is below the floor {bound:g}"
        else:
            if value < baseline:
                return f"{value:g} is tighter than the baseline {baseline:g} (higher is looser)"
            if value > bound:
                return f"{value:g} is above the ceiling {bound:g}"
        return None

    def code_direction(gate, key):
        if gate == "frontier" and key in FRONTIER_DEFAULTS:
            return "lower" if key.endswith("_min_left") else "higher"
        return None

    def effective_spec(cfg, gate, key):
        spec = floor_spec(cfg, gate, key)
        direction = code_direction(gate, key)
        if spec is None or direction is None:
            return spec
        return {**spec, "loosen": direction}

    def baseline_limit(cfg, gate, key, default):
        if code_direction(gate, key) == "higher":
            spec = floor_spec(cfg, gate, key)
            if spec is not None and is_num(spec.get("bound")):
                return float(spec["bound"])
        return default

    def baseline_loosens(cfg, gate, key, value, default):
        direction = code_direction(gate, key)
        if direction is not None:
            spec = {"loosen": direction}
            default = baseline_limit(cfg, gate, key, default)
        else:
            spec = floor_spec(cfg, gate, key)
            if spec is None:
                return False
        if spec.get("loosen") == "lower":
            return value < default
        if spec.get("loosen") == "higher":
            return value > default
        return value != default

    def ordering_problems(gate, values):
        out = []
        for hi, lo in ORDERINGS.get(gate, ()):
            a, b = values.get(hi), values.get(lo)
            if is_num(a) and is_num(b) and a < b:
                out.append(f"{hi} {a:g} must be at least {lo} {b:g}")
        return out

    def profile_problems(cfg, name, baselines):
        if not NAME_RE.fullmatch(str(name)):
            return ["profile name " + show(name) + " is not [a-z0-9_-], 32 chars at most"]
        profiles = cfg.get("profiles")
        prof = profiles.get(name) if isinstance(profiles, dict) else None
        if not isinstance(prof, dict):
            return [f"no profile {name!r} in gates.toml"]
        out = []
        for gate, tbl in prof.items():
            if gate == "description" and isinstance(tbl, str):
                continue
            if gate not in GATES:
                out.append(f"profile {name}: unknown entry {gate!r}")
                continue
            if not isinstance(tbl, dict):
                out.append(f"profile {name}.{gate}: not a table")
                continue
            before = len(out)
            for key, value in tbl.items():
                spec = effective_spec(cfg, gate, key)
                if spec is None:
                    out.append(f"profile {name}.{gate}.{key}: not overridable (no [floors.{gate}] entry)")
                elif key not in baselines.get(gate, {}):
                    out.append(f"profile {name}.{gate}.{key}: no baseline value")
                else:
                    why = value_problem(spec, baselines[gate][key], value)
                    if why:
                        out.append(f"profile {name}.{gate}.{key}: {why}")
            if len(out) == before:
                merged = {**baselines.get(gate, {}), **tbl}
                out += [f"profile {name}.{gate}: {p}" for p in ordering_problems(gate, merged)]
        return out

    # -- the profile state file (in-game dict) ---------------------------------------------------------------------

    def set_profile_mode(mode, now):
        profile_file.clear()
        if mode == "none":
            return
        if mode == "corrupt":
            profile_file["__corrupt__"] = True
            return
        base = {
            "schema": 1,
            "profile": "away",
            "since": iso(now - timedelta(hours=1)),
            "until": iso(now + timedelta(hours=12)),
            "reason": "weekend off-grid, quota is for Monday",
            "set_by": "operator",
        }
        if mode == "wide":
            base["profile"] = "wide"
        elif mode == "greedy":
            base["profile"] = "greedy"
        elif mode == "expired":
            base["until"] = iso(now - timedelta(hours=2))
        elif mode == "future":
            base["since"] = iso(now + timedelta(hours=1))
        elif mode == "too_long":
            base["until"] = iso(now + timedelta(hours=300))
        profile_file.update(base)

    def read_profile_state():
        if profile_file.get("__corrupt__"):
            return None, "corrupt JSON"
        if not profile_file:
            return None, None
        return dict(profile_file), None

    def resolve_profile(cfg, now):
        res = {"profile": None, "ignored": None, "expired": None, "applies": {}}
        data, why = read_profile_state()
        if data is None:
            res["ignored"] = why
            return res
        schema = data.get("schema")
        if type(schema) is not int or schema != SCHEMA:
            res["ignored"] = f"profile file schema {show(schema)} is not {SCHEMA}"
            return res
        raw_name = data.get("profile")
        name = raw_name if isinstance(raw_name, str) and NAME_RE.fullmatch(raw_name) else None
        since, until = parse_utc(data.get("since")), parse_utc(data.get("until"))
        if until is None:
            res["ignored"] = "`until` is missing or not a UTC time (timezone-aware, offset zero)"
            return res
        info = {"name": name, "since": data.get("since"), "until": data.get("until"),
                "reason": data.get("reason"), "set_by": data.get("set_by")}
        if until <= now:
            res["ignored"] = f"profile {name!r} expired at {iso(until)}"
            if not data.get("expired_notified"):
                res["expired"] = info
            return res
        if since is None:
            res["ignored"] = "`since` is missing or not a UTC time (timezone-aware, offset zero)"
        elif since > now:
            res["ignored"] = f"profile {name!r} starts in the future ({iso(since)})"
        elif until <= since:
            res["ignored"] = "`until` is not after `since`"
        elif cfg is None:
            res["ignored"] = "gates.toml is unavailable, so no profile can be checked"
        elif (until - since).total_seconds() > max_hours(cfg) * 3600:
            hours = (until - since).total_seconds() / 3600
            res["ignored"] = f"window is {hours:g} h, over max_profile_hours {max_hours(cfg):g}"
        elif name is None:
            res["ignored"] = "`profile` is missing or not a valid name ([a-z0-9_-], 32 characters at most)"
        else:
            problems = profile_problems(cfg, name, toml_baselines(cfg))
            if problems:
                res["ignored"] = "; ".join(problems)
            else:
                res["profile"] = info
                res["applies"] = {g: dict(t) for g, t in cfg["profiles"][name].items() if g in GATES}
        return res

    # -- the loader ------------------------------------------------------------------------------------------------

    def env_overrides(gate, known):
        var = ENV_VARS.get(gate)
        raw = env_text if var else ""
        if not raw:
            return {}
        try:
            over = json.loads(raw)
        except ValueError as e:
            raise GateEnvError(f"{var} is not JSON: {e}")
        if not isinstance(over, dict):
            raise GateEnvError(f"{var} must be a JSON object")
        out = {}
        for k, v in over.items():
            if k not in known or not is_num(v):
                raise GateEnvError(f"unknown or non-numeric threshold {k!r}")
            out[k] = float(v)
        return out

    def load_gates(gate, now, defaults):
        if gate not in GATES:
            raise ValueError(f"unknown gate {gate!r}")
        now = now.astimezone(UTC)
        base = {k: float(v) for k, v in (defaults or {}).items()}
        info = {"source": "code", "toml_error": None, "baseline": dict(base), "profile": None,
                "ignored": None, "expired": None, "profile_values": {}, "env_values": {},
                "baseline_guarded": {}}
        cfg, err = read_toml()
        if cfg is not None:
            file_base = toml_baseline(cfg, gate)
            if file_base is None:
                err = f"config/gates.toml: [{gate}] is missing, empty or holds a non-number"
                cfg = None
            else:
                accepted = {}
                for k, v in file_base.items():
                    if defaults and k not in base:
                        continue
                    if defaults and baseline_loosens(cfg, gate, k, v, base[k]):
                        info["baseline_guarded"][k] = v
                        lim = baseline_limit(cfg, gate, k, base[k])
                        where = "code default" if lim == base[k] else "floor bound"
                        log_once(f"[{gate}].{k} = {v:g} is looser than the {where} {lim:g}; using the code default")
                        continue
                    accepted[k] = v
                base.update(accepted)
                info.update(source="gates.toml", baseline=dict(base))
        if err:
            info["toml_error"] = err
            log_once(f"{err}; using the code defaults for {gate}")
        prof = resolve_profile(cfg, now)
        info.update(profile=prof["profile"], ignored=prof["ignored"], expired=prof["expired"])
        t = dict(base)
        pv = {k: float(v) for k, v in prof["applies"].get(gate, {}).items() if k in t}
        t.update(pv)
        info["profile_values"] = pv
        ev = env_overrides(gate, t)
        t.update(ev)
        info["env_values"] = ev
        return t, info

    def load_frontier(now):
        return load_gates("frontier", now, FRONTIER_DEFAULTS)

    def profile_brief(info):
        p = info.get("profile")
        return {"name": p.get("name"), "until": p.get("until")} if isinstance(p, dict) else None

    # -- the frontier allowance ------------------------------------------------------------------------------------

    def frontier_reason(text):
        if text is None:
            return None, None
        if not isinstance(text, str):
            return None, "a frontier-reason must be text"
        s = text.strip()
        if not s:
            return None, None
        if "\n" in s or "\r" in s or "\u2028" in s or "\u2029" in s:
            return None, "a frontier-reason is one line, no control or format character"
        if not FRONTIER_REASON_MIN <= len(s) <= FRONTIER_REASON_MAX:
            return None, f"a frontier-reason is {FRONTIER_REASON_MIN}-{FRONTIER_REASON_MAX} characters (got {len(s)})"
        return s, None

    def make_guard_state(mode, now):
        if mode == "missing":
            return None
        state = {"checked_at": iso(now), "level": "ok", "stale": False, "reasons": None, "fable_left": 40.0}
        if mode == "watch_weekly":
            state.update(level="watch", reasons=["weekly"])
        elif mode == "watch_alert":
            state.update(level="watch", reasons=["alert"])
        elif mode == "tight":
            state.update(level="tight", reasons=["weekly"])
        elif mode == "stale":
            state.update(stale=True)
        elif mode == "old":
            state.update(checked_at=iso(now - timedelta(minutes=45)))
        elif mode == "no_fable":
            del state["fable_left"]
        return state

    def judged_guard_block(state, t, now):
        if not isinstance(state, dict):
            return "the quota guard state is missing or unreadable"
        checked = parse_utc(state.get("checked_at"))
        if checked is None:
            return "the quota guard state has no usable checked_at"
        age = (now - checked).total_seconds()
        if not -60 <= age <= GUARD_STATE_MAX_AGE_S:
            return f"the quota guard state is {age / 60:.0f} min old (limit {GUARD_STATE_MAX_AGE_S // 60})"
        level = state.get("level")
        if level not in JUDGED_OK_LEVELS:
            return f"the quota guard level is {level!r}: the closed rules apply at tight and critical"
        if state.get("stale") is not False:
            return "the quota guard data is stale"
        reasons = state.get("reasons")
        if level == "watch" and (not isinstance(reasons, list) or not reasons
                                 or any(r not in JUDGED_OK_REASONS for r in reasons)):
            return f"the quota guard is at watch for a reason other than the weekly window ({reasons!r})"
        if level == "ok" and reasons not in (None, []):
            return f"the quota guard reports reasons {reasons!r} at level ok"
        left = state.get("fable_left")
        if not is_num(left):
            return "the frontier-1 cap reading (fable_left) is missing"
        if left < t.get("frontier1_min_left", FRONTIER_DEFAULTS["frontier1_min_left"]):
            return f"the frontier-1 cap has {left:g}% left (floor {t['frontier1_min_left']:g}%)"
        return None

    def judged_pool_block(family, t, now, guard_state, remaining):
        if family == 1:
            return judged_guard_block(guard_state, t, now)
        floor = t["frontier2_min_left"]
        if is_num(remaining) and remaining >= floor:
            return None
        if not is_num(remaining):
            seen = "no reading"
        else:
            seen = f"{remaining:g}% left"
        return f"the codex pool has {seen} (floor {floor:g}%)"

    # -- expiry notice and daily nudge -----------------------------------------------------------------------------

    def ping_hermes(text):
        PING_BOX["text"] = text
        PING_BOX["ok"] = not ping_failures
        return PING_BOX["ok"]

    def mark_and_ping(data, key, value, text, ping):
        marked = dict(data)
        marked[key] = value
        profile_file.clear()
        profile_file.update(marked)
        ok = False
        try:
            ok = bool(ping(text))
        finally:
            if not ok and profile_file == marked:
                profile_file.clear()
                profile_file.update(data)
        return ok

    def state_lock():
        if lock_busy:
            raise LockBusy("state lock is held (a ping is in flight)")
        return True

    def days_left(until, now):
        mins = max(0, int((until - now).total_seconds() // 60))
        return f"{mins // 1440} days left" if mins >= 1440 else f"{mins // 60}h {mins % 60}m left"

    def next_nudge(data, until, now):
        today, last = now.astimezone(NY).date(), until.astimezone(NY).date()
        if today >= last:
            return None
        if data.get("last_daily_nudge") != today.isoformat():
            return now
        tomorrow = today + timedelta(days=1)
        if tomorrow >= last:
            return None
        midnight = datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=NY)
        return midnight.astimezone(UTC)

    def notify_expired(info, ping, now):
        exp = info.get("expired")
        if not isinstance(exp, dict):
            return False
        try:
            state_lock()
        except LockBusy as e:
            log_once(f"expiry notice skipped, retried next run: {e}")
            return False
        data, _ = read_profile_state()
        if not isinstance(data, dict) or data.get("expired_notified") or data.get("until") != exp.get("until"):
            return False
        until = parse_utc(exp.get("until"))
        name = exp.get("name") or "gate"
        text = f"djbclark-ade: {name} profile expired, baseline restored"
        if until:
            text += f" (gates were loosened until {ny_text(until)})"
        return mark_and_ping(data, "expired_notified", iso(now), text, ping)

    def notify_daily(info, ping, now):
        prof = info.get("profile")
        if not isinstance(prof, dict):
            return False
        until = parse_utc(prof.get("until"))
        if until is None:
            return False
        try:
            state_lock()
        except LockBusy as e:
            log_once(f"daily nudge skipped, retried next run: {e}")
            return False
        data, _ = read_profile_state()
        if not isinstance(data, dict) or data.get("until") != prof.get("until") or data.get("profile") != prof.get("name"):
            return False
        due = next_nudge(data, until, now)
        if due is None or due > now:
            return False
        name = prof.get("name") or "gate"
        text = (f"djbclark-ade: {name} profile active until {ny_text(until)}, {days_left(until, now)}; "
                "restore normal routing now: gate-profile clear (stay longer: gate-profile extend --for 24h)")
        return mark_and_ping(data, "last_daily_nudge", ny_date(now), text, ping)

    # -- prose for the labels ---------------------------------------------------------------------------------------

    def describe_effective(gate, t, info):
        parts = [f"{k} = {v:g}" for k, v in sorted(t.items())]
        src = info.get("source")
        line = f"{gate}: " + ", ".join(parts) + f". Source: {src}."
        if info.get("toml_error"):
            line += " Toml trouble: " + info["toml_error"] + "."
        if info.get("baseline_guarded"):
            guarded = ", ".join(f"{k} {v:g}" for k, v in sorted(info["baseline_guarded"].items()))
            line += " Guarded back to code defaults: " + guarded + "."
        return rpy_escape(line)

    def describe_profile(info):
        if info.get("profile"):
            p = info["profile"]
            return rpy_escape(f"Profile {p.get('name')} is in force until {p.get('until')}.")
        if info.get("expired"):
            return rpy_escape("A profile expired. Its file stays behind as the audit trail.")
        if info.get("ignored"):
            return rpy_escape("Profile ignored: " + str(info["ignored"]) + ".")
        return rpy_escape("No profile. The baseline applies, as it always has.")

    def describe_env(env_raw):
        if not env_raw:
            return "The environment is empty. Nobody is overriding anything."
        return rpy_escape("The environment says: " + env_raw)

# -- labels: the hub -----------------------------------------------------------------------------------------------

label ade_gates_start:
    $ gate_visits += 1
    "The office is dark except for one terminal. A sticky note on the bezel reads: bin/ade_gates.py, ported. Do not touch the original."
    "This is visit number [gate_visits]. The file has no opinions yet; the gates have plenty."
    jump gate_hub

label gate_hub:
    menu:
        "Ask the Governor for its numbers.":
            call gate_governor
            jump gate_hub
        "Ask the Quota Guard what it saw this week.":
            call gate_quota_guard
            jump gate_hub
        "Ask the Frontier Clerk whether the allowance is open.":
            call gate_frontier
            jump gate_hub
        "Open the gate-profile desk.":
            call check_profile
            jump gate_hub
        "Break gates.toml on purpose (demo).":
            call check_toml
            jump gate_hub
        "Feed the environment a bad override (demo).":
            call check_env
            jump gate_hub
        "Ring the expiry pinger and the daily nudge.":
            call check_nudges
            jump gate_hub
        "Hold the state lock (demo).":
            call check_lock
            jump gate_hub
        "Walk the rules as dialogue, one step at a time.":
            call ledger_walkthrough
            jump gate_hub
        "Read the adversary's ending report.":
            call ending_report
            jump gate_hub
        "Close the file and walk out.":
            "You lock the terminal. The sticky note still says ported."
            return

# -- labels: the Governor ------------------------------------------------------------------------------------------

label gate_governor:
    python:
        now = datetime.now(UTC)
        env_error = None
        try:
            gov_t, gov_info = load_gates("governor", now, CODE_DEFAULTS["governor"])
        except GateEnvError as exc:
            env_error = rpy_escape(exc)
    if env_error:
        governor "I refuse to start. The environment sent me something I cannot read."
        governor "[env_error]"
        governor "A gate that will not start is still a gate. Ask again after you fix the variable."
        return
    governor "I am the Governor. I decide where weekly quota turns into a warning, and the warning into a stop."
    python:
        gov_line = describe_effective("governor", gov_t, gov_info)
    governor "[gov_line]"
    menu:
        "Read me the profile line.":
            python:
                gov_prof = describe_profile(gov_info)
            governor "[gov_prof]"
            governor "The profile only moves my numbers in the direction the floors allow. Never tighter than baseline."
            return
        "Describe the environment override.":
            python:
                gov_env = describe_env(env_text)
            governor "[gov_env]"
            governor "Env overrides do not look at floors. That is the point: they are for emergencies."
            return
        "Ask why the floors matter.":
            governor "A floor is the most a profile may move a key. It is a fence, not a suggestion."
            governor "Keys without a floor entry, like timings and ages, take the file's value and nothing more."
            return
        "Walk away from the Governor.":
            governor "Keep your numbers. I will keep mine."
            return

# -- labels: the Quota Guard ---------------------------------------------------------------------------------------

label gate_quota_guard:
    python:
        now = datetime.now(UTC)
        q_t, q_info = load_gates("quota_guard", now, CODE_DEFAULTS["quota_guard"])
        q_line = describe_effective("quota_guard", q_t, q_info)
    guard "I watch the weekly window and tell the Governor when to worry."
    guard "[q_line]"
    if q_info["baseline_guarded"]:
        guard "The file told me watch_weekly 25. That is looser than my own 30, and a loosening belongs in a profile. I refused it."
    menu:
        "Read my state file.":
            call check_guard_state
            return
        "Explain the refusal in plain words.":
            guard "A tighter number is always accepted. A looser number is replaced by my code default, and the operator is told once."
            return
        "Hand me a different reading.":
            call pick_guard_mode
            guard "Reading changed. Ask me again, and I will judge it fresh."
            return

label check_guard_state:
    python:
        now = datetime.now(UTC)
        g_state = make_guard_state(guard_mode, now)
        if g_state is None:
            g_line = "The state file is missing. The guard has nothing to say, and the frontier treats nothing as no."
        else:
            g_line = rpy_escape("Level " + repr(g_state.get("level")) + ", stale " + str(g_state.get("stale"))
                                + ", reasons " + repr(g_state.get("reasons")) + ".")
    guard "[g_line]"
    return

label pick_guard_mode:
    menu:
        "Level ok, fresh, weekly fine.":
            $ guard_mode = "ok"
        "Watch for a weekly reason.":
            $ guard_mode = "watch_weekly"
        "Watch for an alert, which is not a weekly reason.":
            $ guard_mode = "watch_alert"
        "Tight, which is a stop.":
            $ guard_mode = "tight"
        "Data marked stale.":
            $ guard_mode = "stale"
        "Forty-five minutes old.":
            $ guard_mode = "old"
        "No state file at all.":
            $ guard_mode = "missing"
        "No fable cap reading.":
            $ guard_mode = "no_fable"
    return

# -- labels: the Frontier Clerk ------------------------------------------------------------------------------------

label gate_frontier:
    python:
        now = datetime.now(UTC)
        f_t, f_info = load_frontier(now)
        f_line = describe_effective("frontier", f_t, f_info)
    frontier "The frontier allowance is a standing baseline, capped by its floors. The code default is all closed."
    frontier "[f_line]"
    menu:
        "Judge the claude pool (frontier one).":
            call judged_claude
            return
        "Judge the codex pool at a chosen percent left.":
            call judged_codex
            return
        "Check the reason an agent gave.":
            call check_reason
            return
        "Walk back to the hub.":
            frontier "Closed, as the code default is. Come back when a profile has opened something."
            return

label judged_claude:
    call pick_guard_mode
    python:
        now = datetime.now(UTC)
        jc_t, jc_info = load_frontier(now)
        jc_block = judged_pool_block(1, jc_t, now, make_guard_state(guard_mode, now), None)
        if jc_block is None:
            jc_line = "The claude pool is open for judged use, on the quota guard's reading."
        else:
            jc_line = rpy_escape("The claude pool is closed. " + jc_block + ".")
    frontier "[jc_line]"
    return

label judged_codex:
    menu:
        "Seventy-five percent left.":
            $ codex_left = 75.0
        "Sixty percent left, exactly the floor.":
            $ codex_left = 60.0
        "Fifty-nine percent left.":
            $ codex_left = 59.0
        "No reading from the pool.":
            $ codex_left = None
    python:
        now = datetime.now(UTC)
        jx_t, jx_info = load_frontier(now)
        jx_block = judged_pool_block(2, jx_t, now, None, codex_left)
        if jx_block is None:
            jx_line = "The codex pool passes the floor. Judged use is allowed for it."
        else:
            jx_line = rpy_escape("The codex pool is closed. " + jx_block + ".")
    frontier "[jx_line]"
    return

label check_reason:
    menu:
        "Blank: closed treatment.":
            $ frontier_text = ""
        "Too short to mean anything.":
            $ frontier_text = "short"
        "One fine line of reason.":
            $ frontier_text = "a reason on one line"
        "A line break in the middle.":
            $ frontier_text = "a reason\nsplit in two"
    python:
        reason, problem = frontier_reason(frontier_text)
        if problem:
            r_line = rpy_escape("Refused: " + problem + ".")
        elif reason is None:
            r_line = "No reason given, so the closed rules apply."
        else:
            r_line = rpy_escape("Accepted: " + reason + ".")
    frontier "[r_line]"
    return

# -- labels: the gate-profile desk ---------------------------------------------------------------------------------

label pick_profile_mode:
    menu:
        "No profile file.":
            $ profile_mode = "none"
        "An active weekend profile, away.":
            $ profile_mode = "active"
        "A profile that names the wide profile.":
            $ profile_mode = "wide"
        "A profile whose key nobody floors (greedy).":
            $ profile_mode = "greedy"
        "A profile that expired two hours ago.":
            $ profile_mode = "expired"
        "A profile that starts in the future.":
            $ profile_mode = "future"
        "A profile window of three hundred hours.":
            $ profile_mode = "too_long"
        "A corrupt state file.":
            $ profile_mode = "corrupt"
    return

label check_profile:
    call pick_profile_mode
    python:
        now = datetime.now(UTC)
        set_profile_mode(profile_mode, now)
        p_t, p_info = load_gates("governor", now, CODE_DEFAULTS["governor"])
        p_line = describe_profile(p_info)
    profclerk "I file the profile. Here is what the gates actually see."
    profclerk "[p_line]"
    if p_info["profile"]:
        python:
            p_vals = ", ".join(f"{k} {v:g}" for k, v in p_info["profile_values"].items()) or "nothing"
        profclerk "The profile moved these governor keys: [p_vals]."
        profclerk "Only keys with a floor entry may move, and only the way the floor allows."
    if p_info["expired"]:
        profclerk "The file expired. It stays on disk as the audit trail, and the expiry ping is owed once."
    if p_info["ignored"] and not p_info["profile"]:
        python:
            p_why = rpy_escape(p_info["ignored"])
        profclerk "The profile was ignored, and the baseline applies alone. Reason: [p_why]."
    profclerk "Every rule in this desk is one of the if-branches of resolve_profile. Nothing else."
    return

# -- labels: gates.toml and the environment ------------------------------------------------------------------------

label pick_toml_mode:
    menu:
        "The file is fine.":
            $ toml_mode = "ok"
        "The file is missing.":
            $ toml_mode = "missing"
        "The file is not valid TOML.":
            $ toml_mode = "invalid"
        "The governor table has been deleted.":
            $ toml_mode = "no_governor"
        "The guard's watch_weekly is set looser than the code.":
            $ toml_mode = "loose"
    return

label check_toml:
    call pick_toml_mode
    python:
        now = datetime.now(UTC)
        k_t, k_info = load_gates("governor", now, CODE_DEFAULTS["governor"])
        k_line = describe_effective("governor", k_t, k_info)
        k_err = rpy_escape(k_info["toml_error"]) if k_info["toml_error"] else None
    tomlkeeper "I keep config/gates.toml. The Python keeps the code defaults for when I cannot."
    if k_err:
        tomlkeeper "The file has trouble: [k_err]"
        tomlkeeper "So the code defaults apply for this gate. The fail-safe is the whole reason the defaults exist."
    tomlkeeper "[k_line]"
    return

label pick_env:
    menu:
        "Empty environment.":
            $ env_text = ""
        "A key nobody knows.":
            $ env_text = '{"nope": 1}'
        "A word where a number belongs.":
            $ env_text = '{"critical_left": "ten"}'
        "A valid, tighter threshold.":
            $ env_text = '{"critical_left": 8}'
        "Not even JSON.":
            $ env_text = "not json at all"
        "A looser threshold under the floor (emergency).":
            $ env_text = '{"critical_left": 1}'
    return

label check_env:
    call pick_env
    python:
        now = datetime.now(UTC)
        env_err = None
        try:
            e_t, e_info = load_gates("governor", now, CODE_DEFAULTS["governor"])
            e_line = describe_effective("governor", e_t, e_info)
        except GateEnvError as exc:
            env_err = rpy_escape(exc)
    if env_err:
        envvar "The override is refused: [env_err]"
        envvar "A refused override is an error, not a silent default. The gate does not start."
    else:
        envvar "The override is accepted, and it applies last of all, above any profile."
        envvar "[e_line]"
    envvar "Frontier never reads this variable. Its allowance cannot be widened from the environment."
    return

# -- labels: expiry, daily nudge and the state lock ----------------------------------------------------------------

label pick_ping:
    menu:
        "Pings succeed.":
            $ ping_failures = False
        "Pings fail, so the mark must be taken back.":
            $ ping_failures = True
    return

label check_nudges:
    call pick_profile_mode
    call pick_ping
    python:
        now = datetime.now(UTC)
        set_profile_mode(profile_mode, now)
        n_t, n_info = load_gates("governor", now, CODE_DEFAULTS["governor"])
        PING_BOX["text"] = ""
        sent_expired = notify_expired(n_info, ping_hermes, now)
        sent_daily = False
        if not sent_expired:
            sent_daily = notify_daily(n_info, ping_hermes, now)
        n_text = rpy_escape(PING_BOX["text"]) if PING_BOX["text"] else "Nothing to say."
    if PING_BOX["text"]:
        hermes "[n_text]"
    else:
        hermes "Quiet. Nothing is owed right now."
    if sent_expired:
        hermes "The expiry notice went out once, and the file now carries expired_notified so it never repeats."
    if sent_daily:
        hermes "The daily nudge went out for today's New York date. One per day, no matter how many callers ask."
    if ping_failures and not (sent_expired or sent_daily):
        hermes "The ping failed. The mark was taken back, so the next run retries. A sent ping is never retried."
    return

label check_lock:
    menu:
        "The lock is free.":
            $ lock_busy = False
        "A ping is in flight and holds the lock.":
            $ lock_busy = True
    python:
        now = datetime.now(UTC)
        set_profile_mode("active", now)
        l_info = {"profile": {"name": profile_file.get("profile"), "until": profile_file.get("until")},
                  "expired": None}
        l_sent = notify_daily(l_info, ping_hermes, now)
        lock_busy = False
    if l_sent:
        hermes "The lock was free. The daily nudge went out, and it is recorded in the profile file."
    else:
        lockwarden "The lock was held, so the nudge is skipped. It will be retried on the next run, not dropped."
        lockwarden "A writer that waits for the lock never overwrites a profile set meanwhile."
    return

# -- labels: the rules, one step at a time (the original's docstring as dialogue) -----------------------------------

label ledger_walkthrough:
    narrator_note "The Ops Ledger opens to the page that explains the precedence. Lowest wins first, highest wins last."
    menu:
        "Step one: the code defaults.":
            call step_defaults
        "Step two: the gates.toml baseline and its guard.":
            call step_baseline
        "Step three: the active profile window.":
            call step_profile_window
        "Step four: the environment override.":
            call step_env
        "Step five: the frontier allowance.":
            call step_frontier
        "Close the ledger.":
            narrator_note "The ledger closes on the word precedence, underlined twice."
    return

label step_defaults:
    narrator_note "Defaults are the fail-safe. When gates.toml is missing or unparsable, these numbers decide everything."
    narrator_note "The frontier defaults are all closed: no judged use, one frontier slice per wave, always ask on Agent calls."
    return

label step_baseline:
    narrator_note "A gates.toml value may tighten or equal the code default. A looser value is replaced by the default."
    narrator_note "The one exception is the frontier's higher-is-looser keys, which may rise to their floor bound. That is the standing allowance."
    return

label step_profile_window:
    narrator_note "A profile applies only if the file parses, both times are UTC, now sits inside the window, and the window is within max_profile_hours."
    narrator_note "Every key it sets must have a floor entry, move in the loosen direction, and stay inside the bound. One bad value rejects the whole profile."
    menu:
        "Show the ordering rule.":
            narrator_note "Watch, then tight, then critical as the percent falls. The governor's tight triggers must not fire after its critical one."
        "Show what happens to an expired file.":
            narrator_note "It is ignored and left in place as the audit trail, and announced once. It is not deleted."
    return

label step_env:
    narrator_note "The environment JSON is the last word, for tests and emergencies. Bad input raises GateEnvError, loudly."
    narrator_note "The frontier gate has no environment override at all. An agent cannot put a threshold in the environment and widen the allowance."
    return

label step_frontier:
    narrator_note "A judged frontier use needs the quota guard to say ok or watch, fresh within thirty minutes, and the frontier-1 cap above its floor."
    narrator_note "Tight and critical are the stop signal in every profile. A watch for any reason other than weekly is a stop too."
    narrator_note "A frontier reason is one line of ten to two hundred characters. Blank means the closed rules, as before."
    return

# -- labels: the adversary's ending report -------------------------------------------------------------------------

label ending_report:
    python:
        e_count = len(STDERR)
    reviewer "I am the adversary. I have read the port, and I have opinions about its line count."
    reviewer "This visit produced [e_count] log lines in the stderr ledger. Each is printed once, which is the rule."
    menu:
        "Approve the port.":
            reviewer "A verdict belongs in a PR body as a marker, not in a visual novel. I will not write one here."
        "Block the port.":
            reviewer "BLOCK. The file carries no real file locks, no atomic writes, and no daylight saving. I have recorded all three."
            reviewer "A blocked port is still a port, so it stays in the worktree for the record."
    return

# -- end of the Ren'Py port of bin/ade_gates.py -----------------------------------------------------------------
