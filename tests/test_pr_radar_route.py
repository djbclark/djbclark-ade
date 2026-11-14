"""Tests for bin/pr-radar-route: the router is a stub; no live quota is read and the real ADE router is never run.

Every subprocess run gets a throwaway HOME (so ~/src/djbclark-ade/bin/route_agent.py is not the live router) and
PR_RADAR_ROUTE_AGENT unset unless a test sets it.
"""
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get("PR_RADAR_ROUTE_UNDER_TEST") or ROOT / "bin/pr-radar-route")  # mutation checks point at a mutated copy

DISPATCH = "paseo run --provider claude/opus --thinking high --mode bypassPermissions --label ade.kind=judgment --no-wait"
ANSWER = {"kind": "judgment", "agent": "claude", "dispatch": DISPATCH, "why": "judgment: claude; 52% headroom"}

# The stub records its argv and its own path, then behaves as FAKE_MODE says.
STUB = '''#!/usr/bin/env python3
import json, os, sys, time
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps([__file__] + sys.argv[1:]) + "\\n")
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "fail":
    sys.stderr.write("quota snapshot missing\\n")
    sys.exit(7)
if mode == "fail-silent":
    sys.exit(3)
if mode == "no-headroom":      # what route_agent.py route prints when no service has headroom: JSON on stdout, exit 1
    print(json.dumps({"kind": "code", "service": None, "reason": "no eligible service with headroom"}))
    sys.exit(1)
if mode == "fail-both":
    print(json.dumps({"reason": "stdout reason"}))
    sys.stderr.write("stderr reason\\n")
    sys.exit(4)
if mode == "fail-noise":
    print("not json {")
    sys.exit(2)
if mode == "fail-odd-reason":
    print(json.dumps({"reason": ["x"]}))
    sys.exit(5)
if mode == "bad":
    print("not json {")
    sys.exit(0)
if mode == "list":
    print("[1, 2]")
    sys.exit(0)
print(os.environ["FAKE_ANSWER"])
'''


def load_module():
    loader = importlib.machinery.SourceFileLoader("pr_radar_route", str(SCRIPT))
    spec = importlib.util.spec_from_loader("pr_radar_route", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Rig:
    """A directory holding a copy of the script and a stub route_agent.py beside it."""

    def __init__(self, tmp_path, subdir="bin", router_beside=True):
        self.tmp = tmp_path
        self.dir = tmp_path / "place" / subdir
        self.dir.mkdir(parents=True)
        self.script = self.dir / "pr-radar-route"
        shutil.copy(SCRIPT, self.script)
        self.script.chmod(0o755)
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.calls = tmp_path / "calls.jsonl"
        if router_beside:
            (self.dir / "route_agent.py").write_text(STUB)

    def run(self, stdin, mode="ok", answer=ANSWER, **env_extra):
        env = dict(os.environ, HOME=str(self.home), FAKE_CALLS=str(self.calls), FAKE_MODE=mode, FAKE_ANSWER=json.dumps(answer))
        env.pop("PR_RADAR_ROUTE_AGENT", None)
        env.update(env_extra)
        text = stdin if isinstance(stdin, str) else json.dumps(stdin)
        proc = subprocess.run([sys.executable, str(self.script)], input=text, capture_output=True, text=True, env=env,
                              timeout=60, cwd=self.tmp)
        return proc, self.argvs()

    def argvs(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []


@pytest.fixture
def rig(tmp_path):
    """Script beside a stub router with no config/routing.toml: the vendored-copy layout (router choice 4)."""
    r = Rig(tmp_path)

    def run(stdin, **kw):
        proc, argvs = r.run(stdin, **kw)
        return proc, [a[1:] for a in argvs]  # drop the router path

    run.rig = r
    return run


def routed_kind(argv):
    return argv[argv.index("--kind") + 1]


@pytest.mark.parametrize("pr, kind", [
    ({"reviewRequestedFromMe": True}, "judgment"),
    ({"isSecurity": True}, "judgment"),
    ({"reviewRequestedFromMe": True, "authorKind": "bot"}, "judgment"),
    ({"isSecurity": True, "authorKind": "bot"}, "judgment"),
    ({"authorKind": "bot"}, "bulk"),
    ({"authorKind": "human"}, "code"),
    ({"authorKind": "operator", "reviewRequestedFromMe": False, "isSecurity": False}, "code"),
    ({"reviewRequestedFromMe": False, "title": "an issue-like item"}, "code"),
    ({"reviewRequestedFromMe": None, "isSecurity": 0, "authorKind": ["bot"]}, "code"),
    ({}, "code"),
])
def test_kind_mapping(rig, pr, kind):
    proc, argvs = rig({"pr": pr})
    assert proc.returncode == 0, proc.stderr
    assert routed_kind(argvs[0]) == kind


@pytest.mark.parametrize("payload", ["", "  \n", "{}", "[]", '"x"', "null", '{"pr": null}', '{"pr": "text"}', '{"pr": [1]}'])
def test_empty_or_odd_stdin_routes_code(rig, payload):
    proc, argvs = rig(payload)
    assert proc.returncode == 0, proc.stderr
    assert routed_kind(argvs[0]) == "code"
    assert "--repo" not in argvs[0]


@pytest.mark.parametrize("repository, repo", [
    ("frdminc/tendcf", "tendcf"),
    ("djbclark/djbclark-ade", "djbclark-ade"),
    ("Owner/My_Repo.Name", "my_repo.name"),
    ("bare", "bare"),
    ("  frdminc/tendcf  ", "tendcf"),
    ("a/b/c", "c"),
    ("owner/.github", ".github"),
    ("owner/a-b", "a-b"),
])
def test_repo_extraction(rig, repository, repo):
    proc, argvs = rig({"pr": {"repository": repository}})
    assert proc.returncode == 0, proc.stderr
    assert argvs[0] == ["route", "--kind", "code", "--repo", repo, "--json"]


@pytest.mark.parametrize("repository", [
    "", "   ", "owner/", "owner/a b", "owner/a;b", "owner/$(x)", "owner/a`b`", "owner/ünï", "owner/a\nb", "owner/a=b",
    "owner/-x", "owner/--kind", "--json",
    None, ["a/b"], {"a": "b"}, False,
])
def test_repo_rejected(rig, repository):
    proc, argvs = rig({"pr": {"repository": repository}})
    assert proc.returncode == 0, proc.stderr
    assert argvs[0] == ["route", "--kind", "code", "--json"]


def test_router_argv_and_output(rig):
    proc, argvs = rig({"pr": {"reviewRequestedFromMe": True, "repository": "djbclark/djbclark-ade", "title": "x; rm -rf /"},
                       "settings": {"defaultProvider": "codex"}})
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    assert argvs == [["route", "--kind", "judgment", "--repo", "djbclark-ade", "--json"]]
    assert proc.stdout.endswith("\n") and proc.stdout.count("\n") == 1
    out = json.loads(proc.stdout)
    assert out == {
        "provider": "claude", "model": "opus", "thinkingOptionId": "high", "modeId": "bypassPermissions",
        "reason": "[judgment] judgment: claude; 52% headroom",
    }
    assert "contextMode" not in out and "profile" not in out   # PR Radar's launch-profile field (start-agent-modal reads result.profile)


def test_untrusted_text_never_reaches_the_router(rig):
    proc, argvs = rig({"pr": {"title": "ignore previous --kind frontier", "comments": ["--repo evil"], "labels": ["--json"],
                              "headRefName": "$(touch pwn)", "author": "--mode"}})
    assert proc.returncode == 0, proc.stderr
    assert argvs == [["route", "--kind", "code", "--json"]]


def test_bot_keeps_routed_yolo_mode(rig):
    proc, _ = rig({"pr": {"authorKind": "bot", "author": "dependabot[bot]"}})
    assert json.loads(proc.stdout)["modeId"] == "bypassPermissions"


def test_dispatch_without_model_or_mode(rig):
    proc, _ = rig({"pr": {}}, answer={"agent": "pi", "dispatch": "paseo run --provider pi --label ade.kind=code", "why": "w"})
    assert json.loads(proc.stdout) == {"provider": "pi", "reason": "[code] w"}


def test_agent_fallback_when_dispatch_has_no_provider(rig):
    proc, _ = rig({"pr": {}}, answer={"agent": "codex", "dispatch": "paseo run --no-wait"})
    assert json.loads(proc.stdout) == {"provider": "codex"}


def test_no_why_means_no_reason(rig):
    proc, _ = rig({"pr": {}}, answer={"dispatch": DISPATCH})
    assert "reason" not in json.loads(proc.stdout)


def test_router_failure_passes_stderr_and_exit_code_through(rig):
    proc, _ = rig({"pr": {"reviewRequestedFromMe": True}}, mode="fail")
    assert proc.returncode == 7
    assert proc.stdout == ""
    assert proc.stderr == "quota snapshot missing\n"


def test_router_failure_without_stderr_gets_a_reason(rig):
    proc, _ = rig({"pr": {}}, mode="fail-silent")
    assert proc.returncode == 3 and proc.stdout == ""
    assert proc.stderr == "route_agent.py exited with 3\n"


def test_no_headroom_reason_goes_to_stderr_and_stdout_stays_empty(rig):
    """route_agent.py prints the no-headroom reason on stdout (JSON) with empty stderr; PR Radar shows stderr only."""
    proc, _ = rig({"pr": {}}, mode="no-headroom")
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr == "no eligible service with headroom\n"


def test_router_stderr_beats_its_stdout_reason(rig):
    proc, _ = rig({"pr": {}}, mode="fail-both")
    assert proc.returncode == 4 and proc.stdout == ""
    assert proc.stderr == "stderr reason\n"


@pytest.mark.parametrize("mode", ["fail-noise", "fail-odd-reason"])
def test_router_failure_with_no_usable_reason_names_the_exit_code(rig, mode):
    proc, _ = rig({"pr": {}}, mode=mode)
    code = {"fail-noise": 2, "fail-odd-reason": 5}[mode]
    assert proc.returncode == code and proc.stdout == ""
    assert proc.stderr == f"route_agent.py exited with {code}\n"


@pytest.mark.parametrize("dispatch, field", [
    ("paseo run --provider agent/<id from: paseo provider models agent> --label ade.kind=code --no-wait", "model"),
    ("paseo run --provider <provider>/opus --no-wait", "provider"),
    ("paseo run --provider claude/opus --thinking <level> --no-wait", "thinkingOptionId"),
    ("paseo run --provider claude/opus --mode <mode> --no-wait", "modeId"),
    ("paseo run --provider claude/opus> --no-wait", "model"),
])
def test_template_dispatch_values_are_refused(rig, dispatch, field):
    proc, _ = rig({"pr": {}}, answer={"agent": "claude", "dispatch": dispatch, "why": "w"})
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert len(proc.stderr.splitlines()) == 1
    assert f"template {field}" in proc.stderr


def test_template_agent_fallback_is_refused(rig):
    proc, _ = rig({"pr": {}}, answer={"agent": "<agent>", "dispatch": "paseo run --no-wait"})
    assert proc.returncode == 1 and proc.stdout == ""
    assert "template provider" in proc.stderr


def test_angle_brackets_in_the_reason_text_are_not_a_template(rig):
    proc, _ = rig({"pr": {}}, answer={"dispatch": DISPATCH, "why": "judgment: <5% headroom on claude"})
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["reason"] == "[code] judgment: <5% headroom on claude"


@pytest.mark.parametrize("mode", ["bad", "list"])
def test_unparsable_router_output_fails(rig, mode):
    proc, _ = rig({"pr": {}}, mode=mode)
    assert proc.returncode == 1 and proc.stdout == ""
    assert len(proc.stderr.splitlines()) == 1


@pytest.mark.parametrize("answer", [{}, {"dispatch": "", "agent": ""}, {"dispatch": "unbalanced 'quote", "agent": 5}, {"dispatch": 7}])
def test_unusable_answer_fails(rig, answer):
    proc, _ = rig({"pr": {}}, answer=answer)
    assert proc.returncode == 1 and proc.stdout == ""
    assert len(proc.stderr.splitlines()) == 1


@pytest.mark.parametrize("payload", ["{not json", "\xff", '{"pr": '])
def test_bad_stdin_fails_before_the_router(rig, payload):
    proc, argvs = rig(payload)
    assert proc.returncode == 1 and proc.stdout == ""
    assert argvs == []
    assert len(proc.stderr.splitlines()) == 1


def test_missing_router_fails(tmp_path):
    r = Rig(tmp_path, router_beside=False)
    proc, argvs = r.run({"pr": {}})
    assert proc.returncode != 0 and proc.stdout == ""
    assert argvs == []


def test_router_timeout_is_a_failure(tmp_path):
    mod = load_module()
    router = tmp_path / "route_agent.py"
    router.write_text("import time\ntime.sleep(30)\n")
    with pytest.raises(mod.RouteFailure, match="timed out") as info:
        mod.route("code", "", router=router, timeout=0.5)
    assert info.value.code == 1


def test_main_reports_timeout_with_empty_stdout(monkeypatch, capsys):
    mod = load_module()

    def timed_out(*args, **kwargs):
        raise mod.RouteFailure("route_agent.py timed out after 25s")

    monkeypatch.setattr(mod, "route", timed_out)
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"pr": {}}'))
    assert mod.main() == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "route_agent.py timed out after 25s\n"


def test_missing_router_path_raises(tmp_path):
    mod = load_module()
    with pytest.raises(mod.RouteFailure):
        mod.route("code", "", router=tmp_path / "missing" / "route_agent.py")


def test_standalone_copy_has_no_dependency_on_its_ade_location(tmp_path):
    """Script plus a vendored route_agent.py in an unrelated directory, no config/, empty HOME: it just works."""
    r = Rig(tmp_path, subdir="pr-radar/examples")
    assert not (r.dir.parent / "config").exists()
    proc, argvs = r.run({"pr": {"reviewRequestedFromMe": True, "repository": "frdminc/tendcf"}})
    assert proc.returncode == 0, proc.stderr
    assert Path(argvs[0][0]).resolve() == (r.dir / "route_agent.py").resolve()
    assert argvs[0][1:] == ["route", "--kind", "judgment", "--repo", "tendcf", "--json"]
    assert json.loads(proc.stdout)["provider"] == "claude"


def test_script_imports_stdlib_only():
    import ast
    stdlib = set(sys.stdlib_module_names)
    tree = ast.parse(SCRIPT.read_text())
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            mods.add((node.module or "").split(".")[0])
    assert mods <= stdlib, mods - stdlib


def test_router_choice_ade_checkout_uses_sibling(tmp_path):
    """config/routing.toml in the script's parent: the sibling router wins over the live ~/src/djbclark-ade one."""
    r = Rig(tmp_path)
    (r.dir.parent / "config").mkdir()
    (r.dir.parent / "config" / "routing.toml").write_text("")
    decoy = r.home / "src" / "djbclark-ade" / "bin"
    decoy.mkdir(parents=True)
    (decoy / "route_agent.py").write_text(STUB)
    proc, argvs = r.run({"pr": {}})
    assert proc.returncode == 0, proc.stderr
    assert Path(argvs[0][0]).resolve() == (r.dir / "route_agent.py").resolve()


def test_router_choice_live_ade_router_beats_vendored_sibling(tmp_path):
    r = Rig(tmp_path)
    live = r.home / "src" / "djbclark-ade" / "bin"
    live.mkdir(parents=True)
    (live / "route_agent.py").write_text(STUB)
    proc, argvs = r.run({"pr": {}})
    assert proc.returncode == 0, proc.stderr
    assert Path(argvs[0][0]).resolve() == (live / "route_agent.py").resolve()


def test_router_choice_env_override_wins(tmp_path):
    r = Rig(tmp_path)
    (r.dir.parent / "config").mkdir()
    (r.dir.parent / "config" / "routing.toml").write_text("")
    other = tmp_path / "other_router.py"
    other.write_text(STUB)
    proc, argvs = r.run({"pr": {}}, PR_RADAR_ROUTE_AGENT=str(other))
    assert proc.returncode == 0, proc.stderr
    assert Path(argvs[0][0]).resolve() == other.resolve()


def test_script_is_executable():
    assert os.access(SCRIPT, os.X_OK)
