#!/usr/bin/env python3
"""bin/paseo-new-seat --probe archives the throwaway seat; without --probe nothing is archived.

The helper (PASEO_NEW_SEAT_HELPER) and `paseo` (PASEO_NEW_SEAT_PASEO) are fakes that log their argv, so the
real daemon, app bundle and agents are never touched.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SEAT = Path(__file__).resolve().parent.parent / "bin" / "paseo-new-seat"
AID = "11111111-2222-3333-4444-555555555555"


def run(extra: list[str], archive_rc: int = 0, helper_body: str | None = None, env_extra: dict | None = None) -> tuple[subprocess.CompletedProcess, list[str]]:
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        log = d / "paseo.log"
        helper = d / "helper"
        helper.write_text(helper_body or '#!/bin/sh\necho \'{"id":"%s","shortId":"11111111","autoAccept":true}\'\n' % AID)
        paseo = d / "paseo"
        paseo.write_text(
            '#!/bin/sh\necho "$*" >> "%s"\n'
            'if [ "$2" = ls ]; then echo \'[{"id":"%s","status":"idle"}]\'; fi\n'
            'if [ "$2" = archive ]; then exit %d; fi\n' % (log, AID, archive_rc))
        for f in (helper, paseo):
            f.chmod(f.stat().st_mode | stat.S_IXUSR)
        env = {**os.environ, "PASEO_NEW_SEAT_HELPER": str(helper), "PASEO_NEW_SEAT_PASEO": str(paseo),
               "PASEO_NEW_SEAT_POLL": "0.01", "PASEO_NEW_SEAT_PROBE_WAIT": "5", **(env_extra or {})}
        r = subprocess.run([sys.executable, str(SEAT), "--title", "zz probe", "--prompt", "ok", *extra],
                           env=env, capture_output=True, text=True, check=False)
        return r, (log.read_text().splitlines() if log.exists() else [])


class ProbeTests(unittest.TestCase):
    def test_probe_archives_after_the_turn_ends(self) -> None:
        r, calls = run(["--probe"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"agent archive {AID}", calls)
        self.assertEqual(json.loads(r.stdout.strip().splitlines()[-1])["id"], AID)

    def test_no_probe_flag_archives_nothing(self) -> None:
        r, calls = run([])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(calls, [])

    def test_probe_dry_run_archives_nothing(self) -> None:
        r, calls = run(["--probe", "--dry-run"])
        self.assertEqual(calls, [])

    def test_archive_failure_is_exit_5_and_loud(self) -> None:
        r, _ = run(["--probe"], archive_rc=1)
        self.assertEqual(r.returncode, 5)
        self.assertIn("not archived", r.stderr)

    def test_unusable_wait_settings_fall_back_and_still_archive(self) -> None:
        for bad in ("abc", "nan", "inf", "-1"):
            with self.subTest(bad=bad):
                r, calls = run(["--probe"], env_extra={"PASEO_NEW_SEAT_POLL": bad, "PASEO_NEW_SEAT_PROBE_WAIT": bad})
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn(f"agent archive {AID}", calls)

    def test_helper_failure_after_create_with_an_id_still_archives(self) -> None:
        body = '#!/bin/sh\necho \'{"id":"%s","shortId":"11111111"}\'\nexit 1\n' % AID
        r, calls = run(["--probe"], helper_body=body)
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"agent archive {AID}", calls)

    def test_helper_failure_with_no_id_warns_that_a_seat_may_be_open(self) -> None:
        r, calls = run(["--probe"], helper_body="#!/bin/sh\necho 'created, but the daemon returned no agent id' >&2\nexit 1\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("may have been created", r.stderr)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
