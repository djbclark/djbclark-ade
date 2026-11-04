#!/usr/bin/env python3
"""Anthropic credit-balance refusal takes omp out of routing (2026-11-04).

When Anthropic returns HTTP 400 invalid_request_error "Your credit balance is too low
to access the Anthropic API...", acp-dispatch classifies `credit`, notes the pool
exhausted via aiuse (reset from the row's resets_at / expires_at / available_at /
credits stamp, else a fixed 6 h back-off), and a later dispatch is refused on headroom
before launch. Synthetic fakes only: no live agent, aiuse or network.
"""
from __future__ import annotations

import json
import os
import runpy
import textwrap
import unittest
from pathlib import Path
from typing import override

from test_acp_dispatch import SCRIPT, Base, run

OMP = "anthropic/claude-sonnet-5-5"
CREDIT_MSG = (
    'Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":'
    '"Your credit balance is too low to access the Anthropic API. Please go to Plans '
    '& Billing to upgrade or purchase credits."}}'
)
RESET_AT = "2026-11-06T05:00:00+00:00"


class TestCreditFailureClass(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = runpy.run_path(str(SCRIPT))

    def cls(self, text: str, rc: int = 1) -> str | None:
        return self.mod["failure_class"](text, rc)[0]

    def test_anthropic_credit_balance_message_is_credit(self):
        self.assertEqual(self.cls(CREDIT_MSG), "credit")
        self.assertEqual(self.cls(
            "Your credit balance is too low to access the Anthropic API."), "credit")

    def test_credit_balance_too_low_pair_matches_generally(self):
        self.assertEqual(self.cls("provider said: credit balance is too low"), "credit")

    def test_other_400s_are_not_credit(self):
        for text in (
            'Error: 400 {"type":"error","error":{"type":"invalid_request_error",'
            '"message":"messages.1.content.0.thinking.signature: Field required"}}',
            "HTTP 400 bad request: malformed tool call",
            "insufficient quota",
            "You have exceeded your monthly quota",
        ):
            self.assertNotEqual(self.cls(text), "credit", text)


class TestCreditRefusalDispatch(Base):
    """Preflight credit refusal notes aiuse; a second dispatch is refused before launch."""

    @override
    def setUp(self) -> None:
        super().setUp()
        self.calls_file = self.tmp / "aiuse.calls"
        self.available = self.tmp / "available.json"
        self.note_log = self.tmp / "aiuse-notes.log"
        self._write_available(80.0, expires_at=RESET_AT)
        # Extend the shared fake with a credit preflight / run mode (owned test file only).
        fake = self.fake.read_text()
        zcode = ("      zcode_quota) echo 'ZCode turn failed: 1310 [1310][Weekly/Monthly Limit "
                 "Exhausted. Your limit will reset at 2026-10-14 22:56:01]' >&2; exit 1;;")
        assert zcode in fake, "shared FAKE preflight case changed; update this test"
        fake = fake.replace(
            zcode,
            zcode + f"\n      credit) echo '{CREDIT_MSG}' >&2; exit 1;;",
            1,
        )
        quota = '  quota)    echo "FAILED quota" >&2; exit 1;;'
        assert quota in fake, "shared FAKE run modes changed; update this test"
        fake = fake.replace(
            quota,
            quota + (f"\n  credit)   echo '{CREDIT_MSG}' >&2; "
                     'echo "acp-run: agent=omp stop=error secs=1.0 tools=0 fail=credit" >&2; exit 1;;'),
            1,
        )
        self.fake.write_text(fake)
        self.fake_aiuse = self.tmp / "fake-aiuse"
        # note-exhausted logs argv and rewrites ROUTE_AGENT_AIUSE_JSON so the next dispatch
        # sees the pool exhausted (what real aiuse does after the note).
        self.exhausted_json = self.tmp / "exhausted-available.json"
        self.exhausted_json.write_text(json.dumps({
            "age_seconds": 0, "fresh": True,
            "available": [],
            "excluded": [{"provider": "omp", "reason": "noted exhausted",
                          "expires_at": RESET_AT}],
        }))
        self.fake_aiuse.write_text(textwrap.dedent(f"""\
            #!/bin/bash
            if [ "$1" = note-exhausted ]; then
              printf '%s\\n' "$*" >> "{self.note_log}"
              printf '%s\\n' "$*" >> "{self.calls_file}"
              cp "{self.exhausted_json}" "{self.available}"
              exit 0
            fi
            exit 0
            """))
        self.fake_aiuse.chmod(0o755)

    def _write_available(self, headroom: float, *, expires_at: str | None = None) -> None:
        row: dict = {"provider": "omp", "age_seconds": 0, "headroom_percent": headroom,
                     "usable_now": True}
        if expires_at:
            row["expires_at"] = expires_at
            row["available_at"] = expires_at
            row["windows"] = [{"label": "omp credits", "remaining_percent": headroom,
                               "headroom_percent": headroom, "resets_at": expires_at}]
        self.available.write_text(json.dumps({
            "age_seconds": 0, "fresh": True, "available": [row],
        }))

    def credit_env(self, **extra: str) -> dict[str, str]:
        return {
            "ACP_DISPATCH_AIUSE": str(self.fake_aiuse),
            "ROUTE_AGENT_AIUSE_JSON": str(self.available),
            "PREFLIGHT_MODE": "credit",
            **extra,
        }

    def notes(self) -> list[str]:
        return self.note_log.read_text().splitlines() if self.note_log.exists() else []

    def test_preflight_credit_exits_5_and_notes_exhausted_from_row_expiry(self):
        r = self.dispatch_agent(
            "omp", OMP, "--kind", "judgment", "--no-model-check", "--est-pct", "1",
            name="c1", env=self.credit_env())
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("class=credit", r.stdout)
        self.assertEqual(self.record("c1")["status"], "unavailable")
        self.assertEqual(self.record("c1")["unavailable_class"], "credit")
        notes = self.notes()
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("note-exhausted omp", notes[0])
        self.assertIn(f"--resets-at {RESET_AT}", notes[0])
        self.assertIn("credit refusal", notes[0])
        self.assertNotIn("--family", notes[0])

    def test_second_dispatch_refused_before_launch_after_note(self):
        first = self.dispatch_agent(
            "omp", OMP, "--kind", "judgment", "--no-model-check", "--est-pct", "1",
            name="c1", env=self.credit_env())
        self.assertEqual(first.returncode, 5, first.stdout + first.stderr)
        self.assertEqual(self.preflight_probes(), 1)
        self.assertTrue(self.notes())

        second = self.dispatch_agent(
            "omp", OMP, "--kind", "judgment", "--no-model-check", "--est-pct", "1",
            "--min-headroom", "10", name="c2",
            env=self.credit_env(PREFLIGHT_MODE="pass"))
        self.assertEqual(second.returncode, 5, second.stdout + second.stderr)
        self.assertEqual(self.record("c2")["unavailable_class"], "headroom")
        # refused at admission: the credit probe must not run again
        self.assertEqual(self.preflight_probes(), 1)
        self.assertFalse((self.out / "c2.jsonl").exists())

    def test_credit_without_row_reset_uses_6h_backoff(self):
        self._write_available(80.0)  # no expires_at / resets_at
        r = self.dispatch_agent(
            "omp", OMP, "--kind", "judgment", "--no-model-check", "--est-pct", "1",
            name="c3", env=self.credit_env())
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("class=credit", r.stdout)
        notes = self.notes()
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("note-exhausted omp --resets-in 6h", notes[0])

    def test_run_credit_refusal_notes_and_writes_no_report_credit(self):
        r = self.dispatch_agent(
            "omp", OMP, "--kind", "judgment", "--no-model-check", "--est-pct", "1",
            "--no-preflight", mode="credit", name="c4",
            env=self.credit_env(PREFLIGHT_MODE="pass"))
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        failure = self.record("c4").get("failure", "")
        self.assertTrue(failure.startswith("NO-REPORT: credit"), failure)
        notes = self.notes()
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("note-exhausted omp", notes[0])
        self.assertIn("--resets-at", notes[0])

    def test_plain_400_does_not_note_exhausted(self):
        # swap credit mode for a generic 400 so classification is not credit
        credit_arm = f"      credit) echo '{CREDIT_MSG}' >&2; exit 1;;"
        plain = ('      credit) echo \'Error: 400 {"type":"error","error":{"type":"invalid_request_error",'
                 '"message":"messages.0.content: Field required"}}\' >&2; exit 1;;')
        fake = self.fake.read_text()
        assert credit_arm in fake
        self.fake.write_text(fake.replace(credit_arm, plain, 1))
        r = self.dispatch_agent(
            "omp", OMP, "--kind", "judgment", "--no-model-check", "--est-pct", "1",
            name="c5", env=self.credit_env())
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertNotIn("class=credit", r.stdout)
        self.assertEqual(self.notes(), [])


class TestCreditResetStampUnit(unittest.TestCase):
    """aiuse_pool_reset_stamp reads expires_at / resets_at / credits without requiring exhausted."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = runpy.run_path(str(SCRIPT))

    def test_expires_at_on_available_row(self):
        import tempfile
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "a.json"
            path.write_text(json.dumps({
                "fresh": True,
                "available": [{
                    "provider": "omp", "age_seconds": 0, "headroom_percent": 90,
                    "expires_at": RESET_AT,
                }],
            }))
            os.environ["ROUTE_AGENT_AIUSE_JSON"] = str(path)
            try:
                stamp = self.mod["aiuse_pool_reset_stamp"]("omp", OMP)
            finally:
                os.environ.pop("ROUTE_AGENT_AIUSE_JSON", None)
        self.assertIsNotNone(stamp)
        assert stamp is not None
        self.assertEqual(stamp.astimezone(timezone.utc),
                         datetime.fromisoformat(RESET_AT))

    def test_credits_block_on_snapshot_account(self):
        import tempfile
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as td:
            snap = Path(td) / "snap.json"
            snap.write_text(json.dumps({
                "snapshot": {"accounts": [{
                    "provider": "omp",
                    "credits": {"expires_at": RESET_AT},
                    "windows": [{"label": "omp credits", "remaining_percent": 50.0,
                                 "headroom_percent": 50.0}],
                }]},
            }))
            os.environ["AIUSE_SNAPSHOT"] = str(snap)
            os.environ.pop("ROUTE_AGENT_AIUSE_JSON", None)
            try:
                stamp = self.mod["aiuse_pool_reset_stamp"]("omp", OMP)
            finally:
                os.environ.pop("AIUSE_SNAPSHOT", None)
        self.assertIsNotNone(stamp)
        assert stamp is not None
        self.assertEqual(stamp.astimezone(timezone.utc),
                         datetime.fromisoformat(RESET_AT))


if __name__ == "__main__":
    unittest.main()
