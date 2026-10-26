"""bin/mastracode-managed: the key boundary (which secret is fetched, where it may go) and exec failures.

No managed key, no network and no real mastracode: subprocess.run, os.execve and the HTTPS handler
are replaced, and every key is a made-up string.
"""
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import types
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "mastracode-managed"
FAKE_KEY = "sk-ant-test-0000"


def load() -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader("mastracode_managed", str(SCRIPT))
    spec = importlib.util.spec_from_loader("mastracode_managed", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


@pytest.fixture
def mm(monkeypatch):
    mod = load()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("MASTRACODE_REAL_BIN", str(SCRIPT.parent / "acp-dispatch"))  # any executable file
    return mod


@pytest.fixture
def calls(monkeypatch):
    """Record subprocess.run argv lists and execve calls instead of running them."""
    rec = types.SimpleNamespace(run=[], exec=[], rc=0, out=FAKE_KEY + "\n", exec_error=None)

    def fake_run(argv, **kw):
        rec.run.append((argv, kw))
        return subprocess.CompletedProcess(argv, rec.rc, rec.out, "client said: " + FAKE_KEY)

    def fake_execve(path, argv, env):
        rec.exec.append((path, argv, env))
        if rec.exec_error:
            raise rec.exec_error

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("os.execve", fake_execve)
    return rec


def test_fetches_only_the_one_secret_and_adds_only_it(mm, calls, monkeypatch):
    monkeypatch.setenv("KEEP_ME", "1")
    before = dict(os.environ)
    mm.main(["--permission-mode", "auto", "-p", "two words"])

    assert len(calls.run) == 1
    argv, kw = calls.run[0]
    assert argv[1:4] == ["get", "ANTHROPIC_API_KEY", "--reason"]  # never `run`, `export` or another name
    assert kw["stdin"] == subprocess.DEVNULL
    path, child_argv, env = calls.exec[0]
    assert child_argv == [path, "--permission-mode", "auto", "-p", "two words"]
    assert env["ANTHROPIC_API_KEY"] == FAKE_KEY and env["KEEP_ME"] == "1"
    assert set(env) - set(before) == {"ANTHROPIC_API_KEY"}
    assert all(env[k] == before[k] for k in before)
    assert env["ANTHROPIC_API_KEY"] == FAKE_KEY


def test_preset_key_wins_and_nothing_is_fetched(mm, calls, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "preset")
    mm.main([])
    assert calls.run == []
    assert calls.exec[0][2]["ANTHROPIC_API_KEY"] == "preset"


def test_prefers_canonical_client_only_when_executable(mm, calls, monkeypatch):
    monkeypatch.setattr("os.access", lambda p, m: p == mm.CLIENT)
    mm.managed_key()
    assert calls.run[-1][0][0] == mm.CLIENT
    monkeypatch.setattr("os.access", lambda p, m: False)
    mm.managed_key()
    assert calls.run[-1][0][0] == "sudo-secretspec"


@pytest.mark.parametrize("rc,out", [(3, FAKE_KEY), (0, "  \n")])
def test_fetch_failure_never_execs_and_never_prints_the_key(mm, calls, capfd, rc, out):
    calls.rc, calls.out = rc, out
    assert mm.main(["-p", "x"]) == 1
    assert calls.exec == []
    cap = capfd.readouterr()
    assert FAKE_KEY not in cap.out + cap.err


def test_client_missing_is_a_clean_failure(mm, monkeypatch, capfd):
    def boom(*a, **k):
        raise FileNotFoundError("no client")
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr("os.execve", lambda *a: pytest.fail("exec after failed fetch"))
    assert mm.main([]) == 1
    assert "FileNotFoundError" in capfd.readouterr().err


def _fake_https(monkeypatch, code, body=b"", headers=()):
    seen = []

    def https_open(self, req):
        seen.append((req.full_url, dict(req.header_items())))
        msg = Message()
        for k, v in headers:
            msg[k] = v
        resp = urllib.response.addinfourl(io.BytesIO(body), msg, req.full_url, code)
        resp.msg = "fake"
        return resp

    monkeypatch.setattr(urllib.request.HTTPSHandler, "https_open", https_open)
    return seen


def test_check_refuses_a_redirect_and_never_forwards_the_key(mm, monkeypatch, capfd):
    seen = _fake_https(monkeypatch, 302, headers=[("Location", "https://elsewhere.invalid/v1/models")])
    assert mm.check(FAKE_KEY) == 1
    assert [u for u, _ in seen] == [mm.MODELS_URL]  # the Location was not requested
    assert "HTTP 302" in capfd.readouterr().err


def test_check_success_prints_no_key_and_does_not_exec(mm, calls, monkeypatch, capfd):
    _fake_https(monkeypatch, 200, body=json.dumps({"data": [{"id": "claude-sonnet-5-5"}]}).encode())
    assert mm.main(["--check"]) == 0
    assert calls.exec == []
    cap = capfd.readouterr()
    assert "1 models, sonnet-5-5 listed: True" in cap.out and FAKE_KEY not in cap.out + cap.err


def test_missing_mastracode_is_127_before_any_exec(mm, calls, monkeypatch):
    monkeypatch.delenv("MASTRACODE_REAL_BIN")
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert mm.main([]) == 127
    assert calls.exec == []


def test_wrapper_resolving_to_itself_is_127_not_a_loop(mm, calls, monkeypatch):
    monkeypatch.setenv("MASTRACODE_REAL_BIN", str(SCRIPT))
    assert mm.main([]) == 127
    assert calls.exec == []


def test_exec_error_is_126_without_a_traceback_or_the_key(mm, calls, capfd):
    calls.exec_error = PermissionError("no")
    assert mm.main([]) == 126
    cap = capfd.readouterr()
    assert "exec failed: PermissionError" in cap.err and FAKE_KEY not in cap.out + cap.err
