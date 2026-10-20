#!/usr/bin/env python3
"""Tests for bin/ade-template-check (2026-10-20, Phase 0 item 4.4): the credential scan, the
render-and-parse check and --diff over the agents/ templates. The real templates are in the
repo, so nothing here needs the live config files."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import base64
import json
import os
import random
import tempfile
import time
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

    def test_no_template_keeps_a_literal_home_path(self):
        for rel in atc.LIVE:
            text = (REPO / "agents" / rel).read_text()
            bare = text.replace("{{ .home }}", "").replace("{{ .home_escaped }}", "")
            with self.subTest(rel):
                self.assertNotIn("/Users/", bare)
                self.assertNotIn("/home/", bare)
                self.assertNotIn("literal home path", {rule for _, rule in atc.scan(text)})


class ScanTest(unittest.TestCase):
    def rules(self, text: str) -> set[str]:
        return {rule for _, rule in atc.scan(text)}

    def test_planted_values_fail(self):
        # every value is synthetic: repeated or counted characters, example.org, a 555-01xx number
        hex32 = "0123456789abcdef" * 2
        cases = [
            ("sk- key", 'x = "sk-abcdef123456"'),
            ("xai- key", 'x = "xai-' + "yz" * 15 + '"'),
            ("GitHub gh?_ token", "t = ghp_abcdefgh12345678"),
            ("GitHub gh?_ token", "t = ghs_abcdefgh12345678"),
            ("GitHub gh?_ token", "t = ghu_abcdefgh12345678"),
            ("GitHub gh?_ token", "t = ghr_abcdefgh12345678"),
            ("github_pat_ token", "t = github_pat_11ABCDEFG0abcdefgh"),
            ("GitLab glpat- token", "t = glpat-" + "ab12" * 5),
            ("Google AIza key", "k = AIza" + "Ab0" * 11 + "A"),
            ("Telegram bot token", "bot = 123456789:" + "AAF" * 11),
            ("Slack token", "t = xoxb-123456-abcdef"),
            ("AWS key id", "k = AKIAABCDEFGHIJKLMNOP"),
            ("Bearer value", '"Authorization": "Bearer abcdefghijkl"'),
            ("Bearer value", '"Authorization": "Bearer {{ secret "X" }}abcdefgh12345"'),
            ("Bearer value", "Authorization: Bearer ${X}abcdefgh12345"),
            ("PEM block", "-----BEGIN PRIVATE KEY-----"),
            ("password=", "psql password=hunter22"),
            ("api_key=", "curl api_key=abc123"),
            ("token=", "url?token=abc123"),
            ("token=", "url?token={{ .x }}abc123"),
            ("secret-looking key: value", "client_secret: abcdefgh"),
            ("secret-looking key: value", f'"x-api-key": "{hex32}"'),
            ("secret-looking key: value", f"api-key: {hex32}"),
            ("secret-looking key: value", f'"token": "{hex32}"'),
            ("secret-looking key: value", f"token: {hex32}"),
            ("secret-looking key: value", f'token = "{hex32}"'),
            ("secret-looking key: value", '"X-Auth-Token": "abcd1234"'),
            ("secret-looking key: value", 'bot_token = "abcd1234"'),
            ("secret-looking key: value", "password_hash: abcd1234"),
            ("secret-looking key: value", 'private_key = "abcd1234"'),
            ("secret-looking key: value", "credential: abcd1234"),
            ("secret-looking key: value", '"x-api-key": "{{ secret "X" }}abcd1234"'),
            ("email address", "mail a.b@example.org"),
            ("phone number", "n: +15555550100"),
            ("phone number", "n: +44 20 7946 0958"),
            ("phone number", "n: +49 30 901820"),
            ("UUID", "id 123e4567-e89b-12d3-a456-426614174000"),
            ("long numeric id", "chat: 1234567890123456789"),
            ("literal home path", 'p = "/Users/alex/bin"'),
            ("32+ character hex string", "h = " + hex32),
            ("32+ character base64-like string", "k = " + "A1B2C3D4E5F6G7H8I9J0" + "KkLlMmNnOoPpQq"),
            # round 2 of the adversary review: Authorization with any scheme or none, in JSON, YAML and TOML
            ("Authorization header", '"Authorization": "Basic dXNlcjpwYXNzd29yZDEyMw=="'),
            ("Authorization header", '"Authorization": "Token abcdefgh12345678"'),
            ("Authorization header", '"Authorization": "abcdefgh12345678"'),
            ("Authorization header", '"Authorization": "Bot abcdefgh12345678"'),
            ("Authorization header", "Authorization: Basic dXNlcjpwYXNzd29yZDEyMw=="),
            ("Authorization header", 'Authorization = "Digest abcdefgh12345678"'),
            ("Authorization header", 'http_headers = { "authorization" = "Token abcdefgh12345678" }'),
            ("Authorization header", "Proxy-Authorization: Basic dXNlcjpwYXNzd29yZDEyMw=="),
            ("Authorization header", r'printf "{\"Authorization\":\"Basic dXNlcjpwYXNzd29yZDEyMw==\"}"'),
            ("Authorization header", '"Authorization": "Basic {{ secret "X" }}dXNlcjpw"'),
            # a Discord bot token, bare and as a dot-joined run that is no Discord shape
            ("Discord bot token", '  - "' + "MTIzNDU2Nzg5MDEyMzQ1Njc4" + ".Ab3-_x." + "q1W2e3R4t5Y6u7I8o9P0a1S2d3F4" + '"'),
            ("dot-joined token", "jwt: " + "eyJhbGci1Xy9k" + ".eyJzdWIi2Zq7mA" + ".SflKxwRJ3SMeKKF2"),
            # key names ending in _KEY, _SECRET, _TOKEN or _PASSWORD, any case
            ("secret-looking key: value", 'SERVICE_KEY = "abcd1234"'),
            ("secret-looking key: value", "svc_secret: abcd1234"),
            ("secret-looking key: value", '"slack-token": "abcd1234"'),
            ("secret-looking key: value", "DB_PASSWORD=abcd1234"),
            # argv pairs and query parameters
            ("credential flag argument", 'args = ["--token", "abcd1234"]'),
            ("credential flag argument", "args: [--api-key, abcd1234]"),
            ("credential flag argument", "  - --password\n  - abcd1234"),
            ("credential flag argument", 'args = [\n  "--secret",\n  "abcd1234",\n]'),
            ("credential flag argument", "command: tool --api-key abcd1234"),
            ("password=", 'args = ["--password=abcd1234"]'),
            ("credential in a URL query", 'u = "https://x.example/api?key=abcd1234"'),
            ("credential in a URL query", 'u = "https://x.example/api?a=1&access_token=abcd1234"'),
            ("credential in a URL query", 'u = "https://x.example/api?sig=abcd1234"'),
            # a key whose `/` cut it into segments under SEGMENT_MIN is not a path
            ("32+ character base64-like string", 'v = "Ab3dE6gH9jK2/mN5pQ8sT1vW4yZ7/bC0eF3hI6kL9/nP2qR5tU8w"'),
            ("32+ character base64-like string", 'v = "/Ab3dE6gH9jK2mN5pQ8sT1vW4yZ7bC0eF3hI6kL9nP2qR5tU8w"'),
            # a long key between path pieces
            ("32+ character base64-like string", 'v = "/opt/x/Ab3dE6gH9jK2mN5pQ8sT1vW4yZ7bC0eF3hI6kL9nP2/bin"'),
        ]
        for rule, text in cases:
            with self.subTest(text[:40]):
                self.assertIn(rule, self.rules(text))

    def test_random_base64_keys_never_pass_under_a_key_name(self):
        # 1a of the 2026-10-20 adversary review: 15-38% of base64 keys passed through the old `/` exemption
        rng = random.Random(20261020)
        for nbytes in (32, 48, 64):
            keys = [base64.b64encode(rng.randbytes(nbytes)).decode() for _ in range(500)]
            with self.subTest(nbytes):
                passed = [k for k in keys if not atc.scan(f'"x-api-key": "{k}"')]
                self.assertEqual(passed, [])
                # with a neutral key name only the generic rule applies; a letters-only or digit-free key can
                # slip through (about 1 in 1000), a `/` exemption must not
                bare = [k for k in keys if not atc.scan(f'"v": "{k}"')]
                self.assertLessEqual(len(bare), 2)

    def test_random_hex_and_alnum_keys_under_key_names(self):
        rng = random.Random(7)
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        for name in ("x-api-key", "api-key", "token", "X-Auth-Token"):
            for _ in range(100):
                for value in (rng.randbytes(16).hex(), "".join(rng.choice(alphabet) for _ in range(40))):
                    with self.subTest(name):
                        self.assertTrue(atc.scan(f'"{name}": "{value}"'))

    def test_authorization_headers_and_dotted_tokens_never_pass(self):
        # R2-1 of the 2026-10-20 adversary review: every scheme, and Discord's dotted shape, bare and under Bot
        rng = random.Random(20261021)
        alnum = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        url = alnum + "_-"

        def pick(alphabet, n):
            return "".join(rng.choice(alphabet) for _ in range(n))

        def discord():
            ident = base64.b64encode(str(rng.randint(10**17, 10**19)).encode()).decode().rstrip("=")
            return f"{ident}.{pick(url, rng.choice((6, 7)))}.{pick(url, rng.randint(27, 38))}"

        def basic():
            return base64.b64encode(f"user:{pick(alnum, rng.randint(8, 24))}".encode()).decode()

        shapes = {
            "Basic": (basic, '"Authorization": "Basic %s"'),
            "Token": (lambda: pick(alnum, 24), '"Authorization": "Token %s"'),
            "no scheme": (lambda: pick(alnum, 24), '"Authorization": "%s"'),
            "Bot": (discord, '"Authorization": "Bot %s"'),
            "Bearer": (lambda: pick(alnum, 24), '"Authorization": "Bearer %s"'),
            "yaml": (basic, "Authorization: Basic %s"),
            "toml": (basic, 'Authorization = "Basic %s"'),
            "discord bare in a list": (discord, '  - "%s"'),
            "discord bare in yaml": (discord, "x: %s"),
        }
        for name, (gen, ctx) in shapes.items():
            with self.subTest(name):
                passed = [v for v in (gen() for _ in range(2000)) if not atc.scan(ctx % v)]
                self.assertEqual(passed, [])

    def test_key_names_flags_and_query_parameters_never_pass(self):
        rng = random.Random(20261022)
        alnum = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        contexts = (
            'SERVICE_KEY = "%s"', "svc_secret: %s", '"bot-token": "%s"', "DB_PASSWORD = '%s'",
            'args = ["--token", "%s"]', 'args = ["--api-key=%s"]', "run: tool --password %s",
            "  - --secret\n  - %s", 'url = "https://x.example/api?key=%s"', 'url = "https://x.example/a?x=1&token=%s"',
        )
        for ctx in contexts:
            with self.subTest(ctx):
                values = ("".join(rng.choice(alnum) for _ in range(24)) for _ in range(500))
                self.assertEqual([v for v in values if not atc.scan(ctx % v)], [])

    def test_escaped_quotes_around_keys_and_values_are_scanned(self):
        # Codex PR 23 finding 2: a TOML or JSON command string holding escaped header JSON
        value = "Zq7Lm2Xw9Rt4Vb8Nc3Hd6Fk1"
        for name, text in {
            "toml single escape": r"""command = "printf '{\"x-api-key\":\"%s\"}'" """ % value,
            "toml double-quoted header": r"""command = "printf \"{\"x-api-key\":\"%s\"}\"" """ % value,
            "json single escape": r'''"command": "printf '{\"x-api-key\":\"%s\"}'"''' % value,
            "triple escape": r"""command = "printf '{\\\"x-api-key\\\":\\\"%s\\\"}'" """ % value,
            "short value": r"""command = "printf '{\"x-api-key\":\"abcd1234\"}'" """,
            "single-quoted escape": r"""command = "printf \'{\'api_key\':\'%s\'}\'" """ % value,
        }.items():
            with self.subTest(name):
                self.assertIn("secret-looking key: value", self.rules(text))
        for name, text in {
            "env ref": r"""command = "printf '{\"x-api-key\":\"${X}\"}'" """,
            "secret tag": r"""command = "printf '{\"x-api-key\":\"{{ secret "X" }}\"}'" """,
            "triple escape tag": r"""command = "printf '{\\\"x-api-key\\\":\\\"{{ secret "X" }}\\\"}'" """,
            "printf arg": r"""command = "printf '{\"x-api-key\":\"%s\"}' \"$KEY\"" """,
        }.items():
            with self.subTest(name):
                self.assertEqual(self.rules(text), set())

    @unittest.skipUnless(HAVE_YAML, "PyYAML not importable")
    def test_yaml_block_scalar_values_are_scanned(self):
        # Codex PR 23 finding 1: `api_key: >-` and the value on the next line, under the 32-character blob floor
        value = "Zq7Lm2Xw9Rt4Vb8Nc3Hd6Fk1"
        for indicator in ("|", "|-", ">", ">-", "|+"):
            with self.subTest(indicator):
                hits = atc.scan(f"hermes:\n  api_key: {indicator}\n    {value}\n", "yaml")
                self.assertEqual(hits, [(2, "secret-looking key: value")])
        self.assertTrue(atc.scan(f"- token: |\n    {value}\n", "yaml"))
        self.assertTrue(atc.scan(f"token:\n  - >-\n    {value}\n", "yaml"))
        for name, text in {
            "secret tag": 'api_key: >-\n  {{ secret "X" }}\n',
            "literal secret tag": 'api_key: |\n  {{ secret "X" }}\n',
            "env ref": "api_key: |-\n  ${X}\n",
            "env ref folded": "api_key: >\n  ${X}\n",
            "not a credential key": f"note: |\n  {value}\n",
            "comment block": "# api_key is set in the vault\n# token handling:\n#   see the docs\nname: x\n",
            "empty block": "api_key: |\n\nname: x\n",
        }.items():
            with self.subTest(name):
                self.assertEqual(atc.scan(text, "yaml"), [])
        # a tag with a tail after it is a hit, as on one line
        self.assertTrue(atc.scan('api_key: >-\n  {{ secret "X" }}tail1234\n', "yaml"))

    @unittest.skipUnless(HAVE_YAML, "PyYAML not importable")
    def test_yaml_block_scalar_is_a_finding_through_the_cli(self):
        rc, out = Root(self, "a:\n  api_key: >-\n    Zq7Lm2Xw9Rt4Vb8Nc3Hd6Fk1\n", name="t/c.yaml.tmpl").check()
        self.assertEqual(rc, 1)
        self.assertIn("t/c.yaml.tmpl:2: credential scan: secret-looking key: value", out)
        self.assertNotIn("Zq7Lm2Xw9Rt4Vb8Nc3Hd6Fk1", out)

    def test_values_off_the_keys_line_are_scanned_in_toml_and_json(self):
        # adversary round 6 R6-1: the YAML pass's gap in the other two formats, 20-character synthetic keys
        value = "Zq7Lm2Xw9Rt4Vb8Nc3Hd"
        planted = {
            "T1 basic multi-line string": ("toml", f'[a]\napi_key = """\n{value}"""\n', 2),
            "T2 literal multi-line string": ("toml", f"[a]\napi_key = '''\n{value}'''\n", 2),
            "T3 multi-line array": ("toml", f'[a]\ntoken = [\n  "{value}",\n]\n', 2),
            "J1 next-line value": ("json", f'{{\n  "x-api-key":\n    "{value}"\n}}\n', 2),
            "J2 array": ("json", f'{{"token": [\n  "{value}"\n]}}\n', 1),
        }
        for name, (kind, text, line) in planted.items():
            with self.subTest(name):
                self.assertEqual(atc.scan(text, kind), [(line, "secret-looking key: value")])
        clean = {
            "T1 secret tag": ("toml", 'api_key = """\n{{ secret "X" }}"""\n'),
            "T2 secret tag": ("toml", "api_key = '''\n{{ secret \"X\" }}'''\n"),
            "T2 env ref": ("toml", "api_key = '''\n${X}'''\n"),
            "T3 secret tag": ("toml", 'token = [\n  "{{ secret "X" }}",\n]\n'),
            "T3 env ref": ("toml", 'token = [\n  "${X}",\n]\n'),
            "J1 secret tag": ("json", '{"x-api-key":\n  "{{ secret "X" }}"}\n'),
            "J1 env ref": ("json", '{"x-api-key":\n  "${X}"}\n'),
            "not a credential key": ("toml", f"note = '''\n{value}'''\n"),
        }
        for name, (kind, text) in clean.items():
            with self.subTest(name):
                self.assertEqual(atc.scan(text, kind), [])

    def test_a_toml_or_json_hit_is_reported_once_and_at_the_keys_line(self):
        value = "Zq7Lm2Xw9Rt4Vb8Nc3Hd"
        # the line scan already reports a same-line value: the parsed pass adds nothing
        self.assertEqual(atc.scan(f'api_key = "{value}"\n', "toml"), [(1, "secret-looking key: value")])
        self.assertEqual(atc.scan(f'{{"api_key": "{value}"}}\n', "json"), [(1, "secret-looking key: value")])
        # two entries with one key name: the same-line one is reported once, the multi-line one at its own line
        text = f'a = {{ token = "{value}" }}\nb = {{ token = """\n{value}""" }}\n'
        self.assertEqual(sorted(atc.scan(text, "toml")), [(1, "secret-looking key: value"), (2, "secret-looking key: value")])

    @unittest.skipUnless(HAVE_YAML, "PyYAML not importable")
    def test_authorization_block_scalar_is_scanned_in_every_format(self):
        # adversary round 6 R6-2: the parsed pass runs the Authorization rule too
        value = "Zq7Lm2Xw9Rt4Vb8Nc3Hd"
        for kind, text in {
            "yaml": f"Authorization: >-\n  Basic {value}\n",
            "toml": f"Authorization = '''\nBasic {value}'''\n",
            "json": f'{{"Authorization":\n  "Basic {value}"}}\n',
        }.items():
            with self.subTest(kind):
                self.assertIn("Authorization header", {r for _, r in atc.scan(text, kind)})
        self.assertEqual(atc.scan('Authorization: >-\n  Basic {{ secret "X" }}\n', "yaml"), [])
        self.assertEqual(atc.scan("Authorization: >-\n  Bearer ${X}\n", "yaml"), [])

    @unittest.skipUnless(HAVE_YAML, "PyYAML not importable")
    def test_yaml_aliases_do_not_recurse_or_blow_up(self):
        # adversary round 6 R6-4.1: a self-referencing alias and a 2**10 alias tree
        value = "Zq7Lm2Xw9Rt4Vb8Nc3Hd"
        self.assertEqual(atc.scan("a: &a [*a]\n", "yaml"), [])
        self.assertEqual(atc.scan("a: &a {x: *a}\n", "yaml"), [])
        # an alias reached under a credential key is still read under that key, even in a cycle
        self.assertTrue(atc.scan(f"d: &d [{value}]\napi_key: *d\n", "yaml"))
        tree = ["l0: &l0 [x]"] + [f"l{i}: &l{i} [*l{i - 1}, *l{i - 1}]" for i in range(1, 11)]
        tree.append("api_key: *l10\n")
        start = time.monotonic()
        atc.scan("\n".join(tree), "yaml")
        self.assertLess(time.monotonic() - start, 5)

    def test_literal_escaped_home_path_fails(self):
        self.assertIn("literal home path", self.rules(r'p = "\/Users\/alex\/bin"'))

    def test_base64_like_blob_fails_but_a_path_does_not(self):
        key = "Zm9vYmFyQmF6MTIzNDU2Nzg5MEFCQ0RFRkdISUpLTE1OT1BRUg"
        self.assertIn("32+ character base64-like string", self.rules(f'k = "{key}"'))
        long_path = "{{ .home }}/ops/site-private/bin/graft-hook-guard-wrapper-for-claude-code.sh"
        self.assertEqual(self.rules(f'p = "{long_path}"'), set())
        self.assertIn("32+ character hex string", self.rules("h = " + "ab12" * 12))
        # identifiers and dated paths of 32+ characters are not keys
        for text in (
            '"skipDangerousModePermissionPrompt": true',
            'NODE_REPL_TRUSTED_BROWSER_CLIENT_SHA256S = "{{ .x }}"',
            'p = "{{ .home }}/Documents/Codex/2026-07-18/files-mentioned-by-the-user-next"',
            "keepRemoteControlAwakeWhilePluggedIn = true",
        ):
            with self.subTest(text):
                self.assertEqual(self.rules(text), set())

    def test_placeholders_and_references_are_clean(self):
        for text in (
            '"Authorization": "Bearer {{ secret "JINA_API_KEY" }}"',
            "Authorization: Bearer ${MCP_X_API_KEY}",
            'api_key: ${OPENAI_API_KEY}',
            "password: ''",
            "api_key_env: MIT_SIPB_API_KEY",
            'home_channel: \'{{ .signal_account }}\'',
            'printf "Bearer %s" "$KEY"',
            '"x-api-key": "{{ secret "EXA_API_KEY" }}"',
            'token = "{{ secret "X" }}"',
            "password_hash: '{{ secret \"X\" }}'",
            "Authorization: Bearer $KEY",
            '"Authorization": "Bearer {{ secret "X" }}"',
            "Authorization: Basic ${X}",
            'Authorization = "Basic {{ secret "X" }}"',
            "Authorization: $X",
            'authorization: ""',
            'args = ["--token", "{{ secret "X" }}"]',
            "args: [--token, ${T}]",
            'args = ["--password-file", "/etc/pw"]',
            'args = ["--max-tokens", "40000"]',
            'url = "https://x.example/api?key={{ secret "X" }}"',
            "key_env: HERMES_CLINE_API_KEY",
            'SERVICE_KEY = "{{ secret "X" }}"',
            "plugin: com.example.long-service-name.region1.v2.node3",
            '"max_tokens": 4096',
            "plugins: disk-cleanup task-runner",
        ):
            with self.subTest(text):
                self.assertEqual(self.rules(text), set())

    def test_the_orca_hook_blob_is_allowlisted_by_hash_only(self):
        blob = next(iter(
            b for b in atc.BLOB.findall((REPO / "agents/claude/settings.json.tmpl").read_text()) if len(b) > 1000
        ))
        self.assertEqual(self.rules(f'"command": "x {blob}"'), set())
        self.assertIn("32+ character base64-like string", self.rules(f'"command": "x {blob}AAAAqwerty1Z"'))

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

    @unittest.skipUnless(HAVE_YAML, "PyYAML not importable")
    def test_yaml_placeholder_must_be_quoted(self):
        rc, out = Root(self, "a: {{ .host }}\n", name="t/c.yaml.tmpl").check()
        self.assertEqual(rc, 1)
        self.assertIn("hostile", out)
        rc, out = Root(self, "a: '{{ .host }}'\nb: '{{ secret \"JINA_API_KEY\" }}'\n", name="t/c.yaml.tmpl").check()
        self.assertEqual(rc, 0, out)

    def test_json_and_toml_placeholders_survive_a_hostile_value(self):
        rc, out = Root(self, '{"h": "x{{ .host }}y", "a": "Bearer {{ secret "JINA_API_KEY" }}"}').check()
        self.assertEqual(rc, 0, out)
        rc, out = Root(self, 'a = "{{ .host }}"\nb = "{{ secret "JINA_API_KEY" }}"\n', name="t/c.toml.tmpl").check()
        self.assertEqual(rc, 0, out)
        # a TOML literal string cannot hold a quote escape: the hostile value breaks it
        rc, out = Root(self, "a = '{{ .host }}'\n", name="t/c.toml.tmpl").check()
        self.assertEqual(rc, 1)
        self.assertIn("hostile", out)

    def test_hostile_roundtrip_helper(self):
        for kind, body in (("json", '{"a": "{{ .host }}"}'), ("toml", 'a = "{{ .host }}"\n')):
            with self.subTest(kind):
                self.assertTrue(atc.hostile_roundtrip(kind, body, {"host"}, set()))
        self.assertEqual(atc.escape_for("yaml", "a'b"), "a''b")
        self.assertEqual(atc.escape_for("json", 'a"b\\c'), 'a\\"b\\\\c')

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
