"""Unit tests for bin/web-digest: passage ranking, caps, failure and pause output (fake web-get)."""
import importlib.machinery
import importlib.util
import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "web-digest"
loader = importlib.machinery.SourceFileLoader("web_digest", str(SCRIPT))
spec = importlib.util.spec_from_loader("web_digest", loader)
wd = importlib.util.module_from_spec(spec)
loader.exec_module(wd)

SEARCH = (
    "Title: Alpha\nURL: https://a.example/x\nSnippet: Alpha says the limit is 262,144 tokens.\n\n---\n\n"
    "Title: Beta\nURL: https://b.example/y\nSnippet: Unrelated cooking tips.\n"
)
PAGE_A = "# Alpha\n\n" + "Intro paragraph about nothing in particular, long enough to be kept as text. " * 3 + (
    "\n\nThe context window is 262,144 tokens natively and the model activates 3B parameters per token."
    "\n\n[a](http://x.example/1) [b](http://x.example/2) [c](http://x.example/3) [d](http://x.example/4)"
)


def fake_web_get(tmp: Path, search_rc=0, fetch_ok=True) -> str:
    p = tmp / "web-get"
    p.write_text(textwrap.dedent(f"""\
        #!{sys.executable}
        import json, sys
        a = sys.argv[1:]
        if a[0] == "search":
            if {search_rc}:
                print(json.dumps({{"ok": False, "attempts": [{{"provider": "exa-api", "error": "boom"}}]}})); sys.exit(5)
            print(json.dumps({{"ok": True, "content": {SEARCH!r}}}))
        else:
            if {fetch_ok!r} and "a.example" in a[1]:
                print(json.dumps({{"ok": True, "content": {PAGE_A!r}}}))
            else:
                print(json.dumps({{"ok": False, "attempts": [{{"provider": "parallel", "error": "HTTP 403"}}]}})); sys.exit(5)
        """))
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def run(tmp, *args, **kw):
    env = dict(os.environ, WEB_DIGEST_WEB_GET=fake_web_get(tmp, **kw))
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True, env=env)


def test_tokens_drop_stopwords_and_stem():
    assert wd.tokens("How does the context windows work?") == ["context", "window", "work"]


def test_parse_search():
    r = wd.parse_search(SEARCH)
    assert [x["url"] for x in r] == ["https://a.example/x", "https://b.example/y"]
    assert r[0]["snippet"].startswith("Alpha says")


def test_passages_skip_link_lists_and_split_long():
    ps = wd.passages(PAGE_A + "\n\n" + ("word " * 400))
    assert not any("http" in p for p in ps)
    assert all(len(p) <= wd.PASSAGE_MAX + 5 for p in ps)


def test_rank_prefers_matching_passage():
    docs = [(1, "cooking pasta with garlic and oil", 1.0), (2, "the context window is 262,144 tokens", 1.0)]
    assert wd.rank("context window size", docs)[0][1] == 2


def test_digest_end_to_end(tmp_path):
    p = run(tmp_path, "context window and active parameters")
    assert p.returncode == 0, p.stderr
    assert "SOURCES:" in p.stdout and "262,144" in p.stdout
    assert "NOT FETCHED: https://b.example/y" in p.stdout and "--thorough --url" in p.stdout


def test_output_cap(tmp_path):
    p = run(tmp_path, "context window", "--max-tokens", "100")
    assert len(p.stdout.split("PASSAGES")[1]) < 100 * 4 + 400


def test_search_failure_is_pause_signal(tmp_path):
    p = run(tmp_path, "anything", search_rc=5)
    assert p.returncode == 5
    assert "WEB-DIGEST FAILED" in p.stdout and "Do NOT answer from memory" in p.stdout


def test_url_mode_skips_search(tmp_path):
    p = run(tmp_path, "context window", "--url", "https://a.example/x", search_rc=5)
    assert p.returncode == 0 and "262,144" in p.stdout


def test_all_pages_fail_is_pause_signal(tmp_path):
    p = run(tmp_path, "context window", "--url", "https://b.example/y")
    assert p.returncode == 5 and "HTTP 403" in p.stdout
