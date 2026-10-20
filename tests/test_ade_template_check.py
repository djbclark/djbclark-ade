#!/usr/bin/env python3
"""Tests for bin/ade-template-check (2026-10-20, Phase 0 item 4.4): the credential scan, the
render-and-parse check and --diff over the agents/ templates. The real templates are in the
repo, so nothing here needs the live config files."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "bin" / "ade-template-check"

_loader = importlib.machinery.SourceFileLoader("ade_template_check", str(SCRIPT))
_spec = importlib.util.spec_from_loader("ade_template_check", _loader)
atc = importlib.util.module_from_spec(_spec)
_loader.exec_module(atc)

try:
    import yaml  # noqa: F401
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False

README = """| Field | Meaning |
|---|---|
| `home` | home |
| `home_escaped` | home, escaped |
| `host` | a host |
| `JINA_API_KEY` | secret |
"""


def run(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    rc = atc.main(list(argv), out=out)
    return rc, out.getvalue()


class Root:
    """A throwaway repo root with agents/README.md and one json template."""

    def __init__(self, test: unittest.TestCase, body: str, name: str = "t/x.json.tmpl", readme: str = README):
        self.dir = Path(tempfile.mkdtemp())
        test.addCleanup(lambda: __import__("shutil").rmtree(self.dir))
        (self.dir / "agents").mkdir()
        (self.dir / "agents" / "README.md").write_text(readme)
        self.tmpl = self.dir / "agents" / name
        self.tmpl.parent.mkdir(parents=True, exist_ok=True)
        self.tmpl.write_text(body)

    def check(self, *extra: str) -> tuple[int, str]:
        return run("--root", str(self.dir), *extra, str(self.tmpl))


class RealTemplatesTest(unittest.TestCase):
    def test_every_live_mapping_has_a_template(self):
        for rel in atc.LIVE:
            self.assertTrue((REPO / "agents" / rel).is_file(), rel)

    def test_real_templates_pass(self):
        for rel in atc.LIVE:
            if rel.endswith(".yaml.tmpl") and not HAVE_YAML:
                continue
            with self.subTest(rel):
                rc, out = run(str(REPO / "agents" / rel))
                self.assertEqual(rc, 0, out)

    @unittest.skipUnless(HAVE_YAML, "PyYAML not importable")
    def test_default_run_covers_all_four(self):
        rc, out = run()
        self.assertEqual(rc, 0, out)
        self.assertIn("4 template(s), 0 finding(s)", out)

    def test_no_template_leaks_a_home_path_or_dollar_secret(self):
        for rel in atc.LIVE:
            text = (REPO / "agents" / rel).read_text()
            self.assertNotIn("/Users/", text.replace("{{ .home }}", ""), rel)


class ScanTest(unittest.TestCase):
    def rules(self, text: str) -> set[str]:
        return {rule for _, rule in atc.scan(text)}

    def test_planted_values_fail(self):
        cases = {
            "sk- key": 'x = "sk-abcdef123456"',
            "ghp_/gho_ token": "t = ghp_abcdefgh12345678",
            "github_pat_ token": "t = github_pat_11ABCDEFG0abcdefgh",
            "Slack token": "t = xoxb-123456-abcdef",
            "AWS key id": "k = AKIAABCDEFGHIJKLMNOP",
            "Bearer value": '"Authorization": "Bearer abcdefghijkl"',
            "PEM block": "-----BEGIN PRIVATE KEY-----",
            "password=": "psql password=hunter22",
            "api_key=": "curl api_key=abc123",
            "token=": "url?token=abc123",
            "secret-looking key: value": "client_secret: abcdefgh",
            "email address": "mail a.b@example.org",
            "phone number": "n: +15555550100",
            "UUID": "id 123e4567-e89b-12d3-a456-426614174000",
            "long numeric id": "chat: 1234567890123456789",
            "literal home path": 'p = "/Users/alex/bin"',
        }
        for rule, text in cases.items():
            with self.subTest(rule):
                self.assertIn(rule, self.rules(text))

    def test_literal_escaped_home_path_fails(self):
        self.assertIn("literal home path", self.rules(r'p = "\/Users\/alex\/bin"'))

    def test_base64_like_blob_fails_but_a_path_does_not(self):
        key = "Zm9vYmFyQmF6MTIzNDU2Nzg5MEFCQ0RFRkdISUpLTE1OT1BRUg"
        self.assertIn("40+ character base64-like string", self.rules(f'k = "{key}"'))
        long_path = "{{ .home }}/ops/site-private/bin/graft-hook-guard-wrapper-for-claude-code.sh"
        self.assertEqual(self.rules(f'p = "{long_path}"'), set())
        self.assertIn("40+ character hex string", self.rules("h = " + "ab12" * 12))

    def test_placeholders_and_references_are_clean(self):
        for text in (
            '"Authorization": "Bearer {{ secret "JINA_API_KEY" }}"',
            "Authorization: Bearer ${MCP_X_API_KEY}",
            'api_key: ${OPENAI_API_KEY}',
            "password: ''",
            "api_key_env: MIT_SIPB_API_KEY",
            'home_channel: \'{{ .signal_account }}\'',
            'printf "Bearer %s" "$KEY"',
            "plugins: disk-cleanup task-runner",
        ):
            with self.subTest(text):
                self.assertEqual(self.rules(text), set())

    def test_the_orca_hook_blob_is_allowlisted_by_hash_only(self):
        blob = next(iter(
            b for b in atc.BLOB.findall((REPO / "agents/claude/settings.json.tmpl").read_text()) if len(b) > 1000
        ))
        self.assertEqual(self.rules(f'"command": "x {blob}"'), set())
        self.assertIn("40+ character base64-like string", self.rules(f'"command": "x {blob}AAAAqwerty1Z"'))

    def test_findings_never_print_the_value(self):
        secret = "sk-SUPERSECRETVALUE99"
        r = Root(self, json.dumps({"k": secret}), name="t/x.json.tmpl")
        rc, out = r.check()
        self.assertEqual(rc, 1)
        self.assertIn("sk- key", out)
        self.assertNotIn("SUPERSECRET", out)


class RenderTest(unittest.TestCase):
    def test_clean_template_with_documented_placeholders_passes(self):
        body = '{"p": "{{ .home }}/x", "h": "{{ .host }}", "a": "Bearer {{ secret "JINA_API_KEY" }}"}'
        rc, out = Root(self, body).check()
        self.assertEqual(rc, 0, out)

    def test_undocumented_field_and_secret_fail(self):
        rc, out = Root(self, '{"h": "{{ .nope }}", "s": "{{ secret "NOPE_KEY" }}"}').check()
        self.assertEqual(rc, 1)
        self.assertIn("field `nope`", out)
        self.assertIn("secret `NOPE_KEY`", out)

    def test_other_tag_forms_fail(self):
        rc, out = Root(self, '{"h": "{{ env "HOME" }}"}').check()
        self.assertEqual(rc, 1)
        self.assertIn("other than", out)

    def test_unparseable_render_fails(self):
        rc, out = Root(self, '{"h": {{ .home }}').check()
        self.assertEqual(rc, 1)
        self.assertIn("does not parse as json", out)

    def test_toml_render(self):
        rc, out = Root(self, 'a = "{{ .home }}"\nb = 1\n', name="t/c.toml.tmpl").check()
        self.assertEqual(rc, 0, out)
        rc, out = Root(self, 'a = "{{ .home }}\nb = ', name="t/c.toml.tmpl").check()
        self.assertEqual(rc, 1)
        self.assertIn("does not parse as toml", out)

    @unittest.skipUnless(HAVE_YAML, "PyYAML not importable")
    def test_yaml_render(self):
        rc, out = Root(self, "a: '{{ .host }}'\nb:\n  - 1\n", name="t/c.yaml.tmpl").check()
        self.assertEqual(rc, 0, out)
        rc, out = Root(self, "a: [unclosed\n", name="t/c.yaml.tmpl").check()
        self.assertEqual(rc, 1)

    def test_no_templates_is_usage_error(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(d))
        rc, _ = run("--root", str(d))
        self.assertEqual(rc, 2)


class DiffTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.home))
        (self.home / ".claude").mkdir()

    def test_diff_prints_key_paths_never_values(self):
        live = {
            "path": f"{self.home}/bin",
            "host": "real-host-name.example",
            "same": 1,
            "changed": "LIVE-VALUE-ONE",
            "extra": {"deep": "LIVE-EXTRA-VALUE"},
        }
        (self.home / ".claude" / "settings.json").write_text(json.dumps(live))
        body = '{"path": "{{ .home }}/bin", "host": "{{ .host }}", "same": 1, "changed": "tmpl-value", "mine": true}'
        r = Root(self, body, name="claude/settings.json.tmpl")
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            rc, out = r.check("--diff")
        self.assertEqual(rc, 0, out)
        self.assertIn("only in template: mine", out)
        self.assertIn("only in live file: extra.deep", out)
        self.assertIn("differs: changed", out)
        self.assertNotIn("differs: path", out)
        self.assertNotIn("differs: host", out)
        for value in ("LIVE-VALUE-ONE", "LIVE-EXTRA-VALUE", "tmpl-value", "real-host-name"):
            self.assertNotIn(value, out)

    def test_diff_without_a_live_file_says_so(self):
        r = Root(self, '{"a": 1}', name="claude/settings.json.tmpl")
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            rc, out = r.check("--diff")
        self.assertEqual(rc, 0, out)
        self.assertIn("no live file to compare", out)

    def test_diff_escaped_home(self):
        (self.home / ".claude" / "settings.json").write_text(json.dumps({"n": json.dumps([f"{self.home}/h"])}))
        r = Root(self, '{"n": "[\\"{{ .home }}/h\\"]"}', name="claude/settings.json.tmpl")
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            rc, out = r.check("--diff")
        self.assertEqual(rc, 0, out)
        self.assertIn("0 only in template, 0 only in live, 0 differ", out)


if __name__ == "__main__":
    unittest.main()
