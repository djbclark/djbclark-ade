"""bin/mcp-usage (proposed, unwired; docs/mcp-on-demand.md): fixture transcripts only."""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "bin" / "mcp-usage"


def _now(delta_days: float = 0) -> str:
    t = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=delta_days)
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _claude_line(name: str, call_id: str, ts: str, session: str = "s1") -> str:
    return json.dumps({
        "type": "assistant", "timestamp": ts, "sessionId": session,
        "message": {"content": [{"type": "tool_use", "id": call_id, "name": name, "input": {"secret": "x"}}]},
    })


def _run(*args: str) -> dict[str, Any]:
    r = subprocess.run([sys.executable, str(TOOL), "--json", *args], capture_output=True, text=True, check=True)
    return cast(dict[str, Any], json.loads(r.stdout))


def test_counts_dedupes_and_windows(tmp_path: Path) -> None:
    claude = tmp_path / "claude" / "proj"
    claude.mkdir(parents=True)
    _ = (claude / "s1.jsonl").write_text("\n".join([
        _claude_line("mcp__firecrawl__firecrawl_search", "a", _now()),
        _claude_line("mcp__firecrawl__firecrawl_search", "a", _now()),  # resumed copy: same id
        _claude_line("mcp__basic-memory__bm_read", "b", _now()),
        _claude_line("Bash", "c", _now()),  # not MCP
        _claude_line("mcp__graft__graft_find_code", "d", _now(40)),  # outside window
        "not json",
    ]) + "\n")
    codex = tmp_path / "codex" / "2026"
    codex.mkdir(parents=True)
    _ = (codex / "rollout.jsonl").write_text(json.dumps({
        "timestamp": _now(), "payload": {"item": {"type": "McpToolCall", "id": "x1", "server": "bezalel", "tool": "health__check"}},
    }) + "\n")
    out = _run("--claude-root", str(tmp_path / "claude"), "--codex-root", str(tmp_path / "codex"))
    sources = cast(list[dict[str, Any]], out["sources"])
    by: dict[str, dict[str, int]] = {
        str(src["source"]): {str(row["server"]): int(row["calls"]) for row in cast(list[dict[str, Any]], src["servers"])}
        for src in sources
    }
    assert by["claude"] == {"firecrawl": 1, "basic-memory": 1}
    assert by["codex"] == {"bezalel": 1}
    assert "secret" not in json.dumps(out)


def test_missing_root_exits_2(tmp_path: Path) -> None:
    r = subprocess.run([sys.executable, str(TOOL), "--source", "claude", "--claude-root", str(tmp_path / "nope")],
                       capture_output=True, text=True)
    assert r.returncode == 2
