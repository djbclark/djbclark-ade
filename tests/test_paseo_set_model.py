#!/usr/bin/env python3
"""Tests for bin/paseo-set-model (the Python launcher) and bin/paseo-set-model.mjs (its node half).

The launcher is run against a fake helper that records its argv and environment. The node half runs under
the real `node` against a fake bundled-CLI dist (PASEO_SET_MODEL_CLI_DIST), so the real Paseo daemon,
app bundle and agents are never touched; those tests skip when no node is on PATH.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"
LAUNCHER = BIN / "paseo-set-model"
NODE = shutil.which("node")

FAKE_CLIENT = """
import fs from "node:fs";
const D = process.env.FAKE_DAEMON;
const load = () => JSON.parse(fs.readFileSync(D + "/agents.json", "utf8"));
export async function connectToDaemon() {
  if (fs.existsSync(D + "/down")) throw new Error("daemon unreachable");
  return {
    async fetchAgent({ agentId }) {
      const hit = load().filter((a) => a.id.startsWith(agentId));
      return hit.length ? { agent: hit[0] } : null;
    },
    async fetchAgents(opts) {
      fs.appendFileSync(D + "/calls.log", JSON.stringify({ fetchAgents: opts }) + "\\n");
      return { entries: load().map((agent) => ({ agent })), pageInfo: {} };
    },
    async setAgentModel(id, model) {
      fs.appendFileSync(D + "/calls.log", JSON.stringify({ setAgentModel: [id, model] }) + "\\n");
      if (fs.existsSync(D + "/ignore")) return;
      const all = load();
      all.find((a) => a.id === id).model = model;
      fs.writeFileSync(D + "/agents.json", JSON.stringify(all));
    },
    async close() {},
  };
}
"""
FAKE_TARGET = "export const selectDaemonTarget = () => ({ kind: 'fake' });\n"
FAKE_DIRECTORY = """
export async function fetchAllAgents(client, options = {}) {
  const payload = await client.fetchAgents(options);
  return payload.entries.map((e) => e.agent);
}
"""

AGENTS = [
    {"id": "aaaaaaa0-0000-0000-0000-000000000001", "title": "lead", "provider": "claude",
     "model": "claude-opus-5-5", "status": "running", "archivedAt": None},
    {"id": "bbbbbbb0-0000-0000-0000-000000000002", "title": None, "provider": "omp",
     "model": "anthropic/claude-fable-5-1", "status": "idle", "archivedAt": "2026-10-20T00:00:00Z"},
    {"id": "ccccccc0-0000-0000-0000-000000000003", "title": "child", "provider": "claude",
     "model": "claude-sonnet-5-5", "status": "running", "archivedAt": None, "parentAgentId": "aaaaaaa0"},
]


class TestLauncher(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.log = self.root / "helper.log"
        self.helper = self.root / "fake-helper"
        self.helper.write_text(
            f"#!{sys.executable}\nimport json, os, sys\n"
            f"open({str(self.log)!r}, 'a').write(json.dumps({{'argv': sys.argv[1:], 'env': "
            "{k: os.environ.get(k) for k in ('ELECTRON_RUN_AS_NODE', 'PASEO_NODE_ENV', 'PASEO_SET_MODEL_CLI_DIST')}})"
            " + '\\n')\nsys.exit(int(os.environ.get('FAKE_RC', '0')))\n")
        self.helper.chmod(0o755)

    def run_launcher(self, *args: str, rc: int = 0, extra: dict | None = None) -> subprocess.CompletedProcess:
        env = {"PATH": os.environ.get("PATH", ""), "PASEO_SET_MODEL_HELPER": str(self.helper),
               "PASEO_SET_MODEL_CLI_DIST": "/fake/dist", "FAKE_RC": str(rc), **(extra or {})}
        return subprocess.run([sys.executable, "-I", str(LAUNCHER), *args], env=env, capture_output=True, text=True,
                              timeout=30)

    def calls(self) -> list[dict]:
        return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_set_runs_the_helper_with_an_argv_list_and_the_node_environment(self):
        r = self.run_launcher("set", "6ebd939", "claude/claude-sonnet-5-5")
        self.assertEqual(r.returncode, 0, r.stderr)
        (call,) = self.calls()
        self.assertEqual(call["argv"][:2], ["--disable-warning=DEP0040", str(BIN / "paseo-set-model.mjs")])
        self.assertEqual(call["argv"][2:], ["set", "6ebd939", "claude/claude-sonnet-5-5"])
        self.assertEqual(call["env"], {"ELECTRON_RUN_AS_NODE": "1", "PASEO_NODE_ENV": "production",
                                       "PASEO_SET_MODEL_CLI_DIST": "/fake/dist"})

    def test_dry_run_and_list(self):
        self.run_launcher("set", "--dry-run", "6ebd939", "claude-opus-5-5")
        self.run_launcher("list", "--json")
        calls = self.calls()
        self.assertEqual(calls[0]["argv"][2:], ["set", "6ebd939", "claude-opus-5-5", "--dry-run"])
        self.assertEqual(calls[1]["argv"][2:], ["list"])

    def test_the_helpers_exit_status_is_the_launchers(self):
        for rc in (3, 4, 1):
            self.assertEqual(self.run_launcher("set", "x", "m", rc=rc).returncode, rc)

    def test_the_default_cli_dist_is_the_app_bundle(self):
        env = {"PATH": os.environ.get("PATH", ""), "PASEO_SET_MODEL_HELPER": str(self.helper)}
        subprocess.run([sys.executable, "-I", str(LAUNCHER), "list", "--json"], env=env, capture_output=True, timeout=30)
        self.assertEqual(self.calls()[0]["env"]["PASEO_SET_MODEL_CLI_DIST"],
                         "/Applications/Paseo.app/Contents/Resources/app.asar/node_modules/@getpaseo/cli/dist")

    def test_usage_errors_exit_2_and_never_reach_the_helper(self):
        for args in ((), ("set",), ("set", "only-agent"), ("set", "a", "m", "--force"), ("list",),
                     ("list", "--yaml"), ("frobnicate",), ("set", "a", "b", "c")):
            with self.subTest(args=args):
                self.assertEqual(self.run_launcher(*args).returncode, 2)
        self.assertEqual(self.calls(), [])

    def test_a_missing_helper_exits_1(self):
        r = self.run_launcher("list", "--json", extra={"PASEO_SET_MODEL_HELPER": str(self.root / "nope")})
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot run", r.stderr)


@unittest.skipUnless(NODE, "node not on PATH")
class TestNodeHalf(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        dist = self.root / "dist"
        (dist / "utils").mkdir(parents=True)
        (dist / "package.json").write_text('{"type": "module"}')
        (dist / "utils" / "client.js").write_text(FAKE_CLIENT)
        (dist / "utils" / "daemon-target.js").write_text(FAKE_TARGET)
        (dist / "utils" / "agent-directory.js").write_text(FAKE_DIRECTORY)
        self.daemon = self.root / "daemon"
        self.daemon.mkdir()
        (self.daemon / "agents.json").write_text(json.dumps(AGENTS))
        self.dist = dist

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        env = {"PATH": os.environ.get("PATH", ""), "PASEO_SET_MODEL_HELPER": NODE,
               "PASEO_SET_MODEL_CLI_DIST": str(self.dist), "FAKE_DAEMON": str(self.daemon)}
        return subprocess.run([sys.executable, "-I", str(LAUNCHER), *args], env=env, capture_output=True, text=True,
                              timeout=60)

    def model_of(self, prefix: str) -> str:
        return next(a for a in json.loads((self.daemon / "agents.json").read_text())
                    if a["id"].startswith(prefix))["model"]

    def test_set_switches_the_model_and_verifies_it(self):
        r = self.run_cli("set", "aaaaaaa", "claude-sonnet-5-5")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("set: claude-opus-5-5 -> claude-sonnet-5-5", r.stdout)
        self.assertEqual(self.model_of("aaaaaaa"), "claude-sonnet-5-5")

    def test_dry_run_changes_nothing(self):
        r = self.run_cli("set", "aaaaaaa", "claude-sonnet-5-5", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("provider=claude status=running model=claude-opus-5-5", r.stdout)
        self.assertEqual(self.model_of("aaaaaaa"), "claude-opus-5-5")
        self.assertFalse((self.daemon / "calls.log").exists())

    def test_provider_prefix_matching_the_agent_is_stripped(self):
        self.assertEqual(self.run_cli("set", "aaaaaaa", "claude/claude-sonnet-5-5").returncode, 0)
        self.assertEqual(self.model_of("aaaaaaa"), "claude-sonnet-5-5")

    def test_a_different_provider_is_refused_before_any_call(self):
        r = self.run_cli("set", "aaaaaaa", "codex/gpt-6-astra")
        self.assertEqual(r.returncode, 1)
        self.assertIn("provider claude", r.stderr)
        self.assertEqual(self.model_of("aaaaaaa"), "claude-opus-5-5")
        self.assertFalse((self.daemon / "calls.log").exists())

    def test_an_omp_model_id_keeps_its_own_slash(self):
        r = self.run_cli("set", "bbbbbbb", "anthropic/claude-opus-5-5")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.model_of("bbbbbbb"), "anthropic/claude-opus-5-5")

    def test_no_such_agent_exits_3(self):
        r = self.run_cli("set", "zzzzzzz", "claude-opus-5-5")
        self.assertEqual(r.returncode, 3)
        self.assertIn("no agent zzzzzzz", r.stderr)

    def test_a_model_the_daemon_did_not_apply_exits_4(self):
        (self.daemon / "ignore").write_text("")
        r = self.run_cli("set", "aaaaaaa", "claude-sonnet-5-5")
        self.assertEqual(r.returncode, 4)
        self.assertIn("claude-opus-5-5 -> claude-opus-5-5", r.stdout)

    def test_an_unreachable_daemon_exits_1(self):
        (self.daemon / "down").write_text("")
        r = self.run_cli("set", "aaaaaaa", "claude-sonnet-5-5")
        self.assertEqual(r.returncode, 1)
        self.assertIn("daemon unreachable", r.stderr)

    def test_list_prints_every_agent_archived_ones_included(self):
        r = self.run_cli("list", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = json.loads(r.stdout)
        self.assertEqual(rows, [
            {"id": AGENTS[0]["id"], "name": "lead", "provider": "claude", "model": "claude-opus-5-5",
             "status": "running", "archived": False},
            {"id": AGENTS[1]["id"], "name": None, "provider": "omp", "model": "anthropic/claude-fable-5-1",
             "status": "idle", "archived": True},
            {"id": AGENTS[2]["id"], "name": "child", "provider": "claude", "model": "claude-sonnet-5-5",
             "status": "running", "archived": False, "parentAgentId": "aaaaaaa0"},
        ])
        asked = json.loads((self.daemon / "calls.log").read_text().splitlines()[0])["fetchAgents"]
        self.assertEqual(asked, {"filter": {"includeArchived": True, "includeBackground": True}})


if __name__ == "__main__":
    unittest.main()
