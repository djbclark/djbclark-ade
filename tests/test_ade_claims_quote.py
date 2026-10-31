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


@pytest.mark.parametrize("component", ["$(touch${IFS}PWNED-subst)", "`touch${IFS}PWNED-tick`", "x;touch${IFS}PWNED-semi;"])
def test_hook_command_cannot_collapse_shell_payload_via_dotdot(monkeypatch, tmp_path, component):
    guard = tmp_path / "git-identity-guard.sh"
    monkeypatch.setattr(ade_claims, "_acp_run_guard_path", lambda: str(guard))
    command = str(tmp_path) + "/" + component + "/../git-identity-guard.sh"
    assert not ade_claims._acp_run_pair(ade_claims.ACP_RUN_IDENTITY_COMMAND_KEY, command)
    assert not ade_claims._acp_run_pair(ade_claims.ACP_RUN_IDENTITY_COMMAND_KEY, shlex.quote(command))
