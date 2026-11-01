#!/usr/bin/env python3
"""A hook behind bin/hook-deadline needs an outer timeout well above its inner deadline (2026-11-01).

hook-deadline kills its command after N seconds and exits 0 silently, but only once perl has started. At load
30-50 on 8 cores, with memory compressor churn, starting it alone took longer than the old 5 s outer timeout, so
Claude Code killed the wrapper first and printed "timed out after 5s" for prior_art_nudge and quota_nudge on every
prompt. The outer timeout is only a backstop, so it must stay above both the deadline and the spawn delay."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

TMPL = Path(__file__).resolve().parent.parent / "agents" / "claude" / "settings.json.tmpl"
MIN_OUTER_S = 15


def wrapped_hooks() -> list[tuple[str, float, object]]:
    text = re.sub(r"\{\{.*?\}\}", "x", TMPL.read_text())
    out = []
    for event, groups in json.loads(text)["hooks"].items():
        for group in groups:
            for hook in group.get("hooks", []):
                m = re.search(r"hook-deadline (\d+(?:\.\d+)?) ", hook.get("command", ""))
                if m:
                    out.append((event, float(m.group(1)), hook.get("timeout")))
    return out


class HookDeadlineTimeoutsTest(unittest.TestCase):
    def test_some_hooks_are_wrapped(self) -> None:
        self.assertGreaterEqual(len(wrapped_hooks()), 6)

    def test_outer_timeout_leaves_room_for_a_loaded_machine(self) -> None:
        for event, deadline, timeout in wrapped_hooks():
            with self.subTest(event=event, deadline=deadline):
                # An absent timeout is Claude Code's long default, which is also fine.
                if timeout is not None:
                    self.assertGreaterEqual(timeout, MIN_OUTER_S)
                    self.assertGreater(timeout, deadline)


if __name__ == "__main__":
    unittest.main()
