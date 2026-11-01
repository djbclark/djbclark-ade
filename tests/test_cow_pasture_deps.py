"""bin/cow-pasture create keeps a pasture's dependencies out of the source checkout.

cow 0.1.10 symlinks large dependency dirs into the source by default; an `npm install`
in such a pasture emptied ~392 package dirs of ~/src/paseo/node_modules (2026-11-01).
A stub cow (COW_PASTURE_COW) makes a pasture whose node_modules/@scope is an absolute
symlink into the source, records it in `cow list --json` state, and materialises it
unless STUB_MATERIALISE_NOOP is set.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "cow-pasture"

STUB_COW = r'''#!/usr/bin/env python3
import json, os, shutil, subprocess, sys
root = os.environ["STUB_ROOT"]
state_f = os.path.join(root, "state.json")
state = json.load(open(state_f)) if os.path.exists(state_f) else []
with open(os.path.join(root, "calls"), "a") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\n")
cmd = sys.argv[1]
if cmd == "create":
    name, src = sys.argv[2], sys.argv[sys.argv.index("--source") + 1]
    src = os.path.realpath(src)
    path = os.path.join(root, "pastures", name)
    os.makedirs(os.path.join(path, "node_modules", ".bin"))
    subprocess.run(["git", "init", "-q", path], check=True)
    os.symlink(os.path.join(src, "node_modules", "@scope"), os.path.join(path, "node_modules", "@scope"))
    os.symlink("../pkg/cli.js", os.path.join(path, "node_modules", ".bin", "cli"))  # relative, in-pasture
    os.symlink("/usr/bin/env", os.path.join(path, "node_modules", "env"))  # absolute, outside any source
    state.append({"name": os.path.basename(src) + "/" + name, "path": path, "source": src,
                  "symlinked_dirs": ["node_modules/@scope"], "linked_dirs": []})
    json.dump(state, open(state_f, "w"))
    print("Switched to a new branch '%s'" % name)
    print(path)
elif cmd == "list":
    print(json.dumps(state))
elif cmd == "materialise":
    entry = [e for e in state if e["name"] == sys.argv[2]][0]
    if not os.environ.get("STUB_MATERIALISE_NOOP"):
        for rel in entry["symlinked_dirs"]:
            link = os.path.join(entry["path"], rel)
            target = os.readlink(link)
            os.unlink(link)
            shutil.copytree(target, link, symlinks=True)
        entry["symlinked_dirs"] = []
        json.dump(state, open(state_f, "w"))
    print("Done.")
else:
    sys.exit("stub cow: unexpected " + cmd)
'''


def setup(tmp_path):
    src = tmp_path / "src" / "proj"
    (src / "node_modules" / "@scope" / "pkg").mkdir(parents=True)
    (src / "node_modules" / "@scope" / "pkg" / "index.js").write_text("module.exports = 1\n")
    subprocess.run(["git", "init", "-q", str(src)], check=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    cow = bin_dir / "cow"
    cow.write_text(STUB_COW)
    cow.chmod(0o755)
    # The script calls GNU tools by their Homebrew g-names; Linux CI has only the plain ones.
    for g in ("gtail", "ggrep", "gfind"):
        if shutil.which(g) is None:
            (bin_dir / g).symlink_to(shutil.which(g[1:]))
    return src, cow, bin_dir


def run(tmp_path, cow, bin_dir, *args, **extra_env):
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(tmp_path),
           "COW_PASTURE_COW": str(cow), "STUB_ROOT": str(tmp_path), **extra_env}
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=60)


def calls(tmp_path):
    return (tmp_path / "calls").read_text().splitlines()


def test_create_materialises_and_prints_only_the_path(tmp_path):
    src, cow, bin_dir = setup(tmp_path)
    r = run(tmp_path, cow, bin_dir, "create", "feat", "--source", str(src), "--no-trust")
    assert r.returncode == 0, r.stderr
    path = tmp_path / "pastures" / "feat"
    assert r.stdout == f"{path}\n"
    scope = path / "node_modules" / "@scope"
    assert scope.is_dir() and not scope.is_symlink()
    assert (scope / "pkg" / "index.js").read_text() == "module.exports = 1\n"
    log = calls(tmp_path)
    create = [c for c in log if c.startswith("create ")]
    assert len(create) == 1 and "--no-symlink" in create[0].split()
    assert "materialise proj/feat" in log
    # Unrelated links survive: relative in-pasture and absolute outside the source.
    assert (path / "node_modules" / ".bin" / "cli").is_symlink()
    assert (path / "node_modules" / "env").is_symlink()


def test_create_fails_when_a_link_into_the_source_remains(tmp_path):
    src, cow, bin_dir = setup(tmp_path)
    r = run(tmp_path, cow, bin_dir, "create", "feat", "--source", str(src), "--no-trust",
            STUB_MATERIALISE_NOOP="1")
    assert r.returncode == 1
    assert r.stdout == ""  # no path for a caller to cd into
    assert "1 symlink(s)" in r.stderr
    assert f"node_modules/@scope -> {src.resolve()}/node_modules/@scope" in r.stderr
    assert "cow materialise proj/feat" in r.stderr
    # The source is untouched.
    assert (src / "node_modules" / "@scope" / "pkg" / "index.js").exists()


def test_check_reports_links_into_the_source_and_its_source(tmp_path):
    src, cow, bin_dir = setup(tmp_path)
    r = run(tmp_path, cow, bin_dir, "create", "feat", "--source", str(src), "--no-trust",
            STUB_MATERIALISE_NOOP="1")
    assert r.returncode == 1
    path = tmp_path / "pastures" / "feat"
    r = run(tmp_path, cow, bin_dir, "check", str(path))
    assert r.returncode == 1
    assert r.stdout == f"node_modules/@scope -> {src.resolve()}/node_modules/@scope\n"

    # A pasture made from that pasture: its inherited link points into the grandparent
    # source and cow records no symlinked dirs for it.
    child = tmp_path / "pastures" / "child"
    (child / "node_modules").mkdir(parents=True)
    os.symlink(f"{src.resolve()}/node_modules/@scope", child / "node_modules" / "@scope")
    state = json.loads((tmp_path / "state.json").read_text())
    state.append({"name": "feat/child", "path": str(child), "source": str(path),
                  "symlinked_dirs": [], "linked_dirs": []})
    (tmp_path / "state.json").write_text(json.dumps(state))
    r = run(tmp_path, cow, bin_dir, "check", str(child))
    assert r.returncode == 1
    assert "node_modules/@scope" in r.stdout


def test_check_clean_pasture_and_unknown_path(tmp_path):
    src, cow, bin_dir = setup(tmp_path)
    r = run(tmp_path, cow, bin_dir, "create", "feat", "--source", str(src), "--no-trust")
    assert r.returncode == 0, r.stderr
    r = run(tmp_path, cow, bin_dir, "check", str(tmp_path / "pastures" / "feat"))
    assert (r.returncode, r.stdout) == (0, "")
    r = run(tmp_path, cow, bin_dir, "check", str(src))
    assert r.returncode == 2
    assert "no single cow pasture recorded" in r.stderr
