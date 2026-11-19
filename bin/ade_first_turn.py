"""Secret-safe, fail-closed Pi v3 durable first-turn evidence (local daemon only)."""
from __future__ import annotations
import datetime
import hashlib
import json
import os
import stat
from pathlib import Path

class EvidenceError(RuntimeError):
    pass

def stamp(value):
    if not isinstance(value, str):
        raise EvidenceError('invalid native timestamp')
    try:
        result = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError()
        return result
    except ValueError:
        raise EvidenceError('invalid native timestamp') from None

def owned_read(path, limit):
    # Never follow a substituted final symlink or print any file content/error.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022 or info.st_size > limit:
            raise EvidenceError('unsafe or oversized native evidence file')
        with os.fdopen(fd, 'r', encoding='utf-8', closefd=False) as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise EvidenceError('oversized native evidence file')
        return data
    finally:
        os.close(fd)

def pi_first_turn(home, record, snapshot, *, proof=None, failure_only=False):
    """No credentials or transcript content leave this function, even on failure.

    Conservative subset: new, unbranched Pi v3 session. Native terminal stop,
    generated output, post-ack append timestamp and settled runtime are all required.
    Failure-only inspection needs no ack and can never return completion.
    Unknown providers, branch navigation, schema changes and partial writes fail closed.
    """
    try:
        if record['provider'] != 'pi':
            raise EvidenceError('first-turn adapter unavailable for this provider')
        if snapshot.get('Status') == 'error':
            return {'state': 'failed', 'cause': 'runtime-error'}
        if snapshot.get('Status') != 'idle' and not (proof and snapshot.get('Status') == 'running'):
            return {'state': 'pending', 'cause': 'turn-not-settled'}
        cwd = record['cwd']
        key = cwd.strip('/').replace('/', '-') or 'root'
        stored = json.loads(owned_read(Path(home) / 'agents' / key / (record['successor'] + '.json'), 1024 * 1024))
        handle = stored.get('persistence') or {}
        if (stored.get('id') != record['successor'] or stored.get('cwd') != cwd or
                stored.get('provider') != 'pi' or handle.get('provider') != 'pi' or
                stored.get('config', {}).get('model') != record['model']):
            raise EvidenceError('native persistence identity mismatch')
        path = Path(handle.get('nativeHandle', ''))
        if not path.is_absolute() or path.suffix != '.jsonl' or path.resolve() != path:
            raise EvidenceError('native transcript path is not canonical')
        rows = [json.loads(line) for line in owned_read(path, 16 * 1024 * 1024).splitlines() if line.strip()]
        header = rows[0] if rows else {}
        if (header.get('type') != 'session' or header.get('version') != 3 or
                header.get('id') != handle.get('sessionId') or header.get('cwd') != cwd):
            raise EvidenceError('native session header mismatch')
        after = None if failure_only else stamp(record['ack_observed_at'])
        parent = None
        seen = set()
        final = None
        final_time = None
        proven = None
        for entry in rows[1:]:
            eid = entry.get('id')
            if not isinstance(eid, str) or eid in seen or entry.get('parentId') != parent:
                raise EvidenceError('branched or malformed native transcript unsupported')
            seen.add(eid)
            parent = eid
            when = stamp(entry.get('timestamp'))
            if entry.get('type') != 'message':
                continue
            msg = entry.get('message')
            if not isinstance(msg, dict):
                raise EvidenceError('malformed native message')
            if after is not None and when <= after:
                continue
            if msg.get('role') == 'assistant' and msg.get('stopReason') in ('error', 'aborted'):
                return {'state': 'failed', 'cause': 'provider-' + msg['stopReason']}
            if proof and entry['id'] == proof.get('entry_id'):
                proven = (entry, when)
            final, final_time = (entry, when)
        if failure_only:
            return {'state': 'pending', 'cause': 'acknowledgement-required'}
        if proof:
            if proven is None or header['id'] != proof.get('session_id'):
                raise EvidenceError('accepted native terminal no longer exists')
            final, final_time = proven
            actual = hashlib.sha256(json.dumps(final, sort_keys=True).encode()).hexdigest()
            if actual != proof.get('terminal_digest'):
                raise EvidenceError('accepted native terminal changed')
        if final is None:
            return {'state': 'pending', 'cause': 'no-post-ack-turn'}
        msg = final['message']
        usage = msg.get('usage') or {}
        output = usage.get('output')
        content = msg.get('content')
        if (msg.get('role') != 'assistant' or msg.get('stopReason') != 'stop' or
                not isinstance(output, (int, float)) or isinstance(output, bool) or output <= 0 or
                not isinstance(content, list) or not any(isinstance(c, dict) and c.get('type') == 'text'
                    and isinstance(c.get('text'), str) and c['text'].strip() for c in content)):
            return {'state': 'pending', 'cause': 'no-successful-terminal-output'}
        return {'state': 'complete', 'adapter': 'pi-v3', 'entry_id': final['id'],
                'session_id': header['id'], 'completed_at': final_time.isoformat(),
                'terminal_digest': hashlib.sha256(json.dumps(final, sort_keys=True).encode()).hexdigest()}
    except EvidenceError:
        raise
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        raise EvidenceError('native first-turn evidence unavailable or malformed') from None
