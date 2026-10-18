#!/usr/bin/env python3
"""Tests for `acp-dispatch outcome` (2026-10-18, slice D3): the writer for the `outcome`
fields `route_agent.py calibrate` reads (ci, review: "pass" | "fail"; merged: bool).

Uses test_acp_dispatch's fake acp-run and fixtures.
"""
from __future__ import annotations

import unittest

from test_acp_dispatch import run
from test_acp_dispatch_reap import ReapBase


class TestOutcome(ReapBase):
    def outcome(self, *flags: str):
        return run(["outcome", str(self.record_path()), *flags], env=self.base_env())

    def test_flags_merge_across_calls_in_calibrates_schema(self):
        self.dispatch()
        r = self.outcome("--ci", "pass")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "outcome\ts1\tci=pass")
        r = self.outcome("--review", "fail", "--merged")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = self.record()["outcome"]
        self.assertEqual((out["ci"], out["review"], out["merged"]), ("pass", "fail", True))
        self.assertIsInstance(out["at"], float)

    def test_not_merged_is_false_not_absent(self):
        self.dispatch()
        self.assertEqual(self.outcome("--not-merged").returncode, 0)
        self.assertIs(self.record()["outcome"]["merged"], False)

    def test_no_flag_is_refused(self):
        self.dispatch()
        r = self.outcome()
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("outcome", self.record())

    def test_merged_and_not_merged_are_exclusive(self):
        self.dispatch()
        self.assertEqual(self.outcome("--merged", "--not-merged").returncode, 2)

    def test_a_running_slice_is_refused(self):
        self.dispatch()
        self.unfinished()
        r = self.outcome("--ci", "pass")
        self.assertEqual(r.returncode, 2)
        self.assertIn("has not finished", r.stderr)
        self.assertNotIn("outcome", self.record())

    def test_bad_value_is_refused(self):
        self.dispatch()
        self.assertEqual(self.outcome("--ci", "green").returncode, 2)


if __name__ == "__main__":
    unittest.main()
