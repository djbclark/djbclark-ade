## skillopt_sources: SessionDigest adapters for transcript stores SkillOpt-Sleep cannot read.
## Port of the Python tool at HEAD:bin/skillopt_sources.py. Entry label: tool_skillopt_sources.
## Same flags, usage, exit codes and digest shape; the output digest list goes to stdout one
## narrator line at a time, or to --out via an atomic temp-file replace.
##
## Scope of this port: the shared framework (argv, exclusions, redaction, Builder, finalize,
## the output contract) and the two SQLite adapters that need no protobuf or session-file
## decoding: zcode and crush. Native sources (claude, codex, cursor, opencode, copilot_cli)
## still need the upstream skillopt_sleep package, which this runtime does not import, so
## they exit 1 with the same message the Python tool gives outside its venv.

init python:
    import json, math, os, re, shutil, sys, tempfile
    try:
        import sqlite3
    except ImportError:  # the SDK's bundled Python is built without it
        sqlite3 = None
    from datetime import datetime, timezone
    from pathlib import Path

    HOME = Path.home()
    MAX_CHARS = 4000
    MAX_FINALS = 5
    EXCLUDED_ROOTS = ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/",
                      str(HOME / ".local" / "state") + "/")
    ZCODE_DB = HOME / ".zcode" / "cli" / "db" / "db.sqlite"
    CRUSH_PROJECTS = (HOME / ".local" / "share" / "crush-acp" / "projects.json",
                      HOME / ".local" / "share" / "crush" / "projects.json")
    NATIVE = ("claude", "codex", "cursor", "opencode", "copilot_cli")
    TEXT_FIELDS = ("user_prompts", "assistant_finals")
    ENGINE_MARKERS = (
        "Complete the following task for the user",
        "You are mining a user's past AI-assistant sessions",
        "Score how well the response satisfies the rubric",
        "Reply with exactly: OK",
        "create an empty file named canary",
    )
    EXCLUDE_PROJECTS = []
    ade_out = []

    _FALLBACK_SECRETS = [
        re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
        re.compile(r"(?i)(api[_-]?key|token|secret|password)(\s*[:=]\s*)\S+"),
        re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
        re.compile(r"AKIA[0-9A-Z]{16}"),
        re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    ]
    _PEM = re.compile(r"-----BEGIN [A-Z0-9 ]+-----[\s\S]*?(?:-----END [A-Z0-9 ]+-----|\Z)")
    _PROSE_SECRET = re.compile(r"(?i)\b(password|passphrase|passwd|api key|secret key)\b(\s*(?:is|was|:|=)\s*)\S+")
    _BARE_TOKEN = re.compile(r"(?<![A-Za-z0-9+/=_.-])[A-Za-z0-9+/=_-]{24,}(?![A-Za-z0-9+/=_.-])")

    def ade_say(line):
        """Escape a value for narrator output: text tags are the only markup it can hit."""
        return str(line).replace("{", "{{")

    def ade_err(msg):
        sys.stderr.write(msg + "\n")

    def ade_redact(text):
        for pat in _FALLBACK_SECRETS:
            text = pat.sub(lambda m: (m.group(1) + m.group(2) if m.lastindex else "") + "[REDACTED]", text)
        return text

    def ade_entropy(s):
        counts = {c: s.count(c) for c in set(s)}
        return -sum(n / len(s) * math.log2(n / len(s)) for n in counts.values())

    def ade_bare(m):
        tok = m.group(0)
        if "/" in tok.strip("/") and tok.count("/") > 2:
            return tok
        lower = sum(c.islower() for c in tok)
        upper = sum(c.isupper() for c in tok)
        digits = sum(c.isdigit() for c in tok)
        need = 4.2 if len(tok) < 40 else 4.0
        return "[REDACTED]" if lower >= 2 and upper >= 2 and digits >= 2 and ade_entropy(tok) >= need else tok

    def ade_extra_redact(text):
        text = _PEM.sub("[REDACTED PEM]", text)
        text = _PROSE_SECRET.sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]", text)
        return _BARE_TOKEN.sub(ade_bare, text)

    def ade_clean(text):
        return ade_extra_redact(ade_redact(str(text or ""))).replace("\x00", "").strip()[:MAX_CHARS]

    def ade_engine_session(d):
        prompts = d.get("user_prompts") or []
        return bool(prompts) and any(m in str(prompts[0]) for m in ENGINE_MARKERS)

    def ade_iso(epoch):
        if not epoch or epoch <= 0:
            return ""
        return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    def ade_to_epoch(value):
        """ISO to epoch; a naive value is local time, as SkillOpt's checkpoints are."""
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        except ValueError:
            return None
        return dt.timestamp()

    def ade_excluded(project):
        p = (project or "").rstrip("/") + "/"
        roots = list(EXCLUDED_ROOTS) + [x.rstrip("/") + "/" for x in EXCLUDE_PROJECTS]
        return any(p.startswith(root) for root in roots)

    def ade_finalize(d):
        """The filters every digest passes: project exclusions, the engine's own sessions,
        and redaction of every kept string."""
        if ade_excluded(str(d.get("project") or "")) or ade_engine_session(d):
            return None
        for key in TEXT_FIELDS:
            d[key] = [t for t in (ade_clean(x) for x in d.get(key) or []) if t]
        if not d.get("user_prompts"):
            return None
        d["assistant_finals"] = d["assistant_finals"][-MAX_FINALS:]
        return d

    class ade_builder(object):
        """Accumulate one session's turns into a SessionDigest-shaped dict."""

        def __init__(self, session_id, project, raw_path):
            self.d = {"session_id": session_id, "project": project, "git_branch": "",
                      "started_at": "", "ended_at": "", "user_prompts": [], "assistant_finals": [],
                      "tools_used": [], "skills_used": [], "files_touched": [], "feedback_signals": [],
                      "n_user_turns": 0, "n_assistant_turns": 0, "raw_path": raw_path}

        def user(self, text):
            text = ade_clean(text)
            if text:
                self.d["n_user_turns"] += 1
                self.d["user_prompts"].append(text)

        def assistant(self, text, tools):
            self.d["n_assistant_turns"] += 1
            for t in tools:
                name = re.sub(r"[^A-Za-z0-9_.:-]+", "_", t.strip())[:80]
                if name and name not in self.d["tools_used"]:
                    self.d["tools_used"].append(name)
            text = ade_clean(text)
            if text:
                self.d["assistant_finals"] = (self.d["assistant_finals"] + [text])[-MAX_FINALS:]

        def finish(self, start, end):
            self.d["started_at"], self.d["ended_at"] = ade_iso(start), ade_iso(end)
            if not self.d["user_prompts"] or ade_engine_session(self.d):
                return None
            return self.d

    def ade_snapshot(db, tmp):
        """Copy a SQLite file and its -wal/-shm into tmp; the copy is what gets read."""
        dest = tmp / db.name
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(db) + suffix)
            if src.exists():
                shutil.copyfile(src, Path(str(dest) + suffix))
        return dest

    def ade_connect(path):
        con = sqlite3.connect(str(path))
        con.row_factory = sqlite3.Row
        return con

    def ade_json(raw):
        try:
            value = json.loads(raw) if isinstance(raw, (str, bytes)) else None
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    def ade_harvest_zcode(since, tmp, db=ZCODE_DB):
        if not db.exists():
            return
        con = ade_connect(ade_snapshot(db, tmp))
        sessions = con.execute("SELECT id, directory, time_created, time_updated FROM session "
                               "WHERE parent_id IS NULL ORDER BY time_updated DESC").fetchall()
        for s in sessions:
            if since and (s["time_updated"] or 0) / 1000 < since:
                continue
            if ade_excluded(s["directory"] or ""):
                continue
            b = ade_builder(str(s["id"]), str(s["directory"] or ""), "zcode://%s" % s["id"])
            parts = {}
            for p in con.execute("SELECT message_id, data FROM part WHERE session_id = ? "
                                 "ORDER BY time_created, id", (s["id"],)):
                parts.setdefault(p["message_id"], []).append(ade_json(p["data"]))
            for m in con.execute("SELECT id, data FROM message WHERE session_id = ? "
                                 "ORDER BY time_created, id", (s["id"],)):
                role = ade_json(m["data"]).get("role")
                ps = parts.get(m["id"], [])
                text = "\n".join(p.get("text", "") for p in ps if p.get("type") == "text"
                                 and not p.get("synthetic") and not p.get("ignored")
                                 and isinstance(p.get("text"), str))
                if role == "user":
                    b.user(text)
                elif role == "assistant":
                    b.assistant(text, [str(p.get("tool")) for p in ps
                                       if p.get("type") == "tool" and isinstance(p.get("tool"), str)])
            d = b.finish((s["time_created"] or 0) / 1000, (s["time_updated"] or 0) / 1000)
            if d:
                yield d
        con.close()

    def ade_crush_dbs(projects_files=CRUSH_PROJECTS):
        out, seen = [], set()
        for pf in projects_files:
            try:
                rows = json.loads(pf.read_text()).get("projects") or []
            except (OSError, ValueError):
                continue
            for row in rows:
                path, data_dir = str(row.get("path") or ""), str(row.get("data_dir") or "")
                db = Path(data_dir) / "crush.db"
                if not path or ade_excluded(path) or not db.exists() or db.resolve() in seen:
                    continue
                seen.add(db.resolve())
                out.append((path, db))
        return out

    def ade_harvest_crush(since, tmp, projects_files=CRUSH_PROJECTS):
        for n, (project, db) in enumerate(ade_crush_dbs(projects_files)):
            sub = tmp / ("crush-%d" % n)
            sub.mkdir(exist_ok=True)
            con = ade_connect(ade_snapshot(db, sub))
            for s in con.execute("SELECT id, created_at, updated_at FROM sessions "
                                 "WHERE parent_session_id IS NULL OR parent_session_id = '' "
                                 "ORDER BY updated_at DESC").fetchall():
                if since and (s["updated_at"] or 0) < since:
                    continue
                b = ade_builder(str(s["id"]), project, "crush://%s#%s" % (db, s["id"]))
                for m in con.execute("SELECT role, parts FROM messages WHERE session_id = ? "
                                     "ORDER BY created_at, id", (s["id"],)):
                    try:
                        parts = json.loads(m["parts"] or "[]")
                    except ValueError:
                        continue
                    parts = [p for p in parts if isinstance(p, dict)]
                    text = "\n".join(str((p.get("data") or {}).get("text") or "")
                                     for p in parts if p.get("type") == "text")
                    if m["role"] == "user":
                        b.user(text)
                    elif m["role"] == "assistant":
                        b.assistant(text, [str((p.get("data") or {}).get("name") or "")
                                           for p in parts if p.get("type") == "tool_call"])
                d = b.finish(float(s["created_at"] or 0), float(s["updated_at"] or 0))
                if d:
                    yield d
            con.close()

    ADAPTERS = {"zcode": ade_harvest_zcode, "crush": ade_harvest_crush}

    def ade_store_present(name):
        if name == "zcode":
            return ZCODE_DB.exists()
        if name == "crush":
            return bool(ade_crush_dbs())
        return False

    def ade_harvest(name, since=None, limit=0):
        if name in NATIVE:
            raise SystemExit("skillopt_sources: native sources need the skillopt tool's Python")
        since_epoch = ade_to_epoch(since)
        out = []
        tmp = tempfile.mkdtemp(prefix="skillopt-src-%s-" % name)
        try:
            for raw in ADAPTERS[name](since_epoch, Path(tmp)):
                d = ade_finalize(raw)
                if d:
                    out.append(d)
                    if limit and len(out) >= limit:
                        break
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        out.sort(key=lambda d: str(d.get("ended_at") or ""), reverse=True)
        return out

    ADE_USAGE = ("usage: skillopt_sources [-h] [--exclude-project EXCLUDE_PROJECT] [--codex-home CODEX_HOME]\n"
                 "                        [--since SINCE] [--limit LIMIT] [--out OUT] [--stats]\n"
                 "                        {%s}" % ",".join(sorted(list(ADAPTERS) + list(NATIVE))))

    def ade_parse(argv):
        """argparse's contract for the flags this tool takes: --opt VALUE or --opt=VALUE."""
        opts = {"exclude_project": [], "codex_home": None, "since": None, "limit": 0,
                "out": None, "stats": False}
        flags = {"--exclude-project": "exclude_project", "--codex-home": "codex_home",
                 "--since": "since", "--limit": "limit", "--out": "out"}
        pos = []
        i = 0
        while i < len(argv):
            arg = argv[i]
            i += 1
            if arg in ("-h", "--help"):
                return "help", None
            if arg == "--stats":
                opts["stats"] = True
                continue
            if arg.startswith("--") and "=" in arg:
                name, val = arg.split("=", 1)
            elif arg in flags:
                if i >= len(argv):
                    return "error", "argument %s: expected one argument" % arg
                name, val = arg, argv[i]
                i += 1
            else:
                pos.append(arg)
                continue
            if name not in flags:
                return "error", "unrecognized arguments: %s" % arg
            key = flags[name]
            if key == "exclude_project":
                opts[key].append(val)
            elif key == "limit":
                try:
                    opts[key] = int(val)
                except ValueError:
                    return "error", "argument --limit: invalid int value: '%s'" % val
            else:
                opts[key] = val
        if len(pos) != 1:
            return "error", "the following arguments are required: source" if not pos else \
                "unrecognized arguments: %s" % " ".join(pos[1:])
        opts["source"] = pos[0]
        if pos[0] not in ADAPTERS and pos[0] not in NATIVE:
            return "error", "argument source: invalid choice: '%s'" % pos[0]
        return "ok", opts

    def ade_say_lines(text):
        for line in str(text).split("\n"):
            ade_out.append(ade_say(line))

    def ade_skillopt_main(argv):
        """Returns the exit status: 0 ok, 1 runtime refusal, 2 usage error."""
        status, parsed = ade_parse(list(argv))
        if status == "help":
            ade_say_lines(ADE_USAGE)
            return 0
        if status == "error":
            ade_err(ADE_USAGE)
            ade_err("skillopt_sources: error: %s" % parsed)
            return 2
        os.umask(0o077)  # the digests hold transcript excerpts
        EXCLUDE_PROJECTS[:] = [os.path.expanduser(x) for x in parsed["exclude_project"]]
        try:
            digests = ade_harvest(parsed["source"], parsed["since"], parsed["limit"])
        except SystemExit as e:
            ade_err(str(e.code))
            return 1
        if parsed["stats"]:
            ade_say_lines(json.dumps({
                "source": parsed["source"], "upstream_helpers": False, "digests": len(digests),
                "user_prompts": sum(len(d["user_prompts"]) for d in digests),
                "newest": digests[0]["ended_at"] if digests else None}))
            return 0
        text = json.dumps(digests, ensure_ascii=False, indent=1)
        if parsed["out"]:
            dest = Path(parsed["out"])
            tmp = dest.with_name(dest.name + ".tmp")
            tmp.write_text(text)
            os.replace(str(tmp), str(dest))
        else:
            ade_say_lines(text)
        return 0


label tool_skillopt_sources:
    $ ade_exit_code = ade_skillopt_main(ade_argv)
    while ade_out:
        $ ade_line = ade_out.pop(0)
        narrator "[ade_line]"
    return
