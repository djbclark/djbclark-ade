#!/usr/bin/env python3
"""A "transient" acp-run failure on a pool with no headroom is a quota stop (2026-10-18).

A cursor `--model default` slice died after 757 s on "FAILED transient: reply truncated ... http/2
stream closed with error code CANCEL (0x8)"; acp-dispatch said transient and offered `reroute
--escalate (-> judgment)`, and a `resume` minutes later was refused at 0.0% headroom. So the
transient class looks up the same reading the resume refusal uses (`pool_reading`): below the
dispatch minimum it is written as `NO-REPORT: quota` and takes the quota path (auto-resume, reroute,
`check`); otherwise it stays transient, and `check` suggests a reroute, never an escalation.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import override
from unittest.mock import patch

from test_acp_dispatch import FAKE, SCRIPT, Base, run

TRANSIENT_ERR = (
    "acp-run: FAILED transient: reply truncated; edits may be present; it ended with 'http/2 stream "
    "closed with error code CANCEL (0x8)'\n"
    "acp-run: agent=cursor stop=error secs=757.1 tools=60 fail=transient\n")


def load_module():
    loader = importlib.machinery.SourceFileLoader("acp_dispatch_transient", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestFailureNote(unittest.TestCase):
    def note(self, remaining: float | None, err: str = TRANSIENT_ERR) -> str | None:
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(mod, "pool_reading", return_value=(remaining, {})), \
                patch.object(mod, "note_outage_in_aiuse", return_value="ok"):
            stderr = Path(tmp) / "err"
            stderr.write_text(err)
            return mod.failure_note(stderr, 1, "cursor", "default")

    def test_low_headroom_is_a_quota_stop(self):
        note = self.note(0.0)
        self.assertTrue(note.startswith("NO-REPORT: quota (cursor, default)"), note)
        self.assertIn("transient error on a pool at 0.0% headroom: treated as quota", note)

    def test_just_under_the_minimum_is_a_quota_stop(self):
        self.assertTrue(self.note(9.9).startswith("NO-REPORT: quota"))

    def test_headroom_at_the_minimum_stays_transient(self):
        self.assertTrue(self.note(10.0).startswith("NO-REPORT: transient (cursor, default)"))

    def test_healthy_pool_stays_transient(self):
        note = self.note(70.0)
        self.assertTrue(note.startswith("NO-REPORT: transient (cursor, default)"), note)
        self.assertNotIn("treated as quota", note)

    def test_unknown_headroom_stays_transient(self):
        self.assertTrue(self.note(None).startswith("NO-REPORT: transient"))

    def test_other_classes_never_look_at_headroom(self):
        mod = load_module()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(mod, "pool_reading", side_effect=AssertionError("looked up headroom")):
            stderr = Path(tmp) / "err"
            stderr.write_text("acp-run: FAILED refused: model refused the task\n")
            note = mod.failure_note(stderr, 1, "agy", "m1", "Sorry, I cannot fulfill your request.")
        self.assertTrue(note.startswith("NO-REPORT: refused"), note)

    def test_real_quota_text_keeps_its_own_path(self):
        err = "acp-run: FAILED quota: quota exhausted: retry in 2 hours\nacp-run: agent=cursor fail=quota\n"
        note = self.note(70.0, err)
        self.assertTrue(note.startswith("NO-REPORT: quota (cursor, default, retry in 2 hours)"), note)
        self.assertNotIn("treated as quota", note)


FAKE_TRANSIENT = FAKE.replace(
    'quota)    echo "FAILED quota"',
    "transient) printf 'STATUS: working\\npartway\\n' > \"$report\"\n"
    f"    echo {shlex.quote(TRANSIENT_ERR.splitlines()[0])} >&2\n"
    f"    echo {shlex.quote(TRANSIENT_ERR.splitlines()[1])} >&2\n"
    '    exit 1;;\n  quota)    echo "FAILED quota"', 1)


class TestDispatch(Base):
    """End to end: fake acp-run fails transient; the pool snapshot decides the class."""

    @override
    def setUp(self) -> None:
        super().setUp()
        self.assertNotEqual(FAKE_TRANSIENT, FAKE, "the transient mode was not injected")
        _ = self.fake.write_text(FAKE_TRANSIENT)

    def snapshot(self, percent: float) -> Path:
        snap = self.tmp / f"pool-{percent}.json"
        _ = snap.write_text(json.dumps({"collected_at": "2099-01-01T00:00:00+00:00", "snapshot": {
            "accounts": [{"provider": "codex", "windows": [
                {"label": "5h", "remaining_percent": percent},
                {"label": "weekly", "remaining_percent": percent}]}]}}))
        return snap

    def failed(self, percent: float) -> tuple[subprocess.CompletedProcess[str], dict]:
        env = self.base_env("transient", AIUSE_SNAPSHOT=str(self.snapshot(percent)))
        r = self.dispatch_agent("codex", "m1", "--min-headroom", "0", "--est-pct", "0",
                                "--no-preflight", mode="transient", env=env)
        return r, self.record()

    def check_as_kind(self, kind: str, mode: str) -> str:
        """`check` the finished record as if it had been dispatched for KIND (the ladder needs a
        rung above it; codex's default kind is the top one)."""
        path = self.out / "jobs" / "s1.json"
        rec = json.loads(path.read_text())
        rec["kind"] = kind
        _ = path.write_text(json.dumps(rec))
        c = run(["check", str(path)], env=self.base_env(mode))
        return c.stdout

    def test_low_headroom_takes_the_quota_path(self):
        r, rec = self.failed(3.0)
        self.assertTrue(rec["failure"].startswith("NO-REPORT: quota"), r.stdout + r.stderr)
        self.assertIn("transient error on a pool at 3.0% headroom: treated as quota", rec["failure"])
        self.assertTrue(Path(rec["report"]).read_text().splitlines()[-1].startswith("NO-REPORT: quota"))
        # the ordinary quota path: an auto-resume is scheduled, or the manual resume command given
        self.assertEqual((rec.get("auto_resume") or {}).get("state"), "scheduled", r.stdout + r.stderr)
        self.assertEqual(len(self.launchctl()), 1)
        self.assertNotIn("--escalate", self.check_as_kind("code", "transient"))

    def test_healthy_pool_stays_transient_and_suggests_no_escalation(self):
        r, rec = self.failed(70.0)
        self.assertTrue(rec["failure"].startswith("NO-REPORT: transient"), r.stdout + r.stderr)
        self.assertNotIn("treated as quota", rec["failure"])
        self.assertIsNone(rec.get("auto_resume"))
        self.assertEqual(self.launchctl(), [])
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        out = self.check_as_kind("code", "transient")
        self.assertNotIn("--escalate", out)
        self.assertNotIn("escalate:", out)
        # a reroute command per route_agent's plan for the kind, or the statement that none is eligible
        self.assertTrue("reroute " in out or "no other pool eligible" in out, out)

    def test_non_transport_failure_keeps_the_escalation_hint(self):
        _ = self.dispatch_agent("codex", "m1", "--no-preflight", mode="timeout")
        out = self.check_as_kind("code", "timeout")
        self.assertIn("NO-REPORT: timeout", out)
        self.assertIn("escalate:", out)
        self.assertIn("--escalate (-> judgment)", out)


if __name__ == "__main__":
    unittest.main()
