"""Read-only CI sudo topology; never namespace, daemon or admission authority."""
import hashlib
import json
import os
from pathlib import Path
import select
import stat
import sys
import types

BOOTSTRAP_SHA = '605fe0f54cd43ed9614d7c4517919c9867e48a6da719bc33dac55b95ded6a8d7'
BOOTSTRAP_SIZE = 52756


def require(value):
    if not value:
        raise RuntimeError('Diagnostic refused')


def protected(file):
    for member in (file, *file.parents):
        info = member.lstat()
        require(not stat.S_ISLNK(info.st_mode) and info.st_uid == 0 and
                not info.st_mode & 0o022)
        require(stat.S_ISREG(info.st_mode) if member == file else stat.S_ISDIR(info.st_mode))


def record_data(row):
    return {'pid': row[0], 'startTime': row[1], 'parentPid': row[2],
            'uids': row[3], 'gids': row[4], 'groupCount': len(row[5]),
            'groupsSha256': hashlib.sha256(json.dumps(row[5]).encode()).hexdigest(),
            'userNamespace': row[6][0], 'pidNamespace': row[6][1]}


def executable(pid):
    info = os.stat(f'/proc/{pid}/exe')
    return (info.st_dev, info.st_ino, info.st_uid, info.st_mode,
            os.readlink(f'/proc/{pid}/exe') == '/usr/bin/sudo')


def main():
    require(sys.platform == 'linux' and os.getuid() == os.geteuid() == 0)
    require(len(sys.argv) == 3 and sys.argv[2].isdecimal())
    root = Path(sys.argv[1])
    require(root.is_absolute() and root == root.resolve(strict=True) and
            root.parent == Path('/') and root.name.startswith('fork-coupled-diagnostic-'))
    protected(Path(__file__))
    require(Path(__file__).parent == root)
    helper = root / 'system-closure/namespace-bootstrap.py'
    protected(helper)
    fd = os.open(helper, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_size == BOOTSTRAP_SIZE)
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(BOOTSTRAP_SIZE + 1)
        after = os.fstat(fd)
        named = helper.lstat()
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) ==
                (named.st_dev, named.st_ino, named.st_size, named.st_mtime_ns, named.st_ctime_ns))
    finally:
        os.close(fd)
    require(len(raw) == BOOTSTRAP_SIZE and hashlib.sha256(raw).hexdigest() == BOOTSTRAP_SHA)
    # Execute ONLY the exact separately reviewed definitions, from checked bytes.
    # A non-main module name prevents its administrative entry point from running.
    module = types.ModuleType('_accepted_namespace_diagnostic')
    module.__file__ = str(helper)
    sys.modules[module.__name__] = module
    exec(compile(raw, str(helper), 'exec'), module.__dict__)
    caller_pid = int(sys.argv[2])
    require(1 < caller_pid < 2**31 and caller_pid != os.getpid())
    descriptors = []
    try:
        own = module.process_record(os.getpid())
        caller = module.process_record(caller_pid)
        require(caller[3][0] != 0 and len(set(caller[3])) == len(set(caller[4])) == 1)
        require(caller[4][0] != 0 and caller[6] == own[6])
        expected = Path('/usr/bin/sudo').lstat()
        require(stat.S_ISREG(expected.st_mode) and expected.st_uid == 0 and not expected.st_mode & 0o022)
        rows, images = [], []
        current = own[2]
        seen = {os.getpid(), caller_pid}
        while current != caller_pid:
            require(current > 1 and current not in seen and len(rows) < 8)
            seen.add(current)
            row = module.process_record(current)
            rows.append(row)
            images.append(executable(current))
            current = row[2]
        require(rows)
        for row in [own, caller, *rows]:
            descriptors.append(os.pidfd_open(row[0], 0))
        reason = None
        try:
            module.ancestor_chain(caller_pid)
        except module.Hold as error:
            reason = str(error)
            require(len(reason) <= 64)
        for row in [own, caller, *rows]:
            require(module.process_record(row[0]) == row)
        require([executable(row[0]) for row in rows] == images)
        require(not select.select(descriptors, [], [], 0)[0])
        after = Path('/usr/bin/sudo').lstat()
        require(module.identity(after) == module.identity(expected))
        observations = []
        for row, image in zip(rows, images):
            observations.append({**record_data(row), 'exeDev': image[0], 'exeInode': image[1],
                                 'exeUid': image[2], 'exeMode': image[3],
                                 'sudoPathMatch': image[4],
                                 'sudoInodeMatch': image[:2] == (expected.st_dev, expected.st_ino),
                                 'uidAllRoot': row[3] == (0, 0, 0, 0),
                                 'gidAllRoot': row[4] == (0, 0, 0, 0),
                                 'sameUserNs': row[6][0] == own[6][0],
                                 'samePidNs': row[6][1] == own[6][1]})
        result = {'qualification': False, 'diagnosticOnly': True, 'snapshotStable': True,
                  'bootstrapSha256': BOOTSTRAP_SHA, 'predicateRefusal': reason,
                  'helper': record_data(own), 'caller': record_data(caller),
                  'expectedSudo': {'dev': expected.st_dev, 'inode': expected.st_ino,
                                   'uid': expected.st_uid, 'mode': expected.st_mode},
                  'ancestors': observations}
        encoded = json.dumps(result, separators=(',', ':'))
        require(len(encoded.encode()) <= 16384)
        print(encoded)
    finally:
        for fd in descriptors:
            os.close(fd)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('{"qualification":false,"diagnosticOnly":true,"snapshotStable":false}', file=sys.stderr)
        sys.exit(1)
