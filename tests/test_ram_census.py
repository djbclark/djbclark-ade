"""bin/ram-census (queue item 89): classification and totals from a fixture `ps` listing."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "bin" / "ram-census"

PS = """  PID  PPID    RSS COMMAND
  101     1  200000 claude --dangerously-skip-permissions
  102   101   30000 npm exec chrome-devtools-mcp@latest --autoConnect
  103   102   40000 node /x/node_modules/.bin/chrome-devtools-mcp --autoConnect
  104   101   20000 /opt/homebrew/bin/node /opt/homebrew/bin/graft mcp
  105   101   50000 /opt/homebrew/opt/node/bin/node /opt/homebrew/bin/basedpyright-langserver --stdio
  106   101   10000 /opt/homebrew/Cellar/marksman/2026-02-08/libexec/marksman server
  107   101   35000 node /opt/homebrew/bin/typescript-language-server --stdio
  108   107  300000 node /h/tsserver-ts5/node_modules/typescript/lib/tsserver.js --useInferredProjectPerProjectRoot
  109     1    5000 /Applications/ExtraBar.app/Contents/MacOS/extrabar-mcp
  111     1    9000 /usr/bin/vim notes.txt
"""


def _run(tmp: Path, *args: str) -> dict[str, Any]:
    f = tmp / "ps.txt"
    _ = f.write_text(PS)
    r = subprocess.run([sys.executable, str(TOOL), "--json", "--ps-file", str(f), *args], capture_output=True, text=True,
                       check=True)
    return cast(dict[str, Any], json.loads(r.stdout))


def test_classes_and_totals(tmp_path: Path) -> None:
    out = _run(tmp_path)
    assert out["claude"]["n"] == 1
    assert out["chrome-devtools"]["n"] == 2  # npm wrapper and node server
    assert out["graft-mcp"]["n"] == 1
    assert out["basedpyright"] == {"n": 1, "rss_mb": 48.8}
    assert out["marksman"]["n"] == 1 and out["extrabar"]["n"] == 1
    assert out["tsserver"]["n"] == 1 and out["ts-language-server"]["n"] == 1
    assert "vim" not in json.dumps(out)


def test_text_table_and_bad_file(tmp_path: Path) -> None:
    f = tmp_path / "ps.txt"
    _ = f.write_text(PS)
    r = subprocess.run([sys.executable, str(TOOL), "--ps-file", str(f)], capture_output=True, text=True, check=True)
    assert "basedpyright" in r.stdout and "n=  1" in r.stdout
    bad = subprocess.run([sys.executable, str(TOOL), "--ps-file", str(tmp_path / "missing")], capture_output=True, text=True)
    assert bad.returncode == 2



def test_unguarded_log_is_counted_per_server_within_the_window(tmp_path: Path) -> None:
    log = tmp_path / "unguarded.log"
    _ = log.write_text(
        "2020-01-01T00:00:00Z lsp-guard: lsp-root-guard unavailable; marksman starts UNGUARDED\n"  # older than the window
        "2999-01-01T00:00:00Z lsp-guard: lsp-root-guard unavailable; marksman starts UNGUARDED\n"
        "2999-01-01T00:00:05Z lsp-guard: lsp-root-guard off, broken or not on PATH; basedpyright-langserver starts UNGUARDED\n"
        "garbage line\n"
    )
    got = _run(tmp_path, "--roots", "--unguarded-log", str(log))["_unguarded_log"]  # default 7 days
    assert got["total"] == 2 and got["by_server"] == {"marksman": 1, "basedpyright-langserver": 1}
    assert got["newest"].startswith("2999-01-01T00:00:05Z")
    # a window longer than the calendar counts everything (and does not overflow)
    assert _run(tmp_path, "--roots", "--unguarded-log", str(log), "--days", "3650000")["_unguarded_log"]["total"] == 3
    old = tmp_path / "old.log"
    _ = old.write_text("2020-01-01T00:00:00Z lsp-guard: lsp-root-guard unavailable; marksman starts UNGUARDED\n")
    assert _run(tmp_path, "--roots", "--unguarded-log", str(old))["_unguarded_log"]["total"] == 0


def test_unguarded_log_text_and_absent_file_and_no_roots(tmp_path: Path) -> None:
    f = tmp_path / "ps.txt"
    _ = f.write_text(PS)
    log = tmp_path / "unguarded.log"
    _ = log.write_text("2999-01-01T00:00:00Z lsp-guard: lsp-root-guard unavailable; marksman starts UNGUARDED\n")
    base = [sys.executable, str(TOOL), "--ps-file", str(f), "--unguarded-log"]
    hit = subprocess.run([*base, str(log), "--roots"], capture_output=True, text=True, check=True)
    assert "UNGUARDED starts, last 7 days: 1 (marksman 1)" in hit.stdout
    none = subprocess.run([*base, str(tmp_path / "absent.log"), "--roots"], capture_output=True, text=True, check=True)
    assert "unguarded starts, last 7 days: none" in none.stdout
    plain = subprocess.run([*base, str(log)], capture_output=True, text=True, check=True)  # no --roots: the log is not read
    assert "UNGUARDED" not in plain.stdout and "unguarded starts" not in plain.stdout
    assert "_unguarded_log" not in _run(tmp_path)


UNAVAILABLE = "lsp-guard: lsp-root-guard unavailable; marksman starts UNGUARDED\n"
NONE = "none.json"


def _text(tmp: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    f = tmp / "ps.txt"
    _ = f.write_text(PS)
    e = {k: v for k, v in os.environ.items() if k != "ADE_LSP_ROOT_GUARD"} | (env or {})
    return subprocess.run([sys.executable, str(TOOL), "--ps-file", str(f), *args], capture_output=True, text=True, env=e,
                          timeout=30)


def test_an_impossible_date_a_bad_byte_and_a_control_char_do_not_break_the_census(tmp_path: Path) -> None:
    log = tmp_path / "unguarded.log"
    _ = log.write_bytes(
        b"2026-13-01T00:00:00Z " + UNAVAILABLE.encode()  # matches the pattern, is no date (strptime ValueError)
        + b"\xff\xfe not utf-8\n"
        + b"2999-01-01T00:00:00Z " + UNAVAILABLE.encode()
        + b"2999-02-01T00:00:00Z lsp-guard: \x1b[31mlsp-root-guard unavailable; marksman starts UNGUARDED\n"
    )
    args = ["--roots", "--unguarded-log", str(log), "--claude-settings", str(tmp_path / NONE)]
    r = _text(tmp_path, *args)
    assert r.returncode == 0, r.stderr
    assert "UNGUARDED starts, last 7 days: 2 (marksman 2)" in r.stdout
    assert "newest: 2999-02-01" in r.stdout and "\x1b" not in r.stdout
    got = json.loads(_text(tmp_path, "--json", *args).stdout)["_unguarded_log"]
    assert got["total"] == 2 and "\x1b" not in got["newest"]


def test_a_directory_or_fifo_as_the_log_counts_nothing_and_does_not_hang(tmp_path: Path) -> None:
    d = tmp_path / "adir"
    d.mkdir()
    r = _text(tmp_path, "--json", "--roots", "--unguarded-log", str(d), "--claude-settings", str(tmp_path / NONE))
    assert r.returncode == 0 and json.loads(r.stdout)["_unguarded_log"]["total"] == 0
    fifo = tmp_path / "fifo.log"
    os.mkfifo(fifo)  # opening it for reading would block forever
    r = _text(tmp_path, "--json", "--roots", "--unguarded-log", str(fifo), "--claude-settings", str(tmp_path / NONE))
    assert r.returncode == 0 and json.loads(r.stdout)["_unguarded_log"]["total"] == 0


def test_only_the_tail_of_a_huge_log_is_read(tmp_path: Path) -> None:
    log = tmp_path / "unguarded.log"
    filler = "2999-01-01T00:00:00Z " + UNAVAILABLE
    _ = log.write_text(filler * 20000 + "2999-03-03T03:03:03Z " + UNAVAILABLE)  # ~1.8 MiB, more than the 1 MiB tail
    got = json.loads(_text(tmp_path, "--json", "--roots", "--unguarded-log", str(log),
                           "--claude-settings", str(tmp_path / NONE)).stdout)["_unguarded_log"]
    assert 0 < got["total"] < 20001 and got["newest"].startswith("2999-03-03T03:03:03Z")


def test_a_negative_days_is_a_usage_error(tmp_path: Path) -> None:
    r = _text(tmp_path, "--roots", "--days", "-1")
    assert r.returncode == 2 and "--days" in r.stderr


def test_log_options_without_roots_are_flagged_on_stderr(tmp_path: Path) -> None:
    r = _text(tmp_path, "--days", "3")
    assert r.returncode == 0 and "only apply with --roots" in r.stderr


def test_roots_reports_the_off_switch_from_settings_and_from_the_environment(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    base = ["--roots", "--unguarded-log", str(tmp_path / "absent.log"), "--claude-settings", str(settings)]
    _ = settings.write_text(json.dumps({"env": {"ADE_LSP_ROOT_GUARD": "off"}}))
    r = _text(tmp_path, *base)
    assert "ADE_LSP_ROOT_GUARD=off is set in settings.json env" in r.stdout and "not off" not in r.stdout
    assert json.loads(_text(tmp_path, "--json", *base).stdout)["_unguarded_log"]["switch"] == {"settings": "off", "settings_status": "read", "env": None}
    _ = settings.write_text(json.dumps({"env": {"ADE_LSP_ROOT_GUARD": "on"}}))
    r = _text(tmp_path, *base, env={"ADE_LSP_ROOT_GUARD": "off"})
    assert "set in this process's environment" in r.stdout and "settings.json env" not in r.stdout
    _ = settings.write_text("{not json")  # unreadable settings never break the census, and are not "checked"
    r = _text(tmp_path, *base)
    assert r.returncode == 0 and "NOT checked" in r.stdout and "not off in settings.json" not in r.stdout
    r = _text(tmp_path, *base[:-1], str(tmp_path / "missing.json"))
    assert r.returncode == 0 and "ADE_LSP_ROOT_GUARD: not off" in r.stdout


def test_escapes_in_a_server_name_or_a_root_never_reach_the_terminal(tmp_path: Path) -> None:
    log = tmp_path / "unguarded.log"
    _ = log.write_bytes("2999-01-01T00:00:00Z lsp-guard: lsp-root-guard unavailable; mark\x1b]0;PWNED\x07\u009bman starts UNGUARDED\n".encode())
    args = ["--roots", "--unguarded-log", str(log), "--claude-settings", str(tmp_path / NONE)]
    r = _text(tmp_path, *args)
    assert r.returncode == 0 and "\x1b" not in r.stdout and "\x07" not in r.stdout and "\u009b" not in r.stdout
    assert "(mark]0;PWNEDman 1)" in r.stdout
    got = json.loads(_text(tmp_path, "--json", *args).stdout)["_unguarded_log"]
    assert list(got["by_server"]) == ["mark]0;PWNEDman"]


def _switch(tmp: Path, settings: Path) -> tuple[str, dict[str, Any]]:
    args = ["--roots", "--unguarded-log", str(tmp / "absent.log"), "--claude-settings", str(settings)]
    r = _text(tmp, *args)
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stderr
    return r.stdout, json.loads(_text(tmp, "--json", *args).stdout)["_unguarded_log"]["switch"]


def test_a_settings_file_that_could_not_be_read_is_never_reported_as_not_off(tmp_path: Path) -> None:
    """Each valid-JSON-or-not file below holds `ADE_LSP_ROOT_GUARD=off` where a parser that can read it would find it
    (node's JSON.parse reads the deep one): the census must say it did not check, never "not off in settings.json"."""
    key = '"env":{"ADE_LSP_ROOT_GUARD":"off"}'
    files = {
        "deep.json": ("{" + key + ',"x":' + "[" * 200000 + "]" * 200000 + "}", "nested too deeply"),
        "big.json": ("{" + key + ',"pad":"' + "x" * (1 << 20) + '"}', "over 1 MiB"),
        "digits.json": ("{" + key + ',"n":' + "9" * 5000 + "}", "not valid JSON or too large to parse"),
        "list.json": ("[{" + key + "}]", "not a JSON object"),
        "empty.json": ("", "not valid JSON or too large to parse"),
    }
    for name, (text, why) in files.items():
        f = tmp_path / name
        _ = f.write_text(text)
        out, sw = _switch(tmp_path, f)
        assert sw["settings_status"] == f"unreadable: {why}", (name, sw)
        assert "NOT checked" in out and why in out and "not off in settings.json" not in out, (name, out)
    fifo = tmp_path / "settings.fifo"
    os.mkfifo(fifo)  # a blocking read would hang
    d = tmp_path / "adir"
    d.mkdir()
    for special in (fifo, d, Path("/dev/zero")):
        out, sw = _switch(tmp_path, special)
        assert sw["settings_status"] == "unreadable: not a regular file", (special, sw)
        assert "NOT checked" in out and "not off in settings.json" not in out
    out, sw = _switch(tmp_path, tmp_path / "missing.json")  # no file: nothing set there, so "not off" is true
    assert sw["settings_status"] == "missing" and "not off in settings.json env" in out
    ok = tmp_path / "ok.json"
    _ = ok.write_text("{" + key + "}")
    out, sw = _switch(tmp_path, ok)
    assert sw["settings_status"] == "read" and sw["settings"] == "off" and "off is set in settings.json env" in out


def test_a_settings_file_of_exactly_1_mib_is_read_whole_and_one_byte_more_is_not(tmp_path: Path) -> None:
    m = _module()
    head = '{"env":{"ADE_LSP_ROOT_GUARD":"off"},"pad":"'
    tail = '"}'
    exact = tmp_path / "exact.json"
    _ = exact.write_text(head + "x" * ((1 << 20) - len(head) - len(tail)) + tail)
    assert exact.stat().st_size == 1 << 20
    assert m._read_bounded(str(exact), tail=False)[1] == ""  # `>=` instead of `>` would call a fully read file "over 1 MiB"
    sw = m.guard_switch(str(exact))
    assert sw["settings_status"] == "read" and sw["settings"] == "off"
    over = tmp_path / "over.json"
    _ = over.write_text(head + "x" * ((1 << 20) - len(head) - len(tail) + 1) + tail)
    assert over.stat().st_size == (1 << 20) + 1
    assert m._read_bounded(str(over), tail=False)[1] == "over 1 MiB"
    assert m.guard_switch(str(over))["settings_status"] == "unreadable: over 1 MiB"


def test_off_in_the_environment_and_an_unreadable_settings_file_says_settings_was_not_checked(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    _ = settings.write_text("{not json")
    base = ["--roots", "--unguarded-log", str(tmp_path / "absent.log"), "--claude-settings", str(settings)]
    r = _text(tmp_path, *base, env={"ADE_LSP_ROOT_GUARD": "off"})
    assert r.returncode == 0 and "set in this process's environment" in r.stdout
    assert "settings.json unreadable: not valid JSON or too large to parse, so it was not checked" in r.stdout


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode 000 file")
def test_a_permission_denied_settings_file_gives_a_status_without_a_doubled_word(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    _ = settings.write_text(json.dumps({"env": {"ADE_LSP_ROOT_GUARD": "off"}}))
    settings.chmod(0)
    try:
        out, sw = _switch(tmp_path, settings)
    finally:
        settings.chmod(0o600)
    assert sw["settings_status"] == "unreadable: cannot be opened or read" and sw["settings"] is None
    assert "unreadable: unreadable" not in out and "NOT checked" in out and "not off in settings.json" not in out


def _module() -> Any:
    loader = importlib.machinery.SourceFileLoader("ram_census_under_test", str(TOOL))
    spec = importlib.util.spec_from_loader("ram_census_under_test", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_the_reader_caps_what_it_reads_and_refuses_devices(tmp_path: Path) -> None:
    m = _module()
    big = tmp_path / "big.txt"
    _ = big.write_bytes(b"a\n" * (1 << 20))  # 2 MiB
    data, problem = m._read_bounded(str(big), tail=False)
    assert len(data) == 1 << 20 and problem == "over 1 MiB"  # an uncapped read() returns all 2 MiB
    data, problem = m._read_bounded(str(big), tail=True)
    assert 0 < len(data) <= 1 << 20 and problem == ""
    for tail in (False, True):  # /dev/zero is seekable with size 0: only the type check refuses it
        assert m._read_bounded("/dev/zero", tail=tail) == (b"", "not a regular file")
    assert m._read_bounded(str(tmp_path / "none"), tail=False) == (b"", "missing")


def test_a_root_with_an_escape_in_it_is_printed_clean(tmp_path: Path, capsys: Any, monkeypatch: Any) -> None:
    m = _module()
    root = "project:/x\x1b]0;PWN\x07\u009by"
    monkeypatch.setattr(m, "census", lambda *a, **k: {"basedpyright": {"n": 1, "rss_mb": 1.0, "roots": {root: 1}}})
    f = tmp_path / "ps.txt"
    _ = f.write_text(PS)
    rc = m.main(["--ps-file", str(f), "--roots", "--unguarded-log", str(tmp_path / "absent.log"),
                 "--claude-settings", str(tmp_path / NONE)])
    out = capsys.readouterr().out
    assert rc == 0 and "1 x project:/x]0;PWNy" in out
    assert "\x1b" not in out and "\x07" not in out and "\u009b" not in out


def test_a_cut_that_lands_on_a_line_start_keeps_that_line(tmp_path: Path) -> None:
    log = tmp_path / "unguarded.log"
    pad = "x" * (128 - len("2999-01-01T00:00:00Z lsp-guard: ; marksman starts UNGUARDED\n"))
    line = f"2999-01-01T00:00:00Z lsp-guard: {pad}; marksman starts UNGUARDED\n"
    assert len(line) == 128 and (1 << 20) % 128 == 0
    _ = log.write_text(line * 8193)  # exactly one line more than the 1 MiB tail: the tail is 8192 whole lines
    got = json.loads(_text(tmp_path, "--json", "--roots", "--unguarded-log", str(log),
                           "--claude-settings", str(tmp_path / NONE)).stdout)["_unguarded_log"]
    assert got["total"] == 8192


def test_the_not_off_line_says_what_was_checked(tmp_path: Path) -> None:
    r = _text(tmp_path, "--roots", "--unguarded-log", str(tmp_path / "absent.log"), "--claude-settings", str(tmp_path / NONE))
    assert "other settings layers and running sessions are not checked" in r.stdout


DAEMONS_NORMAL_PS = """  PID  PPID     RSS COMMAND
  101     1   65536 /System/Library/CoreServices/loginwindow.app/Contents/MacOS/loginwindow console
  102     1   40960 /System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/Metadata.framework/Versions/A/Support/corespotlightd
  103     1   20480 /System/Library/CoreServices/launchservicesd
  104     1  153600 /System/Library/PrivateFrameworks/SkyLight.framework/Resources/WindowServer -daemon
  105     1   30720 /System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/Metadata.framework/Versions/A/Support/mds_stores
  106     1   10240 /System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/Metadata.framework/Versions/A/Support/mds
  107     1    2048 /usr/sbin/distnoted daemon
  108     1    1024 /usr/sbin/distnoted agent
  109     1    5120 /usr/sbin/cfprefsd daemon
  201     1    1024 /opt/homebrew/bin/rg loginwindow /tmp/foo
  202     1    2048 /usr/bin/vim mds.txt
  203     1    4096 /usr/local/bin/mdsync --watch
"""


def _run_ps(tmp: Path, ps_text: str, *args: str) -> subprocess.CompletedProcess[str]:
    f = tmp / "ps_daemons.txt"
    _ = f.write_text(ps_text)
    return subprocess.run([sys.executable, str(TOOL), "--ps-file", str(f), *args], capture_output=True, text=True, timeout=30)


def test_daemons_normal_below_thresholds_and_exact_basename_matching(tmp_path: Path) -> None:
    import time as _time

    boot = str(int(_time.time() - 3 * 86400))
    plain = _run_ps(tmp_path, DAEMONS_NORMAL_PS, "--json")
    assert plain.returncode == 0
    assert "_daemons" not in json.loads(plain.stdout)

    r = _run_ps(tmp_path, DAEMONS_NORMAL_PS, "--daemons", "--boottime-epoch", boot, "--json")
    assert r.returncode == 0, r.stderr
    dm = json.loads(r.stdout)["_daemons"]
    assert set(dm["daemons"]) == {
        "loginwindow", "corespotlightd", "launchservicesd", "WindowServer",
        "mds_stores", "mds", "distnoted", "cfprefsd",
    }
    assert dm["daemons"]["distnoted"] == {"n": 2, "rss_mb": 3.0}
    assert dm["daemons"]["mds"] == {"n": 1, "rss_mb": 10.0}
    assert dm["daemons"]["mds_stores"] == {"n": 1, "rss_mb": 30.0}
    assert dm["reboot_due"] is False
    assert dm["reboot_reasons"] == []
    assert 2.9 <= dm["uptime_days"] <= 3.1

    txt = _run_ps(tmp_path, DAEMONS_NORMAL_PS, "--daemons", "--boottime-epoch", boot)
    assert txt.returncode == 0
    assert "macOS system daemons (report-only" in txt.stdout
    assert "reboot due: no (advisory)" in txt.stdout


def test_daemons_single_daemon_and_total_bloat_triggers_reboot_due(tmp_path: Path) -> None:
    import time as _time

    bloated = """  PID  PPID     RSS COMMAND
  101     1 2988441 /System/Library/CoreServices/loginwindow.app/Contents/MacOS/loginwindow console
  102     1 2621440 /System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/Metadata.framework/Versions/A/Support/corespotlightd
  103     1  849920 /System/Library/CoreServices/launchservicesd
"""
    boot = str(int(_time.time() - 11.5 * 86400))
    r = _run_ps(tmp_path, bloated, "--daemons", "--boottime-epoch", boot, "--json")
    assert r.returncode == 0, r.stderr
    dm = json.loads(r.stdout)["_daemons"]
    assert dm["reboot_due"] is True
    joined = " | ".join(dm["reboot_reasons"])
    assert "total tracked daemons" in joined
    assert "loginwindow" in joined
    assert "corespotlightd" in joined
    assert "launchservicesd" not in joined

    txt = _run_ps(tmp_path, bloated, "--daemons", "--boottime-epoch", boot)
    assert txt.returncode == 0 and "REBOOT DUE (advisory):" in txt.stdout


def test_daemons_uptime_plus_elevated_memory_threshold(tmp_path: Path) -> None:
    import time as _time

    # Each daemon < 2.0 GB and total ~2.7 GB (< 4.0 GB total threshold, >= 2.5 GB elevated threshold)
    elevated = """  PID  PPID     RSS COMMAND
  101     1 1536000 /System/Library/CoreServices/loginwindow.app/Contents/MacOS/loginwindow console
  102     1 1228800 /System/Library/CoreServices/launchservicesd
"""
    short_up = str(int(_time.time() - 5 * 86400))
    long_up = str(int(_time.time() - 15 * 86400))
    r_short = json.loads(_run_ps(tmp_path, elevated, "--daemons", "--boottime-epoch", short_up, "--json").stdout)["_daemons"]
    assert r_short["reboot_due"] is False

    r_long = json.loads(_run_ps(tmp_path, elevated, "--daemons", "--boottime-epoch", long_up, "--json").stdout)["_daemons"]
    assert r_long["reboot_due"] is True
    assert any("uptime" in reason and "elevated daemon memory" in reason for reason in r_long["reboot_reasons"])

    # Long uptime alone with low daemon memory must not trigger reboot_due
    r_clean = json.loads(_run_ps(tmp_path, DAEMONS_NORMAL_PS, "--daemons", "--boottime-epoch", long_up, "--json").stdout)["_daemons"]
    assert r_clean["reboot_due"] is False


def test_daemons_boottime_validation_sysctl_parse_and_footprint_linux_safe(tmp_path: Path, monkeypatch: Any) -> None:
    m = _module()
    assert m.parse_boottime_sysctl("{ sec = 1794269448, usec = 747501 } Mon Nov  9 19:10:48 2026") == 1794269448.0
    assert m.parse_boottime_sysctl("not a boottime") is None

    bad = _run_ps(tmp_path, DAEMONS_NORMAL_PS, "--daemons", "--boottime-epoch", "-5")
    assert bad.returncode == 2 and "--boottime-epoch" in bad.stderr
    warn = _run_ps(tmp_path, DAEMONS_NORMAL_PS, "--boottime-epoch", "1700000000")
    assert warn.returncode == 0 and "--boottime-epoch only applies with --daemons" in warn.stderr

    # With --footprint: compressed footprint triggers reboot_due even when RSS is small
    rows = m.parse_ps("  PID PPID RSS COMMAND\n  101 1 102400 /System/Library/CoreServices/loginwindow.app/Contents/MacOS/loginwindow console\n")
    monkeypatch.setattr(m, "footprint_mb", lambda pid: 2400.0 if pid == 101 else None)
    dm_fp = m.daemon_census(rows, want_fp=True, boottime_epoch=1_000_000.0, now_epoch=1_086_400.0)
    assert dm_fp["reboot_due"] is True
    assert dm_fp["total_footprint_mb"] == 2400.0
    assert dm_fp["daemons"]["loginwindow"]["footprint_mb"] == 2400.0

    # Linux-safe fallback when `footprint` is absent (footprint_mb returns None)
    monkeypatch.setattr(m, "footprint_mb", lambda pid: None)
    dm_nofp = m.daemon_census(rows, want_fp=True, boottime_epoch=1_000_000.0, now_epoch=1_086_400.0)
    assert dm_nofp["reboot_due"] is False
    assert dm_nofp["effective_total_mb"] == 100.0
