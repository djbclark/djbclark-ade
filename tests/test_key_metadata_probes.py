"""Fixed read-only provider contracts, using only synthetic keys/mocked HTTP."""
from __future__ import annotations

import io
import json
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))
import ade_install as ai

SECRET = "SYNTHETIC_VALUE_MUST_NOT_ESCAPE"
SPECS = {
    "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1/models", {"object": "list", "data": []}),
    "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1/key",
                   {"data": {"is_free_tier": False, "usage": 0, "label": SECRET, "limit_remaining": 0}}),
}


class Response:
    def __init__(self, body, status=200):
        self.body, self.status = body, status
        self.read_sizes = []
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def getcode(self):
        return self.status
    def read(self, size):
        self.read_sizes.append(size)
        return self.body[:size]


@pytest.mark.parametrize("provider", SPECS)
def test_fixed_get_headers_response_limit_and_no_output(provider, capsys):
    name, url, data = SPECS[provider]
    response = Response(json.dumps(data).encode())
    def opener(request, *, timeout):
        assert request.full_url == url
        assert request.get_method() == "GET"
        assert request.data is None
        assert request.get_header("Authorization") == "Bearer " + SECRET
        assert SECRET not in request.full_url
        assert timeout == 10
        return response
    assert ai.verify_key_metadata(provider, environ={name: SECRET}, opener=opener) == 0
    assert response.read_sizes == [256 * 1024 + 1]
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("key,code", [(None, 14), ("", 14), ("bad\r\nheader", 10), ("bad token", 10)])
def test_missing_or_invalid_values_never_open(key, code):
    opener = Mock(side_effect=AssertionError("invalid key reached transport"))
    assert ai.verify_key_metadata("openai", environ={"OPENAI_API_KEY": key}, opener=opener) == code
    opener.assert_not_called()


@pytest.mark.parametrize("status,expected", [(401, 10), (403, 10), (429, 12), (500, 12), (503, 12), (302, 12), (402, 12)])
def test_http_errors_are_exit_codes_without_bodies_or_retries(status, expected, capsys):
    class ErrorBody(io.BytesIO):
        def read(self, *args):
            raise AssertionError("provider error body must not be read")
    error = urllib.error.HTTPError("https://api.openai.com/v1/models", status, SECRET, {}, ErrorBody(SECRET.encode()))
    opener = Mock(side_effect=error)
    assert ai.verify_key_metadata("openai", environ={"OPENAI_API_KEY": SECRET}, opener=opener) == expected
    assert opener.call_count == 1
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("error", [urllib.error.URLError(SECRET), ssl.SSLError(SECRET), TimeoutError(SECRET), OSError(SECRET)])
def test_network_tls_timeout_values_never_escape(error, capsys):
    opener = Mock(side_effect=error)
    assert ai.verify_key_metadata("openai", environ={"OPENAI_API_KEY": SECRET}, opener=opener) == 12
    assert opener.call_count == 1
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("provider,body", [
    ("openai", SECRET.encode()), ("openai", b"[]"), ("openai", b'{"object":"list","data":["bad"]}'),
    ("openai", b'{"data":[]}'), ("openai", b"x" * (256 * 1024 + 1)),
    ("openai", b'{"object":"list","data":[],"extra":NaN}'),
    ("openrouter", b'{"data":{}}'), ("openrouter", b'{"data":{"is_free_tier":true,"usage":true}}'),
    ("openrouter", b'{"data":{"is_free_tier":true,"usage":NaN}}'),
])
def test_malformed_success_is_error_not_authenticated(provider, body, capsys):
    name = SPECS[provider][0]
    assert ai.verify_key_metadata(provider, environ={name: SECRET}, opener=lambda *a, **k: Response(body)) == 1
    assert capsys.readouterr() == ("", "")


def test_transport_refuses_redirects(monkeypatch):
    captured = []
    def build(*handlers):
        captured.extend(handlers)
        return type("FakeOpener", (), {"open": staticmethod(lambda *a, **k: Response(b'{"object":"list","data":[]}'))})()
    monkeypatch.setattr(urllib.request, "build_opener", build)
    assert ai.verify_key_metadata("openai", environ={"OPENAI_API_KEY": SECRET}) == 0
    handler, = captured
    assert isinstance(handler, urllib.request.HTTPRedirectHandler)
    assert handler.redirect_request(None, None, 302, SECRET, {}, "https://other.example/") is None


def test_catalog_engine_uses_secret_boundary_and_persists_only_status(tmp_path, monkeypatch):
    catalog = ai.load_catalog(root=REPO, install_path=REPO / "config/install.toml")
    rows = {row["name"]: row for row in catalog.keys}
    seen = []
    monkeypatch.setattr(ai, "_probe_executable_missing", lambda _: False)
    def runner(argv, cwd):
        seen.append(argv)
        assert SECRET not in repr(argv)
        if argv[:2] == ["sudo-secretspec", "check"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        assert argv[:2] == ["sudo-secretspec", "run"]
        assert argv[argv.index("--") + 1:] in [
            [str(REPO / "bin/ade-install"), "verify-key", "openai"],
            [str(REPO / "bin/ade-install"), "verify-key", "openrouter"],
        ]
        return subprocess.CompletedProcess(argv, 0, SECRET, SECRET)
    state = tmp_path / "keys.json"
    observations, rc = ai.keys_observe(catalog, runner=runner, keys_state_path=state)
    assert rc == 0
    assert len(seen) == 3  # one bulk check and one request for each covered key
    assert rows["OPENAI_API_KEY"]["verify_argv"] == ["{bin}/ade-install", "verify-key", "openai"]
    assert rows["OPENROUTER_API_KEY"]["verify_argv"] == ["{bin}/ade-install", "verify-key", "openrouter"]
    assert sum(bool(r.get("verify_argv")) for r in catalog.keys) == 2
    assert SECRET not in state.read_text() and SECRET not in repr(observations)
    saved = json.loads(state.read_text())
    assert saved["keys"]["OPENAI_API_KEY"]["status"] == "ok"


def test_cli_missing_key_is_silent_exit_only(tmp_path):
    # An empty environment mapping is forced in-process before running the CLI;
    # no actual key or network source is consulted.
    code = '''
import runpy,sys
sys.path.insert(0, sys.argv[1])
import ade_install
original = ade_install.verify_key_metadata
ade_install.verify_key_metadata = lambda p: original(p, environ={})
path = sys.argv[2]
sys.argv = [path, "verify-key", "openai"]
runpy.run_path(path, run_name="__main__")
'''
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(REPO / "bin"), str(REPO / "bin/ade-install")],
                            cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode == 14
    assert result.stdout == result.stderr == ""
