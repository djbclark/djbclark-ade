#!/usr/bin/env python3
"""Every extensionless bin/ tool with a shebang is tracked executable (100755) (2026-10-23): PR 32 replaced
bin/claude-settings-env with a 100644 copy, its tests ran it through sys.executable and passed, and four review
rounds missed it; Codex caught it. Modules with an extension (bin/skillopt_sources.py) are imported, not run."""
from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class BinModesTest(unittest.TestCase):
    def test_extensionless_bin_tools_are_tracked_executable(self) -> None:
        if shutil.which("git") is None or not (ROOT / ".git").exists():
            self.skipTest("not a git checkout")
        out = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-s", "--", "bin"],
            capture_output=True, text=True, check=True,
        ).stdout
        bad: list[str] = []
        for line in out.splitlines():
            meta, path = line.split("\t", 1)
            mode = meta.split()[0]
            p = ROOT / path
            if mode == "120000" or p.suffix or "/" in path[len("bin/"):]:
                continue
            if p.is_file() and p.read_bytes()[:2] == b"#!" and mode != "100755":
                bad.append(f"{path} is {mode}")
        self.assertEqual(bad, [], "git update-index --chmod=+x these")


if __name__ == "__main__":
    unittest.main()
