#!/usr/bin/env python3
"""Every tracked file with a shebang outside tests/ is executable (100755) (2026-10-23).

PR 32 replaced bin/claude-settings-env with a 100644 copy. Its tests ran it through sys.executable and passed, four
review rounds missed it, and Codex caught it. The same check found claude/hooks/context_size_nudge.py at 100644
since 836b306 (2026-10-19): hook-deadline execs it directly, so it exited 127 and no context-size nudge ran for four
days (fixed in d618809). Making a file executable never breaks a caller that runs it through an interpreter, so the
rule has no exemptions."""
from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ShebangModesTest(unittest.TestCase):
    def test_tracked_files_with_a_shebang_are_executable(self) -> None:
        if shutil.which("git") is None or not (ROOT / ".git").exists():
            self.skipTest("not a git checkout")
        out = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-s", "-z"],
            capture_output=True, check=True,
        ).stdout
        bad: list[str] = []
        for rec in out.split(b"\0"):
            if not rec:
                continue
            meta, raw = rec.split(b"\t", 1)
            mode = meta.split()[0].decode()
            path = raw.decode("utf-8", "surrogateescape")
            if mode != "100644" or path.startswith("tests/") or "/tests/" in path:
                continue
            p = ROOT / path
            if p.is_file() and not p.is_symlink():
                with p.open("rb") as f:
                    if f.read(2) == b"#!":
                        bad.append(path)
        self.assertEqual(bad, [], "git update-index --chmod=+x these")


if __name__ == "__main__":
    _ = unittest.main()
