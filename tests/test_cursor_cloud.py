#!/usr/bin/env python3
"""Tests for bin/cursor-cloud, the Cursor Cloud Agents launcher (2026-10-19).

Covers the request body (`launch_body`), the HTTP wrapper (`request`) and the CLI (`main`). No
test makes a network call or reads a real secret: `urllib.request.urlopen` and `request` are
patched, the API key is a fake string, and `os.execvpe` (the sudo-secretspec re-exec) is patched
to fail if reached.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import types
import unittest
import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "cursor-cloud"
FAKE_KEY = "fake-key-for-tests"


def load() -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader("cursor_cloud", str(SCRIPT))
    spec = importlib.util.spec_from_loader("cursor_cloud", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def ns(**kw: Any) -> argparse.Namespace:
    base: dict[str, Any] = {
        "repo": "https://github.com/o/r",
        "ref": "main",
        "prompt": "do the thing",
        "prompt_file": None,
        "model": None,
        "name": None,
        "work_on_branch": False,
        "plan": False,
    }
    return argparse.Namespace(**{**base, **kw})


def fake_response(raw: bytes) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = raw
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.cc = load()


class LaunchBodyTests(Base):
    def test_prompt_from_flag(self) -> None:
        body = self.cc.launch_body(ns(prompt="hello"))
        self.assertEqual(body["prompt"], {"text": "hello"})
        self.assertEqual(body["repos"], [{"url": "https://github.com/o/r", "startingRef": "main"}])

    def test_prompt_from_file(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "p.txt"
            _ = f.write_text("from a file\nline two\n")
            body = self.cc.launch_body(ns(prompt=None, prompt_file=str(f)))
        self.assertEqual(body["prompt"], {"text": "from a file\nline two\n"})

    def test_auto_create_pr_always_false(self) -> None:
        for work in (False, True):
            for plan in (False, True):
                body = self.cc.launch_body(ns(work_on_branch=work, plan=plan, model="m", name="n"))
                self.assertIs(body["autoCreatePR"], False)

    def test_work_on_current_branch_follows_flag(self) -> None:
        self.assertIs(self.cc.launch_body(ns(work_on_branch=False))["workOnCurrentBranch"], False)
        self.assertIs(self.cc.launch_body(ns(work_on_branch=True))["workOnCurrentBranch"], True)

    def test_optional_keys_absent_by_default(self) -> None:
        body = self.cc.launch_body(ns())
        for key in ("model", "name", "mode"):
            self.assertNotIn(key, body)

    def test_model_name_and_plan_when_given(self) -> None:
        body = self.cc.launch_body(ns(model="claude-x", name="my agent", plan=True))
        self.assertEqual(body["model"], {"id": "claude-x"})
        self.assertEqual(body["name"], "my agent")
        self.assertEqual(body["mode"], "plan")

    def test_name_truncated_to_100_chars(self) -> None:
        body = self.cc.launch_body(ns(name="x" * 250))
        self.assertEqual(body["name"], "x" * 100)

    def test_name_of_exactly_100_chars_kept(self) -> None:
        body = self.cc.launch_body(ns(name="y" * 100))
        self.assertEqual(body["name"], "y" * 100)

    def test_empty_prompt_exits_nonzero(self) -> None:
        for text in ("", "   \n\t"):
            with self.subTest(text=text), self.assertRaises(SystemExit) as cm:
                self.cc.launch_body(ns(prompt=text))
            self.assertNotIn(cm.exception.code, (0, None))
            self.assertIn("empty prompt", str(cm.exception.code))

    def test_empty_prompt_file_exits_nonzero(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "empty.txt"
            _ = f.write_text("\n")
            with self.assertRaises(SystemExit) as cm:
                self.cc.launch_body(ns(prompt=None, prompt_file=str(f)))
        self.assertNotIn(cm.exception.code, (0, None))


class RequestTests(Base):
    def call(self, resp_or_exc: Any, *args: Any, **kw: Any) -> tuple[Any, MagicMock]:
        with patch("urllib.request.urlopen") as urlopen:
            if isinstance(resp_or_exc, BaseException):
                urlopen.side_effect = resp_or_exc
            else:
                urlopen.return_value = resp_or_exc
            out = self.cc.request(*args, **kw)
        return out, urlopen

    def test_authorization_is_basic_key_colon(self) -> None:
        _, urlopen = self.call(fake_response(b"{}"), "GET", "/v1/models", key=FAKE_KEY)
        req = urlopen.call_args.args[0]
        expected = "Basic " + base64.b64encode(f"{FAKE_KEY}:".encode()).decode()
        self.assertEqual(req.get_header("Authorization"), expected)
        self.assertEqual(req.get_header("Accept"), "application/json")
        self.assertEqual(req.get_method(), "GET")
        self.assertTrue(req.full_url.endswith("/v1/models"))

    def test_key_defaults_to_environment(self) -> None:
        with patch.dict(os.environ, {"CURSOR_API_KEY": FAKE_KEY}):
            _, urlopen = self.call(fake_response(b"{}"), "GET", "/v1/models")
        req = urlopen.call_args.args[0]
        expected = "Basic " + base64.b64encode(f"{FAKE_KEY}:".encode()).decode()
        self.assertEqual(req.get_header("Authorization"), expected)

    def test_content_type_only_with_body(self) -> None:
        _, urlopen = self.call(fake_response(b"{}"), "GET", "/v1/models", key=FAKE_KEY)
        req = urlopen.call_args.args[0]
        self.assertFalse(req.has_header("Content-type"))
        self.assertIsNone(req.data)

        _, urlopen = self.call(fake_response(b"{}"), "POST", "/v1/agents", {"a": 1}, key=FAKE_KEY)
        req = urlopen.call_args.args[0]
        self.assertEqual(req.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(req.data), {"a": 1})
        self.assertEqual(req.get_method(), "POST")

    def test_http_error_exits_with_status(self) -> None:
        err = urllib.error.HTTPError("http://x", 403, "Forbidden", {}, io.BytesIO(b"nope"))  # type: ignore[arg-type]
        with self.assertRaises(SystemExit) as cm:
            self.call(err, "GET", "/v1/agents/abc", key=FAKE_KEY)
        msg = str(cm.exception.code)
        self.assertIn("HTTP 403", msg)
        self.assertIn("nope", msg)
        self.assertIn("/v1/agents/abc", msg)

    def test_empty_body_returns_empty_dict(self) -> None:
        out, _ = self.call(fake_response(b""), "GET", "/v1/models", key=FAKE_KEY)
        self.assertEqual(out, {})

    def test_json_body_is_parsed(self) -> None:
        out, _ = self.call(fake_response(b'{"id": "bc-1"}'), "GET", "/v1/agents/bc-1", key=FAKE_KEY)
        self.assertEqual(out, {"id": "bc-1"})


class CliTests(Base):
    def run_main(self, argv: list[str], env: dict[str, str] | None = None, clear: bool = True) -> tuple[int, str]:
        buf = io.StringIO()
        with patch.dict(os.environ, env or {}, clear=clear), contextlib.redirect_stdout(buf):
            rc = self.cc.main(argv)
        return rc, buf.getvalue()

    def test_dry_run_prints_body_without_key(self) -> None:
        with patch("os.execvpe", side_effect=AssertionError("must not re-exec")), patch.object(
            self.cc, "request", side_effect=AssertionError("must not call the API")
        ):
            rc, out = self.run_main(
                ["launch", "--repo", "https://github.com/o/r", "--ref", "main", "--prompt", "hi", "--dry-run"]
            )
        self.assertEqual(rc, 0)
        body = json.loads(out)
        self.assertEqual(body["prompt"], {"text": "hi"})
        self.assertIs(body["autoCreatePR"], False)
        self.assertIs(body["workOnCurrentBranch"], False)

    def test_dry_run_reflects_flags(self) -> None:
        rc, out = self.run_main(
            [
                "launch", "--repo", "r", "--ref", "b", "--prompt", "hi", "--dry-run",
                "--model", "m1", "--name", "nm", "--plan", "--work-on-branch",
            ]
        )  # fmt: skip
        self.assertEqual(rc, 0)
        body = json.loads(out)
        self.assertEqual(body["model"], {"id": "m1"})
        self.assertEqual(body["name"], "nm")
        self.assertEqual(body["mode"], "plan")
        self.assertIs(body["workOnCurrentBranch"], True)

    def test_missing_key_without_reexec_exits_nonzero(self) -> None:
        for argv in (["models"], ["launch", "--repo", "r", "--ref", "b", "--prompt", "hi"]):
            with self.subTest(argv=argv):
                with patch("os.execvpe", side_effect=AssertionError("must not re-exec")), patch.object(
                    self.cc, "request", side_effect=AssertionError("must not call the API")
                ), self.assertRaises(SystemExit) as cm:
                    _ = self.run_main(argv, env={"CURSOR_CLOUD_NO_REEXEC": "1"})
                self.assertNotIn(cm.exception.code, (0, None))
                self.assertIn("is not set", str(cm.exception.code))
                self.assertIn("CURSOR_API_KEY", str(cm.exception.code))

    def test_missing_key_reexecs_under_secretspec_once(self) -> None:
        class Reexec(Exception):
            pass

        with patch("os.execvpe", side_effect=Reexec) as execvpe, patch.object(
            self.cc, "request", side_effect=AssertionError("must not call the API")
        ), self.assertRaises(Reexec):
            _ = self.run_main(["models"], env={})
        cmd, argv, env = execvpe.call_args.args
        self.assertEqual(cmd, "sudo-secretspec")
        self.assertEqual(argv[:2], ["sudo-secretspec", "run"])
        self.assertEqual(argv[-1], "models")
        self.assertEqual(env["CURSOR_CLOUD_NO_REEXEC"], "1")

    def check_call(self, argv: list[str], expected: tuple[Any, ...]) -> str:
        env = {"CURSOR_API_KEY": FAKE_KEY}
        with patch.object(self.cc, "request", return_value={"ok": True}) as req:
            rc, out = self.run_main(argv, env=env)
        self.assertEqual(rc, 0)
        req.assert_called_once_with(*expected)
        self.assertEqual(json.loads(out), {"ok": True})
        return out

    def test_status(self) -> None:
        _ = self.check_call(["status", "bc-123"], ("GET", "/v1/agents/bc-123"))

    def test_conversation_subcommand_is_gone(self) -> None:
        with patch.dict(os.environ, {"CURSOR_API_KEY": FAKE_KEY}), patch.object(
            self.cc, "request", side_effect=AssertionError("must not call the API")
        ), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            _ = self.cc.main(["conversation", "bc-123"])
        self.assertNotEqual(cm.exception.code, 0)

    def test_usage(self) -> None:
        _ = self.check_call(["usage", "bc-123"], ("GET", "/v1/agents/bc-123/usage"))

    def test_run_with_explicit_run_id(self) -> None:
        _ = self.check_call(["run", "bc-123", "run-7"], ("GET", "/v1/agents/bc-123/runs/run-7"))

    def test_run_uses_latest_run_id(self) -> None:
        responses = [{"id": "bc-123", "latestRunId": "run-42"}, {"status": "FINISHED"}]
        with patch.object(self.cc, "request", side_effect=responses) as req:
            rc, out = self.run_main(["run", "bc-123"], env={"CURSOR_API_KEY": FAKE_KEY})
        self.assertEqual(rc, 0)
        self.assertEqual(
            [c.args for c in req.call_args_list],
            [("GET", "/v1/agents/bc-123"), ("GET", "/v1/agents/bc-123/runs/run-42")],
        )
        self.assertEqual(json.loads(out), {"status": "FINISHED"})

    def test_run_without_any_run_exits_nonzero(self) -> None:
        for agent in ({"id": "bc-123"}, {"id": "bc-123", "latestRunId": None}, {"id": "bc-123", "latestRunId": ""}):
            with self.subTest(agent=agent):
                with patch.object(self.cc, "request", return_value=agent) as req, self.assertRaises(SystemExit) as cm:
                    _ = self.run_main(["run", "bc-123"], env={"CURSOR_API_KEY": FAKE_KEY})
                self.assertNotIn(cm.exception.code, (0, None))
                self.assertIn("has no run yet", str(cm.exception.code))
                req.assert_called_once_with("GET", "/v1/agents/bc-123")

    def test_followup_posts_prompt_body(self) -> None:
        with patch.object(self.cc, "request", return_value={"id": "run-8"}) as req:
            rc, out = self.run_main(["followup", "bc-123", "--prompt", "more please"], env={"CURSOR_API_KEY": FAKE_KEY})
        self.assertEqual(rc, 0)
        req.assert_called_once_with("POST", "/v1/agents/bc-123/runs", {"prompt": {"text": "more please"}})
        self.assertEqual(json.loads(out), {"id": "run-8"})

    def test_followup_prompt_from_file(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "p.txt"
            _ = f.write_text("from a file\n")
            with patch.object(self.cc, "request", return_value={}) as req:
                rc, _ = self.run_main(["followup", "bc-123", "--prompt-file", str(f)], env={"CURSOR_API_KEY": FAKE_KEY})
        self.assertEqual(rc, 0)
        req.assert_called_once_with("POST", "/v1/agents/bc-123/runs", {"prompt": {"text": "from a file\n"}})

    def test_followup_empty_prompt_exits_nonzero(self) -> None:
        for text in ("", "  \n"):
            with self.subTest(text=text):
                with patch.object(self.cc, "request", side_effect=AssertionError("must not call the API")), \
                        self.assertRaises(SystemExit) as cm:
                    _ = self.run_main(["followup", "bc-123", "--prompt", text], env={"CURSOR_API_KEY": FAKE_KEY})
                self.assertNotIn(cm.exception.code, (0, None))
                self.assertIn("empty prompt", str(cm.exception.code))

    def test_list_with_limit(self) -> None:
        _ = self.check_call(["list", "--limit", "5"], ("GET", "/v1/agents?limit=5"))

    def test_list_default_limit(self) -> None:
        _ = self.check_call(["list"], ("GET", "/v1/agents?limit=20"))

    def test_models(self) -> None:
        _ = self.check_call(["models"], ("GET", "/v1/models"))

    def test_launch_posts_body(self) -> None:
        env = {"CURSOR_API_KEY": FAKE_KEY}
        with patch.object(self.cc, "request", return_value={"agent": {"id": "bc-9"}}) as req:
            rc, out = self.run_main(
                ["launch", "--repo", "https://github.com/o/r", "--ref", "main", "--prompt", "go"], env=env
            )
        self.assertEqual(rc, 0)
        method, path, body = req.call_args.args
        self.assertEqual((method, path), ("POST", "/v1/agents"))
        self.assertEqual(body["prompt"], {"text": "go"})
        self.assertIs(body["autoCreatePR"], False)
        self.assertEqual(json.loads(out), {"agent": {"id": "bc-9"}})


if __name__ == "__main__":
    unittest.main()
