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


# ---- Grep ------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("inp,want", [
    ({"pattern": "x", "path": ".env"}, True),
    ({"pattern": "x", "path": "~/.ssh"}, True),
    ({"pattern": "x", "path": "~/.ssh/config"}, False),
    ({"pattern": "x", "glob": ".env*"}, True),
    ({"pattern": "x", "glob": "*.{env,key}"}, True),
    ({"pattern": "x", "glob": "**/*.key"}, True),
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
    cmd_ok = "apply_patch <<'EOF'\n" + patch("*** Add File: a.py", body='+x = ".env"\n') + "EOF\n"
    assert not blocked(env, "Bash", {"command": cmd_ok})


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


def test_bash_glob_expansion_is_lazy_and_capped(monkeypatch, tmp_path):
    """Adversary finding B2 (2026-11-04): `ls /*/*/*/*/*/*` took 6.3 s in glob.glob, outside the budget."""
    hook = load_hook()
    pulled = []

    def endless(pattern):
        i = 0
        while True:
            pulled.append(i)
            yield "/nowhere/f%d.txt" % i
            i += 1
    monkeypatch.setattr(hook.globmod, "iglob", endless)
    ck = hook.Checker(hook.Policy([".env"], [], homes=[str(tmp_path)], fold=False), str(tmp_path))
    assert ck.glob("/*/*/*/*/*/*") is None
    assert len(pulled) == hook.MAX_GLOB_HITS


def test_bash_glob_expansion_respects_the_budget(monkeypatch, tmp_path, capsys):
    hook = load_hook()

    def slow(pattern):
        while True:
            time.sleep(0.05)
            yield "/nowhere/f.txt"
    monkeypatch.setattr(hook.globmod, "iglob", slow)
    monkeypatch.setattr(hook, "BUDGET_S", 0.3)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "ls /*/*/*/*/*/*"}, "cwd": str(tmp_path)})))
    monkeypatch.delenv("SECRET_DENY_OFF", raising=False)
    monkeypatch.delenv("SECRET_DENY_POLICY", raising=False)
    t0 = time.monotonic()
    assert hook.main() == 0
    assert time.monotonic() - t0 < 3
    assert "OutOfTime" in capsys.readouterr().err


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
