#!/opt/homebrew/opt/python@3.14/bin/python3.14
"""Flatten SKILL.md frontmatter to plain string values (with .bak backups).

Some agent TUIs (crush at least) parse SKILL.md frontmatter with an
all-strings schema: maps and lists under `metadata` (or anywhere else) make
the file unparseable for them, and a description over 1024 bytes fails
validation. Registry-managed skills (e.g. `bl skill` updates for bailian-*)
overwrite fixed files, so re-run this after updates:

    fix-skill-frontmatter.py ~/.bailian/skills/*/SKILL.md
    fix-skill-frontmatter.py --scan ~/.bailian/skills ~/.agents/skills

Every value is coerced to a string (lists join with ", ", dicts flatten to
"k=v; ..."), and descriptions are truncated to <= 1000 bytes with an ellipsis
so they stay under crush's 1024-byte (Go len, i.e. bytes) cap. The original
file is kept beside it as SKILL.md.bak (never overwritten once written).
"""

import argparse
import os
import re
import shutil
import sys

import yaml

MAX_DESC_BYTES = 1000  # safety margin under crush's 1024-byte limit
ELLIPSIS = "……"


def to_str(v):
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return ", ".join(to_str(x) for x in v)
    if isinstance(v, dict):
        return "; ".join(f"{k}={to_str(x)}" for k, x in v.items())
    return str(v)


def trunc_bytes(s, limit=MAX_DESC_BYTES):
    b = s.encode("utf-8")
    if len(b) <= limit:
        return s
    return b[:limit].decode("utf-8", errors="ignore").rstrip() + ELLIPSIS


def needs_fix(fm):
    def leaves(v):
        if isinstance(v, dict):
            for x in v.values():
                yield from leaves(x)
        else:
            yield v
    if any(not isinstance(x, str) for x in leaves(fm)):
        return True
    return len(fm.get("description", "").encode("utf-8")) > 1024


def fix(path):
    text = open(path, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        print(f"skip (no frontmatter): {path}")
        return False
    fm = yaml.safe_load(m.group(1))
    if not isinstance(fm, dict):
        print(f"skip (frontmatter not a mapping): {path}")
        return False
    if not needs_fix(fm):
        print(f"ok (already flat): {path}")
        return False
    out = {k: (trunc_bytes(to_str(v)) if k == "description" else to_str(v))
           for k, v in fm.items()}
    bak = path + ".bak"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
    new_fm = yaml.dump(out, allow_unicode=True, sort_keys=False,
                       default_flow_style=False, width=10**6)
    open(path, "w", encoding="utf-8").write("---\n" + new_fm + "---\n" + text[m.end():])
    check = yaml.safe_load(open(path, encoding="utf-8").read().split("---\n")[1])
    assert all(isinstance(v, str) for v in check.values()), path
    print(f"fixed: {path}")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="*", help="SKILL.md files (or skill dirs)")
    ap.add_argument("--scan", nargs="*", help="skill dirs: check every */SKILL.md inside")
    args = ap.parse_args()

    files = []
    for p in args.paths:
        files.append(os.path.join(p, "SKILL.md") if os.path.isdir(p) else p)
    for d in args.scan or []:
        for root, dirs, names in os.walk(d):
            dirs[:] = [x for x in dirs if not x.startswith(".")]
            if "SKILL.md" in names:
                files.append(os.path.join(root, "SKILL.md"))
    if not files:
        ap.error("give SKILL.md paths or --scan DIRS")

    fixed = sum(fix(f) for f in files if os.path.exists(f))
    print(f"{fixed} file(s) fixed, {len(files)} checked")


if __name__ == "__main__":
    sys.exit(main())
