#!/usr/bin/env python3
"""acp-dispatch --effort / --context (2026-10-15): passed to acp-run first-class, checked together with
the model (`acp-run <agent> --info --model M --effort E --context C` exits 2 naming the valid values),
recorded in the job record and the resume record; --acp-arg keeps working; zcode accepts --model.
acp-run is a fake shell script, as in test_acp_dispatch.py."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import unittest
from pathlib import Path

import test_acp_dispatch as base

ROOT = Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader("acp_dispatch_effort", str(base.SCRIPT))
_spec = importlib.util.spec_from_loader("acp_dispatch_effort", _loader)
acpd = importlib.util.module_from_spec(_spec)
_loader.exec_module(acpd)

# the fake from test_acp_dispatch.py plus: --info with --effort/--context exits 2 when FAKE_OPT_BAD is set,
# and every real (non --info, non preflight) call records its argv in $ARGS_FILE
FAKE = base.FAKE.replace('''# fake acp-run: args are <agent> -C DIR -f BRIEF --model M --perm P --timeout S --log LOG
''', '''# fake acp-run: args are <agent> -C DIR -f BRIEF --model M --perm P --timeout S --log LOG
case " $* " in *" --info "*)
  case " $* " in *" --effort "*|*" --context "*)
    [ -n "$OPT_COUNT" ] && echo "$*" >> "$OPT_COUNT"
    [ -n "$FAKE_OPT_BAD" ] && { echo "acp-run: codex m1 has no effort 'max'; valid: low, medium, high" >&2; exit 2; };;
  esac;;
  *) case " $* " in *"Reply with exactly: OK"*) ;; *) [ -n "$ARGS_FILE" ] && printf '%s\\n' "$@" > "$ARGS_FILE";; esac;;
esac
''')
assert FAKE != base.FAKE


class Effort(base.Base):
    @property
    def args_file(self) -> Path:
        return self.tmp / "args"

    def setUp(self) -> None:
        super().setUp()
        self.fake.write_text(FAKE)

    def env(self, **extra: str) -> dict[str, str]:
        return {"ARGS_FILE": str(self.args_file), "OPT_COUNT": str(self.tmp / "opt-count"), **extra}

    def test_flags_reach_acp_run_after_the_model_and_the_record_keeps_them(self):
        r = self.dispatch("--effort", "low", "--context", "500k", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = self.args_file.read_text().split()
        i = argv.index("--model")
        self.assertEqual(argv[i:i + 6], ["--model", "m1", "--effort", "low", "--context", "500k"])
        rec = self.record()
        self.assertEqual((rec["effort"], rec["context"]), ("low", "500k"))
        self.assertIn("--effort low --context 500k", rec["cmd"])

    def test_without_the_flags_nothing_changes(self):
        r = self.dispatch(env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("--effort", self.args_file.read_text())
        self.assertFalse((self.tmp / "opt-count").exists())  # no extra probe
        rec = self.record()
        self.assertEqual((rec["effort"], rec["context"]), (None, None))

    def test_the_effort_is_checked_with_the_model_before_anything_is_written(self):
        r = self.dispatch("--effort", "max", env=self.env(FAKE_OPT_BAD="1"))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("codex: codex m1 has no effort 'max'; valid: low, medium, high", r.stderr)
        self.assertFalse((self.out / "jobs" / "s1.json").exists())
        probe = (self.tmp / "opt-count").read_text()
        self.assertIn("--model m1 --effort max", probe)

    def test_no_model_check_skips_the_option_check_too(self):
        r = self.dispatch("--effort", "max", "--no-model-check", env=self.env(FAKE_OPT_BAD="1"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.tmp / "opt-count").exists())

    def test_dry_run_prints_the_command_with_the_flags(self):
        r = self.dispatch("--dry-run", "--context", "1m", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--model m1 --context 1m --perm all", r.stdout)

    def test_acp_arg_still_passes_through(self):
        r = self.dispatch("--effort", "high", "--acp-arg=--meta", '--acp-arg={"a":1}', env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = self.args_file.read_text().split("\n")
        self.assertEqual(argv[-3:-1], ["--meta", '{"a":1}'])
        self.assertIn("--effort", argv)

    def test_zcode_accepts_a_model_now_and_still_does_not_need_one(self):
        r = self.dispatch_agent("zcode", "GLM-5.3-Flash", "--no-model-check", "--dry-run", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--model GLM-5.3-Flash", r.stdout)
        r = base.run(["zcode", "--kind", "bulk", "--name", "z", "-p", "hi", "--out", str(self.out),
                      "--acp-run", str(self.fake), "--dry-run", "-C", str(self.repo)],
                     env=self.base_env("writes", **self.env()))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_resume_keeps_the_flags(self):
        r = self.dispatch("--effort", "low", "--context", "500k", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = self.record()
        self.assertEqual((rec["effort"], rec["context"]), ("low", "500k"))
        # resume rebuilds its Namespace from the record; effort/context must be read from it
        src = Path(base.SCRIPT).read_text()
        self.assertIn('effort=rec.get("effort"), context=rec.get("context")', src)


class MatchModel(unittest.TestCase):
    def test_mirrors_acp_run_for_suffixes_and_provider_prefixes(self):
        qwen = [{"value": "qwen3.8-max(openai)", "name": "qwen3.8-max"}, {"value": "glm-5(openai)", "name": "glm-5"}]
        self.assertTrue(acpd.match_model(qwen, "qwen3.8-max")[0])
        hermes = [{"value": "nous:anthropic/claude-sonnet-5.5", "name": "S"}, {"value": "p:other/gpt-6", "name": "G"}]
        self.assertTrue(acpd.match_model(hermes, "claude-sonnet-5.5")[0])
        ok, why = acpd.match_model(hermes, "kimi")
        self.assertFalse(ok)
        self.assertIn("have: nous:anthropic/claude-sonnet-5.5, p:other/gpt-6", why)
        amb = [{"value": "a:x/gpt-6", "name": "A"}, {"value": "b:y/gpt-6", "name": "B"}]
        self.assertIn("ambiguous", acpd.match_model(amb, "gpt-6")[1])


if __name__ == "__main__":
    unittest.main()
