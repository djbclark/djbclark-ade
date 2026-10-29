"""herdr prompt detection in bin/self-slash's waiter: a prompt far above the bottom of the screen, a pane that is
busy, and a pane with no prompt at all (the 2026-10-23/24 "gave up, no empty input prompt seen" failures)."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get('SELF_SLASH_SCRIPT', ROOT / 'bin/self-slash'))
GREY = '\x1b[38;2;153;153;153m'
RESET = '\x1b[0m'
PROMPT = f'❯ {GREY}Try "fix the tests"{RESET}'
SPINNER = '✻ Cultivating… (1m 4s · ↓ 2.8k tokens)'

# A herdr whose `agent read --lines N` returns the last N rows of the screen it is told to show.  The screen
# changes with the number of reads (FAKE_BUSY_READS reads of FAKE_BUSY_SCREEN first) and after `pane run`.
FAKE_HERDR = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
a = sys.argv[1:]
calls = Path(os.environ['FAKE_CALLS'])
with calls.open('a') as f: f.write(json.dumps(a) + '\n')
status = os.environ.get('FAKE_STATUS', 'idle')
reads = Path(str(calls) + '.reads')

def screen():
    n = int(reads.read_text()) if reads.exists() else 0
    reads.write_text(str(n + 1))
    if Path(str(calls) + '.ran').exists():
        return os.environ['FAKE_SCREEN_AFTER']
    if n < int(os.environ.get('FAKE_BUSY_READS', '0')):
        return os.environ['FAKE_BUSY_SCREEN']
    return os.environ['FAKE_SCREEN']

if a[:2] == ['pane', 'get']:
    print(json.dumps({'result': {'pane': {'pane_id': 'fake:p1', 'agent': 'claude', 'agent_status': status}}}))
elif a[:2] == ['pane', 'list']:
    print(json.dumps({'result': {'panes': [{'pane_id': 'fake:p1', 'agent_status': status}]}}))
elif a[:2] == ['agent', 'read']:
    rows = screen().split('\n')
    n = int(a[a.index('--lines') + 1])
    print('\n'.join(rows[-n:]))
elif a[:2] == ['pane', 'run']:
    Path(str(calls) + '.ran').write_text('1')
else:
    print('{}')
'''


def screen(*rows: str) -> str:
    return '\n'.join(rows)


class PromptWaitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.home = base / 'home'
        self.home.mkdir()
        bindir = base / 'bin'
        bindir.mkdir()
        for name, body in (('herdr', FAKE_HERDR), ('sleep', '#!/usr/bin/env python3\nimport time\ntime.sleep(0.01)\n')):
            _ = (bindir / name).write_text(body)
            (bindir / name).chmod(0o755)
        self.calls = base / 'calls.jsonl'
        self.log = self.home / '.local/state/self-slash.log'
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('HERDR_', 'ORCA_', 'PASEO_', 'SELF_SLASH_', 'ACP_RUN_AGENT', 'FAKE_'))}
        self.env.update(HOME=str(self.home), PATH=f'{bindir}:{os.environ["PATH"]}', HERDR_ENV='1',
                        HERDR_PANE_ID='fake:p1', FAKE_CALLS=str(self.calls), SELF_SLASH_WAIT='300',
                        FAKE_SCREEN_AFTER=screen('transcript', PROMPT, 'status'))

    def run_waiter(self, **extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([str(SCRIPT), '--delay', '0', '/context'], env=dict(self.env, SELF_SLASH_CHILD='1', **extra),
                              capture_output=True, text=True, timeout=60, check=False)

    def typed(self) -> list[list[str]]:
        calls = [json.loads(ln) for ln in self.calls.read_text().splitlines()] if self.calls.exists() else []
        return [c for c in calls if c[:2] == ['pane', 'run']]

    def test_a_prompt_more_than_12_rows_above_the_bottom_is_found(self) -> None:
        # a multi-row status area, hook output or queued-message list under the input box
        rows = [PROMPT] + [f'status row {i}' for i in range(25)]
        r = self.run_waiter(FAKE_SCREEN=screen(*rows))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.typed(), [['pane', 'run', 'fake:p1', '/context']])

    def test_a_draft_far_above_the_bottom_is_still_never_typed_over(self) -> None:
        rows = ['❯ half a sentence the operator is typing'] + [f'status row {i}' for i in range(25)]
        r = self.run_waiter(FAKE_SCREEN=screen(*rows), SELF_SLASH_WAIT='20')
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertEqual(self.typed(), [])

    def test_a_pane_busy_for_longer_than_the_idle_polls_is_waited_for(self) -> None:
        # no prompt for 40 reads while a spinner line is on screen: more than the 9 polls an idle pane gets
        busy = screen('output', SPINNER, 'status')
        r = self.run_waiter(FAKE_SCREEN=screen('transcript', PROMPT, 'status'), FAKE_BUSY_SCREEN=busy,
                            FAKE_BUSY_READS='80')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('busy', r.stdout + r.stderr + (self.log.read_text() if self.log.exists() else ''))
        self.assertEqual(self.typed(), [['pane', 'run', 'fake:p1', '/context']])

    def test_a_pane_the_herdr_status_calls_working_is_waited_for(self) -> None:
        # herdr's own status: wait_idle lets a working pane with no spinner through (a background sub-agent), but a
        # pane with NO prompt on screen and a working status is not ready either
        r = self.run_waiter(FAKE_SCREEN=screen('transcript', PROMPT), FAKE_BUSY_SCREEN=screen('output', 'more output'),
                            FAKE_BUSY_READS='80', FAKE_STATUS='working')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.typed(), [['pane', 'run', 'fake:p1', '/context']])

    def test_a_busy_pane_that_never_shows_a_prompt_ends_at_the_wait_limit_sending_nothing(self) -> None:
        busy = screen('output', SPINNER, 'status')
        r = self.run_waiter(FAKE_SCREEN=busy, FAKE_BUSY_SCREEN=busy, FAKE_BUSY_READS='100000', SELF_SLASH_WAIT='30')
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn('gave up, no empty input prompt seen', r.stdout + r.stderr + self.log.read_text())
        self.assertEqual(self.typed(), [])

    def test_an_idle_pane_with_no_prompt_gives_up_after_a_few_polls_sending_nothing(self) -> None:
        plain = screen('$ ls', 'file', '$')
        r = self.run_waiter(FAKE_SCREEN=plain)
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertEqual(self.typed(), [])
        self.assertLess(len([ln for ln in self.calls.read_text().splitlines() if '"agent", "read"' in ln]), 60)


if __name__ == '__main__':
    unittest.main()
