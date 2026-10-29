"""herdr prompt detection in bin/self-slash's waiter: a prompt far above the bottom of the screen, a pane that is
busy, and a pane with no prompt at all (the 2026-10-23/24 "gave up, no empty input prompt seen" failures)."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get('SELF_SLASH_SCRIPT', ROOT / 'bin/self-slash'))
GREY = '\x1b[38;2;153;153;153m'
RESET = '\x1b[0m'
PROMPT = f'❯ {GREY}Try "fix the tests"{RESET}'
SPINNER = '✻ Cultivating… (1m 4s · ↓ 2.8k tokens)'
RULE = '─' * 60

# A herdr whose `agent read --lines N` returns the last N rows of the screen it is told to show.  The screen
# changes with the number of reads (FAKE_BUSY_READS reads of FAKE_BUSY_SCREEN first) and after `pane run`.
FAKE_HERDR = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
a = sys.argv[1:]
calls = Path(os.environ['FAKE_CALLS'])
with calls.open('a') as f: f.write(json.dumps(a) + '\n')
status = os.environ.get('FAKE_STATUS', 'idle')
clock = Path(os.environ['FAKE_CLOCK'])
clock.write_text(str((float(clock.read_text()) if clock.exists() else 0.0) + float(os.environ.get('FAKE_CALL_COST', '0'))))
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
    print(json.dumps({'result': {'pane': {'pane_id': 'fake:p1', 'agent': os.environ.get('FAKE_AGENT', 'claude'), 'agent_status': status}}}))
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

# A clock that only the fake `sleep` and the fake herdr move (FAKE_CALL_COST seconds per herdr call), so the
# waiter's wall-clock budget is testable without waiting.  `gdate +%s` reads it; any other gdate call is real.
FAKE_SLEEP = r'''#!/usr/bin/env python3
import os, sys, time
from pathlib import Path
clock = Path(os.environ['FAKE_CLOCK'])
clock.write_text(str((float(clock.read_text()) if clock.exists() else 0.0) + float(sys.argv[1] if len(sys.argv) > 1 else 0)))
time.sleep(0.01)
'''
FAKE_GDATE = r'''#!/usr/bin/env python3
import os, sys
from pathlib import Path
if sys.argv[1:] == ['+%s'] and not os.environ.get('FAKE_REAL_CLOCK'):
    clock = Path(os.environ['FAKE_CLOCK'])
    print(1000000000 + int(float(clock.read_text()) if clock.exists() else 0))
else:
    os.execv(os.environ['REAL_GDATE'], [os.environ['REAL_GDATE'], *sys.argv[1:]])
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
        for name, body in (('herdr', FAKE_HERDR), ('sleep', FAKE_SLEEP), ('gdate', FAKE_GDATE)):
            _ = (bindir / name).write_text(body)
            (bindir / name).chmod(0o755)
        self.calls = base / 'calls.jsonl'
        self.log = self.home / '.local/state/self-slash.log'
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('HERDR_', 'ORCA_', 'PASEO_', 'SELF_SLASH_', 'ACP_RUN_AGENT', 'FAKE_'))}
        self.env.update(HOME=str(self.home), PATH=f'{bindir}:{os.environ["PATH"]}', HERDR_ENV='1',
                        HERDR_PANE_ID='fake:p1', FAKE_CALLS=str(self.calls), FAKE_CLOCK=str(base / 'clock'),
                        REAL_GDATE=shutil.which('gdate') or 'gdate', SELF_SLASH_WAIT='300',
                        FAKE_SCREEN_AFTER=screen('transcript', PROMPT, 'status'))

    def run_waiter(self, **extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([str(SCRIPT), '--delay', '0', '/context'], env=dict(self.env, SELF_SLASH_CHILD='1', **extra),
                              capture_output=True, text=True, timeout=60, check=False)

    def typed(self) -> list[list[str]]:
        calls = [json.loads(ln) for ln in self.calls.read_text().splitlines()] if self.calls.exists() else []
        return [c for c in calls if c[:2] == ['pane', 'run']]

    def reads(self) -> int:
        return len([ln for ln in self.calls.read_text().splitlines() if '"agent", "read"' in ln])

    def out(self, r: subprocess.CompletedProcess[str]) -> str:
        return r.stdout + r.stderr + (self.log.read_text() if self.log.exists() else '')

    # --- a prompt beyond the bottom 12 rows: only the live input box counts ---
    def test_a_live_prompt_more_than_12_rows_above_the_bottom_is_found(self) -> None:
        # a multi-row status area, hook output or queued-message list under the input box
        rows = [RULE, PROMPT, RULE] + [f'status row {i}' for i in range(25)]
        r = self.run_waiter(FAKE_SCREEN=screen(*rows))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.typed(), [['pane', 'run', 'fake:p1', '/context']])

    def test_a_draft_far_above_the_bottom_is_still_never_typed_over(self) -> None:
        rows = [RULE, '❯ half a sentence the operator is typing', RULE] + [f'status row {i}' for i in range(25)]
        r = self.run_waiter(FAKE_SCREEN=screen(*rows), SELF_SLASH_WAIT='20')
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertEqual(self.typed(), [])

    def test_an_empty_marker_row_without_its_box_far_above_is_not_the_prompt(self) -> None:
        # a captured pane screen printed into the transcript, a stale row in scrollback: no rules around it
        rows = [PROMPT] + [f'status row {i}' for i in range(25)]
        r = self.run_waiter(FAKE_SCREEN=screen(*rows))
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertEqual(self.typed(), [])

    def test_a_stale_empty_prompt_above_a_shell_prompt_is_never_typed_into(self) -> None:
        # claude was killed; its last frame (empty box included) sits above the shell. herdr no longer reports claude.
        rows = [RULE, PROMPT, RULE] + [f'old row {i}' for i in range(20)] + ['$ ls', 'file', '$']
        r = self.run_waiter(FAKE_SCREEN=screen(*rows), FAKE_AGENT='')
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertEqual(self.typed(), [])
        # and the same stale frame with no rules, even where herdr still says claude
        rows = [PROMPT] + [f'old row {i}' for i in range(20)] + ['$ ls', 'file', '$']
        r = self.run_waiter(FAKE_SCREEN=screen(*rows))
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertEqual(self.typed(), [])

    def test_a_blocked_pane_with_a_stale_prompt_row_gets_nothing_typed(self) -> None:
        # a permission or question card: herdr says blocked; the only marker row is far up inside rules
        rows = [RULE, PROMPT, RULE] + [f'card row {i}' for i in range(25)]
        r = self.run_waiter(FAKE_SCREEN=screen(*rows), FAKE_STATUS='blocked')
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertEqual(self.typed(), [])

    def test_an_answer_option_row_is_not_an_empty_prompt(self) -> None:
        option = '❯ 1. Mark all done (Recommended)'
        for rows, rc in (([f'row {i}' for i in range(5)] + [option, '  2. Leave them'], 4),   # bottom window
                         ([option] + [f'row {i}' for i in range(25)], 5)):                       # wide window only
            r = self.run_waiter(FAKE_SCREEN=screen(*rows), SELF_SLASH_WAIT='20')
            self.assertEqual(r.returncode, rc, r.stdout + r.stderr)
            self.assertEqual(self.typed(), [])

    def test_a_slash_menu_row_is_not_an_empty_prompt(self) -> None:
        menu = '→ /quit  Exit'
        for rows, rc in (([f'row {i}' for i in range(5)] + [menu], 4), ([menu] + [f'row {i}' for i in range(25)], 5)):
            r = self.run_waiter(FAKE_SCREEN=screen(*rows), FAKE_AGENT='cursor', SELF_SLASH_WAIT='20')
            self.assertEqual(r.returncode, rc, r.stdout + r.stderr)
            self.assertEqual(self.typed(), [])

    def test_the_wide_window_follows_self_slash_read_lines(self) -> None:
        rows = [RULE, PROMPT, RULE] + [f'status row {i}' for i in range(25)]
        r = self.run_waiter(FAKE_SCREEN=screen(*rows), SELF_SLASH_READ_LINES='20')
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertEqual(self.typed(), [])

    # --- busy panes ---
    def test_a_pane_busy_for_longer_than_the_idle_polls_is_waited_for(self) -> None:
        # no prompt for 80 reads while a spinner line is on screen and herdr cannot say what the pane is doing:
        # more than the 9 polls a quiet pane gets
        busy = screen('output', SPINNER, 'status')
        r = self.run_waiter(FAKE_SCREEN=screen('transcript', PROMPT, 'status'), FAKE_BUSY_SCREEN=busy,
                            FAKE_BUSY_READS='80', FAKE_STATUS='unknown')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('busy', self.out(r))
        self.assertEqual(self.typed(), [['pane', 'run', 'fake:p1', '/context']])

    def test_a_pane_the_herdr_status_calls_working_is_waited_for(self) -> None:
        # herdr's own status: wait_idle lets a working pane with no spinner through (a background sub-agent), but a
        # pane with NO prompt on screen and a working status is not ready either
        r = self.run_waiter(FAKE_SCREEN=screen('transcript', PROMPT), FAKE_BUSY_SCREEN=screen('output', 'more output'),
                            FAKE_BUSY_READS='80', FAKE_STATUS='working')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.typed(), [['pane', 'run', 'fake:p1', '/context']])

    def test_a_busy_pane_that_never_shows_a_prompt_ends_at_the_wait_limit_sending_nothing(self) -> None:
        busy = screen('output', 'more output', 'status')  # no spinner: wait_idle lets a working pane through
        r = self.run_waiter(FAKE_SCREEN=busy, FAKE_BUSY_SCREEN=busy, FAKE_BUSY_READS='100000', SELF_SLASH_WAIT='30',
                            FAKE_STATUS='working')
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn('gave up, no empty input prompt seen', self.out(r))
        self.assertEqual(self.typed(), [])

    def test_the_busy_budget_is_wall_clock_time_not_five_seconds_a_loop(self) -> None:
        # the fake sleep returns at once, so a budget counted as 5 s per loop ends a 4 s wait after 2 loops, in about a
        # second; a wall-clock budget ends it only once 4 s have really passed (whole-second clock: 3 s at least)
        busy = screen('output', 'more output', 'status')  # no spinner: wait_idle lets a working pane through
        t0 = time.monotonic()
        r = self.run_waiter(FAKE_SCREEN=busy, FAKE_BUSY_SCREEN=busy, FAKE_BUSY_READS='100000', SELF_SLASH_WAIT='4',
                            FAKE_STATUS='working', FAKE_REAL_CLOCK='1')
        took = time.monotonic() - t0
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertGreaterEqual(took, 3.0, self.out(r))
        self.assertEqual(self.typed(), [])

    def test_spinner_text_in_the_scrollback_of_an_idle_pane_does_not_hold_it(self) -> None:
        # this repo's own comments, fixtures and captured diffs print these strings
        rows = ['esc to interrupt', SPINNER] + [f'diff line {i}' for i in range(30)]
        r = self.run_waiter(FAKE_SCREEN=screen(*rows))
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertEqual(self.typed(), [])
        self.assertNotIn('is busy', self.out(r))
        self.assertLess(self.reads(), 60)

    def test_an_idle_pane_with_spinner_text_in_its_last_rows_is_not_busy_either(self) -> None:
        r = self.run_waiter(FAKE_SCREEN=screen('diff', 'esc to interrupt', SPINNER))
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertNotIn('is busy', self.out(r))

    def test_an_idle_pane_with_no_prompt_gives_up_after_a_few_polls_sending_nothing(self) -> None:
        plain = screen('$ ls', 'file', '$')
        r = self.run_waiter(FAKE_SCREEN=plain)
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertEqual(self.typed(), [])
        self.assertLess(self.reads(), 60)


if __name__ == '__main__':
    unittest.main()
