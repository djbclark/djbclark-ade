"""EZproxy refusal page must not be saved as a proxied source (research_check.py fetch)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "research" / "scripts" / "research_check.py"
REFUSED = b"<html><body>Oops! It looks like you have attempted to view a page that has not been configured for access.</body></html>"
BIG = (b"<html><body>" + b"word " * 400 + b"</body></html>")


@pytest.fixture(autouse=True)
def _clean_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator's shell exports the proxy variables; a test must start without them."""
    monkeypatch.delenv("RESEARCH_PROXY_URL", raising=False)
    monkeypatch.delenv("RESEARCH_EZPROXY_PREFIX", raising=False)


def _load():
    spec = importlib.util.spec_from_file_location("research_check", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_proxy_refused_detects_only_short_refusal_page() -> None:
    mod = _load()
    assert mod.proxy_refused(REFUSED)
    assert not mod.proxy_refused(BIG)
    assert not mod.proxy_refused(BIG + b"has not been configured for access" * 1000)  # long article quoting the phrase
    assert mod.proxy_refused(b"<p>has not been\n configured <b>for</b>&nbsp;access.</p>")  # wrapped, tagged, nbsp
    assert not mod.proxy_refused(b"%PDF-1.4 has not been configured for access")


def test_forced_proxy_refusal_saves_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    monkeypatch.setenv("RESEARCH_EZPROXY_PREFIX", "https://proxy.example.edu/login?url=")
    monkeypatch.setattr(mod, "http_get", lambda *a, **k: (REFUSED, "text/html", 200, "https://proxy.example.edu/login?url=x"))
    with pytest.raises(SystemExit) as exc:
        mod.cmd_fetch("s1", "https://arxiv.org/abs/1", tmp_path, via_proxy=True)
    assert exc.value.code == 2
    assert not (tmp_path / "sources" / "s1.txt").exists()


def test_auto_retry_refusal_keeps_direct_fetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    monkeypatch.setenv("RESEARCH_EZPROXY_PREFIX", "https://proxy.example.edu/login?url=")
    short = b"<html><body>buy this article</body></html>"

    def fake(url, *a, **k):
        if url.startswith("https://proxy.example.edu"):
            return REFUSED, "text/html", 200, url
        return short, "text/html", 200, url

    monkeypatch.setattr(mod, "http_get", fake)
    assert mod.cmd_fetch("s2", "https://example.org/p", tmp_path) == 0
    text = (tmp_path / "sources" / "s2.txt").read_text()
    assert "# via_proxy: false" in text
    assert "buy this article" in text and "configured for access" not in text
    assert "# final_url: https://example.org/p" in text


def test_auto_retry_login_stub_keeps_direct_fetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    monkeypatch.setenv("RESEARCH_EZPROXY_PREFIX", "https://proxy.example.edu/login?url=")
    direct = b"<html><body>get access through your institution</body></html>"
    login = b"<html><body>Sign in with your institution to continue</body></html>"
    monkeypatch.setattr(mod, "http_get", lambda url, *a, **k: (login, "text/html", 200, url) if "proxy.example" in url else (direct, "text/html", 200, url))
    assert mod.cmd_fetch("s3", "https://example.org/q", tmp_path) == 0
    text = (tmp_path / "sources" / "s3.txt").read_text()
    assert "# via_proxy: false" in text and "Sign in with your institution" not in text


def test_proxy_hop_refuses_file_scheme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    monkeypatch.setenv("RESEARCH_EZPROXY_PREFIX", "https://proxy.example.edu/login?url=")
    page = b"<html><script>location = 'file:///etc/hosts'</script></html>"
    monkeypatch.setattr(mod, "http_get", lambda url, *a, **k: (page, "text/html", 200, url))
    with pytest.raises(SystemExit):
        mod.fetch_via_proxy("https://example.org/z")


def test_old_variable_name_still_read(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    monkeypatch.delenv("RESEARCH_EZPROXY_PREFIX", raising=False)
    monkeypatch.setenv("RESEARCH_PROXY_URL", "https://old.example.edu/login?url=")
    assert mod.proxy_prefix() == "https://old.example.edu/login?url="
    monkeypatch.setenv("RESEARCH_EZPROXY_PREFIX", "https://new.example.edu/login?url=")
    assert mod.proxy_prefix() == "https://new.example.edu/login?url="


def _retry(mod, monkeypatch, tmp_path, proxied_body, ctype="text/html"):
    monkeypatch.setenv("RESEARCH_EZPROXY_PREFIX", "https://proxy.example.edu/login?url=")
    direct = b"<html><body>get access through your institution</body></html>"
    monkeypatch.setattr(mod, "http_get", lambda url, *a, **k: (proxied_body, ctype, 200, url) if "proxy.example" in url else (direct, "text/html", 200, url))
    assert mod.cmd_fetch("r", "https://example.org/a", tmp_path) == 0
    return (tmp_path / "sources" / "r.txt").read_text()


def test_auto_retry_accepts_long_article_with_paywall_phrase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    article = b"<html><body>" + b"word " * 3000 + b" get access to more. Purchase PDF </body></html>"
    assert "# via_proxy: true" in _retry(mod, monkeypatch, tmp_path, article)


def test_auto_retry_accepts_proxied_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    monkeypatch.setattr(mod.shutil, "which", lambda n: None)  # no pdftotext: die after the accept decision, proving it was accepted
    monkeypatch.setenv("RESEARCH_EZPROXY_PREFIX", "https://proxy.example.edu/login?url=")
    direct = b"<html><body>buy this article</body></html>"
    monkeypatch.setattr(mod, "http_get", lambda url, *a, **k: (b"%PDF-1.4 x", "application/pdf", 200, url) if "proxy.example" in url else (direct, "text/html", 200, url))
    with pytest.raises(SystemExit) as exc:
        mod.cmd_fetch("p", "https://example.org/a.pdf", tmp_path)
    assert exc.value.code == 2  # reached the PDF branch with the proxied body


def test_auto_retry_hop_refusal_keeps_direct(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    page = b"<html><script>location = 'file:///etc/hosts'</script></html>"
    text = _retry(mod, monkeypatch, tmp_path, page)
    assert "# via_proxy: false" in text and "get access through your institution" in text


def test_relative_hop_is_joined_to_proxy_url(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    monkeypatch.setenv("RESEARCH_EZPROXY_PREFIX", "https://proxy.example.edu/login?url=")
    seen = []

    def fake(url, *a, **k):
        seen.append(url)
        if len(seen) == 1:
            return b"<html><script>location = '/connect?x=1'</script></html>", "text/html", 200, "https://proxy.example.edu/login?url=u"
        return BIG, "text/html", 200, url

    monkeypatch.setattr(mod, "http_get", fake)
    mod.fetch_via_proxy("https://example.org/z")
    assert seen[1] == "https://proxy.example.edu/connect?x=1"


def test_proxy_stub_word_thresholds() -> None:
    mod = _load()
    page = lambda n, extra="": b"<html><body>" + b"word " * n + extra.encode() + b"</body></html>"
    assert mod.proxy_stub(page(150))                       # short: stub
    assert mod.proxy_stub(page(500, " get access "))       # mid-length with paywall wording: stub
    assert not mod.proxy_stub(page(500))                   # mid-length, no paywall wording: content
    assert not mod.proxy_stub(page(1500, " get access "))  # long: content
