"""Codex lifecycle submission preserves drafts and survives launcher teardown."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get('SELF_SLASH_SCRIPT', ROOT / 'bin/self-slash'))
spec = importlib.util.spec_from_file_location('prompt_line', ROOT / 'skills/session-finder/prompt_line.py')
prompt_line = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prompt_line)
BG = '\x1b[48;2;65;69;76m'


def screen(text='\x1b[2mAsk Codex to do anything\x1b[0m', continuation=''):
    return f'{BG}› {text}\x1b[0m\n{BG}{continuation}\x1b[0m\nGPT-6.1-Sol high · ~/src/example\n'


class CodexComposerTests(unittest.TestCase):
    def test_dim_placeholder_is_empty_but_a_leading_blank_draft_is_preserved(self):
        self.assertEqual(prompt_line.classify(screen(), '›'), '')
        self.assertEqual(prompt_line.classify(screen('typed draft'), '›'), 'typed draft')
        self.assertEqual(prompt_line.classify(screen('', 'second line draft'), '›'), 'second line draft')

    def test_unbounded_transcript_quotes_are_not_a_composer(self):
        self.assertIsNone(prompt_line.classify('› quoted transcript\nordinary output', '›'))


class CodexWaiterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / 'home'
        self.home.mkdir()
        bindir = self.base / 'bin'
        bindir.mkdir()
        fake = bindir / 'herdr'
        fake.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
a = sys.argv[1:]
with open(os.environ['FAKE_CALLS'], 'a') as f: f.write(json.dumps(a)+'\\n')
if a[:2] == ['pane', 'get']:
 print(json.dumps({'result': {'pane': {'pane_id': 'fake:p1', 'agent': 'codex'}}}))
elif a[:2] == ['agent', 'get']:
 print(json.dumps({'result': {'agent': {'agent': 'codex'}}}))
elif a[:2] == ['pane', 'list']:
 print(json.dumps({'result': {'panes': [{'pane_id': 'fake:p1', 'agent_status': os.environ.get('FAKE_STATUS', 'idle')}]}}))
elif a[:2] == ['agent', 'read']:
 print(os.environ['FAKE_SCREEN'])
elif a[:2] == ['agent', 'prompt']:
 sys.exit(int(os.environ.get('FAKE_SUBMIT_RC', '0')))
else:
 print('{}')
''')
        fake.chmod(0o755)
        sleep = bindir / 'sleep'
        sleep.write_text('#!/usr/bin/env python3\nimport time\ntime.sleep(0.02)\n')
        sleep.chmod(0o755)
        self.calls = self.base / 'calls.jsonl'
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('HERDR_', 'ORCA_', 'PASEO_', 'SELF_SLASH_', 'ACP_RUN_AGENT', 'BASH_ENV'))}
        self.env.update(HOME=str(self.home), PATH=f'{bindir}:{os.environ["PATH"]}',
                        HERDR_ENV='1', HERDR_PANE_ID='fake:p1', FAKE_CALLS=str(self.calls),
                        FAKE_SCREEN=screen(), SELF_SLASH_THEN_DELAY='0')

    def run_waiter(self, *args, **extra):
        return subprocess.run([str(SCRIPT), '--delay', '0', *args],
                              env=dict(self.env, SELF_SLASH_CHILD='1', **extra),
                              capture_output=True, text=True, timeout=20)

    def submitted(self):
        return [a for a in map(json.loads, self.calls.read_text().splitlines())
                if a[:2] in (['agent', 'prompt'], ['pane', 'run'], ['agent', 'send-keys'])]

    def test_new_then_one_targeted_baton_uses_atomic_agent_submission(self):
        p = subprocess.run([str(SCRIPT), '--delay', '0', '--then',
                            '/baton /exact/chain/SESSION_LOG.md', '/new'],
                           env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        log = self.home / '.local/state/self-slash.log'
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if log.exists() and 'sent /baton /exact/chain/SESSION_LOG.md' in log.read_text():
                break
            time.sleep(0.02)
        self.assertEqual(self.submitted(), [
            ['agent', 'prompt', 'fake:p1', '/new'],
            ['agent', 'prompt', 'fake:p1', '/baton /exact/chain/SESSION_LOG.md']])

    def test_blocked_unknown_and_working_states_never_submit(self):
        for status in ['blocked', 'unknown', 'working']:
            with self.subTest(status=status):
                p = self.run_waiter('--no-then', '/new', FAKE_STATUS=status, SELF_SLASH_WAIT='0')
                self.assertEqual(p.returncode, 6, p.stdout + p.stderr)
        self.assertEqual(self.submitted(), [])

    def test_multiline_draft_never_submits_and_ambiguous_failure_never_retries(self):
        p = self.run_waiter('--no-then', '/new', FAKE_SCREEN=screen('', 'keep this draft'), SELF_SLASH_WAIT='0')
        self.assertEqual(p.returncode, 4, p.stdout + p.stderr)
        self.assertEqual(self.submitted(), [])
        p = self.run_waiter('--no-then', '/new', FAKE_SUBMIT_RC='1')
        self.assertEqual(p.returncode, 8, p.stdout + p.stderr)
        self.assertEqual(self.submitted(), [['agent', 'prompt', 'fake:p1', '/new']])

    def test_detached_waiter_has_its_own_process_session(self):
        p = subprocess.run([str(SCRIPT), '--delay', '0', '--no-then', '/new'],
                           env=dict(self.env, FAKE_STATUS='working', SELF_SLASH_WAIT='10000'),
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr)
        lock = self.home / '.local/state/self-slash/herdr_fake_p1.lifecycle'
        pid = int(lock.read_text().split()[0])
        try:
            self.assertEqual(os.getsid(pid), pid)
            self.assertNotEqual(os.getsid(pid), os.getsid(0))
            self.assertEqual(self.submitted(), [])
        finally:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
