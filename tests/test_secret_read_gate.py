#!/usr/bin/env python3
"""claude/hooks/secret_read_gate.py: the PreToolUse secret-file gate (2026-11-04, issue #284 item 2; docs/secret-deny.md).

Every case runs the hook as a subprocess with a temporary HOME and project, against the committed policy JSON, so the
matrix below is the shipped policy's behaviour. Python 3.9 compatibility is checked on the source (the hook runs under
macOS /usr/bin/python3) and, when an old interpreter exists, by running it."""
from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "claude" / "hooks" / "secret_read_gate.py"
POLICY = ROOT / "config" / "secret_deny_policy.json"


def load_hook():
    spec = importlib.util.spec_from_file_location("secret_read_gate_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    (home / ".ssh").mkdir(parents=True)
    proj.mkdir()
    e = {k: v for k, v in os.environ.items() if not k.startswith("SECRET_DENY")}
    e["HOME"] = str(home)
    return {"home": home, "proj": proj, "tmp": tmp_path, "env": e}


def run(env, tool, tool_input, cwd=None, extra_env=None, raw=None, python=None):
    payload = raw if raw is not None else json.dumps(
        {"tool_name": tool, "tool_input": tool_input, "cwd": str(cwd or env["proj"]), "hook_event_name": "PreToolUse"})
    e = dict(env["env"])
    e.update(extra_env or {})
    r = subprocess.run([python or sys.executable, str(HOOK)], input=payload, capture_output=True, text=True,
                       env=e, cwd=str(env["proj"]), timeout=30)
    return r.returncode, r.stderr


def blocked(env, tool, tool_input, **kw):
    rc, err = run(env, tool, tool_input, **kw)
    return rc == 2


# ---- the deny/allow matrix (Read) ----------------------------------------------------------------------------------
DENIED_REL = [".env", ".env.local", ".env.production", "sub/dir/.env", "config/.env.staging", "server.key", "cert.p12",
              "cert.pfx", "tls-key.pem", "server.key.pem", "privkey.pem", "privkey1.pem", "id_rsa", "deep/id_ecdsa",
              "id_ed25519"]
DENIED_HOME = [".ssh/anything", ".ssh/id_rsa", ".ssh/id_ed25519", ".ssh/sub/key", ".aws/credentials", ".netrc",
               ".config/gh/hosts.yml", ".docker/config.json", ".kube/config"]
ALLOWED_REL = [".env.example", ".env.sample", ".env.template", "sub/.env.example", "id_rsa.pub", "cert.pem",
               "fullchain.pem", "README.md", "env.py", ".envrc", "keys.txt", "my.keyring", "docs/env.md"]
ALLOWED_HOME = [".ssh/id_ed25519.pub", ".ssh/known_hosts", ".ssh/config", ".aws/config", ".config/gh/config.yml",
                ".docker/daemon.json", ".kube/cache/x", ".netrc.example"]


@pytest.mark.parametrize("rel", DENIED_REL)
def test_denied_project_paths(env, rel):
    assert blocked(env, "Read", {"file_path": rel})
    assert blocked(env, "Read", {"file_path": str(env["proj"] / rel)})


@pytest.mark.parametrize("rel", DENIED_HOME)
def test_denied_home_paths(env, rel):
    assert blocked(env, "Read", {"file_path": str(env["home"] / rel)})
    assert blocked(env, "Read", {"file_path": "~/" + rel})


@pytest.mark.parametrize("rel", ALLOWED_REL)
def test_allowed_project_paths(env, rel):
    assert not blocked(env, "Read", {"file_path": rel})


@pytest.mark.parametrize("rel", ALLOWED_HOME)
def test_allowed_home_paths(env, rel):
    assert not blocked(env, "Read", {"file_path": str(env["home"] / rel)})


def test_system_ca_bundle_is_allowed(env):
    assert not blocked(env, "Read", {"file_path": "/etc/ssl/certs/ca-certificates.pem"})


@pytest.mark.parametrize("tool,key", [("Edit", "file_path"), ("Write", "file_path"), ("MultiEdit", "file_path"),
                                      ("NotebookEdit", "notebook_path")])
def test_every_file_tool_is_gated(env, tool, key):
    assert blocked(env, tool, {key: ".env"})
    assert not blocked(env, tool, {key: ".env.example"})


def test_glob_is_not_gated(env):
    assert not blocked(env, "Glob", {"pattern": "**/.env*"})


def test_block_message_is_one_line_naming_rule_and_doc(env):
    rc, err = run(env, "Read", {"file_path": ".env.local"})
    assert rc == 2
    assert err.count("\n") == 1
    assert "'.env.*'" in err and "docs/secret-deny.md" in err and "config/secret-deny.toml" in err


# ---- symlinks: each form is checked on its own ---------------------------------------------------------------------
def test_symlink_to_env_is_blocked(env):
    (env["proj"] / ".env").write_text("SECRET=1\n")
    (env["proj"] / "notes.txt").symlink_to(env["proj"] / ".env")
    assert blocked(env, "Read", {"file_path": "notes.txt"})


def test_allowed_name_pointing_at_env_is_blocked(env):
    (env["proj"] / ".env").write_text("SECRET=1\n")
    (env["proj"] / ".env.example").symlink_to(env["proj"] / ".env")
    assert blocked(env, "Read", {"file_path": ".env.example"})


def test_pub_symlink_into_ssh_key_is_blocked(env):
    key = env["home"] / ".ssh" / "id_ed25519"
    key.write_text("PRIVATE\n")
    link = env["tmp"] / "a.pub"
    link.symlink_to(key)
    assert blocked(env, "Read", {"file_path": str(link)})


def test_symlinked_home_is_matched_through_its_realpath(env):
    real = env["tmp"] / "realhome"
    (real / ".ssh").mkdir(parents=True)
    (real / ".netrc").write_text("machine x\n")
    linked = env["tmp"] / "linkhome"
    linked.symlink_to(real)
    env["env"]["HOME"] = str(linked)
    assert blocked(env, "Read", {"file_path": str(real / ".netrc")})
    assert blocked(env, "Read", {"file_path": str(linked / ".netrc")})


def test_dotdot_is_normalised(env):
    assert blocked(env, "Read", {"file_path": "sub/../.env"})


def test_symlink_then_dotdot_is_resolved_before_collapsing(env):
    # Codex review, PR 289: link -> ~/.config/gh/subdir, so link/../hosts.yml opens ~/.config/gh/hosts.yml;
    # normalising first would check proj/hosts.yml instead.
    sub = env["home"] / ".config" / "gh" / "subdir"
    sub.mkdir(parents=True)
    (env["home"] / ".config" / "gh" / "hosts.yml").write_text("oauth_token: x\n")
    (env["proj"] / "link").symlink_to(sub)
    assert blocked(env, "Read", {"file_path": "link/../hosts.yml"})
    assert blocked(env, "Bash", {"command": "cat link/../hosts.yml"})


def test_normalized_spelling_symlink_is_still_resolved(env):
    # Mirror case (adversary on PR 289): x -> secret, link -> d/e; a tool that normalizes `link/../x` by text
    # opens x, so realpath(normpath) must still be checked beside realpath(join).
    (env["home"] / ".netrc").write_text("machine x password y\n")
    (env["proj"] / "x").symlink_to(env["home"] / ".netrc")
    (env["proj"] / "d" / "e").mkdir(parents=True)
    (env["proj"] / "link").symlink_to(env["proj"] / "d" / "e")
    assert blocked(env, "Read", {"file_path": "link/../x"})


# ---- Grep ------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("inp,want", [
    ({"pattern": "x", "path": ".env"}, True),
    ({"pattern": "x", "path": "~/.ssh"}, True),
    ({"pattern": "x", "path": "~/.ssh/config"}, False),
    ({"pattern": "x", "glob": ".env*"}, False),              # C2: the walk saw the whole (empty) project
    ({"pattern": "x", "glob": ".env*", "path": "missing"}, True),   # no tree to walk: the glob's text is checked
    ({"pattern": "x", "glob": "*.{env,key}", "path": "missing"}, True),
    ({"pattern": "x", "glob": "**/*.key", "path": "missing"}, True),
    ({"pattern": "x", "glob": "*.py", "path": "missing"}, False),
    ({"pattern": "x", "glob": "*.py"}, False),
    ({"pattern": "x", "glob": "*"}, False),
    ({"pattern": "x", "glob": "*.{ts,tsx}"}, False),
    ({"pattern": "x", "glob": ".env.example"}, False),
    ({"pattern": "x"}, False),
])
def test_grep(env, inp, want):
    assert blocked(env, "Grep", inp) is want


# Claude's Grep is ripgrep with --hidden (2026-11-04 adversary finding A1): it reads dotfiles and enters ~/.ssh.
def secrets_in_home(env):
    (env["home"] / ".ssh" / "id_ed25519").write_text("PRIVATE\n")
    (env["home"] / ".aws").mkdir()
    (env["home"] / ".aws" / "credentials").write_text("[default]\n")


@pytest.mark.parametrize("inp", [
    {"pattern": "x", "path": "$HOME"},
    {"pattern": "x", "path": "~"},
    {"pattern": "x", "path": "$HOME/.aws", "output_mode": "content"},
    {"pattern": "x", "glob": "credentials", "path": "$HOME"},
])
def test_grep_home_repros_block(env, inp):
    secrets_in_home(env)
    assert blocked(env, "Grep", inp), inp


def test_grep_hidden_glob_repro_blocks_when_env_exists(env):
    (env["proj"] / ".env").write_text("A=1\n")
    assert blocked(env, "Grep", {"pattern": "x", "glob": ".e*"})


def test_grep_home_with_extension_glob_reaches_hidden_dirs(env):
    secrets_in_home(env)
    assert not blocked(env, "Grep", {"pattern": "x", "path": str(env["home"]), "glob": "*.py"})
    (env["home"] / ".ssh" / "notes.py").write_text("x\n")   # under ~/.ssh/**, and *.py reaches it with --hidden
    assert blocked(env, "Grep", {"pattern": "x", "path": str(env["home"]), "glob": "*.py"})


def test_grep_of_a_clean_project_passes(env):
    (env["proj"] / "src").mkdir()
    (env["proj"] / "src" / "app.py").write_text("x\n")
    (env["proj"] / ".env.example").write_text("A=\n")
    (env["proj"] / ".github").mkdir()
    (env["proj"] / ".github" / "ci.yml").write_text("x\n")
    assert not blocked(env, "Grep", {"pattern": "x"})
    assert not blocked(env, "Grep", {"pattern": "x", "path": str(env["proj"])})
    assert not blocked(env, "Grep", {"pattern": "x", "path": "src"})


def test_grep_of_a_project_with_env_blocks_unless_the_glob_leaves_it_out(env):
    (env["proj"] / "src").mkdir()
    (env["proj"] / "src" / "app.py").write_text("x\n")
    (env["proj"] / "config").mkdir()
    (env["proj"] / "config" / ".env").write_text("A=1\n")
    rc, err = run(env, "Grep", {"pattern": "x"})
    assert rc == 2 and "config/.env" in err and "narrower path" in err and "glob" in err
    assert err.count("\n") == 1
    assert blocked(env, "Grep", {"pattern": "x", "path": str(env["proj"])})
    assert not blocked(env, "Grep", {"pattern": "x", "glob": "*.py"})
    assert not blocked(env, "Grep", {"pattern": "x", "glob": "!.env"})
    assert not blocked(env, "Grep", {"pattern": "x", "glob": "!config"})
    assert not blocked(env, "Grep", {"pattern": "x", "path": "src"})
    assert blocked(env, "Grep", {"pattern": "x", "glob": "*"})
    assert blocked(env, "Grep", {"pattern": "x", "glob": "config/*"})
    assert blocked(env, "Grep", {"pattern": "x", "glob": "*.py *"})    # any reading of a split glob counts


def test_grep_clean_walk_skips_the_pattern_check(env):
    """Adversary finding C2 (2026-11-04): after a complete walk the glob's text was still run through the overlap
    engine (2.6 s for a long brace glob), and `.env*` blocked in a project with no such file."""
    for d in ("src", "web", "docs"):
        (env["proj"] / d).mkdir()
        for ext in ("py", "ts", "tsx", "md"):
            (env["proj"] / d / ("a." + ext)).write_text("x\n")
    glob = "**/*.{ts,tsx,js,jsx,mjs,cjs,py,pyi,go,rs,java,kt,swift,rb,php,md,json,yaml,yml,toml,css,html}"
    t0 = time.monotonic()
    rc, err = run(env, "Grep", {"pattern": "x", "glob": glob})
    assert (rc, err) == (0, "") and time.monotonic() - t0 < 2.0
    assert not blocked(env, "Grep", {"pattern": "x", "glob": ".env*"})
    (env["proj"] / "web" / ".env.local").write_text("A=1\n")
    assert blocked(env, "Grep", {"pattern": "x", "glob": ".env*"})


def test_grep_cut_short_walk_falls_back_to_the_glob_text(tmp_path, monkeypatch):
    hook = load_hook()
    proj = tmp_path / "proj"
    proj.mkdir()
    for i in range(10):
        (proj / ("f%d.txt" % i)).write_text("x\n")
    policy = hook.Policy([".env", ".env.*"], [], homes=[str(tmp_path / "home")], fold=False)
    assert grep_inproc(hook, policy, str(proj), glob=".env*") is None          # complete walk, no .env
    monkeypatch.setattr(hook, "MAX_WALK_ENTRIES", 3)
    hit = grep_inproc(hook, policy, str(proj), glob=".env*")                     # cut short: the text decides
    assert hit and hit[1] in (".env", ".env.*")
    assert grep_inproc(hook, policy, str(proj), glob="*.py") is None
    assert grep_inproc(hook, policy, str(proj)) is None                          # no glob: fail open as before


def test_grep_type_narrows_the_walk(env):
    """Adversary finding C3 (2026-11-04): `type` was ignored, so `{"type": "py"}` blocked beside a .env."""
    (env["proj"] / "src").mkdir()
    (env["proj"] / "src" / "app.py").write_text("x\n")
    (env["proj"] / ".env").write_text("A=1\n")
    assert blocked(env, "Grep", {"pattern": "x"})
    for t in TYPE_NAMES:
        if t == "sh":   # ripgrep 15.2's sh type reads .env and *.env (2026-11-06): the walk must reach it
            assert blocked(env, "Grep", {"pattern": "x", "type": t}), t
            continue
        assert not blocked(env, "Grep", {"pattern": "x", "type": t}), t
    assert not blocked(env, "Grep", {"pattern": "x", "type": "py", "glob": "!.env"})   # `!` alone combines with type
    rc, err = run(env, "Grep", {"pattern": "x", "type": "nosuchtype"})   # unknown: unfiltered, and the hint says glob
    assert rc == 2 and "glob" in err and "nosuchtype" in err and "'*.nosuchtype'" not in err
    (env["proj"] / ".env.py").write_text("A=1\n")                       # a denied file the type does read
    assert blocked(env, "Grep", {"pattern": "x", "type": "py"})


TYPE_NAMES = ("py", "js", "ts", "go", "rust", "java", "c", "cpp", "sh", "md", "json", "yaml", "toml", "ruby", "php",
              "swift", "kotlin", "html", "css")


@pytest.mark.parametrize("inp,want", [
    # Adversary round 3 (2026-11-04), checked against /usr/bin/rg 14.1.0: a positive glob decides alone, whatever the
    # type (`rg --hidden -t ts -g 'src/**' -l SECRET` lists src/.env), and the last matching glob wins.
    ({"type": "ts", "glob": "src/**"}, True),
    ({"type": "py", "glob": "*"}, True),
    ({"type": "py", "glob": ".env"}, True),
    ({"type": "ts"}, False),
    ({"type": "ts", "glob": "!.env"}, False),
    ({"type": "ts", "glob": "!src"}, False),
    ({"glob": "!.env *"}, True),                    # split on whitespace: `-g '!.env' -g '*'` reads .env
    ({"glob": "* !.env"}, False),
    ({"glob": "src/** !src/.env"}, False),
    ({"glob": "!src/.env src/**"}, True),
])
def test_grep_glob_and_type_combine_as_ripgrep_does(env, inp, want):
    (env["proj"] / "src").mkdir()
    (env["proj"] / "src" / ".env").write_text("SECRET=1\n")
    (env["proj"] / "src" / "a.ts").write_text("SECRET\n")
    assert blocked(env, "Grep", dict(inp, pattern="SECRET")) is want, inp


def test_grep_type_filter_names():
    hook = load_hook()
    py = hook.rg_type_filter("py", False)
    assert py("a.py") and py("sub/b.pyi") and not py(".env") and not py("x.py/.env")
    yml = hook.rg_type_filter("yaml", False)
    assert yml(".config/gh/hosts.yml")
    assert hook.rg_type_filter("nosuchtype", False) is None
    assert hook.rg_type_filter("rb", False) is None              # ripgrep's Ruby type is `ruby`
    assert hook.rg_type_filter("ruby", False)("Gemfile")
    assert hook.rg_type_filter("c", True)("A.H")
    assert sorted(hook.RG_TYPES) == sorted(TYPE_NAMES)


def test_grep_type_map_covers_ripgrep():
    """Every mapped type is a ripgrep type, and the globs the hook uses (the static map unioned with the live
    `rg --type-list`) list every name ripgrep reads for it (more is harmless). The static map alone may lag a newer
    ripgrep; that lag is reported, not failed, since the live union covers it wherever rg is on PATH."""
    rg = shutil.which("rg")
    if rg is None:
        pytest.skip("no rg on this machine")
    out = subprocess.run([rg, "--type-list"], capture_output=True, text=True, timeout=30).stdout
    listed = {}
    for line in out.splitlines():
        name, _, globs = line.partition(":")
        listed[name.strip()] = {g.strip() for g in globs.split(",") if g.strip()}
    hook = load_hook()
    live = hook.rg_live_types()
    assert live, "rg --type-list read nothing"
    for t, globs in hook.RG_TYPES.items():
        assert t in listed, t
        used = set(hook.rg_type_globs(t, live))
        assert listed[t] <= used, (t, listed[t] - used)
        assert set(globs) <= used
        if not listed[t] <= set(globs):
            print("static RG_TYPES[%r] lags this rg by %s" % (t, sorted(listed[t] - set(globs))))


def fake_rg(env, type_list, sleep=0, rc=0):
    """A fake `rg` first on PATH whose `--type-list` prints `type_list` (after `sleep` s, exiting `rc`)."""
    bindir = env["tmp"] / "fakebin"
    bindir.mkdir(exist_ok=True)
    rg = bindir / "rg"
    rg.write_text("#!/bin/sh\nsleep %s\nprintf '%%s\\n' %s\nexit %d\n"
                  % (sleep, " ".join("'%s'" % line for line in type_list), rc))
    rg.chmod(0o755)
    env["env"]["PATH"] = str(bindir) + os.pathsep + env["env"].get("PATH", "")


def test_grep_type_unions_the_live_rg_type_list(env):
    """Codex security review on PR 289 (2026-11-06): ripgrep 15.2's `sh` type reads `.env` and `*.env`, so a static
    map copied from 14.1.0 let `type: sh` pass beside a .env that rg reads. The static map now lists them, and the live
    `rg --type-list` is unioned in, so a newer rg can only widen a type."""
    (env["proj"] / "src").mkdir()
    (env["proj"] / "src" / "a.py").write_text("x\n")
    (env["proj"] / ".env").write_text("A=1\n")
    fake_rg(env, ["sh: *.sh, .env, *.env", "py: *.py, .env"])
    assert blocked(env, "Grep", {"pattern": "x", "type": "sh"})
    assert blocked(env, "Grep", {"pattern": "x", "type": "py"})          # only the live list names .env for py
    assert not blocked(env, "Grep", {"pattern": "x", "type": "go"})      # a type the fake does not list: static only
    fake_rg(env, ["py: *.pyi"])                                          # a narrower live list narrows nothing
    (env["proj"] / ".env").unlink()
    (env["proj"] / ".env.py").write_text("A=1\n")
    assert blocked(env, "Grep", {"pattern": "x", "type": "py"})


@pytest.mark.parametrize("sleep,rc", [(0, 1), (5, 0)])
def test_grep_type_live_rg_failure_is_ignored(env, sleep, rc):
    """A failing or hanging `rg --type-list` is ignored within its ~1 s: the static map stands alone."""
    (env["proj"] / "a.py").write_text("x\n")
    (env["proj"] / ".env").write_text("A=1\n")
    fake_rg(env, ["py: *.py, .env"], sleep=sleep, rc=rc)
    t0 = time.monotonic()
    rc_, err = run(env, "Grep", {"pattern": "x", "type": "py"})
    assert (rc_, err) == (0, "") and time.monotonic() - t0 < 3.0
    assert blocked(env, "Grep", {"pattern": "x", "type": "sh"})          # the static sh lists .env either way


@pytest.mark.parametrize("n", [201, 60000])
def test_grep_type_live_rg_flood_is_ignored(env, n):
    """Adversary on PR 289 (2026-11-06): a fake rg printing 60,000 `sh` globs made the regex compile run past the
    budget and the call fail open. A flooded answer (too many globs, or more than 64 KiB) is now ignored whole."""
    (env["proj"] / "a.py").write_text("x\n")
    (env["proj"] / ".env").write_text("A=1\n")
    fake_rg(env, ["sh: " + ", ".join("*.x%d" % i for i in range(n))])
    t0 = time.monotonic()
    assert blocked(env, "Grep", {"pattern": "x", "type": "sh"})          # the static sh lists .env
    assert time.monotonic() - t0 < 5.0
    hook = load_hook()
    assert hook.RG_LIST_MAX_GLOBS == 200 and hook.RG_LIST_MAX_BYTES == 65536


def test_grep_type_filter_live_globs():
    hook = load_hook()
    live = {"py": ["*.py", "*.{env,cfg}", "conf/*.ini"], "nosuchtype": ["*"]}
    f = hook.rg_type_filter("py", False, live)
    assert f("a.py") and f("x/b.env") and f("c.cfg") and f("conf/d.ini") and not f("e.txt")
    assert hook.rg_type_filter("nosuchtype", False, live) is None        # unknown to the static map: unfiltered
    assert hook._split_type_globs(" *.sh, .env,*.{a,b} ") == ["*.sh", ".env", "*.{a,b}"]


def test_grep_root_symlink_then_dotdot_walks_the_kernel_resolved_root(env):
    """Codex review on PR 289 (2026-11-06): with link -> ~/.config/gh/subdir, `path: "link/.."` makes ripgrep search
    ~/.config/gh (the kernel resolves the link before `..`), but the hook normalized first and walked the project."""
    sub = env["home"] / ".config" / "gh" / "subdir"
    sub.mkdir(parents=True)
    (env["home"] / ".config" / "gh" / "hosts.yml").write_text("oauth_token: SECRETX\n")
    (env["proj"] / "link").symlink_to(sub)
    rg = shutil.which("rg")
    if rg:   # the premise: ripgrep really reads hosts.yml through `link/..`
        r = subprocess.run([rg, "--hidden", "-l", "SECRETX", "link/.."], capture_output=True, text=True,
                           cwd=str(env["proj"]), timeout=30)
        assert "hosts.yml" in r.stdout, (r.returncode, r.stdout, r.stderr)
    rc, err = run(env, "Grep", {"pattern": "SECRETX", "path": "link/.."})
    assert rc == 2 and "hosts.yml" in err, err
    assert blocked(env, "Grep", {"pattern": "SECRETX", "path": str(env["proj"] / "link" / "..")})
    assert not blocked(env, "Grep", {"pattern": "SECRETX", "path": "link"})   # subdir itself holds no secret
    # The mirror: the normalized root is the one holding the secret (a normalizing tool searches it).
    (env["proj"] / ".env").write_text("A=1\n")
    (env["tmp"] / "elsewhere" / "deep").mkdir(parents=True)
    (env["proj"] / "link2").symlink_to(env["tmp"] / "elsewhere" / "deep")
    assert blocked(env, "Grep", {"pattern": "x", "path": "link2/.."})


def test_grep_walk_skips_vcs_dirs_and_does_not_follow_symlinks(env):
    (env["proj"] / ".git").mkdir()
    (env["proj"] / ".git" / "id_rsa").write_text("x\n")
    (env["tmp"] / "outside").mkdir()
    (env["tmp"] / "outside" / ".env").write_text("A=1\n")
    (env["proj"] / "linked").symlink_to(env["tmp"] / "outside")
    assert not blocked(env, "Grep", {"pattern": "x"})


def test_grep_root_above_home_blocks(env):
    (env["home"] / ".ssh" / "id_rsa").write_text("PRIVATE\n")
    assert blocked(env, "Grep", {"pattern": "x", "path": "/"})
    assert blocked(env, "Grep", {"pattern": "x", "path": str(env["tmp"])})


def grep_inproc(hook, policy, path, glob=None, cwd="/"):
    ti = {"pattern": "x", "path": path}
    if glob:
        ti["glob"] = glob
    return hook.check({"tool_name": "Grep", "tool_input": ti, "cwd": cwd}, policy)


def test_grep_truncated_walk_fails_open_except_above_a_home_deny(tmp_path, monkeypatch):
    hook = load_hook()
    home, proj = tmp_path / "home", tmp_path / "proj"
    for d in (home, proj):
        d.mkdir()
        for i in range(10):
            (d / ("f%d.txt" % i)).write_text("x\n")
    (proj / "zz").mkdir()
    (proj / "zz" / ".env").write_text("A=1\n")
    policy = hook.Policy(["~/.netrc", ".env"], [], homes=[str(home)], fold=False)
    assert grep_inproc(hook, policy, str(proj))[1] == ".env"          # the whole walk finds it
    assert grep_inproc(hook, policy, str(home)) is None               # small home, no secret in it
    monkeypatch.setattr(hook, "MAX_WALK_ENTRIES", 5)
    assert grep_inproc(hook, policy, str(proj)) is None               # bound hit: fail open
    hit = grep_inproc(hook, policy, str(home))
    assert hit and hit[1] == "~/.netrc" and "narrower path" in hit[3]  # bound hit above a home deny: block
    assert grep_inproc(hook, policy, str(tmp_path))[1] == "~/.netrc"
    monkeypatch.setattr(hook, "MAX_WALK_ENTRIES", 20000)
    monkeypatch.setattr(hook, "MAX_WALK_DEPTH", 0)
    (home / "d").mkdir()
    assert grep_inproc(hook, policy, str(proj)) is None               # depth bound: fail open
    assert grep_inproc(hook, policy, str(home)) is not None


def test_grep_glob_readings():
    hook = load_hook()
    g = hook.GrepGlob("*.py", False)
    assert g.reaches("a.py") and g.reaches(".env.py") and g.reaches("sub/x.py") and not g.reaches(".env")
    g = hook.GrepGlob("!.env", False)
    assert g.reaches("a.py") and not g.reaches(".env") and not g.reaches("sub/.env")
    g = hook.GrepGlob("!.ssh", False)
    assert not g.reaches(".ssh/id_rsa")
    g = hook.GrepGlob("*.{py,env}", False)
    assert g.reaches("a.env") and not g.reaches("a.key")
    g = hook.GrepGlob("*.py,*.key", False)        # one glob, or two split on the comma: either may be what runs
    assert g.reaches("a.key")
    g = hook.GrepGlob("src/*.py", False)
    assert g.reaches("src/a.py") and not g.reaches("lib/a.py")
    g = hook.GrepGlob("!.env *", False)            # the last matching glob decides (ripgrep's override order)
    assert g.reaches(".env")
    g = hook.GrepGlob("* !.env", False)
    assert not g.reaches(".env") and g.reaches("a.py")
    g = hook.GrepGlob("!.envdir/", False)          # a trailing `/` excludes directories only
    assert g.reaches(".envdir") and not g.reaches(".envdir/f")
    py = hook.rg_type_filter("py", False)
    assert hook.GrepGlob("*", False).reaches(".env", py)        # a positive glob reads it whatever the type
    assert not hook.GrepGlob("!x", False).reaches(".env", py)   # `!` only: the type still filters
    assert hook.GrepGlob("!x", False).reaches("a.py", py)


# ---- Bash ------------------------------------------------------------------------------------------------------------
BASH_DENIED = [
    "cat ~/.ssh/id_ed25519",
    "cat $HOME/.netrc",
    "cat ${HOME}/.netrc",
    'cat "$HOME"/.aws/credentials',
    "cat ~/.ssh/id_*",
    "base64 < .env",
    "base64 <.env",
    "cat .env|base64",
    "x=$(cat .env.local)",
    "python3 app.py --config=.env",
    "docker run -v ~/.aws/credentials:/root/.aws/credentials img",
    "tar czf /tmp/x.tgz ~/.ssh",
    "cp -r ~/.ssh /tmp/x",
    "cat ~/.ssh/{config,id_rsa}",
    "find . -name '*.key'",
    "cat 'config/.env.prod'",
    "git show HEAD:.env",
]
BASH_ALLOWED = [
    "git status && ls -la",
    "cat .env.example",
    "cat ~/.ssh/config ~/.ssh/known_hosts",
    "cat ~/.ssh/*.pub",
    "cat ~/.ssh/{config,known_hosts}",
    "echo *",
    "grep -E 'a.*' README.md",
    "grep -n '\\.env' README.md",
    "echo $((2*3))",
    "find ~ -name 'id_*'",
    "for f in a b c; do echo $f; done; git log --oneline | head -5",
    "openssl x509 -in /etc/ssl/certs/ca.pem -noout",
    "git commit -m 'load settings from the .env file'",
]


@pytest.mark.parametrize("cmd", BASH_DENIED)
def test_bash_denied(env, cmd):
    assert blocked(env, "Bash", {"command": cmd}), cmd


@pytest.mark.parametrize("cmd", BASH_ALLOWED)
def test_bash_allowed(env, cmd):
    assert not blocked(env, "Bash", {"command": cmd}), cmd


def test_bash_glob_hits_on_disk_are_checked_as_paths(env):
    (env["home"] / ".ssh" / "id_ed25519").write_text("PRIVATE\n")
    (env["home"] / ".ssh" / "id_ed25519.pub").write_text("ssh-ed25519 AAAA\n")
    assert blocked(env, "Bash", {"command": "cat ~/.ssh/id_*"})
    assert not blocked(env, "Bash", {"command": "cat ~/.ssh/*.pub"})


def test_bash_glob_in_project_with_env_present(env):
    (env["proj"] / ".env").write_text("A=1\n")
    (env["proj"] / ".env.example").write_text("A=\n")
    assert blocked(env, "Bash", {"command": "cat .env*"})
    assert not blocked(env, "Bash", {"command": "cat *"})


def test_bash_unbalanced_quotes_fall_back_to_whitespace(env):
    assert blocked(env, "Bash", {"command": "echo 'oops; cat .env"})


def test_large_heredoc_with_code_is_fast_and_allowed(env):
    body = "\n".join("x = foo(%d) * bar[%d] ? baz" % (i, i) for i in range(3000))
    rc, err = run(env, "Bash", {"command": "cat > x.py <<'EOF'\n" + body + "\nEOF"})
    assert (rc, err) == (0, "")


def test_heredoc_with_double_star_words_is_fast_and_allowed(env):
    """Adversary finding C1 (2026-11-04): a `**` word skipped the literal-text filter; 100 lines took 8 s."""
    body = "\n".join("x = a[0] * b[i] ** 2 + f(*args, **kw%d)" % i for i in range(200))
    t0 = time.monotonic()
    rc, err = run(env, "Bash", {"command": "cat > x.py <<'EOF'\n" + body + "\nEOF"})
    assert (rc, err) == (0, "")
    assert time.monotonic() - t0 < 2.0


def test_token_items_and_spells():
    hook = load_hook()
    items = hook.token_items
    assert items(hook.atoms("**kw0")) == list("kw0")
    assert items(hook.atoms("a**")) == ["a"]
    assert items(hook.atoms("a/**/b")) == ["a", "/", None, "b"]
    assert items(hook.atoms("a?b")) == ["a", "\x00", "b"]
    sp = hook.spells
    assert sp(items(hook.atoms("/h/.ssh/id_*")), "/h/.ssh/")
    assert sp(items(hook.atoms("**/node_modules/**")), "/node")
    assert not sp(items(hook.atoms("**/node_modules/**")), ".env")
    assert sp(items(hook.atoms("x**/.env")), "x/.env") and sp(items(hook.atoms("x**/.env")), "x.env")
    assert sp(items(hook.atoms(".e*nv")), ".env")             # `*` may match "" between the deny's literals
    assert not sp(items(hook.atoms(".e?nv")), ".env")         # `?` must take a character by a wildcard move
    assert sp(items(hook.atoms("**/.e**/nv")), ".env")        # `**/` spells "" ...
    assert not sp(items(hook.atoms("**/.e**/v")), ".env")     # ... or "/", never "n"


def test_double_star_slash_prefilter_keeps_verdicts():
    """The `**/` pre-filter only skips work: the verdict for each token equals the full engine's."""
    hook = load_hook()
    deny = [".env", ".env.*", "*.key", "*-key.pem", "privkey*.pem", "id_rsa", "~/.ssh/**", "~/.aws/credentials"]
    pol = hook.Policy(deny, [".env.example", "*.pub", "~/.ssh/config"], homes=["/h"], fold=False)
    toks = ["**/node_modules/**", "**/*.log", "**/.env", "**/.env*", "**/*.key", "/h/**/.ssh/**", "/h/.ssh/**",
            "**/id_*", "**/privkey*", "**/.e**/nv", "**/*.ke?", "/h/**/credentials", "**/x/**/*.pem", "**/*-key.pem"]
    for tok in toks:
        ats = hook.atoms(tok, "/p/")
        full = None
        for r in pol.deny:
            if hook.nonempty([ats, r.atoms], [a.atoms for a in pol.allow], dotfile_first=True, pin_first=True):
                full = r.name
                break
        assert pol.pattern_verdict(tok, "/p/") == full, tok


def gitignore_heredoc():
    pats = ["**/node_modules/**", "**/*.log", "dist/", "**/build/**", "**/.cache/**", "**/coverage/**", "*.tmp",
            "**/__pycache__/**", "**/*.pyc", "**/.DS_Store", "**/target/**", "out/"]
    lines = [p.replace("node_modules", "nm%d" % i).replace("build", "b%d" % i).replace("*.log", "*.log%d" % i)
             .replace("dist/", "d%d/" % i) for i, p in ((i, pats[i % len(pats)]) for i in range(60))]
    return "cat > .gitignore <<'EOF'\n" + "\n".join(lines) + "\nEOF"


def test_gitignore_heredoc_with_double_star_lines_is_fast(env):
    """Adversary round 3 (2026-11-04): each `**/` word took 0.1-0.7 s in the pattern check, so a 60-line .gitignore
    heredoc followed by `cat ~/.ssh/id_*` ran past the 8 s budget and failed open."""
    for d in ("src/a", "src/b", "web"):
        (env["proj"] / d).mkdir(parents=True)
        (env["proj"] / d / "x.py").write_text("x\n")
    t0 = time.monotonic()
    rc, err = run(env, "Bash", {"command": gitignore_heredoc() + "\ncat ~/.ssh/id_*"})
    assert rc == 2 and "~/.ssh/**" in err, err
    assert time.monotonic() - t0 < 3.0
    t0 = time.monotonic()
    assert run(env, "Bash", {"command": gitignore_heredoc()}) == (0, "")
    assert time.monotonic() - t0 < 3.0


def test_slow_glob_word_is_retried_after_the_others(monkeypatch, tmp_path):
    hook = load_hook()
    ck = checker(hook, tmp_path)
    real_pv = ck.policy.pattern_verdict

    def slow_pv(glob_str, prefix="", dotfile=True):
        if "zzslowzz" in glob_str:
            while True:
                hook.tick()
        return real_pv(glob_str, prefix, dotfile)
    monkeypatch.setattr(ck.policy, "pattern_verdict", slow_pv)
    monkeypatch.setattr(hook, "WORD_S", 0.2)
    hook._DEADLINE[0] = time.monotonic() + 5.0
    t0 = time.monotonic()
    found = hook.check_command(ck, "ls zzslowzz* %s/.ssh/id_*" % tmp_path)   # the slow word comes first
    assert found and found[0] == "~/.ssh/**"
    assert time.monotonic() - t0 < 1.0
    hook._DEADLINE[0] = time.monotonic() + 0.5
    with pytest.raises(hook.GlobBudgetExceeded):                            # alone: second timeout fails closed
        hook.check_command(hook.Checker(ck.policy, str(tmp_path)), "ls zzslowzz*")
    assert hook._WORD_DEADLINE[0] == float("inf")


def test_eight_slow_glob_words_no_longer_fail_open(monkeypatch, tmp_path):
    """Adversary C7 (2026-11-04): eight crafted slow globs spent 8×WORD_S and failed open before id_*.
    First-pass cap + set-aside cache: the call fails closed (or still finds ~/.ssh/**) instead of allowing."""
    hook = load_hook()
    ck = checker(hook, tmp_path)
    real_pv = ck.policy.pattern_verdict

    def slow_pv(glob_str, prefix="", dotfile=True):
        if "zzslow" in glob_str:
            while True:
                hook.tick()
        return real_pv(glob_str, prefix, dotfile)
    monkeypatch.setattr(ck.policy, "pattern_verdict", slow_pv)
    monkeypatch.setattr(hook, "WORD_S", 0.15)
    monkeypatch.setattr(hook, "FIRST_PASS_S", 0.35)   # ~2 first-pass slots; the rest are set aside free
    hook._DEADLINE[0] = time.monotonic() + 2.0
    slow = " ".join("zzslow%d*" % i for i in range(8))
    cmd = "ls %s %s/.ssh/id_*" % (slow, tmp_path)
    t0 = time.monotonic()
    try:
        found = hook.check_command(ck, cmd)
        assert found and found[0] == "~/.ssh/**", found
    except hook.GlobBudgetExceeded:
        pass   # fail closed is the safe outcome when the secret word was not reached
    assert time.monotonic() - t0 < 2.5


def test_glob_budget_exceeded_fails_closed_through_main(monkeypatch, tmp_path, capsys):
    hook = load_hook()

    def raise_budget(payload, policy):
        raise hook.GlobBudgetExceeded("zzslowzz*")

    monkeypatch.setattr(hook, "check", raise_budget)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "ls zzslowzz*"}, "cwd": str(tmp_path)})))
    monkeypatch.delenv("SECRET_DENY_OFF", raising=False)
    monkeypatch.delenv("SECRET_DENY_POLICY", raising=False)
    assert hook.main() == 2
    err = capsys.readouterr().err
    assert "fail closed" in err and "zzslowzz*" in err
    assert "fail open" not in err


def test_setaside_after_first_pass_burn_blocks_cwd_id_star(monkeypatch, tmp_path):
    """Security HIGH residual (PR 413): FIRST_PASS_S burned by *completing* (not timed-out) slow globs left
    `id_*` set aside and pattern-only-retried, which cannot see cwd `id_rsa` and used to ALLOW. Deferred retry
    must walk (or refuse), never allow a walk-dependent secret glob after set-aside."""
    hook = load_hook()
    (tmp_path / "id_rsa").write_text("PRIVATE\n")
    (tmp_path / "zzslow0.txt").write_text("x\n")   # completing first-pass match for zzslow0*
    ck = hook.Checker(
        hook.Policy(["id_rsa", "*.key"], ["*.pub"], homes=[str(tmp_path)], fold=False),
        str(tmp_path),
    )
    # Prove the residual: pattern-only alone does not catch cwd id_rsa under id_*.
    assert ck.glob_pattern_only("id_*") is None
    # Cap already spent (completing zzslow0* would burn it); rem<=0 set-asides every later word.
    monkeypatch.setattr(hook, "FIRST_PASS_S", 0.0)
    hook._DEADLINE[0] = time.monotonic() + 5.0
    found = hook.check_command(ck, "cat zzslow0* id_*")
    assert found and found[0] == "id_rsa", found


def test_setaside_after_first_pass_burn_blocks_cwd_star(monkeypatch, tmp_path):
    """Same residual for `cat *` beside server.key: pattern-only cannot decide; must walk or fail closed."""
    hook = load_hook()
    (tmp_path / "server.key").write_text("K\n")
    (tmp_path / "zzslow0.txt").write_text("x\n")
    ck = hook.Checker(
        hook.Policy(["id_rsa", "*.key"], ["*.pub"], homes=[str(tmp_path)], fold=False),
        str(tmp_path),
    )
    assert ck.glob_pattern_only("*") is None
    monkeypatch.setattr(hook, "FIRST_PASS_S", 0.0)
    hook._DEADLINE[0] = time.monotonic() + 5.0
    found = hook.check_command(ck, "cat zzslow0* *")
    assert found and found[0] == "*.key", found


def test_setaside_walk_retry_fails_closed_when_no_budget(monkeypatch, tmp_path):
    """When pattern-only is inconclusive and the overall deadline has no time left for a walk, refuse."""
    hook = load_hook()
    (tmp_path / "id_rsa").write_text("PRIVATE\n")
    ck = hook.Checker(
        hook.Policy(["id_rsa", "*.key"], ["*.pub"], homes=[str(tmp_path)], fold=False),
        str(tmp_path),
    )
    monkeypatch.setattr(hook, "FIRST_PASS_S", 0.0)
    hook._DEADLINE[0] = time.monotonic() + 5.0

    real_word = ck.word

    def word_exhaust_on_pattern_only(raw, word_s=None, pattern_only=False):
        found = real_word(raw, word_s, pattern_only)
        if pattern_only and raw == "id_*":
            hook._DEADLINE[0] = time.monotonic() - 1.0   # no budget left for the walk retry
        return found

    monkeypatch.setattr(ck, "word", word_exhaust_on_pattern_only)
    with pytest.raises(hook.GlobBudgetExceeded):
        hook.check_command(ck, "cat id_*")


def test_deferred_walk_fails_closed_when_glob_s_burned_by_completing_dummies(monkeypatch, tmp_path):
    """Security HIGH residual (PR 413): WORD_S-under-budget completing dummies start GLOB_S; with
    FIRST_PASS_S == GLOB_S that clock is already expired when deferred `id_*` walks. expand truncates
    without raising (tick no-ops while WORD/DEADLINE remain), pattern-only is inconclusive, and the
    old path ALLOWed. Deferred incomplete walk must raise GlobBudgetExceeded."""
    hook = load_hook()
    (tmp_path / "id_rsa").write_text("PRIVATE\n")
    for i in range(3):
        (tmp_path / ("zzslow%d.txt" % i)).write_text("x\n")
    ck = hook.Checker(
        hook.Policy(["id_rsa", "*.key"], ["*.pub"], homes=[str(tmp_path)], fold=False),
        str(tmp_path),
    )
    # Prove the residual shape: pattern-only cannot see cwd id_rsa under id_*.
    assert ck.glob_pattern_only("id_*") is None
    monkeypatch.setattr(hook, "GLOB_S", 0.25)
    monkeypatch.setattr(hook, "FIRST_PASS_S", 0.25)   # same as GLOB_S (production: both 2.0)
    monkeypatch.setattr(hook, "WORD_S", 1.0)          # dummies finish under WORD_S
    real_scandir = hook._scandir

    def slow_scandir(path):
        time.sleep(0.12)   # completing zzslow* walks burn GLOB_S while still finishing
        return real_scandir(path)

    monkeypatch.setattr(hook, "_scandir", slow_scandir)
    hook._DEADLINE[0] = time.monotonic() + 5.0
    # Completing dummies (not WordOutOfTime) then id_*: first pass burns GLOB_S + FIRST_PASS_S;
    # deferred id_* walk truncates immediately → refuse, never allow.
    cmd = "cat zzslow0* zzslow1* zzslow2* id_*"
    with pytest.raises(hook.GlobBudgetExceeded):
        hook.check_command(ck, cmd)


# ---- Codex payloads ---------------------------------------------------------------------------------------------------
def patch(*headers, body="+x\n"):
    return "*** Begin Patch\n" + "".join("%s\n%s" % (h, body) for h in headers) + "*** End Patch\n"


@pytest.mark.parametrize("header,want", [
    ("*** Update File: .env", True),
    ("*** Add File: config/.env.prod", True),
    ("*** Delete File: certs/server.key", True),
    ("*** Update File: src/app.py\n*** Move to: .env", True),
    ("*** Update File: .env.example", False),
    ("*** Add File: src/new.py", False),
])
def test_codex_apply_patch_headers(env, header, want):
    assert blocked(env, "apply_patch", {"command": patch(header)}) is want
    assert blocked(env, "apply_patch", {"input": patch(header)}) is want


def test_codex_patch_body_mentioning_env_is_allowed(env):
    assert not blocked(env, "apply_patch", {"command": patch("*** Add File: src/a.py", body='+load(".env")\n')})


def test_codex_patch_inside_a_bash_heredoc(env):
    cmd = "apply_patch <<'EOF'\n" + patch("*** Update File: .env") + "EOF\n"
    assert blocked(env, "Bash", {"command": cmd})
    cmd_ok = "apply_patch <<'EOF'\n" + patch("*** Add File: a.py", body='+x = 1\n') + "EOF\n"
    assert not blocked(env, "Bash", {"command": cmd_ok})
    # Under Bash every word counts, a patch body's too (2026-11-06): a bare `.env` word there is C5's false positive.
    cmd_env = "apply_patch <<'EOF'\n" + patch("*** Add File: a.py", body='+x = ".env"\n') + "EOF\n"
    assert blocked(env, "Bash", {"command": cmd_env})


@pytest.mark.parametrize("cmd", [
    "*** Begin Patch\ncat ~/.ssh/id_rsa\n*** End Patch",
    "*** Begin Patch\ncat .env\n*** End Patch",
    "echo hi\n*** Begin Patch\n*** Add File: a.py\n+x\ncat .env\n*** End Patch\n",
])
def test_bash_runs_the_lines_of_a_patch_block(env, cmd):
    """Cursor review on PR 289 (2026-11-06): a Bash command's `*** Begin Patch` regions were dropped from the shell
    words, but Bash runs those lines."""
    assert blocked(env, "Bash", {"command": cmd}), cmd
    assert blocked(env, "Bash", {"command": ["bash", "-lc", cmd]}), cmd
    assert blocked(env, "shell", {"command": ["bash", "-lc", cmd]}), cmd   # Codex's shell tool too


def test_genuine_apply_patch_payload_reads_only_headers(env):
    ok = patch("*** Update File: src/app.py", body='-x\n+load(".env")\n')
    assert not blocked(env, "apply_patch", {"command": ok})
    assert not blocked(env, "apply_patch", {"input": ok})
    assert not blocked(env, "custom_tool", {"command": ok})               # a patch-only payload of a non-shell tool
    bad = patch("*** Add File: .env", body="+SECRET=1\n")
    assert blocked(env, "apply_patch", {"command": bad})
    assert blocked(env, "apply_patch", {"input": bad})
    # A non-shell tool whose text is more than a patch: the text outside counts, and with it the region's words.
    assert blocked(env, "custom_tool", {"command": "cat x\n" + ok})


def test_codex_shell_argv_list(env):
    assert blocked(env, "Bash", {"command": ["bash", "-lc", "cat .env"]})
    assert not blocked(env, "Bash", {"command": ["bash", "-lc", "cat .env.example"]})


# ---- fail open and the escape hatch ------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw", ["", "not json", "[1, 2]", "null"])
def test_bad_stdin_fails_open(env, raw):
    rc, err = run(env, None, None, raw=raw)
    assert rc == 0 and "fail open" in err


def test_tool_input_not_an_object_is_allowed(env):
    rc, _ = run(env, None, None, raw=json.dumps({"tool_name": "Read", "tool_input": ".env"}))
    assert rc == 0


@pytest.mark.parametrize("content", [None, "{not json", '{"deny": "x", "allow": []}', '{"deny": [], "allow": []}',
                                     '{"deny": [1], "allow": []}'])
def test_missing_or_corrupt_policy_fails_open(env, content):
    pol = env["tmp"] / "policy.json"
    if content is not None:
        pol.write_text(content)
    rc, err = run(env, "Read", {"file_path": ".env"}, extra_env={"SECRET_DENY_POLICY": str(pol)})
    assert rc == 0 and "fail open" in err


def test_policy_override_env_is_used(env):
    pol = env["tmp"] / "policy.json"
    pol.write_text(json.dumps({"deny": ["*.secret"], "allow": []}))
    over = {"SECRET_DENY_POLICY": str(pol)}
    assert run(env, "Read", {"file_path": "a.secret"}, extra_env=over)[0] == 2
    assert run(env, "Read", {"file_path": ".env"}, extra_env=over)[0] == 0


def test_escape_hatch(env):
    assert run(env, "Read", {"file_path": ".env"}, extra_env={"SECRET_DENY_OFF": "1"}) == (0, "")
    assert run(env, "Read", {"file_path": ".env"}, extra_env={"SECRET_DENY_OFF": "0"})[0] == 2


def test_internal_error_fails_open(monkeypatch, capsys):
    hook = load_hook()

    def boom(payload, policy):
        raise RuntimeError("bug")
    monkeypatch.setattr(hook, "check", boom)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_name": "Read", "tool_input": {"file_path": ".env"}})))
    monkeypatch.delenv("SECRET_DENY_OFF", raising=False)
    monkeypatch.delenv("SECRET_DENY_POLICY", raising=False)
    assert hook.main() == 0
    assert "internal error (RuntimeError: bug)" in capsys.readouterr().err


def test_analysis_budget_fails_open(monkeypatch, capsys):
    hook = load_hook()
    monkeypatch.setattr(hook, "BUDGET_S", -1.0)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": "cat .env"}})))
    monkeypatch.delenv("SECRET_DENY_OFF", raising=False)
    monkeypatch.delenv("SECRET_DENY_POLICY", raising=False)
    assert hook.main() == 0
    assert "OutOfTime" in capsys.readouterr().err


class FakeEntry:
    def __init__(self, name, is_dir=True, link=False):
        self.name, self._dir, self._link = name, is_dir, link

    def is_dir(self, follow_symlinks=True):
        return self._dir

    def is_symlink(self):
        return self._link


class FakeDir:
    def __init__(self, entries, delay=0.0):
        self.entries, self.delay = entries, delay

    def __iter__(self):
        for e in self.entries:
            if self.delay:
                time.sleep(self.delay)
            yield e

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def deep_tree(delay=0.0, files=False):
    """A synthetic scandir: every directory holds 50 subdirectories (and, with `files`, 50 files), forever."""
    reads = []

    def scandir(path):
        reads.append(path)
        ents = [FakeEntry("d%d" % i) for i in range(50)]
        if files:
            ents += [FakeEntry("f%d.txt" % i, is_dir=False) for i in range(50)]
        return FakeDir(ents, delay)
    return scandir, reads


def checker(hook, tmp_path, deny=(".env", ".env.*", "~/.ssh/**")):
    return hook.Checker(hook.Policy(list(deny), [], homes=[str(tmp_path)], fold=False), str(tmp_path))


def test_bash_glob_walk_of_a_tree_that_never_matches_is_bounded(monkeypatch, tmp_path):
    """Adversary finding B1 (2026-11-04): iglob's time check ran per match, so `ls /*/*/*/*/*/*/*/zzqq*` (no match,
    /proc/*/root loops) ran past 60 s. The walk now counts every entry it reads."""
    hook = load_hook()
    scandir, reads = deep_tree()
    monkeypatch.setattr(hook, "_scandir", scandir)
    seen = []
    ck = checker(hook, tmp_path)
    real_pv = ck.policy.pattern_verdict
    monkeypatch.setattr(ck.policy, "pattern_verdict", lambda *a, **k: seen.append(a[0]) or real_pv(*a, **k))
    t0 = time.monotonic()
    assert ck.glob("/*/*/*/*/*/*/*/zzqq*") is None
    assert time.monotonic() - t0 < 2.0
    assert ck._scanned == hook.MAX_GLOB_SCAN + 1
    assert seen == ["/*/*/*/*/*/*/*/zzqq*"]                # cut short: the pattern was checked instead
    assert ck.glob("/*/*/*/*/*/*/*/.env*") is not None     # and the pattern check still blocks a secret's name


def test_bash_glob_walk_time_bound_still_checks_every_word(monkeypatch, tmp_path):
    hook = load_hook()
    scandir, _ = deep_tree(delay=0.01)
    monkeypatch.setattr(hook, "_scandir", scandir)
    monkeypatch.setattr(hook, "GLOB_S", 0.3)
    ck = checker(hook, tmp_path)
    t0 = time.monotonic()
    found = hook.check_command(ck, "ls /*/*/*/*/*/*/*/zzqq* /*/*/*/*/*/*/*/yy* %s/.ssh/id_*" % tmp_path)
    assert found and found[0] == "~/.ssh/**"
    assert time.monotonic() - t0 < 2.0


def test_bash_glob_time_bound_through_main_allows_without_failing_open(monkeypatch, tmp_path, capsys):
    hook = load_hook()
    scandir, _ = deep_tree(delay=0.05)
    monkeypatch.setattr(hook, "_scandir", scandir)
    monkeypatch.setattr(hook, "GLOB_S", 0.3)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "ls /*/*/*/*/*/*"}, "cwd": str(tmp_path)})))
    monkeypatch.delenv("SECRET_DENY_OFF", raising=False)
    monkeypatch.delenv("SECRET_DENY_POLICY", raising=False)
    t0 = time.monotonic()
    assert hook.main() == 0
    assert time.monotonic() - t0 < 3
    assert capsys.readouterr().err == ""                    # a bounded walk, then the pattern: no fail-open notice


def test_bash_glob_hits_are_capped_then_the_pattern_is_checked(monkeypatch, tmp_path):
    hook = load_hook()
    scandir, _ = deep_tree(files=True)
    monkeypatch.setattr(hook, "_scandir", scandir)
    ck = checker(hook, tmp_path)
    checked = []
    real_path = ck.path
    monkeypatch.setattr(ck, "path", lambda raw: checked.append(raw) or real_path(raw))
    assert ck.glob("/*/*.txt") is None
    assert len(checked) == hook.MAX_GLOB_HITS


def test_bash_glob_walk_survives_a_symlink_loop(tmp_path):
    hook = load_hook()
    root = tmp_path / "w"
    (root / "a").mkdir(parents=True)
    (root / "self").symlink_to(".")
    (root / "a" / "up").symlink_to("..")
    (root / "a" / "real").mkdir()
    ck = checker(hook, tmp_path)
    t0 = time.monotonic()
    assert ck.glob(str(root) + "/*/*/*/*/*/*/*/*/*/zzqq*") is None
    assert time.monotonic() - t0 < 2.0
    assert ck._scanned < 50                                 # the symlinked directories were not entered
    state = {"complete": True}
    got = list(ck.expand(str(root), ["*", "*"], state))
    assert sorted(p for p, m in got if m) == [str(root / "a" / "real"), str(root / "a" / "up")]
    assert [p for p, m in got if not m] == [str(root / "self")]   # the link itself is handed back to be checked
    assert state["complete"] is False                       # `self` was skipped, so the walk says so
    t0 = time.monotonic()
    assert ck.glob(str(root) + "/**/zzqq*") is None         # `**` does not enter symlinked directories either
    assert time.monotonic() - t0 < 2.0


def test_bash_glob_wildcard_symlinked_dir_is_checked_itself(env):
    """Adversary round 3 (2026-11-04): `d -> ~/.ssh` matched by a wildcard was skipped unchecked."""
    (env["home"] / ".ssh" / "id_ed25519").write_text("PRIVATE\n")
    (env["proj"] / "d").symlink_to(env["home"] / ".ssh")
    rc, err = run(env, "Bash", {"command": "cat */id_*"})
    assert rc == 2 and "~/.ssh/**" in err
    assert blocked(env, "Bash", {"command": "ls */x"})
    (env["proj"] / "d").unlink()
    (env["proj"] / "d").symlink_to(env["tmp"])               # a link to a harmless directory passes
    (env["proj"] / "notes").symlink_to(env["proj"] / "README") # a link to a file is not one the walk enters
    assert not blocked(env, "Bash", {"command": "cat */x"})


def test_bash_double_star_is_recursive(env):
    """Adversary round 3 (2026-11-04): `**` (zsh's default, bash's globstar) was walked as `*`, so `grep -n TODO **/*`
    passed beside a/b/server.key."""
    (env["proj"] / "a" / "b").mkdir(parents=True)
    (env["proj"] / "a" / "b" / "notes.txt").write_text("x\n")
    assert not blocked(env, "Bash", {"command": "grep -n TODO **/*"})
    (env["proj"] / "a" / "b" / "server.key").write_text("K\n")
    for cmd in ("grep -n TODO **/*", "grep -rn TODO **", "cat a/**/*", "cat **/b/*"):
        assert blocked(env, "Bash", {"command": cmd}), cmd
    assert not blocked(env, "Bash", {"command": "cat **/*.txt"})


def test_bash_double_star_walk_rules(tmp_path):
    hook = load_hook()
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "f").write_text("x\n")
    (tmp_path / "a" / "g").write_text("x\n")
    (tmp_path / ".hid" / "c").mkdir(parents=True)
    (tmp_path / ".hid" / "c" / "f").write_text("x\n")
    ck = checker(hook, tmp_path)
    state = {"complete": True}
    got = sorted(p for p, m in ck.expand(str(tmp_path), ["**", "f"], state) if m)
    assert got == [str(tmp_path / "a" / "b" / "f")] and state["complete"]   # zero or more levels, never hidden ones
    got = sorted(p for p, m in ck.expand(str(tmp_path), ["**"], state) if m)
    assert got == [str(tmp_path / "a"), str(tmp_path / "a" / "b"), str(tmp_path / "a" / "b" / "f"),
                   str(tmp_path / "a" / "g")]
    got = sorted(p for p, m in ck.expand(str(tmp_path), ["a", "**", "*"], state) if m)
    assert str(tmp_path / "a" / "g") in got and str(tmp_path / "a" / "b" / "f") in got


def test_bash_double_star_walk_is_bounded(monkeypatch, tmp_path):
    hook = load_hook()
    scandir, _ = deep_tree(files=True)
    monkeypatch.setattr(hook, "_scandir", scandir)
    ck = checker(hook, tmp_path)
    t0 = time.monotonic()
    assert ck.glob("/**/zzqq*") is None
    assert time.monotonic() - t0 < 2.0 and ck._scanned == hook.MAX_GLOB_SCAN + 1
    assert ck.glob("/**/.env*") is not None                 # cut short: the pattern check still blocks


def test_bash_glob_final_symlink_match_is_checked_through_realpath(env):
    (env["proj"] / "d").mkdir()
    (env["proj"] / ".env").write_text("A=1\n")
    (env["proj"] / "d" / "notes.txt").symlink_to(env["proj"] / ".env")
    assert blocked(env, "Bash", {"command": "cat d/*.txt"})


def test_unreadable_directory_midway_is_skipped_not_an_error(monkeypatch, tmp_path):
    """/proc/1/map_files opens but fails on read (EACCES): that raised out of the hook and failed it open."""
    hook = load_hook()

    class Failing(FakeDir):
        def __iter__(self):
            yield FakeEntry("zzqq1", is_dir=False)
            raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(hook, "_scandir", lambda path: Failing([]))
    ck = checker(hook, tmp_path)
    state = {"complete": True}
    assert list(ck.expand("/", ["zzqq*"], state)) == [("/zzqq1", True)] and state["complete"]
    monkeypatch.setattr(hook.os, "scandir", lambda path: Failing([]))
    assert hook.grep_walk(ck.policy, [str(tmp_path)], lambda rel: True) == (None, False)


def test_bash_glob_walk_hidden_names_follow_the_shell(tmp_path):
    hook = load_hook()
    (tmp_path / ".hid").mkdir()
    (tmp_path / ".hid" / "a.txt").write_text("x\n")
    (tmp_path / "vis").mkdir()
    (tmp_path / "vis" / "a.txt").write_text("x\n")
    ck = checker(hook, tmp_path)
    state = {"complete": True}
    assert list(ck.expand(str(tmp_path), ["*", "a.txt"], state)) == [(str(tmp_path / "vis" / "a.txt"), True)]
    assert list(ck.expand(str(tmp_path), [".h*", "*.txt"], state)) == [(str(tmp_path / ".hid" / "a.txt"), True)]


def test_bash_deep_root_glob_repro_is_fast(env):
    """The adversary's repro on the real filesystem, through the hook."""
    t0 = time.monotonic()
    rc, err = run(env, "Bash", {"command": "ls /*/*/*/*/*/*/*/zzqq*"})
    assert (rc, err) == (0, "")
    assert time.monotonic() - t0 < 8.0
    assert run(env, "Bash", {"command": "ls /*/*/*/*/*/*/*/zzqq* ~/.ssh/id_*"})[0] == 2


def test_tilde_user_is_expanded(tmp_path):
    """Adversary finding C5 (2026-11-04): `~user/...` names the same home as `~/...`."""
    pwd = pytest.importorskip("pwd")
    try:
        user = pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        pytest.skip("no passwd entry for this uid")
    home = os.path.expanduser("~" + user)
    if home.startswith("~"):
        pytest.skip("~user does not expand here")
    hook = load_hook()
    ck = hook.Checker(hook.Policy(["~/.netrc"], [], homes=[home], fold=False), str(tmp_path))
    assert ck.path("~%s/.netrc" % user)
    assert hook.check_command(ck, "cat ~%s/.netrc" % user)
    assert ck.path("~%s/notes.txt" % user) is None
    assert ck.path("~no-such-user-xyz/.netrc") is None


def test_nul_in_a_path_is_not_a_path(env):
    rc, _ = run(env, None, None, raw=json.dumps({"tool_name": "Read", "tool_input": {"file_path": ".env\x00x"}}))
    assert rc == 0


# ---- the engine ----------------------------------------------------------------------------------------------------------
def test_regex_and_automaton_agree():
    hook = load_hook()
    pats = ["**/.env", "**/.env.*", "**/*.key", "/h/.ssh/**", "/h/.ssh", "/h/.netrc", "**/privkey*.pem", "**/id_rsa"]
    paths = ["/p/.env", "/.env", "/p/.env.x", "/p/.envx", "/p/a/b.key", "/p/.key", "/h/.ssh/a/b", "/h/.ssh",
             "/h/.sshx", "/h/.netrc", "/p/privkey.pem", "/p/privkey12.pem", "/p/x/privkey/a.pem", "/id_rsa", "/a/id_rsa.pub"]
    for p in pats:
        ats = hook.atoms(p)
        rx = hook.to_regex(ats, False)
        for s in paths:
            lit = [(hook.LIT, c) for c in s]
            assert bool(rx.fullmatch(s)) == hook.nonempty([ats, lit], []), (p, s)


def test_overlap_engine_basics():
    hook = load_hook()
    a = hook.atoms
    assert hook.nonempty([a("/h/.ssh/id_*"), a("/h/.ssh/**")], [a("**/*.pub")])
    assert not hook.nonempty([a("/h/.ssh/*.pub"), a("/h/.ssh/**")], [a("**/*.pub")])
    assert not hook.nonempty([a("**/*.key")], [a("**/*")])             # inclusion
    assert hook.nonempty([a("/p/*"), a("**/*.key")], [])               # plain overlap
    assert not hook.nonempty([a("/p/*"), a("**/*.key")], [], pin_first=True)
    assert not hook.nonempty([a("/p/*.py"), a("**/.env.*")], [], dotfile_first=True)


def test_case_fold_on_macos_semantics():
    hook = load_hook()
    pol = hook.Policy([".env", "~/.netrc"], [".env.example"], homes=["/Users/u"], fold=True)
    assert pol.verdict("/p/.ENV") == ".env"
    assert pol.verdict("/USERS/U/.NETRC") == "~/.netrc"
    assert pol.verdict("/p/.ENV.EXAMPLE") is None
    strict = hook.Policy([".env"], [], homes=["/Users/u"], fold=False)
    assert strict.verdict("/p/.ENV") is None


# ---- Python 3.9 and packaging ----------------------------------------------------------------------------------------------
def test_source_parses_as_python_3_9():
    src = HOOK.read_text()
    ast.parse(src, feature_version=(3, 9))
    assert "from __future__ import annotations" in src


def test_no_tomllib_or_match():
    tree = ast.parse(HOOK.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
        assert type(node).__name__ != "Match"
    assert "tomllib" not in names and "tomli" not in names


def test_executable_with_env_shebang():
    assert HOOK.read_text().startswith("#!/usr/bin/env python3\n")
    assert HOOK.stat().st_mode & stat.S_IXUSR


def oldest_python():
    for name in ("python3.9", "python3.10", "python3.11"):
        found = shutil.which(name)
        if found:
            return found
    if os.path.exists("/usr/bin/python3"):
        return "/usr/bin/python3"
    return None


def test_runs_under_the_oldest_python_available(env):
    py = oldest_python()
    if py is None:
        pytest.skip("no old python3 on this machine")
    assert run(env, "Read", {"file_path": ".env"}, python=py)[0] == 2
    assert run(env, "Read", {"file_path": ".env.example"}, python=py) == (0, "")
    assert run(env, "Bash", {"command": "cat ~/.ssh/id_*"}, python=py)[0] == 2


def test_committed_policy_is_what_the_hook_reads_by_default(env):
    assert POLICY.is_file()
    hook = load_hook()
    os.environ.pop("SECRET_DENY_POLICY", None)
    assert Path(hook.policy_path()).resolve() == POLICY.resolve()
