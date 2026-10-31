## skill-everywhere: make a shared skill visible to every agent TUI on this machine by linking it
## into each TUI's user-level skills dir. Port of the original bin/skill-everywhere (bash).
## Entry label: tool_skill_everywhere; arguments in ade_argv; exit code in ade_exit_code.
##
## Modes: link (default), --check, --remove; --dry-run/-n for link and remove; --all syncs every shared skill.
## SKILL_EVERYWHERE_ONLY limits the targets; SKILL_EVERYWHERE_NO_COPY=1 skips the grokbot copy target.
## Output goes to the process stdout/stderr: callers and ade-update read it.

init python:
    import argparse as _se_argparse
    import os as _se_os
    import re as _se_re
    import shutil as _se_shutil
    import subprocess as _se_subprocess
    import sys as _se_sys

    SE_USAGE = [
        "Make a shared skill visible to every agent TUI on this machine by",
        "symlinking it into each TUI's user-level skills dir.",
        "    skill-everywhere --all                sync every public/private shared skill",
        "    skill-everywhere --check --all        verify every installed target; exit 1 for gaps",
        "    skill-everywhere <name>...            link (idempotent, collapses chains)",
        "    skill-everywhere --check <name>...    report per-TUI status, change nothing; ends with a \"== end\" line",
        "    skill-everywhere --remove <name>...   remove links this script would make",
        "    --dry-run (-n) with link or --remove: print the changes, make none",
        "    SKILL_EVERYWHERE_ONLY=grokbot,claude limits the run to those targets",
        "    SKILL_EVERYWHERE_NO_COPY=1 skips the copy target (grokbot): ade-update sets it for a non-canonical checkout, which",
        "    is a report-only run, so such a run neither lists nor renders the Grok Bot copy",
        "    The grokbot copy refuses a skill holding a symlink that is not a link to a regular file inside the skill (one that",
        "    leaves the skill, dangles, or names a directory or special file): --check reports \"unsafe source symlink\"; link",
        "    mode copies nothing, leaves any existing copy alone and exits 1",
    ]

    # binary|dir, "via <dir>" (the TUI already reads a dir we fill), "x <why>", or "copy <dir>" (rendered copy)
    SE_TARGETS = [
        ("claude", "~/.claude/skills"),
        ("codex", "~/.agents/skills"),
        ("goose", "~/.agents/skills"),
        ("agy", "~/.gemini/antigravity-cli/skills"),
        ("copilot", "~/.copilot/skills"),
        ("opencode", "~/.config/opencode/skills"),
        ("qwen", "~/.qwen/skills"),
        ("devin", "~/.config/devin/skills"),
        ("cline", "~/.cline/skills"),
        ("hermes", "~/.local/share/skill-everywhere/skills"),
        ("cursor-agent", "via ~/.claude/skills"),
        ("grok", "~/.grok/skills"),
        ("muse", "via ~/.claude/skills"),
        ("zcode", "via ~/.agents/skills"),
        ("omp", "~/.omp/agent/skills"),
        ("grokbot", "copy ~/agent-data/workflows"),
    ]

    SE_NAME_RE = _se_re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

    SE_HERMES_SNIPPET = '''
import os, sys
from pathlib import Path
bin_dir = Path(sys.executable).parent
root = bin_dir.parent.parent.resolve() if bin_dir.name == ".venv" else bin_dir.parent.parent
for r in (Path(os.environ["HERMES_HOME"]) / "hermes-agent", root):
    if r.is_dir() and str(r) not in sys.path:
        sys.path.insert(0, str(r))
try:
    from gateway.control_socket import reload_gateway_plugins
except Exception:
    raise SystemExit
os.environ.setdefault("HERMES_HOME", os.path.expanduser("~/.hermes"))
try:
    r = reload_gateway_plugins(Path(os.environ["HERMES_HOME"]), timeout=20)
    print("hermes gateway: plugins %s" % ("reloaded" if r and r.get("reloaded") else "not reloaded (no answer)"))
except Exception as e:
    print("hermes gateway: plugin nudge skipped: %s" % e)
'''

    def se_out(msg):
        print(msg, file=_se_sys.__stdout__)

    def se_err(msg):
        print(msg, file=_se_sys.__stderr__)

    def se_expand(p):
        return _se_os.path.expanduser(p)

    def se_unsafe_links(root_dir):
        """Symlinks under root_dir that are not links to a regular file inside the skill."""
        root = _se_os.path.realpath(root_dir)
        bad = []
        for dirpath, dirnames, filenames in _se_os.walk(root):
            for n in dirnames + filenames:
                link = _se_os.path.join(dirpath, n)
                if not _se_os.path.islink(link):
                    continue
                if not _se_os.path.exists(link):
                    bad.append(link)
                    continue
                t = _se_os.path.realpath(link)
                if not (t.startswith(root + _se_os.sep) and _se_os.path.isfile(t)):
                    bad.append(link)
        return bad

    def se_render_copy(src, out, name, banner_note):
        """Render a grokbot copy of src into out; False (nothing copied) if a source symlink is unsafe."""
        bad = se_unsafe_links(src)
        if bad:
            se_err("error: unsafe source symlink, not copying %s (a link must point at a regular file "
                   "inside the skill): %s" % (src, " ".join(bad)))
            return False
        _se_shutil.copytree(src, out, symlinks=False)
        _se_shutil.rmtree(_se_os.path.join(out, ".git"), ignore_errors=True)
        for dirpath, dirnames, _files in _se_os.walk(out):
            if "__pycache__" in dirnames:
                _se_shutil.rmtree(_se_os.path.join(dirpath, "__pycache__"), ignore_errors=True)
                dirnames.remove("__pycache__")
        with open(_se_os.path.join(out, ".skill-everywhere"), "w") as fh:
            fh.write("source=djbclark-ade/skills/%s\nmanaged-by=bin/skill-everywhere (grokbot target)\n" % name)
        banner = ("> **Managed copy, do not edit here.** Rendered by djbclark-ade `bin/skill-everywhere` from\n"
                  "> [`skills/%s`](https://github.com/djbclark/djbclark-ade/tree/master/skills/%s); the next sync\n"
                  "> overwrites local edits. Written for the agent TUIs on djbclark's Mac: `~/src/<repo>` is\n"
                  "> `/home/box/src/<repo>` here when cloned, and Mac-only tools (launchd, herdr, Orca, Keychain,\n"
                  "> `hermes-ping`) are absent. Grok Bot's own rules win: sending, posting, pushing or merging still\n"
                  "> needs the operator's explicit approval." % (name, name))
        if banner_note:
            banner += "\n>\n> " + banner_note
        skill_md = _se_os.path.join(out, "SKILL.md")
        lines = open(skill_md).read().split("\n")
        result, fences = [], 0
        for line in lines:
            result.append(line)
            if fences < 2 and _se_re.match(r"^---[ \t]*$", line):
                fences += 1
                if fences == 2:
                    result.append("")
                    result.append(banner)
        with open(skill_md, "w") as fh:
            fh.write("\n".join(result))
        return True

    def se_mode_state_copy(ctx, bin_name, dir_, src, name):
        dest_dir = se_expand(dir_)
        if not _se_os.path.isdir(dest_dir):
            se_out("  %-13s not installed (no %s)" % (bin_name, dest_dir))
            return 0
        dest = _se_os.path.join(dest_dir, "ade-" + name)
        if not _se_os.path.lexists(dest):
            state = "missing"
        elif not _se_os.path.isfile(_se_os.path.join(dest, ".skill-everywhere")):
            state = "real dir/file (not ours)"
        elif not _se_os.path.isfile(_se_os.path.join(src, "SKILL.md")):
            state = "copy of a removed skill"
        else:
            state = "render"
        unsafe = False
        if ctx["mode"] != "remove" and state in ("missing", "render") \
                and _se_os.path.isfile(_se_os.path.join(src, "SKILL.md")):
            bad = se_unsafe_links(src)
            if bad:
                state = "unsafe source symlink"
                unsafe = True
                se_err("warning: %s: %s is not copied, a symlink in it leaves the skill or is not a regular file: %s"
                       % (name, src, " ".join(bad)))
        if unsafe:
            pass
        elif state == "render" and ctx["mode"] == "remove":
            state = "copied"
        elif state == "render":
            tmp = _se_os.path.join(dest_dir, ".ade-%s.tmp-check" % name)
            _se_shutil.rmtree(tmp, ignore_errors=True)
            if se_render_copy(src, tmp, name, ctx["note"]):
                same = _se_subprocess.run(["diff", "-r", tmp, dest], stdout=_se_subprocess.DEVNULL,
                                          stderr=_se_subprocess.DEVNULL).returncode == 0
                state = "copied" if same else "stale copy"
            _se_shutil.rmtree(tmp, ignore_errors=True)
        rc = 0
        if ctx["mode"] == "check":
            se_out("  %-13s %s (%s)" % (bin_name, state, dest))
            if ctx["all"] and state != "copied":
                rc = 1
        elif ctx["mode"] == "remove":
            if state == "missing" or state.startswith("real"):
                se_out("  %-13s %s (left alone)" % (bin_name, state))
            else:
                ctx["act"](bin_name, "remove " + dest, lambda: _se_shutil.rmtree(dest))
                if not ctx["dry"]:
                    se_out("  %-13s removed %s" % (bin_name, dest))
        else:
            if state == "copied":
                se_out("  %-13s already copied" % bin_name)
            elif state in ("missing", "stale copy"):
                def do_copy():
                    stage = _se_os.path.join(dest_dir, ".ade-%s.new" % name)
                    _se_shutil.rmtree(stage, ignore_errors=True)
                    if not se_render_copy(src, stage, name, ctx["note"]):
                        raise RuntimeError("copy refused")
                    _se_shutil.rmtree(dest, ignore_errors=True)
                    _se_os.replace(stage, dest)
                try:
                    ctx["act"](bin_name, "copy to %s (%s)" % (dest, state), do_copy)
                except RuntimeError:
                    rc = 1
                    se_out("  %-13s copy refused; left alone" % bin_name)
                    return rc
                if not ctx["dry"]:
                    se_out("  %-13s copied (was %s)" % (bin_name, state))
            else:
                se_out("  %-13s %s; left alone" % (bin_name, state))
                rc = 1
        return rc

    def se_hermes_nudge():
        """Ask the running Hermes gateway to reload plugins (best effort, prints its own line)."""
        hfile = _se_shutil.which("hermes")
        hpy = ""
        for _ in range(3):
            try:
                text = open(hfile, errors="replace").read()
            except OSError:
                break
            first = text.split("\n", 1)[0]
            shebang = first[2:].split(" ")[0] if first.startswith("#!") else ""
            if _se_os.path.basename(shebang).startswith("python") and _se_os.access(shebang, _se_os.X_OK):
                hpy = shebang
                break
            m = _se_re.search(r"exec +(/[^ \"']+)", text)
            nxt = m.group(1) if m else ""
            if _se_os.path.basename(nxt).startswith("python") and _se_os.access(nxt, _se_os.X_OK):
                hpy = nxt
                break
            if not nxt or not _se_os.path.isfile(nxt):
                break
            hfile = nxt
        if not hpy:
            hpy = _se_shutil.which("python3") or "python3"
        env = dict(_se_os.environ)
        env["HERMES_HOME"] = _se_os.environ.get("HERMES_HOME") or _se_os.path.expanduser("~/.hermes")
        res = _se_subprocess.run([hpy, "-c", SE_HERMES_SNIPPET], env=env, stdout=_se_subprocess.PIPE,
                                 stderr=_se_subprocess.DEVNULL, universal_newlines=True)
        if res.stdout:
            se_out(res.stdout.rstrip("\n"))

    def se_gather_all(ade_root, priv_root):
        names = []
        for root in (ade_root, priv_root):
            if not _se_os.path.isdir(root):
                continue
            for entry in sorted(_se_os.listdir(root)):
                skill_file = _se_os.path.join(root, entry, "SKILL.md")
                if not (_se_os.path.isfile(skill_file) and _se_os.access(skill_file, _se_os.R_OK)):
                    continue
                if not SE_NAME_RE.match(entry):
                    return None, "error: unsafe skill directory name: %s" % entry
                if entry not in names:
                    names.append(entry)
        return names, None

    def skill_everywhere_run(argv):
        ap = _se_argparse.ArgumentParser(prog="skill-everywhere", add_help=False)
        ap.add_argument("--check", action="store_true")
        ap.add_argument("--remove", action="store_true")
        ap.add_argument("--dry-run", "-n", action="store_true")
        ap.add_argument("--all", action="store_true")
        ap.add_argument("names", nargs="*")
        args = list(argv)
        opts = []
        while args and args[0].startswith("-"):
            if args[0] not in ("--check", "--remove", "--dry-run", "-n", "--all"):
                se_err("error: unknown option %s" % args[0])
                return 2
            opts.append(args.pop(0))
        a = ap.parse_args(opts + args)
        mode = "check" if a.check else ("remove" if a.remove else "link")
        names = list(a.names)
        if a.all:
            if names or mode == "remove":
                se_err("error: --all accepts no names and cannot be used with --remove")
                return 2
        ade_root = _se_os.environ.get("SKILL_EVERYWHERE_ADE") or _se_os.path.expanduser("~/src/djbclark-ade/skills")
        priv_root = _se_os.environ.get("SKILL_EVERYWHERE_PRIVATE") or _se_os.path.join(
            _se_os.environ.get("OPS_ROOT") or _se_os.path.expanduser("~/ops"), "site-private/skills")
        if a.all:
            names, err = se_gather_all(ade_root, priv_root)
            if err:
                se_err(err)
                return 2
            if not names:
                se_err("error: no readable shared SKILL.md files under %s or %s" % (ade_root, priv_root))
                return 2
        if not names:
            for line in SE_USAGE:
                se_err(line)
            return 2
        only = _se_os.environ.get("SKILL_EVERYWHERE_ONLY", "")
        no_copy = bool(_se_os.environ.get("SKILL_EVERYWHERE_NO_COPY"))
        note = _se_os.environ.get("SKILL_EVERYWHERE_GROKBOT_NOTE", "")
        ctx = {"mode": mode, "all": a.all, "dry": a.dry_run, "note": note}
        rc = 0

        def wanted(b):
            return (not only) or (b in only.split(","))

        def act(bin_name, msg, fn):
            if ctx["dry"]:
                se_out("  %-13s would %s" % (bin_name, msg))
            else:
                fn()

        ctx["act"] = act

        codex_home = _se_os.environ.get("CODEX_HOME") or _se_os.path.expanduser("~/.codex")
        codex_instructions = _se_os.path.join(codex_home, "AGENTS.md")
        if mode == "check" and wanted("codex") and _se_os.path.islink(codex_instructions) \
                and not _se_os.path.exists(codex_instructions):
            se_err("warning: codex global instructions dangling: %s -> %s"
                   % (codex_instructions, _se_os.readlink(codex_instructions)))
            rc = 1

        for name in names:
            if _se_os.path.isfile(_se_os.path.join(ade_root, name, "SKILL.md")):
                src = _se_os.path.join(ade_root, name)
            elif _se_os.path.isfile(_se_os.path.join(priv_root, name, "SKILL.md")):
                src = _se_os.path.join(priv_root, name)
            else:
                if mode != "remove":
                    se_err("error: no SKILL.md under %s or %s" % (_se_os.path.join(ade_root, name),
                                                                    _se_os.path.join(priv_root, name)))
                    rc = 1
                    continue
                src = _se_os.path.join(ade_root, name)
            se_out("== %s" % name)
            for bin_name, dir_ in SE_TARGETS:
                if not wanted(bin_name):
                    continue
                if dir_.startswith("copy "):
                    if not no_copy:
                        rc = max(rc, se_mode_state_copy(ctx, bin_name, dir_[5:], src, name))
                    continue
                if _se_shutil.which(bin_name) is None:
                    se_out("  %-13s not installed" % bin_name)
                    continue
                if dir_.startswith("via") or dir_.startswith("x "):
                    se_out("  %-13s %s" % (bin_name, dir_[2:] if dir_.startswith("x ") else dir_))
                    continue
                link = _se_os.path.join(se_expand(dir_), name)
                if _se_os.path.islink(link) and _se_os.readlink(link) == src:
                    state = "linked"
                elif _se_os.path.islink(link) and _se_os.path.exists(src) \
                        and _se_os.path.realpath(link) == _se_os.path.realpath(src):
                    state = "chained via %s" % _se_os.readlink(link)
                elif _se_os.path.islink(link) and not _se_os.path.exists(link):
                    state = "dangling -> %s" % _se_os.readlink(link)
                elif _se_os.path.islink(link):
                    state = "other link -> %s" % _se_os.readlink(link)
                elif _se_os.path.exists(link):
                    state = "real dir/file (not ours)"
                else:
                    state = "missing"
                if mode == "check":
                    se_out("  %-13s %s" % (bin_name, state))
                    if a.all and state != "linked":
                        rc = 1
                elif mode == "remove":
                    if state == "linked":
                        ctx["act"](bin_name, "remove " + link, lambda l=link: _se_os.remove(l))
                        if not a.dry_run:
                            se_out("  %-13s removed" % bin_name)
                    else:
                        se_out("  %-13s %s (left alone)" % (bin_name, state))
                else:
                    if state == "missing":
                        def do_link(d=se_expand(dir_), l=link, s=src):
                            _se_os.makedirs(d, exist_ok=True)
                            _se_os.symlink(s, l)
                        ctx["act"](bin_name, "link " + link, do_link)
                        if not a.dry_run:
                            se_out("  %-13s linked" % bin_name)
                    elif state == "linked":
                        se_out("  %-13s already linked" % bin_name)
                    elif state.startswith("chained") or state.startswith("dangling"):
                        def do_relink(l=link, s=src):
                            _se_os.unlink(l)
                            _se_os.symlink(s, l)
                        ctx["act"](bin_name, "relink %s direct" % link, do_relink)
                        if not a.dry_run:
                            se_out("  %-13s relinked (was %s)" % (bin_name, state))
                    else:
                        se_out("  %-13s %s; left alone" % (bin_name, state))
                        rc = 1
        if mode == "check":
            se_out("== end")
        if wanted("hermes") and _se_shutil.which("hermes"):
            cfg = _se_os.path.join(_se_os.environ.get("HERMES_HOME") or _se_os.path.expanduser("~/.hermes"),
                                   "config.yaml")
            try:
                listed = "skill-everywhere/skills" in open(cfg).read()
            except OSError:
                listed = False
            if not listed:
                se_err("warning: hermes no longer lists ~/.local/share/skill-everywhere/skills in "
                       "skills.external_dirs; ask Hermes to re-add it")
        if mode == "link" and not a.dry_run and wanted("hermes") and _se_shutil.which("hermes"):
            try:
                se_hermes_nudge()
            except OSError:
                pass
        _se_sys.__stdout__.flush()
        _se_sys.__stderr__.flush()
        return rc

label tool_skill_everywhere:
    python:
        ade_exit_code = skill_everywhere_run(ade_argv)
    return
