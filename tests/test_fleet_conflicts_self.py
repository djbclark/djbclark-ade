"""fleet.conflicts: --sid naming the caller itself is not 'already live' (2026-10-18, Plektra lead's report)."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "session-finder"))
import fleet  # noqa: E402


def test_own_sid_is_not_already_live_but_a_peer_is(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    me = {"id": "me", "sid": "S-ME", "self": True, "cwd": str(tmp_path), "status": "working"}
    peer = {"id": "peer", "sid": "S-PEER", "self": False, "cwd": "/elsewhere", "status": "idle"}
    assert fleet.conflicts(str(tmp_path), live=[me, peer], sid="S-ME")["sid_live"] == []
    assert fleet.conflicts(str(tmp_path), live=[me, peer], sid="S-PEER")["sid_live"] == [peer]
