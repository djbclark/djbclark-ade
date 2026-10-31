## skill-get: load one agent skill on demand, for small-context models.
## Port of the original bin/skill-get (Python). Entry label: tool_skill_get; arguments in ade_argv.
##
##   skill-get --list [keyword ...]        compact catalogue (names only; with keywords: name + one-liner)
##   skill-get <name> [--offset N] [--max-chars N]
##   skill-get <name> --ref <relative/path>   a file under the skill's references/ or scripts/
##
## Exit 0 ok, 1 not found, 2 usage. Output goes to the process stdout/stderr, not the game window,
## because callers capture it; narrator is for operator choices only.

init python:
    import argparse
    import difflib
    import os
    import re
    import sys
    from pathlib import Path

    _SKILL_HOME = Path(os.path.expanduser("~"))
    _SKILL_ROOTS = [
        _SKILL_HOME / "src/djbclark-ade/skills",
        _SKILL_HOME / ".claude/skills",
        _SKILL_HOME / ".agents/skills",
        _SKILL_HOME / "ops/site-private/skills",
    ]
    if os.environ.get("SKILL_GET_ROOTS"):
        _SKILL_ROOTS = [Path(p) for p in os.environ["SKILL_GET_ROOTS"].split(os.pathsep) if p]

    def skill_find_skills():
        found = {}
        for root in _SKILL_ROOTS:
            if not root.is_dir():
                continue
            for d in sorted(root.iterdir()):
                if d.name.startswith(".") or not (d / "SKILL.md").is_file():
                    continue
                found.setdefault(d.name, d)
        return found

    def skill_split_frontmatter(text):
        m = re.match(r"\A---\s*\n(.*?)\n---\s*\n?", text, re.S)
        return (m.group(1), text[m.end():]) if m else ("", text)

    def skill_description(front):
        m = re.search(r"^description:[ \t]*(.*(?:\n[ \t]+.*)*)", front, re.M)
        if not m:
            return ""
        d = re.sub(r"\s+", " ", m.group(1)).strip()
        return re.sub(r"^[>|][-+]?\s*", "", d).strip("\"'")

    def skill_cmd_list(skills, words):
        if not words:
            names = sorted(skills)
            out = [f"{len(names)} skills. Names only; `skill-get --list <keyword>` shows what they do, "
                   "`skill-get <name>` loads one.",
                   ", ".join(names)]
            return 0, out, []
        rows = []
        for name, d in sorted(skills.items()):
            desc = skill_description(skill_split_frontmatter((d / "SKILL.md").read_text(errors="replace"))[0])
            hay = (name + " " + desc).lower()
            if all(w.lower() in hay for w in words):
                rows.append(f"{name}: {desc[:120]}")
        if not rows:
            msg = ("no skill matches " + " ".join(words)
                   + "; try one keyword, or `skill-get --list`.")
            return 1, [msg], []
        out = rows[:25]
        if len(rows) > 25:
            out.append(f"... {len(rows) - 25} more; add a keyword.")
        return 0, out, []

    def skill_cmd_get(skills, name, offset, max_chars, ref):
        d = skills.get(name)
        if d is None:
            near = difflib.get_close_matches(name, list(skills), n=5, cutoff=0.5)
            hint = f" Close: {', '.join(near)}." if near else ""
            return 1, [], [f"skill-get: no skill named {name!r}." + hint
                           + " `skill-get --list <keyword>` searches."]
        if ref:
            f = (d / ref).resolve()
            if not str(f).startswith(str(d.resolve())) or not f.is_file():
                return 1, [], [f"skill-get: {ref!r} is not a file inside {d}."]
            body = f.read_text(errors="replace")
            head = f"FILE: {f}"
            again = f"skill-get {name} --ref {ref}"
        else:
            body = skill_split_frontmatter((d / "SKILL.md").read_text(errors="replace"))[1].lstrip("\n")
            head = f"SKILL: {name}   DIR: {d.resolve()}   (relative paths in it are under DIR)"
            again = f"skill-get {name}"
        chunk = body[offset:offset + max_chars]
        out = [head, "", chunk.rstrip()]
        end = offset + len(chunk)
        if end < len(body):
            out.append(f"\nTRUNCATED: {len(body) - end} more characters. Next page: {again} --offset {end}")
        if not ref and offset == 0:
            extra = [str(p.relative_to(d)) for sub in ("references", "scripts")
                     for p in sorted((d / sub).glob("*")) if p.is_file()][:12]
            if extra:
                out.append("\nMORE FILES (read one only if needed): " + ", ".join(extra)
                           + f"  -> {again} --ref <path>")
        return 0, out, []

    def skill_get_run(argv):
        """Return (exit_code, stdout_lines, stderr_lines) for the original skill-get argv."""
        ap = argparse.ArgumentParser(prog="skill-get", description="Load an agent skill on demand.")
        ap.add_argument("name", nargs="*", help="skill name; with --list, keywords")
        ap.add_argument("--list", action="store_true", help="catalogue (names only) or keyword search")
        ap.add_argument("--offset", type=int, default=0)
        ap.add_argument("--max-chars", type=int, default=7000)
        ap.add_argument("--ref", help="a file under the skill dir, e.g. references/foo.md")
        try:
            a = ap.parse_args(argv)
        except SystemExit as exc:
            return (exc.code if isinstance(exc.code, int) else 2), [], []
        skills = skill_find_skills()
        if a.list:
            return skill_cmd_list(skills, a.name)
        if len(a.name) != 1:
            return 2, [], ["skill-get: error: give exactly one skill name, or --list [keyword]"]
        return skill_cmd_get(skills, a.name[0].lstrip("/"), max(0, a.offset),
                             max(500, a.max_chars), a.ref)

label tool_skill_get:
    python:
        _skill_code, _skill_out, _skill_err = skill_get_run(ade_argv)
        for _line in _skill_out:
            print(_line, file=sys.__stdout__)
        for _line in _skill_err:
            print(_line, file=sys.__stderr__)
        sys.__stdout__.flush()
        sys.__stderr__.flush()
        ade_exit_code = _skill_code
    return
