"""Unit tests for bin/herdr-sleeper: pure decision logic plus the sleep/wake state machine
against a fake `herdr` (no Herdr, no Claude needed)."""

from __future__ import annotations

import json
import os
import plistlib
import time
import types
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "herdr-sleeper"
sleeper = types.ModuleType("herdr_sleeper")
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), sleeper.__dict__)

UUID = "20603f77-21a6-4a16-9f2b-77a87efbc665"
REAL_UUID_LIVE = sleeper.uuid_live_elsewhere  # captured before any fixture stubs it


def agent(
    pane: str = "w1:p1",
    uuid: str | None = UUID,
    status: str = "idle",
    focused: bool = False,
    kind: str = "claude",
    name: str | None = "a",
    seq: int = 5,
) -> dict[str, Any]:
    a: dict[str, Any] = {"pane_id": pane, "agent_status": status, "focused": focused, "agent": kind,
                         "state_change_seq": seq, "cwd": "/tmp/proj", "terminal_title_stripped": "Title"}
    if name:
        a["name"] = name
    if uuid:
        a["agent_session"] = {"value": uuid}
    return a


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated state dir + transcript root, with a 30h-old transcript for UUID."""
    d = tmp_path / "state"
    for name in ("STATE_DIR", "JOURNAL", "SNAPSHOT", "EVENTS", "LOG", "LOCK"):
        base = getattr(sleeper, name)
        monkeypatch.setattr(sleeper, name, d / base.name if name != "STATE_DIR" else d)
    root = tmp_path / "projects"
    (root / "proj").mkdir(parents=True)
    monkeypatch.setattr(sleeper, "TRANSCRIPTS", root)
    return tmp_path


def transcript(tmp_path: Path, uuid: str, age_hours: float, proj: str = "proj") -> Path:
    p = tmp_path / "projects" / proj / f"{uuid}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}\n")
    stamp = time.time() - age_hours * 3600
    os.utime(p, (stamp, stamp))
    return p


EMPTY_SCREEN = "⏺ pong\n────────\n❯ \n────────\n  ◤ graft · 40 nodes\n  ⏵⏵ bypass permissions on\n"


class FakeHerdr:
    """Scripted `herdr` CLI: agents list, per-pane info, screen text, and a call log."""

    def __init__(self, agents: list[dict[str, Any]], screen: str = EMPTY_SCREEN, argv: list[str] | None = None) -> None:
        self.agents = agents
        self.screen: str | None = screen
        self.argv = ["--dangerously-skip-permissions"] if argv is None else argv
        self.calls: list[tuple[str, ...]] = []
        self.exit_leaves_agent = True     # /exit removes the agent from its pane
        self.start_uuid: str | None = None  # what agent start reports; None → the requested --resume uuid

    def __call__(self, *args: str, check: bool = True, timeout: float = 0) -> dict[str, Any]:
        self.calls.append(args)
        by_pane = {a["pane_id"]: a for a in self.agents}
        if args[:2] == ("agent", "list"):
            return {"agents": self.agents}
        if args[:2] == ("pane", "get"):
            a = by_pane.get(args[2])
            if a is None:
                if check:
                    raise sleeper.SleeperError("no such pane")
                return {}
            pane = {"pane_id": args[2], "label": a.get("label")}
            if a.get("agent"):
                pane["agent"] = a["agent"]
                pane["agent_session"] = a.get("agent_session")
            return {"pane": pane}
        if args[:2] == ("pane", "process-info"):
            return {"process_info": {"foreground_processes": [{"argv0": "claude", "name": "claude",
                                                                "argv": ["claude", *self.argv], "pid": 1}]}}
        if args[:2] == ("agent", "prompt") and args[3] == "/exit":
            if self.exit_leaves_agent:
                for a in self.agents:
                    if a.get("name") == args[2] or a["pane_id"] == args[2]:
                        a.pop("agent", None)
                        a.pop("agent_session", None)
            return {}
        if args[:2] == ("agent", "start"):
            pane = args[args.index("--pane") + 1]
            uuid = self.start_uuid or args[args.index("--resume") + 1]
            a = by_pane[pane]
            a.update(agent="claude", agent_session={"value": uuid})
            return {"agent": {"agent_session": {"value": uuid}}}
        if args[:2] in (("pane", "run"), ("pane", "rename")):
            if args[:2] == ("pane", "rename"):
                by_pane[args[2]]["label"] = args[3] if len(args) > 3 else None
            return {}
        raise AssertionError(f"unexpected herdr call {args}")


@pytest.fixture
def fake(state: Path, monkeypatch: pytest.MonkeyPatch) -> FakeHerdr:
    f = FakeHerdr([agent()])
    monkeypatch.setattr(sleeper, "herdr", f)
    monkeypatch.setattr(sleeper, "herdr_screen", lambda pane: f.screen)
    monkeypatch.setattr(sleeper, "uuid_live_elsewhere", lambda uuid, except_pane=None: None)
    monkeypatch.setattr(sleeper.time, "sleep", lambda s: None)
    monkeypatch.setattr(sleeper, "EXIT_WAIT_SECONDS", 2)
    transcript(state, UUID, 30)
    return f


def journal() -> dict[str, Any]:
    return sleeper.read_json(sleeper.JOURNAL)


def events() -> list[str]:
    p = sleeper.EVENTS
    return [json.loads(l)["event"] for l in p.read_text().splitlines()] if p.exists() else []


# ------------------------------------------------------------- pure helpers

def test_replayable_argv_strips_session_selectors() -> None:
    ok = sleeper.replayable_argv
    assert ok(["--dangerously-skip-permissions", "--resume", "abc"]) == (["--dangerously-skip-permissions"], None)
    assert ok(["-r", "abc", "--model", "opus"]) == (["--model", "opus"], None)
    assert ok(["--resume=abc", "-c", "--continue"]) == ([], None)
    assert ok(["--resume", "--model", "opus"]) == (["--model", "opus"], None)  # bare --resume opens a picker
    assert ok([]) == ([], None)
    assert ok(["--add-dir", "/x", "--verbose"]) == (["--add-dir", "/x", "--verbose"], None)
    assert ok(["--unknown-flag", "value"]) == (["--unknown-flag", "value"], None)


@pytest.mark.parametrize(
    "args, needle",
    [
        (["--fork-session"], "--fork-session"),
        (["-p", "hi"], "-p"),
        (["--session-id", "x"], "--session-id"),
        (["--verbose", "publish the release"], "positional"),
        (["--dangerously-skip-permissions", "--", "x"], "`--`"),
    ],
)
def test_replayable_argv_refuses_dangerous(args: list[str], needle: str) -> None:
    argv, why = sleeper.replayable_argv(args)
    assert argv is None and why and needle in why


def test_parse_duration() -> None:
    assert sleeper.parse_duration("12h") == 12
    assert sleeper.parse_duration("90m") == 1.5
    assert sleeper.parse_duration("1d") == 24
    assert sleeper.parse_duration("3600s") == 1
    assert sleeper.parse_duration("2") == 2
    with pytest.raises(sleeper.ConfigError):
        sleeper.parse_duration("soon")


CLAUDE_SCREEN = """
❯ earlier question
⏺ pong
✻ Worked for 1s · done 5:23 PM
────────
❯ {composer}
────────
  ◤ graft · 40 nodes / 63 edges · ✓ synced
  ⏵⏵ bypass permissions on (shift+tab to cycle) · ← for agents
"""


def test_composer_state_fails_closed() -> None:
    cs = sleeper.composer_state
    assert cs(CLAUDE_SCREEN.format(composer=""))[0] == "empty"
    assert cs(CLAUDE_SCREEN.format(composer="half-typed thought")) == ("draft", "half-typed thought")
    multiline = CLAUDE_SCREEN.format(composer="") .replace("────────\n  ◤", "  second line of a draft\n────────\n  ◤", 1)
    assert cs(multiline)[0] == "draft"
    assert cs("❯ \n  ?\n────────\n")[0] == "draft"          # one-character draft is still a draft
    assert cs("❯ \n")[0] == "unknown"                    # bare glyph, nothing rendered below it
    assert cs(None)[0] == "unknown"                       # unreadable screen
    assert cs("djbclark@mac:~$ \n")[0] == "unknown"       # bare shell: no composer to vouch for
    assert cs("⏺ done\n✻ Worked\n")[0] == "unknown"       # transcript visible, composer scrolled off


def test_manual_command_is_shell_safe() -> None:
    cmd = sleeper.manual_command({"cwd": "/tmp/my dir", "argv": ["--model", "it's"], "uuid": "u"})
    assert cmd == "cd '/tmp/my dir' && claude --model 'it'\"'\"'s' --resume u"


def test_wake_name_falls_back_to_pane() -> None:
    assert sleeper.wake_name({"name": None, "pane_id": "w26:p2"}) == "wake-w26-p2"
    assert sleeper.wake_name({"name": "lichess", "pane_id": "w24:p1"}) == "lichess"


# ---------------------------------------------------------------- config

def test_load_config_precedence(state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = state / "config.toml"
    monkeypatch.setattr(sleeper, "CONFIG_FILE", cfg)
    for var in ("HERDR_SLEEPER_IDLE_HOURS", "HERDR_SLEEPER_IDLE", "HERDR_SLEEPER_EXCLUDE"):
        monkeypatch.delenv(var, raising=False)
    values, source = sleeper.load_config()
    assert values == {"idle_hours": 12.0, "exclude": [], "interval_minutes": 30}
    assert set(source.values()) == {"default"}

    cfg.write_text('idle = "90m"\nexclude = "orc"\n')
    values, source = sleeper.load_config()
    assert values["idle_hours"] == 1.5 and values["exclude"] == ["orc"]   # a string is one name, not letters
    assert source["idle_hours"] == str(cfg) and source["interval_minutes"] == "default"

    monkeypatch.setenv("HERDR_SLEEPER_IDLE", "2d")
    monkeypatch.setenv("HERDR_SLEEPER_EXCLUDE", "a b")
    values, source = sleeper.load_config()
    assert values["idle_hours"] == 48 and values["exclude"] == ["a", "b"]
    assert source["idle_hours"] == "$HERDR_SLEEPER_IDLE"


@pytest.mark.parametrize(
    "text",
    ["idle_hours = = 3\n", "idle_hours = nan\n", "idle_hours = -1\n", "exclude = [1, 2]\n", "interval_minutes = 0\n",
     "bogus = 1\n"],
)
def test_load_config_rejects_bad_values(state: Path, monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    cfg = state / "config.toml"
    cfg.write_text(text)
    monkeypatch.setattr(sleeper, "CONFIG_FILE", cfg)
    with pytest.raises(sleeper.ConfigError):
        sleeper.load_config()


def test_scan_refuses_with_broken_config(state: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = state / "config.toml"
    cfg.write_text("idle_hours = = 3\n")
    monkeypatch.setattr(sleeper, "CONFIG_FILE", cfg)
    assert sleeper.main(["scan"]) == 2
    assert "broken config" in capsys.readouterr().out


# ------------------------------------------------------------- assessment

def test_assess_sleeps_old_idle_agent(state: Path) -> None:
    transcript(state, UUID, 13)
    ok, _reason, idle = sleeper.assess(agent(), [agent()], 12, {})
    assert ok and idle is not None and idle > 12


def test_assess_uses_newest_transcript_copy(state: Path) -> None:
    transcript(state, UUID, 40, proj="old")
    transcript(state, UUID, 0.1, proj="new")
    ok, reason, _ = sleeper.assess(agent(), [agent()], 12, {})
    assert not ok and "< 12h" in reason


@pytest.mark.parametrize(
    "kw, needle",
    [
        ({"status": "working"}, "status working"),
        ({"status": "blocked"}, "status blocked"),
        ({"focused": True}, "focused"),
        ({"uuid": None}, "no session uuid"),
        ({"kind": "codex"}, "not supported"),
    ],
)
def test_assess_rejections(state: Path, kw: dict[str, Any], needle: str) -> None:
    transcript(state, UUID, 30)
    a = agent(**kw)
    ok, reason, _ = sleeper.assess(a, [a], 12, {})
    assert not ok and needle in reason


def test_assess_rejects_shared_session_excluded_journaled_missing(state: Path) -> None:
    transcript(state, UUID, 30)
    a, b = agent(pane="w1:p1"), agent(pane="w2:p1", status="working")
    assert "w2:p1" in sleeper.assess(a, [a, b], 12, {})[1]
    assert sleeper.assess(a, [a], 12, {}, {"a"})[1] == "excluded"
    assert sleeper.assess(a, [a], 12, {}, {"w1:p1"})[1] == "excluded"
    assert "journal" in sleeper.assess(a, [a], 12, {"w1:p1": {"phase": "asleep"}})[1]
    assert "no transcript" in sleeper.assess(agent(uuid="other"), [agent(uuid="other")], 12, {})[1]


# ------------------------------------------------------ sleep state machine

def test_sleep_happy_path(fake: FakeHerdr) -> None:
    slept, outcome = sleeper.sleep_agent(agent(), 12, set(), dry_run=False)
    assert slept and outcome == "slept"
    j = journal()["w1:p1"]
    assert j["uuid"] == UUID and j["argv"] == ["--dangerously-skip-permissions"] and j["phase"] == "asleep"
    assert ("agent", "prompt", "a", "/exit") in fake.calls
    assert any(c[:2] == ("pane", "rename") and c[3].startswith("💤") for c in fake.calls)
    assert events() == ["slept"]


def test_sleep_refuses_on_draft_and_never_sends_exit(fake: FakeHerdr) -> None:
    fake.screen = CLAUDE_SCREEN.format(composer="unsent")
    slept, outcome = sleeper.sleep_agent(agent(), 12, set(), dry_run=False)
    assert not slept and "draft" in outcome
    assert not any(c[:2] == ("agent", "prompt") for c in fake.calls)
    assert journal() == {} and events() == ["refused"]


def test_sleep_refuses_on_unreadable_screen(fake: FakeHerdr) -> None:
    fake.screen = None
    slept, outcome = sleeper.sleep_agent(agent(), 12, set(), dry_run=False)
    assert not slept and "unknown" in outcome and journal() == {}


def test_sleep_refuses_when_state_moved_since_scan(fake: FakeHerdr) -> None:
    fake.agents[0]["state_change_seq"] = 6  # scan saw 5
    slept, outcome = sleeper.sleep_agent(agent(seq=5), 12, set(), dry_run=False)
    assert not slept and "state changed" in outcome
    assert not any(c[:2] == ("agent", "prompt") for c in fake.calls)


def test_sleep_refuses_unreplayable_argv(fake: FakeHerdr) -> None:
    fake.argv = ["--fork-session"]
    slept, outcome = sleeper.sleep_agent(agent(), 12, set(), dry_run=False)
    assert not slept and "--fork-session" in outcome and journal() == {}


def test_dry_run_runs_every_check_but_acts_on_nothing(fake: FakeHerdr) -> None:
    slept, outcome = sleeper.sleep_agent(agent(), 12, set(), dry_run=True)
    assert not slept and outcome.startswith("would sleep")
    assert not any(c[:2] == ("agent", "prompt") for c in fake.calls) and journal() == {}
    fake.screen = CLAUDE_SCREEN.format(composer="draft")
    assert "draft" in sleeper.sleep_agent(agent(), 12, set(), dry_run=True)[1]


def test_exit_timeout_keeps_handle_as_exit_requested(fake: FakeHerdr) -> None:
    fake.exit_leaves_agent = False
    slept, outcome = sleeper.sleep_agent(agent(), 12, set(), dry_run=False)
    assert not slept and "uncertain" in outcome
    assert journal()["w1:p1"]["phase"] == "exit-requested"
    assert events() == ["exit-uncertain"]


def test_reconcile_settles_exit_requested(fake: FakeHerdr) -> None:
    fake.exit_leaves_agent = False
    sleeper.sleep_agent(agent(), 12, set(), dry_run=False)
    # case 1: the agent is still there next scan → the entry was a no-op, drop it
    sleeper.reconcile(fake.agents)
    assert journal() == {}
    # case 2: it did leave after the timeout → becomes asleep
    fake.exit_leaves_agent = False
    fake.agents = [agent()]
    sleeper.sleep_agent(agent(), 12, set(), dry_run=False)
    fake.agents[0].pop("agent"); fake.agents[0].pop("agent_session")
    sleeper.reconcile(fake.agents)
    assert journal()["w1:p1"]["phase"] == "asleep"


# ------------------------------------------------------- wake state machine

def slept_entry(fake: FakeHerdr) -> dict[str, Any]:
    sleeper.sleep_agent(agent(), 12, set(), dry_run=False)
    return journal()["w1:p1"]


def test_wake_happy_path_restores_label(fake: FakeHerdr) -> None:
    fake.agents[0]["label"] = "mylabel"
    entry = slept_entry(fake)
    assert fake.agents[0]["label"] == "💤 mylabel"
    assert sleeper.wake_entry(entry)
    start = next(c for c in fake.calls if c[:2] == ("agent", "start"))
    assert start[-2:] == ("--resume", UUID) and "--dangerously-skip-permissions" in start
    assert fake.agents[0]["label"] == "mylabel" and journal() == {} and events()[-1] == "woke"


def test_wake_clears_label_that_did_not_exist_before_sleep(fake: FakeHerdr) -> None:
    entry = slept_entry(fake)
    assert fake.agents[0]["label"] == "💤 Title" and entry["label"] is None
    assert sleeper.wake_entry(entry)
    assert fake.agents[0]["label"] is None


def test_wake_filters_snapshot_argv(fake: FakeHerdr) -> None:
    entry = slept_entry(fake)
    entry["argv"] = ["--fork-session"]  # a raw snapshot argv that sleep never vetted
    assert not sleeper.wake_entry(entry) and "w1:p1" in journal()
    assert not any(c[:2] == ("agent", "start") for c in fake.calls)


def test_read_json_rejects_non_object_root(state: Path) -> None:
    sleeper.STATE_DIR.mkdir(parents=True)
    sleeper.JOURNAL.write_text("[]\n")
    with pytest.raises(sleeper.SleeperError):
        sleeper.read_json(sleeper.JOURNAL)


def test_cli_idle_hours_validated(state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sleeper, "CONFIG_FILE", state / "absent.toml")
    for bad in ("-1", "nan", "inf", "soon"):
        with pytest.raises(SystemExit):
            sleeper.main(["scan", "--idle-hours", bad])
    with pytest.raises(SystemExit):
        sleeper.main(["scan", "--idle", "soon"])


def test_reconcile_needs_a_real_process_before_dropping(fake: FakeHerdr, monkeypatch: pytest.MonkeyPatch) -> None:
    fake.exit_leaves_agent = False
    sleeper.sleep_agent(agent(), 12, set(), dry_run=False)
    monkeypatch.setattr(sleeper, "claude_argv", lambda pane: None)  # agent list says present, process-info says no
    sleeper.reconcile(fake.agents)
    assert journal()["w1:p1"]["phase"] == "exit-requested"


def test_wake_refuses_when_pane_gone_and_keeps_entry(fake: FakeHerdr) -> None:
    entry = slept_entry(fake)
    fake.agents = []
    assert not sleeper.wake_entry(entry) and "w1:p1" in journal()


def test_wake_refuses_when_argv_unknown(fake: FakeHerdr) -> None:
    entry = slept_entry(fake)
    entry["argv"] = None
    assert not sleeper.wake_entry(entry)
    assert not any(c[:2] == ("agent", "start") for c in fake.calls)


def test_wake_refuses_when_session_live_elsewhere(fake: FakeHerdr, monkeypatch: pytest.MonkeyPatch) -> None:
    entry = slept_entry(fake)
    monkeypatch.setattr(sleeper, "uuid_live_elsewhere", lambda uuid, except_pane=None: "pid 42")
    assert not sleeper.wake_entry(entry) and "w1:p1" in journal()


def test_wake_refuses_when_liveness_unknown(fake: FakeHerdr, monkeypatch: pytest.MonkeyPatch) -> None:
    entry = slept_entry(fake)

    def boom(uuid: str, except_pane: str | None = None) -> None:
        raise sleeper.SleeperError("ps failed")

    monkeypatch.setattr(sleeper, "uuid_live_elsewhere", boom)
    with pytest.raises(sleeper.SleeperError):
        sleeper.wake_entry(entry)
    assert "w1:p1" in journal()


def test_wake_clears_entry_when_same_session_already_running(fake: FakeHerdr) -> None:
    entry = slept_entry(fake)
    fake.agents[0].update(agent="claude", agent_session={"value": UUID})  # came back by other means
    assert sleeper.wake_entry(entry) and journal() == {}


def test_wake_keeps_entry_on_session_mismatch(fake: FakeHerdr) -> None:
    entry = slept_entry(fake)
    fake.start_uuid = "fresh-uuid"
    assert not sleeper.wake_entry(entry)
    assert journal()["w1:p1"]["wake_got"] == "fresh-uuid" and events()[-1] == "wake-mismatch"


def test_wake_from_snapshot_persists_before_trying(fake: FakeHerdr, capsys: pytest.CaptureFixture[str]) -> None:
    sleeper.merge_snapshot(fake.agents)
    fake.agents[0].pop("agent"); fake.agents[0].pop("agent_session")   # asleep, but no journal (crash)
    assert sleeper.cmd_wake(types.SimpleNamespace(target="a", all=False)) == 0
    assert (fake.agents[0].get("agent_session") or {}).get("value") == UUID
    assert "recovering from panes.json" in capsys.readouterr().out


def test_snapshot_keeps_sleeping_panes(fake: FakeHerdr) -> None:
    sleeper.merge_snapshot(fake.agents)
    fake.agents[0].pop("agent"); fake.agents[0].pop("agent_session")   # now asleep: not in agent list as claude
    sleeper.merge_snapshot([])
    assert "w1:p1" in sleeper.read_json(sleeper.SNAPSHOT)
    fake.agents[0].update(agent="claude", agent_session={"value": "different"})
    sleeper.merge_snapshot(fake.agents)
    assert sleeper.read_json(sleeper.SNAPSHOT)["w1:p1"]["uuid"] == "different"


# ------------------------------------------------------------- liveness

def test_uuid_live_elsewhere_parses_ps(fake: FakeHerdr, monkeypatch: pytest.MonkeyPatch) -> None:
    lines = {
        f"  11 claude --dangerously-skip-permissions --resume {UUID}": "pid 11",
        f"  12 node /opt/homebrew/bin/claude --resume={UUID}": "pid 12",
        f"  13 /bin/bash -c 'echo claude {UUID}'": None,       # a shell mentioning both is not a session
        f"  14 /usr/local/bin/claude --resume other": None,
    }
    for line, expect in lines.items():
        monkeypatch.setattr(sleeper.subprocess, "run",
                            lambda *a, **k: types.SimpleNamespace(stdout=line + "\n", returncode=0))
        fake.agents = []
        assert REAL_UUID_LIVE(UUID) == expect, line


# --------------------------------------------------------------- install

def test_launchd_plist_is_valid_and_escaped() -> None:
    data = sleeper.launchd_plist(Path("/we&ird <path>/herdr-sleeper"), {"interval_minutes": 15}, {"HERDR_SLEEPER_STATE": "/s"})
    job = plistlib.loads(data)
    assert job["ProgramArguments"][1:] == ["/we&ird <path>/herdr-sleeper", "scan"]
    assert job["StartInterval"] == 900 and job["EnvironmentVariables"]["HERDR_SLEEPER_STATE"] == "/s"


def test_cron_line_only_for_exact_intervals() -> None:
    assert sleeper.cron_line(Path("/x y/s"), 30).startswith("*/30 * * * * ")
    assert "env HERDR_SLEEPER_STATE=/s " in sleeper.cron_line(Path("/s"), 30, {"HERDR_SLEEPER_STATE": "/s"})
    assert "'/x y/s'" in sleeper.cron_line(Path("/x y/s"), 30)
    assert sleeper.cron_line(Path("/s"), 120).startswith("0 */2 * * * ")
    assert sleeper.cron_line(Path("/s"), 45) is None
