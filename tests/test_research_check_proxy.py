"""EZproxy refusal page must not be saved as a proxied source (research_check.py fetch)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "research" / "scripts" / "research_check.py"
REFUSED = b"<html><body>Oops! It looks like you have attempted to view a page that has not been configured for access.</body></html>"
BIG = (b"<html><body>" + b"word " * 400 + b"</body></html>")


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


def test_forced_proxy_refusal_saves_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    monkeypatch.setenv("RESEARCH_PROXY_URL", "https://proxy.example.edu/login?url=")
    monkeypatch.setattr(mod, "http_get", lambda *a, **k: (REFUSED, "text/html", 200, "https://proxy.example.edu/login?url=x"))
    with pytest.raises(SystemExit) as exc:
        mod.cmd_fetch("s1", "https://arxiv.org/abs/1", tmp_path, via_proxy=True)
    assert exc.value.code == 2
    assert not (tmp_path / "sources" / "s1.txt").exists()


def test_auto_retry_refusal_keeps_direct_fetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    monkeypatch.setenv("RESEARCH_PROXY_URL", "https://proxy.example.edu/login?url=")
    short = b"<html><body>buy this article</body></html>"

    def fake(url, *a, **k):
        if url.startswith("https://proxy.example.edu"):
            return REFUSED, "text/html", 200, url
        return short, "text/html", 200, url

    monkeypatch.setattr(mod, "http_get", fake)
    assert mod.cmd_fetch("s2", "https://example.org/p", tmp_path) == 0
    text = (tmp_path / "sources" / "s2.txt").read_text()
    assert "# via_proxy: false" in text
