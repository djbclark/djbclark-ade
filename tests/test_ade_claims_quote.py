"""Quoted identity hook commands are exempt only when they name exactly the guard."""
import shlex
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import ade_claims


@pytest.mark.parametrize("directory", ["John Smith", "o'brien", "plain"])
def test_shell_quoted_guard_path_is_exempt(monkeypatch, tmp_path, directory):
    guard = tmp_path / directory / "guard.sh"
    monkeypatch.setattr(ade_claims, "_acp_run_guard_path", lambda: str(guard.resolve()))
    assert ade_claims._acp_run_pair(ade_claims.ACP_RUN_IDENTITY_COMMAND_KEY, shlex.quote(str(guard)))
    assert not ade_claims._acp_run_pair(ade_claims.ACP_RUN_IDENTITY_COMMAND_KEY, shlex.quote(str(guard)) + " extra")
    assert not ade_claims._acp_run_pair(ade_claims.ACP_RUN_IDENTITY_COMMAND_KEY, "'unclosed")
    assert not ade_claims._acp_run_pair(ade_claims.ACP_RUN_IDENTITY_COMMAND_KEY, shlex.quote(str(guard)) + "; false")
