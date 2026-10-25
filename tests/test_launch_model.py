#!/usr/bin/env python3
"""launch.py checks `--model` against acp-run before it opens a tab (2026-10-25).

`launch.py start --model claude-sonnet-5-5` opened a herdr tab and only then died, because
`acp-run claude` takes `sonnet` or `claude-sonnet-5` but not the API-style `claude-sonnet-5-5`.
launch.py now maps that spelling and probes `acp-run claude --info --model M`; a refusal exits 2
before any claim, launch dir, pane or tab exists.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, override

ROOT = Path(__file__).resolve().parent.parent
LAUNCH = ROOT / "skills" / "session-finder" / "launch.py"

# a stand-in acp-run that knows acp-run claude's model list and logs every call
FAKE_ACP_RUN = """#!/bin/bash
# fake acp-run: supports --interactive
echo "$*" >> "$FAKE_LOG"
model=""
while [ $# -gt 0 ]; do [ "$1" = "--model" ] && model="$2"; shift; done
case "$model" in
  ""|default|opus|fable|sonnet|haiku|claude-sonnet-5|claude-opus-5|claude-fable-5) exit 0 ;;
esac
echo "acp-run: no model '$model'; have: default, opus, fable, sonnet, haiku, claude-sonnet-5" >&2
exit 1
"""


class TestLaunchModel(unittest.TestCase):
    tmp: Path = Path()
    repo: Path = Path()
    log: Path = Path()
    state: Path = Path()
    herdr_log: Path = Path()
    env: dict[str, str] = {}

    @override
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="launchm-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _ = subprocess.run(["git", "init", "-q", str(self.repo)], check=True, capture_output=True)
        self.log = self.tmp / "acp-run.log"
        self.herdr_log = self.tmp / "herdr.log"
        self.state = self.tmp / "state"
        acp_run = self.tmp / "acp-run"
        _ = acp_run.write_text(FAKE_ACP_RUN)
        acp_run.chmod(0o755)
        herdr = self.tmp / "herdr"    # any herdr call means a tab could have opened
        _ = herdr.write_text(f'#!/bin/bash\necho "$*" >> {self.herdr_log}\necho "{{}}"\n')
        herdr.chmod(0o755)
        self.env = dict(os.environ, SESSION_FINDER_STATE=str(self.state), ACP_RUN=str(acp_run),
                        HERDR_BIN_PATH=str(herdr), FAKE_LOG=str(self.log))

    def start(self, agent: str, model: str, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-I", str(LAUNCH), "start", "--agent", agent, "--cwd", str(self.repo),
                               "--host", "none", "--json", "--model", model, "-p", "x", *extra],
                              capture_output=True, text=True, env=self.env)

    def dry(self, agent: str, model: str) -> dict[str, Any]:
        r = self.start(agent, model, "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_api_style_claude_ids_are_mapped_to_what_acp_run_takes(self) -> None:
        for given, want in (("claude-sonnet-5-5", "claude-sonnet-5"), ("claude-opus-5-5", "claude-opus-5"),
                            ("claude-sonnet-5.5", "claude-sonnet-5"), ("claude-haiku-5-5", "haiku")):
            cmd = self.dry("claude", given)["acp_cmd"]
            self.assertEqual(cmd[cmd.index("--model") + 1], want, given)

    def test_accepted_claude_models_pass_through(self) -> None:
        for model in ("sonnet", "claude-opus-5", "haiku"):
            cmd = self.dry("claude", model)["acp_cmd"]
            self.assertEqual(cmd[cmd.index("--model") + 1], model)

    def test_unknown_claude_model_is_refused_before_any_tab_or_state(self) -> None:
        r = self.start("claude", "sonnet-nine")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("refuses --model sonnet-nine", r.stderr)
        self.assertIn("have:", r.stderr)
        self.assertFalse(self.herdr_log.exists(), "no herdr call: no tab was opened")
        self.assertEqual(list(self.state.glob("launch-*")), [])
        self.assertFalse((self.state / "launches.jsonl").exists())

    def test_other_agents_models_are_not_touched_or_probed(self) -> None:
        cmd = self.dry("codex", "claude-sonnet-5-5")["acp_cmd"]
        self.assertEqual(cmd[cmd.index("--model") + 1], "claude-sonnet-5-5")
        self.assertFalse(self.log.exists(), "only claude is probed")


if __name__ == "__main__":
    unittest.main()
