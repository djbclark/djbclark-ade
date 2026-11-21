"""bin/agent-id: field mapping, `?` fallbacks, id validation, timeouts (PR 842 repair).

Every external command is a fake script on a private PATH; nothing here touches the
real paseo, herdr or ~/.paseo.
"""
from __future__ import annotations

import importlib.machinery
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

AGENT_ID = Path(__file__).resolve().parents[1] / "bin" / "agent-id"

FULL = "a7664646-ab64-4495-b667-d47ea05d71ef"
OTHER = "a7664646-0000-4495-b667-d47ea05d71ef"
WSID = "wks_d3c475a39181cdde"

WORKSPACES = [
    {"workspaceId": "wks_other", "name": "OTHER box"},
    {"workspaceId": WSID, "name": "LEAD djbclark-ade (Wave 7)"},
]
# The real inspect keys: no workspace field at all.
INSPECT = {"Id": FULL, "Name": "worker pr-fixes a7664646", "Cwd": "/x", "Status": "idle"}


def _load():
    loader = importlib.machinery.SourceFileLoader("agent_id_mod", str(AGENT_ID))
    mod = types.ModuleType(loader.name)
    loader.exec_module(mod)
    return mod


def _fake(bin_dir: Path, name: str, body: str) -> None:
    """A fake CLI: python script that logs its argv to <name>.log, then runs body."""
    p = bin_dir / name
    p.write_text(
        f"#!{sys.executable}\n"
        "import json, sys, time\n"
        f"open({str(bin_dir / (name + '.log'))!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        f"{body}\n"
    )
    p.chmod(0o755)


def _paseo(bin_dir: Path, inspect=INSPECT, workspaces=WORKSPACES, extra: str = "") -> None:
    _fake(
        bin_dir,
        "paseo",
        f"{extra}\n"
        "a = sys.argv[1:]\n"
        f"if a[:2] == ['agent', 'inspect']: print(json.dumps({inspect!r}))\n"
        f"elif a[:2] == ['workspace', 'ls']: print(json.dumps({workspaces!r}))\n"
        "else: sys.exit(3)\n",
    )


@pytest.fixture
def env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    agents = tmp_path / "agents"
    (agents / "Users-x-src-repo").mkdir(parents=True)
    (agents / "Users-x-src-repo" / f"{FULL}.json").write_text(
        json.dumps({"id": FULL, "workspaceId": WSID, "cwd": "/x"})
    )
    (agents / "Users-x-src-repo" / f"{OTHER}.json").write_text(
        json.dumps({"id": OTHER, "workspaceId": "wks_other"})
    )
    e = {
        "PATH": str(bin_dir),
        "AGENT_ID_PASEO_AGENTS_DIR": str(agents),
        "HOME": str(tmp_path / "home"),
        "AGENT_ID_CLAUDE_SESSIONS_DIR": str(tmp_path / "sessions"),
    }
    (tmp_path / "sessions").mkdir()
    return bin_dir, e


def _run(e, *args, timeout=30):
    return subprocess.run(
        [sys.executable, str(AGENT_ID), *args], capture_output=True, text=True, env=e, timeout=timeout
    )


def _calls(bin_dir: Path, name: str) -> list:
    log = bin_dir / f"{name}.log"
    return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []


def test_paseo_agent_resolves_workspace_from_state_file_and_tab_from_name(env):
    bin_dir, e = env
    _paseo(bin_dir)
    r = _run(e, FULL, "--json")
    assert r.returncode == 0, r.stderr
    rec = json.loads(r.stdout)
    assert rec == {
        "agent_id": FULL,
        "workspace": "LEAD djbclark-ade (Wave 7)",
        "window_paseo_or_tab_herdr": "LEAD djbclark-ade (Wave 7)",
        "tab_paseo_or_pane_herdr": "worker pr-fixes a7664646",
    }
    assert ["agent", "inspect", FULL, "--json"] in _calls(bin_dir, "paseo")


def test_text_output_has_all_four_lines(env):
    bin_dir, e = env
    _paseo(bin_dir)
    r = _run(e, FULL)
    assert r.returncode == 0
    assert r.stdout.splitlines() == [
        f"agent  : {FULL}",
        "workspace : LEAD djbclark-ade (Wave 7)",
        "window (Paseo) / tab (herdr): LEAD djbclark-ade (Wave 7)",
        "tab (Paseo) / pane (herdr): worker pr-fixes a7664646",
    ]


def test_inspect_json_with_no_workspace_field_is_not_the_workspace_source(env):
    # The adversary's finding: inspect has no WorkspaceId, so an inspect that did
    # carry one must not override the state file's workspaceId.
    bin_dir, e = env
    _paseo(bin_dir, inspect={**INSPECT, "WorkspaceId": "wks_other", "workspaceId": "wks_other"})
    assert json.loads(_run(e, FULL, "--json").stdout)["workspace"] == "LEAD djbclark-ade (Wave 7)"


def test_hex_prefix_resolves_to_the_full_id(env):
    bin_dir, e = env
    _paseo(bin_dir)
    rec = json.loads(_run(e, "a7664646-ab6", "--json").stdout)
    assert rec["agent_id"] == FULL
    assert rec["workspace"] == "LEAD djbclark-ade (Wave 7)"
    assert ["agent", "inspect", FULL, "--json"] in _calls(bin_dir, "paseo")


def test_ambiguous_prefix_gives_question_marks_not_a_guess(env):
    bin_dir, e = env
    _paseo(bin_dir)
    rec = json.loads(_run(e, "a7664646", "--json").stdout)
    assert rec["workspace"] == "?"


def test_unknown_workspace_id_is_question_mark(env):
    bin_dir, e = env
    _paseo(bin_dir, workspaces=[{"workspaceId": "wks_zzz", "name": "nope"}])
    rec = json.loads(_run(e, FULL, "--json").stdout)
    assert rec["workspace"] == "?"
    assert rec["tab_paseo_or_pane_herdr"] == "worker pr-fixes a7664646"


def test_workspace_ls_wrapped_in_a_dict_still_resolves(env):
    bin_dir, e = env
    _paseo(bin_dir, workspaces={"workspaces": WORKSPACES})
    assert json.loads(_run(e, FULL, "--json").stdout)["workspace"] == "LEAD djbclark-ade (Wave 7)"


def test_no_paseo_and_no_herdr_binary_gives_clean_question_marks(env):
    bin_dir, e = env  # empty PATH dir: neither binary exists
    r = _run(e, FULL)
    assert r.returncode == 0
    assert "Traceback" not in r.stderr and r.stderr == ""
    assert r.stdout.splitlines()[1:] == [
        "workspace : ?",
        "window (Paseo) / tab (herdr): ?",
        "tab (Paseo) / pane (herdr): ?",
    ]


def test_missing_state_file_and_dead_paseo_is_question_marks(env):
    bin_dir, e = env
    _fake(bin_dir, "paseo", "sys.exit(1)")
    rec = json.loads(_run(e, "deadbeef-0000", "--json").stdout)
    assert rec["workspace"] == "?" and rec["tab_paseo_or_pane_herdr"] == "?"


@pytest.mark.parametrize(
    "bad",
    ["--help", "-h", "--json", "-1", "-x", "zzzz", "abc", "a b c d", "../../etc/passwd", "a7664646;rm", ""],
)
def test_invalid_id_is_refused_before_any_subprocess(env, bad):
    bin_dir, e = env
    _paseo(bin_dir)
    _fake(bin_dir, "herdr", "print('{}')")
    r = _run(e, *([bad] if bad else []))
    assert r.returncode == 2
    assert "Traceback" not in r.stderr
    assert _calls(bin_dir, "paseo") == [] and _calls(bin_dir, "herdr") == []


def test_two_ids_are_refused(env):
    bin_dir, e = env
    _paseo(bin_dir)
    assert _run(e, FULL, OTHER).returncode == 2
    assert _calls(bin_dir, "paseo") == []


def _herdr(bin_dir: Path, tabs, panes, workspaces) -> None:
    _fake(
        bin_dir,
        "herdr",
        "a = sys.argv[1:]\n"
        f"d = {{'tab': {tabs!r}, 'pane': {panes!r}, 'workspace': {workspaces!r}}}\n"
        "print(d[a[0]] if isinstance(d[a[0]], str) else json.dumps(d[a[0]]))\n",
    )


def test_herdr_pane_resolves_all_three_fields(env):
    bin_dir, e = env
    _herdr(
        bin_dir,
        {"result": {"tabs": [{"tab_id": "t1", "label": "claude tab"}]}},
        {"result": {"panes": [{"pane_id": "p9", "tab_id": "t1", "workspace_id": "w1", "agent_session": {"value": FULL}}]}},
        {"result": {"workspaces": [{"workspace_id": "w1", "label": "herdr ws"}]}},
    )
    rec = json.loads(_run(e, FULL, "--json").stdout)
    assert rec == {
        "agent_id": FULL,
        "workspace": "herdr ws",
        "window_paseo_or_tab_herdr": "claude tab",
        "tab_paseo_or_pane_herdr": "p9",
    }


@pytest.mark.parametrize(
    "tabs,panes,workspaces",
    [
        ("[1, 2]", "null", '"text"'),  # top level not a dict
        ('{"result": [1]}', '{"result": null}', '{"result": "x"}'),  # result not a dict
        ('{"result": {"tabs": "x"}}', '{"result": {"panes": [1, null, "p"]}}', '{"result": {"workspaces": {"a": 1}}}'),
        ("not json at all", "", "{"),
        (
            '{"result": {"tabs": [1]}}',
            '{"result": {"panes": [{"agent_session": "str-not-dict"}, {"agent_session": null}]}}',
            '{"result": {"workspaces": [null]}}',
        ),
    ],
)
def test_odd_herdr_json_gives_question_marks_without_traceback(env, tabs, panes, workspaces):
    bin_dir, e = env
    _paseo(bin_dir)
    _herdr(bin_dir, tabs, panes, workspaces)
    r = _run(e, FULL, "--json")
    assert r.returncode == 0 and "Traceback" not in r.stderr, r.stderr
    rec = json.loads(r.stdout)
    # herdr gave nothing usable, so the Paseo fields stand.
    assert rec["workspace"] == "LEAD djbclark-ade (Wave 7)"
    assert rec["tab_paseo_or_pane_herdr"] == "worker pr-fixes a7664646"


def test_a_wedged_command_times_out_instead_of_hanging(tmp_path, monkeypatch):
    mod = _load()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake(bin_dir, "paseo", "time.sleep(30)")
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setattr(mod, "TIMEOUT_S", 0.5)
    assert mod._json_argv(["paseo", "workspace", "ls", "--json"]) is None


def test_every_subprocess_call_carries_a_timeout(monkeypatch):
    mod = _load()
    seen = []

    def fake_run(argv, **kw):
        seen.append(kw.get("timeout"))
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setenv("AGENT_ID_PASEO_AGENTS_DIR", "/nonexistent")
    mod.resolve(FULL)
    assert seen and all(isinstance(t, (int, float)) and t > 0 for t in seen)


SESSION = "264ce667-1111-4222-8333-444455556666"


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid  # reaped: no such process (a reuse inside this test is vanishingly unlikely)


def _session(e, pid: int, sid: str = SESSION, name: str | None = "src-00", **extra) -> None:
    rec = {"pid": pid, "sessionId": sid, "cwd": "/x", "kind": "interactive", "entrypoint": "cli",
           "status": "idle", "messagingSocketPath": "/nowhere/s.sock", **extra}
    if name is not None:
        rec["name"] = name
    (Path(e["AGENT_ID_CLAUDE_SESSIONS_DIR"]) / f"{pid}.json").write_text(json.dumps(rec))


def test_local_claude_session_resolves_to_its_listagents_name(env):
    bin_dir, e = env
    _session(e, os.getpid())
    rec = json.loads(_run(e, SESSION, "--json").stdout)
    assert rec["agent_id"] == SESSION and rec["sendmessage_name"] == "src-00"
    out = _run(e, SESSION).stdout.splitlines()
    assert out[0] == f"agent  : {SESSION}" and out[-1] == "SendMessage name (ListAgents): src-00"
    assert "s.sock" not in "\n".join(out)  # only the name is shown, never the socket path


def test_unique_prefix_of_a_session_id_resolves_to_the_full_id(env):
    bin_dir, e = env
    _session(e, os.getpid())
    rec = json.loads(_run(e, "264ce667", "--json").stdout)
    assert rec["agent_id"] == SESSION and rec["sendmessage_name"] == "src-00"


def test_session_id_match_is_case_insensitive(env):
    bin_dir, e = env
    _session(e, os.getpid())
    assert json.loads(_run(e, "264CE667", "--json").stdout)["sendmessage_name"] == "src-00"


def test_a_stale_session_entry_with_a_dead_pid_is_skipped(env):
    bin_dir, e = env
    _session(e, _dead_pid())
    rec = json.loads(_run(e, SESSION, "--json").stdout)
    assert "sendmessage_name" not in rec and rec["workspace"] == "?"


def test_stale_entry_does_not_make_a_live_one_ambiguous(env):
    bin_dir, e = env
    _session(e, _dead_pid(), sid="264ce667-dead-4222-8333-444455556666", name="src-old")
    _session(e, os.getpid())
    assert json.loads(_run(e, "264ce667", "--json").stdout)["sendmessage_name"] == "src-00"


def test_ambiguous_session_prefix_resolves_to_nothing(env):
    bin_dir, e = env
    _session(e, os.getpid())
    _session(e, os.getppid(), sid="264ce667-9999-4222-8333-444455556666", name="src-01")
    rec = json.loads(_run(e, "264ce667", "--json").stdout)
    assert "sendmessage_name" not in rec and rec["agent_id"] == "264ce667"


def test_session_without_a_name_prints_question_mark_and_junk_entries_are_ignored(env):
    bin_dir, e = env
    sessions = Path(e["AGENT_ID_CLAUDE_SESSIONS_DIR"])
    (sessions / "123.json").write_text("not json")
    (sessions / "456.json").write_text("[1, 2]")
    (sessions / "abc.json").write_text(json.dumps({"sessionId": SESSION, "name": "evil", "pid": os.getpid()}))
    (sessions / "789.key").write_text("k")
    _session(e, os.getpid(), name=None)
    r = _run(e, SESSION, "--json")
    assert r.returncode == 0 and "Traceback" not in r.stderr
    assert json.loads(r.stdout)["sendmessage_name"] == "?"


def test_missing_sessions_dir_is_harmless(env):
    bin_dir, e = env
    e = {**e, "AGENT_ID_CLAUDE_SESSIONS_DIR": e["AGENT_ID_CLAUDE_SESSIONS_DIR"] + "-gone"}
    r = _run(e, SESSION, "--json")
    assert r.returncode == 0 and "sendmessage_name" not in json.loads(r.stdout)


def test_a_paseo_agent_id_never_looks_in_the_session_files(env):
    bin_dir, e = env
    _paseo(bin_dir)
    _session(e, os.getpid(), sid=FULL, name="src-99")  # same id in both worlds: the Paseo state file wins
    assert "sendmessage_name" not in json.loads(_run(e, FULL, "--json").stdout)
