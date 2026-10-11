"""Tests for tools/acp-run/acp-run's ACP_RUN_AGY_SERVER override of agy's server command.

Unset keeps Google's agy_acp_server 1.3.0 (the 2026-10-10 comparison's winner); set, it replaces
that one path so a newer server or a wrapper can be tried without an edit. acp-run imports the ACP
SDK, so the script is loaded in a `uv run --with` subprocess.
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("ACP_RUN_SCRIPT", str(ROOT / "tools" / "acp-run" / "acp-run")))

PROBE = textwrap.dedent("""\
    import importlib.machinery, importlib.util, json, sys
    loader = importlib.machinery.SourceFileLoader("acp_run", sys.argv[1])
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("acp_run", loader))
    loader.exec_module(mod)
    print(json.dumps({"agy": mod.AGENTS["agy"][0], "client": mod.CLIENT_NAME.get("agy"),
                      "yolo": mod.YOLO_SET.get("agy")}))
    """)


def probe(server: str | None) -> dict[str, object]:
    env = {k: v for k, v in os.environ.items() if k != "ACP_RUN_AGY_SERVER"}
    if server is not None:
        env["ACP_RUN_AGY_SERVER"] = server
    r = subprocess.run(
        ["uv", "run", "--quiet", "--with", "agent-client-protocol>=0.9,<1.0", "python", "-I", "-c", PROBE,
         str(SCRIPT)], env=env, check=False, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return json.loads(r.stdout)


class TestAgyServerOverride(unittest.TestCase):
    def test_default_is_google_server_with_zed_client_name_and_yolo(self):
        res = probe(None)
        self.assertEqual(res["agy"], [os.path.expanduser("~/.local/share/agy-acp-server/1.3.0/agy_acp_server.par")])
        self.assertEqual(res["client"], "zed")
        self.assertEqual(res["yolo"], {"mode": "yolo"})

    def test_env_replaces_only_the_command(self):
        res = probe("~/bin/other-agy-server")
        self.assertEqual(res["agy"], [os.path.expanduser("~/bin/other-agy-server")])
        self.assertEqual(res["client"], "zed")

    def test_empty_env_keeps_default(self):
        res = probe("")
        self.assertTrue(str(res["agy"][0]).endswith("/1.3.0/agy_acp_server.par"))  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
