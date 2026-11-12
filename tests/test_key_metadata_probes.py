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
    "anthropic": ("ANTHROPIC_API_KEY", "https://api.anthropic.com/v1/models",
                  {"data": [{"type": "model", "id": "fixture-model"}], "has_more": True}),
    "gemini": ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/models",
               {"models": [{"name": "models/fixture-model"}], "nextPageToken": "not-followed"}),
    "deepseek": ("DEEPSEEK_API_KEY", "https://api.deepseek.com/models",
                 {"object": "list", "data": [{"object": "model", "id": "fixture-model"}]}),
    "cursor": ("CURSOR_API_KEY", "https://api.cursor.com/v1/me",
               {"apiKeyName": "fixture-key", "createdAt": "2026-01-01T00:00:00.000Z"}),
    "github": ("FIRECRAWL_GITHUB_PUBLIC_TOKEN", "https://api.github.com/rate_limit",
               {"resources": {"core": {"limit": 5000, "remaining": 4999, "reset": 1765400000}},
                "rate": {"limit": 5000}}),
}
ENGINE_PROVIDERS = [*SPECS, "telegram"]  # catalog rows with recorded verify_argv


class Response:
    def __init__(self, body, status=200, headers=None):
        self.body, self.status = body, status
        self.headers = headers or {}
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
        if provider == "gemini":
            assert request.get_header("X-goog-api-key") == SECRET
            assert request.get_header("Authorization") is None
            assert "?" not in request.full_url
        else:
            assert request.get_header("Authorization") == "Bearer " + SECRET
            assert request.get_header("X-goog-api-key") is None
        assert request.get_header("Anthropic-version") == ("2026-10-21" if provider == "anthropic" else None)
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


@pytest.mark.parametrize("provider", ["anthropic", "gemini", "deepseek"])
@pytest.mark.parametrize("status,code", [(401, 10), (403, 10), (400, 12), (429, 12), (503, 12), (302, 12)])
def test_added_provider_failures_remain_silent_and_conservative(provider, status, code, capsys):
    name, url, _ = SPECS[provider]
    opener = Mock(side_effect=urllib.error.HTTPError(url, status, SECRET, {}, io.BytesIO(SECRET.encode())))
    assert ai.verify_key_metadata(provider, environ={name: SECRET}, opener=opener) == code
    assert opener.call_count == 1
    assert opener.call_args.args[0].full_url == url
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("provider,body", [
    ("openai", SECRET.encode()), ("openai", b"[]"), ("openai", b'{"object":"list","data":["bad"]}'),
    ("openai", b'{"data":[]}'), ("openai", b"x" * (256 * 1024 + 1)),
    ("openai", b'{"object":"list","data":[],"extra":NaN}'),
    ("openrouter", b'{"data":{}}'), ("openrouter", b'{"data":{"is_free_tier":true,"usage":true}}'),
    ("openrouter", b'{"data":{"is_free_tier":true,"usage":NaN}}'),
    ("anthropic", b'{"data":[]}'),
    ("anthropic", b'{"data":[],"has_more":1}'),
    ("anthropic", b'{"data":[{"object":"model","id":"fixture"}],"has_more":false}'),
    ("gemini", b'{}'), ("gemini", b'{"models":{}}'),
    ("gemini", b'{"models":[{"name":"fixture"}]}'),
    ("gemini", b'{"models":[{"name":"models/"}]}'),
    ("deepseek", b'{"object":"list","data":[{"id":"fixture"}]}'),
    ("cursor", b'{}'), ("cursor", b'{"apiKeyName":""}'), ("cursor", b'{"apiKeyName":123}'),
    ("github", b'{}'), ("github", b'{"resources":{}}'),
    ("github", b'{"resources":{"core":{"limit":60}}}'),
    ("github", b'{"resources":{"core":{"limit":true}}}'),
])
def test_malformed_success_is_error_not_authenticated(provider, body, capsys):
    name = SPECS[provider][0]
    assert ai.verify_key_metadata(provider, environ={name: SECRET}, opener=lambda *a, **k: Response(body)) == 1
    assert capsys.readouterr() == ("", "")


def test_github_expiring_marker_is_the_only_output(capsys):
    name, url, data = SPECS["github"]
    response = Response(
        json.dumps(data).encode(),
        headers={"github-authentication-token-expiration": "2026-12-25 07:00:00 UTC"},
    )
    def opener(request, *, timeout):
        assert request.get_header("Authorization") == "Bearer " + SECRET
        return response
    assert ai.verify_key_metadata("github", environ={name: SECRET}, opener=opener) == 0
    assert capsys.readouterr() == ("", f"{ai.VERIFY_MARKER_PREFIX}expiring:2026-12-25\n")


@pytest.mark.parametrize("header", [
    "2026-12-25 07:00:00 UTC", "2026-12-25T07:00:00Z", "2026-12-25", "2026-12-25trailing",
])
def test_github_parseable_expiration_emits_only_the_marker(header, capsys):
    name, url, data = SPECS["github"]
    response = Response(
        json.dumps(data).encode(),
        headers={"github-authentication-token-expiration": header},
    )
    assert ai.verify_key_metadata("github", environ={name: SECRET}, opener=lambda *a, **k: response) == 0
    assert capsys.readouterr() == ("", f"{ai.VERIFY_MARKER_PREFIX}expiring:2026-12-25\n")


@pytest.mark.parametrize("header", [
    None, "", "not-a-date", "2026-13-99 00:00:00 UTC", "junk2026-12-25", SECRET,
])
def test_github_unparseable_or_absent_expiration_stays_ok_and_silent(header, capsys):
    name, url, data = SPECS["github"]
    headers = {} if header is None else {"github-authentication-token-expiration": header}
    response = Response(json.dumps(data).encode(), headers=headers)
    assert ai.verify_key_metadata("github", environ={name: SECRET}, opener=lambda *a, **k: response) == 0
    assert capsys.readouterr() == ("", "")


def test_telegram_token_travels_in_documented_path_only(capsys):
    response = Response(json.dumps(
        {"ok": True, "result": {"id": 1, "is_bot": True, "username": "fixture_bot"}}
    ).encode())
    def opener(request, *, timeout):
        # Telegram defines no header form; the token is its documented path
        # element and must never appear in a query string or a header.
        assert request.full_url == "https://api.telegram.org/bot" + SECRET + "/getMe"
        assert request.get_method() == "GET"
        assert request.data is None
        assert request.get_header("Authorization") is None
        assert "?" not in request.full_url
        assert timeout == 10
        return response
    assert ai.verify_key_metadata("telegram", environ={"TELEGRAM_BOT_TOKEN": SECRET}, opener=opener) == 0
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("body", [
    b'{}',
    b'{"ok":true}',
    b'{"ok":false,"result":{"id":1,"is_bot":true}}',
    b'{"ok":true,"result":{"id":"1","is_bot":true}}',
    b'{"ok":true,"result":{"id":1,"is_bot":false}}',
    b'{"ok":true,"result":{"id":true,"is_bot":true}}',
    (SECRET * 3).encode(),
])
def test_telegram_malformed_success_is_error_not_authenticated(body, capsys):
    assert ai.verify_key_metadata(
        "telegram", environ={"TELEGRAM_BOT_TOKEN": SECRET}, opener=lambda *a, **k: Response(body)
    ) == 1
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("status,code", [(401, 10), (403, 10), (404, 12), (429, 12), (500, 12)])
def test_telegram_http_failures_remain_silent_and_conservative(status, code, capsys):
    url = "https://api.telegram.org/bot" + SECRET + "/getMe"
    opener = Mock(side_effect=urllib.error.HTTPError(url, status, SECRET, {}, io.BytesIO(SECRET.encode())))
    assert ai.verify_key_metadata("telegram", environ={"TELEGRAM_BOT_TOKEN": SECRET}, opener=opener) == code
    assert opener.call_count == 1
    assert capsys.readouterr() == ("", "")


def test_telegram_network_error_is_unreachable(capsys):
    opener = Mock(side_effect=urllib.error.URLError(SECRET))
    assert ai.verify_key_metadata("telegram", environ={"TELEGRAM_BOT_TOKEN": SECRET}, opener=opener) == 12
    opener.assert_called_once()
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("key", ["123:x/y", "123:x?y", "123:x#y", "123:x%y"])
def test_telegram_structural_key_chars_rejected_without_transport(key):
    opener = Mock(side_effect=AssertionError("structural key reached transport"))
    assert ai.verify_key_metadata("telegram", environ={"TELEGRAM_BOT_TOKEN": key}, opener=opener) == 10
    opener.assert_not_called()


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
            [str(REPO / "bin/ade-install"), "verify-key", provider] for provider in ENGINE_PROVIDERS
        ]
        return subprocess.CompletedProcess(argv, 0, SECRET, SECRET)
    state = tmp_path / "keys.json"
    observations, rc = ai.keys_observe(catalog, runner=runner, keys_state_path=state)
    assert rc == 0
    assert len(seen) == 9  # one bulk check and one request for each covered key
    assert rows["OPENAI_API_KEY"]["verify_argv"] == ["{bin}/ade-install", "verify-key", "openai"]
    assert rows["OPENROUTER_API_KEY"]["verify_argv"] == ["{bin}/ade-install", "verify-key", "openrouter"]
    for provider, (name, _, _) in SPECS.items():
        assert rows[name]["verify_argv"] == ["{bin}/ade-install", "verify-key", provider]
    assert rows["TELEGRAM_BOT_TOKEN"]["verify_argv"] == ["{bin}/ade-install", "verify-key", "telegram"]
    assert sum(bool(r.get("verify_argv")) for r in catalog.keys) == 8
    assert SECRET not in state.read_text() and SECRET not in repr(observations)
    saved = json.loads(state.read_text())
    assert saved["keys"]["OPENAI_API_KEY"]["status"] == "ok"


@pytest.mark.parametrize("provider", [*SPECS, "telegram"])
def test_cli_missing_key_is_silent_exit_only(tmp_path, provider):
    # An empty environment mapping is forced in-process before running the CLI;
    # no actual key or network source is consulted.
    code = '''
import runpy,sys
sys.path.insert(0, sys.argv[1])
import ade_install
original = ade_install.verify_key_metadata
ade_install.verify_key_metadata = lambda p: original(p, environ={})
path = sys.argv[2]
sys.argv = [path, "verify-key", sys.argv[3]]
runpy.run_path(path, run_name="__main__")
'''
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(REPO / "bin"), str(REPO / "bin/ade-install"), provider],
                            cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode == 14
    assert result.stdout == result.stderr == ""
