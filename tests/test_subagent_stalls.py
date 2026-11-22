"""bin/ade_subagent_stalls.py: the stalled Agent-tool sub-agent detector (docs/subagent-stalls.md).

Every test builds its own fake home under tmp_path and passes it in; the fake `hermes-ping` and `paseo` are scripts given by ABSOLUTE
path (2026-11-22: a test reached a real tool through a PATH reorder), so no test sends a real ping or message.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import ade_subagent_stalls as ss  # noqa: E402

NOW = 1_800_000_000.0
MIN = 60.0
SESSION = "11111111-aaaa-4bbb-8ccc-222222222222"
PARENT_PASEO = "99999999-aaaa-4bbb-8ccc-333333333333"
AGENT = "a0123456789abcdef"


class World:
    """A fake home: reports, ~/.claude/projects, ~/.paseo/agents, state and two fake tools."""

    def __init__(self, tmp_path: Path):
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.reports = self.home / ".local/state/agent-reports"
        self.projects = self.home / ".claude/projects"
        self.agents = self.home / ".paseo/agents"
        self.tools = tmp_path / "tools"
        self.tools.mkdir()
        self.hermes = self._tool("hermes-ping", "sys.exit(int(open(os.path.join(here, 'rc')).read()) if os.path.exists(os.path.join(here, 'rc')) else 0)")
        self.paseo = self._tool(
            "paseo",
            "if argv[:2] == ['agent', 'inspect']:\n"
            "    sys.stdout.write(open(os.path.join(here, 'inspect.json')).read())\n"
            "sys.exit(0)")
        self.set_parent_state(archived=False, status="idle")

    def _tool(self, name: str, body: str) -> Path:
        d = self.tools / name
        d.mkdir()
        script = d / name
        script.write_text(f"#!{sys.executable}\nimport json, os, sys\nhere = os.path.dirname(os.path.abspath(__file__))\n"
                          "argv = sys.argv[1:]\nwith open(os.path.join(here, 'calls.jsonl'), 'a') as f:\n"
                          "    f.write(json.dumps(argv) + '\\n')\n" + body + "\n")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        return script

    def calls(self, tool: Path) -> list[list[str]]:
        log = tool.parent / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def set_parent_state(self, archived: bool, status: str) -> None:
        (self.paseo.parent / "inspect.json").write_text(json.dumps({"Archived": archived, "Status": status}))

    def cfg(self, **over) -> ss.Config:
        base = {"now": NOW, "hermes_ping": self.hermes, "paseo": self.paseo}
        base.update(over)
        return ss.make_config(self.home, **base)

    def stub(self, name: str = "adversary-review-report.md", session: str = SESSION, age_min: float = 600, first: str = "STATUS: working",
             done: bool = False) -> str:
        d = self.reports / session
        d.mkdir(parents=True, exist_ok=True)
        p = d / name
        p.write_text(first + "\n")
        os.utime(p, (NOW - age_min * MIN, NOW - age_min * MIN))
        if done:
            (d / (name + ".done")).write_text("")
        return str(p)

    def transcript(self, report: str | None, idle_min: float, tail: str = "tool_result", agent: str = AGENT, session: str = SESSION,
                   description: str = "Adversary review", prompt: str | None = None, tool_timeout_ms: int | None = None,
                   project: str = "-Users-x-proj") -> Path:
        d = self.projects / project / session / "subagents"
        d.mkdir(parents=True, exist_ok=True)
        text = prompt if prompt is not None else (
            f"Review the diff.\n\n## Delivery contract\n\n1. Write the full deliverable to `{report}`. Create it early.\n")
        recs = [{"type": "user", "isSidechain": True, "message": {"role": "user", "content": text}}]
        recs += [{"type": "assistant", "message": {"stop_reason": "tool_use", "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}},
                 {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}}]
        if tail == "final":
            recs.append({"type": "assistant", "message": {"stop_reason": "end_turn", "content": [{"type": "text", "text": "written: x"}]}})
            recs += [{"type": "attachment", "attachment": {"type": "hook_success"}}, {"type": "api-request"}]
        elif tail == "tool_use":
            inp = {"command": "sleep 99"}
            if tool_timeout_ms is not None:
                inp["timeout"] = tool_timeout_ms
            recs.append({"type": "assistant", "message": {"stop_reason": "tool_use", "content": [{"type": "tool_use", "name": "Bash", "input": inp}]}})
            recs.append({"type": "attachment", "attachment": {"type": "hook_success"}})
        elif tail != "tool_result":
            raise ValueError(tail)
        p = d / f"agent-{agent}.jsonl"
        p.write_text("".join(json.dumps(r) + "\n" for r in recs))
        (d / f"agent-{agent}.meta.json").write_text(json.dumps({"agentType": "general-purpose", "description": description}))
        os.utime(p, (NOW - idle_min * MIN, NOW - idle_min * MIN))
        return p

    def paseo_agent(self, session: str = SESSION, agent_id: str = PARENT_PASEO, archived: bool = False) -> None:
        d = self.agents / "Users-x-proj"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{agent_id}.json").write_text(json.dumps({
            "id": agent_id, "archivedAt": "2026-11-22T00:00:00Z" if archived else None,
            "persistence": {"sessionId": session, "nativeHandle": session}, "runtimeInfo": {"sessionId": session}}))


@pytest.fixture
def w(tmp_path, monkeypatch):
    # Nothing here may reach the real home, and no tool may be found through PATH.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: (_ for _ in ()).throw(AssertionError("real home read"))))
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    return World(tmp_path)


# ------------------------------------------------------------------ detection

def test_stalled_transcript_is_found(w):
    report = w.stub()
    t = w.transcript(report, idle_min=30)
    res = ss.scan(w.cfg())
    assert [s.agent_id for s in res.stalled] == [AGENT]
    s = res.stalled[0]
    assert (s.report, s.transcript, s.parent_session, s.session_id) == (report, str(t), SESSION, SESSION)
    assert s.idle_min == pytest.approx(30)
    assert s.last_record == "user" and s.link == "path"
    assert s.parent_paseo_agent_id is None
    assert s.suggested_action == f"SendMessage to {AGENT} from session {SESSION} to resume"
    assert res.unlinked == [] and res.checked == 1


def test_fresh_transcript_is_not_stalled(w):
    report = w.stub()
    w.transcript(report, idle_min=3)
    assert ss.scan(w.cfg()).stalled == []


def test_stale_min_is_the_threshold(w):
    report = w.stub()
    w.transcript(report, idle_min=12)
    assert len(ss.scan(w.cfg(stale_min=10)).stalled) == 1
    assert ss.scan(w.cfg(stale_min=15)).stalled == []


def test_done_marker_is_not_a_stub(w):
    report = w.stub(done=True)
    w.transcript(report, idle_min=300)
    res = ss.scan(w.cfg())
    assert res.stalled == [] and res.checked == 0


def test_a_report_that_is_not_status_working_is_not_a_stub(w):
    report = w.stub(first="BLOCKED: need a decision")
    w.transcript(report, idle_min=300)
    assert ss.scan(w.cfg()).checked == 0


def test_final_message_transcript_is_finished_not_stalled(w):
    report = w.stub()
    w.transcript(report, idle_min=500, tail="final")      # attachment and api-request records follow the final message
    assert ss.scan(w.cfg()).stalled == []


def test_unlinked_stub_is_reported_never_guessed(w):
    lonely = w.stub("lonely-report.md")
    other = w.stub("other-report.md")
    w.transcript(other, idle_min=60)                       # a transcript, but it writes `other`, not `lonely`
    res = ss.scan(w.cfg())
    assert res.unlinked == [lonely]
    assert [s.report for s in res.stalled] == [other]


def test_a_transcript_naming_two_reports_without_a_label_links_to_neither(w):
    a, b = w.stub("a-report.md"), w.stub("b-report.md")
    w.transcript(None, idle_min=60, prompt=f"Compare {a} with {b} and write nothing else.")
    res = ss.scan(w.cfg())
    assert res.stalled == [] and sorted(res.unlinked) == sorted([a, b])


def test_stub_older_than_max_age_is_skipped(w):
    report = w.stub(age_min=49 * 60)
    w.transcript(report, idle_min=48 * 60)
    res = ss.scan(w.cfg(max_age_h=48))
    assert res.stalled == [] and res.too_old == 1 and res.checked == 0
    assert len(ss.scan(w.cfg(max_age_h=72)).stalled) == 1


def test_pending_tool_call_gets_a_grace_period(w):
    report = w.stub()
    w.transcript(report, idle_min=20, tail="tool_use")     # a 25-minute test run is not a stall
    assert ss.scan(w.cfg()).stalled == []
    w.transcript(report, idle_min=40, tail="tool_use")
    s = ss.scan(w.cfg()).stalled
    assert len(s) == 1 and s[0].last_record == "tool_pending"


def test_pending_tool_call_uses_its_own_timeout(w):
    report = w.stub()
    w.transcript(report, idle_min=50, tail="tool_use", tool_timeout_ms=3_600_000)      # 60 min + 5 min margin
    assert ss.scan(w.cfg()).stalled == []
    w.transcript(report, idle_min=70, tail="tool_use", tool_timeout_ms=3_600_000)
    assert len(ss.scan(w.cfg()).stalled) == 1


def test_several_transcripts_stalled_only_when_all_are(w):
    report = w.stub()
    w.transcript(report, idle_min=90, agent="aold")
    w.transcript(report, idle_min=2, agent="anew")          # a resumed or relaunched agent is alive
    assert ss.scan(w.cfg()).stalled == []
    w.transcript(report, idle_min=45, agent="anew")
    res = ss.scan(w.cfg())
    assert [s.agent_id for s in res.stalled] == ["anew"]      # the most recently written one is named


def test_session_and_description_link_when_the_prompt_names_no_report(w):
    report = w.stub("adversary-review-pr-9-report.md")
    w.transcript(None, idle_min=60, description="Adversary review: PR 9", prompt="Review PR 9 and be brief.")
    s = ss.scan(w.cfg()).stalled
    assert len(s) == 1 and s[0].link == "session+description"


def test_description_link_needs_the_same_session(w):
    w.stub("adversary-review-pr-9-report.md")
    w.transcript(None, idle_min=60, session="33333333-aaaa-4bbb-8ccc-444444444444", description="Adversary review: PR 9",
                 prompt="Review PR 9.")
    res = ss.scan(w.cfg())
    assert res.stalled == [] and len(res.unlinked) == 1


def test_description_link_is_refused_when_the_prompt_names_another_report(w):
    w.stub("adversary-review-pr-9-report.md")
    w.transcript(None, idle_min=60, description="Adversary review: PR 9", prompt="Write the full deliverable to `/x/else-report.md`.")
    assert ss.scan(w.cfg()).stalled == []


def test_slug_matches_the_footer_hook(w, tmp_path):
    """The hook derives `<slug(description)>-report.md` under the session directory; the detector's slug must agree."""
    desc = "Adversary review: PR 12 (r3) -- the diff"
    env = {**os.environ, "AGENT_FOOTER_REPORT_DIR": str(tmp_path / "hook-reports"), "AGENT_FOOTER_AGENT_DIRS": str(tmp_path / "no-agents"),
           "PATH": "/usr/bin:/bin"}
    proc = subprocess.run([sys.executable, str(ROOT / "claude/hooks/agent_footer_gate.py")], capture_output=True, text=True, env=env, timeout=60,
                          input=json.dumps({"tool_name": "Agent", "session_id": SESSION, "cwd": str(tmp_path),
                                            "tool_input": {"description": desc, "prompt": "Review it.", "subagent_type": "general-purpose"}}))
    assert proc.returncode == 0, proc.stderr
    hooked = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    expected = str(tmp_path / "hook-reports" / SESSION / (ss.slug(desc) + "-report.md"))
    assert f"Its report is {expected} " in hooked


def test_resume_from_the_hook_prompt_links_by_path(w):
    """A prompt carrying the hook's filled footer (docs/dispatch-footer.md) links by the delivery line."""
    report = w.stub("adversary-review-report.md")
    footer = (ROOT / "docs/dispatch-footer.md").read_text().replace("{report}", report).replace("{done}", report + ".done") \
        .replace("{inbox}", report + ".inbox.md").replace("{replies}", report + ".replies.md").replace("{lead}", "main")
    w.transcript(None, idle_min=60, prompt="Do the review.\n\n" + footer)
    s = ss.scan(w.cfg()).stalled
    assert len(s) == 1 and s[0].link == "path"


def test_last_message_reads_a_huge_file_from_its_end(tmp_path):
    p = tmp_path / "big.jsonl"
    blob = json.dumps({"type": "api-request-blob", "x": "y" * 3_000_000})
    with open(p, "w") as f:
        for _ in range(3):
            f.write(blob + "\n")
        f.write(json.dumps({"type": "assistant", "message": {"stop_reason": "end_turn", "content": []}}) + "\n")
        f.write(blob + "\n")
    assert ss.last_message(p).kind == "final"
    p.write_text("not json\n" + json.dumps({"type": "user", "message": {}}) + "\n{broken")
    assert ss.last_message(p).kind == "user"
    p.write_text("")
    assert ss.last_message(p) is None


# ------------------------------------------------------------------ parent mapping

def test_live_paseo_parent_changes_the_suggested_action(w):
    report = w.stub()
    w.transcript(report, idle_min=30)
    w.paseo_agent()
    s = ss.scan(w.cfg()).stalled[0]
    assert (s.parent_paseo_agent_id, s.parent_live) == (PARENT_PASEO, True)
    assert s.suggested_action.startswith(f"paseo send --json --no-wait {PARENT_PASEO} ")
    assert AGENT in s.suggested_action and "SendMessage" in s.suggested_action


def test_archived_paseo_parent_is_not_messaged_in_the_action(w):
    report = w.stub()
    w.transcript(report, idle_min=30)
    w.paseo_agent(archived=True)
    s = ss.scan(w.cfg()).stalled[0]
    assert (s.parent_paseo_agent_id, s.parent_live) == (PARENT_PASEO, False)
    assert s.suggested_action.startswith("SendMessage to ")


def test_a_live_paseo_agent_beats_an_archived_one_for_the_same_session(w):
    w.paseo_agent(agent_id="00000000-aaaa-4bbb-8ccc-000000000000", archived=True)
    w.paseo_agent(agent_id=PARENT_PASEO)
    assert ss.paseo_parent(w.cfg(), SESSION) == (PARENT_PASEO, True)


# ------------------------------------------------------------------ notify

def stalled_world(w, with_paseo=True):
    report = w.stub()
    w.transcript(report, idle_min=30)
    if with_paseo:
        w.paseo_agent()
    return report


def run_notify(w, now=NOW, **over):
    cfg = w.cfg(now=now, **over)
    res = ss.scan(cfg)
    return res, ss.notify(cfg, res.stalled)


def test_notify_pings_and_messages_the_idle_live_parent_once(w):
    report = stalled_world(w)
    res, _ = run_notify(w)
    pings = w.calls(w.hermes)
    assert len(pings) == 1 and len(pings[0]) == 1
    assert pings[0][0] == (f"djbclark-ade: stalled sub-agent {AGENT} (report {report}), idle 30 min; parent {PARENT_PASEO}")
    sends = [c for c in w.calls(w.paseo) if c[0] == "send"]
    assert len(sends) == 1
    assert sends[0][:4] == ["send", "--json", "--no-wait", PARENT_PASEO]
    assert AGENT in sends[0][4] and report in sends[0][4] and "resume from where you stopped" in sends[0][4]
    assert ["agent", "inspect", PARENT_PASEO, "--json"] in w.calls(w.paseo)
    seen = json.loads((w.home / ".local/state/djbclark-ade/subagent-stalls/seen.json").read_text())
    assert list(seen["stalls"]) == [f"{AGENT}|{report}"]


def test_notify_dedupes_then_pings_again_after_six_hours(w):
    stalled_world(w)
    run_notify(w)
    run_notify(w, now=NOW + 5.9 * 3600)
    assert len(w.calls(w.hermes)) == 1
    assert len([c for c in w.calls(w.paseo) if c[0] == "send"]) == 1
    run_notify(w, now=NOW + 6.01 * 3600)
    assert len(w.calls(w.hermes)) == 2
    assert len([c for c in w.calls(w.paseo) if c[0] == "send"]) == 2


def test_notify_without_a_paseo_parent_only_pings(w):
    stalled_world(w, with_paseo=False)
    run_notify(w)
    assert len(w.calls(w.hermes)) == 1 and w.calls(w.paseo) == []
    assert "parent " + SESSION in w.calls(w.hermes)[0][0]


def test_notify_never_interrupts_a_busy_parent_and_retries_when_idle(w):
    stalled_world(w)
    w.set_parent_state(archived=False, status="running")
    run_notify(w)
    assert len(w.calls(w.hermes)) == 1
    assert [c for c in w.calls(w.paseo) if c[0] == "send"] == []
    w.set_parent_state(archived=False, status="idle")
    run_notify(w, now=NOW + 120)
    assert len(w.calls(w.hermes)) == 1                                       # the ping is not repeated
    assert len([c for c in w.calls(w.paseo) if c[0] == "send"]) == 1       # the parent is told as soon as it is idle


def test_notify_never_wakes_an_archived_parent(w):
    stalled_world(w)
    w.set_parent_state(archived=True, status="idle")
    run_notify(w)
    assert [c for c in w.calls(w.paseo) if c[0] == "send"] == []


def test_failed_ping_is_not_recorded_and_is_retried(w):
    stalled_world(w, with_paseo=False)
    (w.hermes.parent / "rc").write_text("1")
    _, events = run_notify(w)
    assert any("rc=1" in e for e in events)
    (w.hermes.parent / "rc").write_text("0")
    run_notify(w, now=NOW + 60)
    assert len(w.calls(w.hermes)) == 2
    run_notify(w, now=NOW + 120)
    assert len(w.calls(w.hermes)) == 2


def test_a_resolved_stall_is_forgotten_so_a_recurrence_pings_again(w):
    report = stalled_world(w, with_paseo=False)
    run_notify(w)
    w.transcript(report, idle_min=0.5)                      # resumed: fresh again
    run_notify(w, now=NOW + 60)
    seen = json.loads((w.home / ".local/state/djbclark-ade/subagent-stalls/seen.json").read_text())
    assert seen["stalls"] == {}
    w.transcript(report, idle_min=30)
    run_notify(w, now=NOW + 120)
    assert len(w.calls(w.hermes)) == 2


def test_baseline_records_current_stalls_and_announces_nothing(w):
    stalled_world(w)
    run_notify(w, baseline=True)
    run_notify(w, now=NOW + 7 * 3600)
    assert w.calls(w.hermes) == [] and w.calls(w.paseo) == []


def test_ping_cap_per_run(w):
    for i in range(3):
        r = w.stub(f"job{i}-report.md")
        w.transcript(r, idle_min=30, agent=f"a{i}")
    run_notify(w, max_pings=2)
    assert len(w.calls(w.hermes)) == 2
    run_notify(w, now=NOW + 60, max_pings=2)
    assert len(w.calls(w.hermes)) == 3                       # the third waited for the next run; none repeats


def test_dry_run_sends_nothing_and_writes_no_state(w):
    stalled_world(w)
    _, events = run_notify(w, dry_run=True)
    assert w.calls(w.hermes) == [] and w.calls(w.paseo) == []
    assert any("would hermes-ping" in e for e in events)
    assert not (w.home / ".local/state/djbclark-ade/subagent-stalls").exists()


def test_notify_runs_the_tools_by_absolute_path_with_an_empty_path(w, monkeypatch):
    stalled_world(w)
    monkeypatch.setenv("PATH", "")
    run_notify(w)
    assert len(w.calls(w.hermes)) == 1                       # the fake logged the call: it ran from its absolute path, not from PATH


def test_state_write_is_atomic(w, monkeypatch):
    stalled_world(w, with_paseo=False)
    run_notify(w)
    state = w.home / ".local/state/djbclark-ade/subagent-stalls/seen.json"
    before = state.read_text()
    assert [p.name for p in state.parent.iterdir() if p.name.endswith(".tmp")] == []

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    w.stub("second-report.md")
    w.transcript(str(w.reports / SESSION / "second-report.md"), idle_min=30, agent="asecond")
    with pytest.raises(OSError):
        run_notify(w, now=NOW + 60)
    assert state.read_text() == before                       # the old file stands whole
    assert [p.name for p in state.parent.iterdir() if p.name.endswith(".tmp")] == []


def test_corrupt_state_starts_empty_with_a_warning(w):
    stalled_world(w, with_paseo=False)
    d = w.home / ".local/state/djbclark-ade/subagent-stalls"
    d.mkdir(parents=True)
    (d / "seen.json").write_text("{not json")
    _, events = run_notify(w)
    assert any("unreadable" in e for e in events) and len(w.calls(w.hermes)) == 1


# ------------------------------------------------------------------ CLI

def cli(w, *args, **kw):
    cmd = [sys.executable, "-I", str(ROOT / "bin/ade-subagent-stalls"), "--home", str(w.home), "--hermes-ping", str(w.hermes),
           "--paseo", str(w.paseo), "--now", str(NOW), *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, env={"PATH": "", "HOME": str(w.home / "unused")})


def test_cli_exit_0_when_nothing_is_stalled(w):
    r = cli(w)
    assert r.returncode == 0, r.stderr
    assert "0 stalled" in r.stdout


def test_cli_exit_1_and_json_shape_when_something_is(w):
    report = stalled_world(w)
    r = cli(w, "--json")
    assert r.returncode == 1, r.stderr
    rows = json.loads(r.stdout)
    assert len(rows) == 1
    assert set(rows[0]) >= {"report", "session_id", "agent_id", "transcript", "idle_min", "parent_session", "parent_paseo_agent_id",
                            "suggested_action"}
    assert rows[0]["report"] == report and rows[0]["parent_paseo_agent_id"] == PARENT_PASEO
    plain = cli(w)
    assert plain.returncode == 1 and f"STALLED sub-agent {AGENT}" in plain.stdout


def test_cli_notify_end_to_end_with_fakes(w):
    stalled_world(w)
    r = cli(w, "--notify")
    assert r.returncode == 1, r.stderr
    assert len(w.calls(w.hermes)) == 1
    again = cli(w, "--notify")
    assert again.returncode == 1 and len(w.calls(w.hermes)) == 1


def test_cli_exit_2_on_errors(w, tmp_path):
    missing = [sys.executable, "-I", str(ROOT / "bin/ade-subagent-stalls"), "--home", str(w.home), "--notify",
               "--hermes-ping", str(tmp_path / "nope" / "hermes-ping")]
    assert subprocess.run(missing, capture_output=True, text=True, timeout=60).returncode == 2
    assert cli(w, "--stale-min", "-1").returncode == 2
    assert cli(w, "--baseline").returncode == 2                 # --baseline needs --notify
    relative = [sys.executable, "-I", str(ROOT / "bin/ade-subagent-stalls"), "--home", str(w.home), "--notify", "--hermes-ping", "hermes-ping"]
    assert subprocess.run(relative, capture_output=True, text=True, timeout=60).returncode == 2


def test_cli_notify_dry_run_leaves_the_tools_alone(w):
    stalled_world(w)
    r = cli(w, "--notify", "--dry-run")
    assert r.returncode == 1 and "would hermes-ping" in r.stderr
    assert w.calls(w.hermes) == [] and w.calls(w.paseo) == []
