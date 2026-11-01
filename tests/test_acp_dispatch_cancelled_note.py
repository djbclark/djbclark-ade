"""The no-report text names a cancel's real cause, and a model fallback reaches the record (2026-10-31).

A 60 s gpt-6-astra slice, cancelled at a refused permission, was blamed on "a foreground command that ran
about an hour"; a `claude --model fable` slice was declined by Fable's cyber safeguard and answered by
claude-opus-4-8 with only the report text saying so. Hermetic: stderr text and session logs are written here.
"""
import importlib.machinery
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "acp-dispatch"


def load():
    loader = importlib.machinery.SourceFileLoader("acp_dispatch_cancelled", str(SCRIPT))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


MOD = load()
REFUSED = ("acp-run: refused (execute): /opt/homebrew/bin/bash -lc 'timeout 25 curl -X POST "
           "https://example.com'\n")


class TestCancelledNote(unittest.TestCase):
    def note(self, stderr: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            err = Path(tmp) / "err"
            err.write_text(stderr)
            return MOD.failure_note(err, 1, "codex", "gpt-6-astra")

    def test_a_cancel_after_a_denied_permission_names_the_refused_call(self):
        note = self.note(REFUSED + "acp-run: agent=codex stop=cancelled secs=59.7 tools=13 perm=0+/1- tokens=9\n")
        self.assertIn("cancelled after a denied permission", note)
        self.assertIn("curl -X POST https://example.com", note)
        self.assertNotIn("an hour", note)
        self.assertNotIn("item 10", note)

    def test_a_denial_beats_the_hour_hint_even_on_a_long_run(self):
        note = self.note(REFUSED + "acp-run: agent=codex stop=cancelled secs=7444.2 tools=82 perm=3+/1-\n")
        self.assertIn("denied permission", note)
        self.assertNotIn("an hour", note)

    def test_a_denial_without_its_line_still_says_so(self):
        note = self.note("acp-run: agent=codex stop=cancelled secs=59.7 tools=13 perm=0+/1-\n")
        self.assertIn("cancelled after a denied permission", note)
        self.assertNotIn("an hour", note)

    def test_an_hour_long_cancel_without_a_denial_keeps_the_footer_hint(self):
        note = self.note("acp-run: agent=opencode stop=cancelled secs=3626.0 tools=82 perm=5+/0-\n")
        self.assertIn("a foreground command that ran about an hour", note)
        self.assertIn("dispatch-footer item 10", note)

    def test_a_short_cancel_without_a_denial_does_not_blame_an_hour(self):
        note = self.note("acp-run: agent=codex stop=cancelled secs=60.0 tools=13 perm=5+/0-\n")
        self.assertNotIn("an hour", note)
        self.assertIn("after 60 s with no denied permission", note)


class TestModelFallback(unittest.TestCase):
    def record(self, tmp: str, rows: list[dict], **extra) -> tuple[Path, dict]:
        log = Path(tmp) / "slice.jsonl"
        log.write_text("".join(json.dumps(r) + "\n" for r in rows))
        report = Path(tmp) / "slice-report.md"
        report.write_text("STATUS: done\nDONE\n")
        done = Path(tmp) / "slice-report.md.done"
        done.touch()
        rec = {"name": "slice", "report": str(report), "done": str(done), "log": str(log), "finished": 1.0,
               "exit": 0, "agent": "claude", "model": "fable", **extra}
        path = Path(tmp) / "slice.json"
        path.write_text(json.dumps(rec))
        return path, rec

    def test_the_fallback_row_is_read_from_the_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, rec = self.record(tmp, [
                {"kind": "applied", "data": {"model": "fable"}},
                {"kind": "fallback", "data": {"from": "claude-fable-5-1", "reason": "cyber",
                                              "to": "claude-opus-4-8"}}])
            self.assertEqual(MOD.model_fallback(rec),
                             {"from": "claude-fable-5-1", "reason": "cyber", "to": "claude-opus-4-8"})

    def test_no_row_and_no_log_are_no_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, rec = self.record(tmp, [{"kind": "applied", "data": {"model": "fable"}}])
            self.assertIsNone(MOD.model_fallback(rec))
            self.assertIsNone(MOD.model_fallback({"name": "old record"}))

    def test_a_quoted_notice_in_the_agents_words_is_not_a_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, rec = self.record(tmp, [{"kind": "update", "data": {"content": {
                "text": "fallback: retried with claude-opus-4-8"}}}])
            self.assertIsNone(MOD.model_fallback(rec))

    def test_check_shows_who_answered(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = self.record(tmp, [], answered_model="claude-opus-4-8", fallback_from="claude-fable-5-1",
                                  fallback_reason="cyber")
            _, _, _, det = MOD.check_record(path)
        self.assertIn("ANSWERED BY claude-opus-4-8, not claude-fable-5-1 (model fallback: cyber)", det)

    def test_an_old_record_without_the_fields_shows_nothing_extra(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = self.record(tmp, [])
            _, _, _, det = MOD.check_record(path)
        self.assertNotIn("ANSWERED BY", det)


if __name__ == "__main__":
    unittest.main()
