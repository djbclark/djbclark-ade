## gnu-tools-check: find macOS shell code that calls a BSD tool where the GNU one is wanted.
##
## Port of the Python scanner (HEAD:bin/gnu-tools-check). bin/gnu-tools-check runs this through
## bin/ade-console-run; the arguments arrive in `ade_argv` and the exit status is left in `ade_exit_code`.
##
## The scanner is pure standard-library code, so the port keeps its rules, its tokenizer and its
## exclude handling unchanged. Usage: gnu-tools-check [--exclude GLOB]... [PATH...] (default PATH: .).
## Exit 0 clean, 1 findings, 2 usage error. Findings print as file:line lines through the narrator.

init -5 python:

    import re as gct_re

    GCT_SUMMARY = ("gnu-tools-check: find macOS shell code that calls a BSD tool where the GNU one is wanted.")

    # BSD and GNU differ for these in ways that have bitten us (flags, regex dialect, -i).
    GCT_DIFFER = (
        "awk base64 cut date du find grep head mktemp readlink realpath sed seq sort "
        "split stat tail tar tee touch tr uniq wc xargs"
    ).split()
    # macOS ships these as BSD; GNU long options on them fail there.
    GCT_BSD_BASICS = "cat chmod chown cp df env id install ln ls mkdir mv rm rmdir sleep uname".split()

    GCT_DEFAULT_EXCLUDES = [
        "*/.git/*", "*/node_modules/*", "*/graft/*", "*/vendor/*", "*/.venv/*",
        "*/termux/*", "*/android/*", "*/.github/*", "*/.forgejo/*", "*/Dockerfile*",
        "*/gradlew",
        # Records, not instructions: session handoffs, dated reports, the memory index.
        "*/handoffs/*", "*/reports/*", "*/MEMORY.md",
    ]
    GCT_IGNORE_FILE = ".gnu-tools-check-ignore"
    GCT_PORTABLE = "gnu-tools-check: portable"
    GCT_IGNORE_LINE = "gnu-tools-check: ignore"

    # Command position: line start, after a pipe/separator/subshell, or after a word that runs its
    # argument as a command.
    _GCT_LEAD = r"(?:^|[|;&(`{]|\$\(|\b(?:then|do|else|exec|command|xargs|nohup|sudo|time)\s)\s*"
    GCT_DIFFER_RE = gct_re.compile(_GCT_LEAD + r"(" + "|".join(sorted(GCT_DIFFER, key=len, reverse=True)) + r")(?=[\s;)|&]|$)")
    GCT_BASIC_RE = gct_re.compile(_GCT_LEAD + r"(" + "|".join(sorted(GCT_BSD_BASICS, key=len, reverse=True)) + r")\s+([^|;&)]*)")
    GCT_LONG_OPT = gct_re.compile(r"(?:^|\s)(--[a-z][\w-]*)")
    GCT_SHEBANG = gct_re.compile(rb"^#!.*\b(?:ba|z)?sh\b")
    GCT_FENCE_OPEN = gct_re.compile(r"^\s*(```+|~~~+)\s*(bash|sh|shell|zsh|console)\b")
    GCT_SPAN = gct_re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
    GCT_PIPELINE = gct_re.compile(r"[|;&`]|\$\(")
    GCT_HEREDOC = gct_re.compile(r"<<-?\s*(['\"]?)([A-Za-z_]\w*)\1")

    def gct_is_shell(path):
        from pathlib import Path
        name = path.name
        if name.endswith((".sh", ".bash", ".zsh", ".sh.j2", ".just")) or name in ("justfile", "Justfile"):
            return True
        try:
            with path.open("rb") as fh:
                return bool(GCT_SHEBANG.match(fh.read(128)))
        except OSError:
            return False

    def gct_inline_pipelines(line):
        """Inline code spans that hold a pipeline, each prefixed with a dummy word so a tool named at
        the start of a span (prose: "`sed -i ''` is BSD") is not a call."""
        spans = [s.replace("\\|", "|") for s in GCT_SPAN.findall(line)]
        keep = [
            s for s in spans
            if GCT_PIPELINE.search(s) and "{{" not in s and ".action{" not in s
            and s.count("'") % 2 == 0 and s.count('"') % 2 == 0
        ]
        return " ; ".join("x " + s for s in keep)

    def gct_markdown_shell(text):
        """The shell code of a Markdown file: fenced shell blocks, and inline code spans that hold a
        pipeline. Other lines are blank, so line numbers still match. In a console block only
        "$ " / "% " prompt lines count."""
        out, fence, console = [], None, False
        for line in text.splitlines():
            if GCT_IGNORE_LINE in line:
                out.append("")
            elif fence is None:
                m = GCT_FENCE_OPEN.match(line)
                if m:
                    fence, console = m.group(1), m.group(2) == "console"
                    out.append("")
                elif line.lstrip().startswith(("```", "~~~")):
                    fence, console = "NOSHELL" + line.strip()[:3], False
                    out.append("")
                else:
                    out.append(gct_inline_pipelines(line))
            elif fence.startswith("NOSHELL"):
                if line.strip().startswith(fence[7:]):
                    fence = None
                out.append("")
            elif line.strip().startswith(fence):
                fence = None
                out.append("")
            elif console:
                s = line.lstrip()
                out.append(s[2:] if s.startswith(("$ ", "% ")) else "")
            else:
                out.append(line)
        return "\n".join(out) + "\n"

    def gct_excluded(path, globs):
        import fnmatch
        return any(fnmatch.fnmatch(path, g) or fnmatch.fnmatch("/" + path, g) for g in globs)

    def gct_code_lines(text):
        """The text's lines with quoted text, comments and heredoc bodies blanked.

        Single-quoted text is never code here: it is a remote command, a jq/awk program or a message.
        Double-quoted text is blanked except for $(...) and `...` inside it, which run locally.
        """
        out, cur = [], []
        stack = ["code"]  # code | sq | dq | sub | bt
        heredocs = []
        i, n = 0, len(text)
        line_start = 0
        at_word_start = True
        while i < n:
            c = text[i]
            if c == "\n":
                line = "".join(cur)
                out.append(line)
                cur = []
                raw = text[line_start:i]
                for m in GCT_HEREDOC.finditer(raw):
                    if line[m.start():m.start() + 2] == "<<" and not raw.startswith("<<<", m.start()) and (
                        m.start() == 0 or raw[m.start() - 1] != "<"
                    ):
                        heredocs.append(m.group(2))
                i += 1
                at_word_start = True
                while heredocs and i < n:
                    end = text.find("\n", i)
                    end = n if end < 0 else end
                    out.append("")
                    if text[i:end].strip() == heredocs[0]:
                        heredocs.pop(0)
                    i = end + 1
                line_start = i
                continue
            top = stack[-1]
            if top == "sq":
                if c == "'":
                    stack.pop()
                cur.append(" ")
            elif top == "dq":
                if c == "\\" and i + 1 < n and text[i + 1] != "\n":
                    cur.append("  ")
                    i += 1
                elif c == '"':
                    stack.pop()
                    cur.append(" ")
                elif text.startswith("$(", i) and not text.startswith("$((", i):
                    stack.append("sub")
                    cur.append("$(")
                    i += 1
                    at_word_start = True
                elif c == "`":
                    stack.append("bt")
                    cur.append("`")
                    at_word_start = True
                else:
                    cur.append(" ")
            else:  # code, sub, bt
                if c == "#" and at_word_start:
                    j = text.find("\n", i)
                    j = n if j < 0 else j
                    cur.append(" " * (j - i))
                    i = j
                    continue
                if c == "\\" and i + 1 < n and text[i + 1] != "\n":
                    cur.append("  ")
                    i += 2
                    at_word_start = False
                    continue
                if c == "'":
                    stack.append("sq")
                    cur.append(" ")
                elif c == '"':
                    stack.append("dq")
                    cur.append(" ")
                elif c == "`" and top == "bt":
                    stack.pop()
                    cur.append("`")
                elif c == "`":
                    stack.append("bt")
                    cur.append("`")
                elif c == "(":
                    stack.append("sub")
                    cur.append(c)
                elif c == ")" and top == "sub":
                    stack.pop()
                    cur.append(c)
                else:
                    cur.append(c)
                at_word_start = c in " \t;|&(){}`"
            i += 1
        out.append("".join(cur))
        return out

    def gct_scan_text(text):
        """Yield (line_no, tool, message) for one file's text."""
        raw = text.splitlines()
        if any(GCT_PORTABLE in ln for ln in raw[:20]):
            return
        for no, line in enumerate(gct_code_lines(text), 1):
            s = line.strip()
            if not s or (no <= len(raw) and GCT_IGNORE_LINE in raw[no - 1]):
                continue
            for m in GCT_DIFFER_RE.finditer(s):
                tool = m.group(1)
                yield no, tool, "bare %s is BSD on macOS: use g%s" % (tool, tool)
            for m in GCT_BASIC_RE.finditer(s):
                tool = m.group(1)
                for word in m.group(2).split():
                    if word == "--" or not word.startswith("-"):
                        break
                    if GCT_LONG_OPT.match(word):
                        yield no, tool, "%s %s is GNU-only: use g%s" % (tool, word.split("=")[0], tool)
                        break

    def gct_git_files(root):
        """Tracked and untracked-but-not-ignored files under root, or None outside git."""
        import subprocess
        try:
            r = subprocess.run(
                ["git", "-C", str(root), "ls-files", "-z", "-co", "--exclude-standard"],
                capture_output=True, check=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        return [root / p for p in r.stdout.decode(errors="replace").split("\0") if p]

    def gct_iter_files(root, globs):
        import os
        from pathlib import Path
        if root.is_file():
            yield root
            return
        listed = gct_git_files(root)
        if listed is not None:
            for p in listed:
                if p.is_file() and not p.is_symlink() and not gct_excluded(str(p), globs):
                    yield p
            return
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not gct_excluded(os.path.join(dirpath, d) + "/", globs)]
            for f in filenames:
                p = Path(dirpath, f)
                if not gct_excluded(str(p), globs) and not p.is_symlink():
                    yield p

    def gct_load_ignore(root):
        from pathlib import Path
        f = (root if root.is_dir() else root.parent) / GCT_IGNORE_FILE
        if not f.is_file():
            return []
        out = []
        for ln in f.read_text().splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                out.append(str((f.parent / ln)) if not ln.startswith("*") else ln)
        return out

    def gct_main(argv):
        import argparse
        import sys
        from pathlib import Path
        ap = argparse.ArgumentParser(prog="gnu-tools-check", description=GCT_SUMMARY)
        ap.add_argument("paths", nargs="*", default=["."])
        ap.add_argument("--exclude", action="append", default=[], metavar="GLOB")
        args = ap.parse_args(argv)
        findings = 0
        for raw in args.paths:
            root = Path(raw).expanduser()
            if not root.exists():
                print("gnu-tools-check: no such path: %s" % raw, file=sys.stderr)
                return 2
            globs = GCT_DEFAULT_EXCLUDES + args.exclude + gct_load_ignore(root)
            for path in gct_iter_files(root, globs):
                is_md = path.suffix.lower() == ".md"
                if not is_md and not gct_is_shell(path):
                    continue
                try:
                    text = path.read_text(errors="replace")
                except OSError:
                    continue
                if is_md:
                    if any(GCT_PORTABLE in ln for ln in text.splitlines()[:20]):
                        continue
                    text = gct_markdown_shell(text)
                for no, _tool, msg in gct_scan_text(text):
                    print("%s:%d: %s" % (path, no, msg))
                    findings += 1
        return 1 if findings else 0

    def gct_run(argv):
        """Run the scanner on `argv`; returns {"code", "out", "err"}. argparse's usage errors arrive
        as SystemExit and keep their status 2."""
        import contextlib
        import io
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            try:
                code = gct_main(list(argv))
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        return {"code": code, "out": buf_out.getvalue(), "err": buf_err.getvalue()}

    def gct_show(result):
        """Mirror the captured output to the real streams and to the narrator, escaping Ren'Py markup."""
        import sys
        for text, stream in ((result["out"], sys.stdout), (result["err"], sys.stderr)):
            for line in text.splitlines():
                stream.write(line + "\n")
                renpy.say(None, line.replace("{", "{{").replace("[", "[["))
        sys.stdout.flush()
        sys.stderr.flush()


label tool_gnu_tools_check:
    $ gct_result = gct_run(ade_argv)
    $ gct_show(gct_result)
    $ ade_exit_code = gct_result["code"]
    return
