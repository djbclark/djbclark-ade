#!/usr/bin/env python3
"""codex --perm read-only never asks (2026-11-02).

Live finding (tendcf v5-s1 review, 2026-11-02; reproduced with gpt-6-luna): codex-acp's `read-only`
mode is approvalPolicy on-request plus a read-only sandbox, sent with every turn/start. A command the
sandbox blocks became a permission request whose only reject option is codex's `cancel`; acp-run
rightly refused it and codex ended the whole turn (stopReason "cancelled", no report). acp-run now
starts codex through tools/acp-run/codex-never-ask-shim.cjs, which forces approvalPolicy "never"; and
a turn the agent still cancels after a refused request fails as `escalation-abort`, which acp-dispatch
names. The shim is run as node against a fake backend that echoes the frames it receives; acp-run is
loaded in a `uv run --with` subprocess, as test_acp_run_read_only.py does.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import ClassVar, override

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("ACP_RUN_SCRIPT", str(ROOT / "tools" / "acp-run" / "acp-run")))
DISPATCH = ROOT / "bin" / "acp-dispatch"
SHIM = ROOT / "tools" / "acp-run" / "codex-never-ask-shim.cjs"
NODE = shutil.which("node")

FAKE_CODEX = "process.stdin.pipe(process.stdout);\n"  # echoes every frame the shim forwards

PROBE = textwrap.dedent("""\
    import importlib.machinery, importlib.util, json, os, sys
    loader = importlib.machinery.SourceFileLoader("acp_run", sys.argv[1])
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("acp_run", loader))
    loader.exec_module(mod)
    out = {}
    env = {"PATH": os.environ["PATH"], "CODEX_PATH": sys.argv[2]}
    mod.codex_never_ask_shim(["codex-acp"], env)
    out["env"] = env
    try:
        mod.codex_never_ask_shim(["no-such-codex-acp"], {"PATH": os.environ["PATH"]})
        out["missing"] = "no error"
    except mod.ConfigError as e:
        out["missing"] = str(e)
    out["abort"] = {
        "agent_cancelled": mod.escalation_abort("cancelled", False, 1, "Run command"),
        "our_cancel": mod.escalation_abort("cancelled", True, 1, "Run command"),
        "none_refused": mod.escalation_abort("cancelled", False, 0, None),
        "end_turn": mod.escalation_abort("end_turn", False, 2, "Run command"),
    }
    print(json.dumps(out))
    """)


def probe(fake: Path) -> dict[str, object]:
    r = subprocess.run(
        ["uv", "run", "--quiet", "--with", "agent-client-protocol>=0.9,<1.0", "python", "-I", "-c", PROBE,
         str(SCRIPT), str(fake)], check=False, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return json.loads(r.stdout)


@unittest.skipUnless(NODE, "node is needed to run the codex shim")
class NeverAsk(unittest.TestCase):
    res: ClassVar[dict[str, object]] = {}
    tmp: ClassVar[Path]
    fake: ClassVar[Path]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp())
        cls.fake = cls.tmp / "codex.js"
        cls.fake.write_text(FAKE_CODEX)
        cls.res = probe(cls.fake)

    @classmethod
    @override
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def through_shim(self, lines: list[str], real: Path | None = None) -> list[str]:
        """The lines the shim forwards to a fake backend (a .js, as acp-run's bundled codex is)."""
        assert NODE
        env = {**os.environ, "ACP_RUN_REAL_CODEX": str(real or self.fake)}
        r = subprocess.run([NODE, str(SHIM), "app-server"], input="\n".join(lines) + "\n", env=env,
                           check=False, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.splitlines()

    def test_every_turn_and_thread_request_is_forced_to_never(self):
        read_only = {"type": "readOnly", "networkAccess": False}
        out = self.through_shim([
            json.dumps({"id": 1, "method": "turn/start", "params": {
                "threadId": "t", "approvalPolicy": "on-request", "approvalsReviewer": "user",
                "sandboxPolicy": read_only}}),
            json.dumps({"id": 2, "method": "thread/start", "params": {"cwd": "/x"}}),  # no policy at all
            json.dumps({"id": 3, "method": "thread/resume", "params": {"threadId": "t",
                                                                        "approvalPolicy": "untrusted"}}),
            json.dumps({"id": 4, "method": "thread/fork", "params": {"threadId": "t"}}),
            json.dumps({"id": 5, "method": "thread/start", "params": {
                "config": {"approval_policy": "on-request", "model": "m"}}}),
        ])
        got = [json.loads(x) for x in out]
        for msg in got:
            self.assertEqual(msg["params"]["approvalPolicy"], "never", msg)
        # the sandbox and everything else the adapter sent is untouched
        self.assertEqual(got[0]["params"]["sandboxPolicy"], read_only)
        self.assertEqual(got[0]["params"]["approvalsReviewer"], "user")
        self.assertEqual(got[4]["params"]["config"], {"approval_policy": "never", "model": "m"})
        self.assertEqual(got[1]["params"]["cwd"], "/x")

    def test_other_frames_pass_through_byte_for_byte(self):
        lines = [
            json.dumps({"id": 6, "method": "thread/list", "params": {}}),
            '{"id":7,"method":"model/list" , "params":{"approvalPolicy":"never"}}',  # already never
            json.dumps({"id": 8, "result": {"approvalPolicy": "on-request"}}),  # a response, not a request
            "not json {",
        ]
        self.assertEqual(self.through_shim(lines), lines)

    def test_a_non_js_real_codex_is_run_directly(self):
        exe = self.tmp / "codex-bin"
        exe.write_text("#!/bin/sh\ncat\n")
        exe.chmod(0o755)
        out = self.through_shim([json.dumps({"id": 1, "method": "turn/start", "params": {}})], real=exe)
        self.assertEqual(json.loads(out[0])["params"], {"approvalPolicy": "never"})

    def test_acp_run_starts_codex_through_the_shim(self):
        env = self.res["env"]
        assert isinstance(env, dict)
        self.assertEqual(Path(env["CODEX_PATH"]).resolve(), SHIM.resolve())
        self.assertTrue(os.access(env["CODEX_PATH"], os.X_OK), "codex-acp spawns CODEX_PATH directly")
        self.assertEqual(env["ACP_RUN_REAL_CODEX"], str(self.fake.resolve()))  # a caller's CODEX_PATH is kept

    def test_no_real_codex_entry_fails_closed(self):
        self.assertIn("needs the real codex entry", str(self.res["missing"]))

    def test_refused_request_then_agent_cancel_is_named(self):
        a = self.res["abort"]
        assert isinstance(a, dict)
        cls, msg = a["agent_cancelled"]
        self.assertEqual(cls, "escalation-abort")
        self.assertIn("codex aborts the turn on any rejected escalation", msg)
        self.assertIn("Run command", msg)
        for key in ("our_cancel", "none_refused", "end_turn"):
            self.assertIsNone(a[key], key)  # only an agent-side cancel after a refusal qualifies

    def test_dispatch_names_the_refused_escalation_not_a_long_command(self):
        loader = importlib.machinery.SourceFileLoader("acp_dispatch_escalation", str(DISPATCH))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        assert spec
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        cases = {
            # this acp-run: the class is in the stderr
            "new": ("acp-run: FAILED escalation-abort: x\n"
                    "acp-run: agent=codex stop=cancelled secs=113.4 tools=40 perm=0+/1- fail=escalation-abort\n"),
            # an older acp-run: only the summary line
            "old": "acp-run: agent=codex stop=cancelled secs=113.4 tools=40 perm=0+/1-\n",
        }
        for name, text in cases.items():
            err = self.tmp / f"err-{name}"
            err.write_text(text)
            note = mod.failure_note(err, 1, "codex", "gpt-6-astra")
            self.assertIn("rejected escalation", note, name)
            self.assertNotIn("about an hour", note, name)
        err = self.tmp / "err-slow"  # a real hour-long cancel with no refusal keeps the old pointer
        err.write_text("acp-run: agent=opencode stop=cancelled secs=7444.2 tools=82 perm=0+/0-\n")
        self.assertIn("about an hour", mod.failure_note(err, 1, "opencode", "m1"))


if __name__ == "__main__":
    unittest.main()
