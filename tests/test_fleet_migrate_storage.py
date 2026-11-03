"""Security/failure tests run only against pytest's temporary directories."""
import json
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "libexec"))
from fleet_migrate.storage import MAX_BYTES, Store, read_input


def test_private_atomic_roundtrip(tmp_path):
    root = tmp_path / "private"
    with Store(root, create=True) as s, s.lock():
        s.write("plan.json", {"schema_version": 1})
        assert s.read("plan.json") == {"schema_version": 1}
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "plan.json").stat().st_mode) == 0o600


@pytest.mark.parametrize("name", ["../x", "/tmp/x", "a/b", "", ".", "..", "a\n"])
def test_traversal_rejected(tmp_path, name):
    with Store(tmp_path / "private", create=True) as s:
        with pytest.raises(ValueError):
            s.write(name, {})


def test_symlink_root_and_ancestor_refused(tmp_path):
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    (tmp_path / "link").symlink_to(real)
    with pytest.raises(OSError):
        Store(tmp_path / "link", create=True)
    with pytest.raises(OSError):
        Store(tmp_path / "link" / "child", create=True)


def test_unprivate_root_refused(tmp_path):
    root = tmp_path / "public"
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    with pytest.raises(ValueError):
        Store(root)


def test_symlink_or_hardlink_artifact_never_followed_or_overwritten(tmp_path):
    root = tmp_path / "private"
    target = tmp_path / "untouched"
    target.write_text("do not change")
    target.chmod(0o600)
    with Store(root, create=True) as s:
        (root / "link.json").symlink_to(target)
        os.link(target, root / "hard.json")
        for name in ("link.json", "hard.json"):
            with pytest.raises((ValueError, OSError)):
                s.read(name)
            with pytest.raises((ValueError, OSError)):
                s.write(name, {})
    assert target.read_text() == "do not change"


def test_lock_contention_refuses(tmp_path):
    root = tmp_path / "private"
    with Store(root, create=True) as a, Store(root) as b, a.lock():
        with pytest.raises(BlockingIOError):
            with b.lock():
                pytest.fail("second coordinator admitted")


def test_atomic_replace_failure_preserves_previous_value(tmp_path, monkeypatch):
    with Store(tmp_path / "private", create=True) as s:
        s.write("run.json", {"stage": "PREPARED"})
        def crash(*args, **kwargs):
            raise OSError("injected crash before rename")
        monkeypatch.setattr(os, "replace", crash)
        with pytest.raises(OSError):
            s.write("run.json", {"stage": "COMPLETE"})
        assert s.read("run.json") == {"stage": "PREPARED"}
    assert not list((tmp_path / "private").glob(".write-*"))


@pytest.mark.parametrize("body", ['{"x":1,"x":2}', 'NaN', '{', '[', '{"x":Infinity}'])
def test_invalid_duplicate_or_nonfinite_json_refused(tmp_path, body):
    p = tmp_path / "input.json"
    p.write_text(body)
    with pytest.raises(ValueError):
        read_input(p)


def test_bounded_read_and_write(tmp_path):
    p = tmp_path / "large.json"
    p.write_bytes(b" " * (MAX_BYTES + 1))
    with pytest.raises(ValueError):
        read_input(p)
    with Store(tmp_path / "private", create=True) as s:
        with pytest.raises(ValueError):
            s.write("large.json", {"x": "a" * MAX_BYTES})


def test_input_fifo_cannot_block(tmp_path):
    p = tmp_path / "fifo"
    os.mkfifo(p)
    with pytest.raises(ValueError):
        read_input(p)
