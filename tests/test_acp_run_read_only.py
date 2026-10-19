#!/usr/bin/env python3
"""--perm read-only and the fake-tool-calls delivery check (2026-10-19).

Two frontier review slices ran `--perm deny`, which gives claude-agent-acp no tools. The model
printed its calls as text (`<invoke name="Read">...`), ended its turn in 26 s, acp-run exited 0
and acp-dispatch recovered the reply as a finished report. acp-run imports the ACP SDK, so the
script is loaded in a `uv run --with` subprocess, as test_acp_run_failure.py does.
"""
from __future__ import annotations

import json
import os
import subprocess
import textwrap
import unittest
from pathlib import Path
from typing import ClassVar, override

from test_acp_dispatch import Base, run

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("ACP_RUN_SCRIPT", str(ROOT / "tools" / "acp-run" / "acp-run")))
# the real positive: claude fable under --perm deny, ade-v21-review-fable-final.txt
FABLE_FINAL = (ROOT / "tests" / "fixtures" / "fake-tool-calls-fable-final.txt").read_text()

REPORT_QUOTING_MARKUP = (
    "STATUS: done\n\nThe bug: the model printed\n\n```\n<invoke name=\"Read\">\n"
    "<parameter name=\"file_path\">/x</parameter>\n</invoke>\n```\n\nas its reply. Fixed in "
    "`<invoke name=` handling.\n\nDONE"
)
RAW_QUOTE = "As seen in the transcript, <invoke name=\"Read\"> appeared as plain text in the reply."
FENCED_JSON_CALL = 'Let me read it.\n\n```json\n{"tool": "Read", "arguments": {"file_path": "/x"}}\n```\n'
FENCED_TOOL_CALL = 'Reading now.\n```tool_call\n{"name": "Read", "parameters": {"path": "/x"}}\n```'
FENCED_JSON_DATA = 'The config is:\n\n```json\n{"name": "acp-run", "version": 1}\n```\n'
GEMINI_CALL = 'print(default_api.read_file(path="/x/README.md"))'

# (text, real tool calls) -> expected "fake-tool-calls" or None
CASES = {
    "fable_final": [FABLE_FINAL, 0],
    "fable_final_with_tools": [FABLE_FINAL, 3],
    "function_calls": ["<function_calls>\n<invoke name=\"Bash\">\n</invoke>\n</function_calls>", 0],
    "bare_invoke": ["<invoke>x</invoke>", 0],
    "fenced_json_call": [FENCED_JSON_CALL, 0],
    "fenced_tool_call": [FENCED_TOOL_CALL, 0],
    "gemini": [GEMINI_CALL, 0],
    "quoted_in_fence": [REPORT_QUOTING_MARKUP, 3],
    "quoted_in_fence_no_tools": [REPORT_QUOTING_MARKUP, 0],
    "raw_quote_with_tools": [RAW_QUOTE, 2],
    "fenced_json_data": [FENCED_JSON_DATA, 0],
    "plain_report": ["STATUS: done\n\nAll good.\n\nDONE", 0],
    "empty": ["", 0],
}


def probe_tool_calls() -> dict[str, object]:
    code = textwrap.dedent("""\
        import importlib.machinery, importlib.util, io, json, sys, types
        loader = importlib.machinery.SourceFileLoader("acp_run", sys.argv[1])
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("acp_run", loader))
        loader.exec_module(mod)
        cases = json.load(sys.stdin)
        out = {k: mod.reply_failure(v[0], v[1], "", "deny") for k, v in cases.items()}
        out["msg_read_only"] = mod.reply_failure(cases["fable_final"][0], 0, "", "read-only")
        # the tripwire and the permission answer per perm mode and tool kind
        def trips(perm, kind, status="completed", agent="claude"):
            c = mod.RunClient(io.StringIO(), perm, "/tmp")
            c.exempt_kinds = mod.tripwire_exempt_kinds(agent, perm)
            c.check_tripwire(types.SimpleNamespace(
                tool_call_id="1", kind=kind, status=status, title=kind))
            return bool(c.tripped)
        def allows(perm, kind, title):
            c = mod.RunClient(io.StringIO(), perm, "/tmp")
            return c.decide(types.SimpleNamespace(kind=kind, title=title))
        out["trip"] = {f"{p}/{k}": trips(p, k) for p in ("deny", "read-only", "all")
                       for k in ("read", "search", "fetch", "execute", "edit", "other")}
        # codex's read-only session mode runs shell commands inside its own read-only sandbox
        # without asking (2026-10-19: `graft ask` tripped a research slice); only execute is contained
        out["trip_codex"] = {f"{p}/{k}": trips(p, k, agent="codex") for p in ("deny", "read-only")
                             for k in ("execute", "edit", "other", "read")}
        out["exempt_extra"] = sorted(mod.tripwire_exempt_kinds("agy", "all", "read,search"))
        out["decide"] = {"ro_read": allows("read-only", "read", "Read x"),
                         "ro_fetch": allows("read-only", "fetch", "WebFetch x"),
                         "ro_edit": allows("read-only", "edit", "Edit x"),
                         "ro_execute": allows("read-only", "execute", "Bash"),
                         "ro_title_grep": allows("read-only", None, "grep foo"),
                         "ro_other": allows("read-only", "other", "Mystery"),
                         "deny_read": allows("deny", "read", "Read x"),
                         "all_edit": allows("all", "edit", "Edit x")}
        out["modes"] = {a: mod.perm_modes(a) for a in
                        ("claude", "codex", "opencode", "zcode", "agy", "grok", "cursor", "crush")}
        out["claude_tools"] = mod.READONLY_META["claude"]["claudeCode"]["options"]["tools"]
        out["select_exit"] = [mod.select_exit("end_turn", "", 2, 0, 0, "read-only", None),
                              mod.select_exit("end_turn", "hi", 0, 0, 0, "read-only", None)]
        print(json.dumps(out))
        """)
    r = subprocess.run(
        ["uv", "run", "--quiet", "--with", "agent-client-protocol>=0.9,<1.0", "python", "-I", "-c", code,
         str(SCRIPT)], input=json.dumps(CASES), check=False, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return json.loads(r.stdout)


class TestFakeToolCalls(unittest.TestCase):
    res: ClassVar[dict[str, object]] = {}

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.res = probe_tool_calls()

    def cls_of(self, name: str) -> str | None:
        v = self.res[name]
        assert isinstance(v, list) or v is None
        return v[0] if v else None

    def test_real_transcript_is_a_fake_tool_call(self):
        self.assertEqual(self.cls_of("fable_final"), "fake-tool-calls")

    def test_every_markup_style_without_tools_fails(self):
        for name in ("function_calls", "bare_invoke", "fenced_json_call", "fenced_tool_call", "gemini"):
            self.assertEqual(self.cls_of(name), "fake-tool-calls", name)

    def test_real_tool_calls_make_the_same_text_pass(self):
        self.assertIsNone(self.cls_of("fable_final_with_tools"))
        self.assertIsNone(self.cls_of("raw_quote_with_tools"))

    def test_markup_quoted_in_a_code_block_passes(self):
        self.assertIsNone(self.cls_of("quoted_in_fence"))
        self.assertIsNone(self.cls_of("quoted_in_fence_no_tools"))

    def test_ordinary_replies_pass(self):
        for name in ("fenced_json_data", "plain_report", "empty"):
            self.assertIsNone(self.cls_of(name), name)

    def test_message_names_the_perm_mode_that_reads(self):
        deny = self.res["fable_final"]
        ro = self.res["msg_read_only"]
        assert isinstance(deny, list)
        assert isinstance(ro, list)
        self.assertIn("--perm read-only", deny[1])
        self.assertIn("--perm deny gives the agent no tools", deny[1])
        self.assertIn("--perm read-only lets the agent read", ro[1])


class TestReadOnlyPolicy(unittest.TestCase):
    res: ClassVar[dict[str, object]] = {}

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.res = probe_tool_calls()

    def test_tripwire_exempts_only_reading_kinds_under_read_only(self):
        trip = self.res["trip"]
        assert isinstance(trip, dict)
        for kind in ("read", "search", "fetch"):
            self.assertFalse(trip[f"read-only/{kind}"], kind)
        for kind in ("execute", "edit", "other"):
            self.assertTrue(trip[f"read-only/{kind}"], kind)
        self.assertTrue(trip["deny/read"])  # deny still trips on a read
        self.assertFalse(trip["all/execute"])

    def test_codex_sandboxed_execute_does_not_trip_under_read_only(self):
        trip = self.res["trip_codex"]
        assert isinstance(trip, dict)
        self.assertFalse(trip["read-only/execute"])  # contained by codex's read-only sandbox
        self.assertFalse(trip["read-only/read"])
        for kind in ("edit", "other"):
            self.assertTrue(trip[f"read-only/{kind}"], kind)
        self.assertTrue(trip["deny/execute"])  # deny gives codex no sandbox to lean on
        self.assertEqual(self.res["exempt_extra"], ["read", "search"])

    def test_permission_requests_are_answered_by_kind(self):
        d = self.res["decide"]
        assert isinstance(d, dict)
        self.assertTrue(d["ro_read"])
        self.assertTrue(d["ro_fetch"])
        self.assertTrue(d["ro_title_grep"])
        self.assertFalse(d["ro_edit"])
        self.assertFalse(d["ro_execute"])
        self.assertFalse(d["ro_other"])
        self.assertFalse(d["deny_read"])
        self.assertTrue(d["all_edit"])

    def test_supported_agents(self):
        m = self.res["modes"]
        assert isinstance(m, dict)
        for agent in ("claude", "codex", "opencode", "zcode"):
            self.assertIn("read-only", m[agent], agent)
        for agent in ("agy", "grok", "cursor", "crush"):
            self.assertNotIn("read-only", m[agent], agent)
        self.assertNotIn("deny", m["cursor"])

    def test_claude_gets_only_reading_tools(self):
        tools = self.res["claude_tools"]
        assert isinstance(tools, list)
        self.assertEqual(set(tools) & {"Edit", "Write", "Bash", "NotebookEdit", "Task"}, set())
        self.assertTrue({"Read", "Grep", "Glob"} <= set(tools))

    def test_empty_reply_message_names_the_mode(self):
        pair = self.res["select_exit"]
        assert isinstance(pair, list)
        empty, ok = pair
        self.assertEqual(empty[0], 1)
        self.assertIn("--perm read-only", empty[1])
        self.assertEqual(ok, [0, None])

    def test_unsupported_agent_is_refused_up_front(self):
        r = subprocess.run([str(SCRIPT), "grok", "--perm", "read-only", "-p", "x"], check=False,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("--perm read-only: grok:", r.stderr)


class TestDispatch(Base):
    def test_advise_with_deny_is_refused(self):
        r = self.dispatch_agent("claude", "fable", "--kind", "frontier", "--role", "advise", "--perm", "deny",
                                "--no-model-check", "--no-preflight", "--dry-run")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("--perm read-only", r.stderr)
        self.assertFalse((self.out / "jobs" / "s1.json").exists())

    def test_default_frontier_role_with_deny_is_refused(self):
        r = self.dispatch_agent("codex", "gpt-6-astra", "--kind", "frontier", "--perm", "deny",
                                "--no-model-check", "--no-preflight", "--dry-run")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("--role advise with --perm deny is refused", r.stderr)

    def test_exec_with_deny_still_runs(self):
        r = self.dispatch_agent("claude", "opus", "--kind", "judgment", "--perm", "deny",
                                "--no-model-check", "--no-preflight", "--min-headroom", "0", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_read_only_passes_through_and_is_stored(self):
        r = self.dispatch_agent("claude", "fable", "--kind", "frontier", "--role", "advise", "--perm", "read-only",
                                "--no-model-check", "--no-preflight", "--min-headroom", "0",
                                mode="stdout")
        rec = self.record()
        self.assertEqual(rec["perm"], "read-only")
        self.assertIn("--perm read-only", rec["cmd"])
        self.assertEqual(rec["report_source"], "final-message", r.stdout + r.stderr)
        brief = Path(rec["brief"]).read_text()
        self.assertIn("This run is read-only (`--perm read-only`)", brief)

    def test_fake_tool_calls_is_never_recovered_as_a_report(self):
        r = self.dispatch_agent("claude", "fable", "--kind", "frontier", "--perm", "all",
                                "--no-model-check", "--no-preflight", "--min-headroom", "0",
                                mode="fake_tool_calls")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        rec = self.record()
        self.assertEqual(rec["status"], "no-report")
        self.assertEqual(rec["report_source"], "final-message-failed")
        self.assertTrue(rec["failure"].startswith("NO-REPORT: fake-tool-calls (claude, fable)"), rec["failure"])
        self.assertIn("--perm read-only", rec["failure"])
        text = Path(rec["report"]).read_text()
        self.assertNotIn("recovered by acp-dispatch", text)
        self.assertNotIn("DONE", text.splitlines())
        c = run(["check", str(self.out / "jobs" / "s1.json")])
        self.assertEqual(c.returncode, 3, c.stdout)
        self.assertTrue(c.stdout.startswith("no-report\t"), c.stdout)
        self.assertIn("fake-tool-calls", c.stdout)


if __name__ == "__main__":
    unittest.main()
