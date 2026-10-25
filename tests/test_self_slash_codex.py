"""Codex lifecycle submission: skill syntax ($baton), receipts, identity, drafts, and survival of launcher teardown."""
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
SID = '11111111-2222-4333-8444-555555555555'    # synthetic: no real thread id is needed in a fixture
CHAIN = '/Users/x/.local/state/handoffs/chains/my chain/SESSION_LOG.md'

# What herdr 0.x prints, as seen live 2026-10-25: `pane get` names the pane and its agent; `agent get` and
# `agent prompt` return result.agent with pane_id, agent_status and agent_session.value.  The rollout is written
# the way Codex records a prompt: a response_item user message with one input_text block.
FAKE_HERDR = r'''#!/usr/bin/env python3
import datetime, json, os, sys
from pathlib import Path
a = sys.argv[1:]
with open(os.environ['FAKE_CALLS'], 'a') as f: f.write(json.dumps(a) + '\n')
tui = os.environ.get('FAKE_TUI', 'codex')
status = os.environ.get('FAKE_STATUS', 'idle')
prompted = Path(os.environ['FAKE_CALLS'] + '.prompted')
sid = os.environ.get('FAKE_SESSION_AFTER') if prompted.exists() and 'FAKE_SESSION_AFTER' in os.environ \
    else os.environ.get('FAKE_SESSION', '')

def agent():
    after = prompted.exists()    # what herdr says AFTER the submit: another provider, another pane, a broken answer
    name, pane = os.environ.get('FAKE_AGENT', tui), os.environ.get('FAKE_AGENT_PANE', 'fake:p1')
    st, raw = os.environ.get('FAKE_AGENT_STATUS', status), os.environ.get('FAKE_SESSION_RAW')
    if after:
        name, pane = os.environ.get('FAKE_AGENT_AFTER', name), os.environ.get('FAKE_AGENT_PANE_AFTER', pane)
        st, raw = os.environ.get('FAKE_AGENT_STATUS_AFTER', st), os.environ.get('FAKE_SESSION_RAW_AFTER', raw)
    d = {'agent': name, 'pane_id': pane, 'agent_status': st, 'cwd': '/tmp'}
    if raw is not None:    # a JSON document for agent_session, whatever shape the test wants
        d['agent_session'] = json.loads(raw)
    elif sid:
        d['agent_session'] = {'agent': 'codex', 'kind': 'id', 'source': 'herdr:codex', 'value': sid}
    return d

if a[:2] == ['pane', 'get']:
    print(json.dumps({'result': {'pane': {'pane_id': 'fake:p1', 'agent': tui, 'agent_status': status}}}))
elif a[:2] == ['agent', 'get']:
    if prompted.exists() and os.environ.get('FAKE_GET_RC_AFTER'):
        print(json.dumps({'error': {'code': 'boom'}}))
        sys.exit(int(os.environ['FAKE_GET_RC_AFTER']))
    print(json.dumps({'result': {'agent': agent()}}))
elif a[:2] == ['pane', 'list']:
    print(json.dumps({'result': {'panes': [{'pane_id': 'fake:p1', 'agent_status': status}]}}))
elif a[:2] == ['agent', 'read']:
    print(os.environ['FAKE_SCREEN_AFTER'] if prompted.exists() and 'FAKE_SCREEN_AFTER' in os.environ else os.environ['FAKE_SCREEN'])
elif a[:2] == ['agent', 'prompt']:
    rc = int(os.environ.get('FAKE_SUBMIT_RC', '0'))
    text, mode, path = a[3], os.environ.get('FAKE_RECEIPT', 'exact'), os.environ.get('FAKE_ROLLOUT')
    prompted.write_text('1')
    if rc == 0 and path and mode != 'none' and text.startswith('$baton'):
        role, body = 'assistant' if mode == 'assistant' else 'user', text + (' and operator additions' if mode == 'prefix' else '')
        if mode == 'folded':    # the same words with the runs of spaces collapsed: a different message
            body = ' '.join(text.split())
        stamp = '2000-01-01T00:00:00Z' if mode == 'stale' else \
            datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        with open(path, 'a') as f:
            f.write(json.dumps({'timestamp': stamp, 'type': 'response_item', 'payload': {
                'type': 'message', 'role': role, 'content': [{'type': 'input_text', 'text': body}]}}) + '\n')
    if rc == 0:
        print(json.dumps({'result': {'agent': agent()}}))
    sys.exit(rc)
else:
    print('{}')
'''


def screen(text='\x1b[2mAsk Codex to do anything\x1b[0m', continuation=''):
    return f'{BG}› {text}\x1b[0m\n{BG}{continuation}\x1b[0m\nGPT-6.1-Sol high · ~/src/example\n'


def user_line(text, stamp):
    return json.dumps({'timestamp': stamp, 'type': 'response_item', 'payload': {
        'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': text}]}}) + '\n'


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
        fake.write_text(FAKE_HERDR)
        fake.chmod(0o755)
        sleep = bindir / 'sleep'
        sleep.write_text('#!/usr/bin/env python3\nimport time\ntime.sleep(0.02)\n')
        sleep.chmod(0o755)
        self.calls = self.base / 'calls.jsonl'
        self.log = self.home / '.local/state/self-slash.log'
        codex_home = self.home / '.codex'
        day = codex_home / 'sessions/2026/10/25'
        day.mkdir(parents=True)
        self.rollout = day / f'rollout-2026-10-25T00-00-00-{SID}.jsonl'
        self.rollout.write_text('')
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('HERDR_', 'ORCA_', 'PASEO_', 'SELF_SLASH_', 'ACP_RUN_AGENT', 'BASH_ENV',
                                         'CODEX_HOME', 'FAKE_'))}
        self.env.update(HOME=str(self.home), CODEX_HOME=str(codex_home), PATH=f'{bindir}:{os.environ["PATH"]}',
                        HERDR_ENV='1', HERDR_PANE_ID='fake:p1', FAKE_CALLS=str(self.calls),
                        FAKE_SCREEN=screen(), FAKE_SESSION=SID, FAKE_ROLLOUT=str(self.rollout),
                        SELF_SLASH_THEN_DELAY='0', SELF_SLASH_RECEIPT_WAIT='3')

    def run_parent(self, *args, **extra):
        return subprocess.run([str(SCRIPT), '--delay', '0', *args], env=dict(self.env, **extra),
                              capture_output=True, text=True, timeout=20)

    def run_waiter(self, *args, **extra):
        return subprocess.run([str(SCRIPT), '--delay', '0', *args],
                              env=dict(self.env, SELF_SLASH_CHILD='1', **extra),
                              capture_output=True, text=True, timeout=20)

    def calls_made(self):
        return [json.loads(ln) for ln in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def submitted(self):
        return [a for a in self.calls_made() if a[:2] in (['agent', 'prompt'], ['pane', 'run'], ['agent', 'send-keys'])]

    def wait_log(self, needle, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            text = self.log.read_text() if self.log.exists() else ''
            if needle in text:
                return text
            time.sleep(0.02)
        self.fail(f'{needle!r} never reached the log:\n' + (self.log.read_text() if self.log.exists() else ''))

    def prompts(self, *texts):
        return [['agent', 'prompt', 'fake:p1', t] for t in texts]

    # --- skill syntax -------------------------------------------------------------------------------

    def test_new_then_default_followup_is_one_dollar_baton_receipted_in_the_rollout(self):
        p = self.run_parent('/new')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('then $baton once', p.stdout)
        log = self.wait_log('sent $baton')
        self.assertIn('then: $baton', log)
        self.assertEqual(self.submitted(), self.prompts('/new', '$baton'))
        self.assertEqual(log.count('sent $baton'), 1)

    def test_legacy_slash_baton_is_rewritten_once_keeping_every_suffix_byte(self):
        suffix = f' {CHAIN}  baton /baton/x $HOME.md\t'
        p = self.run_parent('--then', '/baton' + suffix, '/new')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.wait_log('sent $baton')
        self.assertEqual(self.submitted(), self.prompts('/new', '$baton' + suffix))

    def test_explicit_literal_dollar_baton_works_in_parent_and_detached_child(self):
        p = self.run_parent('--then', f'$baton {CHAIN}', '/new')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.wait_log('sent $baton')
        self.assertEqual(self.submitted(), self.prompts('/new', f'$baton {CHAIN}'))

    def test_waiter_normalization_is_idempotent_and_takes_the_text_form_too(self):
        for then in ('/baton /x y', '$baton /x y'):
            with self.subTest(then=then):
                self.calls.write_text('')
                p = self.run_waiter('/compact', SELF_SLASH_THEN=then, SELF_SLASH_COMPACT_GAP='0')
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertEqual(self.submitted(), self.prompts('/compact', '$baton /x y'))
        self.calls.write_text('')
        p = self.run_waiter('--no-then', '/baton /x y')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.submitted(), self.prompts('$baton /x y'))

    def test_dry_run_shows_the_normalized_text(self):
        p = self.run_parent('--dry-run', '--then', '/baton /a b', '/new')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('/new; then, once idle again: $baton /a b', p.stdout)
        p = self.run_parent('--dry-run', '/new')
        self.assertIn('then, once idle again: $baton', p.stdout)
        self.assertEqual(self.submitted(), [])

    def test_only_the_exact_baton_command_name_is_rewritten_and_other_dollar_words_are_refused(self):
        p = self.run_waiter('--no-then', '/compact keep /baton notes in the summary')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        p = self.run_waiter('--no-then', '/batonx /y')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.submitted(), self.prompts('/compact keep /baton notes in the summary', '/batonx /y'))
        for bad in ('$batonx /y', '$rm -rf /', '$HOME', '$baton2'):
            with self.subTest(then=bad):
                p = self.run_parent('--then', bad, '/new')
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                p = self.run_parent('--dry-run', bad)
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertEqual(len(self.submitted()), 2)

    def test_native_commands_keep_their_slash_syntax(self):
        for cmd in ('/new', '/compact focus on the diff', '/quit'):
            with self.subTest(cmd=cmd):
                self.calls.write_text('')
                p = self.run_waiter('--no-then', cmd, SELF_SLASH_COMPACT_GAP='0')
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertEqual(self.submitted(), self.prompts(cmd))

    def test_claude_keeps_slash_baton_and_refuses_the_codex_skill_syntax(self):
        claude = dict(FAKE_TUI='claude', FAKE_SCREEN='❯ \n')
        p = self.run_parent('--then', f'/baton {CHAIN}', '/new', **claude)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn(f'then /baton {CHAIN}', p.stdout)
        self.wait_log('sent /baton')
        self.assertEqual(self.submitted(), [['pane', 'run', 'fake:p1', '/new'],
                                            ['pane', 'run', 'fake:p1', f'/baton {CHAIN}']])
        self.assertNotIn(['agent', 'get', 'fake:p1'], self.calls_made())
        for args in (('--then', '$baton /x', '/new'), ('$baton /x',)):
            p = self.run_parent(*args, **claude)
            self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
            self.assertIn('Codex skill', p.stderr)

    def test_claude_default_followup_stays_slash_baton(self):
        p = self.run_parent('--dry-run', '/new', FAKE_TUI='claude')
        self.assertIn('then, once idle again: /baton', p.stdout)
        self.assertNotIn('$baton', p.stdout)

    def test_a_pane_herdr_reports_no_agent_for_gets_no_baton_followup_of_any_spelling(self):
        unknown = dict(FAKE_TUI='')
        for args in (('/new',), ('--then', '/baton /x', '/new'), ('--then', '$baton /x', '/new'), ('/baton /x',), ('$baton /x',)):
            for dry in ((), ('--dry-run',)):
                with self.subTest(args=args, dry=dry):
                    p = self.run_parent(*dry, *args, **unknown)
                    self.assertEqual(p.returncode, 3, p.stdout + p.stderr)
                    self.assertIn('reports no agent', p.stderr)
        p = self.run_waiter('/compact', SELF_SLASH_THEN='/baton /x', **unknown)    # a waiter child too
        self.assertEqual(p.returncode, 3, p.stdout + p.stderr)
        self.assertEqual(self.submitted(), [])

    def test_a_pane_herdr_reports_no_agent_for_still_takes_a_command_with_no_followup(self):
        p = self.run_parent('--dry-run', '--no-then', '/new', FAKE_TUI='')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        p = self.run_parent('--dry-run', '/compact', FAKE_TUI='')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    # --- identity -----------------------------------------------------------------------------------

    def test_missing_or_mismatched_identity_submits_nothing(self):
        cases = {'agent get says another provider': dict(FAKE_AGENT='claude'),
                 'agent get names no provider': dict(FAKE_AGENT=''),
                 'agent get names another pane': dict(FAKE_AGENT_PANE='fake:p9'),
                 'agent get says blocked': dict(FAKE_AGENT_STATUS='blocked'),
                 'agent get says unknown': dict(FAKE_AGENT_STATUS='unknown')}
        for name, extra in cases.items():
            for text in ('/new', '$baton /x'):
                with self.subTest(case=name, text=text):
                    p = self.run_waiter('--no-then', text, SELF_SLASH_COMPACT_GAP='0', **extra)
                    self.assertEqual(p.returncode, 8, p.stdout + p.stderr)
                    self.assertIn('identity not confirmed', p.stdout + p.stderr)
        self.assertEqual(self.submitted(), [])

    def test_identity_that_changes_after_the_submit_is_not_a_receipt_even_with_a_matching_rollout(self):
        # the rollout DOES hold the exact user message (FAKE_RECEIPT=exact); herdr no longer vouches for the target
        cases = {'another provider': dict(FAKE_AGENT_AFTER='claude'),
                 'no provider': dict(FAKE_AGENT_AFTER=''),
                 'another pane': dict(FAKE_AGENT_PANE_AFTER='fake:p9'),
                 'agent get fails': dict(FAKE_GET_RC_AFTER='1'),
                 'session is a string': dict(FAKE_SESSION_RAW_AFTER='"not-a-record"'),
                 'session value is not a string': dict(FAKE_SESSION_RAW_AFTER='{"value": 7}'),
                 'session is a list': dict(FAKE_SESSION_RAW_AFTER='[]')}
        for name, extra in cases.items():
            with self.subTest(case=name):
                self.calls.write_text('')
                (self.base / 'calls.jsonl.prompted').unlink(missing_ok=True)
                self.rollout.write_text('')
                p = self.run_waiter('--no-then', '$baton /x', SELF_SLASH_RECEIPT_WAIT='1', **extra)
                self.assertEqual(p.returncode, 8, p.stdout + p.stderr)
                self.assertIn('NOT confirmed delivered, NOT retried, no Enter sent', p.stdout)
                self.assertNotIn('sent $baton', p.stdout)
                self.assertEqual(self.rollout.read_text().count('$baton /x'), 1)
                self.assertEqual(self.submitted(), self.prompts('$baton /x'))

    def test_a_malformed_session_record_before_the_submit_submits_nothing(self):
        for raw in ('"not-a-record"', '{"value": 7}', '[]'):
            with self.subTest(raw=raw):
                p = self.run_waiter('--no-then', '$baton /x', FAKE_SESSION_RAW=raw)
                self.assertEqual(p.returncode, 8, p.stdout + p.stderr)
                self.assertIn('identity not confirmed', p.stdout)
        self.assertEqual(self.submitted(), [])

    def test_a_working_status_after_the_submit_is_expected_and_still_a_receipt(self):
        p = self.run_waiter('--no-then', '$baton /x', FAKE_AGENT_STATUS_AFTER='working')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.submitted(), self.prompts('$baton /x'))

    def test_a_target_that_changed_since_the_parent_looked_gets_nothing(self):
        p = self.run_waiter('--no-then', '/baton /x', SELF_SLASH_TUI='claude')
        self.assertEqual(p.returncode, 8, p.stdout + p.stderr)
        self.assertIn('target changed', p.stdout)
        self.assertEqual(self.submitted(), [])

    # --- guards, receipts, failures -----------------------------------------------------------------

    def test_blocked_unknown_and_working_states_never_submit(self):
        for status in ['blocked', 'unknown', 'working']:
            with self.subTest(status=status):
                p = self.run_waiter('--no-then', '/new', FAKE_STATUS=status, SELF_SLASH_WAIT='0')
                self.assertEqual(p.returncode, 6, p.stdout + p.stderr)
                p = self.run_waiter('--no-then', '$baton /x', FAKE_STATUS=status, SELF_SLASH_WAIT='0')
                self.assertEqual(p.returncode, 6, p.stdout + p.stderr)
        self.assertEqual(self.submitted(), [])

    def test_drafts_never_submit_a_command_or_a_skill_prompt(self):
        for text in ('/new', '$baton /x'):
            with self.subTest(text=text):
                for draft in (screen('', 'keep this draft'), screen('typed draft')):
                    p = self.run_waiter('--no-then', text, FAKE_SCREEN=draft, SELF_SLASH_WAIT='0')
                    self.assertEqual(p.returncode, 4, p.stdout + p.stderr)
        self.assertEqual(self.submitted(), [])

    def test_a_draft_with_marker_looking_continuation_rows_is_refused_without_enter(self):
        drafts = {'shaded marker': screen('keep this operator draft', '›'),
                  'shaded marker and space': screen('keep this operator draft', '› '),
                  'typed continuation then marker': screen('', 'typed continuation\x1b[0m\n' + BG + '›'),
                  'several marker rows': screen('first', '› second\x1b[0m\n' + BG + '›')}
        for text in ('/new', '$baton /x'):
            for name, draft in drafts.items():
                with self.subTest(text=text, draft=name):
                    self.calls.write_text('')
                    p = self.run_waiter('--no-then', text, FAKE_SCREEN=draft, SELF_SLASH_WAIT='0')
                    self.assertEqual(p.returncode, 4, p.stdout + p.stderr)
                    self.assertEqual(self.submitted(), [])
                    self.assertFalse([a for a in self.calls_made() if 'enter' in a or 'Enter' in a], self.calls_made())

    def test_ambiguous_failure_never_retries(self):
        for text in ('/new', '$baton /x'):
            with self.subTest(text=text):
                self.calls.write_text('')
                p = self.run_waiter('--no-then', text, FAKE_SUBMIT_RC='1', SELF_SLASH_COMPACT_GAP='0')
                self.assertEqual(p.returncode, 8, p.stdout + p.stderr)
                self.assertEqual(self.submitted(), self.prompts(text))

    def test_an_acknowledgement_without_the_exact_user_message_is_not_delivery(self):
        self.rollout.write_text(user_line('$baton /x', time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())))
        shown = screen('$baton /x')    # the composer still shows the text AFTER the submit, herdr acked it, rc 0
        cases = {'no rollout line (herdr acked, composer shows it)': dict(FAKE_RECEIPT='none', FAKE_SCREEN_AFTER=shown),
                 'an assistant echo': dict(FAKE_RECEIPT='assistant'),
                 'a user message with more text': dict(FAKE_RECEIPT='prefix'),
                 'a stale stamp': dict(FAKE_RECEIPT='stale')}
        for name, extra in cases.items():
            with self.subTest(case=name):
                self.calls.write_text('')
                (self.base / 'calls.jsonl.prompted').unlink(missing_ok=True)
                p = self.run_waiter('--no-then', '$baton /x', SELF_SLASH_RECEIPT_WAIT='1', **extra)
                self.assertEqual(p.returncode, 8, p.stdout + p.stderr)
                self.assertIn('NOT confirmed delivered, NOT retried, no Enter sent', p.stdout)
                self.assertNotIn('sent $baton', p.stdout)
                self.assertEqual(self.submitted(), self.prompts('$baton /x'))

    def test_exact_user_message_in_the_rollout_is_the_receipt(self):
        # an older identical prompt already in the file must not count; the one this submit adds does
        self.rollout.write_text(user_line('$baton /x', time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())))
        p = self.run_waiter('--no-then', '$baton /x')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.submitted(), self.prompts('$baton /x'))
        self.assertEqual(self.rollout.read_text().count('$baton /x'), 2)

    def test_the_receipt_is_the_whole_text_byte_for_byte_so_a_path_with_runs_of_spaces_is_not_folded(self):
        text = '$baton /Users/x/my  chain/SESSION_LOG.md'    # two spaces inside the path
        now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        self.rollout.write_text(user_line(text, now))    # an older exact copy never counts for this submit
        p = self.run_waiter('--no-then', text, FAKE_RECEIPT='folded', SELF_SLASH_RECEIPT_WAIT='1')
        self.assertEqual(p.returncode, 8, p.stdout + p.stderr)
        self.assertIn('NOT confirmed delivered', p.stdout)
        self.assertEqual(self.submitted(), self.prompts(text))
        self.calls.write_text('')
        (self.base / 'calls.jsonl.prompted').unlink()
        self.rollout.write_text('')
        p = self.run_waiter('--no-then', text)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('sent ' + text, p.stdout)
        self.assertEqual(self.submitted(), self.prompts(text))

    def test_an_identical_older_message_in_a_session_that_appears_after_the_submit_is_not_a_receipt(self):
        # the fresh session is read from byte 0, so only the stamp can tell an older identical prompt from ours
        self.rollout.write_text(user_line('$baton /x', time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())))
        p = self.run_waiter('--no-then', '$baton /x', FAKE_SESSION='', FAKE_SESSION_AFTER=SID, FAKE_RECEIPT='none',
                            SELF_SLASH_RECEIPT_WAIT='1')
        self.assertEqual(p.returncode, 8, p.stdout + p.stderr)
        self.assertEqual(self.submitted(), self.prompts('$baton /x'))

    def test_a_fresh_session_after_new_is_read_from_its_own_rollout(self):
        # right after /new herdr may name no session until the first prompt: the receipt comes from the session it
        # names afterwards (read from byte 0, stamped since the submit); if it never names one nothing is proven
        p = self.run_waiter('--no-then', '$baton /x', FAKE_SESSION='', FAKE_SESSION_AFTER=SID)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.submitted(), self.prompts('$baton /x'))
        (self.base / 'calls.jsonl.prompted').unlink()
        self.calls.write_text('')
        p = self.run_waiter('--no-then', '$baton /x', FAKE_SESSION='')
        self.assertEqual(p.returncode, 8, p.stdout + p.stderr)
        self.assertEqual(self.submitted(), self.prompts('$baton /x'))

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
