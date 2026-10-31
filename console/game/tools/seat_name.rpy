## seat-name: one ever-increasing base-36 name for every Paseo seat, so no two are ever alike.
##
## Port of the Python tool (HEAD:bin/seat-name). bin/seat-name runs this through bin/ade-console-run;
## the arguments arrive in `ade_argv` and the exit status is left in `ade_exit_code`.
##
## Subcommands, flags, usage text and exit codes match the original: next, peek, issued, check;
## 0 ok, 1 error, 2 usage. The sequence file and its lock are the same files the Python tool uses,
## so both implementations can run against one state file during the transition.

init -5 python:

    SN_SUMMARY = "seat-name — one ever-increasing base-36 name for every Paseo seat, so no two are ever alike."
    SN_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"

    def sn_state_path():
        import os
        from pathlib import Path
        default = Path(os.path.expanduser("~")) / ".local/state/ade/seat-sequence.json"
        return str(Path(os.environ.get("SEAT_NAME_STATE", str(default))))

    def sn_default_role():
        import os
        return os.environ.get("SEAT_NAME_ROLE", "Dann")

    def sn_to_base36(n):
        """`n` (1-based) in base 36 using 0-9 then a-z. 1 -> '1', 10 -> 'a', 36 -> '10'."""
        if n < 1:
            raise ValueError("seat numbers start at 1")
        out = ""
        while n:
            n, rem = divmod(n, 36)
            out = SN_DIGITS[rem] + out
        return out

    def sn_slug(title, max_len=34):
        """A workspace slug from free text: lower case, hyphens, whole words, number-only words dropped.

        The same transformation autorename's title_slug uses, so both tools name workspaces alike.
        """
        import re
        words = [w for w in re.sub(r"[^a-z0-9]+", " ", title.lower()).split()
                 if not re.fullmatch(r"[0-9.-]+", w)]
        out = ""
        for w in words:
            cand = "%s-%s" % (out, w) if out else w
            if len(cand) > max_len:
                break
            out = cand
        return out or "session"

    def sn_load(state):
        import json
        from pathlib import Path
        try:
            d = json.loads(Path(state).read_text())
            if not isinstance(d, dict):
                raise ValueError("not an object")
            d.setdefault("next", 1)
            d.setdefault("issued", {})
            return d
        except (OSError, ValueError):
            return {"next": 1, "issued": {}}

    def sn_save(state, d):
        import json
        import os
        from pathlib import Path
        p = Path(state)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, indent=1, sort_keys=True))
        os.replace(tmp, p)

    def sn_allocate(state, kind, count, role=None, slug=None, agent=None):
        """Take `count` names from the sequence. The whole read-modify-write holds an flock, so two
        allocators at once cannot receive the same number.

        `kind` is `seat` (`<role> <n>`) or `workspace` (`<slug>-<n>-pw`); both draw from one counter.
        """
        import fcntl
        import time
        from pathlib import Path
        p = Path(state)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p.with_suffix(".lock"), "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            try:
                d = sn_load(state)
                out = []
                for _ in range(count):
                    n = int(d["next"])
                    if kind == "workspace":
                        if not slug:
                            raise ValueError("workspace names need --slug")
                        name = "%s-%s-pw" % (sn_slug(slug), sn_to_base36(n))
                    else:
                        name = "%s %s" % (role or sn_default_role(), sn_to_base36(n))
                    d["issued"][name] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                         "n": n, "kind": kind, "id": agent or ""}
                    d["next"] = n + 1
                    out.append(name)
                sn_save(state, d)
                return out
            finally:
                fcntl.flock(lk, fcntl.LOCK_UN)

    def sn_peek(state, count, role, kind="seat", slug=None):
        import fcntl
        from pathlib import Path
        with open(Path(state).with_suffix(".lock"), "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_SH)
            try:
                n0 = int(sn_load(state)["next"])
                if kind == "workspace":
                    return ["%s-%s-pw" % (sn_slug(slug or ""), sn_to_base36(n0 + i)) for i in range(count)]
                return ["%s %s" % (role or sn_default_role(), sn_to_base36(n0 + i)) for i in range(count)]
            finally:
                fcntl.flock(lk, fcntl.LOCK_UN)

    def sn_cmd_next(a):
        for name in sn_allocate(sn_state_path(), a.kind, a.count, role=a.role, slug=a.slug, agent=a.agent):
            print(name)
        return 0

    def sn_cmd_peek(a):
        for name in sn_peek(sn_state_path(), a.count, a.role, kind=a.kind, slug=a.slug):
            print(name)
        return 0

    def sn_cmd_issued(a):
        import json
        d = sn_load(sn_state_path())
        rows = sorted(d["issued"].items(), key=lambda kv: kv[1].get("n", 0), reverse=True)[:a.limit]
        if a.json:
            print(json.dumps([{"name": k, **v} for k, v in rows], indent=1))
            return 0
        for name, meta in rows:
            print("%-20s %s  %s" % (name, meta.get("at", "?"), meta.get("id") or ""))
        return 0

    def sn_cmd_check(a):
        """Prove the two properties that matter: monotonic (no reuse) and atomic under concurrency."""
        import re
        import tempfile
        import threading
        from pathlib import Path
        problems = []
        with tempfile.TemporaryDirectory() as tmp:
            state = str(Path(tmp) / "seq.json")

            # base 36, and the documented rollovers
            expect = {1: "1", 9: "9", 10: "a", 35: "z", 36: "10", 71: "1z", 1296: "100"}
            for n, want in expect.items():
                if sn_to_base36(n) != want:
                    problems.append("base36(%d)=%s want %s" % (n, sn_to_base36(n), want))

            # monotonic: no name ever repeats
            first = sn_allocate(state, "seat", 3, role="Test")
            second = sn_allocate(state, "seat", 3, role="Test")
            if len(set(first + second)) != 6:
                problems.append("names repeated: %s" % (first + second))
            if first != ["Test 1", "Test 2", "Test 3"]:
                problems.append("unexpected first three: %s" % first)

            # a workspace draws from the same counter, so a number never means two things
            ws = sn_allocate(state, "workspace", 2, slug="Dann Home")
            if ws != ["dann-home-7-pw", "dann-home-8-pw"]:
                problems.append("unexpected workspace names: %s" % ws)

            seen = []
            for name in first + second + ws:
                m = re.search(r"(?:^| )([0-9a-z]+)(?:-pw)?$", name)
                if m:
                    seen.append(m.group(1))
            if len(set(seen)) != len(seen):
                dupes = sorted({x for x in seen if seen.count(x) > 1})
                problems.append("a number was reused across seats and workspaces: %s" % dupes)

            # atomic: 6 concurrent allocators, 10 names each, every one distinct
            outs = [None] * 6
            errors = []

            def worker(i):
                try:
                    outs[i] = sn_allocate(state, "Conc", 10)
                except Exception as e:
                    errors.append("worker %d: %s" % (i, e))

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(60)
            problems.extend(errors)
            names = [x for o in outs if o for x in o]
            if len(names) != 60:
                problems.append("expected 60 names, got %d" % len(names))
            if len(set(names)) != len(names):
                dupes = sorted({x for x in names if names.count(x) > 1})
                problems.append("CONCURRENT DUPLICATES (the bug this prevents): %s" % dupes)

        status = "ok" if not problems else "PROBLEM"
        print("seat-name self-test")
        print("1. base-36 rendering: %s" % status)
        print("2. monotonic, no reuse: %s" % status)
        print("3. atomic under 6 concurrent allocators: %s" % status)
        print("self-test: " + ("FAILED: " + "; ".join(problems) if problems else "PASS"))
        return 1 if problems else 0

    def sn_parser():
        import argparse
        p = argparse.ArgumentParser(prog="seat-name", description=SN_SUMMARY)
        sub = p.add_subparsers(dest="command", required=True)
        n = sub.add_parser("next", help="allocate the next name(s)")
        n.add_argument("--role", default=sn_default_role(), help="for a seat: the role name")
        n.add_argument("--kind", choices=("seat", "workspace"), default="seat")
        n.add_argument("--slug", default=None, help="for a workspace: the slug before -<n>-pw")
        n.add_argument("--count", type=int, default=1)
        n.add_argument("--agent", default=None, help="the agent id this name is for (recorded)")
        n.set_defaults(func=sn_cmd_next)
        k = sub.add_parser("peek", help="the next name(s), without consuming")
        k.add_argument("--role", default=sn_default_role())
        k.add_argument("--kind", choices=("seat", "workspace"), default="seat")
        k.add_argument("--slug", default=None)
        k.add_argument("--count", type=int, default=1)
        k.set_defaults(func=sn_cmd_peek)
        i = sub.add_parser("issued", help="what has been handed out")
        i.add_argument("--limit", type=int, default=20)
        i.add_argument("--json", action="store_true")
        i.set_defaults(func=sn_cmd_issued)
        c = sub.add_parser("check", help="self-test: base-36 rendering, monotonic, atomic")
        c.set_defaults(func=sn_cmd_check)
        return p

    def sn_run(argv):
        """Run the tool on `argv`. Returns {"code", "out", "err"}; argparse's usage errors arrive as
        SystemExit and become the exit status 2 they always were."""
        import contextlib
        import io
        import sys
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            try:
                a = sn_parser().parse_args(list(argv))
                try:
                    code = a.func(a)
                except (ValueError, OSError) as e:
                    print("seat-name: error: %s" % e, file=sys.stderr)
                    code = 1
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        return {"code": code, "out": buf_out.getvalue(), "err": buf_err.getvalue()}

    def sn_show(result):
        """Mirror the captured output to the real streams and to the narrator, escaping Ren'Py markup."""
        import sys
        for text, stream in ((result["out"], sys.stdout), (result["err"], sys.stderr)):
            for line in text.splitlines():
                stream.write(line + "\n")
                renpy.say(None, line.replace("{", "{{").replace("[", "[["))
        sys.stdout.flush()
        sys.stderr.flush()


label tool_seat_name:
    $ sn_result = sn_run(ade_argv)
    $ sn_show(sn_result)
    $ ade_exit_code = sn_result["code"]
    return
