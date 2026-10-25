#!/usr/bin/env python3
"""zcode --perm read-only / deny really remove the disallowed tools, and zcode's bare model name
(2026-10-24).

Live finding: `zcode app-server --stdio` ignores --disallowed-tools and zcode-acp-server's
session/create carries no toolDenylist, so READONLY_ENV's ZCODE_DISALLOWED_TOOLS and the setting.json
permission.disallowedTools never took effect; a read-only run was offered Bash, Edit and Write and
ran `ls` unasked. acp-run now starts the backend through tools/acp-run/zcode-denylist-shim.cjs,
which adds toolDenylist / toolAllowlist to session/create|resume|send. The shim is run here as
node against a fake backend that echoes the frames it receives. acp-run is loaded in a `uv run
--with` subprocess, as test_acp_run_read_only.py does.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import ClassVar, override

import test_acp_dispatch_effort as eff

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("ACP_RUN_SCRIPT", str(ROOT / "tools" / "acp-run" / "acp-run")))
NODE = shutil.which("node")

# zcode's real model option values (acp-run zcode --info, 2026-10-24)
ZCODE_MODELS = [{"value": v, "name": v} for v in (
    "builtin:zai\\GLM-5.3", "builtin:zai\\GLM-5.3-Flash",
    "builtin:zai-coding-plan\\GLM-5.3", "builtin:zai-coding-plan\\GLM-5.3-Flash")]

FAKE_BACKEND = "process.stdin.pipe(process.stdout);\n"  # echoes every frame the shim forwards

PROBE = textwrap.dedent("""\
    import importlib.machinery, importlib.util, json, os, sys, tempfile
    from pathlib import Path
    loader = importlib.machinery.SourceFileLoader("acp_run", sys.argv[1])
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("acp_run", loader))
    loader.exec_module(mod)
    vendor = Path(sys.argv[2])
    models = json.loads(sys.argv[3])
    out = {}
    os.environ["HOME"] = tempfile.mkdtemp()
    for perm, make in (("read-only", mod.zcode_readonly_settings), ("deny", mod.zcode_deny_settings)):
        env = dict(mod.READONLY_ENV["zcode"] if perm == "read-only" else mod.DENY_ENV["zcode"])
        env["ZCODE_BIN"] = str(vendor / "zcode.cjs")
        d = make()
        mod.zcode_denylist_shim(d, env, perm)
        shim = Path(env["ZCODE_BIN"])
        out[perm] = {"env": env, "shim": str(shim), "shim_target": os.path.realpath(shim),
                     "provider": (shim.parent / "provider" / "zcode-builtin.json").is_file(),
                     "under_deny_dir": str(shim).startswith(str(d)), "dir": str(d)}
    # no real zcode entry: fails closed instead of running unguarded
    d = mod.zcode_readonly_settings()
    try:
        mod.zcode_denylist_shim(d, {"ZCODE_BIN": str(vendor / "missing.cjs")}, "read-only")
        out["missing"] = "no error"
    except mod.ConfigError as e:
        out["missing"] = str(e)
    mod.remove_deny_dir(d)
    out["match"] = {w: (mod.match_value(models, w)[0] or {}).get("value")
                    for w in ("GLM-5.3", "glm-5.3", "GLM-5.3-Flash", "builtin:zai\\\\GLM-5.3",
                              "builtin:zai-coding-plan\\\\GLM-5.3-Flash")}
    print(json.dumps(out))
    """)


def probe(vendor: Path) -> dict[str, object]:
    r = subprocess.run(
        ["uv", "run", "--quiet", "--with", "agent-client-protocol>=0.9,<1.0", "python", "-I", "-c", PROBE,
         str(SCRIPT), str(vendor), json.dumps(ZCODE_MODELS)], check=False, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return json.loads(r.stdout)


def frames(shim: str, env: dict[str, str], lines: list[str]) -> list[str]:
    """Run the shim as node with the fake backend behind it; the lines it forwards."""
    assert NODE
    r = subprocess.run([NODE, shim, "app-server", "--stdio"], input="\n".join(lines) + "\n",
                       env={**os.environ, **env}, check=False, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.splitlines()


@unittest.skipUnless(NODE, "node is needed to run the zcode shim")
class ZcodeToolRemoval(unittest.TestCase):
    res: ClassVar[dict[str, object]] = {}
    tmp: ClassVar[Path]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp())
        vendor = cls.tmp / "vendor"
        (vendor / "provider").mkdir(parents=True)
        (vendor / "provider" / "zcode-builtin.json").write_text("{}")
        (vendor / "zcode.cjs").write_text(FAKE_BACKEND)
        cls.res = probe(vendor)

    @classmethod
    @override
    def tearDownClass(cls) -> None:
        for perm in ("read-only", "deny"):
            r = cls.res.get(perm)
            if isinstance(r, dict):
                shutil.rmtree(str(r["dir"]), ignore_errors=True)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def sent(self, perm: str) -> dict[str, dict]:
        r = self.res[perm]
        assert isinstance(r, dict)
        out = frames(r["shim"], dict(r["env"]), [
            json.dumps({"id": 1, "method": "session/create", "params": {"workspace": {"path": "/x"}}}),
            json.dumps({"id": 2, "method": "session/send", "params": {"sessionId": "s", "input": "hi"}}),
            json.dumps({"id": 3, "method": "session/resume",
                        "params": {"sessionId": "s", "toolDenylist": ["Custom"]}}),
            json.dumps({"id": 4, "method": "session/list", "params": {}}),
            "not json {",
        ])
        assert len(out) == 5, out
        return {"create": json.loads(out[0]), "send": json.loads(out[1]), "resume": json.loads(out[2]),
                "list": json.loads(out[3]), "raw": out[4]}  # type: ignore[dict-item]

    def test_read_only_session_offers_no_mutating_tool(self):
        s = self.sent("read-only")
        for kind in ("create", "send", "resume"):
            deny = s[kind]["params"]["toolDenylist"]
            for tool in ("Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "Task", "Agent"):
                self.assertIn(tool, deny, f"{kind}: {tool}")
            self.assertNotIn("Read", deny, kind)
            self.assertNotIn("Glob", deny, kind)
        # the reading tools are all that is allowed at create and resume
        for kind in ("create", "resume"):
            allow = set(s[kind]["params"]["toolAllowlist"])
            self.assertEqual(allow, {"Read", "Glob", "Grep", "LS", "WebFetch", "WebSearch"}, kind)
        self.assertNotIn("toolAllowlist", s["send"]["params"])  # session/send's schema has none
        self.assertIn("Custom", s["resume"]["params"]["toolDenylist"])  # a caller's own entries stay
        self.assertEqual(s["create"]["params"]["workspace"], {"path": "/x"})

    def test_deny_session_offers_no_tool_at_all(self):
        s = self.sent("deny")
        for kind in ("create", "resume"):
            self.assertEqual(s[kind]["params"]["toolAllowlist"], ["acp-run-deny-no-tool"], kind)
        for tool in ("Bash", "Read", "Write", "Glob", "Grep", "WebFetch"):
            self.assertIn(tool, s["create"]["params"]["toolDenylist"], tool)

    def test_other_frames_pass_through_untouched(self):
        for perm in ("read-only", "deny"):
            s = self.sent(perm)
            self.assertEqual(s["list"], {"id": 4, "method": "session/list", "params": {}})
            self.assertEqual(s["raw"], "not json {")

    def test_acp_run_starts_the_backend_through_the_shim(self):
        for perm in ("read-only", "deny"):
            r = self.res[perm]
            assert isinstance(r, dict)
            self.assertTrue(r["under_deny_dir"], "the shim dir is inside the per-run dir that is swept")
            self.assertEqual(Path(str(r["shim_target"])).name, "zcode-denylist-shim.cjs")
            self.assertTrue(r["provider"], "provider tables sit next to the shim, or model switches break")
            env = r["env"]
            assert isinstance(env, dict)
            self.assertEqual(env["ZCODE_ACP_RUN_REAL_BIN"], str((self.tmp / "vendor" / "zcode.cjs").resolve()))
            self.assertTrue(str(env["ZCODE_BIN"]).endswith("zcode.cjs"))  # a .cjs, so node launches it

    def test_no_real_zcode_entry_fails_closed(self):
        self.assertIn("needs zcode's vendor/zcode.cjs", str(self.res["missing"]))

    def test_bare_model_name_is_the_coding_plan_pool(self):
        m = self.res["match"]
        assert isinstance(m, dict)
        cp = "builtin:zai-coding-plan\\"
        self.assertEqual(m["GLM-5.3"], cp + "GLM-5.3")
        self.assertEqual(m["glm-5.3"], cp + "GLM-5.3")
        self.assertEqual(m["GLM-5.3-Flash"], cp + "GLM-5.3-Flash")
        self.assertEqual(m["builtin:zai\\GLM-5.3"], "builtin:zai\\GLM-5.3")  # a full id still wins
        self.assertEqual(m["builtin:zai-coding-plan\\GLM-5.3-Flash"], cp + "GLM-5.3-Flash")


class DispatchBareZcodeModel(unittest.TestCase):
    def test_acp_dispatch_accepts_the_bare_name_and_full_ids(self):
        for want in ("GLM-5.3", "glm-5.3", "GLM-5.3-Flash", "builtin:zai-coding-plan\\GLM-5.3",
                     "builtin:zai\\GLM-5.3"):
            self.assertTrue(eff.acpd.match_model(ZCODE_MODELS, want)[0], want)
        ok, why = eff.acpd.match_model(ZCODE_MODELS, "GLM-9")
        self.assertFalse(ok)
        self.assertIn("have: builtin:zai\\GLM-5.3", why)


if __name__ == "__main__":
    unittest.main()
