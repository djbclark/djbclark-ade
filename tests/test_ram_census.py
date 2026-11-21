"""bin/ram-census (queue item 89): classification and totals from a fixture `ps` listing."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

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
