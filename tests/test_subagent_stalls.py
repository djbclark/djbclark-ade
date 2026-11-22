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
import time
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
        self.guard = self._tool("paseo-guard", "sys.exit(0)")        # stands in for libexec/agent-bin/paseo: every `send` goes here
        self.set_parent_state(archived=False, status="idle")

    def sends(self) -> list[list[str]]:
        return self.calls(self.guard)

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
        base = {"now": NOW, "hermes_ping": self.hermes, "paseo": self.paseo, "paseo_guard": self.guard,
                "redirect_probe": lambda cfg, parent, warnings: None}      # the real probe has its own tests (handoff section below)
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
        elif tail == "api_error":              # Claude Code's synthetic API-error ending: stop_reason stop_sequence, model <synthetic>
            recs.append({"type": "assistant", "isApiErrorMessage": True, "message": {
                "model": "<synthetic>", "stop_reason": "stop_sequence", "content": [{"type": "text", "text": "You're out of usage credits."}]}})
        elif tail == "synthetic_tool_use":     # an inner tool call of the REPL tool
            recs.append({"type": "assistant", "message": {"model": "<synthetic>", "stop_reason": "stop_sequence",
                                                           "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "bgrun x"}}]}})
        elif tail == "synthetic_text":         # a synthetic text ending that lacks isApiErrorMessage: only `model` marks it
            recs.append({"type": "assistant", "message": {"model": "<synthetic>", "stop_reason": "stop_sequence",
                                                           "content": [{"type": "text", "text": "No response requested."}]}})
        elif tail == "real_stop_sequence":
            recs.append({"type": "assistant", "message": {"model": "claude-sonnet-5-5", "stop_reason": "stop_sequence",
                                                           "content": [{"type": "text", "text": "written: x"}]}})
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
    assert s.suggested_action.startswith(f"paseo send --json --no-wait -- {PARENT_PASEO} ")
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
    sends = w.sends()
    assert len(sends) == 1
    assert sends[0][:5] == ["send", "--json", "--no-wait", "--", PARENT_PASEO]
    assert AGENT in sends[0][5] and report in sends[0][5] and "resume from where you stopped" in sends[0][5]
    assert ["agent", "inspect", "--json", "--", PARENT_PASEO] in w.calls(w.paseo)
    assert [c for c in w.calls(w.paseo) if c[0] == "send"] == []          # the raw paseo never sees a send: it goes through the guard
    seen = json.loads((w.home / ".local/state/djbclark-ade/subagent-stalls/seen.json").read_text())
    assert list(seen["stalls"]) == [f"{AGENT}|{report}"]


def test_notify_dedupes_then_pings_again_after_six_hours(w):
    stalled_world(w)
    run_notify(w)
    run_notify(w, now=NOW + 5.9 * 3600)
    assert len(w.calls(w.hermes)) == 1
    assert len(w.sends()) == 1
    run_notify(w, now=NOW + 6.01 * 3600)
    assert len(w.calls(w.hermes)) == 2
    assert len(w.sends()) == 2


def test_notify_without_a_paseo_parent_only_pings(w):
    stalled_world(w, with_paseo=False)
    run_notify(w)
    assert len(w.calls(w.hermes)) == 1 and w.calls(w.paseo) == [] and w.sends() == []
    assert "parent " + SESSION in w.calls(w.hermes)[0][0]


def test_notify_never_interrupts_a_busy_parent_and_retries_when_idle(w):
    stalled_world(w)
    w.set_parent_state(archived=False, status="running")
    run_notify(w)
    assert len(w.calls(w.hermes)) == 1
    assert w.sends() == []
    w.set_parent_state(archived=False, status="idle")
    run_notify(w, now=NOW + 120)
    assert len(w.calls(w.hermes)) == 1                                       # the ping is not repeated
    assert len(w.sends()) == 1       # the parent is told as soon as it is idle


def test_notify_never_wakes_an_archived_parent(w):
    stalled_world(w)
    w.set_parent_state(archived=True, status="idle")
    run_notify(w)
    assert w.sends() == []


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
    assert w.calls(w.hermes) == [] and w.calls(w.paseo) == [] and w.sends() == []


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
    assert w.calls(w.hermes) == [] and w.calls(w.paseo) == [] and w.sends() == []
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
           "--paseo", str(w.paseo), "--paseo-guard", str(w.guard), "--now", str(NOW), *args]
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
    assert w.calls(w.hermes) == [] and w.calls(w.paseo) == [] and w.sends() == []


# ------------------------------------------------------------------ PR 938 review (adversary r1): findings MED-1, MED-2, LOW-1..6

def test_out_of_credits_ending_is_a_death_not_a_finish(w):
    """MED-1: Claude Code's synthetic API-error record carries stop_reason stop_sequence; it is how a quota-tight agent dies."""
    report = w.stub()
    w.transcript(report, idle_min=30, tail="api_error")
    s = ss.scan(w.cfg()).stalled
    assert len(s) == 1 and s[0].last_record == "api_error"


def test_a_pending_synthetic_repl_tool_call_gets_the_tool_grace(w):
    """MED-1: the REPL tool's inner tool calls are synthetic tool_use records with stop_reason stop_sequence."""
    report = w.stub()
    w.transcript(report, idle_min=20, tail="synthetic_tool_use")
    assert ss.scan(w.cfg()).stalled == []
    w.transcript(report, idle_min=40, tail="synthetic_tool_use")
    s = ss.scan(w.cfg()).stalled
    assert len(s) == 1 and s[0].last_record == "tool_pending"


def test_a_real_stop_sequence_message_is_still_a_finish(w):
    report = w.stub()
    w.transcript(report, idle_min=500, tail="real_stop_sequence")
    assert ss.scan(w.cfg()).stalled == []


def many_stalls(w, n, parents=False):
    for i in range(n):
        session = f"{i:08d}-aaaa-4bbb-8ccc-222222222222" if parents else SESSION
        r = w.stub(f"job{i}-report.md", session=session)
        w.transcript(r, idle_min=30, agent=f"a{i}", session=session)
        if parents:
            w.paseo_agent(session=session, agent_id=f"{i:08d}-9999-4bbb-8ccc-333333333333")


def test_max_pings_caps_the_repeat_pings_too(w):
    """MED-2: six stalls, cap 2: no run, the 6-hour repeat run included, sends more than two pings."""
    many_stalls(w, 6)
    per_run = []
    for when in (0, 60, 120, 7 * 3600, 7 * 3600 + 60, 7 * 3600 + 120):
        before = len(w.calls(w.hermes))
        run_notify(w, now=NOW + when, max_pings=2)
        per_run.append(len(w.calls(w.hermes)) - before)
    assert per_run == [2, 2, 2, 2, 2, 2]          # six first pings, then six repeats, two per run


def test_max_pings_caps_the_parent_sends(w):
    many_stalls(w, 4, parents=True)
    run_notify(w, max_pings=1)
    assert len(w.sends()) == 1
    run_notify(w, now=NOW + 60, max_pings=1)
    assert len(w.sends()) == 2


def test_one_send_per_parent_lists_all_its_stalled_sub_agents(w):
    many_stalls(w, 3)
    w.paseo_agent()
    run_notify(w)
    sends = w.sends()
    assert len(sends) == 1 and all(f"a{i}" in sends[0][5] for i in range(3)) and "3 of your sub-agents" in sends[0][5]


def test_a_stall_is_announced_at_most_max_notices_times(w):
    """LOW-1: the first announcement and one repeat, then silence."""
    stalled_world(w)
    for when in (0, 7 * 3600, 14 * 3600, 21 * 3600):
        run_notify(w, now=NOW + when)
    assert len(w.calls(w.hermes)) == 2 and len(w.sends()) == 2
    run_notify(w, now=NOW + 28 * 3600, max_notices=3)
    assert len(w.calls(w.hermes)) == 3


def test_stall_ack_file_mutes_a_stub(w):
    report = stalled_world(w)
    Path(report + ".stall-ack").write_text("known")
    res = ss.scan(w.cfg())
    assert res.stalled == [] and res.checked == 0


def test_a_finished_reader_of_a_stub_path_does_not_mask_the_dead_writer(w):
    """LOW-2: a footerless agent told to "read X-report.md" links by bare mention; finishing must not hide the writer's death."""
    report = w.stub()
    w.transcript(report, idle_min=60, agent="awriter")
    w.transcript(None, idle_min=1, tail="final", agent="areader", prompt=f"Read {report} and summarise it.")
    s = ss.scan(w.cfg()).stalled
    assert [x.agent_id for x in s] == ["awriter"] and s[0].link == "path"


def test_a_lone_bare_mention_still_links_when_no_transcript_labels_the_path(w):
    report = w.stub()
    w.transcript(None, idle_min=60, prompt=f"Work on the task and keep notes in {report}.")
    s = ss.scan(w.cfg()).stalled
    assert len(s) == 1 and s[0].link == "path-mention"


def test_suggested_action_survives_shell_quoting():
    """LOW-4: pasting the printed action runs exactly the argv, whatever the report path holds."""
    import shlex
    evil = '/x/a"; touch /tmp/pwned; echo `id` $(id)-report.md'
    action = ss.suggested_action(AGENT, evil, SESSION, PARENT_PASEO, True)
    argv = shlex.split(action)
    assert argv[:6] == ["paseo", "send", "--json", "--no-wait", "--", PARENT_PASEO]
    assert argv[6] == ss.resume_text(AGENT, evil) and len(argv) == 7


def test_a_paseo_id_that_looks_like_an_option_is_not_a_parent(w):
    """LOW-5: ids go to `paseo` as arguments, after `--`; one starting with `-` is never taken."""
    w.paseo_agent(agent_id="--json")
    assert ss.paseo_parent(w.cfg(), SESSION) == (None, False)


def test_reverse_lines_matches_a_plain_reverse_read_at_every_chunk_size(tmp_path, monkeypatch):
    """LOW-6: the linear rewrite of the tail reader returns the same lines as reading the whole file."""
    p = tmp_path / "f.jsonl"
    body = b"\n".join([b"short", b"", b"x" * 100, b"   ", b"y" * 1000, b"z"]) + b"\n" + b"w" * 50
    for chunk in (1, 2, 7, 64, 4096):
        monkeypatch.setattr(ss, "CHUNK", chunk)
        for text in (body, body + b"\n", b"one", b"\n\n", b"a\nb"):
            p.write_bytes(text)
            assert list(ss._reverse_lines(p)) == [ln for ln in reversed(text.split(b"\n")) if ln.strip()]


def test_the_send_goes_through_the_real_guard_shim_by_absolute_path(w, monkeypatch):
    """LOW-3: with the checkout's libexec/agent-bin/paseo as the guard, the shim runs, probes the parent and execs the real paseo."""
    stalled_world(w)
    monkeypatch.setenv("HOME", str(w.home))
    monkeypatch.setenv("ADE_SEND_GUARD_LOG", str(w.home / "send-guard.log"))
    run_notify(w, paseo_guard=ROOT / "libexec/agent-bin/paseo")
    sends = [c for c in w.calls(w.paseo) if c[0] == "send"]
    assert len(sends) == 1 and sends[0][:5] == ["send", "--json", "--no-wait", "--", PARENT_PASEO]


# ---------------------------------------------------------------- PR 938 round-2 LOWs (2026-11-22)

SUCCESSOR = "88888888-aaaa-4bbb-8ccc-444444444444"


def handoff_world(w, monkeypatch, status="acknowledged"):
    """A parent whose self-handoff record names SUCCESSOR; the fake paseo reports every agent live, idle, with the asked Id."""
    from datetime import datetime, timezone
    sys.path.insert(0, str(ROOT / "tests"))
    from test_ade_lead_succession import write_link
    state, phome = w.home / "self-session", w.home / "paseo-home"
    write_link(state, phome, PARENT_PASEO, SUCCESSOR, status=status,
               acknowledged_at=datetime.fromtimestamp(time.time(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    monkeypatch.setenv("ADE_SELF_SESSION_STATE", str(state))
    monkeypatch.setenv("PASEO_HOME", str(phome))
    monkeypatch.setenv("ADE_SEND_GUARD_LOG", str(w.home / "send-guard.log"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: w.home))
    (w.paseo.parent / "inspect.json").unlink()
    w.paseo.write_text(w.paseo.read_text().replace(
        "sys.stdout.write(open(os.path.join(here, 'inspect.json')).read())",
        "sys.stdout.write(json.dumps({'Id': argv[2] if argv[2] != '--json' else argv[-1], 'Archived': False, 'Status': 'idle'}))"))


def test_a_handed_off_parent_gets_no_send_and_the_ping_names_the_successor(w, monkeypatch):
    """LOW-1: the shim would redirect to the successor without an idle check; the tool decides first and sends nothing."""
    stalled_world(w)
    handoff_world(w, monkeypatch)
    res, events = run_notify(w, redirect_probe=None)
    assert w.sends() == []
    pings = w.calls(w.hermes)
    assert len(pings) == 1 and f"handed off to {SUCCESSOR}" in pings[0][0]
    assert any(f"handed off to {SUCCESSOR}" in e and "no message sent" in e for e in events)
    run_notify(w, now=NOW + 60, redirect_probe=None)
    assert w.sends() == [] and len(w.calls(w.hermes)) == 1          # decided once, not retried every run


def test_a_refused_parent_gets_no_send(w, monkeypatch):
    stalled_world(w)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: w.home))
    monkeypatch.setenv("ADE_SELF_SESSION_STATE", str(w.home / "self-session"))
    monkeypatch.setenv("PASEO_HOME", str(w.home / "paseo-home"))
    monkeypatch.setenv("ADE_SEND_GUARD_LOG", str(w.home / "send-guard.log"))
    (w.paseo.parent / "inspect.json").write_text(json.dumps({"Id": PARENT_PASEO, "Archived": False, "Status": "idle"}))
    import ade_send_guard as sg
    monkeypatch.setattr(sg, "guard", lambda parent, **kw: sg.Decision(sg.REFUSE, parent, "test"))
    _, events = run_notify(w, redirect_probe=None)
    assert w.sends() == [] and any("refused by the send guard" in e for e in events)


def test_the_send_environment_drops_the_sender_identity_and_the_operator_overrides(w, monkeypatch):
    """LOW-1: an exported override or a launcher id in the calling shell must not apply to an automated send."""
    for name in ss.SENDER_OVERRIDE_ENV:
        monkeypatch.setenv(name, "x")
    monkeypatch.setenv("KEEP_ME", "1")
    argv, env = ss._send_argv_env(w.cfg(), PARENT_PASEO, "text")
    assert env is not None and env["KEEP_ME"] == "1" and not any(n in env for n in ss.SENDER_OVERRIDE_ENV)
    assert env["PATH"] == ss.SHIM_PATH and argv[-2:] == [PARENT_PASEO, "text"]


def test_a_labelled_mention_by_a_finished_reviewer_does_not_hide_the_dead_writer(w):
    """LOW-2: the reviewer lists `- Report: <writer's report>` as context and has its own footer; it finished, the writer died."""
    report = w.stub()
    w.transcript(report, idle_min=60, agent="awriter")
    own = f"{w.reports}/{SESSION}/review-report.md"
    prompt = (f"Review the diff.\n- Report: {report}\n\n## Delivery contract\n\n"
              f"1. Write the full deliverable to `{own}`. Create it early.\n")
    w.transcript(None, idle_min=1, tail="final", agent="areviewer", prompt=prompt)
    s = ss.scan(w.cfg()).stalled
    assert [x.agent_id for x in s] == ["awriter"]


def test_a_relaunch_with_the_same_footer_path_is_still_covered(w):
    """LOW-2: every footer-linked transcript counts: a finished relaunch hides the dead first run only when it finished the report."""
    report = w.stub()
    w.transcript(report, idle_min=60, agent="afirst")
    w.transcript(report, idle_min=1, tail="final", agent="asecond")
    assert ss.scan(w.cfg()).stalled == []


def test_a_brief_file_names_the_report_the_footer_does_not(w):
    """LOW-3: "Your brief is the file X-brief.md" with another path in the footer: the brief's `Report path:` links the stub."""
    report = w.stub("real-report.md")
    brief = w.reports / SESSION / "task-brief.md"
    brief.write_text(f"Do the review.\nReport path: {report}\n")
    prompt = (f"Your brief is the file {brief}.\n\n## Delivery contract\n\n"
              f"1. Write the full deliverable to `{w.reports}/{SESSION}/footer-report.md`.\n")
    w.transcript(None, idle_min=60, prompt=prompt)
    res = ss.scan(w.cfg())
    assert [x.report for x in res.stalled] == [report] and res.unlinked == []


def test_a_brief_outside_the_reports_dir_is_not_read(w, tmp_path):
    report = w.stub("real-report.md")
    brief = tmp_path / "elsewhere-brief.md"
    brief.write_text(f"Report path: {report}\n")
    w.transcript(None, idle_min=60, prompt=f"Your brief is the file {brief}.\n")
    res = ss.scan(w.cfg())
    assert res.stalled == [] and res.unlinked == [report]


def test_a_synthetic_text_record_without_the_api_error_flag_is_an_api_error(w):
    """LOW-4: the `model == "<synthetic>"` clause stands alone (a mutant that kept only `isApiErrorMessage` survived)."""
    p = w.transcript(w.stub(), idle_min=60, tail="synthetic_text")
    assert ss.last_message(p).kind == "api_error"


def test_inspects_per_run_are_capped(w):
    """LOW-5: a parent that is not idle uses no send slot, so the probes need their own cap."""
    many_stalls(w, 6, parents=True)
    w.set_parent_state(archived=False, status="running")
    run_notify(w, max_inspects=8)          # the five pinged parents each use one guard probe (the injected probe still counts), 3 are left
    assert len(w.calls(w.paseo)) == 3


def test_no_more_inspects_after_the_first_timeout(w, tmp_path):
    """LOW-5: a hung or missing paseo is tried once per run, not once per parent."""
    many_stalls(w, 5, parents=True)
    calls = []
    real = ss._run
    def fake_run(argv, warnings):
        if "inspect" in argv:
            calls.append(argv)
            warnings.append("paseo failed: timed out")
            return None
        return real(argv, warnings)
    import unittest.mock as mock
    with mock.patch.object(ss, "_run", fake_run):
        _, events = run_notify(w)
    assert len(calls) == 1 and any("inspect cap or paseo unreachable" in e for e in events)
