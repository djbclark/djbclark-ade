"""bin/lsp-root-guard (queue item 89): a fixture LSP server echoes the initialize params it received."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "bin" / "lsp-root-guard"

FAKE = r'''
import json, sys
def rd():
    n = -1
    while True:
        l = sys.stdin.buffer.readline()
        if not l: return None
        if l in (b"\r\n", b"\n"): break
        if l.lower().startswith(b"content-length"): n = int(l.split(b":")[1])
    return json.loads(sys.stdin.buffer.read(n))
def wr(o):
    b = json.dumps(o).encode()
    sys.stdout.buffer.write(b"Content-Length: %d\r\n\r\n" % len(b) + b); sys.stdout.buffer.flush()
while True:
    m = rd()
    if m is None: break
    if m.get("method") == "initialize":
        wr({"jsonrpc": "2.0", "id": m["id"], "result": {"echo": m["params"]}})
        wr({"jsonrpc": "2.0", "id": 900, "method": "workspace/workspaceFolders"})
    elif m.get("method") == "workspace/didChangeWorkspaceFolders":
        wr({"jsonrpc": "2.0", "method": "seen/didChange"})
    elif "id" in m and "method" not in m:
        wr({"jsonrpc": "2.0", "method": "seen/response", "params": m})
    elif m.get("method") == "exit":
        break
'''


def _frame(obj: dict[str, Any]) -> bytes:
    b = json.dumps(obj).encode()
    return b"Content-Length: " + str(len(b)).encode() + b"\r\n\r\n" + b


def _parse(data: bytes) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    while data:
        head, _, rest = data.partition(b"\r\n\r\n")
        n = int(head.split(b":")[1])
        out.append(json.loads(rest[:n]))
        data = rest[n:]
    return out


def _session(tmp: Path, root: Path, extra: list[str] | None = None, env: dict[str, str] | None = None,
             folders: list[Path] | None = None) -> list[dict[str, Any]]:
    fake = tmp / "fake_lsp.py"
    _ = fake.write_text(FAKE)
    params: dict[str, Any] = {"rootUri": root.as_uri(), "rootPath": str(root), "capabilities": {}}
    params["workspaceFolders"] = [{"uri": f.as_uri(), "name": f.name} for f in (folders or [root])]
    e = dict(os.environ, HOME=str(tmp / "home"), **(env or {}))
    proc = subprocess.Popen([sys.executable, str(TOOL), *(extra or []), "--", sys.executable, str(fake)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=e)
    assert proc.stdin is not None and proc.stdout is not None
    got: list[dict[str, Any]] = []

    def read_until(pred: Any) -> None:
        while True:
            line = proc.stdout.readline()  # type: ignore[union-attr]
            n = int(line.split(b":")[1])
            _ = proc.stdout.readline()  # type: ignore[union-attr]
            m = json.loads(proc.stdout.read(n))  # type: ignore[union-attr]
            got.append(m)
            if pred(m):
                return

    proc.stdin.write(_frame({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": params}))
    fl = [{"uri": f.as_uri(), "name": f.name} for f in (folders or [root])]
    proc.stdin.write(_frame({"jsonrpc": "2.0", "method": "workspace/didChangeWorkspaceFolders",
                             "params": {"event": {"added": fl, "removed": []}}}))
    proc.stdin.flush()
    read_until(lambda m: m.get("method") == "workspace/workspaceFolders")  # the client answers only after the request
    proc.stdin.write(_frame({"jsonrpc": "2.0", "id": 900, "result": fl}))
    proc.stdin.write(_frame({"jsonrpc": "2.0", "method": "exit"}))
    proc.stdin.close()
    got.extend(_parse(proc.stdout.read()))
    assert proc.wait(timeout=30) == 0
    return got


def _echo(out: list[dict[str, Any]]) -> dict[str, Any]:
    return cast(dict[str, Any], out[0]["result"]["echo"])


def _mk(tmp: Path) -> Path:
    (tmp / "home" / "src").mkdir(parents=True)
    return tmp / "home"


def test_container_root_is_stripped(tmp_path: Path) -> None:
    home = _mk(tmp_path)
    out = _session(tmp_path, home / "src", extra=["--container", str(home / "src")])
    echo = _echo(out)
    assert echo["rootUri"] is None and echo["rootPath"] is None and echo["workspaceFolders"] is None
    assert echo["capabilities"] == {}
    methods = [m.get("method") for m in out]
    assert "seen/didChange" not in methods  # folder-change notification dropped
    resp = next(m for m in out if m.get("method") == "seen/response")
    assert resp["params"]["result"] is None  # server asked for folders: it hears "none"


def test_project_root_passes_through(tmp_path: Path) -> None:
    home = _mk(tmp_path)
    proj = home / "src" / "proj"
    (proj / ".git").mkdir(parents=True)
    out = _session(tmp_path, proj, extra=["--container", str(home / "src")])
    echo = _echo(out)
    assert echo["rootUri"] == proj.as_uri() and echo["rootPath"] == str(proj)
    assert any(m.get("method") == "seen/didChange" for m in out)
    resp = next(m for m in out if m.get("method") == "seen/response")
    assert resp["params"]["result"][0]["uri"] == proj.as_uri()


def test_heuristic_container_and_no_heuristic(tmp_path: Path) -> None:
    home = _mk(tmp_path)
    many = home / "work"
    for n in "abc":
        (many / n / ".git").mkdir(parents=True)
    assert _echo(_session(tmp_path, many))["rootUri"] is None
    assert _echo(_session(tmp_path, many, extra=["--no-heuristic"]))["rootUri"] == many.as_uri()
    _ = (many / "pyproject.toml").write_text("")  # a project, even with 3 repos below
    assert _echo(_session(tmp_path, many))["rootUri"] == many.as_uri()


def test_env_container_and_multi_root_keeps_project(tmp_path: Path) -> None:
    home = _mk(tmp_path)
    proj = home / "src" / "proj"
    (proj / ".git").mkdir(parents=True)
    out = _session(tmp_path, home / "src", env={"ADE_LSP_CONTAINER_ROOTS": str(home / "src")},
                   folders=[home / "src", proj])
    echo = _echo(out)
    assert [f["uri"] for f in echo["workspaceFolders"]] == [proj.as_uri()]
    assert echo["rootUri"] == proj.as_uri()
    resp = next(m for m in out if m.get("method") == "seen/response")
    assert [f["uri"] for f in resp["params"]["result"]] == [proj.as_uri()]  # filtered, not nulled
    assert any(m.get("method") == "seen/didChange" for m in out)  # the project folder change still reaches the server


def test_check_and_errors(tmp_path: Path) -> None:
    home = _mk(tmp_path)
    env = dict(os.environ, HOME=str(home))
    r = subprocess.run([sys.executable, str(TOOL), "--check", str(home)], capture_output=True, text=True, env=env)
    assert r.stdout.strip() == "container" and r.returncode == 0
    (home / "p" / ".git").mkdir(parents=True)
    r = subprocess.run([sys.executable, str(TOOL), "--check", (home / "p").as_uri()], capture_output=True, text=True, env=env)
    assert r.stdout.strip() == "project"
    r = subprocess.run([sys.executable, str(TOOL), "--", "no-such-lsp-binary-xyz"], capture_output=True, input=b"", env=env)
    assert r.returncode == 127
    assert subprocess.run([sys.executable, str(TOOL)], capture_output=True).returncode == 2


def test_uri_forms(tmp_path: Path) -> None:
    home = _mk(tmp_path)
    env = dict(os.environ, HOME=str(home))
    odd = home / "a#b"
    (odd / ".git").mkdir(parents=True)
    for arg, want in ((odd.as_uri().replace("%23", "#"), "project"), (f"file:{home}", "container"),
                      (f"file://localhost{home}", "container"), (f"file://otherhost{home}", None)):
        r = subprocess.run([sys.executable, str(TOOL), "--check", arg], capture_output=True, text=True, env=env)
        assert (r.stdout.strip() or None) == want, (arg, r.stdout, r.stderr)


def test_server_exit_ends_guard_and_sigterm_kills_child(tmp_path: Path) -> None:
    import signal
    import time
    env = dict(os.environ, HOME=str(tmp_path))
    quick = tmp_path / "quick.py"
    _ = quick.write_text("import sys\nsys.stdin.buffer.readline()\nsys.exit(7)\n")
    p = subprocess.Popen([sys.executable, str(TOOL), "--", sys.executable, str(quick)], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, env=env)
    assert p.stdin is not None
    _ = p.stdin.write(b"Content-Length: 2\r\n\r\n{}")
    p.stdin.flush()
    assert p.wait(timeout=15) == 7  # the client never closed stdin: the guard still follows the server out
    pidfile = tmp_path / "pid"
    sleeper = tmp_path / "sleeper.py"
    _ = sleeper.write_text(f"import os, time\nopen({str(pidfile)!r}, 'w').write(str(os.getpid()))\ntime.sleep(300)\n")
    p = subprocess.Popen([sys.executable, str(TOOL), "--", sys.executable, str(sleeper)], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, env=env)
    for _i in range(100):
        if pidfile.exists() and pidfile.read_text():
            break
        time.sleep(0.1)
    child = int(pidfile.read_text())
    p.send_signal(signal.SIGTERM)
    assert p.wait(timeout=15) == 128 + signal.SIGTERM
    time.sleep(0.5)
    try:
        os.kill(child, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    assert not alive
