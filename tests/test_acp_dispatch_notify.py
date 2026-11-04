"""Completion notifications are external notices, not self-addressed agent relays."""
import contextlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'bin/acp-dispatch-notify'
loader = importlib.machinery.SourceFileLoader('dispatch_notify', str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
TARGET = 'c987a634-16f9-4bc7-b4c3-ad84d211e458'


def test_external_notice_context_and_untruncated_receipt(monkeypatch):
    contexts = []
    @contextlib.contextmanager
    def caller(label, **kwargs):
        contexts.append((label, kwargs))
        yield
    def main(args, **kwargs):
        assert contexts == [('acp-dispatch completion', {'scrub': True, 'notice': True})]
        assert '--json' in args and '--steer' not in args
        assert kwargs == {'sweep': False}
        print(json.dumps({'result': 'delivered', 'text': 'x' * 1000}))
        return 0
    monkeypatch.setitem(sys.modules, 'relay', SimpleNamespace(as_caller=caller, main=main))
    code, receipt = mod.notify(TARGET, 'done')
    assert code == 0
    assert json.loads(receipt)['result'] == 'delivered'
    assert len(receipt) > 1000


@pytest.mark.parametrize('receipt,relay_rc,wait_rc,expected,ping', [
    ({'result': 'delivered'}, 0, 0, 0, False),
    ({'result': 'accepted'}, 0, 0, 1, True),
    ({'result': 'queued'}, 0, 0, 1, True),
    ({'result': 'delivered'}, 1, 0, 1, True),
    ('not sent: that is this session', 1, 0, 1, True),
    ({'result': 'delivered'}, 0, 76, 76, False),
])
def test_wait_then_one_notice_no_retry(tmp_path, monkeypatch, receipt, relay_rc, wait_rc, expected, ping):
    record = tmp_path / 'job.json'
    report = tmp_path / 'report.md'
    record.write_text(json.dumps({'report': str(report)}))
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=wait_rc if len(calls) == 1 else 0)
    notices = []
    def send(target, message):
        notices.append((target, message))
        assert len(calls) == 1
        return relay_rc, json.dumps(receipt) if isinstance(receipt, dict) else receipt
    monkeypatch.setattr(mod.subprocess, 'run', run)
    monkeypatch.setattr(mod, 'notify', send)
    assert mod.main([str(record), '--target', TARGET]) == expected
    assert calls[0] == [str(mod.ROOT / 'bin/acp-dispatch-wait'), str(record), str(report) + '.done']
    assert len(notices) == 1
    assert len(calls) == (2 if ping else 1)


def test_malformed_record_never_waits_or_sends(tmp_path, monkeypatch):
    record = tmp_path / 'bad.json'
    record.write_text('{}')
    monkeypatch.setattr(mod.subprocess, 'run', lambda *a, **k: pytest.fail('must not launch'))
    with pytest.raises(SystemExit) as exc:
        mod.main([str(record), '--target', TARGET])
    assert exc.value.code == 2
