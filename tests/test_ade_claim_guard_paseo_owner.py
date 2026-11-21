"""claim-guard (2026-11-21): a claim that names a Paseo worker by `owner.agent` is the worker's; refusal text for the owner itself;
`new --ownerless` exclusivity and the stale ADE_CLAIM_ID note."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import ade_claims  # noqa: E402

W = "8ec213c7-f373-4829-88a2-5a1c8fe6b8b4"
OTHER = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    st = tmp_path / "state"
    monkeypatch.setenv("ADE_STATE_DIR", str(st))
    for k in ("PASEO_AGENT_ID", "ADE_CLAIM_ID", "CLAUDE_CODE_SESSION_ID", "ACP_OPERATOR_APPROVED"):
        monkeypatch.delenv(k, raising=False)
    return st


def _ws(tmp_path, name="ws"):
    ws = tmp_path / name
    ws.mkdir()
    subprocess.run(["git", "init", "-q", str(ws)], check=True)
    return ws


def _claim(ws, cid="c1", **owner):
    c = ade_claims.make_claim(id=cid, path=ws, branch="b", base_sha="abcd", **owner)
    ade_claims.create_claim(c)
    return ade_claims.read_claim(cid)


def _env(**kw):
    return {k: v for k, v in kw.items() if v is not None}


def _decide(ws, **env):
    env = {"PATH": os.environ["PATH"], **env}
    call = ade_claims.parse_git_argv(["-C", str(ws), "add", "-A"], str(ws), env)
    return call, ade_claims.evaluate(call, env)


# --- the guard accepts PASEO_AGENT_ID == owner.agent -------------------------------------------------------------------

def test_owner_agent_alone_is_enough_for_a_plain_paseo_caller(tmp_path):
    claim = _claim(_ws(tmp_path), owner_agent=W)    # no record, no session: what a bare `bind-owner --owner-agent` left
    assert ade_claims.is_mine(claim, ade_claims.caller_ident(_env(PASEO_AGENT_ID=W)))
    assert not ade_claims.is_mine(claim, ade_claims.caller_ident(_env(PASEO_AGENT_ID=OTHER)))


def test_owner_agent_matches_with_a_claude_session_and_with_other_record_or_session(tmp_path):
    claim = _claim(_ws(tmp_path), owner_agent=W, owner_record="rec-x", owner_session="sess-x")
    assert ade_claims.is_mine(claim, ade_claims.caller_ident(_env(CLAUDE_CODE_SESSION_ID="s-new", PASEO_AGENT_ID=W)))
    assert ade_claims.is_mine(claim, ade_claims.caller_ident(_env(PASEO_AGENT_ID=W)))


def test_a_label_or_non_uuid_owner_agent_never_matches_by_agent(tmp_path):
    claim = _claim(_ws(tmp_path), owner_agent="codex", owner_session="sess-x")
    assert not ade_claims.is_mine(claim, ade_claims.caller_ident(_env(PASEO_AGENT_ID="codex")))
    claim2 = _claim(_ws(tmp_path, "w2"), cid="c2", owner_agent="agent-new", owner_record="other-rec")
    assert not ade_claims.is_mine(claim2, ade_claims.caller_ident(_env(PASEO_AGENT_ID="agent-new")))


def test_an_explicit_claim_id_still_wins_over_the_paseo_id(tmp_path):
    claim = _claim(_ws(tmp_path), owner_agent=W)
    assert not ade_claims.is_mine(claim, ade_claims.caller_ident(_env(ADE_CLAIM_ID="another", PASEO_AGENT_ID=W)))


def test_a_plain_string_cannot_carry_the_paseo_id(tmp_path):
    claim = _claim(_ws(tmp_path), owner_agent=W)
    assert not ade_claims.is_mine(claim, W)    # only caller_ident's CallerIdent carries it


def test_lead_precreated_claim_then_bind_owner_lets_the_worker_write(tmp_path):
    ws = _ws(tmp_path)
    c = ade_claims.make_claim(id="pre", path=ws, branch="b", base_sha="abcd")    # an ownerless claim, as `new --ownerless` makes
    ade_claims.create_claim(c)
    assert not _decide(ws, PASEO_AGENT_ID=W)[1].allowed    # before the bind: refused
    ade_claims.bind_owner("pre", owner_agent=W)
    assert _decide(ws, PASEO_AGENT_ID=W)[1].allowed                                  # Codex/Pi-style worker
    assert _decide(ws, PASEO_AGENT_ID=W, CLAUDE_CODE_SESSION_ID="s1")[1].allowed     # Claude worker
    assert not _decide(ws, PASEO_AGENT_ID=OTHER)[1].allowed


def test_bind_owner_defaults_the_record_to_a_paseo_agent_id(tmp_path):
    _claim(_ws(tmp_path), cid="b1")
    o = ade_claims.bind_owner("b1", owner_agent=W)["owner"]
    assert o["agent"] == W and o["record"] == W
    _claim(_ws(tmp_path, "w2"), cid="b2", owner_session="sess")
    assert not ade_claims.bind_owner("b2", owner_agent=W)["owner"]["record"]    # a session is already an identity
    _claim(_ws(tmp_path, "w3"), cid="b3")
    assert not ade_claims.bind_owner("b3", owner_agent="codex")["owner"]["record"]    # a label gets none
    _claim(_ws(tmp_path, "w4"), cid="b4")
    assert ade_claims.bind_owner("b4", owner_agent=W, owner_record="mine")["owner"]["record"] == "mine"


# --- refusal text -----------------------------------------------------------------------------------------------------

def test_refusal_never_tells_the_owner_it_is_somebody_else(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    _claim(ws, owner_agent=W, owner_record=W)
    monkeypatch.setenv("PASEO_AGENT_ID", W)
    monkeypatch.setenv("ADE_CLAIM_ID", "a-stale-claim")    # outranks the Paseo id, so the guard refuses the real owner
    call, d = _decide(ws, PASEO_AGENT_ID=W, ADE_CLAIM_ID="a-stale-claim")
    assert not d.allowed
    text = ade_claims.refusal_text(d, call)
    assert "names you" in text and W in text and "a-stale-claim" in text
    assert "Do not message yourself" in text and "Ask the owner" not in text
    assert "you are a-stale-claim" not in text


def test_refusal_for_a_real_stranger_keeps_the_owner_text(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    _claim(ws, owner_agent=W, owner_record=W)
    monkeypatch.setenv("PASEO_AGENT_ID", OTHER)
    call, d = _decide(ws, PASEO_AGENT_ID=OTHER)
    text = ade_claims.refusal_text(d, call)
    assert "Ask the owner (a Paseo agent)" in text and "names you" not in text and f"you are {OTHER}" in text


def test_hook_refusal_has_the_same_self_owner_text(tmp_path, capsys):
    ws = _ws(tmp_path)
    claim = _claim(ws, owner_agent=W, owner_record=W)
    d = ade_claims._foreign(claim, "ref-in-foreign-workspace", ade_claims.FOREIGN_ALT)
    env = {"PASEO_AGENT_ID": W, "ADE_CLAIM_ID": "stale", "PATH": os.environ["PATH"]}
    assert ade_claims._hook_refusal("ref-in-foreign-workspace", d, "reference-transaction", "the update of `HEAD`", env,
                                    str(ws), {}) == ade_claims.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "names you" in err and "Ask the owner" not in err
    other = {"PASEO_AGENT_ID": OTHER, "PATH": os.environ["PATH"]}
    ade_claims._hook_refusal("ref-in-foreign-workspace", d, "reference-transaction", "the update of `HEAD`", other, str(ws), {})
    assert "Ask the owner" in capsys.readouterr().err


# --- `new` flags ------------------------------------------------------------------------------------------------------

def _run(*args, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PASEO_", "ADE_CLAIM", "CLAUDE_CODE"))}
    env.update(extra)
    return subprocess.run([sys.executable, str(ROOT / "bin" / "ade_claims.py"), *args], capture_output=True, text=True, env=env,
                          timeout=60)


def _repo(tmp_path, name="r"):
    d = tmp_path / name
    d.mkdir()

    def g(*a):
        subprocess.run(["git", "-C", str(d), *a], check=True, capture_output=True)

    g("init", "-q", "-b", "main")
    g("-c", "user.name=t", "-c", "user.email=t@e.invalid", "commit", "-q", "--allow-empty", "-m", "i")
    return d


@pytest.mark.parametrize("flags", [["--owner-agent", W], ["--owner-agent", "codex"], ["--owner-record", "r"], ["--owner-session", "s"]])
def test_ownerless_excludes_every_owner_flag(tmp_path, flags):
    r = _run("new", "--path", str(_repo(tmp_path)), "--ownerless", *flags)
    assert r.returncode == 2 and "--ownerless excludes" in r.stderr
    assert ade_claims.list_claims() == []


def test_ownerless_alone_still_works(tmp_path):
    r = _run("new", "--path", str(_repo(tmp_path)), "--ownerless", PASEO_AGENT_ID=W)
    assert r.returncode == 0, r.stderr
    o = ade_claims.list_claims("active")[0]["owner"]
    assert not o["agent"] and not o["record"]


def test_stale_claim_id_gets_a_note_on_a_same_owner_reclaim(tmp_path):
    repo = _repo(tmp_path)
    assert _run("new", "--path", str(repo), "--owner-agent", W).returncode == 0
    first = ade_claims.list_claims("active")[0]["id"]
    r = _run("new", "--path", str(repo), "--owner-agent", W, ADE_CLAIM_ID=first)
    assert r.returncode == 0, r.stderr
    new_id = ade_claims.list_claims("active")[0]["id"]
    assert new_id != first and f"export ADE_CLAIM_ID={new_id}" in r.stderr
    quiet = _run("new", "--path", str(_repo(tmp_path, "r2")), "--owner-agent", W, ADE_CLAIM_ID="no-such-claim")
    assert quiet.returncode == 0 and "ADE_CLAIM_ID" not in quiet.stderr


def test_help_texts_match_the_code():
    r = _run("new", "-h")
    assert "symbolic-ref" in r.stdout and "abbrev-ref" not in r.stdout
    assert "never created ownerless" not in r.stdout
